"""Scoped model questions. A suggestion is never a tool or spending grant."""
from __future__ import annotations
import copy
import re
from research_partner.storage.store import Problem, digest, require

SCOPES=frozenset({'current_task','followup','optional','historical'})


def model_questions(values):
    require(isinstance(values,list) and len(values)<=32,'模型问题必须为最多32项的列表','invalid_model_output',422)
    result=[];ids=set()
    for index,raw in enumerate(values):
        path='questions.'+str(index)
        def check(condition,message):require(condition,message,'invalid_model_output',422,{'path':path})
        check(isinstance(raw,dict),'问题必须为对象')
        check(isinstance(raw.get('question'),str) and raw['question'].strip(),'问题需要具体正文')
        check('blocking' not in raw or type(raw['blocking']) is bool,'问题blocking必须为布尔值')
        scope=raw.get('scope','historical');check(scope in SCOPES,'问题scope必须明确当前任务、后续建议或可选反馈')
        ident=raw.get('id') or ('legacy-'+digest(raw)[:16]+'-'+str(index))
        if scope!='historical':
            check(isinstance(raw.get('id'),str) and bool(re.fullmatch(r'[A-Za-z0-9_:.-]{1,180}',raw['id'])),'问题需要稳定ASCII id')
            check(isinstance(raw.get('background'),str) and raw['background'].strip(),'问题需要已有证据背景')
            check(isinstance(raw.get('recommendation'),str) and raw['recommendation'].strip(),'问题需要建议及理由/不确定性')
            options=raw.get('options');check(isinstance(options,list) and 2<=len(options)<=8,'问题需要2–8项带后果的选项')
            option_ids=set()
            for option in options:
                check(isinstance(option,dict),'问题选项必须为对象')
                check(isinstance(option.get('id'),str) and bool(re.fullmatch(r'[A-Za-z0-9_:.-]{1,180}',option['id'])),'选项需要稳定ASCII id')
                check(option['id'] not in option_ids,'选项ID重复');option_ids.add(option['id'])
                for key in ['label','consequence']:check(isinstance(option.get(key),str) and option[key].strip(),'选项需要名称与后果')
            check(scope=='current_task' or not raw.get('blocking'),'后续方案或可选反馈不得阻断当前任务')
            check(not(set(raw)-{'id','question','scope','blocking','background','options','recommendation','source_refs'}),'问题含未支持的字段')
        check(isinstance(ident,str) and ident not in ids,'问题ID重复');ids.add(ident)
        result.append({'id':ident,'question':raw['question'].strip(),'scope':scope,
            'blocking':scope=='current_task' and raw.get('blocking',False),'background':raw.get('background',''),
            'options':copy.deepcopy(raw.get('options',[])),'recommendation':raw.get('recommendation',''),
            'raw':copy.deepcopy(raw),'source_refs':copy.deepcopy(raw.get('source_refs',[]))})
    return result


def scoped_input(content):
    """Keep legacy user questions compatible; unbound proposals stay independent."""
    return content.get('scope') not in {'followup','optional','historical'} or bool(content.get('bound_task_id'))


def decision_projection(obj):
    content=obj['content']
    result={'id':obj['id'],'revision':obj['revision'],'question':obj['title'],'answer':content.get('answer'),
        'disposition':content.get('disposition','defer'),'grants_permissions':False}
    if content.get('source_reassessment'):
        result['source_review']=copy.deepcopy(content['source_reassessment'])
    return result


def scientific_candidate(candidate,kind):
    """Project each scientific structure; unknown nested checkpoint fields stop here."""
    from research_partner.domains.collaboration.commission import COMMON,PROSE,LAYOUT
    def scalar(value,path):
        require(value is None or type(value) in {str,int,float,bool},'候选科学字段不是标量文本/数值','candidate_checkpoint_invalid',409,{'field':path})
        return value
    def sequence(value,project,path):
        require(isinstance(value,list),'候选科学字段不是列表','candidate_checkpoint_invalid',409,{'field':path})
        return [project(item,path+'.'+str(index)) for index,item in enumerate(value)]
    def record(value,fields,nested,path):
        require(isinstance(value,dict),'候选科学结构不是对象','candidate_checkpoint_invalid',409,{'field':path})
        return {key:(nested[key](item,path+'.'+key) if key in nested else scalar(item,path+'.'+key))
            for key,item in value.items() if key in fields or key in nested}
    refs={'id','object_id','revision','block_id','citation_key','label','caption','role','title','description'}
    def reference(value,path):return record(value,refs,{},path)
    ref_fields={'source_ref':reference,**{name:lambda value,path:sequence(value,reference,path) for name in ['source_refs','citations','components']}}
    linkage={'component_id','component_revision','source_object_id','source_revision'}
    def block(value,path):return record(value,{'id','kind','type','text','level','title','asset','caption'}|linkage,ref_fields,path)
    def claim(value,path):return record(value,{'id','text','limitation','kind','status'},
        {**ref_fields,'evidence_ids':lambda value,path:sequence(value,scalar,path)},path)
    def option(value,path):return scalar(value,path) if isinstance(value,str) else record(value,{'id','label','consequence'}, {},path)
    def question(value,path):return record(value,{'id','question','scope','blocking','background','recommendation'},
        {**ref_fields,'options':lambda value,path:sequence(value,option,path)},path)
    geometry={'id','type','x','y','width','height','text','label','font_size','linewidth','group','z','color','fill','stroke','align','bold','asset','asset_id','src'}|linkage
    def node(value,path):return record(value,geometry,ref_fields,path)
    def edge(value,path):return record(value,{'id','source','target','src','dst','label','type','status','font_size','linewidth','group','color'}|linkage,ref_fields,path)
    def page(value,path):return record(value,{'id','title','width','height','notes','background'},
        {**ref_fields,'objects':lambda value,path:sequence(value,node,path)},path)
    def assets(value,path):
        require(isinstance(value,dict),'候选附件映射无效','candidate_checkpoint_invalid',409,{'field':path})
        return {name:scalar(sha,path+'.'+name) for name,sha in value.items()}
    nested={**ref_fields,**{name:lambda value,path,project=project:sequence(value,project,path)
        for name,project in [('blocks',block),('claims',claim),('questions',question),('nodes',node),('edges',edge),('pages',page),('citation_keys',scalar)]},'latex_assets':assets}
    allowed=COMMON|(LAYOUT[kind] if kind in LAYOUT else PROSE)
    return record(candidate,allowed-set(nested),{key:value for key,value in nested.items() if key in allowed},'candidate')


def question_view(store,obj,connection=None):
    if obj['kind']!='question':return obj
    if connection is None:
        with store.connect() as c:return question_view(store,obj,c)
    import json
    content=obj['content'];ref=content.get('source_ref');candidate=content.get('source_candidate');source=[];base=[];addressed=False
    def artifact_source(ref):
        if not isinstance(ref,dict) or not isinstance(ref.get('id'),str) or type(ref.get('revision')) is not int:return None
        try:
            latest=store.get(ref['id'],connection=connection)
            require((latest.get('project_id') or latest['id'])==obj['project_id'] or obj['project_id'] in latest['metadata'].get('shared_with',[]),'来源不可访问','forbidden',403)
            store.get(ref['id'],ref['revision'],connection)
            return {'kind':'artifact','id':ref['id'],'revision':ref['revision'],'current_revision':latest['revision'],'stale':latest['revision']!=ref['revision']}
        except Problem:return {'kind':'artifact','id':ref['id'],'revision':ref['revision'],'unavailable':True,'stale':True}
    if isinstance(candidate,dict):
        lineage=artifact_source(ref)
        if lineage:base.append(lineage)
        ref=None  # A target's base is lineage, not the candidate being questioned.
        row=connection.execute("SELECT steps.data FROM steps JOIN tasks ON tasks.id=steps.task_id WHERE task_id=? AND step_key='model' AND tasks.project_id=?",(candidate.get('task_id'),obj['project_id'])).fetchone()
        model=json.loads(row[0]) if row else {};current=model.get('sha256')
        addressed=bool(current and current!=candidate.get('sha256') and candidate.get('task_id')==content.get('task_id')
            and {'id':obj['id'],'revision':obj['revision']} in model.get('input_snapshot',{}).get('decisions',[]))
        if current==candidate.get('sha256'):
            saved=connection.execute("SELECT data FROM steps WHERE task_id=? AND step_key='persist'",(candidate.get('task_id'),)).fetchone()
            adopted=json.loads(saved[0]) if saved else {}
            if adopted.get('object_id') and type(adopted.get('revision')) is int:
                ref={'id':adopted['object_id'],'revision':adopted['revision']}
        source.append({'kind':'candidate','task_id':candidate.get('task_id'),'sha256':candidate.get('sha256'),'current_sha256':current,
            'latest_candidate_known':current is not None,'stale':current is not None and current!=candidate.get('sha256')})
    if not ref and not source and content.get('object_id') and content.get('task_id'):
        row=connection.execute("SELECT steps.data FROM steps JOIN tasks ON tasks.id=steps.task_id WHERE task_id=? AND step_key='persist' AND tasks.project_id=?",(content['task_id'],obj['project_id'])).fetchone()
        if row:
            adopted=json.loads(row[0])
            if adopted.get('object_id')==content['object_id'] and type(adopted.get('revision')) is int:
                ref={'id':adopted['object_id'],'revision':adopted['revision']}
    primary=artifact_source(ref)
    if primary:source.insert(0,primary)
    for extra in content.get('source_refs',[]):
        item=artifact_source(extra)
        if item and item not in source:source.append(item)
    stale=any(item.get('stale') for item in source)
    reassessment=content.get('source_reassessment') or {}
    reassessed=bool(reassessment.get('reason') and reassessment.get('source_snapshot')==source)
    scope=content.get('scope','current_task' if content.get('blocking') else 'optional')
    valid=not stale or reassessed or (addressed and not any(item.get('stale') for item in source if item['kind']!='candidate'))
    view={'scope':scope,'source_bound':bool(source),'source_stale':stale,'source_valid':valid,'source_addressed':addressed,
        'source_reassessed':reassessed,'sources':source,'base_sources':base,
        'effective_blocking':bool(content.get('blocking')) and scoped_input(content),'parent_question_id':content.get('parent_question_id'),
        'materializable':bool(content.get('model_questions')),'inherited_answer':content.get('inherited_answer'),
        'needs_attention':not obj.get('archived') and scope!='historical' and content.get('status','open')=='open' and not stale}
    return {**obj,'question_view':view}
