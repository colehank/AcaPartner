"""Explicit same-planner schema repair, with one transactional enqueue.

This entry cannot reopen other phases, replace tasks, edit native evidence or
grant resources. A preview is a pin; only the explicit commit authorizes a call.
"""
import copy
import json
import re
from research_partner.storage.store import Problem, require, digest, encoded, now
from research_partner.domains.collaboration.cycle import _setting, _put, _write

FEATURE = 'cycle_failed_planner_revision_v1'


def _guard(app, c, parent_id, child_id, scope):
    s = app.store
    parent = s.task(parent_id, c)
    project = app.access(s.get(parent['project_id'], connection=c), scope)
    require(not project['archived'] and (scope is None or parent['project_id'] in scope),
            '无权修订此协作', 'forbidden', 403)
    state = parent['result'].get('cycle', {})
    require(parent['payload'].get('kind') == 'research_cycle'
            and parent['status'] == 'waiting_input' and state.get('phase') == 'planning'
            and state.get('last_failure', {}).get('code') == 'cycle_handoff'
            and state.get('planner') == child_id,
            '仅可接回当前失败规划交接；暂停、取消或后续阶段不能自动恢复', 'conflict', 409)
    child = s.task(child_id, c)
    p = child['payload']
    require(child['project_id'] == parent['project_id'] and p.get('cycle_parent') == parent_id
            and p.get('cycle_role') == 'planner' and child['status'] == 'failed'
            and child['result'].get('failure_code') == 'invalid_model_output',
            '仅可修订原规划的格式失败；已暂停、取消或其他失败需另行处理', 'conflict', 409)
    require(child['attempts'] < 3, '原规划有限尝试次数已耗尽', 'budget_exhausted', 409)
    require(not child['result'].get('object_id') and not child['result'].get('cycle_candidate')
            and not _setting(c, 'commit:' + child_id)
            and not c.execute('SELECT id FROM objects WHERE id=?', ('ART-' + child_id.removeprefix('TASK-'),)).fetchone(),
            '原规划已有保存成果；此入口不能覆盖候选或人工编辑', 'conflict', 409)
    key = p.get('cycle_child_key')
    allocation = state.get('allocations', {}).get(key, {})
    require(any(ref.get('id') == child_id and ref.get('key') == key and ref.get('role') == 'planner'
                for ref in state.get('children', []))
            and allocation.get('task_id') == child_id and allocation.get('budget') == p['budget']
            and allocation.get('provider_id') == p['provider_id']
            and allocation.get('route') == p.get('cycle_provider_route')
            and _setting(c, 'cycle_epoch:' + key) == state['epoch'],
            '原规划身份、轮次或冻结分配已变化', 'conflict', 409)
    cfg = app.config.get('providers', {}).get(p.get('provider_id'), {})
    require(cfg.get('authorized') is True and cfg.get('route') == 'codex'
            and p.get('cycle_provider_route') == 'codex'
            and parent['payload']['cycle_config']['roles']['planner'] == p['provider_id']
            and parent['payload']['cycle_config']['provider_routes']['planner'] == 'codex',
            '本入口仅接续原已授权 Codex 规划会话', 'authorization_required', 403)
    require(not state.get('coordinator_revisions') and not state.get('final_revision'),
            '规划修订不能覆盖后续协调者交接', 'conflict', 409)
    siblings = []
    for ref in [{'id': parent_id}, *state['children']]:
        task = s.task(ref['id'], c)
        lease = _setting(c, 'execution:' + task['id'])
        require(task['status'] not in {'queued', 'running'} and (not lease or lease.get('state') != 'active'),
                '协作仍有在途任务；等待原执行结算', 'conflict', 409)
        siblings.append({'id': task['id'], 'status': task['status'], 'attempts': task['attempts'], 'lease': lease})
    for task in (parent, child):
        s.assert_material_access(c, task['payload'])
        s.assert_feedback_ready(c, task['payload'])
        require(not s.question_blockers(c, task['id']), '必要裁决尚待处理', 'conflict', 409)
        extension = _setting(c, 'budget_extension:' + task['id'], {})
        require(not extension.get('invocations') and not extension.get('seconds'),
                '协作不得用单独扩额绕过原分配', 'budget_exhausted', 409)
    calls = _setting(c, 'provider_invocations:' + child_id, 0)
    elapsed = _setting(c, 'elapsed:' + child_id, 0)
    remaining = {'invocations': p['budget']['max_model_calls'] - calls,
                 'seconds': p['budget']['timeout_seconds'] - elapsed,
                 'attempts': 3 - child['attempts'], 'unit': 'Codex CLI invocations; internal API requests unknown'}
    require(remaining['invocations'] > 0 and remaining['seconds'] > 0,
            '原规划剩余额度已耗尽；未复制或重置预算', 'budget_exhausted', 409)
    return parent, child, remaining, siblings


def availability(app, parent, child, scope=None):
    if child['payload'].get('cycle_role') != 'planner' or child['result'].get('failure_code') != 'invalid_model_output':
        return None
    try:
        with app.store.connect() as c:
            c.execute('BEGIN')
            _, _, remaining, _ = _guard(app, c, parent['id'], child['id'], scope)
        return {'allowed': True, 'remaining': remaining, 'reason': None}
    except Problem as error:
        return {'allowed': False, 'reason': str(error), 'reason_code': error.code}


def _preview(app, c, data, scope):
    from research_partner.providers.registry import Providers, _controlled_file
    s = app.store
    parent, child, remaining, siblings = _guard(app, c, data['id'], data['child_id'], scope)
    require(app.runner, '执行服务未连接，不能核对原生会话', 'runtime_unavailable', 503)
    directory = app.runner.runs / child['id']
    # Codex continuity is a read-only verifier. Do not use the native migration
    # branch here: preview must never mutate accounting or execution materials.
    continuity = Providers(app).assert_codex_continuity(child, directory)
    require(continuity.get('requires_checkpoint') and continuity.get('session_id'),
            '原规划缺少同任务会话检查点；不能冷启动', 'provider_checkpoint_missing', 409)
    raw = _controlled_file(directory, directory / 'candidate.rejected.json', 131072)
    try:
        rejected = json.loads(raw)
    except ValueError as error:
        raise Problem('原被拒候选不可读取，先核对私有执行材料', 'candidate_checkpoint_invalid', 409) from error
    text = data.get('guidance', '')
    require(isinstance(text, str) and bool(text.strip()) and len(text) <= 8000, '需要 1–8000 字的具体修订指导')
    snapshot = s.execution_inputs(c, child['id'])
    parent_inputs = s.execution_inputs(c, parent['id'])
    config = app.config['providers'][child['payload']['provider_id']]
    pin = {'version': 1, 'parent_id': parent['id'], 'child_id': child['id'],
           'parent_sha256': digest(parent), 'child_sha256': digest(child),
           'parent_inputs': parent_inputs, 'child_inputs': snapshot,
           'siblings_sha256': digest(siblings), 'remaining': remaining,
           'provider_configuration_sha256': digest(config), 'continuity': continuity,
           'rejected_sha256': digest(raw), 'guidance_sha256': digest(text)}
    guidance = [s.unpack(c.execute('SELECT * FROM events WHERE seq=?', (seq,)).fetchone()) for seq in snapshot['guidance']]
    decisions = [s.get(ref['id'], ref['revision'], c) for ref in snapshot['decisions']]
    return {'ready': True, 'pin': pin, 'parent_id': parent['id'], 'child_id': child['id'],
            'remaining': remaining, 'failure': child.get('error'), 'input_snapshot': snapshot,
            'input_guidance': guidance, 'input_decisions': decisions, 'guidance': text,
            'rejected_candidate': rejected, 'native_session_id': continuity['session_id'],
            'budget_extended': False, 'permissions_changed': False, 'new_tasks': 0,
            'meaning': '提交后仅接续原规划；后续协作沿用原合同。CLI 内部请求数和账单未知。'}


def dispatch(app, data, scope=None):
    preview = data['action'] == 'cycle.revise_failed_child_preview'
    require(set(data) <= {'action', 'id', 'child_id', 'guidance', 'pin', 'approved', 'request_key'}, '修订参数包含未知字段')
    if preview:
        with app.store.connect() as c:
            c.execute('BEGIN')
            return _preview(app, c, data, scope)
    require(data.get('approved') is True, '需要明确使用原规划剩余额度修订', 'authorization_required', 403)
    key = data.get('request_key')
    require(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,160}', key), '需要稳定修订请求标识')
    require(isinstance(data.get('pin'), dict), '请先预览并核对当前修订输入', 'conflict', 409)
    fingerprint = digest({k: data.get(k) for k in ('id', 'child_id', 'guidance', 'pin')})
    s = app.store
    replay = False
    with s.transaction() as c:
        parent = s.task(data['id'], c)
        project = app.access(s.get(parent['project_id'], connection=c), scope)
        require(not project['archived'] and (scope is None or parent['project_id'] in scope), '无权修订此协作', 'forbidden', 403)
        request = 'cycle_child_revision:' + parent['id'] + ':' + key
        saved = _setting(c, request)
        if saved:
            require(saved['fingerprint'] == fingerprint, '相同请求标识不能登记不同修订', 'conflict', 409)
            result = copy.deepcopy(saved['result'])
            replay = True
        else:
            current = _preview(app, c, data, scope)
            require(current['pin'] == data['pin'], '父子状态、指导或额度已变化；请重新预览', 'conflict', 409)
            from research_partner.packaging.compatibility import require_features
            require_features(c, [FEATURE])
            parent = s.task(data['id'], c)
            child = s.task(data['child_id'], c)
            state = copy.deepcopy(parent['result']['cycle'])
            state['epoch'] += 1
            for ref in state['children']:
                _put(c, 'cycle_epoch:' + ref['key'], state['epoch'])
            s.event(c, 'task.guidance', child['id'], {'text': data['guidance'], 'source': 'user',
                    'source_reference': {'cycle_parent': parent['id'], 'request_key': key},
                    'scope': 'same-task candidate repair; no new permissions'}, 'user')
            inputs = s.execution_inputs(c, child['id'])
            grant = {'input_snapshot': inputs, 'state': 'authorized', 'at': now(),
                     'permissions_changed': False, 'budget_extended': False,
                     'cycle_parent': parent['id'], 'parent_epoch': state['epoch'], 'request_key': key}
            _put(c, 'candidate_revision_authorized:' + child['id'], grant)
            lease = _setting(c, 'execution:' + child['id'])
            if lease:
                lease.update(state='revoked', reason='explicit cycle planner revision', revoked_at=now())
                _put(c, 'execution:' + child['id'], lease)
            c.execute("UPDATE tasks SET status='queued',error=NULL,updated_at=? WHERE id=?", (now(), child['id']))
            state['last_child_revision'] = {'task_id': child['id'], 'request_key': key, 'at': now(),
                                            'rejected_sha256': current['pin']['rejected_sha256'],
                                            'previous_failure': state.pop('last_failure', None)}
            _write(s, c, parent, state)
            s.event(c, 'task.candidate_revision_authorized', child['id'], grant, 'user')
            result = {'saved': True, 'parent_id': parent['id'], 'child_id': child['id'],
                      'request_key': key, 'epoch': state['epoch'], 'input_snapshot': inputs,
                      'remaining_before_execution': current['remaining'], 'budget_extended': False,
                      'permissions_changed': False, 'new_tasks': 0, 'native_session_id': current['native_session_id']}
            _put(c, request, {'fingerprint': fingerprint, 'result': result})
    # A retry acknowledges the original operation, even after a later pause or
    # cancellation; it never changes state or wakes the runner again.
    if not replay and app.runner:
        app.runner.wake()
    return {**result, 'idempotent_replay': replay,
            'current_parent_status': s.task(data['id'])['status'],
            'current_child_status': s.task(data['child_id'])['status']}
