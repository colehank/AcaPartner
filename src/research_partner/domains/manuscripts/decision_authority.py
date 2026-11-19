"""Explicit, one-batch decisions on an existing candidate after grant removal.

These records never authorize a model, Runtime continuation or publication.
The existing restore grant prefix also revokes them on the next restore.
"""
import copy

from research_partner.storage.store import Problem, digest, now, require
from research_partner.domains.workspace.management import authority_scope, generation


def _key(task, record):
    return 'grant:decision:' + task['id'] + ':' + record['proposal_sha256']


def _context(app, task, contract, record, state, principal, scope, c, *, prewritten=None):
    from research_partner.domains.manuscripts import revision as mr
    require(principal is not None, '重新授权需要当前操作者身份', 'forbidden', 403)
    require(contract['version'] in {2, 3}, '此入口仅支持整轮固定候选', 'unsupported_action', 409)
    require(mr.setting(c, 'grant:' + task['id']) is None,
            '原执行授权仍存在；不能替代或绕过失效授权', 'execution_grant_present', 409)
    require(digest(contract) == task['payload'].get('revision_contract_sha256') == record['contract_sha256'],
            '原合同摘要不符', 'integrity', 409)
    require(record['task_id'] == task['id'] and digest({k: record[k] for k in mr.IMMUTABLE}) == record['proposal_sha256'],
            '候选完整性不符', 'integrity', 409)
    require(task['status'] in {'generated', 'review'} and not state['settled'],
            '此任务已撤回、结束或尚无可决定候选', 'proposal_superseded', 409)
    pointer = task['result'].get(mr.KIND, {})
    require(pointer.get('candidate_sha256') == record['candidate_sha256'] and pointer.get('proposal_sha256') == record['proposal_sha256'],
            '较新候选已取代本候选', 'proposal_superseded', 409)
    require(record['generation'] == generation(app.store, task, c),
            '模型或输入代次已改变；请保留旧候选', 'proposal_superseded', 409)
    model = next(step for step in task['steps'] if step['step_key'] == 'model')
    require(model['data'].get('sha256') == record['candidate_sha256'] and
            model['data'].get('provider') == record['provider_receipt'] and
            record['provider_receipt'].get('route') in {'codex', 'deepseek_harness'} and
            isinstance(record['provider_receipt'].get('session_id'), str) and record['provider_receipt']['session_id'],
            '候选缺少同一原生模型检查点', 'integrity', 409)
    require(task['result'].get('provider') == record['provider_receipt'] and record['proposer'] == {
                'role': 'agent', 'provider_id': task['payload']['provider_id'],
                'route': record['provider_receipt']['route'], 'session_id': record['provider_receipt']['session_id'],
                'task_id': task['id']}, '模型生产者与原候选不符', 'integrity', 409)
    objects = mr.round_sources(app, contract, scope, c)
    mr.round_sources(app, contract, authority_scope(app, principal), c)
    from research_partner.domains.collaboration.review import load, assert_round_binding
    rounds = [r for r in load(app, {'id': task['project_id']}, c).get('rounds', []) if r['task_id'] == task['id']]
    require(len(rounds) <= 1, '意见回合身份重复', 'integrity', 409)
    binding = None
    if rounds:
        original = rounds[0]
        require([i['id'] for i in original['opinions']] == [i['id'] for i in contract['opinions']] and
                all(i['text'] == o['text'] for i, o in zip(original['opinions'], contract['opinions'])),
                '原意见回合与合同不符', 'integrity', 409)
        binding = {'project_id': task['project_id'], 'round_id': original['snapshot']['id'],
                   'snapshot_sha256': digest(original['snapshot'])}
        assert_round_binding(app, binding, c)
    revisions = {ident: obj['revision'] for ident, obj in objects.items()}
    # The file/SQL journal has already projected these main figures inside this
    # same transaction. Decision authority still belongs to the approved base,
    # not the uncommitted result of this very decision. This context is private
    # to the journal callback; public request fields cannot supply it.
    main_ids = {t['target']['object_id'] for t in contract['targets']
                if t['target'].get('kind') == 'figure' and t['target'].get('field') == 'slot_layout'}
    for ident, entry in (prewritten or {}).items():
        require(contract['version'] == 3 and ident in main_ids and ident in objects
                and isinstance(entry, dict) and set(entry) == {'base', 'written'},
                '决定授权的事务前主图身份无效', 'integrity', 409)
        base, written = entry['base'], entry['written']
        require(base.get('id') == ident and written.get('id') == ident
                and type(base.get('revision')) is int
                and written.get('revision') == base['revision'] + 1
                and digest(objects[ident]) == digest(written)
                and digest(app.store.get(ident, base['revision'], connection=c)) == digest(base),
                '决定授权的原主图与本事务实际投影不符', 'integrity', 409)
        revisions[ident] = base['revision']
    return revisions, binding


def eligibility(app, task, contract, record, state, principal, scope, c):
    """Read-only availability; no grant is produced merely by viewing a Task."""
    if not record or contract['version'] not in {2, 3}:
        return {'can_authorize_decisions': False, 'authorization_block_code': 'candidate_unavailable'}
    try:
        _context(app, task, contract, record, state, principal, scope, c)
    except Problem as error:
        return {'can_authorize_decisions': False, 'authorization_block_code': error.code}
    return {'can_authorize_decisions': True, 'authorization_block_code': None}


def authorize(app, data, principal, scope, c, task, contract, record, state):
    from research_partner.domains.manuscripts import revision as mr
    require(set(data) <= {'action', 'task_id', 'candidate_sha256', 'proposal_sha256', 'contract_sha256',
                         'expected_decision_version', 'expected_target_revisions', 'approved', 'request_key'},
            '候选授权包含未支持字段')
    require(data.get('approved') is True, '需要明确授权审阅此固定候选', 'authorization_required', 403)
    require(data.get('candidate_sha256') == record['candidate_sha256'] and
            data.get('proposal_sha256') == record['proposal_sha256'] and data.get('contract_sha256') == record['contract_sha256'],
            '请重新核对完整固定候选身份', 'conflict', 409)
    revisions, binding = _context(app, task, contract, record, state, principal, scope, c)
    key = data.get('request_key')
    require(isinstance(key, str) and 0 < len(key) <= 180, '需要稳定的授权请求标识')
    fingerprint = digest({'data': data, 'principal': principal})
    previous = mr.setting(c, 'decision_authorization_receipt:' + task['id'] + ':' + key)
    if previous:
        require(previous['input_sha256'] == fingerprint, '同一授权请求内容或身份已改变', 'idempotency_conflict', 409)
        require(mr.setting(c, _key(task, record)) == previous['grant'],
                '原审阅授权已撤回；请明确重新授权', 'authorization_required', 403)
        return previous['receipt']
    require(type(data.get('expected_decision_version')) is int and data['expected_decision_version'] == state['version'],
            '决定状态已改变，请重新读取', 'conflict', 409)
    expected = data.get('expected_target_revisions')
    require(isinstance(expected, dict) and expected == revisions and all(type(v) is int for v in expected.values()),
            '稿件或笔记版本已改变，请重新读取', 'conflict', 409)
    grant = {'purpose': 'candidate_decision_only', 'task_id': task['id'], 'proposal_sha256': record['proposal_sha256'],
             'candidate_sha256': record['candidate_sha256'], 'contract_sha256': record['contract_sha256'],
             'generation': copy.deepcopy(record['generation']), 'principal': copy.deepcopy(principal),
             'decision_version': state['version'], 'target_revisions': revisions, 'desk_review_round': binding,
             'authorized_at': now()}
    receipt = {'authorized': True, 'task_id': task['id'], 'proposal_sha256': record['proposal_sha256'],
               'decision_version': state['version'], 'operator': mr.actor(principal),
               'execution_authorized': False, 'source_changed': False}
    mr.put(c, _key(task, record), grant)
    mr.put(c, 'decision_authorization_receipt:' + task['id'] + ':' + key,
           {'input_sha256': fingerprint, 'grant': grant, 'receipt': receipt})
    app.store.event(c, mr.KIND + '.decisions_authorized', task['id'], receipt, mr.actor(principal))
    return receipt


def guard(app, task, record, principal, c, *, prewritten=None):
    from research_partner.domains.manuscripts import revision as mr
    contract = mr.task_access(app, task, None, c)
    state = mr.setting(c, 'decisions:' + record['proposal_sha256'])
    revisions, binding = _context(app, task, contract, record, state, principal, None, c, prewritten=prewritten)
    grant = mr.setting(c, _key(task, record))
    require(grant and grant.get('purpose') == 'candidate_decision_only' and grant.get('principal') == principal and
            grant.get('task_id') == task['id'] and grant.get('proposal_sha256') == record['proposal_sha256'] and
            grant.get('candidate_sha256') == record['candidate_sha256'] and grant.get('contract_sha256') == record['contract_sha256'] and
            grant.get('generation') == record['generation'] and grant.get('desk_review_round') == binding and
            grant.get('decision_version') == state['version'] and grant.get('target_revisions') == revisions,
            '恢复后的固定候选需要当前操作者重新授权本次审阅决定', 'decision_authorization_required', 403)
    return grant
