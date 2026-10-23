import {captionComposerError,type CaptionComposerAnchor} from './PaperCaptionSelection';
import React,{createContext,useContext,useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {createRoot} from 'react-dom/client';
import {DockviewReact,DockviewApi,IDockviewPanelProps} from 'dockview-react';
import {Tree} from 'react-arborist';
import * as pdfjs from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import 'dockview-react/dist/styles/dockview.css';
import './style.css';
import {WorkspaceChrome} from './WorkspaceChrome';
import {WorkspaceGuide} from './WorkspaceGuide';
import {NoteToolbar} from './NoteToolbar';
import './workdesk-shell.css';
import './scientific-canvas.css';
import {command,initialize,noteCommand,requestId,readTask,logout} from './api';
import {LocalAccountAccess} from './LocalAccountAccess';
import {Session,manuscriptTextWrite,manuscriptCaptionWrite} from './session';
import {CodeEditor} from './CodeEditor';
import {ReviewBody} from './ReviewPanel';
import {ReviewAuthor} from './ReviewAuthor';
import {PaperCaptionReview} from './PaperCaptionReview';
import './ManuscriptTaskReview.css';
import './native-review-context.css';
import {NoteReview} from './NoteReview';
import './note-history.css';
import {NotebookReading,type WorkspaceLocation} from './NotebookNavigator';
import {TaskDetails} from './TaskDetails';
import {TaskAuthority} from './TaskAuthority';
import {ResearchCommissionPanel,type ResearchCommissionProvider} from './ResearchCommissionPanel';
import {ResearchCyclePanel} from './ResearchCyclePanel';
import {ProjectTaskList} from './ProjectTaskList';
import {FigureBody} from './FigurePanel';
import {GenerationBody} from './GenerationPanel';
import {ResearchGraphPanel as ResearchGraphBody} from './ResearchGraphPanel';
import './ResearchGraphPanel.css';
import {PinnedReferencePanel as PinnedReferenceBody,type PinnedReference} from './PinnedReferencePanel';
import './pinned-reference-panel.css';
import {ClaimPanel as ClaimBody} from './ClaimPanel';
import './claim-panel.css';
import {ContinuousManuscript} from './ContinuousManuscript';
import type {ContinuousSelection} from './ContinuousManuscriptModel';
import {paperReviewMarks,reviewAnchor,type PaperReviewAnchor} from './PaperReviewProjection';
import {usePaperFigures} from './PaperFigureAssets';
import './review-navigation.css';
import {paperReviewNavigationItems,reviewNavigationScope,nextReviewItem,type ReviewNavigationItem,type ReviewFocus,type ReviewNavigationResult} from './ReviewNavigation';
pdfjs.GlobalWorkerOptions.workerSrc=workerUrl;
type ReviewLocation={scope:string,activeKeys:string[],activationId:string,focus:ReviewFocus|null,notice:string};
type ReviewNavigator={state:ReviewLocation|null,locate:(scope:string,item:ReviewNavigationItem)=>void,activate:(scope:string,keys:string[])=>void,result:(value:ReviewNavigationResult)=>void};
const paperNavigationScope=(s:Session)=>reviewNavigationScope({projectId:s.project.id,paperId:s.paper.id,revision:s.paper.revision,taskId:s.reviewView?.task_id,candidateSha:s.reviewView?.proposal?.candidate_sha256,proposalSha:s.reviewView?.proposal?.proposal_sha256});
const Context=createContext<{session:Session,open:(path:string,split?:boolean,offset?:number,record?:boolean,endOffset?:number,expectedSha?:string,originViewId?:string,fallbackOffset?:number)=>Promise<void>,openWorkspaceLink:(location:WorkspaceLocation)=>Promise<void>,openReference:(reference:PinnedReference)=>Promise<void>,move:(old:string,path:string,reviewed:boolean)=>Promise<any>,trash:(path:string)=>Promise<void>,report:(e:unknown)=>void,reviewNavigator:ReviewNavigator}|null>(null);
function useDesk(){return useContext(Context)!;}
function useVersion(s:Session){useSyncExternalStore(s.subscribe,s.snapshot);}
const codePointToUTF16=(text:string,n:number)=>Array.from(text).slice(0,n).join('').length;

// Ordinary supporting views share tabs. A separate group is an explicit split,
// and existing panels keep their saved group and editor instance.
const supportingPanels=new Set(['note','review','task','fixedSource','commission','researchCycle','projectTasks']);
function supportingPosition(a:DockviewApi,originId?:string){
  const origin=originId?a.getPanel(originId):undefined;
  const supports=(panel:typeof origin)=>!!panel&&supportingPanels.has(panel.toJSON().contentComponent||'');
  const host=supports(origin)?origin:a.panels.find(supports);
  if(host)return {referencePanel:host.id,direction:'within' as const};
  const paper=a.panels.find(p=>['paper','pdf','figure'].includes(p.toJSON().contentComponent||''));
  return paper?{referencePanel:paper.id,direction:'right' as const}:{direction:'right' as const};
}


function NotePanel(props:IDockviewPanelProps){
  const {session:s,open,openWorkspaceLink,move,trash,report}=useDesk();useVersion(s);
  const path=props.params.path as string;const b=s.buffers.get(path);
  const [reading,setReading]=useState(!!props.params.reading),[noteReview,setNoteReview]=useState(false);const [saving,setSaving]=useState(false);
  const changeReading=(value:boolean)=>{setReading(value);props.api.updateParameters({reading:value});s.position(props.api.id,{path,readingMode:value});};
  const [managing,setManaging]=useState(false),[destination,setDestination]=useState(''),[links,setLinks]=useState<any>(null);
  const [readError,setReadError]=useState(''),[readAttempt,setReadAttempt]=useState(0);
  // Loading a restored/default panel is a read, not a new navigation action.
  // An older lazy load must never append history after a newer deep link.
  useEffect(()=>{let current=true;setReadError('');if(!b&&!props.params.loading&&!props.params.readError){s.open(path,false).catch(error=>{if(current){setReadError(error instanceof Error?error.message:String(error));report(error);}});}return()=>{current=false;};},[path,props.params.loading,props.params.readError,s,readAttempt]);
  const position=s.views[props.api.id]?.path===path?s.views[props.api.id]:{cursor:0};
  useEffect(()=>{props.api.setTitle((b?.dirty?'● ':'')+path.split('/').pop());},[path,b?.dirty]);
  useEffect(()=>{if(b&&!props.params.loading)s.position(props.api.id,{path,readingMode:reading});},[path,b?.base,props.params.loading,reading]);
  if(s.opening)return <div className="loading">创建并打开 {s.opening}…</div>;
  const error=props.params.readError||readError;
  if(!b||props.params.loading)return error?<section className="note-panel" aria-label={`笔记 ${path}`}><div className="error" role="alert"><p>无法读取 {path}：{error}</p><button onClick={()=>{props.api.updateParameters({readError:''});setReadAttempt(value=>value+1);}}>重试读取笔记</button><button onClick={()=>{const panel=props.containerApi.getPanel(props.api.id);if(panel)props.containerApi.removePanel(panel);}}>关闭不可读笔记</button></div></section>:<div className="loading">读取 {path}…</div>;
  const missingSource=!s.entries.some(entry=>entry.type!=='folder'&&entry.relative_path===path);
  const fav=s.navigation.favorites.includes(path);
  const save=async()=>{setSaving(true);try{await s.save(path);}catch(e){report(e);}finally{setSaving(false);}};
  const activate=()=>{if(s.activePath!==path||s.activeView!==props.api.id){s.activePath=path;s.activeView=props.api.id;s.notify();if(s.layout)void s.saveLayout(s.layout);}};
  const history=(op:string)=>s.navigate({op},s.locationOffset()).then(x=>x.location&&open(x.location.relative_path,false,x.location.cursor_offset,false,undefined,undefined,props.api.id)).catch(report);
  return <section className="note-panel" aria-label={`笔记 ${path}`} onFocusCapture={activate} onWheelCapture={activate}>
    <NoteToolbar path={path} dirty={b.dirty} saving={saving} missingSource={missingSource} reading={reading} favorite={fav} pinned={!!props.params.pinned} reviewOpen={noteReview} managing={managing}
      onBack={()=>void history('back')} onForward={()=>void history('forward')} onSave={()=>void save()} onToggleReading={()=>changeReading(!reading)}
      onToggleFavorite={()=>{void s.navigate({op:'favorite',relative_path:path,favorite:!fav}).then(()=>s.refresh()).catch(report);}}
      onTogglePinned={()=>props.api.updateParameters({pinned:!props.params.pinned})} onSplit={()=>void open(path,true)}
      onToggleReview={()=>setNoteReview(!noteReview)} onFileTools={()=>{setManaging(!managing);setDestination(path);setLinks(null);}}/>
    {b.conflict&&<div className="error" role="alert">{b.conflict}</div>}
    {error&&<div className="error" role="alert">打开笔记失败：{error}。当前缓冲已保留。</div>}
    {missingSource&&<div className="error" role="alert">项目文件当前不在笔记目录中；当前缓冲已保留。请从目录恢复文件，或将草稿复制到新笔记。</div>}
    {managing&&<div className="note-file-tools"><label>移动或重命名目标<input aria-label="笔记移动目标" value={destination} onChange={e=>{setDestination(e.target.value);setLinks(null);}}/></label><button disabled={b.dirty||destination===path} onClick={()=>noteCommand('notes.move.inspect',s.project.id,{relative_path:path,new_path:destination,expected_content_sha256:b.base}).then(x=>setLinks(x.links)).catch(report)}>检查相对链接</button>{links&&<><pre>{JSON.stringify(links,null,2)}</pre><button disabled={b.dirty||saving} onClick={async()=>{setSaving(true);try{await move(path,destination,true);setManaging(false);}catch(e){report(e);}finally{setSaving(false);}}}>确认移动，保留正文</button></>}<button disabled={b.dirty||saving} onClick={async()=>{setSaving(true);try{await trash(path);}catch(e){report(e);}finally{setSaving(false);}}}>回收此笔记</button>{b.dirty&&<p>请先保存当前手改；文件操作不会丢弃草稿。</p>}</div>}
    {reading?<NotebookReading presentation={props.api} session={s} path={path} viewId={props.api.id} jump={props.params.jump||0} onOpenNote={t=>open(t.path,t.split,t.sourceCodePointOffset,true,t.endSourceCodePointOffset,t.contentSha256,t.originViewId)} onWorkspaceLink={openWorkspaceLink} report={report}/>:<CodeEditor readOnly={s.fileBusy.has(path)} viewId={props.api.id+':'+path} text={b.text} initial={position} jump={props.params.jump||0} onChange={text=>s.edit(path,text)} onPosition={value=>s.position(props.api.id,{...value,path})}/>}
    {noteReview&&<NoteReview session={s} path={path} viewId={props.api.id} onLocate={async t=>{changeReading(false);await open(t.path,t.split,t.sourceCodePointOffset,true,t.endSourceCodePointOffset,t.contentSha256,t.originViewId);}} report={report}/>}
    <footer>{b.dirty?'未保存到文件':missingSource?'缓存保存版；项目文件当前不可用':'已保存到项目文件'} · UTF-8 Markdown <span>{b.dirty&&(s.persisted?'服务器草稿已保存':'草稿同步中…')}</span></footer>
  </section>;
}

function PdfPanel(props:IDockviewPanelProps){
  const {session:s,report}=useDesk();useVersion(s);const canvas=useRef<HTMLCanvasElement>(null);const scroll=useRef<HTMLDivElement>(null);const actualScale=useRef(1);const [width,setWidth]=useState(0);const [fit,setFit]=useState(s.views[props.api.id]?.fit??true);const [page,setPage]=useState(s.views[props.api.id]?.page||1);
  const [busy,setBusy]=useState(false);const [scale,setScale]=useState(s.views[props.api.id]?.scale||1);const [readAttempt,setReadAttempt]=useState(0);
  const [view,setView]=useState<{key:string,status:'ready'|'error',count:number,text:string,error:string}|null>(null);
  const compileSequence=useRef(0);const compileSession=useRef(s);compileSession.current=s;
  useEffect(()=>{setBusy(false);return()=>{++compileSequence.current;};},[s]);
  const pdf=s.render?.assets?.['paper.pdf'];
  useEffect(()=>{if(!scroll.current)return;const observer=new ResizeObserver(entries=>setWidth(entries[0].contentRect.width));observer.observe(scroll.current);return()=>observer.disconnect();},[pdf?.sha]);
  // A new source or viewport must not expose the preceding page as current.
  // Compare synchronously during render as well as guarding every async result.
  const readKey=JSON.stringify([s.project.id,s.paper.id,pdf?.sha,page,scale,fit,width,readAttempt]);
  const currentView=view?.key===readKey?view:null;
  const ready=currentView?.status==='ready';
  const readState=!pdf?'empty':currentView?.status||'loading';
  useEffect(()=>{
    if(!pdf)return;let dead=false;let renderTask:any;const load=pdfjs.getDocument({url:'/api/assets/'+pdf.sha});
    load.promise.then(async doc=>{
      if(dead)return;
      const effectivePage=Math.max(1,Math.min(page,doc.numPages));
      if(effectivePage!==page){setPage(effectivePage);return;}
      const p=await doc.getPage(effectivePage);if(dead)return;
      const displayed=fit&&width?Math.max(.2,Math.min(2,(width-48)/p.getViewport({scale:1}).width)):scale;
      const viewport=p.getViewport({scale:displayed}),c=canvas.current;if(!c)return;
      const ctx=c.getContext('2d');if(!ctx)throw new Error('无法创建 PDF 画布。');
      const ratio=window.devicePixelRatio||1;c.width=viewport.width*ratio;c.height=viewport.height*ratio;c.style.width=viewport.width+'px';c.style.height=viewport.height+'px';
      renderTask=p.render({canvas:c,canvasContext:ctx,viewport,transform:ratio===1?undefined:[ratio,0,0,ratio,0,0]});await renderTask.promise;if(dead)return;
      const content=await p.getTextContent();if(dead)return;
      actualScale.current=displayed;
      setView({key:readKey,status:'ready',count:doc.numPages,text:content.items.map((x:any)=>x.str||'').join(' '),error:''});
    }).catch(e=>{if(!dead)setView({key:readKey,status:'error',count:0,text:'',error:e instanceof Error?e.message:String(e)});});
    return()=>{dead=true;renderTask?.cancel();void load.destroy();};
  },[readKey]);
  useEffect(()=>{s.position(props.api.id,{page,scale,fit});},[page,scale,fit]);
  const compile=async()=>{
    const sequence=++compileSequence.current;const current=()=>compileSession.current===s&&compileSequence.current===sequence;
    setBusy(true);
    try{
      await command('desk.paper.render',{project_id:s.project.id,expected_revision:s.paper.revision});
      if(current())await s.refreshPaper();
    }catch(e){if(current())report(e);}finally{if(current())setBusy(false);}
  };
  const stale=s.render?.revision!==s.paper?.revision;
  return <section className="pdf-panel" aria-label="论文 PDF" data-pdf-sha={pdf?.sha} data-rendered-sha={ready?pdf?.sha:undefined} data-pdf-state={readState} aria-busy={readState==='loading'}>
    <div className="panel-tools"><strong>基础论文</strong><span className="path">{stale?'已保存文字待编译':`保存版 r${s.paper?.revision}`}</span><button onClick={()=>setPage(Math.max(1,page-1))} disabled={!ready||page<=1}>上一页</button><span>{ready?`${page} / ${currentView.count}`:'— / —'}</span><button onClick={()=>setPage(Math.min(currentView?.count||1,page+1))} disabled={!ready||page>=(currentView?.count||0)}>下一页</button><button onClick={()=>{setFit(false);setScale(Math.max(.2,actualScale.current-.1));}} aria-label="缩小 PDF" disabled={!ready}>−</button><button onClick={()=>{setFit(false);setScale(Math.min(2,actualScale.current+.1));}} aria-label="放大 PDF" disabled={!ready}>＋</button><button aria-label="适合 PDF 宽度" aria-pressed={fit} onClick={()=>setFit(true)}>适宽</button><button onClick={compile} disabled={busy}>{busy?'编译中…':'编译保存版'}</button><button onClick={()=>{const a=props.containerApi;const p=a.panels.find(p=>p.toJSON().contentComponent==='paper');p?p.api.setActive():a.addPanel({id:'paper-source',component:'paper',title:'连续稿件',position:{referencePanel:props.api.id,direction:'within'}});}}>编辑文字</button>{pdf&&<a href={'/api/assets/'+pdf.sha} target="_blank" rel="noreferrer">下载 PDF</a>}</div>
    {!pdf?<div className="empty"><h2>尚未生成本次 PDF</h2><p>需要配置本地 XeLaTeX。项目和笔记已保存。</p><button onClick={compile}>编译基础模板</button></div>:<div className="pdf-scroll" ref={scroll}>
      {readState==='loading'&&<p role="status">正在读取 PDF…</p>}
      {readState==='error'&&<div className="error" role="alert"><p>PDF 读取失败：{currentView?.error}</p><button onClick={()=>setReadAttempt(value=>value+1)}>重试 PDF</button></div>}
      <canvas ref={canvas} role="img" aria-label={`论文第 ${page} 页`} aria-hidden={!ready} style={{visibility:ready?'visible':'hidden'}}/><p className="sr-only">{ready?currentView.text:''}</p>
    </div>}
  </section>;
}

function PaperPanel(props:IDockviewPanelProps){
  const {session:s,report,reviewNavigator}=useDesk();useVersion(s);const draft=s.paperDraft!;
  const [edits,setEdits]=useState<any>(null),[mode,setMode]=useState<'read'|'review'|'edit'>('edit');
  const [editorEpoch,setEditorEpoch]=useState(0);
  const [showChanges,setShowChanges]=useState(true),[writingSuggestion,setWritingSuggestion]=useState(false),[selection,setSelection]=useState<ContinuousSelection|null>(null),[busy,setBusy]=useState(false);
  const [writeNotice,setWriteNotice]=useState('');
  const [captionSelection,setCaptionSelection]=useState<CaptionComposerAnchor|null>(null);
  const writeSession=useRef(s);writeSession.current=s;const writeSequence=useRef(0);
  useEffect(()=>{setBusy(false);setWriteNotice('');return()=>{++writeSequence.current;};},[s]);
  const title=draft.title??s.paper.title;
  const legacyCaptionDirty=Object.values(s.captionDrafts).some(row=>row?.project===s.project.id&&row.paper===s.paper.id&&row.text!==row.before);
  const figures=usePaperFigures(s.project.id,s.paper.id,s.paper.content.components||[]);
  const readSequence=useRef(0);
  const readEdits=async()=>{const request=++readSequence.current;const [e,r]=await Promise.all([command('desk.paper.edits',{project_id:s.project.id}),command('desk.review.read',{project_id:s.project.id})]);if(writeSession.current===s&&request===readSequence.current){setEdits(e);s.setReviewProjection(r);}};
  useEffect(()=>{void readEdits().catch(e=>{if(writeSession.current===s)report(e);});return()=>{++readSequence.current;};},[s,s.paper.revision]);
  const review=(anchor?:PaperReviewAnchor|CaptionComposerAnchor)=>{
    const a=props.containerApi,params={block_id:anchor?.block_id,anchor};const p=a.getPanel('review-round');
    if(p){p.api.updateParameters(params);p.api.setActive();}
    else {const note=a.panels.find(p=>p.toJSON().contentComponent==='note');a.addPanel({id:'review-round',component:'review',title:'整轮意见',params,position:note?{referencePanel:note.id,direction:'within'}:{referencePanel:props.api.id,direction:'right'}});}
  };
  const write=async(kind:'direct'|'propose')=>{
    const sequence=++writeSequence.current,current=()=>writeSession.current===s&&writeSequence.current===sequence;
    const sent={kind,paperId:s.paper.id,draft,base:draft.base,blocks:structuredClone(draft.blocks),title,captions:structuredClone(draft.captions||[])};
    setBusy(true);setWriteNotice('');
    try{
      if(kind==='propose'&&sent.captions.length)throw new Error('图注修改请在编辑模式保存；正文与图注草稿保留。');
      const captions=manuscriptCaptionWrite(sent.captions,s.paper.content.components||[]);
      const x=await command(`desk.paper.${kind}`,{project_id:s.project.id,expected_revision:sent.base,blocks:manuscriptTextWrite(sent.blocks,s.paper.content.blocks),...(kind==='direct'?{title:sent.title}:{}),...(captions.length?{captions}:{}),request_key:requestId()});
      if(!current())return;
      if(s.applyPaperWrite(x,sent)==='stale'){
        setWriteNotice('此次提交已完成，但稿件已有较新版本。当前内容与草稿均保留，请比较后继续。');
        await readEdits();return;
      }
      if(kind==='propose'&&s.paperDraft!==draft){setWritingSuggestion(false);setSelection(null);setEditorEpoch(value=>value+1);}
      await s.flush();if(!current())return;
      await readEdits();if(current()&&kind==='propose')setMode('review');
    }catch(e){if(current())report(e);}finally{if(current())setBusy(false);}
  };
  const decideOwn=async(rows:any[],decision:string)=>{
    const sequence=++writeSequence.current,current=()=>writeSession.current===s&&writeSequence.current===sequence;
    setBusy(true);setWriteNotice('');try{
    if(draft.dirty)throw new Error('请先保存或整理当前草稿；当前手改保留。');
    await command('desk.paper.edit.decide',{project_id:s.project.id,proposal_id:edits.proposal_id,expected_revision:s.paper.revision,expected_decision_version:edits.decision_version,decisions:rows.map(r=>({change_id:r.id,decision})),request_key:requestId()});
    if(!current())return;await s.refreshPaper();if(!current())return;
    await s.flush();if(current())await readEdits();
  }catch(e){if(current())report(e);}finally{if(current())setBusy(false);}};
  const pending=edits?.changes?.filter((c:any)=>c.state==='pending')||[];
  const preview=mode==='review'&&!draft.dirty&&!writingSuggestion&&pending.length>0;
  const blocks=preview?(edits?.marked_blocks||[]).map((row:any)=>row.block):draft.blocks;
  const navigationScope=paperNavigationScope(s),navigation=reviewNavigator.state?.scope===navigationScope?reviewNavigator.state:null;
  const navigationItems=paperReviewNavigationItems(blocks,s.reviewState,edits,s.reviewView,{paperId:s.paper.id,components:s.paper.content.components||[]});
  const activeKeys=navigation?.activeKeys||[];
  const marks=paperReviewMarks(blocks,s.reviewState,edits,s.reviewView,(showChanges&&mode==='review')||activeKeys.some(key=>key.startsWith('change:')));
  const stepReview=(direction:1|-1)=>{const item=nextReviewItem(navigationItems,activeKeys[0],direction);if(item)reviewNavigator.locate(navigationScope,item);};
  const selected=captionSelection&&!captionComposerError(captionSelection,s.project.id,s.paper)?captionSelection:reviewAnchor(selection);
  const openFigure=(ref:{id:string,revision:number})=>{const {id,revision}=ref;const a=props.containerApi;let p=a.getPanel('figure-editor');if(p){p.api.updateParameters({id,revision,open_epoch:requestId()});p.api.setActive();}else p=a.addPanel({id:'figure-editor',component:'figure',title:'科研图',params:{id,revision,open_epoch:requestId()},position:{referencePanel:props.api.id,direction:'within'}});p.api.maximize();};

  return <section className="paper-editor" aria-label="连续稿件审查"><div className="panel-tools manuscript-tools">
    <div role="group" aria-label="稿件模式">{([['read','阅读'],['review','审查'],['edit','编辑']] as const).map(([value,label])=><button key={value} aria-pressed={mode===value} onClick={()=>setMode(value)}>{label}</button>)}</div>
    <span className="path">{draft.dirty?'未保存修改':'保存版'} · r{draft.base}</span>
    <button disabled={busy||!draft.dirty||(mode==='review'&&(title!==s.paper.title||!!draft.captions?.length))} onClick={()=>write(mode==='review'?'propose':'direct')}>{mode==='review'?'保存为建议修订':'保存文字'}</button>
    <button disabled={busy||draft.dirty||!selected} onMouseDown={e=>e.preventDefault()} onClick={()=>review(selected)}>新建批注</button>
    <button onClick={()=>review()}>整理整轮意见</button>
    <button aria-label="上一审阅项" disabled={!nextReviewItem(navigationItems,activeKeys[0],-1)} onClick={()=>stepReview(-1)}>上一项</button>
    <button aria-label="下一审阅项" disabled={!nextReviewItem(navigationItems,activeKeys[0],1)} onClick={()=>stepReview(1)}>下一项</button>
    <button onClick={()=>{const a=props.containerApi;const p=a.getPanel('paper-pdf');p?p.api.setActive():a.addPanel({id:'paper-pdf',component:'pdf',title:'论文 PDF',position:{referencePanel:props.api.id,direction:'within'}});}}>排版预览</button>
    {mode==='review'&&<><button aria-pressed={showChanges} onClick={()=>setShowChanges(!showChanges)}>显示修订</button>{preview&&<button onClick={()=>setWritingSuggestion(true)}>继续提出修订</button>}</>}
  </div>
  {writeNotice&&<p role="status" aria-label="稿件提交结果">{writeNotice}</p>}
  {navigation?.notice&&<p role="status" aria-label="审阅定位结果">{navigation.notice}</p>}
  {activeKeys.length>0&&<div className="review-location-topics" role="group" aria-label="当前位置的审阅话题">{activeKeys.map(key=>{const item=navigationItems.find(row=>row.key===key);return item?<button key={key} disabled={!item.available} aria-label={'定位审阅话题 '+key} title={item.label} onClick={()=>reviewNavigator.locate(navigationScope,item)}>{item.kind==='opinion'?'批注':'修订'} · {item.label}</button>:null;})}</div>}
  {mode==='review'&&draft.dirty&&title!==s.paper.title&&<p role="status">标题修改须在编辑模式直接保存；审查建议仅处理正文。</p>}
  {mode==='review'&&!!draft.captions?.length&&<p role="status">图注修改须在编辑模式保存；当前草稿保留。</p>}
  {legacyCaptionDirty&&<p role="status">图注辅助区还有未保存文字；先保存或放弃那份草稿，再在连续稿中编辑图注。</p>}
  <ContinuousManuscript key={editorEpoch} documentKey={s.project.id+':'+s.paper.id} version={draft.base} blocks={blocks} title={title} mode={mode} editable={mode!=='read'&&!preview} marks={marks}
    captionEdits={draft.captions||[]} captionEditable={!legacyCaptionDirty} onChange={(next,title,captions)=>s.editManuscript(next,title,captions)} onSelection={setSelection} onCaptionSelection={value=>{setCaptionSelection(value?{...value,field:'caption',component_id:value.componentId,projectId:s.project.id,paperId:s.paper.id}:null);}} figures={figures} onOpenFigure={openFigure}
    reviewScope={navigationScope} reviewFocus={navigation?.focus} activeReviewKeys={activeKeys} reviewItems={navigationItems}
    onReviewActivate={keys=>reviewNavigator.activate(navigationScope,keys.filter(key=>navigationItems.some(item=>item.key===key&&item.available)))}
    onReviewNavigationResult={reviewNavigator.result}/>

  {mode==='review'&&pending.length>0&&<aside className="manuscript-decisions" aria-label="具名建议决定"><ReviewAuthor prefix="建议者：" identity={edits?.proposer?.actor}/>{pending.map((c:any)=><div key={c.id}><span>{c.op==='insert'?'新增段落':c.op==='delete'?'删除段落':'文字修订'}</span>{c.conflict&&<p role="alert">{c.conflict_reason}；手改保留</p>}<button disabled={busy||draft.dirty||!c.can_accept} onClick={()=>decideOwn([c],'accept')}>接受建议项</button><button disabled={busy||draft.dirty} onClick={()=>decideOwn([c],'reject')}>拒绝建议项</button></div>)}<button disabled={busy||draft.dirty||pending.some((c:any)=>!c.can_accept)} onClick={()=>decideOwn(pending,'accept')}>接受全部建议</button><button disabled={busy||draft.dirty} onClick={()=>decideOwn(pending,'reject')}>拒绝全部建议</button></aside>}
  <details className="manuscript-caption-tools"><summary>稿内图注与意见</summary><PaperCaptionReview session={s} report={report} onReview={()=>review()}/></details>
  </section>;
}
function ReviewPanel(props:IDockviewPanelProps){const {session,report,reviewNavigator,open}=useDesk();useVersion(session);const scope=paperNavigationScope(session);return <ReviewBody session={session} report={report} onOpenFigure={(id,revision,selection)=>{
    const a=props.containerApi,params={id,revision,artist_id:typeof selection==='string'?selection:undefined,slot_ids:Array.isArray(selection)?selection:undefined,open_epoch:requestId()};
    const existing=a.getPanel('figure-editor');
    if(existing){existing.api.updateParameters(params);existing.api.setActive();}
    else a.addPanel({id:'figure-editor',component:'figure',title:'科研图',params,position:{referencePanel:props.api.id,direction:'left'}});
  }} onOpenNote={path=>open(path,false,undefined,true,undefined,undefined,props.api.id)} initialBlock={props.params.block_id} initialTask={props.params.task_id} initialAnchor={props.params.anchor} navigation={{scope,activationId:reviewNavigator.state?.scope===scope?reviewNavigator.state.activationId:undefined,activeKeys:reviewNavigator.state?.scope===scope?reviewNavigator.state.activeKeys:[],onLocate:item=>reviewNavigator.locate(scope,item)}}/>;}

function treeData(entries:any[]){
  const root:any={id:'notes',name:'notes',children:[]};
  for(const e of entries.filter(x=>x.type!=='folder'&&(x.relative_path||'').endsWith('.md'))){
    const parts=e.relative_path.split('/').slice(1);let node=root;
    parts.forEach((name:string,i:number)=>{const id='notes/'+parts.slice(0,i+1).join('/');let x=node.children.find((v:any)=>v.id===id);if(!x){x={id,name,...(i<parts.length-1?{children:[]}:{} )};node.children.push(x);}node=x;});
  }return [root];
}
function Navigation(props:IDockviewPanelProps){
  const [treeRoot,setTreeRoot]=useState<HTMLDivElement|null>(null);
  const {session:s,open,report}=useDesk();useVersion(s);const [query,setQuery]=useState('');const [scope,setScope]=useState('current_project');const [searchError,setSearchError]=useState('');const [hits,setHits]=useState<any[]>([]);const [pending,setPending]=useState(false);const [name,setName]=useState('');
  const [newNote,setNewNote]=useState(false);const [tab,setTab]=useState('files');const path=s.activePath;
  const [trashed,setTrashed]=useState<any[]|null>(null),[restoring,setRestoring]=useState(false),[restoreTargets,setRestoreTargets]=useState<Record<string,string>>({});
  const files=treeData(s.entries);const outline=s.buffers.get(path)?.outline||[];
  const searchInput=useRef<HTMLInputElement>(null);
  useEffect(()=>{if(props.params?.focusSearch)searchInput.current?.focus();},[props.params?.focusSearch]);
  useEffect(()=>{setHits([]);setSearchError('');setPending(!!query);if(!query)return;let active=true;const t=setTimeout(()=>{noteCommand('notes.search',s.project.id,{query,scope,limit:200}).then(x=>{if(active)setHits(x.matches);}).catch(e=>{if(active){setHits([]);setSearchError(String(e));}}).finally(()=>{if(active)setPending(false);});},180);return()=>{active=false;clearTimeout(t);};},[query,scope,s.project.id]);
  const activatingLeaves=useRef(new Map<string,Promise<void>>());
  const navigate=(p:string,n?:number,fallback?:number)=>{
    if(n!==undefined)return open(p,false,n,true,undefined,undefined,undefined,fallback).catch(report);
    const pending=activatingLeaves.current.get(p);if(pending)return pending;
    const operation=open(p,false,undefined,s.navigation.location?.relative_path!==p,undefined,undefined,undefined,fallback).catch(report).finally(()=>{
      if(activatingLeaves.current.get(p)===operation)activatingLeaves.current.delete(p);
    });
    activatingLeaves.current.set(p,operation);return operation;
  };
  return <section className="navigation" aria-label="项目笔记导航"><div className="panel-tools"><strong>项目笔记</strong><span className="path"/><button aria-label="查看回收笔记" onClick={()=>trashed===null?noteCommand('notes.trash.list',s.project.id,{}).then(x=>setTrashed(x.items)).catch(report):setTrashed(null)}>回收笔记</button><button aria-label="新建笔记" onClick={()=>setNewNote(!newNote)}>＋</button></div>
    {trashed!==null&&<div className="note-trash"><h3>回收笔记</h3>{!trashed.length&&<p>没有回收笔记。</p>}{trashed.map(x=><div key={x.trash_id}><span>{x.relative_path}</span><input aria-label={'恢复目标 '+x.relative_path} value={restoreTargets[x.trash_id]??x.relative_path} onChange={e=>setRestoreTargets({...restoreTargets,[x.trash_id]:e.target.value})}/><button disabled={restoring} onClick={async()=>{setRestoring(true);try{const restored=await noteCommand('notes.restore',s.project.id,{trash_id:x.trash_id,new_path:restoreTargets[x.trash_id]??x.relative_path});await s.refresh();setTrashed((await noteCommand('notes.trash.list',s.project.id,{})).items);await open(restored.relative_path);}catch(e){report(e);}finally{setRestoring(false);}}}>恢复笔记</button></div>)}</div>}
    {newNote&&<form className="new-note" onSubmit={async e=>{e.preventDefault();try{const path='notes/'+name.replace(/^notes\//,'')+(name.endsWith('.md')?'':'.md');s.opening=path;s.notify();await noteCommand('notes.create',s.project.id,{relative_path:path,markdown:'',if_absent:true});await s.refresh();await navigate(path);setName('');setNewNote(false);}catch(x){report(x);}finally{s.opening=null;s.notify();}}}><label>文件路径<input aria-label="新笔记路径" placeholder="topics/想法.md" value={name} onChange={e=>setName(e.target.value)} required/></label><button>创建笔记</button></form>}
    <div className="search-box"><input ref={searchInput} aria-label="搜索项目笔记" placeholder="搜索标题、正文、标签、路径" value={query} onChange={e=>setQuery(e.target.value)}/><select aria-label="检索范围" value={scope} onChange={e=>setScope(e.target.value)}><option value="current_project">仅本项目</option><option value="all_projects">所有获授权项目</option></select></div>
    {query?<div className="search-results"><p role="status">{pending?'检索实际文件…':searchError?'检索失败，未展示旧结果':`${hits.length} 处匹配`}</p>{searchError&&<p role="alert">{searchError}</p>}{hits.map((h,i)=><button key={i} onClick={async()=>{try{if(h.project_id!==s.project.id){await s.flush();const u=new URL(location.href);u.searchParams.set('project',h.project_id);u.searchParams.set('note',h.relative_path);if(h.field==='content'){u.searchParams.set('match_start',String(h.start_offset));u.searchParams.set('match_end',String(h.end_offset));u.searchParams.set('match_sha',h.content_sha256);}location.assign(u);}else await open(h.relative_path,false,h.field==='content'?h.start_offset:0,true,h.field==='content'?h.end_offset:undefined,h.content_sha256);}catch(e){report(e);}}}><strong>{scope==='all_projects'?h.project_id+' · ':''}{h.relative_path}</strong><span>{h.snippet}</span></button>)}</div>:<><div className="nav-tabs">{[['files','目录'],['recent','最近'],['favorites','收藏']].map(([key,label])=><button aria-pressed={tab===key} onClick={()=>setTab(key)} key={key}>{label}</button>)}</div>{tab==='files'?<div className="file-tree-region" ref={setTreeRoot}>{treeRoot&&<Tree dndRootElement={treeRoot} data={files} selection={path} width="100%" height={350} rowHeight={30} indent={16} disableDrag disableDrop disableEdit onActivate={n=>n.isLeaf?navigate(n.id):n.toggle()}>{({node,style,dragHandle})=><div style={style} ref={dragHandle} aria-current={node.id===path?'page':undefined} data-path={node.id} className={'tree-row '+(node.isSelected?'selected':'')}><span>{node.isInternal?(node.isOpen?'▾':'▸'):'≡'}</span> {node.data.name}</div>}</Tree>}</div>:<div className="quick-list">{s.navigation[tab].map((x:any)=><button key={typeof x==='string'?x:x.relative_path} onClick={()=>navigate(typeof x==='string'?x:x.relative_path,undefined,typeof x==='string'?undefined:x.cursor_offset)}>{typeof x==='string'?x:x.relative_path}</button>)}</div>}
    <div className="outline"><h3>当前文件大纲</h3>{outline.map((x:any,i:number)=><button key={i} style={{paddingLeft:12+(x.level-1)*8}} onClick={()=>navigate(path,x.start_offset)}>{x.title}</button>)}</div><div className="outline"><h3>项目素材</h3><label className="upload-label">上传素材<input type="file" aria-label="上传项目素材" onChange={async e=>{const file=e.target.files?.[0];if(!file)return;try{if(file.size>128*1024*1024)throw new Error('本轮客户端上传支持128MB以内文件');const reader=new FileReader();const base64=await new Promise<string>((resolve,reject)=>{reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(reader.error);reader.readAsDataURL(file);});await command('desk.asset.import',{project_id:s.project.id,filename:file.name,base64});await s.refresh();}catch(x){report(x);}finally{e.target.value='';}}}/></label>{s.assets.map(x=><a className="asset-link" key={x.id} href={'/api/assets/'+x.sha} target="_blank" rel="noreferrer" title={x.id}>{x.filename} <small>{x.size} B</small></a>)}</div></>}
  </section>;
}

function FigurePanel(props:IDockviewPanelProps){
  const {session,report}=useDesk();
  const memory=session.figurePanelMemory(props.api.id);
  // Keep the fresh read on every explicit open. Only view state survives it;
  // a cached selection must never substitute for a current permission check.
  return <FigureBody key={props.params.open_epoch||props.api.id} session={session} report={report} viewMemory={memory} initialId={props.params.id} initialRevision={props.params.revision??undefined} initialArtist={props.params.artist_id} initialSlotIds={props.params.slot_ids} onReviewFigure={anchor=>{
    const a=props.containerApi,params={anchor};
    const existing=a.getPanel('review-round');
    if(existing){existing.api.updateParameters(params);existing.api.setActive();}
    else a.addPanel({id:'review-round',component:'review',title:'整轮意见',params,position:supportingPosition(a,props.api.id)});
  }} onLocationChange={({id,revision})=>{if(props.params.id!==id||(props.params.revision??null)!==(revision??null))props.api.updateParameters({id,revision:revision??null,artist_id:undefined,slot_ids:undefined});}} dockview={{api:props.api,containerApi:props.containerApi}}/>;
}
function GenerationPanel(props:IDockviewPanelProps){const {session,report}=useDesk();return <GenerationBody session={session} report={report} initialRun={props.params.run_id}/>;}
function TaskPanel(props:IDockviewPanelProps){const {session,open,openWorkspaceLink,openReference,report}=useDesk();useVersion(session);return <TaskAuthority session={session} projectId={session.project.id} report={report}>{authority=><TaskDetails session={session} taskId={props.params.task_id} taskAuthority={authority} onOpenFigure={id=>openWorkspaceLink({kind:'figure',id,projectId:session.project.id,originViewId:props.api.id})} onOpenGeneration={id=>openWorkspaceLink({kind:'generation',id,projectId:session.project.id,originViewId:props.api.id})} onOpenNote={path=>open(path,false,undefined,true,undefined,undefined,props.api.id)} onOpenReference={openReference} onOpenTask={ref=>openWorkspaceLink({kind:'task',id:ref.id,projectId:ref.project_id,originViewId:props.api.id})} report={report}/>}</TaskAuthority>;}
function ProjectTasksDock(props:IDockviewPanelProps){const {session,openWorkspaceLink,report}=useDesk();return <ProjectTaskList session={session} report={report} onOpenTask={ref=>openWorkspaceLink({kind:'task',id:ref.id,projectId:ref.project_id,originViewId:props.api.id})}/>;}

function ResearchCycleDock(props:IDockviewPanelProps){
  const {session,openWorkspaceLink,openReference,open,report}=useDesk();useVersion(session);
  return <TaskAuthority session={session} projectId={session.project.id} report={report}>{authority=>
    <ResearchCyclePanel session={session} taskAuthority={authority} parentTaskId={props.params.task_id}
      onOpenTask={ref=>openWorkspaceLink({kind:'task',id:ref.id,projectId:ref.project_id,originViewId:props.api.id})}
      onOpenReference={openReference} onOpenNote={path=>open(path,false,undefined,true,undefined,undefined,props.api.id)} report={report}/>
  }</TaskAuthority>;
}

function ResearchCommissionDock(props:IDockviewPanelProps){
  const {session:s,openWorkspaceLink,openReference,report}=useDesk();
  const sequence=useRef(0),[attempt,setAttempt]=useState(0);
  const [status,setStatus]=useState<{session:Session,running:boolean,providers:ResearchCommissionProvider[]}|null>(null);
  const [error,setError]=useState(''),[loading,setLoading]=useState(true);
  useEffect(()=>{
    const turn=++sequence.current;let live=true;setStatus(null);setError('');setLoading(true);
    // This existing project-scoped read returns actual configured routes and
    // Runtime status. It does not resolve materials, enqueue, or grant access.
    void command('desk.review.read',{project_id:s.project.id}).then(value=>{
      if(!live||sequence.current!==turn)return;
      // desk.review.read exposes configured route identities and authorization,
      // not connectivity or billing probes. An absent availability field is
      // the existing backend contract, not evidence that the route is missing.
      if(typeof value.runtime_running!=='boolean'||!Array.isArray(value.providers)||value.providers.some((p:any)=>
        !p||typeof p.id!=='string'||!p.id.trim()||!['codex','deepseek_harness'].includes(p.route)||
        typeof p.authorized!=='boolean'||p.available!==undefined&&typeof p.available!=='boolean')||
        new Set(value.providers.map((p:any)=>p.id)).size!==value.providers.length)
        throw new Error('执行路线状态不完整；请刷新核对，尚未开放执行。');
      setStatus({session:s,running:value.runtime_running,providers:value.providers});
    }).catch(e=>{if(live&&sequence.current===turn){setError(e instanceof Error?e.message:String(e));report(e);}})
      .finally(()=>{if(live&&sequence.current===turn)setLoading(false);});
    return()=>{live=false;++sequence.current;};
  },[s,attempt]);
  const current=status?.session===s?status:null;
  return <div className="research-commission-dock">
    <div className="panel-tools"><button disabled={loading} onClick={()=>{setStatus(null);setAttempt(n=>n+1);}}>刷新执行状态</button>
      {loading&&<span role="status">正在读取当前项目执行路线…</span>}{error&&<span role="alert">{error}</span>}</div>
    <ResearchCommissionPanel session={s} runtime={{running:current?.running===true}} providers={current?.providers||[]} report={report}
      onOpenTask={ref=>openWorkspaceLink({kind:'task',id:ref.id,projectId:ref.project_id,originViewId:props.api.id})}
      onOpenReference={openReference}/>
  </div>;
}

function ResearchGraphDock(props:IDockviewPanelProps){const {session,report,openReference}=useDesk();useVersion(session);return <ResearchGraphBody session={session} report={report} onOpenReference={openReference} onOpenObject={location=>openReference({id:location.id,revision:location.revision,consumer_id:session.project.id})}/>;}
function PinnedReferenceDock(props:IDockviewPanelProps){
  const {session:s,report,openWorkspaceLink}=useDesk();useVersion(s);
  const live=useRef(s);live.current=s;
  const dirty=()=>!!s.paperDraft?.dirty||[...s.buffers.values()].some(b=>b.dirty)||
    Object.keys(s.figureDrafts).length>0||Object.keys(s.compositionDrafts).length>0||Object.keys(s.captionDrafts).length>0;
  return <div className="fixed-source-dock"><TaskAuthority session={s} projectId={s.project.id} report={report}>{authority=>
    <PinnedReferenceBody reference={props.params.reference} consumerId={props.params.reference?.consumer_id||s.paper.id}
      projectId={s.project.id} report={report} onClose={()=>props.containerApi.removePanel(props.containerApi.getPanel(props.api.id)!)}
      revisionActions={{memoryKey:s,providers:authority?.providers||[],runtimeRunning:authority?.runtimeRunning===true,
        disabled:!authority||!authority.writableProjectIds.includes(s.project.id),dirty:dirty(),
        prepare:async()=>{if(live.current!==s)return false;await s.flush();return live.current===s&&!dirty();},
        onOpenTask:ref=>openWorkspaceLink({kind:'task',id:ref.id,projectId:ref.project_id,originViewId:props.api.id})}}/>
  }</TaskAuthority></div>;
}
function ClaimDock(props:IDockviewPanelProps){const {session,report,openReference}=useDesk();useVersion(session);return <ClaimBody object={{...session.paper,dirty:!!session.paperDraft?.dirty}} projectId={session.project.id} report={report} onOpenReference={openReference}/>;}
const components={researchCycle:ResearchCycleDock,projectTasks:ProjectTasksDock,commission:ResearchCommissionDock,claims:ClaimDock,researchGraph:ResearchGraphDock,fixedSource:PinnedReferenceDock,task:TaskPanel,generation:GenerationPanel,figure:FigurePanel,note:NotePanel,pdf:PdfPanel,paper:PaperPanel,navigation:Navigation,review:ReviewPanel};
function Workdesk({session:s,report,closedSessions,prepareLogout}:{session:Session,report:(e:unknown)=>void,closedSessions:WeakSet<Session>,prepareLogout:React.RefObject<(()=>Promise<void>)|null>}){
  useVersion(s);const api=useRef<DockviewApi|null>(null);const saving=useRef<ReturnType<typeof setTimeout>|undefined>(undefined);const serial=useRef(0);
  const [guideRequest,setGuideRequest]=useState(0);
  useEffect(()=>{
    const prepare=async()=>{
      clearTimeout(saving.current);clearTimeout(s.viewTimer);
      const layout=api.current?.toJSON()||s.layout;
      if(layout&&!await s.saveLayout(layout))throw new Error(s.error||'工作桌位置尚未保存；当前草稿保留。');
    };
    prepareLogout.current=prepare;
    return()=>{if(prepareLogout.current===prepare)prepareLogout.current=null;clearTimeout(saving.current);};
  },[s,prepareLogout]);
  const noteReads=useRef(new WeakMap<object,number>()),noteScope=useRef(s);noteScope.current=s;
  const [reviewLocation,setReviewLocation]=useState<ReviewLocation|null>(null);
  const currentReviewScope=paperNavigationScope(s);
  useEffect(()=>{setReviewLocation(value=>value?.scope===currentReviewScope?value:null);},[s,currentReviewScope]);
  const navigationLive=useRef(true);useEffect(()=>{navigationLive.current=true;return()=>{navigationLive.current=false;};},[s]);
  // Read navigation is transient per workdesk. It never changes saved anchors,
  // proposal decisions or manuscript drafts, and stale scope requests expire.
  const reviewNavigator:ReviewNavigator={
    state:reviewLocation?.scope===paperNavigationScope(s)?reviewLocation:null,
    locate:(scope,item)=>{if(!navigationLive.current||scope!==paperNavigationScope(s))return;
      if(!item.available){setReviewLocation({scope,activeKeys:[item.key],activationId:requestId(),focus:null,notice:item.reason||'原选区已变化，请明确重新定位。'});return;}
      setReviewLocation({scope,activeKeys:[item.key],activationId:requestId(),focus:{scope,item:structuredClone(item),requestId:requestId()},notice:''});
      showPanel('paper-source','paper','连续稿件','left');
    },
    activate:(scope,keys)=>{if(!navigationLive.current||scope!==paperNavigationScope(s)||!keys.length)return;
      setReviewLocation({scope,activeKeys:[...new Set(keys)],activationId:requestId(),focus:null,notice:keys.length>1?'此处有多个审阅话题，请明确选择。':''});
      showPanel('review-round','review','整轮意见','right');
    },
    result:value=>{if(!navigationLive.current||value.scope!==paperNavigationScope(s))return;setReviewLocation(old=>old?.focus?.requestId===value.requestId&&old.scope===value.scope?{...old,notice:value.status==='located'?'已定位原文；稿件与意见均未修改。':value.reason||'当前选区不可定位。'}:old);}
  };
  const open=async(path:string,split=false,offset?:number,record=true,endOffset?:number,expectedSha?:string,originViewId?:string,fallbackOffset?:number)=>{
    const a=api.current!;const previousOffset=s.locationOffset();
    const epoch=++serial.current;
    const origin=a.getPanel(originViewId||s.activeView);
    // History belongs to its initiating view. Never reuse a separate pinned
    // view merely because it displays the target file already.
    const existing=!split?(origin?.params?.path===path?origin:!originViewId?a.panels.find(p=>p.params?.path===path&&!p.params?.pinned):null):null;
    const reusable=!split?(origin?.params?.path&&!origin.params.pinned?origin:a.panels.find(p=>p.params?.path&&!p.params?.pinned)):null;
    let panel=existing||reusable;
    // Capture the target's saved position before changing the panel path.
    // Mounting a dirty buffer immediately would record its temporary caret
    // while the source read is pending, overwriting this history entry.
    const switchingPath=!!panel&&panel.params?.path!==path;
    const savedBeforeSwitch=switchingPath?structuredClone(s.viewLocations[panel!.id]?.[path]||s.locations[path]):undefined;
    if(panel){panel.api.updateParameters({path,readError:'',loading:switchingPath||!s.buffers.get(path)?.dirty&&!(existing&&s.buffers.has(path))});panel.api.setActive();}
    else panel=a.addPanel({id:'note-'+requestId(),component:'note',title:path.split('/').pop(),params:{path,pinned:split,loading:true},position:split?{direction:'right'}:supportingPosition(a,originViewId)});
    // A second view has its own read. Only a later request for this same
    // panel, a closed panel, or a different workdesk invalidates this result.
    noteReads.current.set(panel,epoch);
    const current=()=>navigationLive.current&&noteScope.current===s&&api.current===a&&a.getPanel(panel.id)===panel&&noteReads.current.get(panel)===epoch;
    const activate=()=>{if(a.activePanel===panel){s.activePath=path;s.activeView=panel.id;}s.notify();};
    try{await s.open(path,record,offset||0,previousOffset);}catch(error){
      if(current()){
        panel.api.updateParameters({loading:false,readError:error instanceof Error?error.message:String(error)});
        activate();
        // A disappeared file is an error, never an instruction to create it.
        // Refresh only the directory; retained dirty buffers are untouched.
        await s.refresh().catch(report);
        if(current())await s.saveLayout(a.toJSON());
      }
      throw error;
    }
    if(!current())return;
    const buffer=s.buffers.get(path)!;
    if(expectedSha&&(buffer.base!==expectedSha||buffer.dirty)){
      const message='命中文件已改变或含未保存手改，请保存后重新检索；当前内容保留。';
      panel.api.updateParameters({loading:false,readError:message});
      activate();
      throw new Error(message);
    }
    const cursor=codePointToUTF16(buffer.text,offset??fallbackOffset??0);
    const anchor=endOffset===undefined?cursor:codePointToUTF16(buffer.text,endOffset);
    const saved=savedBeforeSwitch||s.viewLocations[panel.id]?.[path]||s.locations[path];
    s.views[panel.id]=(offset===undefined||!record)&&saved?.base===s.buffers.get(path)!.base?{...saved,path,restoreScroll:true}:{path,cursor,anchor,restoreScroll:false};
    activate();
    // Location is provided through view state and an explicit panel update.
    // Completing a hidden/background view restores it without stealing focus
    // from the view the user selected while the read was in flight.
    panel.api.updateParameters({jump:a.activePanel===panel?epoch:0,cursor,loading:false});
    await s.saveLayout(a.toJSON());
  };
  const openWorkspaceLink=async(target:WorkspaceLocation)=>{
    if(target.projectId!==s.project.id)throw new Error('链接属于其他项目，请明确切换项目。');
    const a=api.current!;
    let panelId:string,component:string,title:string,params:any;
    if(target.kind==='figure'){
      await command('desk.figure.read',{project_id:s.project.id,id:target.id});
      panelId='figure';component='figure';title='图与来源';params={id:target.id};
    }else if(target.kind==='generation'){
      await noteCommand('build.status',s.project.id,{run_id:target.id});
      panelId='generation';component='generation';title='数据与生成';params={run_id:target.id};
    }else if(target.kind==='task'){
      const task=await readTask(target.id);
      if(task.project_id!==s.project.id)throw new Error('任务不属于当前项目。');
      const deskRound=task.payload.kind==='manuscript_revision'&&(await command('desk.review.read',{project_id:s.project.id})).rounds.some((round:any)=>round.task_id===task.id);
      panelId=deskRound?'review-round':'task-'+task.id;
      component=deskRound?'review':task.payload.kind==='research_cycle'?'researchCycle':'task';title=component==='review'?'整轮意见':component==='researchCycle'?'科研协作':'任务回报';params={task_id:task.id};
    }else{
      if(target.id!==s.paper.id)throw new Error('稿件不是当前项目采用的正文。');
      panelId='paper-source';component='paper';title='本地稿件文字';params={};
    }
    await s.flush();
    const existing=a.getPanel(panelId);
    if(existing){existing.api.updateParameters(params);existing.api.setActive();}
    else a.addPanel({id:panelId,component,title,params,position:['task','review','researchCycle'].includes(component)?supportingPosition(a,target.originViewId):{direction:'right'}});
    s.activeView=panelId;s.notify();
    await s.saveLayout(a.toJSON());
  };
  const openReference=async(reference:PinnedReference)=>{
    if(!reference?.id||!Number.isSafeInteger(reference.revision)||reference.revision<1)throw new Error('来源需要准确对象和修订。');
    await s.flush();const a=api.current!;const id='fixed-source-'+reference.id+'-'+reference.revision;
    const params={reference:structuredClone(reference)},existing=a.getPanel(id);
    if(existing){existing.api.updateParameters(params);existing.api.setActive();}
    else a.addPanel({id,component:'fixedSource',title:'固定来源 r'+reference.revision,params,position:supportingPosition(a,s.activeView)});
    s.activeView=id;s.notify();await s.saveLayout(a.toJSON());
  };
  const move=async(old:string,path:string,reviewed:boolean)=>{
    s.fileBusy.add(old);s.fileBusy.add(path);s.notify();try{
    if(s.buffers.get(old)?.dirty||s.buffers.get(path)?.dirty)throw new Error('相关笔记有未保存手改，请先保存；双方内容保留。');
    const a=api.current!;await s.flush();await s.saveLayout(a.toJSON());
    if(!s.persisted||s.error)throw new Error(s.error||'草稿尚未同步，请稍后再移动。');
    const result=await noteCommand('notes.move',s.project.id,{relative_path:old,new_path:path,expected_content_sha256:s.buffers.get(old)!.base,links_reviewed:reviewed});
    s.moved(old,result.relative_path,result.desk_revisions);
    for(const panel of a.panels)if(panel.params?.path===old)panel.api.updateParameters({path:result.relative_path});
    await s.refresh();await s.saveLayout(a.toJSON());await s.flush();return result;
    }finally{s.fileBusy.delete(old);s.fileBusy.delete(path);s.notify();}
  };
  const trash=async(path:string)=>{
    s.fileBusy.add(path);s.notify();try{
    if(s.buffers.get(path)?.dirty)throw new Error('当前笔记有未保存手改，请先保存。');
    const a=api.current!;await s.flush();await s.saveLayout(a.toJSON());
    if(!s.persisted||s.error)throw new Error(s.error||'草稿尚未同步，请稍后再回收。');
    const result=await noteCommand('notes.trash',s.project.id,{relative_path:path,expected_content_sha256:s.buffers.get(path)!.base});
    if(result.desk_revisions?.drafts!==undefined)s.draftRevision=result.desk_revisions.drafts;
    if(result.desk_revisions?.layout!==undefined)s.layoutRevision=result.desk_revisions.layout;
    if(s.buffers.get(path)?.dirty){s.buffers.get(path)!.conflict='文件已回收；操作期间的新输入保留为草稿，请恢复文件或另存。';await s.flush();s.notify();return;}
    for(const panel of [...a.panels])if(panel.params?.path===path)a.removePanel(panel);
    s.buffers.delete(path);delete s.locations[path];for(const locations of Object.values(s.viewLocations))delete locations[path];
    for(const [id,view] of Object.entries(s.views))if(view.path===path)delete s.views[id];
    if(s.activePath===path){s.activePath='';s.activeView='';}
    await s.refresh();await s.saveLayout(a.toJSON());await s.flush();
    }finally{s.fileBusy.delete(path);s.notify();}
  };
  useEffect(()=>{const before=(e:BeforeUnloadEvent)=>{if(!s.persisted){e.preventDefault();e.returnValue='';}};window.addEventListener('beforeunload',before);return()=>{window.removeEventListener('beforeunload',before);if(!closedSessions.has(s))void s.flush();};},[s,closedSessions]);
  const [quick,setQuick]=useState(false),[quickQuery,setQuickQuery]=useState('');
  const [resettingLayout,setResettingLayout]=useState(false),[defaultLayoutHint,setDefaultLayoutHint]=useState('');
  const layoutResetSequence=useRef(0),deskMounted=useRef(true);
  useEffect(()=>{deskMounted.current=true;return()=>{deskMounted.current=false;++layoutResetSequence.current;};},[s]);
  const restoreDefaultLayout=async()=>{
    const a=api.current;if(!a)return;
    const sequence=++layoutResetSequence.current,epoch=++serial.current;
    const current=()=>deskMounted.current&&layoutResetSequence.current===sequence&&serial.current===epoch&&api.current===a;
    setResettingLayout(true);setDefaultLayoutHint('');
    try{
      await s.flush();if(!current())return;
      if(!s.persisted||s.error)throw new Error(s.error||'草稿尚未同步；当前面板和手改保留。');
      // Read the actual directory before choosing a default. Cached inbox paths
      // are not permission to reopen a recycled or externally removed file.
      await s.refresh();if(!current())return;
      const files=s.entries.filter(entry=>entry.type!=='folder'&&entry.relative_path.endsWith('.md')).map(entry=>entry.relative_path as string);
      const available=(path:string)=>files.includes(path)||!!s.buffers.get(path)?.dirty;
      const path=available('notes/inbox.md')?'notes/inbox.md':available(s.activePath)?s.activePath:files[0]||[...s.buffers].find(([,buffer])=>buffer.dirty)?.[0];
      if(path&&!s.buffers.get(path)?.dirty){await s.open(path,false);if(!current())return;}
      if(!s.persisted||s.error)throw new Error(s.error||'操作期间有新输入；当前面板和手改保留，请稍后重试。');
      const oldNote=path?a.panels.find(panel=>panel.toJSON().contentComponent==='note'&&panel.params?.path===path):undefined;
      const noteId=oldNote?.id||'note-default',params={...oldNote?.params,path};
      a.clear();a.addPanel({id:'paper-source',component:'paper',title:'连续稿件'});
      if(path)a.addPanel({id:noteId,component:'note',title:path.split('/').pop()!,params,position:{referencePanel:'paper-source',direction:'right'},initialWidth:Math.max(240,Math.min(460,a.width*.34))});
      else setDefaultLayoutHint('项目暂无可用笔记；可在目录中新建或恢复回收笔记。');
      s.activeView=path?noteId:'paper-source';s.activePath=path||'';s.notify();await s.saveLayout(a.toJSON());
    }catch(error){if(current())report(error);}
    finally{if(deskMounted.current&&layoutResetSequence.current===sequence)setResettingLayout(false);}
  };
  const showPanel=(id:string,component:string,title:string,side:'left'|'right',maximize=false)=>{
    const a=api.current;if(!a)return;const current=a.activePanel;if(current?.api.isMaximized())current.api.exitMaximized();
    let panel=a.getPanel(id);if(panel)panel.api.setActive();else{
      const target=side==='left'?a.panels.find(p=>['paper','pdf','figure'].includes(p.toJSON().contentComponent||'')):undefined;
      panel=a.addPanel({id,component,title,position:side==='right'?supportingPosition(a):target?{referencePanel:target.id,direction:'within'}:{direction:side}});
    }
    if(maximize)panel.api.maximize();s.activeView=id;s.notify();void s.saveLayout(a.toJSON());
  };
  const showNavigation=()=>{const a=api.current;if(!a)return;const panel=a.getPanel('navigation');if(panel&&panel.api.isActive){a.removePanel(panel);return;}if(panel)panel.api.setActive();else a.addPanel({id:'navigation',component:'navigation',title:'笔记导航',position:{direction:'left'},initialWidth:280});};
  const showNotes=()=>{const a=api.current;if(!a)return;const note=a.panels.find(p=>p.toJSON().contentComponent==='note'&&p.params?.path===s.activePath)||a.panels.find(p=>p.toJSON().contentComponent==='note');if(note){if(a.activePanel?.api.isMaximized())a.activePanel.api.exitMaximized();note.api.setActive();return;}const available=s.entries.filter(e=>e.type!=='folder'&&e.relative_path.endsWith('.md'));const path=available.find(e=>e.relative_path===s.activePath)?.relative_path||available.find(e=>e.relative_path==='notes/inbox.md')?.relative_path||available[0]?.relative_path;if(path)void open(path).catch(report);else showNavigation();};
  const guideActions={
      retrySync:()=>void s.retrySync(),quickOpen:()=>setQuick(true),search:showNavigation,notes:showNotes,paper:()=>showPanel('paper-source','paper','连续稿件','left'),partner:()=>showPanel('review-round','review','整轮意见','right'),commission:()=>showPanel('research-commission','commission','研究委托','right'),researchCycle:()=>showPanel('research-cycle','researchCycle','科研协作','right'),tasks:()=>showPanel('project-tasks','projectTasks','项目任务','right'),
      figure:()=>showPanel('figure-editor','figure','科研图','left',true),generation:()=>showPanel('generation','generation','数据与生成','left'),graph:()=>showPanel('research-graph','researchGraph','问题与证据','left'),claims:()=>showPanel('manuscript-claims','claims','稿件 Claim','left'),resetLayout:()=>void restoreDefaultLayout(),guide:()=>setGuideRequest(value=>value+1)
    };
  return <Context.Provider value={{session:s,open,openWorkspaceLink,openReference,move,trash,report,reviewNavigator}}><div className="workdesk-container" onKeyDownCapture={e=>{if((e.target as HTMLElement).closest('[data-workspace-guide]')||e.nativeEvent.isComposing||e.nativeEvent.keyCode===229)return;if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();e.stopPropagation();setQuick(true);}if((e.ctrlKey||e.metaKey)&&e.shiftKey&&e.key.toLowerCase()==='f'){e.preventDefault();const a=api.current!;const p=a.getPanel('navigation');if(p){p.api.updateParameters({focusSearch:requestId()});p.api.setActive();}else a.addPanel({id:'navigation',component:'navigation',title:'笔记导航',params:{focusSearch:requestId()},position:{direction:'left'},initialWidth:280});}}}><WorkspaceChrome activeEditor={api.current?.activePanel?.toJSON().contentComponent} activeTitle={api.current?.activePanel?.title} draftState={s.error?'error':s.persisted?'synced':'syncing'} navigationOpen={!!api.current?.getPanel('navigation')} resettingLayout={resettingLayout} retryingSync={s.retryingSync} hint={defaultLayoutHint} actions={guideActions}/>
    <WorkspaceGuide openRequest={guideRequest} onOpenModule={module=>{
      if(module==='workspace'){document.querySelector<HTMLSelectElement>('[aria-label="当前项目"]')?.focus();return;}
      if(module==='pdf'){showPanel('paper-pdf','pdf','论文 PDF','left');return;}
      const action=module==='sources'?'figure':module==='review'?'partner':module==='collaboration'?'researchCycle':module;
      guideActions[action]();
    }}/>
    {quick&&<div className="modal-backdrop" onKeyDown={e=>{if(e.key==='Escape')setQuick(false);}}><div className="dialog quick-open" role="dialog" aria-label="快速打开笔记"><label>文件名或路径<input aria-label="快速打开查询" autoFocus value={quickQuery} onChange={e=>setQuickQuery(e.target.value)}/></label>{s.entries.filter(x=>x.type!=='folder'&&x.relative_path.toLowerCase().includes(quickQuery.toLowerCase())).map(x=><button key={x.relative_path} onClick={()=>{setQuick(false);open(x.relative_path).catch(report);}}>{x.relative_path}</button>)}<button onClick={()=>setQuick(false)}>关闭快开</button></div></div>}
    <DockviewReact className="dockview-theme-rp" components={components} onReady={e=>{api.current=e.api;let restoredLayoutAdjusted=false;try{if(s.layout){e.api.fromJSON(s.layout);for(const panel of [...e.api.panels]){
      const note=panel.toJSON().contentComponent==='note',path=panel.params?.path;
      const missing=note&&typeof path==='string'&&!s.entries.some(entry=>entry.type!=='folder'&&entry.relative_path===path)&&!s.buffers.get(path)?.dirty;
      if(panel.params?.trashed||missing){e.api.removePanel(panel);restoredLayoutAdjusted=true;if(s.activeView===panel.api.id){s.activeView='';s.activePath='';}}
      else if(note&&panel.params?.loading){panel.api.updateParameters({loading:false});restoredLayoutAdjusted=true;}
    }}else{e.api.addPanel({id:'paper-source',component:'paper',title:'连续稿件'});if(s.entries.some(entry=>entry.relative_path==='notes/inbox.md'))e.api.addPanel({id:'note-default',component:'note',title:'随手记',params:{path:'notes/inbox.md'},position:{referencePanel:'paper-source',direction:'right'},initialWidth:Math.max(240,Math.min(460,e.api.width*.34))});e.api.getPanel('paper-source')?.api.setActive();}}catch(x){report(x);}
      if(!s.layout||restoredLayoutAdjusted)void s.saveLayout(e.api.toJSON());
      const u=new URL(location.href);const entities=['figure','generation_run','task','paper'].filter(key=>u.searchParams.has(key));const path=u.searchParams.get('note');
      if(entities.length+(path?1:0)>1)report(new Error('工作桌链接需要一个明确入口，未自动打开多个对象。'));
      else if(entities.length===1){const key=entities[0],id=u.searchParams.get(key)!;const kind=key==='generation_run'?'generation':key as 'figure'|'task'|'paper';void openWorkspaceLink({kind,id,projectId:s.project.id,originViewId:s.activeView}).catch(report);}
      else if(path)void open(path,false,Number(u.searchParams.get('match_start')||0),true,u.searchParams.has('match_end')?Number(u.searchParams.get('match_end')):undefined,u.searchParams.get('match_sha')||undefined).catch(report);
      for(const key of ['figure','generation_run','task','paper','note','match_start','match_end','match_sha'])u.searchParams.delete(key);window.history.replaceState(null,'',u);
      e.api.onDidActivePanelChange(({panel})=>{if(!panel)return;s.activeView=panel.id;if(panel.toJSON().contentComponent==='note'&&panel.params?.path)s.activePath=panel.params.path;s.notify();});
      e.api.onDidLayoutChange(()=>{if(closedSessions.has(s))return;clearTimeout(saving.current);saving.current=setTimeout(()=>{if(!closedSessions.has(s))void s.saveLayout(e.api.toJSON());},160);});
    }}/><div className="statusbar"><span>● 项目空间 · 原生文件</span><span>{s.error||'本地工作桌候选 · 正式验收未通过'}</span></div></div></Context.Provider>;
}

function App(){
  const [projects,setProjects]=useState<any[]>([]);const [session,setSession]=useState<Session|null>(null);const sessions=useRef(new Map<string,Session>());const [error,setError]=useState('');const [loading,setLoading]=useState(true);const [showNew,setShowNew]=useState(false);const [title,setTitle]=useState('');const [template,setTemplate]=useState('single');const [creating,setCreating]=useState(false);const [auth,setAuth]=useState(false),[loggingOut,setLoggingOut]=useState(false);
  const closedSessions=useRef(new WeakSet<Session>()),prepareLogout=useRef<(()=>Promise<void>)|null>(null),leaving=useRef(false);
  const report=(e:unknown)=>setError(e instanceof Error?e.message:String(e));
  const projectSequence=useRef(0);
  const choose=async(p:any)=>{
    if(leaving.current)return;
    const sequence=++projectSequence.current;setLoading(true);setError('');
    try{
      if(session)await session.flush();if(sequence!==projectSequence.current)return;
      let s=sessions.current.get(p.id);
      if(!s){s=new Session(p);await s.load();if(sequence!==projectSequence.current)return;sessions.current.set(p.id,s);}
      setSession(s);const u=new URL(location.href);u.searchParams.set('project',p.id);window.history.replaceState(null,'',u);
    }catch(e){if(sequence===projectSequence.current)report(e);}finally{if(sequence===projectSequence.current)setLoading(false);}
  };
  const start=async()=>{
    let sequence=++projectSequence.current;setLoading(true);setError('');
    try{
      await initialize();if(sequence!==projectSequence.current)return;
      const x=await command('desk.bootstrap');if(sequence!==projectSequence.current)return;
      setAuth(false);
      setProjects(x.projects);const selected=x.projects.find((p:any)=>p.id===new URL(location.href).searchParams.get('project'))||x.projects[0];
      if(selected){sequence=projectSequence.current+1;await choose(selected);}else setShowNew(true);
    }catch(e:any){if(sequence===projectSequence.current){if(e.code==='unauthorized')setAuth(true);else report(e);}}
    finally{if(sequence===projectSequence.current)setLoading(false);}
  };
  useEffect(()=>{void start();return()=>{++projectSequence.current;};},[]);
  const leave=async()=>{
    if(leaving.current||loading||creating||auth)return;
    leaving.current=true;setLoggingOut(true);setError('');
    const sequence=++projectSequence.current,current=()=>sequence===projectSequence.current;
    const cached=[...sessions.current.values()];
    try{
      await prepareLogout.current?.();if(!current())return;
      for(const s of cached){
        clearTimeout(s.timer);clearTimeout(s.viewTimer);
        if(s!==session&&s.layout&&!await s.saveLayout(s.layout))throw new Error(s.error||'工作桌位置尚未保存。');
        await s.flush();if(!current())return;
        if(!s.persisted||s.error)throw new Error(s.error||'草稿尚未保存。');
      }
      const epochs=cached.map(s=>s.contentEpoch);
      if(!await logout(current))return;
      // A late write result must not discard newer local edits, even after
      // the server has ended the cookie session. Re-login can reuse them.
      if(cached.some((s,i)=>!s.persisted||s.contentEpoch!==epochs[i])){
        setAuth(true);setShowNew(false);setError('已退出登录；操作期间产生的较新草稿仍保留在当前页面，请重新登录后保存。');return;
      }
      for(const s of cached){closedSessions.current.add(s);clearTimeout(s.timer);clearTimeout(s.viewTimer);}
      sessions.current.clear();setSession(null);setProjects([]);setShowNew(false);setTitle('');setTemplate('single');setAuth(true);
      const u=new URL(location.href);for(const key of ['project','figure','generation_run','task','paper','note','match_start','match_end','match_sha'])u.searchParams.delete(key);window.history.replaceState(null,'',u);
    }catch(e){if(current())setError('未能退出登录；当前工作桌和草稿已保留。'+(e instanceof Error?e.message:String(e)));}
    finally{if(current()){leaving.current=false;setLoggingOut(false);}}
  };
  return <main><header><strong className="logo">rp<span>·</span></strong><select aria-label="当前项目" disabled={loading||auth||loggingOut||creating} value={session?.project.id||''} onChange={e=>{const p=projects.find(x=>x.id===e.target.value);if(p)void choose(p);}}><option disabled value="">选择项目</option>{projects.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select><button disabled={loading||auth||loggingOut||creating} onClick={()=>setShowNew(true)}>新建项目</button><span className="header-spacer"/><small>Research Partner</small><span className="candidate">核心协作开发候选</span>{!auth&&<button disabled={loading||creating||loggingOut} onClick={()=>void leave()}>{loggingOut?'退出中…':'退出登录'}</button>}</header>
    {error&&<div className="error global-error" role="alert">{error}<button onClick={()=>setError('')}>关闭提示</button></div>}
    {auth&&<LocalAccountAccess onAuthenticated={start}/>}
    {showNew&&!auth&&<div className="modal-backdrop"><form className="dialog" onSubmit={async e=>{e.preventDefault();if(creating||leaving.current)return;const sequence=++projectSequence.current;setCreating(true);try{const x=await command('desk.project.create',{title,template,request_id:requestId()});if(sequence!==projectSequence.current)return;const p=x.project;setProjects(old=>[...old,p]);setShowNew(false);setTitle('');setCreating(false);await choose(p);if(sequence+1===projectSequence.current&&x.render_error)report(new Error('项目已保存，PDF编译失败：'+x.render_error.message));}catch(x){if(sequence===projectSequence.current)report(x);}finally{if(sequence===projectSequence.current)setCreating(false);}}}><h2>建立项目</h2><p>创建空白论文模板和项目笔记库。无需模型密钥。</p><label>项目名称<input aria-label="项目名称" value={title} onChange={e=>setTitle(e.target.value)} maxLength={200} required autoFocus/></label><label>基础模板<select aria-label="基础模板" value={template} onChange={e=>setTemplate(e.target.value)}><option value="single">中英单栏</option><option value="double">中英双栏</option></select></label><div className="dialog-actions">{session&&<button type="button" disabled={creating} onClick={()=>setShowNew(false)}>取消</button>}<button className="primary" disabled={creating}>{creating?'创建与编译中…':'创建项目'}</button></div></form></div>}
    {loggingOut&&<div className="modal-backdrop"><div className="dialog" role="status">正在保存草稿并退出登录…</div></div>}
    <div style={{display:'contents'}} inert={loggingOut||undefined}>{loading?<div className="loading">读取实际项目…</div>:session?<Workdesk key={session.project.id} session={session} report={report} closedSessions={closedSessions.current} prepareLogout={prepareLogout}/>:!auth&&<div className="empty"><h1>开始你的研究项目</h1><button disabled={loggingOut} onClick={()=>setShowNew(true)}>新建项目</button></div>}</div>
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
