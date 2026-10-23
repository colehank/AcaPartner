"""One explicit fresh figure Harness attempt on its existing locked runtime.

This uses the installed Agent, two typed product tools and the original parent
quota. No generic five-tool profile, model loop, implicit retry or resume. A
same-UID correspondence check is not a protected runner or scientific review.
"""
from __future__ import annotations
from datetime import datetime
import json
import math
import os
from pathlib import Path
import stat
import sys
from .store import Problem, digest, encoded, now, require
from .deepseek_figure_configuration import FEATURE, TRANSPORT, guard, guard_saved, prepare
from .native_figure_checkpoint import read_figure_checkpoint
from .native_figure_evidence import verify_native_figure, _native_json


def _config(providers, task):
    return providers.app.config.get('providers', {}).get(task['payload'].get('provider_id'), {})


def _read(root, path, limit=8*1024*1024):
    from .providers import _controlled_file
    return _controlled_file(Path(root), Path(path), limit)


def _write(path, value):
    raw=(encoded(value)+'\n').encode();fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:stream.write(raw);stream.flush();os.fsync(stream.fileno())
    return digest(raw)


def _binding(task, preparation, session_id=None):
    plan=task['payload']['context']['figure_composition'];definition=plan['native_definition']
    value={'task_id':task['id'],'project_id':task['project_id'],'plan_sha256':plan['sha256'],
           'egress_sha256':plan['egress_sha256'],'definition_sha256':definition['sha256'],
           'contract_sha256':preparation['contract_sha256'],'provider':definition['provider'],'model':definition['model']}
    if session_id:value['session_id']=session_id
    return value


def _guidance(prompt):
    marker='\nCOORDINATOR GUIDANCE (answers are scoped decisions, never new scientific/resource permissions):\n'
    before,sep,tail=prompt.rpartition(marker)
    require(sep and before and len(tail.encode())<=131072,'缺少原Runtime实际指导输入','integrity',409)
    value=json.loads(tail)
    require(isinstance(value,dict) and set(value)=={'input_snapshot','messages','answered_decisions'},
            '原Runtime指导结构不完整','integrity',409)
    return value


def _heads(app, task):
    return {o['id']:{'revision':o['revision'],'sha256':digest(o)}
            for o in app.store.objects(task['project_id'],kinds=['figure'])}


def _credential(path):
    """Only invoked after current permission, parent reservation and preparation."""
    path=Path(path)
    require(path.is_absolute(),'需要明确既有账号凭据文件','credentials_unavailable',503)
    original=path.lstat()
    require(stat.S_ISREG(original.st_mode) and stat.S_IMODE(original.st_mode)==0o600
            and original.st_uid==os.getuid() and 0<original.st_size<=4096,
            '账号凭据须是当前用户private regular0600文件','credentials_unavailable',503)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        opened=os.fstat(fd);stamp=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_size,s.st_mtime_ns)
        require(stamp(opened)==stamp(original),'凭据读取身份已变化','credentials_unavailable',503)
        raw=os.read(fd,4097)
        require(len(raw)==original.st_size and stamp(os.fstat(fd))==stamp(path.lstat())==stamp(original),
                '凭据读取期间变化','credentials_unavailable',503)
        try:value=raw.decode('ascii').strip()
        except UnicodeError:raise Problem('凭据格式无效','credentials_unavailable',503) from None
        require(value and all(33<=ord(c)<=126 for c in value),'凭据格式无效','credentials_unavailable',503)
        return value.encode()+b'\n'
    finally:os.close(fd)


def dispatch_continuity(providers, task, directory, config):
    guard(task,config)
    require(providers.app.config.get('development_budget'),'此原生路线需要现有父资源账','authorization_required',403)
    store=providers.app.store;directory=Path(directory)
    require(not store.setting('native_figure_launch_intent:'+task['id'])
            and not store.setting('provider_invocations:'+task['id'],0)
            and not (directory/'figure-instance').exists() and not (directory/'figure-instance').is_symlink(),
            '此fresh协议已有分派或未知结果；只允许零调用核对，不能重新启动',
            'provider_checkpoint_missing',503)
    return {'requires_checkpoint':False,'transport':TRANSPORT,'fresh_only':True,'new_model_requests':0}


def _snapshot(task, directory, intent, session_id=None, *, accounting_only=False):
    directory=Path(directory);instance=directory/'figure-instance'
    record_raw=_read(directory,instance/'preparation.json',131072);record=json.loads(record_raw)
    require(record['definition']==task['payload']['context']['figure_composition']['native_definition']
            and digest(record_raw)==intent['preparation_sha256'],
            '原生准备记录不属于本次冻结定义','integrity',409)
    for name,sha in record['definition']['modules'].items():
        require(digest(_read(directory,instance/'plugin'/name))==sha,'原生固定模块字节改变','integrity',409)
    require(digest(_read(directory,instance/'launch.py'))==record['definition']['modules']['figure-launch.py'],
            '原生launcher字节改变','integrity',409)
    prompt_raw=_read(directory,instance/'control/prompt.txt',131072)
    require(digest(prompt_raw)==intent['prompt_sha256'] and digest(_read(directory,directory/'evidence.json'))==intent['evidence_sha256'],
            '原提示或冻结材料改变','integrity',409)
    checkpoint=read_figure_checkpoint(instance,_binding(task,record,session_id),
                                      allow_missing_usage_for_accounting=accounting_only)
    return record,prompt_raw.decode('utf-8'),checkpoint


def _terminal(checkpoint):
    """A known native end is separate from complete request accounting."""
    if not isinstance(checkpoint,dict) or checkpoint.get('event_range_verified') is not True:return False
    receipt=checkpoint.get('receipt');events=checkpoint.get('attempt_events')
    if not isinstance(receipt,dict) or receipt.get('phase')!='flushed' or not isinstance(events,list) or not events:return False
    last=events[-1]
    return (isinstance(last,dict) and last.get('type')=='turn/end' and isinstance(last.get('data'),dict)
            and isinstance(receipt.get('reason'),dict) and last['data'].get('reason')==receipt['reason'])


def _accounting(checkpoint, cap):
    # Never release parent request reservations from malformed or partial files.
    # A terminal turn alone says nothing about unaccounted native requests.
    result={'closed':False,'unknown_requests':True,'request_cap':cap,'actual_requests':None,'usage_sha256':None}
    def invalid(reason):return {**result,'validation_error':reason}
    if type(cap) is not int or not 1<=cap<=4:return invalid('invalid_request_cap')
    if not isinstance(checkpoint,dict):return invalid('checkpoint_unavailable')
    sha=checkpoint.get('usage_sha256')
    if not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):return invalid('usage_digest_unavailable')
    result['usage_sha256']=sha
    if not _terminal(checkpoint):return invalid('native_terminal_unverified')
    receipt=checkpoint['receipt'];binding=receipt.get('figure_task_binding');usage=checkpoint.get('usage')
    if not isinstance(binding,dict) or not isinstance(usage,dict):return invalid('invalid_accounting_documents')
    streams=binding.get('streams');calls=usage.get('calls')
    if not isinstance(streams,list) or not isinstance(calls,list):return invalid('invalid_request_collections')
    if binding.get('stream_outcome_unknown') is not False or len(calls)!=len(streams) or len(calls)>cap:return invalid('request_range_unknown')
    session=receipt.get('session_id');model=receipt.get('model')
    if not isinstance(session,str) or not session or not isinstance(model,str) or not model:return invalid('native_identity_missing')
    seen=set()
    for call,stream in zip(calls,streams):
        if not isinstance(call,dict) or not isinstance(stream,dict):return invalid('invalid_request_record')
        ident=call.get('id')
        if not isinstance(ident,str) or not ident or ident in seen or ident!=stream.get('request_id'):return invalid('request_bijection_invalid')
        seen.add(ident)
        if (call.get('session_id')!=session or stream.get('session_id')!=session or call.get('model')!=model
                or call.get('status')!='usage_received_bill_unverified' or stream.get('status')!='stream_returned_bill_unverified'):
            return invalid('request_identity_or_status_invalid')
        tokens=call.get('usage');finish=call.get('finish')
        if (not isinstance(tokens,dict) or not {'inputTokens','outputTokens'}<=set(tokens)
                or not all(type(v) in (int,float) and (type(v) is int or math.isfinite(v)) and v>=0 for v in tokens.values())
                or not isinstance(finish,dict) or finish.get('kind') not in ('stop','tool-calls','max-tokens')
                or tokens!=stream.get('usage') or finish!=stream.get('finish')):return invalid('usage_or_finish_invalid')
    return {**result,'closed':True,'unknown_requests':False,'actual_requests':len(calls)}


def _read_authority(app, task):
    """Finished read verification does not revive a lease or permit any write."""
    from .figure_composition_task import check_current_authority,check_egress
    from .development_budget import Budget
    actual=app.store.task(task['id'])
    require(digest(actual['payload'])==digest(task['payload']) and actual['project_id']==task['project_id'],
            '当前Task固定上下文不匹配','integrity',409)
    completed=actual['status']!='running'
    if completed:
        require(actual['status']=='generated' and task.get('status')=='generated'
                and isinstance(actual.get('result'),dict) and isinstance(actual['result'].get('provider'),dict)
                and actual['result']['provider']==task.get('result',{}).get('provider'),
                '未完成或已撤销Task不能通过零调用读取变成新候选','cancelled',409)
    config=app.config.get('providers',{}).get(task['payload'].get('provider_id'),{})
    plan=(guard_saved if completed else guard)(task,config)
    parent=Budget(app.config['development_budget']);current=parent.check()
    require(parent.native_permission(current,plan['native_definition'],read_only=True) is not None,
            '当前父任务原生账号/有限费用许可缺失或已撤回','authorization_required',403)
    if not completed:
        check_current_authority(app,task,[task['project_id']],task.get('execution_token'))
        return False
    project=app.get(task['project_id'],[task['project_id']])
    require(not project['archived'],'项目已归档，不能核对为当前可用候选','cancelled',409)
    check_egress(app,plan,[task['project_id']],task['id'])
    return True


def _verify_store(app, task, proof, intent, *, read_only=False):
    from .commission import validate_candidate
    from .figure_definition import FigureDefinitions
    from .figure_composition_task import check_current_authority
    if read_only:_read_authority(app,task)
    else:check_current_authority(app,task,[task['project_id']],task.get('execution_token'))
    validate_candidate(proof['payload'],'note',app,task['project_id'],task=task)
    store=app.store;ref=store.setting('composition_task_candidate:'+task['id']);candidate=proof['candidate']
    require(isinstance(ref,dict) and ref['id']==candidate['id'] and ref['revision']==candidate['revision']
            and ref['definition_sha256']==candidate['definition_sha256'] and ref.get('adopted_head_changed') is False,
            '原工具候选没有同一Store登记','domain_tools_unverified',409)
    obj=app.get(ref['id'],[task['project_id']],ref['revision'])
    require(digest(obj)==ref['sha256'],'已保存候选字节身份不符','integrity',409)
    created=[r for r in proof['provenance']['tool_results'] if r['name']=='create_main_figure']
    # JSON 0 and 0.0 represent the same native number. The Store's original
    # digest is retained separately; never rewrite it to a reserialized digest.
    require(created and _native_json(created[-1]['result']['figure'])==_native_json(obj),
            '实际工具返回与保存对象不一致','domain_tools_unverified',409)
    view=FigureDefinitions(store).read(obj['id'],obj['revision'])
    require(view['definition_sha256']==ref['definition_sha256'],'实际定义文件字节不符','integrity',409)
    changed=[]
    for ident,before in intent['human_heads'].items():
        current=app.get(ident,[task['project_id']])
        head=app.get(ident,[task['project_id']],before['revision']) if read_only else current
        if read_only and (current['revision']!=before['revision'] or digest(current)!=before['sha256']):changed.append(ident)
        require(head['revision']==before['revision'] and digest(head)==before['sha256'],
            '原有人类/来源图已经改变；未覆盖用户版本','conflict',409)
    return {**ref,'read_only_completed_result':read_only,'later_human_heads_changed':changed,'durable_jsonl_sha256':proof['provenance']['durable_jsonl_sha256'],
            'actual_source_reads':proof['provenance']['actual_source_reads'],'native_execution_verified':True,
            'verification_meaning':'actual same-UID native protocol and Store correspondence; no scientific, human or protected-runner signature',
            'scientific_or_human_acceptance':'not_implied'}


def verified_result(app, task, directory, receipt):
    read_only=_read_authority(app,task)
    intent=app.store.setting('native_figure_launch_intent:'+task['id'])
    require(isinstance(intent,dict) and receipt.get('attempt_id')==intent['attempt_id']
            and type(receipt.get('invocation')) is int and receipt['invocation']==intent['invocation'] and receipt.get('native_terminal_confirmed') is True
            and type(receipt.get('returncode')) is int and receipt['returncode']==0,'缺同一已结束原生分派','domain_tools_unverified',409)
    _,prompt,checkpoint=_snapshot(task,directory,intent,receipt.get('session_id'))
    require(checkpoint and checkpoint['events_sha256']==receipt['events_sha256']
            and checkpoint['receipt_sha256']==receipt['driver_receipt_sha256']
            and checkpoint['usage_sha256']==receipt['native_usage_sha256'], '原生完整证据摘要不符','integrity',409)
    proof=verify_native_figure(task,checkpoint['receipt'],checkpoint['raw_jsonl_utf8'],
                              expected_cwd=str(Path(directory)/'figure-instance/capsule'),expected_prompt=prompt)
    return _verify_store(app,task,proof,intent,read_only=read_only)


def recover_candidate(providers, task, directory, previous):
    require(previous.get('transport')==TRANSPORT and previous.get('task_id')==task['id'],
            '原生恢复不能回退另一工具协议','provider_checkpoint_missing',503)
    if previous.get('native_terminal_confirmed') is not True:return None
    proof=verified_result(providers.app,task,directory,previous)
    intent=providers.app.store.setting('native_figure_launch_intent:'+task['id'])
    _,prompt,checkpoint=_snapshot(task,directory,intent,previous['session_id'])
    verified=verify_native_figure(task,checkpoint['receipt'],checkpoint['raw_jsonl_utf8'],
        expected_cwd=str(Path(directory)/'figure-instance/capsule'),expected_prompt=prompt)
    return {'text':verified['text'],'receipt':{**previous,'composition_candidate':proof,
            'recovered_registered_candidate':True,'new_model_requests':0}}


def call(providers, config, task, prompt, directory, run_process, resume):
    from .development_budget import Budget
    from .figure_composition_task import task_bridge,check_current_authority
    from .providers import restricted_environment,_native_write
    plan=guard(task,config);require(resume is None,'此figure profile不恢复原生Agent','provider_checkpoint_missing',503)
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    store=providers.app.store;ident=task['id'];invocation=store.setting('provider_invocations:'+ident,0)
    require(type(invocation) is int and invocation==1 and not store.setting('native_figure_launch_intent:'+ident),
            '已有原生分派或未知结果，不重发','provider_checkpoint_missing',503)
    parent=Budget(providers.app.config['development_budget']);state=parent.check()
    require(parent.native_permission(state,plan['native_definition'],read_only=True) is not None,
            '缺少父任务当前原生账号/有限费用许可；未读取凭据','authorization_required',403)
    held=next((r for r in state['reservations'] if r['id']==ident+':1' and r['kind']=='model'),None)
    require(held and held['state']=='reserved_or_uncertain' and type(held.get('request_cap')) is int and held['request_cap']==plan['native_definition']['max_requests'],
            '缺同一原生请求父预留','budget_exhausted',409)
    require(held.get('native_authorization_reference')==plan['native_definition']['authorization_reference']
            and held.get('native_fee_planning_reserved_usd')==plan['native_definition']['budget_usd'],
            '此预留不属于当前明确原生费用许可','authorization_required',403)
    check_current_authority(providers.app,task,[task['project_id']],task.get('execution_token'))
    coordinator=_guidance(prompt);instance=directory/'figure-instance';record=prepare(instance,task,config)
    prompt_raw=prompt.encode();require(0<len(prompt_raw)<=131072,'完整Runtime原提示超限；未截断','context_limit',413)
    path=instance/'control/prompt.txt';path.write_bytes(prompt_raw);path.chmod(0o600)
    intent={'version':1,'feature':FEATURE,'transport':TRANSPORT,'task_id':ident,'provider_id':task['payload']['provider_id'],
            'attempt_id':os.urandom(12).hex(),'invocation':invocation,'started_at':now(),'resume_session':None,
            'preparation_sha256':digest(_read(directory,instance/'preparation.json',131072)),
            'prompt_sha256':digest(prompt_raw),'evidence_sha256':digest(_read(directory,directory/'evidence.json')),
            'human_heads':_heads(providers.app,task)}
    _write(directory/'native-figure-intent.json',intent)
    store.set_setting('native_figure_launch_intent:'+ident,intent,task_id=ident,execution_token=task.get('execution_token'))
    interrupted=None;result=None;key_path=instance/'control/api-key.txt';checkpoint=None
    try:
        check_current_authority(providers.app,task,[task['project_id']],task.get('execution_token'))
        raw=_credential(config.get('credential_file',''));fd=os.open(key_path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
        with os.fdopen(fd,'wb') as f:f.write(raw)
        with task_bridge(providers.app,task,directory) as bridge:
            result=run_process([sys.executable,'-B',str(instance/'launch.py'),'--budget-file',str(parent.path),
                '--reservation-id',ident+':1','--origin',bridge['origin'],'--task-bearer-file',str(bridge['token_file'])],
                directory,None,restricted_environment())
    except BaseException as error:interrupted=error
    finally:
        cleanup_error=None
        try:key_path.unlink(missing_ok=True)
        except OSError as e:cleanup_error={'type':type(e).__name__,'code':'credential_copy_cleanup_failed'}
        snapshot_error=None
        try:_,_,checkpoint=_snapshot(task,directory,intent,accounting_only=True)
        except (Problem,OSError,ValueError,KeyError,TypeError,AttributeError,IndexError) as e:snapshot_error={'code':getattr(e,'code','checkpoint_unavailable'),'type':type(e).__name__}
        native=checkpoint.get('receipt') if isinstance(checkpoint,dict) else None
        native=native if isinstance(native,dict) else {}
        terminal=_terminal(checkpoint)
        receipt={'version':1,'route':'deepseek_harness','transport':TRANSPORT,'feature':FEATURE,
            'task_id':ident,'provider_id':task['payload']['provider_id'],'attempt_id':intent['attempt_id'],'invocation':invocation,
            'model':plan['native_definition']['model'],'session_id':native.get('session_id'),'resumed_from':None,
            'session_identity_confirmed':bool(native.get('session_id')),'native_terminal_confirmed':terminal,
            'returncode':result.get('returncode') if result else None,'started_at':native.get('started_at'),
            'finished_at':native.get('finished_at') if terminal else None,'local_finished_at':now(),
            'driver_receipt_sha256':checkpoint.get('receipt_sha256') if isinstance(checkpoint,dict) else None,
            'events_sha256':checkpoint.get('events_sha256') if isinstance(checkpoint,dict) else None,
            'native_usage_sha256':checkpoint.get('usage_sha256') if isinstance(checkpoint,dict) else None,
            'usage':checkpoint.get('usage') if isinstance(checkpoint,dict) else None,'actual_bill_usd':None,
            'native_request_accounting':_accounting(checkpoint,plan['native_definition']['max_requests']),
            'scoped_domain_tools':['read_figure_context','create_main_figure'],'snapshot_error':snapshot_error,
            'credential_copy_removed':cleanup_error is None and not key_path.exists(),'cleanup_error':cleanup_error,'new_dispatch_not_retried':True}
        _native_write(directory/'provider-receipt.json',receipt)
    if interrupted:raise interrupted
    require(result and result['returncode']==0 and terminal and cleanup_error is None,'原生Agent未形成已结束成功候选；保留现场不重发',
            'provider_checkpoint_missing',503,{'provider_checkpoint':receipt})
    verified=verify_native_figure(task,native,checkpoint['raw_jsonl_utf8'],expected_cwd=str(instance/'capsule'),expected_prompt=prompt)
    proof=_verify_store(providers.app,task,verified,intent)
    receipt.update(reply_sha256=verified['provenance']['reply_sha256'],input_provenance={**verified['provenance'],'coordinator_input':coordinator},
                   composition_candidate=proof,usage_complete=verified['accounting']['usage_complete'])
    _native_write(directory/'provider-receipt.json',receipt)
    return {'text':verified['text'],'receipt':receipt}
