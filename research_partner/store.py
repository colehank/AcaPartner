"""Durable research objects. This store never interprets model text as authority."""
from __future__ import annotations
import contextlib
import copy
import hashlib
import json
import math
import os
import sqlite3
import stat
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix="OBJ"):
    return prefix + "-" + uuid.uuid4().hex[:16]


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else encoded(value).encode()).hexdigest()


class Problem(Exception):
    def __init__(self, message, code="invalid", status=400, details=None):
        super().__init__(message)
        self.code, self.status, self.details = code, status, details or {}


def require(condition, message, code="invalid", status=400, details=None):
    if not condition:
        raise Problem(message, code, status, details)


_ABSENT = object()


def merge3(base, current, proposed, path="content"):
    """Merge disjoint edits, never choose an author silently on disagreement."""
    if current == proposed or base == current:
        return copy.deepcopy(proposed)
    if base == proposed:
        return copy.deepcopy(current)
    if all(isinstance(x, dict) for x in [base, current, proposed]):
        result = {}
        for key in base.keys() | current.keys() | proposed.keys():
            b, c, p = [x.get(key, _ABSENT) for x in [base, current, proposed]]
            if c == p or b == c:
                value = p
            elif b == p:
                value = c
            elif _ABSENT not in (b, c, p):
                value = merge3(b, c, p, path + "." + key)
            else:
                raise Problem("同期编辑冲突；你的候选已保留", "conflict", 409, {"path": path + "." + key})
            if value is not _ABSENT:
                result[key] = copy.deepcopy(value)
        return result
    if all(isinstance(x, list) and all(isinstance(i, dict) and "id" in i for i in x) for x in [base, current, proposed]):
        ids = [[i["id"] for i in x] for x in [base, current, proposed]]
        require(all(len(v) == len(set(v)) for v in ids), "对象标识重复")
        # Concurrent ordering changes require a decision, not arbitrary ordering.
        common = set(ids[0]) & set(ids[1]) & set(ids[2])
        orders = [[i for i in order if i in common] for order in ids]
        if orders[1] != orders[0] and orders[2] != orders[0] and orders[1] != orders[2]:
            raise Problem("同期排序冲突", "conflict", 409, {"path": path})
        merged = merge3(*[{i["id"]: i for i in x} for x in [base, current, proposed]], path)
        order = ids[2] if orders[2] != orders[0] else ids[1]
        order = order + [i for i in ids[2] + ids[1] if i not in order]
        return [merged[i] for i in dict.fromkeys(order) if i in merged]
    raise Problem("同期编辑冲突；需要选择或合并", "conflict", 409, {"path": path})


class _StoreConnection(sqlite3.Connection):
    """Per-connection asset ownership, valid only while a managed write lock is held."""


class Store:
    def __init__(self, workspace):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.blobs = self.workspace / "assets"
        self.blobs.mkdir(exist_ok=True)
        self.db = self.workspace / "research.sqlite3"
        self._read_scope = threading.local()
        self._file_scope = threading.local()
        with self.connect() as c:
            c.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY, kind TEXT NOT NULL, project_id TEXT, title TEXT NOT NULL, revision INTEGER NOT NULL, content TEXT NOT NULL, metadata TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS revisions(object_id TEXT NOT NULL, revision INTEGER NOT NULL, snapshot TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(object_id,revision));
            CREATE TABLE IF NOT EXISTS annotations(id TEXT PRIMARY KEY, object_id TEXT NOT NULL, revision INTEGER NOT NULL, anchor TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS relations(id TEXT PRIMARY KEY, src TEXT NOT NULL, dst TEXT NOT NULL, type TEXT NOT NULL, status TEXT NOT NULL, source_revision INTEGER NOT NULL, target_revision INTEGER NOT NULL, metadata TEXT NOT NULL, UNIQUE(src,dst,type));
            CREATE TABLE IF NOT EXISTS assets(sha TEXT PRIMARY KEY, filename TEXT NOT NULL, media_type TEXT NOT NULL, metadata TEXT NOT NULL, size INTEGER NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, request_key TEXT UNIQUE NOT NULL, payload_digest TEXT NOT NULL, project_id TEXT, status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT NOT NULL, error TEXT, attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS steps(task_id TEXT NOT NULL, step_key TEXT NOT NULL, status TEXT NOT NULL, data TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(task_id,step_key));
            CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, object_id TEXT, actor TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS conflicts(id TEXT PRIMARY KEY, object_id TEXT NOT NULL, base_revision INTEGER NOT NULL, current_revision INTEGER NOT NULL, candidate TEXT NOT NULL, created_at TEXT NOT NULL);
            """)
            c.execute("INSERT OR IGNORE INTO kv VALUES('schema_version','1')")
        os.chmod(self.db, 0o600)

    def _connect(self, *, readonly=False):
        target = self.db.as_uri() + "?mode=ro" if readonly else self.db
        c = sqlite3.connect(target, uri=readonly, timeout=30, isolation_level=None, factory=_StoreConnection)
        try:
            c.asset_store = self.db
            c.new_asset_files = None
            c.row_factory = sqlite3.Row
            from .compatibility import configure_connection
            configure_connection(c)
            c.execute("PRAGMA foreign_keys=ON")
            if readonly:
                c.execute("PRAGMA query_only=ON")
        except BaseException:
            c.close()
            raise
        return c

    def connect(self):
        # Only this thread's explicitly entered read scope may borrow a reader.
        # Nested helpers must never close it or start a second SQL snapshot.
        reader = getattr(self._read_scope, "connection", None)
        return contextlib.nullcontext(reader) if reader is not None else contextlib.closing(self._connect())

    @contextlib.contextmanager
    def read_snapshot(self):
        reader = getattr(self._read_scope, "connection", None)
        if reader is not None:
            yield reader
            return
        with contextlib.closing(self._connect(readonly=True)) as reader:
            try:
                reader.execute("BEGIN")
                # Pin the database version now, before any nested projection.
                reader.execute("SELECT rootpage FROM sqlite_schema LIMIT 1").fetchone()
                self._read_scope.connection = reader
                yield reader
            finally:
                self._read_scope.connection = None
                if reader.in_transaction:
                    reader.execute("ROLLBACK")

    @contextlib.contextmanager
    def transaction(self):
        require(getattr(self._read_scope, "connection", None) is None,
                "只读状态投影不能开启写事务", "read_only_snapshot", 409)
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.new_asset_files = []
            c.project_sync_ids = set()
            try:
                yield c
                c.execute("COMMIT")
            except BaseException:
                # Keep the writer lock until creator-owned files are removed:
                # another transaction must not adopt them before this cleanup.
                # If SQLite has already ended the transaction, the commit state
                # is uncertain; retaining bytes is safer than deleting success.
                if c.in_transaction:
                    failures = []
                    for path, device, inode in c.new_asset_files:
                        try:
                            current = path.lstat()
                            if (current.st_dev, current.st_ino) == (device, inode):
                                path.unlink()
                        except FileNotFoundError:
                            pass
                        except OSError:
                            failures.append(path.name)
                    c.execute("ROLLBACK")
                    if failures:
                        raise Problem("数据库已回滚；部分新资产文件清理失败，未登记文件不会进入备份", "asset_cleanup", 500, {"assets": failures})
                raise
            finally:
                c.new_asset_files = None
            # Commit is already durable. Mirror failure must never roll it back
            # or overwrite an externally edited project file.
            if c.project_sync_ids:
                from .project_files import sync_after_commit
                self._file_scope.results = sync_after_commit(self,c.project_sync_ids)

    @staticmethod
    def unpack(row):
        if row is None:
            return None
        result = dict(row)
        for k in ("content", "metadata", "anchor", "payload", "result", "data"):
            if k in result:
                result[k] = json.loads(result[k])
        if "archived" in result:
            result["archived"] = bool(result["archived"])
        return result

    def event(self, c, kind, object_id, data, actor="user"):
        c.execute("INSERT INTO events(kind,object_id,actor,data,created_at) VALUES(?,?,?,?,?)", (kind, object_id, actor, encoded(data), now()))
        # Exact-source exports also change the native project projection, even
        # when the object's revision stays unchanged. Publish the mirror only
        # after the export transaction commits, using the same conflict guard.
        if hasattr(c,'project_sync_ids') and (kind.startswith(('object.','artifact.','article.')) or kind == 'export.created'):
            row=c.execute('SELECT kind,project_id FROM objects WHERE id=?',(object_id,)).fetchone()
            if row:c.project_sync_ids.add(object_id if row['kind']=='project' else row['project_id'])

    def events(self, object_id=None, limit=200):
        with self.connect() as c:
            rows = c.execute("SELECT * FROM events WHERE (? IS NULL OR object_id=?) ORDER BY seq DESC LIMIT ?", (object_id, object_id, limit)).fetchall()
        return [self.unpack(r) for r in rows]

    def get(self, ident, revision=None, connection=None):
        if connection is None:
            with self.connect() as c:
                return self.get(ident, revision, c)
        if revision is not None:
            row = connection.execute("SELECT snapshot FROM revisions WHERE object_id=? AND revision=?", (ident, revision)).fetchone()
            require(row, "该成果修订不存在", "not_found", 404)
            return json.loads(row[0])
        row = connection.execute("SELECT * FROM objects WHERE id=?", (ident,)).fetchone()
        require(row, "研究对象不存在", "not_found", 404)
        return self.unpack(row)

    def objects(self, project_id=None, kinds=None, include_archived=True):
        with self.connect() as c:
            rows = c.execute("SELECT * FROM objects WHERE (? IS NULL OR project_id=? OR id=?) ORDER BY updated_at DESC", (project_id, project_id, project_id)).fetchall()
        values = [self.unpack(r) for r in rows]
        return [r for r in values if (not kinds or r["kind"] in kinds) and (include_archived or not r["archived"])]

    @staticmethod
    def feedback_disposition(obj):
        content=obj['content']
        if content.get('disposition') in {'ready','defer'}:return content['disposition']
        held=obj.get('metadata',{}).get('timing')=='after_user_trial' or any(
            a.get('status') in {'deferred_by_user','deferred','defer'} or a.get('timing')=='after_user_trial'
            for a in content.get('actions',[]))
        return 'defer' if held else 'ready'

    def assert_feedback_ready(self, connection, payload):
        ident=payload.get('feedback_id')
        if not ident:return None
        obj=self.get(ident,connection=connection);content=obj['content']
        require(content.get('lifecycle')!='withdrawn','关联反馈已撤回','cancelled',409)
        disposition=self.feedback_disposition(obj)
        require(disposition!='defer','关联反馈仍暂缓；请先明确重新安排，接续不代替解除暂缓','feedback_deferred',409)
        # Coordinator action/status updates also create feedback revisions.
        # Bind meaning and controls, not those self-generated execution rows.
        fields={key:content.get(key) for key in ('original','interpretation','source','source_reference','object_id','object_revision','lifecycle','disposition_reason')}
        fields.update(disposition=disposition,scope=obj['metadata'].get('scope'),timing=obj['metadata'].get('timing'))
        return {'id':ident,'input_sha256':digest(fields),'disposition':disposition}

    def assert_execution(self, connection, task_id, execution_token):
        require(task_id, '执行写入缺少所属任务', 'cancelled', 409)
        row=connection.execute('SELECT status,project_id,payload FROM tasks WHERE id=?',(task_id,)).fetchone()
        require(row and row['status']=='running','任务已暂停或取消','cancelled',409)
        lease=connection.execute('SELECT value FROM kv WHERE key=?',('execution:'+task_id,)).fetchone()
        if lease:
            value=json.loads(lease[0])
            require(execution_token and value.get('token')==execution_token and value.get('state')=='active','执行轮次已失效；不接受晚到写入','cancelled',409)
            if 'input_snapshot' in value:
                require(value['input_snapshot']==self.execution_inputs(connection,task_id),'回答或指导已更新；旧候选已保留，请检查后明确修订候选','candidate_revision_required',409)
        else:
            require(execution_token is None,'执行租约缺失','cancelled',409)
        from .acquisition import assert_child as assert_acquisition_child
        assert_acquisition_child(self,connection,json.loads(row["payload"]))
        from .cycle import assert_child
        assert_child(self,connection,json.loads(row['payload']))
        self.assert_material_access(connection,json.loads(row['payload']))
        from .growth import assert_ready
        assert_ready(self,connection,{'id':task_id,'payload':json.loads(row['payload'])})
        # The check and each publish share one SQLite write transaction. A
        # question/withdrawal committed after Runtime.check still fences this
        # write; runtime polling is not the publication authority.
        blockers=self.question_blockers(connection,task_id)
        stale=[q for q in blockers if not q['question_view']['source_valid']]
        require(not stale,'必要裁决来源已更新；请先明确重新评估，旧回答和候选已保留','candidate_revision_required',409)
        require(not blockers,'必要裁决尚未明确继续','cancelled',409)
        self.assert_feedback_ready(connection,json.loads(row['payload']))

    def material_ids(self, payload):
        refs={ref['id'] for ref in payload.get('context',{}).get('materials',[]) if isinstance(ref,dict) and isinstance(ref.get('id'),str)}
        if payload.get('target_id'):refs.add(payload['target_id'])
        refs.update(self.reference_ids(payload.get('context',{}).get('cycle_evidence',[])))
        refs.update(node['id'] for node in payload.get('context',{}).get('graph_catalog',{}).get('nodes',[]))
        return refs

    def reference_ids(self, value):
        refs=set()
        def ref(item):
            if isinstance(item,dict):
                ident=item.get('id',item.get('object_id'))
                if isinstance(ident,str):refs.add(ident)
        def visit(item):
            if isinstance(item,dict):
                if 'source_ref' in item:ref(item['source_ref'])
                for field in ['source_refs','citations','components']:
                    if isinstance(item.get(field),list):
                        for source in item[field]:ref(source)
                if isinstance(item.get('component_id'),str):refs.add(item['component_id'])
                if isinstance(item.get('source_object_id'),str):refs.add(item['source_object_id'])
                if isinstance(item.get('id'),str) and item['id'].startswith(('ART-','PRJ-','QUESTION-')) and type(item.get('revision')) is int:refs.add(item['id'])
                for nested in item.values():visit(nested)
            elif isinstance(item,list):
                for nested in item:visit(nested)
        visit(value);return refs

    def assert_reference_access(self, connection, project_id, value):
        for ident in self.reference_ids(value):self.assert_source_access(connection,project_id,ident)

    def assert_source_access(self, connection, project_id, ident):
        current=self.get(ident,connection=connection)
        owner=current['id'] if current['kind']=='project' else current['project_id']
        require(owner==project_id or project_id in current['metadata'].get('shared_with',[]),
                '任务依赖材料的共享授权已撤回；未保存或发布新衍生成果','forbidden',403,{'source_id':ident})

    def assert_material_access(self, connection, payload):
        for ident in self.material_ids(payload):self.assert_source_access(connection,payload['project_id'],ident)
        self.assert_material_readiness(connection,payload)

    @staticmethod
    def workshop_artifact_identity(obj):
        return digest({k:v for k,v in obj['content'].items() if k not in {'acceptance','status'}})

    @classmethod
    def workshop_readiness(cls, obj, current=None):
        """Current technical judgments for these exact outputs, never science approval."""
        current=current or obj;identity=cls.workshop_artifact_identity(obj)
        same=identity==cls.workshop_artifact_identity(current)
        records=current['content'].get('acceptance',[])
        records=records if isinstance(records,list) else [records]
        # Old unbound failures remain conservative blockers. An unbound pass
        # cannot certify exact bytes, including after an old object was edited.
        applicable=[r for r in records if isinstance(r,dict) and
                    (r.get('artifact_sha256')==identity or (not r.get('artifact_sha256') and r.get('status')=='failed'))]
        definitive=[r for r in applicable if r.get('status') in {'failed','accepted'}]
        latest=applicable[-1] if applicable else None
        state=latest.get('status','pending') if latest else 'generated'
        if state=='pending' and definitive and definitive[-1]['status']=='failed':state='failed'
        if same and current['metadata'].get('technical_status')=='failed':state='failed'
        if not same and obj['metadata'].get('technical_status')=='failed':
            frozen_records=obj['content'].get('acceptance',[])
            frozen_records=frozen_records if isinstance(frozen_records,list) else [frozen_records]
            accepted=definitive[-1] if definitive and definitive[-1]['status']=='accepted' else {}
            # A server-bound append checks revision N and commits at N+1. Only
            # a later append for these exact bytes can supersede this snapshot's
            # failed flag. Imported/older passes or unknown ordering cannot.
            superseded=(accepted.get('artifact_sha256')==identity and
                        type(accepted.get('artifact_revision')) is int and
                        type(obj.get('revision')) is int and type(current.get('revision')) is int and
                        obj['revision']<=accepted['artifact_revision']<current['revision'] and
                        records[:len(frozen_records)]==frozen_records and
                        accepted not in frozen_records and accepted in records[len(frozen_records):])
            if not superseded:state='failed'
        if not latest and current['content'].get('acceptance'):state='pending' if state!='failed' else state
        return {'technical_status':state,'blocked':state=='failed','artifact_sha256':identity,
                'acceptance':copy.deepcopy(latest),'scientific_approval':False}

    def assert_material_readiness(self, connection, payload, *, mark_requirement=False):
        """One guard for explicit revisions, dependency outputs and late writes."""
        refs=list(payload.get('context',{}).get('materials',[]));workshop_material=False
        for ident in payload.get('depends_on',[]):
            dep=self.task(ident,connection)
            require(dep['project_id']==payload['project_id'],'任务依赖不属于此项目','forbidden',403)
            result=dep['result']
            if result.get('object_id'):refs.append({'id':result['object_id'],'revision':result.get('revision')})
        for ref in refs:
            obj=self.get(ref['id'],ref.get('revision'),connection)
            self.assert_source_access(connection,payload['project_id'],obj['id'])
            if obj['kind']=='workshop':
                workshop_material=True
                readiness=self.workshop_readiness(obj,self.get(obj['id'],connection=connection))
                require(not readiness['blocked'],'技术验收失败的产物不能作为就绪科学材料','dependency_failed',409,
                        {'source_id':obj['id'],'source_revision':obj['revision'],**readiness})
            else:require(obj['metadata'].get('technical_status')!='failed','技术依赖失败，不能当作有效科学证据','dependency_failed',409)
        if mark_requirement and workshop_material:
            from .compatibility import require_features,WORKSHOP_ACCEPTANCE_FEATURE
            require_features(connection,[WORKSHOP_ACCEPTANCE_FEATURE])

    def normalize_workshop_acceptance(self, old, proposal, expected_revision):
        """Append-only CAS; legacy object.save clients receive the same binding."""
        previous=old['content'].get('acceptance',[]);records=proposal['content'].get('acceptance',[])
        previous=previous if isinstance(previous,list) else [previous]
        require(isinstance(records,list),'工坊验收历史需要列表')
        changed=records!=previous;identity=self.workshop_artifact_identity(old)
        artifact_changed=identity!=self.workshop_artifact_identity({'content':proposal['content']})
        if changed:
            require(expected_revision==old['revision'],'工坊验收对象已变化，请重读后登记','conflict',409)
            require(records[:len(previous)]==previous and len(records)>len(previous),'工坊验收历史不能删除或改写；请追加更正','conflict',409)
            require(not artifact_changed,'验收与产物修改须分开保存并重新核对','conflict',409)
        bound=copy.deepcopy(previous)
        old_without_flag={**old,'metadata':{**old['metadata'],'technical_status':'pending'}}
        legacy_failure=old['metadata'].get('technical_status')=='failed' and not self.workshop_readiness(old_without_flag)['blocked']
        new_flag=not changed and proposal['metadata'].get('technical_status')=='failed' and old['metadata'].get('technical_status')!='failed'
        if legacy_failure or new_flag:
            require(not new_flag or not artifact_changed,'失败登记与产物修改须分开保存','conflict',409)
            bound.append({'status':'failed','evidence':'Recorded technical_status=failed metadata; no detailed check evidence supplied',
                          'limitations':'Preserved failure flag, not a new scientific or technical experiment',
                          'artifact_revision':old['revision'],'artifact_sha256':identity,'created_at':now(),
                          'author':'stored_failure_flag','scientific_approval':False})
        for record in records[len(previous):] if changed else []:
            require(isinstance(record,dict) and record.get('status') in {'failed','accepted','pending'},'技术验收状态无效')
            require(isinstance(record.get('evidence'),str) and record['evidence'].strip(),'请记录实际检查与证据')
            bound.append({k:copy.deepcopy(record.get(k,'')) for k in ('status','evidence','limitations')} |
                         {'artifact_revision':old['revision'],'artifact_sha256':identity,
                          'created_at':now(),'author':'user','scientific_approval':False})
        if bound!=previous or artifact_changed:
            proposal['content']={**proposal['content'],'acceptance':bound}
            proposal['metadata']={**proposal['metadata'],'technical_status':'pending','scientific_approval':False}
        state=self.workshop_readiness({'content':proposal['content'],'metadata':proposal['metadata']})
        if bound!=previous or artifact_changed or state['blocked']:
            proposal['metadata']={**proposal['metadata'],'technical_status':state['technical_status'],'scientific_approval':False}

    def invalidate_material_access(self, connection, obj):
        # The coordinating parent may still have independent children. Fence
        # only actual dependent workers; future allocations recheck their refs.
        for row in connection.execute("SELECT * FROM tasks WHERE status IN ('queued','running','waiting_input','waiting_resource','waiting_authorization','paused')").fetchall():
            task=self.unpack(row)
            if task['payload'].get('kind')=='research_cycle' or obj['id'] not in self.material_ids(task['payload']):continue
            try:self.assert_source_access(connection,task['project_id'],obj['id'])
            except Problem as error:
                if error.code!='forbidden':raise
                lease_row=connection.execute('SELECT value FROM kv WHERE key=?',('execution:'+task['id'],)).fetchone()
                if lease_row:
                    lease=json.loads(lease_row[0]);lease.update(state='revoked',revoked_at=now(),reason='material authorization withdrawn')
                    connection.execute('UPDATE kv SET value=? WHERE key=?',(encoded(lease),'execution:'+task['id']))
                state='paused' if task['status']=='paused' else 'waiting_authorization'
                connection.execute('UPDATE tasks SET status=?,error=?,result=?,updated_at=? WHERE id=?',
                    (state,str(error),encoded({**task['result'],'failure_code':'material_authorization_withdrawn','source_id':obj['id']}),now(),task['id']))
                self.event(connection,'task.'+state,task['id'],{'source_id':obj['id'],'reason':'material authorization withdrawn'},'runtime')

    def execution_inputs(self, connection, task_id):
        from .questions import scoped_input
        row=connection.execute('SELECT project_id FROM tasks WHERE id=?',(task_id,)).fetchone()
        require(row,'任务不存在','not_found',404)
        decisions=[]
        for question in connection.execute("SELECT id,revision,content FROM objects WHERE project_id=? AND kind='question' ORDER BY id",(row[0],)):
            content=json.loads(question['content'])
            if content.get('answer') and scoped_input(content) and (not content.get('task_id') or content['task_id']==task_id):
                decisions.append({'id':question['id'],'revision':question['revision']})
        guidance=[event[0] for event in connection.execute("SELECT seq FROM events WHERE object_id=? AND kind='task.guidance' ORDER BY seq",(task_id,))]
        return {'decisions':decisions,'guidance':guidance}

    def task_input_view(self, task_id):
        with self.connect() as c:
            snapshot=self.execution_inputs(c,task_id)
            answers=[self.get(d['id'],d['revision'],c) for d in snapshot['decisions']]
            guidance=[self.unpack(c.execute('SELECT * FROM events WHERE seq=?',(seq,)).fetchone()) for seq in snapshot['guidance']]
        return {'input_snapshot':snapshot,'input_decisions':answers,'input_guidance':guidance}

    def question_view(self, obj):
        from .questions import question_view
        return question_view(self,obj)

    def question_blockers(self, connection, task_id):
        from .questions import question_view
        task=connection.execute('SELECT project_id FROM tasks WHERE id=?',(task_id,)).fetchone()
        require(task,'任务不存在','not_found',404)
        blockers=[]
        for row in connection.execute("SELECT * FROM objects WHERE project_id=? AND kind='question'",(task[0],)):
            q=self.unpack(row);content=q['content']
            if not content.get('blocking') or (content.get('task_id') and content['task_id']!=task_id):continue
            q=question_view(self,q,connection)
            if content.get('status')!='answered' or content.get('disposition')!='continue' or not q['question_view']['source_valid']:blockers.append(q)
        return blockers

    def validate_question_scope(self, connection, project_id, content):
        if 'scope' not in content:return  # Existing explicit user/project gates.
        from .questions import SCOPES
        require(content['scope'] in SCOPES,'研究问题作用域无效')
        if content.get('scope')=='current_task' or content.get('bound_task_id'):
            ident=content.get('bound_task_id') or content.get('task_id')
            row=connection.execute('SELECT project_id FROM tasks WHERE id=?',(ident,)).fetchone()
            require(row and row[0]==project_id and content.get('task_id')==ident,'研究问题只能绑定同项目的具体任务','forbidden',403)
        require(not content.get('blocking') or content['scope']=='current_task' or content.get('bound_task_id'),
            '后续、可选和历史问题未经明确绑定不能阻断任务')

    def register_questions(self, project_id, questions, origin, *, source_ref=None, source_candidate=None, parent=None, task_id=None, execution_token=None, connection=None):
        """Register a whole question batch before revoking a blocking execution.

        The original model JSON and parent remain immutable inputs. Deterministic
        identities make recovery/materialization idempotent without erasing an
        answer or revising an existing question. No candidate artifact is needed
        for a question bound to an exact pre-publication model checkpoint.
        """
        created=[];objects=[]
        with (self.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            if task_id:self.assert_execution(c,task_id,execution_token)
            if parent:
                current=self.get(parent['id'],connection=c)
                require(current['revision']==parent['revision'],'父问题已更新，请重读后展开','conflict',409)
            for question in questions:
                seed={'origin':origin,'question_id':question['id']}
                if origin.get('parent_question_id'):seed['original_question_sha256']=digest(question['raw'])
                ident='QUESTION-'+digest(seed)[:24]
                row=c.execute('SELECT * FROM objects WHERE id=?',(ident,)).fetchone()
                if row:objects.append(self.unpack(row));continue
                content={key:copy.deepcopy(question[key]) for key in ['scope','blocking','background','options','recommendation','source_refs']}
                content.update(question=question['question'],model_question_id=question['id'],raw_model_question=copy.deepcopy(question['raw']),
                    status='open',origin=copy.deepcopy(origin),grants_permissions=False)
                if origin.get('task_id'):content['origin_task_id']=origin['task_id']
                if question['scope']=='current_task':content['task_id']=origin['task_id']
                if source_ref:content['source_ref']=copy.deepcopy(source_ref)
                if source_candidate:content['source_candidate']=copy.deepcopy(source_candidate)
                if parent:
                    content['parent_question_id']=parent['id']
                    if parent['content'].get('status') in {'answered','deferred','denied','resolved'} or parent['content'].get('answer'):
                        for key in ['status','answer','disposition','answered_at']:
                            if key in parent['content']:content[key]=copy.deepcopy(parent['content'][key])
                        content['inherited_answer']={'id':parent['id'],'revision':parent['revision'],'scope':'historical parent response; no new execution grant'}
                self.validate_question_scope(c,project_id,content)
                t=now();obj={'id':ident,'kind':'question','project_id':project_id,'title':question['question'],
                    'revision':1,'content':content,'metadata':{'question_origin':'model' if task_id else 'explicit_materialization'},'archived':False,'created_at':t,'updated_at':t}
                c.execute('INSERT INTO objects VALUES(?,?,?,?,?,?,?,?,?,?)',(ident,'question',project_id,obj['title'],1,encoded(content),encoded(obj['metadata']),0,t,t))
                self.snapshot(c,obj,'agent' if task_id else 'user','scoped question registration');self.event(c,'question.registered',ident,{'origin':origin,'source_ref':source_ref,'source_candidate':source_candidate})
                objects.append(obj);created.append(ident)
            if task_id:
                data={'question_ids':[obj['id'] for obj in objects],'created':created,'origin':origin}
                key='questions:'+digest(origin)[:16]
                c.execute('INSERT INTO steps VALUES(?,?,?,?,?) ON CONFLICT(task_id,step_key) DO UPDATE SET status=excluded.status,data=excluded.data,updated_at=excluded.updated_at',(task_id,key,'registered',encoded(data),now()))
            # Run these only after every question and registration receipt is
            # durable in the same transaction; the first blocking item revokes.
            for obj in objects:self.invalidate_control(c,obj)
            waiting=False
            if task_id:
                row=c.execute('SELECT status,result FROM tasks WHERE id=?',(task_id,)).fetchone();waiting=row['status']=='waiting_input'
                if waiting:
                    result={**json.loads(row['result']),'question_ids':[obj['id'] for obj in objects],'failure_code':'questions_required'}
                    c.execute('UPDATE tasks SET result=? WHERE id=?',(encoded(result),task_id))
        return {'questions':[self.question_view(obj) for obj in objects],'created':created,'waiting_input':waiting}

    def wait_for_candidate_revision(self, task_id, execution_token, error):
        """A stale input snapshot cannot authorize writes, including task_update.

        Revoke this exact active execution without checking snapshot freshness;
        a late callback still cannot change a newer, paused or cancelled round.
        """
        with self.transaction() as c:
            row=c.execute('SELECT status,result FROM tasks WHERE id=?',(task_id,)).fetchone()
            saved=c.execute('SELECT value FROM kv WHERE key=?',('execution:'+task_id,)).fetchone()
            lease=json.loads(saved[0]) if saved else {}
            if not row or row['status']!='running' or lease.get('token')!=execution_token or lease.get('state')!='active':return False
            lease.update(state='revoked',revoked_at=now(),reason='candidate inputs changed')
            c.execute('UPDATE kv SET value=? WHERE key=?',(encoded(lease),'execution:'+task_id))
            result={**json.loads(row['result']),'failure_code':'candidate_revision_required'}
            c.execute("UPDATE tasks SET status='waiting_input',error=?,result=?,updated_at=? WHERE id=?",(error,encoded(result),now(),task_id))
            self.event(c,'task.waiting_input',task_id,{'error':error,'failure_code':'candidate_revision_required','execution_token':execution_token},'runtime')
        return True

    def invalidate_control(self, connection, obj):
        """Persist a control object and revoke affected work atomically.

        Called inside create/save, so editing a required question or withdrawing
        feedback through a general object editor has the same stop semantics.
        Explicit user pause is never undone by a deferred decision.
        """
        from .questions import question_view
        affected={obj['id']:obj}
        # A question is also a supported source object. Scan all actual adopted
        # edges once, then apply controls separately. Invalidation does not edit
        # question revisions, so recursion would invent no additional version
        # changes and could loop on cyclic/self references. Each ID acts once.
        for row in connection.execute("SELECT * FROM objects WHERE kind='question'").fetchall():
            q=self.unpack(row)
            if not q['content'].get('blocking'):continue
            view=question_view(self,q,connection)['question_view']
            if not view['source_valid'] and any(ref.get('id')==obj['id'] for ref in view['sources']):affected[q['id']]=q
        for control in affected.values():self._invalidate_control_object(connection,control)

    def _invalidate_control_object(self, connection, obj):
        """Apply direct question/feedback control without traversing sources."""
        from .questions import question_view
        content=obj['content'];question=obj['kind']=='question' and content.get('blocking')
        withdrawn=obj['kind']=='feedback' and content.get('lifecycle')=='withdrawn'
        feedback_held=obj['kind']=='feedback' and self.feedback_disposition(obj)=='defer'
        if feedback_held:
            from .compatibility import require_features
            require_features(connection,['feedback_defer_control_v1'])
        stale=bool(question and not question_view(self,obj,connection)['question_view']['source_valid'])
        if not withdrawn and not feedback_held and (not question or (content.get('status')=='answered' and content.get('disposition')=='continue' and not stale)):return
        for row in connection.execute('SELECT * FROM tasks WHERE project_id=?',(obj['project_id'],)).fetchall():
            task=self.unpack(row)
            relevant=(not content.get('task_id') or content['task_id']==task['id']) if question else task['payload'].get('feedback_id')==obj['id']
            if not relevant or task['status'] in {'generated','review','deliverable','cancelled'}:continue
            denied=withdrawn or content.get('disposition')=='deny'
            state='cancelled' if denied else 'paused' if task['status']=='paused' else 'waiting_input'
            error='关联反馈已撤回' if withdrawn else '必要裁决拒绝该动作' if denied else '用户暂停' if state=='paused' else '关联反馈仍暂缓；请先明确重新安排' if feedback_held else ('必要裁决来源已更新，请明确重新评估：' if stale else '必要裁决尚未明确继续：')+obj['title']
            lease_row=connection.execute('SELECT value FROM kv WHERE key=?',('execution:'+task['id'],)).fetchone()
            if lease_row:
                lease=json.loads(lease_row[0]);lease.update(state='revoked',revoked_at=now(),reason=error)
                connection.execute('UPDATE kv SET value=? WHERE key=?',(encoded(lease),'execution:'+task['id']))
            connection.execute('UPDATE tasks SET status=?,error=?,updated_at=? WHERE id=?',(state,error,now(),task['id']))
            if stale and not denied:
                result={**task['result'],'failure_code':'question_source_review_required','question_ids':[obj['id']]}
                connection.execute('UPDATE tasks SET result=? WHERE id=?',(encoded(result),task['id']))
            self.event(connection,'task.'+state,task['id'],{'error':error,'control_object':obj['id'],'control_revision':obj['revision']},'runtime')
            if task['payload'].get('kind')=='research_cycle':
                from .cycle import fence_descendants
                fence_descendants(self,connection,task['id'],state,error)

    def create(self, kind, title, project_id=None, content=None, metadata=None, actor="user", ident=None, task_id=None, execution_token=None, connection=None):
        require(isinstance(title, str) and title.strip(), "请输入可读标题")
        require(kind in {"project", "concept", "question", "report", "note", "figure", "diagram", "paper", "poster", "slides", "workshop", "workshop_note", "literature", "growth", "feedback", "commission", "dataset", "recipe"}, "未知对象类型")
        ident = ident or uid("PRJ" if kind == "project" else "ART")
        t = now()
        with (self.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            if kind in {'dataset','recipe'}:
                from .compatibility import require_features
                require_features(c,['content_generation_plans_v1'])
            if task_id:
                self.assert_execution(c,task_id,execution_token)
                self.assert_reference_access(c,project_id,content or {})
            if project_id:
                require(self.get(project_id, connection=c)["kind"] == "project", "研究归属必须为项目")
            if kind=='question':self.validate_question_scope(c,project_id,content or {})
            if kind=='workshop' and self.workshop_readiness({'content':content or {},'metadata':metadata or {}})['blocked']:
                metadata={**(metadata or {}),'technical_status':'failed','scientific_approval':False}
            if kind=='workshop' and ((content or {}).get('acceptance') or (metadata or {}).get('technical_status') in {'failed','accepted','pending'}):
                from .compatibility import require_features,WORKSHOP_ACCEPTANCE_FEATURE
                require_features(c,[WORKSHOP_ACCEPTANCE_FEATURE])
            obj = {"id": ident, "kind": kind, "project_id": project_id, "title": title.strip(), "revision": 1, "content": content or {}, "metadata": metadata or {}, "archived": False, "created_at": t, "updated_at": t}
            self.validate_article_object(c,obj)
            self.require_figure_layout_runtime(c, obj)
            self.require_manuscript_format_runtime(c, obj)
            self.require_member_snapshot_runtime(c, obj)
            if kind == 'paper':
                from .paper_sources import source_state
                state = source_state(obj)
                if state['selection_explicit']:
                    from .compatibility import require_features
                    require_features(c, ['paper_source_selection_v1'])
            c.execute("INSERT INTO objects VALUES(?,?,?,?,?,?,?,?,?,?)", (ident, kind, project_id, title.strip(), 1, encoded(obj["content"]), encoded(obj["metadata"]), 0, t, t))
            self.snapshot(c, obj, actor, "create")
            self.event(c, "object.created", ident, {"kind": kind, "project_id": project_id}, actor)
            self.invalidate_control(c,obj)
        return obj

    @staticmethod
    def require_member_snapshot_runtime(connection, obj):
        if obj.get('kind') == 'dataset' and obj.get('content', {}).get('authority_kind') == 'immutable_member_manifest':
            from .compatibility import require_features
            require_features(connection, ['chunked_member_snapshot_v1'])

    @staticmethod
    def require_figure_layout_runtime(connection, obj):
        if obj.get('kind') != 'figure':
            return
        layers = obj.get('content', {}).get('overlays', [])
        targets = list(layers) if isinstance(layers, dict) else [
            layer.get('target') or layer.get('object_id') or layer.get('id')
            for layer in layers if isinstance(layer, dict)
        ] if isinstance(layers, list) else []
        if any(target == 'figure:root' or isinstance(target, str) and target.startswith('colorbar:') for target in targets):
            from .compatibility import require_features
            require_features(connection, ['figure_visual_layout_v1'])

    @staticmethod
    def require_manuscript_format_runtime(connection, obj):
        if 'manuscript_format' not in obj.get('metadata', {}):
            return
        require(obj.get('kind') in {'report', 'note', 'paper', 'workshop_note'}, '格式配置只适用于文稿')
        from .manuscript_format40 import normalize_format
        normalize_format(obj['metadata']['manuscript_format'])
        from .compatibility import require_features
        require_features(connection, ['manuscript_format_v1'])

    def snapshot(self, c, obj, actor, reason):
        c.execute("INSERT INTO revisions VALUES(?,?,?,?,?,?)", (obj["id"], obj["revision"], encoded(obj), actor, reason, now()))

    def save(self, ident, expected_revision, content=None, title=None, metadata=None, archived=None, actor="user", reason="edit", merge=True, operation_key=None, task_id=None, execution_token=None, question_source_snapshot=None, connection=None, prepared_updated_at=None):
        # Internal staged-render commits prepare their complete future snapshot
        # before rendering. Public actions never forward this timestamp.
        if prepared_updated_at is not None:
            require(isinstance(connection, _StoreConnection) and connection.asset_store == self.db and connection.in_transaction
                    and connection.new_asset_files is not None and isinstance(prepared_updated_at, str),
                    "预先准备的时间戳只可用于本工作区托管事务", "prepared_snapshot", 409)
            try:
                require(datetime.fromisoformat(prepared_updated_at).tzinfo is not None,
                        "预先准备的时间戳须含时区", "prepared_snapshot", 409)
            except (ValueError, TypeError):
                raise Problem("预先准备的时间戳无效", "prepared_snapshot", 409)
        conflict = None
        with (self.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            if task_id:self.assert_execution(c,task_id,execution_token)
            if operation_key:
                previous = c.execute('SELECT value FROM kv WHERE key=?', ('commit:'+operation_key,)).fetchone()
                if previous: return json.loads(previous[0])
            old = self.get(ident, connection=c)
            if task_id and content is not None:self.assert_reference_access(c,old['project_id'],content)
            if question_source_snapshot is not None:
                from .questions import question_view
                require(old['kind']=='question' and question_view(self,old,c)['question_view']['sources']==question_source_snapshot,
                    '问题来源在重新评估期间已变化，请重读后答复','conflict',409)
            require(isinstance(expected_revision, int) and expected_revision >= 1, "写入需要已读版本", "version_required", 409)
            base = self.get(ident, expected_revision, c)
            proposal = {"content": base["content"] if content is None else content, "title": base["title"] if title is None else title, "metadata": base["metadata"] if metadata is None else metadata, "archived": base["archived"] if archived is None else bool(archived)}
            keys = list(proposal)
            try:
                if expected_revision != old["revision"]:
                    require(merge, "成果已更新，请重新读取", "conflict", 409)
                    proposal = merge3({k: base[k] for k in keys}, {k: old[k] for k in keys}, proposal)
            except Problem as e:
                cid = uid("CONFLICT")
                c.execute("INSERT INTO conflicts VALUES(?,?,?,?,?,?)", (cid, ident, expected_revision, old["revision"], encoded(proposal), now()))
                self.event(c, "edit.conflict", ident, {"conflict_id": cid, "base": expected_revision, "current": old["revision"]}, actor)
                conflict = Problem(str(e), "conflict", 409, {**e.details, "conflict_id": cid, "current": old, "candidate": proposal})
            if conflict is None:
                if old['kind']=='feedback':
                    from .feedback_external import protect_saved_actions
                    protect_saved_actions(c, old, proposal['content'])
                if old['kind']=='question':self.validate_question_scope(c,old['project_id'],proposal['content'])
                if old['kind']=='workshop':
                    self.normalize_workshop_acceptance(old,proposal,expected_revision)
                    if old['content'].get('acceptance',[])!=proposal['content'].get('acceptance',[]):
                        from .compatibility import require_features,WORKSHOP_ACCEPTANCE_FEATURE
                        require_features(c,[WORKSHOP_ACCEPTANCE_FEATURE])
                if proposal['title']!=old['title']:
                    proposal['metadata']={**proposal['metadata'],'aliases':list(dict.fromkeys(proposal['metadata'].get('aliases',[])+[old['title']]))}
                obj = {**old, **proposal, "revision": old["revision"] + 1, "updated_at": prepared_updated_at or now()}
                self.validate_article_object(c,obj)
                self.require_figure_layout_runtime(c, obj)
                self.require_manuscript_format_runtime(c, obj)
                self.require_member_snapshot_runtime(c, obj)
                require(isinstance(obj["title"], str) and obj["title"].strip(), "标题不能为空")
                if obj['kind'] == 'paper':
                    from .paper_sources import source_state
                    state = source_state(obj)
                    if state['selection_explicit']:
                        from .compatibility import require_features
                        require_features(c, ['paper_source_selection_v1'])
                c.execute("UPDATE objects SET title=?,revision=?,content=?,metadata=?,archived=?,updated_at=? WHERE id=?", (obj["title"], obj["revision"], encoded(obj["content"]), encoded(obj["metadata"]), obj["archived"], obj["updated_at"], ident))
                self.snapshot(c, obj, actor, reason)
                self.event(c, "object.saved", ident, {"base_revision": expected_revision, "revision": obj["revision"], "merged": expected_revision != old["revision"], "reason": reason}, actor)
                self._anchors(c, obj)
                self.invalidate_control(c,obj)
                if old['metadata'].get('shared_with',[])!=obj['metadata'].get('shared_with',[]):self.invalidate_material_access(c,obj)
                if operation_key: c.execute('INSERT INTO kv VALUES(?,?)',('commit:'+operation_key,encoded(obj)))
        if conflict:
            raise conflict
        return obj

    def validate_article_object(self,c,obj):
        if obj['kind']=='workshop_note':
            from .article_workspace import sections
            from .compatibility import require_features
            require_features(c,['article_workspace_v1'])
            content=obj['content'];manuscript=self.get(content.get('manuscript_id'),connection=c)
            require(manuscript['kind'] in {'paper','report'} and manuscript['project_id']==obj['project_id'],
                    '工坊笔记必须关联本项目稿件','article_note_conflict',409)
            matches=[s for s in sections(manuscript) if s['id']==content.get('section_id')]
            require(len(matches)==1 and matches[0]['anchor_valid'] and matches[0]['heading_block_id']==content.get('section_block_id'),
                    '工坊笔记章节身份不符','article_note_conflict',409)
        if obj['kind'] in {'paper','report','note','figure','diagram','poster','slides'}:
            for ident in self.reference_ids(obj['content']):
                row=c.execute('SELECT kind FROM objects WHERE id=?',(ident,)).fetchone()
                require(not row or row['kind']!='workshop_note','准备笔记不能成为成果正文/导出的依赖','preparation_boundary',409)

    def restore(self, ident, target_revision, expected_revision):
        target = self.get(ident, target_revision)
        return self.save(ident, expected_revision, content=target["content"], title=target["title"], metadata=target["metadata"], archived=target["archived"], reason="restore:" + str(target_revision), merge=False)

    def revisions(self, ident):
        with self.connect() as c:
            return [dict(r) for r in c.execute("SELECT revision,actor,reason,created_at FROM revisions WHERE object_id=? ORDER BY revision DESC", (ident,))]

    def annotate(self, ident, revision, anchor, text, *, connection=None):
        if connection is not None:
            require(isinstance(connection,_StoreConnection) and connection.asset_store==self.db and connection.in_transaction and connection.new_asset_files is not None,"批注写入需要本工作区托管事务","asset_transaction",409)
        require(isinstance(text, str) and text.strip(), "批注不能为空")
        obj = self.get(ident, revision, connection=connection)
        aid = uid("ANN")
        with (self.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            if isinstance(anchor,dict) and anchor.get('field')=='caption':
                from .compatibility import require_features
                require_features(c,['workdesk_caption_opinions_v1'])
            c.execute("INSERT INTO annotations VALUES(?,?,?,?,?,?,?)", (aid, ident, revision, encoded(anchor), text, "anchored", now()))
            self._anchors(c, self.get(ident, connection=c))
            self.event(c, "annotation.created", ident, {"annotation_id": aid, "revision": revision})
            return self.unpack(c.execute("SELECT * FROM annotations WHERE id=?", (aid,)).fetchone())

    def _anchors(self, c, obj):
        def collect(value, result):
            if isinstance(value, dict):
                if "id" in value: result[value["id"]] = value
                for v in value.values(): collect(v, result)
            elif isinstance(value, list):
                for v in value: collect(v, result)
        elements = {}
        collect(obj["content"], elements)
        elements[obj["id"]] = obj
        artist_records = None
        region_records = None
        for row in c.execute("SELECT * FROM annotations WHERE object_id=?", (obj["id"],)):
            if row['status']=='resolved': continue
            a = json.loads(row["anchor"])
            if a.get('kind') == 'main_figure_slots':
                from .manuscript_main_round import anchor_status
                c.execute('UPDATE annotations SET status=? WHERE id=?', (anchor_status(a, obj), row['id']))
                continue
            if 'figure_region' in a:
                from .figure_interaction import figure_region_anchor_status
                render=a.get('render_source',{});source=None
                if not isinstance(render,dict):render={}
                try:source=self.get(obj['id'],render['revision'],c) if render.get('object_id')==obj['id'] and type(render.get('revision')) is int and render['revision']>0 else None
                except Problem:pass
                def valid_static_preview(saved):
                    if not saved:return None
                    value=saved.get('content',{}).get('preview')
                    sha=value.get('sha256',value.get('sha')) if isinstance(value,dict) else value
                    try:
                        asset=self.asset(sha,c)
                        projects=set(asset['metadata'].get('projects',[])) | {asset['metadata'].get('project_id')}
                        if saved.get('project_id') not in projects:return None
                        with (self.blobs/asset['sha']).open('rb') as stream:header=stream.read(8)
                        if not ((asset['media_type']=='image/png' and header==b'\x89PNG\r\n\x1a\n') or (asset['media_type']=='image/jpeg' and header.startswith(b'\xff\xd8\xff'))):return None
                        return asset['sha']
                    except (Problem,OSError,TypeError):return None
                if region_records is None:
                    saved=c.execute('SELECT value FROM kv WHERE key LIKE ?',('exports:'+obj['id']+':%',)).fetchall()
                    registered=sorted([item for record in saved for item in json.loads(record[0])],key=lambda r:r['created_at'])
                    region_records=[]
                    for record in registered:
                        result=record.get('result',{})
                        if not isinstance(result,dict) or not isinstance(result.get('assets',{}),dict):continue
                        image=result.get('assets',{}).get('figure.png')
                        if 'preview_identity' in result or not isinstance(image,dict):continue
                        try:
                            asset=self.asset(image.get('sha'),c)
                            projects=set(asset['metadata'].get('projects',[])) | {asset['metadata'].get('project_id')}
                            if asset['media_type']!='image/png' or obj.get('project_id') not in projects:continue
                            with (self.blobs/asset['sha']).open('rb') as stream:
                                if stream.read(8)!=b'\x89PNG\r\n\x1a\n':continue
                        except (Problem,OSError):continue
                        # Use persisted asset identity, not the copied/client
                        # metadata in an export result or annotation payload.
                        region_records.append({**record,'result':{**result,'assets':{'figure.png':asset}}})
                status=figure_region_anchor_status(a,obj,source,digest(source) if source else None,
                    export_records=region_records,current_source_sha256=digest(obj),
                    source_preview_sha256=valid_static_preview(source),current_preview_sha256=valid_static_preview(obj))
                c.execute('UPDATE annotations SET status=? WHERE id=?',(status,row['id']))
                continue
            if a.get('component_region'):
                refs=[ref for ref in obj['content'].get('components',[]) if (ref.get('id') or ref.get('object_id'))==a.get('component_id')]
                bbox=a.get('component_region',{}).get('bbox',[])
                valid=(len(bbox)==4 and all(type(x) in {int,float} and math.isfinite(x) and 0<=x<=1 for x in bbox)
                       and bbox[2]>0 and bbox[3]>0 and bbox[0]+bbox[2]<=1.000001 and bbox[1]+bbox[3]<=1.000001)
                status='anchored' if len(refs)==1 and refs[0].get('revision')==a.get('component_revision') and valid else 'orphaned'
                c.execute('UPDATE annotations SET status=? WHERE id=?',(status,row['id']))
                continue
            if a.get("artist_id"):
                from .figure_interaction import figure_artist_anchor_status
                if artist_records is None:
                    saved = c.execute("SELECT value FROM kv WHERE key LIKE ?", ('exports:'+obj['id']+':%',)).fetchall()
                    artist_records = sorted([item for record in saved for item in json.loads(record[0])], key=lambda r:r['created_at'])
                status = figure_artist_anchor_status(a, obj, artist_records)
                c.execute("UPDATE annotations SET status=? WHERE id=?", (status, row['id']))
                continue
            if a.get('field')=='caption':
                refs=[ref for ref in obj['content'].get('components',[]) if isinstance(ref,dict) and (ref.get('id') or ref.get('object_id'))==a.get('component_id')]
                status='orphaned'
                if len(refs)==1 and isinstance(refs[0].get('caption'),str):
                    caption=refs[0]['caption'];quote=a.get('quote');status='anchored'
                    if a.get('component_ref_sha256') and digest(refs[0])!=a['component_ref_sha256']:status='text_changed'
                    if not isinstance(quote,str) or quote not in caption:status='text_changed'
                    if 'start' in a or 'end' in a:
                        start,end=a.get('start'),a.get('end')
                        if not(type(start) is int and type(end) is int and 0<=start<end<=len(caption) and caption[start:end]==quote):status='text_changed'
                c.execute('UPDATE annotations SET status=? WHERE id=?',(status,row['id']));continue
            if a.get('kind')=='manuscript_range':
                from .manuscript_range import validate_range
                try:
                    validate_range(obj['content'].get('blocks',[]),a);status='anchored'
                except Problem:
                    ids={b.get('id') for b in obj['content'].get('blocks',[])}
                    status='orphaned' if any(segment.get('block_id') not in ids for segment in a.get('segments',[]) if isinstance(segment,dict)) else 'text_changed'
                c.execute('UPDATE annotations SET status=? WHERE id=?',(status,row['id']));continue
            key = a.get("block_id") or a.get("node_id") or a.get("object_id")
            status = "anchored" if not key or key in elements else "orphaned"
            if key in elements and a.get("quote") and a["quote"] not in str(elements[key].get("text", "")):
                status = "text_changed"
            if key in elements and ('start' in a or 'end' in a):
                text=elements[key].get('text','');start,end=a.get('start'),a.get('end')
                if not (isinstance(text,str) and type(start) is int and type(end) is int and 0<=start<end<=len(text) and text[start:end]==a.get('quote')):
                    status='text_changed'
            c.execute("UPDATE annotations SET status=? WHERE id=?", (status, row["id"]))

    def annotations(self, ident):
        with self.connect() as c:
            return [self.unpack(r) for r in c.execute("SELECT * FROM annotations WHERE object_id=? ORDER BY created_at", (ident,))]

    def record_review(self, ident, revision, review, *, parent_fence=None, connection=None):
        with (self.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            if parent_fence:
                from .cycle import assert_parent
                parent,_=assert_parent(self,c,parent_fence['id'],parent_fence['epoch'])
                self.assert_material_access(c,parent['payload'])
            source=self.get(ident,revision,c)
            key='reviews:'+ident+':'+str(revision)
            record={**review,'object_id':ident,'revision':revision,'source_sha256':digest(source),'scientific_approval':False,'user_acceptance':False}
            identity=digest(record)
            row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
            records=json.loads(row[0]) if row else []
            existing=next((r for r in records if r['identity']==identity),None)
            if existing:return existing
            record={**record,'identity':identity,'recorded_at':now()}
            records.append(record)
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,encoded(records)))
            self.event(c,'review.recorded',ident,record,'coordinator')
            return record

    def review_records(self, ident, revision):
        return self.setting('reviews:'+ident+':'+str(revision),[])

    def relate(self, src, dst, relation, status="candidate", metadata=None, target_revision=None, task_id=None, execution_token=None):
        require(src != dst, "不能创建自引用")
        require(relation in {"contains", "uses", "produces", "cites", "supports", "limits", "studies", "related", "depends_on"}, "关系类型不支持")
        require(status in {"candidate", "confirmed"}, "关系状态不支持")
        with self.transaction() as c:
            if task_id:self.assert_execution(c,task_id,execution_token)
            a, b = self.get(src, connection=c), self.get(dst, connection=c)
            if a["project_id"] and b["project_id"] and a["project_id"] != b["project_id"]:
                grants = b["metadata"].get("shared_with", [])
                require(a["project_id"] in grants, "未授权跨项目引用此成果", "forbidden", 403)
            existing = c.execute("SELECT id,target_revision,metadata FROM relations WHERE src=? AND dst=? AND type=?", (src, dst, relation)).fetchone()
            if existing and json.loads(existing['metadata']).get('graph_revision'):
                # Graph decisions are revisioned by graph_growth; routine uses /
                # produces bookkeeping must not overwrite a human withdrawal.
                from .graph_growth import _relation
                return _relation(self,c,existing['id'])
            rid = existing[0] if existing else uid("REL")
            adopted = target_revision or (metadata or {}).get('adopted_revision') or b['revision']
            self.get(dst,adopted,c)
            c.execute("INSERT INTO relations VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(src,dst,type) DO UPDATE SET status=excluded.status,metadata=excluded.metadata", (rid, src, dst, relation, status, a["revision"], adopted, encoded(metadata or {})))
            if existing and (target_revision is not None or (metadata or {}).get('adopted_revision') is not None):
                c.execute('UPDATE relations SET target_revision=?,source_revision=? WHERE id=?',(adopted,a['revision'],rid))
            self.event(c, "relation.saved", src, {"id": rid, "dst": dst, "type": relation,'requested_target_revision':target_revision,'previous_target_revision':existing['target_revision'] if existing else None})
        return next(r for r in self.relations() if r["id"] == rid)

    def relations(self, ident=None):
        with self.connect() as c:
            rows = c.execute("SELECT * FROM relations WHERE (? IS NULL OR src=? OR dst=?)", (ident, ident, ident)).fetchall()
            result = []
            for r in rows:
                v = self.unpack(r)
                current = self.get(v["dst"], connection=c)
                v["update_available"] = current["revision"] != v["target_revision"]
                v["current_target_revision"] = current["revision"]
                result.append(v)
            return result

    def accept_dependency(self, relation_id, expected_target, accept=True, expected_relation_revision=None, expected_source_revision=None):
        with self.transaction() as c:
            row = c.execute("SELECT * FROM relations WHERE id=?", (relation_id,)).fetchone()
            require(row, "引用不存在", "not_found", 404)
            current = self.get(row["dst"], connection=c)
            require(type(expected_target) is int and current["revision"] == expected_target, "源组件又已更新", "conflict", 409)
            metadata = json.loads(row["metadata"])
            source=self.get(row['src'],connection=c)
            from .graph_growth import _relation
            graph_before=_relation(self,c,relation_id)
            if metadata.get('graph_revision'):
                require(type(expected_relation_revision) is int and expected_relation_revision==graph_before['revision'],
                        '关系已改变或缺少已读关系版本；请重新比较后采用', 'conflict',409,{'relation_id':relation_id,'current_relation_revision':graph_before['revision']})
                require(type(expected_source_revision) is int and expected_source_revision==source['revision'],
                        '引用成果已改变或缺少已读版本；未改动正文', 'conflict',409,{'source_id':source['id'],'current_source_revision':source['revision']})
            elif expected_source_revision is not None:
                require(type(expected_source_revision) is int and expected_source_revision==source['revision'],'引用成果已改变；未改动正文','conflict',409)
            metadata['graph_revision']=graph_before['revision']+1
            from .compatibility import require_features
            require_features(c,['graph_proposal_v1'])
            owner=source['id'] if source['kind']=='project' else source['project_id']
            self.assert_source_access(c,owner,current['id'])
            metadata["decision"] = {"at": now(), "action": "accept" if accept else "retain", "observed_revision": expected_target}
            if accept:
                metadata['adopted_revision']=expected_target
                anchors={field:{item.get('id') for item in current['content'].get(collection,[]) if isinstance(item,dict) and isinstance(item.get('id'),str)}
                         for field,collection in [('block_id','blocks'),('node_id','nodes'),('edge_id','edges'),('page_id','pages')]}
                def validate_anchors(reference,path):
                    # A revision upgrade cannot invent a correspondence between
                    # stable scientific elements. An omitted/renamed anchor is
                    # an explicit user decision, never approximate matching.
                    containers=[(reference,path)]
                    if isinstance(reference.get('anchor'),dict):containers.append((reference['anchor'],path+'.anchor'))
                    for container,location in containers:
                        for field,available in anchors.items():
                            if field not in container:continue
                            value=container[field]
                            require(isinstance(value,str) and value in available,
                                    '新版来源缺少原引用锚点；未采用。请保留旧版或明确重新指定引用，不能自动替换段落',
                                    'dependency_anchor_required',409,{'source_id':current['id'],'target_revision':expected_target,
                                        'retained_revision':row['target_revision'],'path':location+'.'+field,'anchor':{field:value}})
                def update_refs(value,path):
                    if isinstance(value,dict):
                        value={k:update_refs(v,path+'.'+str(k)) for k,v in value.items()}
                        rewritten=False
                        if value.get('id')==row['dst'] and 'revision' in value:value['revision']=expected_target;rewritten=True
                        if value.get('object_id')==row['dst'] and 'revision' in value:value['revision']=expected_target;rewritten=True
                        if value.get('component_id')==row['dst']:
                            rewritten=True
                            validate_anchors(value,path)
                            if value.get('type')=='image' and value.get('asset'):
                                old_asset=c.execute('SELECT filename,media_type FROM assets WHERE sha=?',(value['asset'],)).fetchone()
                                exported=c.execute('SELECT value FROM kv WHERE key=?',('exports:'+row['dst']+':'+str(expected_target),)).fetchone()
                                exports={}
                                for record in json.loads(exported[0]) if exported else []:
                                    if record['result'].get('provenance',{}).get('source_sha256')==digest(current):exports.update(record['result'].get('assets',{}))
                                require(old_asset and exports,'请先导出当前源图，再接纳到画布；保留原图和版本','dependency_render_required',409)
                                candidates=[a for a in exports.values() if a.get('filename')==old_asset['filename']]
                                if not candidates:candidates=[a for a in exports.values() if a.get('media_type')==old_asset['media_type']]
                                require(len(candidates)==1,'当前源图没有唯一对应格式；请先导出相同格式','dependency_render_required',409)
                                value['asset']=candidates[0]['sha']
                            value['component_revision']=expected_target
                        if rewritten:validate_anchors(value,path)
                    elif isinstance(value,list):value=[update_refs(v,path+'.'+str(index)) for index,v in enumerate(value)]
                    return value
                content=update_refs(source['content'],'consumer.content')
                self.assert_reference_access(c,owner,content)
                # Current evidence identity changes; historical provenance and
                # old graph-history snapshots retain their original revisions.
                for field in ('source_ref','source_refs'):
                    if field in metadata:metadata[field]=update_refs(metadata[field],'relation.metadata.'+field)
                if content!=source['content']:
                    source={**source,'content':content,'revision':source['revision']+1,'updated_at':now()}
                    c.execute('UPDATE objects SET content=?,revision=?,updated_at=? WHERE id=?',(encoded(content),source['revision'],source['updated_at'],source['id']))
                    self.snapshot(c,source,'user','adopt dependency:'+row['dst'])
                    self._anchors(c,source)
                    self.invalidate_control(c,source)
                c.execute('UPDATE relations SET source_revision=? WHERE id=?',(source['revision'],relation_id))
            c.execute("UPDATE relations SET target_revision=?,metadata=? WHERE id=?", (expected_target if accept else row["target_revision"], encoded(metadata), relation_id))
            metadata['adopted_revision']=expected_target if accept else row['target_revision']
            c.execute('UPDATE relations SET metadata=? WHERE id=?',(encoded(metadata),relation_id))
            if graph_before:
                from .graph_growth import _history,_relation
                _history(self,c,_relation(self,c,relation_id),graph_before,'dependency '+('accept' if accept else 'retain'))
            self.event(c, "dependency.decision", row["src"], metadata["decision"])
        return self.relations(row["src"])

    def add_asset(self, data, filename, media_type="application/octet-stream", metadata=None, task_id=None, execution_token=None, connection=None):
        sha = hashlib.sha256(data).hexdigest()
        path = self.blobs / sha
        with (self.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            require(isinstance(c, _StoreConnection) and c.asset_store == self.db and c.in_transaction and c.new_asset_files is not None,
                    "资产写入需要本工作区的托管写事务", "asset_transaction", 409)
            if task_id:self.assert_execution(c,task_id,execution_token)
            old=c.execute('SELECT metadata FROM assets WHERE sha=?',(sha,)).fetchone()
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                self._verify_asset_blob(sha, len(data))
            else:
                with os.fdopen(fd, "wb") as f:
                    created = os.fstat(f.fileno())
                    # Repairing an already registered asset must survive rollback.
                    # Existing files (including crash residue) are never ours to delete.
                    if old is None:
                        c.new_asset_files.append((path, created.st_dev, created.st_ino))
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
            meta=dict(metadata or {})
            projects=set(meta.get('projects',[])) | ({meta['project_id']} if meta.get('project_id') else set())
            if old:
                previous=json.loads(old[0]);projects.update(previous.get('projects',[]))
                if previous.get('project_id'):projects.add(previous['project_id'])
                meta={**previous,'projects':sorted(projects)}
                c.execute('UPDATE assets SET metadata=? WHERE sha=?',(encoded(meta),sha))
            else:
                meta['projects']=sorted(projects)
                c.execute("INSERT INTO assets VALUES(?,?,?,?,?,?)", (sha, Path(filename).name, media_type, encoded(meta), len(data), now()))
            result = self.asset(sha,c)
        return result

    @staticmethod
    def _file_identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def _verify_asset_blob(self, sha, size, check=None):
        """Full strong verification with bounded memory; this is not a hash cache."""
        path = self.blobs / sha
        directory = None
        try:
            directory = os.open(self.blobs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            fd = os.open(sha, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        except FileNotFoundError as error:
            if directory is not None: os.close(directory)
            raise Problem("资产文件缺失", "missing_asset", 409) from error
        except OSError as error:
            if directory is not None: os.close(directory)
            raise Problem("资产文件不能安全读取", "integrity", 409) from error
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_size == size,
                    "资产大小或文件类型不同", "integrity", 409)
            hasher, count = hashlib.sha256(), 0
            while True:
                if check: check()
                block = os.read(fd, 1024 * 1024)
                if not block: break
                count += len(block)
                require(count <= size, "资产在读取期间增长", "integrity", 409)
                hasher.update(block)
            after = os.fstat(fd)
            current = os.stat(sha, dir_fd=directory, follow_symlinks=False)
            parent, actual_parent = self.blobs.lstat(), os.fstat(directory)
            require(self._file_identity(before) == self._file_identity(after)
                    and self._file_identity(current) == self._file_identity(after)
                    and stat.S_ISDIR(parent.st_mode)
                    and (parent.st_dev, parent.st_ino) == (actual_parent.st_dev, actual_parent.st_ino)
                    and count == size and hasher.hexdigest() == sha,
                    "资产版本校验失败", "integrity", 409)
        except OSError as error:
            raise Problem("资产在读取期间改变或不可读取", "integrity", 409) from error
        finally:
            os.close(fd)
            os.close(directory)

    def add_asset_file(self, source_fd, filename, media_type="application/octet-stream", metadata=None,
                       task_id=None, execution_token=None, connection=None, *, expected_sha256,
                       expected_size, check=None):
        """Copy an already-authorized read-only FD; no path/import authority is granted.

        The caller pins source identity and authorizes project access before entry.
        pread preserves the caller's position. Publication remains inside the same
        managed transaction and ownership rules as byte-sized assets.
        """
        require(isinstance(expected_sha256, str) and len(expected_sha256) == 64
                and all(x in '0123456789abcdef' for x in expected_sha256), "资产标识不合法")
        require(type(expected_size) is int and expected_size >= 0, "资产大小无效")
        require(type(source_fd) is int and source_fd >= 0, "需要已授权的只读文件描述符")
        require(hasattr(os, 'pread'), "此平台的流式文件入口未就绪", "unsupported_runtime", 422)
        import fcntl
        require(fcntl.fcntl(source_fd, fcntl.F_GETFL) & os.O_ACCMODE == os.O_RDONLY,
                "来源必须以只读方式打开", "source_unreadable", 422)
        before = os.fstat(source_fd)
        require(stat.S_ISREG(before.st_mode) and before.st_size == expected_size,
                "来源类型或大小与声明不同", "input_integrity", 409)
        sha = expected_sha256
        path = self.blobs / sha
        with (self.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            require(isinstance(c, _StoreConnection) and c.asset_store == self.db and c.in_transaction
                    and c.new_asset_files is not None,
                    "资产写入需要本工作区的托管写事务", "asset_transaction", 409)
            if task_id: self.assert_execution(c, task_id, execution_token)
            if check: check()
            require(stat.S_ISDIR(self.blobs.lstat().st_mode),
                    "资产目录不能是链接", "integrity", 409)
            old = c.execute('SELECT metadata FROM assets WHERE sha=?', (sha,)).fetchone()
            fd, temporary = tempfile.mkstemp(prefix='.asset-stage-', dir=self.blobs)
            temporary = Path(temporary)
            try:
                with os.fdopen(fd, 'wb') as output:
                    hasher = hashlib.sha256()
                    offset = 0
                    while offset < expected_size:
                        if check: check()
                        block = os.pread(source_fd, min(1024 * 1024, expected_size - offset), offset)
                        require(block, "来源读取提前结束", "input_integrity", 409)
                        output.write(block)
                        hasher.update(block)
                        offset += len(block)
                    require(self._file_identity(before) == self._file_identity(os.fstat(source_fd))
                            and hasher.hexdigest() == sha,
                            "来源身份或字节改变；未登记资产", "input_integrity", 409)
                    output.flush()
                    os.fsync(output.fileno())
                if check: check()
                if task_id: self.assert_execution(c, task_id, execution_token)
                # A callback may observe revocation or a source write after EOF.
                require(self._file_identity(before) == self._file_identity(os.fstat(source_fd)),
                        "来源在发布前改变", "input_integrity", 409)
                try:
                    os.link(temporary, path)
                except FileExistsError:
                    self._verify_asset_blob(sha, expected_size, check)
                else:
                    created = path.lstat()
                    if old is None:
                        c.new_asset_files.append((path, created.st_dev, created.st_ino))
                    directory = os.open(self.blobs, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                    try: os.fsync(directory)
                    finally: os.close(directory)
                meta = dict(metadata or {})
                projects = set(meta.get('projects', [])) | ({meta['project_id']} if meta.get('project_id') else set())
                if old:
                    previous = json.loads(old[0]); projects.update(previous.get('projects', []))
                    if previous.get('project_id'): projects.add(previous['project_id'])
                    meta = {**previous, 'projects': sorted(projects)}
                    c.execute('UPDATE assets SET metadata=? WHERE sha=?', (encoded(meta), sha))
                else:
                    meta['projects'] = sorted(projects)
                    c.execute('INSERT INTO assets VALUES(?,?,?,?,?,?)',
                              (sha, Path(filename).name, media_type, encoded(meta), expected_size, now()))
                if check: check()
                result = self.asset(sha, c, check=check)
                require(self._file_identity(before) == self._file_identity(os.fstat(source_fd)),
                        "来源在登记期间改变；未采用资产", "input_integrity", 409)
            finally:
                temporary.unlink(missing_ok=True)
        return result

    def asset(self, sha, connection=None, *, check=None):
        require(isinstance(sha, str) and len(sha) == 64 and all(x in "0123456789abcdef" for x in sha), "资产标识不合法")
        with (self.connect() if connection is None else contextlib.nullcontext(connection)) as c:
            row = c.execute("SELECT * FROM assets WHERE sha=?", (sha,)).fetchone()
            require(row, "资产不存在", "not_found", 404)
        result = self.unpack(row)
        self._verify_asset_blob(sha, result['size'], check)
        result["url"] = "/api/assets/" + sha
        return result

    def setting(self, key, default=None):
        with self.connect() as c:
            row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def export_records(self, ident, revision=None):
        with self.connect() as c:
            rows=c.execute("SELECT value FROM kv WHERE key LIKE ? ORDER BY key",('exports:'+ident+':%',)).fetchall()
        records=[r for row in rows for r in json.loads(row[0])]
        return sorted([r for r in records if revision is None or r['revision']==revision],key=lambda r:r['created_at'])

    def record_export(self, ident, revision, result, connection=None):
        if connection is not None:
            require(isinstance(connection, _StoreConnection) and connection.asset_store == self.db and connection.in_transaction
                    and connection.new_asset_files is not None, "导出登记需要本工作区托管事务", "asset_transaction", 409)
        with (self.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            source=self.get(ident,revision,connection=c);proof=result.get('provenance',{})
            from .generation_validity import ensure_deliverable
            ensure_deliverable(self,source,connection=c)
            require(proof.get('object_id')==ident and proof.get('revision')==revision and proof.get('source_sha256')==digest(source),'导出来源与采用修订不一致','integrity',409)
            key='exports:'+ident+':'+str(revision)
            row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone();records=json.loads(row[0]) if row else []
            record={'revision':revision,'result':result,'created_at':now()};records.append(record)
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,encoded(records)))
            self._anchors(c, self.get(ident, connection=c))
            self.event(c,'export.created',ident,{'revision':revision,'asset_sha':result['asset']['sha'],'source_sha256':digest(source)},'renderer')
        return record

    def set_setting(self, key, value, task_id=None, execution_token=None):
        with self.transaction() as c:
            if key.startswith('budget_extension:'):
                row=c.execute('SELECT payload FROM tasks WHERE id=?',(key.removeprefix('budget_extension:'),)).fetchone()
                payload=json.loads(row[0]) if row else {}
                require(payload.get('kind')!='research_cycle' and not payload.get('cycle_parent'),'协作额度由父级有限预分配管理；不能从普通任务入口单独扩额','authorization_required',403)
            if task_id or execution_token is not None:self.assert_execution(c,task_id,execution_token)
            c.execute("INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, encoded(value)))

    def submit(self, payload, request_key, *, parent_fence=None, connection=None, initial_result=None, preflight=None):
        require(isinstance(request_key, str) and request_key.strip(), "任务需要稳定请求标识")
        fingerprint = digest(payload)
        with (self.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
            if parent_fence:
                from .cycle import assert_parent
                assert_parent(self,c,parent_fence['id'],parent_fence['epoch'])
            row = c.execute("SELECT * FROM tasks WHERE request_key=?", (request_key,)).fetchone()
            if row:
                require(row["payload_digest"] == fingerprint, "重复请求内容不同", "idempotency_conflict", 409)
                return self.unpack(row)
            if preflight:preflight(c)
            tid, t = uid("TASK"), now()
            c.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)", (tid, request_key, fingerprint, payload.get("project_id"), "queued", encoded(payload), encoded(initial_result or {}), None, 0, t, t))
            self.event(c, "task.queued", tid, {"kind": payload.get("kind"), "request_key": request_key})
            return self.unpack(c.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone())

    def task(self, ident, connection=None):
        with (self.connect() if connection is None else contextlib.nullcontext(connection)) as c:
            row = c.execute("SELECT * FROM tasks WHERE id=?", (ident,)).fetchone()
            require(row, "任务不存在", "not_found", 404)
            result = self.unpack(row)
            acquisition=c.execute("SELECT value FROM kv WHERE key=?",("acquisition:"+result["payload"].get("acquisition_parent",ident),)).fetchone()
            if acquisition:result["acquisition"]={k:v for k,v in json.loads(acquisition[0]).items() if k!="execution_token"}
            result["steps"] = [self.unpack(r) for r in c.execute("SELECT * FROM steps WHERE task_id=? ORDER BY updated_at", (ident,))]
            return result

    def tasks(self):
        with self.connect() as c:
            return [self.unpack(r) for r in c.execute("SELECT * FROM tasks ORDER BY created_at DESC")]

    def task_update(self, ident, status, result=None, error=None, attempts=None, execution_token=None):
        allowed = {"queued", "running", "waiting_input", "waiting_authorization", "waiting_resource", "paused", "cancelled", "failed", "generated", "review", "deliverable"}
        require(status in allowed, "未知任务状态")
        with self.transaction() as c:
            if execution_token is not None:self.assert_execution(c,ident,execution_token)
            row = c.execute("SELECT * FROM tasks WHERE id=?", (ident,)).fetchone()
            require(row, "任务不存在", "not_found", 404)
            require(row['status']!='cancelled' or status=='cancelled','已取消任务不能被晚到返回复活','cancelled',409)
            require(row['status']!='paused' or status in {'paused','queued','cancelled'},'暂停期间不能提交晚到结果','cancelled',409)
            c.execute("UPDATE tasks SET status=?,result=?,error=?,attempts=?,updated_at=? WHERE id=?", (status, encoded(result if result is not None else json.loads(row["result"])), error, row["attempts"] if attempts is None else attempts, now(), ident))
            self.event(c, "task." + status, ident, {"error": error}, "runtime")
        return self.task(ident)

    def step(self, task_id, key, status, data, execution_token=None):
        with self.transaction() as c:
            if execution_token is not None:self.assert_execution(c,task_id,execution_token)
            if execution_token is not None and key.startswith('cycle_candidate:'):
                row=c.execute('SELECT project_id FROM tasks WHERE id=?',(task_id,)).fetchone()
                self.assert_reference_access(c,row[0],data)
            c.execute("INSERT INTO steps VALUES(?,?,?,?,?) ON CONFLICT(task_id,step_key) DO UPDATE SET status=excluded.status,data=excluded.data,updated_at=excluded.updated_at", (task_id, key, status, encoded(data), now()))
            self.event(c, "step." + status, task_id, {"step_key": key}, "runtime")
