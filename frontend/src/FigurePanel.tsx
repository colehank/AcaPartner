import type {MainFigureOpinionAnchor} from './MainFigureOpinionControl';
import {FigureOpinionControl,type FigureOpinionAnchor} from './FigureOpinionControl';
import {FigureSourcePanel} from './FigureSourcePanel';
import {FigureScriptEditor} from './FigureScriptEditor';
import {FigurePurposeCandidates} from './FigurePurposeCandidates';
import {useCallback,useEffect,useLayoutEffect,useRef,useState,useSyncExternalStore} from 'react';
import type {DockviewApi,DockviewPanelApi} from 'dockview-react';
import {command,requestId} from './api';
import {Session} from './session';
import {MainFigure} from './MainFigure';
import {ScientificCanvas,CanvasHandles} from './ScientificCanvas';
import {figureViewMemory,inheritCanvasCamera,type CanvasViewMemory,type FigurePanelMemory} from './figureViewMemory';
import {alignLayout,artistDelta,artistResize,boxSelection,validCanvasBox,type Alignment,type Corner} from './figureCanvasGeometry';

type Layer={target:string,properties:Record<string,any>};
type VisualUndo={version:1,project_id:string,id:string,before:Layer[],after:Layer[],source:any,after_ref:{id:string,revision:number,sha256:string},numeric_sha?:string};
const stableVisual=(value:any):any=>Array.isArray(value)?value.map(stableVisual):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,stableVisual(value[key])])):value;
const sameVisual=(left:any,right:any)=>JSON.stringify(stableVisual(left))===JSON.stringify(stableVisual(right));
// A visual inverse may change only overlays, revision and the save timestamp.
// All other saved fields, including unknown source/purpose metadata, stay pinned.
const visualSource=(figure:any)=>{const {revision,updated_at,content,...fixed}=figure;const {overlays,...science}=content;return {...fixed,content:science};};
const numericSha=(value:any)=>value?.assets?.['numeric_values.json']?.sha;
const visualRef=(value:any)=>{const ref=value?.source_ref;return ref?.id===value?.figure?.id&&ref?.revision===value.figure.revision&&Number.isSafeInteger(ref.revision)&&ref.revision>0&&typeof ref.sha256==='string'&&/^[a-f0-9]{64}$/.test(ref.sha256)?ref:null;};

const geometryKey=(project:string,id:string,revision:number|undefined,overlays:Layer[])=>JSON.stringify([project,id,revision,overlays]);
export type FigureDockview={api:DockviewPanelApi,containerApi:DockviewApi};

export function figurePropertySelection(manifest:any[],layers:Layer[],selected:string[],property:string){
  const members=manifest.filter(member=>selected.includes(member.id)&&member.supported_properties?.includes(property));
  const values=members.map(member=>{const properties=layers.find(layer=>layer.target===member.id)?.properties;return properties&&Object.hasOwn(properties,property)?properties[property]:member[property];});
  return {targets:members.map(member=>member.id),values,value:values[0],mixed:new Set(values.map(value=>JSON.stringify(value))).size>1};
}

export function FigureBody({session:s,report,initialId,initialRevision,expanded,toggleExpanded,dockview,embedded,onSaved,onLocationChange,viewMemory,onReviewFigure,initialArtist,initialSlotIds}:{session:Session,report:(e:unknown)=>void,initialId?:string,initialRevision?:number,initialArtist?:string,initialSlotIds?:string[],expanded?:boolean,toggleExpanded?:()=>void,dockview?:FigureDockview,embedded?:boolean,onSaved?:()=>Promise<void>,onLocationChange?:(location:{id:string,revision?:number})=>void,viewMemory?:FigurePanelMemory,onReviewFigure?:(anchor:FigureOpinionAnchor|MainFigureOpinionAnchor)=>void}){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const subscribeExpanded=useCallback((notify:()=>void)=>{
    if(!dockview)return()=>{};
    const maximized=dockview.containerApi.onDidMaximizedGroupChange(()=>notify());
    const regrouped=dockview.api.onDidGroupChange(()=>notify());
    return()=>{maximized.dispose();regrouped.dispose();};
  },[dockview?.api,dockview?.containerApi]);
  const readExpanded=useCallback(()=>dockview?dockview.api.isMaximized():!!expanded,[dockview?.api,expanded]);
  const canvasExpanded=useSyncExternalStore(subscribeExpanded,readExpanded,readExpanded);
  const changeExpanded=dockview?()=>{dockview.api.isMaximized()?dockview.api.exitMaximized():dockview.api.maximize();}:toggleExpanded;
  const [list,setList]=useState<any[]>([]),[id,setId]=useState(initialId||s.views['figure_selection']?.figure_id||''),[view,setView]=useState<any>(null),[preview,setPreview]=useState<any>(null);
  const [fixedRevision,setFixedRevision]=useState<number|undefined>(initialId?initialRevision:s.views['figure_selection']?.figure_revision??undefined);
  const fixedReadRevision=useRef(fixedRevision);fixedReadRevision.current=fixedRevision;
  const history=fixedRevision!==undefined;
  const figureWriteRevision=s.figureWriteRevisions[id]||0;
  const lastFigureWrite=useRef({session:s,id,revision:figureWriteRevision});
  const localMemory=useRef<FigurePanelMemory>(new Map());
  const memory=viewMemory||localMemory.current;
  const locationMemory=figureViewMemory(memory,s.project.id,id,fixedRevision,view?.figure?.revision,view?.source_ref?.sha256??view?.definition_sha256);
  const panelElement=useRef<HTMLElement>(null);
  const readableLocation=!!view&&view.figure.id===id&&view.figure.project_id===s.project.id&&(fixedRevision===undefined||view.figure.revision===fixedRevision);
  const currentMainCamera=useRef<{session:Session,project:string,id:string,revision:number,canvas:CanvasViewMemory}|undefined>(undefined);
  useLayoutEffect(()=>{
    const previous=currentMainCamera.current;
    if(history||previous&&(previous.session!==s||previous.project!==s.project.id||previous.id!==id))currentMainCamera.current=undefined;
    if(readableLocation&&!history)currentMainCamera.current=view.definition?{session:s,project:s.project.id,id,revision:view.figure.revision,canvas:locationMemory.canvas}:undefined;
    // Pending/failed reads keep only navigation memory. The old graphic remains
    // hidden, and a new identity or fixed view cannot inherit this camera.
  },[s,s.project.id,id,history,readableLocation,view,locationMemory]);
  useLayoutEffect(()=>{
    // Restore only after the fresh authorized content has mounted. Loading or
    // rejected reads must neither display a cached figure nor overwrite its view.
    const element=panelElement.current,scroll=locationMemory.panelScroll;
    if(!readableLocation||!element||!scroll)return;
    if([scroll.top,scroll.left].every(value=>Number.isFinite(value)&&value>=0)){
      element.scrollTop=scroll.top;element.scrollLeft=scroll.left;
    }
  },[locationMemory,readableLocation,canvasExpanded]);
  const [selected,setSelected]=useState<string[]>(['figure:root']),[layers,setLayers]=useState<Layer[]>([]),[actionBusy,setActionBusy]=useState(false),[previewBusy,setPreviewBusy]=useState(false),[newFigure,setNewFigure]=useState(false);
  // Completing a preview cannot unlock an in-flight saved write.
  const [scriptBusy,setScriptBusy]=useState(false);
  const scriptWriteOwner=useRef<string|null>(null),scriptContext=useRef({session:s,project:s.project.id,id});
  scriptContext.current={session:s,project:s.project.id,id};
  const busy=actionBusy||previewBusy||scriptBusy;
  const [imageSize,setImageSize]=useState([1000,700]),[moving,setMoving]=useState<{ids:string[],dx:number,dy:number}|null>(null);
  const [title,setTitle]=useState(''),[script,setScript]=useState(''),[inputs,setInputs]=useState('{}'),[parameters,setParameters]=useState('{}');
  const [source,setSource]=useState(false),[caption,setCaption]=useState(''),[anchor,setAnchor]=useState(s.paper.content.blocks[0]?.id||'');
  const [runs,setRuns]=useState<any[]>([]),[runId,setRunId]=useState(''),[rebindInputs,setRebindInputs]=useState('{}'),[purposeRefresh,setPurposeRefresh]=useState(0);
  const [newMain,setNewMain]=useState(false),[mainTitle,setMainTitle]=useState(''),[slotCount,setSlotCount]=useState(2);
  const active=useRef(''),timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),drag=useRef<any>(null),canvas=useRef<HTMLDivElement>(null);
  const epoch=useRef(0),actionSequence=useRef(0),previewQueue=useRef<Promise<any>>(Promise.resolve());
  const [previewGeometry,setPreviewGeometry]=useState(''),[geometryNotice,setGeometryNotice]=useState('');
  const geometryContext=useRef<any>(null),geometryAction=useRef(0),previewJob=useRef<{key:string,serial:number,promise:Promise<any>}|null>(null);
  const [readError,setReadError]=useState<{project:string,id:string,message:string}|null>(null);
  const readSequence=useRef(0),listSequence=useRef(0),mounted=useRef(false),project=useRef(s.project.id);
  project.current=s.project.id;
  const selectFigure=(target:string,revision?:number)=>{if(target===id&&active.current===target&&revision===fixedReadRevision.current)return;++readSequence.current;active.current=target;fixedReadRevision.current=revision;setFixedRevision(revision);setReadError(null);setView(null);setId(target);};
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;++readSequence.current;++listSequence.current;};},[]);
  const refreshList=()=>{const projectId=s.project.id,sequence=++listSequence.current;return command('desk.figures.list',{project_id:projectId}).then(x=>{if(!mounted.current||project.current!==projectId||sequence!==listSequence.current)return;setList(x.figures);if(!id&&x.figures.length)selectFigure(x.figures[0].id);});};
  const read=async(target=id)=>{
    const projectId=s.project.id,sequence=++readSequence.current,revision=fixedReadRevision.current;
    const current=()=>mounted.current&&project.current===projectId&&active.current===target&&revision===fixedReadRevision.current&&sequence===readSequence.current;
    setReadError(null);
    try{
      if(revision!==undefined&&(!Number.isSafeInteger(revision)||revision<1))throw new Error('稿内图必须有明确的保存修订，不能默读当前head');
      const x=await command('desk.figure.read',{project_id:projectId,id:target,...(revision===undefined?{}:{revision})});if(!current())return;
      if(x.figure?.id!==target||x.figure?.project_id!==projectId||revision!==undefined&&x.figure.revision!==revision)throw new Error('图读取回执与当前项目、图或固定修订不符');
      if(revision===undefined&&x.figure.revision<(s.figureWriteRevisions[target]||0))throw new Error('当前图读取早于已确认的采用修订；请重新读取，草稿保留。');
      const remembered=figureViewMemory(memory,projectId,target,revision,x.figure.revision,x.source_ref?.sha256??x.definition_sha256);
      const previous=currentMainCamera.current;
      if(revision===undefined&&x.definition&&previous?.session===s&&previous.project===projectId&&previous.id===target&&x.figure.revision>previous.revision)
        inheritCanvasCamera(remembered.canvas,previous.canvas,x.definition.width,x.definition.height);
      if(!x.definition){
        const validIds=new Set((x.render?.manifest||[]).map((member:any)=>member.id));
        // A review jump selects only its requested Artist in this freshly authorized
        // saved view. An absent Artist never falls back to an unrelated selection.
        const requested=target===initialId&&revision===initialRevision?initialArtist:undefined;
        const selection=(requested===undefined?(remembered.selected||['figure:root']):[requested]).filter(member=>validIds.has(member));
        setSelected(selection);remembered.selected=selection;
      }
      setImageSize(remembered.imageSize||[1000,700]);
      setView(x);setList(old=>old.map(item=>item.id===x.figure.id?{...item,title:x.figure.title,revision:x.figure.revision}:item));setPreview(null);setPreviewGeometry('');
      ++epoch.current;setLayers((revision===undefined?s.figureDrafts[target]?.overlays:undefined)||x.figure.content.overlays||[]);setRebindInputs(JSON.stringify(x.figure.content.input_assets||{},null,2));return x;
    }catch(error){
      if(!current())return;
      setView(null);setReadError({project:projectId,id:target,message:error instanceof Error?error.message:String(error)});throw error;
    }
  };
  useEffect(()=>{if(initialId)selectFigure(initialId,initialRevision);},[initialId,initialRevision]);
  useEffect(()=>{refreshList().catch(report);},[s.project.id]);
  useEffect(()=>{const projectId=s.project.id;let cancelled=false;setRuns([]);command('desk.datasets.list',{project_id:projectId}).then(x=>{if(!cancelled&&mounted.current&&project.current===projectId)setRuns(x.runs.filter((r:any)=>r.status==='generated'));}).catch(error=>{if(!cancelled&&mounted.current&&project.current===projectId)report(error);});return()=>{cancelled=true;};},[s.project.id,source,newFigure,purposeRefresh]);
  const locationChange=useRef(onLocationChange);locationChange.current=onLocationChange;
  useEffect(()=>{if(!embedded){s.position('figure_selection',{figure_id:id,figure_revision:fixedRevision??null});locationChange.current?.({id,...(fixedRevision===undefined?{}:{revision:fixedRevision})});}},[id,fixedRevision,s.project.id,embedded]);
  useEffect(()=>{active.current=id;epoch.current++;clearTimeout(timer.current);++geometryAction.current;setGeometryNotice('');setView(null);setReadError(null);++actionSequence.current;setActionBusy(false);setPreviewBusy(false);scriptWriteOwner.current=null;setScriptBusy(false);if(id)read(id).catch(report);return()=>{++readSequence.current;active.current='';clearTimeout(timer.current);};},[id,fixedRevision,s.project.id,initialArtist]);
  useEffect(()=>{
    const previous=lastFigureWrite.current;lastFigureWrite.current={session:s,id,revision:figureWriteRevision};
    // A newly mounted/location-switched pane already does its own fresh read.
    // A retained current pane needs another one after a different panel writes.
    if(previous.session!==s||previous.id!==id||figureWriteRevision<=previous.revision||history||!id||view?.figure?.revision>=figureWriteRevision)return;
    ++epoch.current;++geometryAction.current;clearTimeout(timer.current);
    setGeometryNotice('');setView(null);setPreview(null);setPreviewGeometry('');setPreviewBusy(false);
    // Keep an in-flight saved action locked, and preserve all Session drafts.
    // read() fences old replies and clears the canvas on a fresh permission error.
    void read(id).catch(report);
  },[s,id,fixedRevision,figureWriteRevision]);
  const act=async(fn:()=>Promise<void>)=>{const serial=++actionSequence.current,target=active.current,projectId=project.current;setActionBusy(true);const current=()=>mounted.current&&serial===actionSequence.current&&target===active.current&&projectId===project.current;try{await fn();}catch(e){if(current())report(e);}finally{if(current())setActionBusy(false);}};
  const draw=view&&(preview||view.render);const manifest=draw?.manifest||[];
  const staleDraft=!history&&!!view&&!!s.figureDrafts[id]&&s.figureDrafts[id].base!==view.figure.revision;
  const undoKey='figure-visual-undo:'+id,undo=s.views[undoKey]?.entry as VisualUndo|undefined;
  const undoMatches=(value:any,entry=undo)=>!!entry&&entry.version===1&&entry.project_id===s.project.id&&entry.id===value?.figure?.id&&value.figure.project_id===s.project.id&&Array.isArray(entry.before)&&Array.isArray(entry.after)&&!!visualRef(value)&&sameVisual(entry.after_ref,visualRef(value))&&sameVisual(entry.after,value.figure.content.overlays||[])&&sameVisual(entry.source,visualSource(value.figure))&&(!entry.numeric_sha||entry.numeric_sha===numericSha(value.render));
  const undoReady=!history&&!staleDraft&&!!view&&undoMatches(view)&&!s.figureDrafts[id]&&sameVisual(layers,view.figure.content.overlays||[]);
  const currentGeometryKey=geometryKey(s.project.id,id,view?.figure.revision,layers);
  const savedGeometryKey=view?geometryKey(s.project.id,id,view.figure.revision,view.figure.content.overlays||[]):'';
  const geometryReady=!!draw&&Array.isArray(draw.manifest)&&(preview?previewGeometry===currentGeometryKey:savedGeometryKey===currentGeometryKey);
  geometryContext.current={session:s,project:s.project.id,id,revision:view?.figure.revision,key:currentGeometryKey,layers,manifest,selected,history,staleDraft,ready:geometryReady};
  const runPreview=(next:Layer[]):Promise<any>=>{
    const context=geometryContext.current;
    if(history||staleDraft||!view||context.session!==s||context.id!==id||context.revision!==view.figure.revision){report(new Error('固定历史只读；旧覆盖草稿不能覆盖当前图。'));return Promise.resolve(null);}
    const target=id,projectId=s.project.id,revision=s.figureDrafts[id]?.base??view.figure.revision,overlays=structuredClone(next),key=geometryKey(projectId,target,revision,overlays);
    if(previewJob.current?.key===key&&previewJob.current.serial===epoch.current)return previewJob.current.promise;
    const serial=++epoch.current;
    const current=()=>mounted.current&&project.current===projectId&&active.current===target&&serial===epoch.current&&geometryContext.current.session===s&&geometryContext.current.key===key&&!geometryContext.current.history&&!geometryContext.current.staleDraft;
    const promise=previewQueue.current.then(async()=>{
      if(!current())return null;
      setPreviewBusy(true);try{const x=await command('figure.preview',{id:target,expected_revision:revision,overlays,request_key:requestId()});if(!current())return null;
        if(!Array.isArray(x.manifest))throw new Error('当前覆盖预览未返回可核对的元素几何；原草稿保留。');
        setPreview(x);setPreviewGeometry(key);setMoving(null);return {key,value:x};
      }catch(e){if(current())report(e);return null;}finally{if(current())setPreviewBusy(false);}
    });
    previewJob.current={key,serial,promise};previewQueue.current=promise;void promise.finally(()=>{if(previewJob.current?.promise===promise)previewJob.current=null;});return promise;
  };
  const withGeometry=async(operation:(manifest:any[],snapshot:Layer[],ids:string[])=>void)=>{
    const context=geometryContext.current,serial=++geometryAction.current;
    if(context.history||context.staleDraft){report(new Error('固定历史或旧覆盖草稿不能修改当前几何。'));return;}
    const selectedIds=[...context.selected],snapshot=structuredClone(context.layers);
    const current=()=>mounted.current&&serial===geometryAction.current&&geometryContext.current.session===context.session&&geometryContext.current.key===context.key&&JSON.stringify(geometryContext.current.selected)===JSON.stringify(selectedIds)&&!geometryContext.current.history&&!geometryContext.current.staleDraft;
    let actualManifest=context.manifest;
    if(!context.ready){
      setGeometryNotice('正在核对当前草稿的元素几何；核对后执行所选对齐或分布。');clearTimeout(timer.current);
      const received=await runPreview(snapshot);if(!current())return;
      if(!received||received.key!==context.key){setGeometryNotice('当前草稿的几何预览未完成；草稿保留，请预览重绘后重试或撤销未采用调整。');return;}
      actualManifest=received.value.manifest;
    }
    if(!current())return;setGeometryNotice('');operation(actualManifest,snapshot,selectedIds);
  };
  const update=(next:Layer[],auto=true)=>{if(history||staleDraft)throw new Error('固定历史或旧覆盖草稿不能覆盖新图。');++geometryAction.current;setGeometryNotice('');++epoch.current;setLayers(next);s.figureDrafts[id]={base:s.figureDrafts[id]?.base??view.figure.revision,overlays:next};s.contentEpoch++;s.persisted=false;s.notify();s.schedule();if(auto){clearTimeout(timer.current);timer.current=setTimeout(()=>runPreview(next),300);}};
  const apply=(property:string,value:any)=>{
    const next=structuredClone(layers);let changed=false;
    for(const target of selected){const m=manifest.find((x:any)=>x.id===target);if(!m?.supported_properties?.includes(property))continue;let layer=next.find(x=>x.target===target);if(!layer){layer={target,properties:{}};next.push(layer);}layer.properties[property]=value;changed=true;}
    if(changed)update(next);
  };
  const axisSpines=manifest.filter((m:any)=>m.type==='spine'&&m.axes_role==='plot'&&['left','bottom'].includes(m.spine_side));
  const properties=[...new Set(selected.flatMap(target=>manifest.find((x:any)=>x.id===target)?.supported_properties||[]))] as string[];
  const chosen=manifest.find((m:any)=>selected.includes(m.id));
  const propertyOwner=(property:string)=>manifest.find((m:any)=>selected.includes(m.id)&&m.supported_properties?.includes(property));
  const selectTargets=(next:string[]|((old:string[])=>string[]))=>{++geometryAction.current;setGeometryNotice('');setSelected(old=>{const value=typeof next==='function'?next(old):next;locationMemory.selected=[...value];return value;});};
  const choose=(target:string,add=false)=>selectTargets(old=>add?(old.includes(target)?old.filter(x=>x!==target):[...old,target]):old.length>1&&old.includes(target)?old:[target]);
  const dragMembers=(ids:string[],sourceManifest:any[]=manifest)=>sourceManifest.filter((m:any)=>ids.includes(m.id)&&m.interaction?.drag?.enabled&&!(m.owner_axes_id&&m.owner_axes_id!==m.id&&ids.includes(m.owner_axes_id)&&sourceManifest.find((parent:any)=>parent.id===m.owner_axes_id)?.interaction?.drag?.enabled));
  const patchPositions=(changes:{target:string,property:string,value:any}[],snapshot:Layer[]=layers)=>{if(!changes.length)return;const next=structuredClone(snapshot);for(const change of changes){let layer=next.find(l=>l.target===change.target);if(!layer){layer={target:change.target,properties:{}};next.push(layer);}layer.properties[change.property]=change.value;}update(next);};
  const pointerDown=(e:React.PointerEvent,target:string)=>{
    if(history||staleDraft||e.button!==0){choose(target,e.shiftKey);return;}const ids=selected.includes(target)?selected:[target];
    const m=manifest.find((x:any)=>x.id===target);choose(target,e.shiftKey);if(!geometryReady&&!history&&!staleDraft){setGeometryNotice('当前草稿的几何尚未核对；请预览重绘后再拖动或缩放。');return;}if(!m?.interaction?.drag?.enabled||e.shiftKey||!canvas.current)return;
    e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY,ids,scope:currentGeometryKey,rect:canvas.current.getBoundingClientRect(),layers:structuredClone(layers),manifest};
  };
  const pointerUp=(e:React.PointerEvent)=>{
    const r=drag.current;drag.current=null;setMoving(null);if(!r||r.scope!==geometryContext.current.key)return;
    const dx=(e.clientX-r.x)/r.rect.width,dy=(e.clientY-r.y)/r.rect.height;
    if(Math.abs(dx)+Math.abs(dy)<.002)return;
    try{const changes=dragMembers(r.ids,r.manifest).map((m:any)=>r.corner?artistResize(m,r.layers,r.corner,dx,dy):artistDelta(m,r.layers,dx,dy)).filter(Boolean);patchPositions(changes as any,r.layers);}catch(error){report(error);}
  };
  const commit=()=>act(async()=>{
    if(history||staleDraft)throw new Error('固定历史或旧覆盖草稿不能覆盖新保存图。');
    clearTimeout(timer.current);const serial=++epoch.current,target=id,projectId=s.project.id,revision=view.figure.revision,originalDraft=s.figureDrafts[id],overlays=structuredClone(layers),before=structuredClone(view.figure.content.overlays||[]),sourcePin=visualSource(view.figure),previous=undoMatches(view)?undo:undefined,previousNumeric=numericSha(view.render);
    const current=()=>mounted.current&&active.current===target&&project.current===projectId&&epoch.current===serial;
    const location=()=>mounted.current&&active.current===target&&project.current===projectId&&fixedReadRevision.current===undefined;
    await previewQueue.current;if(!current())return;
    const x=await command('figure.visual.commit',{id:target,expected_revision:revision,overlays,request_key:requestId()});if(!current())return;
    if(x.figure?.id!==target||x.figure?.project_id!==projectId||x.figure.revision!==revision+1||x.render?.provenance?.numeric_preserved!==true||(previousNumeric&&previousNumeric!==numericSha(x.render)))throw new Error('采用回执缺少当前图身份或数值保持证据');
    if(s.figureDrafts[target]===originalDraft)delete s.figureDrafts[target];s.notify();await s.flush();if(!current())return;
    // The write response is decorated. Pin the authorized raw saved read instead.
    const saved=await read(target);if(!location()||!saved)return;
    if(!visualRef(saved)||saved.figure.revision!==x.figure.revision||visualRef(saved).sha256!==x.figure.canonical_source_sha256||!sameVisual(sourcePin,visualSource(saved.figure))||!sameVisual(overlays,saved.figure.content.overlays||[])||numericSha(saved.render)!==numericSha(x.render))throw new Error('采用后的保存版身份或完整来源发生变化；不登记可撤销操作。');
    const entry:VisualUndo|undefined=!sameVisual(before,overlays)?{version:1,project_id:projectId,id:target,before,after:overlays,source:sourcePin,after_ref:structuredClone(visualRef(saved)),numeric_sha:numericSha(saved.render)}:previous?{...previous,after_ref:structuredClone(visualRef(saved))}:undefined;
    if(entry)s.views['figure-visual-undo:'+target]={entry};else delete s.views['figure-visual-undo:'+target];s.notify();if(s.layout)await s.saveLayout(s.layout);if(!location())return;await refreshList();if(onSaved)await onSaved();
  });
  const undoVisual=()=>act(async()=>{
    if(!undoReady||!undo)throw new Error('请先处理未采用草稿；固定历史或已改变的保存版不能撤销此操作。');
    const entry=structuredClone(undo),target=id,projectId=s.project.id,serial=++epoch.current;
    clearTimeout(timer.current);++geometryAction.current;setGeometryNotice('');
    const current=()=>mounted.current&&active.current===target&&project.current===projectId&&fixedReadRevision.current===undefined&&epoch.current===serial&&!s.figureDrafts[target];
    await previewQueue.current;if(!current())return;
    const readSerial=++readSequence.current;
    const readCurrent=()=>mounted.current&&active.current===target&&project.current===projectId&&fixedReadRevision.current===undefined&&readSequence.current===readSerial;
    let fresh:any;
    try{
      fresh=await command('desk.figure.read',{project_id:projectId,id:target});if(!readCurrent()||!current())return;
      if(!undoMatches(fresh,entry))throw new Error('保存图已有后续修改或来源改变；当前图和撤销记录保留，请重新读取比较。');
    }catch(error){
      // A rejected fresh read must not leave the old canvas looking authorized.
      // Keep local inverse/drafts and retry only through the existing identity read.
      if(!readCurrent())return;
      setView(null);setPreview(null);setPreviewGeometry('');setMoving(null);setReadError({project:projectId,id:target,message:error instanceof Error?error.message:String(error)});
      throw error;
    }
    const x=await command('figure.visual.commit',{id:target,expected_revision:entry.after_ref.revision,overlays:structuredClone(entry.before),request_key:requestId()});if(!current())return;
    if(x.figure?.id!==target||x.figure?.project_id!==projectId||x.figure.revision!==entry.after_ref.revision+1||x.render?.provenance?.numeric_preserved!==true||(entry.numeric_sha&&entry.numeric_sha!==numericSha(x.render)))throw new Error('撤销回执缺少当前图身份或数值保持证据；请读取实际保存版核对。');
    const saved=await read(target);if(!saved||!mounted.current||active.current!==target||project.current!==projectId||fixedReadRevision.current!==undefined)return;
    if(!visualRef(saved)||visualRef(saved).sha256!==x.figure.canonical_source_sha256||saved.figure.revision!==x.figure.revision||!sameVisual(entry.source,visualSource(saved.figure))||!sameVisual(entry.before,saved.figure.content.overlays||[])||(entry.numeric_sha&&entry.numeric_sha!==numericSha(saved.render)))throw new Error('撤销后保存版与原完整覆盖或来源不符；原记录保留。');
    if(s.views['figure-visual-undo:'+target]?.entry===undo)delete s.views['figure-visual-undo:'+target];s.notify();if(s.layout)await s.saveLayout(s.layout);if(!mounted.current||active.current!==target||project.current!==projectId)return;await refreshList();if(onSaved)await onSaved();
  });
  const cancelVisual=()=>{if(actionBusy||history)return;clearTimeout(timer.current);++geometryAction.current;setGeometryNotice('');++epoch.current;delete s.figureDrafts[id];setLayers(view.figure.content.overlays||[]);setPreview(null);setPreviewGeometry('');setPreviewBusy(false);s.persisted=false;s.contentEpoch++;s.notify();s.schedule();};
  const alignArtists=(mode:Alignment)=>void withGeometry((actualManifest,snapshot,ids)=>{try{const members=dragMembers(ids,actualManifest).filter((m:any)=>validCanvasBox(m.bbox));const aligned=alignLayout(members.map((m:any)=>({id:m.id,box:m.bbox})),mode);patchPositions(aligned.map(item=>{const member=members.find((m:any)=>m.id===item.id);return artistDelta(member,snapshot,item.box[0]-member.bbox[0],item.box[1]-member.bbox[1]);}).filter(Boolean) as any,snapshot);}catch(error){report(error);}});
  const selectBox=(box:number[],add:boolean)=>{const ids=boxSelection(manifest.filter((m:any)=>m.type!=='figure'&&m.bbox?.length===4).map((m:any)=>({id:m.id,box:m.bbox})),box);selectTargets(old=>add?Array.from(new Set([...old,...ids])):ids);};
  const canvasSize=manifest.find((m:any)=>m.interaction?.drag?.source_canvas)?.interaction.drag.source_canvas||imageSize;
  const pointerMove=(e:React.PointerEvent)=>{const r=drag.current;if(!r||r.corner||r.scope!==geometryContext.current.key)return;setMoving({ids:dragMembers(r.ids).map((m:any)=>m.id),dx:e.clientX-r.x,dy:e.clientY-r.y});};
  const resizeMember=selected.length===1?manifest.find((m:any)=>m.id===selected[0]&&m.type==='axes'&&m.interaction?.drag?.enabled&&m.supported_properties?.includes('position')):null;
  const resizeStart=(e:React.PointerEvent<HTMLButtonElement>,corner:Corner)=>{if(!resizeMember||history||staleDraft||!geometryReady||!canvas.current)return;e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY,ids:selected,corner,scope:currentGeometryKey,rect:canvas.current.getBoundingClientRect(),layers:structuredClone(layers),manifest};};
  return <section ref={panelElement} className="figure-panel scientific-figure-panel figure-workarea" aria-label="科研图编辑" onScroll={event=>{const element=event.currentTarget;if(readableLocation&&element.clientHeight>0){const top=element.scrollTop,left=element.scrollLeft;if(locationMemory.panelScroll?.top!==top||locationMemory.panelScroll?.left!==left){locationMemory.panelScroll={top,left};locationMemory.changed?.();}}}}><div className="panel-tools"><strong>{embedded?'主图内源子图':'项目图'}</strong><select disabled={!!embedded} aria-label={embedded?'主图内源子图':'当前图'} value={id} onChange={e=>selectFigure(e.target.value)}><option value="">选择图</option>{list.map(x=><option key={x.id} value={x.id}>{x.title} · r{x.revision}</option>)}</select>{!embedded&&<><button onClick={()=>setNewFigure(!newFigure)}>登记绘图脚本</button><button onClick={()=>setNewMain(!newMain)}>新建主图</button></>}{changeExpanded&&<button aria-pressed={canvasExpanded} onClick={changeExpanded}>{canvasExpanded?'恢复工作桌':'放大图编辑'}</button>}</div>
    {history&&<div className="panel-tools" aria-label="固定图修订"><strong>固定历史 r{fixedRevision} · 只读</strong><span>保持稿内或来源固定引用；切换当前版本不会改旧 pin。</span><button onClick={()=>selectFigure(id)}>编辑当前版本</button></div>}
    {!embedded&&<details onToggle={event=>{if(event.currentTarget.open)setPurposeRefresh(value=>value+1);}}><summary>论文 / PPT 独立用途候选</summary><FigurePurposeCandidates projectId={s.project.id} figures={list} runs={runs} command={command} busy={busy} onCreated={async nextId=>{await refreshList();selectFigure(nextId);}}/></details>}
    {newMain&&<form className="figure-register" onSubmit={e=>{e.preventDefault();act(async()=>{const columns=slotCount===1?1:2,rows=Math.ceil(slotCount/columns);const slots=Array.from({length:slotCount},(_,i)=>({id:String.fromCharCode(65+i),label:String.fromCharCode(65+i),required:true,box:[(i%columns)/columns,Math.floor(i/columns)/rows,1/columns,1/rows],source:null}));const x=await command('desk.figure.composition.create',{project_id:s.project.id,title:mainTitle,slots,request_key:requestId()});setNewMain(false);await refreshList();selectFigure(x.figure.id);});}}><label>主图标题<input aria-label="主图标题" required value={mainTitle} onChange={e=>setMainTitle(e.target.value)}/></label><label>初始必需图位<select aria-label="主图图位数量" value={slotCount} onChange={e=>setSlotCount(Number(e.target.value))}>{[1,2,3,4,5,6].map(n=><option key={n} value={n}>{n}</option>)}</select></label><button disabled={busy}>建立主图定义</button></form>}
    {newFigure&&<form className="figure-register" onSubmit={e=>{e.preventDefault();act(async()=>{const x=await command('desk.figure.create',{project_id:s.project.id,title,script_sha:script,inputs:JSON.parse(inputs),parameters:JSON.parse(parameters),...(runId?{run_id:runId}:{}),request_key:requestId()});setNewFigure(false);await refreshList();selectFigure(x.figure.id);});}}><label>图标题<input aria-label="图标题" value={title} onChange={e=>setTitle(e.target.value)} required/></label><label>已上传脚本<select aria-label="绘图脚本" value={script} onChange={e=>setScript(e.target.value)} required><option value="">选择实际 Python 文件</option>{s.assets.filter(x=>x.filename.endsWith('.py')).map(x=><option key={x.sha} value={x.sha}>{x.filename}</option>)}</select></label><label>输入别名到资产 SHA<textarea aria-label="绘图输入映射" value={inputs} onChange={e=>setInputs(e.target.value)}/></label><label>绘图参数<textarea aria-label="绘图参数" value={parameters} onChange={e=>setParameters(e.target.value)}/></label><label>关联实际计算运行<select aria-label="新图关联运行" value={runId} onChange={e=>setRunId(e.target.value)}><option value="">没有已登记上游</option>{runs.map((r:any)=><option key={r.id} value={r.id}>{r.id}</option>)}</select></label><p>脚本以 build_figure(inputs, parameters) 返回 Matplotlib 图；登记只绑定实际输入，不运行。</p><button disabled={busy||!script}>登记图</button></form>}
    {!id?<p className="quiet">上传你的绘图脚本和实际数据，然后登记图。</p>:readError&&readError.project===s.project.id&&readError.id===id?<div role="alert"><p>无法读取所选图：{readError.message}</p><button onClick={()=>{void read().catch(report);}}>重试读取图</button><button onClick={()=>selectFigure('')}>关闭不可读图</button></div>:!view?<div className="loading">读取图与实际来源…</div>:view.definition?<MainFigure key={view.figure.id} viewMemory={locationMemory} onReview={onReviewFigure} initialSlotIds={initialId===view.figure.id&&initialRevision===view.figure.revision?initialSlotIds:undefined} readOnly={history} session={s} view={view} list={list} read={async()=>{await read();await refreshList();}} openPanel={selectFigure} report={report}/>:<><div className="panel-tools"><span className="path">{view.figure.title} · 保存版 r{view.figure.revision}{preview?' · 当前未采用预览':''}</span><button disabled={busy||history||staleDraft||!view.source.script_authorized} onClick={()=>runPreview(layers)}>预览重绘</button><button disabled={busy||history||staleDraft||!view.source.script_authorized} onClick={commit}>采用图形调整</button><button disabled={actionBusy||history} onClick={cancelVisual}>撤销未采用调整</button><button disabled={busy||!undoReady||!view.source.script_authorized} onClick={undoVisual}>撤销上次采用的图形调整</button><button aria-pressed={source} onClick={()=>setSource(!source)}>数据 / 代码 / 结果链</button></div>{staleDraft&&<p role="alert">保存图已有新修订，原覆盖草稿保留；旧基线不能覆盖新图。请比较当前来源后明确撤销草稿。</p>}
      {!view.source.script_authorized&&<div className="figure-authorize"><p>运行此脚本使用当前服务账号的本地权限；请先检查实际代码。</p><button disabled={busy||history} onClick={()=>act(async()=>{await command('object.authorize_code',{id,expected_revision:view.figure.revision,approved:true,reason:'Explicit owner grant for this registered plotting script and current supplied inputs'});await read();})}>允许执行此绘图脚本</button></div>}
      <div className="figure-editor-layout scientific-leaf-layout"><div className="figure-main"><div className="scientific-layout-tools" role="toolbar" aria-label="图中语义组工具">{[['axes','轴区组'],['legend','图例组'],['text','文字组'],['spine','轴线组']].map(([type,label])=><button key={type} onClick={()=>selectTargets(manifest.filter((m:any)=>type==='text'?['text','title','xlabel','ylabel'].includes(m.type):m.type===type).map((m:any)=>m.id))}>{label}</button>)}<button disabled={history||staleDraft||!selected.some(target=>manifest.find((m:any)=>m.id===target)?.supported_properties?.includes('visible'))} onClick={()=>apply('visible',false)}>隐藏所选元素</button></div><div className="scientific-layout-tools" role="toolbar" aria-label="叶图布局工具">{([['left','左对齐'],['right','右对齐'],['top','顶对齐'],['bottom','底对齐'],['horizontal-distribute','水平等距'],['vertical-distribute','垂直等距']] as [Alignment,string][]).map(([mode,label])=><button key={mode} disabled={history||staleDraft||dragMembers(selected).filter((m:any)=>validCanvasBox(m.bbox)).length<(mode.endsWith('distribute')?3:2)} onClick={()=>alignArtists(mode)}>{label}</button>)}</div>{(!geometryReady||geometryNotice)&&<p role="status" aria-label="图形几何状态">{geometryNotice||'当前草稿的元素几何尚未预览；可以继续修改属性，预览重绘后可拖动、缩放与对齐。'}</p>}<ScientificCanvas width={canvasSize[0]} height={canvasSize[1]} label="叶图布局" stageClass="figure-canvas" stageRef={canvas} viewMemory={locationMemory.canvas} scope={JSON.stringify([s.project.id,id,view.figure.revision])} disabled={history||staleDraft} onBoxSelect={selectBox}>{draw?.assets?.['figure.png']?<><img src={'/api/assets/'+draw.assets['figure.png'].sha} alt={view.figure.title} draggable={false} onLoad={event=>{const image=event.currentTarget;if(image.naturalWidth&&image.naturalHeight){locationMemory.imageSize=[image.naturalWidth,image.naturalHeight];setImageSize(old=>old[0]===image.naturalWidth&&old[1]===image.naturalHeight?old:[image.naturalWidth,image.naturalHeight]);}}}/>{manifest.filter((m:any)=>m.bbox?.length===4&&m.type!=='figure').sort((a:any,b:any)=>b.bbox[2]*b.bbox[3]-a.bbox[2]*a.bbox[3]).map((m:any)=><button key={m.id} data-canvas-object className={'artist-hit '+(selected.includes(m.id)?'chosen':'')} aria-label={'选择元素 '+m.id} aria-pressed={selected.includes(m.id)} title={m.label||m.id} style={{left:m.bbox[0]*100+'%',top:m.bbox[1]*100+'%',width:Math.max(m.bbox[2]*100,.8)+'%',height:Math.max(m.bbox[3]*100,.8)+'%',...(moving?.ids.includes(m.id)?{transform:`translate(${moving.dx/(canvas.current?.getBoundingClientRect().width||1)*canvasSize[0]}px,${moving.dy/(canvas.current?.getBoundingClientRect().height||1)*canvasSize[1]}px)`}:{})}} onPointerDown={e=>pointerDown(e,m.id)} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={()=>{drag.current=null;setMoving(null);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(m.id,e.shiftKey);}}}/>)}</>:<p className="quiet">没有此保存版的实际图。授权后重绘，预览不会修改保存版。</p>}{resizeMember?.bbox&&<CanvasHandles box={resizeMember.bbox} label="轴区" disabled={history||staleDraft||!geometryReady} onStart={resizeStart} onMove={()=>{}} onEnd={pointerUp} onCancel={()=>{drag.current=null;}}/>}</ScientificCanvas>
      {draw&&<div className="figure-downloads">{['figure.svg','figure.pdf','figure.png','numeric_values.json','source.json'].filter(name=>draw.assets?.[name]).map(name=><a key={name} href={'/api/assets/'+draw.assets[name].sha} target="_blank" rel="noreferrer">{name}</a>)}<small>数值保持：{String(draw.provenance?.numeric_preserved)} · {preview?'预览':'实际保存版输出'}</small></div>}</div>
      <aside className="figure-properties"><FigureOpinionControl session={s} view={view} selected={selected} busy={busy} readOnly={history} dirty={staleDraft||!!s.figureDrafts[id]||!sameVisual(layers,view.figure.content.overlays||[])} preview={!!preview} onReview={onReviewFigure}/><h3>元素与子图</h3><button disabled={busy||!axisSpines.length} onClick={()=>selectTargets(axisSpines.map((m:any)=>m.id))}>当前源图全部子图左／下轴线（{axisSpines.length}）</button><small>命中真实轴线；颜色条、数据曲线及轴范围保持。其他独立源图不在此组内。</small>{manifest.filter((m:any)=>m.type==='axes').map((m:any)=><button key={'group-'+m.id} onClick={()=>selectTargets(manifest.filter((x:any)=>x.id===m.id||x.owner_axes_id===m.id).map((x:any)=>x.id))}>子图元素组 {m.id}</button>)}<select aria-label="图形元素" multiple value={selected} onChange={e=>selectTargets(Array.from(e.target.selectedOptions).map(x=>x.value))}>{manifest.map((m:any)=><option key={m.id} value={m.id}>{m.type} · {m.label||m.id}</option>)}</select><p>Shift 点击可多选。属性只作用于所选组中支持该属性的元素。</p>
      {properties.map(property=>{const selection=figurePropertySelection(manifest,layers,selected,property);return <Property disabled={history||staleDraft} key={selected.join('|')+':'+property} name={property} value={selection.value} mixed={selection.mixed} targets={selection.targets} schema={propertyOwner(property)?.property_schema?.[property]} apply={v=>apply(property,v)}/>;})}
      {chosen?.interaction?.drag?.enabled===false&&<p>{chosen.interaction.drag.reason}</p>}</aside></div>
      {source&&<FigureSourcePanel onClose={()=>setSource(false)}><h3>当前保存版的实际输入与运行</h3>{view.source.inputs.map((x:any)=><p key={x.alias}>{x.alias} → <a href={'/api/assets/'+x.asset.sha} target="_blank" rel="noreferrer">{x.asset.filename}</a> · {x.asset.sha}</p>)}<p>参数：{JSON.stringify(view.source.parameters)}</p>{view.source.script&&<p>代码 SHA：{view.source.script.sha}</p>}<FigureScriptEditor key={s.project.id+':'+id} session={s} view={view} readOnly={history} busy={busy} visualDirty={staleDraft||!!s.figureDrafts[id]||!sameVisual(layers,view.figure.content.overlays||[])} onSavingChange={(value,owner)=>{if(!mounted.current||scriptContext.current.session!==s||active.current!==id||project.current!==s.project.id||fixedReadRevision.current!==undefined)return;if(value){scriptWriteOwner.current=owner;clearTimeout(timer.current);++epoch.current;++geometryAction.current;setPreview(null);setPreviewGeometry('');setPreviewBusy(false);setScriptBusy(true);}else if(scriptWriteOwner.current===owner){scriptWriteOwner.current=null;setScriptBusy(false);}}} onSaved={async result=>{const target=id,projectId=s.project.id;if(!mounted.current||scriptContext.current.session!==s||active.current!==target||project.current!==projectId||fixedReadRevision.current!==undefined)return;clearTimeout(timer.current);++epoch.current;++geometryAction.current;setScriptBusy(false);setPreview(null);setPreviewGeometry('');setPreviewBusy(false);if(result.saved){s.figureWriteRevisions[target]=Math.max(s.figureWriteRevisions[target]||0,result.figure.revision);lastFigureWrite.current={session:s,id:target,revision:result.figure.revision};s.notify();}setView(null);await read(target);if(mounted.current&&active.current===target&&project.current===projectId){await refreshList();if(onSaved)await onSaved();}}}/>{view.render&&<details open><summary>已采用运行 / 输出 / 数值身份</summary><pre>{JSON.stringify({provenance:view.render.provenance,execution:view.render.execution,runtime:view.render.runtime},null,2)}</pre></details>}{view.generation&&<details open><summary>实际数据 → 代码 → 中间结果 → 本图输入</summary><p>{view.generation.run_id} · {view.generation.plan_hash}</p><p>{view.generation.scope}</p>{view.generation.steps.map((n:any)=><details key={n.id}><summary>{n.id} · {n.role}</summary><pre>{n.script.code}</pre><pre>{JSON.stringify({parameters:n.parameters,config_keys:n.config_keys,inputs:n.inputs,io:n.io},null,2)}</pre>{n.outputs.map((o:any)=><p key={o.name}>{o.available?<a href={o.url} target="_blank" rel="noreferrer">{o.name}</a>:'缺失：'+o.name} · {o.asset_sha256}</p>)}</details>)}{view.generation.unknown_inputs.map((x:any)=><p key={x.figure_input}>{x.figure_input}：{x.reason}</p>)}</details>}<details><summary>采用另一次计算结果作为图输入</summary><label>已核验运行<select aria-label="图输入采用运行" value={runId} onChange={e=>setRunId(e.target.value)}><option value="">选择实际运行</option>{runs.map((r:any)=><option key={r.id} value={r.id}>{r.id}</option>)}</select></label>{runs.find((r:any)=>r.id===runId)&&<pre>{JSON.stringify(runs.find((r:any)=>r.id===runId).result.nodes,null,2)}</pre>}<label>图输入别名与实际输出SHA<textarea aria-label="新结果图输入映射" value={rebindInputs} onChange={e=>setRebindInputs(e.target.value)}/></label><p>保存新的输入引用，保留布局覆盖和旧修订；已有稿内采用图不会自动切换。需要重新授权并重绘。</p><button disabled={busy||history||!runId||JSON.stringify(layers)!==JSON.stringify(view.figure.content.overlays||[])} onClick={()=>act(async()=>{clearTimeout(timer.current);++epoch.current;await previewQueue.current;await command('desk.figure.rebind',{project_id:s.project.id,id,expected_revision:view.figure.revision,run_id:runId,inputs:JSON.parse(rebindInputs),request_key:requestId()});await read();await refreshList();})}>采用这些输入，保留旧图历史</button></details>{view.trace?.missing?.map((m:string,i:number)=><p key={i}>{m}</p>)}</FigureSourcePanel>}
      <div className="figure-attach"><label>稿件位置<select aria-label="图插入段落" value={anchor} onChange={e=>setAnchor(e.target.value)}>{s.paper.content.blocks.map((b:any,i:number)=><option key={b.id} value={b.id}>{i+1} · {b.text.slice(0,30)}</option>)}</select></label><label>稿内图注<input aria-label="稿内图注" value={caption} onChange={e=>setCaption(e.target.value)}/></label><button disabled={busy||history||s.paperDraft?.dirty||!view.render} onClick={()=>act(async()=>{await command('desk.figure.attach',{project_id:s.project.id,id,expected_revision:view.figure.revision,expected_manuscript_revision:s.paper.revision,after_block_id:anchor,caption,request_key:requestId()});await s.refreshPaper();if(!s.paperDraft?.dirty){s.resetPaperDraft();s.notify();await s.flush();}})}>将保存版图插入稿件</button></div>
    </>}
  </section>;
}

function Property({name,value,mixed,targets,schema,apply,disabled=false}:{disabled?:boolean,name:string,value:any,mixed:boolean,targets:string[],schema:any,apply:(v:any)=>void}){
  const serialized=mixed?'':typeof value==='string'?value:JSON.stringify(value)??'';
  const [raw,setRaw]=useState(serialized),[error,setError]=useState(''),[edited,setEdited]=useState(false);
  useEffect(()=>{setRaw(serialized);setError('');setEdited(false);},[serialized,mixed,JSON.stringify(value)]);
  const submit=()=>{if(!edited||(!mixed&&raw===serialized))return;try{apply(schema?.type==='string'||typeof value==='string'?raw:JSON.parse(raw));setError('');}catch{setError('请输入有效的属性值；数组或数值使用 JSON。');}};
  return <label className="figure-property">{name}{mixed&&<small>混合值；输入后仅改变支持此属性的所选成员。</small>}<small>命中成员：{targets.join('、')}</small><input disabled={disabled} aria-label={'图形属性 '+name} aria-invalid={!!error} value={raw} placeholder={mixed?'混合值':undefined} onChange={e=>{setRaw(e.target.value);setEdited(true);}} onBlur={submit} onKeyDown={e=>{if(e.key==='Enter')submit();}}/>{error&&<small role="alert">{error}</small>}</label>;
}
