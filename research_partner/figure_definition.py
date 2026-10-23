"""File-authoritative main figures with fixed, already rendered panel references.

The definition is UTF-8 JSON (a YAML 1.2 subset) in main/figure.yaml. Store
revisions are immutable projections of its exact bytes. This adapter never
executes a panel, deletes its source, or silently follows a newer revision.
"""
import contextlib
import copy
import fcntl
import json
import math
import os
import re
import stat
import uuid

from .notebook import _open_dir, _parent, _replace_at, _create_at
from .project_files import ProjectFiles
from .store import Problem, digest, encoded, require, uid

SCHEMA = 'research-partner-main-figure/1'
MAX_BYTES = 1024 * 1024


def canonical_geometry(data):
    """JSON numbers have no integer/float spelling identity for geometry.

    Preserve exact finite numeric values and every other field. No epsilon,
    rounding, source substitutions or permission changes are introduced.
    """
    value = copy.deepcopy(data)
    def number(raw):
        require(type(raw) in (int, float), '布局值必须是数值', 'invalid_arguments', 422)
        try: normalized = float(raw)
        except (ValueError, OverflowError) as error: raise Problem('布局值不可表示', 'invalid_arguments', 422) from error
        require(math.isfinite(normalized) and normalized == raw, '布局值必须有限且可精确表示', 'invalid_arguments', 422)
        return 0.0 if normalized == 0 else normalized
    for key in ('width', 'height'):
        if key in value: value[key] = number(value[key])
    if 'box' in value:
        require(isinstance(value['box'], list), '布局需要数值列表', 'invalid_arguments', 422)
        value['box'] = [number(x) for x in value['box']]
    if 'slots' in value:
        require(isinstance(value['slots'], list), '图位需要列表', 'invalid_arguments', 422)
        for slot in value['slots']:
            require(isinstance(slot, dict) and isinstance(slot.get('box'), list), '图位布局无效', 'invalid_arguments', 422)
            slot['box'] = [number(x) for x in slot['box']]
    return value


def is_definition(obj):
    return obj.get('kind') == 'figure' and obj.get('content', {}).get('definition_schema') == SCHEMA


def relative_path(ident):
    require(isinstance(ident, str) and re.fullmatch(r'ART-[a-f0-9]{16}', ident), '主图身份无效')
    return 'figures/' + ident + '/main/figure.yaml'


def _read(fd, name, absent=False):
    try:
        opened = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except FileNotFoundError:
        if absent: return None
        raise Problem('主图定义文件缺失；保留登记历史', 'definition_missing', 409)
    except OSError as error:
        raise Problem('定义文件不能是符号链接', 'invalid_path', 409) from error
    try:
        info = os.fstat(opened)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, '定义必须是普通文件且不能是硬链接', 'invalid_path', 409)
        require(info.st_size <= MAX_BYTES, '定义超过1MiB；原文件未修改', 'definition_limit', 413)
        with os.fdopen(opened, 'rb', closefd=False) as stream: return stream.read(MAX_BYTES + 1)
    finally: os.close(opened)


class FigureDefinitions:
    def __init__(self, store): self.store = store

    @contextlib.contextmanager
    def locked(self, project_id, *, recover=True):
        files = ProjectFiles(self.store)
        with files._locked(): root = files._root(self.store.get(project_id))
        opened = [os.open(self.store.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
        try:
            for part in root.relative_to(self.store.workspace).parts: opened.append(_open_dir(opened[-1], part))
            root_fd = opened[-1]; state = _open_dir(root_fd, '.figure-definitions', create=True); opened.append(state)
            lock = os.open('lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=state); opened.append(lock)
            info = os.fstat(lock)
            require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, '主图定义锁无效', 'invalid_path', 409)
            fcntl.flock(lock, fcntl.LOCK_EX)
            session = {'root': root_fd, 'project_id': project_id, 'path': root}
            for name in ('snapshots', 'pending', 'history'):
                session[name] = _open_dir(state, name, create=True); opened.append(session[name])
            if recover:
                self._recover(session)
            else:
                require(not os.listdir(session['pending']),
                        '主图有待恢复的写入；请先完成恢复再预览', 'definition_recovery_required', 409)
            yield session
        finally:
            for fd in reversed(opened): os.close(fd)

    def _raw(self, session, ident, absent=False):
        try:
            with _parent(session['root'], relative_path(ident).split('/')) as (fd, name): return _read(fd, name, absent)
        except Problem as error:
            if absent and error.code == 'not_found': return None
            raise

    def _snapshot(self, session, raw):
        sha = digest(raw); previous = _read(session['snapshots'], sha, True)
        if previous is None: _create_at(session['snapshots'], sha, raw)
        else: require(previous == raw, '主图历史字节摘要冲突', 'integrity', 409)
        return sha

    def _asset_bytes(self, sha):
        self.store.asset(sha)
        reader = getattr(self.store, 'staged_asset_bytes', None)
        raw = reader(sha) if reader else (self.store.blobs / sha).read_bytes()
        require(digest(raw) == sha, '子图资产字节不匹配', 'integrity', 409)
        return raw

    def resolve_source(self, project_id, value, owner=None):
        require(isinstance(value, dict) and set(value) == {'id', 'revision'} and type(value['revision']) is int and value['revision'] > 0, '请选择准确的已保存子图修订')
        source = self.store.get(value['id'], value['revision']); current = self.store.get(source['id'])
        require(source['kind'] == 'figure' and not source['content'].get('composition') and source['id'] != owner, '当前主图接入独立子图；不允许自引用或循环组成', 'invalid_component', 422)
        require(source['project_id'] == current['project_id'] == project_id, '子图必须来自当前可读项目', 'forbidden', 403)
        records = [r['result'] for r in self.store.export_records(source['id'], source['revision']) if r['result'].get('status') == 'generated' and r['result'].get('provenance', {}).get('source_sha256') == digest(source)]
        records = [r for r in records if 'figure.svg' in r.get('assets', {})]
        require(records, '该子图修订没有实际SVG输出；请先明确重绘，不自动执行', 'panel_render_required', 409)
        render = records[-1]; sha = render['assets']['figure.svg']['sha']; asset = self.store.asset(sha)
        require(asset['size'] <= 16 * 1024 * 1024 and digest(self._asset_bytes(sha)) == sha, '子图实际SVG字节不匹配', 'integrity', 409)
        numeric = render.get('assets', {}).get('numeric_values.json', {}).get('sha')
        return {'id': source['id'], 'revision': source['revision'], 'sha256': digest(source), 'svg_sha256': sha, 'numeric_sha256': numeric}

    def validate(self, value, project_id, ident):
        require(isinstance(value, dict) and set(value) <= {'schema', 'object_id', 'project_id', 'title', 'width', 'height', 'slots', 'extensions'}, '主图定义字段无效', 'invalid_definition', 422)
        require(value.get('schema') == SCHEMA and value.get('object_id') == ident and value.get('project_id') == project_id, '定义身份不能改变或移入其他项目', 'invalid_definition', 422)
        require(isinstance(value.get('title'), str) and 0 < len(value['title'].strip()) <= 200, '主图需要标题', 'invalid_definition', 422)
        for key in ('width', 'height'):
            require(type(value.get(key)) in (int, float) and math.isfinite(value[key]) and 32 <= value[key] <= 8192, '主图尺寸须为32..8192像素', 'invalid_definition', 422)
        slots = value.get('slots'); require(isinstance(slots, list) and 1 <= len(slots) <= 24, '主图需要1..24个固定图位', 'invalid_definition', 422)
        seen = set()
        for slot in slots:
            require(isinstance(slot, dict) and set(slot) == {'id', 'label', 'required', 'box', 'source'}, '图位字段无效', 'invalid_definition', 422)
            name = slot['id']; require(isinstance(name, str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name) and name not in seen, '图位身份重复或无效', 'invalid_definition', 422); seen.add(name)
            require(isinstance(slot['label'], str) and len(slot['label']) <= 200 and type(slot['required']) is bool, '图位标签或必需状态无效', 'invalid_definition', 422)
            box = slot['box']; require(isinstance(box, list) and len(box) == 4 and all(type(x) in (int, float) and math.isfinite(x) for x in box), '图位需要四个有限布局值', 'invalid_definition', 422)
            x, y, w, h = box; require(x >= 0 and y >= 0 and w > 0 and h > 0 and x + w <= 1 and y + h <= 1, '图位布局超出主图', 'invalid_definition', 422)
            if slot['source'] is not None:
                source = slot['source']; require(isinstance(source, dict) and {'id', 'revision'} <= set(source), '图位来源无效', 'invalid_definition', 422)
                actual = self.resolve_source(project_id, {k: source[k] for k in ('id', 'revision')}, ident)
                # Resolve the exact registered SVG among history, so redrawing
                # this same source revision cannot silently change the binding.
                require(set(source) == set(actual) and source['sha256'] == actual['sha256'], '图位来源身份不符', 'integrity', 409)
                matches = [r['result'] for r in self.store.export_records(source['id'], source['revision']) if r['result'].get('provenance', {}).get('source_sha256') == source['sha256'] and r['result'].get('assets', {}).get('figure.svg', {}).get('sha') == source['svg_sha256'] and r['result'].get('assets', {}).get('numeric_values.json', {}).get('sha') == source['numeric_sha256']]
                require(matches and digest(self._asset_bytes(source['svg_sha256'])) == source['svg_sha256'], '固定图位输出未登记或已损坏', 'integrity', 409)
        require(isinstance(value.get('extensions', {}), dict), '扩展字段必须是映射', 'invalid_definition', 422)
        return value

    def parse(self, raw, project_id, ident):
        try: value = json.loads(raw.decode('utf-8-sig'))
        except (ValueError, UnicodeError) as error: raise Problem('定义当前支持UTF-8 JSON形式的YAML；无效原文件保留，不转成旧投影', 'invalid_definition', 422) from error
        return self.validate(value, project_id, ident)

    def content(self, value, sha):
        items = []
        for slot in value['slots']:
            source = slot['source']
            if source is None: continue
            x, y, w, h = slot['box']
            items.append({'id': slot['id'], 'type': 'image', 'asset': source['svg_sha256'], 'source_ref': copy.deepcopy(source), 'x': x * value['width'], 'y': y * value['height'], 'width': w * value['width'], 'height': h * value['height'], 'group': slot['id']})
            if slot['label']:
                size = max(6, min(18, h * value['height'] * .06))
                items.append({'id': slot['id'] + ':label', 'type': 'text', 'text': slot['label'], 'x': x * value['width'], 'y': y * value['height'], 'width': w * value['width'], 'height': min(h * value['height'], size * 2), 'font_size': size, 'bold': True, 'z': 2, 'group': slot['id']})
        return {'composition': True, 'definition_schema': SCHEMA, 'definition_file': relative_path(value['object_id']), 'definition_sha256': sha, 'units': 'px', 'slots': copy.deepcopy(value['slots']), 'pages': [{'id': 'main', 'width': value['width'], 'height': value['height'], 'objects': items}]}

    def _register(self, session, ident, raw, reason, intent=None):
        value = self.parse(raw, session['project_id'], ident); sha = self._snapshot(session, raw); content = self.content(value, sha)
        with self.store.transaction() as c:
            if intent and intent.get('execution'):
                existing = c.execute('SELECT value FROM kv WHERE key=?', (intent['request_storage'],)).fetchone()
                if not existing or json.loads(existing[0]).get('definition_recovery_pending'):
                    from .figure_composition_task import fence_intent
                    fence_intent(self.store, c, intent)
            row = c.execute('SELECT * FROM objects WHERE id=?', (ident,)).fetchone()
            if row:
                obj = self.store.unpack(row)
                require(is_definition(obj) and obj['project_id'] == session['project_id'], '定义投影身份冲突', 'integrity', 409)
                if obj['content'].get('definition_sha256') != sha or obj['content'] != content: obj = self.store.save(ident, obj['revision'], content=content, title=value['title'], merge=False, reason=reason, actor='file_service', connection=c)
            else:
                require(intent and intent['operation'] == 'create' and intent['object_id'] == ident, '未登记定义不能自动新建成果', 'definition_unbound', 409)
                metadata = {'authority_kind': 'file', 'definition_format': 'json_yaml_subset'}
                if intent.get('execution'): metadata.update(origin_task_id=intent['execution']['task_id'], candidate=True)
                obj = self.store.create('figure', value['title'], session['project_id'], content, metadata, actor=intent['actor'], ident=ident, connection=c)
            if intent and sha == intent['after_sha256']:
                result = {'figure': obj, 'definition_path': relative_path(ident), 'definition_sha256': sha, 'executed': False}
                previous = c.execute('SELECT value FROM kv WHERE key=?', (intent['request_storage'],)).fetchone()
                if previous:
                    saved = json.loads(previous[0]); require(saved['fingerprint'] == intent['fingerprint'], '重复组成请求不同', 'idempotency_conflict', 409)
                    if saved.get('definition_recovery_pending'): c.execute('UPDATE kv SET value=? WHERE key=?', (encoded({'fingerprint': intent['fingerprint'], 'result': result}), intent['request_storage']))
                else: c.execute('INSERT INTO kv VALUES(?,?)', (intent['request_storage'], encoded({'fingerprint': intent['fingerprint'], 'result': result})))
                if intent.get('execution'):
                    ref = {'id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj), 'definition_sha256': sha, 'adopted_head_changed': False}
                    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('composition_task_candidate:' + intent['execution']['task_id'], encoded(ref)))
        return obj

    def _recover(self, session):
        names = os.listdir(session['pending']); require(len(names) <= 256, '主图恢复记录过多，请核查', 'definition_recovery', 409)
        for name in names:
            require(re.fullmatch(r'[a-f0-9]{32}\.json', name), '未知主图恢复记录', 'definition_recovery', 409)
            intent = json.loads(_read(session['pending'], name))
            if 'batch_protocol' in intent:
                from .figure_round_journal import recover
                recover(self, session, name, intent)
                continue
            ident = intent['object_id']
            require(intent['project_id'] == session['project_id'], '恢复记录跨项目', 'integrity', 409)
            raw = self._raw(session, ident, True)
            previous = self.store.setting(intent['request_storage'])
            if intent.get('execution') and (not previous or previous.get('definition_recovery_pending')):
                from .figure_composition_task import fence_intent
                try:
                    with self.store.connect() as c: fence_intent(self.store, c, intent)
                except Problem as error:
                    if error.code != 'cancelled': raise
                    self.store.set_setting(intent['request_storage'], {'fingerprint': intent['fingerprint'], 'cancelled_pending': True, 'result': {'object_id': ident, 'proposed_sha256': intent['after_sha256'], 'published': False}})
                    os.rename(name, name, src_dir_fd=session['pending'], dst_dir_fd=session['history']); os.fsync(session['pending']); os.fsync(session['history']); continue
            if raw is not None:
                actual = digest(raw)
                if actual == intent['after_sha256']:
                    if not self._recover_registration(session, intent, raw, 'recover published definition'): continue
                elif actual != intent['before_sha256']:
                    # Preserve proposed, previous and later external bytes; do
                    # not replay the interrupted write over an external editor.
                    self._snapshot(session, raw)
                    obj = self._recover_registration(session, intent, raw, 'external edit after interrupted definition')
                    if not obj: continue
                    previous = self.store.setting(intent['request_storage'])
                    if not previous or previous.get('definition_recovery_pending'): self.store.set_setting(intent['request_storage'], {'fingerprint': intent['fingerprint'], 'interrupted_external_conflict': True, 'result': {'figure': obj, 'proposed_sha256': intent['after_sha256'], 'current_sha256': actual}})
            os.rename(name, name, src_dir_fd=session['pending'], dst_dir_fd=session['history']); os.fsync(session['pending']); os.fsync(session['history'])

    def _recover_registration(self, session, intent, raw, reason):
        try: return self._register(session, intent['object_id'], raw, reason, intent)
        except Problem as error:
            if error.code not in {'invalid_definition', 'integrity', 'missing_asset', 'panel_render_required', 'definition_limit'}: raise
            self._snapshot(session, raw)
            previous = self.store.setting(intent['request_storage'])
            if not previous or previous.get('definition_recovery_pending'):
                self.store.set_setting(intent['request_storage'], {'fingerprint': intent['fingerprint'], 'definition_recovery_pending': True, 'result': {'object_id': intent['object_id'], 'error_code': error.code, 'proposed_sha256': intent['after_sha256'], 'current_sha256': digest(raw)}})
            return None

    def sync(self, ident):
        obj = self.store.get(ident)
        if not is_definition(obj): return obj
        with self.locked(obj['project_id']) as session:
            return self._register(session, ident, self._raw(session, ident), 'external figure definition observed')

    def read(self, ident, revision=None):
        obj = self.store.get(ident, revision)
        with self.locked(obj['project_id']) as session:
            if revision is None:
                raw = self._raw(session, ident); obj = self._register(session, ident, raw, 'external figure definition observed')
            else:
                raw = _read(session['snapshots'], obj['content']['definition_sha256'])
                require(digest(raw) == obj['content']['definition_sha256'], '历史主图定义字节不匹配', 'integrity', 409)
            value = self.parse(raw, obj['project_id'], ident)
            return {'figure': obj, 'definition': value, 'definition_sha256': digest(raw), 'definition_path': relative_path(ident), 'definition_text': raw.decode('utf-8'), 'required_missing': [s['id'] for s in value['slots'] if s['required'] and s['source'] is None], 'execution_on_open': False}

    def _after_replace(self): pass  # Failure-injection seam; no production retry.

    def command(self, data, project_id, principal=None):
        operation = data['action'].rsplit('.', 1)[-1]
        require(operation in {'create', 'bind', 'layout', 'layout_group', 'detach'}, '主图组成操作不支持')
        allowed = {'action', 'project_id', 'request_key', 'id', 'expected_revision', 'expected_definition_sha256', 'restore_definition_sha256', 'slot_id', 'source', 'box', 'title', 'width', 'height', 'slots'}
        require(set(data) <= allowed, '主图组成字段不支持')
        if operation == 'layout_group':
            require(set(data) <= {'action', 'project_id', 'request_key', 'id', 'expected_revision', 'expected_definition_sha256', 'restore_definition_sha256', 'slots'}, '布局组只能修改指定图位的布局')
            changes = data.get('slots')
            require(isinstance(changes, list) and 2 <= len(changes) <= 24, '布局组需要2..24个图位')
            seen = set()
            for change in changes:
                require(isinstance(change, dict) and set(change) == {'id', 'box'} and isinstance(change['id'], str) and change['id'] not in seen, '布局组图位重复或字段无效')
                seen.add(change['id'])
        restore = data.get('restore_definition_sha256')
        if 'restore_definition_sha256' in data:
            require(operation != 'create' and isinstance(restore, str) and re.fullmatch(r'[a-f0-9]{64}', restore), '恢复需本主图固定定义摘要')
        key = data.get('request_key'); require(isinstance(key, str) and 0 < len(key) <= 160, '组成需要稳定请求身份')
        agent = bool(principal and principal.get('kind') == 'agent')
        agent = agent or bool(principal and principal.get('actor_kind') == 'agent')
        require(not agent or operation == 'create', 'Agent默认只能建立未采用的主图候选；不能直接改人工主图', 'forbidden', 403)
        from .figure_composition_task import authorize
        execution = authorize(self.store, principal, data['action'], data)
        fingerprint = digest({'data': canonical_geometry(data), 'principal': principal}); storage = 'main_figure_request:' + project_id + ':' + digest(key.encode())
        with self.locked(project_id) as session:
            previous = self.store.setting(storage)
            if previous:
                require(previous['fingerprint'] == fingerprint, '重复组成请求不同', 'idempotency_conflict', 409)
                require(not previous.get('interrupted_external_conflict'), '原组成写入后发生外改；保留双方版本，不重新执行请求', 'conflict', 409, previous['result'])
                require(not previous.get('cancelled_pending'), '旧任务的主图写入已失效；保留字节但不重发或采用', 'cancelled', 409)
                require(not previous.get('definition_recovery_pending'), '此定义仍待修复；保存原文件和提案，不覆盖或重发', 'definition_recovery', 409, previous['result'])
                return previous['result']
            if operation == 'create':
                ident = uid('ART'); old = None
                value = {'schema': SCHEMA, 'object_id': ident, 'project_id': project_id, 'title': data.get('title'), 'width': data.get('width', 1200), 'height': data.get('height', 600), 'slots': copy.deepcopy(data.get('slots', []))}
                for slot in value['slots']:
                    if slot.get('source') is not None: slot['source'] = self.resolve_source(project_id, slot['source'], ident)
            else:
                ident = data.get('id'); obj = self.store.get(ident); require(is_definition(obj) and obj['project_id'] == project_id and not obj['archived'], '主图不属于当前项目', 'forbidden', 403)
                old = self._raw(session, ident); obj = self._register(session, ident, old, 'external figure definition observed')
                require(obj['revision'] == data.get('expected_revision') and digest(old) == data.get('expected_definition_sha256'), '主图文件或修订已有新修改；保留双方内容', 'conflict', 409, {'current_revision': obj['revision'], 'current_sha256': digest(old)})
                value = self.parse(old, project_id, ident)
                original_value = canonical_geometry(value)
                if operation == 'layout_group':
                    by_id = {s['id']: s for s in value['slots']}
                    require(all(change['id'] in by_id for change in changes), '布局组包含不存在的图位')
                    # Stage all changes before validation and the single file/
                    # Store commit below. No partial per-slot writes are made.
                    for change in changes: by_id[change['id']]['box'] = copy.deepcopy(change['box'])
                else:
                    slot = next((s for s in value['slots'] if s['id'] == data.get('slot_id')), None); require(slot is not None, '图位不存在')
                    if operation == 'bind': slot['source'] = self.resolve_source(project_id, data.get('source'), ident)
                    elif operation == 'detach': slot['source'] = None
                    else: slot['box'] = data.get('box')
            self.validate(value, project_id, ident)
            if restore is not None:
                # Restore original bytes only when the requested inverse, under
                # the current revision/file CAS above, produces this exact
                # historical definition. JSON geometry spelling (0 vs 0.0)
                # is not a numeric change. Every non-geometry field stays exact.
                with self.store.connect() as connection:
                    history = connection.execute('SELECT snapshot FROM revisions WHERE object_id=? AND revision<=?', (ident, obj['revision']))
                    registered = any(json.loads(row[0]).get('content', {}).get('definition_sha256') == restore for row in history)
                require(registered, '原定义未登记为本主图的历史修订', 'conflict', 409)
                raw = _read(session['snapshots'], restore)
                require(digest(raw) == restore, '原定义快照摘要不符', 'integrity', 409)
                restored = self.parse(raw, project_id, ident)
                require(encoded(canonical_geometry(restored)) == encoded(canonical_geometry(value)),
                        '恢复定义与本次撤销操作不一致；保留当前图', 'conflict', 409)
            elif old is not None and encoded(original_value) == encoded(canonical_geometry(value)):
                # A JSON roundtrip can spell 0.0 as 0. If the whole definition
                # is unchanged, preserve its original bytes and revision.
                raw = old
            else:
                raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
            require(len(raw) <= MAX_BYTES, '主图定义超过1MiB', 'definition_limit', 413)
            before = self._snapshot(session, old) if old is not None else None; after = self._snapshot(session, raw)
            intent = {'object_id': ident, 'project_id': project_id, 'operation': operation, 'actor': 'agent' if agent else 'user', 'before_sha256': before, 'after_sha256': after, 'request_storage': storage, 'fingerprint': fingerprint}
            if execution: intent['execution'] = execution
            with self.store.connect() as c:
                from .figure_composition_task import fence_intent
                fence_intent(self.store, c, intent)
            pending = uuid.uuid4().hex + '.json'; _create_at(session['pending'], pending, encoded(intent).encode())
            with _parent(session['root'], relative_path(ident).split('/'), create=True) as (fd, name):
                current = _read(fd, name, True)
                require(current == old, '替换前外部编辑已改变文件；两份快照保留', 'conflict', 409)
                if old is None: _create_at(fd, name, raw)
                else: _replace_at(fd, name, raw)
            self._after_replace()
            actual = self._raw(session, ident)
            require(actual == raw, '替换后观察到外部修改；保留所有快照，未宣称本次保存完成', 'conflict', 409)
            obj = self._register(session, ident, raw, 'explicit figure composition', intent)
            os.rename(pending, pending, src_dir_fd=session['pending'], dst_dir_fd=session['history']); os.fsync(session['pending']); os.fsync(session['history'])
            return self.store.setting(storage)['result']


def require_complete(obj):
    if is_definition(obj):
        missing = [s['id'] for s in obj['content']['slots'] if s['required'] and s['source'] is None]
        require(not missing, '主图仍有必需空图位，不能作为完整成果输出', 'required_figure_slots', 409, {'missing': missing})
