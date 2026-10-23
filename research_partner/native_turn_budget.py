"""Runtime ownership and conservative time accounting for one native turn.

No server, thread or request is created here. The callback owns the exact native
IDs and interrupt/drain protocol; an unconfirmed terminal never releases time.
"""
import json
import math
import threading
import time

from .store import require, now, uid


def no_dispatch(result):
    """An adapter-owned setup failure before entering the dispatching method.

    Empty IDs, socket closure and a locally finished timestamp alone prove
    nothing. Once session.run is entered its outcome remains conservative.
    This is local dispatch evidence, never a fabricated native terminal.
    """
    return (isinstance(result, dict)
            and result.get('state')=='failed_before_dispatch'
            and result.get('dispatch_not_started') is True
            and result.get('session_run_entered') is False
            and result.get('dispatch_stage') in {'bridge_setup','client_initialization','session_constructor'}
            and result.get('native_terminal_observed') is False
            and all(result.get(key) is None for key in ('thread_id','turn_id','turn_request_sent_at','terminal_received_at',
                                                       'terminal','thread_start_response','turn_start_response'))
            and result.get('wire_messages',[])==[])


def terminal_seconds(result):
    if (not isinstance(result, dict) or result.get('native_terminal_observed') is not True
            or result.get('state') not in {'completed', 'failed', 'interrupted', 'unknown'}
            or not result.get('thread_id') or not result.get('turn_id')):
        return None
    # A collector overflow may leave result verification unknown even though
    # the exact owned turn has ended. Settle its time without treating the
    # incomplete result as a candidate or assuming a socket close ended it.
    terminal = result.get('terminal')
    if not isinstance(terminal, dict) or terminal.get('method') != 'turn/completed':
        return None
    params = terminal.get('params', {})
    turn = params.get('turn', {})
    if (params.get('threadId') != result['thread_id']
            or turn.get('id') != result['turn_id']
            or turn.get('status') not in {'completed', 'failed', 'interrupted'}
            or result['state'] not in {'unknown', turn['status']}):
        return None
    try:
        start = float(result['turn_request_sent_at'])
        end = float(result['terminal_received_at'])
        if not math.isfinite(start) or not math.isfinite(end) or end < start:
            return None
        return end - start
    except (KeyError, ValueError, TypeError):
        return None


def execute(runtime, ident, callback):
    task = runtime.check(ident)
    require(task['payload']['kind']=='figure_composition', '原生动态工具只支持明确的主图任务', 'unsupported_action', 422)
    store, token = runtime.store, task['execution_token']
    key = 'time_reservation:' + ident + ':' + uid('TIME')
    record = {'execution_token': token, 'runtime_id': runtime.runtime_id, 'stop': threading.Event()}
    result = None
    with runtime.mutex:
        require(ident not in runtime.native_turns and ident not in runtime.children,
                '该任务已有执行所有者；不重复启动', 'conflict', 409)
        with store.transaction() as c:
            store.assert_execution(c, ident, token)
            consumed = float(store.setting('elapsed:' + ident, 0))
            extension = store.setting('budget_extension:' + ident, {})
            timeout = min(600., float(task['payload']['budget']['timeout_seconds']) + float(extension.get('seconds', 0))) - consumed
            if runtime.app.config.get('development_budget'):
                from .development_budget import Budget
                parent = Budget(runtime.app.config['development_budget']).check()
                invocation = store.setting('provider_invocations:' + ident, 0)
                held = next((r for r in parent['reservations'] if r['kind']=='model' and r['id']==ident+':'+str(invocation)), None)
                require(held and held['state']=='reserved_or_uncertain', '本次原生模型没有同调用预留', 'budget_exhausted', 409)
                timeout = min(timeout, held['seconds'], Budget.deadline(parent) - time.time())
            require(math.isfinite(timeout) and timeout>0, '原生任务剩余执行时限耗尽；不重置', 'budget_exhausted', 409)
            reservation = {'transport':'app_server_dynamic', 'execution_token':token,
                           'runtime_id':runtime.runtime_id, 'state':'reserved', 'started_at':now(),
                           'reserved_seconds':timeout, 'base_consumed_seconds':consumed}
            c.execute('INSERT INTO kv VALUES(?,?)', (key, json.dumps(reservation)))
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', ('elapsed:'+ident, json.dumps(consumed+timeout)))
            store.event(c, 'task.time_reserved', ident, {'reservation':key, 'seconds':timeout, 'transport':'app_server_dynamic'}, 'runtime')
        runtime.native_turns[ident] = record
    deadline = time.monotonic() + timeout
    def check():
        require(not record['stop'].is_set(), '原生任务已停止；仅中断其自身会话', 'cancelled', 409)
        return runtime.check(ident)
    try:
        result = callback(deadline, check)
        require(isinstance(result, dict), '原生执行器未保留结果状态', 'provider_failed', 503)
        return result
    finally:
        actual = terminal_seconds(result)
        before_dispatch = no_dispatch(result)
        if before_dispatch: actual = 0.
        with store.transaction() as c:
            row = c.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
            saved = json.loads(row[0]) if row else {}
            if saved.get('state')=='reserved' and saved.get('execution_token')==token:
                if actual is None:
                    saved.update(state='uncertain_spent', local_finished_at=now(), unused_time_refunded=False)
                    store.event(c, 'task.time_unknown', ident, {'reservation':key, 'reserved_seconds':timeout, 'unused_time_refunded':False}, 'runtime')
                else:
                    row = c.execute('SELECT value FROM kv WHERE key=?', ('elapsed:'+ident,)).fetchone()
                    total = float(json.loads(row[0])) if row else consumed+timeout
                    total = max(0., total-timeout+actual)
                    saved.update(state='settled_before_dispatch' if before_dispatch else 'settled',
                                 finished_at=now(), actual_seconds=actual,
                                 native_terminal_confirmed=not before_dispatch,
                                 dispatch_not_started=before_dispatch,
                                 native_thread_id=result['thread_id'], native_turn_id=result['turn_id'])
                    if before_dispatch:
                        saved['dispatch_stage']=result['dispatch_stage']
                    c.execute('UPDATE kv SET value=? WHERE key=?', (json.dumps(total), 'elapsed:'+ident))
                    store.event(c, 'task.time_settled', ident, {'reservation':key, 'actual_seconds':actual, 'elapsed_seconds':total, 'transport':'app_server_dynamic', 'dispatch_not_started':before_dispatch, 'native_terminal_confirmed':not before_dispatch}, 'runtime')
                c.execute('UPDATE kv SET value=? WHERE key=?', (json.dumps(saved), key))
        with runtime.mutex:
            if runtime.native_turns.get(ident) is record:
                runtime.native_turns.pop(ident, None)
