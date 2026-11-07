"""Read a completed CLI reply after publication was interrupted; never dispatch.

The task's durable checkpoint identifies the exact invocation. A successful
process receipt alone is not a candidate: its terminal event and reply must
agree, and normal Runtime input, schema, permission and CAS checks still apply.
"""
from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime
from pathlib import Path

from research_partner.storage.store import Problem, digest, require


def recover(providers, task, directory, receipt):
    from research_partner.providers.registry import _controlled_file
    from research_partner.execution.runtime import process_identity

    directory = Path(directory)
    continuity = providers.assert_codex_continuity(task, directory)
    attempt = continuity['attempt_id']

    def read(name, limit=131072):
        return json.loads(_controlled_file(directory, directory / name, limit))

    try:
        events = read('codex-events-' + attempt + '.json', 8 * 1024 * 1024)
        completed = [i for i, e in enumerate(events) if e.get('type') == 'turn.completed']
        if not completed:
            return None  # An explicit ordinary continuation may still be needed.
        require(task['payload']['kind'] != 'figure_composition',
                '图组成需要其专用工具证据，未回收普通文字回复', 'candidate_checkpoint_invalid', 409)
        config = providers.app.config.get('providers', {}).get(task['payload']['provider_id'], {})
        require(config.get('route') == 'codex' and config.get('authorized') is True
                and config.get('transport') is None,
                '当前提供者许可或路线不符，未接回候选', 'authorization_required', 403)
        store = providers.app.store
        intent = store.setting('codex_launch_intent:' + task['id'])
        checkpoint = store.setting('codex_checkpoint:' + task['id'])
        require(intent['attempt_id'] == attempt == checkpoint['attempt_id']
                and intent['invocation'] == checkpoint['invocation']
                == receipt['invocation'] == store.setting('provider_invocations:' + task['id'])
                and intent.get('execution_token') == checkpoint.get('execution_token')
                and isinstance(intent.get('execution_token'), str) and intent['execution_token'],
                '较新分派已替代此回复，未接回旧候选', 'candidate_checkpoint_invalid', 409)
        require(completed == [len(events) - 1]
                and sum(e.get('type') == 'turn.started' for e in events) == 1
                and not any(e.get('type') in {'turn.failed', 'error'} for e in events),
                '原CLI没有唯一已完成回合', 'candidate_checkpoint_invalid', 409)
        messages = [e['item'] for e in events if e.get('type') == 'item.completed'
                    and e.get('item', {}).get('type') == 'agent_message']
        require(len(messages) == 1 and isinstance(messages[0].get('text'), str)
                and all(e.get('item', {}).get('type') in {None, 'agent_message', 'reasoning', 'error'}
                        for e in events),
                '普通文字回复含歧义或未支持的工具动作', 'candidate_checkpoint_invalid', 409)
        reply_name = 'reply-' + attempt + '.txt'
        reply = _controlled_file(directory, directory / reply_name)
        require(reply and reply == messages[0]['text'].encode('utf-8'),
                '原CLI回复与已绑定终态事件不同', 'candidate_checkpoint_invalid', 409)
        require((receipt.get('returncode') is None
                 or (type(receipt.get('returncode')) is int and receipt['returncode'] == 0))
                and receipt.get('mcp_servers_disabled_for_this_call') is True
                and receipt.get('scoped_domain_tools') == [],
                '原回复不是已完成的无工具文字调用', 'candidate_checkpoint_invalid', 409)
        matches = []
        for path in directory.glob('process-*.finished.json'):
            finished = read(path.name)
            if (finished.get('task_id') != task['id']
                    or finished.get('execution_token') != intent['execution_token']):
                continue
            argv = finished.get('argv', [])
            if str(directory / reply_name) not in argv:
                continue
            started_name = path.name.replace('.finished.', '.started.')
            started = read(started_name)
            require(all(finished.get(k) == v for k, v in started.items() if k != 'state')
                    and started.get('state') == 'running'
                    and started.get('identity_kind') == 'live_command'
                    and type(started.get('pid')) is int and started['pid'] > 1
                    and type(started.get('uid')) is int and started['uid'] == os.getuid()
                    and isinstance(started.get('start_ticks'), str)
                    and started['start_ticks'].isdigit()
                    and isinstance(started.get('command_sha256'), str)
                    and re.fullmatch(r'[0-9a-f]{64}', started['command_sha256']),
                    '原CLI启动与结束身份不一致', 'candidate_checkpoint_invalid', 409)
            require(finished.get('state') == 'finished'
                    and type(finished.get('returncode')) is int and finished['returncode'] == 0
                    and finished.get('deadline_triggered') is False
                    and finished.get('deadline_stop_errors') == []
                    and finished.get('cwd') == str(directory)
                    and argv.count('-o') == 1
                    and argv[argv.index('-o') + 1] == str(directory / reply_name),
                    '原CLI未确认成功结束，未回收回复', 'candidate_checkpoint_invalid', 409)
            times = [datetime.fromisoformat(v) for v in
                     (receipt['started_at'], started['started_at'], finished['finished_at'], receipt['finished_at'])]
            require(all(t.tzinfo is not None for t in times) and times == sorted(times),
                    '原CLI时间归属不一致', 'candidate_checkpoint_invalid', 409)
            live = process_identity(started['pid'])
            if live is None:
                # The shared helper also returns None for unreadable /proc.
                # Only ESRCH proves absence; permission or parse uncertainty
                # must not be converted into permission to publish a reply.
                try:
                    os.kill(started['pid'], 0)
                except ProcessLookupError:
                    pass
                except OSError as error:
                    raise Problem('无法核验原CLI进程是否退出，未接回或重发',
                                  'candidate_checkpoint_invalid', 409) from error
                else:
                    raise Problem('原CLI进程仍存在但身份不可读，未接回或重发',
                                  'candidate_checkpoint_invalid', 409)
            require(live is None or live['start_ticks'] != started['start_ticks']
                    or (live['uid'] == started['uid'] and live['state'] in {'Z', 'X'}),
                    '原CLI进程尚未确认退出，未接回或重发', 'candidate_checkpoint_invalid', 409)
            matches.append((path.name, started_name, finished))
        require(len(matches) == 1, '缺少唯一原CLI成功退出回执', 'candidate_checkpoint_invalid', 409)
        model = next((s for s in store.task(task['id'])['steps'] if s['step_key'] == 'model'), None)
        require(model and model['status'] == 'running'
                and model['data'].get('dispatch_guard_version') == 1
                and model['data'].get('provider_route') == 'codex',
                '缺少本次未发布模型步骤', 'candidate_checkpoint_invalid', 409)
        inputs = model['data'].get('input_snapshot')
        require(isinstance(inputs, dict) and set(inputs) == {'decisions', 'guidance'}
                and all(isinstance(inputs[k], list) for k in inputs),
                '原模型输入快照缺失', 'candidate_checkpoint_invalid', 409)
        rejected = directory / 'candidate.rejected.json'
        require(not rejected.exists(), '已拒候选须明确修订，未重复接回', 'candidate_revision_required', 409)
        process_file, started_file, finished = matches[0]
        proof = {'kind': 'codex_cli_completed_reply', 'task_id': task['id'],
                 'attempt_id': attempt, 'invocation': receipt['invocation'],
                 'session_id': continuity['session_id'], 'reply_sha256': digest(reply),
                 'events_sha256': continuity['events_sha256'],
                 'contract_sha256': continuity['contract_sha256'],
                 'process_finished_file': process_file,
                 'process_finished_sha256': digest(_controlled_file(directory, directory / process_file)),
                 'process_started_sha256': digest(_controlled_file(directory, directory / started_file)),
                 'process_returncode': finished['returncode'],
                 'input_basis': 'original running model step; not native prompt provenance'}
        return {'text': reply.decode('utf-8'), 'verified_cli_input_snapshot': copy.deepcopy(inputs),
                'receipt': {**receipt, 'candidate': proof, 'recovered_completed_cli_reply': True,
                            'new_model_requests': 0}}
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
        raise Problem('已完成CLI回复证据损坏，未新增调用', 'candidate_checkpoint_invalid', 409) from error
