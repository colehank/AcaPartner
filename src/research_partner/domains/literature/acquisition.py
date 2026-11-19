"""One bounded Crossref acquisition before the existing model evidence freeze.

No model tool loop, arbitrary URL reader, retry, full text fetch or permissions
expansion. SQLite reservations survive disconnects; an uncertain send is spent.
"""
from __future__ import annotations
from research_partner.resources import package_root
import base64
import copy
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit
import json
import re
import time
from research_partner.storage.store import Problem, require, now, digest, encoded
from research_partner.domains.literature.literature import CROSSREF_ENDPOINT

FEATURE = 'literature_acquisition_v1'
LITERATURE_SOURCE = 'crossref'
MAX_RECORDS = 8
MAX_BYTES = 1024*1024
MAX_SECONDS = 20


def _denies_network(request):
    text=request.casefold().replace('’', "'")
    # Use the same provider key as plan() and the actual fetch endpoint's host.
    # Protect only that host's internal dots from sentence splitting, on this
    # matching copy. The stored request, constraints and their hashes stay exact.
    endpoint_host=urlsplit(CROSSREF_ENDPOINT).hostname.casefold()
    protected_host=endpoint_host.replace('.', '\u2024')
    text=text.replace(endpoint_host,protected_host)
    supported_resource=r'(?<![a-z0-9_])(?:'+re.escape(LITERATURE_SOURCE)+'|'+re.escape(protected_host)+r')(?![a-z0-9_])'
    # Scientific qualifications may mention retrieval without prohibiting it.
    # Their exception is scoped: shared negation can still govern a coordinated
    # tool action, and a disclaimer of network authority always remains a ban.
    # Examine every negative independently, including later clauses.
    network_en=r'(?:'+r"\b(?:search(?:ing)?|look(?:ing)?\s+up|retriev\w*|fetch\w*|internet|web|network|online|external\s+(?:services?|sources?))\b"+'|'+supported_resource+')'
    network_zh=r'(?:联网|上网|互联网|网络|外网|外部(?:服务|来源|资料|文献)|检索|搜索|查找|抓取|'+supported_resource+')'

    def scientific_complement(scope,language):
        # Exceptions recognize an entire restricted scientific assertion, never
        # merely its leading verb. Unknown network-bearing complements stay
        # denied; adding a novel tool-action verb cannot enlarge the exception.
        if language=='en':
            qualifier=r'(?:complete|exhaustive|comprehensive|systematic|full)'
            atom=r'(?:'+qualifier+r'\s+(?:search|retrieval|coverage)|completeness|(?:date|year)\s+filter(?:ing|s)?|(?:a\s+)?(?:mechanism|(?:causal|neural)\s+mechanism|causality))'
            subject=r'(?:(?:the|this|a|an|one|online|web|literature|bibliographic)\s+)*(?:search|retrieval|metadata|searching|query\s+terms)'
            subjects=subject+r'(?:\s+(?:or|and)\s+'+subject+r')*'
            assertion=r'(?:(?:that\s+)?'+subjects+r'\s+(?:(?:is|are)\s+'+qualifier+r'|(?:prov(?:e|es)|establish(?:es)?|guarantee(?:s)?|ensure(?:s)?|impl(?:y|ies)|mean(?:s)?)\s+'+atom+r')|'+atom+r')'
            return bool(re.fullmatch(assertion+r'(?:\s+(?:or|and)\s+'+assertion+r')*',scope.strip()))
        atom=r'(?:(?:完备|完整|全面|系统)(?:检索|覆盖|性)|完备|完整|日期过滤|年份过滤|完成全文阅读|(?:文献)?检索的(?:完备|完整)性|(?:神经|因果)?机制)'
        subject=r'(?:这次检索|本次检索|网络检索|外部资料|网络模型|元数据|摘要)'
        subjects=subject+r'(?:(?:或|和|及)'+subject+r')*'
        assertion=r'(?:'+subjects+r'(?:覆盖全部文献|(?:保证|证明|构成|就是)'+atom+r')|'+atom+r')'
        return bool(re.fullmatch(assertion+r'(?:(?:或|和|及)'+assertion+r')*',scope.strip()))

    def clause(tail,negative_pattern,language):
        scope=re.split(r'[.;!?。；！？\n]',tail,maxsplit=1)[0]
        # A later explicit negative is checked in its own iteration. Do not
        # remove a coordinated action that merely shares the first negative.
        later=re.search(negative_pattern,scope)
        if later:
            scope=scope[:later.start()].rstrip()
            scope=re.sub(r'(?:[,，、]\s*|\b(?:and|or|nor|also)\s*|(?:也|而且|并且|但|且)\s*)+$','',scope).strip()
        return scope
    english_denial=r"\b(?:do\s+not|don't|dont|never|must\s+not|mustn't|cannot|can't|without|no|avoid|stop|not)\b"
    scientific_predicate=r'\s*(?:(?:automatically|necessarily|ever)\s+){0,3}(?:imply|implies|mean(?:s)?|equate(?:s)?|guarantee(?:s|ing)?|ensure(?:s)?|prove(?:s)?|proving|establish(?:es|ing)?|claim(?:s|ing)?|assert(?:s|ing)?|assum(?:e|es|ing)|conclud(?:e|es|ing)|infer(?:s|ring)?|demonstrat(?:e|es|ing)|treat(?:s|ing)?|interpret(?:s|ing)?|confus(?:e|es|ing))\b'
    for negative in re.finditer(english_denial,text):
        scope=clause(text[negative.end():],english_denial,'en')
        predicate=re.match(scientific_predicate,scope)
        complement=scope[predicate.end():] if predicate else None
        if negative.group()=='no':
            wrapper=re.match(r'\s*(?:(?:evidence|proof|assurance)\s+|(?:(?:single|literature|online|bibliographic)\s+){0,3}(?:search|retrieval)\s+(?:(?:can|could)\s+)?(?:guarantee|ensure|prove|establish|imply|mean)s?\s+)',scope)
            if wrapper:complement=scope[wrapper.end():]
        if complement is not None and scientific_complement(complement,'en'):continue
        if re.search(network_en,scope):return True
    if re.search(r"\b(?:only|exclusively)\s+(?:(?:use|analyze|analyse|read|consider|discuss|search|work\s+with)\s+)?(?:the\s+)?(?:attached|provided|supplied|existing|local|offline)\b",text):return True
    if re.search(r"\b(?:attached|provided|supplied|existing|local|offline)\s+(?:evidence|materials?|papers?|sources?)\s+only\b",text):return True
    chinese_denial=r'(?:不(?:要|允许|可以|准|应该|应|需(?:要)?|得|能|必)?|无需|禁止|避免|勿)'
    scientific_predicate_zh=r'\s*(?:自动|必然|一定|就|因此){0,3}(?:等于|代表|意味着|保证|确保|构成|表明|证明|说明|声称|宣称|断言|假设|推断|推出|暗示|视为|当成|误称)'
    for negative in re.finditer(chinese_denial,text):
        scope=clause(text[negative.end():],chinese_denial,'zh')
        predicate=re.match(scientific_predicate_zh,scope)
        if predicate and scientific_complement(scope[predicate.end():],'zh'):continue
        if re.search(network_zh,scope):return True
    return bool(re.search(r'(?:仅|只)(?:能|需|允许)?(?:使用|分析|阅读|依据|基于|在|用|讨论|搜索|检索)[^。；;\n]{0,12}(?:已有|现有|本地|离线|附件|提供|给出|附上)',text))


def _asks_for_literature(request):
    # A retrieval instruction must begin its clause. Mentions such as "explain
    # how to search papers" or "research papers" are not tool permissions.
    text=request.casefold()
    start=r'(?:^|[.;!?。；！？,，\n])\s*'
    polite=r'(?:(?:please|can you|could you|would you|help me|i want you to|i need you to|i want to|i need to)\s+)?'
    noun=r'\b(?:literature|papers?|articles?|references?|publications?|crossref)\b'
    pattern=start+polite+r'(?:search(?:\s+(?:for|on))?|find|look\s+up|retrieve|locate|collect)\s+([a-z0-9 -]{0,120}?)'+noun
    for match in re.finditer(pattern,text):
        words=match.group(1).split()
        if len(words)<=8 and not set(words)&{'using','from','in','within','among','based','by','about','attached','provided','supplied','existing','local','offline','counterexample','proof','steps'}:
            return True
    if re.search(start+polite+r'(?:conduct|perform|run|do)\s+(?:a\s+)?(?:literature|paper|bibliographic)\s+search\b',text):return True
    chinese=start+r'(?:(?:可以|能否)?(?:请帮我|请你|请|麻烦你|麻烦|帮我|希望你|需要你)?\s*)'
    return bool(re.search(chinese+r'(?:检索|搜索|查找|搜集|查阅)(?:(?![。！？；;\n]|已有|现有|提供|附上|本地|离线|附件).){0,120}(?:文献|论文|crossref)',text))


def plan(data):
    request = data.get('request',data.get('prompt',''))
    supplied = data.get('literature_plan')
    if supplied is False or isinstance(supplied,dict) and supplied.get('enabled') is False: return None
    denied=_denies_network(request) if isinstance(request,str) else False
    if isinstance(data.get('constraints'),str):denied=denied or _denies_network(data['constraints'])
    if denied:
        require(supplied is None,'明确禁止联网与文献查询计划冲突；未扩大权限，请先修订委托范围','literature_scope_conflict',409)
        return None
    if supplied is None:
        if not isinstance(request,str) or not _asks_for_literature(request): return None
        quoted = re.findall(r'[“"「]([^”"」]{3,600})[”"」]',request)
        query = quoted[0] if len(quoted)==1 else request.strip()
        query = re.sub(r'^(?:请|帮我|please)\s*','',query,flags=re.I)
        require(3<=len(query)<=600,'检索目的需要一条 3–600 字的具体查询；请在预览中补充 literature_plan.query','literature_scope_required',409)
        source = 'explicit_natural_language_intent'
        supplied = {'query':query,'limit':3}
    else:
        require(isinstance(supplied,dict),'文献查询计划必须为对象')
        require(not (set(supplied)-{'enabled','source','query','limit','max_requests','max_bytes','timeout_seconds'}),'文献查询仅支持单条 Crossref 元数据/可用摘要计划；不支持全文、任意 URL 或额外工具')
        source = 'explicit_query_plan'
    require(supplied.get('source',LITERATURE_SOURCE)==LITERATURE_SOURCE,'当前仅接通 Crossref 查询')
    query=supplied.get('query','')
    require(isinstance(query,str) and 3<=len(query.strip())<=600,'请输入 3–600 字的文献查询')
    limit=supplied.get('limit',3);byte_limit=supplied.get('max_bytes',MAX_BYTES);seconds=supplied.get('timeout_seconds',MAX_SECONDS)
    require(type(limit) is int and 1<=limit<=MAX_RECORDS,'文献返回上限为 1–8 条')
    require(type(byte_limit) is int and 1024<=byte_limit<=MAX_BYTES,'响应读取上限为 1024–1048576 字节')
    require(type(seconds) in (int,float) and 0<seconds<=MAX_SECONDS,'文献总时限须为 0–20 秒内有限正数')
    require(type(supplied.get('max_requests',1)) is int and supplied.get('max_requests',1)==1,'每个委托仅允许一次 HTTP；恢复不扩额')
    return {'version':1,'source':LITERATURE_SOURCE,'query':query.strip(),'limit':limit,'max_requests':1,'max_bytes':byte_limit,
            'timeout_seconds':seconds,'intent_source':source,'request_sha256':digest(request),
            'read_scope':'metadata/available abstracts','full_text_supported':False,'server_filters':[],
            'scope_note':'单次 bibliographic query；年份等文字只是查询词，不是日期过滤。无全文、URL 跟随、费用服务或自动重试。'}


def _get(c,key,default=None):
    row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default


def _put(c,key,value):
    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,encoded(value)))


def _task(s,c,ident):
    row=c.execute('SELECT * FROM tasks WHERE id=?',(ident,)).fetchone()
    require(row,'获取所属任务不存在','not_found',404)
    return s.unpack(row)


def assert_child(s,c,payload):
    if not payload.get('acquisition_parent'): return
    from research_partner.domains.collaboration.cycle import assert_parent
    parent_id=payload['acquisition_parent'];parent,state=assert_parent(s,c,parent_id,_get(c,'cycle_epoch:'+payload['acquisition_child_key']))
    require(state.get('acquisition_child')==payload.get('acquisition_task_id') and parent['payload'].get('literature_plan')==payload.get('literature_plan'),
            '文献子任务合同不属于当前父级获取','cancelled',409)
    s.assert_material_access(c,parent['payload'])


def enqueue_cycle(app,c,parent,state):
    """Only reserve a queue slot while the cycle's transaction is open."""
    s=app.store;ident=parent['id'];limits=parent['payload']['cycle_config']['limits'];p=parent['payload']['literature_plan']
    require(state['reserved_seconds']+p['timeout_seconds']<=limits['timeout_seconds'] and state['steps_used']+1<=limits['max_steps'],
            '文献获取超出父协作剩余时间/步骤额度','budget_exhausted',409)
    fullkey=ident+':literature';base=parent['payload']
    payload={'kind':'literature_acquisition','project_id':base['project_id'],'request':base['request'],
             'context':copy.deepcopy(base['context']),'literature_plan':copy.deepcopy(p),'provider_id':None,
             'budget':{'max_model_calls':0,'timeout_seconds':p['timeout_seconds']},'authorization':copy.deepcopy(base.get('authorization',{})),
             'priority':base.get('priority',0),'depends_on':[],'feedback_id':base.get('feedback_id'),
             'acquisition_parent':ident,'acquisition_child_key':fullkey}
    task=s.submit(payload,'acquisition:'+ident,parent_fence={'id':ident,'epoch':state['epoch']},connection=c)
    # The deterministic parent record, not an untrusted worker field, owns child identity.
    payload['acquisition_task_id']=task['id']
    c.execute('UPDATE tasks SET payload=? WHERE id=?',(encoded(payload),task['id']))
    state['acquisition_child']=task['id'];state['reserved_seconds']+=p['timeout_seconds'];state['steps_used']+=1
    state['children'].append({'id':task['id'],'key':fullkey,'role':'acquisition','round':0,'route':'crossref'})
    _put(c,'cycle_epoch:'+fullkey,state['epoch'])
    return task['id']


def summary(store,ident): return store.setting('acquisition:'+ident)


def _permission(app,payload):
    return digest({'network':app.config.get('network',{}),'authorization':payload.get('authorization',{}),
                   'project_id':payload['project_id'],'literature_plan':payload.get('literature_plan')})


def _worker_argv():
    return [sys.executable,'-m','research_partner.domains.literature.worker',str(os.getpid())]


def recover_process(runtime,ident):
    path=runtime.runs/ident/'acquisition-process.json'
    if path.exists():
        from research_partner.execution.runtime import terminate_owned
        record=json.loads(path.read_text())
        if record.get('state') in {'running','terminal_group_anchor'}:terminate_owned(record)
    task=runtime.store.task(ident);key='acquisition:'+task['payload'].get('acquisition_parent',ident)
    with runtime.store.transaction() as c:
        receipt=_get(c,key)
        if receipt and receipt.get('executor_task_id')==ident and receipt.get('state')=='dispatched':
            receipt.update(state='uncertain',error_code='service_interrupted',error='服务中断；未确认原请求完成，不自动重发',finished_at=now())
            _put(c,key,receipt)


def _assert_dispatch(runtime,task,operation):
    # Caller owns Runtime.mutex, the same boundary as task controls. In-process
    # configuration changes must take this mutex too; production config is only
    # loaded at startup and has no unsynchronized hot-reload endpoint.
    s=runtime.store
    with s.transaction() as c:
        s.assert_execution(c,task['id'],task.get('execution_token'))
        owner=_task(s,c,operation['owner_task_id'])
        require(_get(c,'acquisition:'+operation['owner_task_id'])==operation,'获取预留已改变；不发送请求','cancelled',409)
        require(time.time()<operation['deadline_epoch'],'获取预留已过期；不发送请求','literature_timeout',409)
        require(runtime.app.config.get('network',{}).get('literature_enabled',True) and _permission(runtime.app,owner['payload'])==operation['permission_sha256'],
                '发送前获取权限已变化；不发送请求','authorization_required',403)


def _settle_time(s,c,ident,operation,actual=None):
    key=operation['time_reservation_key'];reservation=_get(c,key,{})
    if reservation.get('state')!='reserved' or reservation.get('execution_token')!=operation['execution_token']:return
    if actual is None:
        reservation.update(state='uncertain_spent',finished_at=now(),unused_time_refunded=False)
    else:
        actual=max(0,float(actual));total=float(_get(c,'elapsed:'+ident,0))
        _put(c,'elapsed:'+ident,max(0,total-reservation['reserved_seconds']+actual))
        reservation.update(state='settled',finished_at=now(),actual_seconds=actual,unused_time_refunded=actual<reservation['reserved_seconds'],refunded_seconds=max(0,reservation['reserved_seconds']-actual))
        s.event(c,'task.time_settled',ident,{'reservation':key,'actual_seconds':actual,'tool':'crossref','elapsed_seconds':max(0,total-reservation['reserved_seconds']+actual)},'runtime')
    _put(c,key,reservation)


def fetch(runtime,task,p,operation):
    """Hard wall-clock deadline includes DNS, TLS, headers, body and parsing.

    This is a single host tool process, without a model invocation/time reset.
    Its full time slice has already been reserved by execute().
    """
    from research_partner.execution.runtime import confirm_process_identity,cleanup_unregistered,terminate_owned
    from research_partner.providers.registry import restricted_environment
    ident=task['id'];directory=runtime.runs/ident;directory.mkdir(exist_ok=True,mode=0o700)
    output=directory/'acquisition-response.json';errors=directory/'acquisition-stderr.txt';ownership=directory/'acquisition-process.json'
    process=None;record=None;timer=None;failure=None;result=None;request_dispatched=False;spawn_failed=False;start=time.monotonic()
    registration={};deadline_fired=threading.Event();deadline_errors=[]
    try:
        with output.open('w') as stdout,errors.open('w') as stderr:
            with runtime.mutex:
                runtime.check(ident)
                _assert_dispatch(runtime,task,operation)
                argv=_worker_argv();environment=restricted_environment()
                try:
                    process=subprocess.Popen(argv,cwd=package_root().parent,
                        env=environment,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,text=True,start_new_session=True)
                except OSError:
                    # Popen has not returned a worker or handed it a request.
                    # Preserve the OS exception; no process time was consumed.
                    spawn_failed=True;raise
                record=confirm_process_identity(process,start+p['timeout_seconds'],registration,timeout_code='literature_timeout')
                record.update(state='running' if record['identity_kind']=='live_command' else 'terminal_group_anchor',
                              execution_token=task.get('execution_token'),started_at=now(),tool='bounded_crossref')
                # Keep the original absolute deadline through registration,
                # second authorization check and descendant cleanup.
                def enforce_deadline():
                    deadline_fired.set()
                    try:terminate_owned(record,hard=True)
                    except (Problem,OSError) as error:deadline_errors.append({'code':getattr(error,'code','process_stop_failed'),'message':str(error)[:400]})
                timer=threading.Timer(max(0,p['timeout_seconds']-(time.monotonic()-start)),enforce_deadline)
                timer.daemon=True;timer.start()
                ownership.write_text(encoded(record));runtime.children[ident]=record
                # A spawned worker remains blocked on stdin until the second
                # permission/deadline check. No HTTP occurs inside SQLite.
                _assert_dispatch(runtime,task,operation)
                require(record['identity_kind']=='live_command' and process.poll() is None,'文献子进程在接收请求前已退出','literature_unavailable',503)
                request_dispatched=True
                process.stdin.write(encoded({k:p[k] for k in ['query','limit','max_bytes','timeout_seconds']}));process.stdin.close()
            while process.poll() is None:
                runtime.check(ident)
                require(time.monotonic()-start<p['timeout_seconds'],'文献子进程达到硬时限；原请求状态保留，不自动重发','literature_timeout',409)
                require(output.stat().st_size+errors.stat().st_size<=p['max_bytes']*2+65536,'文献子进程输出超限','literature_response_limit',413)
                time.sleep(.025)
            require(time.monotonic()-start<p['timeout_seconds'],'文献子进程超过硬时限','literature_timeout',409)
        value=json.loads(output.read_text())
        if value.get('error'):
            failure=value['error'];raise Problem(failure['message'],failure['code'],failure['status'],failure.get('details',{}))
        require(process.returncode==0 and isinstance(value.get('response'),dict),'文献子进程没有成功响应','literature_unavailable',503)
        result=value['response'];result['raw']=base64.b64decode(result.pop('raw_base64'),validate=True)
        require(len(result['raw'])<=p['max_bytes'],'文献响应超出上限','literature_response_limit',413)
        result['items']=json.loads(result['raw'])['message']['items'][:p['limit']]
        result['host_elapsed_seconds']=time.monotonic()-start
        return result
    except Exception as error:
        failure=error;raise
    finally:
        try:
            if record is None:record=registration.get('confirmed')
            if record:terminate_owned(record,hard=timer is None)
            elif process:cleanup_unregistered(process,registration)
            if process:
                process.wait(timeout=5)
                if process.stdin and not process.stdin.closed:
                    try:process.stdin.close()
                    except OSError:pass
        finally:
            if timer:timer.cancel();timer.join(timeout=1)
        late_failure=None
        if failure is None and process and (deadline_fired.is_set() or time.monotonic()-start>=p['timeout_seconds']):
            late_failure=Problem('文献进程组清理达到原硬时限；未重发请求','literature_timeout',409,{'deadline_stop_errors':list(deadline_errors)})
            failure=late_failure
        if failure is None and result is not None:result['host_elapsed_seconds']=time.monotonic()-start
        with runtime.mutex:
            if runtime.children.get(ident) is record:runtime.children.pop(ident,None)
            if record:
                record.update(state='finished',finished_at=now(),returncode=process.returncode,
                              deadline_triggered=deadline_fired.is_set(),deadline_stop_errors=list(deadline_errors))
                ownership.write_text(encoded(record))
        if failure is not None:
            failure.details=getattr(failure,'details',{})
            failure.details.update(request_dispatched=request_dispatched,worker_started=process is not None)
            if spawn_failed:
                failure.details.update(host_elapsed_seconds=0,host_control_elapsed_seconds=time.monotonic()-start,
                    error_type=type(failure).__name__,os_errno=failure.errno)
            elif not request_dispatched:failure.details['host_elapsed_seconds']=time.monotonic()-start
        if late_failure:raise late_failure


def execute(runtime,task,directory=None):
    app=runtime.app;s=runtime.store;ident=task['id'];token=task.get('execution_token');payload=task['payload']
    p=payload.get('literature_plan')
    if not p:return task
    owner=payload.get('acquisition_parent',ident);key='acquisition:'+owner
    # Native sessions, evidence files and model checkpoints are immutable.
    if directory is not None and (directory/'evidence.json').exists():
        require((s.setting(key) or {}).get('state')=='adopted','已冻结模型材料，不能静默追加文献','integrity',409)
    with s.transaction() as c:
        s.assert_execution(c,ident,token);saved=_get(c,key)
        if saved and saved.get('state')=='adopted':
            require(saved['plan_sha256']==digest(p),'获取计划身份变化','integrity',409)
            return task
        require(not saved,'已有已发送或状态不明的文献请求；额度保留，未自动重发。请检查原任务回执。','acquisition_uncertain',409,saved)
        require(app.config.get('network',{}).get('literature_enabled',True),'文献联网未启用','network_disabled',403)
        require(not c.execute("SELECT 1 FROM steps WHERE task_id=? AND step_key IN ('context','model')",(ident,)).fetchone(),
                '任务已冻结模型材料，不能追加来源','integrity',409)
        owner_task=_task(s,c,owner)
        permission=_permission(app,owner_task['payload'])
        # Reserve the complete network slice against existing task seconds. An
        # uncertain interruption is never refunded. Cycle allocation is already
        # debited from its total by enqueue_cycle.
        spent=float(_get(c,'elapsed:'+ident,0));budget=payload['budget']['timeout_seconds']
        require(spent+p['timeout_seconds']<=budget,'文献获取超出任务剩余总秒数','budget_exhausted',409)
        _put(c,'elapsed:'+ident,spent+p['timeout_seconds'])
        operation={'version':1,'state':'dispatched','owner_task_id':owner,'executor_task_id':ident,'execution_token':token,
                   'plan':copy.deepcopy(p),'plan_sha256':digest(p),'original_context_sha256':digest(owner_task['payload']['context']),
                   'original_materials':copy.deepcopy(owner_task['payload']['context']['materials']),
                   'permission_sha256':permission,'requests_reserved':1,'seconds_reserved':p['timeout_seconds'],
                   'bytes_read':None,'started_at':now(),'deadline_epoch':time.time()+p['timeout_seconds'],
                   'time_reservation_key':'time_reservation:'+ident+':acquisition',
                   'model_calls':0,'cost':'unknown; no paid service configured','full_text_read':False}
        _put(c,operation['time_reservation_key'],{'execution_token':token,'runtime_id':runtime.runtime_id,'state':'reserved',
            'started_at':operation['started_at'],'reserved_seconds':p['timeout_seconds'],'base_consumed_seconds':spent,'tool':'crossref','owner_task_id':owner})
        s.event(c,'task.time_reserved',ident,{'reservation':operation['time_reservation_key'],'seconds':p['timeout_seconds'],'execution_token':token,'tool':'crossref'},'runtime')
        _put(c,key,operation);s.event(c,'literature.dispatched',owner,{k:v for k,v in operation.items() if k!='execution_token'},'runtime')
    from research_partner.domains.literature.literature import Literature
    lib=Literature(s,app.config.get('network',{}));fetched=None
    try:
        fetched=fetch(runtime,task,{**p,'timeout_seconds':max(0,operation['deadline_epoch']-time.time())},operation)
        with s.transaction() as c:
            s.assert_execution(c,ident,token)
            current=_get(c,key);owner_task=_task(s,c,owner)
            require(current==operation,'文献获取预留已变化','cancelled',409)
            require(time.time()<=operation['deadline_epoch'],'文献回执超过预留时限，未登记正式来源','literature_timeout',409)
            require(_permission(app,owner_task['payload'])==permission and app.config.get('network',{}).get('literature_enabled',True),
                    '获取权限已变化；不接受旧查询返回','authorization_required',403)
            require(digest(owner_task['payload']['context'])==operation['original_context_sha256'],'获取期间上下文变化','integrity',409)
            response=lib.persist_response(fetched,payload['project_id'],connection=c,task_id=ident,execution_token=token)
            imported=lib.import_records(response['records'],payload['project_id'],response['source']['sha'],connection=c,task_id=ident,execution_token=token)
            from research_partner.domains.collaboration.resolver import evidence_projection,MAX_MATERIALS,MAX_BYTES as EVIDENCE_BYTES
            context=copy.deepcopy(owner_task['payload']['context']);refs=context['materials'];excluded=[]
            objects=[s.get(ref['id'],ref['revision'],c) for ref in refs]
            adopted=list(imported['created']);duplicate_selections=[]
            for duplicate in imported['duplicates']:
                latest=s.get(duplicate['existing_id'],connection=c)
                selected=[ref for ref in operation['original_materials'] if ref['id']==latest['id']]
                chosen=[s.get(ref['id'],ref['revision'],c) for ref in selected] if selected else [latest]
                for ref,obj in zip(selected,chosen):require(digest(obj)==ref['sha256'],'原采用文献身份改变','integrity',409)
                adopted.extend(chosen)
                duplicate_selections.append({'existing_id':latest['id'],'existing_revision':latest['revision'],
                    'current_library_ref':{'id':latest['id'],'revision':latest['revision'],'sha256':digest(latest)},
                    'conflicting_fields':duplicate['conflicting_fields'],'action':duplicate['action'],
                    'selection_action':'retained_original_exact_selection' if selected else 'adopted_current_unselected_library_source',
                    'selected_sources':[{'id':o['id'],'revision':o['revision'],'sha256':digest(o),
                        'incoming_conflicting_fields':[k for k in ('title','authors','year','abstract','doi')
                            if duplicate['incoming'].get(k) and duplicate['incoming'].get(k)!=o['content'].get(k)]} for o in chosen]})
            for obj in adopted:
                ref={'id':obj['id'],'revision':obj['revision'],'sha256':digest(obj)}
                if any(r['id']==ref['id'] and r['revision']==ref['revision'] for r in refs):continue
                size=sum(len(encoded(evidence_projection(o)).encode()) for o in objects+[obj])
                if obj['archived'] or len(refs)>=MAX_MATERIALS or size>EVIDENCE_BYTES:
                    excluded.append({**ref,'reason':'archived source or complete evidence count/byte limit; no truncation'});continue
                refs.append(ref);objects.append(obj)
            manifest={'plan':copy.deepcopy(p),'raw_response_sha256':response['source']['sha'],'read_scope':'metadata/available abstracts',
                      'full_text_read':False,'original_context_sha256':operation['original_context_sha256'],
                      'sources':[{ 'id':o['id'],'revision':o['revision'],'sha256':digest(o),'read_scope':o['content'].get('read_scope','unverified') } for o in adopted],
                      'excluded':excluded,'duplicates':duplicate_selections,
                      'warnings':imported['warnings'],'limitations':['Crossref metadata and supplied abstracts only; no external full text read.',
                        'Duplicate records retain user edits; conflicting fields are not overwritten.','Search terms do not enforce date, completeness or relevance filters.']}
            context['literature_acquisition']=manifest
            from research_partner.domains.evidence.graph import extend_acquired_catalog
            extend_acquired_catalog(app,c,payload['project_id'],context,operation['original_materials'])
            updated=copy.deepcopy(owner_task['payload']);updated['context']=context
            c.execute('UPDATE tasks SET payload=?,updated_at=? WHERE id=?',(encoded(updated),now(),owner))
            receipt={**operation,'state':'adopted','completed_at':now(),'raw_response_sha256':response['source']['sha'],
                     'bytes_read':fetched['bytes_read'],'elapsed_seconds':fetched['elapsed_seconds'],'host_elapsed_seconds':fetched.get('host_elapsed_seconds'),'manifest':manifest,
                     'derived_context_sha256':digest(context),'adopted_materials':copy.deepcopy(refs)}
            _settle_time(s,c,ident,operation,fetched['host_elapsed_seconds'])
            _put(c,key,receipt);s.event(c,'literature.adopted',owner,{'raw_response_sha256':response['source']['sha'],
                  'original_context_sha256':operation['original_context_sha256'],'derived_context_sha256':digest(context),
                  'bytes_read':receipt['bytes_read'],'material_refs':refs},'runtime')
            if owner!=ident:
                c.execute("UPDATE tasks SET status='generated',result=?,updated_at=? WHERE id=?",(encoded({'acquisition':{k:v for k,v in receipt.items() if k!='execution_token'}}),now(),ident))
                s.event(c,'task.generated',ident,{'acquisition_owner':owner,'model_calls':0},'runtime')
    except Exception as error:
        # Audit received/discarded bytes without publishing an asset or source.
        # A cancelled worker may record only its own operation disposition.
        if fetched is None:
            try:
                saved_response=json.loads((runtime.runs/ident/'acquisition-response.json').read_text())['response']
                raw=base64.b64decode(saved_response['raw_base64'],validate=True)
                if len(raw)<=p['max_bytes']:fetched={'raw':raw,'bytes_read':len(raw)}
            except (OSError,ValueError,KeyError,TypeError):pass
        with s.transaction() as c:
            current=_get(c,key)
            if current and current.get('execution_token')==token and current.get('state')=='dispatched':
                current.update(state='discarded' if fetched else 'not_sent' if getattr(error,'details',{}).get('request_dispatched') is False else 'uncertain',error_code=getattr(error,'code','execution_error'),
                               error=str(error)[:500],finished_at=now(),bytes_read=fetched['bytes_read'] if fetched else getattr(error,'details',{}).get('bytes_read'),
                               raw_response_sha256=digest(fetched['raw']) if fetched else None,
                               failure_observation=getattr(error,'details',{}))
                actual=fetched.get('host_elapsed_seconds') if fetched else getattr(error,'details',{}).get('host_elapsed_seconds')
                _settle_time(s,c,ident,operation,actual)
                _put(c,key,current)
        raise
    return runtime.check(ident) if owner==ident else s.task(ident)
