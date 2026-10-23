"""Selected-paragraph revision proposals, with explicit operator decisions.

Model completion only publishes a candidate. Neither candidate generation nor an
operator's engineering review claims scientific approval or resolves comments.
"""
from __future__ import annotations
import contextlib
import copy
import json
import math
import re
from .store import Problem, require, digest, encoded, now
from .project_management import authority_scope, generation

KIND = 'manuscript_revision'
FEATURE = 'reviewed_manuscript_revision_v1'
FEATURE_V2 = 'reviewed_manuscript_revision_v2'
KEY = KIND + ':'


def setting(c, key, default=None):
    row = c.execute('SELECT value FROM kv WHERE key=?', (KEY + key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(c, key, value):
    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY + key, encoded(value)))


def actor(principal):
    suffix = 'credential:' + principal['credential_sha256'][:16] if principal['kind'] == 'credential' else principal['kind']
    return 'operator:' + suffix


def source(app, ident, scope, c):
    obj = app.access(app.store.get(ident, connection=c), scope)
    require(scope is None or obj['project_id'] in scope, '文稿修订仅在当前可写项目内可见和操作', 'forbidden', 403)
    require(obj['kind'] in {'paper', 'report', 'note'}, '请选择结构化文稿、报告或笔记')
    return obj


def blocks(obj):
    content = obj['content']
    require(obj['kind'] != 'paper' or content.get('paper_source_mode') == 'structured' or
            (not content.get('paper_source_mode') and not str(content.get('latex', '')).strip()),
            '当前论文不是明确的结构稿；请先选择并保存结构稿来源', 'conflict', 409)
    items = content.get('blocks')
    require(isinstance(items, list) and all(isinstance(b, dict) and isinstance(b.get('id'), str) and b['id'] and isinstance(b.get('text'), str) for b in items), '文稿段落需要稳定标识和正文')
    require(len({b['id'] for b in items}) == len(items), '文稿段落标识重复')
    return {b['id']: b for b in items}


def task_access(app, task, scope, c):
    require(task['payload'].get('kind') == KIND, '原任务没有定向文稿修订合同', 'forbidden', 403)
    contract = task['payload']['context'].get(KIND, {})
    require(contract.get('version') in {1, 2, 3} and contract.get('object_id'), '文稿修订合同缺失', 'forbidden', 403)
    source(app, contract['object_id'], scope, c)
    if contract['version'] in {2, 3}:
        round_sources(app, contract, scope, c)
    return contract


def guard(app, task, c):
    contract = task_access(app, task, None, c)
    grant = setting(c, 'grant:' + task['id'])
    require(grant and grant['contract'] == contract and digest(contract) == task['payload'].get('revision_contract_sha256'), '文稿修订合同或授权不符', 'forbidden', 403)
    if grant.get('desk_review_round'):
        from .review_w1b import assert_round_binding
        assert_round_binding(app,grant['desk_review_round'],c)
    if contract['version'] in {2, 3}:
        round_sources(app, contract, authority_scope(app, grant['principal']), c)
    else:
        source(app, contract['object_id'], authority_scope(app, grant['principal']), c)
    return grant


def annotation_content(row):
    # Anchor status can legitimately change after adopting one paragraph. Text,
    # identity and anchor changes are new instructions and fence the old proposal.
    return {k: row[k] for k in ('id', 'object_id', 'revision', 'anchor', 'text', 'created_at')}


def current_annotations(app, contract, c):
    for frozen in contract['annotations']:
        row = c.execute('SELECT * FROM annotations WHERE id=?', (frozen['id'],)).fetchone()
        current = app.store.unpack(row) if row else None
        require(current and annotation_content(current) == annotation_content(frozen) and current['status'] != 'resolved',
                '所选批注已改变或被解决；请保留旧候选并重新委托', 'conflict', 409)


def submit(app, data, scope, principal):
    if data.get('contract_version') in {2, 3}:
        return submit_round(app, data, scope, principal)
    require(set(data) <= {'action', 'object_id', 'expected_revision', 'block_ids', 'annotation_ids', 'request', 'provider_id', 'budget', 'request_key'}, '文稿修订含未支持字段')
    request = data.get('request')
    require(isinstance(request, str) and 0 < len(request.strip()) <= 4000, '请描述具体修订要求（最多4000字）')
    ids, aids = data.get('block_ids'), data.get('annotation_ids', [])
    require(isinstance(ids, list) and 0 < len(ids) <= 24 and all(isinstance(i, str) for i in ids) and len(set(ids)) == len(ids), '请选择1–24个明确段落')
    require(isinstance(aids, list) and len(aids) <= 48 and all(isinstance(i, str) for i in aids) and len(set(aids)) == len(aids), '批注标识需唯一且最多48条')
    require(type(data.get('expected_revision')) is int, '需要已读的文稿版本')
    budget = data.get('budget', {'max_model_calls': 6, 'timeout_seconds': 300})
    require(isinstance(budget, dict) and set(budget) == {'max_model_calls', 'timeout_seconds'} and type(budget.get('max_model_calls')) is int and 1 <= budget['max_model_calls'] <= 20 and type(budget.get('timeout_seconds')) in (int, float) and math.isfinite(budget['timeout_seconds']) and 0 < budget['timeout_seconds'] <= 900, '任务需要1–20次和不超过900秒的有限预算')
    provider = data.get('provider_id') or app.config.get('default_provider')
    require(app.config.get('providers', {}).get(provider, {}).get('route') in {'codex', 'deepseek_harness'}, '请选择已配置的原生模型路线', 'provider_missing', 503)
    key = data.get('request_key')
    require(isinstance(key, str) and 0 < len(key) <= 180, '需要有限且稳定的请求标识')
    spec = {**copy.deepcopy(data), 'provider_id': provider, 'budget': budget, 'principal': principal}
    s = app.store
    with s.transaction() as c:
        obj = source(app, data.get('object_id'), scope, c)
        source(app, obj['id'], authority_scope(app, principal), c)
        previous = setting(c, 'submission:' + key)
        if previous:
            require(previous['input_sha256'] == digest(spec), '重复请求内容或操作者不同', 'idempotency_conflict', 409)
            task = s.task(previous['task_id'], c); task_access(app, task, scope, c)
            return task
        require(obj['revision'] == data['expected_revision'], '文稿已改变；请保存并核对当前版本再提交', 'conflict', 409)
        by_id = blocks(obj)
        require(set(ids) <= set(by_id), '所选段落不在已读版本中', 'conflict', 409)
        selected = [copy.deepcopy(b) for b in obj['content']['blocks'] if b['id'] in ids]
        annotations = []
        for aid in aids:
            row = c.execute('SELECT * FROM annotations WHERE id=?', (aid,)).fetchone()
            a = s.unpack(row) if row else None
            require(a and a['object_id'] == obj['id'] and a['anchor'].get('block_id') in ids and a['status'] not in {'resolved', 'orphaned'}, '批注需属于所选段落且尚未解决', 'conflict', 409)
            quote = a['anchor'].get('quote')
            require(not quote or quote in by_id[a['anchor']['block_id']]['text'], '批注原文已变化；请先重新定位', 'conflict', 409)
            annotations.append(a)
        contract = {'version': 1, 'object_id': obj['id'], 'base_revision': obj['revision'], 'base_sha256': digest(obj), 'kind': obj['kind'], 'title': obj['title'], 'selected_blocks': selected, 'annotations': annotations,
                    'apply': 'explicit operator decisions on exact candidate; current ACL and revision; only selected unchanged paragraph text may be replaced; comments never automatically resolved'}
        payload = {'kind': KIND, 'project_id': obj['project_id'], 'target_id': None, 'request': request.strip(), 'provider_id': provider, 'budget': budget, 'depends_on': [], 'authorization': {}, 'priority': 0,
                   'revision_contract_sha256': digest(contract), 'context': {'output': KIND, 'materials': [], KIND: contract, 'constraints': 'Only propose text for selected stable paragraph IDs. No title, new blocks, scientific computations, external tools, source or citation changes. Operator review required before any source write.'}}
        require(len(encoded(payload).encode()) <= 96000, '所选正文与批注超过有限上下文，请减少选择；不会截断', 'context_limit', 413)
        from .compatibility import require_features
        require_features(c, [FEATURE, 'bounded_growth_evidence_v1', 'reviewed_growth_comparison_v2'])
        task = s.submit(payload, 'manuscript-revision:' + key, connection=c)
        put(c, 'grant:' + task['id'], {'principal': principal, 'contract': contract, 'issuer': actor(principal), 'at': now()})
        put(c, 'submission:' + key, {'input_sha256': digest(spec), 'task_id': task['id']})
        s.event(c, KIND + '.submitted', task['id'], {'contract_sha256': digest(contract), 'object_id': obj['id'], 'revision': obj['revision'], 'block_ids': ids, 'annotation_ids': aids}, actor(principal))
    if app.runner: app.runner.wake()
    return task


def schema(task):
    require(task and task['payload'].get('kind') == KIND and task['payload'].get('revision_contract_sha256'), '原任务没有定向文稿修订合同', 'forbidden', 403)
    if task['payload']['context'][KIND]['version'] in {2, 3}:
        return round_schema(task)
    return '''Return exactly one JSON object: {"kind":"manuscript_revision","contract_sha256":"supplied revision_contract_sha256","summary":"brief rationale and limits","changes":[{"block_id":"exact selected stable ID","before_sha256":"SHA256 of UTF-8 original paragraph text supplied below","text":"complete proposed replacement paragraph text","reason":"why this addresses the quoted annotation/request"}]}. Changes contain only selected IDs, each at most once. Never return title, other fields, new blocks or unselected text. Preserve empirical values, scope and citations; do not invent evidence or run computations. Returning changes:[] with an explanation is valid when no safe revision is warranted. A candidate is not source application, scientific approval, user acceptance or comment resolution. Maximum replacement length per paragraph 30000 characters, reason 2000, summary 4000. For this editing task, annotations[].anchor.quote is only a short quoted selection and may end mid-sentence. The complete authoritative source is selected_blocks[].text; do not mistake the quote for truncation of that source. Preserve axis names as written; do not invent abbreviation mappings absent from the selected paragraph. Exact original text hashes:\n''' + encoded({b['id']: digest(b['text'].encode()) for b in task['payload']['context'][KIND]['selected_blocks']}) + '\nrevision_contract_sha256=' + task['payload']['revision_contract_sha256']


def validate(candidate, task):
    schema(task)
    if task['payload']['context'][KIND]['version'] in {2, 3}:
        return validate_round(candidate, task)
    bad = lambda ok, message: require(ok, message, 'invalid_model_output', 422)
    bad(isinstance(candidate, dict) and set(candidate) == {'kind', 'contract_sha256', 'summary', 'changes'}, '文稿候选只能包含约定字段')
    bad(candidate['kind'] == KIND and candidate['contract_sha256'] == task['payload']['revision_contract_sha256'], '候选合同身份不符')
    bad(isinstance(candidate['summary'], str) and 0 < len(candidate['summary'].strip()) <= 4000, '候选需明确说明修订或不修改的理由')
    selected = {b['id']: b for b in task['payload']['context'][KIND]['selected_blocks']}
    changes = candidate['changes']; seen = set()
    bad(isinstance(changes, list) and len(changes) <= len(selected), '候选变更数量超出所选段落')
    for item in changes:
        bad(isinstance(item, dict) and set(item) == {'block_id', 'before_sha256', 'text', 'reason'}, '段落候选包含越界字段')
        ident = item['block_id']
        bad(isinstance(ident, str) and ident in selected and ident not in seen, '候选试图改变未选段落或重复段落'); seen.add(ident)
        bad(item['before_sha256'] == digest(selected[ident]['text'].encode()), '候选原文摘要不是冻结版本')
        bad(isinstance(item['text'], str) and len(item['text']) <= 30000 and item['text'] != selected[ident]['text'], '候选替换正文无效或没有改变')
        bad(isinstance(item['reason'], str) and 0 < len(item['reason'].strip()) <= 2000, '段落修订理由无效')
    return copy.deepcopy(candidate)


IMMUTABLE = ('version', 'task_id', 'candidate', 'candidate_sha256', 'proposer', 'provider_receipt', 'contract_sha256', 'generation', 'changes')


def publish(app, task, candidate, receipt, candidate_sha):
    s = app.store; candidate = validate(candidate, task)
    with s.transaction() as c:
        s.assert_execution(c, task['id'], task.get('execution_token')); grant = guard(app, task, c)
        stored = s.task(task['id'], c); model = next((p for p in stored['steps'] if p['step_key'] == 'model'), None)
        require(model and model['status'] == 'done' and model['data']['sha256'] == candidate_sha and model['data']['provider'] == receipt, '文稿候选缺少匹配的模型检查点', 'integrity', 409)
        require(receipt.get('route') in {'codex', 'deepseek_harness'} and isinstance(receipt.get('session_id'), str) and receipt['session_id'], '文稿候选缺少原生会话身份', 'integrity', 409)
        selected = {b['id']: b for b in grant['contract']['selected_blocks']}
        version = grant['contract']['version']
        immutable = {'version': version, 'task_id': task['id'], 'candidate': candidate, 'candidate_sha256': candidate_sha,
                     'proposer': {'role': 'agent', 'provider_id': task['payload']['provider_id'], 'route': receipt['route'], 'session_id': receipt['session_id'], 'task_id': task['id']},
                     'provider_receipt': receipt, 'contract_sha256': task['payload']['revision_contract_sha256'], 'generation': generation(s, stored, c),
                     'changes': copy.deepcopy(candidate['changes']) if version in {2, 3} else [{'id': item['block_id'], 'before': selected[item['block_id']]['text'], 'after': item['text'], 'reason': item['reason']} for item in candidate['changes']]}
        sha = digest(immutable)
        record = setting(c, 'proposal:' + task['id'] + ':' + sha)
        if not record:
            record = {**immutable, 'proposal_sha256': sha, 'proposed_at': now()}
            put(c, 'proposal:' + task['id'] + ':' + sha, record)
            put(c, 'decisions:' + sha, {'version': 0, 'changes' if version in {2, 3} else 'blocks': {}, 'receipts': [], 'settled': False})
            s.event(c, KIND + '.proposed', task['id'], {'proposal_sha256': sha, 'candidate_sha256': candidate_sha, 'proposer': immutable['proposer']}, 'agent:' + receipt['route'] + ':' + receipt['session_id'])
        put(c, 'candidate:' + task['id'] + ':' + candidate_sha, sha)
        result = {KIND: {'candidate_sha256': candidate_sha, 'proposal_sha256': sha}, 'provider': receipt}
        c.execute('UPDATE tasks SET status=?,result=?,error=NULL,updated_at=? WHERE id=?', ('generated', encoded(result), now(), task['id']))
        s.event(c, 'task.generated', task['id'], result, 'runtime')
    return record


def proposal(app, data, scope, c):
    task = app.store.task(data.get('task_id'), c); contract = task_access(app, task, scope, c)
    pointer = task['result'].get(KIND, {})
    candidate_pin = data.get('candidate_sha256')
    require(candidate_pin is None or isinstance(candidate_pin, str) and re.fullmatch(r'[a-f0-9]{64}', candidate_pin), '候选摘要无效')
    pin = data.get('proposal_sha256') or (setting(c, 'candidate:' + task['id'] + ':' + candidate_pin) if candidate_pin else pointer.get('proposal_sha256'))
    require(not candidate_pin or pin, '所选历史候选不存在', 'not_found', 404)
    if not pin: return task, contract, None, None
    require(isinstance(pin, str) and re.fullmatch(r'[a-f0-9]{64}', pin), '提案摘要无效')
    record = setting(c, 'proposal:' + task['id'] + ':' + pin)
    require(record and digest({k: record[k] for k in IMMUTABLE}) == pin, '文稿提案不存在或完整性不符', 'integrity', 409)
    require(not data.get('candidate_sha256') or data['candidate_sha256'] == record['candidate_sha256'], '候选摘要不符', 'conflict', 409)
    return task, contract, record, setting(c, 'decisions:' + pin)


def current_proposal(app, task, record, c, principal=None, *, prewritten=None):
    if setting(c, 'grant:' + task['id']) is not None or principal is None:
        guard(app, task, c)
    else:
        from .manuscript_decision_authority import guard as decision_guard
        decision_guard(app, task, record, principal, c, prewritten=prewritten)
    if record.get('generation', {}).get('recovery_id'):
        from .manuscript_recovery39 import is_current_recovery
        if is_current_recovery(app, task, record, c): return
    require(task['status'] in {'generated', 'review'} and task['result'].get(KIND, {}).get('proposal_sha256') == record['proposal_sha256'] and record['generation'] == generation(app.store, task, c), '当前任务或输入已改变；此旧候选仅供审阅', 'proposal_superseded', 409)


def may_revise(app, task, c):
    pointer = task['result'].get(KIND, {})
    state = setting(c, 'decisions:' + pointer.get('proposal_sha256', ''), {})
    require(not state.get('version'), '此候选已有明确审阅决定；如需再次修订，请从当前稿件重新委托', 'conflict', 409)


def view(app, task, contract, record, state, scope, c, principal=None):
    if contract['version'] in {2, 3}:
        return view_round(app, task, contract, record, state, scope, c, principal)
    obj = source(app, contract['object_id'], scope, c)
    result = {'task_id': task['id'], 'task_status': task['status'], 'task_error': task.get('error'), 'target': {'id': obj['id'], 'title': obj['title'], 'base_revision': contract['base_revision'], 'current_revision': obj['revision']}, 'selected_blocks': contract['selected_blocks'], 'annotations': contract['annotations'], 'proposal': None, 'decision_version': 0, 'can_decide': False, 'block_reason': None}
    if not record: return result
    can = True; reason = None
    try: current_proposal(app, task, record, c)
    except Problem as error: can = False; reason = str(error)
    accept_ready = can
    try: current = blocks(obj)
    except Problem as error: current = {}; accept_ready = False; reason = str(error)
    try: current_annotations(app, contract, c)
    except Problem as error: accept_ready = False; reason = str(error)
    selected = {b['id']: b for b in contract['selected_blocks']}
    changes = []
    for row in record['changes']:
        decided = state['blocks'].get(row['id'])
        conflict = not decided and current.get(row['id']) != selected[row['id']]
        changes.append({**row, 'state': decided['decision'] if decided else 'pending', 'decision_receipt': decided, 'can_accept': accept_ready and not conflict and not decided, 'conflict': bool(conflict), 'current_text': current.get(row['id'], {}).get('text') if conflict else None})
    result.update(proposal={**record, 'changes': changes}, decision_version=state['version'], can_decide=can and not state['settled'], block_reason=reason, decisions=state['receipts'], settled=state['settled'])
    return result


def dispatch(app, data, scope, principal, *, connection=None):
    principal = principal or {'kind': 'local_operator'}
    require(scope is None or principal.get('kind') != 'local_operator', '受限操作需要可核对的当前身份', 'forbidden', 403)
    action = data['action']
    if action == 'manuscript.revision.submit': return submit(app, data, scope, principal)
    require(action in {'manuscript.revision.view', 'manuscript.revision.decide', 'manuscript.revision.authorize_decisions'}, '文稿修订操作不支持')
    s = app.store
    if action == 'manuscript.revision.decide' and connection is None:
        with s.read_snapshot() as reader:
            probe = proposal(app, data, scope, reader)
        if probe[1]['version'] == 3:
            from .manuscript_figure_round import decide
            return decide(app, data, scope, principal)
    with (s.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
        task, contract, record, state = proposal(app, data, scope, c)
        if action == 'manuscript.revision.view': return view(app, task, contract, record, state, scope, c, principal)
        require(record, '候选尚未就绪', 'conflict', 409)
        if action == 'manuscript.revision.authorize_decisions':
            from .manuscript_decision_authority import authorize
            return authorize(app, data, principal, scope, c, task, contract, record, state)
        if contract['version'] in {2, 3}:
            return decide_round(app, data, principal, scope, c, task, contract, record, state)
        require(set(data) <= {'action', 'task_id', 'candidate_sha256', 'proposal_sha256', 'expected_decision_version', 'expected_target_revision', 'decisions', 'request_key'}, '审阅决定包含未支持字段')
        require(data.get('candidate_sha256') == record['candidate_sha256'] and data.get('proposal_sha256') == record['proposal_sha256'], '需要审阅并明确选择同一候选摘要', 'conflict', 409)
        key = data.get('request_key'); require(isinstance(key, str) and 0 < len(key) <= 180, '需要稳定的审阅请求标识')
        source(app, contract['object_id'], authority_scope(app, principal), c)
        fingerprint = digest({'data': data, 'principal': principal})
        previous = setting(c, 'receipt:' + task['id'] + ':' + key)
        if previous:
            require(previous['input_sha256'] == fingerprint, '重复审阅请求内容不同', 'idempotency_conflict', 409)
            return previous['receipt']
        current_proposal(app, task, record, c)
        require(type(data.get('expected_decision_version')) is int and data['expected_decision_version'] == state['version'] and not state['settled'], '审阅决定已改变，请重新读取', 'conflict', 409)
        obj = source(app, contract['object_id'], scope, c)
        require(type(data.get('expected_target_revision')) is int and data['expected_target_revision'] == obj['revision'], '文稿已改变，请重新读取差异', 'conflict', 409)
        decisions = data.get('decisions'); pending = {r['id']: r for r in record['changes'] if r['id'] not in state['blocks']}
        require(isinstance(decisions, list) and len(decisions) <= len(pending) and (decisions or not record['changes']), '需要逐项采用/拒绝，或确认没有变更的候选')
        seen = set(); accepted = []
        for item in decisions:
            require(isinstance(item, dict) and set(item) == {'block_id', 'decision'} and isinstance(item['block_id'], str) and item['block_id'] in pending and item['block_id'] not in seen and item['decision'] in {'accept', 'reject'}, '审阅决定的段落或操作无效')
            seen.add(item['block_id'])
            if item['decision'] == 'accept': accepted.append(item['block_id'])
        content = copy.deepcopy(obj['content'])
        if accepted:
            current_annotations(app, contract, c); current = blocks(obj)
            frozen = {b['id']: b for b in contract['selected_blocks']}
            for ident in accepted:
                require(current.get(ident) == frozen[ident], '所选段落已被修改或移除；请保留用户改动并重新委托', 'conflict', 409, {'block_id': ident})
            for item in content['blocks']:
                if item['id'] in accepted: item['text'] = pending[item['id']]['after']
        result = s.save(obj['id'], obj['revision'], content=content, actor=actor(principal), reason='explicit manuscript review ' + task['id'] + ' proposal ' + record['proposal_sha256'], merge=False, connection=c) if accepted else obj
        receipt = {'task_id': task['id'], 'candidate_sha256': record['candidate_sha256'], 'proposal_sha256': record['proposal_sha256'], 'decision_version': state['version'] + 1, 'decisions': decisions, 'operator': actor(principal), 'at': now(), 'object_id': obj['id'], 'base_revision': obj['revision'], 'result_revision': result['revision'], 'result_sha256': digest(result), 'source_changed': bool(accepted), 'scientific_approval': False, 'user_acceptance': False, 'annotations_automatically_resolved': False}
        for item in decisions: state['blocks'][item['block_id']] = {'decision': 'accepted' if item['decision'] == 'accept' else 'rejected', 'receipt_version': receipt['decision_version'], 'operator': receipt['operator'], 'result_revision': result['revision']}
        state['version'] += 1; state['receipts'].append(receipt); state['settled'] = len(state['blocks']) == len(record['changes'])
        put(c, 'decisions:' + record['proposal_sha256'], state)
        put(c, 'receipt:' + task['id'] + ':' + key, {'input_sha256': fingerprint, 'receipt': receipt})
        pointer = {**task['result'].get(KIND, {}), 'decision_version': state['version'], 'settled': state['settled']}
        c.execute('UPDATE tasks SET status=?,result=?,updated_at=? WHERE id=?', ('deliverable' if state['settled'] else 'review', encoded({**task['result'], KIND: pointer}), now(), task['id']))
        s.event(c, KIND + '.decided', task['id'], receipt, actor(principal))
        return receipt


# Version 2: an opinion round can propose separately reviewable manuscript and
# workshop-note edits. The legacy contract and its immutable records stay v1.
def round_sources(app, contract, scope, c):
    main = source(app, contract['object_id'], scope, c)
    result = {main['id']: main}
    for item in contract['targets']:
        ident = item['target']['object_id']
        if ident in result:
            continue
        if item['target']['kind'] == 'figure':
            require(contract['version'] == 3, '旧回合不能扩为图写入', 'integrity', 409)
            if item['target'].get('field') == 'slot_layout':
                from .manuscript_main_round import writable
            else:
                from .manuscript_figure_round import writable
            result[ident] = writable(app, ident, main['project_id'], scope, c)
            continue
        obj = app.access(app.store.get(ident, connection=c), scope)
        require(scope is None or obj['project_id'] in scope, '章节笔记修订仅在当前可写项目内可见和操作', 'forbidden', 403)
        require(obj['kind'] == 'workshop_note' and obj['project_id'] == main['project_id'], '章节笔记不再属于此项目', 'conflict', 409)
        result[ident] = obj
    return result


def note_binding(main, note):
    from .article_workspace import sections
    content = note['content']
    blocks(main)
    matches = [s for s in sections(main) if s['id'] == content.get('section_id')]
    require(content.get('manuscript_id') == main['id'] and len(matches) == 1 and
            matches[0].get('heading_block_id') == content.get('section_block_id') and
            matches[0]['anchor_valid'],
            '章节笔记与当前稿件章节的稳定关联已改变', 'conflict', 409)
    return {k: content[k] for k in ('manuscript_id', 'section_id', 'section_block_id')}


def target_key(target):
    return encoded(target)


def target_value(obj, target):
    if target.get('kind') == 'figure':
        if target.get('field') == 'slot_layout':
            from .manuscript_main_round import selected_slots
            return copy.deepcopy(obj), encoded(selected_slots(obj, target['slot_ids']))
        from .manuscript_figure_round import selected_overlays
        return copy.deepcopy(obj), encoded(selected_overlays(obj, target['artist_ids']))
    if target.get('field') == 'caption':
        refs = obj['content'].get('components', [])
        require(isinstance(refs, list), '稿内组件格式无效', 'conflict', 409)
        matches = [r for r in refs if isinstance(r, dict) and (r.get('id') or r.get('object_id')) == target['component_id']]
        require(len(matches) == 1 and isinstance(matches[0].get('caption'), str),
                '图注目标需唯一且已保存明确图注；请先定位并保存稿内图注', 'conflict', 409)
        return copy.deepcopy(matches[0]), matches[0]['caption']
    by_id = blocks(obj)
    block = by_id.get(target['block_id'])
    if not target['exists']:
        require(block is None, '拟新增笔记段落的标识已被使用', 'conflict', 409)
        return None, ''
    require(block is not None, '修订目标段落已移除', 'conflict', 409)
    return copy.deepcopy(block), block['text']


def freeze_target(app, raw, main, scope, c, version=2):
    require(isinstance(raw, dict), '修订目标格式无效')
    if raw.get('kind') == 'figure':
        require(version == 3, '图目标需要明确的v3图文回合；旧合同不扩权')
        if raw.get('field') == 'slot_layout':
            from .manuscript_main_round import freeze
            return freeze(app, raw, main, scope, c)
        from .manuscript_figure_round import freeze
        return freeze(app, raw, main, scope, c)
    common = {'object_id', 'expected_revision', 'kind'}
    is_caption = raw.get('field') == 'caption'
    allowed = common | ({'field', 'component_id'} if is_caption else {'block_id', 'exists'})
    require(set(raw) <= allowed and common <= set(raw), '修订目标包含未支持字段')
    ident = raw['object_id']
    require(isinstance(ident, str) and type(raw['expected_revision']) is int, '修订目标需要准确对象和已读版本')
    if raw['kind'] == 'manuscript':
        require(ident == main['id'], '正文和图注只能属于本轮主稿件')
        obj = main
        binding = None
    else:
        require(raw['kind'] == 'workshop_note' and not is_caption, '笔记只支持明确段落文字')
        obj = app.access(app.store.get(ident, connection=c), scope)
        require(scope is None or obj['project_id'] in scope, '章节笔记需当前可写权限', 'forbidden', 403)
        require(obj['kind'] == 'workshop_note' and obj['project_id'] == main['project_id'], '请选择同项目关联的章节工坊笔记')
        binding = note_binding(main, obj)
    require(obj['revision'] == raw['expected_revision'], '修订目标已改变，请重新读取', 'conflict', 409)
    target = {k: raw[k] for k in ('object_id', 'kind')}
    if is_caption:
        require(isinstance(raw.get('component_id'), str) and raw['component_id'], '图注需要稳定的稿内组件标识')
        target.update(field='caption', component_id=raw['component_id'])
        blocks(main)  # LaTeX-only drafts cannot silently receive structured edits.
    else:
        require(isinstance(raw.get('block_id'), str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,180}', raw['block_id']), '段落需要稳定标识')
        exists = raw.get('exists', True)
        require(type(exists) is bool and (exists or raw['kind'] == 'workshop_note'), '仅工坊笔记允许明确新增段落')
        target.update(block_id=raw['block_id'], exists=exists)
    base, text = target_value(obj, target)
    return {'target': target, 'base_revision': obj['revision'], 'base': base, 'before': text, 'binding': binding, 'title': obj['title']}


def submit_round(app, data, scope, principal, *, connection=None, include_artifact_context=False, native_note_snapshot=None):
    from . import manuscript_main_round as main_round
    main_targets = data.get('targets')
    if isinstance(main_targets, list) and any(isinstance(t, dict) and main_round.is_main(t) for t in main_targets) and not main_round.has_session(app):
        require(connection is None, '主图冻结必须先获取定义锁', 'context_preparation', 409)
        obj = source(app, data.get('object_id'), scope, None)
        with main_round.locked(app, obj['project_id']):
            return submit_round(app, data, scope, principal, include_artifact_context=include_artifact_context,
                                native_note_snapshot=native_note_snapshot)
    version = data.get('contract_version', 2)
    require(type(version) is int and version in {2, 3}, '整轮合同版本无效')
    allowed = {'action', 'contract_version', 'object_id', 'expected_revision', 'targets', 'opinions', 'annotation_ids', 'request', 'provider_id', 'budget', 'request_key', 'native_note_refs'}
    if version == 3: allowed.update({'dependency_groups', 'slot_adoptions'})
    require(set(data) <= allowed, '逐条修订回合包含未支持字段')
    request = data.get('request')
    require(isinstance(request, str) and 0 < len(request.strip()) <= 4000, '请描述本轮修订范围（最多4000字）')
    raw_targets, raw_opinions, aids = data.get('targets'), data.get('opinions', []), data.get('annotation_ids', [])
    require(isinstance(raw_targets, list) and 0 < len(raw_targets) <= 48, '请选择1–48个明确文字或图注目标')
    require(isinstance(raw_opinions, list) and len(raw_opinions) <= 48, '每轮最多48条意见')
    require(isinstance(aids, list) and len(aids) <= 48 and all(isinstance(i, str) for i in aids) and len(set(aids)) == len(aids), '批注标识需唯一且最多48条')
    require(type(data.get('expected_revision')) is int, '需要已读的稿件版本')
    budget = data.get('budget', {'max_model_calls': 6, 'timeout_seconds': 300})
    require(isinstance(budget, dict) and set(budget) == {'max_model_calls', 'timeout_seconds'} and type(budget['max_model_calls']) is int and 1 <= budget['max_model_calls'] <= 20 and type(budget['timeout_seconds']) in (int, float) and math.isfinite(budget['timeout_seconds']) and 0 < budget['timeout_seconds'] <= 900, '回合需要1–20次和不超过900秒的有限预算')
    provider = data.get('provider_id') or app.config.get('default_provider')
    require(app.config.get('providers', {}).get(provider, {}).get('route') in {'codex', 'deepseek_harness'}, '请选择已配置的原生模型路线', 'provider_missing', 503)
    key = data.get('request_key')
    require(isinstance(key, str) and 0 < len(key) <= 180, '需要有限且稳定的请求标识')
    spec = {**copy.deepcopy(data), 'provider_id': provider, 'budget': budget, 'principal': principal}
    s = app.store
    # Canonical notes.read maintains its own file/index bookkeeping. Capture
    # before the SQL writer transaction, never nest its write lock. Replayed
    # identical submissions retain their original snapshot instead of reading
    # a later file revision or dispatching another task.
    if 'native_note_refs' in data and native_note_snapshot is None:
        require(connection is None, '原生笔记需在提交写事务之前固定', 'context_preparation', 409)
        if not s.setting(KIND + ':submission:' + key):
            from .native_review_context import freeze_notes
            main = source(app, data.get('object_id'), scope, None)
            native_note_snapshot = freeze_notes(app, main['project_id'], data['native_note_refs'], scope, principal)
    with (s.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
        main = source(app, data.get('object_id'), scope, c)
        previous = setting(c, 'submission:' + key)
        if previous:
            require(previous['input_sha256'] == digest(spec), '重复请求内容或操作者不同', 'idempotency_conflict', 409)
            task = s.task(previous['task_id'], c); task_access(app, task, scope, c)
            round_sources(app, task['payload']['context'][KIND], authority_scope(app, principal), c)
            return task
        require(main['revision'] == data['expected_revision'], '稿件已改变，请保存并核对当前版本', 'conflict', 409)
        blocks(main)
        targets = [freeze_target(app, t, main, scope, c, version) for t in raw_targets]
        visual_ids = [t['target']['object_id'] for t in targets if t['target']['kind'] == 'figure']
        require(len(set(visual_ids)) == len(visual_ids), '同一图需合并为一个明确视觉目标')
        require(len({target_key(t['target']) for t in targets}) == len(targets), '修订目标不能重复')
        by_object = {}
        for t in targets:
            ident = t['target']['object_id']
            require(ident not in by_object or by_object[ident] == t['base_revision'], '同一对象的目标版本不一致')
            by_object[ident] = t['base_revision']
        annotations = {}; opinions = []; opinion_ids = set()

        def add_opinion(item):
            require(isinstance(item, dict) and set(item) <= {'id', 'text', 'annotation_id', 'target_indices'}, '意见字段无效')
            aid = item.get('annotation_id')
            oid = item.get('id', aid)
            require(isinstance(oid, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,180}', oid) and oid not in opinion_ids, '意见需要唯一稳定标识')
            indices = item.get('target_indices')
            require(isinstance(indices, list) and 0 < len(indices) <= len(targets) and all(type(i) is int and 0 <= i < len(targets) for i in indices) and len(set(indices)) == len(indices), '意见需关联本轮明确目标')
            if aid is not None:
                require(isinstance(aid, str) and 'text' not in item and aid not in annotations, '批注原话由服务端读取，每条批注仅收录一次')
                row = c.execute('SELECT * FROM annotations WHERE id=?', (aid,)).fetchone()
                a = s.unpack(row) if row else None
                require(a and isinstance(a['anchor'], dict) and a['status'] not in {'resolved', 'orphaned','text_changed'}, '批注不存在或已经解决／失去锚点，请先明确重新定位', 'conflict', 409)
                from .manuscript_range import annotation_targets, validate_range
                if version == 3 and a['anchor'].get('kind') == 'main_figure_slots':
                    main_round.check_annotation(a, targets, indices)
                elif version == 3 and a['anchor'].get('artist_id'):
                    from .manuscript_figure_round import check_annotation
                    check_annotation(a, targets, indices)
                elif a['anchor'].get('kind')=='manuscript_range':
                    saved=s.get(a['object_id'],connection=c)
                    validate_range(saved['content'].get('blocks',[]),a['anchor'])
                    ids=annotation_targets(a['anchor'])
                    matches=[t for t in targets if t['target']['object_id']==a['object_id'] and t['target'].get('block_id') in ids]
                    require(len(matches)==len(ids) and len(indices)==len(ids) and all(targets[i] in matches for i in indices),
                            '跨段批注必须准确覆盖其全部选区目标','conflict',409)
                    require(all(next(t for t in matches if t['target']['block_id']==segment['block_id'])['before'][segment['start']:segment['end']]==segment['quote'] for segment in a['anchor']['segments']),
                            '跨段批注引文已变化，请重新定位','conflict',409)
                else:
                    matches = [t for t in targets if t['target']['object_id'] == a['object_id'] and
                               (t['target'].get('block_id') == a['anchor'].get('block_id') if a['anchor'].get('block_id') else
                                t['target'].get('component_id') == a['anchor'].get('component_id') and a['anchor'].get('field') == 'caption')]
                    require(matches and any(targets[i] in matches for i in indices), '批注必须定位本条意见的正文、图注或笔记目标', 'conflict', 409)
                    quote = a['anchor'].get('quote')
                    require(quote is None or isinstance(quote, str) and (not quote or any(quote in t['before'] for t in matches)), '批注引文已变化，请先重新定位', 'conflict', 409)
                annotations[aid] = a
                text = a['text']; origin = {'kind': 'annotation', 'annotation_id': aid, 'object_id': a['object_id'], 'revision': a['revision'], 'anchor': a['anchor']}
            else:
                text = item.get('text')
                require(isinstance(text, str) and 0 < len(text.strip()) <= 4000, '手动意见需要准确原话（最多4000字）')
                origin = {'kind': 'manual', 'operator': actor(principal)}
            opinion_ids.add(oid)
            opinions.append({'id': oid, 'text': text, 'source': origin, 'target_indices': indices})

        for item in raw_opinions:
            add_opinion(item)
        for aid in aids:
            if aid in annotations:
                continue
            row = c.execute('SELECT * FROM annotations WHERE id=?', (aid,)).fetchone()
            a = s.unpack(row) if row else None
            require(a and isinstance(a['anchor'], dict), '批注不存在或锚点无效', 'conflict', 409)
            from .manuscript_range import annotation_targets
            indices = [i for i, t in enumerate(targets) if t['target']['object_id'] == a['object_id'] and
                       (t['target'].get('block_id') in annotation_targets(a['anchor']) if a['anchor'].get('block_id') else
                        t['target'].get('component_id') == a['anchor'].get('component_id') and a['anchor'].get('field') == 'caption')]
            if version == 3 and a['anchor'].get('artist_id'):
                from .manuscript_figure_round import annotation_indices
                indices = annotation_indices(a, targets)
            if version == 3 and a['anchor'].get('kind') == 'main_figure_slots':
                indices = main_round.annotation_indices(a, targets)
            add_opinion({'id': aid, 'annotation_id': aid, 'target_indices': indices})
        require(0 < len(opinions) <= 48, '请明确提供本轮1–48条意见；不会从总要求预填回应')
        require(set(i for opinion in opinions for i in opinion['target_indices']) == set(range(len(targets))), '每个修订目标都需关联具体意见')
        contract = {'version': version, 'object_id': main['id'], 'base_revision': main['revision'], 'base_sha256': digest(main), 'kind': main['kind'], 'title': main['title'],
                    'targets': targets, 'opinions': opinions, 'annotations': list(annotations.values()),
                    'selected_blocks': [t['base'] for t in targets if t['target']['kind'] == 'manuscript' and t['target'].get('block_id')],
                    'apply': 'Explicit per-change operator acceptance only; manuscript and workshop-note changes are independent. Current ACL, object CAS and unchanged target required. No automatic comment resolution, human approval or scientific execution.'}
        if version == 3:
            from .manuscript_figure_round import freeze_groups
            contract['dependency_groups'] = freeze_groups(data.get('dependency_groups', []), targets)
            if data.get('slot_adoptions'):
                from .manuscript_slot_adoption import freeze as freeze_slots
                contract['slot_adoptions'] = freeze_slots(app, data['slot_adoptions'], targets, contract['dependency_groups'], main['project_id'], c)
            elif 'slot_adoptions' in data:
                require(data['slot_adoptions'] == [], '图位采用需明确列表')
            contract['apply'] = 'Explicit decisions on typed text and selected registered visual targets; frozen dependency groups are atomic. Current ACL/source/object CAS and unsaved-draft protection. Rendering remains explicitly authorized and staged before a common commit. No scientific execution or automatic resolution.'
        # Freeze the complete actual adopted manuscript as reading context;
        # allowed candidate changes still target only the explicit selections.
        if native_note_snapshot is not None:
            from .native_review_context import note_ref
            require(native_note_snapshot['project_id'] == main['project_id'] and
                    [note_ref(note) for note in native_note_snapshot['notes']] == data['native_note_refs'],
                    '原生保存版与明确选择的引用不同', 'source_mismatch', 409)
        native_notes = native_note_snapshot is not None and bool(native_note_snapshot['notes'])
        if include_artifact_context or native_notes:contract['artifact_snapshot']=copy.deepcopy(main)
        if native_notes:contract['native_note_context']=copy.deepcopy(native_note_snapshot)
        round_sources(app, contract, authority_scope(app, principal), c)
        payload = {'kind': KIND, 'project_id': main['project_id'], 'target_id': None, 'request': request.strip(), 'provider_id': provider, 'budget': budget, 'depends_on': [], 'authorization': {}, 'priority': 0,
                   'revision_contract_sha256': digest(contract), 'context': {'output': KIND, 'materials': [], KIND: contract,
                   'constraints': 'Respond individually to every frozen opinion. Propose only allowed text/caption/note changes. Preparation belongs only in workshop notes. No scientific computation, figure execution, title/reference/data changes or automatic adoption.'}}
        if version == 3:
            payload['context']['constraints'] = 'Respond to every frozen opinion. Only explicit manuscript/note text, selected registered figure visual overlays, or explicitly selected main-figure slot_layout boxes may change. Frozen dependency groups require all-or-none decisions. No data/script/numeric/source changes, scientific computation, invented evidence or automatic adoption.'
        require(len(encoded(payload).encode()) <= 96000, '本轮原话与目标超过有限上下文，请减少选择；不会截断', 'context_limit', 413)
        from .compatibility import require_features
        require_features(c, [FEATURE, FEATURE_V2, 'bounded_growth_evidence_v1', 'reviewed_growth_comparison_v2'] +
                         (['reviewed_figure_round_v3'] if version == 3 else []) +
                         (['reviewed_main_layout_round_v1'] if any(main_round.is_main(t['target']) for t in targets) else []) +
                         (['reviewed_main_leaf_adoption_v1'] if contract.get('slot_adoptions') else []) +
                         (['native_review_context_v1'] if native_notes else []) +
                         (['native_review_fragment_context_v1'] if native_notes and
                          any('fragment' in note for note in native_note_snapshot['notes']) else []))
        task = s.submit(payload, 'manuscript-revision:' + key, connection=c)
        put(c, 'grant:' + task['id'], {'principal': principal, 'contract': contract, 'issuer': actor(principal), 'at': now()})
        put(c, 'submission:' + key, {'input_sha256': digest(spec), 'task_id': task['id']})
        s.event(c, KIND + '.submitted', task['id'], {'version': version, 'contract_sha256': digest(contract), 'object_id': main['id'], 'revision': main['revision'], 'opinion_ids': [o['id'] for o in opinions]}, actor(principal))
    if app.runner and connection is None:
        app.runner.wake()
    return task


def round_schema(task):
    if task['payload']['context'][KIND]['version'] == 3:
        from .manuscript_figure_round import schema
        return schema(task)
    return '''Return exactly one JSON object: {"kind":"manuscript_revision","contract_sha256":"supplied revision_contract_sha256","summary":"overall rationale and limits","responses":[{"opinion_id":"exact frozen opinion id","text":"individual response and interpretation","verification":"actual checks performed or explicitly not performed","limitations":"remaining limits or none with reason","change_ids":["linked change id"]}],"changes":[{"id":"unique stable change id","opinion_id":"frozen opinion id","target":{},"before":"exact frozen target before text","after":"complete proposed replacement text","reason":"how this change addresses this opinion"}]}. Every opinion must have exactly one substantive response, including opinions warranting no safe change (change_ids:[]). Copy each target object exactly from the frozen targets list; only targets authorized by that opinion's target_indices may change. One opinion may produce both manuscript and workshop_note changes; each is independently accepted/rejected. Each target can change only once per candidate. An absent note block is explicitly exists:false with before:""; it becomes an ordinary paragraph only after acceptance. Manuscript caption targets edit only the saved caption on that adopted component, never the figure, data, rendering or component version. Preserve empirical values, citations, scientific scope and all unselected content; do not invent evidence, checks, approvals or completed computations. Preparation, tasks and pending decisions go in workshop_note changes, never manuscript prose. A response is not adoption or resolution. Summary<=4000 characters; response text<=4000, verification/limitations/reason<=2000; replacement<=30000. Changes:[] is valid with honest individual responses. Exact frozen target text is targets[].before; annotation quotes may be incomplete snippets. The complete task contract follows in the supplied materials. revision_contract_sha256=''' + task['payload']['revision_contract_sha256']


def change_opinion_ids(change):
    return change.get('opinion_ids', [change['opinion_id']])


def validate_round(candidate, task):
    bad = lambda ok, message: require(ok, message, 'invalid_model_output', 422)
    contract = task['payload']['context'][KIND]
    bad(isinstance(candidate, dict) and set(candidate) == {'kind', 'contract_sha256', 'summary', 'responses', 'changes'}, '逐条修订候选只能包含约定字段')
    bad(candidate['kind'] == KIND and candidate['contract_sha256'] == task['payload']['revision_contract_sha256'], '候选合同身份不符')
    def text(value, length): return isinstance(value, str) and 0 < len(value.strip()) <= length
    bad(text(candidate['summary'], 4000), '候选需明确说明整体理由与限制')
    opinions = {o['id']: o for o in contract['opinions']}
    changes = candidate['changes']; responses = candidate['responses']
    bad(isinstance(changes, list) and len(changes) <= len(contract['targets']), '候选变更数超出目标范围')
    bad(isinstance(responses, list) and len(responses) == len(opinions), '每条意见都需要独立回应')
    seen, target_seen, per_opinion = set(), set(), {o: set() for o in opinions}
    for change in changes:
        fields = {'id', 'opinion_id', 'target', 'before', 'after', 'reason'}
        bad(isinstance(change, dict) and (set(change) == fields or
            contract['version'] == 3 and set(change) == fields | {'opinion_ids'}), '变更字段越界')
        ident, oid, target = change['id'], change['opinion_id'], change['target']
        bad(isinstance(ident, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,180}', ident) and ident not in seen, '变更需要唯一稳定标识')
        bad(isinstance(oid, str) and oid in opinions, '变更没有对应意见')
        linked = change_opinion_ids(change)
        bad(isinstance(linked, list) and linked and all(isinstance(i, str) and i in opinions for i in linked)
            and len(linked) == len(set(linked)) and oid in linked, '合并变更需明确、唯一且有效的全部意见')
        bad(isinstance(target, dict), '变更目标格式无效')
        allowed = [contract['targets'][i] for i in opinions[oid]['target_indices']]
        tk = target_key(target)
        match = next((t for t in allowed if target_key(t['target']) == tk), None)
        bad(match is not None and tk not in target_seen, '变更目标越界或同一目标重复变更')
        bad(all(any(target_key(contract['targets'][i]['target']) == tk for i in opinions[o]['target_indices'])
                for o in linked), '合并变更不能越过任一关联意见的目标边界')
        bad(isinstance(change['before'], str) and change['before'] == match['before'], '变更原文不等于冻结版本')
        bad(isinstance(change['after'], str) and len(change['after']) <= 30000 and
            (change['after'] != change['before'] or match.get('binding', {}).get('slot_adoptions')), '变更正文无效或没有改变')
        if target.get('kind') == 'figure':
            from .manuscript_figure_round import validate_after
            validate_after(match, change['after'])
        bad(text(change['reason'], 2000), '每项变更需要理由')
        seen.add(ident); target_seen.add(tk)
        for o in linked: per_opinion[o].add(ident)
    if contract.get('slot_adoptions'):
        from .manuscript_slot_adoption import check_changes
        check_changes(contract, changes)
    responded = set()
    for response in responses:
        bad(isinstance(response, dict) and set(response) == {'opinion_id', 'text', 'verification', 'limitations', 'change_ids'}, '逐条回应字段无效')
        oid = response['opinion_id']
        bad(isinstance(oid, str) and oid in opinions and oid not in responded, '意见回应缺失或重复')
        bad(text(response['text'], 4000) and text(response['verification'], 2000) and text(response['limitations'], 2000), '逐条回应需如实写明理解、验证和限制')
        ids = response['change_ids']
        bad(isinstance(ids, list) and all(isinstance(i, str) for i in ids) and len(ids) == len(set(ids)) and set(ids) == per_opinion[oid], '回应与本条意见变更不对应')
        responded.add(oid)
    bad(len(encoded(candidate).encode()) <= 192000, '本轮候选超过有限字节上限')
    return copy.deepcopy(candidate)


def target_current(contract, frozen, objects):
    main = objects[contract['object_id']]
    obj = objects[frozen['target']['object_id']]
    if frozen['target']['kind'] == 'figure':
        from .manuscript_figure_round import current
        return current(frozen, objects, main)
    if frozen['binding'] is not None:
        require(note_binding(main, obj) == frozen['binding'], '章节笔记关联已改变', 'conflict', 409)
    else:
        blocks(main)
    value, text = target_value(obj, frozen['target'])
    require(value == frozen['base'], '此处已由用户编辑、改绑或移除，请保留当前内容', 'conflict', 409)
    return text


def opinion_current(app, contract, opinion_id, c):
    opinion = next(o for o in contract['opinions'] if o['id'] == opinion_id)
    if opinion['source']['kind'] == 'annotation':
        aid = opinion['source']['annotation_id']
        frozen = next(a for a in contract['annotations'] if a['id'] == aid)
        current_annotations(app, {'annotations': [frozen]}, c)


def view_round(app, task, contract, record, state, scope, c, principal=None):
    objects = round_sources(app, contract, scope, c); main = objects[contract['object_id']]
    targets = [{**t, 'current_revision': objects[t['target']['object_id']]['revision']} for t in contract['targets']]
    revisions = {ident: obj['revision'] for ident, obj in objects.items()}
    result = {'version': contract['version'], 'task_id': task['id'], 'task_status': task['status'], 'task_error': task.get('error'),
              'target': {'id': main['id'], 'title': main['title'], 'base_revision': contract['base_revision'], 'current_revision': main['revision']},
              'targets': targets, 'current_target_revisions': revisions, 'opinions': copy.deepcopy(contract['opinions']), 'annotations': contract['annotations'],
              'proposal': None, 'decision_version': 0, 'can_decide': False, 'block_reason': None,
              'contract_sha256': task['payload']['revision_contract_sha256'], 'can_authorize_decisions': False}
    if contract['version'] == 3: result['dependency_groups'] = copy.deepcopy(contract['dependency_groups'])
    if not record:
        return result
    can = True; reason = None
    try: current_proposal(app, task, record, c, principal)
    except Problem as error: can = False; reason = str(error)
    if not can:
        from .manuscript_decision_authority import eligibility
        result.update(eligibility(app, task, contract, record, state, principal, scope, c))
    by_target = {target_key(t['target']): t for t in contract['targets']}; changes = []
    for row in record['changes']:
        decided = state['changes'].get(row['id']); conflict = False; conflict_reason = None; current_text = None
        if not decided:
            try:
                target_current(contract, by_target[target_key(row['target'])], objects)
                for oid in change_opinion_ids(row): opinion_current(app, contract, oid, c)
            except Problem as error:
                conflict = True; conflict_reason = str(error)
                try: _, current_text = target_value(objects[row['target']['object_id']], {**row['target'], **({'exists': True} if row['target'].get('exists') is False else {})})
                except Problem: pass
        changes.append({**row, 'state': decided['decision'] if decided else 'pending', 'decision_receipt': decided,
                        'can_accept': can and not conflict and not decided, 'conflict': conflict, 'conflict_reason': conflict_reason, 'current_text': current_text})
    opinions = []
    for opinion in contract['opinions']:
        linked = [r for r in changes if opinion['id'] in change_opinion_ids(r)]
        states = {r['state'] for r in linked}
        decision_state = 'no_changes' if not linked else next(iter(states)) if len(states) == 1 else 'partially_decided' if 'pending' in states else 'mixed_decisions'
        opinions.append({**opinion, 'adoption_state': decision_state, 'automatically_resolved': False})
    result.update(opinions=opinions, proposal={**record, 'responses': record['candidate']['responses'], 'changes': changes},
                  decision_version=state['version'], can_decide=can and not state['settled'], block_reason=reason, decisions=state['receipts'], settled=state['settled'])
    return result


def prepare_round_selection(app, data, principal, scope, c, task, contract, record, state, *, objects=None, prewritten=None):
    """Read-only projection of a complete selected group; never records a decision.

    Used both before adoption and by explicitly requested visual previews. All
    after values come from the immutable proposal, not the preview request.
    """
    require(data.get('candidate_sha256') == record['candidate_sha256'] and
            data.get('proposal_sha256') == record['proposal_sha256'],
            '请审阅并选择准确候选身份', 'conflict', 409)
    if objects is None:
        objects = round_sources(app, contract, scope, c)
        round_sources(app, contract, authority_scope(app, principal), c)
    current_proposal(app, task, record, c, principal, prewritten=prewritten)
    require(type(data.get('expected_decision_version')) is int and data['expected_decision_version'] == state['version'] and not state['settled'], '审阅状态已变化，请重新读取', 'conflict', 409)
    expected = data.get('expected_target_revisions')
    require(isinstance(expected, dict) and set(expected) == set(objects) and all(type(r) is int and r == objects[ident]['revision'] for ident, r in expected.items()), '正文或章节笔记已改变，请重新读取差异', 'conflict', 409)
    pending = {r['id']: r for r in record['changes'] if r['id'] not in state['changes']}
    decisions = data.get('decisions')
    if any(isinstance(item,dict) and item.get('decision')=='accept' for item in (decisions or [])):
        draft_row=c.execute('SELECT value FROM kv WHERE key=?',('desk_w1a:drafts:'+task['project_id'],)).fetchone()
        draft=(json.loads(draft_row[0]) if draft_row else {}).get('value',{}).get('manuscript',{})
        require(not draft.get('dirty'),'当前稿件还有服务器未保存草稿，旧候选不得覆盖新手改','unsaved_manuscript',409)
    require(isinstance(decisions, list) and len(decisions) <= len(pending) and (decisions or not record['changes']), '请逐项接受／拒绝，或确认无变更回应')
    seen, accepted = set(), []
    frozen = {target_key(t['target']): t for t in contract['targets']}
    for item in decisions:
        require(isinstance(item, dict) and set(item) == {'change_id', 'decision'} and isinstance(item['change_id'], str) and item['change_id'] in pending and item['change_id'] not in seen and item['decision'] in {'accept', 'reject'}, '修订项或决定无效')
        seen.add(item['change_id'])
        if item['decision'] == 'accept':
            row = pending[item['change_id']]
            target_current(contract, frozen[target_key(row['target'])], objects)
            for oid in change_opinion_ids(row): opinion_current(app, contract, oid, c)
            accepted.append(row)
    if contract['version'] == 3:
        from .manuscript_figure_round import group_decisions, protect_dirty
        group_decisions(contract, record, decisions)
        if contract.get('slot_adoptions'):
            from .manuscript_slot_adoption import check_changes
            check_changes(contract, record['changes'], decisions)
        protect_dirty(app, task, accepted, c)
    contents = {}
    for row in accepted:
        target = row['target']; ident = target['object_id']
        content = contents.setdefault(ident, copy.deepcopy(objects[ident]['content']))
        if target.get('kind') == 'figure':
            from .manuscript_figure_round import apply_content
            apply_content(content, frozen[target_key(target)], row['after'])
        elif target.get('field') == 'caption':
            next(r for r in content['components'] if (r.get('id') or r.get('object_id')) == target['component_id'])['caption'] = row['after']
        elif not target['exists']:
            content['blocks'].append({'id': target['block_id'], 'kind': 'paragraph', 'text': row['after']})
        else:
            next(b for b in content['blocks'] if b['id'] == target['block_id'])['text'] = row['after']
    return {'prepared': True, 'objects': objects, 'contents': contents, 'accepted': accepted, 'frozen': frozen}


def decide_round(app, data, principal, scope, c, task, contract, record, state, *, prepare_only=False, staged=None, prewritten=None):
    require(set(data) <= {'action', 'task_id', 'candidate_sha256', 'proposal_sha256', 'expected_decision_version', 'expected_target_revisions', 'decisions', 'request_key'}, '回合决定包含未支持字段')
    require(data.get('candidate_sha256') == record['candidate_sha256'] and data.get('proposal_sha256') == record['proposal_sha256'], '请审阅并选择准确候选身份', 'conflict', 409)
    key = data.get('request_key'); require(isinstance(key, str) and 0 < len(key) <= 180, '需要稳定的决定请求标识')
    objects = round_sources(app, contract, scope, c)
    round_sources(app, contract, authority_scope(app, principal), c)
    prewritten = prewritten or {}
    for ident, entry in prewritten.items():
        require(ident in objects and digest(objects[ident]) == digest(entry['written'])
                and entry['written']['revision'] == entry['base']['revision'] + 1,
                '联合提交的主图投影不属于当前事务', 'integrity', 409)
        objects[ident] = entry['base']
    fingerprint = digest({'data': data, 'principal': principal})
    previous = setting(c, 'receipt:' + task['id'] + ':' + key)
    if previous:
        require(previous['input_sha256'] == fingerprint, '重复决定请求内容不同', 'idempotency_conflict', 409)
        return previous['receipt']
    prepared = prepare_round_selection(app, data, principal, scope, c, task, contract, record, state,
                                       objects=objects, prewritten=prewritten)
    contents, accepted, frozen = prepared['contents'], prepared['accepted'], prepared['frozen']
    decisions = data['decisions']
    pending = {r['id']: r for r in record['changes'] if r['id'] not in state['changes']}
    if prepare_only:
        return {'prepared': True, 'objects': objects, 'contents': contents, 'accepted': accepted, 'frozen': frozen}
    visual_ids = {row['target']['object_id'] for row in accepted if row['target']['kind'] == 'figure'}
    staged = staged or {}
    require(set(staged) == visual_ids, '图视觉采用缺少本次实际渲染与数值保护', 'visual_staging_required', 409)
    if staged:
        if contract.get('slot_adoptions'):
            from .manuscript_slot_adoption import apply_staged
            apply_staged(contract, accepted, contents, staged)
        from .manuscript_figure_round import adopt_occurrences
        adopt_occurrences(contract, accepted, frozen, objects, contents, staged)
    written = {}
    for ident, content in contents.items():
        obj = objects[ident]
        if ident in prewritten:
            candidate = staged[ident]['candidate']
            require(digest(prewritten[ident]['written']) == digest(candidate)
                    and content['slots'] == candidate['content']['slots'],
                    '联合主图实际保存与所选布局不同', 'integrity', 409)
            written[ident] = prewritten[ident]['written']
        else:
            written[ident] = app.store.save(ident, obj['revision'], content=content, actor=actor(principal), reason='explicit manuscript round review ' + task['id'] + ' proposal ' + record['proposal_sha256'], merge=False, connection=c, **({'prepared_updated_at': staged[ident]['candidate']['updated_at']} if ident in staged else {}))
    require(set(prewritten) <= set(written), '联合主图缺少对应接受决定', 'integrity', 409)
    if staged:
        from .manuscript_figure_round import register_renders
        register_renders(app, written, staged, c)
    object_receipts = [{'object_id': ident, 'base_revision': obj['revision'], 'result_revision': written.get(ident, obj)['revision'], 'result_sha256': digest(written.get(ident, obj)), 'source_changed': ident in written} for ident, obj in objects.items()]
    main = objects[contract['object_id']]; result = written.get(main['id'], main)
    receipt = {'version': contract['version'], 'task_id': task['id'], 'candidate_sha256': record['candidate_sha256'], 'proposal_sha256': record['proposal_sha256'],
               'decision_version': state['version'] + 1, 'decisions': decisions, 'operator': actor(principal), 'at': now(), 'objects': object_receipts,
               'object_id': main['id'], 'base_revision': main['revision'], 'result_revision': result['revision'], 'result_sha256': digest(result), 'source_changed': bool(written),
               'scientific_approval': False, 'user_acceptance': False, 'annotations_automatically_resolved': False, 'scientific_execution': False}
    if contract['version'] == 3:
        receipt['visual_execution'] = bool(staged)
        receipt['renders'] = {ident: {'source_sha256': digest(written[ident]), 'numeric_preserved': True} for ident in staged}
        for ident, stage in staged.items():
            if 'layout_proof' in stage: receipt['renders'][ident]['layout_proof'] = copy.deepcopy(stage['layout_proof'])
    for item in decisions:
        row = pending[item['change_id']]; ident = row['target']['object_id']
        state['changes'][row['id']] = {'decision': 'accepted' if item['decision'] == 'accept' else 'rejected', 'receipt_version': receipt['decision_version'], 'operator': receipt['operator'], 'object_id': ident, 'result_revision': written.get(ident, objects[ident])['revision']}
    state['version'] += 1; state['receipts'].append(receipt); state['settled'] = len(state['changes']) == len(record['changes'])
    put(c, 'decisions:' + record['proposal_sha256'], state)
    put(c, 'receipt:' + task['id'] + ':' + key, {'input_sha256': fingerprint, 'receipt': receipt})
    pointer = {**task['result'].get(KIND, {}), 'decision_version': state['version'], 'settled': state['settled']}
    c.execute('UPDATE tasks SET status=?,result=?,updated_at=? WHERE id=?', ('deliverable' if state['settled'] else 'review', encoded({**task['result'], KIND: pointer}), now(), task['id']))
    app.store.event(c, KIND + '.decided', task['id'], receipt, actor(principal))
    return receipt
