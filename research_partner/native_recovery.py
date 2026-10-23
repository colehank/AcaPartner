"""Explicit, zero-dispatch recovery of a failed delegate's registered candidate.

This path never resumes a provider and never changes its native capsule. The
parent stays at its existing handoff until a separate explicit continuation.
"""
import copy
import difflib
import json
from pathlib import Path
from .store import Problem, require, digest, encoded, now
from .providers import _native_checkpoint, _native_candidate, _controlled_file
from .native_accounting import accounting, public_accounting
from .commission import candidate_input_snapshot, validate_candidate
from .questions import model_questions


FEATURE='native_explicit_recovery_v1'


def _setting(c,key):
    row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None


def _directory(app,ident):
    base=Path(app.config.get('control_root',str(Path.home()/'.local/share/research-partner/control'))).expanduser()
    default=base/digest(str(app.store.workspace))[:20]/ident
    candidates=[default,*[Path(root).expanduser()/ident for root in app.config.get('native_recovery_roots',[])]]
    found=list(dict.fromkeys(str(path.absolute()) for path in candidates if path.is_dir()))
    require(len(found)==1,'原生恢复目录缺失或不唯一；只读取明确配置的旧实例目录','candidate_checkpoint_unavailable',503)
    return Path(found[0])


def _guard(app,c,ident,scope,*,completed=False):
    s=app.store;task=s.task(ident,c);p=task['payload']
    if p.get('cycle_provider_route')=='codex':
        from .codex_recovery import guard
        return guard(app,c,ident,scope,completed=completed)
    project=s.get(task['project_id'],connection=c);app.access(project,scope)
    require(not project['archived'],'协作项目已归档','forbidden',403)
    require(scope is None or project['id'] in scope,'共享材料不授予候选接回权限','forbidden',403)
    require(p.get('cycle_role')=='delegate' and p.get('cycle_parent') and p.get('cycle_provider_route')=='deepseek_harness',
            '此接回入口仅处理原协作分工的 DeepSeek 候选，不改写正式成果','invalid',400)
    require(task['status'] in ({'generated'} if completed else {'failed','waiting_input','waiting_resource','waiting_authorization'}),
            '任务仍在执行、已暂停/取消或已有结果；不能接回','cancelled',409)
    lease=_setting(c,'execution:'+ident)
    require(not lease or lease.get('state')!='active','原执行租约尚未结束','conflict',409)
    parent=s.task(p['cycle_parent'],c);state=parent['result'].get('cycle',{})
    require(parent['status']=='waiting_input' and state.get('phase') in {'delegating','reworking','reviewing'}
            and state.get('last_failure',{}).get('code')=='cycle_handoff',
            '父协作必须处于失败交接；暂停、取消或其他阶段不能接回','cancelled',409)
    require(ident in state.get('delegates',[]) and state.get('epoch')==_setting(c,'cycle_epoch:'+p['cycle_child_key']),
            '原分工不属于父协作当前轮次','cancelled',409)
    for ref in [{'id':parent['id']},*state.get('children',[])]:
        current=s.task(ref['id'],c);lease=_setting(c,'execution:'+current['id'])
        require(current['status'] not in {'queued','running'} and (not lease or lease.get('state')!='active'),
                '原协作执行尚未停止；接回不清租约或中断在途任务','conflict',409)
    if state['phase']=='reviewing':
        reviewer_id=state.get('reviewer')
        require(any(ref['id']==reviewer_id and ref['role']=='reviewer' for ref in state.get('children',[])),
                '审查交接缺少此轮审查身份','conflict',409)
        reviewer=s.task(reviewer_id,c);rp=reviewer['payload']
        require(rp.get('cycle_parent')==parent['id'] and rp.get('cycle_role')=='reviewer'
                and state['epoch']==_setting(c,'cycle_epoch:'+rp['cycle_child_key'])
                and rp['context'].get('cycle_handoff_generation',0)==state.get('revision_generation',0)
                and any(e.get('task_id')==ident and e.get('no_scientific_output') is True
                        for e in rp['context'].get('cycle_evidence',[])),
                '原审查没有把该失败分工作为缺失证据；不能替换此审查输入','conflict',409)
    allocation=state.get('allocations',{}).get(p['cycle_child_key'],{})
    require(allocation.get('task_id')==ident and allocation.get('budget')==p['budget']
            and allocation.get('provider_id')==p['provider_id'] and allocation.get('route')==p['cycle_provider_route'],
            '候选分工或预算偏离原分配','budget_exhausted',409)
    extension=_setting(c,'budget_extension:'+ident) or {}
    require(not extension.get('invocations') and not extension.get('seconds'),'协作分工不得独立扩额','budget_exhausted',409)
    cfg=app.config.get('providers',{}).get(p['provider_id'],{})
    require(cfg.get('authorized') is True and cfg.get('route')=='deepseek_harness','原提供者授权或路线已撤回','authorization_required',403)
    for current in (task,parent):
        s.assert_material_access(c,current['payload'])
        s.assert_feedback_ready(c,current['payload'])
        require(not s.question_blockers(c,current['id']),'必要裁决尚待处理','cancelled',409)
        fb=current['payload'].get('feedback_id')
        if fb:require(s.get(fb,connection=c)['content'].get('lifecycle')!='withdrawn','关联反馈已撤回','cancelled',409)
    require(p['context'].get('cycle_parent_inputs')==s.execution_inputs(c,parent['id']),
            '候选产生后父级输入已变化','candidate_revision_required',409)
    for ref in p['context'].get('materials',[]):
        source=s.get(ref['id'],ref['revision'],c)
        require(ref.get('sha256')==digest(source),'冻结科学来源身份不一致','integrity',409)
    return task,parent


def _inspect(app,c,data,scope,*,allow_invalid=False):
    if app.store.task(data['id'],c)['payload'].get('cycle_provider_route')=='codex':
        from .codex_recovery import inspect
        return inspect(app,c,data,scope,allow_invalid=allow_invalid)
    task,parent=_guard(app,c,data['id'],scope)
    directory=_directory(app,task['id'])
    lock=directory/'instance/launch.lock'
    require(not lock.exists() and not lock.is_symlink(),'原生执行锁仍在；显式接回不清锁或中断在途作业','conflict',409)
    receipt=_native_checkpoint(directory/'instance')
    usage=accounting(app.store,task,c)
    require(usage['status']=='verified' and 'durable_anchor' in usage['sources'],'接回需要数据库原生用量锚点','native_accounting_integrity',409)
    require(receipt.get('session_id')==usage['session_id'] and receipt.get('usage')==usage['usage'],
            '原生文件回执与数据库用量锚点不同','native_accounting_integrity',409)
    selected=_native_candidate(task,directory,receipt,allow_budget_tail=True,allow_bookkeeping_tail=True)
    require(selected is not None,'本轮没有成功登记的 JSON 候选','candidate_checkpoint_invalid',409)
    raw=selected['text'].encode();original_sha=digest(raw)
    from .native_json_repair import KIND,inspect_syntax
    revision=data.get('revision',{'kind':'none'})
    require(isinstance(revision,dict) and revision.get('kind') in {'none','remove_context_object_pointers',KIND},'不支持此候选修订方式')
    allowed={'kind','reason','native_candidate_sha256','byte_offset','expected'} if revision['kind']==KIND else {'kind','reason'}
    require(not(set(revision)-allowed),'候选修订含未授权字段')
    source,output,changes,syntax_error,suggested_revision=inspect_syntax(raw,revision)
    if source is None and syntax_error is None:raise Problem('已登记候选不是 JSON 对象','invalid_model_output',422)
    if source is None and not allow_invalid:raise Problem(syntax_error['message'],'invalid_model_output',422,syntax_error['details'])
    if source is not None:
        require(isinstance(source,dict),'已登记候选不是 JSON 对象','invalid_model_output',422)
        model_questions(source.get('questions',[]))
    inputs=candidate_input_snapshot(app.store,task,selected['receipt'].get('input_provenance'))
    require(inputs==app.store.execution_inputs(c,task['id']),'候选产生后回答或指导已变化','candidate_revision_required',409)
    contract=json.loads(_controlled_file(directory,directory/'capsule/task.json',131072))
    candidate=copy.deepcopy(source)
    if revision['kind']=='remove_context_object_pointers':
        require(candidate is not None,'请先预览原始 JSON 语法错误；不能合并语法和引用修订','invalid_model_output',422)
        require(isinstance(revision.get('reason'),str) and revision['reason'].strip(),'引用类型修正需要具体理由')
        contexts={item['id'] for item in contract['evidence'] if item.get('role') in {'context','bundle'}}
        for i,question in enumerate(candidate.get('questions',[])):
            refs=question.get('source_refs',[]);kept=[]
            for j,ref in enumerate(refs):
                if isinstance(ref,dict) and ref.get('id') in contexts:
                    changes.append({'path':f'questions.{i}.source_refs.{j}','removed_object_pointer':copy.deepcopy(ref),
                                    'retained_task_context':{'task_id':task['id'],'contract_sha256':usage['contract_sha256'],
                                                             'native_candidate_sha256':original_sha,'tool_evidence_id':ref['id']}})
                else:kept.append(ref)
            if len(kept)!=len(refs):question['source_refs']=kept
        require(changes,'候选没有可修正的上下文对象指针；未产生空修订')
    if revision['kind']=='remove_context_object_pointers':output=(json.dumps(candidate,ensure_ascii=False,indent=2)+'\n').encode()
    validation_error=None;content=None;questions=[]
    try:
        if candidate is None:raise Problem(syntax_error['message'],'invalid_model_output',422,syntax_error['details'])
        content=validate_candidate(candidate,task['payload']['context']['output'],app,task['project_id'],task=task)
        questions=model_questions(candidate.get('questions',[]))
        require(not any(q['blocking'] for q in questions),'候选包含当前必要裁决；需先单独处理，接回不代替回答','candidate_revision_required',409)
    except Problem as error:
        if not allow_invalid:raise
        validation_error={'code':error.code,'message':str(error),'details':error.details}
    sha=digest(output)
    pin={'task_id':task['id'],'task_sha256':digest(task),'parent_sha256':digest(parent),
         'native_candidate_sha256':original_sha,'candidate_sha256':sha,'contract_sha256':usage['contract_sha256'],
         'session_id':usage['session_id'],'input_snapshot':inputs,'revision':revision,
         'native_receipt_sha256':digest(selected['receipt']),'usage_sha256':digest(usage['usage']),'registered_result_seq':selected['receipt']['candidate']['result_seq']}
    return {'task':task,'parent':parent,'candidate':candidate,'content':content,'questions':questions,
            'validation_error':validation_error,'syntax_error':syntax_error,'suggested_revision':suggested_revision,'raw':raw,'output':output,'receipt':selected['receipt'],'usage':usage,'changes':changes,'pin':pin}


def dispatch(app,data,scope=None):
    s=app.store
    if data['action']=='task.recover_candidate_preview':
        with s.connect() as c:
            c.execute('BEGIN')
            value=_inspect(app,c,data,scope,allow_invalid=True)
        return {'raw_candidate_text':value['raw'].decode('utf-8'),'candidate_text':value['output'].decode('utf-8'),
                'bookkeeping_tail':value['receipt'].get('bookkeeping_tail'),'syntax_error':value.get('syntax_error'),'suggested_revision':value.get('suggested_revision'),
                'diff':''.join(difflib.unified_diff(value['raw'].decode('utf-8').splitlines(keepends=True),value['output'].decode('utf-8').splitlines(keepends=True),fromfile='registered-native-original',tofile='proposed-recovered-candidate')),
                'pin':value['pin'],'candidate':value['candidate'],'changes':value['changes'],'ready':value['validation_error'] is None,'validation_error':value['validation_error'],
                'native_accounting':public_accounting(value['usage']) if value['usage'].get('route')!='codex' else None,'provider_accounting':value['usage'] if value['usage'].get('route')=='codex' else public_accounting(value['usage']),'new_model_requests':0,
                'candidate_status':'pending_independent_scientific_review','parent_continuation':'separate explicit action'}
    require(data.get('approved') is True,'需要明确选择接回既存候选；不启动模型','authorization_required',403)
    require(isinstance(data.get('reason'),str) and data['reason'].strip(),'接回需要具体理由')
    require(isinstance(data.get('request_key'),str) and data['request_key'].strip(),'接回需要稳定请求标识')
    request_hash=digest(data);key='native_recovery_request:'+data['request_key']
    with s.transaction() as c:
        previous=_setting(c,key)
        if previous:
            require(previous['request_sha256']==request_hash,'同一接回请求内容不同','idempotency_conflict',409)
            _guard(app,c,data['id'],scope,completed=True)
            return previous['result']
        value=_inspect(app,c,data,scope)
        require(data.get('pin')==value['pin'],'接回预览、来源或状态已变化，请重新读取','conflict',409)
        task=value['task'];ident=task['id'];pin=value['pin'];sha=pin['candidate_sha256']
        from .compatibility import require_features
        from .native_json_repair import FEATURE as SYNTAX_FEATURE,KIND
        require_features(c,[FEATURE]+([SYNTAX_FEATURE] if data.get('revision',{}).get('kind')==KIND or value['receipt'].get('bookkeeping_tail') or value['parent']['result'].get('cycle',{}).get('phase')=='reviewing' else [])+(['codex_technical_candidate_recovery_v1'] if value['usage'].get('route')=='codex' else []))
        original=s.add_asset(value['raw'],'native-original-'+ident+'.json','application/json',
                             {'project_id':task['project_id'],'source_task_id':ident,'native_candidate':True},connection=c)
        revised=s.add_asset(value['output'],'recovered-'+ident+'.json','application/json',
                            {'project_id':task['project_id'],'source_task_id':ident,'candidate_recovery':True},connection=c)
        proof={'task_id':ident,'session_id':pin['session_id'],'contract_sha256':pin['contract_sha256'],
               'native_candidate_sha256':pin['native_candidate_sha256'],'candidate_sha256':sha,
               'original_asset_sha256':original['sha'],'candidate_asset_sha256':revised['sha'],
               'changes':value['changes'],'reason':data['reason'],'revision':data.get('revision',{'kind':'none'}),
               'native_reason':value['receipt']['reason'],'registered_candidate':value['receipt']['candidate'],
               'input_snapshot':pin['input_snapshot'],'at':now(),'new_model_requests':0,'budget_reset':False,
               'scientific_approval':False,'user_acceptance':False,'parent_automatically_resumed':False,
               'model_authorship':'original_native_session','repair_origin':'coordinator_technical_syntax_repair' if data.get('revision',{}).get('kind')==KIND else 'explicit_native_recovery',
               'syntax_error':value.get('syntax_error'),'native_receipt_sha256':pin.get('native_receipt_sha256'),
               'bookkeeping_tail':value['receipt'].get('bookkeeping_tail'),'usage_sha256':pin.get('usage_sha256')}
        old_model=c.execute("SELECT * FROM steps WHERE task_id=? AND step_key='model'",(ident,)).fetchone()
        if old_model:
            model=s.unpack(old_model)
            c.execute('INSERT INTO steps VALUES(?,?,?,?,?)',(ident,'native_recovery_original_model:'+sha,'preserved',encoded(model),now()))
        receipt={**value['receipt'],'recovery':proof,'input_snapshot':pin['input_snapshot'],'new_model_requests':0}
        model={'sha256':sha,'provider':receipt,'input_snapshot':pin['input_snapshot'],'candidate_origin':'explicit_native_recovery'}
        c.execute("INSERT INTO steps VALUES(?,?,?,?,?) ON CONFLICT(task_id,step_key) DO UPDATE SET status=excluded.status,data=excluded.data,updated_at=excluded.updated_at",(ident,'model','done',encoded(model),now()))
        registered=s.register_questions(task['project_id'],value['questions'],
            {'task_id':ident,'candidate_sha256':sha,'stage':'explicit_native_recovery'},
            source_candidate={'task_id':ident,'sha256':sha},connection=c)
        content=copy.deepcopy(value['content']);content['context']=task['payload']['context']
        candidate={'task_id':ident,'title':value['candidate']['title'],'kind':value['candidate'].get('kind','report'),
                   'content':content,'candidate_sha256':sha}
        if value['candidate'].get('cycle_contract'):candidate['cycle_contract']=value['candidate']['cycle_contract']
        c.execute('INSERT INTO steps VALUES(?,?,?,?,?)',(ident,'cycle_candidate:'+sha,'saved',encoded(candidate),now()))
        historical={'status':task['status'],'error':task['error'],'result':task['result'],'attempts':task['attempts'],'updated_at':task['updated_at']}
        result={'cycle_candidate':candidate,'provider':receipt,'independent_review':'pending','user_acceptance':'pending',
                'question_ids':[q['id'] for q in registered['questions']],'native_recovery':proof,'failure_history':[historical]}
        c.execute("UPDATE tasks SET status='generated',result=?,error=NULL,updated_at=? WHERE id=?",(encoded(result),now(),ident))
        parent=value['parent'];state=copy.deepcopy(parent['result'].get('cycle',{}))
        if task['payload'].get('cycle_provider_route')=='deepseek_harness' and state.get('phase')=='reviewing':
            from .cycle import _write
            state.setdefault('native_recovery_review_history',[]).append({'reviewer_id':state['reviewer'],
                'delegate_id':ident,'candidate_sha256':sha,'previous_generation':state.get('revision_generation',0),
                'reason':'Previously missing delegate recovered; fresh independent review required','at':now()})
            state['revision_generation']=state.get('revision_generation',0)+1
            state['phase']='delegating'
            _write(s,c,parent,state,'waiting_input','既存候选已接回；原审查保留，待明确继续安排新的独立审查')
        recoverykey='native_recovery:'+ident+':'+sha
        c.execute('INSERT INTO kv VALUES(?,?)',(recoverykey,encoded(proof)))
        response={'task_id':ident,'status':'generated','candidate_sha256':sha,'recovery':proof,'new_model_requests':0,'parent_status':value['parent']['status']}
        c.execute('INSERT INTO kv VALUES(?,?)',(key,encoded({'request_sha256':request_hash,'result':response})))
        s.event(c,'task.native_candidate_recovered',ident,proof,'coordinator')
    return response


def stored_candidate(app,task,sha,scope=None):
    """Question preview fallback: only a registered same-task recovery asset."""
    app.access(app.store.get(task['project_id']),scope)
    proof=app.store.setting('native_recovery:'+task['id']+':'+sha)
    if not proof:return None
    require(proof.get('task_id')==task['id'] and proof.get('candidate_sha256')==sha
            and proof.get('candidate_asset_sha256')==sha,'候选接回来源记录不符','integrity',409)
    if task['payload'].get('cycle_provider_route')=='codex':
        from .providers import Providers
        usage=Providers(app).assert_codex_continuity(task,_directory(app,task['id']))
    else:usage=accounting(app.store,task)
    require(usage.get('contract_sha256')==proof.get('contract_sha256') and usage.get('session_id')==proof.get('session_id'),
            '候选接回与原任务合同不一致','integrity',409)
    app.asset(sha,scope,task['project_id'])
    raw=(app.store.blobs/sha).read_bytes()
    require(digest(raw)==sha,'接回候选资产摘要不符','integrity',409)
    return raw
