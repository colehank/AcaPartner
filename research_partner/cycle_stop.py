"""Local cycle execution observations. Reads never send a signal or a model call.

Database pause/cancel fences dispatch immediately. Completion is a separate
owner observation; an old runtime or an absent receipt is not proof of a stop.
These records do not assert remote provider cancellation or fee settlement.
"""
import json
from pathlib import Path
from .store import now


def _quiet_group(record):
    """Conservative /proc observation of the exact locally registered group."""
    from .runtime import process_identity
    try:
        pid = record['pid']; owner = record['uid']; started = record['start_ticks']
        if type(pid) is not int or pid <= 0 or type(owner) is not int or owner < 0: return False
        if not isinstance(started, str) or not started or not started.isascii() or not started.isdecimal(): return False
        current = process_identity(pid)
        if current is not None:
            if any(str(current[k]) != str(record[k]) for k in ('pid', 'start_ticks', 'uid')): return False
            if current['state'] != 'Z': return False
        for path in Path('/proc').iterdir():
            if not path.name.isdigit(): continue
            try:
                stat = (path / 'stat').read_text().rsplit(')', 1)[1].split()
                if int(stat[2]) == pid and int(stat[3]) == pid and stat[0] != 'Z': return False
            except (FileNotFoundError, ProcessLookupError): continue
        return True
    except (OSError, KeyError, ValueError, TypeError, IndexError): return False


def completion(runtime, ident, token):
    """Called only by the original worker finally, while its mutex is held."""
    if ident in runtime.children or ident in runtime.native_turns: return None
    try:
        path = runtime.runs / ident / 'process.json'
        record = json.loads(path.read_text()) if path.exists() else None
        if record is not None and (not isinstance(record, dict) or not _quiet_group(record)): return None
        with runtime.store.connect() as c:
            reservations = {row[0]: json.loads(row[1]) for row in c.execute(
                'SELECT key,value FROM kv WHERE key LIKE ?', ('time_reservation:' + ident + ':%',))}
        if any(not isinstance(r, dict) for r in reservations.values()): return None
        current = {k: r for k, r in reservations.items() if r.get('execution_token') == token}
        if any(r.get('state') != 'settled' or r.get('runtime_id') != runtime.runtime_id
               for r in current.values()): return None
        # process.json is only the latest execution. A settled time reservation
        # is not proof that an earlier process group has disappeared.
        starts = {}
        directory = runtime.runs / ident
        for start_path in directory.glob('process-*.started.json'):
            start = json.loads(start_path.read_text())
            if not isinstance(start, dict): return None
            if start.get('execution_token') != token: continue
            key = start.get('reservation_key'); index = start.get('process_index')
            if not isinstance(key, str) or key not in current or key in starts: return None
            if type(index) is not int or index < 1 or start_path.name != f'process-{index}.started.json': return None
            finish = json.loads((directory / f'process-{index}.finished.json').read_text())
            if not isinstance(finish, dict): return None
            identity = ('pid', 'start_ticks', 'uid', 'task_id', 'execution_token', 'reservation_key', 'process_index')
            if any(start.get(k) is None or start[k] != finish.get(k) for k in identity): return None
            if start['task_id'] != ident or finish.get('state') != 'finished' or not finish.get('finished_at'): return None
            if not _quiet_group(finish): return None
            starts[key] = start
        if set(starts) != set(current): return None
        if current and (not record or record.get('execution_token') != token or
                        record.get('state') != 'finished' or not record.get('finished_at')): return None
        return {'version': 1, 'execution_token': token, 'runtime_id': runtime.runtime_id,
                'finished_at': now(), 'scope': 'local_execution_only'}
    except (OSError, ValueError, TypeError, KeyError): return None


def _matching_completion(receipt, lease):
    if not isinstance(receipt, dict): return False
    if type(receipt.get('version')) is not int or receipt['version'] != 1: return False
    if receipt.get('scope') != 'local_execution_only': return False
    if not isinstance(receipt.get('finished_at'), str) or not receipt['finished_at'].strip(): return False
    for original, observed in (('token', 'execution_token'), ('runtime_id', 'runtime_id')):
        value = lease.get(original)
        if not isinstance(value, str) or not value.strip() or value != receipt.get(observed): return False
    return lease.get('state') in {'revoked', 'finished'}


def observation(app, parent):
    """Public, identity-bound stop state; no leases, PIDs or private paths leak."""
    if parent['status'] not in {'paused', 'cancelled'}: return None
    state = parent['result']['cycle']; runner = app.runner
    rows = []
    for ref in state['children']:
        ident = ref['id']; task = app.store.task(ident)
        lease = app.store.setting('execution:' + ident, {})
        if not isinstance(lease, dict): lease = {}
        pending = False
        if runner is not None:
            with runner.mutex:
                pending = ident in runner.active or ident in runner.children or ident in runner.native_turns
        receipt = lease.get('cycle_stop_receipt')
        if lease.get('state') == 'active': status, reason = 'unknown', '执行授权尚未完成撤销，不能确认停止'
        elif pending: status, reason = 'draining', '本地执行者仍在结束当前工作'
        elif _matching_completion(receipt, lease):
            status, reason = 'stopped', '原执行者已记录本次本地工作结束'
        elif task['attempts'] == 0 and not lease: status, reason = 'stopped', '子任务尚未派发'
        else: status, reason = 'unknown', '没有匹配本次执行的本地结束回执'
        rows.append({'id': ident, 'status': status, 'reason': reason})
    status = 'unknown' if any(r['status'] == 'unknown' for r in rows) else \
             'draining' if any(r['status'] == 'draining' for r in rows) else 'stopped'
    return {'version': 1, 'parent_id': parent['id'], 'epoch': state['epoch'],
            'status': status, 'dispatch_blocked': True, 'children': rows}
