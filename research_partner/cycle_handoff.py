"""Explicit coordinator-authored revisions; originals and spent budgets survive."""
import copy
import json
import re
from .store import Problem,require,digest,encoded,now
from .resolver import evidence_projection
from .document_sources import asset_declarations as _asset_declarations

FEATURE='cycle_coordinator_revision_controls_v2'
from .evidence_neutral import REVIEW_BLOCKS


def _scientific(obj):
    projection=evidence_projection(obj)
    from .evidence_neutral import SCOPE
    projection.setdefault('excluded',{'typed_blocks':[],'typed_fields':[],'scope':SCOPE})
    # Use the common scientific projection once. A second allowlist silently
    # dropped supported interpretation/limitations when handing off a source.
    content=copy.deepcopy(projection['content'])
    blocks=content.get('blocks',[])
    require(isinstance(blocks,list) and all(isinstance(b,dict) for b in blocks),'修订报告段落无效')
    excluded=[b.get('id') for b in blocks if b.get('kind') in REVIEW_BLOCKS]
    content['blocks']=[b for b in blocks if b.get('kind') not in REVIEW_BLOCKS]
    if not any(isinstance(b.get('text'),str) and b['text'].strip() for b in content['blocks']) and isinstance(content.get('markdown'),str) and content['markdown'].strip():
        # Saved Markdown is already a supported document representation. Keep
        # its exact text and normalize only the review body's block container.
        ident='coordinator_markdown';suffix=1
        while any(b.get('id')==ident for b in content['blocks']):
            suffix+=1;ident='coordinator_markdown_'+str(suffix)
        content['blocks'].append({'id':ident,'kind':'paragraph','text':content['markdown']})
    require(any(isinstance(b.get('text'),str) and b['text'].strip() for b in content['blocks']) or bool(content.get('markdown')),
            '修订报告缺少可供科学审查的正文')
    require(len(encoded(content).encode())<=131072,'修订科学正文超过 128 KiB；未截断','context_limit',413)
    return content,{'fields':sorted(set(obj['content'])-set(content)),'blocks':excluded,'typed_blocks':projection['excluded']['typed_blocks'],'typed_fields':projection['excluded']['typed_fields'],'scope':projection['excluded']['scope']}


def _diff(old,new,path='content'):
    if old==new:return []
    if isinstance(old,dict) and isinstance(new,dict):
        result=[]
        for key in sorted(set(old)|set(new)):
            if key not in old:result.append({'path':path+'.'+key,'operation':'add','after':new[key]})
            elif key not in new:result.append({'path':path+'.'+key,'operation':'remove','before':old[key]})
            else:result.extend(_diff(old[key],new[key],path+'.'+key))
        return result
    return [{'path':path,'operation':'replace','before':old,'after':new}]


def _dependencies(s,c,project_id,value):
    """Freeze exact adopted references plus their current heads; no silent rebase."""
    refs={}
    def add(ref):
        require(isinstance(ref,dict),'科学来源引用必须是对象')
        ident=ref.get('id',ref.get('object_id'));revision=ref.get('revision')
        require(isinstance(ident,str) and type(revision) is int and revision>0,'科学来源必须明确对象与修订')
        s.assert_source_access(c,project_id,ident)
        adopted=s.get(ident,revision,c);current=s.get(ident,connection=c)
        require(not current['archived'],'科学来源已归档','forbidden',403)
        refs[(ident,revision)]={'id':ident,'revision':revision,'sha256':digest(adopted),'current_revision':current['revision']}
    def walk(item):
        if isinstance(item,dict):
            if 'source_ref' in item:add(item['source_ref'])
            if 'component_id' in item:add({'id':item['component_id'],'revision':item.get('component_revision',item.get('revision'))})
            if 'source_object_id' in item:add({'id':item['source_object_id'],'revision':item.get('source_revision')})
            for key in ('source_refs','citations','components'):
                if key in item:
                    require(isinstance(item[key],list),'科学来源引用必须是列表')
                    for ref in item[key]:add(ref)
            for key,nested in item.items():
                if key not in {'source_ref','source_refs','citations','components'}:walk(nested)
        elif isinstance(item,list):
            for nested in item:walk(nested)
    walk(value)
    return [refs[k] for k in sorted(refs)]



def _assets(s,c,project_id,content,dependencies):
    """Keep registered image bindings and recheck their bytes and current ACL."""
    refs=_asset_declarations(content)
    result=[]
    for sha in sorted(refs):
        asset=s.asset(sha,c);owners=set(asset['metadata'].get('projects',[]))|{asset['metadata'].get('project_id')}
        allowed=project_id in owners
        if not allowed:
            for ref in dependencies:
                s.assert_source_access(c,project_id,ref['id']);source=s.get(ref['id'],ref['revision'],c)
                if source['project_id'] in owners and sha in _asset_declarations(source['content'],strict=False):allowed=True;break
        require(allowed,'修订报告无权读取此图片资产','forbidden',403)
        raw=(s.blobs/sha).read_bytes()
        require(len(raw)==asset['size'] and digest(raw)==sha,'修订报告的登记资产字节已变化','integrity',409)
        result.append({'sha':sha,'size':asset['size'],'media_type':asset['media_type']})
    return result


def _feedback_inputs(s,c,parent,child):
    return {task['id']:s.assert_feedback_ready(c,task['payload']) for task in (parent,child)}


def _native_identity(s,c,child):
    if child['payload'].get('cycle_provider_route')!='deepseek_harness':return None
    from .native_accounting import accounting
    value=accounting(s,child,c)
    require(value['status']=='verified' and 'durable_anchor' in value['sources'],
            '原生候选需要同任务的用量、会话和合同锚点','native_accounting_integrity',409)
    return {key:value[key] for key in ('session_id','contract_sha256','reserved_requests')} | {'usage_sha256':digest(value['usage'])}


def validate_staged(s,c,parent,state):
    """Pure same-transaction guard, shared by enqueue, claim and publication."""
    s.assert_feedback_ready(c,parent['payload'])
    from .cycle_final_handoff import validate_staged as validate_final
    validate_final(s,c,parent,state)
    # Final review uses its explicitly pinned source closure. Earlier delegate
    # overrides remain historical and may not reopen or constrain new input.
    if state.get('final_revision'):return
    for ident,record in state.get('coordinator_revisions',{}).items():
        try:
            require('feedback_inputs' in record and 'assets' in record,'旧交接记录需要按当前图片与反馈规则重新预览')
            require(not s.get(parent['project_id'],connection=c)['archived'],'协作项目已归档')
            require(record['bound_epoch']==state['epoch'],'父级暂停或执行轮次已变化')
            require(record['parent_inputs']==s.execution_inputs(c,parent['id']),'父级意见或裁决已变化')
            require(record['parent_payload_sha256']==digest(parent['payload']),'父级冻结合同已变化')
            child=s.task(ident,c)
            require(record['feedback_inputs']==_feedback_inputs(s,c,parent,child),'关联反馈内容、处理时机或暂缓状态已变化')
            require(record['child_payload_sha256']==digest(child['payload']),'原分工冻结合同已变化')
            require(child['status']=='generated' and child['result'].get('cycle_candidate',{}).get('candidate_sha256')==record['original_candidate_sha256'],'原分工候选已变化')
            require(record['child_inputs']==s.execution_inputs(c,ident),'原分工意见或裁决已变化')
            require(record['native_identity']==_native_identity(s,c,child),'原生会话、合同或用量已变化')
            require(not s.question_blockers(c,ident),'原分工仍有必要裁决')
            s.assert_material_access(c,child['payload']);s.assert_material_access(c,parent['payload'])
            feedback=child['payload'].get('feedback_id')
            if feedback:require(s.get(feedback,connection=c)['content'].get('lifecycle')!='withdrawn','分工反馈已撤回')
            source=s.get(record['source_ref']['id'],connection=c)
            require(source['project_id']==parent['project_id'] and not source['archived'] and source['revision']==record['source_ref']['revision'] and digest(source)==record['source_sha256'],'协调者修订报告已编辑、归档或改变归属')
            for ref in record['dependencies']:
                s.assert_source_access(c,parent['project_id'],ref['id']);current=s.get(ref['id'],connection=c)
                require(not current['archived'] and current['revision']==ref['current_revision'] and digest(s.get(ref['id'],ref['revision'],c))==ref['sha256'],'修订科学来源版本已变化')
            require(record['assets']==_assets(s,c,parent['project_id'],record['candidate']['content'],record['dependencies']),'修订报告资产身份已变化')
        except Problem as error:
            raise Problem('协调者修订需重新预览并明确关联：'+str(error),'cycle_handoff',409,{'delegate_id':ident,'reason_code':error.code}) from error


def project_record(s,c,parent,record):
    public={k:copy.deepcopy(v) for k,v in record.items() if k not in {'parent_inputs','child_inputs','dependencies','native_identity','candidate'}}
    try:validate_staged(s,c,parent,{**parent['result']['cycle'],'coordinator_revisions':{record['delegate_id']:record}})
    except Problem as error:public.update(valid=False,invalid_reason=str(error))
    else:public.update(valid=True,invalid_reason=None)
    return public


def selected(s,c,parent,state,child):
    record=state.get('coordinator_revisions',{}).get(child['id'])
    if record:
        validate_staged(s,c,parent,state)
        candidate=copy.deepcopy(record['candidate'])
        # Native candidates receive this exact binding through cycle._neutral.
        # Coordinator handoffs preserve their explicit provenance, but must
        # provide the same proposal identity to the actual reviewer input.
        proposal=candidate.get('content',{}).get('graph_proposal')
        if proposal is not None:candidate['graph_proposal_digest']=digest(proposal)
        return candidate
    from .cycle import _neutral
    return _neutral(child['result']['cycle_candidate']) if child['status']=='generated' and child['result'].get('cycle_candidate') else {'task_id':child['id'],'no_scientific_output':True,'failure':{'status':child['status'],'summary':'子任务没有可采用输出，未作为成功材料'}}


def _inspect(app,c,data,scope,*,availability=False):
    require(all(isinstance(data.get(k),str) and data[k] for k in (('id','delegate_id') if availability else ('id','delegate_id','source_id'))),'父任务、分工与报告ID必须是字符串')
    require(isinstance(data.get('candidate_sha256'),str) and re.fullmatch(r'[0-9a-f]{64}',data['candidate_sha256']),'需要明确原候选SHA256')
    s=app.store;parent=s.task(data['id'],c);state=parent['result'].get('cycle',{})
    project=app.access(s.get(parent['project_id'],connection=c),scope)
    require(not project['archived'],'协作项目已归档','forbidden',403)
    require(scope is None or parent['project_id'] in scope,'共享来源不授予协作接手权限','forbidden',403)
    failure=state.get('last_failure',{})
    ordinary=parent['status']=='waiting_input' and failure.get('code')=='cycle_handoff'
    resource=parent['status']=='waiting_resource' and failure.get('code')=='budget_exhausted'
    require(parent['payload'].get('kind')=='research_cycle' and (ordinary or resource),
            '父协作须停在失败交接处；提交不恢复执行','conflict',409)
    require(state.get('phase') in {'delegating','reworking','reviewing'},'此入口处理分工或分工审查交接；最终成果修订需独立安排','conflict',409)
    ident=data.get('delegate_id');require(ident in state.get('delegates',[]),'接手只能指向此父协作的原分工')
    child=s.task(ident,c);original=child['result'].get('cycle_candidate',{})
    require(child['status']=='generated' and child['payload'].get('cycle_parent')==parent['id'] and original.get('candidate_sha256')==data.get('candidate_sha256'),
            '原候选身份或状态已变化','conflict',409)
    if resource:
        native=_native_identity(s,c,child)
        require(native is not None and native['reserved_requests']>=child['payload']['budget']['max_model_calls'],
                '资源交接仅允许明确耗尽原生请求的既有候选','conflict',409)
        reviewer=s.task(state.get('reviewer'),c) if state.get('reviewer') else None
        review=reviewer['result'].get('cycle_candidate',{}).get('cycle_contract',{}) if reviewer else {}
        require(review.get('verdict')=='rework' and ident in {f.get('target_task_id') for f in review.get('findings',[])},
                '资源交接缺少针对该原分工的真实返工要求','conflict',409)
    model=next((step for step in child['steps'] if step['step_key']=='model'),None)
    require(model and model['status']=='done' and model['data'].get('sha256')==data['candidate_sha256'],'原候选与模型检查点身份不符','integrity',409)
    for current in (parent,child):
        s.assert_material_access(c,current['payload']);require(not s.question_blockers(c,current['id']),'仍有必要裁决','conflict',409)
        s.assert_feedback_ready(c,current['payload'])
    # Existing work must finish stopping before this explicit handoff changes inputs.
    for ref in state.get('children',[]):
        row=c.execute('SELECT value FROM kv WHERE key=?',('execution:'+ref['id'],)).fetchone()
        require(not row or json.loads(row[0]).get('state')!='active','原协作执行尚未结束；保留在途任务','conflict',409)
    if availability:return {'allowed':True,'mode':'native_budget_handoff' if resource else 'control_handoff','parent_status':parent['status'],'original_candidate_sha256':data['candidate_sha256'],'excluded_source_ids':[parent['payload']['target_id']] if parent['payload'].get('target_id') else [],'reason':None}
    source=s.get(data.get('source_id'),connection=c)
    require(source['id']!=parent['payload'].get('target_id'),'修订来源不能同时是本轮整合写回目标；请另存一份协调者报告后关联，原目标保留','cycle_source_is_target',409)
    require(source['project_id']==parent['project_id'] and source['kind']=='report' and not source['archived'],'请选择同项目未归档报告','forbidden',403)
    require(type(data.get('source_revision')) is int and source['revision']==data['source_revision'],'修订报告版本已变化','conflict',409)
    require(isinstance(data.get('reason'),str) and data['reason'].strip(),'请说明此科学修订如何接回原分工')
    content,excluded=_scientific(source)
    from .commission import COMMON,PROSE,validate_candidate
    validate_candidate({'title':source['title'],'kind':'report',**{k:v for k,v in content.items() if k in COMMON|PROSE}},'report',app,parent['project_id'],task=child)
    dependencies=_dependencies(s,c,parent['project_id'],content)
    for ref in parent['payload']['context'].get('materials',[]):
        s.assert_source_access(c,parent['project_id'],ref['id']);current=s.get(ref['id'],connection=c)
        require(digest(s.get(ref['id'],ref['revision'],c))==ref['sha256'],'原科学材料冻结身份损坏','integrity',409)
        value={**ref,'current_revision':current['revision']}
        if value not in dependencies:dependencies.append(value)
    assets=_assets(s,c,parent['project_id'],content,dependencies)
    source_ref={'id':source['id'],'revision':source['revision']};native=_native_identity(s,c,child)
    candidate={'task_id':ident,'id':source['id'],'revision':source['revision'],'title':source['title'],'kind':'report','content':content,
               'candidate_origin':'coordinator_revision','source_ref':source_ref,'original_candidate_sha256':data['candidate_sha256']}
    candidate['candidate_sha256']=digest(candidate)
    from .cycle import _neutral
    original_science=_neutral(original);diff=_diff(original_science.get('content',{}),content)
    require(diff or original_science.get('title')!=source['title'],'修订科学正文与原候选相同；无需生成接手版本')
    pin={'parent_id':parent['id'],'delegate_id':ident,'parent_sha256':digest(parent),'child_sha256':digest(child),'epoch':state['epoch'],
         'original_candidate_sha256':data['candidate_sha256'],'source_ref':source_ref,'source_sha256':digest(source),
         'candidate_sha256':candidate['candidate_sha256'],'parent_inputs':s.execution_inputs(c,parent['id']),
         'child_inputs':s.execution_inputs(c,ident),'parent_payload_sha256':digest(parent['payload']),'child_payload_sha256':digest(child['payload']),'native_identity':native,'dependencies':dependencies,'assets':assets,'feedback_inputs':_feedback_inputs(s,c,parent,child),'reason':data['reason']}
    return {'parent':parent,'child':child,'source':source,'candidate':candidate,'original_candidate':original_science,'diff':diff,'excluded':excluded,'pin':pin}


def availability(app,parent,child,scope=None):
    try:
        with app.store.connect() as c:
            c.execute('BEGIN')
            return _inspect(app,c,{'id':parent['id'],'delegate_id':child['id'],
                                  'candidate_sha256':child['result'].get('cycle_candidate',{}).get('candidate_sha256')},scope,availability=True)
    except Problem as error:
        return {'allowed':False,'mode':None,'parent_status':parent['status'],'reason':str(error),'reason_code':error.code}


def dispatch(app,data,scope=None):
    s=app.store
    if data['action']=='cycle.stage_revision_preview':
        with s.connect() as c:
            c.execute('BEGIN');value=_inspect(app,c,data,scope)
        return {'ready':True,'pin':value['pin'],'candidate':value['candidate'],'revised_candidate':value['candidate'],
                'original_candidate':value['original_candidate'],'source':{'id':value['source']['id'],'revision':value['source']['revision'],'title':value['source']['title'],'kind':'report','sha256':digest(value['source'])},
                'diff':value['diff'],'excluded':value['excluded'],'lineage':{key:value['pin'][key] for key in ('parent_id','delegate_id','original_candidate_sha256','source_ref','source_sha256','native_identity')},'new_model_requests':0,'scientific_approval':False,'parent_status':value['parent']['status'],'resource_boundary':{'budget_reset':False,'resume_separate':True,'remaining_parent_preallocated_calls':value['parent']['payload']['cycle_config']['limits']['max_model_calls']-value['parent']['result']['cycle']['reserved_calls']}}
    require(data.get('approved') is True,'需要明确关联协调者修订；保存不启动协作','authorization_required',403)
    require(isinstance(data.get('request_key'),str) and data['request_key'].strip(),'需要稳定请求标识')
    key='cycle_stage_revision:'+data['request_key'];request_hash=digest(data)
    with s.transaction() as c:
        saved=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
        if saved:
            saved=json.loads(saved[0]);require(saved['request_sha256']==request_hash,'同一接手请求内容不同','idempotency_conflict',409)
            parent=s.task(data['id'],c);app.access(s.get(parent['project_id'],connection=c),scope)
            require(scope is None or parent['project_id'] in scope,'无权修改此协作','forbidden',403)
            require(parent['status'] in {'waiting_input','waiting_resource'},'协作状态已变化','conflict',409)
            validate_staged(s,c,parent,parent['result']['cycle']);return saved['response']
        value=_inspect(app,c,data,scope);require(value['pin']==data.get('pin'),'预览后任务、来源或意见已变化；请重新预览','conflict',409)
        from .compatibility import require_features
        from .cycle import _write,_put
        require_features(c,['cycle_coordinator_revision_v1',FEATURE]);parent=value['parent'];state=copy.deepcopy(parent['result']['cycle']);pin=value['pin']
        generation=state.get('revision_generation',0)+1
        record={key:copy.deepcopy(pin[key]) for key in ('delegate_id','original_candidate_sha256','source_ref','source_sha256','candidate_sha256','parent_inputs','child_inputs','parent_payload_sha256','child_payload_sha256','native_identity','dependencies','assets','feedback_inputs')}
        record.update(candidate=value['candidate'],reason=data['reason'],diff=value['diff'],excluded=value['excluded'],at=now(),
                      stage_epoch=state['epoch'],bound_epoch=state['epoch'],generation=generation,scientific_approval=False,new_model_requests=0)
        previous=state.setdefault('coordinator_revisions',{}).get(data['delegate_id'])
        state.setdefault('coordinator_revision_history',[]).append({'generation':generation,'record':copy.deepcopy(record),'supersedes_generation':previous.get('generation') if previous else None,'previous_phase':state['phase']})
        state['coordinator_revisions'][data['delegate_id']]=record;state['revision_generation']=generation;state['phase']='delegating'
        for ref in state.get('children',[]):
            if ref['role'] not in {'reviewer','integrator','final_reviewer'}:continue
            old=s.task(ref['id'],c)
            if old['status'] in {'queued','paused','waiting_input','waiting_resource','waiting_authorization'}:
                c.execute("UPDATE tasks SET status='waiting_input',error=?,updated_at=? WHERE id=?",('旧科学输入已由明确协调者修订替代；此历史任务未自动恢复',now(),old['id']))
                state.get('suspended_children',{}).pop(old['id'],None)
        # Other explicitly staged delegates still need their own fresh pins after
        # an input/epoch change; this action grants nothing on their behalf.
        _write(s,c,parent,state,parent['status'],'协调者修订已关联；原资源边界保留，待明确继续并独立审查')
        response={'parent_id':parent['id'],'delegate_id':data['delegate_id'],'parent_status':parent['status'],'coordinator_revision':project_record(s,c,s.task(parent['id'],c),record),'new_model_requests':0,'scientific_approval':False}
        _put(c,key,{'request_sha256':request_hash,'response':response});s.event(c,'cycle.coordinator_revision_staged',parent['id'],{**record,'candidate':None},'coordinator')
    return response


def review_key(state,base):
    generation=state.get('revision_generation',0)
    return base+(':coordinator:'+str(generation) if generation else '')
