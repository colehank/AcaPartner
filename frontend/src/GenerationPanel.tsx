import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {command,requestId} from './api';
import {Session} from './session';
import {GenerationFlow} from './GenerationFlow';
import {DatasetMembership} from './DatasetMembership';
import {GenerationResultErrors} from './GenerationResultErrors';
import {SourceImpactPanel} from './SourceImpactPanel';

const staleAction=Symbol('generation action scope changed');
const emptyCatalog={datasets:[],recipes:[],runs:[]};
const canonical=(value:any):any=>Array.isArray(value)?value.map(canonical):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])])):value;
const stableIdentity=(value:any)=>JSON.stringify(canonical(value));
function targetSet(refs:any):{id:string,revision:number}[]|undefined{
  if(!Array.isArray(refs)||refs.length<1||refs.length>8)return;
  const ids=new Set<string>();
  for(const ref of refs){
    if(!ref||typeof ref!=='object'||Array.isArray(ref)||Object.keys(ref).sort().join(',')!=='id,revision'||typeof ref.id!=='string'||!ref.id||!Number.isInteger(ref.revision)||ref.revision<1||ids.has(ref.id))return;
    ids.add(ref.id);
  }
  return refs.map(ref=>({id:ref.id,revision:ref.revision})).sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0);
}
type ActionContext={check:()=>void,call:(action:string,payload:any,extra?:any)=>Promise<any>,command:(action:string,fields:any)=>Promise<any>,wait:<T>(operation:()=>Promise<T>)=>Promise<T>,fixedPlan:(value:any,targets:any[],resumeRun?:string)=>void};

export function GenerationBody({session:s,report,initialRun}:{session:Session,report:(e:unknown)=>void,initialRun?:string}){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const [impactOpen,setImpactOpen]=useState(false);
  const [catalogReceipt,setCatalogReceipt]=useState<any>(null),[busySequence,setBusySequence]=useState<number|null>(null);
  const catalog=catalogReceipt?.session===s&&catalogReceipt?.projectId===s.project.id?catalogReceipt.value:emptyCatalog;
  const [title,setTitle]=useState(''),[asset,setAsset]=useState(''),[columns,setColumns]=useState('[]'),[identity,setIdentity]=useState('[]'),[units,setUnits]=useState('{}');
  const [scriptAsset,setScriptAsset]=useState(''),[filename,setFilename]=useState(''),[sourceReceipt,setSourceReceipt]=useState<any>(null),[code,setCode]=useState('');
  const source=sourceReceipt?.session===s&&sourceReceipt?.projectId===s.project.id&&sourceReceipt?.filename===filename?sourceReceipt.value:null;
  const setSource=(value:any)=>setSourceReceipt({session:s,projectId:s.project.id,filename,value});
  const [recipe,setRecipe]=useState(''),[recipeTitle,setRecipeTitle]=useState(''),[steps,setSteps]=useState('[]'),[fixedPlan,setFixedPlan]=useState<any>(null),[run,setRun]=useState(initialRun||''),[readActual,setActual]=useState<any>(null);
  const [parameterDrafts,setParameterDrafts]=useState<Record<string,string>>({});
  const hasParameterDrafts=Object.keys(parameterDrafts).length>0;
  const [recipeBaseRef,setRecipeBaseRef]=useState<{id:string,revision:number}|null>(null);
  const actual=readActual?.run?.id===run&&readActual?.run?.project_id===s.project.id?readActual:null;
  const readContext=useRef({s,projectId:s.project.id,run,sequence:0,live:true});
  readContext.current.s=s;readContext.current.projectId=s.project.id;readContext.current.run=run;
  const [tab,setTabState]=useState(()=>['run','data','script','recipe'].includes(s.views['generation-panel-ui']?.tab)?s.views['generation-panel-ui'].tab:'run'),[sourceMode,setSourceMode]=useState('actual');
  const setTab=(value:string)=>{setTabState(value);s.position('generation-panel-ui',{tab:value});};
  useEffect(()=>{if(initialRun){setRun(initialRun);setSourceMode('actual');}},[initialRun]);
  const [additionalTargets,setAdditionalTargets]=useState<string[]>([]),[joinedMessage,setJoinedMessage]=useState('');
  const current=catalog.recipes.find((r:any)=>r.id===recipe);
  let recipeDirty=false;try{recipeDirty=!!current&&(hasParameterDrafts||recipeTitle!==current.title||stableIdentity(JSON.parse(steps))!==stableIdentity(current.content.steps));}catch{recipeDirty=!!current;}
  const recipeBaseChanged=!!current&&!!recipeBaseRef&&recipeBaseRef.id===current.id&&recipeBaseRef.revision!==current.revision;
  const targetHeads=[recipe,...additionalTargets].filter(Boolean).map(id=>({id,revision:catalog.recipes.find((r:any)=>r.id===id)?.revision??null}));
  // Render-time identity checks also fence the frame before effects run. The
  // selected saved revisions and local edit bytes are independent identities.
  const scopeKey=stableIdentity({project_id:s.project.id,targetHeads,recipeBaseRef,recipeTitle,steps,parameterDrafts,run,
    title,asset,columns,identity,units,scriptAsset,filename,code,source:source&&{relative_path:source.relative_path,sha256:source.sha256}});
  const actionScope=useRef({s,projectId:s.project.id,key:scopeKey,epoch:0,sequence:0,live:true});
  if(actionScope.current.s!==s||actionScope.current.projectId!==s.project.id||actionScope.current.key!==scopeKey){
    actionScope.current.s=s;actionScope.current.projectId=s.project.id;actionScope.current.key=scopeKey;++actionScope.current.epoch;++actionScope.current.sequence;
  }
  const busy=busySequence!==null&&busySequence===actionScope.current.sequence&&actionScope.current.live;
  const plan=fixedPlan?.session===s&&fixedPlan?.scopeKey===scopeKey&&fixedPlan?.epoch===actionScope.current.epoch?fixedPlan.value:null;
  const setPlan=(value:null)=>setFixedPlan(value);
  useEffect(()=>{actionScope.current.live=true;return()=>{actionScope.current.live=false;++actionScope.current.sequence;};},[s,s.project.id]);
  const call=(action:string,payload:any,extra:any={})=>command(action,{project_id:s.project.id,request_id:requestId(),payload,...extra});
  const load=async()=>{
    const sequence=++readContext.current.sequence,projectId=s.project.id;
    const current=()=>readContext.current.live&&readContext.current.s===s&&s.project.id===projectId&&readContext.current.projectId===projectId&&readContext.current.run===run&&readContext.current.sequence===sequence;
    try{
      const c=await command('desk.datasets.list',{project_id:s.project.id});if(!current())return;
      const a=run?await call('build.status',{run_id:run}):null;if(!current())return;
      if(a&&(a.run?.id!==run||a.run?.project_id!==s.project.id))throw new Error('实际生成回报与当前项目或运行不一致。');
      setCatalogReceipt({session:s,projectId,value:c});setActual(a);
    }catch(error){if(current())throw error;}
  };
  useEffect(()=>{readContext.current.live=true;const timer=setInterval(()=>load().catch(report),1800);load().catch(report);return()=>{readContext.current.live=false;++readContext.current.sequence;clearInterval(timer);};},[s,s.project.id,run]);
  const act=async(fn:(context:ActionContext)=>Promise<void>)=>{
    const sequence=++actionScope.current.sequence,epoch=actionScope.current.epoch,projectId=s.project.id;setBusySequence(sequence);
    const active=()=>actionScope.current.live&&actionScope.current.s===s&&s.project.id===projectId&&actionScope.current.projectId===projectId&&actionScope.current.key===scopeKey&&actionScope.current.epoch===epoch&&actionScope.current.sequence===sequence;
    const check=()=>{if(!active())throw staleAction;};
    const wait=async<T,>(operation:()=>Promise<T>)=>{check();const value=await operation();check();return value;};
    const context:ActionContext={check,wait,call:(action,payload,extra={})=>wait(()=>call(action,payload,extra)),command:(action,fields)=>wait(()=>command(action,fields)),
      fixedPlan:(value,targets,resumeRun)=>{
        check();const refs=value?.recipe_refs||[value?.recipe_ref];
        const actualTargets=targetSet(refs),requestedTargets=targetSet(targets);
        if(value?.project_id!==projectId||!actualTargets||!requestedTargets||stableIdentity(actualTargets)!==stableIdentity(requestedTargets)||!Array.isArray(value?.nodes)||typeof value?.plan_hash!=='string'||(resumeRun&&value?.resume_from?.run_id!==resumeRun))throw new Error('固定计划回报与本次项目、配方修订或检查点不一致。');
        setFixedPlan({value,session:s,scopeKey,epoch});
      }};
    try{await fn(context);if(active())await wait(load);}catch(error){if(error!==staleAction&&active())report(error);}
    finally{if(active())setBusySequence(null);}
  };
  const selectRecipe=(id:string)=>{if(hasParameterDrafts){report(new Error('所选步骤仍有未应用参数。请回到生成配方更新参数，或明确撤销该步骤草稿，再切换配方。'));return;}const r=catalog.recipes.find((x:any)=>x.id===id);setRecipe(id);setRecipeBaseRef(r?{id:r.id,revision:r.revision}:null);setRecipeTitle(r?.title||'');setSteps(JSON.stringify(r?.content.steps||[],null,2));setPlan(null);setAdditionalTargets([]);setJoinedMessage('');};
  const makePlan=()=>act(async context=>{if(!current||recipeDirty||recipeBaseChanged)throw new Error('请先比较保存版变化并保存当前配方的参数、数据引用与名称。');const targets=[current,...additionalTargets.map(id=>catalog.recipes.find((r:any)=>r.id===id))];if(targets.some(r=>!r))throw new Error('共同目标已改变，请重新选择。');const refs=targets.map(r=>({id:r.id,revision:r.revision}));context.fixedPlan(await context.call('build.plan',{target_refs:refs,constraints:{timeout_seconds:180}}),refs);setSourceMode('planned');setJoinedMessage('');});
  const saveRecipe=()=>act(async context=>{
    if(hasParameterDrafts)throw new Error('请先更新或撤销所选步骤参数草稿，再保存配方定义。');
    const baseline=recipeBaseRef?.id===recipe?recipeBaseRef:undefined;
    if(recipe&&!baseline)throw new Error('配方草稿缺少固定修订基线，请重新读取已保存定义。');
    const r=await context.call('recipe.propose',{title:recipeTitle,steps:JSON.parse(steps)},baseline?{object_id:baseline.id,expected_revision:baseline.revision}:{});
    setRecipe(r.id);setRecipeBaseRef({id:r.id,revision:r.revision});setPlan(null);
    // This is the actual save receipt, not an inferred head or optimistic edit.
    setCatalogReceipt({session:s,projectId:s.project.id,value:{...catalog,recipes:catalog.recipes.some((item:any)=>item.id===r.id)?catalog.recipes.map((item:any)=>item.id===r.id?r:item):[r,...catalog.recipes]}});
  });
  let parsed:any[]=[],parseError='';try{parsed=JSON.parse(steps);if(!Array.isArray(parsed)||parsed.some(n=>!n||typeof n.id!=='string'||!n.inputs||!n.io?.inputs||!n.io?.outputs||Object.values(n.inputs).some((r:any)=>!r||typeof r!=='object'||!(r.dataset_id||r.node_id)))||new Set(parsed.map(n=>n.id)).size!==parsed.length)throw new Error('尚未具备可显示的步骤、输入或输出。');}catch(e){parseError=String(e);parsed=[];}
  const flow=(nodes:any[],key:string,mode:'definition'|'planned'|'actual',edit?:boolean)=><GenerationFlow steps={nodes} datasets={catalog.datasets} positions={s.generationLayouts[key]||{}} mode={mode} plan={mode==='planned'?plan:mode==='actual'?actual?.run?.payload?.generation_plan:undefined} actual={mode==='actual'?actual:undefined} report={report} onChange={edit?next=>{setSteps(JSON.stringify(next,null,2));setPlan(null);}:undefined}
    parameterDrafts={edit?parameterDrafts:undefined}
    onParameterDraft={edit?(id,text)=>{const original=nodes.find(n=>n.id===id);setParameterDrafts(previous=>{const next={...previous};if(text===JSON.stringify(original?.parameters||{},null,2))delete next[id];else next[id]=text;return next;});setPlan(null);}:undefined}
    onParameterCommit={edit?(id,parameters)=>{if(!nodes.some(step=>step.id===id)){report(new Error('步骤已改变，保留参数草稿并重新核对定义。'));return;}setSteps(JSON.stringify(nodes.map(step=>step.id===id?{...step,parameters,config_keys:Object.keys(parameters)}:step),null,2));setParameterDrafts(previous=>{const next={...previous};delete next[id];return next;});setPlan(null);}:undefined}
    onParameterDiscard={edit?id=>{setParameterDrafts(previous=>{const next={...previous};delete next[id];return next;});setPlan(null);}:undefined} onPositions={p=>{s.generationLayouts[key]=p;s.notify();if(s.layout)void s.saveLayout(s.layout);}}/>;
  return <section className="generation-panel" aria-label="数据与受管生成" aria-busy={busy}><h2>数据与受管生成</h2><button onClick={()=>setImpactOpen(true)}>查看采用位置 / 来源变化影响</button>{impactOpen&&<SourceImpactPanel session={s} initialSource={run?{kind:'run',id:run}:undefined} onClose={()=>setImpactOpen(false)}/>}<div className="panel-tools">{[['run','计划 / 运行'],['data','数据身份'],['script','实际代码'],['recipe','生成配方']].map(([id,label])=><button key={id} aria-pressed={tab===id} onClick={()=>setTab(id)}>{label}</button>)}</div>{hasParameterDrafts&&<p role="status">步骤参数草稿尚未应用。回到生成配方选中原步骤，更新或撤销参数后才能保存或固定计划。</p>}{recipeDirty&&<p role="status">当前配方的参数、数据引用或名称尚未保存。保存定义后再固定新计划；历史运行保留原来源。</p>}{recipeBaseChanged&&<details><summary>比较配方保存版与原基线草稿</summary><p>草稿仍基于 r{recipeBaseRef?.revision}；保存版已为 r{current.revision}。未自动改用最新修订覆盖保存。</p><pre aria-label="当前保存配方定义">{JSON.stringify({title:current.title,steps:current.content.steps},null,2)}</pre><pre aria-label="当前本地配方草稿">{JSON.stringify({title:recipeTitle,steps:parseError?steps:parsed},null,2)}</pre><button type="button" onClick={()=>{setRecipeBaseRef({id:current.id,revision:current.revision});setPlan(null);}}>比较后将草稿基线设为当前修订</button></details>}
    {tab==='data'&&<><h3>登记数据快照</h3><label>快照名称<input aria-label="数据快照名称" value={title} onChange={e=>setTitle(e.target.value)}/></label><label>已上传 CSV<select aria-label="数据快照文件" value={asset} onChange={e=>setAsset(e.target.value)}><option value="">选择真实文件</option>{s.assets.filter(a=>a.filename.endsWith('.csv')).map(a=><option key={a.sha} value={a.sha}>{a.filename}</option>)}</select></label><label>字段及实际顺序<textarea aria-label="数据字段顺序" placeholder={'["sample_id","value"]'} value={columns} onChange={e=>setColumns(e.target.value)}/></label><label>身份字段<textarea aria-label="数据身份字段" placeholder={'["sample_id"]'} value={identity} onChange={e=>setIdentity(e.target.value)}/></label><label>输入说明中的单位<textarea aria-label="数据单位声明" placeholder={'{"value":"declared unit"}'} value={units} onChange={e=>setUnits(e.target.value)}/></label><p>身份必须来自实际输入；不推测样本对应关系或单位。当前支持 UTF-8 CSV，其他格式保留未支持状态。</p><button disabled={busy||!title||!asset} onClick={()=>act(async context=>{await context.call('dataset.snapshot',{title,asset_sha256:asset,contract:{format:'csv',columns:JSON.parse(columns),identity_fields:JSON.parse(identity),units:JSON.parse(units)}});})}>登记固定快照</button>{catalog.datasets.map((d:any)=><details key={d.id}><summary>{d.title} · {d.content?.authority_kind==='immutable_member_manifest'?(Number.isSafeInteger(d.content?.snapshot?.member_manifest?.count)?d.content.snapshot.member_manifest.count+' 个成员':'成员数量未核定'):(Number.isSafeInteger(d.content?.snapshot?.row_count)?d.content.snapshot.row_count+' 行':'尚未登记成员快照')} · r{d.revision}</summary><pre>{JSON.stringify(d,null,2)}</pre></details>)}</>}
    {tab==='script'&&<><h3>原生项目脚本</h3><label>已上传 Python 文件<select aria-label="计算脚本素材" value={scriptAsset} onChange={e=>setScriptAsset(e.target.value)}><option value="">选择文件</option>{s.assets.filter(a=>a.filename.endsWith('.py')).map(a=><option key={a.sha} value={a.sha}>{a.filename}</option>)}</select></label><label>scripts 下文件名<input aria-label="原生计算脚本文件名" value={filename} onChange={e=>setFilename(e.target.value)} placeholder="analysis.py"/></label><button disabled={busy||!scriptAsset||!filename} onClick={()=>act(async context=>{const x=await context.call('recipe.script.import',{asset_sha256:scriptAsset,filename});setSource(x);setCode(x.code);})}>登记为项目脚本</button><button disabled={busy||!filename} onClick={()=>act(async context=>{const x=await context.call('recipe.script.read',{filename});setSource(x);setCode(x.code);})}>读取实际文件</button>{source&&<><p>{source.relative_path} · {source.sha256} · 查看不执行</p><textarea className="script-source" aria-label="计算脚本源码" value={code} onChange={e=>setCode(e.target.value)}/><button disabled={busy||code===source.code} onClick={()=>act(async context=>{const x=await context.call('recipe.script.write',{filename,expected_sha256:source.sha256,code});setSource(x);setPlan(null);})}>保存脚本文件</button></>}<p>受管步骤提供 build_step(inputs, parameters, output_dir)，写出声明的 CSV。登记、阅读、保存均不执行。</p></>}
    {tab==='data'&&<DatasetMembership session={s} datasets={catalog.datasets} reload={load} report={report}/>}
    {tab==='recipe'&&<><h3>待执行定义</h3><label>配方<select aria-label="待执行配方" value={recipe} onChange={e=>selectRecipe(e.target.value)}><option value="">新配方</option>{catalog.recipes.map((r:any)=><option key={r.id} value={r.id}>{r.title} · r{r.revision}</option>)}</select></label><label>配方名称<input aria-label="配方名称" value={recipeTitle} onChange={e=>setRecipeTitle(e.target.value)}/></label>{parseError?<p role="status">{parseError}</p>:flow(parsed,recipe||'draft','definition',true)}<label>代码步骤及 I/O 合同<textarea className="recipe-source" aria-label="生成步骤定义" disabled={hasParameterDrafts} value={steps} onChange={e=>setSteps(e.target.value)}/></label><p>每一步声明 id、role、script、parameters、config_keys、deterministic、inputs 和 io。数据用 dataset_id/revision 引用；上游用 node_id/output 引用。保存定义不会运行或改变历史结果。</p><button disabled={busy||!recipeTitle||hasParameterDrafts} onClick={saveRecipe}>保存配方定义</button><button disabled={busy||!current||recipeDirty||recipeBaseChanged} onClick={makePlan}>固定变化计划</button></>}
    {tab==='run'&&<><label>目标配方<select aria-label="生成目标配方" value={recipe} onChange={e=>selectRecipe(e.target.value)}><option value="">选择已保存定义</option>{catalog.recipes.map((r:any)=><option key={r.id} value={r.id}>{r.title} · r{r.revision}</option>)}</select></label>{current&&catalog.recipes.length>1&&<fieldset aria-label="共同计算目标"><legend>一并计算的成果配方</legend>{catalog.recipes.filter((r:any)=>r.id!==current.id).map((r:any)=><label key={r.id}><input type="checkbox" disabled={busy} checked={additionalTargets.includes(r.id)} onChange={e=>{setAdditionalTargets(ids=>e.target.checked?[...ids,r.id]:ids.filter(id=>id!==r.id));setPlan(null);setJoinedMessage('');}}/>{r.title} · r{r.revision}</label>)}<p>声明确定性且代码、输入、参数和合同完全相同的步骤共享执行。各成果保留自己的来源。</p></fieldset>}<button disabled={busy||!current||recipeDirty||recipeBaseChanged} onClick={makePlan}>核对输入并固定计划</button><div className="panel-tools"><button aria-pressed={sourceMode==='actual'} onClick={()=>setSourceMode('actual')}>实际运行来源</button><button aria-pressed={sourceMode==='planned'} onClick={()=>setSourceMode('planned')}>待执行定义 / 计划</button></div>
      {sourceMode==='planned'&&plan&&<><p>固定计划：{plan.plan_hash}</p><p>变化影响：{plan.changed.join(' → ')||'无新变化'}</p><p>实际待跑：{plan.pending.join('、')||'无'}；核验复用：{plan.reused.join('、')||'无'}</p>{plan.target_mappings&&<details open><summary>共同计算来源 · {plan.target_mappings.length} 个成果配方，{plan.nodes.length} 个计算步骤</summary>{plan.target_mappings.map((t:any)=><p key={t.recipe_ref.id}>{t.title} · r{t.recipe_ref.revision}：{Object.entries(t.nodes).map(([local,physical])=>local+' → '+physical).join('；')}</p>)}</details>}<p>{plan.environment.snakemake_sha256?'Snakemake 入口已识别；启动仍核对权限、输入和实际 job 集合。':'Snakemake 尚未就绪，计算未启动。'}</p>{plan.nodes.map((n:any)=><details key={n.id}><summary>{n.id} · {n.role} · {n.reuse?'核验复用':'待执行'}</summary><p>实际配置键：{n.config_keys.join('、')}</p><pre>{JSON.stringify({script:n.script_snapshot,inputs:n.bound_inputs,outputs:n.io.outputs,parameters:n.parameters,logical_sources:n.logical_sources,environment:n.environment},null,2)}</pre></details>)}<p>执行使用当前账号本地权限；当前不是操作系统安全沙箱。请核对实际代码和范围。</p><button disabled={busy||!plan.environment.snakemake_sha256} onClick={()=>act(async context=>{const grant=await context.call('build.authorize',{plan_hash:plan.plan_hash,approved:true});const x=await context.call('build.start',{plan_hash:plan.plan_hash,authorization_ref:grant.authorization_ref});setRun(x.run_id);setJoinedMessage(x.shared_existing_run?'已接入同一固定计划的运行，没有重复提交计算。':'');setSourceMode('actual');})}>授权并启动此固定计划</button></>}
      {joinedMessage&&<p role="status">{joinedMessage}</p>}
      <label>已有运行<select aria-label="生成历史运行" value={run} onChange={e=>setRun(e.target.value)}><option value="">选择实际运行</option>{catalog.runs.map((r:any)=><option key={r.id} value={r.id}>{r.status} · {r.id}</option>)}</select></label>
      {sourceMode==='planned'&&plan&&flow(plan.nodes,'plan:'+plan.plan_hash,'planned')}
      {sourceMode==='actual'&&actual&&flow(actual.run.payload.generation_plan.nodes,'run:'+actual.run.id,'actual')}
      {sourceMode==='actual'&&actual&&<GenerationResultErrors projectId={s.project.id} runId={actual.run.id} command={command} onChanged={()=>{void load().catch(report);}}/>}
      {sourceMode==='actual'&&actual?.run.result?.target_results&&<details open><summary>各成果的实际共享来源</summary>{actual.run.result.target_results.map((t:any)=><div key={t.recipe_ref.id}><p>{t.recipe_ref.id} · r{t.recipe_ref.revision}</p>{Object.entries(t.nodes).map(([local,result]:any)=><p key={local}>{local} → {result.physical_node_id} · 运行 {result.run_id}</p>)}</div>)}</details>}
      {sourceMode==='actual'&&actual&&<><h3>{actual.run.status} · {actual.run.id}</h3><p role="status">{actual.run.error}</p>{['queued','running','waiting_input','waiting_resource','waiting_authorization'].includes(actual.run.status)&&<div className="panel-tools"><button disabled={busy} onClick={()=>act(async context=>{await context.call('build.control',{run_id:run,operation:'pause'});})}>暂停计算</button><button disabled={busy} onClick={()=>act(async context=>{await context.call('build.control',{run_id:run,operation:'cancel'});})}>取消计算</button></div>}{['paused','failed','cancelled'].includes(actual.run.status)&&<><p>已核验完成步骤：{Object.keys(actual.checkpoint?.nodes||{}).join('、')||'无'}。保留原输入、代码与剩余额度；接续需要新计划和新授权。</p><button disabled={busy||!actual.can_resume_checkpoint} onClick={()=>act(async context=>{const refs=actual.run.payload.generation_plan.recipe_refs||[actual.run.payload.generation_plan.recipe_ref];context.fixedPlan(await context.call('build.plan',{target_refs:refs,constraints:{resume_run_id:actual.run.id}}),refs,actual.run.id);setSourceMode('planned');})}>从原检查点固定剩余计划</button>{actual.resume_successor_id&&<p>此运行已有后续接续。<button disabled={busy} onClick={()=>setRun(actual.resume_successor_id)}>查看后续运行</button></p>}</>}<p>本运行固定 plan_hash：{actual.run.payload.generation_plan.plan_hash}</p><p>采用状态：{actual.run.result.adoption||'尚无可采用产出'}；科学批准：{String(actual.run.result.scientific_approval||false)}</p>{actual.run.payload.generation_plan.nodes.map((n:any)=><details key={n.id}><summary>{n.id} · {n.role} · {actual.run.result.nodes?.[n.id]?'已有核验输出':actual.checkpoint?.nodes?.[n.id]?'步骤完成，整轮未完成':'尚无核验输出'}</summary><p>产生此结果的代码与配置，不随待执行定义变化：</p><pre>{n.script_snapshot.code}</pre><pre>{JSON.stringify({inputs:n.bound_inputs,parameters:n.parameters,io:n.io,result:actual.run.result.nodes?.[n.id]||actual.checkpoint?.nodes?.[n.id]},null,2)}</pre>{Object.entries((actual.run.result.nodes?.[n.id]||actual.checkpoint?.nodes?.[n.id])?.outputs||{}).map(([name,out]:any)=><a key={name} href={'/api/assets/'+out.asset_sha256} target="_blank" rel="noreferrer">{name}</a>)}</details>)}<button disabled={busy||actual.run.status!=='generated'} onClick={()=>act(async context=>{await context.command('desk.task.brief',{project_id:s.project.id,task_id:run});await context.wait(()=>s.refresh());})}>将计算回报记入项目笔记</button></>}
    </>}
  </section>;
}
