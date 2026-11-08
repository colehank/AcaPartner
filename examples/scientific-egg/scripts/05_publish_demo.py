"""Create a new, fully labelled example through existing local application APIs."""
from pathlib import Path
import argparse,base64,json,uuid,urllib.request,urllib.parse,hashlib,mimetypes,zipfile
from case_content import QUESTIONS,DESCRIPTION,build_case,readable_copy
from research_graph import configure_graph
from free_graph import configure_free_graph
ROOT=Path(__file__).resolve().parents[1]
CN={'soft_boiled':'沸水6分钟','hard_boiled':'沸水12分钟','sous_vide':'65°C恒温60分钟','periodic':'冷热交替32分钟'}
def package_case():
 bundle=ROOT/'scientific-egg-reproducible.zip'
 with zipfile.ZipFile(bundle,'w',zipfile.ZIP_DEFLATED) as z:
  for path in sorted(ROOT.rglob('*')):
   if path.is_file() and path!=bundle and '__pycache__' not in path.parts and path.suffix!='.pyc':z.write(path,path.relative_to(ROOT))
 return bundle

def publish(base,receipt):
 if urllib.parse.urlparse(base).hostname not in {'localhost','127.0.0.1'}:raise ValueError('Use an explicitly local workbench instance.')
 state=json.load(urllib.request.urlopen(base+'/api/state'));csrf=state['csrf']
 def call(action,**fields):
  request=urllib.request.Request(base+'/api/action',json.dumps({'action':action,**fields},ensure_ascii=False).encode(),{'Content-Type':'application/json','X-CSRF-Token':csrf})
  try:body=json.load(urllib.request.urlopen(request,timeout=120))
  except urllib.error.HTTPError as e:raise RuntimeError(action+': '+e.read().decode()) from e
  if not body.get('ok'):raise RuntimeError(str(body))
  return body['result']
 summary=json.loads((ROOT/'results/summary.json').read_text());protocol=json.loads((ROOT/'protocol.json').read_text());captions=json.loads((ROOT/'manuscript/captions.json').read_text());periodic=summary['methods']['periodic'];config_sha=hashlib.sha256((ROOT/'protocol.json').read_bytes()).hexdigest()
 project=call('project.create',title='科学煮蛋 · 可复现研究示例',content={'description':DESCRIPTION},metadata={'synthetic':True,'demo':'scientific_egg_v1','seed':protocol['seed'],'protocol_sha256':config_sha});pid=project['id'];ids={};assets={}
 def asset(path,name=None):
  data=path.read_bytes();entry=call('asset.import',project_id=pid,filename=name or path.name,base64=base64.b64encode(data).decode(),provenance='synthetic',source='AcaPartner synthetic cooking demonstration; actual local code output; no laboratory measurements')
  assets[str(path.relative_to(ROOT))]=entry;return entry
 def url(entry):return '/api/assets/'+entry['sha']
 def link(obj,label=None,fixed=True):
  params={'project':pid,'object':obj['id']};
  if fixed:params['revision']=str(obj['revision'])
  return '['+(label or obj['title'])+'](/?'+urllib.parse.urlencode(params)+')'
 def note_link(path,label):return '['+label+'](/?'+urllib.parse.urlencode({'project':pid,'note':path})+')'
 def obj(kind,title,markdown,role=None,sources=(),inputs=None,extra=None,short=None):
  content={'markdown':readable_copy(markdown),'source_refs':[{'id':s['id'],'revision':s['revision']} for s in sources]}
  if inputs:content['input_assets']=inputs
  if extra:content.update(extra)
  return call('object.create',kind=kind,title=title,project_id=pid,content=content,metadata={'synthetic':True,'research_role':role,'summary':short or ''})
 def upload_group(folder,extensions=None):
  return {p.name:asset(p) for p in sorted((ROOT/folder).iterdir()) if p.is_file() and (not extensions or p.suffix in extensions)}
 raw=asset(ROOT/'data/observations.csv');traces=asset(ROOT/'data/temperature_traces.csv');dictionary=asset(ROOT/'data/data_dictionary.json');config=asset(ROOT/'protocol.json');result_assets=upload_group('results',{'.csv','.json'});figure_assets=upload_group('figures',{'.png','.pdf','.svg'})
 script_assets={}
 for path in sorted((ROOT/'scripts').glob('0[1-4]*.py')):
  text=path.read_text();saved=call('recipe.script.write',project_id=pid,request_id=str(uuid.uuid4()),payload={'filename':path.name,'code':text,'expected_sha256':None});script_assets[path.name]={'sha':saved['sha256'],'url':'/api/assets/'+saved['sha256']}
 # A real immutable-data snapshot, with member identities checked by the existing service.
 import csv,io
 rows=list(csv.DictReader(io.StringIO((ROOT/'data/observations.csv').read_text())));columns=list(rows[0]);contract={'format':'csv','columns':columns,'identity_fields':['sample_id'],'units':{'mass_g':'g','initial_temperature_c':'degC','duration_s':'s','end_white_c':'degC','end_yolk_c':'degC','white_index':'arbitrary simulated units','yolk_index':'arbitrary simulated units'}}
 data=call('dataset.snapshot',project_id=pid,request_id=str(uuid.uuid4()),payload={'title':'原始观测 · 480枚鸡蛋','asset_sha256':raw['sha'],'contract':contract})
 preview='\n'.join('| '+r['sample_id']+' | '+r['method']+' | '+r['white_index']+' | '+r['yolk_index']+' | '+r['batch']+' |' for r in rows[:10])
 data_body=f'''**合成数据 · 不是实际实验记录。** 每行是一枚模拟蛋，蛋白与蛋黄按sample_id配对。\n\n480行、4程序、4批次；4行缺失保留，没有插补或剔除。40,080条温度记录不是40,080枚独立样本。\n\n[下载完整原始CSV]({url(raw)}) · [下载温度轨迹]({url(traces)}) · [变量字典]({url(dictionary)}) · [生成配置]({url(config)})\n\n## 原始数据前10行\n\n| 样本 | 程序 | 蛋白指数 | 蛋黄指数 | 批次 |\n|:--|:--|--:|--:|:--|\n{preview}\n\n## 身份与质量\n\n缺失样本：{', '.join(summary['checks']['missing_rows'])}。`quality_flag`逐行记录原因；原始CSV保持480行。两个指数为0–10的模拟代理量，不能解释为实测质构、蛋白质变性率或食品安全标准。\n\n原始CSV SHA-256：`{raw['sha']}`。完整列、单位和成员身份由当前数据快照保存。'''
 data=call('object.save',id=data['id'],expected_revision=data['revision'],content={**data['content'],'markdown':readable_copy(data_body)},metadata={'synthetic':True,'research_role':'material','summary':'480行原始配对观测；4个缺失读数保留；可下载完整CSV。'});ids['data']=data
 literature=obj('literature','背景文献 · 周期煮蛋',f'''[打开出版方原文](https://www.nature.com/articles/s44172-024-00334-w)\n\nDi Lorenzo E. et al. *Periodic cooking of eggs*. Communications Engineering 4, 5 (2025). DOI: 10.1038/s44172-024-00334-w。\n\n本项目只借用程序名称与条件作为背景。数据、双节点模型、质构代理量和噪声完全独立生成，不是该论文的实验数据或CFD复现。''','material');ids['literature']=literature
 script_links='\n'.join('- ['+name+']('+url(value)+')' for name,value in script_assets.items())
 analysis_body=f'''**合成数据分析；计算已在本机实际完成，未伪造后台Agent任务。**\n\n## 输入与规则\n\n输入：{link(data)}。判据与参数：[protocol.json]({url(config)})。蛋白指数≥7.5且蛋黄指数∈[5.0,8.5]，必须在同一样本上同时满足；缺失不插补，主要分母包含全部样本。\n\n## 可运行源码\n\n{script_links}\n\n01生成数据，02读取CSV并逐样本分类，03从分析输出绘图，04从JSON和图片组装文稿。下载完整包后按顺序执行；这些源码可查看、下载，但没有被冒充为已经登记的后台build_step任务。\n\n## 分析脚本\n\n```python\n{(ROOT/'scripts/02_analyze.py').read_text()}\n```\n\n## 数值输出\n\n[逐样本分类]({url(result_assets['classified_samples.csv'])}) · [按程序汇总]({url(result_assets['method_summary.csv'])}) · [分批结果]({url(result_assets['batch_summary.csv'])}) · [分层结果]({url(result_assets['condition_summary.csv'])}) · [阈值敏感性]({url(result_assets['threshold_sensitivity.csv'])})\n\n没有显著性检验。Wilson区间仅为模拟蛋级计数的描述，未调整批内依赖；四个模拟批次不等于实物重复验证。'''
 analysis=obj('report','分析与绘图 · 实际源码和输入输出',analysis_body,'analysis',[data,literature],{'script_'+str(i):a['sha'] for i,a in enumerate(script_assets.values())}|{'configuration':config['sha'],'summary':result_assets['summary.json']['sha'],'observations':raw['sha'],'temperature_traces':traces['sha'],'dictionary':dictionary['sha']},short='配对判据、完整源码、逐样本分类、分层与敏感性分析。');ids['analysis']=analysis
 figures={}
 for name in ['fig1_thermal','fig2_joint','fig3_robustness','figS1_conditions']:
  title={'fig1_thermal':'图1 · 蛋白与蛋黄的温度轨迹','fig2_joint':'图2 · 均值合适，配对却未普遍达标','fig3_robustness':'图3 · 批次与判据限制稳定性结论','figS1_conditions':'补充图 · 质量与初温分层'}[name];png=figure_assets[name+'.png'];pdf=figure_assets[name+'.pdf'];svg=figure_assets[name+'.svg']
  body=f'''**合成数据 · 原始数值由脚本实际生成与计算。**\n\n![{title}]({url(png)})\n\n{captions[name]}\n\n[下载PNG]({url(png)}) · [下载可编辑SVG]({url(svg)}) · [下载矢量PDF]({url(pdf)})\n\n## 追溯\n\n- {link(data,'原始样本与质量记录')}\n- {link(analysis,'分析与绘图脚本')}\n- [绘图源码]({url(script_assets['03_plot.py'])})\n- [按程序统计]({url(result_assets['method_summary.csv'])}) · [分批统计]({url(result_assets['batch_summary.csv'])}) · [分层统计]({url(result_assets['condition_summary.csv'])})\n\nPNG SHA-256：`{png['sha']}`。图中数值不能解释为真实煮蛋效果或安全建议。'''
  figures[name]=obj('figure',title,body,'result',[data,analysis],{'preview':png['sha'],'vector_pdf':pdf['sha'],'vector_svg':svg['sha'],'plot_source':script_assets['03_plot.py']['sha']},extra={'caption':captions[name],'synthetic':True},short=captions[name].split('。')[0]+'。')
 ids['figures']=figures
 table='\n'.join('| '+CN[k]+' | '+str(r['joint_pass_n'])+'/'+str(r['n_total'])+' | '+f"{r['joint_rate']:.1%}"+' | '+f"{r['wilson_low']:.1%}–{r['wilson_high']:.1%}"+' |' for k,r in summary['methods'].items())
 result_body=f'''**合成研究结果 · 脚本真实计算。**\n\n## 当前认识\n\n周期程序的平均蛋白指数{periodic['white_mean']:.2f}、平均蛋黄指数{periodic['yolk_mean']:.2f}均满足演示目标，逐枚配对却只有{periodic['joint_pass_n']}/120（{periodic['joint_rate']:.1%}）达标。不能用均值替代同一样本的联合事件，也不能从一个较好的批次自动推广稳定性。\n\n| 程序 | 配对达标/全部 | 达标率 | 名义95% Wilson区间 |\n|:--|--:|--:|:--|\n{table}\n\n## 图表证据\n\n{chr(10).join('- '+link(f) for f in figures.values())}\n\n## 范围与下一步\n\n温控偏移与B04热端停留变化同时出现，当前数据不能区分原因。下一轮应保持其他条件一致，单独检验热端占空比，并使用新批次或真实测量。模型、量表、四个模拟批次和名义区间都未经实物校准。\n\n{link(data)} · {link(analysis)} · [完整结果JSON]({url(result_assets['summary.json'])})'''
 result=obj('report','研究结果 · 可行性不等于稳定复现',result_body,'result',[data,analysis,*figures.values()],{'summary_json':result_assets['summary.json']['sha']},short=f"周期程序{periodic['joint_pass_n']}/120配对达标；均值与批次带来不同判断。");ids['result']=result
 run=obj('report','复现与执行记录 · 真实本机运行',f'''**这是实际脚本运行记录，不是平台后台任务，也不是实验室仪器记录。**\n\n[下载执行回执]({url(result_assets['run_receipt.json'])}) · [质量检查]({url(result_assets['quality_checks.json'])}) · [独立核验]({url(result_assets['verification.json'])})\n\n本机按顺序实际执行4个脚本，均返回0。固定种子可逐字节重新生成两份原始CSV；回执给出代码、输入和输出的SHA-256及环境版本。\n\n```sh\npython scripts/01_simulate.py\npython scripts/02_analyze.py\npython scripts/03_plot.py\npython scripts/04_write_paper.py\npython scripts/verify_demo.py\n```\n\n平台当前保留数据快照、登记源码、文稿与固定来源；未启动的Agent/SSH运行器仍显示未连接，不会显示假任务完成状态。\n\n{link(analysis)} · {link(result)}''','run_record',[analysis,result],{'receipt':result_assets['run_receipt.json']['sha']},short='4步实际本机计算、环境与SHA-256；不冒充平台任务。');ids['run']=run
 # Each question has its own goal, analysis, evidence and conclusion.
 sources={**ids,**figures}
 case=build_case(lambda key,label:link(sources[key],label))
 for key,parent,order,title,old_title in QUESTIONS:
  q=call('workbench.question.create',project_id=pid,title=title,parent_id=ids[parent]['id'] if parent else None,request_key=str(uuid.uuid4()))
  q=call('workbench.question.save',project_id=pid,id=q['id'],expected_revision=q['revision'],title=title,qaec=case['questions'][key],status='active' if key=='qb' else 'review',request_key=str(uuid.uuid4()))
  figure=figures['fig2_joint' if key in {'q1','qw','qy'} else 'figS1_conditions' if key=='qs' else 'fig3_robustness']
  q=call('object.save',id=q['id'],expected_revision=q['revision'],metadata={**q['metadata'],'demo_question_key':key,'workbench':{'order':order},
         'source_refs':[{'id':analysis['id'],'revision':analysis['revision']},{'id':figure['id'],'revision':figure['revision']}]})
  ids[key]=q
 research=call('workbench.research.read',project_id=pid)
 call('workbench.background.save',project_id=pid,expected_revision=research['project']['revision'],background=case['background'],request_key=str(uuid.uuid4()))
 # Default required paper: real DOCX, separate saved LaTeX and registered local figure attachments.
 paper=call('document.read',project_id=pid)
 paper_object=next(o for o in json.load(urllib.request.urlopen(base+'/api/state'))['objects'] if o['id']==paper['id'])
 latex_assets={name+'.png':figure_assets[name+'.png']['sha'] for name in figures}
 updated=call('object.save',id=paper['id'],expected_revision=paper['revision'],title='科学煮蛋 · 从配对达标到稳定性',content={**paper_object['content'],'latex_assets':latex_assets,'source_refs':[{'id':x['id'],'revision':x['revision']} for x in [data,analysis,result,*figures.values()]]})
 paper=call('document.save',project_id=pid,object_id=paper['id'],expected_revision=updated['revision'],request_key=str(uuid.uuid4()),format='docx',source={'base64':base64.b64encode((ROOT/'manuscript/paper.docx').read_bytes()).decode(),'filename':'scientific-egg-paper.docx'})
 paper=call('document.save',project_id=pid,object_id=paper['id'],expected_revision=paper['revision'],request_key=str(uuid.uuid4()),format='latex',source=(ROOT/'manuscript/paper.tex').read_text())
 render=None
 try:render=call('document.render',project_id=pid,object_id=paper['id'],expected_revision=paper['revision'],request_key=str(uuid.uuid4()))
 except RuntimeError as error:print('LaTeX preview unavailable:',error)
 # Package already generated public artifacts; no credentials, workspace paths or private notes.
 bundle=package_case()
 package=asset(bundle)
 guide_body=f'''**完整科研项目 · 全部数据为合成，计算与文件真实存在。**\n\n## 先看问题，再追到依据\n\n本例有480枚模拟蛋、40,080条温度记录、4种程序与4个批次。最值得观察的是：周期程序的均值满足目标，逐枚配对却只有{periodic['joint_pass_n']}/120达标；批次证据也不能支持稳定复现。\n\n1. {link(ids['q1'],'打开配对达标问题',False)}，在Q/A/E/C之间阅读。\n2. {link(data,'查看原始数据、缺失与完整CSV')}。\n3. {link(analysis,'检查真正运行过的分析和绘图代码')}。\n4. {link(figures['fig2_joint'],'打开配对证据图')}，再看{link(figures['fig3_robustness'],'批次与敏感性')}。\n5. {link(ids['q2'],'查看稳定性问题及其子问题',False)}，注意结论仍保留边界。\n6. [打开可编辑论文](/?{urllib.parse.urlencode({'project':pid,'paper':paper['id']})})；DOCX与LaTeX分别保存，不会自动互相同步。\n\n## 文件与复现\n\n{link(run)} · [下载完整数据、脚本、图和文章]({url(package)})\n\n左侧文件视角可查看实际登记的代码与文件；科研结构视角保留问题树。引用链接打开固定修订，图中数据能追到同一套CSV和脚本。\n\n{note_link('notes/示例/研究决策.md','研究决策与未决事项')} · {note_link('notes/示例/下一轮委托.md','下一轮工作约定')}\n\n## 能力边界\n\n示例中的脚本已在本机真实执行，但不是后台Agent会话；当前未接通的实时讨论与SSH仍按真实状态显示。可以从右侧编写委托，提交仍需要实际运行器、路线与授权。'''
 guide=obj('report','从这里开始 · 一次完整研究的导览',guide_body,'result',[result,run],{'reproduction_package':package['sha']},short='按问题→数据→代码→证据→论文浏览，或下载完整可复现包。');ids['guide']=guide
 notes={
 '从这里开始.md':guide_body,
 '研究设计.md':'# 研究设计\n\n合成数据演示。设计为4程序×4批次×3质量×2初温×5重复，共480枚。每枚蛋的白/黄读数有相同sample_id。\n\n'+link(data)+' · '+link(analysis)+'\n\n判据先按配置固定，再按同一样本分类。缺失不插补，不选择有利批次。',
 '研究决策.md':'# 研究决策与未决事项\n\n**合成数据，非实物实验。**\n\n- 保留全部480行；不因缺失或B04过程变化而删除样本。\n- “有配对成功样本”与“方法稳定”分别回答。\n- 不用均值替代联合事件，不用单批高成功率替代跨批验证。\n- B04的占空比变化与温控偏移混杂，暂不采用单一原因解释。\n\n'+link(result)+' · '+link(figures['fig3_robustness']),
 '下一轮委托.md':'# 下一轮工作约定\n\n这是一份可编辑的计划，不是已提交任务。可将下面要求复制到右侧“编写委托”。\n\n## 目的\n在当前合成模型内分离热端占空比与温控偏移的贡献，不改写原始480枚样本。\n\n## 输入\n'+link(data)+' · '+link(analysis)+' · '+link(result)+'\n\n## 工作与交付\n固定温控偏移，单独比较50%与58.3%的占空比；保留同样本参数与独立新种子，输出逐样本CSV、条件比较、图与限制。\n\n## 完成与停止条件\n说明所有输入和代码版本；不将计算结果表述为真实实验；模型或输入缺失时报告阻塞，不编造完成。任何论文更新作为可检查的候选提交。'}
 for name,body in notes.items():call('notes.create',project_id=pid,request_id=str(uuid.uuid4()),payload={'relative_path':'notes/示例/'+name,'markdown':readable_copy(body),'if_absent':True})
 for item in [guide,result,analysis,figures['fig2_joint'],run]:
  latest=call('workbench.research.read',project_id=pid)['project'];call('project.feature',project_id=pid,object_id=item['id'],featured=True,expected_revision=latest['revision'])
 files=call('article.files',project_id=pid)
 final_research=call('workbench.research.read',project_id=pid)
 assert len(final_research['questions'])==7, 'Published Q tree lost research identities'
 assert sum(bool(q['metadata'].get('parent_question_id')) for q in final_research['questions'])==5
 assert all(set(q['content']['qaec'])=={'Q','A','E','C'} for q in final_research['questions'])
 assert paper['source_state']['mode']=='docx'
 graph=configure_graph(call,pid)
 graph['free_graph']=configure_free_graph(call,pid)
 output={'research_graph':graph,'project_id':pid,'url':base+'/?project='+pid,'paper_id':paper['id'],'primary_format':paper['source_state']['mode'],'latex_rendered':bool(render),'objects':{k:v['id'] for k,v in ids.items() if isinstance(v,dict) and 'id' in v},'figures':{k:v['id'] for k,v in figures.items()},'registered_assets':len(assets),'project_file_count':len(files['entries']),'source_data_sha256':raw['sha'],'summary':summary['methods'],'synthetic':True}
 receipt.parent.mkdir(parents=True,exist_ok=True);receipt.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'url':output['url'],'primary':output['primary_format'],'latex_rendered':bool(render),'assets':len(assets),'files':len(files['entries']),'synthetic':True}))
def update_case(base,pid,receipt):
 """Revise the authored example through CAS APIs, retaining user files and manuscript."""
 if urllib.parse.urlparse(base).hostname not in {'localhost','127.0.0.1'}:raise ValueError('Use an explicitly local workbench instance.')
 state=json.load(urllib.request.urlopen(base+'/api/state'));csrf=state['csrf']
 project=next(p for p in state['projects'] if p['id']==pid)
 if project['metadata'].get('demo')!='scientific_egg_v1':raise ValueError('Not the scientific egg example.')
 def call(action,**fields):
  request=urllib.request.Request(base+'/api/action',json.dumps({'action':action,**fields},ensure_ascii=False).encode(),{'Content-Type':'application/json','X-CSRF-Token':csrf})
  try:body=json.load(urllib.request.urlopen(request,timeout=120))
  except urllib.error.HTTPError as e:raise RuntimeError(action+': '+e.read().decode()) from e
  if not body.get('ok'):raise RuntimeError(str(body))
  return body['result']
 objects=[o for o in state['objects'] if o['project_id']==pid and not o['archived']]
 questions={}
 for key,parent,order,title,old_title in QUESTIONS:
  matches=[o for o in objects if o['metadata'].get('research_role')=='research_question_v1' and
           (o['metadata'].get('demo_question_key')==key or o['title'] in (title,old_title))]
  if len(matches)!=1:raise ValueError('Cannot unambiguously identify example question '+key)
  questions[key]=matches[0]
 # Preserve the pre-edit versions so this editorial update remains reviewable/reversible.
 receipt.parent.mkdir(parents=True,exist_ok=True)
 before=receipt.with_name(receipt.stem+'-before.json')
 if before.exists():raise ValueError('Use a fresh receipt path; previous recovery snapshot is preserved.')
 before.write_text(json.dumps({'project':project,'objects':objects},ensure_ascii=False,indent=2)+'\n')
 revised={}
 for o in objects:
  if o['kind'] not in {'report','figure','dataset'} or not o['metadata'].get('synthetic'):continue
  content=o['content'];markdown=content.get('markdown')
  if not isinstance(markdown,str):continue
  clean=readable_copy(markdown);title=readable_copy(o['title'])
  if clean!=markdown or title!=o['title']:
   o=call('object.save',id=o['id'],expected_revision=o['revision'],title=title,content={**content,'markdown':clean})
  revised[o['id']]=o
 objects=[revised.get(o['id'],o) for o in objects]
 def source(key,label):
  figure={'fig2_joint':'图2','fig3_robustness':'图3','figS1_conditions':'补充图'}
  role={'data':'dataset','analysis':'analysis','run':'run_record','literature':'literature'}
  candidates=[o for o in objects if (key in figure and o['kind']=='figure' and o['title'].startswith(figure[key])) or
              (key=='data' and o['kind']=='dataset') or (key=='literature' and o['kind']=='literature') or
              (key not in ('data','literature') and key in role and o['metadata'].get('research_role')==role[key])]
  if len(candidates)!=1:raise ValueError('Cannot unambiguously identify source '+key)
  o=candidates[0]
  return '['+label+'](/?'+urllib.parse.urlencode({'project':pid,'object':o['id'],'revision':o['revision']})+')'
 case=build_case(source)
 for key,parent,order,title,old_title in QUESTIONS:
  q=questions[key]
  if q['metadata'].get('parent_question_id')!=(questions[parent]['id'] if parent else None):raise ValueError('Question hierarchy changed; inspect before updating.')
  if q['title']!=title or q['content'].get('qaec')!=case['questions'][key]:
   q=call('workbench.question.save',project_id=pid,id=q['id'],expected_revision=q['revision'],title=title,qaec=case['questions'][key],status=q['content']['research_status'],request_key=str(uuid.uuid4()))
  metadata={**q['metadata'],'demo_question_key':key,'workbench':{**q['metadata'].get('workbench',{}),'order':order}}
  if metadata!=q['metadata']:call('object.save',id=q['id'],expected_revision=q['revision'],metadata=metadata)
 project=call('workbench.research.read',project_id=pid)['project']
 if project['content'].get('description')!=case['description']:
  project=call('object.save',id=pid,expected_revision=project['revision'],content={**project['content'],'description':case['description']})
 if project['content'].get('background')!=case['background']:
  call('workbench.background.save',project_id=pid,expected_revision=project['revision'],background=case['background'],request_key=str(uuid.uuid4()))
 # The downloadable case must carry the revised publisher and reading copy too.
 bundle=package_case();raw=bundle.read_bytes();sha=hashlib.sha256(raw).hexdigest()
 guides=[o for o in objects if o['content'].get('input_assets',{}).get('reproduction_package')]
 if len(guides)!=1:raise ValueError('Cannot unambiguously identify the case download.')
 guide=guides[0];old_sha=guide['content']['input_assets']['reproduction_package']
 if old_sha!=sha:
  package=call('asset.import',project_id=pid,filename=bundle.name,base64=base64.b64encode(raw).decode(),provenance='synthetic',source='Scientific egg example: revised reading copy and publisher; original data and manuscript retained')
  content={**guide['content'],'markdown':guide['content']['markdown'].replace('/api/assets/'+old_sha,'/api/assets/'+package['sha']),
           'input_assets':{**guide['content']['input_assets'],'reproduction_package':package['sha']}}
  call('object.save',id=guide['id'],expected_revision=guide['revision'],content=content)
 final=call('workbench.research.read',project_id=pid)
 paper_before=next(o for o in objects if o['kind']=='paper')
 paper_after=call('document.read',project_id=pid)
 assert paper_after['revision']==paper_before['revision'],'Manuscript changed during editorial update; inspect separately.'
 result={'project_id':pid,'questions':[{'id':q['id'],'number':q.get('number'),'title':q['title']} for q in final['questions']],
         'paper_revision':paper_after['revision'],'paper_unchanged':True,'user_notes_untouched':True,'before_snapshot':str(before)}
 receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--base-url',default='http://127.0.0.1:8924');p.add_argument('--receipt',type=Path,default=ROOT.parents[1]/'.private/egg-showcase/publish.json');p.add_argument('--update-project',help='Revise an existing egg case; retain its paper and notes.');args=p.parse_args()
 if args.update_project:update_case(args.base_url.rstrip('/'),args.update_project,args.receipt)
 else:publish(args.base_url.rstrip('/'),args.receipt)
