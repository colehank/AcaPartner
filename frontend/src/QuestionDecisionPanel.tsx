import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {command,CommandError,readTask} from './api';
import type {Session} from './session';

type TaskRef={id:string,project_id:string};
type SourceRef={id:string,revision:number,consumer_id:string};
type Task=TaskRef&{status:string,payload:Record<string,any>,attempts?:number,error?:string|null,result?:any};
type Source={kind:'artifact',id:string,revision:number,current_revision?:number,unavailable?:boolean,stale:boolean}|
  {kind:'candidate',task_id:string,sha256:string,current_sha256?:string|null,stale:boolean};
type Question={id:string,project_id:string,kind:'question',title:string,revision:number,archived?:boolean,
  content:Record<string,any>,question_view:{scope:string,source_bound:boolean,source_valid:boolean,source_stale:boolean,sources:Source[],base_sources:Source[]}};
type Snapshot={question:Question,tasks:Task[],writable:boolean};
export type QuestionDecisionPanelProps={session:Session,questionId:string,report:(error:unknown)=>void,
  onOpenReference?:(ref:SourceRef)=>Promise<void>|void,onOpenTask?:(ref:TaskRef)=>Promise<void>|void,
  onDecisionRecorded?:(taskIds:readonly string[])=>void};
type Disposition=''|'continue'|'deny'|'defer';
type Intent={snapshot:Snapshot,answer:string,disposition:Exclude<Disposition,''>,mode:'answer'|'reassess',reason:string};
type Draft={answer:string,disposition:Disposition,mode:'answer'|'reassess',reason:string,approved:boolean,
  phase:'idle'|'checking'|'sending'|'unknown'|'confirmed',intent?:Intent,error:string,notice:string,readVersion:number};
type Memory={value:Draft,version:number,listeners:Set<()=>void>,set:(patch:Partial<Draft>)=>void,
  subscribe:(listener:()=>void)=>()=>void,snapshot:()=>number};
const memories=new WeakMap<Session,Map<string,Memory>>();
const record=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const ident=(value:any)=>typeof value==='string'&&!!value&&!/[\s/\\\u0000-\u001f]/u.test(value);
const positive=(value:any)=>Number.isSafeInteger(value)&&value>0;
const sha=(value:any)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const errorText=(error:unknown)=>error instanceof Error?error.message:String(error);
const stable=(value:any):any=>Array.isArray(value)?value.map(stable):record(value)?Object.fromEntries(Object.keys(value).sort().map(key=>[key,stable(value[key])])):value;
const equal=(a:any,b:any)=>JSON.stringify(stable(a))===JSON.stringify(stable(b));

function checkedSource(source:any):Source {
  if(!record(source)||typeof source.stale!=='boolean')throw Error('问题来源状态不完整；未开放决定。');
  if(source.kind==='artifact'&&ident(source.id)&&positive(source.revision)&&
    (source.current_revision===undefined||positive(source.current_revision))&&
    (source.unavailable===undefined||typeof source.unavailable==='boolean'))return source;
  if(source.kind==='candidate'&&ident(source.task_id)&&sha(source.sha256)&&
    (source.current_sha256===undefined||source.current_sha256===null||sha(source.current_sha256)))return source;
  throw Error('问题来源身份不完整；未开放决定。');
}
function checkedQuestion(value:any,project:string,id:string):Question {
  if(!record(value)||value.id!==id||value.project_id!==project||value.kind!=='question'||!positive(value.revision)||
    typeof value.title!=='string'||!record(value.content)||value.archived!==undefined&&typeof value.archived!=='boolean')
    throw Error('问题身份、项目或修订不符；未显示其他问题。');
  const c=value.content,v=value.question_view;
  if(!record(v)||typeof v.scope!=='string'||!['source_bound','source_valid','source_stale'].every(key=>typeof v[key]==='boolean')||
    !Array.isArray(v.sources)||!Array.isArray(v.base_sources)||!Array.isArray(c.options??[]))throw Error('问题与来源状态不完整；未开放决定。');
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
    ['request','kind'].some(key=>value.payload[key]!==undefined&&typeof value.payload[key]!=='string'))throw Error('目标 Task 身份或内容不完整。');
  return structuredClone({id:value.id,project_id:project,status:value.status,payload:value.payload,attempts:value.attempts,error:value.error,result:value.result});
}
function checkedState(value:any,project:string){
  if(!record(value)||!Array.isArray(value.projects)||!value.projects.some((p:any)=>p?.id===project)||!Array.isArray(value.tasks))
    throw Error('当前项目或任务目录不可核对；未显示旧目录。');
  const authority=value.project_management;
  if(!record(authority)||typeof authority.can_create!=='boolean'||!Array.isArray(authority.writable_project_ids)||authority.writable_project_ids.some((id:any)=>!ident(id)))
    throw Error('当前项目写入权限不完整；未推定可回答。');
  const tasks=value.tasks.filter((task:any)=>task?.project_id===project).map((task:any)=>checkedTask(task,project));
  if(new Set(tasks.map((task:Task)=>task.id)).size!==tasks.length)throw Error('本项目 Task 身份重复；请重新读取。');
  return {tasks,writable:!value.projects.find((p:any)=>p.id===project)?.archived&&(authority.can_create||authority.writable_project_ids.includes(project))};
}

function memoryFor(session:Session,id:string):Memory {
  let questions=memories.get(session);if(!questions){questions=new Map();memories.set(session,questions);}
  const key=JSON.stringify([session.project.id,id]),existing=questions.get(key);if(existing)return existing;
  const memory:Memory={value:{answer:'',disposition:'',mode:'answer',reason:'',approved:false,phase:'idle',error:'',notice:'',readVersion:0},version:0,listeners:new Set(),
    set(patch){memory.value={...memory.value,...patch};memory.version++;for(const listener of memory.listeners)listener();},
    subscribe(listener){memory.listeners.add(listener);return()=>{memory.listeners.delete(listener);};},snapshot:()=>memory.version};
  questions.set(key,memory);return memory;
}
async function get(path:string,signal?:AbortSignal,envelope=true){
  const response=await fetch(path,{method:'GET',credentials:'same-origin',signal}),value=await response.json();
  if(!response.ok||envelope&&value?.ok!==true)throw new CommandError(value?.code,typeof value?.error==='string'?value.error:'问题或权限不可读取',value?.details);
  return envelope?value.result:value;
}
async function snapshot(project:string,id:string,signal?:AbortSignal):Promise<Snapshot>{
  const [raw,state]=await Promise.all([get('/api/objects/'+encodeURIComponent(id)+'?consumer='+encodeURIComponent(project),signal),get('/api/state',signal,false)]);
  const question=checkedQuestion(raw,project,id),directory=checkedState(state,project),c=question.content;
  if(c.task_id&&c.bound_task_id&&c.task_id!==c.bound_task_id)throw Error('问题的目标 Task 身份冲突；未开放决定。');
  const target=c.task_id||c.bound_task_id;
  const ids=target?[target]:[];
  if(ids.some(id=>!directory.tasks.some((t:Task)=>t.id===id)))throw Error('目标 Task 不在当前可读取项目中；未开放决定。');
  const tasks=await Promise.all(ids.map(async id=>checkedTask(await readTask(id),project,id)));
  if(signal?.aborted)throw Error('本次读取已取消');
  return {question,tasks,writable:directory.writable};
}
function same(a:Snapshot,b:Snapshot){return a.writable===b.writable&&equal(a.tasks,b.tasks)&&
  a.question.revision===b.question.revision&&a.question.id===b.question.id&&a.question.project_id===b.question.project_id&&
  a.question.title===b.question.title&&!!a.question.archived===!!b.question.archived&&equal(a.question.content,b.question.content)&&equal(a.question.question_view,b.question.question_view);}
function canReassess(q:Question){const v=q.question_view;return v.source_stale&&v.source_bound&&v.sources.length>0&&v.sources.every(source=>!('unavailable' in source&&source.unavailable));}
function permitted(q:Question,d:Pick<Draft,'mode'|'disposition'|'reason'>){return !q.archived&&(!q.content.blocking||ident(q.content.task_id))&&(d.mode==='reassess'?canReassess(q)&&!!d.reason.trim():d.disposition!=='continue'||!q.content.blocking||q.question_view.source_valid);}
// answer returns a canonical object; reassess returns the enriched view. Never combine a new object with old derived fields.
function matchesReceipt(value:any,intent:Intent){
  const before=intent.snapshot.question,c=value?.content;
  if(!record(value)||value.id!==before.id||value.project_id!==before.project_id||value.kind!=='question'||value.revision!==before.revision+1||value.title!==before.title||
    !!value.archived!==!!before.archived||!record(c)||typeof c.answered_at!=='string'||!c.answered_at)return false;
  const expected:Record<string,any>={...before.content,answer:intent.answer,answered_at:c.answered_at,status:intent.disposition==='defer'?'deferred':intent.disposition==='deny'?'denied':'answered',disposition:intent.disposition,grants_permissions:false};
  if(intent.mode==='reassess'){
    const r=c.source_reassessment;
    if(!record(r)||typeof r.at!=='string'||!r.at)return false;
    expected.source_reassessment={source_snapshot:intent.snapshot.question.question_view.sources,reason:intent.reason,at:r.at,previous_question_revision:before.revision,adopted_sources_changed:false,grants_permissions:false};
  }
  return equal(c,expected);
}

/** Explicit human decision, using existing answer/reassess contracts. Does not create a Task or grant permissions. */
export function QuestionDecisionPanel({session:s,questionId,report,onOpenReference,onOpenTask,onDecisionRecorded}:QuestionDecisionPanelProps){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const memory=memoryFor(s,questionId);useSyncExternalStore(memory.subscribe,memory.snapshot);
  const scope=useRef({session:s,project:s.project.id,id:questionId,memory});
  if(scope.current.session!==s||scope.current.project!==s.project.id||scope.current.id!==questionId)scope.current={session:s,project:s.project.id,id:questionId,memory};
  const active=scope.current,live=useRef(false),serial=useRef(0),controller=useRef<AbortController|null>(null),explicit=useRef(false);
  const [reading,setReading]=useState<{scope:typeof active,value?:Snapshot,error?:string}|null>(null),[reload,setReload]=useState(0),[opening,setOpening]=useState(false);
  const d=memory.value,pending=d.phase==='checking'||d.phase==='sending',unknown=d.phase==='unknown';
  useEffect(()=>{
    live.current=true;const origin=active,ticket=++serial.current,abort=new AbortController(),reconcile=explicit.current;explicit.current=false;controller.current=abort;
    const current=()=>live.current&&scope.current===origin&&serial.current===ticket;
    setReading(null);setOpening(false);origin.memory.set({approved:false});
    void snapshot(origin.project,origin.id,abort.signal).then(value=>{
      if(!current())return;
      setReading({scope:origin,value});
      const old=origin.memory.value;
      if(reconcile&&old.phase==='unknown'&&old.intent&&matchesReceipt(value.question,old.intent))
        origin.memory.set({phase:'confirmed',approved:false,error:'',notice:'已读回与原请求一致的完整决定；未再次提交。'});
    }).catch(error=>{if(current()){setReading({scope:origin,error:errorText(error)});report(error);}});
    return()=>{live.current=false;++serial.current;abort.abort();};
  },[s,s.project.id,questionId,reload,d.readVersion]);
  const read=reading?.scope===active?reading:null,value=read?.value,q=value?.question;
  const ready=!!q&&value?.writable&&!!d.answer.trim()&&!!d.disposition&&d.approved&&permitted(q,d)&&!pending&&!unknown&&d.phase!=='confirmed';
  const edit=(patch:Partial<Draft>)=>{if(pending||unknown)return;memory.set({...patch,approved:false,error:'',notice:'',phase:'idle',intent:undefined});};
  const refresh=()=>{if(pending)return;++serial.current;controller.current?.abort();explicit.current=true;setReading(null);memory.set({approved:false,error:'',notice:''});setReload(n=>n+1);};
  const submit=async()=>{
    if(!ready||!value||!q||!d.disposition||['checking','sending','unknown','confirmed'].includes(memory.value.phase))return;
    const origin=active,ticket=++serial.current,intent:Intent={snapshot:structuredClone(value),answer:d.answer.trim(),disposition:d.disposition,mode:d.mode,reason:d.reason.trim()};
    const current=()=>live.current&&scope.current===origin&&serial.current===ticket;
    origin.memory.set({phase:'checking',intent,approved:false,error:'',notice:''});let sent=false;
    try{
      const fresh=await snapshot(origin.project,origin.id);
      if(!current()){origin.memory.set({phase:'idle',intent:undefined});return;}
      if(!fresh.writable)throw new CommandError('forbidden','当前项目不可写；未提交决定。',null);
      if(!same(fresh,intent.snapshot)||!permitted(fresh.question,intent))throw Error('问题、来源、权限或目标 Task 已变化；请刷新后重新确认。');
      origin.memory.set({phase:'sending'});sent=true;
      const fields={id:origin.id,expected_revision:intent.snapshot.question.revision,answer:intent.answer,disposition:intent.disposition};
      const result=intent.mode==='reassess'?await command('question.reassess',{...fields,source_snapshot:intent.snapshot.question.question_view.sources,reason:intent.reason,approved:true}):await command('decision.answer',fields);
      if(!matchesReceipt(result,intent))throw Error('决定回执与原问题、回答或来源不一致；结果尚未确认。');
      origin.memory.set({phase:'confirmed',error:'',notice:'决定已登记；正在读取实际问题与目标 Task 状态。',readVersion:origin.memory.value.readVersion+1});
      // A recorded decision can change a Task's state. Notify only the current
      // view; the owner reads the complete Task rather than merging this
      // component's deliberately narrow target projection into its cache.
      if(current())onDecisionRecorded?.(intent.snapshot.tasks.map(task=>task.id));
    }catch(error){
      const rejected=error instanceof CommandError&&['csrf','forbidden','unauthorized','conflict','not_found','authorization_required'].includes(error.code);
      origin.memory.set({phase:sent&&!rejected?'unknown':'idle',error:errorText(error),approved:false,...(!sent||rejected?{intent:undefined}:{})});
      if(current()){setReading({scope:origin,error:errorText(error)});report(error);}
    }
  };
  const navigate=async(action:()=>Promise<void>|void)=>{if(pending||opening)return;const origin=active;setOpening(true);try{await action();}catch(e){if(live.current&&scope.current===origin)report(e);}finally{if(live.current&&scope.current===origin)setOpening(false);}};
  const sources=(items:Source[],label:string)=><section aria-label={label}><h4>{label}</h4>{items.length?items.map((source,index)=><div key={index}>
    {source.kind==='artifact'?<><p>{source.id} · 固定 r{source.revision}{source.current_revision!==undefined?` · 当前 r${source.current_revision}`:''}{source.unavailable?' · 当前不可读取':source.stale?' · 来源已变化':''}</p>
      {onOpenReference&&!source.unavailable&&<button disabled={pending||opening} onClick={()=>void navigate(()=>onOpenReference({id:source.id,revision:source.revision,consumer_id:active.project}))}>读取固定来源 {source.id} r{source.revision}</button>}</>:
      <p>原候选 Task：{source.task_id}<br/>固定 SHA：{source.sha256}{source.stale?' · 候选已变化':''}</p>}</div>):<p>未登记。</p>}</section>;
  return <section className="review-panel" aria-label={'问题决定 '+questionId}>
    <div className="panel-tools"><h2>问题决定</h2><button disabled={pending} onClick={refresh}>刷新问题与目标 Task</button></div>
    <p>请根据原来源填写具体回答。本操作不新增科学、代码、数据或费用权限，不替代科学批准，也不生成新的候选。</p>
    {!read&&<p role="status">正在核对问题、来源、项目权限与目标 Task…</p>}
    {(read?.error||d.error)&&<p role="alert">{read?.error||d.error}</p>}
    {d.notice&&<p role="status">{d.notice}</p>}
    {pending&&<p role="status">{d.phase==='checking'?'正在重新核对决定范围…':'决定请求已发送，正在核对回执…'}</p>}
    {unknown&&<p role="status">原决定结果尚未确认；只能刷新核对，不会再次提交。原回答和处置已保留。</p>}
    {q&&<>
      <h3>{q.title}</h3><p>{q.id} · r{q.revision} · {q.question_view.scope}{q.archived?' · 已归档':''}</p>
      <h4>问题背景</h4><p style={{whiteSpace:'pre-wrap'}}>{q.content.background??'未登记。'}</p>
      <h4>原建议选项（只读）</h4><ol>{(q.content.options??[]).map((o:any,i:number)=><li key={i}><p>{typeof o==='string'?o:o.label}</p>{typeof o!=='string'&&<><small>选项 {o.id}</small><p>后果：{o.consequence}</p></>}</li>)}</ol>
      <h4>原建议及限制</h4><p style={{whiteSpace:'pre-wrap'}}>{q.content.recommendation??'未登记。'}</p>
      <h4>已有决定（只读）</h4><p>状态：{q.content.status??'未登记'} · 处置：{q.content.disposition??'未登记'}</p><p style={{whiteSpace:'pre-wrap'}}>原回答：{q.content.answer??'尚无回答'}</p>
      {q.content.answered_at&&<p>回答时间：{q.content.answered_at}</p>}
      {q.content.source_reassessment&&<details><summary>原来源重新评估</summary><pre>{JSON.stringify(q.content.source_reassessment,null,2)}</pre></details>}
      {q.content.inherited_answer&&<details><summary>原继承回答</summary><pre>{JSON.stringify(q.content.inherited_answer,null,2)}</pre></details>}
      {sources(q.question_view.sources,'问题固定来源')}{sources(q.question_view.base_sources,'候选原基线')}
      <section aria-label="本次决定涉及的 Task"><h4>本次决定涉及的 Task</h4>{value!.tasks.map(t=><div key={t.id}><p>{t.id} · {t.status}</p><p style={{whiteSpace:'pre-wrap'}}>{t.payload.request??'未登记委托正文。'}</p>{onOpenTask&&<button disabled={pending||opening} onClick={()=>void navigate(()=>onOpenTask({id:t.id,project_id:active.project}))}>打开目标 Task {t.id}</button>}</div>)}
      {!value!.tasks.length&&<p>未关联具体 Task。</p>}</section>
      {q.content.blocking?<p>{q.content.task_id?'这是必要前置决定。继续可能接续因该必要裁决等待的目标 Task；拒绝可能取消该目标 Task；暂缓保持门控。实际执行仍受原预算、权限和其他依赖限制。':'此必要问题尚无明确目标 Task，原合同可能影响本项目多个任务。本入口仅供只读核对，须先明确范围；不会从原始任务推测目标。'}</p>:<p>此问题不阻断 Task；记录回答不直接接续或取消任务。</p>}
      <p>已有候选不会因回答而重新生成。若其依据已变化，须另行明确候选修订，保留原候选与预算。</p>
      {!value!.writable&&<p role="status">当前项目只读；可读取原问题，不能保存决定。</p>}
      {!q.question_view.source_valid&&<p role="status">{q.content.blocking?'来源当前无效；不能直接继续。来源确已更新且可读时，请明确重新评估。':'来源当前无效；记录非阻断回答不会放行 Task，也不会更新原采用版本。可读取更新来源后明确重新评估。'}</p>}
      <fieldset disabled={pending||unknown||!value!.writable||!!q.archived||!!q.content.blocking&&!ident(q.content.task_id)}>
        <legend>人工明确决定</legend>
        <label>决定方式<select aria-label="决定方式" value={d.mode} onChange={e=>edit({mode:e.target.value as Draft['mode']})}><option value="answer">回答原问题</option><option value="reassess" disabled={!canReassess(q)}>重新评估已更新来源</option></select></label>
        {d.mode==='reassess'&&<><p>将记录上方完整当前来源快照，保留原固定来源与采用版本。</p><label>来源重新评估原因<textarea aria-label="来源重新评估原因" value={d.reason} onChange={e=>edit({reason:e.target.value})}/></label></>}
        <label>具体回答<textarea aria-label="具体回答" value={d.answer} onChange={e=>edit({answer:e.target.value})}/></label>
        <label>本次处置<select aria-label="本次处置" value={d.disposition} onChange={e=>edit({disposition:e.target.value as Disposition})}><option value="">请选择</option><option value="continue">在既有范围继续</option><option value="deny">拒绝相关动作</option><option value="defer">暂缓</option></select></label>
        <label><input type="checkbox" aria-label="确认此次决定及 Task 后果" checked={d.approved} onChange={e=>memory.set({approved:e.target.checked})}/>我已核对上述来源、具体回答与目标 Task 后果；不增加权限或预算。</label>
        <button disabled={!ready} onClick={()=>void submit()}>确认保存决定</button>
      </fieldset>
    </>}
  </section>;
}
