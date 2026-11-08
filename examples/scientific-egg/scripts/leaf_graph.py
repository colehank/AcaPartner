"""Organize the authored egg graph without replacing its saved research content."""
TITLES={
 'q1':'四种煮法中，哪种方法的联合达标率最高？',
 'q2':'现有证据支持冷热交替法适用于哪些大小与初温条件？',
}
BODIES={
 'q1':'综合蛋白凝固、蛋黄柔软的单项结果，按同一 sample_id 判断两项目标是否同时满足，比较四种程序的联合达标率。蛋白评分≥7.5，蛋黄评分5至8.5。单项达标率不能代替逐枚联合判断；结论限于本例数据与程序。',
 'q2':'综合大小与初温分层、批次过程核对和阈值敏感性，判断当前证据能够支持的适用范围。已有分层结果不等于稳定泛化；固定程序后的独立批次验证尚未开展，不填造验证结果。',
}

def configure_leaf_questions(call,pid):
    research=call('workbench.research.read',project_id=pid)
    assert research['project']['metadata'].get('demo')=='scientific_egg_v1','Only the authored egg case is adapted'
    original={q['id']:q['content'] for q in research['questions']}
    by_key={q['metadata'].get('demo_question_key'):q for q in research['questions']}
    graph=call('workbench.graph.read',project_id=pid);before={n['id']:(n['title'],n['body']) for n in graph['nodes']}
    eligible={n['id'] for n in graph['nodes'] if n['status']=='completed'};parents={k:by_key[k]['id'] for k in TITLES};children={};changed=False
    initial_scopes={k:{qid,*[n['id'] for n in graph['nodes'] if (n.get('origin') or {}).get('kind')=='question_organization' and n['origin']['question_id']==qid]} for k,qid in parents.items()}
    initial_answers={k:[e['src'] for e in graph['edges'] if e['active'] and e['kind']=='answers' and e['dst'] in initial_scopes[k]] for k in parents}
    def mutate(action,**fields):
        nonlocal graph,changed
        result=call('workbench.graph.'+action,project_id=pid,expected_project_revision=graph['project']['revision'],**fields)
        graph=result['graph'];changed=True;return result
    for key,parent in parents.items():
        routes=[e for e in graph['edges'] if e['active'] and ((e['kind']=='analyzes' and e['src']==parent) or (e['kind']=='answers' and e['dst']==parent))]
        if routes:
            n=next(n for n in graph['nodes'] if n['id']==parent)
            children[key]=mutate('question.organize',id=parent,expected_revision=n['revision'],title=TITLES[key],body=BODIES[key])['node_id']
        else:
            child_ids={e['dst'] for e in graph['edges'] if e['active'] and e['kind']=='contains' and e['src']==parent}
            candidates=[n for n in graph['nodes'] if n['id'] in child_ids and ((n.get('origin') or {}).get('kind')=='question_organization' and n['origin']['question_id']==parent or n['title']==TITLES[key])]
            assert len(candidates)<=1,'Ambiguous synthesis question; no automatic replacement'
            if candidates:
                n=candidates[0];children[key]=n['id']
                if n['title']!=TITLES[key] or n['body']!=BODIES[key]:
                    parent_node=next(x for x in graph['nodes'] if x['id']==parent)
                    assert n['title']==parent_node['title'] and n['body']==parent_node['body'],'Synthesis was edited; inspect it without overwriting'
                    mutate('node.save',id=n['id'],expected_revision=n['revision'],title=TITLES[key],body=BODIES[key],status='active')
            else:children[key]=mutate('node.create',kind='Q',title=TITLES[key],body=BODIES[key],status='active',parent_id=parent,relation_kind='contains')['node_id']
    def ensure(src,dst,kind,reason):
        existing=next((e for e in graph['edges'] if e['src']==src and e['dst']==dst and e['kind']==kind),None)
        if existing and existing['active']:return
        if existing:mutate('edge.save',id=existing['id'],expected_revision=existing['revision'],active=True,rationale=reason)
        else:mutate('edge.create',src=src,dst=dst,kind=kind,rationale=reason)
    for key,parent in parents.items():
        source_ids=[e['dst'] for e in graph['edges'] if e['active'] and e['kind']=='contains' and e['src']==parent and e['dst']!=children[key]]
        for ident in source_ids:ensure(ident,children[key],'prerequisite','综合子问题显式依赖前面子问题的回答；计算联合达标仍读取逐枚原始数据。')
    if changed:
        # Reconfirm only computations and conclusions that were authenticated
        # before this structural move. Pending findings never become complete.
        current={n['id']:n for n in graph['nodes']}
        desired={i for i in eligible if current[i]['kind'] in {'A','E','C'} and current[i]['status']!='completed'}
        q1_answered=bool(initial_answers['q1']) and all(i in eligible for i in initial_answers['q1'])
        if q1_answered:desired.update((children['q1'],parents['q1']))
        note='重新核对组织调整后的范围与依赖：原有数据、脚本和结果正文未变；蛋白≥7.5、蛋黄5至8.5，按同一枚蛋计算联合达标。四种程序的描述性比较可以作答，不代表稳定性或真实总体泛化。'
        while desired:
            ready=[n for n in graph['nodes'] if n['id'] in desired and n['can_complete']]
            if not ready:break
            for n in ready:
                n=next(x for x in graph['nodes'] if x['id']==n['id'])
                mutate('node.save',id=n['id'],expected_revision=n['revision'],title=n['title'],body=n['body'],status='completed',expected_dependencies=n['dependencies'],confirmation_note=note,answers_question=True)
                desired.remove(n['id'])
    final=call('workbench.research.read',project_id=pid)
    assert all(next(q for q in final['questions'] if q['id']==ident)['content']==content for ident,content in original.items() if ident not in children.values()),'Original QAEC content changed'
    assert all((n['title'],n['body'])==before[n['id']] for n in graph['nodes'] if n['id'] in before and n['id'] not in children.values()),'Original graph content changed'
    assert not any(n.get('needs_organization') for n in graph['nodes'])
    return {'graph':graph,'synthesis_questions':children,'original_content_unchanged':True,'changed':changed}

if __name__=='__main__':
    import argparse,json,pathlib,urllib.request,urllib.error,uuid
    p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:8924');p.add_argument('--project',required=True);p.add_argument('--receipt',type=pathlib.Path,required=True);args=p.parse_args();base=args.base_url.rstrip('/')
    state=json.load(urllib.request.urlopen(base+'/api/state'))
    def call(action,**fields):
        if action not in {'workbench.graph.read','workbench.research.read'}:fields['request_key']='egg-leaf-graph:'+str(uuid.uuid4())
        req=urllib.request.Request(base+'/api/action',data=json.dumps({'action':action,**fields}).encode(),headers={'Content-Type':'application/json','Origin':base,'X-CSRF-Token':state['csrf']})
        try:response=json.load(urllib.request.urlopen(req))
        except urllib.error.HTTPError as error:raise RuntimeError(error.read().decode()) from error
        assert response['ok'],response
        return response['result']
    result=configure_leaf_questions(call,args.project);args.receipt.parent.mkdir(parents=True,exist_ok=True);args.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'nodes':len(result['graph']['nodes']),'synthesis_questions':result['synthesis_questions'],'original_content_unchanged':True}))
