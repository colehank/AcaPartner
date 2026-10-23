"""Explicit error observations on fixed generated outputs; never scientific approval.

Execution records and bytes remain immutable. Retraction appends history; a new
run, edited head or successful process never silently clears an observation.
"""
from __future__ import annotations
import copy
import contextlib
import json
from .store import require, Problem, digest, encoded, now

FIELDS = {'origin_run_id', 'plan_hash', 'node_id', 'node_key', 'output_name', 'asset_sha256'}


def _get(connection, key, default=None):
    row = connection.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def _nodes(task):
    nodes = dict(task.get('result', {}).get('nodes', {}))
    for step in task.get('steps', []):
        key = step.get('step_key', '')
        if key.startswith('generation:') and step.get('status') == 'verified':
            nodes.setdefault(key.removeprefix('generation:'), step.get('data', {}))
    return nodes


def _task(store, run_id, connection):
    task = store.task(run_id, connection)
    require(task['payload'].get('kind') == 'generation', '需要准确的生成运行', 'invalid_result_subject', 422)
    return task


def subject_for(store, run_id, node_id, output_name, connection=None):
    with (store.connect() if connection is None else contextlib.nullcontext(connection)) as c:
        task = _task(store, run_id, c)
        nodes = _nodes(task); node = nodes.get(node_id)
        require(isinstance(node, dict) and output_name in node.get('outputs', {}),
                '此运行没有登记该实际输出', 'invalid_result_subject', 422)
        output = node['outputs'][output_name]; origin = node.get('run_id')
        producer = _task(store, origin, c)
        require(producer['project_id'] == task['project_id'], '结果生产者不属于项目', 'forbidden', 403)
        producer_nodes = _nodes(producer)
        matches = [ident for ident, value in producer_nodes.items()
                   if value.get('run_id') == origin and value.get('node_key') == node.get('node_key')
                   and value.get('outputs', {}).get(output_name) == output]
        if origin == run_id and node_id in matches:
            matches = [node_id]
        require(len(matches) == 1, '实际结果生产者无法唯一定位；不选择未标错的替代来源', 'result_source_ambiguous', 409)
        ident = matches[0]
        plan = producer['payload']['generation_plan']
        step = next((n for n in plan['nodes'] if n['id'] == ident), None)
        require(step and step['node_key'] == node['node_key'], '输出与原固定计划不一致', 'integrity', 409)
        asset = store.asset(output['asset_sha256'],connection=c)
        require(asset['sha'] == output['asset_sha256'], '输出资产身份不符', 'integrity', 409)
        return {'origin_run_id': origin, 'plan_hash': plan['plan_hash'], 'node_id': ident,
                'node_key': node['node_key'], 'output_name': output_name, 'asset_sha256': output['asset_sha256']}


def _observation(c, subject):
    return _get(c, 'generation_result_error:' + digest(subject),
                {'subject': subject, 'revision': 0, 'status': 'unmarked', 'history': [], 'scientific_approval': False})


def dispatch(app, data, project, scope, principal):
    action = data['action']; payload = data.get('payload', {})
    require(isinstance(payload, dict), '错误观察需要明确字段')
    with app.store.transaction() as c:
        if action == 'build.result_errors.read':
            require(set(payload) == {'run_id'} and isinstance(payload['run_id'],str) and 0<len(payload['run_id'])<=200, '读取需要准确运行')
            task = _task(app.store, payload['run_id'], c)
            require(task['project_id'] == project['id'], '运行不属于此项目', 'forbidden', 403)
            rows = []
            for ident, node in _nodes(task).items():
                for name in node.get('outputs', {}):
                    subject = subject_for(app.store, task['id'], ident, name, c)
                    rows.append({'node_id': ident, 'output_name': name, 'subject': subject,
                                 'observation': _observation(c, subject)})
            return {'run_id': task['id'], 'plan_hash': task['payload']['generation_plan']['plan_hash'],
                    'rows': rows, 'executed': False}
        require(action == 'build.result_errors.record', '错误观察命令未实现', 'unsupported_action', 422)
        from .generation import _owner
        _owner(principal)
        require(set(payload) == {'subject', 'expected_revision', 'status', 'reason'}, '错误观察字段不支持')
        subject = payload['subject']
        require(isinstance(subject, dict) and set(subject) == FIELDS and all(isinstance(v,str) and 0<len(v)<=512 for v in subject.values()), '结果身份字段不完整', 'invalid_result_subject', 422)
        task = _task(app.store, subject['origin_run_id'], c)
        require(task['project_id'] == project['id'], '运行不属于此项目', 'forbidden', 403)
        require(subject == subject_for(app.store, subject['origin_run_id'], subject['node_id'], subject['output_name'], c),
                '观察不匹配原实际结果', 'invalid_result_subject', 422)
        require(type(payload['expected_revision']) is int and payload['expected_revision'] >= 0, '需要当前观察修订')
        require(isinstance(payload['status'],str) and payload['status'] in {'confirmed_error', 'retracted'}, '需要明确确认或撤销错误观察')
        reason = payload['reason']
        require(isinstance(reason, str) and 0 < len(reason.strip()) <= 3000, '需要非空且有界的理由')
        request = data.get('request_id')
        require(isinstance(request, str) and 0 < len(request) <= 200, '观察写入需要稳定请求身份')
        fingerprint = digest({'payload': payload, 'principal': principal})
        request_key = 'generation_error_request:' + project['id'] + ':' + request
        previous = _get(c, request_key)
        if previous:
            require(previous['fingerprint'] == fingerprint, '同一请求内容已改变', 'idempotency_conflict', 409)
            return previous['result']
        old = _observation(c, subject)
        require(old['revision'] == payload['expected_revision'], '错误观察已改变；原记录保留，请重新读取', 'conflict', 409)
        require(payload['status'] != 'retracted' or old['status'] == 'confirmed_error', '只能撤销当前错误观察', 'conflict', 409)
        revision = old['revision'] + 1
        event = {'revision': revision, 'status': payload['status'], 'reason': reason.strip(),
                 'actor': copy.deepcopy(principal or {'kind': 'local_operator'}), 'recorded_at': now()}
        result = {'subject': copy.deepcopy(subject), **event, 'history': [*old['history'], event], 'scientific_approval': False}
        c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  ('generation_result_error:' + digest(subject), encoded(result)))
        c.execute('INSERT INTO kv VALUES(?,?)', (request_key, encoded({'fingerprint': fingerprint, 'result': result})))
        app.store.event(c, 'generation.result_error.recorded', task['id'], {'subject': subject, **event}, 'operator')
        return result


def _inspect_output(store,c,run_id,ident,name,path,seen,checked,failures):
    subject = subject_for(store, run_id, ident, name, c)
    key = digest(subject)
    if key in seen: return
    seen.add(key)
    observation = _observation(c, subject)
    checked.append({'subject': subject, 'revision': observation['revision'], 'status': observation['status']})
    if observation['status'] == 'confirmed_error':
        failures.append({'subject': subject, 'observation': observation, 'dependency_path': path})
    producer = _task(store, subject['origin_run_id'], c)
    step = next(n for n in producer['payload']['generation_plan']['nodes'] if n['id'] == subject['node_id'])
    for alias, ref in step.get('bound_inputs', {}).items():
        if ref.get('kind') != 'node': continue
        upstream = _nodes(producer).get(ref['node_id'], {})
        require(upstream.get('node_key') == ref.get('node_key'), '实际上游与固定计划不同', 'integrity', 409)
        _inspect_output(store,c,producer['id'], ref['node_id'], ref['output'], path + [{'input': alias, 'node_id': ref['node_id'], 'output': ref['output']}],seen,checked,failures)


def ensure_reusable(store, project_id, cached, connection=None):
    """An exact cached producer and its actual ancestors must be unmarked.

    The caller chooses a fresh plan or explicit scientific correction; this
    check never deletes cache bytes, retracts observations or starts work.
    """
    with (store.connect() if connection is None else contextlib.nullcontext(connection)) as c:
        task=_task(store,cached.get('run_id'),c)
        require(task['project_id']==project_id,'缓存生产者不属于项目','forbidden',403)
        nodes=_nodes(task)
        matches=[ident for ident,value in nodes.items() if value.get('node_key')==cached.get('node_key')
                 and value.get('outputs')==cached.get('outputs')]
        require(matches,'缓存没有原实际生产者','output_integrity',409)
        failures=[];checked=[];seen=set()
        for ident in matches:
            for name in cached['outputs']:
                _inspect_output(store,c,task['id'],ident,name,[{'run_id':task['id'],'node_id':ident,'output':name}],seen,checked,failures)
        require(not failures,'固定复用来源含已确认错误的结果，请重新固定计划；原历史保留',
                'known_result_error',409,{'errors':failures})
        return checked


def check_plan_reuse(store,plan,connection=None):
    for node in plan['nodes']:
        if node.get('reuse'):
            ensure_reusable(store,plan['project_id'],node['reuse'],connection)


def ensure_deliverable(store, obj, connection=None):
    """Walk actual output dependencies and saved object pins, not current heads.

    The check is repeated inside the final export registration transaction.
    Unknown provenance is not converted into scientific approval.
    """
    with (store.connect() if connection is None else contextlib.nullcontext(connection)) as c:
        failures = []; checked = []; seen_outputs = set(); seen_objects = set()
        def artifact(current, path):
            identity = (current['id'], current['revision'])
            if identity in seen_objects: return
            require(len(seen_objects) < 256, '成果依赖超过有限检查范围', 'context_limit', 413)
            seen_objects.add(identity)
            content = current['content']; binding = content.get('computation_path')
            if isinstance(binding, dict) and binding.get('run_id'):
                task = _task(store, binding['run_id'], c)
                require(task['project_id'] == current['project_id'] and task['payload']['generation_plan']['plan_hash'] == binding.get('plan_hash'),
                        '图输入与固定运行不符', 'integrity', 409)
                inputs = content.get('input_assets', {})
                any_output=False
                for alias, asset in (inputs.items() if isinstance(inputs, dict) else enumerate(inputs)):
                    sha = asset.get('sha', asset.get('asset')) if isinstance(asset, dict) else asset
                    matches = [(ident, name) for ident, node in _nodes(task).items()
                               for name, value in node.get('outputs', {}).items() if value.get('asset_sha256') == sha]
                    any_output=any_output or bool(matches)
                    # Equal bytes are not proof of one producer: retain/check all
                    # matching declared outputs, never choose an unmarked alias.
                    for ident, name in matches:
                        _inspect_output(store,c,task['id'], ident, name, path + [{'figure_input': str(alias), 'run_id': task['id'], 'node_id': ident, 'output': name}],seen_outputs,checked,failures)
                require(any_output, '图输入没有此固定运行的实际输出', 'integrity', 409)
            from .artifacts import ArtifactEngine
            class TransactionView:
                def __getattr__(self, name): return getattr(store,name)
                def get(self, ident, revision=None, connection=None):
                    return store.get(ident,revision,connection=c)
                def relations(self, ident=None):
                    return [store.unpack(row) for row in c.execute(
                        'SELECT * FROM relations WHERE (? IS NULL OR src=? OR dst=?)', (ident,ident,ident)).fetchall()]
            engine = ArtifactEngine(TransactionView())
            projection = copy.deepcopy(current)
            projection.setdefault('metadata', {}).pop('last_export', None)
            for ref in engine._declared_references(projection):
                if ref.get('content_role') == 'preparation': continue
                source, _ = engine._reference(current, ref)
                artifact(source, path + [{'object_id': source['id'], 'revision': source['revision']}])
        artifact(obj, [{'object_id': obj['id'], 'revision': obj['revision']}])
        require(not failures, '当前交付包含已确认错误的结果；请检查来源并明确纠正或撤销观察，历史保持',
                'known_result_error', 409, {'object_id': obj['id'], 'revision': obj['revision'], 'errors': failures})
        return checked
