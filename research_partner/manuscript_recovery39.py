"""Explicit zero-dispatch registration of an already recorded native revision.

No model checkpoint is fabricated, no native file is modified, and the failed
provider task is not relabelled as a successful generation. Source application
continues through the ordinary exact manuscript decision contract.
"""
import copy
import json
from .store import require, digest, encoded, now
from . import manuscript_revision as mr
from .project_management import authority_scope
from .native_recovery import _directory, _setting
from .providers import _native_checkpoint, _native_candidate
from .native_accounting import accounting, public_accounting
from .commission import candidate_input_snapshot

PREFIX = 'manuscript_recovery39:'
ORIGIN = 'technical_zero_dispatch_recovery'


def _access(app, c, task, scope, principal):
    contract = mr.task_access(app, task, scope, c)
    mr.task_access(app, task, authority_scope(app, principal), c)
    grant = mr.guard(app, task, c)
    project = app.access(app.store.get(task['project_id'], connection=c), scope)
    require(not project['archived'] and (scope is None or project['id'] in scope), '恢复需要当前未归档项目的写权限', 'forbidden', 403)
    cfg = app.config.get('providers', {}).get(task['payload'].get('provider_id'), {})
    require(cfg.get('authorized') is True and cfg.get('route') == 'deepseek_harness', '原提供者授权或原生路线已撤回', 'authorization_required', 403)
    return contract, grant


def _inputs(app, c, task):
    app.store.assert_material_access(c, task['payload'])
    app.store.assert_feedback_ready(c, task['payload'])
    require(not app.store.question_blockers(c, task['id']), '必要裁决尚待处理', 'candidate_revision_required', 409)
    return app.store.execution_inputs(c, task['id'])


def _execution_identity(task):
    return digest({k: task[k] for k in ('payload', 'attempts', 'steps')})


def _inspect(app, c, data, scope, principal):
    task = app.store.task(data.get('task_id'), c)
    contract, grant = _access(app, c, task, scope, principal)
    require(task['status'] in {'failed', 'waiting_resource'}, '仅接回已停止的失败或资源等待任务；不继续暂停、取消或在途任务', 'cancelled', 409)
    require(not task['result'].get(mr.KIND) and not task['result'].get('manuscript_recovery'), '此任务已有文稿候选或接回记录', 'conflict', 409)
    lease = _setting(c, 'execution:' + task['id'])
    require(not lease or lease.get('state') != 'active', '原执行租约仍在；接回不清租约或停止进程', 'conflict', 409)
    extension = _setting(c, 'budget_extension:' + task['id']) or {}
    require(not extension.get('invocations') and not extension.get('seconds'), '本入口不接受已扩容的任务', 'budget_exhausted', 409)
    current_inputs = _inputs(app, c, task)
    mr.current_annotations(app, contract, c)
    directory = _directory(app, task['id'])
    lock = directory / 'instance/launch.lock'
    require(not lock.exists() and not lock.is_symlink(), '原生执行锁仍在；接回不清锁', 'conflict', 409)
    receipt = _native_checkpoint(directory / 'instance')
    usage = accounting(app.store, task, c)
    require(usage['status'] == 'verified' and 'durable_anchor' in usage['sources'], '缺少数据库原生用量锚点', 'native_accounting_integrity', 409)
    require(receipt.get('session_id') == usage['session_id'] and receipt.get('usage') == usage['usage'], '原生文件回执与数据库用量不一致', 'native_accounting_integrity', 409)
    selected = _native_candidate(task, directory, receipt, allow_budget_tail=True, allow_bookkeeping_tail=True)
    require(selected is not None, '本轮没有成功登记的原生 JSON 候选；不从聊天或截断输出制造候选', 'candidate_checkpoint_invalid', 409)
    inputs = candidate_input_snapshot(app.store, task, selected['receipt'].get('input_provenance'))
    require(inputs == current_inputs, '候选产生后回答或指导已变化', 'candidate_revision_required', 409)
    raw = selected['text'].encode('utf-8')
    from .native_json_repair import inspect_syntax
    candidate, output, changes, syntax_error, suggestion = inspect_syntax(raw, {'kind': 'none'})
    require(candidate is not None and syntax_error is None and output == raw and not changes, '已登记候选 JSON 无效；此入口不修补候选字节', 'invalid_model_output', 422)
    candidate = mr.validate(candidate, task)
    objects = mr.round_sources(app, contract, scope, c) if contract['version'] in {2, 3} else {contract['object_id']: mr.source(app, contract['object_id'], scope, c)}
    pin = {'version': 1, 'task_id': task['id'], 'task_sha256': digest(task), 'grant_sha256': digest(grant),
           'execution_identity': _execution_identity(task), 'input_snapshot': inputs, 'revision_contract_sha256': digest(contract),
           'native_contract_sha256': usage['contract_sha256'], 'native_candidate_sha256': digest(raw),
           'native_receipt_sha256': digest(selected['receipt']), 'usage_sha256': digest(usage['usage']),
           'registered_result_seq': selected['receipt']['candidate']['result_seq'], 'session_id': usage['session_id'],
           'current_objects': {ident: {'revision': obj['revision'], 'sha256': digest(obj)} for ident, obj in objects.items()}}
    return {'task': task, 'contract': contract, 'candidate': candidate, 'raw': raw, 'receipt': selected['receipt'], 'usage': usage, 'pin': pin}


def is_current_recovery(app, task, record, c):
    """Gate only a sealed recovery proposal; no alternate native validation path."""
    identity = record.get('generation', {}).get('recovery_id')
    if not identity:
        return False
    proof = _setting(c, PREFIX + 'proof:' + identity)
    require(proof and proof.get('origin') == ORIGIN and proof.get('recovery_id') == identity
            and digest({k: v for k, v in proof.items() if k != 'proof_sha256'}) == proof.get('proof_sha256')
            and task['result'].get('manuscript_recovery') == proof
            and record['proposal_sha256'] == proof['proposal_sha256']
            and record['candidate_sha256'] == proof['candidate_sha256']
            and record['provider_receipt'] == proof['provider_receipt']
            and record['generation'] == proof['generation'], '接回提案缺少匹配的不可变原生收据', 'integrity', 409)
    require(task['status'] in {'failed', 'waiting_resource', 'review', 'deliverable'}
            and task['result'].get(mr.KIND, {}).get('proposal_sha256') == record['proposal_sha256']
            and _execution_identity(task) == proof['execution_identity'], '任务执行或当前接回候选已变化', 'proposal_superseded', 409)
    _access(app, c, task, None, {'kind': 'local_operator'})
    require(_inputs(app, c, task) == proof['generation']['input_snapshot'], '候选产生后回答或指导已变化', 'proposal_superseded', 409)
    lease = _setting(c, 'execution:' + task['id'])
    require(not lease or lease.get('state') != 'active', '任务已开始新的执行', 'proposal_superseded', 409)
    usage = accounting(app.store, task, c)
    require(usage['status'] == 'verified' and digest(usage['usage']) == proof['usage_sha256'], '原生用量已变化', 'proposal_superseded', 409)
    return True


def dispatch(app, data, scope=None, principal=None):
    principal = principal or {'kind': 'local_operator'}
    require(scope is None or principal.get('kind') != 'local_operator', '受限操作需要可核对的当前身份', 'forbidden', 403)
    action = data.get('action')
    require(action in {'manuscript.revision.recover_preview', 'manuscript.revision.recover'}, '不支持的候选恢复操作')
    allowed = {'action', 'task_id'} if action.endswith('_preview') else {'action', 'task_id', 'pin', 'approved', 'reason', 'request_key'}
    require(not (set(data) - allowed), '接回请求含未授权字段')
    s = app.store
    if action.endswith('_preview'):
        with s.connect() as c:
            c.execute('BEGIN')
            value = _inspect(app, c, data, scope, principal)
        return {'ready': True, 'task_id': value['task']['id'], 'task_status': value['task']['status'], 'task_error': value['task']['error'],
                'pin': value['pin'], 'candidate': value['candidate'], 'raw_candidate_text': value['raw'].decode(),
                'provider_receipt': value['receipt'], 'native_accounting': public_accounting(value['usage']),
                'origin': ORIGIN, 'new_model_requests': 0, 'source_changed': False, 'scientific_approval': False, 'user_acceptance': False}
    require(data.get('approved') is True, '需要明确选择登记既存候选；不会调用模型', 'authorization_required', 403)
    require(isinstance(data.get('reason'), str) and 0 < len(data['reason'].strip()) <= 2000, '接回需要具体理由')
    require(isinstance(data.get('request_key'), str) and 0 < len(data['request_key']) <= 180, '接回需要稳定请求标识')
    fingerprint = digest({'data': data, 'principal': principal}); request_key = PREFIX + 'request:' + data['request_key']
    with s.transaction() as c:
        previous = _setting(c, request_key)
        if previous:
            require(previous['input_sha256'] == fingerprint, '重复接回请求内容不同', 'idempotency_conflict', 409)
            _access(app, c, s.task(data['task_id'], c), scope, principal)
            return previous['result']
        value = _inspect(app, c, data, scope, principal)
        require(isinstance(data.get('pin'), dict) and encoded(data['pin']) == encoded(value['pin']), '候选字节、预览、来源或任务状态已变化，请重新读取', 'conflict', 409)
        from .compatibility import require_features
        require_features(c, ['native_manuscript_recovery_v1'])
        task = value['task']; contract = value['contract']; candidate = value['candidate']; pin = value['pin']; sha = pin['native_candidate_sha256']
        identity = digest({'task_id': task['id'], 'pin': pin, 'operator': mr.actor(principal)})
        generation = {'recovery_id': identity, 'input_snapshot': pin['input_snapshot'], 'native_receipt_sha256': pin['native_receipt_sha256']}
        immutable = {'version': contract['version'], 'task_id': task['id'], 'candidate': candidate, 'candidate_sha256': sha,
                     'proposer': {'role': 'agent', 'provider_id': task['payload']['provider_id'], 'route': 'deepseek_harness', 'session_id': pin['session_id'], 'task_id': task['id']},
                     'provider_receipt': value['receipt'], 'contract_sha256': task['payload']['revision_contract_sha256'], 'generation': generation,
                     'changes': copy.deepcopy(candidate['changes']) if contract['version'] in {2, 3} else [
                         {'id': item['block_id'], 'before': next(b['text'] for b in contract['selected_blocks'] if b['id'] == item['block_id']), 'after': item['text'], 'reason': item['reason']} for item in candidate['changes']]}
        proposal_sha = digest(immutable)
        asset = s.add_asset(value['raw'], 'native-manuscript-' + task['id'] + '.json', 'application/json',
                            {'project_id': task['project_id'], 'source_task_id': task['id'], 'native_candidate': True, 'technical_recovery': True}, connection=c)
        proof = {'version': 1, 'origin': ORIGIN, 'recovery_id': identity, 'task_id': task['id'], 'candidate_sha256': sha,
                 'candidate_asset_sha256': asset['sha'], 'proposal_sha256': proposal_sha, 'provider_receipt': value['receipt'],
                 'execution_identity': pin['execution_identity'], 'generation': generation, 'pin': pin, 'usage_sha256': pin['usage_sha256'],
                 'operator': mr.actor(principal), 'reason': data['reason'], 'at': now(),
                 'original_failure': {k: copy.deepcopy(task[k]) for k in ('status', 'error', 'result', 'attempts', 'updated_at')},
                 'new_model_requests': 0, 'budget_reset': False, 'provider_success': False, 'source_changed': False,
                 'scientific_approval': False, 'user_acceptance': False, 'annotations_automatically_resolved': False}
        proof['proof_sha256'] = digest(proof)
        record = {**immutable, 'proposal_sha256': proposal_sha, 'proposed_at': now()}
        mr.put(c, 'proposal:' + task['id'] + ':' + proposal_sha, record)
        mr.put(c, 'candidate:' + task['id'] + ':' + sha, proposal_sha)
        mr.put(c, 'decisions:' + proposal_sha, {'version': 0, 'changes' if contract['version'] in {2, 3} else 'blocks': {}, 'receipts': [], 'settled': False})
        result = {**task['result'], mr.KIND: {'candidate_sha256': sha, 'proposal_sha256': proposal_sha}, 'manuscript_recovery': proof}
        c.execute('UPDATE tasks SET result=?,updated_at=? WHERE id=?', (encoded(result), now(), task['id']))
        response = {'task_id': task['id'], 'status': task['status'], 'candidate_sha256': sha, 'proposal_sha256': proposal_sha,
                    'recovery': proof, 'new_model_requests': 0, 'source_changed': False, 'next_action': 'manuscript.revision.view'}
        c.execute('INSERT INTO kv VALUES(?,?)', (PREFIX + 'proof:' + identity, encoded(proof)))
        c.execute('INSERT INTO kv VALUES(?,?)', (request_key, encoded({'input_sha256': fingerprint, 'result': response})))
        s.event(c, 'manuscript_revision.native_candidate_recovered', task['id'], proof, mr.actor(principal))
    return response
