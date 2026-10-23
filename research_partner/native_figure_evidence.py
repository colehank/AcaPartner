"""Pure checks for the explicit fresh DeepSeek figure profile's durable evidence.

Input bytes are already decoded from session.v3.jsonl.zstd by the owning host.
This module reads no files, credentials, HTTP, model or Store. Same-UID records
prove internal correspondence only. Candidate validation, actual saved objects,
definition bytes, current permissions and unchanged adopted heads remain root
checks; neither a service snapshot nor this result signs scientific acceptance.
"""
from __future__ import annotations
import copy
from decimal import Decimal
from datetime import datetime
import json
import math
import re
from .store import Problem, digest, require
from .mcp_workbench import BridgeError, validate as validate_arguments

FEATURE = 'deepseek_task_figure_tools_v1'
TRANSPORT = 'deepseek_harness_native'
TOOLS = ('read_figure_context', 'create_main_figure')
MAX_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 20000


def _check(value, message):
    require(value, message, 'native_figure_evidence_invalid', 409)


def _same_tool_declarations(actual, expected):
    """SDK prompt ordering is not tool identity; retain every declaration field."""
    return (isinstance(actual, list) and len(actual) == len(expected)
            and all(isinstance(tool, dict) and isinstance(tool.get('name'), str) for tool in actual)
            and len({tool['name'] for tool in actual}) == len(actual)
            and _native_json(sorted(actual, key=lambda tool: tool['name']))
                == _native_json(sorted(expected, key=lambda tool: tool['name'])))


def _json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            _check(key not in result, 'JSON字段重复')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
        _native_json(value)  # Also reject depth, surrogate and unsafe number loss.
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise Problem('原生证据不是有限完整UTF-8 JSON', 'native_figure_evidence_invalid', 409)


def _native_json(value, depth=0):
    """The native modules' sorted, finite JSON encoding (including JS numbers)."""
    _check(depth <= 64, 'JSON嵌套超过边界')
    if value is None or type(value) is bool:
        return json.dumps(value)
    if type(value) in (int, float):
        _check(math.isfinite(value), 'JSON数字不是有限值')
        if type(value) is int:
            _check(abs(value) <= 9007199254740991, 'JSON整数不能无损映射原生运行时')
            return str(value)
        if value == 0:
            return '0'
        text = repr(value).lower()
        if 1e-6 <= abs(value) < 1e21:
            return format(Decimal(text), 'f').rstrip('0').rstrip('.') if '.' in format(Decimal(text), 'f') else format(Decimal(text), 'f')
        mantissa, exponent = text.split('e') if 'e' in text else (text, '0')
        return mantissa.removesuffix('.0') + 'e' + ('+' if int(exponent) >= 0 else '-') + str(abs(int(exponent)))
    if isinstance(value, str):
        value.encode('utf-8', errors='strict')
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return '[' + ','.join(_native_json(x, depth + 1) for x in value) + ']'
    _check(isinstance(value, dict) and all(isinstance(k, str) for k in value), 'JSON对象字段无效')
    keys = sorted(value, key=lambda k: k.encode('utf-16-be'))
    return '{' + ','.join(_native_json(k, depth + 1) + ':' + _native_json(value[k], depth + 1) for k in keys) + '}'


def _sha(value):
    return digest(_native_json(value).encode())


def _hex(value):
    return isinstance(value, str) and re.fullmatch('[a-f0-9]{64}', value) is not None


def _integer(value, minimum=0):
    return type(value) is int and minimum <= value <= 9007199254740991


def _stream(records):
    """Check the pinned rc.2 compact records and reconstruct their own blocks."""
    _check(isinstance(records, list) and records, '缺少本次实际紧凑模型流')
    chunks = []
    for record in records:
        _check(isinstance(record, dict), '模型流记录无效')
        kind = record.get('type')
        if kind == 'chunk':
            _check(_integer(record.get('time')) and isinstance(record.get('chunk'), dict), '模型流原chunk无效')
            chunks.append(record['chunk']); continue
        _check(kind in {'text-chunks', 'reasoning-chunks', 'tool-call-chunks'}
               and _integer(record.get('time0')) and _integer(record.get('index')), '未知紧凑模型流类型')
        members = record.get('args' if kind == 'tool-call-chunks' else 'texts')
        gaps = record.get('dt')
        _check(isinstance(members, list) and members and all(isinstance(x, str) for x in members)
               and isinstance(gaps, list) and len(gaps) == len(members) - 1
               and all(type(x) is int and abs(x) <= 9007199254740991 for x in gaps), '紧凑模型流成员不完整')
        time = record['time0']
        for index, text in enumerate(members):
            if index: time += gaps[index - 1]
            _check(_integer(time), '紧凑模型流时间无效')
            chunk = {'index': record['index']}
            if kind == 'tool-call-chunks':
                _check(isinstance(record.get('id'), str) and record['id'] and ('name' not in record or isinstance(record['name'], str)), '原生tool-call流身份无效')
                chunk.update(type='tool-call-delta', id=record['id'], argumentsDelta=text)
                if 'name' in record: chunk['name'] = record['name']
            else: chunk.update(type='text-delta' if kind == 'text-chunks' else 'reasoning-delta', text=text)
            chunks.append(chunk)
    partials = {}; usage = None; finish = None
    for chunk in chunks:
        kind = chunk.get('type')
        if kind == 'usage': usage = chunk.get('usage'); continue
        if kind == 'finish': finish = chunk.get('reason'); continue
        _check(kind in {'block-start', 'block-end', 'text-delta', 'reasoning-delta', 'tool-call-delta'}
               and _integer(chunk.get('index')), '未知原生模型chunk或块位置')
        index = chunk['index']
        block_type = (chunk.get('blockType') if kind == 'block-start' else
                      chunk.get('block', {}).get('type') if kind == 'block-end' else
                      {'text-delta': 'text', 'reasoning-delta': 'reasoning', 'tool-call-delta': 'tool-call'}[kind])
        _check(block_type in {'text', 'reasoning', 'tool-call'}, '此固定主图profile出现未知模型块')
        partial = partials.setdefault(index, {'type': block_type, 'text': '', 'arguments': ''})
        if 'block' in partial: continue  # Actual rc.2 assembler's first close wins.
        if kind == 'block-end': partial['block'] = chunk['block']
        elif kind in {'text-delta', 'reasoning-delta'}:
            _check(isinstance(chunk.get('text'), str), '模型文本chunk缺少原字节')
            partial['text'] += chunk['text']
        elif kind == 'tool-call-delta':
            _check(isinstance(chunk.get('id'), str) and isinstance(chunk.get('argumentsDelta'), str), '模型工具chunk缺少身份/参数')
            partial['id'] = chunk['id']; partial['arguments'] += chunk['argumentsDelta']
            if chunk.get('name'): partial['name'] = chunk['name']
    _check(isinstance(finish, dict) and finish.get('kind') in {'stop', 'tool-calls'}, '本次模型流没有明确成功finish')
    blocks = []
    for index, part in partials.items():
        if 'block' in part: blocks.append(part['block'])
        elif part['type'] == 'tool-call':
            _check(part.get('id') and part.get('name'), '工具流没有实际call ID/名称')
            blocks.append({k: part[k] for k in ('type', 'id', 'name', 'arguments')})
        else: blocks.append({'type': part['type'], 'text': part['text']})
    return blocks, usage, finish


def _verify_native_figure(task, receipt, durable_jsonl, *, expected_cwd, expected_prompt):
    """Return checked payload/provenance for root's existing candidate/Store gates.

    durable_jsonl must be complete decompressed UTF-8 bytes, not selected event
    dictionaries. No receipt reply SHA is invented; the final own assistant's
    exact text bytes receive a new explicitly identified digest.
    """
    _check(isinstance(task, dict) and isinstance(receipt, dict), '需要实际Task和driver回执')
    _check(len(_native_json(task).encode()) <= MAX_BYTES and len(_native_json(receipt).encode()) <= MAX_BYTES, 'Task/driver证据超出完整读取边界')
    plan = task.get('payload', {}).get('context', {}).get('figure_composition', {})
    definition = plan.get('native_definition', {})
    _check(task.get('payload', {}).get('kind') == 'figure_composition'
           and plan.get('native_transport') == TRANSPORT and definition.get('feature') == FEATURE
           and definition.get('transport') == TRANSPORT and definition.get('route') == 'deepseek_harness'
           and definition.get('provider') == 'deepseek-official' and definition.get('fresh_only') is True
           and definition.get('retry_max') == 0 and definition.get('max_tool_calls') == plan.get('max_tool_calls') == 8
           and digest({k: v for k, v in definition.items() if k != 'sha256'}) == definition.get('sha256')
           and digest({k: v for k, v in plan.items() if k != 'sha256'}) == plan.get('sha256'), 'Task冻结模型/profile/计划身份不符')
    _check(isinstance(expected_cwd, str) and expected_cwd.startswith('/')
           and isinstance(expected_prompt, str) and expected_prompt.strip(), '需要root原任务目录和精确提示')
    _check(receipt.get('feature') == FEATURE and receipt.get('native_api') == 'agents.create'
           and 'resumed_from' in receipt and receipt['resumed_from'] is None and receipt.get('identity_source') == 'authoritative_agents_create_return'
           and receipt.get('phase') == 'flushed' and receipt.get('checkpoint') is None
           and receipt.get('reason') == {'kind': 'completed'}
           and receipt.get('provider') == definition['provider'] and receipt.get('model') == definition.get('model'), 'driver不是同一fresh已完成任务/模型')
    binding = receipt.get('figure_task_binding', {})
    _check(isinstance(binding, dict) and binding.get('feature') == FEATURE and binding.get('transport') == TRANSPORT
           and binding.get('native_execution_verified') is False and binding.get('stream_outcome_unknown') is False
           and binding.get('binding_proof') == {'native_api': 'agents.create', 'resumed_from': None,
                                              'identity_source': 'authoritative_host_return_after_agent_created'}, '原生绑定/stream未知或不属于实际create返回')
    for field, expected in [('task_id', task.get('id')), ('project_id', task.get('project_id')),
                            ('definition_sha256', definition['sha256']), ('plan_sha256', plan['sha256']),
                            ('egress_sha256', plan.get('egress_sha256')), ('session_id', receipt.get('session_id'))]:
        _check(isinstance(expected, str) and expected and binding.get(field) == expected, 'figure binding字段不符: ' + field)
    _check(_hex(plan.get('egress_sha256')) and plan.get('adopted_head_changed') is False
           and plan.get('request', {}).get('project_id') == task.get('project_id'), 'Task外发/采用/目标项目边界不符')
    _check(isinstance(durable_jsonl, bytes) and 0 < len(durable_jsonl) <= MAX_BYTES
           and durable_jsonl.endswith(b'\n'), '完整原生JSONL缺失、截尾或超过边界')
    try: lines = durable_jsonl.decode('utf-8', errors='strict').splitlines()
    except UnicodeError: _check(False, '原生JSONL不是完整UTF-8')
    _check(1 < len(lines) <= MAX_EVENTS + 1 and all(lines), '原生JSONL事件范围无效')
    records = [_json(line) for line in lines]; header = records[0]; events = records[1:]
    _check(isinstance(header, dict) and header.get('type') == 'session' and header.get('version') == 3
           and header.get('id') == receipt['session_id'] and header.get('cwd') == expected_cwd
           and _integer(header.get('createdAt')) and header.get('isSeeded') is False
           and not header.get('parentSession') and header.get('delegationDepth', 0) == 0
           and 'origin' not in header, 'durable session不属于同一新建Task目录/身份')
    for seq, event in enumerate(events):
        _check(isinstance(event, dict) and event.get('seq') == seq and type(event.get('seq')) is int
               and _integer(event.get('time')) and isinstance(event.get('data'), dict), 'durable事件序列或原生envelope不完整')
    loaded, first, final = (receipt.get(k) for k in ('loaded_seq', 'first_seq', 'final_seq'))
    _check(all(_integer(x) for x in (loaded, first, final)) and 0 <= loaded <= first < final == len(events), 'driver事件范围与完整durable尾部不符')
    _check(all(e.get('type') in {'agent-preset/selected', 'model/selection', 'permission/preset', 'sandbox/mode', 'session/title'}
               or e.get('type') == 'approval/policy' and e['data'] == {'policy': 'ask'}
               for e in events[:first]), 'fresh范围前已有原生执行、未知动作或恢复种子')
    owned = events[first:final]
    # Native followup first records its inbox enqueue, then wakes the turn.
    # Keep that original sequence and bind the one queued message to the exact
    # consumed user message, rather than skipping arbitrary metadata/actions.
    queued = None
    if owned[0].get('type') == 'agent/inbox/spliced':
        entry = owned[0]['data']
        _check(set(entry) == {'target', 'start', 'inserted'} and entry['target'] == 'next-turn'
               and type(entry['start']) is int and entry['start'] == 0
               and isinstance(entry['inserted'], list) and len(entry['inserted']) == 1,
               'fresh初始入队不是唯一固定Task消息')
        queued = entry['inserted'][0]
        _check(isinstance(queued, dict) and isinstance(queued.get('id'), str) and queued['id']
               and queued.get('role') == 'user' and queued.get('source') == {'kind': 'user'}
               and queued.get('content') == [{'type': 'text', 'text': expected_prompt}],
               'fresh入队消息不是完整原Task提示')
    turn_index = 1 if queued is not None else 0
    _check(len(owned) > turn_index and owned[turn_index].get('type') == 'turn/start' and owned[-1].get('type') == 'turn/end'
           and owned[-1]['data'].get('reason') == receipt['reason'], '本次范围没有对应turn首尾')
    catalog = binding.get('catalog', {})
    _check(isinstance(catalog.get('raw_json'), str) and digest(catalog['raw_json'].encode()) == catalog.get('sha256') == definition.get('catalog_sha256')
           and _sha(catalog.get('native_declarations')) == catalog.get('native_declarations_sha256') == definition.get('native_declarations_sha256')
           and catalog.get('native_schema_is_projection') is True, '冻结两工具catalog摘要不符')
    original = _json(catalog['raw_json']); projected = catalog.get('native_declarations')
    _check(isinstance(original, list) and isinstance(projected, list)
           and len(original) == len(projected) == 2 and {x.get('name') for x in original} == set(TOOLS)
           and {x.get('name') for x in projected} == set(TOOLS), '不是精确两工具原生声明')
    schemas = {x['name']: x['inputSchema'] for x in original}
    expected_tools = [{'name': x['name'], 'description': x['description'], 'parameters': x['inputSchema']} for x in projected]
    tools = binding.get('tools', {})
    _check(isinstance(tools, dict) and _sha({k: v for k, v in tools.items() if k != 'sha256'}) == tools.get('sha256')
           and tools.get('version') == 1 and tools.get('feature') == FEATURE
           and tools.get('native_execution_verified') is False and tools.get('write_outcome_uncertain') is False
           and tools.get('fixed_sources') == plan.get('fixed_sources'), '领域工具snapshot缺失或不完整')
    for key in ('task_id', 'project_id', 'session_id', 'plan_sha256'):
        _check(tools.get(key) == binding[key], '工具snapshot身份不属于driver绑定')
    _check(tools.get('catalog_sha256') == catalog['sha256'] and tools.get('native_declarations_sha256') == catalog['native_declarations_sha256'], '工具snapshot声明已变化')
    scope = tools.get('scope', {})
    normalize = lambda r: {'project_id': r.get('project_id'), 'title': r.get('title'), 'width': r.get('width', 1200), 'height': r.get('height', 600), 'slots': r.get('slots')}
    _check(scope == {'task_id': task['id'], 'project_id': task['project_id'], 'plan_sha256': plan['sha256'], 'allowed_tools': list(TOOLS),
                     'fixed_sources': plan['fixed_sources'], 'composition_request_sha256': _sha(normalize(plan['request'])),
                     'request_key': task['id'] + ':composition', 'adopted_head_write': False}, '领域scope不是冻结组成请求')
    receipts = tools.get('receipts'); streams = binding.get('streams')
    _check(isinstance(receipts, list) and 1 <= len(receipts) <= 64 and isinstance(streams, list)
           and 1 <= len(streams) <= definition.get('max_requests', 0), '工具/模型stream证据计数超限或为空')
    by_call = {}
    for record in receipts:
        _check(isinstance(record, dict) and isinstance(record.get('call_id'), str) and record['call_id'] not in by_call
               and record.get('session_id') == receipt['session_id'] and record.get('name') in TOOLS
               and record.get('arguments_sha256') == _sha({'name': record['name'], 'arguments': record.get('arguments')})
               and type(record.get('callback_invoked')) is bool and type(record.get('success')) is bool
               and isinstance(record.get('finished_at'), str), '领域回调记录缺失/重复或参数摘要不符')
        by_call[record['call_id']] = record
    _check(tools.get('executed_tool_calls') == sum(x['callback_invoked'] for x in receipts)
           and type(tools.get('executed_tool_calls')) is int and tools['executed_tool_calls'] <= 8, '实际回调计数不符')
    pins = plan.get('fixed_sources', [])
    _check(isinstance(pins, list) and 1 <= len(pins) <= 24 and all(isinstance(x, dict)
           and set(x) == {'id', 'revision', 'sha256', 'svg_sha256', 'numeric_sha256'}
           and isinstance(x.get('id'), str) and _integer(x.get('revision'), 1)
           and all(_hex(x.get(key)) for key in ('sha256', 'svg_sha256', 'numeric_sha256'))
           for x in pins), '冻结来源pin不完整')
    needed = {(x['id'], x['revision']): x for x in pins}
    _check(len(needed) == len(pins) and {(s['source']['id'], s['source']['revision']) for s in plan['request']['slots'] if s.get('source')} == set(needed), '固定来源pin重复或不属于组成目标')
    history = []; request_histories = {}
    turn = None; step = None; next_step = 1; pending = {}; model_calls = {}; completed = {}; successful = []; failures = []; assistant = []; prompt = []; request_headers = 0
    metadata = {'request/context', 'session/title'}
    inbox_claimed = False
    for event in owned:
        kind, data, seq = event.get('type'), event['data'], event['seq']
        if kind == 'agent/inbox/spliced':
            if queued is not None and seq == first:
                continue
            _check(queued is not None and turn == 1 and step is None and seq == first + 2 and not inbox_claimed
                   and set(data) == {'target', 'start', 'removedCount', 'inserted'}
                   and data['target'] == 'next-turn' and type(data['start']) is int and data['start'] == 0
                   and type(data['removedCount']) is int and data['removedCount'] == 1 and data['inserted'] == [],
                   '出现额外或不匹配的Task输入消费')
            inbox_claimed = True
            continue
        if kind == 'turn/start':
            _check(turn is None and not assistant and type(data.get('turn')) is int and data['turn'] == 1, '本次存在第二个或无效turn')
            turn = data['turn']; continue
        if kind == 'turn/end':
            _check(type(data.get('turn')) is int and data.get('turn') == turn and step is None and not pending and seq == final - 1, 'turn结束身份或次序不符'); continue
        if kind == 'step/start':
            _check(type(data.get('turn')) is int and data.get('turn') == turn and step is None and type(data.get('step')) is int and data.get('step') == next_step, 'step开始身份或次序不符')
            step = next_step; continue
        if kind == 'step/end':
            _check(type(data.get('turn')) is int and data.get('turn') == turn and type(data.get('step')) is int and data.get('step') == step and not pending
                   and step in completed and all(ident in {x['call_id'] for x in successful + failures} for ident, (_, _, own_step) in model_calls.items() if own_step == step), 'step未实际完成或仍有待回包工具')
            step = None; next_step += 1; continue
        if kind in metadata:
            if kind == 'request/context': _check(data.get('provider') == definition['provider'] and data.get('model') == definition['model'], 'durable实际模型路由不同')
            continue
        if kind == 'request/header':
            head = data.get('header', {})
            _check(step is not None and data.get('reason') in {'initial', 'change', 'series'}
                   and head.get('config', {}).get('provider') == definition['provider']
                   and head.get('config', {}).get('model') == definition['model'] and _same_tool_declarations(head.get('tools'), expected_tools),
                   'durable模型请求不是冻结模型/两工具声明')
            request_headers += 1; continue
        if kind == 'user/message':
            _check(queued is None or inbox_claimed and _native_json(data) == _native_json(queued), '实际用户消息与唯一入队原文/身份不符')
            _check(event.get('surfaceOp') == 'append' and data.get('role') == 'user' and data.get('source') == {'kind': 'user'}, 'Task提示来自外来或替换消息')
            _check(isinstance(data.get('content'), list) and all(x.get('type') == 'text' and isinstance(x.get('text'), str) for x in data['content']), 'Task提示不是精确文本')
            prompt.append((seq, ''.join(x['text'] for x in data['content']))); history.append(copy.deepcopy(data)); continue
        if kind == 'system/message':
            _check(event.get('surfaceOp') == 'append' and type(data.get('turn')) is int and data.get('turn') == turn and type(data.get('step')) is int and data.get('step') == step, 'system事件不属于本次step'); history.append(copy.deepcopy(data['message'])); continue
        _check(kind in {'assistant/message', 'tool/call', 'tool/result'} and step is not None
               and type(data.get('turn')) is int and data.get('turn') == turn and type(data.get('step')) is int and data.get('step') == step, '出现未知动作/模型attempt或外来turn/step')
        if kind == 'assistant/message':
            message = data.get('message', {})
            _check(event.get('surfaceOp') == 'append' and data.get('interrupted', False) is False
                   and message.get('role') == 'assistant' and isinstance(message.get('id'), str)
                   and message.get('source', {}).get('kind') == 'model'
                   and message['source'].get('provider') == definition['provider'] and message['source'].get('model') == definition['model']
                   and step not in completed, 'assistant不是本次实际模型消息')
            blocks, usage, finish = _stream(data.get('stream'))
            _check(blocks == message.get('content') and usage == data.get('usage'), 'durable模型流与实际assistant/usage不一致')
            completed[step] = (usage, finish); assistant.append(event)
            request_histories[seq] = copy.deepcopy(history); history.append(copy.deepcopy(message))
            for block in blocks:
                if block.get('type') != 'tool-call': continue
                _check(isinstance(block.get('id'), str) and block['id'] not in model_calls and block.get('name') in TOOLS,
                       '模型申请未知工具或重复call ID')
                model_calls[block['id']] = (block, seq, step)
            continue
        call_id = data.get('callId') if kind == 'tool/call' else data.get('message', {}).get('source', {}).get('callId')
        if kind == 'tool/call':
            _check(call_id in model_calls and call_id not in pending and call_id not in {x['call_id'] for x in successful + failures}, '工具没有本次模型原申请或重复执行')
            block, model_seq, own_step = model_calls[call_id]
            _check(data.get('name') == block['name'] and data.get('arguments') == block['arguments'] and model_seq < seq and own_step == step, '实际工具名称/原参数不属于模型申请')
            args = _json(data.get('arguments'))
            validate_arguments(args, schemas[block['name']])
            _check(call_id in by_call and by_call[call_id]['name'] == block['name'] and by_call[call_id]['arguments'] == args
                   and args.get('project_id') == task['project_id'], '模型工具参数/回调身份越出任务')
            pending[call_id] = (event, args); continue
        message = data.get('message', {}); content = message.get('content')
        _check(call_id in pending and message.get('role') == 'user' and message.get('source') == {'kind': 'tool', 'callId': call_id}
               and event.get('surfaceOp') == 'append' and event.get('sourceEventSeqs') == [pending[call_id][0]['seq']]
               and isinstance(content, list) and len(content) == 1 and content[0].get('type') == 'tool-result'
               and content[0].get('toolCallId') == call_id and type(content[0].get('isError')) is bool, '实际工具回包没有对应原call/来源位置')
        result_blocks = content[0].get('content')
        _check(isinstance(result_blocks, list) and len(result_blocks) == 1 and result_blocks[0].get('type') == 'text', '领域回包不是完整原JSON文本')
        value = _json(result_blocks[0].get('text')); record = by_call[call_id]; call, args = pending.pop(call_id)
        _check(content[0]['isError'] is (not record['success']) and value == record.get('result' if record['success'] else 'error'), 'native实际回包与领域服务snapshot不一致')
        history.append(copy.deepcopy(message))
        entry = {'call_id': call_id, 'call_seq': call['seq'], 'result_seq': seq, 'name': record['name'], 'arguments': args, 'result': value}
        if not record['success']:
            _check(isinstance(value, dict) and value.get('write_outcome_uncertain') is False, '失败回调结果未知，不能采用候选')
            failures.append(entry); continue
        _check(record['callback_invoked'] is True and isinstance(value, dict) and 'error' not in value and value.get('ok', True) is not False and value.get('isError', False) is False
               and value.get('write_outcome_uncertain', False) is False, '没有实际成功领域回调')
        figure = value.get('figure', {})
        if record['name'] == 'read_figure_context':
            key = (args.get('id'), args.get('revision'))
            _check(key in needed and figure.get('id') == key[0] and figure.get('revision') == key[1]
                   and figure.get('kind') == 'figure' and figure.get('project_id') == task['project_id'] and digest(figure) == needed[key]['sha256'], '实际读取不是冻结保存来源')
        else:
            _check(set(args) <= {'project_id', 'title', 'width', 'height', 'slots', 'request_key'}
                   and args.get('request_key') == task['id'] + ':composition' and normalize(args) == normalize(plan['request']), '实际创建不是冻结唯一目标组成')
        successful.append(entry)
    _check((queued is None or inbox_claimed) and len(prompt) == 1 and prompt[0][1] == expected_prompt and request_headers > 0
           and len(assistant) == len(streams) and set(by_call) == set(model_calls)
           and len(successful) + len(failures) == len(by_call), '提示/模型stream/工具证据有遗漏或额外执行')
    missing = ['streams[' + str(i) + '].request_json_utf8' for i, stream in enumerate(streams) if 'request_json_utf8' not in stream]
    require(not missing, '缺少原始模型request字节；不能返回已验证候选', 'native_figure_evidence_unavailable', 503,
            {'verification_status': 'NOT_VERIFIED', 'missing_fields': missing})
    stream_ids = set()
    for stream, event in zip(streams, assistant):
        _check(isinstance(stream, dict) and isinstance(stream.get('request_id'), str) and stream['request_id'] not in stream_ids
               and stream.get('session_id') == receipt['session_id'] and stream.get('status') == 'stream_returned_bill_unverified'
               and _hex(stream.get('request_sha256')) and stream.get('usage') == completed[event['data']['step']][0]
               and stream.get('finish') == completed[event['data']['step']][1], 'stream记录未对应本次durable实际settlement')
        request_raw = stream.get('request_json_utf8')
        _check(isinstance(request_raw, str) and 0 < len(request_raw.encode('utf-8')) <= min(262144, definition.get('max_request_bytes', 0))
               and digest(request_raw.encode('utf-8')) == stream['request_sha256'], '原request UTF8字节、边界或逐字摘要不符')
        request = _json(request_raw)
        _check(isinstance(request, dict) and set(request) <= {'messages', 'system', 'tools'}
               and request.get('messages') == request_histories[event['seq']] and _same_tool_declarations(request.get('tools'), expected_tools)
               and 'system' not in request, '原模型request与本次durable派生messages/两工具不同或存在未登记system')
        started = datetime.fromisoformat(stream['started_at'].replace('Z', '+00:00'))
        finished = datetime.fromisoformat(stream['local_finished_at'].replace('Z', '+00:00'))
        _check(started.tzinfo is not None and finished.tzinfo is not None and 0 <= (finished - started).total_seconds() <= definition.get('timeout_seconds', 0), 'stream历史时间缺失或超出Task边界')
        stream_ids.add(stream['request_id'])
    reads = {(x['arguments']['id'], x['arguments']['revision']) for x in successful if x['name'] == 'read_figure_context'}
    created = [x for x in successful if x['name'] == 'create_main_figure']
    _check(reads == set(needed) and created, '本轮未实际读取全部固定来源或创建候选')
    result = created[-1]['result']; figure = result.get('figure', {}); content = figure.get('content', {})
    # The actual composition producer resolves request references to complete
    # immutable source pins. Compare that complete saved representation, not
    # the intentionally smaller tool-input reference; never discard its hashes.
    expected_slots = copy.deepcopy(plan['request']['slots'])
    for slot in expected_slots:
        if slot.get('source') is not None:
            source = slot['source']
            slot['source'] = copy.deepcopy(needed[(source['id'], source['revision'])])
    _check(isinstance(figure.get('id'), str) and figure['id'] not in {x['id'] for x in pins}
           and _integer(figure.get('revision'), 1) and figure.get('project_id') == task['project_id'] and figure.get('kind') == 'figure'
           and figure.get('metadata', {}).get('origin_task_id') == task['id'] and figure.get('metadata', {}).get('candidate') is True
           and figure.get('title') == plan['request']['title'] and content.get('composition') is True
           and content.get('definition_schema') == 'research-partner-main-figure/1'
           and _hex(result.get('definition_sha256')) and content.get('definition_sha256') == result['definition_sha256']
           and _native_json(content.get('slots')) == _native_json(expected_slots) and result.get('executed') is False
           and result.get('definition_path') == 'figures/' + figure['id'] + '/main/figure.yaml'
           and all(x['result'] == result for x in created), '领域实际候选/主图定义目标不符')
    pages = content.get('pages', [])
    _check(isinstance(pages, list) and len(pages) == 1 and pages[0].get('id') == 'main'
           and pages[0].get('width') == plan['request'].get('width', 1200)
           and pages[0].get('height') == plan['request'].get('height', 600), '目标主图画布不是冻结定义')
    last = assistant[-1]
    _check(completed[last['data']['step']][1] == {'kind': 'stop'}
           and last['seq'] > max(x['result_seq'] for x in created)
           and all(x.get('type') in {'text', 'reasoning'} for x in last['data']['message']['content']), '最后own assistant不是完成工具后的自身最终正文')
    text = ''.join(x['text'] for x in last['data']['message']['content'] if x.get('type') == 'text')
    if 'reply_sha256' in receipt:
        _check(receipt['reply_sha256'] == digest(text.encode()), 'driver已有reply SHA不属于最后自身消息')
    payload = _json(text); _check(isinstance(payload, dict), '最终候选不是原note合同的JSON对象')
    return {'payload': payload, 'text': text,
            'candidate': {'id': figure['id'], 'revision': figure['revision'], 'sha256': digest(figure), 'definition_sha256': result['definition_sha256']},
            'provenance': {'transport': TRANSPORT, 'task_id': task['id'], 'project_id': task['project_id'], 'session_id': receipt['session_id'],
                           'plan_sha256': plan['sha256'], 'egress_sha256': plan['egress_sha256'], 'definition_sha256': definition['sha256'],
                           'driver_receipt_canonical_sha256': digest(receipt), 'durable_jsonl_sha256': digest(durable_jsonl),
                           'first_seq': first, 'final_seq': final, 'assistant_seq': last['seq'], 'assistant_message_id': last['data']['message']['id'],
                           'reply_sha256': digest(text.encode()), 'reply_sha256_origin': 'computed_from_durable_own_assistant_not_historical_receipt',
                           'prompt_seq': prompt[0][0], 'prompt_sha256': digest(expected_prompt.encode()),
                           'actual_source_reads': len(reads), 'tool_results': successful, 'tool_failures': failures,
                           'stream_settlements': [{'request_id': x['request_id'], 'assistant_seq': e['seq'], 'request_sha256': x['request_sha256'],
                                                   'request_bytes_verification': 'exact_utf8_sha_and_durable_messages_catalog_checked', 'started_at': x['started_at'],
                                                   'local_finished_at': x['local_finished_at'], 'usage': x.get('usage'), 'finish': x['finish']} for x, e in zip(streams, assistant)]},
            'accounting': {'observed_native_streams': len(streams), 'provider_invocation_attempts': None, 'actual_bill_usd': None,
                           'usage': [copy.deepcopy(x.get('usage')) for x in streams], 'usage_complete': all(x.get('usage') is not None for x in streams)},
            'verification_status': 'PROTOCOL_CHECKED_STORE_PENDING', 'protocol_evidence_checked': True, 'native_execution_verified': False,
            'pending_root_checks': ['commission.validate_candidate(note,task)', 'saved_source_objects_and_permissions',
                                    'same_task_saved_composition_candidate', 'definition_file_bytes', 'unchanged_human_main_and_adopted_heads',
                                    'parent_attempt_and_billing_ledger'],
            'scientific_or_human_acceptance': 'not_implied'}


def verify_native_figure(task, receipt, durable_jsonl, *, expected_cwd, expected_prompt):
    """Pure public boundary; malformed evidence always refuses as a Problem."""
    try:
        return _verify_native_figure(task, receipt, durable_jsonl,
                                     expected_cwd=expected_cwd, expected_prompt=expected_prompt)
    except Problem:
        raise
    except (KeyError, TypeError, AttributeError, ValueError, UnicodeError, RecursionError, OverflowError, BridgeError):
        raise Problem('原生主图证据字段/完整原合同无效', 'native_figure_evidence_invalid', 409) from None
