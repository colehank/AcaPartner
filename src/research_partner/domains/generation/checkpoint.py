"""Verified per-step checkpoints and explicit remaining-work plans.

Only the live execution lease can register completed outputs. Recovery reads
registered immutable assets, never adopts half-written files from a stopped job.
New plans keep original frozen input/code refs and require fresh authorization.
"""
import copy
import json
import stat
from pathlib import Path
from research_partner.storage.store import require,digest,now


def environment_binding(original,current):
    """Allow only relocation of the two registered source lock files.

    Interpreter, installed runtime receipt, platform and worker bytes retain
    exact identity. This does not bind a different runtime or claim portability.
    The derived plan records both environments and still needs a fresh grant.
    """
    if original==current:return None
    names={'core-generation-runtime.lock','core-existing-python-runtime.json'}
    def normalized(value):
        result=copy.deepcopy(value);refs=result.get('lock_refs')
        require(isinstance(refs,list) and len(refs)==2,'原环境缺少两个已登记锁引用','environment_changed',409)
        mapped={}
        for ref in refs:
            require(isinstance(ref,dict) and set(ref)=={'path','sha256'},'环境锁引用字段已改变','environment_changed',409)
            path=Path(ref['path']);name=path.name
            require(path.is_absolute() and path.parent.name in {'development', 'environments'} and name in names and name not in mapped,'只允许已登记源码锁路径迁移','environment_changed',409)
            mapped[name]=ref['sha256']
        require(set(mapped)==names,'环境锁引用缺失','environment_changed',409)
        result['lock_refs']=mapped
        return result
    require(normalized(original)==normalized(current),'原解释器、运行时、代码或锁字节已改变，不能接续','environment_changed',409)
    return {'kind':'same_runtime_source_lock_relocation','original_environment_sha256':digest(original),
            'current_environment_sha256':digest(current),'original_lock_refs':copy.deepcopy(original['lock_refs']),
            'current_lock_refs':copy.deepcopy(current['lock_refs']),'cross_machine_tested':False}


def verify_output(app,project,node,result):
    from research_partner.domains.generation.generation import table
    require(result['node_key']==node['node_key'] and set(result['outputs'])==set(node['io']['outputs']),'检查点与固定步骤不同','output_integrity',409)
    for name,output in result['outputs'].items():
        asset=app.asset(output['asset_sha256'],[project],project);raw=(app.store.blobs/asset['sha']).read_bytes()
        require(digest(raw)==asset['sha'] and table(raw,node['io']['outputs'][name])==output['snapshot'],'检查点实际字节、成员或单位不同','output_integrity',409)


def collect(runtime,task,directory):
    from research_partner.domains.generation.generation import table,MAX_BYTES
    app=runtime.app;ident=task['id'];p=task['payload']['generation_plan'];token=task['execution_token']
    key='generation_checkpoint:'+ident
    saved=app.store.setting(key,{'plan_hash':p['plan_hash'],'nodes':{}})
    require(saved['plan_hash']==p['plan_hash'],'检查点计划身份不同','output_integrity',409)
    available={n['id']:n['reuse'] for n in p['nodes'] if n['reuse']};available.update(saved['nodes'])
    for node in p['nodes']:
        if node['id'] in available:continue
        path=Path(directory)/node['id']/'outputs.json'
        if not path.exists():continue
        expected={}
        for alias,ref in node['bound_inputs'].items():
            if ref['kind']=='dataset':expected[alias]=ref['asset_sha256']
            elif ref['node_id'] in available:expected[alias]=available[ref['node_id']]['outputs'][ref['output']]['asset_sha256']
            else:break
        if set(expected)!=set(node['bound_inputs']):continue
        info=path.lstat();require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=65536,'步骤回执不是受管文件','output_integrity',409)
        manifest=json.loads(path.read_text())
        require(manifest['plan_hash']==p['plan_hash'] and manifest['node_key']==node['node_key'] and manifest['inputs']==expected and manifest['script_sha256']==node['script_snapshot']['sha256'] and set(manifest['outputs'])==set(node['io']['outputs']),'步骤回执与实际固定输入不符','output_integrity',409)
        outputs={}
        for name,contract in node['io']['outputs'].items():
            output=path.parent/name;info=output.lstat();require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=MAX_BYTES,'步骤输出不是受管文件','output_integrity',409)
            raw=output.read_bytes();snapshot=table(raw,contract)
            require(digest(raw)==manifest['outputs'][name]['sha256'] and snapshot['row_count']==manifest['outputs'][name]['rows'] and contract==manifest['outputs'][name]['contract'],'步骤实际输出与回执不同','output_integrity',409)
            asset=app.store.add_asset(raw,name,'text/csv',{'project_id':p['project_id'],'generation_output':True,'run_id':ident,'node_key':node['node_key'],'plan_hash':p['plan_hash']},task_id=ident,execution_token=token)
            outputs[name]={'asset_sha256':asset['sha'],'snapshot':snapshot}
        result={'run_id':ident,'node_key':node['node_key'],'outputs':outputs,'actual_inputs':expected,'source_script_sha256':node['script_snapshot']['sha256'],'parameters':node['parameters'],'io':node['io'],'verified_at':now(),'completion_manifest_sha256':digest(path.read_bytes())}
        saved['nodes'][node['id']]=result;available[node['id']]=result
        app.store.set_setting(key,saved,task_id=ident,execution_token=token)
        app.store.set_setting('generation_cache:'+p['project_id']+':'+node['node_key'],result,task_id=ident,execution_token=token)
        app.store.step(ident,'generation:'+node['id'],'verified',result,execution_token=token)
    return saved


def remaining_plan(app,project,recipe,constraints,scope,persist):
    from research_partner.domains.generation.generation import environment
    require(set(constraints)=={'resume_run_id'} and isinstance(constraints['resume_run_id'],str),'接续只接受一个明确旧运行；不混入新参数或范围')
    task=app.store.task(constraints['resume_run_id'])
    require(task['project_id']==project['id'] and task['payload'].get('kind')=='generation','接续运行不属于当前项目','forbidden',403)
    with app.store.connect() as connection:
        successor=connection.execute("SELECT id FROM tasks WHERE json_extract(payload,'$.generation_plan.resume_from.run_id')=? ORDER BY created_at LIMIT 1",(task['id'],)).fetchone()
    require(not successor,'原运行已有接续；请从其后续运行继续，不能重置原累计额度','resume_superseded',409)
    require(task['status'] in {'paused','failed','cancelled'},'原运行尚未停止，不能同时接续','conflict',409)
    if app.runner:
        require(task['id'] not in app.runner.active and task['id'] not in app.runner.children,'原进程尚在收尾；接续未启动','conflict',409)
    original=task['payload']['generation_plan']
    require({'id':recipe['id'],'revision':recipe['revision']}==original['recipe_ref'] and digest(recipe)==original['recipe_sha256'],'接续必须指向原固定配方修订','plan_stale',409)
    for binding in original.get('recipe_bindings',[]):
        ref=binding['ref'];frozen=app.get(ref['id'],scope,ref['revision'])
        require(frozen['project_id']==project['id'] and frozen['kind']=='recipe' and digest(frozen)==binding['sha256'],'原多目标配方修订发生变化','plan_stale',409)
    current_environment=environment(app)
    binding=environment_binding(original['environment'],current_environment)
    checkpoint=app.store.setting('generation_checkpoint:'+task['id'],{'plan_hash':original['plan_hash'],'nodes':{}})
    require(checkpoint['plan_hash']==original['plan_hash'],'检查点不属于原计划','output_integrity',409)
    value=copy.deepcopy(original);value.pop('plan_hash');value['constraints']=copy.deepcopy(constraints)
    value['environment']=current_environment
    for node in value['nodes']:
        # The old plan stores full immutable input refs and exact code bytes.
        source=app.asset(node['script_snapshot']['sha256'],scope,project['id'])
        require(digest((app.store.blobs/source['sha']).read_bytes())==source['sha'] and digest(node['script_snapshot']['code'].encode())==source['sha'],'原代码快照改变','input_integrity',409)
        for ref in node['bound_inputs'].values():
            if ref['kind']=='dataset':
                data=app.get(ref['ref']['dataset_id'],scope,ref['ref']['revision'])
                require(data['content']['asset_sha256']==ref['asset_sha256'],'原数据修订引用改变','input_integrity',409)
                asset=app.asset(ref['asset_sha256'],scope,project['id']);require(digest((app.store.blobs/asset['sha']).read_bytes())==asset['sha'],'原输入字节改变','input_integrity',409)
        result=checkpoint['nodes'].get(node['id']) or node['reuse']
        if result:
            verify_output(app,project['id'],node,result)
            from research_partner.domains.generation.validity import ensure_reusable
            ensure_reusable(app.store,project['id'],result)
        node['reuse']=copy.deepcopy(result)
    value['pending']=[n['id'] for n in value['nodes'] if not n['reuse']];value['reused']=[n['id'] for n in value['nodes'] if n['reuse']];value['changed']=[]
    remaining=float(original['budget']['timeout_seconds'])-float(app.store.setting('elapsed:'+task['id'],0))
    require(remaining>0,'原运行累计执行额度已耗尽，不通过接续重置','budget_exhausted',409)
    value['budget']['timeout_seconds']=remaining
    value['resume_from']={'run_id':task['id'],'plan_hash':original['plan_hash'],'checkpoint_sha256':digest(checkpoint),'remaining_seconds':remaining,'frozen_source':True}
    if binding:value['resume_from']['environment_binding']=binding
    value['plan_hash']=digest(value)
    if persist:app.store.set_setting('generation_plan:'+value['plan_hash'],value)
    return value
