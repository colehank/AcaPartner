"""Local, explainable commission resolution. No model calls or persistent preview state."""
from __future__ import annotations
import copy
import re
import unicodedata
from .store import Problem, digest, encoded, require
from .commission import COMMON, PROSE

VERSION = 1
MAX_MATERIALS = 8
MAX_BYTES = 45000
MAX_CANDIDATES = 32
EVIDENCE_KINDS = {'report','note','paper','figure','diagram','poster','slides','workshop','concept','literature'}
# Scientific content only; execution context and arbitrary metadata are not evidence.
LITERATURE_KEYS = {'authors','author_details','author_name_source','author_name_format','year','doi','url','abstract','reading_scope','read_scope','full_text','missing_fields','import_source','source_asset','source_url','metadata_conflicts','citation_key','entry_type','volume','number','issue','publisher','publication_status','journal','venue','publication_type','bibliography'}
CONTENT_KEYS = COMMON | PROSE | LITERATURE_KEYS | {'definition','domain','epistemic_status','caption','description','methods','selection_history','method_history','nodes','edges','groups','pages','width','height','units','resources','attachments','spec','input_assets','script_asset','overlays','source','limitations','outputs','validation','provenance','acceptance'}

def evidence_projection(obj):
    """Exact scientific fields of one revision; full identity remains separately pinned."""
    # Runtime-private containers live at the object metadata / content context
    # boundary. Do not delete generic words recursively: methods.history may
    # describe post-hoc selection and is part of the scientific evidence.
    from .evidence_neutral import project
    projected,excluded=project(obj.get('content',{}),kind=obj.get('kind'))
    content={k:v for k,v in projected.items() if k in CONTENT_KEYS}
    return {k:copy.deepcopy(obj.get(k)) for k in ('id','kind','project_id','title','revision')} | {'content':content, 'source_sha256':digest(obj)} | ({'excluded':excluded} if excluded['typed_blocks'] or excluded['typed_fields'] else {})

def _norm(value):return unicodedata.normalize('NFKC',str(value)).casefold().strip()
def _terms(value):
    text=_norm(value);terms=set(re.findall(r'[a-z0-9][a-z0-9_-]{1,}',text))
    for part in re.findall(r'[\u3400-\u9fff]+',text):
        for n in (2,3):terms.update(part[i:i+n] for i in range(len(part)-n+1))
    return terms

def _aliases(obj):
    value=obj.get('metadata',{}).get('aliases',[])
    return [x for x in value if isinstance(x,str)] if isinstance(value,list) else []
def _names(obj):
    title=obj['title'];base=re.sub(r'\s*[（(][^()（）]{1,60}[)）]\s*$','',title).strip()
    # A source-copy/version qualifier may be omitted in ordinary speech. If
    # two titles share this base, the normal duplicate-name choice still gates.
    return list(dict.fromkeys(x for x in [title,base,*_aliases(obj)] if isinstance(x,str) and len(x.strip())>=2))
def _hits(request,obj):return [name for name in _names(obj) if _norm(name) in _norm(request)]
def _plain(value):
    if isinstance(value,dict):return ' '.join(_plain(v) for v in value.values())
    if isinstance(value,list):return ' '.join(_plain(v) for v in value)
    return str(value) if isinstance(value,(str,int,float)) else ''
def _scientific_text(obj):
    c=evidence_projection(obj)['content'];return ' '.join([obj['title'],*_aliases(obj),str(obj.get('metadata',{}).get('category','')),_plain(c)])
def _score(request,obj):
    overlap=sorted(_terms(request)&_terms(_scientific_text(obj)))
    return len(overlap),overlap[:12]

def _get(app,ident,scope,revision=None,connection=None):
    current=app.access(app.store.get(ident,connection=connection),scope)
    return (app.store.get(ident,revision,connection) if revision is not None else current),current

def _writable_project(app,ident,scope,connection=None):
    obj,_=_get(app,ident,scope,connection=connection)
    require(obj['kind']=='project' and not obj['archived'],'请选择未归档研究项目')
    require(scope is None or obj['id'] in scope,'共享对象不授予对方项目写入或约定读取权','forbidden',403)
    return obj

def _all(app,connection=None):
    if connection is None:return app.store.objects()
    return [app.store.unpack(row) for row in connection.execute('SELECT * FROM objects ORDER BY id')]

def _ref(obj):return {'id':obj['id'],'revision':obj['revision'],'sha256':digest(obj)}
def _key(ref):return (ref['id'],ref['revision'])
def _input_ref(value):
    if isinstance(value,str):return {'id':value}
    require(isinstance(value,dict) and isinstance(value.get('id'),str),'材料应为对象 ID 或 {id, revision}')
    require(value.get('revision') is None or type(value['revision']) is int and value['revision']>0,'材料修订必须为正整数')
    return value

def material(app,value,project_id,scope=None,connection=None):
    ref=_input_ref(value);obj,current=_get(app,ref['id'],scope,ref.get('revision'),connection)
    require(current['project_id']==project_id or project_id in current['metadata'].get('shared_with',[]),'材料未授权给此项目','forbidden',403)
    require(obj['kind'] in EVIDENCE_KINDS,'此对象类型不能自动作为科学材料')
    require(not current['archived'],'材料已归档，请先明确恢复或另选来源')
    require(not ref.get('sha256') or ref['sha256']==digest(obj),'材料冻结身份变化','conflict',409)
    return obj,current

def _candidate(obj,current,reason,required=False):
    return {**_ref(obj),'title':obj['title'],'kind':obj['kind'],'reason':reason,'bytes':len(encoded(evidence_projection(obj)).encode()),'current_revision':current['revision'],'current_sha256':digest(current),'required':required,'selected':False}

def _adopted_refs(obj):
    content=obj['content'];refs=list(content.get('components',[]))+list(content.get('citations',[]))
    for item in list(content.get('nodes',[]))+list(content.get('edges',[])):
        if isinstance(item,dict) and item.get('source_ref'):refs.append(item['source_ref'])
    for page in content.get('pages',[]):
        if not isinstance(page,dict):continue
        for item in page.get('objects',[]):
            if isinstance(item,dict) and item.get('component_id') and item.get('component_revision'):
                refs.append({'id':item['component_id'],'revision':item['component_revision']})
    return [r for r in refs if isinstance(r,dict) and r.get('id') and r.get('revision')]

def resolve(app,data,scope=None,connection=None):
    request=data.get('request',data.get('prompt',''))
    from .acquisition import plan as acquisition_plan
    literature_plan=acquisition_plan(data)
    require(isinstance(request,str) and request.strip(),'请描述研究目的')
    require(len(request.encode())<=12000,'研究目的过长，请将具体材料登记为成果后引用')
    all_objects=_all(app,connection);projects=[]
    for obj in all_objects:
        if obj['kind']!='project' or obj['archived']:continue
        try:projects.append(_writable_project(app,obj['id'],scope,connection))
        except Problem:pass
    projects.sort(key=lambda x:x['id'])
    explicit_ids=re.findall(r'\b(?:PRJ|ART|OBJ|CONCEPT|LIT|FIG|NOTE|PAPER)-[a-fA-F0-9]{8,}\b',request)
    explicit_objects=[];explicit_projects=[]
    for ident in dict.fromkeys(explicit_ids):
        obj,_=_get(app,ident,scope,connection=connection)
        if obj['kind']=='project':explicit_projects.append(_writable_project(app,ident,scope,connection))
        else:explicit_objects.append(obj)
    named_projects=[p for p in all_objects if p['kind']=='project' and _hits(request,p)]
    # An explicitly named inaccessible project must not be silently replaced by
    # the currently open project. The error never returns its content/settings.
    for p in named_projects:_writable_project(app,p['id'],scope,connection)
    strong=explicit_projects or [p for p in projects if _hits(request,p)]
    named_objects=[]
    for obj in all_objects:
        if obj['kind'] not in EVIDENCE_KINDS or obj['archived'] or not _hits(request,obj):continue
        try:app.access(obj,scope);named_objects.append(obj)
        except Problem:pass
    if not strong and not data.get('project_id') and (explicit_objects or named_objects):
        # A named source locates its own project only where this client can write;
        # sharing does not expose parent project conventions.
        owners={o['project_id'] for o in explicit_objects or named_objects};strong=[p for p in projects if p['id'] in owners]
    project_candidates=[];project=None;ambiguities=[];gaps=[]
    for p in projects:
        score,terms=_score(request,{**p,'content':{'blocks':[{'text':p['content'].get('description','')}]}})
        reason='研究目的明确提及项目 ID / 名称 / 别名' if p in strong else '当前项目上下文' if p['id']==data.get('project_id') else ('本地相关词：'+ '、'.join(terms) if score else '可写项目，尚无足够匹配')
        project_candidates.append({**_ref(p),'title':p['title'],'reason':reason,'score':score})
    selected=data.get('selected_project_id')
    if selected:
        project=_writable_project(app,selected,scope,connection)
        require(not strong or selected in {p['id'] for p in strong},'目的明确指向另一项目；请修改目的或选择匹配项目','resolution_required',409)
    elif len(strong)==1:project=strong[0]
    elif len(strong)>1:ambiguities.append({'kind':'project','label':'目的匹配多个项目，请明确所属项目','candidates':[p['id'] for p in strong]})
    elif data.get('project_id'):project=_writable_project(app,data['project_id'],scope,connection)
    else:
        ranked=sorted(project_candidates,key=lambda p:(-p['score'],p['id']))
        if len(ranked)==1:project=_writable_project(app,ranked[0]['id'],scope,connection)
        elif ranked and ranked[0]['score']>=2 and (len(ranked)==1 or ranked[0]['score']>=ranked[1]['score']*2+2):project=_writable_project(app,ranked[0]['id'],scope,connection)
        else:ambiguities.append({'kind':'project','label':'请从可写项目中选择所属项目','candidates':[p['id'] for p in ranked]})
    result={'status':'needs_selection' if ambiguities else 'ready','project':({**_ref(project),'title':project['title']} if project else None),'project_candidates':project_candidates,'materials':[],'ambiguities':ambiguities,'excluded':[],'gaps':gaps,'limits':{'max_materials':MAX_MATERIALS,'max_bytes':MAX_BYTES},'pin':None,'literature_plan':literature_plan}
    if not project:
        if not projects:gaps.append('没有可写项目；先创建项目或取得项目授权。')
        return result
    available=[]
    for obj in all_objects:
        if obj['kind'] not in EVIDENCE_KINDS or obj['archived']:continue
        try:
            app.access(obj,scope)
            if obj['project_id']==project['id'] or project['id'] in obj['metadata'].get('shared_with',[]):available.append(obj)
        except Problem:pass
    candidates={};ambiguous_ids=set()
    if any(o['id'] not in {x['id'] for x in available} for o in named_objects):
        ambiguities.append({'kind':'permission','label':'目的中明确提到的部分材料尚未授权给此项目；请先共享或调整目的','candidates':[]})
    # Exact material names can be ambiguous; do not silently select the first.
    name_groups={}
    for obj in available:
        for name in _hits(request,obj):name_groups.setdefault(_norm(name),[]).append(obj['id'])
    for name,ids in name_groups.items():
        if len(set(ids))>1:
            ambiguous_ids.update(ids);ambiguities.append({'kind':'material','label':'同名 / 同别名材料：'+name,'candidates':sorted(set(ids))})
    for obj in available:
        score,terms=_score(request,obj);hits=_hits(request,obj);explicit=obj['id'] in {o['id'] for o in explicit_objects}
        if explicit or hits or score>=2:
            reason='目的明确提及材料 ID' if explicit else '目的匹配材料名称 / 别名：'+'、'.join(hits) if hits else '本地科学内容相关词：'+'、'.join(terms)
            candidates[_key(_ref(obj))]=_candidate(obj,obj,reason,explicit or bool(hits)) | {'score':10000 if explicit else 1000 if hits else score}
    require(isinstance(data.get('additional_materials',[]),list),'补充来源需要列表')
    extra=list(data.get('additional_materials',[]))
    if data.get('object_id'):extra.append({'id':data['object_id']})
    for obj in explicit_objects:extra.append({'id':obj['id']})
    for value in extra:
        obj,current=material(app,value,project['id'],scope,connection)
        candidates[_key(_ref(obj))]=_candidate(obj,current,'明确补充 / 目标材料',True)|{'score':20000}
    # Expand only explicitly adopted components/citations, one level and pinned
    # to their declared revisions; never walk the whole project or history.
    for candidate in list(candidates.values()):
        if not candidate['required']:continue
        parent,_=material(app,candidate,project['id'],scope,connection)
        for adopted in _adopted_refs(parent):
            try:
                obj,current=material(app,adopted,project['id'],scope,connection)
                newer=candidates.get(_key(_ref(current)))
                if newer and not newer['required'] and obj['revision']!=current['revision']:candidates.pop(_key(_ref(current)))
                candidates.setdefault(_key(_ref(obj)),_candidate(obj,current,f"由 {parent['id']} r{parent['revision']} 采用的精确修订")|{'score':500})
            except Problem:gaps.append(f"{parent['id']} 的一项采用来源当前不可读或不存在；未纳入。")
    ranked=sorted(candidates.values(),key=lambda x:(-x['score'],x['id'],x['revision']))
    chosen=data.get('selected_materials')
    if chosen is not None:
        require(isinstance(chosen,list),'实际采用材料须为列表')
        require(all(isinstance(x,dict) and type(x.get('revision')) is int and x['revision']>0 for x in chosen),'选择材料必须保留明确修订')
        selected_keys={_key(_input_ref(x)) for x in chosen}
        require(selected_keys<=set(candidates),'选择不在本次候选中，请补充来源后重新预览','resolution_required',409)
        ambiguities[:]=[a for a in ambiguities if a['kind']!='material' or len({x[0] for x in selected_keys}&set(a['candidates']))!=1]
    else:selected_keys=None
    total=0;selected_count=0;visible=[];has_named=any(c['required'] for c in ranked)
    for candidate in ranked:
        include=(_key(candidate) in selected_keys) if selected_keys is not None else candidate['id'] not in ambiguous_ids and (not has_named or candidate['required'] or candidate['score']==500)
        fits=selected_count<MAX_MATERIALS and total+candidate['bytes']<=MAX_BYTES
        if include and not fits:
            result['excluded'].append({'id':candidate['id'],'revision':candidate['revision'],'reason':'达到材料数量或完整证据字节上限，未截断正文'})
            if selected_keys is not None or candidate['required']:
                ambiguities.append({'kind':'limit','label':'明确材料超出额度，请修订选择或先形成来源明确的较小成果','candidates':[candidate['id']]})
        candidate['selected']=include and fits
        if not include:result['excluded'].append({'id':candidate['id'],'revision':candidate['revision'],'reason':'用户未采用此候选' if selected_keys is not None else '存在名称歧义，等待明确选择' if candidate['id'] in ambiguous_ids else '目的已明确来源，此项仅为相关候选，未自动采用'})
        if candidate['selected']:total+=candidate['bytes'];selected_count+=1
        if len(visible)<MAX_CANDIDATES:visible.append(candidate)
        elif candidate['selected']:
            candidate['selected']=False;total-=candidate['bytes'];selected_count-=1
        else:result['excluded'].append({'id':candidate['id'],'revision':candidate['revision'],'reason':'候选展示上限；可用明确 ID 补充'})
    if not selected_count:gaps.append('尚无采用材料；可明确补充来源。不会据此声称已读取或获得科学证据。')
    inputs={k:data.get(k) for k in ('project_id','selected_project_id','object_id','additional_materials','literature_plan')}
    # Full current catalog fingerprints detect changed sources/ACL/search order,
    # while previews and prompts expose only bounded scientific candidates.
    pin={'version':VERSION,'request_sha256':digest(request),'context_sha256':digest(inputs),'project':_ref(project),'catalog_sha256':digest([_ref(o) for o in sorted(available,key=lambda x:x['id'])])}
    result.update(status='needs_selection' if ambiguities else 'ready',materials=visible,pin=pin,selected_bytes=total)
    return result

def prepare_submission(app,data,scope=None,connection=None):
    """Return (project, frozen refs, resolution report); preserve explicit [] mode."""
    auto=data.get('material_mode')=='auto' or ('materials' not in data and data.get('kind')!='workshop' and data.get('action')!='workshop.submit')
    if not auto:
        project=_writable_project(app,data['project_id'],scope,connection);refs=[]
        require(isinstance(data.get('materials',[]),list),'明确材料需要列表；空列表表示不自动选材')
        for value in data.get('materials',[]):
            obj,_=material(app,value,project['id'],scope,connection);refs.append(_ref(obj))
        return project,refs,None
    preview=resolve(app,data,scope,connection)
    require(not data.get('resolution_pin') or preview['pin']==data['resolution_pin'],'项目或材料来源已变化，请重新预览','conflict',409)
    require(preview['status']=='ready','需要明确项目或材料选择','resolution_required',409,preview)
    project=_writable_project(app,preview['project']['id'],scope,connection)
    refs=[{k:m[k] for k in ('id','revision','sha256')} for m in preview['materials'] if m['selected']]
    report={'version':VERSION,'mode':'auto','pin':preview['pin'],'included':[{k:m[k] for k in ('id','revision','sha256','reason','bytes')} for m in preview['materials'] if m['selected']], 'excluded':preview['excluded'],'gaps':preview['gaps'],'limits':preview['limits'],'selected_bytes':preview['selected_bytes'],'projection':'scientific_fields_v1'}
    return project,refs,report
