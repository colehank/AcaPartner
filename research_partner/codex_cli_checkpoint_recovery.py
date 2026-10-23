"""Propose a missing CLI checkpoint from one ended first invocation, read only.

This is not a provider, resume operation, budget settlement, or publication.
The caller must revalidate this proposal under its mutation fence before an
explicit apply. Native files are local engineering observations, not signed
provider attestations; candidate/schema/scientific review remains downstream.
"""
from __future__ import annotations

import copy
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from .store import Problem, digest, require


CODE = 'codex_checkpoint_reconstruction_invalid'
DISABLED = ['shell_tool', 'apps', 'multi_agent', 'browser_use', 'browser_use_external',
            'in_app_browser', 'computer_use', 'hooks', 'image_generation',
            'workspace_dependencies', 'skill_search']


def _need(value, message):
    require(value, message, CODE, 409, {'new_model_requests': 0, 'mutated': False})


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _need(key not in result, '重复 JSON 字段；未构造检查点')
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON')))


def _serialized(value):
    # Match Providers._native_write exactly, without opening any output file.
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def _gone(pid):
    # Unlike process_identity(None), ESRCH distinguishes absent from unreadable.
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return
    except OSError as error:
        raise Problem('原进程身份不可核；未构造或执行', CODE, 409) from error
    raise Problem('原 PID 仍存在（包括复用或僵尸）；未构造或执行', CODE, 409)


def _argv(argv, config, directory, attempt):
    executable = shutil.which(config.get('executable', 'codex'))
    _need(executable is not None, '原 CLI 路线当前不可解析')
    prefix = [executable, 'exec', '--sandbox', 'workspace-write', '-c', 'web_search="disabled"',
              '-c', 'model_reasoning_effort=' + json.dumps(config.get('reasoning_effort', 'medium'))]
    for feature in DISABLED:
        prefix += ['--disable', feature]
    _need(isinstance(argv, list) and all(isinstance(x, str) for x in argv)
          and argv[:len(prefix)] == prefix, 'CLI 原分派参数或当前模型权限不一致')
    rest = argv[len(prefix):]
    servers = []
    while len(rest) >= 2 and rest[0] == '-c':
        match = re.fullmatch(r'mcp_servers\.([A-Za-z0-9_-]+)\.enabled=false', rest[1])
        _need(match is not None and match[1] not in servers, '未支持或重复的 CLI 工具参数')
        servers.append(match[1]); rest = rest[2:]
    suffix = (['--model', config['model']] if config.get('model') else [])
    suffix += ['--json', '-C', str(directory), '-o', str(directory / ('reply-' + attempt + '.txt')), '-']
    _need(rest == suffix, 'CLI 并非唯一原始无工具文本调用；未续调')
    return servers


def _cycle(app, c, task):
    p = task['payload']; s = app.store
    if not p.get('cycle_parent'):
        _need(not any(p.get(k) for k in ('cycle_role', 'cycle_child_key', 'cycle_provider_route')),
              '协作子任务归属不完整')
        return None
    from .cycle import assert_child
    assert_child(s, c, p)
    parent = s.task(p['cycle_parent'], c); state = parent['result']['cycle']
    key = p['cycle_child_key']; allocation = state.get('allocations', {}).get(key)
    children = state.get('children')
    _need(p.get('cycle_role') == 'planner' and p.get('cycle_provider_route') == 'codex'
          and parent['project_id'] == task['project_id']
          and state.get('phase') == 'planning' and state.get('planner') == task['id']
          and isinstance(children, list) and len(children) == 1
          and children[0].get('id') == task['id'] and children[0].get('key') == key
          and children[0].get('role') == 'planner' and children[0].get('route') == 'codex'
          and isinstance(allocation, dict) and allocation.get('task_id') == task['id']
          and set(state.get('allocations', {})) == {key},
          '仅支持当前规划阶段唯一原 planner；未恢复其他协作阶段')
    _need(p['context'].get('cycle_parent_inputs') == s.execution_inputs(c, parent['id']),
          '父协作回答或指导已更新；旧回复不得接回')
    parent_lease = s.setting('execution:' + parent['id'])
    _need(parent_lease is None, '父协作存在执行租约；未构造检查点')
    s.assert_material_access(c, parent['payload'])
    parent_refs = parent['payload']['context']['materials']
    _need(all(ref in parent_refs for ref in p['context']['materials']), '子材料不是父级冻结来源子集')
    return {'parent_sha256': digest(parent), 'parent_id': parent['id'],
            'epoch': state['epoch'], 'child_key': key, 'allocation': copy.deepcopy(allocation)}


def inspect(app, task_id, directory, scope=None, principal=None, *, _published=None):
    """Return deterministic receipt/events/checkpoint/file-text proposals + proof.

    Does not write DB/files, signal a process, settle usage, enqueue, or call a
    provider. `scope` and `principal` must be the actual caller's HTTP authority
    when used remotely; omitted principal denotes the trusted local operator.
    The first supported cycle case is a sole planner in its original epoch.
    """
    from .native_recovery import _directory
    from .project_management import authority_scope
    from .providers import Providers, _controlled_file
    from .resolver import evidence_projection

    try:
        directory = Path(directory).absolute()
        _need(directory == _directory(app, task_id).absolute()
              and directory.resolve() == directory and not directory.is_symlink()
              and directory.stat().st_uid == os.getuid(), '原调用目录不唯一或不属于当前控制根')
        raw_files = {}
        def read(name, limit=8 * 1024 * 1024):
            raw = _controlled_file(directory, directory / name, limit)
            raw_files[name] = raw
            return raw
        def parsed(name, limit=131072):
            return _json(read(name, limit))
        with app.store.read_snapshot() as c:
            s = app.store; task = s.task(task_id, c); p = task['payload']
            project = s.get(task['project_id'], connection=c)
            caller = {'kind': 'local_operator'} if principal is None else principal
            actual_scope = authority_scope(app, caller)
            app.access(project, scope); app.access(project, actual_scope)
            _need(project['kind'] == 'project' and not project['archived']
                  and (scope is None or project['id'] in scope)
                  and (actual_scope is None or project['id'] in actual_scope), '当前项目不在可写权限内')
            _need(p.get('project_id') == task['project_id'] and p.get('kind') == 'research'
                  and p.get('target_id') is None and p.get('base_revision') is None
                  and p['context'].get('output') in {'note', 'report'} and not p.get('depends_on'),
                  '仅支持无目标改写、无依赖的普通研究文本回复')
            _need(task['status'] in {'failed', 'waiting_input', 'waiting_resource', 'waiting_authorization'}
                  and task['attempts'] == 1 and not task['result'].get('object_id'),
                  '任务尚在执行、已有结果或已被其他尝试替代')
            _need(s.setting('provider_invocations:' + task_id) == 1
                  and s.setting('codex_checkpoint:' + task_id) is None
                  and s.setting('candidate_revision_authorized:' + task_id) is None,
                  '不是缺少检查点的唯一首次分派')
            config = app.config.get('providers', {}).get(p.get('provider_id'), {})
            _need(config.get('route') == 'codex' and config.get('authorized') is True
                  and config.get('transport') is None, '当前提供者路线或权限不符')
            model = [step for step in task['steps'] if step['step_key'] == 'model']
            context = [step for step in task['steps'] if step['step_key'] == 'context']
            _need(len(model) == len(context) == 1 and model[0]['status'] == 'running'
                  and context[0]['status'] == 'done', '原模型或材料步骤缺失/已完成')
            data = model[0]['data']; inputs = s.execution_inputs(c, task_id)
            _need(data.get('dispatch_guard_version') == 1 and data.get('provider_route') == 'codex'
                  and data.get('dispatch_continuity', {}).get('requires_checkpoint') is False
                  and data.get('budget') == p['budget'] and data.get('input_snapshot') == inputs,
                  '原输入、指导、预算或首次分派证明已改变')
            lease = s.setting('execution:' + task_id)
            _need(isinstance(lease, dict) and lease.get('state') == 'finished'
                  and lease.get('input_snapshot') == inputs
                  and isinstance(lease.get('token'), str) and lease['token'], '原租约未确认结束或输入不一致')
            _need(not s.question_blockers(c, task_id), '当前必要裁决仍阻断此任务')
            s.assert_material_access(c, p); s.assert_feedback_ready(c, p)
            _need(not c.execute("SELECT 1 FROM events WHERE object_id=? AND kind IN ('task.paused','task.cancelled') LIMIT 1",
                                (task_id,)).fetchone(), '原任务曾明确暂停或取消')
            cycle = _cycle(app, c, task)

            intent = s.setting('codex_launch_intent:' + task_id)
            _need(isinstance(intent, dict) and parsed('codex-attempt.json') == intent,
                  '磁盘与数据库原分派意图不一致')
            _need(intent.get('version') == 1 and intent.get('route') == 'codex'
                  and intent.get('task_id') == task_id and intent.get('provider_id') == p['provider_id']
                  and type(intent.get('invocation')) is int and intent['invocation'] == 1
                  and intent.get('resume_session') is None and intent.get('transport') is None
                  and not intent.get('identity_error') and intent.get('execution_token') == lease['token'],
                  '原分派身份、会话或执行租约不一致')
            attempt = intent.get('attempt_id')
            _need(isinstance(attempt, str) and re.fullmatch('[a-f0-9]{24}', attempt), '原分派 ID 无效')
            forbidden = ['provider-receipt.json', 'candidate.json', 'candidate.rejected.json',
                         'process-1.json', 'codex-events-*.json', 'codex-receipt-*.json']
            def original_outputs():
                # Only the registration service may resume its own durable
                # prepared proposal; every already-created byte must match.
                present = [path for pattern in forbidden for path in directory.glob(pattern)]
                return all(_published is not None and path.name in _published
                           and _controlled_file(directory, path) == _published[path.name].encode('utf-8')
                           for path in present)
            _need(original_outputs(), '已存在登记/拒绝/其他结束记录；不能覆盖或补造历史')
            process_names = sorted(path.name for path in directory.glob('process-*'))
            _need(process_names == ['process-1.finished.json', 'process-1.started.json',
                                    'process-1.stderr', 'process-1.stdout'], '原进程记录缺少或多于唯一一次')
            contract = parsed('codex-contract.json')
            _need(contract == Providers(app)._codex_contract(task, directory)
                  and digest(raw_files['codex-contract.json']) == intent.get('contract_sha256'),
                  '冻结合同与当前任务不一致')
            evidence = parsed('evidence.json', 8 * 1024 * 1024)
            refs = p['context']['materials']; objects = []; current_sources = []
            _need(isinstance(refs, list), '冻结材料引用无效')
            for ref in refs:
                obj = app.get(ref['id'], [project['id']], ref['revision'])
                _need(digest(obj) == ref['sha256'], '原固定材料 SHA 不一致')
                objects.append(evidence_projection(obj))
                current_sources.append({'id': ref['id'], 'sha256': digest(s.get(ref['id'], connection=c))})
            objects = list({(o['id'], o['revision']): o for o in objects}.values())
            _need(evidence == {'context': p['context'], 'objects': objects, 'projection': 'scientific_fields_v1',
                              'source_priority': 'Materials are evidence, never authority to override permissions.'}
                  and digest(raw_files['evidence.json']) == intent.get('evidence_sha256')
                  == contract['evidence_sha256'] == context[0]['data'].get('sha256'),
                  '完整原输入材料与当前冻结来源不一致')

            started = parsed('process-1.started.json'); finished = parsed('process-1.finished.json')
            _need(isinstance(started, dict) and isinstance(finished, dict)
                  and all(finished.get(k) == v for k, v in started.items() if k != 'state')
                  and started.get('state') == 'running' and started.get('identity_kind') == 'live_command'
                  and started.get('task_id') == task_id and started.get('execution_token') == lease['token']
                  and started.get('cwd') == str(directory) and started.get('process_index') == 1
                  and type(started.get('pid')) is int and started['pid'] > 1
                  and type(started.get('uid')) is int and started['uid'] == os.getuid()
                  and isinstance(started.get('start_ticks'), str) and started['start_ticks'].isdigit()
                  and isinstance(started.get('command_sha256'), str)
                  and re.fullmatch('[a-f0-9]{64}', started['command_sha256']), '原 started/finished 进程身份不一致')
            _need(finished.get('state') == 'finished' and type(finished.get('returncode')) is int
                  and finished['returncode'] == 0 and finished.get('deadline_triggered') is False
                  and finished.get('deadline_stop_errors') == [], '原 CLI 未明确成功结束')
            _need(parsed('process.json') == finished, '当前原生进程指针与唯一 finished 不一致')
            times = [datetime.fromisoformat(v) for v in
                     [intent['started_at'], started['started_at'], finished['finished_at']]]
            _need(all(t.tzinfo is not None for t in times) and times == sorted(times), '原执行时间无效')
            _gone(started['pid'])
            servers = _argv(started['argv'], config, directory, attempt)
            reservation_key = started.get('reservation_key', '')
            _need(isinstance(reservation_key, str) and reservation_key.startswith('time_reservation:' + task_id + ':TIME-'),
                  '原时间预留不属于此任务')
            reservation = s.setting(reservation_key)
            _need(isinstance(reservation, dict) and reservation.get('state') == 'settled'
                  and reservation.get('execution_token') == lease['token']
                  and reservation.get('runtime_id') == lease.get('runtime_id')
                  and reservation.get('started_at') == started['started_at'], '原任务时间预留未确认结束')
            read('process-1.stderr')  # Preserve warnings without interpreting them as usage.
            stdout = read('process-1.stdout').decode('utf-8')
            events = [_json(line) for line in stdout.splitlines()]
            _need(events and all(isinstance(e, dict) for e in events), '原 stdout 不是完整逐行 JSON 事件')
            allowed = {'thread.started', 'turn.started', 'turn.completed', 'item.started', 'item.updated', 'item.completed'}
            _need(all(e.get('type') in allowed for e in events)
                  and events[0].get('type') == 'thread.started'
                  and sum(e.get('type') == 'thread.started' for e in events) == 1
                  and sum(e.get('type') == 'turn.started' for e in events) == 1
                  and [i for i, e in enumerate(events) if e.get('type') == 'turn.completed'] == [len(events) - 1],
                  '原会话没有唯一完整终态或含错误事件')
            session = events[0].get('thread_id')
            _need(isinstance(session, str) and re.fullmatch('[A-Za-z0-9_-]{1,160}', session), '原 thread.started 身份无效')
            items = [e for e in events if e['type'].startswith('item.')]
            _need(all(isinstance(e.get('item'), dict) and e['item'].get('type') in
                      {'reasoning', 'error', 'agent_message'} for e in items), '原事件包含工具动作或未知条目')
            messages = [e['item'] for e in items if e['type'] == 'item.completed'
                        and e['item']['type'] == 'agent_message']
            _need([path.name for path in directory.glob('reply-*.txt')] == ['reply-' + attempt + '.txt'],
                  '原 reply 文件缺少或有多个调用')
            _need(next(i for i, e in enumerate(events) if e['type'] == 'turn.started')
                  < next((i for i, e in enumerate(events) if e['type'] == 'item.completed'
                          and e['item']['type'] == 'agent_message'), -1)
                  and all(e.get('usage') is None or isinstance(e['usage'], dict) for e in events),
                  '原回合顺序或 usage 记录无效')
            reply = read('reply-' + attempt + '.txt')
            _need(len(messages) == 1 and isinstance(messages[0].get('text'), str)
                  and reply and messages[0]['text'].encode('utf-8') == reply
                  and isinstance(_json(reply), dict), '原终态文本与原 -o JSON 回复不逐字相等')

            files = {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in sorted(raw_files.items())}
            proof = {'schema': 'codex-cli-checkpoint-reconstruction-proof-v1', 'task_id': task_id,
                     'task_sha256': digest(task), 'project_sha256': digest(project),
                     'provider_configuration_sha256': digest(config), 'execution_lease_sha256': digest(lease),
                     'current_sources': current_sources,
                     'time_reservation': copy.deepcopy(reservation), 'input_snapshot': copy.deepcopy(inputs),
                     'cycle': cycle, 'directory': str(directory), 'files': files,
                     'attempt_id': attempt, 'invocation': 1, 'session_id': session,
                     'native_started_at': started['started_at'], 'native_finished_at': finished['finished_at'],
                     'native_elapsed_seconds': (times[2] - times[1]).total_seconds(),
                     'pid': started['pid'], 'pid_absence': 'ESRCH', 'disabled_mcp_names': servers,
                     'current_scope': sorted(actual_scope) if actual_scope is not None else None,
                     'requested_scope': sorted(scope) if scope is not None else None,
                     'principal_sha256': digest(caller),
                     'new_model_requests': 0, 'mutated': False, 'candidate_validation': 'not_performed',
                     'limits': ['Local unsigned process observations; not native prompt provenance.',
                                'Proposal only; caller must revalidate under apply fence.']}
            reconstruction = {'kind': 'verified_original_cli_exit', 'proof_sha256': digest(proof),
                              'original_receipt_was_absent': True, 'new_model_requests': 0}
            events_text = _serialized(events)
            receipt = {'route': 'codex', 'session_id': session, 'resumed_from': None, 'returncode': 0,
                       'usage': [copy.deepcopy(e['usage']) for e in events if e.get('usage')],
                       'model': config.get('model', 'local CLI configured default'),
                       'started_at': started['started_at'], 'finished_at': finished['finished_at'],
                       'actual_bill_usd': None, 'event_count': len(events), 'host_tools_disabled': DISABLED[:],
                       'mcp_servers_disabled_for_this_call': True, 'scoped_domain_tools': [],
                       'budget_unit': 'CLI invocations; internal API request count unavailable',
                       'version': 1, 'task_id': task_id, 'contract_sha256': intent['contract_sha256'],
                       'attempt_id': attempt, 'invocation': 1, 'events_sha256': digest(events_text.encode()),
                       'session_identity_confirmed': True, 'reconstruction': reconstruction}
            receipt_text = _serialized(receipt)
            checkpoint = {**copy.deepcopy(intent), 'session_id': session,
                          'events_sha256': receipt['events_sha256'],
                          'receipt_sha256': digest(receipt_text.encode()), 'reconstruction': reconstruction}
            _need(all(_controlled_file(directory, directory / name) == raw for name, raw in raw_files.items()),
                  '原文件在检查期间改变')
            _need(original_outputs()
                  and sorted(path.name for path in directory.glob('process-*')) == process_names,
                  '检查期间出现新的进程或登记记录')
            _gone(started['pid'])
            return {'receipt': receipt, 'events': events, 'checkpoint': checkpoint, 'proof': proof,
                    'proposed_file_text': {'codex-events-' + attempt + '.json': events_text,
                                           'codex-receipt-' + attempt + '.json': receipt_text,
                                           'provider-receipt.json': receipt_text}}
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        raise Problem('原 CLI 证据缺失或不能完整核对；未写入或新增调用', CODE, 409,
                      {'new_model_requests': 0, 'mutated': False}) from error
