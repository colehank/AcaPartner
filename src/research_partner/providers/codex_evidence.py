"""Verify the real AppServer wire protocol without coercing it into CLI/MCP.

This verifies protocol and domain identity. Same-UID files still do not establish
a protected execution identity, scientific approval or human acceptance.
"""
import json
from research_partner.storage.store import require, digest


def verify_wire(snapshot, receipt):
    require(receipt.get('transport')=='app_server_dynamic' and receipt.get('route')=='codex',
            '回执不是原生动态工具协议', 'domain_tools_unverified', 409)
    require(snapshot.get('raw_evidence_complete') is True and not snapshot.get('overflow_digests'),
            '原生消息证据不完整', 'domain_tools_unverified', 409)
    values=[];last_sequence=-1
    for expected, entry in enumerate(snapshot.get('wire_messages', [])):
        raw=entry.get('raw_json')
        require(isinstance(raw,str) and digest(raw.encode())==entry.get('sha256')
                and len(raw.encode())==entry.get('utf8_bytes') and entry.get('direction') in {'in','out'},
                '原生消息原字节与摘要不符', 'integrity', 409)
        sequence=entry.get('sequence')
        require(type(sequence) is int and sequence>last_sequence, '原生消息顺序身份不符', 'integrity', 409)
        last_sequence=sequence
        value=json.loads(raw)
        require(isinstance(value,dict), '原生消息不是对象', 'integrity', 409)
        values.append((entry,value))
    def requests(method):
        return [(e,v) for e,v in values if e['direction']=='out' and v.get('method')==method and e.get('delivery')=='sent']
    def response(ident):
        found=[v for e,v in values if e['direction']=='in' and v.get('id')==ident and 'method' not in v]
        require(len(found)==1 and 'error' not in found[0] and isinstance(found[0].get('result'),dict),
                '权威原生RPC响应缺失或歧义', 'domain_tools_unverified', 409)
        return found[0]
    starts=requests('thread/start');turns=requests('turn/start')
    require(len(starts)==1 and len(turns)==1, '本任务必须只有一个新原生thread/turn请求', 'domain_tools_unverified', 409)
    start=response(starts[0][1]['id']);turn=response(turns[0][1]['id'])
    start_entry=next(e for e,v in values if e['direction']=='in' and v==start)
    turn_entry=next(e for e,v in values if e['direction']=='in' and v==turn)
    thread_id=start['result']['thread']['id'];turn_id=turn['result']['turn']['id']
    require(starts[0][1]['id']==snapshot['request_ids']['thread/start']
            and turns[0][1]['id']==snapshot['request_ids']['turn/start']
            and start==snapshot.get('thread_start_response') and turn==snapshot.get('turn_start_response')
            and turns[0][1]['params']['threadId']==thread_id
            and thread_id==snapshot.get('thread_id')==receipt.get('session_id')
            and turn_id==snapshot.get('turn_id')==receipt.get('native_turn_id'),
            '原生请求、响应与任务会话绑定不一致', 'domain_tools_unverified', 409)
    require(starts[0][0]['sequence']<start_entry['sequence']<turns[0][0]['sequence']<turn_entry['sequence'],
            '原生创建请求与权威回包顺序不符', 'domain_tools_unverified', 409)
    declared=starts[0][1]['params'].get('dynamicTools',[])
    require([t.get('name') for t in declared]==['read_figure_context','create_main_figure'],
            '原生声明不是固定的两个领域工具', 'domain_tools_unverified', 409)
    require(start['result'].get('model')==receipt.get('model')==receipt.get('requested_model'),
            '原生实际模型与冻结请求不同', 'domain_tools_unverified', 409)
    require(starts[0][1]['params'].get('model')==turns[0][1]['params'].get('model')==receipt['requested_model'],
            '原生请求模型与冻结模型不同', 'domain_tools_unverified', 409)
    inputs=turns[0][1]['params'].get('input')
    require(isinstance(inputs,list) and len(inputs)==1 and inputs[0].get('type')=='text'
            and isinstance(inputs[0].get('text'),str),
            '原生任务提示不是唯一固定文本', 'domain_tools_unverified', 409)
    prompt=inputs[0]['text'];coordinator=None
    if '\nCOORDINATOR GUIDANCE' in prompt:
        tail=prompt.rsplit('\nCOORDINATOR GUIDANCE',1)[1]
        require('\n' in tail,'原生任务指导缺少正文', 'domain_tools_unverified',409)
        try:coordinator=json.loads(tail.split('\n',1)[1].strip())
        except ValueError:require(False,'原生任务指导无法核对', 'domain_tools_unverified',409)
        require(isinstance(coordinator,(dict,list)),'原生任务指导类型无效', 'domain_tools_unverified',409)
    provenance={'native_request_id':turns[0][1]['id'],'native_turn_id':turn_id,
                'prompt_sha256':digest(prompt.encode()),'coordinator_input':coordinator}
    require(receipt.get('input_provenance',provenance)==provenance,
            '原生回执指导不属于实际发送提示', 'domain_tools_unverified',409)
    terminals=[v for e,v in values if e['direction']=='in' and v.get('method')=='turn/completed'
               and v.get('params',{}).get('threadId')==thread_id and v.get('params',{}).get('turn',{}).get('id')==turn_id]
    require(len(terminals)==1 and terminals[0]==snapshot.get('terminal')
            and terminals[0]['params']['turn']['status']=='completed'
            and snapshot.get('state')=='completed' and snapshot.get('native_terminal_observed') is True
            and receipt.get('native_terminal_confirmed') is True,
            '原生模型没有本任务可核对的成功终态', 'domain_tools_unverified', 409)
    terminal_sequence=next(e['sequence'] for e,v in values if e['direction']=='in' and v==terminals[0])
    completed=[];messages=[];matched_requests=[]
    for entry,v in values:
        p=v.get('params',{})
        if entry['direction']!='in' or p.get('threadId')!=thread_id or p.get('turnId')!=turn_id:
            continue
        if v.get('method')=='item/tool/call':matched_requests.append(v)
        if v.get('method')!='item/completed':continue
        item=p.get('item',{})
        require(turns[0][0]['sequence']<entry['sequence']<terminal_sequence,
                '原生完成对象不在本次请求与终态之间', 'domain_tools_unverified', 409)
        if item.get('type')=='agentMessage':messages.append(item)
        elif item.get('type')=='dynamicToolCall':completed.append(item)
        elif item.get('type') not in {'userMessage','reasoning','plan'}:
            require(False,'本次原生执行出现未授权工具或宿主动作', 'domain_tools_unverified', 409)
    finals=[item for item in messages if item.get('phase')=='final_answer']
    final=finals[-1] if finals else (messages[-1] if messages and messages[-1].get('phase') is None else None)
    require(final and final.get('text')==snapshot.get('final_reply')
            and digest(final['text'].encode())==receipt.get('reply_sha256'),
            '候选正文不属于本次已完成原生回复', 'domain_tools_unverified', 409)
    successful=[];failed=[]
    for item in completed:
        require(item.get('tool') in {'read_figure_context','create_main_figure'} and item.get('namespace') is None,
                '原生领域工具类型不符', 'domain_tools_unverified', 409)
        calls=[v for v in matched_requests if v['params']['callId']==item['id']]
        require(calls and all(v['params']['tool']==item['tool'] and v['params']['arguments']==item.get('arguments') for v in calls),
                '原生完成工具与实际服务请求不符', 'domain_tools_unverified', 409)
        replies=[v for e,v in values if e['direction']=='out' and e.get('delivery')=='sent'
                 and 'method' not in v and v.get('id') in {c['id'] for c in calls}]
        require(replies and all(v.get('result',{}).get('success')==item.get('success')
                and v.get('result',{}).get('contentItems')==item.get('contentItems') for v in replies),
                '原生完成工具与实际发送的服务回执不符', 'domain_tools_unverified', 409)
        completed_sequence=next(e['sequence'] for e,v in values if e['direction']=='in' and v.get('method')=='item/completed' and v.get('params',{}).get('item')==item and v.get('params',{}).get('threadId')==thread_id and v['params'].get('turnId')==turn_id)
        for reply in replies:
            reply_sequences=[e['sequence'] for e,v in values if e['direction']=='out' and e.get('delivery')=='sent' and v==reply]
            call_sequences=[e['sequence'] for e,v in values if e['direction']=='in' and v in calls and v['id']==reply['id']]
            require(all(turn_entry['sequence']<position<completed_sequence and any(turns[0][0]['sequence']<request_position<position for request_position in call_sequences) for position in reply_sequences),
                    '领域请求、服务回包、原生完成事件顺序不符', 'domain_tools_unverified', 409)
        if item.get('status')=='completed' and item.get('success') is True:
            content=item.get('contentItems')
            require(isinstance(content,list) and len(content)==1 and content[0].get('type')=='inputText',
                    '领域工具没有完整JSON服务结果', 'domain_tools_unverified', 409)
            result=json.loads(content[0]['text'])
            require(isinstance(result,dict) and 'error' not in result, '领域服务结果不成功', 'domain_tools_unverified', 409)
            successful.append({'item':item,'result':result})
        else:
            content=item.get('contentItems') or []
            result=json.loads(content[0]['text']) if len(content)==1 and content[0].get('type')=='inputText' else {}
            failed.append({'tool':item['tool'],'call_id':item['id'],'arguments':item['arguments'],'response':result})
    return {'thread_id':thread_id, 'turn_id':turn_id, 'successful':successful,
            'final_reply':final['text'], 'declared':declared,'failed':failed,
            'input_provenance':provenance}


def verified_figure(app, task, snapshot, receipt):
    wire=verify_wire(snapshot,receipt)
    plan=task['payload'].get('context',{}).get('figure_composition',{})
    definition=plan.get('native_definition',{})
    require(receipt.get('task_id')==task['id'] and receipt.get('project_id')==task['project_id']
            and task['payload']['kind']=='figure_composition' and plan.get('native_transport')=='app_server_dynamic'
            and definition.get('transport')=='app_server_dynamic' and definition.get('model')==receipt.get('model')
            and digest({k:v for k,v in definition.items() if k!='sha256'})==definition.get('sha256'),
            '原生证明不属于任务冻结模型和协议', 'domain_tools_unverified', 409)
    needed={(r['id'],r['revision']):r for r in plan['fixed_sources']};observed=set();created=[]
    for entry in wire['successful']:
        item,result=entry['item'],entry['result']
        require(item['arguments'].get('project_id')==task['project_id'],
                '原生工具参数越出任务项目', 'domain_tools_unverified', 409)
        figure=result.get('figure',{})
        if item['tool']=='read_figure_context':
            args=item['arguments'];key=(args.get('id'),args.get('revision'))
            require(key in needed and figure.get('id')==key[0] and figure.get('revision')==key[1]
                    and digest(figure)==needed[key]['sha256'], '原生服务读取不是冻结子图', 'domain_tools_unverified', 409)
            observed.add(key)
        else:created.append(result)
    require(set(needed)<=observed and created, '原生事件未读取全部固定来源或保存实际候选', 'domain_tools_unverified', 409)
    saved=app.store.setting('composition_task_candidate:'+task['id'])
    require(saved and digest(app.store.get(saved['id'],saved['revision']))==saved['sha256'],
            '原生组成候选与保存来源不一致', 'domain_tools_unverified', 409)
    require(all(v.get('figure',{}).get('id')==saved['id'] and v['figure'].get('revision')==saved['revision']
                and digest(v['figure'])==saved['sha256'] and v.get('definition_sha256')==saved['definition_sha256'] for v in created),
            '原生服务创建回执与实际保存候选不一致', 'domain_tools_unverified', 409)
    return {**saved, 'native_dynamic_events_sha256':receipt['events_sha256'],
            'actual_source_reads':len(needed), 'native_tool_event_ids':[x['item']['id'] for x in wire['successful']],
            'native_tool_failures':wire['failed'],
            'scientific_or_human_acceptance':'not_implied'}
