"""Version-bound paired method assessments, never automatic scientific approval."""
import copy
import math
from research_partner.storage.store import Problem,require,digest,uid,now,encoded
from research_partner.domains.evidence.evidence import setting,read,output,input_comparison

FEATURE='reviewed_growth_comparison_v2'


def protocol(value):
    if value is None:return None
    require(isinstance(value,dict) and value.get('measure')=='reviewed_method_outcome','非结构比较需明确 reviewed_method_outcome 协议')
    require(value.get('comparison_design') in {'matched_inputs','related_tasks_observational'},'请明确同输入或相关任务观察性比较')
    for key in ['domain_scope','outcome_definition','limitations']:
        require(isinstance(value.get(key),str) and value[key].strip(),f'评价协议缺少 {key}')
    criteria=value.get('criteria');require(isinstance(criteria,list) and 1<=len(criteria)<=8,'需要 1–8 项明确评价准则')
    ids=[]
    for item in criteria:
        require(isinstance(item,dict) and all(isinstance(item.get(k),str) and item[k].strip() for k in ['id','definition','unit']),'准则需要 ID、定义与单位')
        require(item.get('kind') in {'qualitative','scored_review','provider_bill_usd'},'评价类型不支持')
        require(item.get('direction') in ({'review_judgment'} if item['kind']=='qualitative' else {'lower','higher'}),'改进方向与指标类型不符')
        if item['kind']=='provider_bill_usd':require(item['unit']=='USD','真实账单只支持 USD 原始单位')
        ids.append(item['id'])
    require(len(ids)==len(set(ids)),'评价准则 ID 重复')
    return copy.deepcopy(value)


def _ref(obj):return {'id':obj['id'],'revision':obj['revision'],'sha256':digest(obj)}


def _source(s,c,project,ref):
    require(isinstance(ref,dict) and isinstance(ref.get('id'),str) and type(ref.get('revision')) is int,'需要明确成果 ID 和修订')
    s.assert_source_access(c,project,ref['id']);obj=s.get(ref['id'],ref['revision'],c)
    if ref.get('sha256'):require(ref['sha256']==digest(obj),'来源哈希与指定修订不符','integrity',409)
    return obj


def review_evidence(s,c,project,refs):
    """Read exact existing output/review contracts, including legacy records."""
    require(isinstance(refs,list) and 1<=len(refs)<=2,'读取 1–2 项明确成果版本')
    result=[]
    for ref in refs:
        obj=_source(s,c,project,ref);records=setting(c,'reviews:'+obj['id']+':'+str(obj['revision'])) or [];reviews=[]
        for record in records:
            require(record.get('source_sha256')==digest(obj),'审查记录未绑定此输出原文','integrity',409)
            item={'record':record,'artifact':None,'review_task':None}
            if record.get('review_object_id'):
                report=_source(s,c,project,{'id':record['review_object_id'],'revision':record['review_revision'],'sha256':record['review_source_sha256']})
                item['artifact']={'reference':_ref(report),'title':report['title'],'content':copy.deepcopy(report['content'])}
            if record.get('review_task_id'):
                task=s.task(record['review_task_id'],c);require(task['project_id']==project,'审阅执行来源无权读取','forbidden',403)
                candidate=task['result'].get('cycle_candidate',{})
                require(candidate.get('candidate_sha256')==record.get('review_candidate_sha256'),'审阅任务候选身份不符','integrity',409)
                s.assert_material_access(c,task['payload'])
                item['review_task']={'id':task['id'],'role':task['payload'].get('cycle_role'),'status':task['status'],'candidate_sha256':candidate['candidate_sha256'],'contract':candidate.get('cycle_contract'),'provider':task['result'].get('provider')}
            reviews.append(item)
        result.append({'output':_ref(obj),'title':obj['title'],'reviews':reviews,'does_not_prove_strategy_effect':True})
    return {'outputs':result,'scientific_approval':False,'growth_adoption_eligible':False,'scope':'Exact historical output/review binding only; no reconstruction of missing past trial inputs.'}


def packet(s,c,g,data):
    from research_partner.domains.evidence.growth import identity
    from research_partner.domains.collaboration.resolver import evidence_projection
    p=protocol(g['content'].get('comparison_protocol'));require(p,'此候选尚无非结构评价协议')
    refs=[data.get('baseline'),data.get('treatment')]
    require(all(isinstance(r,dict) and set(r)=={'task_id','attempt'} for r in refs) and refs[0]!=refs[1],'请指定两侧不同 task@attempt')
    tasks=[s.task(r['task_id'],c) for r in refs]
    require(all(t['project_id']==g['project_id'] and t['status'] in {'generated','review','deliverable','failed'} for t in tasks),'成果尚未形成或不属于当前项目','forbidden',403)
    attempts=[read(s,c,t,r['attempt']) for t,r in zip(tasks,refs)]
    bindings=[output(s,c,t,r['attempt']) for t,r in zip(tasks,refs)]
    require(all(bindings),'此历史尝试缺少不可变 task@attempt→输出绑定；只能回顾读取已有成果/审阅','growth_evidence_required',409)
    require(all(a.get('full_inputs') for a in attempts),'缺少完整实际输入捕获；不能补写历史试用','growth_evidence_required',409)
    matches=[t for t in attempts[1]['trials'] if t['growth_id']==g['id'] and t['strategy_sha256']==identity(g)]
    exposure=matches[-1] if matches else None
    compare=input_comparison(attempts[0],attempts[1],exposure)
    scientific=[]
    for binding,attempt in zip(bindings,attempts):
        obj=s.get(binding['object_id'],binding['revision'],c);projected=evidence_projection(obj)
        scientific.append({'binding':binding,'scientific_source':projected,'actual_bill_usd':attempt['provider'].get('actual_bill_usd')})
    value={'version':1,'growth_id':g['id'],'strategy_sha256':identity(g),'protocol':p,'protocol_sha256':digest(p),
           'baseline':refs[0],'treatment':refs[1],'outputs':scientific,'input_comparison':compare,
           'scope':'Paired outcome assessment. Candidate instruction, author hypothesis/feedback/self-rating and previous review verdicts are not supplied. Typed exclusions preserve full-source hashes; untyped prose is not automatically scrubbed.',
           'inference_limits':['Nonrandom assignment, prior/session history and provider variability remain.','A scoped working hypothesis is not scientific approval or general efficacy.']}
    # Reviewers get scientific outputs and comparison identity, not complete
    # working prompts containing author strategy text or self-assessments.
    value['review_packet']={k:copy.deepcopy(value[k]) for k in ['version','protocol','protocol_sha256','outputs','scope','inference_limits']}
    value['review_packet']['input_comparison']={k:compare[k] for k in ['matched','baseline_full_sha256','treatment_full_sha256','differences_sha256']}
    value['review_packet']['input_difference_paths']=[d['path'] for d in compare['differences']]
    value['review_packet']['strategy_sha256']=identity(g)
    value['review_packet_sha256']=digest(value['review_packet']);value['pin']=digest(value)
    return value


def _at(value,path):
    require(isinstance(path,str) and path.startswith('/content/'),'引文定位须指向科学正文 /content/...')
    for token in path.split('/')[1:]:
        token=token.replace('~1','/').replace('~0','~')
        try:value=value[int(token)] if isinstance(value,list) else value[token]
        except (KeyError,IndexError,ValueError,TypeError):raise Problem('引文定位不在采用的科学正文','invalid',400)
    return value


def _quotes(source,values):
    require(isinstance(values,list) and values,'每侧评价必须定位实际科学正文证据')
    for item in values:
        require(isinstance(item,dict) and isinstance(item.get('quote'),str) and len(item['quote'].strip())>=4,'引文必须为实际非空片段')
        text=_at(source,item.get('path'));require(isinstance(text,str) and item['quote'] in text,'引文与采用的科学正文不符，不能引用作者自评替代结果','integrity',409)


def verify(s,c,g,pack,data,scope,*,execution=None):
    report=_source(s,c,g['project_id'],data.get('assessment_ref'));require(report['kind'] in {'report','note'},'配对评估须为可读报告或笔记')
    require(report['id'] not in {x['binding']['object_id'] for x in pack['outputs']},'作者的被评输出不能同时作为其独立评价','forbidden',403)
    if execution is not None:
        from research_partner.domains.evidence.execution import body as execution_body
        require(report['metadata'].get('task_id')==execution['task_id'],'评估执行归属不符','integrity',409)
        provenance=data['evaluator'];body=execution_body(report)
    else:
        require(not report['metadata'].get('task_id'),'自动生成的评估不能冒充外部人工判断；请用具有独立执行来源的路径','forbidden',403)
        require(scope is None,'外部人工比较登记需要空间所有者明确操作','authorization_required',403)
        provenance=data.get('evaluator');require(isinstance(provenance,dict) and provenance.get('mode')=='owner_registered_external_manual','需明确外部/人工评价登记来源，不能用作者自评或 approved 代替')
        require(all(isinstance(provenance.get(k),str) and provenance[k].strip() for k in ['identity','role','authorization_reference','scope']),'评价者、角色、授权来源与评价范围须明确')
        require(provenance['role'] in {'external_human_reviewer','external_independent_review_context','space_owner_manual_case_assessor'},'作者或任务执行者不能登记为独立比较来源')
        body=report['content'].get('growth_assessment');require(isinstance(body,dict),'评估报告缺少可审查的 growth_assessment 配对合同')
    require(body.get('review_packet_sha256')==pack['review_packet_sha256'] and body.get('protocol_sha256')==pack['protocol_sha256'],'评估不属于此冻结科学包/协议','conflict',409)
    require(body.get('strategy_sha256')==pack['strategy_sha256'] and body.get('baseline')==pack['outputs'][0]['binding'] and body.get('treatment')==pack['outputs'][1]['binding'],'评估未精确绑定两侧 task@attempt 与输出版本','conflict',409)
    require(body.get('input_differences_sha256')==pack['input_comparison']['differences_sha256'],'评价没有绑定完整输入差异','conflict',409)
    require(body.get('comparison_design')==pack['protocol']['comparison_design'],'评价设计与试用前协议不同','conflict',409)
    require(isinstance(body.get('comparability'),str) and body['comparability'].strip() and isinstance(body.get('limitations'),list) and body['limitations'] and all(isinstance(x,str) and x.strip() for x in body['limitations']),'需要实际相关性判断与未解决限制')
    differences=pack['input_comparison']['differences'];addressed=body.get('input_difference_assessments',[])
    require(isinstance(addressed,list) and {x.get('path') for x in addressed if isinstance(x,dict)}=={x['path'] for x in differences} and all(isinstance(x.get('scope_limit'),str) and x['scope_limit'].strip() for x in addressed),'需逐项解释完整输入差异对比较范围的限制')
    ids=data.get('review_ids');require(isinstance(ids,list) and len(ids)==2,'需要分别绑定两侧输出的真实 review.record 身份')
    records=[]
    for binding,ident in zip([x['binding'] for x in pack['outputs']],ids):
        candidates=setting(c,'reviews:'+binding['object_id']+':'+str(binding['revision'])) or []
        record=next((r for r in candidates if r['identity']==ident),None)
        require(record and record.get('source_sha256')==binding['source_sha256'] and record.get('review_object_id')==report['id'] and record.get('review_revision')==report['revision'] and record.get('review_source_sha256')==digest(report),'不是同一份配对评估对精确两侧输出的审查绑定','integrity',409)
        records.append(record)
    outcomes=body.get('outcomes');criteria=pack['protocol']['criteria'];require(isinstance(outcomes,list) and len(outcomes)==len(criteria) and {x.get('criterion_id') for x in outcomes}=={x['id'] for x in criteria},'评价项须完整对应试用前准则')
    issues=[];judgments=[]
    for criterion in criteria:
        row=next(x for x in outcomes if x['criterion_id']==criterion['id']);require(isinstance(row.get('rationale'),str) and row['rationale'].strip(),'评价须有实质解释')
        sides=[row.get('baseline'),row.get('treatment')];require(all(isinstance(v,dict) and isinstance(v.get('explanation'),str) and v['explanation'].strip() for v in sides),'两侧需分别保存观察与解释')
        if criterion['kind']=='provider_bill_usd':
            bills=[]
            for ref,side in zip([pack['baseline'],pack['treatment']],sides):
                attempt=read(s,c,s.task(ref['task_id'],c),ref['attempt']);bill=attempt['provider'].get('actual_bill_usd');bills.append(bill)
                require(side.get('value')==bill,'费用评价不能替换真实未知账单','integrity',409)
                require(side.get('denominator')==1 and side.get('unit')=='USD','真实账单的比较分母必须为每次原始账单，单位 USD')
            if any(x is None for x in bills):issues.append('Actual bill is unknown; no cost-effect claim.');judgments.append('inconclusive');continue
        else:
            for source,side in zip(pack['outputs'],sides):_quotes(source['scientific_source'],side.get('evidence'))
        judgment=row.get('judgment');require(judgment in {'improved','unchanged','worse','mixed','inconclusive'},'评价判断不支持')
        if criterion['kind']!='qualitative':
            for side in sides:
                require(type(side.get('value')) in (int,float) and math.isfinite(side['value']) and type(side.get('denominator')) in (int,float) and math.isfinite(side['denominator']) and side['denominator']>0,'数值评价需有限实际值和正分母')
                require(side.get('unit')==criterion['unit'],'数值评价单位与协议不同')
            a,b=[v['value']/v['denominator'] for v in sides]
            expected='unchanged' if a==b else 'improved' if (b<a)==(criterion['direction']=='lower') else 'worse'
            require(judgment==expected,'评价判断与已登记数值/方向不符；未自动替用户改评价','conflict',409)
        judgments.append(judgment)
    if not pack['input_comparison']['matched'] and pack['protocol']['comparison_design']=='matched_inputs':issues.append('Frozen protocol requires matching inputs; complete actual inputs differ.')
    supported='improved' in judgments and all(x in {'improved','unchanged'} for x in judgments) and not issues
    return {'assessment_ref':_ref(report),'review_records':records,'evaluator':copy.deepcopy(provenance),'execution':execution,'source_strength':execution['independence_scope'] if execution else 'explicit owner registration of a manual/external assessment; evaluator identity and independence are declared, not independently authenticated',
            'body_sha256':digest(body),'packet_pin':pack['pin'],'review_packet_sha256':pack['review_packet_sha256'],'protocol_sha256':pack['protocol_sha256'],
            'baseline':pack['baseline'],'treatment':pack['treatment'],'output_bindings':[x['binding'] for x in pack['outputs']],
            'judgments':judgments,'supported':supported,'issues':issues,'comparability':body['comparability'],'limitations':body['limitations'],
            'scientific_approval':False,'causal_effect':False,'general_effectiveness':False}


def registered(s,c,g,data,scope,preview):
    pack=packet(s,c,g,data);assessment=verify(s,c,g,pack,data,scope)
    pin=digest(assessment)
    if preview:return {'packet':pack,'assessment':assessment,'pin':pin,'new_model_requests':0}
    require(data.get('pin')==pin,'评价或输出在预览后变化，请重新读取','conflict',409)
    ident=uid('ASSESS');record={**assessment,'id':ident,'growth_id':g['id'],'strategy_sha256':pack['strategy_sha256'],'at':now()};record['sha256']=digest(record)
    c.execute('INSERT INTO kv VALUES(?,?)',('growth_assessment:'+g['id']+':'+ident,encoded(record)))
    s.event(c,'growth.assessment_registered',g['id'],record,'owner')
    return record


def reread(s,c,g,record,app=None):
    data={'baseline':record['baseline'],'treatment':record['treatment'],'assessment_ref':record['assessment_ref'],'review_ids':[r['identity'] for r in record['review_records']],'evaluator':record['evaluator']}
    execution=None
    if record.get('execution'):
        require(app,'执行绑定复核缺少当前提供者配置','integrity',409)
        from research_partner.domains.evidence.execution import execution as verify_execution
        _,_,_,_,execution=verify_execution(app,c,g,{'assessment_task_id':record['execution']['task_id'],'attempt':record['execution']['attempt']})
        require(execution==record['execution'],'独立执行来源已变化','integrity',409)
    value=verify(s,c,g,packet(s,c,g,data),data,None,execution=execution)
    require(all((record.get(k) if k=='execution' else record[k])==v for k,v in value.items()),'配对评价证据已变化或访问被撤回','integrity',409)
    return value


def create(s,c,g,data,scope,preview):
    """Ordinary note + two real review records, atomically; previews roll back."""
    require(scope is None,'人工比较登记需要空间所有者明确操作','authorization_required',403)
    pack=packet(s,c,g,data);body=data.get('assessment_body');title=data.get('title')
    require(isinstance(title,str) and title.strip() and isinstance(body,dict),'需要可读评估标题和完整配对正文')
    verdicts=data.get('verdicts');require(isinstance(verdicts,list) and len(verdicts)==2 and all(v in {'needs_revision','usable_for_discussion','reviewed_with_limits'} for v in verdicts),'两侧均须有明确且有限的审阅判断')
    evaluator=data.get('evaluator');pin=digest({'packet_pin':pack['pin'],'body':body,'title':title,'evaluator':evaluator,'verdicts':verdicts})
    if not preview:require(data.get('pin')==pin,'评估草稿或源数据在预览后已变化','conflict',409)
    report=s.create('note',title,g['project_id'],{'blocks':[{'id':'assessment-scope','kind':'paragraph','text':body.get('comparability','')},{'id':'assessment-limits','kind':'paragraph','text':'\n'.join(body.get('limitations',[]))}],'growth_assessment':body},
                    {'assessment_origin':'explicit owner registered manual/external comparison','evaluator':evaluator,'scientific_approval':False},connection=c)
    records=[]
    for binding,verdict in zip([x['binding'] for x in pack['outputs']],verdicts):
        records.append(s.record_review(binding['object_id'],binding['revision'],{'review_object_id':report['id'],'review_revision':report['revision'],'review_source_sha256':digest(report),
                'verdict':verdict,'scope':evaluator.get('scope','') if isinstance(evaluator,dict) else '',
                'summary':body.get('comparability',''),'reviewer_reference':evaluator.get('identity','') if isinstance(evaluator,dict) else ''},connection=c))
    assessment=verify(s,c,g,pack,{**data,'assessment_ref':_ref(report),'review_ids':[r['identity'] for r in records]},scope)
    if preview:return {'pin':pin,'saved':False,'new_model_requests':0,'assessment_body':body,'assessment':assessment,'scope':'Preview only; note/review rows will be rolled back. Explicit next action creates them.'}
    ident=uid('ASSESS');record={**assessment,'id':ident,'growth_id':g['id'],'strategy_sha256':pack['strategy_sha256'],'at':now()};record['sha256']=digest(record)
    c.execute('INSERT INTO kv VALUES(?,?)',('growth_assessment:'+g['id']+':'+ident,encoded(record)));s.event(c,'growth.assessment_registered',g['id'],record,'owner')
    return record
