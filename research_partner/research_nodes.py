"""Named QAEC state and version-bound dependencies on existing question revisions.

No task engine or graph database: content, decisions and links share Store snapshots.
"""
from __future__ import annotations
import copy
import json
from graphlib import TopologicalSorter, CycleError
from .store import digest, encoded, require, now
from .workbench_research import ROLE, create_question
from .desk_w1a import _project

PARTS = ('Q', 'A', 'E', 'C')
STATUSES = {'unmarked', 'not_started', 'active', 'review', 'completed', 'paused'}
KINDS = {'requires', 'supports', 'limits', 'refutes'}
FEATURE = 'research_node_states_v1'
KEY = 'research_nodes:'


def questions(app, project_id, c):
    return [app.store.unpack(row) for row in c.execute(
        "SELECT * FROM objects WHERE project_id=? AND archived=0 AND json_extract(metadata,'$.research_role')=?", (project_id, ROLE))]


def config(q, part):
    values = q['metadata'].get('research_nodes', {})
    value = values.get(part, {}) if isinstance(values, dict) else {}
    return value if isinstance(value, dict) else {}


def identity(qid, part):
    return qid + ':' + part


def content_sha(q, part):
    return digest({'question_scope':{'title':q['title'],'Q':q['content'].get('qaec', {}).get('Q','')}, 'text': q['content'].get('qaec', {}).get(part, ''),
                   'title': q['title'] if part == 'Q' else config(q, part).get('title', '')})


def dependencies(q, part, custom=None):
    # Q completion requires a confirmed C; C confirmation requires checked evidence.
    builtin = ([{'question_id': q['id'], 'part': 'C', 'kind': 'requires', 'builtin': True}] if part == 'Q' else
               [{'question_id': q['id'], 'part': 'E', 'kind': 'requires', 'builtin': True}] if part == 'C' else [])
    items = config(q, part).get('dependencies', []) if custom is None else custom
    if not isinstance(items, list): items = [None]
    normalized = [d if isinstance(d,dict) and isinstance(d.get('question_id'),str) and d.get('part') in PARTS and isinstance(d.get('kind'),str) and d['kind'] in KINDS else {'question_id':'unavailable','part':'Q','kind':'requires'} for d in items]
    return builtin + [{**d, 'builtin': False} for d in normalized]


def project_states(items, store=None, connection=None):
    """Pure projection. Missing/archived sources block; changes invalidate pins transitively."""
    by_id = {q['id']: q for q in items}
    records = {identity(q['id'], p): (q, p) for q in items for p in PARTS}
    links = {key: dependencies(q, part) for key, (q, part) in records.items()}
    graph = {key: [identity(d['question_id'], d['part']) for d in ds] for key, ds in links.items()}
    try:
        order = list(TopologicalSorter(graph).static_order())
    except CycleError:
        # Imported malformed metadata cannot hide the project or attest completion.
        order = list(records)
        cyclic = True
    else:
        cyclic = False
    result = {}
    for key in order:
        if key not in records: continue
        q, part = records[key]; value = config(q, part)
        state = value.get('status')
        if not isinstance(state, str) or state not in STATUSES:
            state = ({'open':'not_started','active':'active','review':'review','answered':'review'}.get(q['content'].get('research_status'), 'unmarked') if part=='Q' else 'not_started' if not q['content'].get('qaec', {}).get(part, '').strip() else 'unmarked')
        ds = []
        for d in links[key]:
            source_key = identity(d['question_id'], d['part']); source = result.get(source_key)
            available = source_key in records and not cyclic
            source_q = by_id.get(d['question_id'])
            ds.append({**d, 'id': source_key, 'available': available,
                       'title': source['title'] if source else '依赖节点不可用',
                       'status': source['status'] if source else 'blocked',
                       'signature': source['signature'] if source else 'unavailable',
                       'question_revision': source_q['revision'] if available else None})
        blockers = [d for d in ds if not d['available'] or d['status'] != 'completed']
        pins = [{'id': d['id'], 'signature': d['signature'], 'kind':d['kind']} for d in ds]
        confirmation = value.get('confirmation')
        if not isinstance(confirmation, dict): confirmation = None
        authentic, changed_since = False, False
        if confirmation and store is not None:
            row = connection.execute('SELECT value FROM kv WHERE key=?', (KEY+str(confirmation.get('id')),)).fetchone()
            saved = json.loads(row[0]).get('result',{}).get('question',{}) if row else {}
            authentic = saved.get('id') == q['id'] and config(saved,part).get('confirmation') == confirmation
            revision = confirmation.get('question_revision')
            if type(revision) is int and 0 < revision <= q['revision']:
                # Restoring identical old text is a new version, not a resurrection of approval.
                for row in connection.execute('SELECT snapshot FROM revisions WHERE object_id=? AND revision>? ORDER BY revision DESC', (q['id'],revision)):
                    if content_sha(json.loads(row[0]),part) != confirmation.get('content_sha256'):
                        changed_since = True; break
            else: changed_since = True
        stale = state == 'completed' and (not confirmation or confirmation.get('content_sha256') != content_sha(q, part)
                    or confirmation.get('dependencies') != pins or store is not None and (not authentic or changed_since))
        effective = 'stale' if stale else 'blocked' if blockers and state == 'completed' else state
        # Expose blocked readiness without erasing the person's active/paused progress.
        flags = (['stale'] if stale else []) + (['blocked'] if blockers else [])
        signature = digest({'content': content_sha(q, part), 'status': effective,
                            'confirmation': confirmation.get('id') if confirmation else None, 'dependencies': pins})
        result[key] = {'id': key, 'question_id': q['id'], 'part': part,
            'title': q['title'] if part == 'Q' else value.get('title', ''),
            'status': effective, 'stored_status': state, 'flags': flags,
            'configured': bool(value), 'content_sha256': content_sha(q, part), 'signature': signature,
            'dependencies': ds, 'blockers': [d['id'] for d in blockers],
            'confirmation': confirmation, 'can_complete': not blockers and bool(q['content'].get('qaec', {}).get(part, '').strip())
                              and bool(q['title'] if part == 'Q' else value.get('title', ''))}
    return result


def _validate_dependencies(q, part, items, objects):
    require(isinstance(items, list) and len(items) <= 24, '单个节点最多关联24项依赖')
    by_id = {o['id']: o for o in objects}; seen = set()
    builtin = {(d['question_id'], d['part']) for d in dependencies(q, part, [])}
    for d in items:
        require(isinstance(d, dict) and set(d) == {'question_id', 'part', 'kind'}, '依赖需要问题、节点类型与关系')
        require(isinstance(d['question_id'], str) and d['part'] in PARTS and isinstance(d['kind'], str) and d['kind'] in KINDS, '依赖节点或关系无效')
        target = by_id.get(d['question_id'])
        require(target is not None, '依赖不属于当前项目或已归档', 'forbidden', 403)
        pair = (d['question_id'], d['part'])
        require(pair != (q['id'], part) and pair not in seen and pair not in builtin, '依赖不能自引用或重复')
        seen.add(pair)
    pending = copy.deepcopy(objects)
    for o in pending:
        if o['id'] == q['id']:
            o['metadata'].setdefault('research_nodes', {}).setdefault(part, {})['dependencies'] = items
    graph = {identity(o['id'], p): [identity(d['question_id'], d['part']) for d in dependencies(o, p)] for o in pending for p in PARTS}
    try: list(TopologicalSorter(graph).static_order())
    except CycleError: require(False, '依赖会形成循环；组织关系无需设为完成依赖', 'dependency_cycle', 409)


def dispatch(app, data, scope=None, principal=None):
    action = data.get('action')
    allowed = ({'action', 'project_id', 'question_id', 'part', 'expected_revision', 'title', 'status', 'dependencies',
                'expected_dependencies', 'confirmation_note', 'answers_question', 'request_key'} if action == 'workbench.node.save' else
               {'action', 'project_id', 'expected_project_revision', 'question_id', 'title', 'attach_roots', 'expected_roots', 'request_key'})
    require(action in {'workbench.node.save', 'workbench.root.set'} and set(data) <= allowed, '研究节点操作或字段不支持')
    project = _project(app, data.get('project_id'), scope, principal, True)
    key = data.get('request_key'); require(isinstance(key, str) and 0 < len(key) <= 180, '需要稳定请求标识')
    fingerprint = digest({'request': data, 'scope': sorted(scope) if scope is not None else None, 'principal': principal})
    with app.store.transaction() as c:
        _project(app, project['id'], scope, principal, True)
        row = c.execute('SELECT value FROM kv WHERE key=?', (KEY + key,)).fetchone()
        if row:
            prior = json.loads(row[0]); require(prior['fingerprint'] == fingerprint, '同一请求内容已改变', 'idempotency_conflict', 409)
            return {**prior['result'], 'replayed': True}
        from .project_management import actor
        from .compatibility import require_features
        who = actor(principal or {'kind': 'local_operator'})
        project = app.store.get(project['id'], connection=c); objects = questions(app, project['id'], c)
        active_ids = {o['id'] for o in objects}
        def top(o): return o['metadata'].get('parent_question_id') not in active_ids
        if action == 'workbench.root.set':
            require(type(data.get('expected_project_revision')) is int and data['expected_project_revision'] == project['revision'], '项目已更新，请重新核对根问题', 'conflict', 409)
            existing = project['metadata'].get('research_root_question_id')
            existing = existing if any(o['id']==existing for o in objects) else None
            q = next((o for o in objects if o['id'] == data.get('question_id')), None)
            if data.get('question_id'):
                require(q is not None and top(q), '根问题需要当前项目的顶层研究问题')
            else:
                require(not existing, '已经有文章根问题，请直接编辑或选择已有顶层问题', 'conflict', 409)
                q = create_question(app.store, c, project['id'], data.get('title'), actor=who)
            require(not existing or existing == q['id'], '已有文章根问题，不能隐式替换其论证结构', 'conflict', 409)
            require(type(data.get('attach_roots', False)) is bool, '是否接入现有问题需要明确选择')
            if data.get('attach_roots'):
                roots = [o for o in objects if o['id'] != q['id'] and top(o)]
                expected = [{'id': o['id'], 'revision': o['revision']} for o in roots]
                require(isinstance(data.get('expected_roots'), list) and all(isinstance(x,dict) and set(x)=={'id','revision'} and isinstance(x['id'],str) and type(x['revision']) is int for x in data['expected_roots']) and sorted(data['expected_roots'], key=lambda x:x['id']) == sorted(expected, key=lambda x:x['id']), '顶层问题已有变化，请重新核对', 'conflict', 409)
                for o in roots:
                    app.store.save(o['id'], o['revision'], metadata={**o['metadata'], 'parent_question_id': q['id']}, actor=who, reason=action, merge=False, connection=c)
                    app.store.relate(q['id'], o['id'], 'contains', 'confirmed', connection=c)
            require(data.get('attach_roots') or not any(o['id']!=q['id'] and top(o) for o in objects), '请明确将现有顶层问题接入文章根问题')
            project = app.store.save(project['id'], project['revision'], metadata={**project['metadata'], 'research_root_question_id':q['id']}, actor=who, reason=action, merge=False, connection=c)
            result = {'project': project, 'question': q}
        else:
            q = next((o for o in objects if o['id'] == data.get('question_id')), None)
            require(q is not None, '研究节点不属于当前项目或已归档', 'forbidden', 403)
            part = data.get('part'); require(part in PARTS, '节点类型无效')
            require(type(data.get('expected_revision')) is int and data['expected_revision'] == q['revision'], '研究问题已更新，输入已保留；请核对新版配置', 'conflict', 409)
            title = data.get('title'); state = data.get('status')
            require(isinstance(title, str) and 0 < len(title.strip()) <= 500 and isinstance(state, str) and state in STATUSES, '需要具体标题与有效节点状态')
            require(part != 'Q' or title.strip() == q['title'], '问题标题请在研究正文中修改，以便核对问题范围')
            custom = data.get('dependencies', [])
            _validate_dependencies(q, part, custom, objects)
            metadata = copy.deepcopy(q['metadata']); record = metadata.setdefault('research_nodes', {}).setdefault(part, {})
            record.update(title=title.strip(), status=state, dependencies=copy.deepcopy(custom))
            prospective = {**q, 'metadata': metadata}
            states = project_states([prospective if o['id'] == q['id'] else o for o in objects], app.store, c); node = states[identity(q['id'], part)]
            if state == 'completed':
                note = data.get('confirmation_note')
                require(isinstance(note, str) and 0 < len(note.strip()) <= 4000, '完成前请说明核对依据；Q需要说明结论如何回答问题')
                require(part != 'Q' or data.get('answers_question') is True, '请明确确认：当前结论足以回答这个研究问题')
                pins = [{'id': d['id'], 'signature': d['signature'], 'kind':d['kind']} for d in node['dependencies']]
                require(data.get('expected_dependencies') == [{'id':d['id'],'signature':d['signature']} for d in pins], '依赖版本或状态已变化，请重新核对完成条件', 'dependency_conflict', 409)
                require(not node['blockers'], '完成条件尚未满足：先核对所依赖的节点', 'dependencies_unmet', 409, {'blockers':node['blockers']})
                require(bool(q['content'].get('qaec', {}).get(part, '').strip()), '这部分还没有保存内容，不能确认完成')
                record['confirmation'] = {'id':key, 'actor':who, 'at':now(), 'question_revision':q['revision'],
                    'content_sha256':content_sha(prospective, part), 'dependencies':pins, 'note':note.strip()}
            record['updated_by'] = who; record['updated_at'] = now()
            result_q = app.store.save(q['id'], q['revision'], metadata=metadata, actor=who, reason=action, merge=False, connection=c)
            result = {'question':result_q}
        require_features(c, [FEATURE])
        c.execute('INSERT INTO kv VALUES(?,?)', (KEY+key, encoded({'fingerprint':fingerprint, 'result':result})))
        return result
