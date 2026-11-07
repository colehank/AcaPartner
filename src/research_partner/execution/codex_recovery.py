"""Zero-call recovery of one Codex review rejected only at the schema boundary.

CLI reply, durable task/session/contract binding and terminal events are checked;
this never edits a native file or interprets/revises scientific prose.
"""
import copy
import json
import re
from research_partner.storage.store import Problem, require, digest
from research_partner.providers.registry import Providers, _controlled_file
from research_partner.domains.collaboration.commission import validate_candidate
from research_partner.domains.collaboration.questions import model_questions

FEATURE='codex_technical_candidate_recovery_v1'


def guard(app,c,ident,scope,*,completed=False):
    from research_partner.execution.recovery import _setting
    s=app.store;task=s.task(ident,c);p=task['payload']
    project=s.get(task['project_id'],connection=c);app.access(project,scope)
    require(not project['archived'] and (scope is None or project['id'] in scope),'无权接回此项目候选','forbidden',403)
    require(p.get('cycle_role')=='final_reviewer' and p.get('cycle_parent') and p.get('cycle_provider_route')=='codex',
            '此技术接回仅处理原 Codex 最终审查候选')
    require(task['status'] in ({'generated'} if completed else {'failed'}),'原审查仍在途、已暂停/取消或已有结果','cancelled',409)
    parent=s.task(p['cycle_parent'],c);state=parent['result'].get('cycle',{})
    require(parent['status']=='waiting_input' and state.get('phase')=='final_reviewing'
            and state.get('last_failure',{}).get('code')=='cycle_handoff' and state.get('final_reviewer')==ident,
            '父协作必须停在当前最终审查失败交接；不会自动恢复','cancelled',409)
    require(state.get('epoch')==_setting(c,'cycle_epoch:'+p['cycle_child_key']), '审查轮次已变化','cancelled',409)
    allocation=state.get('allocations',{}).get(p['cycle_child_key'],{})
    require(allocation.get('task_id')==ident and allocation.get('budget')==p['budget'] and allocation.get('provider_id')==p['provider_id'] and allocation.get('route')=='codex','原审查分配已变化','budget_exhausted',409)
    extension=_setting(c,'budget_extension:'+ident) or {}
    require(not extension.get('invocations') and not extension.get('seconds'),'协作子任务不得独立扩额','budget_exhausted',409)
    cfg=app.config.get('providers',{}).get(p['provider_id'],{})
    require(cfg.get('authorized') is True and cfg.get('route')=='codex','原 Codex 授权已撤回','authorization_required',403)
    for ref in [{'id':parent['id']},*state.get('children',[])]:
        lease=_setting(c,'execution:'+ref['id'])
        require(not lease or lease.get('state')!='active','原协作执行尚未结束','conflict',409)
    for current in (task,parent):
        s.assert_material_access(c,current['payload']);s.assert_feedback_ready(c,current['payload'])
        require(not s.question_blockers(c,current['id']),'必要裁决尚待处理','cancelled',409)
    record=state.get('final_revision')
    original_inputs=record['parent_inputs'] if record else s.task(state['integrator'],c)['payload']['context'].get('cycle_parent_inputs')
    require(original_inputs==s.execution_inputs(c,parent['id']),'最终稿产生后父级输入已变化','candidate_revision_required',409)
    for ref in p['context'].get('materials',[]):
        require(ref['sha256']==digest(s.get(ref['id'],ref['revision'],c)),'冻结材料身份不符','integrity',409)
    source=state['final_source'];current=s.get(source['id'],connection=c)
    require(current['revision']==source['revision'] and digest(current)==source['sha256'] and not current['archived'],'原最终稿已编辑或归档','candidate_revision_required',409)
    s.assert_source_access(c,parent['project_id'],source['id'])
    return task,parent


def _parse(text):
    text=text.strip()
    if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
    value=json.loads(text)
    require(isinstance(value,dict),'原候选不是 JSON 对象','invalid_model_output',422)
    return value


def inspect(app,c,data,scope,*,allow_invalid=False):
    from research_partner.execution.recovery import _directory
    task,parent=guard(app,c,data['id'],scope);s=app.store;directory=_directory(app,task['id'])
    identity=Providers(app).assert_codex_continuity(task,directory)
    require(identity.get('requires_checkpoint') is True,'没有同任务已结束 Codex 调用','provider_checkpoint_missing',503)
    receipt=json.loads(_controlled_file(directory,directory/'provider-receipt.json',131072))
    events=json.loads(_controlled_file(directory,directory/('codex-events-'+identity['attempt_id']+'.json')))
    require(receipt.get('returncode')==0 and len([e for e in events if e.get('type')=='turn.completed'])==1
            and events[-1].get('type')=='turn.completed' and not any(e.get('type') in {'turn.failed','error'} for e in events),
            'Codex 本次调用没有可证明的成功结束','candidate_checkpoint_invalid',409)
    reply=_controlled_file(directory,directory/('reply-'+identity['attempt_id']+'.txt'))
    raw=_controlled_file(directory,directory/'candidate.rejected.json')
    require(data.get('candidate_sha256')==digest(raw),'需要明确原被拒候选摘要','conflict',409)
    preserved=_controlled_file(directory,directory/('candidate.rejected-'+digest(raw)+'.json'))
    require(preserved==raw,'被拒候选与不可变副本不一致','integrity',409)
    source=_parse(raw.decode());reply_value=_parse(reply.decode())
    messages=[(i,e['item']['text']) for i,e in enumerate(events) if e.get('type')=='item.completed' and e.get('item',{}).get('type')=='agent_message' and isinstance(e['item'].get('text'),str)]
    require(messages and messages[-1][0]==len(events)-2 and _parse(messages[-1][1])==source==reply_value,
            '被拒候选、同次回复与完成事件不一致','candidate_checkpoint_invalid',409)
    model=next((row for row in task['steps'] if row['step_key']=='model'),None)
    require(model and model['status']=='running' and model['data'].get('provider_route')=='codex','缺少原调用输入检查点','candidate_checkpoint_invalid',409)
    inputs=model['data'].get('input_snapshot')
    require(inputs==s.execution_inputs(c,task['id']),'候选产生后审查输入已变化','candidate_revision_required',409)
    revision=data.get('revision',{'kind':'none'})
    require(isinstance(revision,dict) and revision.get('kind') in {'none','remove_empty_graph_review'} and not(set(revision)-{'kind','reason'}),'仅支持明确移除无提案的空图谱审查')
    candidate=copy.deepcopy(source);changes=[]
    if revision['kind']=='remove_empty_graph_review':
        require(isinstance(revision.get('reason'),str) and revision['reason'].strip(),'技术修订需要具体理由')
        from research_partner.domains.evidence.graph import items
        for evidence in task['payload']['context'].get('cycle_evidence',[]):
            proposal=evidence.get('content',{}).get('graph_proposal')
            require(not proposal or not items(proposal),'冻结输入仍有真实图谱提案；不得删除审查','invalid',409)
        graph=candidate.get('graph_review')
        require(isinstance(graph,dict) and set(graph)=={'version','proposals'} and type(graph['version']) is int and graph['version']==1
                and isinstance(graph['proposals'],list) and all(isinstance(row,dict) and set(row)=={'task_id','proposal_digest','items'}
                and isinstance(row['task_id'],str) and isinstance(row['proposal_digest'],str) and re.fullmatch(r'[0-9a-f]{64}',row['proposal_digest'])
                and row['items']==[] for row in graph['proposals']),'原 graph_review 不仅含空项；不能机械修正','invalid',409)
        del candidate['graph_review'];changes=[{'path':'graph_review','operation':'remove','before':graph,'basis':'frozen cycle_evidence has zero nonempty graph proposals'}]
    require(candidate.get('cycle_contract')==source.get('cycle_contract'),'科学审查合同不得被技术修订改变','integrity',409)
    output=raw if not changes else (json.dumps(candidate,ensure_ascii=False,indent=2)+'\n').encode()
    error=None;content=None;questions=[]
    try:
        content=validate_candidate(candidate,task['payload']['context']['output'],app,task['project_id'],task=task)
        questions=model_questions(candidate.get('questions',[]))
        require(not any(q['blocking'] for q in questions),'必要裁决仍需处理','candidate_revision_required',409)
    except Problem as exc:
        if not allow_invalid:raise
        error={'code':exc.code,'message':str(exc),'details':exc.details}
    calls=s.setting('provider_invocations:'+task['id'],0)
    usage={'route':'codex','status':'verified','session_id':identity['session_id'],'contract_sha256':identity['contract_sha256'],
           'usage':receipt.get('usage',[]),'cli_invocations':calls,'internal_api_requests':None,'actual_bill_usd':receipt.get('actual_bill_usd'),
           'sources':['durable_codex_checkpoint','verified_receipt','thread_started_event']}
    proof={**identity,'reply_sha256':digest(reply),'native_candidate_sha256':digest(raw),'terminal_event_index':len(events)-1}
    receipt={**receipt,'reason':{'kind':'completed'},'candidate':proof}
    pin={'task_id':task['id'],'task_sha256':digest(task),'parent_sha256':digest(parent),'native_candidate_sha256':digest(raw),
         'candidate_sha256':digest(output),'contract_sha256':identity['contract_sha256'],'session_id':identity['session_id'],
         'input_snapshot':inputs,'revision':revision,'usage_sha256':digest(usage),'codex_proof':proof,
         'material_heads':[{ 'id':ref['id'],'revision':s.get(ref['id'],connection=c)['revision']} for ref in task['payload']['context'].get('materials',[])]}
    return {'task':task,'parent':parent,'candidate':candidate,'content':content,'questions':questions,'validation_error':error,
            'raw':raw,'output':output,'receipt':receipt,'usage':usage,'changes':changes,'pin':pin}
