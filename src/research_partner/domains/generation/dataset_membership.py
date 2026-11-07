"""Explicit CSV membership revisions, preserving source bytes and prior refs.

This bounded adapter does not replace the pending large-data/chunked identity
contract. Original batches remain immutable assets; recipes bind exact revisions.
"""
import copy
import csv
import io
from research_partner.storage.store import require,digest,encoded,now

def rows(raw,contract):
    from research_partner.domains.generation.generation import table
    table(raw,contract)
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'),newline='')))

def serialize(values,contract):
    out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=contract['columns']);writer.writeheader();writer.writerows(values)
    return out.getvalue().encode()

def revise(app,project,data,scope):
    from research_partner.domains.generation.generation import table
    payload=data.get('payload',{})
    require(isinstance(payload,dict) and set(payload)=={'base_ref','operation','members','asset_sha256','corrections','reason'},'成员修订需要固定基线、操作、明确范围和原因')
    base=payload['base_ref'];require(isinstance(base,dict) and set(base)=={'id','revision'} and isinstance(base['id'],str) and base['id'] and type(base['revision']) is int and base['revision']>0,'需要准确数据基线')
    operation=payload['operation'];require(operation in {'append','exclude','restore','correct_labels'},'数据修订操作不支持')
    require(isinstance(payload['reason'],str) and 0<len(payload['reason'].strip())<=2000,'数据修订需要明确原因')
    key='dataset_revision:'+project['id']+':'+data['request_id'];fingerprint=digest(payload)
    with app.store.transaction() as c:
        previous=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
        if previous:
            import json
            saved=json.loads(previous[0]);require(saved['input']==fingerprint,'同一数据修订请求内容不同','idempotency_conflict',409)
            return saved['result']
        source=app.store.get(base['id'],base['revision'],c);app.access(source,scope)
        require(source['kind']=='dataset' and source['project_id']==project['id'] and not source['archived'],'数据基线不属于当前项目')
        current=app.store.get(source['id'],connection=c);require(current['revision']==base['revision'],'数据已在另一窗口改变；未覆盖新修订','conflict',409)
        require(source['content'].get('authority_kind') != 'immutable_member_manifest',
                '此分块成员来源暂不支持此修订操作；原快照保持', 'unsupported_dataset_adapter', 422)
        old=source['content'];contract=old['snapshot']['contract'];master_sha=old.get('master_asset_sha256',old['asset_sha256'])
        app.asset(master_sha,scope,project['id']);raw=(app.store.blobs/master_sha).read_bytes();require(digest(raw)==master_sha,'成员主源字节改变','input_integrity',409)
        master=rows(raw,contract);fields=contract['identity_fields'];identity=lambda r:{k:r[k] for k in fields}
        all_ids={encoded(identity(r)) for r in master};excluded={encoded(m):m for m in old.get('excluded_members',[])}
        require(set(excluded)<=all_ids and all(isinstance(m,dict) and set(m)==set(fields) for m in excluded.values()),'已存排除范围与实际主源不一致','identity_mismatch',409)
        if old.get('master_snapshot'):require(table(raw,contract)==old['master_snapshot'],'主源成员快照不符','identity_mismatch',409)
        app.asset(old['asset_sha256'],scope,project['id']);selected_before=(app.store.blobs/old['asset_sha256']).read_bytes()
        require(digest(selected_before)==old['asset_sha256'] and table(selected_before,contract)==old['snapshot'],'实际选中范围与固定快照不同','identity_mismatch',409)
        members=payload['members'];corrections=payload['corrections']
        require(isinstance(members,list) and len(members)<=10000 and isinstance(corrections,list) and len(corrections)<=10000,'本切片成员操作最多10000项；大规模操作未就绪','context_limit',413)
        require(all(isinstance(m,dict) and set(m)==set(fields) and all(isinstance(v,str) and v for v in m.values()) for m in members),'成员身份需来自实际字段和值')
        ids=[encoded(m) for m in members];require(len(ids)==len(set(ids)) and set(ids)<=all_ids,'成员重复或不属于固定主源','identity_mismatch',422)
        batches=copy.deepcopy(old.get('batch_sources',[{'asset_sha256':master_sha,'filename':old['source_filename']}]))
        if operation=='append':
            require(not members and not corrections and payload['asset_sha256'],'追加仅接已上传真实批次')
            asset=app.asset(payload['asset_sha256'],scope,project['id']);extra=(app.store.blobs/asset['sha']).read_bytes();addition=rows(extra,contract)
            require(addition and not (all_ids&{encoded(identity(r)) for r in addition}),'新批次为空或与已有成员重复；不推测合并','identity_mismatch',422)
            master.extend(addition);batches.append({'asset_sha256':asset['sha'],'filename':asset['filename']})
        elif operation in {'exclude','restore'}:
            require(ids and not corrections and payload['asset_sha256'] is None,'排除/恢复需要明确成员集合')
            if operation=='exclude':
                require(not set(ids)&set(excluded),'范围包含已经排除的成员')
                excluded.update({encoded(m):copy.deepcopy(m) for m in members})
            else:
                require(set(ids)<=set(excluded),'只能恢复实际已排除成员')
                for key_id in ids:excluded.pop(key_id)
        else:
            require(corrections and not members and payload['asset_sha256'] is None,'标注更正需要明确更正集合')
            seen=set();by_id={encoded(identity(row)):row for row in master}
            for correction in corrections:
                require(isinstance(correction,dict) and set(correction)=={'identity','field','before','after'},'更正必须含身份、字段、原值及新值')
                ident=correction['identity'];field=correction['field']
                require(isinstance(ident,dict) and set(ident)==set(fields) and all(isinstance(v,str) and v for v in ident.values()),'更正身份无效')
                ident_key=encoded(ident);require(ident_key in by_id and isinstance(field,str) and field in contract['columns'] and field not in fields,'更正不能重写身份或推测未知字段')
                require((ident_key,field) not in seen and isinstance(correction['before'],str) and isinstance(correction['after'],str) and correction['before']!=correction['after'],'更正重复或原/新值无效')
                require(by_id[ident_key][field]==correction['before'],'实际原值与更正基线不同','conflict',409)
                by_id[ident_key][field]=correction['after'];seen.add((ident_key,field))
        master_raw=serialize(master,contract);master_snapshot=table(master_raw,contract)
        active=[r for r in master if encoded(identity(r)) not in excluded];selected=serialize(active,contract);snapshot=table(selected,contract)
        require(len(encoded(master_snapshot).encode())<=4*1024*1024,'成员清单超过本切片边界；不丢弃成员','context_limit',413)
        # Publish only new immutable bytes; never edit original batch blobs.
        m=app.store.add_asset(master_raw,'members-master.csv','text/csv',{'project_id':project['id'],'dataset_membership_master':True},connection=c)
        a=app.store.add_asset(selected,'members-selected.csv','text/csv',{'project_id':project['id'],'dataset_membership_selection':True},connection=c)
        content={**copy.deepcopy(old),'asset_sha256':a['sha'],'snapshot':snapshot,'master_asset_sha256':m['sha'],'master_snapshot':master_snapshot,'batch_sources':batches,
                 'excluded_members':[identity(r) for r in master if encoded(identity(r)) in excluded],
                 'membership_change':{'base_ref':base,'operation':operation,'members':members,'corrections':corrections,'reason':payload['reason'],'at':now()},'authority_kind':'immutable_asset','automatic_recipe_update':False}
        result=app.store.save(source['id'],base['revision'],content=content,merge=False,reason='explicit dataset '+operation,connection=c)
        c.execute('INSERT INTO kv VALUES(?,?)',(key,encoded({'input':fingerprint,'result':result})))
        return result
