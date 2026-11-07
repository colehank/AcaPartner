"""Finite scientific graph proposals; model output is data, never an action API.

All acceptance/repair/merge commits use one SQLite transaction. Accepted scientific
hypotheses stay candidates. The graph catalog is an exact, bounded identity view,
not permission to mutate the objects it describes.
"""
from __future__ import annotations
import copy
import json
import re
import unicodedata
from research_partner.storage.store import Problem, require, digest, encoded, now, uid

FEATURE='graph_proposal_v1'
TYPES={'contains','uses','produces','cites','supports','limits','studies','related','depends_on'}
SEMANTIC={'contains','supports','limits','studies','related','depends_on'}
STATUSES={'candidate','confirmed','rejected','withdrawn','superseded'}
EMPTY={'version':1,'concepts':[],'relations':[],'duplicate_candidates':[]}


def _get(c,key,default=None):
    row=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default


def _put(c,key,value):
    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,encoded(value)))


def enabled(task):return task.get('payload',{}).get('context',{}).get('graph_catalog',{}).get('version')==1

def _text(value,maximum=4000):return isinstance(value,str) and bool(value.strip()) and len(value.encode())<=maximum

def _norm(value):return unicodedata.normalize('NFKC',value).casefold().strip()


def freeze_catalog(app,project_id,materials,extra_ids=None,connection=None):
    s=app.store
    if connection is None:
        with s.connect() as c:return freeze_catalog(app,project_id,materials,extra_ids,c)
    # Own concepts, actual materials, and the project itself form a reproducible
    # useful scope. Unrelated feedback/ledger/private metadata are never read out.
    ids={project_id,*[ref['id'] for ref in materials]}
    if extra_ids is not None:
        require(isinstance(extra_ids,list) and len(extra_ids)<=64 and all(isinstance(i,str) for i in extra_ids),'图谱目录选择无效')
        ids.update(extra_ids)
    else:
        ids.update(row[0] for row in connection.execute("SELECT id FROM objects WHERE project_id=? AND kind='concept' AND archived=0",(project_id,)))
    require(len(ids)<=80,'相关图谱超过80个节点；请明确graph_catalog_ids范围，未静默截断','context_limit',413)
    nodes=[]
    for ident in sorted(ids):
        s.assert_source_access(connection,project_id,ident);obj=s.get(ident,connection=connection)
        require(obj['kind'] not in {'feedback','growth','commission','workshop'},'控制记录不可作为图谱目录材料')
        content=obj['content'];aliases=obj['metadata'].get('aliases',[])
        node={k:copy.deepcopy(obj[k]) for k in ('id','kind','project_id','title','revision')}
        node.update(aliases=[x for x in aliases if isinstance(x,str)],definition=content.get('definition',content.get('description','')) if obj['kind'] in {'concept','project'} else '',
                    domain=content.get('domain',''),source_sha256=digest(obj),writable=(ident==project_id or obj['project_id']==project_id),archived=obj['archived'])
        nodes.append(node)
    relations=[]
    for row in connection.execute('SELECT * FROM relations ORDER BY id'):
        if row['src'] not in ids or row['dst'] not in ids:continue
        r=s.unpack(row)
        relations.append({k:r[k] for k in ('id','src','dst','type','status','source_revision','target_revision')}|{'revision':r['metadata'].get('graph_revision',1),'identity':digest(r)})
    require(len(relations)<=160,'相关关系超过160条；请明确缩小目录','context_limit',413)
    result={'version':1,'nodes':nodes,'relations':relations,'scope':'identity catalog only; evidence must come from frozen materials; no implicit write authority'}
    require(len(encoded(result).encode())<=32768,'图谱目录超过32768字节；请明确缩小范围','context_limit',413)
    return result


def extend_acquired_catalog(app, connection, project_id, context, original_materials):
    """Extend only with newly adopted acquisition identities in the same commit.

    Existing nodes/relations remain frozen, including any now-stale identities.
    A later edit is a conflict, not an excuse to refresh the old catalog silently.
    """
    catalog=context.get('graph_catalog')
    if not isinstance(catalog,dict) or catalog.get('version')!=1:return
    previous=copy.deepcopy(catalog);result=copy.deepcopy(catalog)
    known={node['id'] for node in result['nodes']}
    original={(ref['id'],ref['revision']) for ref in original_materials}
    added=[];s=app.store
    for ref in context['materials']:
        if (ref['id'],ref['revision']) in original or ref['id'] in known:continue
        s.assert_source_access(connection,project_id,ref['id'])
        obj=s.get(ref['id'],ref['revision'],connection)
        require(obj['kind']=='literature' and digest(obj)==ref['sha256'],
                '获取图谱增量必须来自同次采用的准确文献版本','integrity',409)
        content=obj['content']
        node={key:copy.deepcopy(obj[key]) for key in ('id','kind','project_id','title','revision')}
        node.update(aliases=[value for value in obj['metadata'].get('aliases',[]) if isinstance(value,str)],
                    definition='',domain=content.get('domain',''),source_sha256=digest(obj),
                    writable=obj['project_id']==project_id,archived=obj['archived'])
        result['nodes'].append(node);known.add(obj['id']);added.append({'id':obj['id'],'revision':obj['revision'],'sha256':digest(obj)})
    require(len(result['nodes'])<=80 and len(encoded(result).encode())<=32768,
            '获取后的图谱目录超出原有限范围；未截断或重扫其他来源','context_limit',413)
    context['graph_catalog']=result
    context['literature_acquisition']['graph_catalog_derivation']={
        'original_sha256':digest(previous),'derived_sha256':digest(result),'added':added,
        'existing_nodes_and_relations_unchanged':True}


def schema(task):
    if not enabled(task):return ''
    role=task['payload'].get('cycle_role')
    if role in {'delegate','integrator'}:
        return (' Optional graph_proposal:{version:1,concepts:[{local_id,title,aliases:[string],definition,domain:string,source_refs:[{id,revision,block_id?}]}],'
                'relations:[{local_id,src,dst,type,rationale,source_refs:[{id,revision,block_id?}],epistemic_status:"hypothesis"|"source_supported"}],'
                'duplicate_candidates:[{local_id,source_id,target_id,reason,source_refs:[{id,revision,block_id?}]}]}. '
                'Omission means no graph proposal. Empty arrays are valid; never invent nodes just to grow a graph. '
                'At most 8 concepts, 12 relations, 8 duplicate candidates. Every item needs a unique ASCII local_id and nonempty exact source_refs from THIS TASK materials. '
                'Endpoints must be IDs in graph_catalog or concept local_ids in THIS proposal. Relation types contains/supports/limits/studies/related/depends_on only. '
                'Existing same names are suspected duplicates, never automatic merges. Give substantive scientific definitions, relation limits and supported domain grouping. '
                'All accepted model edges remain candidate; independent review is not empirical or user approval. The integrator must emit its own canonical complete proposal, not task-relative fragments.')
    if role in {'reviewer','final_reviewer'}:
        return (' For EACH nonempty graph_proposal in supplied cycle_evidence REQUIRED graph_review:{version:1,proposals:[{task_id,proposal_digest,items:[{id,decision:"accept"|"reject"|"needs_correction",reason}]}]}. '
                'Bind exact graph_proposal_digest supplied beside the candidate; enumerate every proposal local_id exactly once. '
                'Judge concept definitions, each relation evidence/epistemic limit and suspected duplicates individually. Accepting an artifact does not accept unreviewed graph items. '
                'Rejection may coexist with an otherwise useful artifact; unsupported edges stay unaccepted. Never issue graph mutation actions.')
    return ''


def items(proposal):
    return [('concept',x) for x in proposal['concepts']]+[('relation',x) for x in proposal['relations']]+[('duplicate',x) for x in proposal['duplicate_candidates']]


def validate_proposal(proposal,task):
    require(enabled(task),'旧任务没有图谱增量合同；不能隐式升级','invalid_model_output',422)
    require(isinstance(proposal,dict) and set(proposal)==set(EMPTY) and type(proposal['version']) is int and proposal['version']==1,'图谱增量合同字段无效','invalid_model_output',422)
    context=task['payload']['context'];catalog=context['graph_catalog'];nodes={n['id']:n for n in catalog['nodes']}
    allowed={r['id']:r['revision'] for r in context['materials']}
    limits={'concepts':8,'relations':12,'duplicate_candidates':8}
    for key,limit in limits.items():require(isinstance(proposal[key],list) and len(proposal[key])<=limit,'图谱提案数量超出有限范围','invalid_model_output',422)
    local=set()
    for kind,item in items(proposal):
        require(isinstance(item,dict),'图谱条目必须为对象','invalid_model_output',422)
        ident=item.get('local_id');require(isinstance(ident,str) and re.fullmatch(r'[A-Za-z0-9_:.\-]{1,64}',ident) and ident not in local and ident not in nodes,'图谱条目local_id无效或重复','invalid_model_output',422);local.add(ident)
        refs=item.get('source_refs');require(isinstance(refs,list) and 1<=len(refs)<=8,'每项图谱提案必须有冻结科学来源','invalid_model_output',422)
        for ref in refs:
            require(isinstance(ref,dict) and {'id','revision'}<=set(ref)<= {'id','revision','block_id'} and isinstance(ref['id'],str) and type(ref['revision']) is int and allowed.get(ref['id'])==ref['revision'] and ('block_id' not in ref or _text(ref['block_id'],180)),'图谱来源不属于本子任务实际冻结材料','invalid_model_output',422)
        if kind=='concept':
            require(set(item)=={'local_id','title','aliases','definition','domain','source_refs'} and _text(item['title'],300) and _text(item['definition'],4000) and isinstance(item['domain'],str) and len(item['domain'].encode())<=300 and isinstance(item['aliases'],list) and len(item['aliases'])<=8 and all(_text(x,300) for x in item['aliases']),'概念提案字段无效','invalid_model_output',422)
        elif kind=='relation':
            require(set(item)=={'local_id','src','dst','type','rationale','source_refs','epistemic_status'} and isinstance(item['src'],str) and isinstance(item['dst'],str) and item['src']!=item['dst'] and isinstance(item['type'],str) and item['type'] in SEMANTIC and _text(item['rationale']) and isinstance(item['epistemic_status'],str) and item['epistemic_status'] in {'hypothesis','source_supported'},'关系提案字段无效','invalid_model_output',422)
        else:
            require(set(item)=={'local_id','source_id','target_id','reason','source_refs'} and isinstance(item['source_id'],str) and isinstance(item['target_id'],str) and item['source_id']!=item['target_id'] and _text(item['reason']),'疑似重复字段无效','invalid_model_output',422)
    endpoints=set(nodes)|{x['local_id'] for x in proposal['concepts']}
    for kind,item in items(proposal):
        for field in (('src','dst') if kind=='relation' else ('source_id','target_id') if kind=='duplicate' else ()):
            require(item[field] in endpoints,'图谱端点不在冻结目录或本提案概念中','invalid_model_output',422)
        if kind=='relation' and item['src'] in nodes:require(nodes[item['src']]['writable'],'共享目录不授予修改他项目关系的权限','invalid_model_output',422)
    require(len(encoded(proposal).encode())<=24000,'图谱增量正文超过24000字节','invalid_model_output',422)
    return copy.deepcopy(proposal)


def validate_candidate(candidate,task):
    role=task['payload'].get('cycle_role');active=enabled(task)
    if 'graph_proposal' in candidate:
        require(active and role in {'delegate','integrator'},'该角色/旧任务不得输出图谱增量','invalid_model_output',422)
        validate_proposal(candidate['graph_proposal'],task)
    if 'graph_review' in candidate:require(active and role in {'reviewer','final_reviewer'},'该角色不得输出图谱审查','invalid_model_output',422)
    if not active or role not in {'reviewer','final_reviewer'}:return
    expected={}
    for evidence in task['payload']['context'].get('cycle_evidence',[]):
        proposal=evidence.get('content',{}).get('graph_proposal')
        if proposal and items(proposal):expected[evidence['task_id']]=(digest(proposal),{x['local_id'] for _,x in items(proposal)})
    review=candidate.get('graph_review',{'version':1,'proposals':[]})
    require(isinstance(review,dict) and set(review)=={'version','proposals'} and review['version']==1 and isinstance(review['proposals'],list) and len(review['proposals'])==len(expected),'图谱审查缺少逐提案判定','invalid_model_output',422)
    seen=set()
    for part in review['proposals']:
        require(isinstance(part,dict) and set(part)=={'task_id','proposal_digest','items'} and isinstance(part['task_id'],str) and part['task_id'] in expected and part['task_id'] not in seen,'图谱审查指向未供给候选','invalid_model_output',422);seen.add(part['task_id'])
        sha,ids=expected[part['task_id']]
        require(part['proposal_digest']==sha and isinstance(part['items'],list) and len(part['items'])==len(ids),'图谱审查未绑定精确提案','invalid_model_output',422)
        checked=set()
        for decision in part['items']:
            require(isinstance(decision,dict) and set(decision)=={'id','decision','reason'} and isinstance(decision['id'],str) and decision['id'] in ids and decision['id'] not in checked and isinstance(decision['decision'],str) and decision['decision'] in {'accept','reject','needs_correction'} and _text(decision['reason']),'图谱逐项审查缺失或无效','invalid_model_output',422);checked.add(decision['id'])


def _record(s,c,ident):
    record=_get(c,'graph_proposal:'+ident);require(record,'图谱提案不存在','not_found',404);return record


def _save_record(s,c,record,reason,actor='coordinator'):
    record['revision']+=1;record['updated_at']=now();record.setdefault('history',[]).append({'revision':record['revision'],'at':now(),'actor':actor,'reason':reason,'items':copy.deepcopy(record['items'])})
    _put(c,'graph_proposal:'+record['id'],record);s.event(c,'graph.proposal.saved',record['id'],{'revision':record['revision'],'reason':reason},actor)
    return record


def stage(app,c,parent,source,integrator):
    if not enabled(parent):return None
    proposal=copy.deepcopy(source['content'].get('graph_proposal',EMPTY));validate_proposal(proposal,integrator)
    ident='GRAPH-'+digest({'cycle':parent['id'],'artifact':{k:source[k] for k in ('id','revision','sha256')},'proposal':proposal})[:20]
    previous=_get(c,'graph_proposal:'+ident)
    if previous:return previous
    record={'id':ident,'revision':0,'version':1,'project_id':parent['project_id'],'cycle_id':parent['id'],'epoch':parent['result']['cycle']['epoch'],
            'integrator_id':integrator['id'],'artifact_ref':{k:source[k] for k in ('id','revision','sha256')},'proposal_digest':digest(proposal),'proposal':proposal,
            'catalog':copy.deepcopy(parent['payload']['context']['graph_catalog']),'materials':copy.deepcopy(integrator['payload']['context']['materials']),
            'status':'awaiting_final_review','items':[{'id':i['local_id'],'kind':kind,'proposal':copy.deepcopy(i),'decision':'pending','reason':'等待精确最终独立审查'} for kind,i in items(proposal)],
            'duplicates':[],'created_at':now(),'history':[]}
    return _save_record(app.store,c,record,'frozen exact integrated proposal')


def _relation(s,c,ident):
    row=c.execute('SELECT * FROM relations WHERE id=?',(ident,)).fetchone();require(row,'关系不存在','not_found',404)
    value=s.unpack(row);value['revision']=value['metadata'].get('graph_revision',1);value['history']=_get(c,'graph_relation_history:'+ident,[])
    return value


def _history(s,c,relation,before,reason,actor='user'):
    history=_get(c,'graph_relation_history:'+relation['id'],[])
    history.append({'at':now(),'actor':actor,'reason':reason,'before':{k:v for k,v in before.items() if k!='history'} if before else None,'after':{k:v for k,v in relation.items() if k!='history'}})
    _put(c,'graph_relation_history:'+relation['id'],history);s.event(c,'graph.relation.saved',relation['src'],{'id':relation['id'],'revision':relation.get('revision',1),'reason':reason},actor)
    return _relation(s,c,relation['id'])


def _insert_relation(s,c,src,dst,kind,status,metadata,actor='user',target_revision=None,source_revision=None):
    require(src!=dst and kind in TYPES and status in STATUSES,'图谱关系字段无效')
    a,b=s.get(src,connection=c),s.get(dst,connection=c)
    project_id=a['id'] if a['kind']=='project' else a['project_id'];s.assert_source_access(c,project_id,dst);s.assert_reference_access(c,project_id,metadata)
    existing=c.execute('SELECT id FROM relations WHERE src=? AND dst=? AND type=?',(src,dst,kind)).fetchone()
    require(not existing,'已有关系不可覆盖；请读取版本后明确纠正','conflict',409,{'relation_id':existing[0]} if existing else None)
    adopted=b['revision'] if target_revision is None else target_revision
    origin=a['revision'] if source_revision is None else source_revision
    require(type(adopted) is int and adopted>=1 and type(origin) is int and origin>=1,'关系引用必须绑定有效整数版本','version_required',409)
    s.get(dst,adopted,c);s.get(src,origin,c)
    ident=uid('REL');metadata={**metadata,'graph_revision':1}
    c.execute('INSERT INTO relations VALUES(?,?,?,?,?,?,?,?)',(ident,src,dst,kind,status,origin,adopted,encoded(metadata)))
    return _history(s,c,_relation(s,c,ident),None,'create',actor)


def _check_frozen(s,c,record):
    from research_partner.domains.collaboration.cycle import assert_parent
    parent,state=assert_parent(s,c,record['cycle_id'],record['epoch'])
    s.assert_material_access(c,parent['payload'])
    source=record['artifact_ref'];current=s.get(source['id'],connection=c)
    require(current['revision']==source['revision'] and digest(current)==source['sha256'],'最终成果已变；旧图谱审查不能接纳新版本','conflict',409)
    frozen_nodes={node['id']:node for node in record['catalog']['nodes']}
    for ref in record['materials']:
        s.assert_source_access(c,record['project_id'],ref['id']);obj=s.get(ref['id'],connection=c)
        adopted=s.get(ref['id'],ref['revision'],c)
        require(digest(adopted)==ref['sha256'],'采用的历史材料身份不符','integrity',409)
        # A deliberately selected older revision is valid. Detect changes since
        # the catalog freeze, rather than demanding adoption of the latest text.
        expected=frozen_nodes.get(ref['id'])
        own_final=ref['id']==source['id'] and digest(obj)==source['sha256']
        require(own_final or (expected and obj['revision']==expected['revision'] and digest(obj)==expected['source_sha256']),'图谱科学来源在冻结后改变，需重审','conflict',409,{'source_id':ref['id']})
    # Only referenced endpoints are version-fenced; an unrelated node edit must
    # not block independent work. ACL of the complete supplied catalog is checked.
    refs=set()
    for kind,item in items(record['proposal']):
        for key in (('src','dst') if kind=='relation' else ('source_id','target_id') if kind=='duplicate' else ()):refs.add(item[key])
    for node in record['catalog']['nodes']:
        s.assert_source_access(c,record['project_id'],node['id'])
        if node['id'] not in refs:continue
        obj=s.get(node['id'],connection=c)
        require((node['id']==source['id'] and digest(obj)==source['sha256']) or (obj['revision']==node['revision'] and digest(obj)==node['source_sha256']),'图谱端点版本改变；不能沿用旧提案','conflict',409,{'source_id':node['id']})
    return parent,state


def apply_final(app,c,parent,state,reviewer,review_record):
    ident=state.get('graph_proposal_id')
    if not ident:return None
    s=app.store;record=_record(s,c,ident)
    if record['status']=='applied':return record
    _check_frozen(s,c,record)
    require(state.get('final_reviewer')==reviewer['id'] and reviewer['status']=='generated' and reviewer['payload'].get('cycle_role')=='final_reviewer' and reviewer['payload'].get('cycle_parent')==parent['id'],'最终图谱审查身份不符','conflict',409)
    candidate=reviewer['result']['cycle_candidate'];content=candidate['content']
    require(candidate['cycle_contract']['verdict']=='accept' and review_record['source_sha256']==record['artifact_ref']['sha256'],'科研成果未通过精确最终独立审查','conflict',409)
    validate_candidate(content,reviewer)
    parts=content.get('graph_review',{}).get('proposals',[])
    decisions=next((p['items'] for p in parts if p['task_id']==record['integrator_id'] and p['proposal_digest']==record['proposal_digest']),[])
    indexed={d['id']:d for d in decisions};mapping={};catalog={n['id']:n for n in record['catalog']['nodes']}
    for item in record['items']:
        decision=indexed.get(item['id']);require(decision,'缺少精确逐项最终审查','conflict',409)
        item['independent_review']={**decision,'review_task_id':reviewer['id'],'review_identity':review_record['identity']}
        if item.get('human_decision') in {'reject','needs_correction'}:continue
        item.update(decision=decision['decision'],reason=decision['reason'])
        if decision['decision']!='accept' or item['kind']!='concept':continue
        proposal=item['proposal'];object_id='ART-GRAPH-'+digest([ident,item['id']])[:20]
        obj=s.create('concept',proposal['title'],record['project_id'],{'definition':proposal['definition'],'domain':proposal['domain'],'source_refs':proposal['source_refs'],'epistemic_status':'candidate','blocks':[{'id':'definition','kind':'paragraph','text':proposal['definition']}]},
                     {'aliases':proposal['aliases'],'graph_proposal_id':ident,'graph_item_id':item['id'],'review_status':'independently_reviewed_candidate','scientific_approval':False},actor='coordinator',ident=object_id,connection=c)
        mapping[item['id']]=obj['id'];item['applied_id']=obj['id']
        names={_norm(proposal['title']),*[_norm(x) for x in proposal['aliases']]}
        for node in catalog.values():
            if node['kind']=='concept' and names & {_norm(node['title']),*[_norm(x) for x in node['aliases']]}:
                record['duplicates'].append({'id':'name:'+item['id']+':'+node['id'],'item_id':'name:'+item['id']+':'+node['id'],'source_id':obj['id'],'target_id':node['id'],'source_revision':obj['revision'],'target_revision':node['revision'],'reason':'名称或别名相同；定义和证据仍须人工核对，未自动合并','decision':'pending'})
    for item in record['items']:
        if item['decision']!='accept' or item['kind']=='concept':continue
        proposal=item['proposal'];fields=('src','dst') if item['kind']=='relation' else ('source_id','target_id')
        endpoints=[mapping.get(proposal[f],proposal[f]) for f in fields]
        if any(e not in catalog and e not in mapping.values() for e in endpoints):item.update(decision='needs_correction',reason='所依赖概念未被接纳；未创建悬空关系');continue
        if item['kind']=='duplicate':
            a,b=[s.get(e,connection=c) for e in endpoints]
            record['duplicates'].append({'id':item['id'],'item_id':item['id'],'source_id':a['id'],'target_id':b['id'],'source_revision':a['revision'],'target_revision':b['revision'],'reason':proposal['reason'],'decision':'pending'});continue
        a,b=endpoints
        old=c.execute('SELECT id FROM relations WHERE src=? AND dst=? AND type=?',(a,b,proposal['type'])).fetchone()
        if old:
            item.update(decision='needs_correction',reason='已有关系及其人工/拒绝状态完整保留；请显式处理冲突',existing_relation_id=old['id']);continue
        relation=_insert_relation(s,c,a,b,proposal['type'],'candidate',{'source_refs':proposal['source_refs'],'rationale':proposal['rationale'],'epistemic_status':proposal['epistemic_status'],'graph_proposal_id':ident,'graph_item_id':item['id'],'review_identity':review_record['identity'],'scientific_approval':False},'coordinator')
        item['applied_id']=relation['id']
    record.update(status='applied',mapping=mapping,final_review=review_record['identity'],review_task_id=reviewer['id'])
    return _save_record(s,c,record,'atomic independently reviewed candidate graph acceptance')


def _scope(app,record,scope,write=False):
    if write:app.writable(record['project_id'],scope)
    else:require(scope is None or record['project_id'] in scope,'没有此图谱提案权限','forbidden',403);app.get(record['project_id'],scope)


def proposal_view(app,ident,scope=None,connection=None):
    if connection is None:
        with app.store.connect() as c:return proposal_view(app,ident,scope,c)
    record=_record(app.store,connection,ident);_scope(app,record,scope)
    # Catalog carries no secrets, but public view omits full frozen/control data.
    return {k:copy.deepcopy(v) for k,v in record.items() if k not in {'catalog','materials','epoch'}}


def review_view(app,project_id=None,scope=None):
    if project_id:app.writable(project_id,scope)
    proposals=[];relations=[];conflicts=[]
    with app.store.connect() as c:
        for row in c.execute("SELECT value FROM kv WHERE key LIKE 'graph_proposal:%' ORDER BY key"):
            record=json.loads(row[0])
            if project_id and record['project_id']!=project_id:continue
            if scope is not None and record['project_id'] not in scope:continue
            proposals.append(proposal_view(app,record['id'],scope,c))
        for row in c.execute('SELECT id FROM relations ORDER BY id'):
            relation=_relation(app.store,c,row[0]);source=app.store.get(relation['src'],connection=c)
            owner=source['id'] if source['kind']=='project' else source['project_id']
            if project_id and owner!=project_id:continue
            if scope is not None and owner not in scope:continue
            if app._relation_allowed(relation,scope):relations.append(relation)
        for row in c.execute("SELECT value FROM kv WHERE key LIKE 'graph_conflict:%' ORDER BY key"):
            conflict=json.loads(row[0])
            if (not project_id or conflict['project_id']==project_id) and (scope is None or conflict['project_id'] in scope):conflicts.append(conflict)
    duplicates=[{**d,'proposal_id':p['id'],'proposal_revision':p['revision']} for p in proposals for d in p['duplicates']]
    return {'proposals':proposals,'relations':relations,'duplicates':duplicates,'conflicts':conflicts}


def relation_update(app,data,scope=None,connection=None):
    s=app.store
    if connection is None:
        with s.transaction() as c:return relation_update(app,data,scope,c)
    c=connection;old=_relation(s,c,data['id']);app.writable(old['src'],scope)
    require(type(data.get('expected_revision')) is int and data['expected_revision']==old['revision'],'关系已改变，请重读已存历史','conflict',409,{'current':old})
    require(_text(data.get('reason')),'纠正关系需要理由')
    src=data.get('src',old['src']);dst=data.get('dst',old['dst']);kind=data.get('type',old['type']);status=data.get('status',old['status'])
    app.writable(src,scope);app.get(dst,scope);require(status in STATUSES,'关系状态无效')
    require('target_revision' in data or dst==old['dst'],'改变目标对象需要明确选择采用版本','version_required',409)
    adopted=data.get('target_revision',old['target_revision'])
    require(type(adopted) is int and adopted>=1,'引用版本必须为有效整数','version_required',409);s.get(dst,adopted,c)
    metadata=copy.deepcopy(old['metadata']);metadata['graph_revision']=old['revision']+1;metadata['human_decision']={'reason':data['reason'],'at':now(),'status':status}
    metadata['adopted_revision']=adopted
    if 'source_refs' in data:
        _validate_refs(s,c,s.get(src,connection=c),data['source_refs']);metadata['source_refs']=copy.deepcopy(data['source_refs'])
    if (src,dst,kind)!=(old['src'],old['dst'],old['type']):
        require(old['status']!='superseded','已经替换的旧关系不能再次改写','conflict',409)
        replacement=_insert_relation(s,c,src,dst,kind,status,{**metadata,'graph_revision':1,'replaces_relation_id':old['id']},target_revision=adopted,source_revision=old['source_revision'] if src==old['src'] else None)
        superseded={**old['metadata'],'graph_revision':old['revision']+1,'adopted_revision':old['target_revision'],'superseded_by':replacement['id'],'human_decision':{'reason':data['reason'],'at':now(),'status':'superseded'}}
        c.execute('UPDATE relations SET status=?,metadata=? WHERE id=?',('superseded',encoded(superseded),old['id']))
        _history(s,c,_relation(s,c,old['id']),old,data['reason']);return replacement
    a=s.get(src,connection=c);project=a['id'] if a['kind']=='project' else a['project_id'];s.assert_source_access(c,project,dst);s.assert_reference_access(c,project,metadata)
    c.execute('UPDATE relations SET status=?,metadata=?,target_revision=? WHERE id=?',(status,encoded(metadata),adopted,old['id']))
    return _history(s,c,_relation(s,c,old['id']),old,data['reason'])


def _validate_refs(s,c,source,refs):
    require(isinstance(refs,list) and len(refs)<=16,'来源列表无效')
    project=source['id'] if source['kind']=='project' else source['project_id']
    for ref in refs:
        require(isinstance(ref,dict) and {'id','revision'}<=set(ref)<= {'id','revision','block_id'} and isinstance(ref['id'],str) and type(ref['revision']) is int,'来源必须绑定明确版本')
        s.assert_source_access(c,project,ref['id']);obj=s.get(ref['id'],ref['revision'],c)
        if ref.get('block_id'):require(ref['block_id'] in {b.get('id') for b in obj['content'].get('blocks',[])},'来源段落不存在')


def _merge_plan(app,data,scope=None,connection=None):
    if connection is None:
        with app.store.connect() as c:return _merge_plan(app,data,scope,c)
    s=app.store;a=s.get(data['source_id'],connection=connection);b=s.get(data['target_id'],connection=connection)
    app.writable(a['id'],scope);app.writable(b['id'],scope)
    require(a['id']!=b['id'] and a['kind']==b['kind'] and a['project_id']==b['project_id'] and a['kind'] not in {'project','question','feedback','growth','commission'},'只能显式合并同项目同类型科学对象')
    require(not a['archived'] and not b['archived'],'已归档对象不能再次合并','conflict',409)
    relations=[_relation(s,connection,r[0]) for r in connection.execute('SELECT id FROM relations WHERE src=? OR dst=? ORDER BY id',(a['id'],a['id']))]
    conflicts=[]
    for r in relations:
        src=b['id'] if r['src']==a['id'] else r['src'];dst=b['id'] if r['dst']==a['id'] else r['dst']
        old=connection.execute('SELECT id FROM relations WHERE src=? AND dst=? AND type=?',(src,dst,r['type'])).fetchone()
        if old and old[0]!=r['id']:conflicts.append({'source_relation_id':r['id'],'target_relation_id':old[0],'handling':'retain both old relations and source evidence; attach conflict provenance without overriding target status'})
    from research_partner.domains.collaboration.resolver import evidence_projection
    return {'source':{**evidence_projection(a),'aliases':a['metadata'].get('aliases',[]),'position':a['metadata'].get('position')},'target':{**evidence_projection(b),'aliases':b['metadata'].get('aliases',[]),'position':b['metadata'].get('position')},'relations':relations,'conflicts':conflicts,'history':[],'meaning':'source stays archived and readable at its old ID; all historical source references remain exact, never silently rewritten'}


def _public_merge_record(app,record,scope):
    result=copy.deepcopy(record);result.pop('external_references_retained',None)
    visible=[]
    for conflict in result.get('relation_conflicts',[]):
        ids=[conflict.get('source_relation_id'),conflict.get('target_relation_id')]
        with app.store.connect() as c:
            if all(ident and app._relation_allowed(_relation(app.store,c,ident),scope) for ident in ids):visible.append(conflict)
    if 'relation_conflicts' in result:result['relation_conflicts']=visible
    return result


def _public_merge(app,plan,scope):
    result=copy.deepcopy(plan)
    result['relations']=[relation for relation in plan['relations'] if app._relation_allowed(relation,scope)]
    visible_ids={r['id'] for r in result['relations']}
    if 'conflicts' in result:
        allowed=[]
        with app.store.connect() as c:
            for conflict in result['conflicts']:
                if conflict['source_relation_id'] in visible_ids and app._relation_allowed(_relation(app.store,c,conflict['target_relation_id']),scope):allowed.append(conflict)
        result['conflicts']=allowed
    result['history']=[_public_merge_record(app,record,scope) for record in plan.get('history',[])]
    return result


def merge_preview(app,data,scope=None,connection=None):
    return _public_merge(app,_merge_plan(app,data,scope,connection),scope)


def merge(app,data,scope=None,connection=None):
    s=app.store
    if connection is None:
        with s.transaction() as c:return merge(app,data,scope,c)
    c=connection;preview=_merge_plan(app,data,scope,c);a=s.get(data['source_id'],connection=c);b=s.get(data['target_id'],connection=c)
    require(type(data.get('source_revision')) is int and type(data.get('target_revision')) is int and data['source_revision']==a['revision'] and data['target_revision']==b['revision'],'合并需要两端已读最新版本；未修改任何对象','conflict',409,{'source_revision':a['revision'],'target_revision':b['revision']})
    require(_text(data.get('reason')),'合并需要说明定义和来源为何可复用')
    external=[]
    for edge in preview['relations']:
        origin=s.get(edge['src'],connection=c);owner=origin['id'] if origin['kind']=='project' else origin['project_id']
        if owner!=a['project_id']:external.append(edge['id'])
    record={'external_references_retained':external,'id':uid('MERGE'),'source_id':a['id'],'target_id':b['id'],'source_revision':a['revision'],'target_revision':b['revision'],'source_sha256':digest(a),'target_sha256':digest(b),'reason':data['reason'],'at':now(),'relation_conflicts':preview['conflicts'],'original_references_retained':True}
    public_record={k:copy.deepcopy(v) for k,v in record.items() if k not in {'external_references_retained','relation_conflicts'}}
    aliases=list(dict.fromkeys(b['metadata'].get('aliases',[])+[a['title'],a['id']]+a['metadata'].get('aliases',[])))
    target=s.save(b['id'],b['revision'],metadata={**b['metadata'],'aliases':aliases,'merge_history':b['metadata'].get('merge_history',[])+[public_record]},merge=False,reason='explicit graph merge',connection=c)
    source=s.save(a['id'],a['revision'],archived=True,metadata={**a['metadata'],'redirect_to':b['id'],'merge_history':a['metadata'].get('merge_history',[])+[public_record]},merge=False,reason='explicit graph merge redirect',connection=c)
    for old in preview['relations']:
        origin=s.get(old['src'],connection=c);owner=origin['id'] if origin['kind']=='project' else origin['project_id']
        if owner!=a['project_id']:
            continue
        src=b['id'] if old['src']==a['id'] else old['src'];dst=b['id'] if old['dst']==a['id'] else old['dst']
        if src==dst:continue
        original={k:old[k] for k in ('id','src','dst','type','status','source_revision','target_revision','metadata')}
        existing=c.execute('SELECT id FROM relations WHERE src=? AND dst=? AND type=?',(src,dst,old['type'])).fetchone()
        if existing:
            before=_relation(s,c,existing[0]);metadata={**before['metadata'],'graph_revision':before['revision']+1,'merge_conflicts':before['metadata'].get('merge_conflicts',[])+[{'merge_id':record['id'],'original_relation':original}]}
            c.execute('UPDATE relations SET metadata=? WHERE id=?',(encoded(metadata),before['id']));_history(s,c,_relation(s,c,before['id']),before,'explicit merge; retain status and conflicting evidence')
        else:
            _insert_relation(s,c,src,dst,old['type'],old['status'],{**old['metadata'],'graph_revision':1,'merged_from_relation':old['id'],'original_reference':original,'merge_id':record['id']},target_revision=old['target_revision'] if dst==old['dst'] else target['revision'])
    _put(c,'graph_merge:'+record['id'],record);s.event(c,'graph.merged',a['id'],record)
    return _public_merge(app,{'source':source,'target':target,'relations':[_relation(s,c,r[0]) for r in c.execute('SELECT id FROM relations WHERE src=? OR dst=?',(b['id'],b['id']))],'history':[record]},scope)


def _dispatch(app,action,data,scope=None):
    s=app.store
    if action=='graph.review':return review_view(app,data.get('project_id'),scope)
    if action=='graph.proposal_view':return proposal_view(app,data['id'],scope)
    if action=='graph.merge_preview':return merge_preview(app,data,scope)
    # Every new persistent graph operation raises the monotone feature floor in
    # its commit, even if no new research cycle was needed.
    with s.transaction() as c:
        from research_partner.packaging.compatibility import require_features
        require_features(c,[FEATURE])
        if action=='graph.merge':return merge(app,data,scope,c)
        if action=='graph.relation_update':return relation_update(app,data,scope,c)
        if action=='graph.relate':
            src=app.writable(data['src'],scope);app.get(data['dst'],scope)
            metadata=copy.deepcopy(data.get('metadata') or {})
            require(isinstance(metadata,dict),'关系metadata无效');_validate_refs(s,c,src,metadata.get('source_refs',[]))
            return _insert_relation(s,c,data['src'],data['dst'],data.get('type','related'),data.get('status','candidate'),metadata,target_revision=data.get('target_revision'))
        require(action in {'graph.proposal_review','graph.duplicate_resolve'},'未知图谱操作')
        ident=data.get('id',data.get('proposal_id'));record=_record(s,c,ident);_scope(app,record,scope,True)
        require(type(data.get('expected_revision')) is int and data['expected_revision']==record['revision'],'提案已有新处理，请重读','conflict',409)
        require(_text(data.get('reason')),'图谱处理需要说明理由')
        if action=='graph.proposal_review':
            item=next((i for i in record['items'] if i['id']==data.get('item_id')),None);require(item,'提案条目不存在','not_found',404)
            decision=data.get('decision');require(decision in {'accept','reject','needs_correction'},'未知处理决定')
            if decision=='accept':
                require(not item.get('applied_id') and item['decision'] not in {'reject','needs_correction'} and not item.get('independent_review'),'人工接受不能代替或推翻精确最终独立审查；请形成新修订','conflict',409)
                item.update(human_decision='accept',reason=data['reason'])
            else:
                item.update(human_decision=decision,decision=decision,reason=data['reason'])
                if item.get('applied_id') and item['kind']=='relation':
                    edge=_relation(s,c,item['applied_id']);relation_update(app,{'id':edge['id'],'expected_revision':edge['revision'],'status':'rejected' if decision=='reject' else 'withdrawn','reason':data['reason']},scope,c)
                if item.get('applied_id') and item['kind']=='concept':
                    obj=s.get(item['applied_id'],connection=c);s.save(obj['id'],obj['revision'],metadata={**obj['metadata'],'graph_decision':decision,'graph_decision_reason':data['reason']},merge=False,reason='graph proposal decision',connection=c)
                    for row in c.execute('SELECT id FROM relations WHERE src=? OR dst=?',(obj['id'],obj['id'])).fetchall():
                        edge=_relation(s,c,row['id'])
                        if edge['metadata'].get('graph_proposal_id')==ident and not edge['metadata'].get('human_decision'):
                            relation_update(app,{'id':edge['id'],'expected_revision':edge['revision'],'status':'withdrawn','reason':'Dependent proposed concept '+decision+': '+data['reason']},scope,c)
            _save_record(s,c,record,'human '+decision+': '+data['reason'],'user')
        else:
            item=next((i for i in record['duplicates'] if i['item_id']==data.get('item_id')),None);require(item and item['decision']=='pending','疑似重复不存在或已处理','conflict',409)
            decision=data.get('decision');require(decision in {'keep','reuse','reject'},'未知重复处理')
            if decision=='reuse':
                require(data.get('source_id')==item['source_id'] and data.get('target_id')==item['target_id'],'复用端点与疑似重复不符','conflict',409)
                merge(app,data,scope,c)
            item.update(decision=decision,resolution_reason=data['reason'],resolved_at=now());_save_record(s,c,record,'duplicate '+decision,'user')
        return proposal_view(app,ident,scope,c)


def dispatch(app,action,data,scope=None):
    try:return _dispatch(app,action,data,scope)
    except Problem as error:
        # The failed mutation transaction has rolled back. Preserve the user's
        # exact attempted revision and current identity separately for recovery;
        # recording a conflict must never commit half of the attempted edit.
        if error.code!='conflict' or action not in {'graph.relate','graph.relation_update','graph.merge','graph.proposal_review','graph.duplicate_resolve'}:raise
        s=app.store
        with s.transaction() as c:
            if action in {'graph.proposal_review','graph.duplicate_resolve'}:
                record=_record(s,c,data.get('id',data.get('proposal_id')));_scope(app,record,scope,True);project_id=record['project_id'];current={'id':record['id'],'revision':record['revision'],'items':record['items']}
            elif action=='graph.relation_update':
                current=_relation(s,c,data['id']);obj=app.writable(current['src'],scope);project_id=obj['id'] if obj['kind']=='project' else obj['project_id']
            else:
                obj=app.writable(data.get('src',data.get('source_id')),scope);project_id=obj['id'] if obj['kind']=='project' else obj['project_id'];current={'source_id':obj['id'],'source_revision':obj['revision']}
                target=data.get('dst',data.get('target_id'))
                if target:
                    dest=app.get(target,scope);current.update(target_id=dest['id'],target_revision=dest['revision'])
            from research_partner.packaging.compatibility import require_features
            require_features(c,[FEATURE])
            conflict={'id':uid('GRAPH-CONFLICT'),'project_id':project_id,'action':action,'candidate':copy.deepcopy(data),'current':current,'reason':str(error),'created_at':now()}
            _put(c,'graph_conflict:'+conflict['id'],conflict);s.event(c,'graph.conflict',conflict['id'],{'project_id':project_id,'action':action},'user')
        error.details={**error.details,'conflict_id':conflict['id']}
        raise
