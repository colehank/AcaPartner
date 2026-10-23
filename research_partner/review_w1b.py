"""Workdesk adapter for existing manuscript rounds and persistent user opinions.

Annotations keep their existing identity/anchors; deleted draft opinions remain
in history. Submission freezes the public ReviewRound shape and delegates to
the existing guarded v2 candidate pipeline. No model response edits the source.
"""
import copy
import json
import threading
from .store import require, digest, encoded, uid, now
from .manuscript_revision import actor

LOCK=threading.RLock()

def anchor_for(block,value,blocks=None):
    if isinstance(value,dict) and value.get('kind')=='manuscript_range':
        from .manuscript_range import validate_range
        require(value.get('block_id')==block['id'],'选区起点不属于目标段落')
        return validate_range(blocks,value)
    anchor=value if value is not None else {'block_id':block['id'],'quote':block['text']}
    require(isinstance(anchor,dict) and anchor.get('block_id')==block['id'],'选区不属于目标段落')
    if 'start' in anchor or 'end' in anchor:
        require(set(anchor)=={'block_id','start','end','quote'} and type(anchor['start']) is int and type(anchor['end']) is int and 0<=anchor['start']<anchor['end']<=len(block['text']),'选区范围无效')
        require(block['text'][anchor['start']:anchor['end']]==anchor['quote'],'选中文字与已保存稿件不同，意见未创建','anchor_conflict',409)
    else:require(anchor=={'block_id':block['id'],'quote':block['text']},'整段锚点与原文不同')
    return copy.deepcopy(anchor)


def caption_anchor(obj, component_id, value=None):
    from .manuscript_revision import target_value
    require(isinstance(component_id,str) and component_id,'图注需要已保存的组件标识')
    component,text=target_value(obj,{'field':'caption','component_id':component_id})
    anchor=value if value is not None else {'field':'caption','component_id':component_id,'quote':text}
    required={'field','component_id','quote'}
    require(isinstance(anchor,dict) and anchor.get('field')=='caption' and anchor.get('component_id')==component_id,'选区不属于目标图注')
    if 'start' in anchor or 'end' in anchor:
        require(set(anchor)==required|{'start','end'} and type(anchor.get('start')) is int and type(anchor.get('end')) is int and 0<=anchor['start']<anchor['end']<=len(text),'图注选区范围无效')
        require(text[anchor['start']:anchor['end']]==anchor['quote'],'图注选中文字与当前保存版不同','anchor_conflict',409)
    else:require(set(anchor)==required and anchor['quote']==text,'整段图注锚点与原文不同','anchor_conflict',409)
    return {**copy.deepcopy(anchor),'component_ref_sha256':digest(component)}


def load(app, project, c=None):
    if c is None:return app.store.setting('desk_review:'+project['id'], {'revision':0,'opinions':[],'rounds':[],'history':[]})
    row=c.execute('SELECT value FROM kv WHERE key=?',('desk_review:'+project['id'],)).fetchone()
    return json.loads(row[0]) if row else {'revision':0,'opinions':[],'rounds':[],'history':[]}


def save(app, project, state, principal, event, c):
    state['revision']+=1
    state['history'].append({'revision':state['revision'],'at':now(),'actor':actor(principal),'event':event})
    require(len(encoded(state).encode())<=4*1024*1024,'审阅记录超出本轮有界上下文；原记录保留','context_limit',413)
    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('desk_review:'+project['id'],encoded(state)))
    return state


def assert_round_binding(app, binding, c):
    state=load(app,{'id':binding['project_id']},c)
    round=next((r for r in state.get('rounds',[]) if r['snapshot']['id']==binding['round_id']),None)
    require(round and round['status']=='submitted' and digest(round['snapshot'])==binding['snapshot_sha256'],
            '意见回合已撤回或上下文变化；旧候选仅保留审阅','proposal_superseded',409)
    current={i['id']:i for i in state['opinions']}
    require(all(i['id'] in current and not current[i['id']]['deleted'] and current[i['id']]['revision']==i['revision'] for i in round['opinions']),
            '提交后意见已修改或删除；不采用旧候选','proposal_superseded',409)


def dispatch(app,data,project,scope,principal):
    principal=principal or {'kind':'local_operator'}
    require(scope is None or principal['kind']!='local_operator','受限操作需要当前身份','forbidden',403)
    if data['action']=='desk.review.preview':
        from .review_visual_preview import preview
        def check(c):
            state=load(app,project,c)
            require(data.get('expected_review_revision')==state['revision'],'意见列表已改变','conflict',409)
            found=next((r for r in state['rounds'] if r['task_id']==data.get('task_id')),None)
            require(found and found['status']=='submitted','本回合不存在或已经撤回','forbidden',403)
        return preview(app,data,scope,principal,precheck=check)
    if data['action']=='desk.review.decide':
        task=app.store.task(data.get('task_id'))
        if task['payload'].get('context',{}).get('manuscript_revision',{}).get('version')==3:
            from .review_figure_round import decide
            return decide(app,data,project,scope,principal)
    with LOCK:
        # Runtime cancellation owns its mutex/transaction; perform it before
        # our transaction. A cancellation without a state update stays fenced.
        if data["action"]=="desk.review.withdraw":
            state=load(app,project)
            require(data.get("expected_review_revision")==state["revision"],"意见列表已改变","conflict",409)
            round=next((r for r in state["rounds"] if r["task_id"]==data.get("task_id")),None)
            require(round and round["status"]=="submitted","回合不存在或已撤回","conflict",409)
            task=app.store.task(round["task_id"])
            if app.runner and task["status"] not in {"deliverable","cancelled"}:app.runner.control(task["id"],"cancel")
        needs_definition = data['action'] in {'desk.review.change', 'desk.review.submit'} and (
            data.get('field') == 'slot_layout' or any(i.get('field') == 'slot_layout' for i in load(app, project)['opinions']))
        if needs_definition:
            from .manuscript_main_round import locked
            with locked(app, project['id']): result = _dispatch(app,data,project,scope,principal)
        else: result=_dispatch(app,data,project,scope,principal)
        if data["action"]=="desk.review.submit" and app.runner:app.runner.wake()
        return result


def _dispatch(app,data,project,scope,principal):
    action=data['action'];primary=project['metadata']['article']['primary_manuscript_id']
    if action=='desk.review.read':
        state=load(app,project)
        state['annotations']=app.store.annotations(primary)
        from .review_figure_round import visual_item,writable
        for ident in sorted({i['base_ref']['id'] for i in state['opinions'] if visual_item(i)}):
            with app.store.read_snapshot() as reader: writable(app,ident,project['id'],scope,reader)
            state['annotations'].extend(app.store.annotations(ident))
        state['providers']=[{'id':key,'route':cfg.get('route'),'authorized':cfg.get('authorized') is True}
                            for key,cfg in app.config.get('providers',{}).items() if cfg.get('route') in {'codex','deepseek_harness'}]
        state['runtime_running']=bool(app.runner and app.runner.status().get('running'))
        return state
    if action=='desk.review.view':
        state=load(app,project)
        require(any(r['task_id']==data.get('task_id') for r in state['rounds']),'本任务不属于此项目审阅回合','forbidden',403)
        return app.dispatch({'action':'manuscript.revision.view','task_id':data['task_id']},scope,principal=principal)
    native_note_snapshot=None
    if action=='desk.review.submit' and 'native_note_refs' in data:
        require(set(data)<={'action','project_id','expected_review_revision','expected_manuscript_revision','request','provider_id','budget','request_key','native_note_refs','dependency_groups','slot_adoptions'},'回合含未支持字段')
        if data.get('request_key') not in load(app,project).get('submissions',{}):
            from .native_review_context import freeze_notes
            native_note_snapshot=freeze_notes(app,project['id'],data['native_note_refs'],scope,principal)
    with app.store.transaction() as c:
        state=load(app,project,c)
        if action=='desk.review.submit' and data.get('request_key') in state.get('submissions',{}):
            previous=state['submissions'][data['request_key']]
            require(previous['input_sha256']==digest({'data':data,'principal':principal}),'同一提交请求不能改变内容或身份','idempotency_conflict',409)
            return {'task':app.store.task(previous['task_id'],c),'review':state}
        require(data.get('expected_review_revision')==state['revision'],'意见列表已在另一窗口改变，请重新读取','conflict',409)
        if action=='desk.review.change':
            op=data.get('op');require(op in {'create','edit','delete','restore','reanchor'},'意见操作不支持')
            from .manuscript_revision import source
            obj=source(app,primary,scope,c)
            require(obj['revision']==data.get('expected_manuscript_revision'),'稿件已改变，请重新读取后定位意见','conflict',409)
            from .review_figure_round import visual_item,change as visual_change
            existing=next((i for i in state['opinions'] if i['id']==data.get('id')),None)
            if data.get('field') in {'visual_overlays', 'slot_layout'} or existing and visual_item(existing):
                return visual_change(app,data,project,state,obj,scope,principal,c)
            require(set(data)<={'action','project_id','expected_review_revision','expected_manuscript_revision','op','id','block_id','field','component_id','text','anchor'},'意见含未支持字段')
            if op=='create':
                if data.get('field')=='caption':
                    require('block_id' not in data,'图注意见不能同时指定正文目标')
                    anchor=caption_anchor(obj,data.get('component_id'),data.get('anchor'))
                    target={'field':'caption','component_id':data['component_id']}
                else:
                    require('field' not in data and 'component_id' not in data,'意见目标字段不支持')
                    block=next((b for b in obj['content']['blocks'] if b['id']==data.get('block_id')),None)
                    require(block is not None,'意见目标不属于当前稿件')
                    anchor=anchor_for(block,data.get('anchor'),obj['content']['blocks']);target={'block_id':block['id']}
                text=data.get('text');require(isinstance(text,str) and 0<len(text.strip())<=4000,'意见需要1–4000字')
                annotation=app.store.annotate(primary,obj['revision'],anchor,text,connection=c)
                item={'id':annotation['id'],**target,'anchor':anchor,'text':text,'revision':1,'base_ref':{'id':primary,'revision':obj['revision']},'deleted':False,'created_by':actor(principal),'created_at':now()}
                state['opinions'].append(item)
            else:
                item=next((i for i in state['opinions'] if i['id']==data.get('id')),None)
                require(item is not None,'意见不存在','not_found',404)
                before=copy.deepcopy({k:v for k,v in item.items() if k!='history'})
                if op=='edit':
                    require(not item['deleted'],'请先恢复已删除意见')
                    text=data.get('text');require(isinstance(text,str) and 0<len(text.strip())<=4000,'意见需要1–4000字')
                    row=c.execute('SELECT * FROM annotations WHERE id=? AND object_id=?',(item['id'],primary)).fetchone()
                    require(row,'批注不存在','not_found',404)
                    c.execute('UPDATE annotations SET text=? WHERE id=?',(text,item['id']))
                    app.store.event(c,'annotation.updated',primary,{'id':item['id'],'previous_text':row['text']},actor(principal))
                    item['text']=text
                elif op=='reanchor':
                    require(not item['deleted'],'请先恢复已删除意见')
                    if item.get('field')=='caption':
                        require(data.get('field')=='caption' and 'block_id' not in data and data.get('anchor') is not None,'图注重新定位需要明确保存选区')
                        anchor=caption_anchor(obj,data.get('component_id'),data['anchor']);target={'field':'caption','component_id':data['component_id']}
                    else:
                        require('field' not in data and 'component_id' not in data,'正文意见不可伪装成图注目标')
                        block=next((b for b in obj['content']['blocks'] if b['id']==data.get('block_id')),None)
                        require(block is not None and data.get('anchor') is not None,'重新定位需要明确的已保存选区')
                        anchor=anchor_for(block,data['anchor'],obj['content']['blocks']);target={'block_id':block['id']}
                    row=c.execute('SELECT anchor,revision FROM annotations WHERE id=? AND object_id=?',(item['id'],primary)).fetchone()
                    require(row,'批注不存在','not_found',404)
                    c.execute("UPDATE annotations SET anchor=?,revision=?,status='anchored' WHERE id=?",(encoded(anchor),obj['revision'],item['id']))
                    app.store.event(c,'annotation.reanchored',primary,{'id':item['id'],'previous_anchor':json.loads(row['anchor']),'previous_revision':row['revision'],'anchor':anchor,'revision':obj['revision']},actor(principal))
                    item.update(**target,anchor=anchor,base_ref={'id':primary,'revision':obj['revision']})
                else:item['deleted']=op=='delete'
                item['revision']+=1
                item.setdefault('history',[]).append(before)
            return save(app,project,state,principal,{'op':op,'opinion_id':item['id']},c)
        if action=='desk.review.submit':
            require(set(data)<={'action','project_id','expected_review_revision','expected_manuscript_revision','request','provider_id','budget','request_key','native_note_refs','dependency_groups','slot_adoptions'},'回合含未支持字段')
            if app.config.get('development_budget'):
                from .development_budget import Budget
                Budget(app.config['development_budget']).check()
            require(app.runner is not None,'执行器未启动；意见保留，没有创建假Agent任务','runtime_unavailable',503)
            active=[i for i in state['opinions'] if not i['deleted']]
            require(active and len(active)<=48,'请选择本轮1–48条保留意见')
            from .manuscript_revision import source
            obj=source(app,primary,scope,c)
            require(obj['revision']==data.get('expected_manuscript_revision'),'稿件已改变，请重新读取后提交整轮','conflict',409)
            draft_row=c.execute('SELECT value FROM kv WHERE key=?',('desk_w1a:drafts:'+project['id'],)).fetchone()
            dirty=(json.loads(draft_row[0]) if draft_row else {}).get('value',{}).get('manuscript',{}).get('dirty')
            require(not dirty,'请先保存或撤销本轮文字草稿，再固定提交上下文','unsaved_manuscript',409)
            blocks={b['id']:b for b in obj['content']['blocks']}
            from .review_figure_round import visual_item,targets as round_targets,groups
            text_targets=[]
            for item in active:
                if visual_item(item):targets=[]
                elif item.get('field')=='caption':targets=[{'field':'caption','component_id':item['component_id']}]
                else:
                    from .manuscript_range import annotation_targets, validate_range
                    if item['anchor'].get('kind')=='manuscript_range':validate_range(obj['content']['blocks'],item['anchor'])
                    ids=annotation_targets(item['anchor'])
                    require(ids and all(ident in blocks for ident in ids),'意见锚点的段落已删除，请重新定位','conflict',409)
                    targets=[{'block_id':ident} for ident in ids]
                text_targets.append(targets)
            selected,opinion_targets=round_targets(active,obj,text_targets)
            version=3 if any(visual_item(i) for i in active) or 'dependency_groups' in data or 'slot_adoptions' in data else 2
            from .manuscript_revision import submit_round
            request={'action':'manuscript.revision.submit','contract_version':version,'object_id':primary,'expected_revision':obj['revision'],
                     'targets':selected,
                     'opinions':[{'id':i['id'],'annotation_id':i['id'],'target_indices':index} for i,index in zip(active,opinion_targets)],
                     'request':data.get('request'),'provider_id':data.get('provider_id'),
                     'budget':data.get('budget',{'max_model_calls':2,'timeout_seconds':180}),'request_key':data.get('request_key')}
            if 'native_note_refs' in data:request['native_note_refs']=data['native_note_refs']
            if version==3:request['dependency_groups']=groups(data.get('dependency_groups',[]),active,opinion_targets)
            if 'slot_adoptions' in data:
                from .review_figure_round import slot_adoptions
                request['slot_adoptions']=slot_adoptions(data['slot_adoptions'],active,opinion_targets,data.get('dependency_groups',[]))
            task=submit_round(app,request,scope,principal,connection=c,include_artifact_context=True,native_note_snapshot=native_note_snapshot)
            if not any(r['task_id']==task['id'] for r in state['rounds']):
                snapshot={'id':uid('ROUND'),'project_id':project['id'],'items':[{'feedback_id':i['id'],'revision':i['revision'],'text_hash':digest(i['text'].encode()),'base_ref':i['base_ref']} for i in active],
                          'created_at':now(),'constraints':{'new_compute':'not_authorized','delegation_ref':None},'withdrawn_ids':[]}
                state['rounds'].append({'task_id':task['id'],'snapshot':snapshot,'opinions':copy.deepcopy(active),'status':'submitted'})
                state.setdefault('submissions',{})[data['request_key']]={'task_id':task['id'],'input_sha256':digest({'data':data,'principal':principal})}
                key='manuscript_revision:grant:'+task['id']
                grant=json.loads(c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()[0])
                grant['desk_review_round']={'project_id':project['id'],'round_id':snapshot['id'],'snapshot_sha256':digest(snapshot)}
                c.execute('UPDATE kv SET value=? WHERE key=?',(encoded(grant),key))
                save(app,project,state,principal,{'op':'submit','task_id':task['id'],'snapshot_sha256':digest(snapshot)},c)
            return {'task':task,'review':state}
        if action in {'desk.review.withdraw','desk.review.decide','desk.review.authorize_decisions'}:
            round=next((r for r in state['rounds'] if r['task_id']==data.get('task_id')),None)
            require(round is not None,'本任务不属于此审阅回合','forbidden',403)
            if action=='desk.review.withdraw':
                require(round['status']=='submitted','此回合已经撤回','conflict',409)
                task=app.store.task(round['task_id'],c)
                c.execute("UPDATE tasks SET status='cancelled',error=?,updated_at=? WHERE id=?",('Review round withdrawn by owner',now(),task['id']))
                lease_row=c.execute('SELECT value FROM kv WHERE key=?',('execution:'+task['id'],)).fetchone()
                if lease_row:
                    lease=json.loads(lease_row[0]);lease['state']='revoked'
                    c.execute('UPDATE kv SET value=? WHERE key=?',(encoded(lease),'execution:'+task['id']))
                round['status']='withdrawn';round['snapshot']['withdrawn_ids']=[i['feedback_id'] for i in round['snapshot']['items']]
                return save(app,project,state,principal,{'op':'withdraw','task_id':task['id']},c)
            require(round['status']=='submitted','此回合已撤回；候选和已采用历史保留','conflict',409)
            current={i['id']:i for i in state['opinions']}
            if any(d.get('decision')=='accept' for d in data.get('decisions',[])):
                require(all(i['id'] in current and not current[i['id']]['deleted'] and current[i['id']]['revision']==i['revision'] for i in round['opinions']),
                        '提交后意见已编辑或删除，旧候选不得覆盖新要求','conflict',409)
            request={k:v for k,v in data.items() if k not in {'project_id','expected_review_revision'}}
            request['action']='manuscript.revision.authorize_decisions' if action=='desk.review.authorize_decisions' else 'manuscript.revision.decide'
            from .manuscript_revision import dispatch as decide
            return decide(app,request,scope,principal,connection=c)
    require(False,'工作桌审阅命令不支持','unsupported_action')
