"""Verify a stopped post-candidate bookkeeping tail for explicit recovery only."""
import json
import uuid
from pathlib import Path
from .store import require,digest


def verify(directory,tail,selected,contract,evidence_ids):
    from .providers import _controlled_file
    def check(ok):require(ok,'候选之后不是可核验的独立审查打包/观察登记尾部','candidate_checkpoint_invalid',409)
    def read(path,limit=131072):
        raw=_controlled_file(directory,path,limit)
        try:value=json.loads(raw)
        except ValueError:check(False)
        return value,raw
    announced={};pending={};done=[];seen=set();accompanying=[];text_bytes=0
    for event in tail:
        kind=event.get('type');data=event.get('data',{});check(isinstance(data,dict))
        if kind in {'step/start','step/end','turn/end'}:continue
        if kind=='assistant/attempt':check(data.get('stream')==[] and not pending and not announced);continue
        if kind=='assistant/message':
            blocks=data.get('message',{}).get('content',[])
            check(isinstance(blocks,list) and len(blocks) in {1,2} and not pending and not announced)
            # A bounded text prefix is presentation only. Preserve it verbatim;
            # it never substitutes for the matched call/result/audit below.
            # Keep the extension narrow: one text, then the one allowed call.
            if len(blocks)==2:
                text=blocks[0]
                check(isinstance(text,dict) and set(text)=={'type','text'} and text['type']=='text' and isinstance(text['text'],str))
                size=len(text['text'].encode('utf-8'));text_bytes+=size
                check(0<size<=4096 and text_bytes<=8192)
                accompanying.append({'event_seq':event['seq'],'kind':'non_authoritative_accompanying_text',
                                     'text':text['text'],'sha256':digest(text['text'].encode('utf-8')),
                                     'scientific_approval':False,'user_acceptance':False})
            b=blocks[-1];check(isinstance(b,dict) and set(b)=={'type','id','name','arguments'}
                             and b.get('type')=='tool-call' and b.get('name') in {'prepare_independent_review','record_observation'}
                             and isinstance(b.get('arguments'),str))
            ident=b.get('id');check(isinstance(ident,str) and ident and ident not in seen)
            announced[ident]=b;seen.add(ident);continue
        if kind=='tool/call':
            ident=data.get('callId');check(isinstance(ident,str));b=announced.pop(ident,None)
            check(b is not None and data.get('name')==b['name'] and data.get('arguments')==b.get('arguments'))
            try:args=json.loads(data['arguments'])
            except (ValueError,TypeError,KeyError):check(False)
            check(isinstance(args,dict));pending[ident]={'name':b['name'],'args':args,'call_seq':event['seq']};continue
        check(kind=='tool/result')
        blocks=data.get('message',{}).get('content',[]);check(isinstance(blocks,list) and len(blocks)==1)
        b=blocks[0];check(isinstance(b,dict) and b.get('type')=='tool-result' and b.get('isError') is False)
        ident=b.get('toolCallId');check(isinstance(ident,str));call=pending.pop(ident,None);check(call is not None)
        parts=b.get('content');check(isinstance(parts,list) and len(parts)==1 and parts[0].get('type')=='text')
        try:result=json.loads(parts[0]['text'])
        except (ValueError,TypeError,KeyError):check(False)
        check(isinstance(result,dict));args=call['args'];record={k:call[k] for k in ('name','call_seq')}
        record.update(tool_call_id=ident,result_seq=event['seq'],result_sha256=digest(result))
        if call['name']=='record_observation':
            check(set(args)=={'observation','evidence_id'} and isinstance(args['observation'],str)
                  and 0<len(args['observation'].encode())<=8192 and args['evidence_id'] in evidence_ids)
            check(set(result)=={'origin','observation','evidence_id','at','tested_across_tasks','user_approval'}
                  and result.get('origin')=='agent_observation' and result.get('observation')==args['observation']
                  and result.get('evidence_id')==args['evidence_id'] and result.get('tested_across_tasks') is False
                  and result.get('user_approval') is False and isinstance(result.get('at'),str))
            matches=[]
            for path in (directory/'capsule/audit').glob('observation-*.json'):
                value,raw=read(path,32768)
                if value==result:matches.append({'path':path.name,'sha256':digest(raw)})
            check(len(matches)==1);record['audit']=matches[0]
        else:
            name=selected['receipt']['candidate']['name'];check(args=={'names':[name]})
            review_id=result.get('review_id')
            try:check(str(uuid.UUID(review_id))==review_id)
            except (ValueError,TypeError,AttributeError):check(False)
            root=directory/'capsule/reviews'/review_id;path=root/'packet.json'
            check(set(result)=={'review_id','packet','status','reviewed'} and result.get('packet')==str(path)
                  and result.get('status')=='pending_independent_review' and result.get('reviewed') is False)
            packet,packetraw=read(path);task,taskraw=read(root/'task.json')
            check(task==contract and digest(taskraw)==selected['receipt']['candidate']['contract_sha256'])
            check(packet.get('schema_version')==2 and packet.get('review_id')==review_id
                  and packet.get('task')==contract and packet.get('task_path')=='task.json'
                  and packet.get('contract_sha256')==digest(taskraw) and packet.get('paths_relative_to')=='packet_directory'
                  and packet.get('status')=='pending_independent_review' and packet.get('reviewed') is False)
            check(packet.get('artifacts')==[{'name':name,'sha256':selected['receipt']['candidate']['sha256'],'path':'artifacts/'+name}])
            raw=_controlled_file(directory,root/'artifacts'/name,131072);check(raw==selected['text'].encode())
            for evidence in contract['evidence']:
                raw=_controlled_file(directory,root/evidence['path'],65536);check(digest(raw)==evidence['sha256'])
            record.update(review_id=review_id,packet_sha256=digest(packetraw),candidate_sha256=digest(selected['text'].encode()))
        done.append(record)
    check(done and not pending and not announced)
    return {'kind':'verified_post_candidate_bookkeeping','actions':done,'tail_sha256':digest(tail),
            'candidate_unchanged':True,'scientific_approval':False,'observations_adopted_as_science':False,
            'non_authoritative_text':accompanying}
