"""Typed, explicitly registered manuscript claims with immutable source pins.

Explicit proposals and registrations; no model dispatch or scientific confirmation.
"""
from __future__ import annotations
import copy
import json
from research_partner.storage.store import Problem, require, digest, encoded, now, uid
from research_partner.domains.manuscripts.revision import source, blocks
from research_partner.domains.workspace.management import authority_scope, actor

FEATURE = 'typed_manuscript_claims_v1'
KEY = 'typed_manuscript_claims:'
RELATIONS = {'supports', 'limits', 'contradicts', 'motivates'}


def _get(c, key, default=None):
    row = c.execute('SELECT value FROM kv WHERE key=?', (KEY + key,)).fetchone()
    return json.loads(row[0]) if row else copy.deepcopy(default)


def _put(c, key, value):
    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY + key, encoded(value)))


def _authority(app, principal, scope):
    principal = principal or {'kind': 'local_operator'}
    require(scope is None or principal.get('kind') != 'local_operator', '受限Claim命令需要实际身份', 'forbidden', 403)
    current = authority_scope(app, principal)
    if current is not None:
        scope = set(current) if scope is None else set(scope) & set(current)
    return principal, scope


def _main(app, data, scope, c):
    obj = source(app, data.get('object_id'), scope, c)
    require(obj['kind'] in {'paper', 'report'} and obj['project_id'] == data.get('project_id'), 'Claim必须属于本项目稿件', 'forbidden', 403)
    blocks(obj)
    return obj


def _anchor(obj, anchor):
    required = {'block_id', 'start', 'end', 'quote'}
    require(isinstance(anchor, dict) and required <= set(anchor) <= required | {'offset_unit'}, 'Claim需要准确段落和Unicode选区')
    require(anchor.get('offset_unit', 'unicode_code_point') == 'unicode_code_point', 'Claim选区仅接受Unicode code point')
    require(isinstance(anchor['block_id'], str) and 0 < len(anchor['block_id']) <= 200, 'Claim段落身份无效')
    block = blocks(obj).get(anchor['block_id'])
    require(block is not None and type(anchor['start']) is int and type(anchor['end']) is int and
            0 <= anchor['start'] < anchor['end'] <= len(block['text']) and isinstance(anchor['quote'], str) and
            block['text'][anchor['start']:anchor['end']] == anchor['quote'], 'Claim选区与实际保存稿件不同', 'anchor_conflict', 409)
    return {**copy.deepcopy(anchor), 'offset_unit': 'unicode_code_point', 'object_id': obj['id'], 'revision': obj['revision']}


def _references(app, project, refs, scope, c):
    require(isinstance(refs, list) and 1 <= len(refs) <= 32, 'Claim需要1–32个固定来源')
    pins, seen = [], set()
    for ref in refs:
        require(isinstance(ref, dict) and set(ref) == {'id', 'revision'} and isinstance(ref['id'], str) and
                type(ref['revision']) is int and ref['revision'] >= 0, '来源仅接受准确id/revision')
        key = (ref['id'], ref['revision'])
        require(key not in seen, 'Claim来源不得重复'); seen.add(key)
        current = app.access(app.store.get(ref['id'], connection=c), scope)
        app.store.assert_source_access(c, project, ref['id'])
        fixed = app.store.get(ref['id'], ref['revision'], connection=c)
        require(fixed['project_id'] == current['project_id'] and fixed['kind'] == current['kind'], '固定来源身份不同', 'source_mismatch', 409)
        require(not current['archived'] and fixed['kind'] != 'project', 'Claim来源已归档或不是科研材料', 'source_mismatch', 409)
        pins.append({'id': ref['id'], 'revision': ref['revision'], 'sha256': digest(fixed)})
    return pins


def _gaps(app, obj, row, scope, c, source_errors=None):
    gaps = []
    a = row['claim']['anchor']; block = blocks(obj).get(a['block_id'])
    if block is None or block['text'][a['start']:a['end']] != a['quote']:
        gaps.append({'kind': 'manuscript_anchor_changed', 'object_id': obj['id'], 'block_id': a['block_id']})
    for pin in row['pins']:
        try:
            if pin['id'] in (source_errors or {}): raise source_errors[pin['id']]
            current = app.access(app.store.get(pin['id'], connection=c), scope)
            app.store.assert_source_access(c, obj['project_id'], pin['id'])
            fixed = app.store.get(pin['id'], pin['revision'], connection=c)
            require(digest(fixed) == pin['sha256'], '固定来源字节不同', 'source_mismatch', 409)
            if current['revision'] != pin['revision'] or current['archived']:
                gaps.append({'kind': 'source_head_changed', 'id': pin['id'], 'fixed_revision': pin['revision'], 'current_revision': current['revision']})
        except Problem as error:
            gaps.append({'kind': 'source_unavailable', 'id': pin['id'], 'code': error.code})
    return gaps


def _view(app, obj, state, scope, c, source_errors=None):
    claims, observations = [], []
    for row in state['rows']:
        claim = copy.deepcopy(row['claim']); gaps = _gaps(app, obj, row, scope, c, source_errors)
        if claim['status'] == 'registered' and gaps: claim['status'] = 'needs_review'
        claims.append(claim)
        observations.append({'claim_id': claim['id'], 'stored_status': row['claim']['status'], 'gaps': gaps,
                             'source_pins': copy.deepcopy(row['pins']), 'scientific_confirmation': False})
    return {'object_id': obj['id'], 'project_id': obj['project_id'], 'manuscript_revision': obj['revision'],
            'registry_revision': state['revision'], 'claims': claims, 'observations': observations,
            'history': copy.deepcopy(state['history']), 'scientific_approval': False,
            'status_basis': 'Current source/anchor observation; immutable proposal and registration history retained.'}


def dispatch(app, data, scope=None, principal=None):
    action = data.get('action')
    require(action in {'claim.read', 'claim.propose', 'claim.accept'}, 'Claim命令不支持', 'unsupported_action', 422)
    expected_keys = {'action', 'project_id', 'object_id'} if action == 'claim.read' else {'action', 'project_id', 'object_id', 'expected_revision', 'request_id', 'payload'}
    require(set(data) == expected_keys, 'Claim命令包含不支持字段')
    principal, scope = _authority(app, principal, scope)
    if action == 'claim.accept':
        require(principal.get('actor_kind') != 'agent', 'Agent不能自行登记Claim关系', 'forbidden', 403)
    # File-owned figure definitions must be observed before the SQL lifetime.
    # Sync uses the existing authority service and never executes plotting code.
    # Failure stays visible as an unavailable source; stale Store projections
    # cannot turn a missing/invalid current definition into a valid registration.
    with app.store.connect() as c:
        obj = _main(app, data, scope, c)
        state = _get(c, 'object:' + obj['id'], {'revision': 0, 'rows': [], 'history': []})
        ids = {p['id'] for row in state['rows'] for p in row['pins']}
        if action == 'claim.propose':
            payload = data.get('payload')
            require(isinstance(payload, dict), 'Claim需要明确payload')
            pins = _references(app, obj['project_id'], payload.get('result_or_source_refs'), scope, c)
            ids.update(p['id'] for p in pins)
    source_errors = {}
    for ident in ids:
        try: app.get(ident, scope)
        except Problem as error: source_errors[ident] = error
    with app.store.transaction() as c:
        obj = _main(app, data, scope, c)
        state = _get(c, 'object:' + obj['id'], {'revision': 0, 'rows': [], 'history': []})
        if action == 'claim.read': return _view(app, obj, state, scope, c, source_errors)
        request_id = data.get('request_id')
        require(isinstance(request_id, str) and 0 < len(request_id) <= 180, 'Claim命令需要稳定请求身份')
        signature = digest({'data': data, 'principal': principal})
        prior = _get(c, 'request:' + request_id)
        if prior:
            require(prior['input_sha256'] == signature, '同一Claim请求不能改变内容或身份', 'idempotency_conflict', 409)
            for row in state['rows']:
                if row['claim']['id'] in prior['result']['changed_claim_ids']:
                    for ref in row['claim']['result_or_source_refs']:
                        if ref['id'] in source_errors: raise source_errors[ref['id']]
                    _references(app, obj['project_id'], row['claim']['result_or_source_refs'], scope, c)
            return {**_view(app, obj, state, scope, c, source_errors), 'changed_claim_ids': prior['result']['changed_claim_ids'], 'manuscript_changed': False, 'replayed': True}
        require(not obj['archived'], '归档稿件仅可查看Claim历史', 'forbidden', 403)
        require(type(data['expected_revision']) is int and data['expected_revision'] == obj['revision'], '稿件已改变，请核对保存版', 'conflict', 409)
        payload = data['payload']
        require(isinstance(payload, dict), 'Claim需要明确payload')
        from research_partner.packaging.compatibility import require_features
        require_features(c, [FEATURE])
        if action == 'claim.propose':
            require(set(payload) == {'anchor', 'result_or_source_refs', 'relation', 'explanation'}, 'Claim提议字段不支持')
            require(isinstance(payload['relation'], str) and payload['relation'] in RELATIONS and isinstance(payload['explanation'], str) and 0 < len(payload['explanation'].strip()) <= 4000, 'Claim关系或解释无效')
            anchor = _anchor(obj, payload['anchor']); pins = _references(app, obj['project_id'], payload['result_or_source_refs'], scope, c)
            for pin in pins:
                if pin['id'] in source_errors: raise source_errors[pin['id']]
            claim = {'id': uid('CLM'), 'project_id': obj['project_id'], 'anchor': anchor,
                     'result_or_source_refs': copy.deepcopy(payload['result_or_source_refs']), 'relation': payload['relation'],
                     'explanation': payload['explanation'], 'principal_id': actor(principal), 'status': 'proposed', 'evidence_refs': []}
            state['rows'].append({'claim': claim, 'pins': pins, 'created_at': now()})
            changed_ids = [claim['id']]
        else:
            require(set(payload) == {'claim_ids'} and isinstance(payload['claim_ids'], list) and 1 <= len(payload['claim_ids']) <= 32 and
                    all(isinstance(i, str) for i in payload['claim_ids']) and len(set(payload['claim_ids'])) == len(payload['claim_ids']), '登记需要明确唯一Claim标识')
            selected = [next((r for r in state['rows'] if r['claim']['id'] == ident), None) for ident in payload['claim_ids']]
            require(all(r and r['claim']['status'] == 'proposed' for r in selected), 'Claim不存在或已登记', 'conflict', 409)
            for row in selected:
                require(not _gaps(app, obj, row, scope, c, source_errors), 'Claim锚点或来源已变化；旧提议保留，不能登记', 'source_mismatch', 409)
                _references(app, obj['project_id'], row['claim']['result_or_source_refs'], scope, c)
            for row in selected: row['claim']['status'] = 'registered'
            changed_ids = payload['claim_ids']
        state['revision'] += 1
        state['history'].append({'revision': state['revision'], 'action': action, 'claim_ids': changed_ids, 'actor': actor(principal), 'at': now(), 'scientific_confirmation': False})
        require(len(encoded(state).encode()) <= 4 * 1024 * 1024, 'Claim登记超出本轮界限；未截断', 'context_limit', 413)
        _put(c, 'object:' + obj['id'], state)
        result = {**_view(app, obj, state, scope, c, source_errors), 'changed_claim_ids': changed_ids, 'manuscript_changed': False}
        _put(c, 'request:' + request_id, {'input_sha256': signature, 'result': result})
        app.store.event(c, action, obj['id'], {'claim_ids': changed_ids, 'registry_revision': state['revision'], 'manuscript_revision': obj['revision'], 'scientific_confirmation': False}, actor(principal))
        return result
