"""Fixed-source purpose candidates; creation never changes a delivery pin.

Each candidate is an ordinary independent figure, rendered and adopted through
the existing explicit code grant, renderer and fixed manuscript/main-figure
binding. A new actual result remains a scientific source change, not an overlay.
"""
import copy
import json

from research_partner.domains.figures.preview import _overlays
from research_partner.storage.store import digest, encoded, require


def create(app, data, project, scope, principal):
    require(set(data) <= {'action', 'project_id', 'request_key', 'run_id', 'inputs', 'variants'},
            '用途候选只接受固定来源、实际运行和明确输入映射')
    require(not principal or principal.get('actor_kind') != 'agent',
            '用途候选需要用户明确选择；Agent不能自动迁移交付图', 'forbidden', 403)
    key = data.get('request_key')
    require(isinstance(key, str) and 0 < len(key) <= 160, '用途候选需要稳定请求身份')
    variants = data.get('variants')
    require(isinstance(variants, list) and 2 <= len(variants) <= 8, '请选择二至八个用途固定来源')
    purposes = []
    for variant in variants:
        require(isinstance(variant, dict) and set(variant) == {'id', 'revision', 'sha256', 'purpose', 'title'},
                '每个用途需要准确图身份、修订、摘要和标题')
        require(isinstance(variant['id'], str) and type(variant['revision']) is int and variant['revision'] > 0,
                '用途来源身份无效')
        require(isinstance(variant['sha256'], str) and len(variant['sha256']) == 64,
                '用途来源需要保存版对象摘要')
        for field, limit in [('purpose', 100), ('title', 200)]:
            require(isinstance(variant[field], str) and 0 < len(variant[field].strip()) <= limit,
                    '用途及候选标题须明确且有界')
        purposes.append(variant['purpose'].strip())
    require(len(set(purposes)) == len(purposes), '用途须各自明确，不能重复')
    inputs = data.get('inputs')
    require(isinstance(inputs, dict) and 0 < len(inputs) <= 48 and
            all(isinstance(k, str) and 0 < len(k) <= 180 and isinstance(v, str) for k, v in inputs.items()),
            '请明确候选输入别名与资产SHA映射')
    for value in inputs.values():
        app.asset(value, scope, project['id'])
    fingerprint = digest({'data': data, 'principal': principal})
    storage = 'figure_purpose_candidates:' + project['id'] + ':' + key
    with app.store.transaction() as connection:
        previous = connection.execute('SELECT value FROM kv WHERE key=?', (storage,)).fetchone()
        if previous:
            saved = json.loads(previous[0])
            require(saved['input_sha256'] == fingerprint, '同一用途候选请求内容已改变', 'idempotency_conflict', 409)
            return {**saved['result'], 'created': False}
        run = app.store.task(data.get('run_id'), connection)
        require(run['project_id'] == project['id'] and run['payload'].get('kind') == 'generation'
                and run['status'] == 'generated', '候选必须选择本项目已核验的实际运行')
        outputs = {out['asset_sha256'] for node in run['result'].get('nodes', {}).values()
                   for out in node.get('outputs', {}).values()}
        require(set(inputs.values()) & outputs, '候选输入没有此运行的实际输出')
        sources = []
        shared_path = None
        shared_outputs = None
        for ref in variants:
            app.writable(ref['id'], scope)
            source = app.store.get(ref['id'], connection=connection)
            require(source['project_id'] == project['id'] and source['kind'] == 'figure'
                    and not source['archived'] and not source['content'].get('composition'),
                    '用途来源须为本项目可编辑的独立源图', 'forbidden', 403)
            require(source['revision'] == ref['revision'] and digest(source) == ref['sha256'],
                    '来源图已有新手改；请重新读取固定保存版', 'conflict', 409)
            content = source['content']
            require(content.get('editable_source_available') is not False and content.get('script_asset'),
                    '静态图没有可重绘来源', 'missing_source', 422)
            app.asset(content['script_asset'], scope, project['id'])
            old_inputs = content.get('input_assets')
            require(isinstance(old_inputs, dict) and set(old_inputs) == set(inputs),
                    '两用途须有相同输入别名；不能隐式丢弃原绘图输入')
            old_path = content.get('computation_path')
            require(isinstance(old_path, dict) and old_path.get('run_id'), '用途来源尚未绑定实际结果')
            old_run = app.store.task(old_path['run_id'], connection)
            require(old_run['project_id'] == project['id'] and old_run['status'] == 'generated'
                    and old_run['payload'].get('kind') == 'generation'
                    and old_path.get('plan_hash') == old_run['payload']['generation_plan']['plan_hash'],
                    '原用途实际结果身份无法核验')
            old_outputs = {out['asset_sha256'] for node in old_run['result'].get('nodes', {}).values()
                           for out in node.get('outputs', {}).values()}
            bound = set(old_inputs.values()) & old_outputs
            require(bound, '原用途输入没有其登记运行的实际输出')
            for value in old_inputs.values():
                app.asset(value, scope, project['id'])
            if shared_path is None:
                shared_path, shared_outputs = old_path, bound
            else:
                require(old_path == shared_path, '两用途来源不是同一个实际运行结果')
                shared_outputs &= bound
            sources.append((ref, source, _overlays(content.get('overlays', []))))
        require(shared_outputs, '两用途没有共同的实际输出引用，未将不同结果冒充同源')
        candidates = []
        for ref, source, overlays in sources:
            content = copy.deepcopy(source['content'])
            content.update(input_assets=copy.deepcopy(inputs), overlays=overlays,
                           computation_path={'run_id': run['id'], 'plan_hash': run['payload']['generation_plan']['plan_hash']})
            fixed = {'id': source['id'], 'revision': source['revision'], 'sha256': digest(source)}
            metadata = {'scientific_approval': False, 'user_acceptance': False,
                        'purpose_candidate': {'purpose': ref['purpose'].strip(), 'source_ref': fixed,
                        'original_result': copy.deepcopy(shared_path), 'candidate_run_id': run['id'],
                        'automatic_adoption': False}}
            candidate = app.store.create('figure', ref['title'].strip(), project['id'], content,
                                         metadata=metadata, connection=connection)
            candidates.append({'figure': candidate, 'source_ref': fixed, 'purpose': ref['purpose'].strip()})
        result = {'candidates': candidates, 'created': True, 'executed': False, 'originals_unchanged': True,
                  'script_authorization_required': True}
        connection.execute('INSERT INTO kv VALUES(?,?)', (storage, encoded({'input_sha256': fingerprint, 'result': result})))
        return result
