"""Content-addressed generation on the existing task, lease and asset service.

Recipes are managed revisions; registered Python files remain authoritative.
Planning reads/snapshots files and does not execute them. Only the pending
subgraph is compiled for Snakemake, with verified cache hits as external inputs.
No model, scientific approval or automatic adoption is part of this service.
"""
from __future__ import annotations
import copy
import csv
import io
import json
import os
from pathlib import Path
import re
import shlex
import stat
import sys
from .store import Problem, require, uid, digest, encoded, now
from .notebook import _open_dir, _read_at, _create_at, _replace_at

ROOT=Path(__file__).resolve().parent.parent
MAX_BYTES=16*1024*1024
NAME=re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')
FILE=re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}')


def table(raw, contract):
    require(isinstance(contract,dict) and set(contract)<={'format','columns','identity_fields','units'},'表格I/O合同含未支持字段')
    require(contract.get('format')=='csv','当前受管数据支持UTF-8 CSV；其他格式保留未支持边界','unsupported_format',422)
    columns=contract.get('columns');ids=contract.get('identity_fields');units=contract.get('units')
    require(isinstance(columns,list) and columns and all(isinstance(c,str) and c for c in columns) and len(columns)==len(set(columns)),'CSV字段合同无效')
    require(isinstance(ids,list) and ids and all(isinstance(c,str) and c for c in ids) and len(ids)==len(set(ids)) and set(ids)<=set(columns),'必须明确身份字段')
    require(isinstance(units,dict) and set(units)<=set(columns) and all(isinstance(v,str) and v for v in units.values()),'单位声明无效')
    require(len(raw)<=MAX_BYTES,'CSV超过本切片16MiB边界；原数据保留','context_limit',413)
    try:
        reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline=''))
        require(reader.fieldnames==columns,'实际CSV列及顺序与合同不同','io_mismatch',422)
        rows=list(reader)
    except (UnicodeError,csv.Error) as error:raise Problem('不能按声明读取CSV；原输入未改变','source_unreadable',422) from error
    require(all(None not in r and all(v is not None for v in r.values()) for r in rows),'CSV行缺列或多列','io_mismatch',422)
    members=[{c:r[c] for c in ids} for r in rows]
    keys=[encoded(m) for m in members]
    require(all(all(v!='' for v in m.values()) for m in members) and len(keys)==len(set(keys)),'身份字段缺失或重复；不推测映射','identity_mismatch',422)
    return {'row_count':len(rows),'members':members,'ordered_members_sha256':digest(members),'contract':copy.deepcopy(contract)}


def _project(app, ident, scope, principal):
    from .desk_w1a import _project as project
    return project(app,ident,scope,principal,True)


def _owner(principal):
    require(not principal or principal.get('kind')!='agent' and principal.get('actor_kind')!='agent','Agent不能自行授权代码或采用计算定义','forbidden',403)


def script(app, project, filename, *, raw=None, expected=None):
    require(isinstance(filename,str) and FILE.fullmatch(filename) and filename.endswith('.py'),'脚本必须是scripts下明确的.py文件')
    with app.notebook._locked(project['id']) as session:
        fd=_open_dir(session['project_root_fd'],'scripts',create=raw is not None)
        try:
            previous=_read_at(fd,filename,absent=raw is not None)
            if raw is not None:
                require(len(raw)<=1024*1024,'脚本超过1MiB显示/编辑边界','context_limit',413)
                try:raw.decode('utf-8')
                except UnicodeError as error:raise Problem('脚本不是UTF-8；文件未改变','source_unreadable',422) from error
                require((expected is None and previous is None) or (previous is not None and digest(previous)==expected),'脚本文件已改变；未覆盖外改','script_conflict',409)
                require(_read_at(fd,filename,absent=True)==previous,'脚本外改与保存竞争；原输入保留','script_conflict',409)
                if previous is None:_create_at(fd,filename,raw)
                else:
                    app.store.add_asset(previous,filename,'text/x-python',{'project_id':project['id'],'script_snapshot':True})
                    _replace_at(fd,filename,raw)
                actual=_read_at(fd,filename)
                require(actual==raw,'脚本保存后发生外改；两份字节均保留','script_conflict',409)
            else:actual=previous
        finally:os.close(fd)
    require(actual is not None,'脚本文件不存在','not_found',404)
    try:code=actual.decode('utf-8')
    except UnicodeError as error:raise Problem('脚本不是UTF-8；不执行或转换','source_unreadable',422) from error
    asset=app.store.add_asset(actual,filename,'text/x-python',{'project_id':project['id'],'script_snapshot':True,'source_path':'scripts/'+filename})
    return {'relative_path':'scripts/'+filename,'sha256':asset['sha'],'code':code,'authority_kind':'file','executed':False}


def environment(app):
    python=Path(app.config.get('generation',{}).get('python') or app.config.get('rendering',{}).get('scientific_python') or os.environ.get('RESEARCH_PARTNER_SCIENTIFIC_PYTHON',sys.executable))
    command=app.config.get('generation',{}).get('snakemake') or os.environ.get('RESEARCH_PARTNER_SNAKEMAKE')
    runtime_record=app.config.get('generation',{}).get('runtime_record') or os.environ.get('RESEARCH_PARTNER_GENERATION_RUNTIME_RECORD')
    lock=ROOT/'development/core-generation-runtime.lock'
    inventory=ROOT/'development/core-existing-python-runtime.json'
    worker=Path(__file__).with_name('generation_worker.py')
    require(python.is_file(),'配置的计算解释器不可访问','runtime_unavailable',503)
    readiness=None
    if command and runtime_record:
        try:
            receipt=json.loads(Path(runtime_record).read_text())
            require(receipt['version']=='9.27.0' and receipt['snakemake']==str(command) and receipt['lock_sha256']==digest(lock.read_bytes()) and receipt['snakemake_sha256']==digest(Path(command).read_bytes()),'Snakemake运行时与锁定记录不符','runtime_unavailable',503)
            require(receipt['python_sha256']==digest(Path(receipt['python']).read_bytes()),'Snakemake解释器已改变，需要新环境识别','runtime_unavailable',503)
            require(isinstance(receipt['packages'],list) and receipt['packages'],'实际安装清单缺失','runtime_unavailable',503)
            for package in receipt['packages']:
                for name in ['metadata','record']:require(digest(Path(package[name]).read_bytes())==package[name+'_sha256'],'已安装包清单已改变，需要新环境识别','runtime_unavailable',503)
            readiness={'path':str(runtime_record),'sha256':digest(Path(runtime_record).read_bytes()),'version':receipt['version']}
        except (KeyError,ValueError,OSError) as error:raise Problem('Snakemake安装记录不可核验；不执行未识别入口','runtime_unavailable',503) from error
    value={'platform':sys.platform,'interpreter':str(python),'interpreter_sha256':digest(python.read_bytes()),
           'lock_refs':[{'path':str(p),'sha256':digest(p.read_bytes())} for p in (lock,inventory) if p.is_file()],
           'worker_sha256':digest(worker.read_bytes()),'snakemake':str(command) if command else None,
           'snakemake_sha256':digest(Path(command).read_bytes()) if readiness else None,'snakemake_runtime':readiness,
           'reproducibility_level':'same_environment','cross_machine_tested':False}
    return value


def _recipe(app, ref, scope, project):
    require(isinstance(ref,dict) and set(ref)=={'id','revision'},'计划需要准确配方修订')
    require(type(ref['revision']) is int and ref['revision']>0,'配方需要实际正修订，不以0暗指最新版')
    recipe=app.get(ref['id'],scope,ref['revision'])
    require(recipe['kind']=='recipe' and recipe['project_id']==project['id'] and not recipe['archived'],'需要本项目配方')
    return recipe


def plan(app, project, recipe, constraints, scope, *, persist=True):
    require(isinstance(constraints,dict),'计划约束必须为明确对象')
    if 'resume_run_id' in constraints:
        from .generation_checkpoint import remaining_plan
        return remaining_plan(app,project,recipe,constraints,scope,persist)
    require(set(constraints)<={'force_nodes','timeout_seconds'},'计划约束含未支持字段')
    definitions=recipe['content'].get('steps');require(isinstance(definitions,list) and 1<=len(definitions)<=32,'配方需要1–32项有I/O合同的代码步骤')
    require(all(isinstance(d,dict) for d in definitions),'每一步必须是明确对象')
    ids=[d.get('id') for d in definitions]
    require(all(isinstance(i,str) and NAME.fullmatch(i) for i in ids) and len(ids)==len(set(ids)),'步骤身份重复或无效')
    timeout=constraints.get('timeout_seconds',180);require(type(timeout) is int and 1<=timeout<=600,'本次计算时限必须为1–600秒')
    force=constraints.get('force_nodes',[]);require(isinstance(force,list) and all(isinstance(i,str) for i in force) and set(force)<=set(ids),'强制重做集合无效')
    from .generation_identity import key_environment, verify_relocated_cache
    env=environment(app);key_env,env_binding=key_environment(app.store,project['id'],env);nodes=[];by_id={}
    for definition in definitions:
        require(set(definition)=={'id','role','script','parameters','inputs','io','config_keys','deterministic'},'步骤必须声明科学职责、脚本、参数、配置键、输入和I/O合同')
        ident=definition['id'];require(isinstance(definition['role'],str) and definition['role'].strip(),'代码步骤缺少职责说明')
        params=definition['parameters'];keys=definition['config_keys']
        require(isinstance(params,dict) and len(encoded(params))<=64000 and isinstance(keys,list) and all(isinstance(k,str) for k in keys) and len(keys)==len(set(keys)) and set(keys)==set(params),'配置键必须逐项对应实际参数')
        require(type(definition['deterministic']) is bool,'必须声明确定性；不推测随机种子')
        source=script(app,project,definition['script'])
        io_contract=definition['io'];require(isinstance(io_contract,dict) and set(io_contract)=={'inputs','outputs'},'需要可读输入输出合同')
        inputs=definition['inputs'];require(isinstance(inputs,dict) and isinstance(io_contract['inputs'],dict) and set(inputs)==set(io_contract['inputs']),'输入映射与I/O合同不同')
        outputs=io_contract['outputs'];require(isinstance(outputs,dict) and outputs and len(outputs)<=16 and all(isinstance(n,str) and FILE.fullmatch(n) and n not in {'outputs.json','job.json'} for n in outputs),'输出文件名无效')
        bound={}
        for alias,ref in inputs.items():
            require(NAME.fullmatch(alias),'输入别名无效')
            require(isinstance(ref,dict),'输入引用必须为明确对象')
            contract=io_contract['inputs'][alias]
            if set(ref)=={'dataset_id','revision'}:
                require(type(ref['revision']) is int and ref['revision']>0,'数据需要实际固定修订')
                data=app.get(ref['dataset_id'],scope,ref['revision']);require(data['kind']=='dataset' and data['project_id']==project['id'],'数据快照不属于项目')
                require(data['content'].get('authority_kind') != 'immutable_member_manifest',
                        '此分块成员来源尚未连接计算适配器；未创建运行计划', 'unsupported_dataset_adapter', 422)
                asset=app.asset(data['content']['asset_sha256'],scope,project['id']);actual=table((app.store.blobs/asset['sha']).read_bytes(),contract)
                require(actual==data['content']['snapshot'],'输入身份、顺序或单位与固定快照不同','identity_mismatch',409)
                bound[alias]={'kind':'dataset','ref':ref,'asset_sha256':asset['sha'],'snapshot':actual,'contract':contract}
            elif set(ref)=={'node_id','output'}:
                upstream=by_id.get(ref['node_id']);require(upstream is not None,'依赖缺失、成环或顺序不合法；不自动补画来源')
                declared=upstream['io']['outputs'].get(ref['output']);require(declared==contract,'上下游字段/身份/单位合同不一致','io_mismatch',422)
                bound[alias]={'kind':'node','node_id':ref['node_id'],'output':ref['output'],'node_key':upstream['node_key'],'contract':contract}
            else:require(False,'来源必须为固定数据快照或登记节点输出')
        for contract in outputs.values():
            # Validate the contract without inventing output rows.
            require(isinstance(contract,dict) and set(contract)=={'format','columns','identity_fields','units'} and contract['format']=='csv','当前计算输出必须是带身份/单位的CSV合同')
            header=io.StringIO(newline='');csv.writer(header).writerow(contract['columns']);table(header.getvalue().encode(),contract)
        node={**copy.deepcopy(definition),'script_snapshot':source,'bound_inputs':bound,'environment':env}
        node['node_key']=digest({**node,'environment':key_env})
        cached=app.store.setting('generation_cache:'+project['id']+':'+node['node_key'])
        reusable=bool(cached and definition['deterministic'] and ident not in force and all(r['kind']=='dataset' or by_id[r['node_id']]['reuse'] for r in bound.values()))
        if reusable:
            try:
                from .generation_validity import ensure_reusable
                ensure_reusable(app.store,project['id'],cached)
                if env_binding:verify_relocated_cache(node,cached,by_id)
                for name,output in cached['outputs'].items():
                    asset=app.asset(output['asset_sha256'],scope,project['id']);raw=(app.store.blobs/asset['sha']).read_bytes()
                    require(digest(raw)==asset['sha'] and table(raw,outputs[name])==output['snapshot'],'缓存实际输出核验失败')
            except (Problem,OSError,KeyError):reusable=False
        node['reuse']=copy.deepcopy(cached) if reusable else None
        if not reusable and ident in force:
            for descendant in definitions:
                if any(r.get('node_id')==ident for r in descendant['inputs'].values()) and descendant['id'] not in force:force=[*force,descendant['id']]
        nodes.append(node);by_id[ident]=node
    previous_runs=[t for t in app.store.tasks() if t['project_id']==project['id'] and t['payload'].get('kind')=='generation' and t['payload'].get('generation_plan',{}).get('recipe_ref',{}).get('id')==recipe['id']]
    previous=previous_runs[0]['payload']['generation_plan'] if previous_runs else None
    old_keys={n['id']:n['node_key'] for n in previous['nodes']} if previous else {}
    value={'project_id':project['id'],'recipe_ref':{'id':recipe['id'],'revision':recipe['revision']},'recipe_sha256':digest(recipe),
           'nodes':nodes,'environment':env,'constraints':copy.deepcopy(constraints),'pending':[n['id'] for n in nodes if not n['reuse']],
           'reused':[n['id'] for n in nodes if n['reuse']], 'changed':[n['id'] for n in nodes if old_keys.get(n['id'])!=n['node_key']],
           'budget':{'timeout_seconds':timeout,'max_model_calls':0,'max_output_bytes':MAX_BYTES},'scientific_approval':False}
    if env_binding:value.update(node_key_environment=key_env,node_key_environment_binding=env_binding)
    value['plan_hash']=digest(value)
    require(len(encoded(value).encode())<=4*1024*1024,'固定计划超过本切片4MiB边界；原数据保留','context_limit',413)
    if persist:app.store.set_setting('generation_plan:'+value['plan_hash'],value)
    return value


def guard(app, task, connection=None):
    from .generation_validity import check_plan_reuse
    check_plan_reuse(app.store,task['payload']['generation_plan'],connection)
    payload=task['payload'];p=payload['generation_plan'];grant=app.store.setting('generation_grant:'+payload['authorization_ref'],{})
    require(grant.get('plan_hash')==p['plan_hash'] and grant.get('active') is True,'本计划计算授权已撤回','authorization_required',403)
    require(not grant.get('consumed_request') or task.get('request_key')==grant['consumed_request'],'本次执行授权已被另一请求使用','authorization_required',403)
    from .project_management import authority_scope
    _project(app,p['project_id'],authority_scope(app,grant['principal']),grant['principal'])
    require(environment(app)==p['environment'],'执行环境或工具已改变，不能沿用旧计划','environment_changed',409)


def figure_source(app,figure,scope):
    """Read the exact registered run behind current input bytes, never redraw."""
    ref=figure['content'].get('computation_path',{})
    if not isinstance(ref,dict) or not ref.get('run_id'):return None
    task=app.store.task(ref['run_id']);require(task['project_id']==figure['project_id'] and task['payload'].get('kind')=='generation','图来源运行不属于此项目','forbidden',403)
    p=task['payload']['generation_plan'];require(ref.get('plan_hash')==p['plan_hash'],'图来源计划身份不同','source_mismatch',409)
    actual=task['result'].get('nodes',{});links=[];unknown=[]
    for alias,value in figure['content'].get('input_assets',{}).items():
        sha=value.get('sha',value.get('asset')) if isinstance(value,dict) else value
        matches=[{'node_id':name,'output':filename,'asset_sha256':sha} for name,node in actual.items() for filename,out in node.get('outputs',{}).items() if out['asset_sha256']==sha]
        if matches:links.append({'figure_input':alias,'outputs':matches})
        else:unknown.append({'figure_input':alias,'asset_sha256':sha,'reason':'未登记为此运行输出；不补画上游'})
    steps=[]
    for node in p['nodes']:
        outputs=[]
        for name,out in actual.get(node['id'],{}).get('outputs',{}).items():
            asset=app.asset(out['asset_sha256'],scope,figure['project_id']);available=(app.store.blobs/asset['sha']).is_file()
            if available:available=digest((app.store.blobs/asset['sha']).read_bytes())==asset['sha']
            outputs.append({'name':name,**out,'available':available,'url':'/api/assets/'+asset['sha']})
        steps.append({'id':node['id'],'role':node['role'],'script':node['script_snapshot'],'parameters':node['parameters'],'config_keys':node['config_keys'],'io':node['io'],'inputs':node['bound_inputs'],'outputs':outputs,'reused_from_run':actual.get(node['id'],{}).get('run_id')})
    return {'run_id':task['id'],'run_status':task['status'],'plan_hash':p['plan_hash'],'recipe_ref':p['recipe_ref'],'steps':steps,'figure_input_links':links,'unknown_inputs':unknown,'execution_on_open':False,
            'scope':'已登记I/O及实际输出；未声明的脚本内文件/网络读取未被当前账号进程隔离证明'}


def dispatch(app, data, scope=None, principal=None):
    project=_project(app,data.get('project_id'),scope,principal);action=data['action'];payload=data.get('payload',{})
    if action.startswith('build.result_errors.'):
        from .generation_validity import dispatch as result_error_dispatch
        return result_error_dispatch(app,data,project,scope,principal)
    if action=='desk.datasets.list':return {'datasets':app.store.objects(project['id'],['dataset'],False),'recipes':app.store.objects(project['id'],['recipe'],False),'runs':[{'id':t['id'],'status':t['status'],'error':t['error'],'result':t['result'],'created_at':t['created_at']} for t in app.store.tasks() if t['project_id']==project['id'] and t['payload'].get('kind')=='generation']}
    if action=='dataset.read':
        ref=payload.get('ref');require(isinstance(ref,dict) and set(ref)=={'id','revision'} and type(ref['revision']) is int and ref['revision']>0,'读取需要固定数据修订')
        obj=app.get(ref['id'],scope,ref['revision']);require(obj['kind']=='dataset' and obj['project_id']==project['id'],'数据修订不属于项目','forbidden',403);return obj
    if action=='dataset.members.read':
        from .dataset_manifests import page
        return page(app,project,payload,scope,principal)
    if action=='recipe.script.read':return script(app,project,payload.get('filename'))
    if action=='build.status':
        task=app.store.task(payload.get('run_id'));require(task['project_id']==project['id'] and task['payload'].get('kind')=='generation','运行不属于此项目','forbidden',403)
        with app.store.connect() as connection:
            successor=connection.execute("SELECT id FROM tasks WHERE json_extract(payload,'$.generation_plan.resume_from.run_id')=? ORDER BY created_at LIMIT 1",(task['id'],)).fetchone()
        can_resume=bool(not successor and app.runner and task['status'] in {'paused','failed','cancelled'} and task['id'] not in app.runner.active and task['id'] not in app.runner.children)
        return {'run':task,'steps':task['steps'],'checkpoint':app.store.setting('generation_checkpoint:'+task['id'],{}),'can_resume_checkpoint':can_resume,'resume_successor_id':successor['id'] if successor else None,'executed_on_read':False}
    if action=='build.control':
        _owner(principal)
        task=app.store.task(payload.get('run_id'))
        require(task['project_id']==project['id'] and task['payload'].get('kind')=='generation','运行不属于此项目','forbidden',403)
        require(payload.get('operation') in {'pause','cancel'},'当前仅支持暂停/取消；接续须重新核对计划，不隐式重跑','unsupported_action',422)
        require(app.runner is not None,'执行器未启动；保留历史，不伪造停止回执','runtime_unavailable',503)
        return {'run':app.runner.control(task['id'],payload['operation']),'automatic_resume':False}
    _owner(principal)
    require(isinstance(data.get('request_id'),str) and 0<len(data['request_id'])<=200,'生成修改需要稳定请求身份')
    if action=='dataset.revise':
        from .dataset_membership import revise
        return revise(app,project,data,scope)
    if action=='dataset.snapshot':
        if isinstance(payload,dict) and 'dataset' in payload:
            from .dataset_manifests import create
            return create(app,project,data,scope,principal)
        asset=app.asset(payload.get('asset_sha256'),scope,project['id']);snapshot=table((app.store.blobs/asset['sha']).read_bytes(),payload.get('contract'))
        content={'asset_sha256':asset['sha'],'snapshot':snapshot,'authority_kind':'immutable_asset','source_filename':asset['filename']}
        require(len(encoded(snapshot).encode())<=4*1024*1024,'成员清单超过本切片边界；未以摘要替代实际集合','context_limit',413)
        key='dataset_request:'+project['id']+':'+data['request_id']
        with app.store.transaction() as c:
            row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
            if row:
                existing=json.loads(row[0]);require(existing['input']==digest(payload),'同一快照请求内容不同','idempotency_conflict',409);return app.store.get(existing['id'],1,c)
            obj=app.store.create('dataset',payload.get('title'),project['id'],content=content,connection=c)
            c.execute('INSERT INTO kv VALUES(?,?)',(key,encoded({'input':digest(payload),'id':obj['id']})));return obj
    if action=='recipe.script.import':
        asset=app.asset(payload.get('asset_sha256'),scope,project['id']);return script(app,project,payload.get('filename'),raw=(app.store.blobs/asset['sha']).read_bytes())
    if action=='recipe.script.write':return script(app,project,payload.get('filename'),raw=payload.get('code','').encode('utf-8'),expected=payload.get('expected_sha256'))
    if action=='recipe.propose':
        require(set(payload)=={'title','steps'},'配方仅接标题及明确步骤')
        candidate={'id':data.get('object_id') or 'UNSAVED','kind':'recipe','project_id':project['id'],'revision':data.get('expected_revision',0)+1,'archived':False,'content':{'steps':payload['steps']},'title':payload['title']}
        # Resolve and validate before writing; it never runs code.
        plan(app,project,candidate,{},scope,persist=False)
        key='recipe_request:'+project['id']+':'+data['request_id'];fingerprint=digest(data)
        with app.store.transaction() as c:
            row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
            if row:
                old=json.loads(row[0]);require(old['input']==fingerprint,'同一配方请求内容不同','idempotency_conflict',409);return old['result']
            if data.get('object_id'):
                obj=app.store.get(data['object_id'],connection=c);app.access(obj,scope);require(obj['project_id']==project['id'] and obj['kind']=='recipe','配方归属不同')
                result=app.store.save(obj['id'],data.get('expected_revision'),content={'steps':payload['steps']},title=payload['title'],merge=False,reason='explicit recipe edit',connection=c)
            else:result=app.store.create('recipe',payload['title'],project['id'],content={'steps':payload['steps']},connection=c)
            c.execute('INSERT INTO kv VALUES(?,?)',(key,encoded({'input':fingerprint,'result':result})));return result
    if action=='build.plan':
        from .generation_batch import targets
        return targets(app,project,payload.get('target_refs'),payload.get('constraints',{}),scope)
    p=app.store.setting('generation_plan:'+payload.get('plan_hash',''));require(p and p['project_id']==project['id'],'固定计划不存在','not_found',404)
    if action=='build.authorize':
        require(scope is None,'仅所有者可授权导入脚本执行','forbidden',403)
        require(payload.get('approved') is True,'代码执行需要显式批准','authorization_required',403)
        key='generation_authorize:'+project['id']+':'+data['request_id'];fingerprint=digest(payload)
        with app.store.transaction() as c:
            row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
            if row:
                saved=json.loads(row[0]);require(saved['input']==fingerprint,'同一授权请求内容不同','idempotency_conflict',409);return saved['result']
            ref=uid('BUILDGRANT');grant={'active':True,'plan_hash':p['plan_hash'],'principal':principal or {'kind':'local_operator'},'at':now(),'sandbox':False,'max_runs':1}
            result={'authorization_ref':ref,'plan_hash':p['plan_hash'],'sandbox':False,'executed':False}
            c.execute('INSERT INTO kv VALUES(?,?)',('generation_grant:'+ref,encoded(grant)))
            c.execute('INSERT INTO kv VALUES(?,?)',(key,encoded({'input':fingerprint,'result':result})));return result
    if action=='build.start':
        from .generation_validity import check_plan_reuse
        check_plan_reuse(app.store,p)
        task_payload={'kind':'generation','project_id':project['id'],'context':{'materials':[],'output':'result'},'generation_plan':p,'authorization_ref':payload.get('authorization_ref'),'budget':p['budget'],'depends_on':[]}
        request='generation:'+project['id']+':'+data['request_id']
        with app.store.connect() as c:previous=c.execute('SELECT id,payload_digest FROM tasks WHERE request_key=?',(request,)).fetchone()
        if previous:
            require(previous['payload_digest']==digest(task_payload),'重复生成请求内容不同','idempotency_conflict',409)
            return {'run_id':previous['id'],'task':app.store.task(previous['id']),'plan_hash':p['plan_hash'],'shared_existing_run':False}
        if p.get('shared_generation'):
            from .generation_batch import replayed
            existing=replayed(app,request,task_payload)
            if existing:return {'run_id':existing['id'],'task':existing,'plan_hash':p['plan_hash'],'shared_existing_run':True}
        if app.config.get('development_budget'):
            from .development_budget import Budget
            Budget(app.config['development_budget']).check()
        require(app.runner is not None,'持久执行器未启动；未创建假运行','runtime_unavailable',503)
        require(p['environment']['snakemake_sha256'],'Snakemake尚未就绪；未启动替代执行器','runtime_unavailable',503)
        bindings=p.get('recipe_bindings') or [{'ref':p['recipe_ref'],'sha256':p['recipe_sha256']}]
        for binding in bindings:
            ref=binding['ref'];current=app.get(ref['id'],scope,ref['revision'] if p.get('resume_from') else None)
            require(digest(current)==binding['sha256'],'待执行配方已改变，请固定新计划；历史运行不变','plan_stale',409)
        from .generation_batch import targets,material_identity,joined
        fresh=targets(app,project,[b['ref'] for b in bindings],p['constraints'],scope)
        shared=p.get('shared_generation') is True
        if shared:require(material_identity(fresh)==material_identity(p),'共享目标的输入、代码或范围已改变，需要新plan_hash','plan_stale',409)
        else:require(fresh['plan_hash']==p['plan_hash'],'输入、代码、环境或复用集合已改变，需要新plan_hash','plan_stale',409)
        guard(app,{'payload':task_payload,'request_key':request})
        from .compatibility import require_features
        def preflight(c):
            check_plan_reuse(app.store,p,c)
            require_features(c,['content_generation_plans_v1'])
            if shared:require_features(c,['shared_generation_plans_v1'])
            if p.get('resume_from'):
                parent=p['resume_from']['run_id']
                successor=c.execute("SELECT id FROM tasks WHERE json_extract(payload,'$.generation_plan.resume_from.run_id')=? LIMIT 1",(parent,)).fetchone()
                require(not successor,'原运行已在另一请求接续，未创建第二执行链','resume_superseded',409)
            key='generation_grant:'+payload['authorization_ref'];row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone();grant=json.loads(row[0]) if row else {}
            require(grant.get('active') and grant.get('plan_hash')==p['plan_hash'] and not grant.get('consumed_request'),'计算授权已撤回或被使用','authorization_required',403)
            grant['consumed_request']=request;c.execute('UPDATE kv SET value=? WHERE key=?',(encoded(grant),key))
        with app.store.transaction() as c:
            check_plan_reuse(app.store,p,c)
            task=joined(app,p,payload,request,task_payload,c) if shared else None
            joined_existing=task is not None
            if task is None:
                require(fresh['plan_hash']==p['plan_hash'],'复用集合已改变，需要新plan_hash','plan_stale',409)
                task=app.store.submit(task_payload,request,preflight=preflight,connection=c)
        app.runner.wake();return {'run_id':task['id'],'task':task,'plan_hash':p['plan_hash'],'shared_existing_run':joined_existing}
    require(False,'生成命令未实现','unsupported_action',422)


def execute(runtime, task):
    p=task['payload']['generation_plan'];app=runtime.app;ident=task['id'];token=task['execution_token']
    directory=runtime.runs/ident/('attempt-'+str(task['attempts']));directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    paths={};rules=[];rule_nodes={}
    inputs_dir=directory/'inputs';inputs_dir.mkdir(mode=0o700)
    def frozen_input(sha):
        app.asset(sha,[p['project_id']],p['project_id']);raw=(app.store.blobs/sha).read_bytes();require(digest(raw)==sha,'不可变输入字节不符','input_integrity',409)
        target=inputs_dir/(sha+'.csv')
        if not target.exists():target.write_bytes(raw);target.chmod(0o400)
        return str(target)
    for number,node in enumerate(p['nodes']):
        node_dir=directory/node['id'];node_dir.mkdir(mode=0o700)
        if node['reuse']:
            paths[node['id']]={name:frozen_input(out['asset_sha256']) for name,out in node['reuse']['outputs'].items()};continue
        outputs={name:str(node_dir/name) for name in node['io']['outputs']};paths[node['id']]=outputs
        bound={alias:frozen_input(r['asset_sha256']) if r['kind']=='dataset' else paths[r['node_id']][r['output']] for alias,r in node['bound_inputs'].items()}
        script_path=node_dir/'source.py';script_path.write_text(node['script_snapshot']['code'],encoding='utf-8')
        job={'node_key':node['node_key'],'script':str(script_path),'script_sha256':node['script_snapshot']['sha256'],'inputs':bound,'parameters':node['parameters'],'output_dir':str(node_dir),'contracts':node['io'],'plan_hash':p['plan_hash']}
        job_path=node_dir/'job.json';job_path.write_text(encoded(job)+'\n')
        cmd=shlex.join([p['environment']['interpreter'],str(Path(__file__).with_name('generation_worker.py')),str(job_path)])
        # Public node IDs may contain '-'. Internal rule identifiers are
        # separately valid Python identifiers and map back to exact node IDs.
        rule='rp_job_'+str(number);rule_nodes[rule]=node['id']
        rules.append('rule '+rule+':\n    input: '+repr(list(bound.values()))+'\n    output: '+repr([*outputs.values(),str(node_dir/'outputs.json')])+'\n    shell: '+repr(cmd)+'\n')
    snake=directory/'Snakefile';snake.write_text('\n'.join(rules))
    targets=[str(directory/n/'outputs.json') for n in p['pending']]
    actual=[];processes=[]
    try:
        if targets:
            argv=[p['environment']['snakemake'],'--snakefile',str(snake),'--directory',str(directory),'--cores','1','--nocolor','--rerun-triggers','mtime','--']+targets
            env={k:v for k,v in os.environ.items() if k in {'PATH','LANG','LC_ALL','LC_CTYPE','TZ'}}
            env.update(XDG_CACHE_HOME=str(directory/'cache'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
            dry=runtime.run_process(ident,argv[:1]+['--dry-run']+argv[1:],directory,env=env);processes.append(dry)
            text=dry['stdout']+'\n'+dry['stderr']
            actual_rules=re.findall(r'^(?:local)?rule ([A-Za-z_][A-Za-z0-9_]*):',text,re.M)
            require(all(rule in rule_nodes for rule in actual_rules),'Snakemake含计划外job，未执行','execution_graph_mismatch',409)
            actual=[rule_nodes[rule] for rule in actual_rules]
            require(dry['returncode']==0 and sorted(actual)==sorted(p['pending']),'Snakemake实际待跑job集合与计划不同；未执行','execution_graph_mismatch',409)
            executed=runtime.run_process(ident,argv,directory,env=env);processes.append(executed)
            from .generation_checkpoint import collect
            collect(runtime,task,directory)
            require(executed['returncode']==0,'计算退出失败；已核验独立步骤保留，未发布完整结果','execution_failed',422)
        runtime.check(ident);results={}
        for node in p['nodes']:
            if node['reuse']:results[node['id']]=node['reuse'];continue
            node_dir=directory/node['id'];manifest=json.loads((node_dir/'outputs.json').read_text())
            require(manifest['node_key']==node['node_key'] and manifest['plan_hash']==p['plan_hash'] and set(manifest['outputs'])==set(node['io']['outputs']),'实际输出清单与固定计划不符','output_integrity',409)
            outputs={}
            for name,contract in node['io']['outputs'].items():
                path=node_dir/name;info=path.lstat();require(stat.S_ISREG(info.st_mode) and info.st_nlink==1 and info.st_size<=MAX_BYTES,'输出不是受管普通文件','output_integrity',409)
                raw=path.read_bytes();snapshot=table(raw,contract);require(digest(raw)==manifest['outputs'][name]['sha256'],'输出字节与执行清单不同','output_integrity',409)
                asset=app.store.add_asset(raw,name,'text/csv',{'project_id':p['project_id'],'generation_output':True,'run_id':ident,'node_key':node['node_key'],'plan_hash':p['plan_hash']},task_id=ident,execution_token=token)
                outputs[name]={'asset_sha256':asset['sha'],'snapshot':snapshot}
            result={'run_id':ident,'node_key':node['node_key'],'outputs':outputs,'actual_inputs':manifest['inputs'],'source_script_sha256':node['script_snapshot']['sha256'],'parameters':node['parameters'],'io':node['io'],'verified_at':now()}
            results[node['id']]=result
            app.store.set_setting('generation_cache:'+p['project_id']+':'+node['node_key'],result,task_id=ident,execution_token=token)
            app.store.step(ident,'generation:'+node['id'],'verified',result,execution_token=token)
        result={'plan_hash':p['plan_hash'],'recipe_ref':p['recipe_ref'],'nodes':results,'planned_jobs':p['pending'],'actual_dry_run_jobs':actual,'reused_nodes':p['reused'],'processes':processes,'scientific_approval':False,'adoption':'candidate','output_checks':'actual_files_identity_units_and_hashes'}
        if p.get('shared_generation'):
            from .generation_batch import target_results
            result.update(recipe_refs=p['recipe_refs'],target_results=target_results(p,results))
        app.store.task_update(ident,'generated',result=result,execution_token=token)
    except Exception:
        # Files stay in this owned attempt for diagnosis. No success marker,
        # invented result or automatic retry is produced on an incomplete run.
        raise
