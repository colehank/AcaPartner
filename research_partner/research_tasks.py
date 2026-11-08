"""Shared finite lifecycle for research exploration and Q-scoped work.

Uses the existing Store and Runtime. Domain modules retain their own candidate
contracts and adoption rules; these helpers never adopt scientific content.
"""
from __future__ import annotations
import copy
import json
import shutil
from dataclasses import dataclass
from .store import Problem, digest, encoded, require, now

TASK_KINDS = frozenset({'research_exploration', 'research_work', 'research_partner'})

@dataclass(frozen=True)
class Contract:
    kind: str
    key: str
    feature: str
    context_key: str
    label: str
    constraints: str
    acceptance: str


def domain(kind):
    if kind == 'research_partner':
        from . import project_partner
        return project_partner
    if kind == 'research_exploration':
        from . import research_exploration
        return research_exploration
    if kind == 'research_work':
        from . import research_work
        return research_work
    raise Problem('不支持的科研任务合同')

def project_access(app, ident, scope, principal, write=False):
    from .desk_w1a import _project as project_access
    return project_access(app, ident, scope, principal, write)


def text(value, label, maximum=12000, code='invalid'):
    require(isinstance(value, str) and bool(value.strip()) and len(value.encode()) <= maximum,
            label + '无效或过长', code, 422)
    return value


def input_snapshot(app, data, scope, principal, connection=None):
    text(data.get('request'), '原始研究想法')
    refs = data.get('materials', [])
    require(isinstance(refs, list) and len(refs) <= 8, '单次最多选择8份保存材料')
    seen = set()
    for ref in refs:
        require(isinstance(ref, dict) and set(ref) == {'id', 'revision'}
                and isinstance(ref['id'], str) and type(ref['revision']) is int and ref['revision'] > 0,
                '材料需要准确的 id/revision')
        key = (ref['id'], ref['revision'])
        require(key not in seen, '材料重复'); seen.add(key)
    project = project_access(app, data['project_id'], scope, principal)
    from .resolver import prepare_submission
    fixed, materials, _ = prepare_submission(app, {**data, 'materials': refs}, scope, connection)
    require(project == fixed, '项目在读取期间变化，请重新预览', 'conflict', 409)
    content = project['content']
    background, description = content.get('background', ''), content.get('description', '')
    require(isinstance(background, str) and isinstance(description, str), '项目背景需要保存为文字')
    questions, registered_text = [], []
    for ref in materials:
        obj = app.store.get(ref['id'], ref['revision'], connection)
        if obj['metadata'].get('research_role') == 'research_question_v1':
            questions.append({**ref, 'title': obj['title'], 'qaec': copy.deepcopy(obj['content'].get('qaec', {})),
                              'recorded_node_decisions':copy.deepcopy(obj['metadata'].get('research_nodes', {}))})
        # Legacy manually registered notes may use text instead of blocks or
        # markdown. The generic resolver deliberately omits this loose field;
        # carry it only in this explicit, fixed-source exploration contract.
        if obj['kind'] in {'note', 'report', 'concept', 'literature'} and 'text' in obj['content']:
            require(isinstance(obj['content']['text'], str), '选定材料的 text 正文需要文字，未发送不支持内容')
            registered_text.append({**ref, 'title': obj['title'], 'text': obj['content']['text']})
    snapshot = {
        'version': 1,
        'project': {'id': project['id'], 'revision': project['revision'], 'sha256': digest(project)},
        'request': data['request'],
        'background': {'title': project['title'], 'description': description, 'text': background},
        'materials': materials,
        'research_questions': questions,
        'registered_text': registered_text,
    }
    return snapshot


def check_input_size(app, snapshot, connection=None):
    require(len(encoded(snapshot).encode()) <= 45000, '科研上下文超过45000字节，请减少采用内容；不会截断正文', 'context_limit', 413)
    # Same resolver projection that Runtime actually sends; include its bytes in
    # the limit even though this preview does not duplicate them in task context.
    from .resolver import evidence_projection
    size = len(encoded(snapshot).encode()) + sum(len(encoded(evidence_projection(
        app.store.get(r['id'], r['revision'], connection))).encode()) for r in snapshot['materials'])
    require(size <= 45000, '完整科研材料超过45000字节，请减少采用材料', 'context_limit', 413)
    return snapshot


def provider(app, ident):
    config = app.config.get('providers', {}).get(ident, {})
    require(config.get('authorized') is True, '研究任务路线尚未授权或授权已撤回', 'authorization_required', 403)
    require(config.get('route') == 'codex' and not config.get('transport'),
            '研究任务当前仅支持 Codex CLI 路线', 'provider_missing', 503)
    require(isinstance(config.get('executable'), str) and shutil.which(config['executable']),
            'Codex CLI 不可用', 'provider_missing', 503)
    return {k: config.get(k) for k in ('route', 'transport', 'executable', 'model', 'reasoning_effort')}


def guard(app, task, connection, contract):
    """Revalidate the actual issuer and fixed contract at execution boundaries."""
    from .project_management import authority_scope
    grant = app.store.setting(contract.key + 'grant:' + task['id']) if connection is None else None
    if connection is not None:
        import json
        row = connection.execute('SELECT value FROM kv WHERE key=?', (contract.key + 'grant:' + task['id'],)).fetchone()
        grant = json.loads(row[0]) if row else None
    payload = task['payload']; snapshot = payload.get('context', {}).get(contract.context_key)
    require(payload.get('kind') == contract.kind and isinstance(snapshot, dict) and snapshot.get('version') == 1
            and grant and grant.get('state') == 'active' and digest(snapshot) == grant['input_pin']
            and payload['project_id'] == snapshot['project']['id']
            and payload['context'].get('output') == 'note' and not payload.get('target_id')
            and payload.get('request') == snapshot['request']
            and payload['context'].get('question') == snapshot['request']
            and payload['context'].get('materials') == snapshot['materials']
            and payload['context'].get('background') == snapshot['background']
            and payload.get('budget') == grant.get('budget')
            and payload.get('provider_id') == grant['provider_id'], '研究任务合同缺失或变化', 'forbidden', 403)
    current_scope = authority_scope(app, grant['principal'])
    project_access(app, payload['project_id'], current_scope, grant['principal'], True)
    require(provider(app, payload['provider_id']) == grant['provider_definition'],
            '研究任务执行路线已变化；请核对原任务', 'provider_checkpoint_missing', 409)
    app.store.assert_material_readiness(connection, {**payload, 'context': {**payload['context'],
        'materials': payload['context']['materials'] + snapshot.get('conversation_sources', [])}})
    return grant


def submit(app, data, scope, principal, contract, build_input, *, freeze_input=None):
    require(principal.get('actor_kind') != 'agent' and principal.get('kind') != 'agent',
            'Agent 不能通过此入口自行派发模型任务', 'forbidden', 403)
    request_key = text(data.get('request_key'), '稳定请求标识', 180)
    fingerprint = digest({'data': data, 'scope': sorted(scope) if scope is not None else None, 'principal': principal})
    from .compatibility import require_features
    import json
    with app.store.transaction() as c:
        key = contract.key + 'request:' + request_key
        row = c.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        if row:
            previous = json.loads(row[0])
            require(previous['fingerprint'] == fingerprint, '同一研究请求内容已变化', 'idempotency_conflict', 409)
            return app.store.task(previous['task_id'], c)
        snapshot = build_input(app, data, scope, principal, c)
        require(data.get('input_pin') == digest(snapshot), contract.label + '输入已变化，请重新预览', 'conflict', 409)
        provider_id = data.get('provider_id') or app.config.get('default_provider')
        definition = provider(app, provider_id)
        budget = data.get('budget', {'max_model_calls': 1, 'timeout_seconds': 180})
        require(isinstance(budget, dict) and set(budget) == {'max_model_calls', 'timeout_seconds'}
                and type(budget['max_model_calls']) is int and 1 <= budget['max_model_calls'] <= 100
                and type(budget['timeout_seconds']) in (int, float) and 0 < budget['timeout_seconds'] <= 900,
                '研究工作需要有限次数与执行时限')
        if freeze_input:
            snapshot = freeze_input(app, snapshot, c)
        context = {'question': snapshot['request'], 'background': snapshot['background'],
                   'materials': snapshot['materials'], 'output': 'note', contract.context_key: snapshot,
                   'constraints': contract.constraints,
                   'acceptance': contract.acceptance,
                   'unresolved': []}
        payload = {'project_id': data['project_id'], 'kind': contract.kind, 'request': snapshot['request'],
                   'context': context, 'provider_id': provider_id, 'budget': copy.deepcopy(budget),
                   'target_id': None, 'base_revision': None, 'depends_on': [], 'authorization': {}}
        if snapshot.get('previous_proposal'):
            payload['exploration_root_task_id'] = snapshot['previous_proposal']['root_task_id']
        require_features(c, [contract.feature])
        app.store.assert_material_readiness(c, payload, mark_requirement=True)
        task = app.store.submit(payload, request_key, connection=c)
        grant = {'state': 'active', 'input_pin': digest(snapshot), 'principal': principal,
                 'provider_id': provider_id, 'provider_definition': definition, 'budget': copy.deepcopy(budget)}
        c.execute('INSERT INTO kv VALUES(?,?)', (contract.key + 'grant:' + task['id'], encoded(grant)))
        c.execute('INSERT INTO kv VALUES(?,?)', (key, encoded({'fingerprint': fingerprint, 'task_id': task['id']})))
    if app.runner: app.runner.wake()
    return task


def publish(app, task, candidate, receipt, candidate_sha, contract, validate, *, on_publish=None):
    s = app.store
    content = validate(candidate, task, app, task['project_id'])
    with s.transaction() as c:
        s.assert_execution(c, task['id'], task.get('execution_token')); grant = guard(app, task, c, contract)
        model = next((x for x in s.task(task['id'], c)['steps'] if x['step_key'] == 'model'), None)
        require(model and model['status'] == 'done' and model['data']['sha256'] == candidate_sha
                and model['data']['provider'] == receipt and receipt.get('route') == 'codex'
                and receipt.get('returncode') == 0
                and isinstance(receipt.get('session_id'), str) and receipt['session_id'],
                '科研工作缺少匹配的已完成模型回执', 'integrity', 409)
        metadata = {'task_id': task['id'], contract.kind: {'version': 1, 'input_pin': grant['input_pin']},
                    'provider_receipt': receipt, 'evidence_revisions': copy.deepcopy(task['payload']['context']['materials']),
                    'review_status': 'pending', 'scientific_approval': False}
        if task['payload']['context'][contract.context_key].get('conversation_sources'):
            metadata['conversation_source_revisions'] = copy.deepcopy(task['payload']['context'][contract.context_key]['conversation_sources'])
        ident = 'ART-' + task['id'].removeprefix('TASK-')
        try: obj = s.get(ident, connection=c)
        except Problem as error:
            if error.status != 404: raise
            obj = s.create('note', candidate['title'], task['project_id'], content, metadata,
                           ident=ident, actor='agent', connection=c, task_id=task['id'], execution_token=task.get('execution_token'))
        require(obj['content'] == content and obj['metadata'] == metadata, '原科研工作提案已有不同内容', 'conflict', 409)
        s.relate(task['project_id'], obj['id'], 'produces', 'confirmed', connection=c)
        for ref in task['payload']['context']['materials']:
            s.relate(obj['id'], ref['id'], 'uses', 'confirmed', {'adopted_revision': ref['revision']}, connection=c)
        persisted = {'object_id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj)}
        graph_change = on_publish(app, task, content, persisted, c) if on_publish else None
        c.execute('INSERT INTO steps VALUES(?,?,?,?,?) ON CONFLICT(task_id,step_key) DO UPDATE SET status=excluded.status,data=excluded.data,updated_at=excluded.updated_at',
                  (task['id'], 'persist', 'done', encoded(persisted), now()))
        result = {'object_id': obj['id'], 'revision': obj['revision'], 'provider': receipt,
                  'independent_review': 'pending', 'user_acceptance': 'pending', 'adopted': False}
        if graph_change is not None: result['graph_change'] = graph_change
        c.execute("UPDATE tasks SET status='generated',result=?,error=NULL,updated_at=? WHERE id=?",
                  (encoded(result), now(), task['id']))
        s.event(c, 'task.generated', task['id'], {'error': None, **persisted}, 'runtime')



def read_proposal(app, project_id, task_id, contract, connection):
    task = app.store.task(task_id, connection)
    require(task['project_id'] == project_id and task['payload'].get('kind') == contract.kind,
            '科研任务不属于当前项目', 'forbidden', 403)
    payload = task['payload']
    app.store.assert_material_readiness(connection, {**payload, 'context': {**payload['context'],
        'materials': payload['context']['materials'] + payload['context'][contract.context_key].get('conversation_sources', [])}})
    proposal = None
    if task['result'].get('object_id'):
        result = task['result']; obj = app.store.get(result['object_id'], result['revision'], connection)
        persist = next((s for s in task['steps'] if s['step_key'] == 'persist' and s['status'] == 'done'), None)
        require(obj['project_id'] == project_id and obj['metadata'].get('task_id') == task['id']
                and persist and persist['data'] == {'object_id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj)},
                '候选与固定保存记录不同', 'integrity', 409)
        proposal = {**obj, 'sha256': digest(obj)}
    return task, proposal
