"""Finite project-management grants and reviewed, transactional native proposals.

No model receives a credential or generic application dispatcher. Both native
routes request typed lookups/operations in a candidate; the product executes the
lookups and publishes an immutable review. Only an explicit digest-bound apply
mutates projects. This is distinct from scientific/graph task permissions.
"""
from __future__ import annotations
import copy
import json
import math
import re
from .store import Problem, require, digest, encoded, now, uid
from .authentication import token_fingerprint as token_hash

FEATURE = 'reviewed_project_management_v2'
KIND = 'project_management'
ACTIONS = {'rename', 'set_category', 'archive', 'restore'}
KEY = 'project_management:'


def setting(c, key, default=None):
    row = c.execute('SELECT value FROM kv WHERE key=?', (KEY + key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(c, key, value):
    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY + key, encoded(value)))


def authority_scope(app, principal):
    """Resolve current issuer rights, not the scope cached at submission."""
    if principal.get('kind') == 'local_operator': return None
    if principal.get('kind') == 'loopback':
        require(not app.config.get('access_token_file') and not app.config.get('clients'), '本地免登录授权已撤回', 'forbidden', 403)
        return None
    fp = principal.get('credential_sha256')
    require(principal.get('kind') == 'credential' and isinstance(fp, str), '项目管理需要可核对的操作者身份', 'forbidden', 403)
    if app.config.get('access_token_file') and token_hash(app.config['access_token_file']) == fp: return None
    for client in app.config.get('clients', []):
        if token_hash(client.get('token_file', '')) == fp: return client.get('projects', [])
    raise Problem('项目管理原授权凭据已撤回；需要新的有限委托', 'forbidden', 403)


def actor(principal):
    if principal.get('kind') == 'credential': return 'user:credential:' + principal['credential_sha256'][:16]
    return 'user:' + principal['kind']


def project(app, ident, scope, c):
    obj = app.store.get(ident, connection=c)
    require(obj['kind'] == 'project', '管理目标必须是项目', 'forbidden', 403)
    require(scope is None or ident in scope, '所选项目不在当前可管理范围', 'forbidden', 403)
    return obj


def summary(obj):
    # Hash covers the full canonical object; the capsule receives no scientific body.
    require(isinstance(obj['metadata'].get('aliases', []),list) and all(isinstance(a,str) for a in obj['metadata'].get('aliases', [])) and isinstance(obj['metadata'].get('category',''),str), '项目现有别名/分类格式无效，请先修复项目设置')
    return {'id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj),
            'title': obj['title'], 'aliases': copy.deepcopy(obj['metadata'].get('aliases', [])),
            'category': obj['metadata'].get('category', ''), 'archived': obj['archived'], 'writable': True}


def task_access(app, task, scope, c):
    require(task['payload'].get('kind') == KIND, '原任务没有项目管理合同', 'forbidden', 403)
    public = task['payload']['context'].get('project_management', {})
    require(public.get('version') == 1, '项目管理合同缺失', 'forbidden', 403)
    require(scope is None or not public.get('allow_create'), '创建项目的管理任务仅所有者可见', 'forbidden', 403)
    for ident in public.get('project_ids', []): project(app, ident, scope, c)
    return public


def guard(app, task, c):
    public = task_access(app, task, None, c)
    grant = setting(c, 'grant:' + task['id'])
    require(grant and grant.get('state') == 'active' and grant['contract'] == public
            and digest(public) == task['payload'].get('management_contract_sha256'),
            '项目管理授权已撤回或合同不符', 'forbidden', 403)
    current_scope = authority_scope(app, grant['principal'])
    require(not public['allow_create'] or current_scope is None, '创建项目授权已撤回', 'forbidden', 403)
    for ident in public['project_ids']: project(app, ident, current_scope, c)
    return grant


def submit(app, data, scope, principal):
    s = app.store
    require(set(data) <= {'action','request','project_ids','operations','allow_create','provider_id','budget','request_key'}, '项目管理委托含未支持字段')
    request = data.get('request')
    require(isinstance(request, str) and 0 < len(request.strip()) <= 4000, '请描述项目管理目的（最多4000字）')
    ids = data.get('project_ids', [])
    ops = data.get('operations', [])
    require(isinstance(ids, list) and len(ids) <= 24 and all(isinstance(i, str) for i in ids) and len(ids) == len(set(ids)), '请选择至多24个明确项目')
    require(isinstance(ops, list) and all(isinstance(o, str) and o in ACTIONS for o in ops) and len(ops) == len(set(ops)), '请选择允许的项目操作')
    create = data.get('allow_create', False)
    require(type(create) is bool and (not create or scope is None), '创建项目需当前所有者授权', 'forbidden', 403)
    require(ids or create, '请选择项目，或明确允许创建新项目')
    budget = data.get('budget', {'max_model_calls': 4, 'timeout_seconds': 300})
    require(isinstance(budget, dict) and set(budget) == {'max_model_calls','timeout_seconds'} and type(budget.get('max_model_calls')) is int and 1 <= budget['max_model_calls'] <= 20
            and type(budget.get('timeout_seconds')) in (int,float) and math.isfinite(budget['timeout_seconds']) and 0 < budget['timeout_seconds'] <= 900, '任务需要有限请求次数（1–20）和时限（不超过900秒）')
    provider_id = data.get('provider_id') or app.config.get('default_provider')
    require(app.config.get('providers', {}).get(provider_id, {}).get('route') in {'codex','deepseek_harness'}, '请选择已配置的原生模型路线', 'provider_missing', 503)
    key = data.get('request_key') or uid('REQUEST')
    require(isinstance(key, str) and 0 < len(key) <= 180, '需要有限请求标识')
    input_spec = {k:copy.deepcopy(v) for k,v in {'request':request.strip(),'project_ids':sorted(ids),'operations':sorted(ops),'allow_create':create,'budget':budget,'provider_id':provider_id,'principal':principal}.items()}
    with s.transaction() as c:
        current_scope = authority_scope(app, principal)
        require(not create or current_scope is None, '创建项目需当前所有者授权', 'forbidden', 403)
        for ident in ids:
            project(app, ident, scope, c); project(app, ident, current_scope, c)
        previous = setting(c, 'submission:' + key)
        if previous:
            require(previous['input_sha256'] == digest(input_spec), '重复请求内容或授权不同', 'idempotency_conflict', 409)
            task = s.task(previous['task_id'], c); task_access(app, task, scope, c)
            return task
        catalog = [summary(project(app, ident, scope, c)) for ident in sorted(ids)]
        public = {'version':1,'project_ids':sorted(ids),'operations':sorted(ops),'allow_create':create,
                  'max_creates':4 if create else 0,'catalog':catalog,'catalog_sha256':digest(catalog),
                  'lookup':{'fields':['any','id','title','alias','category'],'archived':['all','active','archived'],
                            'semantics':'case-insensitive substring against frozen selected projects; actual product lookup recorded at candidate publication'},
                  'apply':'explicit digest-bound human review; current issuer and applier ACL plus exact revision/hash checked atomically'}
        payload = {'kind':KIND,'project_id':sorted(ids)[0] if ids else None,'request':request.strip(),'provider_id':provider_id,
                   'budget':budget,'depends_on':[],'authorization':{},'priority':0,'target_id':None,
                   'management_contract_sha256':digest(public),
                   'context':{'output':KIND,'materials':[],'project_management':public,
                              'constraints':'Only named project metadata operations. No scientific contents, permissions, task control, graph edits or external tools. Archive only changes visibility.'}}
        require(len(encoded(payload).encode())<=48000,'项目管理目录超过有限上下文，请缩小项目选择；不会静默截断','context_limit',413)
        from .compatibility import require_features
        require_features(c, [FEATURE,'bounded_growth_evidence_v1','reviewed_growth_comparison_v2'])
        task = s.submit(payload, 'project-management:' + key, connection=c)
        put(c, 'grant:' + task['id'], {'state':'active','principal':principal,'issuer':actor(principal),'contract':public,'at':now()})
        put(c, 'submission:' + key, {'input_sha256':digest(input_spec),'task_id':task['id']})
        s.event(c, 'project_management.granted', task['id'], {'contract_sha256':digest(public),'operations':ops,'project_ids':ids,'allow_create':create}, actor(principal))
    if app.runner: app.runner.wake()
    return task


def schema(task):
    require(task and task['payload'].get('kind') == KIND and task['payload'].get('management_contract_sha256'), '原任务没有项目管理授权', 'forbidden', 403)
    return '''Return exactly one JSON object: {"kind":"project_management","title":"readable proposal title","contract_sha256":"the supplied management_contract_sha256","lookups":[{"id":"local ASCII id","field":"any|id|title|alias|category","query":"search text","archived":"all|active|archived"}],"operations":[...],"explanation":"brief rationale and ambiguity/limits"}. At least one lookup or operation is required. These typed lookup requests are executed by the product on the frozen scoped catalog after this candidate, with task/proposer identity and recorded results; do not invent lookup results. At most 16 lookups and 16 operations. Each operation has unique ASCII id, op, reason. Create: {id,op:"create",title,category,description,reason}, only with allow_create, at most max_creates; do not invent target IDs. Other operations: {id,op:"rename"|"set_category"|"archive"|"restore",project_id,expected_revision,expected_sha256,reason} plus title ONLY for rename or category ONLY for set_category. Use exact frozen project revision/full sha256 for every operation, even multiple changes to the same project; the product applies those changes in listed order in one transaction. Only granted project IDs and operations. No ACL, graph, source, task or scientific fields. Preserve old names as aliases automatically; no deletion. Do not combine archive and restore in one candidate, or duplicate one action for a target; use a new finite request after applying a state change. If the request is ambiguous, return a lookup-only candidate explaining the ambiguity; never guess a target. Project changes need a visible explicit review/apply; candidate publication is not application or approval.''' + '\nmanagement_contract_sha256=' + task['payload']['management_contract_sha256']


def text(value, name, limit=500, empty=False):
    require(isinstance(value,str) and len(value)<=limit and (empty or value.strip()), '候选字段无效：'+name, 'invalid_model_output', 422)


def validate(candidate, task):
    schema(task)
    bad = lambda condition, message: require(condition, message, 'invalid_model_output', 422)
    bad(isinstance(candidate,dict) and set(candidate)=={'kind','title','contract_sha256','lookups','operations','explanation'}, '项目候选需要完整且仅限约定字段')
    bad(candidate['kind']==KIND and candidate['contract_sha256']==task['payload']['management_contract_sha256'], '项目候选合同身份不符')
    text(candidate['title'],'title',200);text(candidate['explanation'],'explanation',4000)
    public = task['payload']['context']['project_management']; catalog = {p['id']:p for p in public['catalog']}
    lookups, operations = candidate['lookups'], candidate['operations']
    bad(isinstance(lookups,list) and len(lookups)<=16 and isinstance(operations,list) and len(operations)<=16 and bool(lookups or operations),'项目候选需有限操作或检索')
    seen=set(); seen_ops=set(); archive_targets=set(); creates=0
    for item in lookups+operations:
        bad(isinstance(item,dict) and isinstance(item.get('id'),str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',item['id'])) and item['id'] not in seen, '操作/检索ID无效或重复');seen.add(item['id'])
    for q in lookups:
        bad(set(q)=={'id','field','query','archived'} and q['field'] in public['lookup']['fields'] and q['archived'] in public['lookup']['archived'], '检索字段或范围无效')
        text(q['query'],'query',200)
    for op in operations:
        action=op.get('op');bad(isinstance(action,str),'需要明确操作');text(op.get('reason'),'reason',1000)
        if action=='create':
            bad(public['allow_create'] and set(op)=={'id','op','title','category','description','reason'}, '创建项目未获授权或字段无效')
            creates+=1;bad(creates<=public['max_creates'], '创建数量超过有限授权')
            text(op['title'],'title',200);text(op['category'],'category',200,True);text(op['description'],'description',2000,True)
            continue
        bad(action in public['operations'], '操作不在项目管理授权范围')
        fields={'id','op','project_id','expected_revision','expected_sha256','reason'}|({'title'} if action=='rename' else {'category'} if action=='set_category' else set())
        bad(set(op)==fields, '项目操作包含未支持字段')
        bad(isinstance(op['project_id'],str) and op['project_id'] in catalog, '项目不在冻结授权范围')
        p=catalog[op['project_id']]
        bad(type(op['expected_revision']) is int and op['expected_revision']==p['revision'] and op['expected_sha256']==p['sha256'], '项目修订或哈希不是已读版本')
        key=(action,p['id']);bad(key not in seen_ops,'同一项目操作重复');seen_ops.add(key)
        if action=='rename':text(op['title'],'title',200)
        if action=='set_category':text(op['category'],'category',200,True)
        if action in {'archive','restore'}:
            bad(p['id'] not in archive_targets,'同一候选不能反复归档恢复');archive_targets.add(p['id'])
            bad(p['archived']==(action=='restore'),'项目归档状态与请求不符')
    return copy.deepcopy(candidate)


def lookup(catalog, query):
    results=[];needle=query['query'].casefold()
    for p in catalog:
        if query['archived']=='active' and p['archived']:continue
        if query['archived']=='archived' and not p['archived']:continue
        fields={'id':[p['id']],'title':[p['title']],'alias':p['aliases'],'category':[p['category']]}
        values=sum(fields.values(),[]) if query['field']=='any' else fields[query['field']]
        if any(needle in str(v).casefold() for v in values):results.append(copy.deepcopy(p))
    return {'query':copy.deepcopy(query),'results':results,'catalog_sha256':digest(catalog),'basis':'frozen scoped catalog; not live global search'}


def previews(candidate, public):
    current={p['id']:copy.deepcopy(p) for p in public['catalog']};rows=[]
    for op in candidate['operations']:
        if op['op']=='create':
            rows.append({'operation':copy.deepcopy(op),'before':None,'after':{'title':op['title'].strip(),'category':op['category'],'description':op['description'],'archived':False,'aliases':[]},'target':'new project: '+op['id']});continue
        before=copy.deepcopy(current[op['project_id']]);after=copy.deepcopy(before)
        if op['op']=='rename':
            after['title']=op['title'].strip()
            if before['title']!=after['title']:after['aliases']=list(dict.fromkeys(before['aliases']+[before['title']]))
        elif op['op']=='set_category':after['category']=op['category']
        else:after['archived']=op['op']=='archive'
        rows.append({'operation':copy.deepcopy(op),'before':before,'after':after,'target':op['project_id']});current[op['project_id']]=after
    return rows


def generation(store, task, c):
    model=next((step for step in task['steps'] if step['step_key']=='model'),None)
    require(model and model['status']=='done', '当前执行尚无成功候选；旧提案仅供审阅', 'proposal_superseded',409)
    inputs=store.execution_inputs(c,task['id'])
    require(model['data'].get('input_snapshot')==inputs, '指导或回答已变化；旧提案仅供审阅', 'proposal_superseded',409)
    return {'model_checkpoint_sha256':digest(model),'input_snapshot':inputs}


def assert_current_proposal(store, task, record, c):
    require(task['status']=='generated' and record['state']=='proposed', '当前任务不是已成功生成的待审候选；旧提案仅供审阅', 'proposal_superseded',409)
    pointer=task['result'].get('project_management',{})
    require(pointer.get('candidate_sha256')==record['candidate_sha256'] and pointer.get('proposal_sha256')==record['proposal_sha256'], '较新的提案已取代此候选；旧提案仅供审阅', 'proposal_superseded',409)
    require(record.get('generation')==generation(store,task,c), '执行或输入代次已变化；旧提案仅供审阅', 'proposal_superseded',409)


def publish(app, task, candidate, receipt, candidate_sha):
    """Runtime-only completion, reached after registered candidate validation."""
    s=app.store;candidate=validate(candidate,task)
    with s.transaction() as c:
        s.assert_execution(c,task['id'],task.get('execution_token'));grant=guard(app,task,c)
        from .compatibility import require_features
        require_features(c,[FEATURE])
        stored=s.task(task['id'],c);model=next((p for p in stored['steps'] if p['step_key']=='model'),None)
        require(model and model['status']=='done' and model['data']['sha256']==candidate_sha and model['data']['provider']==receipt,
                '项目提案缺少匹配的已完成模型检查点', 'integrity',409)
        require(receipt.get('route') in {'codex','deepseek_harness'} and isinstance(receipt.get('session_id'),str) and receipt['session_id'], '项目提案缺少原生会话身份', 'integrity',409)
        proposer={'role':'agent','provider_id':task['payload']['provider_id'],'route':receipt['route'],'session_id':receipt['session_id'],'task_id':task['id'],'candidate_sha256':candidate_sha}
        bound_generation=generation(s,stored,c)
        lookups=[{**lookup(grant['contract']['catalog'],q),'task_id':task['id'],'proposer':proposer} for q in candidate['lookups']]
        immutable={'version':2,'task_id':task['id'],'candidate':candidate,'candidate_sha256':candidate_sha,'proposer':proposer,'provider_receipt':receipt,
                   'contract_sha256':task['payload']['management_contract_sha256'],'lookups':lookups,'changes':previews(candidate,grant['contract']),
                   'generation':bound_generation}
        proposal_sha=digest(immutable)
        # Same candidate bytes can be returned in two explicitly requested
        # generations. Keep each immutable provenance/digest separately.
        history_key='proposal_revision:'+task['id']+':'+proposal_sha
        record=setting(c,history_key)
        if not record:
            record={**immutable,'proposal_sha256':proposal_sha,'state':'proposed','proposed_at':now()}
            put(c,history_key,record)
            for item in lookups:s.event(c,'project_management.lookup',task['id'],item,'agent:'+receipt['route']+':'+receipt['session_id'])
            s.event(c,'project_management.proposed',task['id'],{'proposal_sha256':record['proposal_sha256'],'candidate_sha256':candidate_sha,'proposer':proposer},'agent:'+receipt['route']+':'+receipt['session_id'])
        put(c,'proposal:'+task['id']+':'+candidate_sha,record)
        result={'project_management':{'candidate_sha256':candidate_sha,'proposal_sha256':record['proposal_sha256'],'state':record['state']},'provider':receipt}
        c.execute('UPDATE tasks SET status=?,result=?,error=NULL,updated_at=? WHERE id=?',('generated',encoded(result),now(),task['id']))
        s.event(c,'task.generated',task['id'],result,'runtime')
    return record


def proposal(app, data, scope, c):
    task=app.store.task(data.get('task_id'),c);task_access(app,task,scope,c)
    sha=data.get('candidate_sha256') or task['result'].get('project_management',{}).get('candidate_sha256')
    require(isinstance(sha,str) and re.fullmatch(r'[0-9a-f]{64}',sha), '项目候选尚未就绪','not_found',404)
    pin=data.get('proposal_sha256')
    require(pin is None or isinstance(pin,str) and re.fullmatch(r'[0-9a-f]{64}',pin),'项目提案摘要格式无效')
    record=setting(c,'proposal_revision:'+task['id']+':'+pin) if pin else None
    if record is None:record=setting(c,'proposal:'+task['id']+':'+sha)
    require(record and record['candidate_sha256']==sha,'项目提案不存在','not_found',404)
    require(pin is None or pin==record['proposal_sha256'],'项目提案摘要与历史记录不符','conflict',409)
    keys=('version','task_id','candidate','candidate_sha256','proposer','provider_receipt','contract_sha256','lookups','changes')
    immutable={k:record[k] for k in keys+(('generation',) if record['version']==2 else ())}
    require(record['proposal_sha256']==digest(immutable),'项目提案完整性不符','integrity',409)
    return task,record


def dispatch(app,data,scope,principal):
    action=data['action'];s=app.store
    principal=principal or {'kind':'local_operator'}
    require(scope is None or principal['kind']!='local_operator','受限调用必须提供可核对的认证身份','forbidden',403)
    if action=='project.management.submit':return submit(app,data,scope,principal)
    with s.transaction() as c:
        if action=='project.management.revoke':
            task=s.task(data.get('task_id'),c);task_access(app,task,scope,c);grant=setting(c,'grant:'+task['id'])
            require(scope is None or grant['principal']==principal,'只能撤回自己的项目管理授权','forbidden',403)
            grant.update(state='revoked',revoked_by=actor(principal),revoked_at=now());put(c,'grant:'+task['id'],grant)
            lease=c.execute('SELECT value FROM kv WHERE key=?',('execution:'+task['id'],)).fetchone()
            if lease:
                value=json.loads(lease[0]);value.update(state='revoked',revoked_at=now(),reason='project management grant revoked')
                c.execute('UPDATE kv SET value=? WHERE key=?',(encoded(value),'execution:'+task['id']))
            c.execute("UPDATE tasks SET status='cancelled',error=?,updated_at=? WHERE id=?",('项目管理授权已撤回；已应用历史保留',now(),task['id']))
            s.event(c,'project_management.revoked',task['id'],{'already_applied':task['status']=='deliverable'},actor(principal))
            result={'revoked':True,'task_id':task['id']}
        else:
            task,record=proposal(app,data,scope,c)
            if action=='project.management.view':
                available=True;blocked=None
                try:guard(app,task,c);assert_current_proposal(s,task,record,c)
                except Problem as error:available=False;blocked=str(error)
                return {**record,'authorization_active':available,'application_blocked_reason':blocked,'task_status':task['status'],'archive_notice':'归档仅改变可见性，不取消任务或撤销访问。'}
            require(action=='project.management.apply','项目管理操作不支持')
            # This is the review action: the operator saw this exact digest.
            require(data.get('approved') is True and data.get('proposal_sha256')==record['proposal_sha256'], '请核对具体提案后明确应用相同摘要','authorization_required',403)
            current_scope=authority_scope(app,principal)
            task_access(app,task,current_scope,c)
            # Already applied is a read-only idempotency receipt, not a new write
            # grant. Current caller access still applies after issuer revocation.
            if record['state']=='applied':return record
            guard(app,task,c)
            assert_current_proposal(s,task,record,c)
            validate(record['candidate'],task)
            touched={op['project_id'] for op in record['candidate']['operations'] if op['op']!='create'}
            catalog={p['id']:p for p in task['payload']['context']['project_management']['catalog']}
            current={}
            for ident in touched:
                obj=project(app,ident,scope,c);project(app,ident,current_scope,c)
                require(obj['revision']==catalog[ident]['revision'] and digest(obj)==catalog[ident]['sha256'], '项目在提案后已改变；旧候选保留，请重新委托','conflict',409)
                current[ident]=obj
            applied=[];applier=actor(principal)
            for op in record['candidate']['operations']:
                if op['op']=='create':
                    require(scope is None and current_scope is None,'创建项目需当前所有者权限','forbidden',403)
                    ident='PRJ-'+digest({'task':task['id'],'proposal':record['proposal_sha256'],'op':op['id']})[:24]
                    obj=s.create('project',op['title'],content={'description':op['description']},metadata={'category':op['category']},actor=applier,ident=ident,connection=c)
                    from .article_workspace import initialize_output
                    obj=initialize_output(s,c,obj,kind='paper')['project']
                else:
                    old=current[op['project_id']];kw={}
                    if op['op']=='rename':kw['title']=op['title'].strip()
                    elif op['op']=='set_category':kw['metadata']={**old['metadata'],'category':op['category']}
                    else:kw['archived']=op['op']=='archive'
                    obj=s.save(old['id'],old['revision'],**kw,actor=applier,reason='reviewed project management '+task['id']+' proposal '+record['proposal_sha256']+' operation '+op['id'],merge=False,connection=c)
                    current[obj['id']]=obj
                item={'operation_id':op['id'],'op':op['op'],'project_id':obj['id'],'revision':obj['revision'],'sha256':digest(obj),'proposer':record['proposer'],'applier':applier}
                applied.append(item);s.event(c,'project_management.applied_operation',obj['id'],item,applier)
            record.update(state='applied',review={'proposal_sha256':record['proposal_sha256'],'reviewer':applier,'at':now(),'decision':'apply exact visible proposal'},application={'applier':applier,'at':now(),'operations':applied,'atomic':True})
            put(c,'proposal:'+task['id']+':'+record['candidate_sha256'],record)
            put(c,'proposal_revision:'+task['id']+':'+record['proposal_sha256'],record)
            result={**task['result'],'project_management':{'candidate_sha256':record['candidate_sha256'],'proposal_sha256':record['proposal_sha256'],'state':'applied','application':record['application']}}
            c.execute("UPDATE tasks SET status='deliverable',result=?,updated_at=? WHERE id=?",(encoded(result),now(),task['id']))
            s.event(c,'project_management.applied',task['id'],{'proposal_sha256':record['proposal_sha256'],'application':record['application']},applier)
            return record
    if app.runner:app.runner.stop_revoked()
    return result
