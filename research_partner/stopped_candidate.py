"""Explicitly recover a completed manuscript checkpoint misclassified on stop.

No provider/worker starts here. Ordinary cancellation remains terminal. A
recovered task may subsequently use only this exact completed checkpoint.
"""
import json
from .store import require, digest, encoded, now
from .native_recovery import _directory, _setting
from .providers import Providers, _controlled_file
from .project_management import authority_scope

KEY = 'stopped_candidate_recovery:'
FEATURE = 'stopped_completed_candidate_recovery_v1'


def checkpoint(app, task, c, scope=None, principal=None):
    from . import manuscript_revision as mr
    s = app.store
    principal = principal or {'kind': 'local_operator'}
    project = app.access(s.get(task['project_id'], connection=c), scope)
    require(not project['archived'] and (scope is None or project['id'] in scope),
            '接回需要当前未归档项目的写权限', 'forbidden', 403)
    contract = mr.task_access(app, task, scope, c)
    mr.task_access(app, task, authority_scope(app, principal), c)
    mr.guard(app, task, c)
    s.assert_material_access(c, task['payload'])
    s.assert_feedback_ready(c, task['payload'])
    require(not s.question_blockers(c, task['id']), '必要裁决尚未解决', 'conflict', 409)
    mr.current_annotations(app, contract, c)
    if contract['version'] in {2, 3}:
        objects = mr.round_sources(app, contract, scope, c)
        for target in contract['targets']:
            mr.target_current(contract, target, objects)
    cfg = app.config.get('providers', {}).get(task['payload'].get('provider_id'), {})
    require(cfg.get('authorized') is True and cfg.get('route') == 'codex'
            and cfg.get('transport') != 'app_server_dynamic',
            '仅接回原已授权 Codex CLI 的完整稿件检查点', 'authorization_required', 403)
    model = next((r for r in task['steps'] if r['step_key'] == 'model'), None)
    require(model and model['status'] == 'done', '缺少已完成模型检查点', 'integrity', 409)
    directory = _directory(app, task['id'])
    identity = Providers(app).assert_codex_continuity(task, directory)
    require(identity.get('requires_checkpoint') is True, '缺少原生会话绑定', 'integrity', 409)
    raw = _controlled_file(directory, directory / 'candidate.json')
    require(digest(raw) == model['data']['sha256'], '候选检查点字节已变化', 'integrity', 409)
    receipt = json.loads(_controlled_file(directory, directory / 'provider-receipt.json', 131072))
    saved_receipt = dict(model['data']['provider']); saved_receipt.pop('input_snapshot', None)
    require(receipt == saved_receipt and receipt.get('returncode') == 0,
            '模型检查点与原成功回执不同', 'integrity', 409)
    events = json.loads(_controlled_file(directory, directory / ('codex-events-' + identity['attempt_id'] + '.json')))
    require(events and events[-1].get('type') == 'turn.completed'
            and sum(e.get('type') == 'turn.completed' for e in events) == 1
            and not any(e.get('type') in {'turn.failed', 'error'} for e in events),
            '原调用没有完整成功结束', 'integrity', 409)
    inputs = s.execution_inputs(c, task['id'])
    require(model['data'].get('input_snapshot') == inputs
            and (_setting(c, 'candidate_revision_authorized:' + task['id']) or {}).get('state') != 'authorized',
            '生成后的指导或修订许可已变化；此入口不调用模型', 'candidate_revision_required', 409)
    mr.validate(json.loads(raw), task)
    return {'candidate_sha256': digest(raw), 'model_sha256': digest(model),
            'payload_sha256': digest(task['payload']), 'input_snapshot': inputs,
            'native_identity': identity, 'provider_receipt_sha256': digest(receipt)}


def cached_only(app, task, c):
    """Fence ordinary resume and the actual execute boundary; never spend again."""
    proof = _setting(c, KEY + task['id'])
    if proof:
        current = checkpoint(app, task, c)
        require(current == proof['checkpoint'],
                '接回后检查点或输入已变化；禁止再次分派', 'candidate_revision_required', 409)


def inspect(app, data, scope, principal, c):
    s = app.store; task = s.task(data['id'], c)
    require(task['status'] == 'cancelled' and task.get('error') == '执行服务已停止'
            and task['result'] == {'failure_code': 'cancelled', 'details': {}},
            '仅接回服务停止竞争造成的技术取消，不接续用户取消或其他结果', 'conflict', 409)
    events = [s.unpack(r) for r in c.execute('SELECT * FROM events WHERE object_id=? ORDER BY seq', (task['id'],))]
    starts = [r for r in events if r['kind'] == 'task.started']
    require(starts, '缺少原执行身份', 'integrity', 409)
    tail = [r for r in events if r['seq'] > starts[-1]['seq']]
    require(tail and tail[-1]['kind'] == 'task.cancelled' and tail[-1]['actor'] == 'runtime'
            and tail[-1]['data'] == {'error': '执行服务已停止'}
            and not any(r['kind'] == 'task.paused' or r['data'].get('operation') in {'pause', 'cancel'}
                        for r in tail), '用户停止或历史事件不符合技术接回条件', 'conflict', 409)
    lease = _setting(c, 'execution:' + task['id']) or {}
    # stop() may revoke the lease after the worker's cancellation update, but
    # before loop.finally marks it finished. Both schedules are service stop;
    # user cancel and general startup recovery revocations remain ineligible.
    closed_lease = (lease.get('state') == 'finished' or
                    (lease.get('state') == 'revoked' and lease.get('reason') == 'runtime stopped'))
    require(closed_lease and isinstance(lease.get('token'), str)
            and lease['token'] == starts[-1]['data'].get('execution_token'),
            '原执行尚未完整结束或租约身份不符', 'conflict', 409)
    directory = _directory(app, task['id'])
    checkpoint_value = checkpoint(app, task, c, scope, principal)
    invocation = _setting(c, 'provider_invocations:' + task['id'])
    require(type(invocation) is int and invocation == 1, '仅核对首个已结束调用', 'conflict', 409)
    finished = json.loads(_controlled_file(directory, directory / 'process-1.finished.json', 65536))
    started = json.loads(_controlled_file(directory, directory / 'process-1.started.json', 65536))
    require(finished.get('state') == 'finished' and finished.get('returncode') == 0
            and finished.get('task_id') == task['id'] and finished.get('execution_token') == lease.get('token')
            and started.get('state') == 'running' and started.get('cwd') == str(directory)
            and all(key in started and finished.get(key) == started[key] for key in
                    ('pid', 'start_ticks', 'uid', 'command_sha256', 'argv', 'cwd', 'task_id', 'execution_token', 'process_index')),
            '原进程完成回执与租约不符', 'integrity', 409)
    from .runtime import process_identity
    live = process_identity(finished['pid'])
    require(live is None or live.get('start_ticks') != finished['start_ticks'],
            '原进程身份仍在，不能接回', 'conflict', 409)
    pin = {'task_sha256': digest(task), 'checkpoint': checkpoint_value,
           'last_event_sha256': digest(tail[-1]), 'finished_sha256': digest(finished)}
    return task, pin


def dispatch(app, data, scope, principal):
    preview = data['action'].endswith('_preview')
    allowed = {'action', 'id'} if preview else {'action', 'id', 'pin', 'approved', 'reason', 'request_key'}
    require(set(data) == allowed, '接回请求字段不完整或越界')
    principal = principal or {'kind': 'local_operator'}
    require(scope is None or principal.get('kind') != 'local_operator', '需要当前操作者身份', 'forbidden', 403)
    if app.config.get('development_budget'):
        from .development_budget import Budget
        Budget(app.config['development_budget']).check()
    s = app.store
    if preview:
        with s.connect() as c:
            c.execute('BEGIN'); task, pin = inspect(app, data, scope, principal, c)
        return {'ready': True, 'task_id': task['id'], 'pin': pin, 'new_model_requests': 0,
                'source_changed': False, 'next_action': 'task.recover_stopped_candidate'}
    require(data['approved'] is True and isinstance(data['reason'], str) and 0 < len(data['reason'].strip()) <= 2000,
            '需要明确检查已保存输出并给出接回理由', 'authorization_required', 403)
    require(isinstance(data['request_key'], str) and 0 < len(data['request_key']) <= 180, '需要稳定请求标识')
    fingerprint = digest({'request': data, 'principal': principal})
    with s.transaction() as c:
        task = s.task(data['id'], c)
        from . import manuscript_revision as mr
        mr.task_access(app, task, scope, c); mr.task_access(app, task, authority_scope(app, principal), c)
        previous = _setting(c, KEY + task['id'])
        if previous:
            require(previous['request_sha256'] == fingerprint, '同任务已接回其他输入', 'conflict', 409)
            return previous['receipt']
        task, pin = inspect(app, data, scope, principal, c)
        require(encoded(data['pin']) == encoded(pin), '任务或候选已改变，请重新预览', 'conflict', 409)
        from .compatibility import require_features
        require_features(c, [FEATURE])
        receipt = {'task_id': task['id'], 'status': 'waiting_input', 'new_model_requests': 0,
                   'automatically_resumed': False, 'source_changed': False, 'next_action': 'task.control'}
        proof = {'checkpoint': pin['checkpoint'], 'pin': pin, 'request_sha256': fingerprint,
                 'original_task': task, 'reason': data['reason'], 'principal': principal,
                 'at': now(), 'receipt': receipt}
        c.execute('INSERT INTO kv VALUES(?,?)', (KEY + task['id'], encoded(proof)))
        c.execute("UPDATE tasks SET status='waiting_input',error=?,updated_at=? WHERE id=?",
                  ('已明确接回服务中断前完成的候选；普通继续只使用此检查点', now(), task['id']))
        s.event(c, 'task.stopped_candidate_recovered', task['id'],
                {'pin': pin, 'original_status': task['status'], 'reason': data['reason'], 'new_model_requests': 0}, mr.actor(principal))
    return receipt
