"""Adapt the authored egg example to named, stateful QAEC without replacing text."""
from urllib.parse import urlencode

ROOT_TITLE = '如何协调蛋白与蛋黄不同的加热需求，实现蛋白凝固、蛋黄柔软？'
TITLES = {
 'q1':('逐枚比较蛋白与蛋黄是否同时达标','四种煮法的两项指标与联合达标结果','冷热交替表现较好，但尚不能稳定达标'),
 'qw':('按7.5阈值统计蛋白凝固情况','四种煮法的蛋白达标数与缺失记录','恒温程序的主要瓶颈是蛋白未充分凝固'),
 'qy':('按5至8.5区间核对蛋黄软度','四种煮法的蛋黄目标区间计数','只达到蛋黄目标不足以选定整枚煮法'),
 'q2':('按鸡蛋大小与初温比较同一程序','六种大小与初温组合的达标表现','现有分层结果不足以确认广泛适用'),
 'qs':('比较六个大小与初温组合','大小与初温分层后的联合达标率','不同条件下的达标表现存在差异'),
 'qb':('区分批次变化与加热过程混杂','分批结果及热端停留变化记录','现有批次无法分离过程变化的影响'),
 'qt':('比较不同蛋白阈值下的结果','阈值敏感性分析的达标计数','判据变化需要纳入适用范围判断'),
}

def configure_graph(call, pid):
 research=call('workbench.research.read',project_id=pid);project=research['project'];root_id=project['metadata'].get('research_root_question_id')
 previous={q['id']:q['content']['qaec'].copy() for q in research['questions']}
 if not root_id:
  roots=[q for q in research['questions'] if not q.get('tree_parent_id')]
  value=call('workbench.root.set',project_id=pid,expected_project_revision=project['revision'],title=ROOT_TITLE,attach_roots=True,expected_roots=[{'id':q['id'],'revision':q['revision']} for q in roots],request_key='egg-article-root-v1:'+pid)
  root_id=value['question']['id'];root=value['question']
  root=call('workbench.question.save',project_id=pid,id=root_id,expected_revision=root['revision'],title=root['title'],qaec={
   'Q':ROOT_TITLE+'\n\n先比较四种加热程序，再检查冷热交替程序对鸡蛋大小与下锅前初温的适用范围。两项目标必须在同一枚蛋上同时满足。',
   'A':'综合煮法比较与条件分层，分别检查单枚蛋的两项指标、联合达标、缺失读数和批次混杂，不以整组均值替代单枚判断。',
   'E':'方法比较和大小、初温分层已有结果；根问题的综合判断采用对应子问题的核对记录，并保留原始数据、脚本和图表来源。',
   'C':'冷热交替在当前比较中更有希望，但多数鸡蛋仍未同时达到两项目标，且大小、初温与批次过程仍限制推广。需要进一步验证，文章研究问题尚未完整回答。'},status='active',request_key='egg-root-body-v1:'+pid)
 research=call('workbench.research.read',project_id=pid);by_key={q['metadata'].get('demo_question_key'):q for q in research['questions'] if q['metadata'].get('demo_question_key')}
 for initial in research['questions']:
  key=initial['metadata'].get('demo_question_key');is_root=initial['id']==root_id
  titles=('综合煮法比较与适用范围','汇总子问题的结果与限制','冷热交替有优势，适用范围仍需验证') if is_root else TITLES.get(key)
  if not titles:continue
  q=initial
  for part,title in zip(('Q','A','E','C'),(q['title'],*titles)):
   if q['metadata'].get('research_nodes',{}).get(part):continue
   deps=[]
   if is_root and part=='Q':
    deps=[{'question_id':by_key[k]['id'],'part':'Q','kind':'requires'} for k in ('q1','q2') if k in by_key]
   if is_root and part in ('E','C'):
    deps=[{'question_id':by_key[k]['id'],'part':part,'kind':'requires' if part=='E' else 'supports'} for k in ('q1','q2') if k in by_key]
   if not is_root and part=='E':deps=[{'question_id':q['id'],'part':'A','kind':'requires'}]
   state='active' if part=='Q' and (is_root or key=='qb') else 'review' if q['content']['qaec'][part].strip() else 'not_started'
   q=call('workbench.node.save',project_id=pid,question_id=q['id'],part=part,expected_revision=q['revision'],title=title,status=state,dependencies=deps,request_key='egg-node-state-v1:'+q['id']+':'+part)['question']
 final=call('workbench.research.read',project_id=pid)
 assert all(q['content']['qaec']==previous[q['id']] for q in final['questions'] if q['id'] in previous), 'Existing research text changed'
 return {'root_question_id':root_id,'question_count':len(final['questions']),'existing_qaec_unchanged':True,'confirmation_policy':'No completion inferred from existing text'}

if __name__=='__main__':
 import argparse,json,pathlib,urllib.request,urllib.parse,uuid
 parser=argparse.ArgumentParser();parser.add_argument('--base-url',default='http://127.0.0.1:8924');parser.add_argument('--project',required=True);parser.add_argument('--receipt',type=pathlib.Path,required=True);args=parser.parse_args();base=args.base_url.rstrip('/')
 if urllib.parse.urlparse(base).hostname not in {'localhost','127.0.0.1'}:raise ValueError('An explicitly local workspace is required.')
 state=json.load(urllib.request.urlopen(base+'/api/state'));csrf=state['csrf'];project=next(p for p in state['projects'] if p['id']==args.project)
 assert project['metadata'].get('demo')=='scientific_egg_v1','Only the authored scientific egg example can be adapted by this command'
 assert not any(t['project_id']==args.project and t['status'] in ('queued','running') for t in state['tasks']), 'Wait for active project work'
 args.receipt.parent.mkdir(parents=True,exist_ok=True);before=args.receipt.with_suffix('.before.json');before.write_text(json.dumps(state,ensure_ascii=False))
 def call(action,**fields):
  req=urllib.request.Request(base+'/api/action',json.dumps({'action':action,**fields}).encode(),{'Content-Type':'application/json','X-CSRF-Token':csrf,'Origin':base})
  try:body=json.load(urllib.request.urlopen(req))
  except urllib.error.HTTPError as e:raise RuntimeError(e.read().decode()) from e
  assert body['ok'],body
  return body['result']
 result=configure_graph(call,args.project);after=json.load(urllib.request.urlopen(base+'/api/state'));new={o['id']:o for o in after['objects']}
 protected=[o for o in state['objects'] if (o['project_id']!=args.project and o['id']!=args.project) or o['kind']=='paper']
 assert all(new[o['id']]==o for o in protected),'Unexpected change outside research nodes'
 result.update(project_id=args.project,paper_and_other_projects_unchanged=True,before_snapshot=str(before));args.receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
