"""Candidate, single-task trial, comparison and scoped policy are distinct states."""
import copy
import json
from .store import Problem,require,digest,encoded,uid,now
from .growth_evidence import setting,profile,read,input_comparison

FEATURE='bounded_growth_evidence_v1'


def feedback_identity(obj):
    from .store import Store
    fields={k:obj['content'].get(k) for k in ('original','interpretation','source','source_reference','object_id','object_revision','lifecycle','disposition_reason')}
    fields.update(disposition=Store.feedback_disposition(obj),scope=obj['metadata'].get('scope'),timing=obj['metadata'].get('timing'))
    return digest(fields)


def identity(obj):
    value={k:obj['content'].get(k) for k in ('candidate','hypothesis','source_refs','feedback_semantics_sha256')}
    if obj['content'].get('comparison_protocol') is not None:value['comparison_protocol']=obj['content']['comparison_protocol']
    return digest(value)


def policy_current(policy):
    return bool(policy and policy.get('status') in {'adopt','preference'} and (policy['status']=='preference' or policy.get('comparison_engine_version')==2))


def _put(c,key,value):
    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,encoded(value)))


def _refs(s,c,project,refs):
    require(isinstance(refs,list),'方法来源须为具体版本的 source_refs')
    result=[]
    for ref in refs:
        require(isinstance(ref,dict) and isinstance(ref.get('id'),str) and type(ref.get('revision')) is int,'方法来源需明确对象和修订')
        s.assert_source_access(c,project,ref['id']);obj=s.get(ref['id'],ref['revision'],c)
        require(not s.get(ref['id'],connection=c)['archived'],'方法来源已归档','forbidden',403)
        result.append({'id':obj['id'],'revision':obj['revision'],'sha256':digest(obj)})
    return result


def source_ready(s,c,obj):
    require(not obj['archived'],'成长候选已归档','forbidden',403)
    require(not s.get(obj['project_id'],connection=c)['archived'],'项目已归档','forbidden',403)
    s.assert_feedback_ready(c,{'feedback_id':obj['content']['feedback']})
    fb=s.get(obj['content']['feedback'],connection=c)
    require(not obj['content'].get('feedback_semantics_sha256') or feedback_identity(fb)==obj['content']['feedback_semantics_sha256'],'反馈含义或安排已变化，需明确提出新候选；历史保留','growth_stale',409)
    for ref in obj['content'].get('source_refs',[]):
        s.assert_source_access(c,obj['project_id'],ref['id'])
        require(digest(s.get(ref['id'],ref['revision'],c))==ref['sha256'],'方法来源身份已变化','integrity',409)


def _link(s,c,obj):
    fb=s.get(obj['content']['feedback'],connection=c);actions=copy.deepcopy(fb['content'].get('actions',[]))
    prior=next((a for a in actions if a.get('growth_id')==obj['id'] and a.get('scope')=='method' and not a.get('trial_id')),None)
    action={**(prior or {'id':uid('ACTION')}),'scope':'method','timing':'after_task','owner':'coordinator','growth_id':obj['id'],
            'revision':obj['revision'],'status':obj['content']['status'],'verification':obj['content'].get('evidence_level','effects_unverified')}
    actions=[a for a in actions if a is not prior]+[action]
    for trial in obj['content'].get('trials',[]):
        if not any(a.get('trial_id')==trial['id'] for a in actions):
            task=s.task(trial['task_id'],c)
            actions.append({'id':uid('ACTION'),'scope':'method','timing':'immediate','owner':'research_agent','growth_id':obj['id'],'trial_id':trial['id'],
                            'task_id':task['id'],'provider_id':task['payload'].get('provider_id'),'status':task['status'],'verification':'Finite trial registered; actual attempt/output evidence remains separately inspectable.'})
    s.save(fb['id'],fb['revision'],content={**fb['content'],'actions':actions},reason='growth evidence disposition',connection=c)



def _save(s,c,obj,content):
    result=s.save(obj['id'],obj['revision'],content=content,reason='explicit bounded growth action',merge=False,connection=c);_link(s,c,result);return result


def _object(app,c,data,scope,cas=True):
    obj=app.store.get(data['id'],connection=c);project=app.access(app.store.get(obj['project_id'],connection=c),scope)
    require(obj['kind']=='growth' and (scope is None or project['id'] in scope),'无权修改此成长候选','forbidden',403)
    require(not data.get('project_id') or obj['project_id']==data['project_id'],'成长候选项目不一致','forbidden',403)
    if cas:require(data.get('expected_revision')==obj['revision'],'成长候选已变化，请重新读取','conflict',409)
    return obj


def active(s,project,task_profile,connection=None):
    if connection is None:
        with s.connect() as c:return active(s,project,task_profile,c)
    result=[];c=connection
    for row in c.execute("SELECT * FROM objects WHERE project_id=? AND kind='growth' AND archived=0",(project,)):
        obj=s.unpack(row);policy=setting(c,'growth_policy:'+obj['id'])
        if not policy_current(policy) or policy.get('strategy_sha256')!=identity(obj) or obj['content'].get('status')!=policy.get('status') or policy.get('profile')!=task_profile:continue
        try:source_ready(s,c,obj)
        except Problem:continue
        result.append({'id':obj['id'],'revision':policy['strategy_revision'],'instruction':policy['instruction'],'strategy_sha256':policy['strategy_sha256'],
            'source_feedback':obj['content']['feedback'],'policy_sha256':digest(policy),'mode':policy['status'],
            'evidence_level':policy['evidence_level'],'evidence_scope':policy.get('evidence_scope'),'scope':'This exact research task kind/output/role only; no permission, budget or scientific-approval change.'})
    return result


def assert_ready(s,c,task):
    """Revert/withdraw blocks unconsumed instructions, never deletes old output."""
    if task['payload'].get('kind')=='growth_assessment':
        from .growth_execution import guard
        guard(s,c,task)
    for item in task['payload'].get('context',{}).get('working_strategies',[]):
        obj=s.get(item['id'],connection=c);policy=setting(c,'growth_policy:'+obj['id'])
        require(policy and item.get('policy_sha256')==digest(policy) and policy_current(policy) and obj['content'].get('status')==policy.get('status') and identity(obj)==item.get('strategy_sha256'),
                '工作策略已撤回、修订或缺少证据绑定；旧输入保留，需明确新安排','growth_stale',409)
        source_ready(s,c,obj)
    inputs=s.execution_inputs(c,task['id'])
    for row in c.execute('SELECT value FROM kv WHERE key LIKE ?',('growth_trial:'+task['id']+':%',)):
        trial=json.loads(row[0])
        if trial['guidance_seq'] not in inputs['guidance']:continue
        obj=s.get(trial['growth_id'],connection=c);source_ready(s,c,obj)
        require(identity(obj)==trial['strategy_sha256'] and obj['content'].get('status') not in {'reject','revert'} and trial['status']=='armed',
                '此任务的试用策略已撤回或改变；不会静默继续旧指令','growth_stale',409)


def view(s,obj,connection=None):
    if connection is None:
        with s.connect() as c:return view(s,obj,c)
    policy=setting(connection,'growth_policy:'+obj['id']);bound=bool(policy and policy.get('strategy_sha256')==identity(obj) and policy_current(policy) and obj['content'].get('status')==policy.get('status'))
    blocked=None
    if bound:
        try:source_ready(s,connection,obj)
        except Problem as error:blocked={'code':error.code,'message':str(error)};bound=False
    observations=[]
    for row in connection.execute("SELECT value FROM kv WHERE key LIKE 'growth_attempt:%'"):
        record=json.loads(row[0])
        if any(t['growth_id']==obj['id'] and t['strategy_sha256']==identity(obj) for t in record['trials']):
            observations.append({k:record[k] for k in ('task_id','attempt','input_snapshot','output','validation','provider','recorded_at','sha256')})
    qualified=[json.loads(row[0]) for row in connection.execute('SELECT value FROM kv WHERE key LIKE ?',('growth_comparison:'+obj['id']+':%',))]
    qualified=[x for x in qualified if x.get('comparison_engine_version')==2 and x.get('adoption_eligible') and x.get('strategy_sha256')==identity(obj)]
    treatment_tasks=sorted({x['evidence'][1]['task_id'] for x in qualified})
    case_counts={'eligible_comparisons':len(qualified),'distinct_treatment_tasks':len(treatment_tasks),'task_ids':treatment_tasks,'cross_task_general_effectiveness':'unverified'}
    level=policy['evidence_level'] if bound else obj['content'].get('evidence_level','effects_unverified')
    if observations and level in {'written_rule_only','trial_registered_not_executed','trial_registered_exposure_pending'}:level='actually_triggered_effect_unverified'
    return {**obj,'growth_state':{'strategy_sha256':identity(obj),'activation':policy['status'] if bound else 'inactive',
            'evidence_level':level,'attempt_observations':observations,'case_counts':case_counts,
            'blocked':blocked,'legacy_unverified':obj['content'].get('status')=='adopt' and not bound,'policy':policy if bound else None,
            'scope_note':'Recorded rule / actual exposure / current-case outcome / multiple-task observations are separate; no automatic scientific or cost claim.'}}


def _trial(app,c,obj,data):
    s=app.store;source_ready(s,c,obj);require(obj['content'].get('status') not in {'reject','revert'},'候选已拒绝或撤回；请保留历史并另提修订')
    task=s.task(data['task_id'],c);p=task['payload'];
    provider=app.config.get('providers',{}).get(p.get('provider_id'),{})
    require(provider.get('authorized'),'既有执行路线未获授权；只保留候选，不登记执行介入','authorization_required',403)
    require(task['project_id']==obj['project_id'] and p.get('kind')=='research','试用须为同项目单项科研任务','forbidden',403)
    require(task['status'] in {'queued','failed','waiting_input','waiting_resource','waiting_authorization'} and task['attempts']<3,'任务正在执行、已暂停/取消/完成或尝试已耗尽','conflict',409)
    lease=setting(c,'execution:'+task['id']);require(not lease or lease.get('state')!='active','任务仍有活动执行','conflict',409)
    parent_pin=None
    if p.get('cycle_parent'):
        parent=s.task(p['cycle_parent'],c);require(parent['status'] not in {'paused','cancelled','generated','deliverable'},'父协作已停止或结束','cancelled',409)
        s.assert_feedback_ready(c,parent['payload']);s.assert_material_access(c,parent['payload'])
        require(not s.question_blockers(c,parent['id']),'父级必要裁决尚待处理','conflict',409)
        parent_pin={'task_sha256':digest(parent),'input_snapshot':s.execution_inputs(c,parent['id'])}
    require(p.get('budget',{}).get('max_model_calls',0)>int(setting(c,'provider_invocations:'+task['id']) or 0),'既有任务调用额度不足；试用不扩额','budget_exhausted',409)
    require(float(setting(c,'elapsed:'+task['id']) or 0)<p['budget']['timeout_seconds'],'既有时限已耗尽','budget_exhausted',409)
    if p.get('cycle_provider_route')=='deepseek_harness' or app.config.get('providers',{}).get(p.get('provider_id'),{}).get('route')=='deepseek_harness':
        from .native_accounting import accounting
        usage=accounting(s,task,c)
        require(not task['attempts'] or (usage['status']=='verified' and usage['reserved_requests']<p['budget']['max_model_calls']),'原生额度未知或已耗尽；不重开任务','budget_exhausted',409)
    s.assert_material_access(c,p);s.assert_feedback_ready(c,p);require(not s.question_blockers(c,task['id']),'必要裁决尚待处理','conflict',409)
    require(isinstance(data.get('relevance'),str) and data['relevance'].strip() and isinstance(data.get('limits'),str) and data['limits'].strip(),'请登记任务相关性、比较范围和限制')
    pin={'growth_id':obj['id'],'growth_revision':obj['revision'],'strategy_sha256':identity(obj),'task_id':task['id'],'task_sha256':digest(task),
         'comparison_protocol_sha256':digest(obj['content'].get('comparison_protocol')),'input_snapshot':s.execution_inputs(c,task['id']),'parent':parent_pin,'relevance':data['relevance'],'limits':data['limits'],'profile':profile(p)}
    return task,pin


def _compare(s,c,obj,data,app=None):
    refs=[data.get('baseline'),data.get('treatment')]
    require(all(isinstance(r,dict) and set(r)=={'task_id','attempt'} for r in refs),'比较需明确 baseline/treatment 的 task_id 与 attempt')
    require(refs[0]!=refs[1],'不能把同一次执行同时作为基线和处理')
    tasks=[s.task(r['task_id'],c) for r in refs]
    require(all(t['project_id']==obj['project_id'] and t['status'] in {'generated','review','deliverable','failed'} for t in tasks),'比较任务未形成结果或不在项目范围','forbidden',403)
    evidence=[read(s,c,t,r['attempt']) for t,r in zip(tasks,refs)]
    require(all(isinstance(data.get(k),str) and data[k].strip() for k in ('interpretation','limits')),'比较需要实际观察解释和混杂限制')
    complete=all(e.get('identity_status')=='captured_provider_return' for e in evidence)
    issues=[];exposure=None;matched=False;improved=False;prospective=False;before=False;isolated=False;assessment=None
    inputs={'complete':False,'matched':False,'differences':[],'limits':'Historical attempt input/output evidence incomplete.'}
    if complete:
        a,b=evidence;matches=[t for t in b['trials'] if t['growth_id']==obj['id'] and t['strategy_sha256']==identity(obj)]
        exposure=matches[-1] if matches else None
        inputs=input_comparison(a,b,exposure);matched=inputs['matched']
        before=any(t['growth_id']==obj['id'] and t['strategy_sha256']==identity(obj) for t in a['trials']) or any(g.get('strategy_sha256')==identity(obj) for g in a['payload'].get('context',{}).get('working_strategies',[]))
        prospective=bool(exposure and exposure['created_at']<b['recorded_at'] and exposure['guidance_seq'] in b['input_snapshot']['guidance'])
        unchanged_decisions=a['input_snapshot']['decisions']==b['input_snapshot']['decisions']
        extra=set(b['input_snapshot']['guidance'])-set(a['input_snapshot']['guidance'])
        isolated=bool(exposure and unchanged_decisions and set(a['input_snapshot']['guidance'])<=set(b['input_snapshot']['guidance']) and extra=={exposure['guidance_seq']})
        if not exposure:issues.append('No exact candidate-version trial instruction was supplied to treatment.')
        if before:issues.append('Baseline already exposed to the candidate.')
        if not inputs['complete']:issues.append('Full actual model inputs were not captured; old design hashes cannot prove equivalence.')
        if not matched:issues.append('Complete actual model inputs differ; see the full input comparison, not a field allowlist.')
        if not isolated:issues.append('Other guidance or decision inputs changed; cannot isolate this candidate intervention.')
    else:issues.append('Historical per-attempt input/output identities were not captured; observation only.')
    applicable=bool(complete and exposure and prospective and not before and isolated and inputs['complete'])
    protocol=obj['content'].get('comparison_protocol');measure='reviewed_method_outcome' if protocol else 'candidate_structure'
    if protocol:
        if data.get('assessment_id'):
            assessment=setting(c,'growth_assessment:'+obj['id']+':'+str(data['assessment_id']))
            require(assessment and assessment['strategy_sha256']==identity(obj) and assessment['baseline']==refs[0] and assessment['treatment']==refs[1],'评估不属于当前策略和这对执行','growth_evidence_required',409)
            from .growth_assessment import reread
            reread(s,c,obj,assessment,app)
            improved=assessment['supported'];issues.extend(assessment['issues'])
        else:issues.append('A version-bound paired outcome assessment is still required; no method benefit is inferred.')
        qualified=bool(applicable and assessment and improved and (matched or protocol['comparison_design']=='related_tasks_observational'))
        verified=bool(assessment and assessment.get('execution'))
        level='independent_context_method_hypothesis' if verified else 'owner_assessed_method_hypothesis'
        effect_limits=['Registered paired assessment supports only this explicitly scoped working hypothesis.','Separate task/session provenance is verified; this is not cross-model consensus or human acceptance.' if verified else 'Manual evaluator independence is owner-attested; not independently authenticated.','Nonrandom assignment, context/session history and remaining input differences preclude causal or general efficacy claims.','No scientific approval, user acceptance or unobserved cost saving.']
    else:
        improved=bool(complete and evidence[0]['validation'].get('passed') is False and evidence[1]['validation'].get('passed') is True)
        if not improved:issues.append('No captured failed-to-valid candidate-structure transition.')
        qualified=bool(applicable and matched and improved);level='current_case_structure_improved'
        effect_limits=['Only candidate structural validity is measured.','Scientific quality, efficiency, cost saving and causal/general effectiveness are unverified.']
    record={'id':uid('CMP'),'comparison_engine_version':2,'strategy_sha256':identity(obj),'strategy_revision':obj['revision'],'evidence':evidence,'interpretation':data['interpretation'],'limits':data['limits'],
            'observation_refs':_refs(s,c,obj['project_id'],data.get('observation_refs',[])),'measure':measure,'assessment':assessment,
            'input_comparison':inputs,'design':('prospective_intervention_observational_comparison' if protocol else 'prospective_single_task_trial') if prospective else 'retrospective_observation',
            'candidate_exposed':bool(exposure),'inputs_matched':matched,'current_case_improved':bool(qualified and not protocol),'owner_assessed_case_improvement':bool(qualified and protocol and not assessment.get('execution')),'independent_context_assessed_case_improvement':bool(qualified and protocol and assessment and assessment.get('execution')),'adoption_eligible':bool(qualified),
            'issues':issues,'profile':evidence[-1]['profile'],'evidence_level':level,'effect_limits':effect_limits,'at':now(),'scientific_approval':False}
    record['sha256']=digest(record);return record


def dispatch(app,data,scope=None):
    s=app.store;preview=data['action'].endswith('_preview') or data['action'] in {'growth.view','growth.assessment_packet','growth.review_evidence'}
    with (s.connect() if preview else s.transaction()) as c:
        if preview:c.execute('BEGIN')
        key=data.get('request_key')
        if key:
            require(isinstance(key,str) and 1<=len(key)<=180,'动作身份格式无效')
            project=data.get('project_id') or s.get(data['id'],connection=c)['project_id']
            app.access(s.get(project,connection=c),scope)
            require(scope is None or project in scope,'无权写此项目','forbidden',403)
            cachekey='growth_action:'+project+':'+key
            cached=setting(c,cachekey)
            if cached:
                require(cached['request_sha256']==digest(data),'同一动作身份不能更换请求内容','conflict',409)
                return cached['response']
        if not preview:
            from .compatibility import require_features
            require_features(c,[FEATURE,'reviewed_growth_comparison_v2'])
        result=_dispatch(app,data,scope,c)
        if key and not preview:_put(c,cachekey,{'request_sha256':digest(data),'response':result})
        return result


def _dispatch(app,data,scope,c):
    s=app.store;action=data['action'];preview=action.endswith('_preview')
    if action=='growth.propose':
        project=app.access(s.get(data['project_id'],connection=c),scope);require(project['kind']=='project' and (scope is None or project['id'] in scope),'无权写此项目','forbidden',403)
        fb=s.get(data['source_feedback'],connection=c);require(fb['kind']=='feedback' and fb['project_id']==project['id'],'反馈来源不符','forbidden',403)
        require(all(isinstance(data.get(k),str) and data[k].strip() for k in ('hypothesis','candidate','baseline')) and len(data['candidate'])<=4000,'需要具体假设、可读最小策略和基线')
        refs=_refs(s,c,project['id'],data.get('source_refs',[]))
        from .growth_assessment import protocol
        comparison_protocol=protocol(data.get('comparison_protocol'))
        obj=s.create('growth',data.get('title',data['hypothesis'][:80]),project['id'],{'version':2,'feedback':fb['id'],'feedback_ref':{'id':fb['id'],'revision':fb['revision'],'sha256':digest(fb)},
            'feedback_semantics_sha256':feedback_identity(fb),'hypothesis':data['hypothesis'],'candidate':data['candidate'],'baseline':data['baseline'],'source_refs':refs,'origin':data.get('origin','local_case'),
            'comparison_protocol':comparison_protocol,'status':'candidate','evidence_level':'written_rule_only','comparisons':[],'trials':[]},connection=c)
        _link(s,c,obj);return view(s,obj,c)
    obj=_object(app,c,data,scope,cas=action!='growth.view')
    if action=='growth.view':return view(s,obj,c)
    if action=='growth.review_evidence':
        from .growth_assessment import review_evidence
        return review_evidence(s,c,obj['project_id'],data.get('output_refs'))
    if action=='growth.assessment_packet':
        source_ready(s,c,obj)
        from .growth_assessment import packet
        return packet(s,c,obj,data)
    if action in {'growth.assessment_task_preview','growth.assessment_task_create'}:
        source_ready(s,c,obj)
        from .growth_execution import create
        result=create(app,c,obj,data,scope,preview)
        if preview:return result
        saved=_save(s,c,obj,{**obj['content'],'assessment_tasks':obj['content'].get('assessment_tasks',[])+[result]})
        return {**result,'growth':view(s,saved,c)}
    if action in {'growth.assessment_execution_preview','growth.assessment_execution_register'}:
        source_ready(s,c,obj)
        from .growth_execution import register
        record=register(app,c,obj,data,scope,preview)
        if preview:return record
        saved=_save(s,c,obj,{**obj['content'],'assessments':obj['content'].get('assessments',[])+[record]})
        return {'growth':view(s,saved,c),'assessment':record}
    if action in {'growth.assessment_create_preview','growth.assessment_create'}:
        source_ready(s,c,obj)
        from .growth_assessment import create
        record=create(s,c,obj,data,scope,preview)
        if preview:return record
        saved=_save(s,c,obj,{**obj['content'],'assessments':obj['content'].get('assessments',[])+[record]})
        return {'growth':view(s,saved,c),'assessment':record}
    if action in {'growth.assessment_register_preview','growth.assessment_register'}:
        source_ready(s,c,obj)
        from .growth_assessment import registered
        record=registered(s,c,obj,data,scope,preview)
        if preview:return record
        saved=_save(s,c,obj,{**obj['content'],'assessments':obj['content'].get('assessments',[])+[record]})
        return {'growth':view(s,saved,c),'assessment':record}

    if action in {'growth.trial_preview','growth.trial_bind','growth.trial_create_preview','growth.trial_create'}:
        creating=action in {'growth.trial_create_preview','growth.trial_create'}
        if creating:
            submission=data.get('submission')
            require(isinstance(submission,dict) and submission.get('project_id')==obj['project_id'] and submission.get('kind','research')=='research','需要同项目的完整有限科研委托')
            require(not submission.get('feedback_id'),'试用来源反馈已由成长候选绑定；不要重复注册任务反馈')
            task=app.submit({**submission,'action':'task.submit'},scope,connection=c)
            require(task['attempts']==0 and task['status']=='queued','该提交身份已使用；不将既有任务伪装成新试用','conflict',409)
            data={**data,'task_id':task['id']}
        task,pin=_trial(app,c,obj,data)
        if creating:
            pin={k:v for k,v in pin.items() if k not in {'task_id','task_sha256'}}
            pin['submission_sha256']=digest(task['payload'])
        if preview:return {'pin':pin,'strategy':{'id':obj['id'],'revision':obj['revision'],'instruction':obj['content']['candidate'],'sha256':identity(obj)},'task':{'id':task['id'],'status':task['status'],'budget':task['payload']['budget']},'new_model_requests':0,'will_wait_for_explicit_continuation':True}
        require(data.get('pin')==pin,'预览后任务、策略或输入已变化','conflict',409)
        from .compatibility import require_features
        require_features(c,[FEATURE,'reviewed_growth_comparison_v2']);trialid=uid('TRIAL')
        s.event(c,'task.guidance',task['id'],{'text':obj['content']['candidate'],'source':'coordinator','source_reference':{'growth_id':obj['id'],'growth_revision':obj['revision'],'strategy_sha256':identity(obj),'trial_id':trialid},'scope':'one existing finite task trial; not adoption or new permissions'},'coordinator')
        seq=c.execute('SELECT last_insert_rowid()').fetchone()[0]
        record={**pin,'task_id':task['id'],'id':trialid,'instruction':obj['content']['candidate'],'guidance_seq':seq,'created_at':now(),'status':'armed','parent_id':task['payload'].get('cycle_parent'),'scientific_approval':False}
        _put(c,'growth_trial:'+task['id']+':'+trialid,record)
        c.execute("UPDATE tasks SET status='waiting_input',error=?,updated_at=? WHERE id=?",('单任务试用已登记，等待明确继续/修订；预算与权限未改变',now(),task['id']))
        result=_save(s,c,obj,{**obj['content'],'trials':obj['content'].get('trials',[])+[record],'evidence_level':'trial_registered_exposure_pending'})
        return {'growth':view(s,result,c),'trial':record,'task_id':task['id'],'new_model_requests':0,'continuation':'separate explicit task control/revise_candidate; parent control still applies'}
    if action in {'growth.compare_preview','growth.compare'}:
        source_ready(s,c,obj);record=_compare(s,c,obj,data,app)
        # Preview identity is deterministic apart from storage ID/time.
        pin=digest({k:v for k,v in record.items() if k not in {'id','at','sha256'}})
        if preview:return {'comparison':record,'pin':pin,'new_model_requests':0}
        require(data.get('pin')==pin,'比较证据或输入已变化，请重新预览','conflict',409)
        _put(c,'growth_comparison:'+obj['id']+':'+record['id'],record)
        result=_save(s,c,obj,{**obj['content'],'comparisons':obj['content'].get('comparisons',[])+[record],
                  'evidence_level':record['evidence_level'] if record['adoption_eligible'] else 'observed_effect_unverified'})
        return view(s,result,c)
    require(action in {'growth.adopt','growth.preference','growth.reject','growth.revert'},'成长操作不支持')
    require(isinstance(data.get('reason'),str) and data['reason'].strip(),'决定需要具体范围与理由')
    mode=action.split('.')[1];policy=None
    if mode in {'adopt','preference'}:
        source_ready(s,c,obj)
        if mode=='adopt':
            ident=data.get('comparison_id');record=setting(c,'growth_comparison:'+obj['id']+':'+str(ident))
            require(record and record.get('comparison_engine_version')==2 and record['strategy_sha256']==identity(obj) and record['adoption_eligible'],'没有绑定当前策略版本的有效比较；可先有限试用，或明确保存未验证用户偏好','growth_evidence_required',409)
            # Re-open immutable attempt output and current source ACL at adoption.
            for ref in record.get('observation_refs',[]):
                s.assert_source_access(c,obj['project_id'],ref['id'])
                require(digest(s.get(ref['id'],ref['revision'],c))==ref['sha256'],'观察来源身份已变化','integrity',409)
            for e in record['evidence']:
                current=read(s,c,s.task(e['task_id'],c),e['attempt']);require(current==e,'采用证据已变化','integrity',409)
            if record.get('assessment'):
                from .growth_assessment import reread
                reread(s,c,obj,record['assessment'],app)
            task_profile=record['profile'];level=record['evidence_level'];evidence=record['sha256']
        else:
            task_profile=data.get('profile');require(isinstance(task_profile,dict) and set(task_profile)=={'kind','output','cycle_role'} and task_profile['kind']=='research' and task_profile['output'] in {'note','report','paper','slides','poster','diagram'},'用户偏好需明确科研任务种类、产出类型和角色')
            level='user_preference_effects_unverified';evidence=None
        require(task_profile.get('cycle_role') not in {'reviewer','final_reviewer'},'独立科研首评不自动注入已采用策略；此角色只能使用显式单任务指导试用','conflict',409)
        from .compatibility import require_features
        require_features(c,[FEATURE,'reviewed_growth_comparison_v2']);policy={'status':mode,'growth_id':obj['id'],'strategy_revision':obj['revision'],'strategy_sha256':identity(obj),'instruction':obj['content']['candidate'],
            'comparison_engine_version':2,'profile':task_profile,'evidence_level':level,'evidence_scope':copy.deepcopy(obj['content'].get('comparison_protocol')),'comparison_sha256':evidence,'reason':data['reason'],'at':now(),'scientific_approval':False}
    else:policy={'status':mode,'growth_id':obj['id'],'at':now(),'reason':data['reason']}
    old=setting(c,'growth_policy:'+obj['id']);_put(c,'growth_policy:'+obj['id'],policy)
    result=_save(s,c,obj,{**obj['content'],'status':mode,'decision_reason':data['reason'],'decision_history':obj['content'].get('decision_history',[])+[{'previous':old,'policy':policy}],
        'evidence_level':policy.get('evidence_level',obj['content'].get('evidence_level','effects_unverified'))})
    return view(s,result,c)
