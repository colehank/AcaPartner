import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {command,CommandError,readTask} from './api';
import type {Session} from './session';

type TaskRef={id:string,project_id:string};
type SourceRef={id:string,revision:number,consumer_id:string};
type Task=TaskRef&{status:string,payload:{request?:string,kind?:string}};
type Source={kind:'artifact',id:string,revision:number,current_revision?:number,unavailable?:boolean,stale:boolean}|
  {kind:'candidate',task_id:string,sha256:string,current_sha256?:string|null,stale:boolean};
type Question={id:string,project_id:string,kind:'question',title:string,revision:number,archived?:boolean,
  content:Record<string,any>,question_view:{scope:string,source_bound:boolean,source_valid:boolean,source_stale:boolean,sources:Source[],base_sources:Source[]}};
type Snapshot={question:Question,tasks:Task[],writable:boolean};
type Props={session:Session,questionId:string,report:(error:unknown)=>void,
  onOpenReference?:(ref:SourceRef)=>Promise<void>|void,onOpenTask?:(ref:TaskRef)=>Promise<void>|void};
type Intent={question:Question,task:Task,blocking:boolean};
type Phase='idle'|'checking'|'sending'|'unknown'|'confirmed';
type Draft={taskId:string,mode:''|'blocking'|'reference',approved:boolean,phase:Phase,intent?:Intent,error:string,notice:string};
type Memory={value:Draft,version:number,listeners:Set<()=>void>,set:(patch:Partial<Draft>)=>void,
  subscribe:(listener:()=>void)=>()=>void,snapshot:()=>number};
const memories=new WeakMap<Session,Map<string,Memory>>();
const eligible=new Set(['queued','paused','waiting_input','waiting_resource','waiting_authorization','failed']);
const followupScopes=new Set(['followup','optional','historical']);
const record=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const ident=(value:any)=>typeof value==='string'&&!!value&&!/[\s/\\\u0000-\u001f]/u.test(value);
const positive=(value:any)=>Number.isSafeInteger(value)&&value>0;
const sha=(value:any)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const errorText=(error:unknown)=>error instanceof Error?error.message:String(error);
const stable=(value:any):any=>Array.isArray(value)?value.map(stable):record(value)?Object.fromEntries(Object.keys(value).sort().map(key=>[key,stable(value[key])])):value;
const equal=(a:any,b:any)=>JSON.stringify(stable(a))===JSON.stringify(stable(b));

function memoryFor(session:Session,questionId:string):Memory {
  let questions=memories.get(session);if(!questions){questions=new Map();memories.set(session,questions);}
  const key=JSON.stringify([session.project.id,questionId]),existing=questions.get(key);if(existing)return existing;
  const memory:Memory={value:{taskId:'',mode:'',approved:false,phase:'idle',error:'',notice:''},version:0,listeners:new Set(),
    set(patch){memory.value={...memory.value,...patch};memory.version++;for(const listener of memory.listeners)listener();},
    subscribe(listener){memory.listeners.add(listener);return()=>{memory.listeners.delete(listener);};},snapshot:()=>memory.version};
  questions.set(key,memory);return memory;
}
function checkedSource(source:any):Source {
  if(!record(source)||typeof source.stale!=='boolean')throw Error('问题来源状态不完整；未开放关联。');
  if(source.kind==='artifact'&&ident(source.id)&&positive(source.revision)&&
    (source.current_revision===undefined||positive(source.current_revision))&&
    (source.unavailable===undefined||typeof source.unavailable==='boolean'))return source;
  if(source.kind==='candidate'&&ident(source.task_id)&&sha(source.sha256)&&
    (source.current_sha256===undefined||source.current_sha256===null||sha(source.current_sha256)))return source;
  throw Error('问题来源身份不完整；未开放关联。');
}
function checkedQuestion(value:any,project:string,id:string):Question {
  if(!record(value)||value.id!==id||value.project_id!==project||value.kind!=='question'||!positive(value.revision)||
    typeof value.title!=='string'||!record(value.content)||value.archived!==undefined&&typeof value.archived!=='boolean')
    throw Error('问题身份、项目或修订不符；未显示其他问题。');
  const c=value.content,v=value.question_view;
  if(!record(v)||typeof v.scope!=='string'||!['source_bound','source_valid','source_stale'].every(key=>typeof v[key]==='boolean')||
    !Array.isArray(v.sources)||!Array.isArray(v.base_sources)||!Array.isArray(c.options??[]))throw Error('问题与来源状态不完整；未开放关联。');
  for(const key of ['background','recommendation','answer','answered_at','status','disposition','scope'])
    if(c[key]!==undefined&&c[key]!==null&&typeof c[key]!=='string')throw Error('问题正文或已有决定字段无效；未省略后显示。');
  if(c.blocking!==undefined&&typeof c.blocking!=='boolean')throw Error('问题关联模式无效。');
  for(const option of c.options??[])
    if(typeof option!=='string'&&(!record(option)||!ident(option.id)||typeof option.label!=='string'||typeof option.consequence!=='string'))
      throw Error('原建议选项结构无效；未省略选项。');
  for(const key of ['bound_task_id','task_id','origin_task_id'])if(c[key]!==undefined&&c[key]!==null&&!ident(c[key]))throw Error('问题的任务身份无效。');
  v.sources.forEach(checkedSource);v.base_sources.forEach(checkedSource);
  return structuredClone(value);
}
function checkedTask(value:any,project:string,id?:string):Task {
  if(!record(value)||!ident(value.id)||value.project_id!==project||id!==undefined&&value.id!==id||
    typeof value.status!=='string'||!record(value.payload)||
    ['request','kind'].some(key=>value.payload[key]!==undefined&&typeof value.payload[key]!=='string'))throw Error('后续 Task 身份或内容不完整。');
  return {id:value.id,project_id:project,status:value.status,payload:{request:value.payload.request,kind:value.payload.kind}};
}
function checkedState(value:any,project:string){
  if(!record(value)||!Array.isArray(value.projects)||!value.projects.some((p:any)=>p?.id===project)||!Array.isArray(value.tasks))
    throw Error('当前项目或任务目录不可核对；未显示旧目录。');
  const authority=value.project_management;
  if(!record(authority)||typeof authority.can_create!=='boolean'||!Array.isArray(authority.writable_project_ids)||authority.writable_project_ids.some((id:any)=>!ident(id)))
    throw Error('当前项目写入权限不完整；未推定可关联。');
  const tasks=value.tasks.filter((task:any)=>task?.project_id===project).map((task:any)=>checkedTask(task,project));
  if(new Set(tasks.map((task:Task)=>task.id)).size!==tasks.length)throw Error('本项目 Task 身份重复；请重新读取。');
  return {tasks,writable:authority.can_create||authority.writable_project_ids.includes(project)};
}
async function get(path:string,signal?:AbortSignal,envelope=true){
  const response=await fetch(path,{method:'GET',credentials:'same-origin',signal}),value=await response.json();
  if(!response.ok||envelope&&value?.ok!==true)throw new CommandError(value?.code,typeof value?.error==='string'?value.error:'问题或任务不可读取',value?.details);
  return envelope?value.result:value;
}
async function snapshot(project:string,id:string,signal?:AbortSignal):Promise<Snapshot>{
  const [question,state]=await Promise.all([get('/api/objects/'+encodeURIComponent(id)+'?consumer='+encodeURIComponent(project),signal),get('/api/state',signal,false)]);
  return {question:checkedQuestion(question,project,id),...checkedState(state,project)};
}
function allowed(question:Question){
  return !question.archived&&followupScopes.has(question.content.scope)&&question.question_view.source_bound&&question.question_view.source_valid;
}
function sameQuestion(a:Question,b:Question){return a.id===b.id&&a.project_id===b.project_id&&a.revision===b.revision&&
  a.title===b.title&&!!a.archived===!!b.archived&&equal(a.content,b.content)&&equal(a.question_view,b.question_view);}
function matchesBinding(question:Question,intent:Intent){
  const before=intent.question,c=question.content,binding=c.binding;
  if(question.id!==before.id||question.project_id!==before.project_id||question.revision!==before.revision+1||question.title!==before.title||
    !!question.archived!==!!before.archived||c.bound_task_id!==intent.task.id||c.task_id!==intent.task.id||c.blocking!==intent.blocking||
    !record(binding)||binding.task_id!==intent.task.id||binding.question_revision!==before.revision||binding.permissions_changed!==false||typeof binding.at!=='string'||!binding.at)return false;
  return equal(c,{...before.content,bound_task_id:intent.task.id,task_id:intent.task.id,blocking:intent.blocking,binding});
}

/** Read original suggestions and explicitly associate one existing Task. Never answers or resumes it. */
export function QuestionFollowupPanel({session:s,questionId,report,onOpenReference,onOpenTask}:Props){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const memory=memoryFor(s,questionId);useSyncExternalStore(memory.subscribe,memory.snapshot);
  const scope=useRef({session:s,project:s.project.id,id:questionId,memory});
  if(scope.current.session!==s||scope.current.project!==s.project.id||scope.current.id!==questionId)scope.current={session:s,project:s.project.id,id:questionId,memory};
  const active=scope.current,live=useRef(false),serial=useRef(0),controller=useRef<AbortController|null>(null),explicitRead=useRef(false);
  const [reading,setReading]=useState<{scope:typeof active,value?:Snapshot,error?:string}|null>(null);
  const [reload,setReload]=useState(0),[opening,setOpening]=useState(false);
  const {taskId,mode,approved,phase,error,notice,intent}=memory.value;
  const pending=phase==='checking'||phase==='sending',unknown=phase==='unknown';
  useEffect(()=>{
    live.current=true;const origin=active,ticket=++serial.current,abort=new AbortController(),reconcile=explicitRead.current;controller.current=abort;explicitRead.current=false;
    const current=()=>live.current&&scope.current===origin&&serial.current===ticket;
    setReading(null);setOpening(false);origin.memory.set({approved:false});
    void snapshot(origin.project,origin.id,abort.signal).then(value=>{
      if(!current())return;
      setReading({scope:origin,value});
      const previous=origin.memory.value;
      if(reconcile&&previous.phase==='unknown'&&previous.intent&&matchesBinding(value.question,previous.intent))
        origin.memory.set({phase:'confirmed',error:'',notice:'已从当前问题读回确认原关联；未再次提交。',approved:false});
    }).catch(error=>{if(current()){setReading({scope:origin,error:errorText(error)});report(error);}});
    return()=>{live.current=false;++serial.current;abort.abort();};
  },[s,s.project.id,questionId,reload]);
  const currentReading=reading?.scope===active?reading:null,value=currentReading?.value,question=value?.question;
  const tasks=value?.tasks.filter(task=>eligible.has(task.status))||[],selected=tasks.find(task=>task.id===taskId);
  const already=!!question&&question.content.bound_task_id===taskId&&question.content.blocking===(mode==='blocking');
  const ready=!!question&&value?.writable&&allowed(question)&&!!selected&&!!mode&&approved&&!already&&!pending&&!unknown;
  const refresh=()=>{if(pending)return;++serial.current;controller.current?.abort();explicitRead.current=true;setReading(null);memory.set({approved:false,error:'',notice:''});setReload(n=>n+1);};
  const bind=async()=>{
    if(!ready||memory.value.phase==='checking'||memory.value.phase==='sending'||!question||!selected)return;
    const origin=active,ticket=++serial.current,request:Intent={question:structuredClone(question),task:structuredClone(selected),blocking:mode==='blocking'};
    const current=()=>live.current&&scope.current===origin&&serial.current===ticket;
    origin.memory.set({phase:'checking',intent:request,approved:false,error:'',notice:''});
    let sent=false;
    try{
      const [fresh,task]=await Promise.all([snapshot(origin.project,origin.id),readTask(request.task.id)]);
      if(!current()){origin.memory.set({phase:'idle',intent:undefined});return;}
      const target=checkedTask(task,origin.project,request.task.id);
      if(!sameQuestion(fresh.question,request.question))throw Error('问题、已有决定或来源状态已变化；请刷新后重新选择。');
      if(!fresh.writable)throw new CommandError('forbidden','当前项目只读；未提交关联。',null);
      if(!allowed(fresh.question)||!eligible.has(target.status)||!fresh.tasks.some(t=>t.id===target.id)||!equal(target,request.task))
        throw Error('来源或所选 Task 状态已变化；请刷新后重新选择。');
      origin.memory.set({phase:'sending'});sent=true;
      const response=await command('question.bind',{id:origin.id,expected_revision:request.question.revision,task_id:request.task.id,blocking:request.blocking,approved:true});
      const bound=checkedQuestion(response,origin.project,origin.id);
      if(!matchesBinding(bound,request))throw Error('关联回执与原问题、Task 或关联模式不符；结果尚未确认。');
      origin.memory.set({phase:'confirmed',error:'',notice:'关联已登记；原科学选项与已有决定保持。未创建或接续 Task。'});
      if(current())setReading({scope:origin,value:{...fresh,question:bound}});
    }catch(error){
      // server.post_body rejects CSRF before calling App dispatch.
      const rejected=error instanceof CommandError&&['csrf','forbidden','unauthorized','conflict','not_found','authorization_required'].includes(error.code);
      origin.memory.set({phase:sent&&!rejected?'unknown':'idle',error:errorText(error),approved:false,...(!sent||rejected?{intent:undefined}:{})});
      if(current()){setReading({scope:origin,error:errorText(error)});report(error);}
    }
  };
  const navigate=async(action:()=>Promise<void>|void)=>{
    if(opening||pending)return;const origin=active;setOpening(true);memory.set({error:''});
    try{await action();}catch(error){if(live.current&&scope.current===origin){memory.set({error:errorText(error)});report(error);}}
    finally{if(live.current&&scope.current===origin)setOpening(false);}
  };
  const sources=(items:Source[],label:string)=><section aria-label={label}><h4>{label}</h4>{items.length?items.map((source,index)=><div key={index}>
    {source.kind==='artifact'?<><p>{source.id} · 固定 r{source.revision}{source.current_revision!==undefined?` · 当前 r${source.current_revision}`:''}{source.unavailable?' · 当前不可读取':source.stale?' · 来源已变化':''}</p>
      {onOpenReference&&!source.unavailable&&<button disabled={opening||pending} onClick={()=>void navigate(()=>onOpenReference({id:source.id,revision:source.revision,consumer_id:active.project}))}>读取固定来源 {source.id} r{source.revision}</button>}</>:
      <p>原候选 Task：{source.task_id}<br/>固定 SHA：{source.sha256}{source.stale?' · 候选已变化':''}</p>}
  </div>):<p>未登记。</p>}</section>;
  return <section className="review-panel" aria-label={'后续问题 '+questionId}>
    <div className="panel-tools"><h2>后续问题与任务关联</h2><button disabled={pending} onClick={refresh}>刷新问题与可关联任务</button></div>
    <p>原建议选项与已有决定只读。本操作只关联既存 Task；不采用科学建议，不增加权限或预算。</p>
    {!currentReading&&<p role="status">正在读取问题、当前来源状态与本项目任务…</p>}
    {(currentReading?.error||error)&&<p role="alert">{currentReading?.error||error}</p>}
    {notice&&<p role="status">{notice}</p>}
    {pending&&<p role="status">{phase==='checking'?'正在重新核对问题与 Task…':'关联请求已发送，正在核对回执…'}</p>}
    {unknown&&<p role="status">原关联结果尚未确认；请刷新读取当前问题，确认前不会再次提交。{intent&&` 原目标 ${intent.task.id}，${intent.blocking?'必要前置决定':'仅关联不阻断'}，基于问题 r${intent.question.revision}。`}</p>}
    {question&&<>
      <h3>{question.title}</h3><p>{question.id} · 当前 r{question.revision} · {question.question_view.scope}{question.archived?' · 已归档':''}</p>
      <h4>问题背景</h4><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{question.content.background??'未登记。'}</p>
      <h4>原建议选项（只读）</h4><ol>{(question.content.options??[]).map((option:any,index:number)=><li key={index}>
        <p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{typeof option==='string'?option:option.label}</p>
        {typeof option!=='string'&&<><small>选项 {option.id}</small><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>后果：{option.consequence}</p></>}
      </li>)}</ol>{!(question.content.options??[]).length&&<p>未登记选项。</p>}
      <h4>原建议及限制</h4><p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{question.content.recommendation??'未登记。'}</p>
      <h4>已有决定（只读）</h4><p>状态：{question.content.status??'未登记'} · 处置：{question.content.disposition??'未登记'}</p>
      <p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>原回答：{question.content.answer??'尚无回答'}</p>
      {question.content.answered_at&&<p>回答时间：{question.content.answered_at}</p>}
      {question.content.inherited_answer&&<details><summary>原继承回答</summary><pre>{JSON.stringify(question.content.inherited_answer,null,2)}</pre></details>}
      {sources(question.question_view.sources,'问题固定来源')}{question.question_view.base_sources.length>0&&sources(question.question_view.base_sources,'候选原基线')}
      {!question.question_view.source_bound&&<p role="status">尚无可核对的固定来源；当前不能关联。</p>}
      {!question.question_view.source_valid&&<p role="status">问题来源已变化或不可用；需另行明确重新评估，当前不能关联。</p>}
      {question.content.bound_task_id&&<p>当前已关联：{question.content.bound_task_id} · {question.content.blocking?'必要前置决定':'仅关联不阻断'}
        {onOpenTask&&<button disabled={opening||pending} onClick={()=>void navigate(()=>onOpenTask({id:question.content.bound_task_id,project_id:active.project}))}>打开已关联 Task</button>}</p>}
      {!value!.writable&&<p role="status">当前项目只读；可阅读问题，不能改变关联。</p>}
      {!followupScopes.has(question.content.scope)&&<p role="status">此问题已有当前任务作用域；本入口只关联后续、可选或历史问题。</p>}
      <fieldset disabled={pending||unknown||!value!.writable||!allowed(question)}>
        <legend>显式关联既存后续 Task</legend>
        <label>同项目后续 Task<select aria-label="同项目后续 Task" value={taskId} onChange={e=>memory.set({taskId:e.target.value,approved:false,notice:'',error:''})}>
          <option value="">请选择已有 Task</option>{tasks.map(task=><option key={task.id} value={task.id}>{task.id} · {task.status}</option>)}</select></label>
        {!tasks.length&&<p>当前没有状态允许关联的同项目 Task。</p>}
        {selected&&<p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>该 Task 原委托：{selected.payload.request??'未登记'}</p>}
        <label>关联模式<select aria-label="关联模式" value={mode} onChange={e=>memory.set({mode:e.target.value as Draft['mode'],approved:false,notice:'',error:''})}>
          <option value="">请选择关联模式</option><option value="blocking">必要前置决定</option><option value="reference">仅关联不阻断</option></select></label>
        {mode==='blocking'&&<p>此问题将成为该 Task 的前置决定；未答、暂缓、拒绝或来源过期可能阻止其执行。已有回答保持，本操作不回答问题，也不接续 Task。</p>}
        {mode==='reference'&&<p>仅登记关联，不把此问题作为该 Task 的执行阻断条件；不改变原回答或授予执行权限。</p>}
        <label><input type="checkbox" aria-label="确认此次任务关联" checked={approved} disabled={!selected||!mode||already} onChange={e=>memory.set({approved:e.target.checked})}/>我确认上述 Task 与关联模式，保留原科学选项和已有决定。</label>
        <button disabled={!ready} onClick={()=>void bind()}>确认关联已有 Task</button>
        {already&&<p>当前已登记相同关联，无需重复提交。</p>}
      </fieldset>
    </>}
  </section>;
}
