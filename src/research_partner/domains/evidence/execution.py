"""Finite independent-context assessment tasks, with exact output/review lineage.

Independence here means a separately verified execution/session with a frozen
neutral packet. It is not a claim of independent provider/model/human consensus.
"""
import copy,json,math
from research_partner.storage.store import require,Problem,digest,uid,encoded,now
from research_partner.domains.evidence.evidence import setting,read,output
from research_partner.domains.evidence.assessment import packet,_ref,verify

FEATURE='execution_bound_growth_assessment_v1'
KIND='growth_assessment'
BLOCK='growth-assessment-contract'
INSTRUCTION='''Independently assess the two exact scientific outputs in context.growth_review_packet under its frozen comparison protocol. The strategy text, author self-assessment and previous verdicts are intentionally absent. Do not infer hidden context or causal/general efficacy. If relatedness or evidence is inadequate, return inconclusive rather than inventing support. Read every quoted field you use. No fitting, new research calculation, web access or new permissions. Return one ordinary note JSON with title, kind="note", readable prose blocks, and exactly one block id="growth-assessment-contract",kind="review",text containing a JSON-encoded paired assessment object. That object must have review_packet_sha256,protocol_sha256,strategy_sha256; baseline and treatment copied exactly from outputs[0/1].binding; input_differences_sha256 from input_comparison.differences_sha256; comparison_design from protocol; comparability (actual relevance judgment); input_difference_assessments:[{path,scope_limit}] for every input_difference_paths entry; limitations:[nonempty strings]; outcomes:[one per protocol criterion, with criterion_id, baseline/treatment:{value,denominator,unit,explanation,evidence:[{path:"/content/...",quote:literal source excerpt}]},judgment:"improved"|"unchanged"|"worse"|"mixed"|"inconclusive",rationale]; verdicts:["needs_revision"|"usable_for_discussion"|"reviewed_with_limits" for each exact output]. For qualitative values describe observations; for numerical reviews use actual values with explicit units and positive denominators. Actual bill criteria use only supplied actual_bill_usd, USD, denominator 1; unknown stays null. Conclusions are bounded observations, never scientific approval. Do not include strategy guesses or author reputation in the judgment.'''


def body(report):
    rows=[b for b in report['content'].get('blocks',[]) if b.get('id')==BLOCK]
    require(len(rows)==1 and rows[0].get('kind')=='review','评估执行产物缺少唯一具名配对合同','growth_evidence_required',409)
    try:value=json.loads(rows[0]['text'])
    except (KeyError,ValueError,TypeError):raise Problem('评估执行合同不是 JSON 对象','growth_evidence_required',409)
    require(isinstance(value,dict),'评估合同需要对象');return value


def heads(s,c,pack):
    result=[]
    for item in pack['outputs']:
        binding=item['binding'];current=s.get(binding['object_id'],connection=c)
        require(current['revision']==binding['revision'] and digest(current)==binding['source_sha256'],'评估输出已经出现新修订，请明确采用新比较输入','growth_stale',409)
        result.append(_ref(current))
    return result


def guard(s,c,task):
    if task['payload'].get('kind')!=KIND:return None
    record=setting(c,'growth_assessor:'+task['id']);require(record,'此评估任务没有注册冻结合同','growth_evidence_required',409)
    require(record['sha256']==digest({k:v for k,v in record.items() if k!='sha256'}) and digest(task['payload'])==record['payload_sha256'],'评估任务合同被改动','integrity',409)
    from research_partner.domains.evidence.growth import identity,source_ready
    g=s.get(record['growth_id'],connection=c);source_ready(s,c,g)
    require(g['content']['status'] not in {'reject','revert'} and identity(g)==record['strategy_sha256'],'成长候选已撤回或改变','growth_stale',409)
    pack=packet(s,c,g,record['pair'])
    require(pack['pin']==record['packet_pin'] and heads(s,c,pack)==record['source_heads'],'评估采用输入已变化','growth_stale',409)
    require(s.execution_inputs(c,task['id'])=={'decisions':[],'guidance':[]},'评估任务新增作者指导或裁决；不再是冻结的独立上下文，请另行明确安排','growth_stale',409)
    return record,pack,g


def guard_configuration(app,c,task):
    if task['payload'].get('kind')!=KIND:return
    record=setting(c,'growth_assessor:'+task['id']);cfg=app.config.get('providers',{}).get(task['payload'].get('provider_id'),{})
    require(record and cfg.get('authorized') and digest(cfg)==record['provider_configuration_sha256'],'评估提供者权限或配置在预览后改变；未派发或接受新结果','authorization_required',403)


def create(app,c,g,data,scope,preview):
    s=app.store;pack=packet(s,c,g,data);source_heads=heads(s,c,pack)
    provider=data.get('provider_id') or app.config.get('default_provider');cfg=app.config.get('providers',{}).get(provider,{})
    require(cfg.get('authorized') and cfg.get('route')=='codex','当前版本的执行绑定评估要求已授权 Codex 路线；不会授权或启用新服务','authorization_required',403)
    budget=data.get('budget');require(isinstance(budget,dict) and type(budget.get('max_model_calls')) is int and 1<=budget['max_model_calls']<=4 and type(budget.get('timeout_seconds')) in (int,float) and math.isfinite(budget['timeout_seconds']) and 0<budget['timeout_seconds']<=900,'评估需要明确有限调用和时限')
    from research_partner.domains.evidence.growth import identity
    context={'background':{},'additional_background':'','question':INSTRUCTION,'materials':[],'constraints':'Read-only frozen output comparison; no network, fitting, original data edits or additional permissions.','output':'note','acceptance':'Publish an exact source-bound, limited paired evaluation; no scientific approval.','unresolved':[],'working_conventions':[],'working_strategies':[],'growth_review_packet':{**pack['review_packet'],'review_packet_sha256':pack['review_packet_sha256']}}
    payload={'project_id':g['project_id'],'kind':KIND,'request':INSTRUCTION,'context':context,'target_id':None,'base_revision':None,'provider_id':provider,'depends_on':[],'budget':copy.deepcopy(budget),'authorization':{},'priority':0,'feedback_id':g['content']['feedback'],'workshop':{}}
    plan={'payload':payload,'packet_pin':pack['pin'],'source_heads':source_heads,'strategy_sha256':identity(g),'provider_configuration_sha256':digest(cfg),'growth_id':g['id'],'pair':{'baseline':pack['baseline'],'treatment':pack['treatment']}}
    pin=digest(plan)
    if preview:return {'pin':pin,'plan':plan,'new_model_requests':0,'will_wait_for_explicit_continuation':True,'independence_scope':'New task/session and neutral frozen packet; not different-model/human consensus.'}
    require(data.get('pin')==pin,'评估来源或配置在预览后改变','conflict',409)
    from research_partner.packaging.compatibility import require_features
    require_features(c,[FEATURE]);task=s.submit(payload,uid('GROWTH-EVAL-REQUEST'),connection=c)
    record={**plan,'task_id':task['id'],'payload_sha256':digest(payload),'created_at':now()};record['sha256']=digest(record)
    c.execute('INSERT INTO kv VALUES(?,?)',('growth_assessor:'+task['id'],encoded(record)))
    c.execute("UPDATE tasks SET status='waiting_input',error=?,updated_at=? WHERE id=?",('评估任务已冻结，需明确继续；未调用提供者',now(),task['id']))
    s.event(c,'growth.assessor_registered',g['id'],{'task_id':task['id'],'contract_sha256':record['sha256'],'new_model_requests':0},'coordinator')
    return {'task_id':task['id'],'contract_sha256':record['sha256'],'packet_sha256':pack['review_packet_sha256'],'new_model_requests':0,'state':'waiting_input','budget':budget}


def execution(app,c,g,data):
    s=app.store;task=s.task(data.get('assessment_task_id'),c)
    require(task['payload'].get('kind')==KIND and task['project_id']==g['project_id'] and task['status']=='generated','评估执行尚未发布完成，或已暂停取消','growth_evidence_required',409)
    registry,pack,current=guard(s,c,task);require(current['id']==g['id'],'评估属于其他候选','forbidden',403)
    require(data.get('attempt')==task['attempts'],'请明确本次已发布评估 attempt','conflict',409)
    cfg=app.config.get('providers',{}).get(task['payload']['provider_id'],{})
    require(cfg.get('authorized') and digest(cfg)==registry['provider_configuration_sha256'],'评估提供者权限或配置已变化','authorization_required',403)
    attempt=read(s,c,task,data['attempt']);binding=output(s,c,task,data['attempt']);require(binding and attempt.get('full_inputs') and attempt['validation']['passed'],'评估没有完整的执行和发布绑定','growth_evidence_required',409)
    require(attempt['full_inputs']['payload']==task['payload'] and not attempt['input_snapshot']['guidance'] and not attempt['input_snapshot']['decisions'] and not attempt['trials'],'评估实际输入被额外介入污染','integrity',409)
    require(attempt['full_inputs']['frozen_evidence']['context']==task['payload']['context'] and attempt['full_inputs']['frozen_evidence']['objects']==[],'评估读取了冻结包之外的材料','integrity',409)
    from research_partner.providers.registry import Providers
    from research_partner.execution.recovery import _directory
    continuity=Providers(app).assert_codex_continuity(task,_directory(app,task['id']))
    require(continuity.get('session_id')==attempt['provider'].get('session_id') and continuity.get('contract_sha256')==attempt['provider'].get('contract_sha256') and continuity.get('attempt_id')==attempt['provider'].get('attempt_id'),'评估原生回执与发布尝试不一致','integrity',409)
    for ref in [pack['baseline'],pack['treatment']]:
        author=read(s,c,s.task(ref['task_id'],c),ref['attempt']);session=author.get('provider',{}).get('session_id')
        require(task['id']!=ref['task_id'] and session and session!=continuity['session_id'],'评估未形成可核对的独立会话身份','growth_evidence_required',409)
    report=s.get(binding['object_id'],binding['revision'],c);require(s.get(report['id'],connection=c)['revision']==report['revision'],'评估输出被后续编辑，请明确重新安排审查绑定','growth_stale',409);require(report['metadata'].get('task_id')==task['id'],'评估发布成果归属不符','integrity',409)
    body_value=body(report);verdicts=body_value.get('verdicts');require(isinstance(verdicts,list) and len(verdicts)==2 and all(x in {'needs_revision','usable_for_discussion','reviewed_with_limits'} for x in verdicts),'实际评估须明确两侧有限审阅判断')
    evidence={'task_id':task['id'],'attempt':task['attempts'],'attempt_sha256':attempt['sha256'],'output':binding,'registry_sha256':registry['sha256'],'continuity':continuity,'provider_configuration_sha256':registry['provider_configuration_sha256'],'independence_scope':'Verified separate task/session, frozen neutral inputs and actual output; same-provider/context separation is not cross-model consensus or human peer acceptance.'}
    return pack,report,body_value,verdicts,evidence


def register(app,c,g,data,scope,preview):
    s=app.store;pack,report,body_value,verdicts,evidence=execution(app,c,g,data)
    provenance={'mode':'verified_independent_execution','identity':evidence['task_id']+'@'+str(evidence['attempt']),'role':'independent_assessment_execution','authorization_reference':evidence['registry_sha256'],'scope':pack['protocol']['domain_scope']}
    pin=digest({'packet_pin':pack['pin'],'report':_ref(report),'execution':evidence})
    if not preview:require(data.get('pin')==pin,'评估执行或源结果在预览后改变','conflict',409)
    reviews=[]
    for item,verdict in zip(pack['outputs'],verdicts):
        binding=item['binding'];reviews.append(s.record_review(binding['object_id'],binding['revision'],{'review_object_id':report['id'],'review_revision':report['revision'],'review_source_sha256':digest(report),'verdict':verdict,'scope':pack['protocol']['domain_scope'],'summary':body_value['comparability'],'reviewer_reference':provenance['identity'],'assessment_execution':evidence},connection=c))
    assessment=verify(s,c,g,pack,{'assessment_ref':_ref(report),'review_ids':[r['identity'] for r in reviews],'evaluator':provenance},scope,execution=evidence)
    if preview:return {'pin':pin,'assessment':assessment,'new_model_requests':0,'saved':False}
    ident=uid('ASSESS');record={**assessment,'id':ident,'growth_id':g['id'],'strategy_sha256':pack['strategy_sha256'],'at':now()};record['sha256']=digest(record)
    c.execute('INSERT INTO kv VALUES(?,?)',('growth_assessment:'+g['id']+':'+ident,encoded(record)));s.event(c,'growth.assessment_registered',g['id'],record,'coordinator');return record
