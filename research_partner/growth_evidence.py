"""Immutable per-attempt observations for bounded strategy comparisons.

An output receipt proves exposure and a specific structural outcome, not better
science or causal attribution. Older attempts without this capture stay partial.
"""
import copy
import json
from .store import Problem,require,digest,encoded,now


def setting(c,key):
    row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None


def profile(payload):
    context=payload.get('context',{})
    return {'kind':payload.get('kind'),'output':context.get('output'),'cycle_role':payload.get('cycle_role')}


def design(payload):
    """Complete payload, not a scientific-field allowlist."""
    return copy.deepcopy(payload)


def differences(a,b,path='$'):
    if isinstance(a,dict) and isinstance(b,dict):
        result=[]
        for key in sorted(set(a)|set(b)):
            if key not in a or key not in b:result.append({'path':path+'.'+key,'baseline':a.get(key),'treatment':b.get(key),'baseline_present':key in a,'treatment_present':key in b})
            else:result.extend(differences(a[key],b[key],path+'.'+key))
        return result
    if a!=b:return [{'path':path,'baseline':a,'treatment':b}]
    return []


def input_comparison(a,b,exposure):
    if 'full_inputs' not in a or 'full_inputs' not in b:
        return {'complete':False,'matched':False,'differences':[],'limits':'Older attempt lacks full model input capture; legacy design hash is insufficient.'}
    left=copy.deepcopy(a['full_inputs']);right=copy.deepcopy(b['full_inputs']);removed=[]
    if exposure:
        matches=[g for g in right['guidance'] if g['seq']==exposure['guidance_seq']]
        require(len(matches)==1 and matches[0]['data'].get('text')==exposure['instruction'],'策略指导原文与实际输入不一致','integrity',409)
        removed=[{'path':'$.guidance','seq':exposure['guidance_seq'],'sha256':digest(matches[0]),'reason':'exact evaluated intervention'}]
        right['guidance']=[g for g in right['guidance'] if g['seq']!=exposure['guidance_seq']]
    # These are event transport identities, never arbitrary content fields.
    for value in (left,right):
        value['guidance']=[{'data':g['data'],'actor':g['actor']} for g in value['guidance']]
    delta=differences(left,right)
    return {'complete':True,'matched':not delta,'baseline_full_sha256':a['full_inputs_sha256'],'treatment_full_sha256':b['full_inputs_sha256'],
            'baseline_comparison_sha256':digest(left),'treatment_comparison_sha256':digest(right),'differences':delta,'differences_sha256':digest(delta),
            'excluded':removed,'execution_identity_exclusions':['guidance event seq, object_id and created_at only; full event data/actor retained'],
            'limits':'Same-session history, nonrandom assignment and unobserved provider variability prevent a causal/general efficacy claim.'}


def bind_output(s,task,obj,candidate_sha):
    """Append a separate immutable publication receipt; never rewrite attempt."""
    with s.transaction() as c:
        s.assert_execution(c,task['id'],task.get('execution_token'))
        attempt=setting(c,f"growth_attempt:{task['id']}:{task['attempts']}")
        if not attempt:return # No backfilling a legacy generation.
        output={'task_id':task['id'],'attempt':task['attempts'],'attempt_sha256':attempt['sha256'],'raw_output_sha256':attempt['output']['sha256'],
                'object_id':obj['id'],'revision':obj['revision'],'source_sha256':digest(obj),'candidate_sha256':candidate_sha}
        key=f"growth_output:{task['id']}:{task['attempts']}";old=setting(c,key)
        require(old is None or old==output,'执行产物绑定不能覆盖','integrity',409)
        if old is None:
            c.execute('INSERT INTO kv VALUES(?,?)',(key,encoded(output)));s.event(c,'growth.output_bound',task['id'],output,'runtime')


def output(s,c,task,attempt):
    record=setting(c,f"growth_output:{task['id']}:{attempt}")
    if not record:return None
    captured=read(s,c,task,attempt)
    require(captured.get('sha256')==record['attempt_sha256'] and captured['output']['sha256']==record['raw_output_sha256'],'产物与执行身份不一致','integrity',409)
    s.assert_source_access(c,task['project_id'],record['object_id']);obj=s.get(record['object_id'],record['revision'],c)
    require(digest(obj)==record['source_sha256'],'采用输出修订身份已变化','integrity',409)
    return copy.deepcopy(record)


def capture(app,task,result,inputs,validation,full_inputs):
    """Called on an actual provider return, before candidate publication."""
    s=app.store;ident=task['id'];attempt=task['attempts'];raw=result['text'].encode()
    with s.transaction() as c:
        s.assert_execution(c,ident,task.get('execution_token'))
        from .compatibility import require_features
        require_features(c,['bounded_growth_evidence_v1','reviewed_growth_comparison_v2'])
        old=setting(c,f'growth_attempt:{ident}:{attempt}')
        require(old is None,'此执行尝试已记录输出；不覆盖比较证据','integrity',409)
        asset=s.add_asset(raw,'attempt-'+ident+'-'+str(attempt)+'.txt','text/plain',{'project_id':task['project_id'],'task_id':ident,'growth_attempt':attempt},connection=c)
        guidance=[]
        for seq in inputs['guidance']:
            row=c.execute("SELECT * FROM events WHERE seq=? AND object_id=? AND kind='task.guidance'",(seq,ident)).fetchone()
            require(row,'尝试输入指导缺失','integrity',409);event=s.unpack(row)
            guidance.append({'seq':seq,'text':event['data'].get('text'),'source_reference':event['data'].get('source_reference'),'at':event['created_at']})
        trials=[json.loads(row[0]) for row in c.execute('SELECT value FROM kv WHERE key LIKE ?',('growth_trial:'+ident+':%',))]
        trials=[t for t in trials if t['guidance_seq'] in inputs['guidance']]
        record={'version':2,'task_id':ident,'attempt':attempt,'project_id':task['project_id'],'payload_sha256':digest(task['payload']),
                'payload':copy.deepcopy(task['payload']),'profile':profile(task['payload']),'design_sha256':digest(design(task['payload'])),
                'input_snapshot':copy.deepcopy(inputs),'guidance':guidance,'trials':trials,
                'full_inputs':copy.deepcopy(full_inputs),'full_inputs_sha256':digest(full_inputs),
                'output':{'sha256':asset['sha'],'asset_sha256':asset['sha'],'bytes':len(raw)},
                'validation':validation,'provider':copy.deepcopy(result['receipt']),'implementation':app.loaded_implementation['digest'],
                'recorded_at':now(),'identity_status':'captured_provider_return','scientific_approval':False}
        record['sha256']=digest(record)
        c.execute('INSERT INTO kv VALUES(?,?)',(f'growth_attempt:{ident}:{attempt}',encoded(record)))
        s.event(c,'growth.attempt_captured',ident,{'attempt':attempt,'record_sha256':record['sha256'],'output_sha256':asset['sha'],'validation':validation},'runtime')


def read(s,c,task,attempt):
    require(type(attempt) is int and 1<=attempt<=task['attempts'],'需要已执行的具体 attempt')
    record=setting(c,f"growth_attempt:{task['id']}:{attempt}")
    if not record:
        return {'task_id':task['id'],'attempt':attempt,'project_id':task['project_id'],'identity_status':'legacy_attempt_not_captured',
                'payload_sha256':digest(task['payload']),'profile':profile(task['payload']),'current_task_status':task['status'],
                'limits':'Historical task counters alone do not bind this attempt input, strategy exposure or output. Import a labelled retrospective observation; do not infer a prospective trial.'}
    require(record['task_id']==task['id'] and record['attempt']==attempt and record['project_id']==task['project_id']
            and record['sha256']==digest({k:v for k,v in record.items() if k!='sha256'}),'执行尝试证据身份不一致','integrity',409)
    if 'full_inputs' in record:require(digest(record['full_inputs'])==record['full_inputs_sha256'],'完整输入哈希不一致','integrity',409)
    s.assert_material_access(c,record['payload'])
    asset=s.asset(record['output']['asset_sha256'],c);raw=(s.blobs/asset['sha']).read_bytes()
    require(asset['metadata'].get('project_id')==task['project_id'] or task['project_id'] in asset['metadata'].get('projects',[]),'无权读取此尝试输出','forbidden',403)
    require(digest(raw)==record['output']['sha256'] and len(raw)==record['output']['bytes'],'尝试输出资产已损坏','integrity',409)
    return copy.deepcopy(record)
