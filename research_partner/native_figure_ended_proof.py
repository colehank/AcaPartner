"""Read-only proof for one fresh native error with no candidate/domain action.

This deliberately narrow classifier raises on incomplete evidence. It does not
repair a Task, close request accounting, refund fees, grant permission or launch
anything. The trusted caller pins the original receipt and reservation; current
fee/account/stop/fresh-Task authorization remains the caller's responsibility.
"""
from contextlib import closing
from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
import time

from .native_figure_checkpoint import _file, _json, _root, read_figure_checkpoint
from .native_figure_evidence import _native_json
from .store import Problem, digest

CODE = 'native_ended_proof_invalid'
MODULES = {'acaworker-core.mjs', 'figure-host-plugin.mjs', 'figure-host.mjs',
           'figure-launch.py', 'figure-plugin.mjs', 'figure-tools.mjs', 'native-session-driver.mjs'}
EXPECTED = {'task_id', 'project_id', 'workspace_id', 'provider_id', 'attempt_id',
            'invocation', 'session_id', 'reservation_id', 'budget_file', 'original_receipt_sha256'}


def _need(condition, message):
    if not condition:
        raise Problem(message, CODE, 409)


def _absolute(value):
    path = Path(value)
    _need(path.is_absolute() and str(path.resolve()) == str(path), 'Exact nonsymlink absolute paths required')
    return path


def _read(path, inputs):
    with _root(path.parent) as parent, _file(parent, (path.name,)) as (fd, raw):
        _need(os.fstat(fd).st_nlink == 1, 'Proof input cannot be a hard link')
    inputs[str(path)] = digest(raw)
    return raw


def _stamp_time(value):
    _need(isinstance(value, str), 'Missing original timestamp')
    moment = datetime.fromisoformat(value.replace('Z', '+00:00'))
    _need(moment.tzinfo is not None, 'Timestamp needs an explicit timezone')
    return moment.timestamp()


def _unpack(row):
    _need(row is not None, 'Original saved row missing')
    value = dict(row)
    for field in ('payload', 'result', 'content', 'metadata'):
        if field in value:
            value[field] = json.loads(value[field])
    if 'archived' in value:
        value['archived'] = bool(value['archived'])
    return value


def _empty_directory(path):
    with _root(path) as fd:
        return not os.listdir(fd)


def _no_domain_rows(connection, task):
    for key in ('composition_task_candidate:' + task['id'], 'composition_tool_calls:' + task['id'],
                'main_figure_request:' + task['project_id'] + ':' + digest((task['id'] + ':composition').encode())):
        _need(connection.execute('SELECT 1 FROM kv WHERE key=?', (key,)).fetchone() is None,
              'Possible candidate or domain dispatch exists')
    _need(not connection.execute("SELECT 1 FROM objects WHERE json_extract(metadata,'$.origin_task_id')=? LIMIT 1", (task['id'],)).fetchone()
          and not connection.execute("SELECT 1 FROM revisions WHERE json_extract(snapshot,'$.metadata.origin_task_id')=? LIMIT 1", (task['id'],)).fetchone()
          and not connection.execute("SELECT 1 FROM events WHERE object_id=? AND kind='figure.domain_tool' LIMIT 1", (task['id'],)).fetchone(),
          'Registered candidate/history/domain event exists')


def _writer_observation(process, launch, event_path):
    _need(type(process.get('pid')) is int and process['pid'] > 0
          and isinstance(process.get('start_ticks'), str) and process['start_ticks'].isdigit()
          and process.get('identity_kind') == 'live_command' and process.get('uid') == os.getuid()
          and re.fullmatch('[a-f0-9]{64}', process.get('command_sha256', '')),
          'Original registered process identity missing')
    _need(type(launch.get('owned_child_pid')) is int and launch['owned_child_pid'] > 0,
          'Original owned native child identity missing')
    for pid in (process['pid'], launch['owned_child_pid']):
        # PID reuse is deliberately not accepted as a shortcut to this proof.
        _need(not (Path('/proc') / str(pid)).exists(), 'Original writer PID remains present or was reused')
    paths = (event_path, event_path.parent / 'session.lock')
    identities = {}
    for path in paths:
        info = path.lstat()
        _need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Native writer file identity invalid')
        identities[(info.st_dev, info.st_ino)] = str(path)
    uninspectable = set()
    for folder in Path('/proc').iterdir():
        if not folder.name.isdigit():
            continue
        try:
            if folder.stat().st_uid != os.getuid():
                continue
            descriptors = list((folder / 'fd').iterdir())
        except FileNotFoundError:
            continue
        except PermissionError:
            uninspectable.add(int(folder.name)); continue
        for descriptor in descriptors:
            try:
                info = descriptor.stat()
            except FileNotFoundError:
                continue
            except PermissionError:
                uninspectable.add(int(folder.name)); continue
            _need((info.st_dev, info.st_ino) not in identities, 'Native session still has an open writer descriptor')
    info = paths[1].stat()
    identity = f'{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino}'
    _need(not any(identity in line for line in Path('/proc/locks').read_text().splitlines()),
          'Native session still has a lock holder')
    return {'observed_at': time.time(), 'registered_pid': process['pid'],
            'registered_start_ticks': process['start_ticks'], 'command_sha256': process['command_sha256'],
            'owned_child_pid': launch['owned_child_pid'], 'pids_absent': True,
            'visible_session_descriptors_absent': True, 'session_lock_holders_absent': True,
            'uninspectable_same_uid_pids': sorted(uninspectable),
            'scope': 'Original registered launcher and owned native writer ended; no global hidden-process guarantee'}


def classify_ended_error(workspace, control_directory, *, expected):
    """Return an actual-input proof or raise ``native_ended_proof_invalid``.

    ``expected`` must be pinned by the caller to the original reservation/ref:
    task/project/workspace/provider/attempt/invocation/session/reservation IDs,
    existing parent budget_file and original_receipt_sha256. No report Boolean
    is accepted. Only this no-domain-call error class is supported, not generic
    failed native attempts. Secret process fields and credential files are not
    exposed; missing usage always remains unknown.
    """
    try:
        return _classify(workspace, control_directory, expected)
    except Problem as error:
        if error.code == CODE:
            raise
        raise Problem('Incomplete or mismatched native saved evidence', CODE, 409) from error
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError,
            OverflowError, RecursionError, sqlite3.Error) as error:
        raise Problem('Incomplete or unreadable original ended-error evidence', CODE, 409) from error


def _classify(workspace, control_directory, expected):
    _need(isinstance(expected, dict) and set(expected) == EXPECTED, 'Explicit complete original reservation/ref required')
    for field in ('task_id', 'project_id', 'workspace_id', 'provider_id'):
        _need(isinstance(expected[field], str) and re.fullmatch('[A-Za-z0-9_.:-]{1,200}', expected[field]), 'Invalid original identity')
    _need(type(expected['invocation']) is int and expected['invocation'] == 1
          and isinstance(expected['attempt_id'], str) and re.fullmatch('[a-f0-9]{24}', expected['attempt_id'])
          and isinstance(expected['session_id'], str) and re.fullmatch('session-[A-Za-z0-9_-]{1,160}', expected['session_id'])
          and expected['reservation_id'] == expected['task_id'] + ':1'
          and isinstance(expected['original_receipt_sha256'], str) and re.fullmatch('[a-f0-9]{64}', expected['original_receipt_sha256']),
          'Original fresh attempt/reservation identity invalid')
    workspace = _absolute(workspace); directory = _absolute(control_directory)
    _need(directory == workspace.parent / 'agent-control' / digest(str(workspace))[:20] / expected['task_id'],
          'Control directory is not the original workspace-bound Task directory')
    instance = directory / 'figure-instance'; inputs = {}
    get = lambda relative: _json(_read(directory / relative, inputs))
    intent = get('native-figure-intent.json'); preparation = get('figure-instance/preparation.json')
    frozen_context = _read(directory / 'evidence.json', inputs)
    prompt = _read(instance / 'control/prompt.txt', inputs).decode('utf8')
    original = get('provider-receipt.json')
    _need(inputs[str(directory / 'provider-receipt.json')] == expected['original_receipt_sha256'], 'Original receipt digest changed')
    _need(original.get('transport') == 'deepseek_harness_native' and original.get('route') == 'deepseek_harness'
          and original.get('feature') == 'deepseek_task_figure_tools_v1'
          and original.get('new_dispatch_not_retried') is True and original.get('resumed_from') is None
          and original.get('actual_bill_usd') is None and intent.get('resume_session') is None,
          'Not the original bounded fresh native route with unknown billing')
    process = get('process.json'); outer = get('process-1.json'); launch = get('figure-instance/control/launch-attempt.json')
    _need(not _read(directory / 'process-1.stdout', inputs).strip(), 'Unknown local candidate/output remains')
    _need(_empty_directory(instance / 'capsule'), 'Unknown capsule output remains')
    budget = _json(_read(_absolute(expected['budget_file']), inputs))
    reservations = [row for row in budget['reservations'] if row.get('id') == expected['reservation_id']]
    _need(len(reservations) == 1, 'Original reservation absent or ambiguous')
    reservation = reservations[0]; evidence = reservation['evidence']
    _need(reservation['kind'] == 'model' and reservation['state'] == 'result_unknown', 'Only original result_unknown accounting is supported')
    for field in ('task_id', 'provider_id', 'attempt_id', 'invocation'):
        _need(intent[field] == original[field] == evidence[field] == expected[field], 'Original intent/receipt/reservation identity mismatch')
    if evidence.get('inspection') is not None:
        _need(evidence['inspection']['original_receipt_sha256'] == expected['original_receipt_sha256'], 'Supplemental inspection points at another original receipt')
    else:
        _need(evidence == original, 'Reservation evidence differs from the original receipt')
    _need(evidence.get('session_id') == expected['session_id'] and evidence.get('native_terminal_confirmed') is True,
          'Reservation lacks its original independently inspected session')
    database = workspace / 'research.sqlite3'
    _need(stat.S_ISREG(database.lstat().st_mode) and database.lstat().st_nlink == 1,
          'Original database must be a single ordinary file')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row; connection.execute('PRAGMA query_only=ON'); connection.execute('BEGIN')
        task = _unpack(connection.execute('SELECT * FROM tasks WHERE id=?', (expected['task_id'],)).fetchone())
        _need(task['project_id'] == expected['project_id'] and task['payload']['provider_id'] == expected['provider_id']
              and task['payload']['kind'] == 'figure_composition' and task['status'] == 'waiting_resource'
              and type(task['attempts']) is int and task['attempts'] == 1 and task['payload']['target_id'] is None
              and task['result'].get('failure_code') == 'provider_checkpoint_missing'
              and set(task['result']) <= {'details', 'failure_code'}, 'Original Task outcome/candidate class not supported')
        _need(task['result'].get('details') == {'provider_checkpoint': original}, 'Original saved result/receipt differs or has unknown output')
        plan = task['payload']['context']['figure_composition']; definition = plan['native_definition']
        _need(plan['native_transport'] == 'deepseek_harness_native' and plan['adopted_head_changed'] is False
              and digest({k: v for k, v in plan.items() if k != 'sha256'}) == plan['sha256']
              and digest({k: v for k, v in definition.items() if k != 'sha256'}) == definition['sha256']
              and preparation['definition'] == definition, 'Original frozen native plan/definition changed')
        _need(type(reservation['request_cap']) is int and 1 <= reservation['request_cap'] <= 4
              and type(definition['max_requests']) is int and reservation['request_cap'] == definition['max_requests']
              and type(reservation['accounted_requests']) is int
              and reservation['accounted_requests'] == reservation['request_cap']
              and type(reservation.get('released_unused_requests', 0)) is int and reservation.get('released_unused_requests', 0) == 0
              and type(reservation['native_fee_planning_reserved_usd']) in (int, float)
              and math.isfinite(reservation['native_fee_planning_reserved_usd']) and reservation['native_fee_planning_reserved_usd'] > 0
              and reservation['native_fee_planning_reserved_usd'] == definition['budget_usd']
              and reservation['native_authorization_reference'] == definition['authorization_reference'], 'Original retained accounting/ref mismatch')
        for key, value in [('workspace_id', expected['workspace_id']),
                           ('provider_invocations:' + task['id'], 1), ('native_figure_launch_intent:' + task['id'], intent)]:
            row = connection.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
            _need(row is not None and json.loads(row[0]) == value, 'Saved original invocation/intent/workspace differs')
        lease = connection.execute("SELECT json_extract(value,'$.state') AS state,json_extract(value,'$.runtime_id') AS runtime_id,json_extract(value,'$.finished_at') AS finished_at FROM kv WHERE key=?", ('execution:' + task['id'],)).fetchone()
        _need(lease is not None and lease['state'] == 'finished' and lease['runtime_id'] and lease['finished_at'], 'Original execution lease remains active or unknown')
        _need(_stamp_time(lease['finished_at']) >= _stamp_time(process['finished_at']), 'Lease closed before its writer')
        _no_domain_rows(connection, task)
        heads = {}; physical_definitions = {}
        for ident, ref in intent['human_heads'].items():
            obj = _unpack(connection.execute('SELECT * FROM objects WHERE id=?', (ident,)).fetchone())
            _need(obj['project_id'] == task['project_id'] and obj['revision'] == ref['revision'] and digest(obj) == ref['sha256'], 'Original human head changed')
            heads[ident] = ref
            if obj['content'].get('definition_sha256'):
                physical_definitions[ident] = obj['content']['definition_sha256']
        _need(heads and all(ref['id'] in heads for ref in plan['fixed_sources']), 'Frozen original human/source heads incomplete')
        task_sha = digest(task); lease_public = dict(lease)
    _need(digest(frozen_context) == intent['evidence_sha256'] and digest(prompt.encode()) == intent['prompt_sha256']
          and inputs[str(instance / 'preparation.json')] == intent['preparation_sha256'], 'Frozen material/prompt/preparation bytes changed')
    _need(set(definition['modules']) == MODULES, 'Unsupported original native module set')
    for name, expected_sha in definition['modules'].items():
        _need(digest(_read(instance / 'plugin' / name, inputs)) == expected_sha, 'Original native module changed')
    _need(digest(_read(instance / 'launch.py', inputs)) == definition['modules']['figure-launch.py'], 'Original launcher changed')
    scope = get('figure-instance/control/scope.json')
    _need(digest((instance / 'control/scope.json').read_bytes()) == preparation['contract_sha256']
          and scope['task_id'] == task['id'] and scope['project_id'] == task['project_id']
          and scope['plan_sha256'] == plan['sha256'] and scope['egress_sha256'] == plan['egress_sha256']
          and scope['definition'] == definition, 'Original scope contract mismatch')
    binding = {'task_id': task['id'], 'project_id': task['project_id'], 'plan_sha256': plan['sha256'],
               'egress_sha256': plan['egress_sha256'], 'definition_sha256': definition['sha256'],
               'contract_sha256': preparation['contract_sha256'], 'provider': definition['provider'],
               'model': definition['model'], 'session_id': expected['session_id']}
    checkpoint = read_figure_checkpoint(instance, binding, allow_missing_usage_for_accounting=True)
    _need(checkpoint is not None and checkpoint['event_range_verified'] is True, 'Complete original durable range missing')
    receipt = checkpoint['receipt']; events = checkpoint['attempt_events']; header = checkpoint['header']
    _need(checkpoint['events_sha256'] == evidence.get('events_sha256')
          and checkpoint['receipt_sha256'] == evidence.get('driver_receipt_sha256'),
          'Original reservation does not pin this complete native log/receipt')
    _need(receipt['phase'] == 'flushed' and receipt['checkpoint'] is None and receipt['reason'].get('kind') == 'error'
          and header.get('isSeeded') is False and not header.get('parentSession') and header.get('delegationDepth', 0) == 0
          and 'origin' not in header and len(events) >= 3, 'Not a complete original fresh error turn')
    _need(sum(event['type'] == 'turn/start' for event in events) == sum(event['type'] == 'turn/end' for event in events) == 1
          and events[-1]['type'] == 'turn/end' and events[-1]['data']['reason'] == receipt['reason'], 'Original turn terminal contradicts receipt')
    error = _json(receipt['reason']['error']['message'].encode())
    _need(error == {'code': 'integrity', 'error': 'Outgoing native tool catalog changed',
                   'http_status': 409, 'write_outcome_uncertain': False}
          and error['write_outcome_uncertain'] is False and type(error['http_status']) is int,
          'This proof supports only the original bounded catalog-guard error class')
    setup = {'permission/preset', 'sandbox/mode', 'approval/policy', 'agent-preset/selected', 'model/selection', 'session/title'}
    _need(all(event['type'] in setup for event in checkpoint['events'][:receipt['first_seq']])
          and all(type(event.get('time')) is int and event['time'] >= 0 for event in checkpoint['events']),
          'Original event prefix or timestamps contain unknown execution')
    allowed = {'agent/inbox/spliced', 'turn/start', 'step/start', 'system/message', 'user/message',
               'request/header', 'request/context', 'assistant/attempt', 'session/title', 'step/end', 'turn/end'}
    _need(all(event['type'] in allowed for event in events), 'Unknown action or possible candidate in durable events')
    messages = [event['data'] for event in events if event['type'] == 'user/message']
    _need(len(messages) == 1 and messages[0]['content'] == [{'type': 'text', 'text': prompt}]
          and all(event['data'].get('stream') == [] for event in events if event['type'] == 'assistant/attempt'), 'Prompt differs or assistant/tool output is unknown')
    queued = events[0]['data']
    _need(events[0]['type'] == 'agent/inbox/spliced' and queued.get('target') == 'next-turn'
          and type(queued.get('start')) is int and queued['start'] == 0 and len(queued.get('inserted', [])) == 1
          and queued['inserted'][0].get('content') == messages[0]['content']
          and queued['inserted'][0].get('id') == messages[0].get('id'), 'Original fixed prompt enqueue differs')
    tools = receipt['figure_task_binding']['tools']
    _need(digest(_native_json({k: v for k, v in tools.items() if k != 'sha256'}).encode()) == tools['sha256']
          and tools['task_id'] == task['id'] and tools['project_id'] == task['project_id']
          and tools['session_id'] == expected['session_id'] and tools['plan_sha256'] == plan['sha256']
          and tools['fixed_sources'] == plan['fixed_sources'] and type(tools['closed']) is bool
          and type(tools['executed_tool_calls']) is int and tools['executed_tool_calls'] == 0
          and tools['receipts'] == [] and tools['write_outcome_uncertain'] is False, 'Unknown or uncertain domain tool outcome')
    _need(receipt['figure_task_binding'].get('streams') == []
          and receipt['figure_task_binding'].get('stream_outcome_unknown') is False,
          'This original pre-stream error class has unknown stream state')
    index = _json(_read(workspace / 'projects/.project-index.json', inputs)); folder = index['projects'][task['project_id']]
    _need(isinstance(folder, str) and Path(folder).name == folder and folder not in ('.', '..'), 'Invalid original project folder')
    project_root = workspace / 'projects' / folder
    _need(_empty_directory(project_root / '.figure-definitions/pending'), 'Unresolved definition intent exists')
    for ident, expected_sha in physical_definitions.items():
        raw = _read(project_root / 'figures' / ident / 'main/figure.yaml', inputs)
        _need(len(raw) <= 1024 * 1024 and digest(raw) == expected_sha, 'Unregistered physical main edit exists')
    _need(process['state'] == 'finished' and process.get('deadline_triggered') is False
          and process.get('deadline_stop_errors') == [] and launch['task_id'] == task['id']
          and launch['mode'] == 'fresh_native' and launch['child_closed'] is True
          and type(launch['automatic_retries']) is int and launch['automatic_retries'] == 0
          and all(type(value.get('returncode')) is int and value['returncode'] == 1 for value in (process, outer, launch, original)), 'Writer closure records missing or contradictory')
    _need(_stamp_time(receipt['started_at']) <= _stamp_time(receipt['finished_at']) <= _stamp_time(launch['finished_at'])
          <= _stamp_time(process['finished_at']) and _stamp_time(process['started_at']) == _stamp_time(outer['started_at']), 'Original writer/turn timeline contradicts')
    _need(process['cwd'] == str(directory) and process['reservation_key'].startswith('time_reservation:' + task['id'] + ':')
          and outer['reservation_key'] == process['reservation_key'], 'Original process belongs to another Task reservation')
    writer = _writer_observation(process, launch, Path(checkpoint['event_path']))
    inputs[checkpoint['event_path']] = checkpoint['physical_sha256']
    inputs[str(instance / 'control/native-receipt.json')] = checkpoint['receipt_sha256']
    # Recheck every read input; a concurrent edit invalidates this observation.
    for path, sha in list(inputs.items()):
        _need(digest(_read(Path(path), {})) == sha, 'Proof input changed during observation')
    _need(_empty_directory(instance / 'capsule') and _empty_directory(project_root / '.figure-definitions/pending'),
          'Candidate output or definition intent appeared during proof read')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.row_factory = sqlite3.Row; connection.execute('PRAGMA query_only=ON')
        current = _unpack(connection.execute('SELECT * FROM tasks WHERE id=?', (task['id'],)).fetchone())
        lease_now = connection.execute("SELECT json_extract(value,'$.state') AS state,json_extract(value,'$.runtime_id') AS runtime_id,json_extract(value,'$.finished_at') AS finished_at FROM kv WHERE key=?", ('execution:' + task['id'],)).fetchone()
        _need(digest(current) == task_sha and lease_now and dict(lease_now) == lease_public,
              'Original Task/lease changed during proof read')
        _no_domain_rows(connection, task)
        for ident, ref in heads.items():
            obj = _unpack(connection.execute('SELECT * FROM objects WHERE id=?', (ident,)).fetchone())
            _need(obj['revision'] == ref['revision'] and digest(obj) == ref['sha256'],
                  'Original human head changed during proof read')
    return {'version': 1, 'classification': 'ended_error_no_candidate_no_domain_write', 'verified': True,
            'original_ref': {**{k: expected[k] for k in EXPECTED if k != 'budget_file'}, **binding,
                             'workspace': str(workspace), 'control_directory': str(directory)},
            'inputs_sha256': inputs, 'task_snapshot_sha256': task_sha, 'execution_lease': lease_public,
            'terminal_reason': receipt['reason'], 'events_sha256': checkpoint['events_sha256'],
            'first_seq': receipt['first_seq'], 'final_seq': receipt['final_seq'], 'writer': writer,
            'saved_tools_closed': tools['closed'], 'no_registered_candidate': True, 'human_heads': heads,
            'usage_missing': checkpoint['usage_missing'], 'usage_sha256': checkpoint['usage_sha256'],
            'actual_requests': None, 'actual_bill_usd': None, 'accounting_state': reservation['state'],
            'retained_request_cap': reservation['request_cap'],
            'retained_fee_planning_usd': reservation['native_fee_planning_reserved_usd'],
            'fee_authorization': False, 'old_task_resume_authorized': False, 'fresh_task_authorized': False}
