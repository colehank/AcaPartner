import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {command,CommandError,readTask,requestId} from './api';
import type {Session} from './session';
import {TaskAuthority} from './TaskAuthority';
import {LiteratureFulltextInput} from './LiteratureFulltextInput';

type Ref={id:string,revision:number};
type Material=Ref&{sha256:string,title:string,kind:string,reason:string,bytes:number,current_revision:number,current_sha256:string,required:boolean,selected:boolean};
type Resolution={status:'ready'|'needs_selection',project:(Ref&{sha256:string,title:string})|null,materials:Material[],
  ambiguities:{kind:string,label:string,candidates:string[]}[],excluded:{id:string,revision:number,reason:string}[],gaps:string[],
  limits:{max_materials:number,max_bytes:number},pin:any,selected_bytes?:number};
export type ResearchCommissionProvider={id:string,route:string,model?:string,available?:boolean,authorized:boolean};
export type ResearchCommissionTaskRef={id:string,project_id:string};
type Props={session:Session,runtime:{running?:boolean}|null,providers:ResearchCommissionProvider[],
  onOpenTask:(ref:ResearchCommissionTaskRef)=>Promise<void>|void,
  onOpenReference?:(ref:{id:string,revision:number,consumer_id:string})=>Promise<void>|void,report:(error:unknown)=>void};
type Form={request:string,additional:string,background:string,constraints:string,acceptance:string,unresolved:string,
  output:'report'|'note',provider:string,calls:string,seconds:string};
type Preview={signature:string,value:Resolution,selection:string[],verified:boolean};
type Draft={form:Form,preview:Preview|null,busy:'resolve'|'submit'|'read'|null,message:string,
  consent:string,emptyConsent:string,accepted:{task:any,read:boolean}|null,uncertain:string,
  attempt:{signature:string,key:string}|null};
type Memory={project:string,value:Draft,version:number,listeners:Set<()=>void>,set:(patch:Partial<Draft>)=>void,
  subscribe:(listener:()=>void)=>()=>void,snapshot:()=>number};
// Closing a dock is not evidence that an already sent commission was rejected.
// Keep its form and request identity for the lifetime of this same Session.
const drafts=new WeakMap<Session,Map<string,Memory>>();
function commissionMemory(session:Session):Memory {
  let projects=drafts.get(session);if(!projects){projects=new Map();drafts.set(session,projects);}
  const existing=projects.get(session.project.id);if(existing)return existing;
  const memory:Memory={project:session.project.id,value:{form:initial(),preview:null,busy:null,message:'',consent:'',emptyConsent:'',accepted:null,uncertain:'',attempt:null},
    version:0,listeners:new Set(),set(patch){memory.value={...memory.value,...patch};memory.version++;for(const listener of memory.listeners)listener();},
    subscribe(listener){memory.listeners.add(listener);return()=>{memory.listeners.delete(listener);};},snapshot:()=>memory.version};
  projects.set(session.project.id,memory);return memory;
}
const initial=():Form=>({request:'',additional:'',background:'',
  constraints:'读取采用的保存材料，保留来源和不确定性；不改原始数据，不启动新拟合或未经授权的服务。',
  acceptance:'形成可编辑成果，说明问题、证据、限制和下一步，进入审阅；不以模型返回代替验收。',
  unresolved:'',output:'report',provider:'',calls:'1',seconds:'300'});
const sha=(x:any)=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
const ident=(x:any)=>typeof x==='string'&&x.length>0&&x.length<=200&&!/[\s/\\\u0000-\u001f]/u.test(x);
function providerProblem(provider:ResearchCommissionProvider){
  if(!ident(provider.id)||!['codex','deepseek_harness'].includes(provider.route))return '不支持的路线';
  if(provider.authorized!==true)return '未授权';
  // desk.review.read provides configured identity and authorization, not a
  // connection probe. Hosts may additionally supply an explicit veto.
  if(provider.available===false)return '当前不可用';
  if(provider.available!==undefined&&provider.available!==true)return '配置状态无效';
  return '';
}
const positive=(x:any)=>Number.isSafeInteger(x)&&x>0;
const refKey=(x:Ref)=>x.id+'@'+x.revision;
const errorText=(e:unknown)=>e instanceof Error?e.message:String(e);
const clone=<T,>(x:T):T=>structuredClone(x);
const sameMaterials=(actual:any,expected:any)=>Array.isArray(actual)&&Array.isArray(expected)&&actual.length===expected.length&&
  expected.every((m:any)=>actual.some((x:any)=>x?.id===m.id&&x.revision===m.revision&&x.sha256===m.sha256));
// Runtime may append execution fields; only the original commission contract is immutable.
function sameCommission(actual:any,expected:any){
  return actual?.kind==='research'&&actual.target_id===null&&actual.base_revision===null&&
    actual.request===expected.request&&actual.provider_id===expected.provider_id&&
    actual.budget?.max_model_calls===expected.budget?.max_model_calls&&
    actual.budget?.timeout_seconds===expected.budget?.timeout_seconds&&
    sameMaterials(actual.context?.materials,expected.context?.materials)&&
    ['output','additional_background','constraints','acceptance'].every(key=>actual.context?.[key]===expected.context?.[key])&&
    JSON.stringify(actual.context?.unresolved)===JSON.stringify(expected.context?.unresolved);
}

function additionalRefs(text:string):Ref[]|{id:string}[]{
  return text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean).map(line=>{
    const match=/^([^@]+)(?:@([1-9]\d*))?$/.exec(line),revision=match?.[2]?Number(match[2]):undefined;
    if(!match||!ident(match[1])||revision!==undefined&&!positive(revision))throw new Error('补充来源请每行填写一个已登记成果 ID，可附 @正整数修订号。');
    return revision===undefined?{id:match[1]}:{id:match[1],revision};
  });
}
function resourceBudget(form:Form){
  const calls=Number(form.calls),seconds=Number(form.seconds);
  return /^\d+$/.test(form.calls)&&/^\d+$/.test(form.seconds)&&Number.isSafeInteger(calls)&&calls>=1&&calls<=100&&
    Number.isSafeInteger(seconds)&&seconds>=1&&seconds<=900?{max_model_calls:calls,timeout_seconds:seconds}:null;
}
function checkedResolution(value:any,project:string):Resolution {
  const bad=()=>{throw new Error('材料预览身份或结构不完整；请重新核对，未开放提交。');};
  if(!value||!['ready','needs_selection'].includes(value.status)||!Array.isArray(value.materials)||
    !Array.isArray(value.ambiguities)||!Array.isArray(value.excluded)||!Array.isArray(value.gaps)||value.gaps.some((x:any)=>typeof x!=='string')||
    !positive(value.limits?.max_materials)||!positive(value.limits?.max_bytes))bad();
  if(value.project&&(value.project.id!==project||!positive(value.project.revision)||!sha(value.project.sha256)||typeof value.project.title!=='string'))bad();
  if(value.status==='ready'&&(!value.project||value.ambiguities.length))bad();
  if(value.project&&(!value.pin||value.pin.version!==1||!sha(value.pin.request_sha256)||!sha(value.pin.context_sha256)||!sha(value.pin.catalog_sha256)||
    value.pin.project?.id!==project||value.pin.project.revision!==value.project.revision||value.pin.project.sha256!==value.project.sha256))bad();
  const seen=new Set<string>();
  for(const m of value.materials){
    if(!ident(m?.id)||!positive(m.revision)||!sha(m.sha256)||!positive(m.current_revision)||!sha(m.current_sha256)||
      !Number.isSafeInteger(m.bytes)||m.bytes<0||typeof m.title!=='string'||typeof m.kind!=='string'||typeof m.reason!=='string'||
      typeof m.selected!=='boolean'||typeof m.required!=='boolean'||seen.has(refKey(m)))bad();
    seen.add(refKey(m));
  }
  if(value.ambiguities.some((x:any)=>typeof x?.label!=='string'||typeof x.kind!=='string'||!Array.isArray(x.candidates))||
    value.excluded.some((x:any)=>typeof x?.id!=='string'||!positive(x.revision)||typeof x.reason!=='string'))bad();
  return clone(value);
}

/** Resolve saved evidence first; one explicit confirmation may enqueue a new research task. */
export function ResearchCommissionPanel({session:s,runtime,providers,onOpenTask,onOpenReference,report}:Props){
  const [fulltextOpen,setFulltextOpen]=useState(false);
  useSyncExternalStore(s.subscribe,s.snapshot);
  const memory=commissionMemory(s);useSyncExternalStore(memory.subscribe,memory.snapshot);
  const currentMemory=useRef(memory),live=useRef(true);currentMemory.current=memory;
  const {form,preview:plan,busy,message,consent,emptyConsent,accepted,uncertain:unknown}=memory.value;
  const submitted=accepted?.task;
  const sourceSignature=(f:Form)=>JSON.stringify([memory.project,f.request,f.additional]);
  useEffect(()=>{live.current=true;return()=>{live.current=false;};},[memory]);
  const update=(name:keyof Form,value:string)=>memory.set({form:{...form,[name]:value},consent:'',message:'',
    ...(name==='request'||name==='additional'?{preview:null,emptyConsent:''}:{})});
  const selected=plan?plan.value.materials.filter(m=>plan.selection.includes(refKey(m))):[];
  const provider=providers.find(p=>p.id===form.provider),budget=resourceBudget(form);
  const available=runtime?.running===true&&!!provider&&!providerProblem(provider);
  const sourceCurrent=!!plan&&plan.signature===sourceSignature(form)&&plan.verified&&plan.value.status==='ready'&&plan.value.project?.id===memory.project;
  const confirmation=JSON.stringify([memory.project,form,plan?.value.pin,selected.map(refKey),provider,runtime?.running]);
  const emptyConfirmed=selected.length>0||emptyConsent===confirmation;
  const ready=sourceCurrent&&available&&!!budget&&emptyConfirmed&&consent===confirmation;
  const dirty=!!s.paperDraft?.dirty||[...s.buffers.values()].some(b=>b.dirty)||Object.keys(s.figureDrafts).length>0||
    Object.keys(s.compositionDrafts).length>0||Object.keys(s.captionDrafts).length>0;
  const requestFields=(f:Form)=>({request:f.request,material_mode:'auto',project_id:memory.project,selected_project_id:memory.project,
    additional_materials:additionalRefs(f.additional),literature_plan:false});
  const resolve=async()=>{
    if(memory.value.busy||submitted||unknown)return;
    const origin=memory,f=clone(form),signature=sourceSignature(f),current=()=>live.current&&currentMemory.current===origin;
    origin.set({busy:'resolve',message:'',consent:'',emptyConsent:''});
    try{
      if(!f.request.trim())throw new Error('请填写研究目的。');
      const fields=requestFields(f),selection=plan&&plan.signature===signature?selected.map(({id,revision})=>({id,revision})):undefined;
      const value=await command('task.resolve',{...fields,...(selection===undefined?{}:{selected_materials:selection})});
      if(sourceSignature(origin.value.form)!==signature)return;
      const checked=checkedResolution(value,origin.project);
      origin.set({preview:{signature,value:checked,selection:checked.materials.filter(m=>m.selected).map(refKey),verified:true}});
    }catch(error){if(sourceSignature(origin.value.form)===signature){origin.set({preview:null,message:errorText(error)});if(current())report(error);}}
    finally{origin.set({busy:null});}
  };
  const submit=async()=>{
    if(memory.value.busy||submitted||!ready||!plan||!budget)return;
    const origin=memory,current=()=>live.current&&currentMemory.current===origin;
    const fields={...requestFields(form),resolution_pin:clone(plan.value.pin),selected_materials:selected.map(({id,revision})=>({id,revision})),
      provider_id:form.provider,output_kind:form.output,budget,background:form.background,constraints:form.constraints,
      acceptance:form.acceptance,unresolved:form.unresolved?[form.unresolved]:[]};
    const signature=JSON.stringify(fields),previous=origin.value.attempt;
    const attempt=previous?.signature===signature?previous:{signature,key:requestId()};
    origin.set({attempt,busy:'submit',message:'',uncertain:'正在确认原请求；关闭并重新打开此面板不会再次派发。'});
    try{
      const task=await command('commission.submit',{...fields,request_key:attempt.key});
      const payload=task?.payload,materials=payload?.context?.materials;
      if(!ident(task?.id)||task.project_id!==origin.project||task.request_key!==attempt.key||typeof task.status!=='string'||payload?.kind!=='research'||
        payload.target_id!==null||payload.base_revision!==null||payload.request!==fields.request||payload.provider_id!==fields.provider_id||
        payload.budget?.max_model_calls!==budget.max_model_calls||payload.budget?.timeout_seconds!==budget.timeout_seconds||payload.context?.output!==fields.output_kind||!Array.isArray(materials)||
        materials.length!==selected.length||selected.some(m=>!materials.some((x:any)=>x.id===m.id&&x.revision===m.revision&&x.sha256===m.sha256)))
        throw new Error('提交回包缺少同一项目、请求和保存来源的任务身份；结果尚未确认，请保留原请求核对。');
      origin.set({accepted:{task,read:false},uncertain:''});
    }catch(error){
      origin.set({message:errorText(error)});if(current())report(error);
      if(error instanceof CommandError&&!unknown)origin.set({uncertain:'',consent:'',
        ...(['conflict','resolution_required','context_limit','forbidden'].includes(error.code)?{preview:null}:{})});
      else origin.set({uncertain:'提交结果尚未确认；保留当前输入，只能用同一请求身份重试核对。'});
    }finally{origin.set({busy:null});}
  };
  const openTask=async()=>{if(!submitted)return;const origin=memory;try{await onOpenTask({id:submitted.id,project_id:origin.project});}
    catch(error){origin.set({message:errorText(error)});if(live.current&&currentMemory.current===origin)report(error);}};
  const refreshTask=async()=>{
    if(!submitted||memory.value.busy)return;
    const origin=memory,id=submitted.id,current=()=>live.current&&currentMemory.current===origin;
    origin.set({busy:'read',message:'',accepted:{task:submitted,read:false}});
    try{const task=await readTask(id);
      if(task.project_id!==origin.project||task.request_key!==submitted.request_key||!sameCommission(task.payload,submitted.payload))throw new Error('任务读回身份与原委托不符；未打开其他候选。');
      origin.set({accepted:{task,read:true}});
    }catch(error){origin.set({message:errorText(error)});if(current())report(error);}
    finally{origin.set({busy:null});}
  };
  const candidate=accepted?.read&&submitted?.status==='generated'&&ident(submitted.result?.object_id)&&positive(submitted.result?.revision)?
    {id:submitted.result.object_id,revision:submitted.result.revision,consumer_id:memory.project}:null;
  const openCandidate=async()=>{if(!candidate||!onOpenReference)return;const origin=memory;try{await onOpenReference(candidate);}
    catch(error){origin.set({message:errorText(error)});if(live.current&&currentMemory.current===origin)report(error);}};
  return <section className="review-panel" aria-label="研究委托">
    <h2>发起研究委托</h2><p>所属项目：{s.project.title}。本入口只创建新的报告或笔记候选。</p>
    <p>先核对已登记成果与文献的保存版本。解析不调用模型、不联网检索；原生 Markdown 笔记全文不会经此入口自动读取。</p>
    <details onToggle={event=>setFulltextOpen(event.currentTarget.open)}>
      <summary>取得公开全文资料</summary>
      {fulltextOpen&&<TaskAuthority session={s} projectId={s.project.id} report={report}>{authority=>
        <LiteratureFulltextInput session={s} writable={authority?authority.writableProjectIds.includes(s.project.id):null}
          onOpenReference={onOpenReference} report={report}/>}</TaskAuthority>}
    </details>
    {dirty&&<p role="status">当前有未保存草稿。本委托只采用保存来源，不会保存或发送这些手改；如需纳入，请先在原编辑区保存后重新预览。</p>}
    <fieldset disabled={busy==='submit'||!!submitted||!!unknown}>
      <legend>目的与范围</legend>
      <label>研究目的<textarea aria-label="研究目的" value={form.request} onChange={e=>update('request',e.target.value)}/></label>
      <label>产出类型<select aria-label="产出类型" value={form.output} onChange={e=>update('output',e.target.value)}><option value="report">报告</option><option value="note">笔记</option></select></label>
      <details><summary>补充来源与研究边界</summary>
        <label>补充已登记来源<textarea aria-label="补充已登记来源" placeholder="每行一个成果 ID，可附 @修订号" value={form.additional} onChange={e=>update('additional',e.target.value)}/></label>
        <label>补充背景<textarea aria-label="补充背景" value={form.background} onChange={e=>update('background',e.target.value)}/></label>
        <label>方法与授权边界<textarea aria-label="方法与授权边界" value={form.constraints} onChange={e=>update('constraints',e.target.value)}/></label>
        <label>产出检查条件<textarea aria-label="产出检查条件" value={form.acceptance} onChange={e=>update('acceptance',e.target.value)}/></label>
        <label>未决事项<textarea aria-label="未决事项" value={form.unresolved} onChange={e=>update('unresolved',e.target.value)}/></label>
      </details>
      <button disabled={!!busy||!form.request.trim()} onClick={()=>void resolve()}>解析保存来源</button>
      {plan&&<section aria-label="保存来源预览"><h3>本次采用的保存来源</h3>
        <p>{plan.value.project?.title||'项目尚未核定'} · 已选 {selected.length} 项 / {plan.value.limits.max_materials} 项；证据 {selected.reduce((n,m)=>n+m.bytes,0)} / {plan.value.limits.max_bytes} 字节。</p>
        {plan.value.materials.map(m=><article key={refKey(m)}><label><input type="checkbox" aria-label={'采用来源 '+refKey(m)} checked={plan.selection.includes(refKey(m))} disabled={!!busy}
          onChange={e=>{memory.set({preview:{...plan,selection:e.target.checked?[...plan.selection,refKey(m)]:plan.selection.filter(x=>x!==refKey(m)),verified:false},consent:'',emptyConsent:''});}}/>{m.title} · r{m.revision} · {m.kind}</label>
          <p>{m.reason}{m.required?'（明确提及来源，可在此取消）':''}{m.current_revision!==m.revision?`；当前为 r${m.current_revision}，此处采用固定 r${m.revision}`:''}</p>
          <details><summary>来源身份</summary><p>{m.id} · r{m.revision}</p><p>保存来源 SHA：{m.sha256}</p><p>当前 SHA：{m.current_sha256}</p></details>
        </article>)}
        {!plan.verified&&<p role="status">采用选择已变化，请重新解析保存来源。</p>}
        {plan.value.ambiguities.map((x,i)=><p role="status" key={i}>{x.label}</p>)}
        {plan.value.gaps.map((x,i)=><p role="status" key={i}>{x}</p>)}
        <details><summary>未采用来源与预览依据</summary>{plan.value.excluded.map((x,i)=><p key={i}>{x.id} r{x.revision}：{x.reason}</p>)}<pre>{JSON.stringify(plan.value.pin,null,2)}</pre></details>
      </section>}
      <label>执行路线<select aria-label="执行路线" value={form.provider} onChange={e=>update('provider',e.target.value)}><option value="">请选择已配置路线</option>
        {providers.map(p=><option key={p.id} value={p.id} disabled={!!providerProblem(p)}>{p.id} · {p.route}{p.model?' · '+p.model:''}{providerProblem(p)?' · '+providerProblem(p):''}</option>)}</select></label>
      <label>模型调用上限<input aria-label="模型调用上限" type="number" min="1" max="100" step="1" value={form.calls} onChange={e=>update('calls',e.target.value)}/></label>
      <label>执行秒数上限<input aria-label="执行秒数上限" type="number" min="1" max="900" step="1" value={form.seconds} onChange={e=>update('seconds',e.target.value)}/></label>
      {!budget&&<p role="alert">请输入 1 至 100 次调用、1 至 900 秒的整数上限。</p>}
      <p>提交后任务进入队列，由运行中的执行器按配置调用所选路线。调用可能产生费用；次数与时限上限不代表金额上限，也不保证产出已完成。</p>
      {runtime?.running!==true&&<p role="status">执行器尚未运行；可以解析来源，当前不能提交执行。</p>}
      {runtime?.running===true&&!available&&<p role="status">请选择支持且已授权的执行路线；已有配置不代表已验证连接或费用。</p>}
      {sourceCurrent&&selected.length===0&&<label><input type="checkbox" aria-label="确认无保存来源" checked={emptyConsent===confirmation} onChange={e=>memory.set({emptyConsent:e.target.checked?confirmation:''})}/>本次没有采用保存来源，仅提出概念性委托，不声称已有调查证据。</label>}
      <label><input type="checkbox" aria-label="确认本次委托与预算" checked={consent===confirmation} disabled={!sourceCurrent||!available||!budget} onChange={e=>memory.set({consent:e.target.checked?confirmation:''})}/>
        我确认按以上保存来源、文字范围和有限预算调用所选路线，生成新候选。</label>
    </fieldset>
    {message&&<p role="alert">{message}</p>}
    {unknown&&<p role="status">{unknown}</p>}
    <button disabled={!!busy||!!submitted||!ready} onClick={()=>void submit()}>{unknown?'重试同一委托':'确认提交研究委托'}</button>
    {busy&&<p role="status">{busy==='resolve'?'正在解析保存来源…':busy==='read'?'正在读取此委托的实际任务…':'正在确认提交回执…'}</p>}
    {submitted&&<div role="status"><p>已登记委托 {submitted.id}；实际状态：{submitted.status}。任务登记不代表候选已完成或已采用。</p>
      <button disabled={!!busy} onClick={()=>void openTask()}>打开此委托任务</button><button disabled={!!busy} onClick={()=>void refreshTask()}>刷新此委托任务</button>
      {candidate&&onOpenReference&&<><p>实际候选：{candidate.id} r{candidate.revision}；审阅与采用另行决定。</p><button disabled={!!busy} onClick={()=>void openCandidate()}>查看固定候选</button></>}
      <button disabled={!!busy} onClick={()=>memory.set({form:initial(),preview:null,message:'',consent:'',emptyConsent:'',accepted:null,uncertain:'',attempt:null})}>新建另一项委托</button>
    </div>}
  </section>;
}
