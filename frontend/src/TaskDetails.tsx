import {actualTaskBrief,type TaskBriefRef} from './TaskBriefReference';
export {actualTaskBrief,type TaskBriefRef} from './TaskBriefReference';
import {useEffect,useRef,useState} from 'react';
import {command,CommandError,readTask} from './api';
import type {Session} from './session';
import {ManuscriptTaskReview} from './ManuscriptTaskReview';
import {QuestionFollowupPanel} from './QuestionFollowupPanel';
import {QuestionDecisionPanel} from './QuestionDecisionPanel';
import {ResearchCyclePanel} from './ResearchCyclePanel';
import type {PinnedReference} from './PinnedReferencePanel';

type TaskRecord = Record<string,any>;
export type TaskDetailsSnapshot = {task:TaskRecord,manuscriptView?:TaskRecord,detailError?:string,candidateRefreshRequired?:boolean};
type TaskDetailsIO = {readTask:(id:string)=>Promise<any>,command:(action:string,fields:Record<string,any>)=>Promise<any>};
const actualText=(value:any):string=>typeof value==='string'?value:'';
const firstText=(...values:any[])=>values.map(actualText).find(value=>value.trim())||'';
const identity=(value:any)=>typeof value==='string'&&value.length>0&&value.length<=200&&!/[\s/\\\u0000-\u001f]/u.test(value);
const sha=(value:any)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const errorText=(error:unknown)=>error instanceof Error?error.message:String(error);
type ResearchCandidate={id:string,revision:number,kind:'report'|'note'};
type ResearchCandidateRef={id:string,revision:number,sha256:string,consumer_id:string};

function researchCandidate(task:TaskRecord):ResearchCandidate|null {
  const payload=task.payload,result=task.result,kind=payload?.context?.output;
  const original=payload?.kind==='research'&&payload.target_id===null&&payload.base_revision===null;
  const revision=payload?.kind==='revision'&&identity(payload.target_id)&&result?.object_id===payload.target_id&&
    Number.isSafeInteger(payload.base_revision)&&payload.base_revision>0&&result.revision>payload.base_revision;
  return task.status==='generated'&&(original||revision)&&
    (kind==='report'||kind==='note')&&identity(result?.object_id)&&Number.isSafeInteger(result?.revision)&&result.revision>0?
    {id:result.object_id,revision:result.revision,kind}:null;
}

async function readResearchCandidate(task:TaskRecord,projectId:string,expected:ResearchCandidate):Promise<ResearchCandidateRef>{
  const reference=researchCandidate(task);
  if(!reference||reference.id!==expected.id||reference.revision!==expected.revision||reference.kind!==expected.kind)
    throw new Error('候选引用已变化；请刷新任务详情核对，未打开另一候选或修订。');
  const query=new URLSearchParams({revision:String(reference.revision),consumer:projectId});
  const response=await fetch('/api/objects/'+encodeURIComponent(reference.id)+'?'+query,{method:'GET',credentials:'same-origin'});
  const body=await response.json();
  if(!response.ok||body?.ok!==true)throw new CommandError(body?.code,typeof body?.error==='string'?body.error:'固定候选读取失败；未打开旧缓存。',body?.details);
  const source=body.result;
  if(!source||source.id!==reference.id||source.project_id!==projectId||source.revision!==reference.revision||source.kind!==reference.kind||
    source.metadata?.task_id!==task.id||!sha(source.canonical_source_sha256))
    throw new Error('候选来源与此项目、任务、成果类型或固定修订不符；未打开其他内容。');
  return {id:reference.id,revision:reference.revision,sha256:source.canonical_source_sha256,consumer_id:projectId};
}

function assertTask(task:any,projectId:string,taskId:string):asserts task is TaskRecord {
  if(!task||task.id!==taskId||task.project_id!==projectId||typeof task.status!=='string')throw new Error('任务身份或项目不符；未显示其他任务内容。');
}

/** The same sequence gate guards initial load, explicit refresh and unmount. */
export class TaskDetailsReader {
  private sequence=0;
  invalidate(){this.sequence++;}
  start(projectId:string,taskId:string,io:TaskDetailsIO={readTask,command},options:{includeCandidate?:boolean}={}){
    const sequence=++this.sequence,current=()=>this.sequence===sequence;
    const result=(async():Promise<TaskDetailsSnapshot|null>=>{
      const task=await io.readTask(taskId);
      if(!current())return null;
      assertTask(task,projectId,taskId);
      const snapshot:TaskDetailsSnapshot={task};
      // Other task kinds must never be interpreted as manuscript revisions.
      if(options.includeCandidate!==false&&task.payload?.kind==='manuscript_revision'&&task.result?.manuscript_revision?.proposal_sha256){
        try{
          const view=await io.command('manuscript.revision.view',{task_id:taskId});
          if(!current())return null;
          if(view?.task_id!==taskId||view.proposal&&(
            view.proposal.task_id!==taskId||view.proposal.proposal_sha256!==task.result.manuscript_revision.proposal_sha256))
            throw new Error('稿件候选与此任务的固定引用不符。');
          snapshot.manuscriptView=view;
        }catch(error){if(!current())return null;snapshot.detailError=errorText(error);}
      }
      return current()?snapshot:null;
    })();
    return {current,result};
  }
}

export function projectTaskDetails(snapshot:TaskDetailsSnapshot,projectId:string,taskId:string){
  const task=snapshot.task;assertTask(task,projectId,taskId);
  const payload=task.payload||{},result=task.result||{},proposal=snapshot.manuscriptView?.proposal;
  const composition=result.composition_candidate;
  const figureRef=payload.kind==='figure_composition'&&task.status==='generated'&&identity(composition?.id)&&
    Number.isInteger(composition?.revision)&&composition.revision>0&&sha(composition?.sha256)?composition:null;
  const generationRef=payload.kind==='generation'&&sha(payload.generation_plan?.plan_hash)?task.id:null;
  const summaries=[firstText(result.summary,result.candidate?.summary,proposal?.candidate?.summary)].filter(Boolean);
  const limitations:string[]=[];
  if(actualText(result.limitations).trim())limitations.push(result.limitations);
  else if(Array.isArray(result.limitations))limitations.push(...result.limitations.filter((x:any)=>actualText(x).trim()));
  for(const response of proposal?.responses||proposal?.candidate?.responses||[])
    if(actualText(response.limitations).trim())limitations.push(response.limitations);
  const researchRef=snapshot.candidateRefreshRequired?null:researchCandidate(task);
  const canBrief=payload.kind==='manuscript_revision'&&!!proposal||task.status==='generated'&&(
    payload.kind==='generation'&&!!generationRef&&!!result.output_checks||
    payload.kind==='manuscript_revision'&&!!proposal||
    payload.kind==='figure_composition'&&!!figureRef&&result.provider?.session_identity_confirmed===true||
    payload.kind==='research'&&!!researchRef);
  return {task,title:firstText(task.title,payload.title,payload.context?.figure_composition?.request?.title)||task.id,
    kind:actualText(payload.kind)||'未登记',request:actualText(payload.request),error:task.error,
    summaries,limitations,figureRef,generationRef,researchRef,canBrief,detailError:snapshot.detailError,
    recordedResult:result};
}

/** Only registered identities are offered; no inferred question or automatic read. */
export function taskQuestionReferences(result:any):{ids:string[],error?:string}{
  if(!result||typeof result!=='object'||Array.isArray(result))return {ids:[]};
  const ids=result.question_ids??[];
  if(!Array.isArray(ids)||ids.some(id=>!identity(id))||
    result.feedback_requested!=null&&!identity(result.feedback_requested))
    return {ids:[],error:'任务登记的问题引用不完整；请查看原结果，未猜测打开问题。'};
  return {ids:[...new Set<string>([...ids,...(result.feedback_requested?[result.feedback_requested]:[])])]};
}


type TaskDetailsProps={session:Session,taskId:string,onOpenFigure:(id:string)=>Promise<void>|void,
  onOpenGeneration:(runId:string)=>Promise<void>|void,onOpenNote:(relativePath:string)=>Promise<void>|void,
  onOpenReference?:(reference:PinnedReference)=>Promise<void>|void,
  onOpenTask?:(reference:{id:string,project_id:string})=>Promise<void>|void,
  taskAuthority?:TaskAuthority,
  report:(error:unknown)=>void};

export type TaskAuthority={workspaceOwner:boolean,writableProjectIds:string[],runtimeRunning:boolean,
  providers:{id:string,route:string,authorized:boolean}[]};
type BudgetIntent={operation:'extend'|'resume',seq:number,attempts:number,calls:number,seconds:number,reason:string};
type BudgetMemory={calls:string,seconds:string,reason:string,approved:boolean,phase:'idle'|'pending'|'unknown'|'confirmed'|'rejected',
  intent?:BudgetIntent,error?:string,notice?:string};
const budgetMemories=new WeakMap<Session,Map<string,BudgetMemory>>();
function taskBudgetMemory(s:Session,key:string){
  let tasks=budgetMemories.get(s);if(!tasks){tasks=new Map();budgetMemories.set(s,tasks);}
  let value=tasks.get(key);if(!value){value={calls:'1',seconds:'300',reason:'',approved:false,phase:'idle'};tasks.set(key,value);}
  return value;
}
const finite=(x:any)=>typeof x==='number'&&Number.isFinite(x)&&x>=0;
const count=(x:any)=>Number.isSafeInteger(x)&&x>=0;
const exactKeys=(x:any,names:string[])=>!!x&&typeof x==='object'&&!Array.isArray(x)&&
  JSON.stringify(Object.keys(x).sort())===JSON.stringify([...names].sort());
function taskEvents(task:TaskRecord){return (Array.isArray(task.events)?task.events:[])
  .filter((e:any)=>e.object_id===task.id&&Number.isSafeInteger(e.seq)&&e.seq>0).sort((a:any,b:any)=>b.seq-a.seq);}
function budgetRecords(task:TaskRecord){
  const events=taskEvents(task),call=events.find((e:any)=>e.kind==='provider.reserved'&&count(e.data?.invocation)),
    elapsed=events.find((e:any)=>e.kind==='task.time_settled'&&finite(e.data?.elapsed_seconds)),
    extension=events.find((e:any)=>e.kind==='budget.explicit_extension'&&count(e.data?.current?.invocations)&&finite(e.data?.current?.seconds));
  return {events,calls:call?.data.invocation,seconds:elapsed?.data.elapsed_seconds,extension:extension?.data.current};
}

/** Explicit deltas never rewrite the declared budget or silently resume a task. */
function TaskBudgetControls({session:s,task,authority,busy,onBusy,onChanged,report}:{session:Session,task:TaskRecord,
  authority?:TaskAuthority,busy:boolean,onBusy:(value:boolean)=>void,onChanged:()=>void,report:(error:unknown)=>void}){
  const project=s.project.id,memory=taskBudgetMemory(s,project+'\n'+task.id),[,paint]=useState(0),live=useRef(false);
  const signature=JSON.stringify({project,id:task.id,status:task.status,kind:task.payload?.kind,result:task.result,authority});
  const scope=useRef({session:s,signature});if(scope.current.session!==s||scope.current.signature!==signature)scope.current={session:s,signature};
  const active=scope.current,current=()=>live.current&&scope.current===active;
  const records=budgetRecords(task),provider=authority?.providers.find(p=>p.id===task.payload?.provider_id);
  const eligible=task.project_id===project&&task.payload?.kind==='research'&&provider?.route==='codex'&&provider.authorized===true;
  const writable=authority?.writableProjectIds.includes(project)===true;
  const canExtend=eligible&&!task.payload?.cycle_parent&&writable&&authority?.workspaceOwner===true&&['failed','waiting_resource','waiting_authorization','paused'].includes(task.status);
  const canResume=eligible&&writable&&authority?.runtimeRunning===true&&['failed','waiting_resource','waiting_authorization','paused','waiting_input'].includes(task.status)&&count(task.attempts)&&task.attempts<3;
  const redraw=()=>paint(x=>x+1);
  useEffect(()=>{live.current=true;return()=>{live.current=false;if(memory.phase==='pending'){
    memory.phase='unknown';memory.error='请求结果未知；请刷新任务详情核对实际记录，不要重复追加或继续。';
  }};},[s,project,task.id]);
  useEffect(()=>{
    const sent=memory.intent;if(memory.phase!=='unknown'||!sent)return;
    const matches=records.events.filter((e:any)=>e.seq>sent.seq&&(sent.operation==='extend'?
      e.kind==='budget.explicit_extension'&&finite(e.data?.previous?.seconds)&&count(e.data?.previous?.invocations)&&
      finite(e.data?.current?.seconds)&&count(e.data?.current?.invocations)&&e.data.current.reason===sent.reason&&
      e.data.current.invocations-e.data.previous.invocations===sent.calls&&e.data.current.seconds-e.data.previous.seconds===sent.seconds:
      e.kind==='task.queued'&&e.data?.operation==='resume'));
    if(matches.length===1){memory.phase='confirmed';memory.error=undefined;memory.approved=false;
      memory.notice=sent.operation==='extend'?'已核对实际追加记录；未自动继续原任务。':'已核对原任务实际继续记录。';redraw();}
  },[task,memory]);
  const calls=Number(memory.calls),seconds=Number(memory.seconds),valid=memory.calls.trim()!==''&&memory.seconds.trim()!==''&&
    count(calls)&&calls<=5&&count(seconds)&&seconds<=900&&calls+seconds>0&&!!memory.reason.trim();
  const locked=busy||memory.phase==='pending'||memory.phase==='unknown';
  const act=async(operation:'extend'|'resume')=>{
    if(locked||operation==='extend'&&(!canExtend||!valid||!memory.approved)||operation==='resume'&&!canResume)return;
    const sent:BudgetIntent={operation,seq:records.events[0]?.seq??0,attempts:task.attempts,calls,seconds,reason:memory.reason.trim()};
    memory.intent=sent;memory.phase='pending';memory.error=undefined;memory.notice=undefined;redraw();onBusy(true);
    try{
      const result=await command(operation==='extend'?'task.extend_budget':'task.control',operation==='extend'?
        {id:task.id,additional_invocations:sent.calls,additional_seconds:sent.seconds,reason:sent.reason,approved:true}:
        {id:task.id,operation:'resume'});
      if(memory.intent!==sent)return;
      if(operation==='extend'){
        const x=result?.extension;
        if(!exactKeys(result,['task_id','extension','consumption_preserved','automatically_resumed'])||result.task_id!==task.id||
          result.consumption_preserved!==true||result.automatically_resumed!==false||!exactKeys(x,['invocations','seconds','reason','at'])||
          !count(x.invocations)||!finite(x.seconds)||x.invocations<sent.calls||x.seconds<sent.seconds||x.reason!==sent.reason||typeof x.at!=='string'||!x.at)
          throw new Error('追加回执结构或原任务身份不符；结果未知。');
        if(records.extension&&(x.invocations!==records.extension.invocations+sent.calls||x.seconds!==records.extension.seconds+sent.seconds))
          throw new Error('追加累计值与读取的记录不符；结果未知，请核对实际追加事件。');
      }else{
        assertTask(result,project,task.id);
        if(!['queued','running'].includes(result.status)||result.payload?.kind!=='research'||result.payload?.provider_id!==task.payload.provider_id||
          JSON.stringify(result.payload?.budget)!==JSON.stringify(task.payload.budget))throw new Error('继续回执与原任务或原预算不符；结果未知。');
      }
      if(!current()){memory.phase='unknown';memory.error='请求已有回执；当前视图已改变，请刷新原任务核对实际记录。';return;}
      memory.phase='confirmed';memory.approved=false;
      memory.notice=operation==='extend'?'额度已追加；原任务尚未继续。':'原任务已登记继续；请读取实际执行状态。';
      redraw();onChanged(); // Fresh Task clears any old same-kind candidate/result.
    }catch(error){
      if(memory.intent!==sent)return;
      const rejected=error instanceof CommandError&&['forbidden','authorization_required','csrf','unauthorized','conflict','invalid','unsupported_action','budget_exhausted',
        ...(operation==='resume'?['provider_checkpoint_missing','runtime_unavailable']:[])].includes(error.code);
      memory.phase=rejected?'rejected':'unknown';memory.error=errorText(error)+(rejected?'':' 结果未知；请刷新任务详情核对实际记录，不要重复追加或继续。');
      if(current()){redraw();report(error);}
    }finally{onBusy(false);}
  };
  if(!canExtend&&!canResume)return null;
  const declared=task.payload.budget,extra=records.extension;
  const remainingCalls=records.calls!==undefined&&count(declared?.max_model_calls)&&extra?Math.max(0,declared.max_model_calls+extra.invocations-records.calls):null;
  const remainingSeconds=records.seconds!==undefined&&finite(declared?.timeout_seconds)&&extra?Math.max(0,Math.min(1800,declared.timeout_seconds+extra.seconds)-records.seconds):null;
  return <section aria-label="原任务有限额度与继续">
    <h3>原任务额度与继续</h3>
    <p>原登记上限：{declared?.max_model_calls??'未登记'} 次 CLI / {declared?.timeout_seconds??'未登记'} 秒；原预算不会重置。</p>
    <p>已登记调用计数（含预留）：{records.calls??'未登记'}</p><p>已记录累计执行：{records.seconds===undefined?'未登记':records.seconds+' 秒'}</p>
    {extra?<p>已登记累计追加：{extra.invocations} 次 CLI / {extra.seconds} 秒</p>:<p>当前返回事件未登记追加额度。</p>}
    {extra&&count(declared?.max_model_calls)&&finite(declared?.timeout_seconds)&&<p>按登记值计算的累计上限：{declared.max_model_calls+extra.invocations} 次 CLI / {Math.min(1800,declared.timeout_seconds+extra.seconds)} 秒。</p>}
    {remainingCalls!==null&&<p>按当前已返回事件计算的累计剩余上限：{remainingCalls} 次 CLI / {remainingSeconds??'未知'} 秒。</p>}
    <p className="quiet">仅依据本次返回的最多 200 条任务事件；调用计数不等于内部 API 请求数或实际费用。实际可执行时长、调用、原会话和权限由服务端与父额度及停止标记核验；累计上限不是单次可用时长。</p>
    {canExtend&&<fieldset disabled={locked}><legend>明确追加有限额度</legend>
      <label>新增 CLI 调用次数<input aria-label="新增 CLI 调用次数" type="number" min="0" max="5" step="1" value={memory.calls} onChange={e=>{memory.calls=e.target.value;memory.approved=false;redraw();}}/></label>
      <label>新增累计执行秒数<input aria-label="新增累计执行秒数" type="number" min="0" max="900" step="1" value={memory.seconds} onChange={e=>{memory.seconds=e.target.value;memory.approved=false;redraw();}}/></label>
      <label>追加理由<textarea aria-label="追加理由" value={memory.reason} onChange={e=>{memory.reason=e.target.value;memory.approved=false;redraw();}}/></label>
      <p>每次可明确新增 0–5 次 CLI、0–900 个整数秒，至少一项大于零；保留既有消耗和三次尝试上限。</p>
      <label><input type="checkbox" aria-label="明确批准本次有限追加额度" checked={memory.approved} onChange={e=>{memory.approved=e.target.checked;redraw();}}/>明确批准本次填写的有限追加；这不会自动继续。</label>
      <button disabled={!valid||!memory.approved} onClick={()=>act('extend')}>确认追加有限额度</button>
    </fieldset>}
    {canResume&&<><p>继续同一 Task 可能消耗已批准的剩余额度，并增加一次执行尝试；不会新建任务或自动追加额度。</p><button disabled={locked} onClick={()=>act('resume')}>继续原任务</button></>}
    {memory.phase==='pending'&&<p role="status">正在请求原任务操作；等待真实回执，不重复发送。</p>}
    {memory.notice&&<p role="status">{memory.notice}</p>}{memory.error&&<p role="alert">{memory.error}</p>}
  </section>;
}

type TaskDetailsContext={session:Session,key:string};

/** Task changes and native brief writes each require their explicit button. */
export function TaskDetails({session:s,taskId,onOpenFigure,onOpenGeneration,onOpenNote,onOpenReference,onOpenTask,taskAuthority,report}:TaskDetailsProps){
  const key=s.project.id+'\n'+taskId,context=useRef<TaskDetailsContext>({session:s,key});
  if(context.current.session!==s||context.current.key!==key)context.current={session:s,key};
  const active=context.current;
  const [stored,setStored]=useState<{context:TaskDetailsContext,value:TaskDetailsSnapshot}|null>(null),[loading,setLoading]=useState(false),
    [busy,setBusy]=useState(false),[message,setMessage]=useState<{context:TaskDetailsContext,text:string}|null>(null),
    [brief,setBrief]=useState<{context:TaskDetailsContext,ref:TaskBriefRef}|null>(null),
    [selectedQuestion,setSelectedQuestion]=useState<{context:TaskDetailsContext,id:string,purpose?:'decision'}|null>(null),
    [priority,setPriority]=useState(''),[savedNotice,setSavedNotice]=useState<{context:TaskDetailsContext,text:string}|null>(null);
  const reader=useRef(new TaskDetailsReader()),actionRevision=useRef(0),actionOwner=useRef<object|null>(null);
  const snapshot=stored?.context===active?stored.value:null;
  const load=()=>{
    const captured=active,pending=reader.current.start(s.project.id,taskId);
    actionRevision.current++;actionOwner.current=null;setSelectedQuestion(null);setBusy(false);setStored(null);setLoading(true);setMessage(null);setSavedNotice(null);setPriority('');
    pending.result.then(value=>{
      if(pending.current()&&context.current===captured&&value){
        setStored({context:captured,value});setPriority(String(value.task.payload?.priority??0));
        if(value.detailError)report(new Error(value.detailError));
      }
    }).catch(error=>{if(pending.current()&&context.current===captured){setMessage({context:captured,text:errorText(error)});report(error);}})
      .finally(()=>{if(pending.current()&&context.current===captured)setLoading(false);});
  };
  useEffect(()=>{setBrief(null);load();return()=>{reader.current.invalidate();actionRevision.current++;actionOwner.current=null;};},[s,s.project.id,taskId]);
  const loaded=snapshot?.task.id===taskId&&snapshot.task.project_id===s.project.id;
  const details=loaded?projectTaskDetails(snapshot!,s.project.id,taskId):null;
  const questionRefs=details?taskQuestionReferences(details.recordedResult):{ids:[]};
  const questionId=selectedQuestion?.context===active&&questionRefs.ids.includes(selectedQuestion.id)?selectedQuestion.id:null;
  const decisionRecorded=(taskIds:readonly string[])=>{
    if(context.current!==active||!snapshot||!taskIds.includes(taskId))return;
    const captured=active,revision=++actionRevision.current,pending=reader.current.start(s.project.id,taskId,undefined,{includeCandidate:false});
    const current=()=>context.current===captured&&actionRevision.current===revision&&pending.current();
    setLoading(true);setMessage(null);
    void pending.result.then(value=>{
      if(!current()||!value)return;
      const sameCandidate=value.task.payload?.kind===snapshot.task.payload?.kind&&
        JSON.stringify(value.task.result)===JSON.stringify(snapshot.task.result);
      const next=sameCandidate?{...snapshot,task:value.task}:{task:value.task,candidateRefreshRequired:true,
        detailError:'决定后任务候选已变化；请明确刷新任务详情读取当前候选。'};
      if(!sameCandidate)setBrief(null);
      setStored({context:captured,value:next});
      setPriority(draft=>draft===String(snapshot.task.payload?.priority??0)?String(value.task.payload?.priority??0):draft);
    }).catch(error=>{if(current()){
      setStored(null);setBrief(null);setMessage({context:captured,text:errorText(error)});report(error);
    }}).finally(()=>{if(current())setLoading(false);});
  };
  const open=async(callback:(current:()=>boolean)=>Promise<void>|void)=>{
    if(busy||actionOwner.current)return;
    const owner={};actionOwner.current=owner;setBusy(true);setMessage(null);setSavedNotice(null);const captured=active,revision=++actionRevision.current;
    const current=()=>context.current===captured&&actionRevision.current===revision;
    try{await callback(current);}catch(error){if(current()){setMessage({context:captured,text:errorText(error)});report(error);}}
    // A confirmed child decision can supersede this action's data while its
    // original request is still pending. Only that request owns its busy flag.
    finally{if(context.current===captured&&actionOwner.current===owner){actionOwner.current=null;setBusy(false);}}
  };
  const savedPriority=details?.task.payload?.priority??0,value=Number(priority);
  const validPriority=priority.trim()!==''&&Number.isSafeInteger(value);
  const priorityError=priority.trim()===''?'':!Number.isInteger(value)?'优先级必须是整数。':!Number.isSafeInteger(value)?
    '数值超出可精确保存的整数范围，请输入 −9007199254740991 至 9007199254740991。':'';
  const savePriority=()=>open(async current=>{
    if(!snapshot||!validPriority||value===savedPriority)return;
    const task=await command('task.control',{id:taskId,operation:'priority:'+value});
    if(!current())return;
    assertTask(task,s.project.id,taskId);
    if(task.payload?.priority!==value)throw new Error('返回的任务优先级与此次保存不符；请刷新核对实际记录。');
    const sameCandidate=task.payload?.kind===snapshot.task.payload?.kind&&
      task.result?.manuscript_revision?.proposal_sha256===snapshot.task.result?.manuscript_revision?.proposal_sha256;
    // A priority receipt can observe a newly produced candidate. Do not combine
    // it with the previous detail view or leave the embedded review mounted.
    const next=sameCandidate?{...snapshot,task}:{task,candidateRefreshRequired:true,
      detailError:'稿件候选已变化；请刷新任务详情读取当前候选。'};
    if(!sameCandidate)setBrief(null);
    setStored({context:active,value:next});setPriority(String(task.payload.priority));
    setSavedNotice({context:active,text:`任务优先级已保存为 ${task.payload.priority}。`});
  });
  const writeBrief=()=>open(async current=>{
    if(!details?.canBrief)throw new Error('本任务尚不具备原生简报需要的实际结果。');
    const projectId=s.project.id;
    const research=details.researchRef;
    let verified:TaskDetailsSnapshot|undefined;
    if(research){
      // Only this explicit action reads the candidate. A cached Task pointer
      // cannot grant current source access or select another result revision.
      setStored(null);setBrief(null);
      const pending=reader.current.start(projectId,taskId),next=await pending.result;
      if(!current()||!pending.current()||!next)return;
      await readResearchCandidate(next.task,projectId,research);
      if(!current()||!pending.current())return;
      verified=next;
    }
    const response=await command('desk.task.brief',{project_id:projectId,task_id:taskId});
    if(!current())return;
    const ref=actualTaskBrief(response,projectId);
    if(research&&(typeof response.appended!=='boolean'||ref.relative_path!=='notes/tasks/'+taskId+'.md'))
      throw new Error('研究回报与此任务的原生笔记路径或写入回执不符；未打开其他笔记。');
    if(verified)setStored({context:active,value:verified});
    setBrief({context:active,ref});
    await onOpenNote(ref.relative_path);
  });
  const openResearch=()=>open(async current=>{
    const expected=details?.researchRef;
    if(!expected||!onOpenReference)return;
    // A previously loaded summary is not fresh source permission. Clear it
    // before reading again; a denied/unknown read must not leave a cached link.
    setStored(null);
    const pending=reader.current.start(s.project.id,taskId),next=await pending.result;
    if(!current()||!pending.current()||!next)return;
    const reference=await readResearchCandidate(next.task,s.project.id,expected);
    if(!current()||!pending.current())return;
    setStored({context:active,value:next});
    await onOpenReference(reference);
  });
  // Saved layouts can still contain a generic task tab for a cycle parent.
  // Its children, budget and controls belong to the cycle's dedicated view.
  if(details?.kind==='research_cycle')return <ResearchCyclePanel session={s} parentTaskId={taskId}
    taskAuthority={taskAuthority} onOpenTask={onOpenTask} onOpenReference={onOpenReference} onOpenNote={onOpenNote} report={report}/>;
  return <section className="review-panel" aria-label={`任务详情 ${taskId}`}>
    <div className="panel-tools"><strong>任务详情</strong><button disabled={loading||busy} onClick={load}>刷新任务详情</button></div>
    {loading&&<p role="status">读取此任务的实际记录…</p>}
    {message?.context===active&&<p role="alert">{message.text}</p>}
    {details&&<fieldset disabled={busy}>
      <legend>执行优先级</legend>
      <p>已保存优先级：{String(savedPriority)}</p>
      <label>任务优先级 <input type="number" step="1" aria-label="任务优先级" aria-invalid={!!priorityError} value={priority} onChange={event=>{setPriority(event.target.value);setSavedNotice(null);}}/></label>
      <button disabled={!validPriority||value===savedPriority} onClick={savePriority}>保存任务优先级</button>
      <p className="quiet">数值越大越先排队；不抢占正在执行的任务。依赖与权限检查仍适用。</p>
      <p className="quiet">请输入整数</p>
      {priorityError&&<p role="alert">{priorityError}</p>}
      {savedNotice?.context===active&&<p role="status">{savedNotice.text}</p>}
    </fieldset>}
    {details&&<TaskDetailsContent details={details} busy={busy} onOpenFigure={()=>open(()=>onOpenFigure(details.figureRef!.id))}
      onOpenGeneration={()=>open(()=>onOpenGeneration(details.generationRef!))} onWriteBrief={writeBrief}
      onOpenResearchCandidate={onOpenReference?openResearch:undefined}/>}
    {details&&(questionRefs.error||questionRefs.ids.length>0)&&<section aria-label="任务登记的后续问题">
      <h3>后续问题</h3><p>读取原问题、固定来源与已有决定；可关联已有任务，或另行整理具体回答与处置。</p>
      {questionRefs.error&&<p role="alert">{questionRefs.error}</p>}
      {questionRefs.ids.map(id=><div key={id}>
        <button disabled={busy} onClick={()=>setSelectedQuestion({context:active,id})}>查看后续问题 {id}</button>
        <button disabled={busy} onClick={()=>setSelectedQuestion({context:active,id,purpose:'decision'})}>整理问题裁决 {id}</button>
      </div>)}
      {questionId&&<><button onClick={()=>setSelectedQuestion(null)}>关闭后续问题</button>
        {selectedQuestion?.purpose==='decision'
          ?<QuestionDecisionPanel key={questionId+':decision'} session={s} questionId={questionId} report={report}
            onOpenReference={onOpenReference} onOpenTask={onOpenTask} onDecisionRecorded={decisionRecorded}/>
          :<QuestionFollowupPanel key={questionId} session={s} questionId={questionId} report={report}
            onOpenReference={onOpenReference} onOpenTask={onOpenTask}/>}</>}
    </section>}
    {details&&<TaskBudgetControls session={s} task={details.task} authority={taskAuthority} busy={busy}
      onBusy={value=>{if(context.current===active)setBusy(value);}} onChanged={load} report={report}/>}
    {loaded&&!snapshot!.candidateRefreshRequired&&snapshot!.task.payload?.kind==='manuscript_revision'&&[2,3].includes(snapshot!.task.payload.context?.manuscript_revision?.version)&&
      <ManuscriptTaskReview session={s} taskId={taskId} report={report} onOpenNote={onOpenNote} onChanged={load}/>}
    {brief?.context===active&&brief.ref.project_id===s.project.id&&<p>原生简报 {brief.ref.id} · {brief.ref.relative_path}<button disabled={busy} onClick={()=>open(()=>onOpenNote(brief.ref.relative_path))}>打开已登记简报</button></p>}
  </section>;
}

/** Kept separate so offline SSR verifies actual fields and disabled actions. */
export function TaskDetailsContent({details,busy=false,onOpenFigure,onOpenGeneration,onWriteBrief,onOpenResearchCandidate}:{
  details:ReturnType<typeof projectTaskDetails>,busy?:boolean,onOpenFigure:()=>void,onOpenGeneration:()=>void,onWriteBrief:()=>void,onOpenResearchCandidate?:()=>void}){
  return <>
    <h2>{details.title}</h2><p>{details.task.id} · {details.kind} · 实际状态：{details.task.status}</p>
    {details.request&&<details><summary>原任务要求</summary><p>{details.request}</p></details>}
    {details.error&&<p role="alert">{typeof details.error==='string'?details.error:JSON.stringify(details.error)}</p>}
    <h3>登记的结果摘要</h3>{details.summaries.length?details.summaries.map((text,i)=><p key={i}>{text}</p>):<p>本任务记录未登记摘要。</p>}
    <h3>登记的限制</h3>{details.limitations.length?details.limitations.map((text,i)=><p key={i}>{text}</p>):<p>本任务记录未登记限制；不能据此推定没有限制。</p>}
    {details.detailError&&<p role="alert">{details.detailError}</p>}
    <div className="panel-tools">
      <button disabled={busy||!details.generationRef} onClick={onOpenGeneration}>打开实际生成运行</button>
      <button disabled={busy||!details.figureRef} onClick={onOpenFigure}>打开登记的主图候选</button>
      {details.researchRef&&onOpenResearchCandidate&&<button disabled={busy} onClick={onOpenResearchCandidate}>查看固定研究候选</button>}
      <button disabled={busy||!details.canBrief} onClick={onWriteBrief}>将任务回报记入项目笔记并打开</button>
    </div>
    {details.figureRef&&<p>候选记录：{details.figureRef.id} r{details.figureRef.revision} · {details.figureRef.sha256}</p>}
    {details.researchRef&&<p>研究候选记录：{details.researchRef.id} r{details.researchRef.revision}；审阅与采用另行决定。</p>}
    <details><summary>任务登记的原结果</summary><pre>{JSON.stringify(details.recordedResult,null,2)}</pre></details>
    <p className="quiet">任务状态、候选和采用分别记录；此详情没有签署科研批准或正式验收。</p>
  </>;
}
