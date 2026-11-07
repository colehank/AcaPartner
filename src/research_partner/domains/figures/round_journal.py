"""Internal file/SQL batch boundary for explicit manuscript/figure decisions.

This is not a public action or an authorization path. The caller holds the
project definition lock, stages rendering outside the SQL writer, and rechecks
the round, current permissions and scientific source in the supplied callback.
An uncommitted batch restores only its own exact bytes. A committed receipt
never invokes a renderer or repeats the decision during recovery.
"""
import copy
import json
import os
import re
import uuid

from research_partner.domains.figures.definition import MAX_BYTES, canonical_geometry, is_definition, relative_path, _read
from research_partner.domains.workspace.notebook import _parent, _create_at, _replace_at
from research_partner.storage.store import digest, encoded, now, require

PROTOCOL = 'research-partner-figure-round-batch/1'


def prepare(definitions, session, changes):
    """Prepare only selected slot boxes; no file or database mutation."""
    require(isinstance(changes, list) and 0 < len(changes) <= 24,
            '主图批次需明确的有限目标', 'invalid_arguments', 422)
    entries, seen = [], set()
    for change in changes:
        require(isinstance(change, dict) and set(change) in ({
            'object_id', 'expected_revision', 'expected_definition_sha256', 'slots'}, {
            'object_id', 'expected_revision', 'expected_definition_sha256', 'slots', 'sources'}),
            '主图批次只接受固定来源及已选图位布局', 'invalid_arguments', 422)
        ident = change['object_id']
        require(isinstance(ident, str) and ident not in seen, '主图批次目标重复', 'invalid_arguments', 422)
        seen.add(ident)
        old = definitions.store.get(ident)
        require(is_definition(old) and old['project_id'] == session['project_id'] and not old['archived'],
                '主图不属于当前可编辑项目', 'forbidden', 403)
        raw = definitions._raw(session, ident)
        require(type(change['expected_revision']) is int and old['revision'] == change['expected_revision']
                and digest(raw) == change['expected_definition_sha256'] == old['content']['definition_sha256'],
                '主图文件或保存版本已变化；先重新读取', 'conflict', 409)
        original = definitions.parse(raw, session['project_id'], ident)
        require(definitions.content(original, digest(raw)) == old['content'] and original['title'] == old['title'],
                '主图原文件与登记投影不符', 'integrity', 409)
        value = copy.deepcopy(original)
        slots, selected = change['slots'], set()
        require(isinstance(slots, list) and 0 < len(slots) <= len(value['slots']), '请选择准确图位', 'invalid_arguments', 422)
        by_id = {s['id']: s for s in value['slots']}
        for slot in slots:
            require(isinstance(slot, dict) and set(slot) == {'id', 'box'}
                    and isinstance(slot['id'], str) and slot['id'] in by_id and slot['id'] not in selected,
                    '图位缺失、重复或包含非布局写入', 'invalid_arguments', 422)
            selected.add(slot['id']); by_id[slot['id']]['box'] = copy.deepcopy(slot['box'])
        sources = change.get('sources', {})
        require(isinstance(sources, dict) and set(sources) <= selected, '来源采用只能作用于明确所选图位')
        for slot_id, ref in sources.items():
            old_ref = by_id[slot_id]['source']
            require(isinstance(ref, dict) and old_ref is not None and ref.get('id') == old_ref['id']
                    and ref.get('revision', 0) > old_ref['revision'], '来源采用必须推进同一叶图', 'integrity', 409)
            by_id[slot_id]['source'] = copy.deepcopy(ref)
        definitions.validate(value, session['project_id'], ident)
        require(value != original and (sources or canonical_geometry(value) != canonical_geometry(original)),
                '主图布局和明确来源没有变化', 'invalid_arguments', 422)
        after = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
        require(len(after) <= MAX_BYTES, '主图定义超过1MiB', 'definition_limit', 413)
        candidate = {**copy.deepcopy(old), 'content': definitions.content(value, digest(after)),
                     'revision': old['revision'] + 1, 'updated_at': now()}
        entries.append({'base': old, 'before': raw, 'after': after, 'candidate': candidate,
                        'selected_slots': [s['id'] for s in slots]})
    return {'project_id': session['project_id'], 'entries': entries}


def _identities(prepared):
    return [{'object_id': e['base']['id'], 'base_revision': e['base']['revision'],
             'base_sha256': digest(e['base']), 'before_sha256': digest(e['before']),
             'after_sha256': digest(e['after']), 'result_revision': e['candidate']['revision'],
             'result_sha256': digest(e['candidate'])} for e in prepared['entries']]


def _archive(session, name):
    os.rename(name, name, src_dir_fd=session['pending'], dst_dir_fd=session['history'])
    os.fsync(session['pending']); os.fsync(session['history'])


def publish(definitions, session, prepared, request_key, request_fingerprint, commit, *, prewrite=None, checkpoint=lambda phase: None):
    """Publish all projections and caller's other effects in one SQL transaction.

    `commit(connection, written)` must recheck the full round and register the
    already staged exports plus manuscript/decisions in that same transaction.
    It must not obtain another definition lock, launch work or start a writer.
    The private failure seam is for crash tests, never forwarded from the API.
    """
    require(prepared['project_id'] == session['project_id'], '批次跨项目', 'forbidden', 403)
    require(isinstance(request_key, str) and 0 < len(request_key) <= 160 and isinstance(request_fingerprint, str),
            '批次需要准确请求身份', 'invalid_arguments', 422)
    store = definitions.store; identities = _identities(prepared)
    fingerprint = digest({'request': request_fingerprint, 'entries': identities})
    key = 'figure_round_batch:' + session['project_id'] + ':' + digest(request_key.encode())
    previous = store.setting(key)
    if previous:
        require(previous['fingerprint'] == fingerprint, '重复批次输入不同', 'idempotency_conflict', 409)
        return previous['result']
    for e in prepared['entries']:
        require(definitions._raw(session, e['base']['id']) == e['before']
                and digest(store.get(e['base']['id'])) == digest(e['base']),
                '渲染后主图已有外改；整批未发布', 'conflict', 409)
        require(digest(e['after']) == e['candidate']['content']['definition_sha256']
                and definitions.content(definitions.parse(e['after'], session['project_id'], e['base']['id']),
                                        digest(e['after'])) == e['candidate']['content'],
                '暂存主图字节与候选投影不符', 'integrity', 409)
        definitions._snapshot(session, e['before']); definitions._snapshot(session, e['after'])
    intent = {'batch_protocol': PROTOCOL, 'project_id': session['project_id'], 'entries': identities,
              'request_storage': key, 'fingerprint': fingerprint}
    name = uuid.uuid4().hex + '.json'
    _create_at(session['pending'], name, encoded(intent).encode()); checkpoint('intent')
    for e in prepared['entries']:
        with _parent(session['root'], relative_path(e['base']['id']).split('/')) as (fd, leaf):
            require(_read(fd, leaf) == e['before'], '替换前外改；保留双方字节', 'conflict', 409)
            _replace_at(fd, leaf, e['after'])
        checkpoint('replace:' + e['base']['id'])
    with store.transaction() as connection:
        # File bytes and every projection head are checked again under the
        # definition lock + writer, before any authoritative projection write.
        for e in prepared['entries']:
            require(definitions._raw(session, e['base']['id']) == e['after']
                    and digest(store.get(e['base']['id'], connection=connection)) == digest(e['base']),
                    '批次提交前来源已变化；不部分采用', 'conflict', 409)
        if prewrite: prewrite(connection)
        written = {}
        for e in prepared['entries']:
            candidate = e['candidate']; ident = candidate['id']
            obj = store.save(ident, e['base']['revision'], content=candidate['content'], merge=False,
                             actor='file_service', reason='explicit manuscript figure batch',
                             prepared_updated_at=candidate['updated_at'], connection=connection)
            require(digest(obj) == digest(candidate), '实际保存主图与渲染候选不同', 'integrity', 409)
            written[ident] = obj; checkpoint('projection:' + ident)
        result = commit(connection, written)
        checkpoint('before_sql_commit')
        # Rendering is staged, but unmanaged editors do not share this lock.
        # Recheck after the caller's paper/decision writes as well as before
        # them. A detected external edit aborts all SQL and keeps both files.
        for e in prepared['entries']:
            require(definitions._raw(session, e['base']['id']) == e['after']
                    and digest(store.get(e['base']['id'], connection=connection)) == digest(e['candidate']),
                    '联合提交期间主图再次变化；保留外改且整批不采用', 'conflict', 409)
        connection.execute('INSERT INTO kv VALUES(?,?)', (key, encoded({
            'fingerprint': fingerprint, 'result': result, 'objects': identities})))
    checkpoint('after_sql_commit')
    _archive(session, name)
    return result


def recover(definitions, session, name, intent):
    """Recover the batch as a unit; never call single-main _register here."""
    require(set(intent) == {'batch_protocol', 'project_id', 'entries', 'request_storage', 'fingerprint'}
            and intent.get('batch_protocol') == PROTOCOL and intent['project_id'] == session['project_id'],
            '主图批次恢复身份不符', 'integrity', 409)
    entries = intent.get('entries')
    require(isinstance(entries, list) and 0 < len(entries) <= 24
            and all(isinstance(e, dict) and set(e) == {
                'object_id', 'base_revision', 'base_sha256', 'before_sha256', 'after_sha256',
                'result_revision', 'result_sha256'} for e in entries), '批次恢复目标不完整', 'integrity', 409)
    for e in entries:
        require(isinstance(e['object_id'], str) and re.fullmatch(r'ART-[a-f0-9]{16}', e['object_id'])
                and type(e['base_revision']) is int and e['base_revision'] >= 1
                and type(e['result_revision']) is int and e['result_revision'] == e['base_revision'] + 1
                and all(isinstance(e[k], str) and re.fullmatch(r'[a-f0-9]{64}', e[k])
                        for k in ('base_sha256', 'before_sha256', 'after_sha256', 'result_sha256')),
                '批次恢复版本或摘要无效', 'integrity', 409)
    require(len({e['object_id'] for e in entries}) == len(entries)
            and isinstance(intent['fingerprint'], str) and re.fullmatch(r'[a-f0-9]{64}', intent['fingerprint'])
            and isinstance(intent['request_storage'], str) and re.fullmatch(
                re.escape('figure_round_batch:' + session['project_id'] + ':') + r'[a-f0-9]{64}', intent['request_storage']),
            '批次恢复回执身份无效', 'integrity', 409)
    previous = definitions.store.setting(intent['request_storage'])
    if previous:
        require(previous['fingerprint'] == intent['fingerprint'] and previous['objects'] == entries,
                '批次提交回执不符；不重新执行', 'integrity', 409)
        for e in entries:
            committed = definitions.store.get(e['object_id'], e['result_revision'])
            require(digest(committed) == e['result_sha256']
                    and committed['content']['definition_sha256'] == e['after_sha256'],
                    '批次历史与已提交回执不符', 'integrity', 409)
            raw = definitions._raw(session, e['object_id'], True)
            if raw is not None: definitions._snapshot(session, raw)
        # Later external bytes are preserved. Normal current-read validation
        # will surface them; the committed batch is never rerendered/replayed.
        _archive(session, name); return
    restored = []
    # Check all targets before restoring any: a later external edit or an
    # unrelated SQL change must not be overwritten to manufacture rollback.
    for e in entries:
        raw = definitions._raw(session, e['object_id'], True)
        if raw is not None: definitions._snapshot(session, raw)
        require(raw is not None and digest(raw) in {e['before_sha256'], e['after_sha256']}
                and digest(definitions.store.get(e['object_id'])) == e['base_sha256'],
                '中断批次后有外部修改；原稿与所有主图快照保留，需明确处理', 'definition_round_conflict', 409)
        before = _read(session['snapshots'], e['before_sha256'])
        require(digest(before) == e['before_sha256'], '批次原定义快照损坏', 'integrity', 409)
        restored.append((e, raw, before))
    for e, raw, before in restored:
        if raw == before: continue
        with _parent(session['root'], relative_path(e['object_id']).split('/')) as (fd, leaf):
            require(_read(fd, leaf) == raw, '恢复期间出现外改；未覆盖', 'definition_round_conflict', 409)
            _replace_at(fd, leaf, before)
    _archive(session, name)
