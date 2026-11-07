import {ReviewVisualPreview,type ReviewVisualPreviewIdentity} from './ReviewVisualPreview';
import {SlotAdoptionControl,slotAdoptionProblem} from './SlotAdoptionControl';
import {mainFigureOpinionError,mainFigureOpinionViewError,mainFigureOpinionWire,type MainFigureOpinionAnchor} from './MainFigureOpinionControl';
import {isFigureOpinionAnchor,figureOpinionError as leafError,figureOpinionViewError as leafViewError,figureOpinionWire as leafWire,type FigureOpinionAnchor} from './FigureOpinionControl';
import {isCaptionComposerAnchor,captionComposerError,captionWireAnchor,type CaptionComposerAnchor} from './PaperCaptionSelection';
import {useEffect,useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import {command,requestId} from './api';
import {Session} from './session';
import type {PaperReviewAnchor} from './PaperReviewProjection';
import {NativeReviewContext,validateNativeNote} from './NativeReviewContext';
import {actualTaskBrief,type TaskBriefRef} from './TaskDetails';
import {ReviewAuthor} from './ReviewAuthor';
import {paperReviewNavigationItems,reviewNavigationScope,type ReviewNavigation} from './ReviewNavigation';
import {collectDecisionAuthorization,checkedDecisionAuthorizationReceipt,sameDecisionAuthorization} from './ManuscriptTaskReview';

type SavedFigureAnchor=FigureOpinionAnchor|MainFigureOpinionAnchor;
const isSavedFigureAnchor=(value:any):value is SavedFigureAnchor=>value?.kind==='main_figure_slots'||isFigureOpinionAnchor(value);
const isFigureField=(field:unknown)=>field==='visual_overlays'||field==='slot_layout';
const figureOpinionError=(a:SavedFigureAnchor,s:Session)=>a.kind==='main_figure_slots'?mainFigureOpinionError(a,s):leafError(a,s);
const figureOpinionViewError=(a:SavedFigureAnchor,v:any)=>a.kind==='main_figure_slots'?mainFigureOpinionViewError(a,v):leafViewError(a,v);
const figureOpinionWire=(a:SavedFigureAnchor)=>a.kind==='main_figure_slots'?mainFigureOpinionWire(a):leafWire(a);
const figureOpinionLabel=(a:SavedFigureAnchor)=>a.kind==='main_figure_slots'?(a.slot_labels||[]).map(slot=>`${slot.label}（${slot.id}）`).join('、'):`${a.artist_label}（${a.artist_id}）`;
const matchesFigureKind=(o:any,a:SavedFigureAnchor)=>o.field===(a.kind==='main_figure_slots'?'slot_layout':'visual_overlays');

export function roundResourceBudget(calls:string,seconds:string){
  if(!/^[12]$/.test(calls)||!/^\d+$/.test(seconds))return null;
  const timeout=Number(seconds);
  return Number.isSafeInteger(timeout)&&timeout>=1&&timeout<=600?{max_model_calls:Number(calls),timeout_seconds:timeout}:null;
}

const canonicalTarget=(value:any):any=>Array.isArray(value)?value.map(canonicalTarget):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonicalTarget(value[key])])):value;
const sameTarget=(a:any,b:any)=>JSON.stringify(canonicalTarget(a))===JSON.stringify(canonicalTarget(b));
const changeOpinions=(row:any):string[]=>Array.isArray(row.opinion_ids)?row.opinion_ids:[row.opinion_id];
// Preview only the existing server target coalescing: one target per figure,
// saved caption occurrence or manuscript block. The server freezes authority.
function opinionTargetKeys(opinion:any,paperId:string):string[]{
  const object=opinion.base_ref?.id||paperId;
  if(isFigureField(opinion.field))return opinion.base_ref?.id?[JSON.stringify(['figure',object])]:[];
  if(opinion.field==='caption')return opinion.component_id?[JSON.stringify(['caption',object,opinion.component_id])]:[];
  const blocks=opinion.anchor?.kind==='manuscript_range'?opinion.anchor.segments?.map((part:any)=>part.block_id):[opinion.anchor?.block_id||opinion.block_id];
  return Array.isArray(blocks)&&blocks.length&&blocks.every((id:any)=>typeof id==='string'&&id)?[...new Set(blocks.map((id:string)=>JSON.stringify(['block',object,id])))]:[];
}
function dependencyError(view:any){
  const groups=view?.dependency_groups;if(groups===undefined)return undefined;
  if(!Array.isArray(groups)||groups.some((group:any)=>!group||typeof group.id!=='string'||!Array.isArray(group.target_indices)||!group.target_indices.length||new Set(group.target_indices).size!==group.target_indices.length||group.target_indices.some((index:any)=>!Number.isSafeInteger(index)||index<0||!view.targets?.[index]?.target)))return '关联组身份不完整，请刷新实际候选；没有提交决定。';
  if(groups.length&&(view.proposal?.changes||[]).some((change:any)=>view.targets.filter((entry:any)=>sameTarget(entry.target,change.target)).length!==1))return '候选目标未准确对应冻结目标；没有猜测关联组。';
}
function relatedDecisionRows(view:any,rows:any[]){
  if(!rows.length||rows.some(row=>!row)||dependencyError(view))return rows;
  const changes=view?.proposal?.changes||[],selected=new Set(rows.map(row=>row.id));let expanded=true;
  while(expanded){expanded=false;for(const group of view?.dependency_groups||[]){
    const members=changes.filter((change:any)=>group.target_indices.some((index:number)=>sameTarget(view.targets[index].target,change.target)));
    if(members.some((change:any)=>selected.has(change.id)))for(const change of members)if(!selected.has(change.id)){selected.add(change.id);expanded=true;}
  }}
  return changes.filter((change:any)=>selected.has(change.id));
}
function completeDecisionRows(view:any,rows:any[]){return !dependencyError(view)&&!rows.some(row=>!row)&&relatedDecisionRows(view,rows).length===rows.length;}

export function ReviewBody({session:s,report,initialBlock,initialTask,initialAnchor,navigation,onOpenNote,onOpenFigure}:{session:Session,report:(e:unknown)=>void,initialBlock?:string,initialTask?:string,initialAnchor?:PaperReviewAnchor|CaptionComposerAnchor|SavedFigureAnchor,navigation?:ReviewNavigation,onOpenNote?:(path:string)=>Promise<void>|void,onOpenFigure?:(id:string,revision:number,selection:string|string[])=>Promise<void>|void}){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const [readReview,setReadReview]=useState<any>(null),[readView,setReadView]=useState<any>(null);
  const initialInput=()=>({text:s.reviewComposer?.text||'',block:initialBlock||s.reviewComposer?.block||s.paper.content.blocks[0]?.id||'',request:s.reviewComposer?.request||'处理本轮保留意见，逐条说明回应与限制；不新增科研结论或计算。'});
  const [composer,setComposer]=useState(()=>({session:s,...initialInput()}));
  const {text,block,request}=composer.session===s?composer:initialInput();
  const input=(key:'text'|'block'|'request',value:string|((old:string)=>string))=>setComposer(old=>{const current=old.session===s?old:{session:s,...initialInput()};return {...current,[key]:typeof value==='function'?value(current[key]):value};});
  const setText=(v:string|((old:string)=>string))=>input('text',v),setBlock=(v:string)=>input('block',v),setRequest=(v:string)=>input('request',v);
  const [provider,setProvider]=useState(''),[actionBusy,setBusy]=useState(false),[selected,setSelected]=useState(initialTask||''),[editing,setEditing]=useState(''),[editText,setEditText]=useState('');
  const [pausePending,setPausePending]=useState<any>(null),pauseRequest=useRef<any>(null);
  const [modelCalls,setModelCalls]=useState('1'),[modelSeconds,setModelSeconds]=useState('300');
  const [briefNotice,setBriefNotice]=useState<{session:Session,project:string,paper:string,revision:number,selected:string,task:string,ref:TaskBriefRef}|null>(null);
  const [picked,setPicked]=useState<{session:Session|null,scope:string,ids:string[]}>({session:null,scope:'',ids:[]});
  const anchor=initialAnchor||s.reviewComposer?.anchor;
  // The public Session owns persistence through its existing composer CAS.
  const dependencyGroups=s.reviewComposer.dependencyGroups||[];
  const slotAdoptions=s.reviewComposer.slotAdoptions||[];
  const [groupSelection,setGroupSelection]=useState<{session:Session,ids:string[]}>({session:s,ids:[]});
  const selectedOpinionIds=groupSelection.session===s?groupSelection.ids:[];
  const [groupEditor,setGroupEditor]=useState<Session|null>(null),groupEditing=groupEditor===s;
  const saveGroups=(groups:{id:string,opinion_ids:string[]}[])=>{const composer={...s.reviewComposer,dependencyGroups:structuredClone(groups)};s.setReviewComposer(composer);};
  const figureAnchor=isSavedFigureAnchor(anchor)?anchor:null;
  const figureKey=JSON.stringify(figureAnchor),figureScope=useRef({session:s,key:figureKey});figureScope.current={session:s,key:figureKey};
  const [figureRead,setFigureRead]=useState<{session:Session,key:string,error?:string}|null>(null);
  useEffect(()=>{let live=true;setFigureRead(null);if(!figureAnchor)return;const problem=figureOpinionError(figureAnchor,s);
    if(problem){setFigureRead({session:s,key:figureKey,error:problem});return;}
    command('desk.figure.read',{project_id:s.project.id,id:figureAnchor.object_id}).then(value=>{if(live)setFigureRead({session:s,key:figureKey,error:figureOpinionViewError(figureAnchor,value)});}).catch(error=>{if(live)setFigureRead({session:s,key:figureKey,error:String(error)});});
    return()=>{live=false;};
  },[s,s.project.id,s.paper.id,s.paper.revision,figureKey]);
  const figureError=figureAnchor?(figureOpinionError(figureAnchor,s)||(figureRead?.session===s&&figureRead.key===figureKey?figureRead.error:'正在核对所选保存图元素…')):undefined;
  useEffect(()=>{if(figureAnchor&&figureAnchor.project_id!==s.project.id)return;s.setReviewComposer({...s.reviewComposer,text,request,block,anchor});},[s,text,request,block,anchor]);
  const roundBudget=roundResourceBudget(modelCalls,modelSeconds);
  const editRef=useRef(editText);editRef.current=editText;
  const context=useRef({session:s,project:s.project.id,paper:s.paper.id,revision:s.paper.revision,selected}),sequence=useRef(0),live=useRef(true),readScope=useRef('');
  context.current={session:s,project:s.project.id,paper:s.paper.id,revision:s.paper.revision,selected};
  const matchesPaper=(value:any)=>value?.session===s&&value.project===s.project.id&&value.paper===s.paper.id&&value.revision===s.paper.revision;
  const review=matchesPaper(readReview)?readReview.value:null;
  const reviewElement=useRef<HTMLElement|null>(null),shownNavigation=useRef('');
  const navigationSelection=JSON.stringify([navigation?.scope,navigation?.activeKeys,navigation?.activationId]);
  useLayoutEffect(()=>{
    const element=reviewElement.current;
    if(!element||!navigation?.activeKeys.length||shownNavigation.current===navigationSelection)return;
    const targets=Array.from(element.querySelectorAll<HTMLElement>('article[data-review-key]')).filter(row=>navigation.activeKeys.includes(row.dataset.reviewKey!));
    if(!targets.length||!element.clientHeight)return;
    shownNavigation.current=navigationSelection;
    const viewport=element.getBoundingClientRect(),rects=targets.map(row=>row.getBoundingClientRect());
    const first=rects[0],top=Math.min(...rects.map(r=>r.top)),bottom=Math.max(...rects.map(r=>r.bottom));
    const upper=viewport.top+element.clientTop,lower=upper+element.clientHeight;
    const delta=bottom-top>element.clientHeight?first.top-upper:top<upper?top-upper:bottom>lower?bottom-lower:0;
    // Move only this opinion pane, once per explicit topic selection. Polling
    // and manual scrolling must not keep pulling the reader back to the row.
    element.scrollTop+=delta;
  },[navigationSelection,review]);
  const activeTask=selected||review?.rounds.at(-1)?.task_id;
  const view=matchesPaper(readView)&&readView.task===activeTask?readView.value:null;
  const briefScope=useRef<any>(null);
  briefScope.current={session:s,project:s.project.id,paper:s.paper.id,revision:s.paper.revision,selected,task:activeTask};
  const sameBriefScope=(a:any,b:any)=>!!a&&!!b&&a.session===b.session&&a.project===b.project&&a.paper===b.paper&&
    a.revision===b.revision&&a.selected===b.selected&&a.task===b.task;
  const currentBrief=briefNotice&&sameBriefScope(briefNotice,briefScope.current)&&view?.task_id===briefNotice.task?briefNotice:null;
  const pauseScope=useRef<any>(null);
  pauseScope.current={session:s,project:s.project.id,paper:s.paper.id,revision:s.paper.revision,task:activeTask,initialTask};
  const samePauseScope=(a:any,b:any)=>!!a&&!!b&&a.session===b.session&&a.project===b.project&&a.paper===b.paper&&a.revision===b.revision&&a.task===b.task&&a.initialTask===b.initialTask;
  const pausing=samePauseScope(pausePending,pauseScope.current),busy=actionBusy||pausing;
  const authorizationView=useRef<any>(null);authorizationView.current=view;
  const selectionScope=JSON.stringify([s.project.id,s.paper.id,activeTask,view?.proposal?.candidate_sha256,view?.proposal?.proposal_sha256]);
  const currentSelection=useRef({session:s,scope:selectionScope});currentSelection.current={session:s,scope:selectionScope};
  const pickedIds=picked.session===s&&picked.scope===selectionScope?picked.ids:[];
  useEffect(()=>{setPicked(value=>value.session===s&&value.scope===selectionScope?value:{session:s,scope:selectionScope,ids:[]});},[s,selectionScope]);
  const load=async()=>{
    const origin=context.current,read=++sequence.current;
    const current=()=>live.current&&read===sequence.current&&context.current.session===origin.session&&context.current.project===origin.project&&context.current.selected===origin.selected&&origin.session.paper.id===origin.paper&&origin.session.paper.revision===origin.revision;
    const scope=JSON.stringify([origin.project,origin.paper,origin.revision,origin.selected]);
    if(readScope.current!==scope){readScope.current=scope;setReadView(null);s.setReviewProjection(null,null);}
    try{
      const x=await command('desk.review.read',{project_id:origin.project});if(!current())return;
      setReadReview({...origin,value:x});s.setReviewProjection(x);
      const last=origin.selected||x.rounds.at(-1)?.task_id;
      if(!last){setReadView(null);s.setReviewProjection(x,null);return;}
      const next=await command('desk.review.view',{project_id:origin.project,task_id:last});
      if(current()&&next.task_id===last){setReadView({...origin,task:last,value:next});s.setReviewProjection(x,next);}
    }catch(e){if(current()){setReadReview(null);setReadView(null);s.setReviewProjection(null,null);report(e);}}
  };
  useEffect(()=>{live.current=true;load();const timer=setInterval(load,2200);return()=>{live.current=false;++sequence.current;clearInterval(timer);};},[s,s.project.id,s.paper.id,s.paper.revision,selected]);
  useEffect(()=>{if(initialBlock)setBlock(initialBlock);},[initialBlock]);
  useEffect(()=>{if(initialTask)setSelected(initialTask);},[initialTask]);
  const actionLock=useRef<any>(null);
  useEffect(()=>{actionLock.current=null;setBusy(false);setEditing('');},[s,s.project.id]);
  const act=async(fn:()=>Promise<void|false>)=>{const origin=context.current;if(actionLock.current?.session===origin.session&&actionLock.current.project===origin.project)return;const token={session:origin.session,project:origin.project};actionLock.current=token;const current=()=>live.current&&context.current.session===origin.session&&context.current.project===origin.project;setBusy(true);try{if(await fn()!==false&&current())await load();}catch(e){if(current())report(e);}finally{if(actionLock.current===token)actionLock.current=null;if(current())setBusy(false);}};
  if(!review)return <div className="loading">读取项目意见…</div>;
  const writeBrief=()=>act(async()=>{
    if(busy||!view?.proposal||view.task_id!==activeTask)return false;
    const origin={...briefScope.current};
    const current=()=>live.current&&sameBriefScope(origin,briefScope.current);
    setBriefNotice(null);
    try{
      const response=await command('desk.task.brief',{project_id:origin.project,task_id:origin.task});
      if(!current())return false;
      const ref=actualTaskBrief(response,origin.project);
      if(typeof response.appended!=='boolean'||ref.relative_path!==`notes/tasks/${origin.task}.md`)
        throw new Error('简报返回与本轮原任务不符；未提供其他笔记的打开入口。');
      await validateNativeNote(response.note,origin.project,ref.relative_path);
      if(!current())return false;
      await origin.session.refresh();
      if(!current())return false;
      setBriefNotice({...origin,ref});
    }catch(error){if(current())throw error;return false;}
  });
  const openBrief=()=>act(async()=>{
    if(busy||!currentBrief||!onOpenNote)return false;
    const origin={...briefScope.current},ref=currentBrief.ref;
    const current=()=>live.current&&sameBriefScope(origin,briefScope.current);
    try{if(current())await onOpenNote(ref.relative_path);}catch(error){if(current())throw error;}
    // Opening is an explicit navigation, not another brief write or a reload
    // of review state that can replace the reader's working context.
    return false;
  });
  const controllable=!!view&&typeof activeTask==='string'&&view.task_id===activeTask&&review.runtime_running===true&&
    review.rounds.some((round:any)=>round.task_id===activeTask&&round.status==='submitted');
  const canPause=controllable&&['queued','running'].includes(view.task_status),canResume=controllable&&['paused','waiting_input'].includes(view.task_status);
  const controlRound=async(operation:'pause'|'resume')=>{
    if(!(operation==='pause'?canPause:canResume)||busy||samePauseScope(pauseRequest.current,pauseScope.current))return;
    const origin={...pauseScope.current,operation,expectedStatus:view.task_status};pauseRequest.current=origin;setPausePending(origin);
    const current=()=>live.current&&pauseRequest.current===origin&&samePauseScope(origin,pauseScope.current);
    try{
      // Stopping the original task must not wait for draft synchronization or
      // replace the user's dirty manuscript, selection or opinion context.
      const receipt=await command('task.control',{id:origin.task,operation,...(operation==='pause'?{expected_status:origin.expectedStatus}:{})});
      if(!current())return;
      if(receipt?.id!==origin.task||receipt.project_id!==origin.project||!(operation==='pause'?receipt.status==='paused':['queued','running'].includes(receipt.status)))
        throw new Error(operation==='pause'?'暂停回执与当前原任务不一致；未确认暂停，请读取实际状态。':'继续回执与当前原任务不一致；未确认继续，请读取实际状态。');
      await load();
    }catch(e){if(current())report(e);}
    finally{
      if(pauseRequest.current===origin)pauseRequest.current=null;
      setPausePending((value:any)=>value===origin?null:value);
    }
  };
  const captionAnchor=isCaptionComposerAnchor(anchor)?anchor:null;
  const captionError=captionAnchor?captionComposerError(captionAnchor,s.project.id,s.paper):undefined;
  const change=(op:string,id?:string)=>act(async()=>{
    const sent=text,sentEdit=editText,origin=context.current,selectedFigure=figureAnchor?structuredClone(figureAnchor):null,key=figureKey;
    const current=()=>live.current&&context.current.session===origin.session&&context.current.project===origin.project&&context.current.paper===origin.paper&&context.current.revision===origin.revision&&figureScope.current.key===key;
    if(op==='create'||op==='reanchor'){
      if(s.paperDraft?.dirty)throw new Error('请先保存文字草稿；当前意见和选区保留。');
      if(selectedFigure){
        const error=figureOpinionError(selectedFigure,s);if(error)throw new Error(error);
        const fresh=await command('desk.figure.read',{project_id:origin.project,id:selectedFigure.object_id});if(!current())return false;
        const problem=figureOpinionError(selectedFigure,s)||figureOpinionViewError(selectedFigure,fresh);if(problem)throw new Error(problem);
      }else if(captionAnchor){const error=captionComposerError(captionAnchor,s.project.id,s.paper);if(error)throw new Error(error);}
    }
    const target=selectedFigure?figureOpinionWire(selectedFigure):captionAnchor?{field:'caption',component_id:captionAnchor.component_id,anchor:captionWireAnchor(captionAnchor)}:{block_id:block,...(anchor?.block_id===block?{anchor}:{})};
    await command('desk.review.change',{project_id:origin.project,expected_review_revision:review.revision,expected_manuscript_revision:origin.revision,op,...(id?{id,...(op==='edit'?{text:sentEdit}:op==='reanchor'?target:{})}:{...target,text:sent})});
    if(!current())return false;
    if(op==='create')setText(current=>current===sent?'':current);if(op==='edit'&&editRef.current===sentEdit)setEditing('');
  });
  const decide=(rows:any[],decision:string)=>act(async()=>{
    const origin=context.current,scope=selectionScope,ids=rows.map(row=>row.id);
    if(!view?.proposal||ids.length===0||new Set(ids).size!==ids.length||rows.some(row=>row.state!=='pending'))throw new Error('请选择准确的待定候选；空项或已有决定项不能合并提交。');
    if(!completeDecisionRows(view,rows))throw new Error('所选候选包含关联组的一部分；请明确选择完整关联组。');
    if(decision==='accept'&&(s.paperDraft!.dirty||rows.some(row=>!row.can_accept)))throw new Error('所选组含手改冲突或当前草稿；整组未采用，请先核对。');
    const input={project_id:origin.project,expected_review_revision:review.revision,task_id:view.task_id,candidate_sha256:view.proposal.candidate_sha256,proposal_sha256:view.proposal.proposal_sha256,
      expected_decision_version:view.decision_version,expected_target_revisions:structuredClone(view.current_target_revisions),decisions:ids.map(id=>({change_id:id,decision})),request_key:requestId()};
    const current=()=>live.current&&context.current.session===origin.session&&context.current.project===origin.project&&context.current.selected===origin.selected&&currentSelection.current.session===origin.session&&currentSelection.current.scope===scope;
    await s.flush();if(!current())return;
    if(!s.persisted)throw new Error('草稿尚未同步；本组决定未发送，请先处理保存错误。');
    if(decision==='accept'&&s.paperDraft!.dirty)throw new Error('等待同步期间产生新手改；本组未采用，当前草稿保留。');
    const receipt=await command('desk.review.decide',input);if(!current())return;
    if(receipt.task_id!==input.task_id||receipt.candidate_sha256!==input.candidate_sha256||receipt.proposal_sha256!==input.proposal_sha256||JSON.stringify(receipt.decisions)!==JSON.stringify(input.decisions))throw new Error('实际决定回执与选中组不一致；保留原选择并重新读取。');
    if(decision==='accept'){
      const figures=new Set(rows.filter(row=>row.target.kind==='figure').map(row=>row.target.object_id));
      s.noteFigureWrites((receipt.objects||[]).filter((row:any)=>row.source_changed===true&&figures.has(row.object_id)));
    }
    setPicked(value=>value.session===s&&value.scope===scope&&value.ids.length===ids.length&&value.ids.every(id=>ids.includes(id))?{...value,ids:[]}:value);
    await s.refreshPaper();if(!current())return;
    if(!s.paperDraft!.dirty){s.resetPaperDraft();await s.flush();if(current())s.notify();}
  });
  const authorizeDecisions=()=>act(async()=>{
    if(!s.paperDraft||s.paperDraft.dirty)throw new Error('当前手改保留；请先整理草稿再授权此固定候选。');
    const origin=context.current,fields=collectDecisionAuthorization(view,requestId()),draft=JSON.stringify(s.paperDraft);
    if(view.target.id!==origin.paper||fields.expected_target_revisions[origin.paper]!==origin.revision)throw new Error('当前稿件版本尚未与候选视图核对；请刷新。');
    const input={project_id:origin.project,expected_review_revision:review.revision,...fields};
    const current=()=>{
      const latest=context.current,value=authorizationView.current;
      return live.current&&latest.session===origin.session&&latest.project===origin.project&&latest.selected===origin.selected&&
        origin.session.paper.id===origin.paper&&origin.session.paper.revision===origin.revision&&JSON.stringify(origin.session.paperDraft)===draft&&
        sameDecisionAuthorization(value,fields);
    };
    await s.flush();if(!current())return false;
    if(!s.persisted||s.error)throw new Error(s.error||'草稿同步未完成；没有发送新的审阅授权。');
    const receipt=await command('desk.review.authorize_decisions',input);if(!current())return false;
    checkedDecisionAuthorizationReceipt(receipt,fields);
  });
  const canAuthorize=()=>{try{collectDecisionAuthorization(view,'offline-authorization-check');return true;}catch{return false;}};
  const visualPreview=(rows:any[])=>{
    if(!view?.proposal||!rows.some(row=>row.target.kind==='figure'))return null;
    const identity:ReviewVisualPreviewIdentity={project_id:s.project.id,task_id:view.task_id,
      candidate_sha256:view.proposal.candidate_sha256,proposal_sha256:view.proposal.proposal_sha256,
      decision_version:view.decision_version,target_revisions:structuredClone(view.current_target_revisions),change_ids:rows.map(row=>row.id)};
    const dirty=()=>!!s.paperDraft?.dirty||rows.some(row=>row.target.kind==='figure'&&(s.figureDrafts[row.target.object_id]||s.compositionDrafts[row.target.object_id]));
    return <ReviewVisualPreview identity={identity} disabled={busy||dirty()||!view.can_decide||!completeDecisionRows(view,rows)||rows.some(row=>!row.can_accept||row.state!=='pending')}
      load={async()=>{
        const origin=context.current,scope=selectionScope;
        await s.flush();
        if(!live.current||context.current.session!==origin.session||context.current.project!==origin.project||currentSelection.current.scope!==scope)throw Error('已离开原候选，未请求预览。');
        if(!s.persisted||s.error||dirty())throw Error('仍有未同步或未保存的手改；请先核对，原输入保留。');
        return command('desk.review.preview',{project_id:identity.project_id,task_id:identity.task_id,
          candidate_sha256:identity.candidate_sha256,proposal_sha256:identity.proposal_sha256,
          expected_review_revision:review.revision,expected_decision_version:identity.decision_version,
          expected_target_revisions:identity.target_revisions,change_ids:identity.change_ids});
      }} onError={report}/>;
  };
  const pending=(view?.proposal?.changes||[]).filter((r:any)=>r.state==='pending');
  const pickedRows=pickedIds.map(id=>view?.proposal?.changes.find((row:any)=>row.id===id));
  const invalidPicked=pickedRows.some(row=>!row||row.state!=='pending')||!completeDecisionRows(view,pickedRows);
  const togglePick=(id:string,checked:boolean)=>setPicked(value=>{const ids=value.session===s&&value.scope===selectionScope?value.ids:[];return {session:s,scope:selectionScope,ids:checked?[...new Set([...ids,id])]:ids.filter(value=>value!==id)};});
  const groupTargets=(ids:string[])=>[...new Set(ids.flatMap(id=>{const opinion=review.opinions.find((o:any)=>o.id===id);return opinion?opinionTargetKeys(opinion,s.paper.id):[];}))];
  const usedGroupTargets=new Set<string>();
  const overlappingGroups=dependencyGroups.some(group=>{const targets=groupTargets(group.opinion_ids),overlaps=targets.length<2||targets.some(key=>usedGroupTargets.has(key));targets.forEach(key=>usedGroupTargets.add(key));return overlaps;});
  const groupProblem=overlappingGroups||dependencyGroups.some(group=>!group.id||!Array.isArray(group.opinion_ids)||group.opinion_ids.length<2||new Set(group.opinion_ids).size!==group.opinion_ids.length||group.opinion_ids.some(id=>!review.opinions.some((o:any)=>o.id===id&&!o.deleted)));
  const slotProblem=slotAdoptionProblem(review.opinions,dependencyGroups,slotAdoptions);
  const groupedOpinionIds=new Set(dependencyGroups.flatMap(group=>group.opinion_ids));
  const selectedGroupTargets=groupTargets(selectedOpinionIds);
  const groupSelectionProblem=selectedOpinionIds.length>=2&&(selectedGroupTargets.length<2||selectedGroupTargets.some(key=>usedGroupTargets.has(key)));
  const canGroup=selectedOpinionIds.length>=2&&!groupSelectionProblem&&selectedOpinionIds.every(id=>review.opinions.some((o:any)=>o.id===id&&!o.deleted)&&!groupedOpinionIds.has(id));
  const unanchored=review.opinions.some((o:any)=>!o.deleted&&review.annotations.find((a:any)=>a.id===o.id)?.status!=='anchored');
  const navigationItems=navigation?paperReviewNavigationItems(s.paper.content.blocks,review,null,view,{paperId:s.paper.id,components:s.paper.content.components||[]}):[];
  const navigationScope=reviewNavigationScope({projectId:s.project.id,paperId:s.paper.id,revision:s.paper.revision,taskId:view?.task_id,candidateSha:view?.proposal?.candidate_sha256,proposalSha:view?.proposal?.proposal_sha256});
  const locate=(key:string)=>{const item=navigationItems.find(item=>item.key===key);if(navigation&&item?.available){if(navigation.scope!==navigationScope){report(new Error('稿件或候选基线已变化，请重新读取后定位；未使用旧回包。'));return;}navigation.onLocate(item);}};
  return <section ref={reviewElement} className="review-panel" aria-label="稿件整轮意见"><h2>稿件整轮意见</h2><button disabled={busy} onClick={()=>act(async()=>{})}>刷新本轮意见</button>
    <p className="quiet">意见、提交、候选与采用各自保留。删除后可恢复；接受旧候选不会覆盖已保存的新手改。</p>
    {!captionAnchor&&!figureAnchor&&<details className="review-whole-block"><summary>整段意见（可选）</summary><label>批注段落<select aria-label="批注段落" value={block} onChange={e=>setBlock(e.target.value)}>{s.paper.content.blocks.map((b:any,i:number)=><option key={b.id} value={b.id}>{i+1} · {b.text.slice(0,35)||'空白段落'}</option>)}</select></label></details>}{!anchor&&<p className="quiet">在左侧稿件中选择文字，再点击“新建批注”，即可将意见固定到真实选区。</p>}
    <label>批注或修改意见<textarea aria-label="本轮修改意见" value={text} onChange={e=>setText(e.target.value)}/></label>
    {figureAnchor&&<p aria-label="意见图元素">{figureAnchor.figure_title} · r{figureAnchor.expected_object_revision} · {figureOpinionLabel(figureAnchor)}{figureAnchor.component_index!==undefined?` · 采用时更新稿内第 ${figureAnchor.component_index+1} 处`:' · 不更新稿内引用'}</p>}{figureError&&<p role="status">{figureError}</p>}
    {anchor&&!figureAnchor&&(captionAnchor||anchor.block_id===block)&&<blockquote aria-label="意见选区">{anchor.quote}</blockquote>}
    {captionAnchor&&<p className="quiet">图注选区 · {captionAnchor.component_id}</p>}{captionError&&<p role="status">{captionError}</p>}
    <button disabled={busy||!text.trim()||s.paperDraft!.dirty||!!captionError||!!figureError} onClick={()=>change('create')}>添加意见</button>{s.paperDraft!.dirty&&<p role="status">请先保存文字草稿，再固定意见上下文或采用候选。</p>}
    <button disabled={busy} aria-pressed={groupEditing} onClick={()=>setGroupEditor(groupEditing?null:s)}>{groupEditing?'收起意见关联':'设置意见关联'}</button>
    <div className="opinion-list">{review.opinions.map((o:any)=><article key={o.id} data-review-key={'opinion:'+o.id} className={o.deleted?'deleted':''} aria-current={navigation?.activeKeys.includes('opinion:'+o.id)?'true':undefined}><small>{o.field==='slot_layout'?'主图图位 · '+o.base_ref?.id+' · r'+o.base_ref?.revision+' · '+(o.slot_ids||[]).join('、'):o.field==='visual_overlays'?'图元素 · '+o.base_ref?.id+' · r'+o.base_ref?.revision+' · '+o.artist_id:o.field==='caption'?'图注 · '+o.component_id:o.anchor?.segments?'跨段正文 · '+o.anchor.segments.map((a:any)=>a.block_id).join(' → '):'正文 · '+o.block_id}</small><ReviewAuthor identity={o.created_by}/>{groupEditing&&<label><input type="checkbox" aria-label={'关联意见 '+o.id} checked={selectedOpinionIds.includes(o.id)} disabled={busy||o.deleted||groupedOpinionIds.has(o.id)} onChange={event=>{const checked=event.target.checked;setGroupSelection(value=>{const ids=value.session===s?value.ids:[];return {session:s,ids:checked?[...new Set([...ids,o.id])]:ids.filter(id=>id!==o.id)};});}}/>选择关联</label>}<blockquote>{o.anchor?.quote}</blockquote><p>{o.text}</p>{isFigureField(o.field)?<button disabled={busy||!onOpenFigure||review.annotations.find((a:any)=>a.id===o.id)?.status!=='anchored'} onClick={()=>act(async()=>{await onOpenFigure?.(o.base_ref.id,o.base_ref.revision,o.field==='slot_layout'?o.slot_ids:o.artist_id);return false;})}>{o.field==='slot_layout'?'查看所选图位':'查看所选图元素'}</button>:navigation&&<><button type="button" aria-label={'查看批注原文 '+o.id} disabled={!navigationItems.find(item=>item.key==='opinion:'+o.id)?.available} onClick={()=>locate('opinion:'+o.id)}>查看原文</button>{navigationItems.find(item=>item.key==='opinion:'+o.id)?.reason&&<p role="status">{navigationItems.find(item=>item.key==='opinion:'+o.id)?.reason}</p>}</>}{review.annotations.find((a:any)=>a.id===o.id)?.status!=='anchored'&&<p role="status">原选区已变化，请在对应保存内容中重新选择并明确定位。</p>}{editing===o.id&&<label>修改意见<textarea aria-label="修改意见" value={editText} onChange={e=>setEditText(e.target.value)}/><button disabled={busy||!editText.trim()} onClick={()=>change('edit',o.id)}>保存修改意见</button></label>}<button disabled={busy||o.deleted} onClick={()=>{setEditing(o.id);setEditText(o.text);}}>编辑意见</button><small>意见 r{o.revision} · {o.deleted?'本轮已删除，历史保留':'本轮保留'}</small><button disabled={busy||o.deleted||s.paperDraft!.dirty||(isFigureField(o.field)?(!figureAnchor||!!figureError||!matchesFigureKind(o,figureAnchor)||o.base_ref?.id!==figureAnchor.object_id):figureAnchor?true:o.field==='caption'?(!captionAnchor||!!captionError||o.component_id!==captionAnchor.component_id):!!captionAnchor||anchor?.block_id!==block)} onClick={()=>change('reanchor',o.id)}>重新定位到当前选区</button><button disabled={busy} onClick={()=>change(o.deleted?'restore':'delete',o.id)}>{o.deleted?'恢复意见':'删除意见'}</button></article>)}</div>
    <div role="group" aria-label="本轮意见关联组"><p>仅明确关联的意见一并决定其实际候选；普通多条意见不会自动成组。</p>{groupEditing&&<button disabled={busy||!canGroup} onClick={()=>{if(!canGroup)return;saveGroups([...dependencyGroups,{id:'GROUP-'+requestId(),opinion_ids:[...selectedOpinionIds]}]);setGroupSelection({session:s,ids:[]});}}>关联所选意见</button>}
      {dependencyGroups.map((group,index)=><div key={group.id}><span>关联组 {index+1} · {group.opinion_ids.length} 条意见</span><ul>{group.opinion_ids.map(id=><li key={id}>{review.opinions.find((o:any)=>o.id===id)?.text||id}{review.opinions.find((o:any)=>o.id===id)?.deleted?'（已删除）':''}</li>)}</ul><button disabled={busy} aria-label={'解除关联组 '+(index+1)} onClick={()=>saveGroups(dependencyGroups.filter(item=>item.id!==group.id))}>解除关联组</button></div>)}
      {groupSelectionProblem&&<p role="status">关联需要至少两个不同目标，且不能与已有组共享目标；同一图的多个元素意见已合为一个图目标。</p>}
      {groupProblem&&<p role="alert">关联组含已删除、无法读取或重叠的目标；请核对原意见或明确解除关联，未自动缩小提交范围。</p>}
    </div>
    {(slotAdoptions.length>0||review.opinions.some((o:any)=>!o.deleted&&o.field==='slot_layout'))&&<SlotAdoptionControl opinions={review.opinions} groups={dependencyGroups} value={slotAdoptions} disabled={busy} onChange={value=>s.setReviewComposer({...s.reviewComposer,slotAdoptions:structuredClone(value)})}/>}
    <NativeReviewContext session={s} refs={s.reviewNoteRefs} onChange={refs=>s.setReviewNoteRefs(refs)} report={report} disabled={busy}/>
    <label>本轮要求<textarea aria-label="整轮处理要求" value={request} onChange={e=>setRequest(e.target.value)}/></label>
    <label>真实执行路线<select aria-label="真实执行路线" value={provider||review.providers.find((x:any)=>x.authorized)?.id||''} onChange={e=>setProvider(e.target.value)}><option value="">未配置</option>{review.providers.map((x:any)=><option key={x.id} value={x.id}>{x.id} · {x.route}{x.authorized?'':' · 未授权'}</option>)}</select></label>
    <fieldset disabled={busy}><legend>本轮资源上限</legend><label>执行调用<select aria-label="本轮最多执行调用" value={modelCalls} onChange={e=>setModelCalls(e.target.value)}><option value="1">1 次</option><option value="2">2 次</option></select></label><label>执行秒数<input aria-label="本轮执行秒数" type="number" min="1" max="600" step="1" value={modelSeconds} onChange={e=>setModelSeconds(e.target.value)}/></label></fieldset>
    {!roundBudget&&<p role="alert">本轮资源需要 1 或 2 次调用及 1–600 的整数秒数；请修正后再提交。</p>}
    <button className="primary" disabled={busy||!roundBudget||groupProblem||slotProblem||unanchored||s.paperDraft!.dirty||!review.runtime_running||!review.providers.some((x:any)=>x.authorized)||!review.opinions.some((o:any)=>!o.deleted)} onClick={()=>act(async()=>{const origin=context.current,sentBudget=roundResourceBudget(modelCalls,modelSeconds);if(!sentBudget)throw new Error('请修正本轮资源上限。');const sent={project_id:origin.project,expected_review_revision:review.revision,expected_manuscript_revision:s.paper.revision,request,provider_id:provider||review.providers.find((x:any)=>x.authorized)?.id,budget:sentBudget,request_key:requestId(),native_note_refs:structuredClone(s.reviewNoteRefs),...(dependencyGroups.length?{dependency_groups:structuredClone(dependencyGroups)}:{}),...(slotAdoptions.length?{slot_adoptions:structuredClone(slotAdoptions)}:{})};await s.flush();if(!live.current||context.current.session!==origin.session||context.current.project!==origin.project)return;if(!s.persisted)throw new Error('草稿或上下文选择尚未同步，请处理保存错误后再提交。');const x=await command('desk.review.submit',sent);if(live.current&&context.current.session===origin.session&&context.current.project===origin.project)setSelected(x.task.id);})}>整轮提交给 Agent</button>
    {!review.runtime_running&&<p role="status">真实执行器尚未启动；已保存意见可继续整理。</p>}
    {review.runtime_running&&!review.providers.some((x:any)=>x.authorized)&&<p role="status">Agent 路线尚未配置或授权；当前可以继续整理意见。</p>}
    <p className="quiet">提交固定完整已保存稿件、本轮保留意见及明确选择的笔记保存版；仅本轮明确目标可提出文字或已支持图元素外观候选；图元素覆盖定义不等于实际输出，阅读笔记不会授权写入。本轮提交固定上述资源上限，服务端父预算及全局限制仍会核验；设置上限不会授予科学或计算权限，新的科学计算不在本轮授权内。</p>
    {review.rounds.length>0&&<label>已提交回合<select aria-label="已提交回合" disabled={busy} value={selected||review.rounds.at(-1).task_id} onChange={e=>setSelected(e.target.value)}>{review.rounds.map((r:any,i:number)=><option key={r.task_id} value={r.task_id}>第{i+1}轮 · {r.status} · {r.task_id}</option>)}</select></label>}
    {dependencyError(view)&&<p role="alert">{dependencyError(view)}</p>}
    {view&&<><h3>本轮处理 · {view.task_status}</h3><p>{view.task_error||view.block_reason}</p>{canPause&&<button disabled={busy} onClick={()=>controlRound('pause')}>暂停本轮任务</button>}{canResume&&<div><p>继续此原任务可能使用原剩余额度，并增加一次尝试；不会新增任务或扩额度。</p>{view.task_status==='waiting_input'&&<p>将核对原任务的会话检查点和权限；缺少检查点会显示拒绝，不会新建任务或重置预算。</p>}<button disabled={busy} onClick={()=>controlRound('resume')}>{view.task_status==='waiting_input'?'检查并继续原任务':'继续此回合'}</button></div>}{pausing&&<p role="status">正在请求{pausePending.operation==='pause'?'暂停':'继续'}此原任务；实际状态读取后显示，当前手改与意见保留。</p>}<button disabled={busy} onClick={()=>act(async()=>{await command('desk.review.withdraw',{project_id:s.project.id,task_id:view.task_id,expected_review_revision:review.revision});})}>撤回已提交回合</button><button disabled={busy||!view.proposal} onClick={writeBrief}>将本轮回报记入项目笔记</button>
      {currentBrief&&<p role="status" aria-label="任务回报保存结果">任务回报已写入 {currentBrief.ref.relative_path}{onOpenNote&&<button disabled={busy} onClick={openBrief}>打开本轮项目笔记</button>}</p>}
      {canAuthorize()&&<div><p>仅授权此固定候选的下一批接受或拒绝；不会重新调用模型或自动采用。</p><button disabled={busy||!s.paperDraft||s.paperDraft.dirty} onClick={authorizeDecisions}>重新授权审阅此固定候选</button></div>}
      {view.proposal&&<><p>{view.proposal.candidate.summary}</p><ReviewAuthor identity={view.proposal.proposer.session_id} kind="agent" route={view.proposal.proposer.route}/>
        {view.proposal.responses.map((r:any)=><article className="agent-response" aria-label={'原意见 '+r.opinion_id} key={r.opinion_id}><h4>{view.opinions.find((o:any)=>o.id===r.opinion_id)?.text}</h4><p>{r.text}</p><p>验证：{r.verification}</p><p>限制：{r.limitations}</p>
          {!view.proposal.changes.some((c:any)=>changeOpinions(c).includes(r.opinion_id))&&<p role="status">本意见仅有回应，没有候选改动。</p>}
          {relatedDecisionRows(view,pending.filter((c:any)=>changeOpinions(c).includes(r.opinion_id))).length>pending.filter((c:any)=>changeOpinions(c).includes(r.opinion_id)).length&&<p>此意见涉及明确关联组；接受或拒绝此组将一并决定该组所有实际候选。</p>}
          <button disabled={busy||s.paperDraft!.dirty||!view.can_decide||!pending.some((c:any)=>changeOpinions(c).includes(r.opinion_id))} onClick={()=>decide(relatedDecisionRows(view,pending.filter((c:any)=>changeOpinions(c).includes(r.opinion_id))),'accept')}>接受此意见组</button><button disabled={busy||!view.can_decide||!pending.some((c:any)=>changeOpinions(c).includes(r.opinion_id))} onClick={()=>decide(relatedDecisionRows(view,pending.filter((c:any)=>changeOpinions(c).includes(r.opinion_id))),'reject')}>拒绝此意见组</button></article>)}
        {view.proposal.changes.map((c:any)=><article data-review-key={'change:'+c.id} className="candidate-change" aria-label={'候选项 '+c.id} key={c.id} aria-current={navigation?.activeKeys.includes('change:'+c.id)?'true':undefined}><small>实际决定：{c.state} · {c.target.field==='slot_layout'?'主图布局 '+c.target.object_id:c.target.field==='visual_overlays'?'图元素外观 '+c.target.object_id:c.target.field==='caption'?'图注 '+c.target.component_id:c.target.block_id}</small>{isFigureField(c.target.field)?<div aria-label={c.target.field==='slot_layout'?'主图布局候选差异':'图元素外观候选差异'}><p>{c.target.field==='slot_layout'?'保存布局 → 候选布局；这里只展示所选图位的位置定义。':'保存覆盖 → 候选覆盖；这里只展示元素覆盖定义。'}点击下方预览可查看本轮实际候选图，尚未采用。</p><details><summary>查看精确参数差异</summary><pre>{c.before}</pre><pre>{c.after}</pre></details>{c.state==='pending'&&visualPreview(relatedDecisionRows(view,[c]))}</div>:<><del>{c.before}</del><ins>{c.after}</ins></>}<p>{c.reason}</p>{!isFigureField(c.target.field)&&navigation&&<><button type="button" aria-label={'查看候选原文 '+c.id} disabled={!navigationItems.find(item=>item.key==='change:'+c.id)?.available} onClick={()=>locate('change:'+c.id)}>查看原文</button>{navigationItems.find(item=>item.key==='change:'+c.id)?.reason&&<p role="status">{navigationItems.find(item=>item.key==='change:'+c.id)?.reason}</p>}</>}{c.conflict&&<p role="alert">{c.conflict_reason} · 当前手改保留</p>}{relatedDecisionRows(view,[c]).length>1&&<p role="status">此候选属于明确关联组，共 {relatedDecisionRows(view,[c]).length} 项；须一起决定。</p>}{c.state==='pending'&&<><label><input type="checkbox" aria-label={'选择候选 '+c.id} disabled={busy} checked={pickedIds.includes(c.id)} onChange={e=>togglePick(c.id,e.target.checked)}/>选择此候选</label><button disabled={busy||s.paperDraft!.dirty||relatedDecisionRows(view,[c]).some((row:any)=>!row.can_accept||row.state!=='pending')} onClick={()=>decide(relatedDecisionRows(view,[c]),'accept')}>{relatedDecisionRows(view,[c]).length>1?'接受关联组':'接受此项'}</button><button disabled={busy||!view.can_decide||relatedDecisionRows(view,[c]).some((row:any)=>row.state!=='pending')} onClick={()=>decide(relatedDecisionRows(view,[c]),'reject')}>{relatedDecisionRows(view,[c]).length>1?'拒绝关联组':'拒绝此项'}</button></>}</article>)}
        <div role="group" aria-label="明确选中的候选组"><p>已选择 {pickedIds.length} 项；一次决定仅提交这些候选 ID，接受时整组核对并保存。</p>{invalidPicked&&<p role="alert">选中候选已有决定、已不在当前列表或缺少关联组成员；原组选项保留，请核对完整组。</p>}<button disabled={busy||pickedIds.length===0||invalidPicked||s.paperDraft!.dirty||!view.can_decide||pickedRows.some(row=>!row?.can_accept)} onClick={()=>decide(pickedRows,'accept')}>接受选中候选组</button><button disabled={busy||pickedIds.length===0||invalidPicked||!view.can_decide} onClick={()=>decide(pickedRows,'reject')}>拒绝选中候选组</button><button disabled={busy||pickedIds.length===0} onClick={()=>setPicked({session:s,scope:selectionScope,ids:[]})}>清空候选选择</button></div>
        <button disabled={busy||s.paperDraft!.dirty||!view.can_decide||pending.length===0||pending.some((c:any)=>!c.can_accept)} onClick={()=>decide(pending,'accept')}>接受全部待定项</button><button disabled={busy||!view.can_decide||pending.length===0} onClick={()=>decide(pending,'reject')}>拒绝全部待定项</button>
      </>}
    </>}
  </section>;
}
