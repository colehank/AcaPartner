"""Append task-level reports to actual project Markdown, without dispatching.

A report is a projection of fixed task evidence and current explicit decisions,
not an invented scientific conclusion. Stable content markers make replay safe;
concurrent file changes use the native CAS/recovery service and retain both.
"""
from .store import require,digest,encoded,uid,now,Problem


def _quote(text):
    return '\n'.join('> '+line for line in str(text or '').splitlines()) or '> （无正文）'


def report(app,project,task,scope,principal):
    if task['payload'].get('kind')=='research_cycle':
        from .cycle_brief import report as cycle_report
        record,lines=cycle_report(app,project,task,scope)
    elif task['payload'].get('kind')=='research':
        from .research_brief import report as research_report
        record,lines=research_report(app,project,task,scope)
    elif task['payload'].get('kind')=='manuscript_revision':
        # Both the workdesk and the public revision API create real rounds.
        # Access to the original contract, all target objects and proposal is
        # checked by the same public view; a desk-only index is not authority.
        view=app.dispatch({'action':'manuscript.revision.view','task_id':task['id']},scope,principal=principal)
        proposal=view.get('proposal')
        require(proposal is not None,'本轮尚无实际候选；不生成完成回报','not_ready',409)
        record={'task_id':task['id'],'status':task['status'],'proposal_sha256':proposal['proposal_sha256'],'candidate_sha256':proposal['candidate_sha256'],'decision_version':view['decision_version'],
                'summary':proposal['candidate']['summary'],'responses':proposal['responses'],'changes':proposal['changes'],'current_target_revisions':view['current_target_revisions']}
        lines=['### 稿件整轮意见','任务：'+task['id'],'实际状态：'+task['status'],'候选摘要：',_quote(record['summary']),
               '候选 SHA：`'+record['candidate_sha256']+'`',f'[打开本轮意见与决定](/?project={project["id"]}&task={task["id"]})']
        context=task['payload']['context']['manuscript_revision'].get('native_note_context')
        if context and context.get('notes'):
            from .native_review_context import note_ref
            refs=[note_ref(n) for n in context['notes']]
            record['native_note_context']={'sha256':context['sha256'],'refs':refs}
            lines+=['#### 固定原生笔记阅读上下文','提供上下文不等于已核实Agent读取；笔记未授权写入。','上下文 SHA：`'+context['sha256']+'`']
            for ref in refs:
                lines+=['- 固定保存版：'+ref['id']+'；r'+str(ref['revision'])+'；SHA `'+ref['content_sha256']+'`',_quote(ref['relative_path'])]
                if 'fragment' in ref:
                    fragment=ref['fragment']
                    lines += [f"  仅选中原文码点 [{fragment['start_offset']}, {fragment['end_offset']})；片段 SHA `"+fragment['content_sha256']+'`；未提供整篇正文。']
        for response in record['responses']:
            lines+=['#### 意见 '+response['opinion_id'],_quote(response['text']),'实际核查：'+str(response.get('verification','')),'限制：'+str(response.get('limitations',''))]
        for change in record['changes']:
            lines+=['- '+change['id']+'：'+change['state']+'；目标 '+str(change['target'])+('；当前文字冲突，手改保留' if change.get('conflict') else '')]
    elif task['payload'].get('kind')=='generation':
        require(task['status']=='generated' and task['result'].get('output_checks'),'计算尚未登记可验证输出；不生成完成回报','not_ready',409)
        p=task['payload']['generation_plan'];result=task['result']
        record={'task_id':task['id'],'plan_hash':p['plan_hash'],'result':result}
        lines=['### 受管计算回报','任务：'+task['id'],'固定计划：`'+p['plan_hash']+'`',
               '实际待跑：'+', '.join(result['planned_jobs']),'已核验复用：'+', '.join(result['reused_nodes']),
               f'[打开固定运行与来源](/?project={project["id"]}&generation_run={task["id"]})']
        if p.get('shared_generation'):
            lines+=['共同计算目标：'+str(len(p['target_mappings']))+'；独立计算步骤：'+str(len(p['nodes']))]
            for target in p['target_mappings']:
                lines+=['#### 成果 '+target['title']+' · '+target['recipe_ref']['id']+' r'+str(target['recipe_ref']['revision']),
                        '固定配方 SHA：`'+target['recipe_sha256']+'`']
                for local,physical in target['nodes'].items():lines+=['- '+local+' → '+physical+'；实际运行 '+result['nodes'][physical]['run_id']]
        for node in p['nodes']:
            actual=result['nodes'][node['id']]
            lines+=['#### '+node['id']+' · '+node['role'],'实际代码：'+node['script_snapshot']['relative_path']+'；SHA `'+node['script_snapshot']['sha256']+'`','参数：`'+encoded(node['parameters'])+'`']
            for name,output in actual['outputs'].items():lines+=['- ['+name+'](/api/assets/'+output['asset_sha256']+')；实际 '+str(output['snapshot']['row_count'])+' 行；SHA `'+output['asset_sha256']+'`']
    elif task['payload'].get('kind')=='figure_composition':
        result=task['result'];ref=result.get('composition_candidate');provider=result.get('provider',{})
        require(task['status']=='generated' and isinstance(ref,dict),'主图委托尚无已登记实际候选；不生成完成回报','not_ready',409)
        plan=task['payload']['context']['figure_composition']
        event_field='native_dynamic_events_sha256' if provider.get('transport')=='app_server_dynamic' else 'native_mcp_events_sha256'
        provider_completed=(provider.get('native_terminal_confirmed') is True and provider.get('native_status')=='completed') if provider.get('transport')=='app_server_dynamic' else provider.get('returncode')==0
        require(ref.get(event_field)==provider.get('events_sha256') and provider.get('session_identity_confirmed') is True
                and provider_completed and ref.get('actual_source_reads')==len({(s['id'],s['revision']) for s in plan['fixed_sources']})
                and ref.get('native_tool_event_ids'),'主图原登记回执与候选不一致','domain_tools_unverified',409)
        view=app.dispatch({'action':'desk.figure.read','project_id':project['id'],'id':ref['id'],'revision':ref['revision']},scope,principal=principal)
        require(digest(view['figure'])==ref['sha256'] and view['definition_sha256']==ref['definition_sha256'],'主图候选或固定定义摘要不符','integrity',409)
        sources=[s['source'] for s in view['definition']['slots'] if s['source']]
        require({encoded(s) for s in sources}=={encoded(s) for s in plan['fixed_sources']},'主图候选来源不同于原任务','integrity',409)
        authored=app.get(result['object_id'],scope,result['revision'])
        require(authored['project_id']==project['id'] and authored['kind']=='note','主图说明不属于此项目','forbidden',403)
        outputs={name:asset['sha'] for name,asset in (view.get('render') or {}).get('assets',{}).items() if name in {'canvas.svg','canvas.png','canvas.pdf','source.json'}}
        record={'task_id':task['id'],'status':task['status'],'composition_candidate':ref,'fixed_sources':plan['fixed_sources'],
                'provider_receipt':{k:provider.get(k) for k in ('route','model','session_id','resumed_from','invocation','attempt_id','events_sha256')},
                'authored_note_ref':{'id':authored['id'],'revision':authored['revision'],'sha256':digest(authored)},'rendered_outputs':outputs}
        if provider.get('transport')=='app_server_dynamic':
            record['provider_receipt'].update(transport='app_server_dynamic',native_turn_id=provider.get('native_turn_id'))
        lines=['### 主图组成回报','任务：'+task['id'],'固定候选：'+ref['id']+' r'+str(ref['revision'])+'；SHA `'+ref['sha256']+'`',
               '固定定义 SHA：`'+ref['definition_sha256']+'`','原登记来源读取：'+str(ref['actual_source_reads']),
               '原生会话：'+str(provider.get('session_id'))+'；原事件 SHA `'+provider['events_sha256']+'`',
               f'[打开此主图的当前保存版](/?project={project["id"]}&figure={ref["id"]})',
               '候选创建不代表采用、科研批准或审查通过；后续手改不改变本条固定引用。']
        for slot in view['definition']['slots']:
            source=slot['source']
            lines+=['- 图位 '+slot['id']+'：'+(source['id']+' r'+str(source['revision'])+'；SVG `'+source['svg_sha256']+'`' if source else '未接入')]
        for name,sha in outputs.items():lines+=['- [固定输出 '+name+'](/api/assets/'+sha+')；SHA `'+sha+'`']
        if not outputs:lines+=['此固定候选尚无实际重绘输出；写简报不会重绘。']
        lines+=['#### Agent原说明（含原限制）']
        for block in authored['content'].get('blocks',[]):lines+=[_quote(block.get('text',''))]
    else:require(False,'该任务类型尚无原生简报适配','unsupported_action',422)
    lines+=['','这是一条任务级工程回报。运行、候选和用户采用分别记录；未取得科学批准或正式验收通过。']
    return record,'\n\n'.join(lines)+'\n'


def append(app,project,task,scope=None,principal=None,expected_final_source=None):
    require(task['project_id']==project['id'],'任务不属于本项目','forbidden',403)
    record,text=report(app,project,task,scope,principal);marker='<!-- rp-task-report:'+digest(record)+' -->'
    if task['payload'].get('kind')=='research_cycle':
        from .cycle_brief import _reference
        require(_reference(expected_final_source)==record['fixed_output'],
                '协作最终稿已变化；请重新读取，未把另一版本写入简报','conflict',409)
    path='notes/tasks/'+task['id']+'.md'
    base={'project_id':project['id'],'request_id':'brief:'+digest(record)}
    try:
        document=app.dispatch({'action':'notes.read',**base,'payload':{'relative_path':path}},scope,principal=principal)
    except Problem as error:
        if error.status!=404:raise
        document=None
    if task['payload'].get('kind') in {'research','research_cycle'}:
        # A note read may observe concurrent source withdrawal or a changed
        # task result. Recheck before returning/replaying or writing a brief.
        current,_=report(app,project,app.store.task(task['id']),scope,principal)
        require(digest(current)==digest(record),'研究候选已变化；请重新读取任务，未追加另一份候选','conflict',409)
    if document and marker in document['markdown']:return {'note':document,'appended':False,'executed':False}
    raw=(document['markdown'] if document else '# 任务回报 · '+task['id']+'\n')+'\n'+marker+'\n\n记录时间：'+now()+'\n\n'+text
    if document:
        command={'action':'notes.write',**base,'payload':{'relative_path':path,'expected_content_sha256':document['content_sha256'],'markdown':raw,'encoding':'utf-8'}}
    else:command={'action':'notes.create',**base,'payload':{'relative_path':path,'markdown':raw,'if_absent':True}}
    def marker_value(saved):
        return {'note_id':saved['id'],'relative_path':path,'content_sha256':saved['content_sha256'],'record_sha256':digest(record)}
    if task['payload'].get('kind') in {'research','research_cycle'}:
        def check():
            from .desk_w1a import _project
            current_project=_project(app,project['id'],scope,principal,write=True)
            current,_=report(app,current_project,app.store.task(task['id']),scope,principal)
            require(digest(current)==digest(record),'研究候选已变化；请重新读取任务，未追加另一份候选','conflict',409)
        def published(connection,saved):
            connection.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                               ('task_native_brief:'+task['id'],encoded(marker_value(saved))))
        # No wire field grants this fence. Retain App's normal command path,
        # then serialize current source/project authority with file publication.
        with app.notebook._guard_publication(command,check,published):
            saved=app.dispatch(command,scope,principal=principal)
    else:
        saved=app.dispatch(command,scope,principal=principal)
        app.store.set_setting('task_native_brief:'+task['id'],marker_value(saved))
    return {'note':saved,'appended':True,'executed':False}
