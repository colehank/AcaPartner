import {useEffect,useRef,useSyncExternalStore} from 'react';
import {command,CommandError,requestId} from './api';

type Ref={id:string,revision:number};
type Provider={id:string,route:string,model?:string,authorized:boolean,available?:boolean};
export type ReportRevisionActions={memoryKey:object,providers:Provider[],runtimeRunning:boolean,disabled?:boolean,dirty?:boolean,
  prepare:()=>Promise<boolean>,onOpenTask:(reference:{id:string,project_id:string})=>Promise<void>|void};
type Target=Ref&{sha256:string,title:string,project_id:string,source_refs:unknown};
type Material=Ref&{sha256:string,title:string,kind:string,bytes:number,selected:boolean,required:boolean,current_revision:number,current_sha256:string,reason:string};
type Plan={status:string,project:{id:string,revision:number,sha256:string},materials:Material[],pin:any,ambiguities:any[],gaps:string[],limits:{max_materials:number,max_bytes:number}};
type Feedback={id:string,revision:number,project_id:string,content:{original:string,object_id:string,object_revision:number}};
type Value={open:boolean,text:string,additional:string,provider:string,calls:string,seconds:string,feedback:Feedback|null,
  plan:Plan|null,selection:string[],verified:boolean,consent:string,busy:boolean,message:string,uncertain:string,
  attempt:{signature:string,key:string}|null,accepted:{id:string,project_id:string}|null};
type Memory={value:Value,version:number,listeners:Set<()=>void>,set:(patch:Partial<Value>)=>void,subscribe:(listener:()=>void)=>()=>void,snapshot:()=>number};
const memories=new WeakMap<object,Map<string,Memory>>();
const hash=(x:unknown):x is string=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
const id=(x:unknown):x is string=>typeof x==='string'&&/^[A-Z]+-[A-Za-z0-9]+$/.test(x);
const positive=(x:unknown):x is number=>Number.isSafeInteger(x)&&Number(x)>0;
const key=(ref:Ref)=>ref.id+'@'+ref.revision;
const clone=<T,>(value:T):T=>structuredClone(value);
const message=(error:unknown)=>error instanceof Error?error.message:String(error);
const definiteRejection=(error:unknown)=>error instanceof CommandError&&['forbidden','conflict','version_required','resolution_required','context_limit','authorization_required'].includes(error.code);
function originalRefs(value:unknown){
  if(value===undefined)return '';
  if(!Array.isArray(value)||value.some(ref=>!id(ref?.id)||!positive(ref.revision)))return '请核对原报告的来源登记格式';
  return value.map(ref=>key(ref)).join('\n');
}
function memoryFor(owner:object,scope:string,target:Target):Memory{
  let map=memories.get(owner);if(!map){map=new Map();memories.set(owner,map);}
  const previous=map.get(scope);if(previous)return previous;
  const memory:Memory={value:{open:false,text:'',additional:originalRefs(target.source_refs),provider:'',calls:'1',seconds:'300',feedback:null,
    plan:null,selection:[],verified:false,consent:'',busy:false,message:'',uncertain:'',attempt:null,accepted:null},version:0,listeners:new Set(),
    set(patch){memory.value={...memory.value,...patch};memory.version++;for(const listener of memory.listeners)listener();},
    subscribe(listener){memory.listeners.add(listener);return()=>{memory.listeners.delete(listener);};},snapshot:()=>memory.version};
  map.set(scope,memory);return memory;
}
function refs(text:string):Ref[]{
  const seen=new Set<string>();return text.split(/\r?\n/).map(line=>line.trim()).filter(Boolean).map(line=>{
    const match=/^([A-Z]+-[A-Za-z0-9]+)@([1-9]\d*)$/.exec(line),revision=Number(match?.[2]);
    if(!match||!positive(revision)||seen.has(line))throw new Error('来源需要每行一个不同的已登记 ID@正整数修订；不会改读最新版本。');
    seen.add(line);return {id:match[1],revision};
  });
}
function budgetOf(value:Value){
  const calls=Number(value.calls),seconds=Number(value.seconds);
  return /^\d+$/.test(value.calls)&&/^\d+$/.test(value.seconds)&&Number.isSafeInteger(calls)&&calls>=1&&calls<=100&&
    Number.isSafeInteger(seconds)&&seconds>=1&&seconds<=900?{max_model_calls:calls,timeout_seconds:seconds}:null;
}
function permitted(provider:Provider|undefined){return !!provider&&typeof provider.id==='string'&&!!provider.id&&
  ['codex','deepseek_harness'].includes(provider.route)&&provider.authorized===true&&(provider.available===undefined||provider.available===true);}
function checkedPlan(value:any,project:string):Plan{
  const invalid=()=>{throw new Error('修订来源回包的项目、固定修订或摘要不完整；未开放派发。');};
  if(!value||!['ready','needs_selection'].includes(value.status)||value.project?.id!==project||!positive(value.project.revision)||!hash(value.project.sha256)||
    !Array.isArray(value.materials)||!Array.isArray(value.ambiguities)||!Array.isArray(value.gaps)||value.gaps.some((x:any)=>typeof x!=='string')||
    !positive(value.limits?.max_materials)||!positive(value.limits?.max_bytes)||value.pin?.version!==1||
    !hash(value.pin.request_sha256)||!hash(value.pin.context_sha256)||!hash(value.pin.catalog_sha256)||
    value.pin.project?.id!==project||value.pin.project.revision!==value.project.revision||value.pin.project.sha256!==value.project.sha256)invalid();
  const seen=new Set<string>();
  for(const m of value.materials){
    if(!id(m?.id)||!positive(m.revision)||!hash(m.sha256)||typeof m.title!=='string'||typeof m.kind!=='string'||
      typeof m.reason!=='string'||!Number.isSafeInteger(m.bytes)||m.bytes<0||!positive(m.current_revision)||!hash(m.current_sha256)||
      typeof m.selected!=='boolean'||typeof m.required!=='boolean'||seen.has(key(m)))invalid();
    seen.add(key(m));
  }
  return clone(value);
}
async function freshTarget(target:Target,project:string){
  const response=await fetch('/api/objects/'+encodeURIComponent(target.id),{method:'GET',credentials:'same-origin'});
  const body=await response.json();
  if(!response.ok||body?.ok!==true)throw new CommandError(body?.code,body?.error||'当前报告权限核对失败；意见草稿保留。',body?.details);
  const current=body.result;
  if(current?.id!==target.id||current.kind!=='report'||current.project_id!==project||current.revision!==target.revision||current.canonical_source_sha256!==target.sha256)
    throw new Error('当前报告已变化，或不属于此项目；固定旧版与意见草稿保留，请核对新版后另行提出修订。');
}

/** One saved feedback, then one explicit, bounded revision task. Never resumes its producer. */
export function ReportRevisionForm({target,projectId,actions,report}:{target:Target,projectId:string,actions:ReportRevisionActions,report:(error:unknown)=>void}){
  const scope=JSON.stringify([projectId,target.id,target.revision,target.sha256]);
  const memory=memoryFor(actions.memoryKey,scope,target);useSyncExternalStore(memory.subscribe,memory.snapshot);
  const latest=useRef({memory,actions,scope}),live=useRef(true);latest.current={memory,actions,scope};
  useEffect(()=>{live.current=true;return()=>{live.current=false;memory.set({open:false});};},[memory]);
  const value=memory.value,provider=actions.providers.find(p=>p.id===value.provider),budget=budgetOf(value);
  const own=target.project_id===projectId&&id(target.id)&&positive(target.revision)&&hash(target.sha256);
  const selected=value.plan?.materials.filter(m=>value.selection.includes(key(m)))||[];
  const confirmation=JSON.stringify([scope,value.feedback,value.additional,value.plan?.pin,selected,value.provider,value.calls,value.seconds,provider,actions.runtimeRunning,actions.disabled,actions.dirty]);
  const ready=own&&!actions.disabled&&!actions.dirty&&!value.busy&&!value.uncertain&&!value.accepted&&!!value.feedback&&
    value.verified&&value.plan?.status==='ready'&&!value.plan.ambiguities.length&&!!budget&&actions.runtimeRunning&&permitted(provider)&&value.consent===confirmation;
  const current=(origin:Memory)=>live.current&&latest.current.memory===origin&&latest.current.scope===scope&&origin.value.open&&!latest.current.actions.disabled;
  const fields=(v:Value)=>({request:v.feedback?.content.original||v.text,project_id:projectId,selected_project_id:projectId,
    object_id:target.id,material_mode:'auto',additional_materials:refs(v.additional),literature_plan:false});
  const fail=(origin:Memory,error:unknown)=>{origin.set({message:message(error)});if(current(origin))report(error);};
  const save=async()=>{
    const origin=memory,v=clone(origin.value);if(!current(origin)||!own||v.busy||v.feedback||v.uncertain||!v.text.trim())return;
    origin.set({busy:true,message:''});let sent=false;
    try{
      await freshTarget(target,projectId);if(!current(origin))return;
      sent=true;origin.set({uncertain:'保存意见的结果未确认；保留此草稿，不会自动重复保存。'});
      const result=await command('feedback.add',{project_id:projectId,object_id:target.id,object_revision:target.revision,expected_target_revision:target.revision,
        text:v.text,scope:'result',timing:'immediate',disposition:'ready',source:'user',source_reference:{id:target.id,revision:target.revision,sha256:target.sha256}});
      if(!id(result?.id)||result.kind!=='feedback'||!positive(result.revision)||result.project_id!==projectId||result.content?.object_id!==target.id||
        result.content.object_revision!==target.revision||result.content.original!==v.text||result.content.lifecycle!=='active'||result.content.disposition!=='ready'||
        result.metadata?.scope!=='result'||result.metadata.timing!=='immediate')throw new Error('意见保存回包身份不符，结果未确认；请保留原草稿核对，未重复保存。');
      origin.set({feedback:clone(result),uncertain:'',message:''});
    }catch(error){if(!sent||definiteRejection(error))origin.set({uncertain:''});fail(origin,error);}
    finally{origin.set({busy:false});}
  };
  const resolve=async()=>{
    const origin=memory,v=clone(origin.value);if(!current(origin)||!own||v.busy||!v.feedback||v.uncertain||v.accepted)return;
    origin.set({busy:true,consent:'',message:''});
    try{
      await freshTarget(target,projectId);if(!current(origin))return;
      const response=await command('task.resolve',{...fields(v),...(v.plan?{selected_materials:v.plan.materials.filter(m=>v.selection.includes(key(m))).map(({id,revision})=>({id,revision}))}:{})});
      if(!current(origin)||origin.value.additional!==v.additional)return;
      const plan=checkedPlan(response,projectId);origin.set({plan,selection:plan.materials.filter(m=>m.selected).map(key),verified:true});
    }catch(error){origin.set({plan:null,verified:false});fail(origin,error);}
    finally{origin.set({busy:false});}
  };
  const dispatch=async()=>{
    const origin=memory,v=clone(origin.value),p=clone(provider);if(!ready||!current(origin)||!v.feedback||!v.plan||!budget)return;
    const frozenConfirmation=confirmation,chosen=v.plan.materials.filter(m=>v.selection.includes(key(m)));
    origin.set({busy:true,message:''});let sent=false;
    try{
      if(!await actions.prepare())throw new Error('当前草稿尚未安全保存；未派发新修订任务。');
      if(!current(origin))return;
      const actual=latest.current.actions;
      if(actual.dirty||!actual.runtimeRunning||!permitted(actual.providers.find(x=>x.id===v.provider))||
        JSON.stringify(actual.providers.find(x=>x.id===v.provider))!==JSON.stringify(p)||origin.value.consent!==frozenConfirmation)
        throw new Error('草稿、权限、路线或本次确认已变化；未派发，请重新核对。');
      await freshTarget(target,projectId);if(!current(origin))return;
      const request={...fields(v),selected_materials:chosen.map(({id,revision})=>({id,revision}))};
      const plan=checkedPlan(await command('task.resolve',request),projectId);if(!current(origin))return;
      const selectedNow=plan.materials.filter(m=>m.selected);
      if(plan.status!=='ready'||plan.ambiguities.length||JSON.stringify(plan.pin)!==JSON.stringify(v.plan.pin)||
        JSON.stringify(selectedNow.map(({id,revision,sha256})=>({id,revision,sha256})))!==JSON.stringify(chosen.map(({id,revision,sha256})=>({id,revision,sha256}))))
        throw new Error('保存来源或采用范围已变化；未派发，请重新解析。');
      // Recheck host changes after every asynchronous preflight, before the sole write.
      if(latest.current.actions.dirty||!latest.current.actions.runtimeRunning||origin.value.consent!==frozenConfirmation||
        JSON.stringify(latest.current.actions.providers.find(x=>x.id===v.provider))!==JSON.stringify(p))throw new Error('当前输入或路线已变化；未派发。');
      const payload={...request,id:v.feedback.id,expected_revision:v.feedback.revision,expected_target_revision:target.revision,
        scope:'result',timing:'immediate',depends_on:[],resolution_pin:plan.pin,provider_id:v.provider,output_kind:'report',budget,
        constraints:'仅按保存的修订意见修订此固定报告；保留原来源、未涉及原文与不确定性；不改变稿件引用、原始数据、科学批准或执行新计算。',
        acceptance:'保存有来源与限制的待审报告修订；原修订保留，生成和保存不等于采用或科学批准。'};
      const signature=JSON.stringify(payload),attempt=v.attempt?.signature===signature?v.attempt:{signature,key:requestId()};
      origin.set({attempt,uncertain:'新修订任务的登记结果未确认；保留原请求身份，不会自动重发。'});sent=true;
      const task=await command('feedback.request',{...payload,request_key:attempt.key});const contract=task?.payload;
      if(!id(task?.id)||!['queued','running','paused','waiting_input','waiting_resource','waiting_authorization','failed','generated','review','deliverable','cancelled'].includes(task.status)||
        task.project_id!==projectId||task.request_key!==attempt.key||contract?.kind!=='revision'||contract.project_id!==projectId||
        contract.target_id!==target.id||contract.base_revision!==target.revision||contract.feedback_id!==v.feedback.id||contract.request!==v.feedback.content.original||
        contract.provider_id!==v.provider||contract.budget?.max_model_calls!==budget.max_model_calls||contract.budget.timeout_seconds!==budget.timeout_seconds||
        contract.context?.output!=='report'||contract.context.question!==v.feedback.content.original||contract.context.feedback?.id!==v.feedback.id||
        contract.context.feedback.revision!==v.feedback.revision||contract.context.feedback.original!==v.feedback.content.original||
        !Array.isArray(contract.context.materials)||JSON.stringify(contract.context.materials.map(({id,revision,sha256}:any)=>({id,revision,sha256})))!==
        JSON.stringify(chosen.map(({id,revision,sha256})=>({id,revision,sha256})))||!Array.isArray(contract.depends_on)||contract.depends_on.length)
        throw new Error('新修订任务回包不符合固定目标、意见或来源，结果未确认；保留原请求，不再派发。');
      // Persist a known accepted request in its original memory even after closure.
      origin.set({accepted:{id:task.id,project_id:projectId},uncertain:'',consent:'',message:'已登记新的修订任务；尚未生成或采用修订。'});
    }catch(error){origin.set({consent:'',verified:false,...(!sent||definiteRejection(error)?{uncertain:''}:{}),...(error instanceof CommandError?{plan:null}:{})});fail(origin,error);}
    finally{origin.set({busy:false});}
  };
  const locked=value.busy||!!value.uncertain||!!value.accepted||!!actions.disabled;
  return <section className="report-revision-entry" aria-label="固定报告修订">
    <button disabled={!own||!!actions.disabled} onClick={()=>memory.set({open:!value.open})}>提出修订</button>
    {!own&&<p role="status">此来源仅供读取；请在有写权限的原项目提出修订。</p>}
    {value.open&&<div className="report-revision-form">
      <h3>对固定报告提出修订 · r{target.revision}</h3>
      <p>这是新的修订任务；原报告与原任务记录保留。结果保存为待审候选，不自动改变稿件引用或科学批准。</p>
      <label>修订意见<textarea aria-label="修订意见" disabled={locked||!!value.feedback} value={value.text} onChange={e=>memory.set({text:e.target.value,message:''})}/></label>
      <button disabled={locked||!!value.feedback||!value.text.trim()} onClick={()=>void save()}>仅保存修订意见</button>
      {value.feedback&&<>
        {!value.accepted&&!value.uncertain&&<p role="status">修订意见已保存；尚未派发任务。</p>}
        <label>修订补充来源<textarea aria-label="修订补充来源" disabled={locked} value={value.additional} onChange={e=>memory.set({additional:e.target.value,plan:null,verified:false,consent:'',message:''})}/></label>
        <p>每行一个已登记来源 ID@修订。仅发送明确选定的保存来源；原生笔记和未保存手改不会自动加入。</p>
        <button disabled={locked} onClick={()=>void resolve()}>解析修订来源</button>
        {value.plan&&<section aria-label="修订保存来源"><h4>核对保存来源</h4>
          {value.plan.materials.map(m=><label key={key(m)}><input type="checkbox" aria-label={'采用修订来源 '+key(m)} disabled={locked} checked={value.selection.includes(key(m))}
            onChange={e=>memory.set({selection:e.target.checked?[...value.selection,key(m)]:value.selection.filter(x=>x!==key(m)),verified:false,consent:''})}/>{m.title} · r{m.revision}<small>{m.id} · SHA-256 {m.sha256}</small></label>)}
          {!value.verified&&<p role="status">来源选择已变化，请重新解析。</p>}
          {!selected.length&&<p role="status">没有选定补充材料；固定报告本身仍作为修订目标发送。</p>}
          {value.plan.gaps.map((gap,index)=><p key={index} role="status">{gap}</p>)}
          {value.plan.ambiguities.map((item,index)=><p key={index} role="status">{String(item.label||'来源尚未明确')}</p>)}
        </section>}
        <label>修订执行路线<select aria-label="修订执行路线" disabled={locked} value={value.provider} onChange={e=>memory.set({provider:e.target.value,consent:''})}>
          <option value="">请选择已配置路线</option>{actions.providers.map(p=><option key={p.id} value={p.id} disabled={!permitted(p)}>{p.id} · {p.route}{p.model?' · '+p.model:''}{!permitted(p)?' · 当前不可用':''}</option>)}
        </select></label>
        <label>修订模型调用上限<input aria-label="修订模型调用上限" type="number" min="1" max="100" step="1" disabled={locked} value={value.calls} onChange={e=>memory.set({calls:e.target.value,consent:''})}/></label>
        <label>修订执行秒数上限<input aria-label="修订执行秒数上限" type="number" min="1" max="900" step="1" disabled={locked} value={value.seconds} onChange={e=>memory.set({seconds:e.target.value,consent:''})}/></label>
        {!budget&&<p role="alert">请设置 1–100 次调用、1–900 秒的有限整数上限。</p>}
        {!actions.runtimeRunning&&<p role="status">执行器尚未运行；可保存意见和核对来源，不能派发。</p>}
        {actions.dirty&&<p role="status">现有手改尚未保存；保持原草稿，保存并重新核对后才可派发。</p>}
        <label><input type="checkbox" aria-label="确认新修订任务与有限预算" disabled={locked||!value.verified||value.plan?.status!=='ready'||!budget||!permitted(provider)||!actions.runtimeRunning||!!actions.dirty}
          checked={value.consent===confirmation} onChange={e=>memory.set({consent:e.target.checked?confirmation:''})}/>确认新修订任务与有限预算</label>
        <button disabled={!ready} onClick={()=>void dispatch()}>确认派发新的修订任务</button>
      </>}
      {value.uncertain&&<p role="alert">{value.uncertain}</p>}
      {value.message&&!value.uncertain&&<p role={value.accepted?'status':'alert'}>{value.message}</p>}
      {value.accepted&&<button disabled={!!actions.disabled} onClick={()=>{if(current(memory)&&memory.value.accepted)void Promise.resolve(actions.onOpenTask(memory.value.accepted)).catch(error=>fail(memory,error));}}>打开新修订任务</button>}
    </div>}
  </section>;
}
