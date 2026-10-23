import {useEffect,useRef,useSyncExternalStore} from 'react';
import {command,CommandError,requestId} from './api';
import type {Session} from './session';
import type {TaskExecutionAuthority} from './TaskAuthority';
import {actualTaskBrief,type TaskBriefRef} from './TaskBriefReference';

type TaskRef={id:string,project_id:string};
export type ResearchCyclePanelProps={session:Session,taskAuthority?:TaskExecutionAuthority,parentTaskId?:string,
  onOpenTask?:(reference:TaskRef)=>void|Promise<void>,
  onOpenNote?:(path:string)=>void|Promise<void>,
  onOpenReference?:(reference:{id:string,revision:number,sha256:string,consumer_id:string})=>void|Promise<void>,report:(error:unknown)=>void};
const roleNames={planner:'规划路线',delegate:'具体工作路线',reviewer:'独立复核路线',integrator:'整合路线',final_reviewer:'最终复核路线'};
type Role=keyof typeof roleNames;
const roles=Object.keys(roleNames) as Role[];
const limitNames={max_model_calls:'合计模型调用上限',timeout_seconds:'合计执行秒数',max_steps:'步骤上限',max_rework:'返工轮数上限',child_max_model_calls:'单步骤调用上限',child_timeout_seconds:'单步骤秒数'};
type Limits=Record<keyof typeof limitNames,number>;
type Form={request:string,additional:string,output:'report'|'note',background:string,constraints:string,acceptance:string,unresolved:string,
  roles:Record<Role,string>,limits:Record<keyof Limits,string>};
type Ref={id:string,revision:number,sha256:string};
type Material=Ref&{title:string,kind:string,reason:string,bytes:number,current_revision:number,current_sha256:string,selected:boolean,required:boolean};
type Resolution={status:string,project:Ref&{title:string},materials:Material[],pin:any,ambiguities:{label:string}[],gaps:string[],excluded:any[],limits:{max_materials:number,max_bytes:number}};
type CycleView={task:any,cycle:any,children:any[],actual_consumption:any,parent_inputs_current:any,integration_inputs:any,unincorporated_parent_inputs:boolean,accounting_note:string,handoff_meaning:string,execution_stop?:unknown};
type StopStatus='draining'|'stopped'|'unknown';
type ExecutionStop={version:1,parent_id:string,epoch:number,status:StopStatus,dispatch_blocked:true,
  children:{id:string,status:StopStatus,reason:string}[]};
type Intent={fields:Record<string,any>,materials:Ref[],routes:Record<Role,string>};
type Draft={form:Form,preview:{value:Resolution,signature:string,selection:string[],verified:boolean}|null,consent:string,
  owner:object|null,phase:'idle'|'pending'|'unknown'|'accepted',intent:Intent|null,parent:string|null,error:string,notice:string};
type Parent={view:CycleView|null,stamp:object|null,error:string,readOwner:object|null,controlOwner:object|null,
  unknown:{operation:string,epoch:number}|null,notice:string,briefOwner:object|null,briefUnknown:boolean,
  briefNote:TaskBriefRef|null,briefError:string};
type Memory<T>={value:T,set:(patch:Partial<T>)=>void,subscribe:(listener:()=>void)=>()=>void,snapshot:()=>number};
function memory<T>(value:T):Memory<T>{
  let version=0;const listeners=new Set<()=>void>();
  const result:Memory<T>={value,set(patch){result.value={...result.value,...patch};version++;for(const f of listeners)f();},
    subscribe(f){listeners.add(f);return()=>{listeners.delete(f);};},snapshot:()=>version};return result;
}
const drafts=new WeakMap<Session,Map<string,Memory<Draft>>>(),parents=new WeakMap<Session,Map<string,Memory<Parent>>>();
function draftFor(s:Session){let map=drafts.get(s);if(!map){map=new Map();drafts.set(s,map);}let value=map.get(s.project.id);
  if(!value){value=memory<Draft>({form:{request:'',additional:'',output:'report',background:'',constraints:'仅使用采用的保存来源，保留证据与不确定性；不改原始数据，不启动新实验、拟合或未经授权的服务。',
    acceptance:'保存可审查的新候选，说明依据、限制与下一步；模型返回与独立审查均不等于科学或用户验收。',unresolved:'',roles:{planner:'',delegate:'',reviewer:'',integrator:'',final_reviewer:''},
    limits:{max_model_calls:'6',timeout_seconds:'600',max_steps:'6',max_rework:'0',child_max_model_calls:'1',child_timeout_seconds:'100'}},preview:null,consent:'',owner:null,phase:'idle',intent:null,parent:null,error:'',notice:''});map.set(s.project.id,value);}return value;
}
function parentFor(s:Session,key:string){let map=parents.get(s);if(!map){map=new Map();parents.set(s,map);}let value=map.get(key);
  if(!value){value=memory<Parent>({view:null,stamp:null,error:'',readOwner:null,controlOwner:null,unknown:null,notice:'',briefOwner:null,briefUnknown:false,briefNote:null,briefError:''});map.set(key,value);}return value;
}
const record=(x:any)=>x!==null&&typeof x==='object'&&!Array.isArray(x);
const id=(x:any)=>typeof x==='string'&&x.length>0&&x.length<=200&&!/[\s/\\\u0000-\u001f]/u.test(x);
const sha=(x:any)=>typeof x==='string'&&/^[a-f0-9]{64}$/.test(x);
const count=(x:any)=>Number.isSafeInteger(x)&&x>=0;
const positive=(x:any)=>count(x)&&x>0;
const text=(e:unknown)=>e instanceof Error?e.message:String(e);
const key=(x:{id:string,revision:number})=>x.id+'@'+x.revision;
const copy=<T,>(x:T):T=>structuredClone(x);
function finiteLimits(x:any):x is Limits{return record(x)&&Object.keys(limitNames).every(k=>typeof x[k]==='number'&&Number.isFinite(x[k]))&&
  [x.max_model_calls,x.max_steps,x.max_rework,x.child_max_model_calls].every(Number.isSafeInteger)&&x.max_model_calls>=1&&x.max_model_calls<=100&&
  x.max_steps>=1&&x.max_steps<=24&&x.max_rework>=0&&x.max_rework<=1&&x.child_max_model_calls>=1&&x.child_max_model_calls<=10&&x.child_max_model_calls<=x.max_model_calls&&
  x.timeout_seconds>0&&x.timeout_seconds<=7200&&x.child_timeout_seconds>0&&x.child_timeout_seconds<=900&&x.child_timeout_seconds<=x.timeout_seconds;}
function formLimits(form:Form){const raw=form.limits;if(Object.values(raw).some(x=>!/^\d+(?:\.\d+)?$/.test(x)))return null;
  const value=Object.fromEntries(Object.entries(raw).map(([k,v])=>[k,Number(v)]));return finiteLimits(value)?value:null;}
function additional(text:string){return text.split(/\r?\n/).map(x=>x.trim()).filter(Boolean).map(line=>{
  const m=/^([^@]+)(?:@([1-9]\d*))?$/.exec(line);if(!m||!id(m[1])||m[2]&&!positive(Number(m[2])))throw Error('补充来源每行填写一个已登记成果 ID，可附 @正整数修订号。');
  return {id:m[1],...(m[2]?{revision:Number(m[2])}:{})};});}
function resolution(value:any,project:string):Resolution{
  const bad=()=>{throw Error('协作来源预览身份或字段不完整；未开放登记。');};
  if(!record(value)||!['ready','needs_selection'].includes(value.status)||!record(value.project)||value.project.id!==project||!positive(value.project.revision)||!sha(value.project.sha256)||typeof value.project.title!=='string'||
    !Array.isArray(value.materials)||!Array.isArray(value.ambiguities)||!Array.isArray(value.gaps)||value.gaps.some((x:any)=>typeof x!=='string')||!Array.isArray(value.excluded)||
    !positive(value.limits?.max_materials)||!positive(value.limits?.max_bytes)||value.pin?.version!==1||value.pin.project?.id!==project||
    value.pin.project?.revision!==value.project.revision||value.pin.project?.sha256!==value.project.sha256||!['request_sha256','context_sha256','catalog_sha256'].every(k=>sha(value.pin[k])))bad();
  const seen=new Set<string>();for(const m of value.materials){if(!id(m?.id)||!positive(m.revision)||!sha(m.sha256)||!positive(m.current_revision)||!sha(m.current_sha256)||!count(m.bytes)||
    !['title','kind','reason'].every(k=>typeof m[k]==='string')||typeof m.selected!=='boolean'||typeof m.required!=='boolean'||seen.has(key(m)))bad();seen.add(key(m));}
  if(value.ambiguities.some((x:any)=>typeof x?.label!=='string')||value.status==='ready'&&value.ambiguities.length)bad();return copy(value);
}
function checkedView(value:any,project:string,expectedId?:string):CycleView{
  const bad=()=>{throw Error('协作回包的父任务、项目或阶段身份不符；未展示其他任务。');};
  const t=value?.task,c=value?.cycle,p=t?.payload;
  if(!record(value)||!id(t?.id)||expectedId!==undefined&&t.id!==expectedId||t.project_id!==project||typeof t.status!=='string'||!count(t.attempts)||p?.kind!=='research_cycle'||typeof p.request!=='string'||
    !record(p.context)||!Array.isArray(p.context.materials)||!finiteLimits(p.cycle_config?.limits)||!roles.every(r=>id(p.cycle_config.roles?.[r])&&['codex','deepseek_harness'].includes(p.cycle_config.provider_routes?.[r]))||
    !record(c)||c.version!==1||!positive(c.epoch)||!count(c.transition)||typeof c.phase!=='string'||!count(c.round)||!count(c.reserved_calls)||typeof c.reserved_seconds!=='number'||!Number.isFinite(c.reserved_seconds)||c.reserved_seconds<0||!count(c.steps_used)||
    !Array.isArray(c.children)||!Array.isArray(c.history)||!Array.isArray(value.children)||!record(value.actual_consumption)||typeof value.accounting_note!=='string'||typeof value.handoff_meaning!=='string')bad();
  const seen=new Set<string>();for(const ref of p.context.materials)if(!id(ref?.id)||!positive(ref.revision)||!sha(ref.sha256))bad();
  for(const row of value.children){if(!id(row?.id)||seen.has(row.id)||row.task?.id!==row.id||row.task.project_id!==project||row.task.payload?.cycle_parent!==t.id||typeof row.task.status!=='string'||
    ![...roles,'acquisition'].includes(row.role)||!c.children.some((ref:any)=>ref.id===row.id&&ref.role===row.role))bad();seen.add(row.id);}
  if(c.children.length!==value.children.length)bad();
  if(c.final_source!==undefined&&(!id(c.final_source?.id)||!positive(c.final_source.revision)||!sha(c.final_source.sha256)))bad();
  return copy(value);
}
function sameIntent(task:any,intent:Intent){const p=task?.payload,f=intent.fields;
  return p?.kind==='research_cycle'&&p.request===f.request&&p.target_id===null&&p.base_revision===null&&p.feedback_id===null&&p.provider_id===f.roles.planner&&
    Object.keys(limitNames).every(k=>p.cycle_config?.limits?.[k]===f.limits[k])&&roles.every(r=>p.cycle_config?.roles?.[r]===f.roles[r]&&p.cycle_config?.provider_routes?.[r]===intent.routes[r])&&
    p.budget?.max_model_calls===f.limits.max_model_calls&&p.budget?.timeout_seconds===f.limits.timeout_seconds&&p.literature_plan===undefined&&p.context?.graph_catalog===undefined&&
    ['output','additional_background','constraints','acceptance'].every((k,i)=>p.context?.[k]===[f.output_kind,f.background,f.constraints,f.acceptance][i])&&
    JSON.stringify(p.context?.unresolved)===JSON.stringify(f.unresolved)&&Array.isArray(p.context?.materials)&&p.context.materials.length===intent.materials.length&&
    intent.materials.every(r=>p.context.materials.some((m:any)=>m.id===r.id&&m.revision===r.revision&&m.sha256===r.sha256));}
const phases:Record<string,string>={new:'准备分工',planning:'规划中',delegating:'子任务执行中',reviewing:'审查中',reworking:'返工中',integrating:'整合中',final_reviewing:'最终审查中',complete:'本轮形成候选与审查记录',handoff:'等待接手'};
const measured=(x:any)=>typeof x==='number'&&Number.isFinite(x)&&x>=0?String(x):'未记录';
const stopLabels:Record<StopStatus,string>={draining:'本地执行仍在收尾（drain）',stopped:'本地执行已停止',unknown:'执行停止尚未确认（unknown）'};
function executionStop(view:CycleView):{value:ExecutionStop|null,invalid:boolean}{
  const value:any=view.execution_stop;
  if(value===undefined)return {value:null,invalid:false};
  const bad=()=>({value:null,invalid:true});
  if(!record(value)||value.version!==1||value.parent_id!==view.task.id||value.epoch!==view.cycle.epoch||
    !Object.hasOwn(stopLabels,value.status)||value.dispatch_blocked!==true||!Array.isArray(value.children)||value.children.length!==view.children.length)return bad();
  const expected=new Set(view.children.map(row=>row.id)),seen=new Set<string>();
  for(const row of value.children){
    if(!record(row)||!expected.has(row.id)||seen.has(row.id)||!Object.hasOwn(stopLabels,row.status)||typeof row.reason!=='string')return bad();
    seen.add(row.id);
  }
  const aggregate=value.children.some((row:any)=>row.status==='unknown')?'unknown':value.children.some((row:any)=>row.status==='draining')?'draining':'stopped';
  if(value.status!==aggregate)return bad();
  return {value:value as ExecutionStop,invalid:false};
}

/** One bounded collaboration over the existing queue; no polling or execution engine. */
export function ResearchCyclePanel({session:s,taskAuthority:authority,parentTaskId,onOpenTask,onOpenReference,onOpenNote,report}:ResearchCyclePanelProps){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const project=s.project.id,draft=draftFor(s);useSyncExternalStore(draft.subscribe,draft.snapshot);
  const d=draft.value,parentId=parentTaskId??d.parent??undefined,entry=parentFor(s,project+'\n'+(parentId||''));useSyncExternalStore(entry.subscribe,entry.snapshot);
  const writable=authority?.writableProjectIds.includes(project)===true,signature=JSON.stringify(authority);
  const scope=useRef({s,project,parentId,signature});if(scope.current.s!==s||scope.current.project!==project||scope.current.parentId!==parentId||scope.current.signature!==signature)scope.current={s,project,parentId,signature};
  const active=scope.current,live=useRef(false),current=()=>live.current&&scope.current===active;
  const view=entry.value.stamp===active?entry.value.view:null;
  const stop=view&&['paused','cancelled'].includes(view.task.status)?executionStop(view):null;
  const fields=(f:Form)=>({request:f.request,material_mode:'auto',project_id:project,selected_project_id:project,additional_materials:additional(f.additional),literature_plan:false});
  const sourceSignature=JSON.stringify([project,d.form.request,d.form.additional]);
  const selected=d.preview?.value.materials.filter(m=>d.preview!.selection.includes(key(m)))||[],limits=formLimits(d.form);
  const providers=authority?.providers||[],configured=(provider:string)=>providers.some(p=>p.id===provider&&p.authorized&&['codex','deepseek_harness'].includes(p.route));
  const sourceReady=d.preview?.signature===sourceSignature&&d.preview.verified&&d.preview.value.status==='ready'&&selected.length>0;
  const confirmation=JSON.stringify([d.form,d.preview?.value.pin,selected.map(key),signature]);
  const ready=writable&&authority?.runtimeRunning===true&&roles.every(r=>configured(d.form.roles[r]))&&!!limits&&sourceReady&&d.consent===confirmation;
  const locked=!!d.owner||d.phase!=='idle',parentLocked=!!entry.value.controlOwner||!!entry.value.unknown;
  const error=(e:unknown)=>{if(current())report(e);return text(e);};
  const reconcile=(next:CycleView)=>{const unknown=entry.value.unknown;if(!unknown)return;
    const matched=next.cycle.epoch>unknown.epoch&&(unknown.operation==='pause'?next.task.status==='paused':unknown.operation==='cancel'?next.task.status==='cancelled':['queued','generated','deliverable'].includes(next.task.status));
    if(matched)entry.set({unknown:null,notice:'已读取原协作的当前状态；没有重复发送控制。'});
  };
  const read=async()=>{
    if(!parentId||!id(parentId)||entry.value.readOwner)return;
    const owner={},origin=active;entry.set({readOwner:owner,view:null,stamp:null,error:'',briefNote:null});
    try{const value=await command('cycle.view',{id:parentId});if(!live.current||scope.current!==origin)return;
      const next=checkedView(value,project,parentId);entry.set({view:next,stamp:origin});reconcile(next);
    }catch(e){if(live.current&&scope.current===origin)entry.set({view:null,stamp:null,error:error(e)});}
    finally{if(entry.value.readOwner===owner)entry.set({readOwner:null});}
  };
  useEffect(()=>{live.current=true;return()=>{live.current=false;
    if(draft.value.phase==='pending')draft.set({phase:'unknown',notice:'原登记回包尚未确认；重新打开不会再次登记。'});
  };},[active]);
  useEffect(()=>{if(parentId&&authority)void read();},[active]);
  useEffect(()=>{if(!writable&&draft.value.preview)draft.set({preview:null,consent:''});},[active]);
  const update=(name:keyof Form,value:any)=>draft.set({form:{...d.form,[name]:value},consent:'',error:'',...(name==='request'||name==='additional'?{preview:null}:{})});
  const resolve=async()=>{
    if(locked||!writable||!d.form.request.trim())return;
    const owner={},f=copy(d.form),sig=sourceSignature,origin=active;draft.set({owner,error:'',consent:''});
    try{const value=await command('task.resolve',{...fields(f),...(d.preview?.signature===sig?{selected_materials:selected.map(({id,revision})=>({id,revision}))}:{})});
      if(!live.current||scope.current!==origin||JSON.stringify([project,draft.value.form.request,draft.value.form.additional])!==sig)return;
      const checked=resolution(value,project);draft.set({preview:{value:checked,signature:sig,selection:checked.materials.filter(m=>m.selected).map(key),verified:true}});
    }catch(e){if(live.current&&scope.current===origin)draft.set({preview:null,error:error(e)});}
    finally{if(draft.value.owner===owner)draft.set({owner:null});}
  };
  const submit=async()=>{
    if(locked||!ready||!d.preview||!limits)return;
    const intent:Intent={fields:{...fields(d.form),resolution_pin:copy(d.preview.value.pin),selected_materials:selected.map(({id,revision})=>({id,revision})),
      roles:copy(d.form.roles),limits,output_kind:d.form.output,background:d.form.background,constraints:d.form.constraints,acceptance:d.form.acceptance,
      unresolved:d.form.unresolved?[d.form.unresolved]:[],graph_growth:false,request_key:requestId()},materials:selected.map(({id,revision,sha256})=>({id,revision,sha256})),
      routes:Object.fromEntries(roles.map(r=>[r,providers.find(p=>p.id===d.form.roles[r])!.route])) as Record<Role,string>};
    const owner={},origin=active;draft.set({owner,phase:'pending',intent,error:'',notice:''});
    try{const value=await command('cycle.submit',intent.fields);if(!live.current||scope.current!==origin)return;
      const checked=checkedView(value,project);if(!sameIntent(checked.task,intent))throw Error('登记回包与原角色、预算或固定来源不符；原请求结果尚未确认。');
      draft.set({parent:checked.task.id,phase:'accepted',notice:'已登记原父协作；排队不代表已执行，候选与审查也不代表科学或用户验收。'});
    }catch(e){if(live.current&&scope.current===origin)draft.set({phase:'unknown',error:error(e),notice:'登记结果尚未确认；请核对原请求，不要再次建立协作。',
      ...(e instanceof CommandError&&e.code==='forbidden'?{preview:null,consent:''}:{})});}
    finally{if(draft.value.owner===owner)draft.set({owner:null,...(draft.value.phase==='pending'?{phase:'unknown' as const}:{})});}
  };
  const recoverRegistration=async()=>{
    if(d.owner||d.phase!=='unknown'||!d.intent||!writable)return;
    const owner={},origin=active,intent=d.intent;draft.set({owner,error:''});
    try{const response=await fetch('/api/state',{method:'GET',credentials:'same-origin'}),value=await response.json();if(!live.current||scope.current!==origin)return;
      if(!response.ok)throw new CommandError(value?.code,value?.error||'无法核对原登记请求',value?.details);
      if(!Array.isArray(value?.tasks))throw Error('任务列表回包不完整；原登记仍未确认。');
      const found=value.tasks.filter((t:any)=>t?.project_id===project&&t.request_key===intent.fields.request_key);
      if(found.length!==1||!id(found[0].id)||!sameIntent(found[0],intent))throw Error('尚未找到唯一且完整匹配的原登记；未释放原请求或再次派发。');
      const checked=checkedView(await command('cycle.view',{id:found[0].id}),project,found[0].id);if(!live.current||scope.current!==origin)return;
      if(!sameIntent(checked.task,intent))throw Error('原协作合同发生变化；未改用其他任务。');draft.set({parent:checked.task.id,phase:'accepted',notice:'已只读核对原请求对应的父协作；没有再次登记。'});
    }catch(e){if(live.current&&scope.current===origin)draft.set({error:error(e),...(e instanceof CommandError&&e.code==='forbidden'?{preview:null,consent:''}:{})});}
    finally{if(draft.value.owner===owner)draft.set({owner:null});}
  };
  const control=async(operation:'pause'|'cancel'|'resume')=>{
    if(!view||!writable||parentLocked||entry.value.readOwner||operation==='resume'&&authority?.runtimeRunning!==true)return;
    const owner={},origin=active,unknown={operation,epoch:view.cycle.epoch};entry.set({controlOwner:owner,unknown,error:'',notice:''});
    try{const value=await command('cycle.control',{id:view.task.id,operation});if(!live.current||scope.current!==origin)return;
      const checked=checkedView(value,project,view.task.id);entry.set({view:checked,stamp:origin,unknown:null,notice:'已读取实际控制回包；没有另建任务或扩额。'});
    }catch(e){if(live.current&&scope.current===origin){const rejected=e instanceof CommandError&&['csrf','unauthorized','forbidden','not_found','conflict'].includes(e.code);
      entry.set({error:error(e),...(rejected?{view:null,stamp:null,unknown:null}:{notice:'控制回包未知；先刷新原协作记录，不要重复控制。'})});}}
    finally{if(entry.value.controlOwner===owner)entry.set({controlOwner:null});}
  };
  const open=async(fn:()=>void|Promise<void>)=>{if(!current())return;try{await fn();}catch(e){if(current())entry.set({error:error(e)});}};
  const briefReady=!!view&&['generated','deliverable'].includes(view.task.status)&&!!view.cycle.final_source;
  const writeBrief=async()=>{
    if(!current()||!onOpenNote||!writable||!briefReady||!view||entry.value.briefOwner||entry.value.briefUnknown||entry.value.readOwner||parentLocked)return;
    const owner={},origin=active,expected:Ref=copy(view.cycle.final_source);
    let sent=false,confirmed=false;
    entry.set({briefOwner:owner,briefError:'',briefNote:null,view:null,stamp:null});
    const owned=()=>live.current&&scope.current===origin&&entry.value.briefOwner===owner;
    try{
      const next=checkedView(await command('cycle.view',{id:parentId}),project,parentId);
      if(!owned())return;
      const actual=next.cycle.final_source;
      if(!['generated','deliverable'].includes(next.task.status)||!actual||actual.id!==expected.id||actual.revision!==expected.revision||actual.sha256!==expected.sha256)
        throw Error('固定整合候选已变化；请刷新协作记录核对，未改用另一成果或修订。');
      const query=new URLSearchParams({revision:String(expected.revision),consumer:project});
      const response=await fetch('/api/objects/'+encodeURIComponent(expected.id)+'?'+query,{method:'GET',credentials:'same-origin'});
      const body=await response.json();if(!owned())return;
      if(!response.ok||body?.ok!==true)throw new CommandError(body?.code,typeof body?.error==='string'?body.error:'固定整合候选读取失败',body?.details);
      const source=body.result;
      if(!record(source)||source.id!==expected.id||source.project_id!==project||source.revision!==expected.revision||
        !['report','note'].includes(source.kind)||source.canonical_source_sha256!==expected.sha256)
        throw Error('整合候选的项目、类型、修订或规范 SHA-256 不符；未写入简报。');
      // This separately owned write remains locked through refresh/remount.
      // Current source/ACL are checked again by the server with this exact pin.
      sent=true;entry.set({briefUnknown:true});
      const result=await command('desk.task.brief',{project_id:project,task_id:parentId,expected_final_source:expected});
      if(!owned())return;
      const ref=actualTaskBrief(result,project);
      if(typeof result.appended!=='boolean'||ref.relative_path!=='notes/tasks/'+parentId+'.md')
        throw Error('简报回执与原父协作的笔记路径或追加状态不符；未打开其他笔记。');
      confirmed=true;entry.set({view:next,stamp:origin,briefUnknown:false,briefNote:ref});
      await onOpenNote(ref.relative_path);
    }catch(e){if(owned()){
      // This endpoint's conflict is a rejected pre-write final-source check.
      // notes_conflict/write failure and unknown transport remain locked.
      const rejected=e instanceof CommandError&&['csrf','unauthorized','forbidden','conflict'].includes(e.code);
      entry.set({briefError:error(e),briefUnknown:sent&&!confirmed&&!rejected,...(!confirmed?{view:null,stamp:null,briefNote:null}:{})});
    }}finally{if(entry.value.briefOwner===owner)entry.set({briefOwner:null});}
  };
  const dirty=!!s.paperDraft?.dirty||[...s.buffers.values()].some(b=>b.dirty)||Object.keys(s.figureDrafts).length>0||Object.keys(s.compositionDrafts).length>0||Object.keys(s.captionDrafts).length>0;
  return <section className="review-panel" aria-label="有限科研协作">
    <h2>有限科研协作</h2><p>围绕明确目的登记一轮规划、分工、审查与整合。使用现有队列，不代表完整项目托管已配置。</p>
    {!parentTaskId&&!d.parent&&<>
      {dirty&&<p role="status">当前手改保留；本协作只采用保存来源，不保存或发送这些草稿。</p>}
      <fieldset disabled={locked||!writable}><legend>新成果的有限协作</legend>
        <label>协作研究目的<textarea aria-label="协作研究目的" value={d.form.request} onChange={e=>update('request',e.target.value)}/></label>
        <label>协作产出类型<select aria-label="协作产出类型" value={d.form.output} onChange={e=>update('output',e.target.value)}><option value="report">报告</option><option value="note">笔记</option></select></label>
        <details><summary>保存来源与研究边界</summary>
          <label>补充协作来源<textarea aria-label="补充协作来源" value={d.form.additional} onChange={e=>update('additional',e.target.value)}/></label>
          {(['background','constraints','acceptance','unresolved'] as const).map((name,i)=><label key={name}>{['协作背景','协作边界','协作检查条件','协作未决事项'][i]}<textarea aria-label={['协作背景','协作边界','协作检查条件','协作未决事项'][i]} value={d.form[name]} onChange={e=>update(name,e.target.value)}/></label>)}
        </details>
        <button disabled={!!d.owner||!d.form.request.trim()} onClick={()=>void resolve()}>解析协作保存来源</button>
        {d.preview&&writable&&<section aria-label="协作保存来源"><h3>采用的保存来源</h3>
          {d.preview.value.materials.map(m=><article key={key(m)}><label><input type="checkbox" aria-label={'协作采用来源 '+key(m)} checked={d.preview!.selection.includes(key(m))} onChange={e=>draft.set({preview:{...d.preview!,verified:false,selection:e.target.checked?[...d.preview!.selection,key(m)]:d.preview!.selection.filter(x=>x!==key(m))},consent:''})}/>{m.title} · r{m.revision}</label><p>{m.reason}；当前 r{m.current_revision}，本次固定 r{m.revision}</p><details><summary>固定来源身份</summary><p>{m.id} · {m.sha256} · {m.bytes} UTF-8 字节</p></details></article>)}
          {d.preview.value.ambiguities.map((x,i)=><p role="status" key={i}>{x.label}</p>)}{d.preview.value.gaps.map((x,i)=><p key={i}>{x}</p>)}
          {!d.preview.verified&&<p role="status">选择已改变，请重新解析后确认。</p>}{!selected.length&&<p role="status">此入口需要至少一项保存来源；尚未开放无材料登记。</p>}
          <p>已选 {selected.length} / {d.preview.value.limits.max_materials} 项；{selected.reduce((n,m)=>n+m.bytes,0)} / {d.preview.value.limits.max_bytes} UTF-8 字节。不截断正文。</p>
        </section>}
        <fieldset><legend>明确角色与有限额度</legend>{roles.map(role=><label key={role}>{roleNames[role]}<select aria-label={roleNames[role]} value={d.form.roles[role]} onChange={e=>update('roles',{...d.form.roles,[role]:e.target.value})}><option value="">选择已有授权路线</option>{providers.map(p=><option key={p.id} value={p.id} disabled={!configured(p.id)}>{p.id} · {p.route}{!p.authorized?' · 未授权':''}</option>)}</select></label>)}
          {(Object.keys(limitNames) as (keyof Limits)[]).map(name=><label key={name}>{limitNames[name]}<input type="number" aria-label={limitNames[name]} min={name==='max_rework'?0:0.001} step={name.includes('seconds')?'any':1} value={d.form.limits[name]} onChange={e=>update('limits',{...d.form.limits,[name]:e.target.value})}/></label>)}
          {!limits&&<p role="alert">需要完整有限预算：总调用 1–100、步骤 1–24、返工 0–1、单步骤调用 1–10；总时限最多 7200 秒、单步骤最多 900 秒，子额度不能超过父额。</p>}
        </fieldset>
        <p>本入口不联网检索、不增长图谱、不改已有目标。角色选择不增加数据、工具或科学授权。同一路线的不同上下文不是跨模型共识。</p>
        <p>子任务按额度预分配，未用分配不退回；有限调用和秒数不代表费用上限。实际账单未知，候选不自动采用。</p>
        <label><input type="checkbox" aria-label="确认有限协作范围与预算" checked={d.consent===confirmation} disabled={!sourceReady||!limits||!roles.every(r=>configured(d.form.roles[r]))} onChange={e=>draft.set({consent:e.target.checked?confirmation:''})}/>确认以上保存来源、角色与有限额度；点击登记后可由真实执行器推进。</label>
      </fieldset>
      {authority?.runtimeRunning!==true&&<p role="status">执行器未运行；后端具备登记能力，本入口当前不开放执行登记。</p>}
      {!writable&&<p role="status">当前项目写权限尚未确认或不可用；未开放登记。</p>}
      <button disabled={locked||!ready} onClick={()=>void submit()}>登记新的有限协作</button>
      {d.phase==='unknown'&&<button disabled={!!d.owner||!writable} onClick={()=>void recoverRegistration()}>核对原登记请求</button>}
    </>}
    {d.error&&!parentTaskId&&<p role="alert">{d.error}</p>}{d.notice&&!parentTaskId&&<p role="status">{d.notice}</p>}
    {parentId&&<>
      <button disabled={!!entry.value.readOwner||!!entry.value.controlOwner||!!entry.value.briefOwner||!authority} onClick={()=>void read()}>刷新协作记录</button>
      {entry.value.readOwner&&<p role="status">正在读取此父协作的实际记录…</p>}{entry.value.error&&<p role="alert">{entry.value.error}</p>}
      {entry.value.notice&&<p role="status">{entry.value.notice}</p>}{entry.value.unknown&&<p role="status">原控制结果尚未确认；只读取原协作，不重复发送。</p>}
      {entry.value.briefOwner&&<p role="status">正在核对固定候选并写入原生任务简报…</p>}
      {entry.value.briefError&&<p role="alert">{entry.value.briefError}</p>}
      {entry.value.briefUnknown&&<p role="status">原简报写入结果尚未确认；请核对原生笔记，不要重复提交。</p>}
      {view&&<><p>父协作任务：{view.task.id}</p><p>实际状态：{view.task.status}</p><p>{phases[view.cycle.phase]||view.cycle.phase} · 返工 {view.cycle.round} / {view.task.payload.cycle_config.limits.max_rework}</p>
        <p>{view.task.payload.request}</p>{view.cycle.last_failure&&<p role="alert">{String(view.cycle.last_failure.message)}</p>}
        {stop&&<section aria-label="协作执行停止状态"><h3>执行停止观测</h3>
          <p role="status">{stopLabels[stop.value?.status??'unknown']}</p>
          {stop.invalid&&<p role="alert">停止观测身份或字段不完整；未认定执行已停止。</p>}
          {!stop.value&&<p>当前任务状态不能单独证明本地执行已停止；请显式刷新协作记录核对。</p>}
          {stop.value&&<><p>已阻止本协作新派发。</p>{stop.value.children.map(row=><article key={row.id} aria-label={'子任务执行停止 '+row.id}>
            <h4>{row.id}</h4><p>子任务本地执行：{stopLabels[row.status]}</p><p style={{whiteSpace:'pre-wrap'}}>{row.reason}</p>
          </article>)}</>}
          <p className="quiet">仅观测本地执行与进程收尾；远端模型是否停止计费及未知回执仍按原记录核对。此处不自动控制或轮询。</p>
        </section>}
        <p>排队不代表已执行；候选、独立审查与科学或用户验收分别保留。</p>
        {onOpenTask&&<button onClick={()=>void open(()=>onOpenTask({id:view.task.id,project_id:project}))}>打开父协作任务记录</button>}
        {writable&&!['generated','deliverable','cancelled'].includes(view.task.status)&&<>
          {view.task.status!=='paused'&&<button disabled={parentLocked||!!entry.value.readOwner} onClick={()=>void control('pause')}>暂停此协作</button>}
          {['paused','failed','waiting_input','waiting_resource','waiting_authorization'].includes(view.task.status)&&<button disabled={parentLocked||!!entry.value.readOwner||authority?.runtimeRunning!==true} onClick={()=>void control('resume')}>继续此协作</button>}
          <button disabled={parentLocked||!!entry.value.readOwner} onClick={()=>void control('cancel')}>取消此协作</button>
          <p>暂停与取消作用于原父协作及未终态子任务。继续不扩额；已尝试的子任务仍须单独明确接续其原会话。</p>
        </>}
        <section aria-label="协作预算与实际记录"><h3>预算与实际记录</h3><p>已分配调用额度 {view.cycle.reserved_calls} / {view.task.payload.cycle_config.limits.max_model_calls}；秒数 {view.cycle.reserved_seconds} / {view.task.payload.cycle_config.limits.timeout_seconds}；步骤 {view.cycle.steps_used} / {view.task.payload.cycle_config.limits.max_steps}。</p>
          <p>已登记 Codex 调用 {measured(view.actual_consumption.codex_cli_invocations)}；Harness 调用 {measured(view.actual_consumption.deepseek_harness_invocations)}。调用计数不代表内部 API 次数或实际费用。</p>
          <p>已结算耗时 {measured(view.actual_consumption.settled_elapsed_seconds)} 秒；在途预留 {measured(view.actual_consumption.reserved_seconds)} 秒；实际耗时未知的扣留 {measured(view.actual_consumption.uncertain_charged_seconds)} 秒。</p><p>{view.accounting_note}</p>
        </section>
        <section aria-label="协作子任务"><h3>分工与当前返回</h3>{!view.children.length&&<p>尚无已登记子任务；没有返回不等于研究完成。</p>}
          {view.children.map(row=><article key={row.id}><h4>{roleNames[row.role as Role]||row.role} · {row.id}</h4><p>实际状态：{row.task.status} · 路线：{row.route}</p>{onOpenTask&&<button onClick={()=>void open(()=>onOpenTask({id:row.id,project_id:project}))}>打开子任务 {row.id}</button>}
            {row.candidate&&<details><summary>此子任务保存的候选</summary><p>{String(row.candidate.title||'')}</p>{Array.isArray(row.candidate.content?.blocks)&&row.candidate.content.blocks.map((b:any,i:number)=><p key={i} style={{whiteSpace:'pre-wrap'}}>{typeof b?.text==='string'?b.text:''}</p>)}<pre>{JSON.stringify({candidate_sha256:row.candidate.candidate_sha256,contract:row.contract},null,2)}</pre></details>}
          </article>)}
        </section>
        {view.cycle.final_source&&onOpenReference&&<button onClick={()=>void open(()=>onOpenReference({id:view.cycle.final_source.id,revision:view.cycle.final_source.revision,sha256:view.cycle.final_source.sha256,consumer_id:project}))}>打开固定整合候选</button>}
        {onOpenNote&&<><button disabled={!writable||!briefReady||!!entry.value.briefOwner||entry.value.briefUnknown||!!entry.value.readOwner||parentLocked} onClick={()=>void writeBrief()}>将任务回报记入项目笔记并打开</button>
          <p className="quiet">仅整理此父协作与固定成果；保留原论述、限制和实际任务引用，不启动任务或代表采用与科学批准。</p></>}
        {entry.value.briefNote&&onOpenNote&&<p>原生简报 {entry.value.briefNote.id} · {entry.value.briefNote.relative_path}<button disabled={!!entry.value.briefOwner} onClick={()=>void open(()=>onOpenNote(entry.value.briefNote!.relative_path))}>打开已登记简报</button></p>}
        <details><summary>冻结来源、阶段与意见交接</summary><pre>{JSON.stringify({roles:view.task.payload.cycle_config.roles,limits:view.task.payload.cycle_config.limits,materials:view.task.payload.context.materials,history:view.cycle.history,parent_inputs_current:view.parent_inputs_current,integration_inputs:view.integration_inputs},null,2)}</pre><p>{view.handoff_meaning}</p></details>
        <details><summary>完整协作返回字段</summary><pre>{JSON.stringify(view,null,2)}</pre></details>
        {!parentTaskId&&d.phase==='accepted'&&<button disabled={!!entry.value.controlOwner||!!entry.value.readOwner} onClick={()=>draft.set({parent:null,phase:'idle',intent:null,preview:null,consent:'',error:'',notice:''})}>整理另一轮有限协作</button>}
      </>}
    </>}
  </section>;
}
