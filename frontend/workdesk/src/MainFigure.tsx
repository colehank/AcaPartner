import {MainFigureOpinionControl,type MainFigureOpinionAnchor} from './MainFigureOpinionControl';
import {FigureSourcePanel} from './FigureSourcePanel';
import {useEffect,useRef,useState} from 'react';
import {ReactFlow,Background,Controls,Handle,Position,NodeProps,Node,Connection} from '@xyflow/react';
import {command,requestId,readTask} from './api';
import {Session} from './session';
import {FigureBody} from './FigurePanel';
import {ScientificCanvas,CanvasHandles} from './ScientificCanvas';
import type {FigureViewMemory} from './figureViewMemory';
import {alignLayout,boxSelection,layoutBounds,pointerLayoutDelta,resizeLayout,type Alignment,type Corner} from './figureCanvasGeometry';

type FigureNode=Node<{label:string,output?:boolean,input?:boolean},'figure'>;
function FigureNodeBody({data}:NodeProps<FigureNode>){return <div className="composition-node"><strong>{data.label}</strong>{data.output&&<Handle type="source" position={Position.Right} id="panel"/>}{data.input&&<Handle type="target" position={Position.Left} id="panel"/>}</div>;}
const nodeTypes={figure:FigureNodeBody};
const MIME='application/x-research-partner-panel';

export type FigureCompositionProvider={id:string,route:string,model:string,supports_resume:boolean,budget:{max_model_calls:number,timeout_seconds:number}};
export function figureCompositionProviders(records:unknown,runtimeRunning:boolean):FigureCompositionProvider[]{
  if(!runtimeRunning||!Array.isArray(records))return [];
  return records.flatMap(raw=>{
    if(!raw||typeof raw!=='object'||typeof raw.id!=='string'||!raw.id||typeof raw.route!=='string'||!raw.route||raw.available!==true||raw.authorized!==true)return [];
    const supports=raw.supports_figure_composition===true||(raw.route==='codex'&&!Object.hasOwn(raw,'supports_figure_composition'));
    if(!supports)return [];
    const supplied=Object.hasOwn(raw,'figure_composition_budget');
    const budget=supplied?raw.figure_composition_budget:raw.route==='codex'?{max_model_calls:1,timeout_seconds:180}:null;
    if(!budget||!Number.isSafeInteger(budget.max_model_calls)||budget.max_model_calls<=0||typeof budget.timeout_seconds!=='number'||!Number.isFinite(budget.timeout_seconds)||budget.timeout_seconds<=0||budget.timeout_seconds>600)return [];
    return [{id:raw.id,route:raw.route,model:typeof raw.model==='string'&&raw.model?raw.model:'模型未登记',supports_resume:raw.supports_resume===true||(raw.route==='codex'&&!Object.hasOwn(raw,'supports_resume')),budget:{max_model_calls:budget.max_model_calls,timeout_seconds:budget.timeout_seconds}}];
  });
}
export function figureCompositionSubmission(projectId:string,view:any,provider:FigureCompositionProvider){
  if(!provider||!view?.figure||view.figure.project_id!==projectId||view.required_missing?.length||!view.definition?.slots?.length)throw new Error('主图提交需要当前项目的完整保存定义和明确支持的提供者');
  return {project_id:projectId,title:view.figure.title+' · Agent候选',width:view.definition.width,height:view.definition.height,
    slots:view.definition.slots.map((slot:any)=>({...slot,source:slot.source?{id:slot.source.id,revision:slot.source.revision}:null})),
    provider_id:provider.id,budget:{...provider.budget}};
}

type SlotLayout={id:string,box:number[]};
export type MainFigureLayoutDraft={base:number,sha:string}&({slot:string,box:number[],slots?:never}|{slots:SlotLayout[],slot?:never,box?:never});
export type CompositionUndo={project_id:string,id:string,slot_id?:string,operation:'layout'|'layout_group'|'bind'|'detach',fields:{box?:number[],slots?:SlotLayout[],source?:{id:string,revision:number}},before_sha256:string,after_sha256:string,after_revision:number};
const validBox=(box:unknown):box is number[]=>Array.isArray(box)&&box.length===4&&box.every(n=>typeof n==='number'&&Number.isFinite(n))&&box[0]>=0&&box[1]>=0&&box[2]>0&&box[3]>0&&box[0]+box[2]<=1&&box[1]+box[3]<=1;
const stableValue=(value:any):any=>Array.isArray(value)?value.map(stableValue):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,stableValue(value[key])])):value;
const sameValue=(left:any,right:any)=>JSON.stringify(stableValue(left))===JSON.stringify(stableValue(right));
function draftSlots(draft:MainFigureLayoutDraft):SlotLayout[]{return draft.slots||[{id:draft.slot!,box:draft.box!}];}
export function compositionUndoFields(projectId:string,view:any,entry:CompositionUndo){
  if(!entry||entry.project_id!==projectId||entry.id!==view?.figure?.id||view.figure.project_id!==projectId||entry.after_revision!==view.figure.revision||entry.after_sha256!==view.definition_sha256||!['layout','layout_group','bind','detach'].includes(entry.operation)||!view.definition?.slots?.length||(entry.operation!=='layout_group'&&!view.definition.slots.some((slot:any)=>slot.id===entry.slot_id)))throw new Error('主图已有后续修改；保留当前图和撤销记录，不能覆盖新修改。');
  const hex=(value:unknown)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
  if(!hex(entry.before_sha256)||!hex(entry.after_sha256)||!Number.isSafeInteger(entry.after_revision)||entry.after_revision<1)throw new Error('撤销记录的固定身份无效。');
  const fields=entry.fields;
  if(!fields||typeof fields!=='object'||Array.isArray(fields))throw new Error('撤销记录无有效操作。');
  if(entry.operation==='layout'&&(Object.keys(fields).join(',')!=='box'||!Array.isArray(fields.box)||fields.box.length!==4||fields.box.some(n=>typeof n!=='number'||!Number.isFinite(n))))throw new Error('撤销布局记录无效。');
  if(entry.operation==='layout'){const [x,y,w,h]=fields.box!;if(x<0||y<0||w<=0||h<=0||x+w>1||y+h>1)throw new Error('撤销布局超出主图；保留原记录并重新核对。');}
  if(entry.operation==='bind'&&(Object.keys(fields).join(',')!=='source'||!fields.source||Object.keys(fields.source).sort().join(',')!=='id,revision'||typeof fields.source.id!=='string'||!fields.source.id||!Number.isSafeInteger(fields.source.revision)||fields.source.revision<1))throw new Error('撤销来源记录无效。');
  if(entry.operation==='detach'&&Object.keys(fields).length)throw new Error('撤销空图位记录无效。');
  if(entry.operation==='layout_group'){
    const patches=fields.slots;
    if(entry.slot_id!==undefined||Object.keys(fields).join(',')!=='slots'||!Array.isArray(patches)||patches.length<2||patches.length>24||new Set(patches.map(p=>p?.id)).size!==patches.length||patches.some(p=>!p||Object.keys(p).sort().join(',')!=='box,id'||typeof p.id!=='string'||!view.definition.slots.some((slot:any)=>slot.id===p.id)||!validBox(p.box)))throw new Error('撤销布局组记录无效；保留实际图和完整组。');
  }
  return {project_id:projectId,id:entry.id,...(entry.operation==='layout_group'?{}:{slot_id:entry.slot_id}),expected_revision:entry.after_revision,expected_definition_sha256:entry.after_sha256,...fields,restore_definition_sha256:entry.before_sha256};
}

export function MainFigure({session:s,view,list,read,openPanel,report,readOnly=false,viewMemory,onReview,initialSlotIds}:{session:Session,view:any,list:any[],read:()=>Promise<void>,openPanel:(id:string,revision?:number)=>void,report:(e:unknown)=>void,readOnly?:boolean,viewMemory?:FigureViewMemory,onReview?:(anchor:MainFigureOpinionAnchor)=>void,initialSlotIds?:string[]}){
  // Root owns the compatible persisted union and server validation. This local
  // view type supports old single-slot drafts and the explicit group contract.
  const layoutDrafts=s.compositionDrafts as Record<string,MainFigureLayoutDraft>;
  const id=view.figure.id,slots=view.definition.slots,panels=list.filter(x=>!x.composition),draft=readOnly?undefined:layoutDrafts[id];
  const validSlot=(id:string)=>slots.some((slot:any)=>slot.id===id);
  // Explicit opinion navigation is scoped by FigureBody to this exact saved view.
  const requested=initialSlotIds===undefined?undefined:(initialSlotIds.length>0&&new Set(initialSlotIds).size===initialSlotIds.length&&initialSlotIds.every(validSlot)?initialSlotIds:[]);
  const [selected,setSelected]=useState(()=>requested!==undefined?requested[0]||'':viewMemory?.active&&validSlot(viewMemory.active)?viewMemory.active:draft?.slots?.[0]?.id||draft?.slot||slots[0].id),[source,setSource]=useState(''),[busy,setBusy]=useState(false),[showSource,setShowSource]=useState(false),[showFlow,setShowFlow]=useState(false),[caption,setCaption]=useState(''),[anchor,setAnchor]=useState(s.paper.content.blocks[0]?.id||'');
  const [layoutSelection,setLayoutSelection]=useState<string[]>(()=>requested!==undefined?[...requested]:viewMemory?.selected?.filter(validSlot)||draft?.slots?.map(slot=>slot.id)||[draft?.slot||slots[0].id]);
  useEffect(()=>{if(viewMemory){viewMemory.selected=layoutSelection.filter(validSlot);viewMemory.active=validSlot(selected)?selected:undefined;}},[viewMemory,layoutSelection,selected,slots]);
  const [groupOffset,setGroupOffset]=useState(['0','0']);
  const layoutScope=useRef('');layoutScope.current=JSON.stringify([s.project.id,id,view.figure.revision,view.definition_sha256]);
  const selectedLayout=slots.filter((slot:any)=>layoutSelection.includes(slot.id));
  const [egress,setEgress]=useState<any>(null),[egressGranted,setEgressGranted]=useState(false);
  const [providerMetadata,setProviderMetadata]=useState<any[]>([]),[providers,setProviders]=useState<FigureCompositionProvider[]>([]),[provider,setProvider]=useState(''),[task,setTask]=useState<any>(null),[taskId,setTaskId]=useState(s.views['composition-task:'+id]?.task_id||view.figure.metadata?.origin_task_id||'');
  const [inlineSlot,setInlineSlot]=useState('');
  const [occurrence,setOccurrence]=useState(''),[attachNotice,setAttachNotice]=useState<{paperId:string,revision:number,text:string}|null>(null);
  const attachContext=useRef({session:s,view,readOnly});attachContext.current={session:s,view,readOnly};
  useEffect(()=>{setOccurrence('');},[s.project.id,id,view.figure.revision,readOnly,s.paper.id,s.paper.revision]);
  useEffect(()=>{setAttachNotice(null);},[s.project.id,id,view.figure.revision,readOnly,s.paper.id]);
  const inlinePanel=view.panels.find((panel:any)=>panel.slot_id===inlineSlot);
  const chosenPanel=view.panels.find((panel:any)=>panel.slot_id===selected);
  const canvas=useRef<HTMLDivElement>(null),drag=useRef<any>(null),resize=useRef<any>(null);
  const undoKey='composition-undo:'+id,undoHistory:CompositionUndo[]=Array.isArray(s.views[undoKey]?.entries)?s.views[undoKey].entries:[];
  const chosen=slots.find((x:any)=>x.id===selected)||slots[0],key='composition:'+id;
  const actionEpoch=useRef(0);
  useEffect(()=>{++actionEpoch.current;drag.current=null;resize.current=null;setBusy(false);},[s.project.id,id,view.figure.revision,view.definition_sha256]);
  const act=async(fn:()=>Promise<void>)=>{if(busy)return;if(readOnly){report(new Error('固定历史图只读，请明确切换当前版本后编辑。'));return;}const serial=++actionEpoch.current,savedScope=layoutScope.current;setBusy(true);const current=()=>mounted.current&&serial===actionEpoch.current&&savedScope===layoutScope.current;try{await fn();}catch(e){if(current())report(e);}finally{if(current())setBusy(false);}};
  useEffect(()=>{
    let dead=false;setProviderMetadata([]);setProviders([]);setProvider('');
    const readPublic=async(path:string)=>{const response=await fetch(path,{cache:'no-store'}),value=await response.json();if(!response.ok)throw new Error(value.error||'提供者元数据不可读取');return value;};
    Promise.all([readPublic('/api/state'),readPublic('/api/health')]).then(([state,health])=>{
      if(dead)return;setProviderMetadata(Array.isArray(state.providers)?state.providers:[]);const choices=figureCompositionProviders(state.providers,health.runtime?.running===true);setProviders(choices);setProvider(choices[0]?.id||'');
    }).catch(error=>{if(!dead)report(error);});
    return()=>{dead=true;};
  },[s.project.id]);
  useEffect(()=>{
    if(!taskId)return;let dead=false;let timer:ReturnType<typeof setTimeout>|undefined;const until=Date.now()+240000;
    const inspect=async()=>{try{const value=await readTask(taskId);if(dead)return;setTask(value);if(['queued','running'].includes(value.status)&&Date.now()<until)timer=setTimeout(inspect,700);}catch(error){if(!dead)report(error);}};
    void inspect();return()=>{dead=true;clearTimeout(timer);};
  },[taskId,s.project.id]);
  const selectedProvider=providers.find(p=>p.id===provider);
  const stopped=['paused','waiting_input'].includes(task?.status);
  const originalProvider=providerMetadata.find(p=>p.id===task?.payload?.provider_id);
  const freshOnlyTask=stopped&&originalProvider?.supports_resume===false;
  const pendingTaskRead=!!taskId&&task?.id!==taskId;
  const scope=JSON.stringify([s.project.id,id,view.definition_sha256,provider,selectedProvider?.budget,!!draft,freshOnlyTask,pendingTaskRead]);
  const activeScope=useRef(scope);activeScope.current=scope;
  const mounted=useRef(false);useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{setEgress(null);setEgressGranted(false);},[scope]);
  const selectProvider=(value:string)=>{activeScope.current='';setEgress(null);setEgressGranted(false);setProvider(value);};
  const previewEgress=()=>act(async()=>{
    if(freshOnlyTask||pendingTaskRead)throw new Error('当前原生协议不能续接或重发此原任务');const savedScope=activeScope.current,packet=await command('desk.figure.composition.preview',egressFields());
    if(!mounted.current||savedScope!==activeScope.current)return;
    if(packet.project_id!==s.project.id||packet.provider_id!==provider)throw new Error('外发预览与当前项目或提供者不符');
    setEgress(packet);setEgressGranted(false);
  });
  const authorizeEgress=()=>act(async()=>{
    if(freshOnlyTask||pendingTaskRead)throw new Error('当前原生协议不能续接或重发此原任务');const savedScope=activeScope.current;await command('desk.figure.composition.authorize',{...egressFields(),preview_sha256:egress.sha256,approved:true});
    if(mounted.current&&savedScope===activeScope.current)setEgressGranted(true);
  });
  const currentRefs=slots.filter((slot:any)=>slot.source).map((slot:any)=>({id:slot.source.id,revision:slot.source.revision}));
  const keyRefs=(refs:any[])=>Array.from(new Set(refs.map(r=>r.id+'@'+r.revision))).sort().join('|');
  const sameTaskSources=!!task?.payload?.context?.figure_composition&&keyRefs(currentRefs)===keyRefs(task.payload.context.figure_composition.fixed_sources);
  const egressFields=()=>({project_id:s.project.id,provider_id:provider,sources:currentRefs,...(stopped&&sameTaskSources?{task_id:task.id}:{})});
  const retainUndo=async(operation:string,slotId:string,before:any,beforeSha:string,result:any)=>{
    if(result.figure?.id!==id||result.figure?.project_id!==s.project.id||!Number.isSafeInteger(result.figure.revision)||typeof result.definition_sha256!=='string')throw new Error('保存回执缺少当前主图身份；未推断撤销记录。');
    const inverse=operation==='layout'?{operation:'layout' as const,fields:{box:structuredClone(before.box)}}:before.source?{operation:'bind' as const,fields:{source:{id:before.source.id,revision:before.source.revision}}}:{operation:'detach' as const,fields:{}};
    const entry:CompositionUndo={project_id:s.project.id,id,slot_id:slotId,...inverse,before_sha256:beforeSha,after_revision:result.figure.revision,after_sha256:result.definition_sha256};
    const previous=undoHistory.at(-1),continuous=!previous||previous.after_sha256===beforeSha;
    s.views[undoKey]={entries:[...(continuous?undoHistory:[]),entry].slice(-20)};s.notify();if(s.layout)await s.saveLayout(s.layout);
  };
  const mutate=async(operation:string,slot:string,fields:any)=>{
    const before=slots.find((item:any)=>item.id===slot);if(!before)throw new Error('当前图位不存在。');
    const savedScope=layoutScope.current;
    const result=await command('desk.figure.composition.'+operation,{project_id:s.project.id,id,expected_revision:view.figure.revision,expected_definition_sha256:view.definition_sha256,slot_id:slot,...fields,request_key:requestId()});
    if(!mounted.current||savedScope!==layoutScope.current)return null;
    await retainUndo(operation,slot,before,view.definition_sha256,result);return result;
  };
  const undoSaved=()=>act(async()=>{
    if(draft)throw new Error('请先保存或撤销当前布局草稿。');const entry=undoHistory.at(-1);if(!entry)throw new Error('没有可撤销的本地保存操作。');
    const savedScope=layoutScope.current;
    const fields=compositionUndoFields(s.project.id,view,entry),result=await command('desk.figure.composition.'+entry.operation,{...fields,request_key:requestId()});
    if(!mounted.current||savedScope!==layoutScope.current)return;
    if(result.figure?.id!==id||result.figure?.project_id!==s.project.id||result.definition_sha256!==entry.before_sha256)throw new Error('撤销回执未匹配原保存定义；保留实际历史与记录，重新核对当前图。');
    const remaining=structuredClone(undoHistory.slice(0,-1)),next=remaining.at(-1);
    if(next?.after_sha256===entry.before_sha256)next.after_revision=result.figure.revision;
    s.views[undoKey]={entries:remaining};s.notify();if(s.layout)await s.saveLayout(s.layout);await read();
  });
  const bind=async(slot:string,panel:any)=>{
    if(draft)throw new Error('请先保存或撤销主图布局草稿。');
    if(!panels.some(p=>p.id===panel.id&&p.revision===panel.revision))throw new Error('请选择当前项目目录中的准确子图修订。');
    if(await mutate('bind',slot,{source:{id:panel.id,revision:panel.revision}}))await read();
  };
  const updateDraft=(slot:string,box:number[])=>{
    if(!validBox(box))throw new Error('图位需要主图内的有效位置和正宽高。');
    const previous=layoutDrafts[id];
    if(previous&&previous.slot!==slot)throw new Error('请先保存或撤销当前图位布局。');
    layoutDrafts[id]={base:previous?.base??view.figure.revision,sha:previous?.sha??view.definition_sha256,slot,box};s.persisted=false;s.contentEpoch++;s.notify();s.schedule();
  };
  const updateGroupDraft=(patches:SlotLayout[])=>{
    const previous=layoutDrafts[id];
    if(view.figure.project_id!==s.project.id||patches.length<2||patches.length>24||patches.some(p=>!validBox(p.box)||!slots.some((slot:any)=>slot.id===p.id))||new Set(patches.map(p=>p.id)).size!==patches.length)throw new Error('布局组需要当前主图中的2至24个唯一图位与有效边界。');
    if(previous&&(!previous.slots||!sameValue(previous.slots.map(p=>p.id).sort(),patches.map(p=>p.id).sort())))throw new Error('请先保存或撤销当前布局草稿，再改变布局组成员。');
    if(patches.every(p=>sameValue(p.box,previous?.slots?.find(old=>old.id===p.id)?.box||slots.find((slot:any)=>slot.id===p.id).box)))return;
    layoutDrafts[id]={base:previous?.base??view.figure.revision,sha:previous?.sha??view.definition_sha256,slots:structuredClone(patches)};
    s.persisted=false;s.contentEpoch++;s.notify();s.schedule();
  };
  const chooseLayout=(target:string,add=false,forceSingle=false)=>{
    if(busy)return;
    const next=add?(layoutSelection.includes(target)?layoutSelection.filter(id=>id!==target):[...layoutSelection,target]):!forceSingle&&layoutSelection.length>1&&layoutSelection.includes(target)?layoutSelection:[target];
    if(!next.length)return;
    if(draft&&!sameValue(draftSlots(draft).map(p=>p.id).sort(),next.slice().sort())){report(new Error('先保存或撤销布局草稿，再改变所选图位。'));return;}
    setLayoutSelection(next);setSelected(next.includes(target)?target:next[next.length-1]);
  };
  const boxesFor=(members:any[]):SlotLayout[]=>members.map(slot=>({id:slot.id,box:structuredClone(draft?draftSlots(draft).find(p=>p.id===slot.id)?.box||slot.box:slot.box)}));
  const translateBoxes=(boxes:SlotLayout[],dx:number,dy:number)=>{
    if(!Number.isFinite(dx)||!Number.isFinite(dy)||boxes.some(p=>!validBox(p.box)))throw new Error('布局组位移需要有限数值及有效保存位置。');
    const x=Math.max(Math.max(...boxes.map(p=>-p.box[0])),Math.min(dx,Math.min(...boxes.map(p=>1-p.box[0]-p.box[2]))));
    const y=Math.max(Math.max(...boxes.map(p=>-p.box[1])),Math.min(dy,Math.min(...boxes.map(p=>1-p.box[1]-p.box[3]))));
    return boxes.map(p=>({id:p.id,box:[p.box[0]+x,p.box[1]+y,p.box[2],p.box[3]]}));
  };
  const translateSelection=()=>{
    try{if(busy||selectedLayout.length<2)return;if(groupOffset.some(raw=>!raw.trim()))throw new Error('请填写布局组水平和垂直位移。');updateGroupDraft(translateBoxes(boxesFor(selectedLayout),Number(groupOffset[0]),Number(groupOffset[1])));}
    catch(error){report(error);}
  };
  const retainGroupUndo=async(before:SlotLayout[],result:any)=>{
    const expected=slots.map((slot:any)=>({...slot,box:draft?.slots?.find(p=>p.id===slot.id)?.box||slot.box}));
    const unchanged=sameValue(expected,slots),matched=result.figure?.id===id&&result.figure.project_id===s.project.id&&typeof result.definition_sha256==='string'&&/^[a-f0-9]{64}$/.test(result.definition_sha256)&&sameValue(result.figure.content?.slots,expected);
    if(matched&&unchanged&&result.figure.revision===view.figure.revision&&result.definition_sha256===view.definition_sha256)return;
    if(!matched||unchanged||result.figure.revision!==view.figure.revision+1)throw new Error('布局组保存回执未匹配全部目标及未选图位；保留草稿并重新读取，不推断部分成功。');
    const entry:CompositionUndo={project_id:s.project.id,id,operation:'layout_group',fields:{slots:structuredClone(before)},before_sha256:view.definition_sha256,after_sha256:result.definition_sha256,after_revision:result.figure.revision};
    const previous=undoHistory.at(-1),continuous=!previous||previous.after_sha256===view.definition_sha256;
    s.views[undoKey]={entries:[...(continuous?undoHistory:[]),entry].slice(-20)};s.notify();if(s.layout)await s.saveLayout(s.layout);
  };
  const saveDraft=()=>act(async()=>{
    const d=layoutDrafts[id];if(!d)return;const savedScope=layoutScope.current;
    const patches=draftSlots(d),before=patches.map(p=>slots.find((slot:any)=>slot.id===p.id));
    if(view.figure.project_id!==s.project.id||before.some(slot=>!slot)||d.base!==view.figure.revision||d.sha!==view.definition_sha256)throw new Error('保存版已有后续修改；保留布局草稿并核对当前图。');
    if(d.slots){
      const result=await command('desk.figure.composition.layout_group',{project_id:s.project.id,id,expected_revision:d.base,expected_definition_sha256:d.sha,slots:structuredClone(d.slots),request_key:requestId()});
      if(!mounted.current||savedScope!==layoutScope.current)return;
      await retainGroupUndo(before.map(slot=>({id:slot.id,box:slot.box})),result);
    }else{
      const result=await command('desk.figure.composition.layout',{project_id:s.project.id,id,expected_revision:d.base,expected_definition_sha256:d.sha,slot_id:d.slot,box:d.box,request_key:requestId()});
      if(!mounted.current||savedScope!==layoutScope.current)return;
      await retainUndo('layout',d.slot,before[0],d.sha,result);
    }
    if(!mounted.current||savedScope!==layoutScope.current)return;
    if(layoutDrafts[id]===d)delete layoutDrafts[id];s.notify();await s.flush();if(mounted.current&&savedScope===layoutScope.current)await read();
  });
  const cancelDraft=()=>{delete layoutDrafts[id];s.persisted=false;s.contentEpoch++;s.notify();s.schedule();};
  const startDrag=(e:React.PointerEvent<HTMLDivElement>,slot:any)=>{
    if(busy||e.button!==0)return;
    // Native text selection/drag must not take over a canvas gesture after a
    // Shift selection. Keep keyboard focus without scrolling the work area.
    e.preventDefault();e.currentTarget.focus({preventScroll:true});
    if(readOnly||e.shiftKey)return;
    const members=layoutSelection.includes(slot.id)&&selectedLayout.length>1?selectedLayout:[slot];
    if(draft&&!sameValue(draftSlots(draft).map(p=>p.id).sort(),members.map((p:any)=>p.id).sort())){report(new Error('先保存或撤销当前布局草稿。'));return;}
    const rect=canvas.current!.getBoundingClientRect();setSelected(slot.id);setLayoutSelection(members.map((p:any)=>p.id));
    drag.current={slot:slot.id,x:e.clientX,y:e.clientY,rect,boxes:boxesFor(members),group:members.length>1,scope:layoutScope.current};e.currentTarget.setPointerCapture(e.pointerId);
  };
  const moveDrag=(e:React.PointerEvent)=>{const d=drag.current;if(!d||d.scope!==layoutScope.current)return;if(e.clientX!==d.x||e.clientY!==d.y){try{const boxes=translateBoxes(d.boxes,pointerLayoutDelta(e.clientX-d.x,d.rect.width),pointerLayoutDelta(e.clientY-d.y,d.rect.height));if(d.group)updateGroupDraft(boxes);else updateDraft(d.slot,boxes[0].box);}catch(error){drag.current=null;report(error);}}};
  const applyLayout=(patches:SlotLayout[])=>{if(patches.length>1)updateGroupDraft(patches);else if(patches.length)updateDraft(patches[0].id,patches[0].box);};
  const alignSelection=(mode:Alignment)=>{try{if(readOnly||busy)return;applyLayout(alignLayout(boxesFor(selectedLayout),mode));}catch(error){report(error);}};
  const selectBox=(box:number[],add:boolean)=>{
    const hits=boxSelection(boxesFor(slots),box),next=add?Array.from(new Set([...layoutSelection,...hits])):hits;
    if(draft&&!sameValue(draftSlots(draft).map(p=>p.id).sort(),next.slice().sort())){report(new Error('先保存或撤销布局草稿，再改变所选图位。'));return;}
    setLayoutSelection(next);if(next.length)setSelected(next[next.length-1]);
  };
  const resizeStart=(e:React.PointerEvent<HTMLButtonElement>,corner:Corner)=>{
    if(readOnly||busy||!selectedLayout.length||e.button!==0||!canvas.current)return;
    e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);
    resize.current={corner,x:e.clientX,y:e.clientY,rect:canvas.current.getBoundingClientRect(),boxes:boxesFor(selectedLayout),scope:layoutScope.current};
  };
  const resizeMove=(e:React.PointerEvent<HTMLButtonElement>)=>{const d=resize.current;if(!d||d.scope!==layoutScope.current)return;try{applyLayout(resizeLayout(d.boxes,d.corner,pointerLayoutDelta(e.clientX-d.x,d.rect.width),pointerLayoutDelta(e.clientY-d.y,d.rect.height)));}catch(error){resize.current=null;report(error);}};
  const occurrences=(s.paper.content.components||[]).map((ref:any,index:number)=>({ref,index})).filter(({ref}:any)=>(ref.id||ref.object_id)===id);
  const targetOccurrence=occurrence===''?undefined:occurrences.find(({index}:any)=>index===Number(occurrence));
  const validOccurrence=(ref:any)=>ref&&Number.isSafeInteger(ref.revision)&&ref.revision>0&&(ref.sha256==null||typeof ref.sha256==='string'&&/^[a-f0-9]{64}$/.test(ref.sha256))&&
    (ref.id||ref.object_id)===id&&['id','object_id'].every(key=>!(key in ref)||ref[key]===id);
  const renderSourceSha=view.render?.provenance?.source_sha256;
  const renderReady=view.render?.status==='generated'&&/^[a-f0-9]{64}$/.test(renderSourceSha||'')&&/^[a-f0-9]{64}$/.test(view.render?.assets?.['canvas.svg']?.sha||'');
  const attachBlocked=busy||readOnly||!renderReady||view.required_missing.length>0||!!layoutDrafts[id]||
    !s.paperDraft||s.paperDraft.dirty||s.paperDraft.base!==s.paper.revision||view.figure.project_id!==s.project.id||s.paper.project_id!==s.project.id;
  const attachSaved=async(replacement?:{index:number,ref:any})=>{
    if(attachBlocked)throw new Error('请先保存当前主图和稿件，完成主图重绘后再更新稿内引用。');
    if(replacement&&(!validOccurrence(replacement.ref)||replacement.ref.revision>=view.figure.revision))throw new Error('此处稿内图没有可更新的准确旧版本引用；请先核对保存来源。');
    const projectId=s.project.id,sentView=view,sentPaper=s.paper,sentDraft=s.paperDraft!,sentDraftValue=structuredClone(sentDraft);
    const paperRead=s.paperReadSequence,contentEpoch=s.contentEpoch,serial=actionEpoch.current,savedScope=layoutScope.current;
    const contextCurrent=()=>mounted.current&&attachContext.current.session===s&&attachContext.current.view===sentView&&!attachContext.current.readOnly&&
      serial===actionEpoch.current&&savedScope===layoutScope.current&&s.project.id===projectId&&!s.compositionDrafts[id]&&s.contentEpoch===contentEpoch;
    const current=()=>contextCurrent()&&s.paper===sentPaper&&s.paper.id===sentPaper.id&&s.paper.revision===sentPaper.revision&&
      s.paperReadSequence===paperRead&&s.paperDraft===sentDraft&&!s.paperDraft.dirty&&sameValue(s.paperDraft,sentDraftValue);
    const index=replacement?.index??(sentPaper.content.components||[]).length;
    const expectedRef=replacement?structuredClone(replacement.ref):undefined;
    let result:any;
    try{
      result=await command('desk.figure.attach',{project_id:projectId,id,expected_revision:sentView.figure.revision,
        expected_manuscript_revision:sentPaper.revision,request_key:requestId(),
        ...(replacement?{replace_component:{index,expected_ref:expectedRef}}:{after_block_id:anchor,caption})});
    }catch(error){if(current())throw error;return;}
    // A completed server write is a receipt, not permission to overwrite later
    // input, a newer read, another project, or another canvas location.
    if(!current())return;
    const component=replacement?{...expectedRef,revision:sentView.figure.revision,sha256:renderSourceSha}:
      {id,revision:sentView.figure.revision,sha256:renderSourceSha,after_block_id:anchor,caption};
    const content=structuredClone(sentPaper.content);content.components=content.components||[];
    if(replacement)content.components[index]=component;else content.components.push(component);
    if(result.executed!==false||result.manuscript?.id!==sentPaper.id||result.manuscript?.project_id!==projectId||
      result.manuscript.revision!==sentPaper.revision+1||result.component_index!==index||
      !sameValue(result.component_ref,component)||!sameValue(result.manuscript.content,content))
      throw new Error('稿内图更新回执与所选位置、保存版本或完整原文不符；当前稿件和草稿保留，请重新读取核对。');
    // Keep Session's existing latest-read and dirty-draft protections. Never
    // reconstruct a minimal manuscript draft from an attach receipt.
    await s.refreshPaper();
    if(!contextCurrent()||s.paper.id!==sentPaper.id||s.paper.revision!==result.manuscript.revision||
      s.paperReadSequence!==paperRead+1||s.paperDraft?.dirty)return;
    setAttachNotice({paperId:sentPaper.id,revision:result.manuscript.revision,text:replacement?`已更新第 ${index+1} 处稿内图：r${expectedRef.revision} → r${sentView.figure.revision}。其他位置保留。`:'已将保存版主图插入新稿内位置。'});
    await s.flush();
  };
  const selectionBounds=selectedLayout.length?layoutBounds(boxesFor(selectedLayout)):null;
  const nodes:FigureNode[]=[...panels.map((p,i)=>({id:p.id+'@'+p.revision,type:'figure' as const,position:s.generationLayouts[key]?.[p.id+'@'+p.revision]||{x:20,y:20+i*80},data:{label:p.title+' · r'+p.revision,output:true}})),...slots.map((slot:any,i:number)=>({id:'slot:'+slot.id,type:'figure' as const,position:s.generationLayouts[key]?.['slot:'+slot.id]||{x:340,y:20+i*80},data:{label:'图位 '+slot.label+(slot.required?' · 必需':''),input:true}}))];
  // A pinned older source stays visible even when the catalog has a new revision.
  for(const slot of slots){const ref=slot.source;if(ref&&!nodes.some(n=>n.id===ref.id+'@'+ref.revision))nodes.push({id:ref.id+'@'+ref.revision,type:'figure',position:{x:20,y:nodes.length*70},data:{label:ref.id+' · 固定 r'+ref.revision,output:true}});}
  const edges=slots.filter((slot:any)=>slot.source).map((slot:any)=>({id:slot.id,source:slot.source.id+'@'+slot.source.revision,target:'slot:'+slot.id,sourceHandle:'panel',targetHandle:'panel',label:'已保存引用'}));
  const connect=(c:Connection)=>{const panel=panels.find(p=>p.id+'@'+p.revision===c.source),slot=slots.find((x:any)=>'slot:'+x.id===c.target);if(!panel||!slot){report(new Error('需要子图输出 → 图位输入。'));return;}void act(()=>bind(slot.id,panel));};
  const currentBox=draft?draftSlots(draft).find(p=>p.id===chosen.id)?.box||chosen.box:chosen.box;
  return <>
    <div className="panel-tools"><strong>{view.figure.title} · r{view.figure.revision}</strong><button disabled={busy||readOnly||view.required_missing.length>0||!!draft} onClick={()=>act(async()=>{await command('object.export',{id,expected_revision:view.figure.revision,format:'png'});await read();})}>{busy?'处理中…':'重绘保存版主图'}</button><button disabled={busy||readOnly||!!draft||undoHistory.length===0} onClick={undoSaved}>撤销上次保存的图位修改</button><button aria-pressed={showSource} onClick={()=>setShowSource(!showSource)}>组成与实际来源</button></div>
    {view.required_missing.length>0&&<p className="composition-warning" role="status">必需图位未接入：{view.required_missing.join('、')}。正式完整输出被阻止。</p>}
    <div className="composition-layout scientific-main-layout"><aside className="composition-catalog" aria-label="子图目录"><details open><summary>子图目录 · 拖入图位接入固定来源</summary><div>{panels.map(p=><button key={p.id} draggable={!readOnly} onDragStart={e=>{e.dataTransfer.setData(MIME,JSON.stringify({id:p.id,revision:p.revision}));e.dataTransfer.effectAllowed='copy';}} onClick={()=>setSource(p.id)} aria-pressed={source===p.id}>{p.title} · r{p.revision}</button>)}</div></details></aside>
      <div className="composition-center"><div className="scientific-layout-tools" role="toolbar" aria-label="主图选区布局工具">{([['left','左对齐'],['right','右对齐'],['top','顶对齐'],['bottom','底对齐'],['horizontal-center','水平居中'],['vertical-center','垂直居中'],['horizontal-distribute','水平等距'],['vertical-distribute','垂直等距']] as [Alignment,string][]).map(([mode,label])=><button key={mode} disabled={busy||readOnly||selectedLayout.length<(mode.endsWith('distribute')?3:2)} onClick={()=>alignSelection(mode)}>{label}</button>)}<small>选区布局操作只改所选图位；数值与固定来源保持。</small></div><ScientificCanvas width={view.definition.width} height={view.definition.height} label="主图布局" stageClass="composition-canvas" stageRef={canvas} viewMemory={viewMemory?.canvas} scope={layoutScope.current} disabled={busy||readOnly} onBoxSelect={selectBox}>
        {slots.map((slot:any)=>{const box=draft?draftSlots(draft).find(p=>p.id===slot.id)?.box||slot.box:slot.box;return <div key={slot.id} data-canvas-object className={'composition-slot '+(layoutSelection.includes(slot.id)?'chosen':'')} aria-label={'主图图位 '+slot.id} aria-pressed={layoutSelection.includes(slot.id)} role="button" tabIndex={0} style={{left:box[0]*100+'%',top:box[1]*100+'%',width:box[2]*100+'%',height:box[3]*100+'%'}} onPointerDown={e=>startDrag(e,slot)} onPointerMove={moveDrag} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}} onClick={e=>chooseLayout(slot.id,e.shiftKey)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();chooseLayout(slot.id,e.shiftKey);}const delta:{[key:string]:number[]}={ArrowLeft:[-.01,0],ArrowRight:[.01,0],ArrowUp:[0,-.01],ArrowDown:[0,.01]};if(delta[e.key]&&!busy&&!readOnly){e.preventDefault();try{applyLayout(translateBoxes(boxesFor(layoutSelection.includes(slot.id)?selectedLayout:[slot]),...delta[e.key] as [number,number]));}catch(error){report(error);}}}} onDragOver={e=>{if(!readOnly&&!busy&&e.dataTransfer.types.includes(MIME)){e.preventDefault();e.dataTransfer.dropEffect='copy';}}} onDrop={e=>{if(readOnly||busy||!e.dataTransfer.types.includes(MIME))return;e.preventDefault();try{const p=JSON.parse(e.dataTransfer.getData(MIME));void act(()=>bind(slot.id,p));}catch(error){report(error);}}}>
          <span className="composition-slot-label">{slot.label}{slot.source?'':' · 空位'}</span>{slot.source&&<img src={'/api/assets/'+slot.source.svg_sha256} alt={'固定子图 '+slot.id} draggable={false}/>}</div>;})}
        {selectionBounds&&<CanvasHandles box={selectionBounds} label="主图布局" disabled={busy||readOnly} onStart={resizeStart} onMove={resizeMove} onEnd={()=>{resize.current=null;}} onCancel={()=>{resize.current=null;}}/>}
      </ScientificCanvas><p className="composition-state">{draft?'主图布局草稿未保存':view.render?'保存版主图已有实际输出':'定义布局；尚未生成本保存版主图'}</p>
      {view.render&&<div className="figure-downloads">{['canvas.svg','canvas.pdf','canvas.png','source.json'].filter(name=>view.render.assets[name]).map(name=><a key={name} href={'/api/assets/'+view.render.assets[name].sha} target="_blank" rel="noreferrer">{name}</a>)}</div>}</div>
      <aside className="composition-properties"><MainFigureOpinionControl session={s} view={view} layoutSelection={layoutSelection} busy={busy} readOnly={readOnly} dirty={!!draft} onReview={onReview}/>{requested?.length===0&&<p role="status">意见所选图位不在此保存版中，未替换为其他图位。</p>}<label>当前图位<select aria-label="主图当前图位" value={selected} onChange={e=>chooseLayout(e.target.value,false,true)}>{slots.map((slot:any)=><option key={slot.id} value={slot.id}>{slot.label}</option>)}</select></label><label>接入子图<select aria-label="图位接入子图" value={source} onChange={e=>setSource(e.target.value)}><option value="">选择固定子图</option>{panels.map(p=><option key={p.id} value={p.id}>{p.title} · r{p.revision}</option>)}</select></label><button disabled={busy||readOnly||!source||!!draft} onClick={()=>act(()=>bind(chosen.id,panels.find(p=>p.id===source)))}>接入所选子图</button><button disabled={busy||readOnly||!chosen.source||!!draft} onClick={()=>act(async()=>{if(await mutate('detach',chosen.id,{}))await read();})}>解除此图位</button>
        <p>Shift 点击或 Shift＋Enter 可多选图位。</p><p aria-live="polite">已选布局图位：{selectedLayout.map((slot:any)=>slot.id).join('、')}（{selectedLayout.length}）</p>
        {selectedLayout.length>1&&<fieldset aria-label="主图临时布局组" style={{minWidth:0,padding:'8px'}}><legend>临时布局组</legend><p>共同平移所选图位，保留相对位置。源图轴线、曲线和数据保持。</p>{['水平','垂直'].map((label,index)=><label key={label}>{label}位移（主图比例）<input aria-label={'布局组'+label+'位移'} type="number" step={.01} disabled={busy||readOnly} value={groupOffset[index]} onChange={e=>setGroupOffset(old=>old.map((value,i)=>i===index?e.target.value:value))}/></label>)}<button disabled={busy||readOnly} onClick={translateSelection}>平移所选布局组</button></fieldset>}
        {['X','Y','宽度','高度'].map((label,i)=><label key={label}>{label}<input type="number" min={0} max={1} step={.01} disabled={busy||readOnly||selectedLayout.length>1} aria-label={'图位布局 '+label} value={currentBox[i]} onChange={e=>{try{const box=[...currentBox];box[i]=Number(e.target.value);updateDraft(chosen.id,box);}catch(error){report(error);}}}/></label>)}
        {draft&&<><p>{draft.base!==view.figure.revision||draft.sha!==view.definition_sha256?'保存版已有新修订；草稿保留，旧基线不能覆盖新改。':'拖动和尺寸调整尚未写入定义文件。'}</p><button disabled={busy||readOnly} onClick={saveDraft}>{draft.slots?'保存布局组':'保存图位布局'}</button><button disabled={busy||readOnly} onClick={cancelDraft}>撤销布局草稿</button></>}
      </aside></div>
    <div className="panel-tools"><button disabled={busy||readOnly||!chosen.source||!chosenPanel||chosenPanel.current_revision!==chosen.source.revision} onClick={()=>setInlineSlot(chosen.id)}>在主图中编辑此子图元素组</button>{chosen.source&&chosenPanel?.current_revision!==chosen.source.revision&&<p>此图位使用固定 r{chosen.source.revision}，源图已为 r{chosenPanel?.current_revision}。请比较后明确接入新修订；未自动修改旧图位。</p>}</div>
    {inlinePanel&&<section className="embedded-figure" aria-label={'主图内子图元素组 '+inlineSlot}><div className="panel-tools"><strong>图位 {inlineSlot} 的源子图</strong><button onClick={()=>setInlineSlot('')}>关闭子图元素组</button></div><p>调整保存为源子图的新修订，数值不变。当前主图保留固定引用；接入新修订需要明确操作。未采用草稿保留在项目工作桌中。</p><FigureBody key={inlinePanel.source_ref.id} session={s} initialId={inlinePanel.source_ref.id} report={report} embedded onSaved={read}/></section>}
    <details className="composition-flow" onToggle={e=>setShowFlow(e.currentTarget.open)}><summary>节点组成</summary>{showFlow&&<div className="generation-flow" role="region" aria-label="主图组成节点"><ReactFlow<FigureNode> nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView nodesConnectable={!readOnly&&!busy&&!draft} onConnect={connect} onNodeClick={(_,n)=>{if(n.id.startsWith('slot:'))chooseLayout(n.id.slice(5),false,true);}} onNodeDrag={(_,n)=>{s.generationLayouts[key]={...s.generationLayouts[key],[n.id]:n.position};s.notify();}} onNodeDragStop={(_,n)=>{s.generationLayouts[key]={...s.generationLayouts[key],[n.id]:n.position};s.notify();if(s.layout)void s.saveLayout(s.layout);}}><Background/><Controls/></ReactFlow></div>}</details>
    {showSource&&<FigureSourcePanel onClose={()=>setShowSource(false)}><p>定义文件：{view.definition_path} · {view.definition_sha256}</p><details><summary>完整组成定义</summary><pre>{view.definition_text}</pre></details>{view.panels.map((p:any)=><details key={p.slot_id} open><summary>图位 {p.slot_id} → {p.view.figure.title} · 固定 r{p.source_ref.revision}</summary>{p.current_revision!==p.source_ref.revision&&<p>源图当前为 r{p.current_revision}；本图位保留旧修订，接入新修订需要明确操作及实际输出。</p>}<button onClick={()=>openPanel(p.source_ref.id,p.source_ref.revision)}>打开源图编辑与计算链</button><p>实际绘图输出：{p.source_ref.svg_sha256}</p>{p.source_ref.numeric_sha256&&<a href={'/api/assets/'+p.source_ref.numeric_sha256} target="_blank" rel="noreferrer">原子图数值文件</a>}<details><summary>输入、参数与生成记录</summary><pre>{JSON.stringify({parameters:p.view.source.parameters,inputs:p.view.source.inputs,generation:p.view.generation},null,2)}</pre></details><pre>{p.view.source.code}</pre></details>)}</FigureSourcePanel>}
    <div className="figure-authorize">{providers.length>0&&<><label>主图委托提供者<select aria-label="主图委托提供者" value={provider} onChange={e=>selectProvider(e.target.value)}>{providers.map(p=><option key={p.id} value={p.id}>{p.id} · {p.route} · {p.model}</option>)}</select></label>{selectedProvider&&<p>调用上限：{selectedProvider.budget.max_model_calls} · 时间上限：{selectedProvider.budget.timeout_seconds} 秒 · {selectedProvider.route} · {selectedProvider.model}</p>}</>}{selectedProvider&&!freshOnlyTask&&!pendingTaskRead&&<><button disabled={busy||readOnly||!!draft||view.required_missing.length>0} onClick={previewEgress}>查看将发送的子图上下文</button>{egress&&<details open><summary>将发送到 {provider} · {selectedProvider.route} · {selectedProvider.model} · 仅组成新主图候选</summary><pre>{JSON.stringify(egress.contexts,null,2)}</pre><p>授权仅适用此摘要和提供者，一小时后到期；restricted 素材默认拒绝。</p><button disabled={busy||readOnly||egressGranted} onClick={authorizeEgress}>允许发送这组固定上下文</button>{egressGranted&&<button onClick={()=>act(async()=>{const {task_id,...scope}=egressFields() as any;await command('desk.figure.composition.authorize',{...scope,preview_sha256:egress.sha256,approved:false});setEgressGranted(false);})}>撤回这组外发授权</button>}</details>}</>}{selectedProvider&&!freshOnlyTask&&!pendingTaskRead&&<button disabled={busy||readOnly||!egressGranted||!!draft||view.required_missing.length>0||['queued','running'].includes(task?.status)} onClick={()=>act(async()=>{if(!selectedProvider||freshOnlyTask||pendingTaskRead||draft||!egressGranted)throw new Error('请核对当前主图提供者及固定上下文授权');const savedScope=activeScope.current;const created=await command('desk.figure.composition.submit',{...figureCompositionSubmission(s.project.id,view,selectedProvider),request_key:requestId()});if(!mounted.current||savedScope!==activeScope.current)return;setTask(created);setTaskId(created.id);s.views['composition-task:'+id]={task_id:created.id};s.notify();if(s.layout)await s.saveLayout(s.layout);})}>让Agent组成新主图候选</button>}{!selectedProvider&&<p>当前服务没有可执行且已授权的主图组成提供者；目录与节点组成仍可用。</p>}{task&&<><p>主图委托 {task.id} · {task.status}</p>{freshOnlyTask&&<p role="status">当前原生协议不支持续接或重发此原任务；实际任务与已登记候选历史保留，未确认的结果不能通过新任务重试。</p>}{task.result?.composition_candidate&&<><button onClick={()=>openPanel(task.result.composition_candidate.id)}>打开Agent主图候选</button><button disabled={busy||readOnly||task.status!=='generated'} onClick={()=>act(async()=>{await command('desk.task.brief',{project_id:s.project.id,task_id:task.id});await s.refresh();})}>将主图回报记入项目笔记</button></>}{['queued','running'].includes(task.status)&&<button onClick={()=>act(async()=>{await command('task.control',{id:task.id,operation:'cancel'});setTask(await readTask(task.id));})}>取消此主图委托</button>}{stopped&&sameTaskSources&&selectedProvider?.supports_resume&&selectedProvider.id===task.payload?.provider_id&&!freshOnlyTask&&<button disabled={busy||readOnly||!selectedProvider||!egressGranted||!!draft} onClick={()=>act(async()=>{await command('task.control',{id:task.id,operation:'resume'});setTask(await readTask(task.id));setTaskId('');queueMicrotask(()=>setTaskId(task.id));})}>接续原主图委托</button>}{task.error&&<p role="alert">{typeof task.error==='string'?task.error:JSON.stringify(task.error)}</p>}</>}<p>固定已有子图，创建新的未采用候选；不会改当前主图、重做分析或自动插入稿件。</p></div>
    <div className="figure-attach" role="group" aria-label="更新稿内已有主图"><label>稿内已有位置<select aria-label="选择要更新的稿内主图位置" value={occurrence} disabled={busy} onChange={e=>{setOccurrence(e.target.value);setAttachNotice(null);}}>
      <option value="">选择一处已有稿内图</option>{occurrences.map(({ref,index}:any)=>{const block=s.paper.content.blocks.find((block:any)=>block.id===ref.after_block_id);
        return <option key={index} value={String(index)}>第 {index+1} 处 · {block?.text?.slice(0,32)||'未登记段落锚点'} · {String(ref.caption||'无图注').slice(0,48)} · r{ref.revision}</option>;})}
    </select></label><button disabled={attachBlocked||!targetOccurrence||!validOccurrence(targetOccurrence.ref)||targetOccurrence.ref.revision>=view.figure.revision} onClick={()=>act(()=>attachSaved(targetOccurrence))}>更新此处稿内图版本</button>
      {targetOccurrence&&<span>第 {targetOccurrence.index+1} 处：r{targetOccurrence.ref.revision} → 保存版 r{view.figure.revision}{targetOccurrence.ref.revision===view.figure.revision?'（已经相同）':''}</span>}
      {!occurrences.length&&<p>当前主图尚未被稿件引用；可选择下方位置插入。</p>}
      <p>只更新明确选择的一处固定图版本，保留原图注、段落位置和其他引用。</p>
    </div>
    <div className="figure-attach"><label>稿件位置<select aria-label="主图插入段落" value={anchor} onChange={e=>setAnchor(e.target.value)}>{s.paper.content.blocks.map((b:any,i:number)=><option key={b.id} value={b.id}>{i+1} · {b.text.slice(0,30)}</option>)}</select></label><label>稿内图注<input aria-label="主图稿内图注" value={caption} onChange={e=>setCaption(e.target.value)}/></label><button disabled={attachBlocked} onClick={()=>act(()=>attachSaved())}>将保存版主图插入稿件</button></div>
    {attachNotice&&attachNotice.paperId===s.paper.id&&attachNotice.revision===s.paper.revision&&<p role="status" aria-label="稿内图引用更新结果">{attachNotice.text}</p>}
  </>;
}
