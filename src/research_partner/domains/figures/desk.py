"""Project-scoped workdesk adapter for the existing figure authority/renderer.

Opening a figure reads registered exports and source bytes; it never redraws.
Creation binds existing uploaded assets. Explicit preview/adoption still passes
the existing grant, numerical baseline, CAS and exact-occurrence checks.
"""
import copy
import json
import math
from research_partner.storage.store import require, encoded, digest, now,Problem


def _same_reference(left, right):
    """Compare an echoed JSON identity without replacing any stored metadata.

    Browser JSON numbers may spell 0.0 as 0. Booleans are not numbers; the
    original server value (including signed zero) is always the value retained.
    """
    if type(left) in (int, float) and type(right) in (int, float):
        return (not isinstance(left, float) or math.isfinite(left)) and (not isinstance(right, float) or math.isfinite(right)) and left == right
    if type(left) is not type(right): return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_reference(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_reference(a, b) for a, b in zip(left, right))
    return left == right


def view(app,obj,scope):
    records=app.store.export_records(obj['id'],obj['revision'])
    exports=[r['result'] for r in records if r['result'].get('status')=='generated' and 'figure.svg' in r['result'].get('assets',{}) and r['result'].get('provenance',{}).get('source_sha256')==digest(obj)]
    render=exports[-1] if exports else None
    from research_partner.domains.figures.definition import FigureDefinitions, is_definition
    if is_definition(obj):
        definition = FigureDefinitions(app.store).read(obj['id'], obj['revision'])
        obj = definition['figure']
        exports = [r['result'] for r in app.store.export_records(obj['id'], obj['revision']) if r['result'].get('status') == 'generated' and 'canvas.svg' in r['result'].get('assets', {}) and r['result'].get('provenance', {}).get('source_sha256') == digest(obj)]
        render = exports[-1] if exports else None
        panels = []
        for slot in definition['definition']['slots']:
            if slot['source'] is None: continue
            ref = slot['source']; source = app.get(ref['id'], scope, ref['revision'])
            panels.append({'slot_id': slot['id'], 'source_ref': ref, 'current_revision': app.get(ref['id'], scope)['revision'], 'view': view(app, source, scope)})
        return {**definition, 'render': render, 'panels': panels, 'source': {'execution_on_open': False}}
    script=obj['content'].get('script_asset')
    script_record=app.asset(script,scope,obj['project_id']) if script else None
    code=None
    if script_record:
        raw=(app.store.blobs/script).read_bytes()
        require(len(raw)<=1024*1024,'脚本超过1MB显示边界；原资产保留','context_limit',413)
        try:code=raw.decode('utf-8-sig')
        except UnicodeDecodeError:code=None
    inputs=obj['content'].get('input_assets',{})
    source_inputs=[]
    for name,ref in (inputs.items() if isinstance(inputs,dict) else enumerate(inputs)):
        sha=ref.get('sha',ref.get('asset')) if isinstance(ref,dict) else ref
        source_inputs.append({'alias':str(name),'asset':app.asset(sha,scope,obj['project_id'])})
    grant=app.store.setting('code_grant:'+obj['id'],{})
    from research_partner.domains.evidence.trace import inspect
    from research_partner.domains.generation.generation import figure_source
    try:generation=figure_source(app,obj,scope)
    except Problem as error:
        ref=obj['content'].get('computation_path',{})
        generation={'run_id':ref.get('run_id') if isinstance(ref,dict) else None,'plan_hash':ref.get('plan_hash') if isinstance(ref,dict) else None,'scope':'上游运行未能核验：'+error.code+'；不补画完整链','steps':[],'unknown_inputs':[],'execution_on_open':False,'source_unavailable':True}
    return {'figure':obj,'render':render,'source':{'script':script_record,'code':code,'inputs':source_inputs,'parameters':obj['content'].get('parameters',{}),
            'script_authorized':bool(script and grant.get('script_sha')==script),'execution_on_open':False},
            'trace':inspect(app,{'action':'trace.inspect','object_id':obj['id'],'revision':obj['revision']},scope),'generation':generation}


def dispatch(app,data,project,scope,principal):
    action=data['action']
    if action in {'desk.figure.script.save','desk.figure.script.receipt'}:
        from research_partner.domains.figures.script import save
        return save(app,data,project,scope,principal)
    if action=='desk.figure.variants.create':
        from research_partner.domains.figures.purpose_candidates import create
        return create(app,data,project,scope,principal)
    if action=='desk.figures.list':
        return {'figures':[{'id':o['id'],'title':o['title'],'revision':o['revision'],'composition':bool(o['content'].get('composition'))} for o in app.store.objects(project['id'],['figure'],False)]}
    if action.startswith('desk.figure.composition.'):
        if principal and principal.get('actor_kind') == 'agent':
            from research_partner.domains.figures.composition import check_egress
            task = app.store.task(principal['domain_task_id'])
            check_egress(app, task['payload']['context']['figure_composition'], scope, task['id'])
        if action.endswith(('.preview', '.authorize')):
            from research_partner.domains.figures.composition import egress_command
            return egress_command(app, data, project, scope, principal)
        if action.endswith('.submit'):
            from research_partner.domains.figures.composition import submit
            return submit(app, data, project, scope)
        from research_partner.domains.figures.definition import FigureDefinitions
        return FigureDefinitions(app.store).command(data, project['id'], principal)
    if action=='desk.figure.create':
        require(set(data)<={'action','project_id','title','script_sha','inputs','parameters','request_key','run_id'},'新图字段不支持')
        key=data.get('request_key');require(isinstance(key,str) and 0<len(key)<=160,'新图需要稳定请求身份')
        title=data.get('title');require(isinstance(title,str) and 0<len(title.strip())<=200,'新图需要标题')
        script=data.get('script_sha');app.asset(script,scope,project['id'])
        inputs=data.get('inputs',{});params=data.get('parameters',{})
        require(isinstance(inputs,dict) and len(inputs)<=48 and all(isinstance(n,str) and 0<len(n)<=180 for n in inputs),'输入别名无效')
        require(isinstance(params,dict) and len(encoded(params).encode())<=64000,'绘图参数无效')
        for sha in inputs.values():app.asset(sha,scope,project['id'])
        fingerprint=digest({'data':data,'principal':principal})
        with app.store.transaction() as c:
            storage='desk_figure_create:'+project['id']+':'+key
            row=c.execute('SELECT value FROM kv WHERE key=?',(storage,)).fetchone()
            if row:
                previous=json.loads(row[0]);require(previous['input_sha256']==fingerprint,'重复新图请求不同','idempotency_conflict',409)
                return {'figure':app.store.get(previous['id'],connection=c),'created':False}
            content={'script_asset':script,'input_assets':inputs,'parameters':params,'overlays':[],'caption':'','editable_source_available':True}
            if data.get('run_id'):
                task=app.store.task(data['run_id'],c);require(task['project_id']==project['id'] and task['payload'].get('kind')=='generation' and task['status']=='generated','必须绑定本项目有实际核验输出的运行')
                actual={out['asset_sha256'] for node in task['result'].get('nodes',{}).values() for out in node.get('outputs',{}).values()}
                require(set(inputs.values()) & actual,'图输入没有此运行的实际结果，未伪造来源')
                content['computation_path']={'run_id':task['id'],'plan_hash':task['payload']['generation_plan']['plan_hash']}
            obj=app.store.create('figure',title.strip(),project['id'],content=content,connection=c)
            c.execute('INSERT INTO kv VALUES(?,?)',(storage,encoded({'input_sha256':fingerprint,'id':obj['id']})))
            return {'figure':obj,'created':True,'executed':False}
    obj=(app.get(data.get('id'),scope,data['revision']) if action=='desk.figure.read' and data.get('revision') is not None else app.writable(data.get('id'),scope))
    require(obj['project_id']==project['id'] and obj['kind']=='figure' and not obj['archived'],'图不属于当前项目','forbidden',403)
    if action=='desk.figure.read':
        from research_partner.domains.figures.composition import authorize
        authorized = authorize(app.store, principal, action, data)
        revision = authorized['revision'] if authorized else data.get('revision')
        if revision is not None: obj = app.get(obj['id'], scope, revision)
        result = view(app,obj,scope)
        result['source_ref'] = {'id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj)}
        if authorized:
            from research_partner.domains.figures.composition import check_egress
            task = app.store.task(authorized['task_id'])
            packet = check_egress(app, task['payload']['context']['figure_composition'], scope, task['id'])
            result = next(x for x in packet['contexts'] if x['figure']['id'] == obj['id'] and x['figure']['revision'] == obj['revision'])
            with app.store.transaction() as c:
                app.store.assert_execution(c, authorized['task_id'], principal['_execution_token'])
                app.store.event(c, 'figure.domain_context_read', authorized['task_id'], {'id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj)}, 'agent')
        return result
    if action=='desk.figure.rebind':
        require(set(data)<={'action','project_id','id','expected_revision','run_id','inputs','request_key'},'结果采用仅接新运行、输入映射和准确图修订')
        with app.store.transaction() as c:
            key='figure_rebind:'+obj['id']+':'+data['request_key'];fingerprint=digest({'data':data,'principal':principal})
            row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
            if row:
                previous=json.loads(row[0]);require(previous['input']==fingerprint,'同一结果采用请求不同','idempotency_conflict',409);return previous['result']
            figure=app.store.get(obj['id'],connection=c);require(figure['revision']==data['expected_revision'],'图已有新手改；旧运行不覆盖它','conflict',409)
            task=app.store.task(data['run_id'],c);require(task['project_id']==project['id'] and task['payload'].get('kind')=='generation' and task['status']=='generated','必须选择本项目有核验输出的运行')
            inputs=data['inputs'];require(isinstance(inputs,dict) and inputs,'请明确图输入映射')
            output_shas={out['asset_sha256'] for node in task['result'].get('nodes',{}).values() for out in node.get('outputs',{}).values()}
            require(set(inputs.values())&output_shas,'输入未包含此运行输出')
            for sha in inputs.values():app.asset(sha,scope,project['id'])
            content=copy.deepcopy(figure['content']);content.update(input_assets=inputs,computation_path={'run_id':task['id'],'plan_hash':task['payload']['generation_plan']['plan_hash']})
            saved=app.store.save(figure['id'],figure['revision'],content=content,merge=False,reason='explicit adoption of computed input bytes; preserve figure manual overlays',connection=c)
            c.execute('DELETE FROM kv WHERE key=?',('code_grant:'+figure['id'],))
            result={'figure':saved,'manuscript_updated':False,'executed':False,'render_required':True}
            c.execute('INSERT INTO kv VALUES(?,?)',(key,encoded({'input':fingerprint,'result':result})));return result
    if action=='desk.figure.attach':
        from research_partner.domains.figures.definition import require_complete
        require_complete(obj)
        require(set(data)<={'action','project_id','id','expected_revision','expected_manuscript_revision','after_block_id','caption','request_key','replace_component'},'稿内图引用字段不支持')
        replacing = 'replace_component' in data
        if replacing:
            require(all(type(data.get(k)) is int and data[k] > 0 for k in ('expected_revision','expected_manuscript_revision')),
                    '更新图版本需要准确的图与稿件修订', 'invalid_occurrence', 422)
            target = data['replace_component']
            require(isinstance(target, dict) and set(target) == {'index', 'expected_ref'}
                    and type(target['index']) is int and target['index'] >= 0
                    and isinstance(target['expected_ref'], dict), '请选择准确的原稿内图位置', 'invalid_occurrence', 422)
            require('caption' not in data and 'after_block_id' not in data,
                    '更新图版本保留原图注和位置；文字须由稿件编辑单独保存', 'invalid_occurrence', 422)
            require(not principal or (principal.get('kind') != 'agent' and principal.get('actor_kind') != 'agent'),
                    '更新稿内采用图需要用户明确操作', 'forbidden', 403)
        primary=project['metadata']['article']['primary_manuscript_id']
        key=data.get('request_key');require(isinstance(key,str) and 0<len(key)<=160,'图引用需要请求身份')
        with app.store.transaction() as c:
            paper=app.store.get(primary,connection=c);figure=app.store.get(obj['id'],connection=c)
            storage='desk_figure_attach:'+primary+':'+key;fingerprint=digest({'data':data,'principal':principal})
            row=c.execute('SELECT value FROM kv WHERE key=?',(storage,)).fetchone()
            if row:
                previous=json.loads(row[0]);require(previous['input_sha256']==fingerprint,'重复绑定请求不同','idempotency_conflict',409)
                return previous['result']
            require(paper['revision']==data.get('expected_manuscript_revision') and figure['revision']==data.get('expected_revision'),'稿件或图已改变，请重新读取','conflict',409)
            content=copy.deepcopy(paper['content'])
            if replacing:
                require(paper['project_id'] == project['id'] and not paper['archived'], '当前主稿不可修改', 'forbidden', 403)
                refs=content.get('components',[]);index=target['index']
                require(isinstance(refs,list) and index<len(refs) and isinstance(refs[index],dict)
                        and _same_reference(refs[index],target['expected_ref']), '原稿内图已变化；未替换任何引用', 'conflict', 409)
                previous=refs[index]
                require((previous.get('id') or previous.get('object_id')) == figure['id']
                        and all(previous[k] == figure['id'] for k in ('id','object_id') if k in previous)
                        and type(previous.get('revision')) is int and previous['revision'] > 0,
                        '只能更新所选位置的同一图；原引用保留', 'invalid_occurrence', 422)
                adopted=app.store.get(figure['id'],previous['revision'],connection=c)
                # Existing fixed references may omit the optional digest (or
                # store null), as ArtifactEngine._reference permits. Resolve
                # the exact saved id/revision above; never substitute HEAD.
                if previous.get('sha256') is not None:
                    require(previous['sha256'] == digest(adopted), '原稿内图来源摘要不符', 'integrity', 409)
                require(previous['revision'] < figure['revision'], '此位置已经采用当前保存版图', 'unchanged_occurrence', 409)
                app.store.assert_source_access(c, paper['project_id'], figure['id'])
                from research_partner.domains.generation.validity import ensure_deliverable
                ensure_deliverable(app.store, figure, connection=c)
                renders=[r['result'] for r in app.store.export_records(figure['id'],figure['revision'])
                         if r['result'].get('status') == 'generated'
                         and r['result'].get('provenance',{}).get('source_sha256') == digest(figure)
                         and any(k in r['result'].get('assets',{}) for k in ('canvas.svg','figure.svg'))]
                require(renders, '请先重绘当前保存版图，再明确更新稿内引用', 'render_required', 409)
                for asset in renders[-1]['assets'].values():
                    app.asset(asset['sha'], scope, project['id'])
                ref=copy.deepcopy(previous)
                ref.update(revision=figure['revision'],sha256=digest(figure))
                refs[index]=ref
            else:
                require(data.get('after_block_id') in {b['id'] for b in paper['content']['blocks']},'图引用需要当前段落锚点')
                caption=data.get('caption','');require(isinstance(caption,str) and len(caption)<=30000,'图注无效')
                index=len(content.get('components',[]))
                ref={'id':figure['id'],'revision':figure['revision'],'sha256':digest(figure),'after_block_id':data['after_block_id'],'caption':caption}
                content.setdefault('components',[]).append(ref)
            saved=app.store.save(primary,paper['revision'],content=content,merge=False,connection=c,
                                 reason='explicit workdesk figure occurrence version' if replacing else 'explicit workdesk figure occurrence')
            result={'manuscript':saved,'component_index':index,'component_ref':ref,'executed':False}
            c.execute('INSERT INTO kv VALUES(?,?)',(storage,encoded({'input_sha256':fingerprint,'result':result})))
            return result
    require(False,'图工作桌操作不支持')
