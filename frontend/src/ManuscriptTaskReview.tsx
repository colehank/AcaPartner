import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {command,readTask,requestId} from './api';
import type {Session} from './session';

type RecordValue=Record<string,any>;
export type ManuscriptTaskSnapshot={task:RecordValue,view:RecordValue};
type IO={readTask:(id:string)=>Promise<any>,command:(action:string,fields:Record<string,any>)=>Promise<any>};
export type DecisionSelection={scope:'item'|'opinion'|'dependency'|'all'|'acknowledge',id?:string,decision:'accept'|'reject'};
const failure=(message:string):never=>{throw new Error(message);};
const sha=(value:any)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const revision=(value:any)=>Number.isInteger(value)&&value>0;
const text=(value:any)=>typeof value==='string';
const ident=(value:any)=>text(value)&&value.length>0&&value.length<=200&&!/[\s/\\\u0000-\u001f]/u.test(value);
const targetKey=(target:RecordValue)=>JSON.stringify(Object.fromEntries(Object.keys(target).sort().map(key=>[key,target[key]])));
const errorText=(error:unknown)=>error instanceof Error?error.message:String(error);
const opinionIds=(row:any):string[]=>row.opinion_ids||[row.opinion_id];
export function dependencyChangeIds(view:any,group:any):string[]{
  const keys=group.target_indices.map((i:number)=>targetKey(view.targets[i].target));
  return (view.proposal?.changes||[]).filter((row:any)=>keys.includes(targetKey(row.target))).map((row:any)=>row.id);
}

/** Validate the actual public v2 response before rendering or collecting writes. */
export function checkedManuscriptTask(task:any,view:any,projectId:string,taskId:string):ManuscriptTaskSnapshot {
  const contract=task?.payload?.context?.manuscript_revision;
  if(task?.id!==taskId||task?.project_id!==projectId||task?.payload?.kind!=='manuscript_revision'||![2,3].includes(contract?.version)||
    !ident(contract.object_id)||view?.version!==contract.version||view.task_id!==taskId||view.target?.id!==contract.object_id||!text(view.task_status)||!text(view.target.title))
    failure('任务、项目或公共修订合同身份不符；未显示其他任务。');
  if(!Array.isArray(view.targets)||!view.targets.length||!Array.isArray(view.opinions)||!view.current_target_revisions||
    Array.isArray(view.current_target_revisions))failure('公共修订视图缺少完整目标和当前版本。');
  if(!Array.isArray(contract.targets)||contract.targets.length!==view.targets.length||!Array.isArray(contract.opinions)||
    contract.opinions.length!==view.opinions.length)failure('公共视图与原合同目标或意见不一致。');
  const objects=new Set<string>([contract.object_id]),targets=new Set<string>(),opinions=new Map<string,any>();
  for(const [index,entry] of view.targets.entries()){
    const t=entry?.target;
    const visual=contract.version===3&&t?.kind==='figure'&&t?.field==='visual_overlays'&&
      Array.isArray(t.artist_ids)&&t.artist_ids.length>0&&t.artist_ids.every(ident)&&new Set(t.artist_ids).size===t.artist_ids.length;
    if(!t||!ident(t.object_id)||!text(entry.before)||(!visual&&(!['manuscript','workshop_note'].includes(t.kind)||
      (t.field==='caption'?t.kind!=='manuscript'||!ident(t.component_id):!ident(t.block_id)))))
      failure('修订目标没有准确正文、保存图注或笔记身份。');
    const frozen=contract.targets[index];
    if(!frozen?.target||targetKey(t)!==targetKey(frozen.target)||entry.before!==frozen.before)failure('显示目标或原文不同于本任务冻结合同。');
    const key=targetKey(t);if(targets.has(key))failure('修订目标身份重复。');
    targets.add(key);objects.add(t.object_id);
    if(!revision(view.current_target_revisions[t.object_id])||entry.current_revision!==view.current_target_revisions[t.object_id])
      failure('目标当前版本与完整版本表不符。');
  }
  if(Object.keys(view.current_target_revisions).length!==objects.size||[...objects].some(id=>!revision(view.current_target_revisions[id]))||
    view.target.current_revision!==view.current_target_revisions[contract.object_id])failure('必须保留本轮全部目标的当前版本表。');
  for(const opinion of view.opinions){
    if(!ident(opinion.id)||opinions.has(opinion.id)||!text(opinion.text)||!Array.isArray(opinion.target_indices)||
      !opinion.target_indices.length||opinion.target_indices.some((i:any)=>!Number.isInteger(i)||i<0||i>=view.targets.length))
      failure('意见与准确目标的关联无效。');
    const frozen=contract.opinions.find((o:any)=>o.id===opinion.id);
    if(!frozen||frozen.text!==opinion.text||JSON.stringify(frozen.target_indices)!==JSON.stringify(opinion.target_indices))
      failure('显示意见不同于本任务原始意见。');
    opinions.set(opinion.id,opinion);
  }
  if(contract.version===3){
    const groups=view.dependency_groups,names=new Set<string>(),used=new Set<number>();
    if(!Array.isArray(groups)||JSON.stringify(groups)!==JSON.stringify(contract.dependency_groups))failure('显示关联组不同于冻结合同。');
    for(const group of groups){
      if(!ident(group.id)||names.has(group.id)||!Array.isArray(group.target_indices)||group.target_indices.length<2||
        group.target_indices.some((i:any)=>!Number.isInteger(i)||i<0||i>=view.targets.length||used.has(i))||
        new Set(group.target_indices).size!==group.target_indices.length)failure('关联组目标重复或无效。');
      names.add(group.id);group.target_indices.forEach((i:number)=>used.add(i));
    }
  }
  const p=view.proposal;
  if(p){
    const pin=task.result?.manuscript_revision;
    if(p.task_id!==taskId||p.candidate?.kind!=='manuscript_revision'||!text(p.candidate.summary)||!sha(p.proposal_sha256)||!sha(p.candidate_sha256)||p.proposal_sha256!==pin?.proposal_sha256||
      p.candidate_sha256!==pin?.candidate_sha256||!Array.isArray(p.responses)||!Array.isArray(p.changes)||
      !Number.isInteger(view.decision_version)||view.decision_version<0)failure('候选身份或决定版本已变化；请刷新原任务。');
    const responses=new Set<string>(),changes=new Set<string>();
    for(const response of p.responses){
      if(!opinions.has(response.opinion_id)||responses.has(response.opinion_id)||!text(response.text)||!text(response.verification)||
        !text(response.limitations))failure('逐条回应与原意见不一致。');
      responses.add(response.opinion_id);
    }
    if(responses.size!==opinions.size)failure('真实候选尚未提供本轮全部逐条回应。');
    for(const row of p.changes){
      const index=view.targets.findIndex((t:any)=>targetKey(t.target)===targetKey(row.target||{}));
      const linked=opinionIds(row);
      if(!ident(row.id)||changes.has(row.id)||!opinions.has(row.opinion_id)||index<0||
        !opinions.get(row.opinion_id).target_indices.includes(index)||!text(row.before)||!text(row.after)||
        !['pending','accepted','rejected'].includes(row.state))failure('候选变化不属于准确意见或冻结目标。');
      if(contract.version===3&&(!Array.isArray(linked)||!linked.length||!linked.includes(row.opinion_id)||
        new Set(linked).size!==linked.length||linked.some((id:any)=>!opinions.has(id)||!opinions.get(id).target_indices.includes(index))))
        failure('合并变化没有保留全部关联意见的目标身份。');
      if(contract.version===2&&row.opinion_ids!==undefined)failure('旧合同不能增加合并意见字段。');
      changes.add(row.id);
    }
    if(contract.version===3)for(const response of p.responses){
      const expected=p.changes.filter((row:any)=>opinionIds(row).includes(response.opinion_id)).map((row:any)=>row.id).sort();
      if(!Array.isArray(response.change_ids)||JSON.stringify([...response.change_ids].sort())!==JSON.stringify(expected))failure('逐意见回应与合并候选身份不符。');
    }
  }
  return {task,view};
}

/** No polling: a later explicit load or unmount makes earlier reads inert. */
export class ManuscriptTaskReader {
  private serial=0;
  invalidate(){this.serial++;}
  start(projectId:string,taskId:string,io:IO={readTask,command}){
    const serial=++this.serial,current=()=>serial===this.serial;
    const result=(async()=>{
      const task=await io.readTask(taskId);if(!current())return null;
      if(task?.id!==taskId||task?.project_id!==projectId||task?.payload?.kind!=='manuscript_revision')failure('任务不属于此项目的文稿修订。');
      const view=await io.command('manuscript.revision.view',{task_id:taskId});if(!current())return null;
      return checkedManuscriptTask(task,view,projectId,taskId);
    })();return {current,result};
  }
}

export function collectManuscriptDecision(snapshot:ManuscriptTaskSnapshot,selection:DecisionSelection,
  draft:{ready:boolean,dirty:boolean},requestKey:string){
  const {task,view}=checkedManuscriptTask(snapshot.task,snapshot.view,snapshot.task.project_id,snapshot.task.id),p=view.proposal;
  if(!p||!view.can_decide)failure(view.block_reason||'本轮当前不可决定；原候选与手改保留。');
  if(!['item','opinion','dependency','all','acknowledge'].includes(selection.scope))failure('决定必须明确选择项、意见组或全部待定项。');
  if(!ident(requestKey))failure('决定必须有稳定请求身份。');
  const pending=p.changes.filter((row:any)=>row.state==='pending');
  let rows:any[];
  if(selection.scope==='acknowledge'){
    if(p.changes.length)failure('有实际变更的回合不能以空决定确认。');rows=[];
  }else{
    if(selection.scope==='dependency'){
      const group=(view.dependency_groups||[]).find((g:any)=>g.id===selection.id);
      if(!group)failure('所选关联组不在本次固定合同中。');
      const ids=dependencyChangeIds(view,group);rows=pending.filter((r:any)=>ids.includes(r.id));
    }else rows=selection.scope==='all'?pending:selection.scope==='item'?pending.filter((r:any)=>r.id===selection.id):pending.filter((r:any)=>opinionIds(r).includes(selection.id!));
    if(!rows.length)failure('所选意见或项没有待决定变化。');
  }
  for(const group of view.dependency_groups||[]){
    const ids=dependencyChangeIds(view,group),picked=new Set(rows.map(r=>r.id));
    if(ids.some(id=>picked.has(id))&&!ids.every(id=>picked.has(id)))failure('关联组必须整体决定，请选择该组或全部待定项。');
  }
  if(!['accept','reject'].includes(selection.decision))failure('决定只能接受或拒绝准确变更。');
  if(selection.decision==='accept'&&rows.length&&(!draft.ready||draft.dirty||rows.some(r=>!r.can_accept)))
    failure('当前有未保存手改或目标冲突；不能接受旧候选覆盖它。');
  return {task_id:task.id,candidate_sha256:p.candidate_sha256,proposal_sha256:p.proposal_sha256,
    expected_decision_version:view.decision_version,expected_target_revisions:{...view.current_target_revisions},
    decisions:rows.map(row=>({change_id:row.id,decision:selection.decision})),request_key:requestKey};
}

/** A fixed candidate decision grant never starts or resumes its producer. */
export function collectDecisionAuthorization(view:any,requestKey:string,taskContractSha?:string){
  const p=view?.proposal,map=view?.current_target_revisions;
  if(view?.can_authorize_decisions!==true||view.can_decide||!p||!['generated','review'].includes(view.task_status))
    failure('当前候选没有可显式重新授权的审阅权限；原文与历史保留。');
  if(!ident(view.task_id)||p.task_id!==view.task_id||!sha(p.candidate_sha256)||!sha(p.proposal_sha256)||
    !sha(view.contract_sha256)||p.contract_sha256!==view.contract_sha256||
    (taskContractSha!==undefined&&taskContractSha!==view.contract_sha256)||!ident(requestKey)||
    !Number.isSafeInteger(view.decision_version)||view.decision_version<0)
    failure('固定候选、原合同或决定版本不完整；请刷新核对。');
  const ids=new Set<string>([view.target?.id]);
  if(!ident(view.target?.id)||!Array.isArray(view.targets)||!view.targets.length||!map||Array.isArray(map)||typeof map!=='object')
    failure('授权需要完整目标身份与当前版本。');
  for(const entry of view.targets){
    const id=entry?.target?.object_id;
    if(!ident(id)||!revision(map[id])||entry.current_revision!==map[id])failure('授权目标当前版本不符。');
    ids.add(id);
  }
  if(Object.keys(map).length!==ids.size||[...ids].some(id=>!revision(map[id]))||view.target.current_revision!==map[view.target.id])
    failure('授权需要本轮全部目标的准确版本。');
  return {task_id:view.task_id,candidate_sha256:p.candidate_sha256,proposal_sha256:p.proposal_sha256,
    contract_sha256:view.contract_sha256,expected_decision_version:view.decision_version,
    expected_target_revisions:structuredClone(map),approved:true,request_key:requestKey};
}
export function checkedDecisionAuthorizationReceipt(receipt:any,fields:ReturnType<typeof collectDecisionAuthorization>){
  if(receipt?.authorized!==true||receipt.task_id!==fields.task_id||receipt.proposal_sha256!==fields.proposal_sha256||
    receipt.decision_version!==fields.expected_decision_version||receipt.execution_authorized!==false||receipt.source_changed!==false)
    failure('授权返回不属于此固定候选的决定权限；请刷新核对，不重复发送。');
}
export function sameDecisionAuthorization(view:any,fields:ReturnType<typeof collectDecisionAuthorization>){
  const revisions=view?.current_target_revisions;
  return view?.task_id===fields.task_id&&view?.proposal?.proposal_sha256===fields.proposal_sha256&&
    view?.proposal?.candidate_sha256===fields.candidate_sha256&&view?.contract_sha256===fields.contract_sha256&&
    view?.decision_version===fields.expected_decision_version&&revisions&&
    Object.keys(revisions).length===Object.keys(fields.expected_target_revisions).length&&
    Object.entries(fields.expected_target_revisions).every(([id,value])=>revisions[id]===value);
}

function checkedReceipt(receipt:any,fields:ReturnType<typeof collectManuscriptDecision>){
  if(receipt?.task_id!==fields.task_id||receipt.candidate_sha256!==fields.candidate_sha256||receipt.proposal_sha256!==fields.proposal_sha256||
    receipt.decision_version!==fields.expected_decision_version+1||JSON.stringify(receipt.decisions)!==JSON.stringify(fields.decisions))
    failure('决定返回缺少同一任务与候选回执；请刷新核对，不重复发送。');
}
function briefPath(response:any,projectId:string):string {
  const n=response?.note,p=n?.relative_path;
  if(response?.executed!==false||n?.project_id!==projectId||!ident(n.id)||!sha(n.content_sha256)||!text(p)||
    !p.startsWith('notes/')||!p.endsWith('.md')||p.split('/').some((s:string)=>!s||['.','..','.trash','.notebook'].includes(s))||/[\\\u0000-\u001f]/u.test(p))
    failure('简报缺少本项目真实笔记身份；未猜测路径。');
  return p;
}

type Props={session:Session,taskId:string,report:(error:unknown)=>void,
  onOpenNote?:(relativePath:string)=>Promise<void>|void,onChanged?:()=>Promise<void>|void};
export function ManuscriptTaskReview({session:s,taskId,report,onOpenNote,onChanged}:Props){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const [snapshot,setSnapshot]=useState<ManuscriptTaskSnapshot|null>(null),[busy,setBusy]=useState(false),
    [loading,setLoading]=useState(false),[message,setMessage]=useState<{key:string,text:string}|null>(null);
  const reader=useRef(new ManuscriptTaskReader()),actions=useRef(0),actionInFlight=useRef(false),context=useRef('');
  const key=s.project.id+'\n'+taskId;context.current=key;
  const load=async()=>{
    const captured=key,pending=reader.current.start(s.project.id,taskId);setLoading(true);setMessage(null);
    try{const value=await pending.result;if(pending.current()&&context.current===captured)setSnapshot(value);}
    catch(error){if(pending.current()&&context.current===captured){setMessage({key:captured,text:errorText(error)});report(error);}}
    finally{if(pending.current()&&context.current===captured)setLoading(false);}
  };
  useEffect(()=>{setSnapshot(null);setBusy(false);actionInFlight.current=false;actions.current++;void load();return()=>{reader.current.invalidate();actions.current++;};},[s,s.project.id,taskId]);
  const loaded=snapshot?.task.id===taskId&&snapshot.task.project_id===s.project.id?snapshot:null;
  const authorizationScope=useRef({session:s,taskId,loaded});authorizationScope.current={session:s,taskId,loaded};
  const act=async(fn:(current:()=>boolean)=>Promise<void>)=>{
    if(actionInFlight.current||busy||loading)return;actionInFlight.current=true;const captured=key,serial=++actions.current,current=()=>context.current===captured&&actions.current===serial;
    setBusy(true);setMessage(null);try{await fn(current);}catch(error){if(current()){setMessage({key:captured,text:errorText(error)});report(error);}}
    finally{if(current()){actionInFlight.current=false;setBusy(false);}}
  };
  const decide=(selection:DecisionSelection)=>act(async current=>{
    if(!loaded)failure('原任务尚未读取。');
    const requestKey=requestId();
    // Flush only a requested acceptance; a rejection never saves source text.
    if(selection.decision==='accept'&&selection.scope!=='acknowledge'){
      if(!s.paperDraft||s.paperDraft.dirty)failure('请先保存或整理当前手改；不会覆盖草稿。');
      await s.flush();if(!current())return;
      if(!s.persisted||s.error)failure(s.error||'草稿同步尚未完成；没有采用旧候选。');
    }
    const fields=collectManuscriptDecision(loaded!,selection,{ready:!!s.paperDraft,dirty:!!s.paperDraft?.dirty},requestKey);
    const receipt=await command('manuscript.revision.decide',fields);if(!current())return;checkedReceipt(receipt,fields);
    await s.refreshPaper();if(!current())return;s.notify();await load();if(current())await onChanged?.();
  });
  const writeBrief=()=>act(async current=>{
    if(!loaded?.view.proposal||!onOpenNote)failure('尚无真实候选或笔记打开入口。');
    const response=await command('desk.task.brief',{project_id:s.project.id,task_id:taskId});if(!current())return;
    await onOpenNote!(briefPath(response,s.project.id));if(current())await onChanged?.();
  });
  const authorizeDecisions=()=>act(async current=>{
    if(!loaded||!s.paperDraft||s.paperDraft.dirty)return failure('当前手改保留；请先整理草稿再授权此固定候选。');
    if(!sha(loaded.task.payload.revision_contract_sha256))failure('原任务缺少准确合同摘要；请刷新核对。');
    const fields=collectDecisionAuthorization(loaded.view,requestId(),loaded.task.payload.revision_contract_sha256);
    const origin=s,paper=s.paper.id,revision=s.paper.revision,draft=JSON.stringify(s.paperDraft);
    if(loaded.view.target.id!==paper||fields.expected_target_revisions[paper]!==revision)failure('当前稿件版本尚未与候选视图核对；请刷新。');
    const same=()=>{
      const latest=authorizationScope.current,value=latest.loaded?.view;
      return current()&&latest.session===origin&&latest.taskId===fields.task_id&&
        origin.paper.id===paper&&origin.paper.revision===revision&&JSON.stringify(origin.paperDraft)===draft&&
        sameDecisionAuthorization(value,fields);
    };
    await s.flush();if(!same())return;
    if(!s.persisted||s.error)failure(s.error||'草稿同步未完成；没有发送新的审阅授权。');
    const receipt=await command('manuscript.revision.authorize_decisions',fields);if(!same())return;
    checkedDecisionAuthorizationReceipt(receipt,fields);await load();
  });
  return <section className="review-panel mr-task-review" aria-label={`公共稿件任务审阅 ${taskId}`}>
    <div className="panel-tools"><strong>原任务的逐意见审阅</strong><button disabled={busy||loading} onClick={()=>void load()}>刷新原任务</button></div>
    {loading&&<p role="status">读取原合同、目标和候选…</p>}
    {message?.key===key&&<p role="alert">{message.text}</p>}
    {loaded&&<ManuscriptTaskReviewContent snapshot={loaded} disabled={busy||loading||message?.key===key} draft={{ready:!!s.paperDraft,dirty:!!s.paperDraft?.dirty}}
      onDecide={decide} onAuthorizeDecisions={authorizeDecisions} onWriteBrief={onOpenNote?writeBrief:undefined}/>}
  </section>;
}

export function ManuscriptTaskReviewContent({snapshot,disabled=false,draft,onDecide,onAuthorizeDecisions,onWriteBrief}:{snapshot:ManuscriptTaskSnapshot,
  disabled?:boolean,draft:{ready:boolean,dirty:boolean},onDecide:(selection:DecisionSelection)=>void,onAuthorizeDecisions?:()=>void,onWriteBrief?:()=>void}){
  const {task,view}=checkedManuscriptTask(snapshot.task,snapshot.view,snapshot.task.project_id,snapshot.task.id),p=view.proposal;
  const native=task.payload.context.manuscript_revision.native_note_context;
  const pending=(p?.changes||[]).filter((r:any)=>r.state==='pending');
  const can=(selection:DecisionSelection)=>{try{collectManuscriptDecision(snapshot,selection,draft,'offline-collect-check');return !disabled;}catch{return false;}};
  const canAuthorize=()=>{try{if(!sha(task.payload.revision_contract_sha256))return false;collectDecisionAuthorization(view,'offline-authorization-check',task.payload.revision_contract_sha256);return true;}catch{return false;}};
  const buttons=(scope:DecisionSelection['scope'],id?:string)=><div className="mr-task-actions">
    <button disabled={!can({scope,id,decision:'accept'})} onClick={()=>onDecide({scope,id,decision:'accept'})}>接受{scope==='dependency'?'此关联组':scope==='opinion'?'此意见组':scope==='all'?'全部待定项':'此项'}</button>
    <button disabled={!can({scope,id,decision:'reject'})} onClick={()=>onDecide({scope,id,decision:'reject'})}>拒绝{scope==='dependency'?'此关联组':scope==='opinion'?'此意见组':scope==='all'?'全部待定项':'此项'}</button>
  </div>;
  return <>
    <h2>{view.target.title}</h2><p>{task.id} · 实际状态 {view.task_status} · 原稿 r{view.target.base_revision} → 当前 r{view.target.current_revision}</p>
    <details><summary>本轮 {view.targets.length} 个准确目标与当前版本</summary>{view.targets.map((entry:any,i:number)=><p key={i}>{entry.target.kind==='figure'?'图中元素':entry.target.field==='caption'?'保存图注':entry.target.kind==='workshop_note'?'章节工坊笔记':'稿件正文'} · {entry.target.object_id} · {entry.target.artist_ids?.join('、')||entry.target.component_id||entry.target.block_id} · r{entry.current_revision}</p>)}</details>
    {Array.isArray(native?.notes)&&native.notes.length>0&&<details><summary>本轮固定原生笔记阅读上下文</summary><p>提供保存版不等于已核实读取；这些笔记不能在本轮被改写。上下文 SHA：{native.sha256}</p>{native.notes.map((note:any)=><article key={note.id}><h3>{note.relative_path} · r{note.revision}</h3><small>{note.id} · {note.content_sha256}</small><pre>{note.markdown}</pre></article>)}</details>}
    {draft.dirty&&<p role="status">未保存手改保留；接受按钮暂不可用，拒绝不保存源稿。</p>}
    {view.block_reason&&<p role="status">{view.block_reason}</p>}
    {canAuthorize()&&onAuthorizeDecisions&&<div><p>仅授权此固定候选的下一批接受或拒绝；不会重新调用模型或自动采用。</p><button disabled={disabled||!draft.ready||draft.dirty} onClick={onAuthorizeDecisions}>重新授权审阅此固定候选</button></div>}
    {p?<p className="mr-task-summary">{p.candidate.summary}</p>:<p role="status">原任务尚无真实候选；原内容保留。</p>}
    {view.opinions.map((opinion:any)=>{const response=p?.responses.find((r:any)=>r.opinion_id===opinion.id),rows=(p?.changes||[]).filter((r:any)=>opinionIds(r).includes(opinion.id));return <article key={opinion.id} aria-label={`原意见 ${opinion.id}`}>
      <h3>原意见 · {opinion.adoption_state||'待回应'}</h3><blockquote>{opinion.text}</blockquote>
      {response&&<><h4>Agent 原回应</h4><p>{response.text}</p><p>核查：{response.verification}</p><p>限制：{response.limitations}</p></>}
      {rows.map((row:any)=><section key={row.id} className="mr-task-change" aria-label={`候选项 ${row.id}`}>
        <h4>{row.target.kind==='figure'?'图中元素视觉建议':row.target.field==='caption'?'保存图注':row.target.kind==='workshop_note'?'章节工坊笔记':'稿件正文'} · {row.target.artist_ids?.join('、')||row.target.component_id||row.target.block_id} · {row.state}</h4>
        <div className="mr-task-diff"><div><strong>原文</strong><pre>{row.before}</pre></div><div><strong>建议</strong><pre>{row.after}</pre></div></div>
        <p>理由：{row.reason}</p>{row.conflict&&<p role="alert">{row.conflict_reason||'当前目标已变化'}；当前手改保留。</p>}
        {row.state==='pending'?buttons('item',row.id):<p>实际决定：{row.state} · {row.decision_receipt?.operator||'查看决定回执'}</p>}
      </section>)}
      {rows.length?buttons('opinion',opinion.id):response&&<p>这条意见没有提出内容变化；回应不代表自动解决。</p>}
    </article>;})}
    {(view.dependency_groups||[]).map((group:any)=><section key={group.id} aria-label={'关联组 '+group.id}><h3>关联组 · {group.id}</h3><p>此组所有实际改动一同采用或拒绝；其中的源稿和图先共同检查。</p>{buttons('dependency',group.id)}</section>)}
    {pending.length>0&&buttons('all')}
    {p&&!p.changes.length&&<button disabled={!can({scope:'acknowledge',decision:'reject'})} onClick={()=>onDecide({scope:'acknowledge',decision:'reject'})}>确认已审阅无变更回应</button>}
    {p&&<details><summary>实际候选与决定记录</summary><p>候选 {p.candidate_sha256}<br/>提案 {p.proposal_sha256} · 决定版本 {view.decision_version}</p><pre>{JSON.stringify(view.decisions||[],null,2)}</pre></details>}
    <button disabled={disabled||!p||!onWriteBrief} onClick={onWriteBrief}>将原任务实际回报记入笔记并打开</button>
    <p className="quiet">独立改动可分别决定，明确关联组须整体决定；意见不会自动解决，采用不代表科研批准或正式验收。</p>
  </>;
}
