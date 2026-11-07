"""Read-only accounting over task-bound native receipts; no provider/file access."""
import copy
import json
import math
import re
from research_partner.storage.store import require
from research_partner.providers.registry import _merge_native_usage


def accounting(store, task, connection=None):
    if connection is None:
        with store.connect() as c:
            return accounting(store, task, c)
    def setting(key):
        row=connection.execute('SELECT value FROM kv WHERE key=?',(key+task['id'],)).fetchone()
        return json.loads(row[0]) if row else None
    anchor=setting('native_usage_anchor:');intent=setting('native_launch_intent:')
    records=[]
    if anchor:
        require(anchor.get('task_id')==task['id'],'原生用量锚点属于其他任务','native_accounting_integrity',409)
        records.append(('durable_anchor',anchor))
    for name,record in [('successful_result',task['result'].get('provider')),
                        ('failed_checkpoint',task['result'].get('details',{}).get('provider_checkpoint'))]:
        if isinstance(record,dict) and isinstance(record.get('usage'),dict):records.append((name,record))
    row=connection.execute("SELECT data FROM steps WHERE task_id=? AND step_key='model'",(task['id'],)).fetchone()
    model=json.loads(row[0]) if row else {}
    if isinstance(model.get('provider'),dict) and isinstance(model['provider'].get('usage'),dict):records.append(('model_checkpoint',model['provider']))
    if not records:return {'status':'unknown','reserved_requests':None,'actual_bill_usd':None,'sources':[]}
    session=None;contract=None;chosen=None;origins=[]
    for name,record in records:
        usage=record.get('usage');sid=record.get('session_id')
        require(isinstance(usage,dict),'原生用量锚点缺少账本','native_accounting_integrity',409)
        sha=usage.get('contract_sha256')
        require(isinstance(sid,str) and sid and isinstance(sha,str) and re.fullmatch(r'[a-f0-9]{64}',sha),
                '原生用量缺少可核验会话/合同身份','native_accounting_integrity',409)
        require((session is None or session==sid) and (contract is None or contract==sha),
                '原生用量会话或合同互相矛盾','native_accounting_integrity',409)
        require(not intent or intent.get('contract_sha256')==sha,'原生用量与数据库分派合同不一致','native_accounting_integrity',409)
        reserved=usage.get('reserved_usd',0)
        require(type(reserved) in {int,float} and math.isfinite(reserved) and reserved>=0,
                '原生预留费用无效','native_accounting_integrity',409)
        calls=usage.get('calls');require(isinstance(calls,list),'原生用量请求列表无效','native_accounting_integrity',409)
        ids=[]
        for call in calls:
            require(isinstance(call,dict) and isinstance(call.get('id'),str) and call['id'] and call.get('session_id')==sid,
                    '原生用量请求缺少唯一ID或会话绑定','native_accounting_integrity',409)
            ids.append(call['id'])
        require(len(ids)==len(set(ids)),'同一原生账本重复请求ID','native_accounting_integrity',409)
        chosen=copy.deepcopy(usage) if chosen is None else _merge_native_usage(chosen,usage)
        session=sid;contract=sha;origins.append(name)
    return {'status':'verified','reserved_requests':len(chosen['calls']),'session_id':session,
            'contract_sha256':contract,'actual_bill_usd':None,'sources':origins,'usage':chosen}


def public_accounting(value):
    return {k:v for k,v in value.items() if k!='usage'}
