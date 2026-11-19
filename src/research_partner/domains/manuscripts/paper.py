"""Explicit operator saves reuse the tracked-edit engine in one transaction."""
import copy
import json
from research_partner.storage.store import require, digest, encoded
from research_partner.domains.manuscripts import formatting as fmt


def _caption_changes(data, obj):
    """Text-only edits to saved occurrences; all identity comes from the source.

    Validate the whole batch before the tracked body engine writes anything.
    Paper CAS protects the complete component metadata, while occurrence and
    before-text checks prevent applying an editor range to a different figure.
    """
    edits = data.get('captions', [])
    components = obj['content'].get('components', [])
    require(isinstance(edits, list) and len(edits) <= len(components), '稿内图注修改无效')
    seen = set()
    for edit in edits:
        require(isinstance(edit, dict) and set(edit) == {'index', 'component_id', 'component_revision', 'before', 'text'}, '稿内图注仅允许保存文字')
        index = edit['index']
        require(type(index) is int and 0 <= index < len(components) and index not in seen, '稿内图注位置无效或重复')
        seen.add(index)
        ref = components[index]
        require(isinstance(edit['component_id'], str) and type(edit['component_revision']) is int and
                isinstance(edit['before'], str) and isinstance(edit['text'], str), '稿内图注字段无效')
        require((ref.get('id') or ref.get('object_id')) == edit['component_id'] and
                ref.get('revision') == edit['component_revision'] and ref.get('caption') == edit['before'],
                '保存版图注或所在位置已变化；当前草稿保留', 'conflict', 409)
    return [edit for edit in edits if edit['text'] != edit['before']]


def save_direct(app,data,primary,scope,principal):
    principal=principal or {'kind':'local_operator'}
    require(set(data)<={'action','project_id','expected_revision','blocks','request_key','title','captions'},'稿件保存字段不支持')
    key=data.get('request_key')
    require(isinstance(key,str) and 0<len(key)<=160,'需要稳定保存请求身份')
    fingerprint=digest({'data':data,'principal':principal})
    with app.store.transaction() as c:
        obj=fmt._source(app,primary,scope,c,principal)
        receipt_key='desk_direct:'+primary+':'+key
        old_receipt=c.execute('SELECT value FROM kv WHERE key=?',(receipt_key,)).fetchone()
        if old_receipt:
            previous=json.loads(old_receipt[0])
            require(previous['input_sha256']==fingerprint,'同一保存请求不能改变内容或身份','idempotency_conflict',409)
            return previous['result']
        require(type(data.get('expected_revision')) is int and obj['revision']==data['expected_revision'],'稿件已变化，当前草稿保留','conflict',409)
        captions = _caption_changes(data, obj)
        if data['action'] == 'desk.paper.propose':
            require(not data.get('captions'), '图注修改须在编辑模式直接保存；当前正文和图注草稿保留')
        incoming=data.get('blocks')
        require(isinstance(incoming,list) and 0<len(incoming)<=1000,'稿件段落无效')
        require(all(isinstance(b,dict) and {'id','text'}<=set(b)<={'id','text','kind','level'} and isinstance(b['id'],str) and isinstance(b['text'],str) for b in incoming),'稿件段落字段无效')
        require(len({b['id'] for b in incoming})==len(incoming),'段落身份不能重复')
        old={b['id']:b for b in obj['content']['blocks']};new={b['id']:b for b in incoming}
        require([i for i in old if i in new]==[b['id'] for b in incoming if b['id'] in old],'段落重排需要明确布局操作，草稿保留','unsupported_reorder',409)
        require(all(all(k not in b or b[k]==old[b['id']].get(k) for k in ('kind','level')) for b in incoming if b['id'] in old),'既有段落类型不能在文字保存中改变')
        changes=[]
        for ident,b in old.items():
            if ident not in new:changes.append({'op':'delete','block_id':ident})
            elif b['text']!=new[ident]['text']:changes.append({'op':'replace','block_id':ident,'text':new[ident]['text']})
        previous='start'
        for b in incoming:
            if b['id'] not in old:
                changes.append({'op':'insert','block':{**b,'kind':b.get('kind','paragraph')},'after_block_id':previous})
            previous=b['id']
        title=data.get('title',obj['title'])
        require(isinstance(title,str) and 0<len(title.strip())<=200,'稿件标题需要1–200字')
        require(changes or title!=obj['title'] or captions,'没有文字或结构变化')
        if data['action']=='desk.paper.propose':
            require(changes and title==obj['title'],'建议修订只处理正文和段落，标题请直接保存')
            tracked=fmt._track(app,{'action':'manuscript.edit.track','object_id':primary,'expected_revision':obj['revision'],'changes':changes,'request_key':'suggest:'+key},scope,principal,c,obj)
            result={'object':obj,'edits':tracked,'source_changed':False}
            c.execute('INSERT INTO kv VALUES(?,?)',(receipt_key,encoded({'input_sha256':fingerprint,'result':result})))
            return result
        receipt=None
        if changes:
            tracked=fmt._track(app,{'action':'manuscript.edit.track','object_id':primary,'expected_revision':obj['revision'],'changes':changes,'request_key':'direct:'+key},scope,principal,c,obj)
            record=fmt._proposal(c,obj,tracked['proposal_id'])
            receipt=fmt._decide(app,{'action':'manuscript.edit.decide','object_id':primary,'proposal_id':tracked['proposal_id'],'expected_revision':obj['revision'],'expected_decision_version':tracked['decision_version'],'decisions':[{'change_id':r['id'],'decision':'accept'} for r in tracked['changes']],'request_key':'direct:'+key},principal,c,obj,record,direct_save=True,direct_caption_edits=captions,direct_title=title.strip() if title!=obj['title'] else None)
            obj=receipt['object']
        if not changes and (title!=obj['title'] or captions):
            content=copy.deepcopy(obj['content'])
            for edit in captions:
                content['components'][edit['index']]['caption']=edit['text']
            obj=app.store.save(primary,obj['revision'],content=content,title=title.strip(),actor=fmt.mr.actor(principal),reason='explicit operator manuscript title or caption edit',merge=False,connection=c)
        row=c.execute('SELECT value FROM kv WHERE key=?',('desk_pdf:'+primary,)).fetchone()
        result={'object':obj,'render':json.loads(row[0]) if row else None,'edit_receipt':receipt}
        c.execute('INSERT INTO kv VALUES(?,?)',(receipt_key,encoded({'input_sha256':fingerprint,'result':result})))
        return copy.deepcopy(result)
