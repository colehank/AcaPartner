"""An explicit coordinator final-source handoff; no provider dispatch on stage."""
import copy
import json
from .store import Problem,require,digest,encoded,now
from .cycle_handoff import _scientific,_diff,_dependencies,_assets,_feedback_inputs

FEATURE='cycle_final_source_handoff_v1'


def _source(s,c,ref):
    obj=s.get(ref['id'],ref['revision'],c)
    require(digest(obj)==ref['sha256'],'原最终稿冻结身份损坏','integrity',409)
    return obj


def _idle(s,c,parent,state):
    for ref in [{'id':parent['id']},*state.get('children',[])]:
        row=c.execute('SELECT value FROM kv WHERE key=?',('execution:'+ref['id'],)).fetchone()
        task=s.task(ref['id'],c)
        require(task['status']!='running' and (not row or json.loads(row[0]).get('state')!='active'),'原协作执行尚未结束；保留在途工作','conflict',409)


def _guard(app,c,data,scope):
    s=app.store;parent=s.task(data['id'],c);state=parent['result'].get('cycle',{})
    project=app.access(s.get(parent['project_id'],connection=c),scope)
    require(not project['archived'] and (scope is None or parent['project_id'] in scope),'无权修改此协作','forbidden',403)
    require(parent['payload'].get('kind')=='research_cycle' and parent['status'] in {'waiting_input','waiting_resource','waiting_authorization'}
            and state.get('phase') in {'final_reviewing','handoff','final_revision_staged'},'最终稿交接仅在最终审查等待时可用；暂停/取消禁止','conflict',409)
    reviewer=s.task(state['final_reviewer'],c)
    require(reviewer['payload'].get('cycle_parent')==parent['id'] and reviewer['payload'].get('cycle_role')=='final_reviewer'
            and reviewer['status'] in {'generated','failed','waiting_input','waiting_resource','waiting_authorization'},'旧最终审查仍在途或已暂停/取消','conflict',409)
    require(state.get('phase')!='handoff' or reviewer['result'].get('cycle_candidate',{}).get('cycle_contract',{}).get('verdict') in {'rework','handoff'},'最终审查没有要求修订','conflict',409)
    _idle(s,c,parent,state)
    for task in (parent,reviewer):
        s.assert_material_access(c,task['payload']);s.assert_feedback_ready(c,task['payload'])
        require(not s.question_blockers(c,task['id']),'仍有必要裁决','conflict',409)
    role=parent['payload']['cycle_config']['roles']['final_reviewer'];cfg=app.config.get('providers',{}).get(role,{})
    require(cfg.get('authorized') is True and cfg.get('route')==parent['payload']['cycle_config']['provider_routes']['final_reviewer'],'最终审查角色授权或路线已撤回','authorization_required',403)
    previous=state.get('final_revision')
    old=copy.deepcopy(previous['old_source'] if state['phase']=='final_revision_staged' and previous else state['final_source'])
    obj=_source(s,c,old);s.assert_source_access(c,parent['project_id'],obj['id'])
    require(not s.get(obj['id'],connection=c)['archived'],'原最终稿已归档','forbidden',403)
    from .graph_growth import items
    proposal=obj['content'].get('graph_proposal')
    require(not proposal or not items(proposal),'非空图谱提案需要独立精确重绑定；本次最终稿交接未改图谱','cycle_handoff',409)
    if state.get('graph_proposal_id'):
        row=c.execute('SELECT value FROM kv WHERE key=?',('graph_proposal:'+state['graph_proposal_id'],)).fetchone()
        require(row and not json.loads(row[0]).get('items'),'现有图谱提案仍含待审条目','cycle_handoff',409)
    return parent,reviewer,old


def availability(app,parent,scope=None):
    try:
        with app.store.connect() as c:
            c.execute('BEGIN');parent,reviewer,old=_guard(app,c,{'id':parent['id']},scope)
            state=parent['result']['cycle']
            return {'allowed':True,'old_source':old,'reviewer_id':reviewer['id'],
                    'reviewer_candidate_sha256':reviewer['result'].get('cycle_candidate',{}).get('candidate_sha256'),
                    'parent_status':parent['status'],'remaining_preallocated_calls':parent['payload']['cycle_config']['limits']['max_model_calls']-state['reserved_calls'],
                    'reason':None,'resume_separate':True}
    except Problem as error:return {'allowed':False,'reason':str(error),'reason_code':error.code,'parent_status':parent['status']}



def _material_closure(s,c,project_id,source,content):
    """Declared scientific refs only; copy/audit lineage is not review evidence."""
    pending=_dependencies(s,c,project_id,{'science':content,'source_refs':source['metadata'].get('source_refs',[])})
    adopted={};assets={}
    while pending:
        ref=pending.pop(0);key=(ref['id'],ref['revision'])
        if key in adopted:continue
        require(ref['id']!=source['id'],'最终稿不能把自身作为科学来源')
        require(not any(k[0]==ref['id'] and k[1]!=ref['revision'] for k in adopted),'同一科学来源被声明为不同修订；请先明确采用版本','conflict',409)
        require(len(adopted)<32,'最终审查声明来源闭合超过 32 项；未截断','context_limit',413)
        obj=s.get(ref['id'],ref['revision'],c)
        from .resolver import EVIDENCE_KINDS,evidence_projection
        require(obj['kind'] in EVIDENCE_KINDS,'声明来源不是可读科学材料')
        adopted[key]=ref;science=evidence_projection(obj)['content']
        pending.extend(_dependencies(s,c,project_id,{'science':science,'source_refs':obj['metadata'].get('source_refs',[])}))
    refs=[adopted[k] for k in sorted(adopted)]
    for ref in refs:
        from .resolver import evidence_projection
        obj=s.get(ref['id'],ref['revision'],c)
        for asset in _assets(s,c,project_id,evidence_projection(obj)['content'],refs):assets[asset['sha']]=asset
    return refs,[assets[k] for k in sorted(assets)]


def _inspect(app,c,data,scope):
    s=app.store;parent,reviewer,old=_guard(app,c,data,scope);state=parent['result']['cycle']
    require(data.get('old_source_sha256')==old['sha256'] and data.get('reviewer_id')==reviewer['id']
            and 'reviewer_candidate_sha256' in data and data['reviewer_candidate_sha256']==reviewer['result'].get('cycle_candidate',{}).get('candidate_sha256'),
            '请明确当前最终稿与原审查候选身份','conflict',409)
    source=s.get(data.get('source_id'),connection=c)
    require(source['project_id']==parent['project_id'] and source['kind'] in {'note','report'} and not source['archived'],'请选择同项目未归档科研笔记或报告','forbidden',403)
    require(type(data.get('source_revision')) is int and data['source_revision']==source['revision'],'修订报告已变化','conflict',409)
    require(s.get(old['id'],connection=c)['revision']==old['revision'] or source['id']==old['id'],
            '原最终稿已被编辑；请显式采用它的当前修订，不能用另一份报告绕过用户修改','conflict',409)
    require(isinstance(data.get('reason'),str) and data['reason'].strip(),'请说明最终稿修订理由')
    content,excluded=_scientific(source)
    from .graph_growth import items
    proposal=content.get('graph_proposal')
    require(not proposal or not items(proposal),'此交接不能引入未经精确图谱绑定的提案','cycle_handoff',409)
    from .commission import COMMON,PROSE,validate_candidate
    validate_candidate({'title':source['title'],'kind':source['kind'],**{k:v for k,v in content.items() if k in COMMON|PROSE}},source['kind'],app,parent['project_id'],task=s.task(state['integrator'],c))
    dependencies,dependency_assets=_material_closure(s,c,parent['project_id'],source,content)
    require(dependencies or not parent['payload']['context'].get('materials'),'最终稿须明确声明此次独立审查采用的科学 source_refs；不会静默沿用旧材料')
    assets=_assets(s,c,parent['project_id'],content,dependencies)
    materials=[{k:ref[k] for k in ('id','revision','sha256')} for ref in dependencies]
    materials_view={'adopted':materials,'omitted_parent':[ref for ref in parent['payload']['context'].get('materials',[]) if ref not in materials],
                    'scope':'Only these declared scientific sources enter the new final review; old parent materials and reviews remain historical records.'}
    from .cycle import _neutral
    original=_neutral(_source(s,c,old));diff=_diff(original['content'],content)
    require(diff or original['title']!=source['title'],'科学正文与旧最终稿相同；没有可提交修订')
    source_ref={'id':source['id'],'revision':source['revision']}
    candidate={'task_id':parent['id'],'id':source['id'],'revision':source['revision'],'sha256':digest(source),'source_sha256':digest(source),
               'title':source['title'],'kind':source['kind'],'content':content,'candidate_origin':'coordinator_final_revision',
               'author_role':'coordinator','original_integrator_id':state['integrator'],'source_ref':source_ref,'excluded':excluded}
    candidate['candidate_sha256']=digest(candidate)
    pin={'parent_id':parent['id'],'parent_sha256':digest(parent),'reviewer_id':reviewer['id'],'reviewer_sha256':digest(reviewer),
         'reviewer_candidate_sha256':reviewer['result'].get('cycle_candidate',{}).get('candidate_sha256'),'old_source':old,
         'old_source_current_revision':s.get(old['id'],connection=c)['revision'],'source_ref':source_ref,'source_sha256':digest(source),'candidate_sha256':candidate['candidate_sha256'],
         'epoch':state['epoch'],'parent_inputs':s.execution_inputs(c,parent['id']),'reviewer_inputs':s.execution_inputs(c,reviewer['id']),
         'parent_payload_sha256':digest(parent['payload']),'dependencies':dependencies,'assets':assets,'dependency_assets':dependency_assets,'materials':materials_view,'feedback_inputs':_feedback_inputs(s,c,parent,reviewer),'reason':data['reason']}
    return {'parent':parent,'reviewer':reviewer,'source':source,'candidate':candidate,'original_candidate':original,'excluded':excluded,'diff':diff,'pin':pin}


def validate_staged(s,c,parent,state):
    record=state.get('final_revision')
    if not record:return
    try:
        require(record['bound_epoch']==state['epoch'],'父级已暂停或改变执行轮次')
        require(record['parent_payload_sha256']==digest(parent['payload']) and record['parent_inputs']==s.execution_inputs(c,parent['id']),'父级合同或输入已变化')
        require(not s.get(parent['project_id'],connection=c)['archived'],'项目已归档')
        reviewer=s.task(record['reviewer_id'],c)
        require(digest(reviewer)==record['reviewer_sha256'] and record['reviewer_inputs']==s.execution_inputs(c,reviewer['id']),'原审查候选或输入已变化')
        require(record['feedback_inputs']==_feedback_inputs(s,c,parent,reviewer),'关联反馈已暂缓、修改或撤回')
        for task in (parent,reviewer):
            s.assert_material_access(c,task['payload']);require(not s.question_blockers(c,task['id']),'仍有必要裁决')
        source=s.get(record['source_ref']['id'],connection=c)
        require(source['project_id']==parent['project_id'] and not source['archived'] and source['revision']==record['source_ref']['revision'] and digest(source)==record['source_sha256'],'最终修订报告已编辑、归档或改变归属')
        _source(s,c,record['old_source']);s.assert_source_access(c,parent['project_id'],record['old_source']['id'])
        old_head=s.get(record['old_source']['id'],connection=c)
        require(not old_head['archived'] and old_head['revision']==record['old_source_current_revision'],'原最终稿已被编辑或归档')
        require(state['final_source']=={**record['source_ref'],'sha256':record['source_sha256']},'当前最终稿不等于已关联修订')
        for ref in record['dependencies']:
            s.assert_source_access(c,parent['project_id'],ref['id']);head=s.get(ref['id'],connection=c)
            require(not head['archived'] and head['revision']==ref['current_revision'] and digest(s.get(ref['id'],ref['revision'],c))==ref['sha256'],'科学来源已编辑、归档或撤权')
        require(record['assets']==_assets(s,c,parent['project_id'],record['candidate']['content'],record['dependencies']),'修订资产已变化')
        deps,assets=_material_closure(s,c,parent['project_id'],source,record['candidate']['content'])
        require(deps==record['dependencies'] and assets==record['dependency_assets'],'采用来源闭合或来源资产已变化')
    except Problem as error:raise Problem('最终稿修订需重新预览并明确提交：'+str(error),'cycle_final_handoff',409,{'reason_code':error.code}) from error


def projection(s,c,parent,record):
    value={k:copy.deepcopy(v) for k,v in record.items() if k not in {'parent_inputs','reviewer_inputs','feedback_inputs','dependencies'}}
    try:validate_staged(s,c,parent,parent['result']['cycle'])
    except Problem as error:value.update(valid=False,invalid_reason=str(error))
    else:value.update(valid=True,invalid_reason=None)
    return value


def dispatch(app,data,scope=None):
    s=app.store
    if data['action']=='cycle.stage_final_revision_preview':
        with s.connect() as c:c.execute('BEGIN');value=_inspect(app,c,data,scope)
        return {'ready':True,'pin':value['pin'],'candidate':value['candidate'],'original_candidate':value['original_candidate'],
                'source':value['pin']['source_ref']|{'title':value['source']['title'],'sha256':value['pin']['source_sha256']},
                'diff':value['diff'],'excluded':value['excluded'],'materials':value['pin']['materials'],'new_model_requests':0,'scientific_approval':False,
                'parent_status':value['parent']['status'],'resource_boundary':{'budget_reset':False,'resume_separate':True,
                    'remaining_parent_preallocated_calls':value['parent']['payload']['cycle_config']['limits']['max_model_calls']-value['parent']['result']['cycle']['reserved_calls']}}
    require(data.get('approved') is True,'需要明确提交最终稿修订；不自动继续','authorization_required',403)
    require(isinstance(data.get('request_key'),str) and data['request_key'].strip(),'需要稳定请求标识')
    key='cycle_stage_final_revision:'+data['request_key'];request_hash=digest(data)
    with s.transaction() as c:
        row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
        if row:
            saved=json.loads(row[0]);require(saved['request_sha256']==request_hash,'同一请求内容不同','idempotency_conflict',409)
            parent=s.task(data['id'],c);app.access(s.get(parent['project_id'],connection=c),scope)
            require(scope is None or parent['project_id'] in scope,'无权修改此协作','forbidden',403)
            require(parent['status'] in {'waiting_input','waiting_resource','waiting_authorization'},'协作状态已变化','conflict',409)
            validate_staged(s,c,parent,parent['result']['cycle']);return saved['response']
        value=_inspect(app,c,data,scope);require(value['pin']==data.get('pin'),'预览后来源、审查或输入已变化；请重新预览','conflict',409)
        from .compatibility import require_features
        from .cycle import _write,_put
        require_features(c,[FEATURE]);parent=value['parent'];state=copy.deepcopy(parent['result']['cycle']);pin=value['pin']
        generation=state.get('final_revision_generation',0)+1
        record={k:copy.deepcopy(v) for k,v in pin.items() if k not in {'parent_sha256','epoch'}}
        record.update(candidate=value['candidate'],diff=value['diff'],excluded=value['excluded'],bound_epoch=state['epoch'],stage_epoch=state['epoch'],
                      generation=generation,at=now(),new_model_requests=0,scientific_approval=False,user_acceptance=False)
        state.setdefault('final_source_history',[]).append({'final_source':copy.deepcopy(state['final_source']),
            'final_reviewer':state['final_reviewer'],'final_review':copy.deepcopy(state.get('final_review')),
            'final_revision':copy.deepcopy(state.get('final_revision')),'phase':state['phase'],'at':now()})
        state['final_revision']=record;state['final_revision_generation']=generation
        state['final_source']={**pin['source_ref'],'sha256':pin['source_sha256']};state['phase']='final_revision_staged'
        if state.get('graph_proposal_id'):state.setdefault('graph_proposal_history',[]).append(state.pop('graph_proposal_id'))
        _write(s,c,parent,state,parent['status'],'最终稿修订已关联；等待明确继续安排新的独立最终审查，额度不重置')
        response={'parent_id':parent['id'],'parent_status':parent['status'],'final_revision':projection(s,c,s.task(parent['id'],c),record),'new_model_requests':0,'scientific_approval':False}
        _put(c,key,{'request_sha256':request_hash,'response':response});s.event(c,'cycle.final_revision_staged',parent['id'],{k:v for k,v in record.items() if k!='candidate'},'coordinator')
    return response
