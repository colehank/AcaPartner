"""Migrate only the authored egg case; retain original QAEC, papers and notes.

API operations are the same version-bound operations available to an agent.
Existing verified decisions transfer; the small derived single-target summary is
explicitly checked against the case's fixed source, never a fabricated experiment.
"""
from leaf_graph import configure_leaf_questions
from revise_graph import revise_case_graph, SINGLE_ANALYSIS, SINGLE_EVIDENCE

def configure_free_graph(call,pid):
    research=call('workbench.research.read',project_id=pid)
    assert research['project']['metadata'].get('demo')=='scientific_egg_v1','Only the authored egg example may be adapted'
    by_key={q['metadata'].get('demo_question_key'):q for q in research['questions']}
    previous={q['id']:q['content'] for q in research['questions']}
    graph=call('workbench.graph.read',project_id=pid)
    if graph['migrated']:
        leaf=configure_leaf_questions(call,pid)
        return {**leaf,**revise_case_graph(call,pid)}
    def mutate(action,**fields):
        nonlocal graph
        result=call('workbench.graph.'+action,project_id=pid,expected_project_revision=graph['project']['revision'],**fields)
        graph=result['graph'];return result
    result=mutate('migrate',expected_sources=graph['source_refs']);mapping=result['mapping']
    leaf=configure_leaf_questions(call,pid);graph=leaf['graph'];q1,q2=by_key['q1']['id'],by_key['q2']['id'];s1,s2=leaf['synthesis_questions']['q1'],leaf['synthesis_questions']['q2']
    sources=[{'id':by_key[k]['id'],'revision':by_key[k]['revision']} for k in ('qw','qy')]
    a=mutate('node.create',kind='A',title='分别核对蛋白凝固与蛋黄柔软',body=SINGLE_ANALYSIS,status='review',parent_id=s1,relation_kind='analyzes',source_refs=sources)['node_id']
    e=mutate('node.create',kind='E',title='两项单独达标，不能推出整枚同时达标',body=SINGLE_EVIDENCE,status='review',parent_id=a,relation_kind='produces',source_refs=sources)['node_id']
    c1=mapping[q1+':C'];mutate('edge.create',src=e,dst=c1,kind='supports',rationale='解释不同煮法的单项目标瓶颈；结论仍同时需要逐枚联合达标证据，不能从边际计数推断联合达标。')
    # Method selection is a genuine Q-to-Q prerequisite, not decomposition.
    if not any(x['kind']=='prerequisite' and x['src']==q1 and x['dst']==q2 for x in graph['edges']):
        mutate('edge.create',src=q1,dst=q2,kind='prerequisite',rationale='先选定冷热交替程序，再判断该程序对大小与初温的适用范围。')
    mutate('node.create',kind='A',title='固定程序后做独立批次验证',body='保持同一冷热交替程序、热端停留与测量判据，预先确定大小及初温分层，收集独立批次。现有 B04 同时改变了过程条件，不能充当这一验证。\n\n等待新批次数据；尚未产生证据结果，也不填写虚构的 E。',status='not_started',parent_id=s2,relation_kind='analyzes')
    # Transfer only already-authenticated completed claims. The derived summary
    # is confirmed only when both underlying individual-target Qs are complete.
    if all(next(n for n in graph['nodes'] if n['id']==by_key[k]['id'])['status']=='completed' for k in ('qw','qy')):
        for ident in (a,e,c1,s1,q1):
            n=next(n for n in graph['nodes'] if n['id']==ident)
            mutate('node.save',id=ident,expected_revision=n['revision'],title=n['title'],body=n['body'],status='completed',expected_dependencies=n['dependencies'],answers_question=True,
                   confirmation_note='依据已核对的Q1.1、Q1.2固定保存版与480行原始计数，重新核对这次汇总关系。范围为本例四种程序的描述性比较；多数样本仍未联合达标，不推断稳定性或真实总体泛化。')
    final=call('workbench.research.read',project_id=pid)
    assert all(next(q for q in final['questions'] if q['id']==ident)['content']==content for ident,content in previous.items()),'Original QAEC content changed'
    return {'mapping':mapping,'original_qaec_unchanged':True,'new_analysis_id':a,'new_evidence_id':e,**revise_case_graph(call,pid)}

if __name__=='__main__':
    import argparse,json,pathlib,urllib.request,uuid
    p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:8924');p.add_argument('--project',required=True);p.add_argument('--receipt',type=pathlib.Path,required=True);args=p.parse_args();base=args.base_url.rstrip('/')
    state=json.load(urllib.request.urlopen(base+'/api/state'))
    def call(action,**fields):
        if action not in {'workbench.graph.read','workbench.research.read'}:fields['request_key']='egg-free-graph:'+str(uuid.uuid4())
        req=urllib.request.Request(base+'/api/action',data=json.dumps({'action':action,**fields}).encode(),headers={'Content-Type':'application/json','Origin':base,'X-CSRF-Token':state['csrf']})
        try:response=json.load(urllib.request.urlopen(req))
        except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode()) from e
        assert response['ok'],response
        return response['result']
    result=configure_free_graph(call,args.project);args.receipt.parent.mkdir(parents=True,exist_ok=True);args.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'nodes':len(result['graph']['nodes']),'edges':len(result['graph']['edges'])}))
