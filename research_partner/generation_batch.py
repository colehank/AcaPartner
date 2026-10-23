"""One frozen multi-recipe DAG, with explicit aliases for shared computation.

Only deterministic nodes with identical code, inputs, parameters, contracts and
environment share work. Recipe names and display IDs remain provenance, never a
reason to execute the same computation twice. No model or implicit grant exists.
"""
import copy
import json
from .store import require, digest, encoded, now


def targets(app, project, refs, constraints, scope, *, persist=True):
    from .generation import _recipe, plan
    require(isinstance(refs, list) and 1 <= len(refs) <= 8, '计划需要1–8个准确配方修订')
    recipes = [_recipe(app, ref, scope, project) for ref in refs]
    require(len({r['id'] for r in recipes}) == len(recipes), '同一配方不能在目标中重复登记')
    recipes.sort(key=lambda r: r['id'])
    require(isinstance(constraints, dict), '计划约束必须为明确对象')
    if 'resume_run_id' in constraints:
        task = app.store.task(constraints['resume_run_id'])
        require(task['project_id'] == project['id'] and task['payload'].get('kind') == 'generation', '接续运行不属于当前项目', 'forbidden', 403)
        original = task['payload'].get('generation_plan', {})
        require([{'id': r['id'], 'revision': r['revision']} for r in recipes] == (original.get('recipe_refs') or [original.get('recipe_ref')]),
                '接续需要原完整目标修订集合', 'plan_stale', 409)
        return plan(app, project, recipes[0], constraints, scope, persist=persist)
    if len(recipes) == 1:
        return plan(app, project, recipes[0], constraints, scope, persist=persist)
    require(set(constraints) <= {'force_nodes', 'timeout_seconds'}, '计划约束含未支持字段')
    force = constraints.get('force_nodes', [])
    parts = [(r, plan(app, project, r, {k:v for k,v in constraints.items() if k != 'force_nodes'}, scope, persist=False)) for r in recipes]
    logical_names = {r['id'] + '/' + s['id'] for r,p in parts for s in p['nodes']}
    require(isinstance(force, list) and all(isinstance(n, str) and n in logical_names for n in force),
            '多目标强制重做须使用配方ID/步骤ID，不能含糊指向重名步骤')
    require(sum(len(p['nodes']) for _, p in parts) <= 64, '多目标计划超过当前64个逻辑步骤边界', 'context_limit', 413)
    nodes, by_key, mappings, forced = [], {}, [], set()
    environment = parts[0][1]['environment']
    key_environment = parts[0][1].get('node_key_environment', environment)
    for recipe, part in parts:
        require(part['environment'] == environment, '目标执行环境不一致', 'environment_changed', 409)
        require(part.get('node_key_environment', part['environment']) == key_environment,
                '目标节点键环境不一致', 'environment_changed', 409)
        local = {}
        for original in part['nodes']:
            node = copy.deepcopy(original)
            inputs = {}
            for alias, ref in node['bound_inputs'].items():
                if ref['kind'] == 'dataset':
                    inputs[alias] = copy.deepcopy(ref)
                else:
                    upstream = local[ref['node_id']]
                    inputs[alias] = {**ref, 'node_id': upstream['id'], 'node_key': upstream['node_key']}
            identity_inputs = {alias: {k:v for k,v in ref.items() if k != 'node_id'} for alias,ref in inputs.items()}
            identity = {'schema': 'shared-generation-computation/1', 'script_sha256': node['script_snapshot']['sha256'],
                        'parameters': node['parameters'], 'inputs': identity_inputs, 'io': node['io'],
                        'environment': key_environment, 'deterministic': node['deterministic']}
            if not node['deterministic']:
                identity['unshared_source'] = {'recipe': part['recipe_ref'], 'node_id': node['id']}
            key = digest(identity)
            if key not in by_key:
                ident = 'shared-' + key[:20]
                require(all(n['id'] != ident for n in nodes), '共享步骤缩写身份碰撞，未合并', 'identity_mismatch', 409)
                node.update(id=ident, node_key=key, bound_inputs=inputs, reuse=None, logical_sources=[])
                node['inputs'] = {alias: ref['ref'] if ref['kind'] == 'dataset' else {'node_id': ref['node_id'], 'output': ref['output']} for alias,ref in inputs.items()}
                nodes.append(node); by_key[key] = node
            canonical = by_key[key]
            canonical['logical_sources'].append({'recipe_ref': part['recipe_ref'], 'recipe_sha256': part['recipe_sha256'],
                                                  'node_id': original['id'], 'role': original['role'], 'script': original['script']})
            local[original['id']] = canonical
            if recipe['id'] + '/' + original['id'] in force: forced.add(canonical['id'])
        mappings.append({'recipe_ref': part['recipe_ref'], 'recipe_sha256': part['recipe_sha256'], 'title': recipe['title'],
                         'nodes': {ident: node['id'] for ident,node in local.items()}})
    by_id = {n['id']: n for n in nodes}
    for node in nodes:
        if any(ref['kind'] == 'node' and ref['node_id'] in forced for ref in node['bound_inputs'].values()): forced.add(node['id'])
        cached = app.store.setting('generation_cache:' + project['id'] + ':' + node['node_key'])
        reusable = bool(cached and node['deterministic'] and node['id'] not in forced
                        and all(ref['kind'] == 'dataset' or by_id[ref['node_id']]['reuse'] for ref in node['bound_inputs'].values()))
        if reusable:
            from .generation_checkpoint import verify_output
            from .store import Problem
            try:
                from .generation_validity import ensure_reusable
                ensure_reusable(app.store,project['id'],cached)
                verify_output(app, project['id'], node, cached)
                expected = {alias: ref['asset_sha256'] if ref['kind'] == 'dataset' else by_id[ref['node_id']]['reuse']['outputs'][ref['output']]['asset_sha256'] for alias,ref in node['bound_inputs'].items()}
                require(cached['actual_inputs'] == expected and cached['source_script_sha256'] == node['script_snapshot']['sha256']
                        and cached['parameters'] == node['parameters'] and cached['io'] == node['io'], '共享缓存与实际计算身份不同', 'output_integrity', 409)
            except (Problem, OSError, KeyError, TypeError): reusable = False
        if reusable: node['reuse'] = copy.deepcopy(cached)
    bindings = [{'ref': p['recipe_ref'], 'sha256': p['recipe_sha256']} for _,p in parts]
    prior = next((t['payload']['generation_plan'] for t in app.store.tasks()
                  if t['project_id'] == project['id'] and t['payload'].get('kind') == 'generation'
                  and [r['id'] for r in t['payload']['generation_plan'].get('recipe_refs',[])] == [b['ref']['id'] for b in bindings]), None)
    old_keys = {n['node_key'] for n in prior['nodes']} if prior else set()
    value = {'project_id': project['id'], 'recipe_ref': bindings[0]['ref'], 'recipe_sha256': bindings[0]['sha256'],
             'recipe_refs': [b['ref'] for b in bindings], 'recipe_bindings': bindings, 'target_mappings': mappings,
             'shared_generation': True, 'nodes': nodes, 'environment': environment, 'constraints': copy.deepcopy(constraints),
             'pending': [n['id'] for n in nodes if not n['reuse']], 'reused': [n['id'] for n in nodes if n['reuse']],
             'changed': [n['id'] for n in nodes if n['node_key'] not in old_keys],
             'budget': copy.deepcopy(parts[0][1]['budget']), 'scientific_approval': False}
    if 'node_key_environment' in parts[0][1]:
        value.update(node_key_environment=copy.deepcopy(key_environment),
                     node_key_environment_binding=copy.deepcopy(parts[0][1]['node_key_environment_binding']))
    value['plan_hash'] = digest(value)
    require(len(encoded(value).encode()) <= 4*1024*1024, '固定多目标计划超过4MiB边界', 'context_limit', 413)
    if persist: app.store.set_setting('generation_plan:' + value['plan_hash'], value)
    return value


def material_identity(plan):
    """Ignore current cache observations when joining an identical live plan."""
    return digest({'project_id': plan['project_id'], 'recipes': plan['recipe_bindings'], 'constraints': plan['constraints'],
                   'environment': plan['environment'], 'nodes': [(n['id'], n['node_key']) for n in plan['nodes']]})


def replayed(app, request, task_payload):
    saved = app.store.setting('generation_join:' + request)
    if not saved: return None
    require(saved['input'] == digest(task_payload), '重复共享请求内容不同', 'idempotency_conflict', 409)
    task = app.store.task(saved['run_id'])
    require(task['project_id'] == task_payload['project_id'], '共享请求归属不同', 'forbidden', 403)
    return task


def joined(app, plan, payload, request, task_payload, connection):
    """Caller owns the enqueue transaction; a join never creates another task."""
    key = 'generation_join:' + request
    saved = connection.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
    if saved:
        record = json.loads(saved[0]); require(record['input'] == digest(task_payload), '重复共享请求内容不同', 'idempotency_conflict', 409)
        return app.store.task(record['run_id'], connection)
    row = connection.execute("SELECT id FROM tasks WHERE project_id=? AND status IN ('queued','running') AND json_extract(payload,'$.kind')='generation' AND json_extract(payload,'$.generation_plan.plan_hash')=? LIMIT 1", (plan['project_id'], plan['plan_hash'])).fetchone()
    if not row: return None
    grant_key = 'generation_grant:' + str(payload.get('authorization_ref'))
    raw = connection.execute('SELECT value FROM kv WHERE key=?', (grant_key,)).fetchone()
    grant = json.loads(raw[0]) if raw else {}
    require(grant.get('active') and grant.get('plan_hash') == plan['plan_hash'] and grant.get('consumed_request') in (None, request), '共享请求授权已撤回或被使用', 'authorization_required', 403)
    grant['consumed_request'] = request
    connection.execute('UPDATE kv SET value=? WHERE key=?', (encoded(grant), grant_key))
    connection.execute('INSERT INTO kv VALUES(?,?)', (key, encoded({'input': digest(task_payload), 'run_id': row[0]})))
    app.store.event(connection, 'generation.joined', row[0], {'request_key': request, 'plan_hash': plan['plan_hash'], 'new_task': False, 'at': now()})
    return app.store.task(row[0], connection)


def target_results(plan, nodes):
    return [{'recipe_ref': t['recipe_ref'], 'recipe_sha256': t['recipe_sha256'],
             'nodes': {local: {'physical_node_id': physical, **copy.deepcopy(nodes[physical])} for local,physical in t['nodes'].items()}}
            for t in plan['target_mappings']]
