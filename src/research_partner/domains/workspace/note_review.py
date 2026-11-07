"""Comments bind native notebook identity and exact file revision, never a copy.

The Markdown bytes and snapshots are authoritative. Feedback lives separately;
editing feedback neither rewrites the file nor erases its revision history.
"""
import copy
import hashlib
import json
from research_partner.storage.store import require, uid, now, encoded
from research_partner.domains.manuscripts.revision import actor


def dispatch(app,data,project,scope,principal):
    principal=principal or {'kind':'local_operator'}
    require(set(data)<={'action','project_id','relative_path','expected_revision','expected_content_sha256','op','id','text','start_offset','end_offset'},'笔记意见字段不支持')
    path=data.get('relative_path')
    document=app.notebook.dispatch({'action':'notes.read','project_id':project['id'],'request_id':uid('READ'),'payload':{'relative_path':path}})
    key='note_review:'+document['id']
    with app.store.transaction() as c:
        row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
        state=json.loads(row[0]) if row else {'revision':0,'opinions':[],'history':[]}
        if data['action']=='desk.note.review.change':
            require(state['revision']==data.get('expected_revision'),'笔记意见已改变','conflict',409)
            require(document['content_sha256']==data.get('expected_content_sha256'),'笔记文件已改变，请重新读取；未改写笔记','conflict',409)
            op=data.get('op');require(op in {'create','edit','delete','restore'},'笔记意见操作不支持')
            if op=='create':
                start,end=data.get('start_offset'),data.get('end_offset')
                require(type(start) is int and type(end) is int and 0<=start<=end<=len(document['markdown']),'笔记批注位置无效')
                text=data.get('text');require(isinstance(text,str) and 0<len(text.strip())<=4000,'意见需要1–4000字')
                item={'id':uid('NANN'),'text':text,'revision':1,'deleted':False,'author':actor(principal),
                      'base_ref':{'id':document['id'],'revision':document['revision'],'content_sha256':document['content_sha256']},
                      'anchor':{'start_offset':start,'end_offset':end,'offset_unit':'unicode_code_point','quote':document['markdown'][start:end]}}
                state['opinions'].append(item)
            else:
                item=next((i for i in state['opinions'] if i['id']==data.get('id')),None)
                require(item,'笔记意见不存在','not_found',404)
                state['history'].append({'before':copy.deepcopy(item),'at':now()})
                if op=='edit':
                    text=data.get('text');require(isinstance(text,str) and 0<len(text.strip())<=4000,'意见需要1–4000字')
                    item['text']=text
                else:item['deleted']=op=='delete'
                item['revision']+=1
            state['revision']+=1
            require(len(encoded(state).encode())<=4*1024*1024,'笔记意见超过有界容量，原记录保留','context_limit',413)
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,encoded(state)))
            app.store.event(c,'notes.feedback.'+op,project['id'],{'note_id':document['id'],'feedback_id':item['id'],'revision':item['revision']},actor(principal))
        else:require(data['action']=='desk.note.review.read','笔记意见操作不支持')
        revision_key='notebook:revision:'+project['id']+':'+hashlib.sha256(path.encode()).hexdigest()
        revisions=json.loads(c.execute('SELECT value FROM kv WHERE key=?',(revision_key,)).fetchone()[0])
        result=copy.deepcopy(state)
        for i in result['opinions']:
            a=i['anchor'];i['anchor_status']='anchored' if document['markdown'][a['start_offset']:a['end_offset']]==a['quote'] else 'text_changed'
        return {**result,'note_ref':{k:document[k] for k in ('id','project_id','relative_path','revision','content_sha256','authority_kind')},'file_revisions':revisions['history']}
