"""A finite existing-provider task with only typed figure-domain MCP tools.

No additional runner, model service, autonomous retries or adopted-head writes.
The temporary credential is private, project/task-bound and revoked on return.
"""
from research_partner.resources import module_file
import contextlib
import copy
import json
import os
from pathlib import Path
import secrets
import sys
import time
import urllib.parse

from research_partner.domains.figures.definition import FigureDefinitions, canonical_geometry
from research_partner.storage.store import digest, require, encoded

TOOLS = ['read_figure_context', 'create_main_figure']
ACTIONS = ['desk.figure.read', 'desk.figure.composition.create']


def provider_definition(config):
    require(config.get('authorized'), '此模型路线没有当前授权', 'authorization_required', 403)
    if config.get('route') == 'deepseek_harness':
        from research_partner.providers.deepseek_figure import definition
        require(config.get('authorized') is True, '此账号费用授权不是明确许可', 'authorization_required', 403)
        return definition(config)
    require(config.get('route') == 'codex', '此主图工具路线尚未接通', 'provider_missing', 503)
    transport = config.get('transport', 'cli_mcp')
    require(transport in {'cli_mcp', 'app_server_dynamic'}, '原生主图协议未配置', 'provider_missing', 503)
    if transport == 'app_server_dynamic':
        from research_partner.providers.codex_configuration import definition
        return definition(config)
    return None


def source_asset(record):
    """Keep evidence identity; omit mutable unrelated project catalog/ACLs."""
    return {k: copy.deepcopy(record[k]) for k in ('sha', 'filename', 'media_type', 'size', 'url') if k in record} | {'metadata': {k: copy.deepcopy(record.get('metadata', {})[k]) for k in ('provenance', 'synthetic', 'source_identity', 'immutable_input', 'data_sensitivity') if k in record.get('metadata', {})}}


def egress_preview(app, project_id, sources, provider, scope=None):
    """Exact source-only packet; no blanket project/network authorization."""
    from research_partner.domains.figures.desk import view
    project = app.get(project_id, scope)
    records = [project]; contexts = []
    for ref in sorted({(s['id'], s['revision']) for s in sources}):
        obj = app.get(ref[0], scope, ref[1]); records.extend([obj, app.get(obj['id'], scope)])
        full = view(app, obj, scope)
        source = {k: full[k] for k in ('figure', 'render', 'source', 'generation')}
        source['generation'] = source['generation'] or {}
        # The bounded domain context omits unrelated graph/annotation records.
        records.extend([source['source']['script']] if source['source']['script'] else [])
        records.extend(x['asset'] for x in source['source']['inputs'])
        if source['source']['script']: source['source']['script'] = source_asset(source['source']['script'])
        source['source']['inputs'] = [{**x, 'asset': source_asset(x['asset'])} for x in source['source']['inputs']]
        records.extend(app.store.asset(a['sha']) for a in (source['render'] or {}).get('assets', {}).values())
        for step in source['generation'].get('steps', []):
            records.extend(app.store.asset(out['asset_sha256']) for out in step.get('outputs', []) if out.get('available'))
            # Generation scripts/inputs not in the plotting-input grant are
            # deliberately omitted from this source-only composition packet.
        source['generation'] = {k: source['generation'].get(k) for k in ('run_id', 'plan_hash', 'scope', 'execution_on_open')}
        contexts.append(source)
    for record in records:
        level = record.get('metadata', {}).get('data_sensitivity', 'internal')
        require(level in {'public', 'internal'}, 'restricted或未知敏感等级的素材不能由此普通主图授权外发', 'disclosure_scope', 403)
        from research_partner.rendering.engine import ArtifactEngine
        omissions = []; ArtifactEngine._portable_value(record, omissions)
        require(not any(x['reason'] == 'credential_or_private_configuration' for x in omissions), '素材含凭据/私有配置字段；不能发送为子图上下文', 'sensitive_asset', 403)
    packet = {'project_id': project_id, 'provider_id': provider, 'purpose': 'fixed_main_figure_candidate', 'contexts': contexts}
    raw = json.dumps(packet, ensure_ascii=False, allow_nan=False).encode()
    ArtifactEngine._check_bundle_asset({'filename': 'figure-context.json', 'sha': digest(raw), 'media_type': 'application/json'}, raw)
    return {**packet, 'sha256': digest(packet), 'restricted_supported': False}


def egress_command(app, data, project, scope, principal):
    require(set(data) <= {'action', 'project_id', 'sources', 'provider_id', 'preview_sha256', 'approved', 'task_id'}, '主图外发预览字段不支持')
    refs = data.get('sources'); require(isinstance(refs, list) and 1 <= len(refs) <= 24, '需要明确固定子图')
    definitions = FigureDefinitions(app.store)
    refs = [definitions.resolve_source(project['id'], r) for r in refs]
    provider = data.get('provider_id', app.config.get('default_provider'))
    config = app.config.get('providers', {}).get(provider, {})
    provider_definition(config)
    packet = egress_preview(app, project['id'], refs, provider, scope)
    if data['action'].endswith('.preview'): return packet
    from research_partner.domains.workspace.management import authority_scope
    principal = principal or {'kind': 'local_operator'}
    require(principal.get('actor_kind') != 'agent' and principal.get('kind') != 'agent' and authority_scope(app, principal) is None, '外发授权需要当前空间所有者，Agent不能自授权', 'forbidden', 403)
    require(data.get('preview_sha256') == packet['sha256'] and type(data.get('approved')) is bool, '发送内容已变化；重新核对预览', 'conflict', 409)
    grant = {'project_id': project['id'], 'provider_id': provider, 'purpose': packet['purpose'], 'preview_sha256': packet['sha256'], 'expires_at': time.time() + 3600, 'state': 'active' if data['approved'] else 'revoked', 'principal': principal}
    if data.get('task_id'):
        task = app.store.task(data['task_id']); plan = task['payload']['context'].get('figure_composition', {})
        require(task['project_id'] == project['id'] and task['payload']['kind'] == 'figure_composition', '仅限此项目的原主图委托', 'forbidden', 403)
        if data['approved']:
            require(task['status'] in {'paused', 'waiting_input'}, '仅重新批准已停止的原委托', 'conflict', 409)
            require(not any(e['kind'].startswith('provider.') for e in app.store.events(task['id'])), '已有提供者边界，不能修改本次外发授权', 'conflict', 409)
        identity = lambda r: (r['id'], r['revision'], r['sha256'], r['svg_sha256'], r['numeric_sha256'])
        require(plan.get('provider_id') == provider and {identity(r) for r in refs} == {identity(r) for r in plan['fixed_sources']}, '不能扩大原任务来源或提供者', 'forbidden', 403)
        grant.update(task_id=task['id'], plan_sha256=plan['sha256'])
    storage = 'figure_egress:' + packet['sha256'] + (':' + grant['task_id'] if grant.get('task_id') else '')
    with app.store.transaction() as c:
        c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (storage, encoded(grant)))
        if grant.get('task_id'):
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('figure_task_egress:' + grant['task_id'], encoded(storage)))
        elif not data['approved']:
            # Withdrawing the source-group grant also revokes its task-specific
            # refinements atomically; a running task cannot retain that egress.
            for row in c.execute('SELECT key,value FROM kv WHERE key LIKE ?', ('figure_egress:' + packet['sha256'] + ':%',)).fetchall():
                refined = json.loads(row['value']); refined['state'] = 'revoked'
                c.execute('UPDATE kv SET value=? WHERE key=?', (encoded(refined), row['key']))
        app.store.event(c, 'figure.egress_grant', project['id'], {k: v for k, v in grant.items() if k != 'principal'}, 'user')
    return {k: v for k, v in grant.items() if k != 'principal'}


def check_egress(app, plan, scope=None, task_id=None):
    packet = egress_preview(app, plan['request']['project_id'], plan['fixed_sources'], plan['provider_id'], scope)
    storage = app.store.setting('figure_task_egress:' + task_id) if task_id else None
    grant = app.store.setting(storage or 'figure_egress:' + packet['sha256'])
    require(not grant or grant['preview_sha256'] == packet['sha256'], '原任务外发预览已变化', 'disclosure_scope', 403)
    bound = grant and (grant.get('task_id') == task_id and grant.get('plan_sha256') == plan['sha256'] if grant.get('task_id') else plan['egress_sha256'] == packet['sha256'])
    require(bound and grant['state'] == 'active' and grant['expires_at'] > time.time(), '此固定子图上下文没有有效外发授权或已变化/撤回', 'disclosure_scope', 403)
    from research_partner.domains.workspace.management import authority_scope
    require(authority_scope(app, grant['principal']) is None, '主图外发操作者授权已撤回', 'forbidden', 403)
    return packet


def check_current_authority(app, task, scope, execution_token):
    """Recheck the live Task authority before a native tool's next boundary.

    A still-valid lease does not preserve revoked disclosure/provider rights.
    This probe returns no project contents to the model.
    """
    with app.store.connect() as connection:
        app.store.assert_execution(connection, task['id'], execution_token)
    budget_state = None
    if app.config.get('development_budget'):
        from research_partner.execution.budget import Budget
        budget_state = Budget(app.config['development_budget']).check()
    require(isinstance(scope, list) and task['project_id'] in scope,
            '主图任务的项目读取授权已撤回', 'forbidden', 403)
    project = app.get(task['project_id'], scope)
    require(not project['archived'], '项目已归档，不能继续原主图任务', 'cancelled', 409)
    plan = task['payload'].get('context', {}).get('figure_composition')
    require(task['payload'].get('kind') == 'figure_composition' and isinstance(plan, dict)
            and plan.get('sha256') == digest({k: v for k, v in plan.items() if k != 'sha256'}),
            '主图任务固定计划身份已变化', 'integrity', 409)
    config = app.config.get('providers', {}).get(plan.get('provider_id'), {})
    require(task['payload'].get('provider_id') == plan.get('provider_id')
            and config.get('authorized') is True,
            '此主图任务的提供者授权已撤回', 'authorization_required', 403)
    transport = plan.get('native_transport', 'cli_mcp')
    if transport == 'app_server_dynamic':
        from research_partner.providers.codex_configuration import guard
        guard(task, config)
    elif transport == 'deepseek_harness_native':
        from research_partner.providers.deepseek_figure import guard
        guard(task, config)
        from research_partner.execution.budget import Budget
        require(budget_state is not None
                and Budget.native_permission(budget_state, plan['native_definition'], read_only=True) is not None,
                '此原生主图任务的父费用许可已撤回', 'authorization_required', 403)
    else:
        require(transport == 'cli_mcp' and config.get('route') == 'codex'
                and config.get('transport', 'cli_mcp') == 'cli_mcp',
                '原主图任务的工具路线已变化', 'provider_missing', 503)
    check_egress(app, plan, scope, task['id'])
    return {'task_id': task['id'], 'project_id': task['project_id'],
            'plan_sha256': plan['sha256'], 'egress_sha256': plan['egress_sha256']}


def verified_result(app, task, directory, receipt):
    """Native successful MCP events and the same saved domain candidate agree."""
    if receipt.get('transport')=='app_server_dynamic':
        from research_partner.providers.codex_dynamic import read_snapshot
        from research_partner.providers.codex_evidence import verified_figure
        return verified_figure(app,task,read_snapshot(directory,receipt),receipt)
    if receipt.get('transport') == 'deepseek_harness_native':
        from research_partner.providers.native_figure import verified_result
        return verified_result(app, task, directory, receipt)
    require(receipt.get('session_identity_confirmed') and receipt.get('returncode') == 0 and receipt.get('scoped_domain_tools') == TOOLS, '领域模型会话/工具身份未成立', 'domain_tools_unverified', 409)
    path = Path(directory) / ('codex-events-' + receipt['attempt_id'] + '.json')
    raw = path.read_bytes(); require(digest(raw) == receipt['events_sha256'], '领域工具原生事件摘要改变', 'integrity', 409)
    events = json.loads(raw)
    completed = [e['item'] for e in events if e.get('type') == 'item.completed' and isinstance(e.get('item'), dict) and e['item'].get('type') == 'mcp_tool_call' and e['item'].get('server') == 'rp_figure_candidate' and e['item'].get('status') == 'completed' and not e['item'].get('error') and not (e['item'].get('result') or {}).get('isError')]
    require(any(i.get('tool') == 'create_main_figure' for i in completed), '没有本轮真实成功的领域组成工具调用', 'domain_tools_unverified', 409)
    needed = {(r['id'], r['revision']) for r in task['payload']['context']['figure_composition']['fixed_sources']}
    observed = set()
    for item in completed:
        if item.get('tool') != 'read_figure_context': continue
        args = item.get('arguments', {})
        if isinstance(args, str): args = json.loads(args)
        observed.add((args.get('id'), args.get('revision')))
    require(needed <= observed, '原生事件没有全部固定子图的实际上下文读取', 'domain_tools_unverified', 409)
    result = app.store.setting('composition_task_candidate:' + task['id'])
    require(result and digest(app.store.get(result['id'], result['revision'])) == result['sha256'], '领域工具没有同一已保存实际候选', 'domain_tools_unverified', 409)
    return {**result, 'native_mcp_events_sha256': receipt['events_sha256'], 'actual_source_reads': len(needed), 'native_tool_event_ids': [i.get('id') for i in completed], 'scientific_or_human_acceptance': 'not_implied'}


def submit(app, data, project, scope):
    require(set(data) <= {'action', 'project_id', 'title', 'width', 'height', 'slots', 'request', 'provider_id', 'budget', 'request_key'}, '主图委托字段不支持')
    require(app.runner is not None, '当前服务没有模型执行器；主图定义仍可直接编辑', 'runtime_unavailable', 503)
    request = {k: copy.deepcopy(data[k]) for k in ('project_id', 'title', 'slots')}
    request.update(width=data.get('width', 1200), height=data.get('height', 600))
    definitions = FigureDefinitions(app.store)
    probe = copy.deepcopy({'schema': 'research-partner-main-figure/1', 'object_id': 'ART-0000000000000000', **request})
    sources = []; sources_by_revision = {}
    for slot in probe['slots']:
        require(slot.get('source') is not None or not slot.get('required'), '委托前需明确每个必需图位的固定子图')
        if slot.get('source') is not None:
            ref = definitions.resolve_source(project['id'], slot['source'])
            key = (ref['id'], ref['revision'])
            if key in sources_by_revision:
                require(sources_by_revision[key] == ref, '同一固定子图修订的来源摘要改变', 'integrity', 409)
            else:
                sources_by_revision[key] = ref
                sources.append(ref)
            slot['source'] = ref
    definitions.validate(probe, project['id'], probe['object_id'])
    require(sources, '请明确至少一个实际子图，不让模型猜来源')
    provider = data.get('provider_id', app.config.get('default_provider')); config = app.config.get('providers', {}).get(provider, {})
    frozen = provider_definition(config)
    requests = frozen['max_requests'] if config.get('route') == 'deepseek_harness' else 1
    budget = data.get('budget'); require(isinstance(budget, dict) and type(budget.get('max_model_calls')) is int and budget.get('max_model_calls') == requests and type(budget.get('timeout_seconds')) in (int, float) and 0 < budget['timeout_seconds'] <= 600, '主图委托需要匹配冻结请求次数和至多600秒')
    if config.get('route') == 'deepseek_harness':
        require(budget['timeout_seconds'] >= frozen['timeout_seconds'], 'Task时间不能小于已冻结运行界限', 'budget_exhausted', 409)
    packet = egress_preview(app, project['id'], sources, provider, scope)
    plan = {'version': 1, 'request': request, 'fixed_sources': sources, 'provider_id': provider, 'egress_sha256': packet['sha256'], 'max_tool_calls': 8, 'adopted_head_changed': False}
    if frozen:
        plan.update(native_transport=frozen['transport'], native_definition=frozen)
    check_egress(app, plan, scope)
    plan['sha256'] = digest(plan)
    return app.submit({'action': 'task.submit', 'kind': 'figure_composition', 'project_id': project['id'], 'request': data.get('request') or 'Read the actual saved panel contexts. Use the provided typed create_main_figure tool to create the exact fixed main-figure candidate. No computations or adoption.', 'materials': [{'id': s['id'], 'revision': s['revision']} for s in sources], 'provider_id': provider, 'budget': budget, 'output_kind': 'note', 'request_key': data['request_key'], 'constraints': 'Only the two explicit domain tools. No computations, shell, external network, deletion, user-comment changes or adopted-head updates.'}, scope, domain_context=plan)


def authorize(store, principal, action, data, connection=None):
    if not principal or principal.get('actor_kind') != 'agent': return None
    require(principal.get('domain_task_id') and principal.get('_execution_token'), '领域Agent缺少真实任务与执行授权', 'forbidden', 403)
    with (store.transaction() if connection is None else contextlib.nullcontext(connection)) as c:
        ident = principal['domain_task_id']; store.assert_execution(c, ident, principal['_execution_token']); task = store.task(ident, c)
        plan = task['payload']['context'].get('figure_composition')
        require(task['payload']['kind'] == 'figure_composition' and isinstance(plan, dict) and digest({k: v for k, v in plan.items() if k != 'sha256'}) == plan['sha256'], '领域工具计划身份不符', 'integrity', 409)
        require(data.get('project_id') == task['project_id'], '领域工具越出固定项目', 'forbidden', 403)
        count_key = 'composition_tool_calls:' + ident
        count = c.execute('SELECT value FROM kv WHERE key=?', (count_key,)).fetchone(); count = json.loads(count[0]) if count else 0
        require(count < plan['max_tool_calls'], '本次领域工具调用额度已用尽，不自动重试', 'budget_exhausted', 409)
        if action == 'desk.figure.read':
            refs = [r for r in plan['fixed_sources'] if r['id'] == data.get('id') and (data.get('revision') is None or r['revision'] == data['revision'])]
            require(len({r['revision'] for r in refs}) == 1, '只能读取委托固定的子图修订', 'forbidden', 403)
            store.event(c, 'figure.domain_tool', ident, {'action': action, 'source_id': refs[0]['id'], 'source_revision': refs[0]['revision'], 'plan_sha256': plan['sha256']}, 'agent')
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (count_key, json.dumps(count + 1)))
            return {'task_id': ident, 'revision': refs[0]['revision']}
        require(action == 'desk.figure.composition.create', 'Agent领域命令未授权', 'forbidden', 403)
        expected = plan['request']
        actual = {k: data.get(k) for k in ('project_id', 'title', 'slots')}; actual.update(width=data.get('width', 1200), height=data.get('height', 600))
        require(digest(canonical_geometry(actual)) == digest(canonical_geometry(expected)) and data.get('request_key') == ident + ':composition', '只能保存本任务固定的组成候选；不能扩大或修改来源', 'forbidden', 403)
        store.event(c, 'figure.domain_tool', ident, {'action': action, 'request_sha256': digest(actual), 'plan_sha256': plan['sha256']}, 'agent')
        c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (count_key, json.dumps(count + 1)))
        return {'task_id': ident, 'token_sha256': digest(principal['_execution_token'].encode()), 'egress_sha256': plan['egress_sha256'], 'egress_storage': store.setting('figure_task_egress:' + ident, 'figure_egress:' + plan['egress_sha256'])}


def fence_intent(store, c, intent):
    execution = intent.get('execution') if intent else None
    if not execution: return
    row = c.execute('SELECT value FROM kv WHERE key=?', (execution.get('egress_storage') or 'figure_egress:' + execution['egress_sha256'],)).fetchone()
    grant = json.loads(row[0]) if row else None
    require(grant and grant['state'] == 'active' and grant['expires_at'] > time.time(), '主图候选外发授权已撤销/到期', 'cancelled', 409)
    lease = store.setting('execution:' + execution['task_id'], {})
    require(isinstance(lease.get('token'), str) and digest(lease['token'].encode()) == execution['token_sha256'], '主图候选执行身份已撤销', 'cancelled', 409)
    store.assert_execution(c, execution['task_id'], lease['token'])


@contextlib.contextmanager
def task_bridge(app, task, directory):
    """Temporary task-bound HTTP authority shared by the two native transports."""
    plan = task['payload']['context'].get('figure_composition')
    require(task['payload']['kind'] == 'figure_composition' and plan, '没有固定的领域工具委托', 'forbidden', 403)
    check_egress(app, plan, task_id=task['id'])
    origin = app.config.get('_local_mcp_origin'); parsed = urllib.parse.urlsplit(origin or '')
    require(parsed.scheme == 'http' and parsed.hostname in {'127.0.0.1', 'localhost', '::1'} and parsed.port and not parsed.path and not parsed.query, '领域MCP需要当前服务实际绑定的loopback入口', 'runtime_unavailable', 503)
    lease = app.store.setting('execution:' + task['id'], {}); token = lease.get('token')
    with app.store.connect() as c: app.store.assert_execution(c, task['id'], token)
    directory = Path(directory); credential = directory / ('domain-' + secrets.token_hex(12) + '.token')
    fd = os.open(credential, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream: stream.write(secrets.token_urlsafe(32) + '\n')
    client = {'token_file': str(credential), 'projects': [task['project_id']], 'actor_kind': 'agent', 'allowed_actions': ACTIONS, 'task_binding': {'id': task['id'], 'token': token}}
    app.config.setdefault('clients', []).append(client)
    try: yield {'origin': origin, 'token_file': credential}
    finally:
        app.config['clients'] = [value for value in app.config.get('clients', []) if value is not client]
        credential.unlink(missing_ok=True)


@contextlib.contextmanager
def transport(app, task, directory):
    """Only this CLI invocation gets the required two-tool stdio adapter."""
    with task_bridge(app, task, directory) as bridge:
        script = module_file('research_partner.integrations.mcp_workbench')
        yield {'command': sys.executable,
               'args': [str(script), '--url', bridge['origin'], '--token-file', str(bridge['token_file']), '--tools', ','.join(TOOLS)],
               'enabled': True, 'required': True, 'enabled_tools': TOOLS,
               'startup_timeout_sec': 10, 'tool_timeout_sec': 15, 'default_tools_approval_mode': 'approve'}
