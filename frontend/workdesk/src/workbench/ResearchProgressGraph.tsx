import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {ReactFlow,Handle,Position,MarkerType,type NodeProps,type ReactFlowInstance,type Node,type BuiltInEdge} from '@xyflow/react';
import {Check,ChevronDown,ChevronUp,Clock3,Expand,LockKeyhole,Minus,Pause,Plus,RotateCcw} from 'lucide-react';
import {parts,partNames,currentVersion,nodeLabel,nodeStatusNames,dependencyNames,type Part,type ProgressQuestion,type Revision} from './researchProgress';
import '@xyflow/react/dist/style.css';

type Selection={question:ProgressQuestion;part:Part;version:Revision;historical:boolean};
export type ProgressSelection=Selection;
type Data=Record<string,unknown>&{question:ProgressQuestion;part:Part;version:Revision;compact:boolean;selected:boolean;childCount:number;expanded:boolean;select:(value:Selection)=>void;expand:()=>void};
type ProgressNode=Node<Data,'research'>;
function StageNode({data}:NodeProps<ProgressNode>){
 const {question:q,part,version:v,compact}=data,empty=q.parts[part].empty,node=q.parts[part].node;
 const Badge=node.status==='completed'?Check:node.status==='stale'?RotateCcw:node.status==='paused'?Pause:node.flags.includes('blocked')?LockKeyhole:node.status==='active'||node.status==='review'?Clock3:null;
 return <div className={'progress-stage state-'+node.status+' '+(empty?'is-empty ':'')+(compact?'compact ':'')+(data.selected?'selected ':'')+(q.is_root?'article-root ':'')+'stage-'+part}>
 <Handle type="target" position={Position.Left} id="context-in" style={{left:compact?0:54,top:36}}/><Handle type="source" position={Position.Right} id="context-out" style={{right:54,top:36}}/>
 <Handle type="target" position={Position.Top} id="vertical-in" style={{left:28,top:8}}/><Handle type="source" position={Position.Bottom} id="vertical-out" style={{left:28,top:64,bottom:'auto'}}/>
 <Handle type="target" position={Position.Top} id="dependency-in" style={{left:82,top:8}}/><Handle type="source" position={Position.Top} id="dependency-out" style={{left:82,top:8}}/>
 <Handle type="source" position={Position.Left} id="child-out" style={{left:compact?0:54,top:36}}/>
 <button className="progress-stage-content nodrag nopan" title={node.title+' · '+nodeStatusNames[node.status]} aria-label={q.number+' '+part+' '+partNames[part]+' '+(empty?'尚未整理':'当前内容 r'+v.revision)} aria-pressed={data.selected} onClick={()=>data.select({question:q,part,version:v,historical:false})}>
 <span className="progress-node-circle"><span>{nodeLabel(q,part)}</span>{Badge&&<span className="progress-state-symbol" aria-hidden="true"><Badge/></span>}</span>
 <span className="progress-node-label"><strong>{node.title||'未命名'+partNames[part]}</strong><span className="progress-node-caption">{q.is_root&&part==='Q'?'文章研究问题 · ':''}{nodeStatusNames[node.status]}{node.flags.includes('blocked')&&node.status!=='blocked'&&node.status!=='stale'?' · 条件未满足':''}</span></span>
 </button>
 {part==='Q'&&data.childCount>0&&<button className="progress-child-toggle nodrag nopan" aria-expanded={data.expanded} onClick={e=>{e.stopPropagation();data.expand();}}>{data.expanded?<ChevronUp/>:<ChevronDown/>}{data.expanded?'收起子问题':data.childCount+' 个子问题'}</button>}
 </div>;
}
const nodeTypes={research:StageNode};
export function ResearchProgressGraph({questions,selected,onSelect,theme}:{questions:ProgressQuestion[];selected:ProgressSelection|null;onSelect:(s:ProgressSelection)=>void;theme:'light'|'dark'}){
 const host=useRef<HTMLDivElement>(null),[width,setWidth]=useState(900),[height,setHeight]=useState(600),[flow,setFlow]=useState<ReactFlowInstance<ProgressNode>|null>(null),[filter,setFilter]=useState('all'),[expanded,setExpanded]=useState<string[]>(()=>questions.filter(q=>q.is_root).map(q=>q.id));
 const compact=width<640,roots=questions.filter(q=>!q.parent_id),effectiveFilter=compact&&filter==='all'?roots[0]?.id||'all':filter;
 const articleRoot=questions.find(q=>q.is_root)?.id;
 useEffect(()=>{if(articleRoot)setExpanded(old=>old.includes(articleRoot)?old:[...old,articleRoot]);},[articleRoot]);
 useEffect(()=>{const observer=new ResizeObserver(([e])=>{setWidth(e.contentRect.width);setHeight(e.contentRect.height);});observer.observe(host.current!);return()=>observer.disconnect();},[]);
 const expand=useCallback((id:string)=>setExpanded(old=>old.includes(id)?old.filter(x=>x!==id):[...old,id]),[]);
 const graph=useMemo(()=>{
  const nodes:ProgressNode[]=[],edges:BuiltInEdge[]=[],visible:ProgressQuestion[]=[];
  const visit=(q:ProgressQuestion)=>{visible.push(q);if(expanded.includes(q.id))questions.filter(x=>x.parent_id===q.id).forEach(visit);};
  if(effectiveFilter==='all')roots.forEach(visit);else {const q=questions.find(q=>q.id===effectiveFilter);if(q)visit(q);}
  const gap=194,nodeWidth=compact?280:164,step=compact?150:202;
  visible.forEach((q,row)=>{
   const base=compact?row*650:row*gap;
   parts.forEach((part,col)=>{
    const version=currentVersion(q,part);
    const position=compact?{x:28,y:base+col*step+28}:{x:36+col*step,y:base+36};
    const currentId=q.id+':'+part;
    nodes.push({id:currentId,type:'research',position,width:nodeWidth,data:{question:q,part,version,compact,selected:selected?.question.id===q.id&&selected.part===part,childCount:questions.filter(x=>x.parent_id===q.id).length,expanded:expanded.includes(q.id),select:onSelect,expand:()=>expand(q.id)},draggable:false,focusable:false});
    if(col>0)edges.push({id:q.id+':organize:'+part,source:q.id+':'+parts[col-1],target:currentId,sourceHandle:compact?'vertical-out':'context-out',targetHandle:compact?'vertical-in':'context-in',type:'smoothstep',className:'progress-organizing-edge',markerEnd:{type:MarkerType.ArrowClosed,width:11,height:11},selectable:false,focusable:false});
   });
   if(q.parent_id&&visible.some(x=>x.id===q.parent_id))edges.push({id:'parent:'+q.id,source:q.parent_id+':Q',target:q.id+':Q',sourceHandle:'child-out',targetHandle:'context-in',type:'smoothstep',className:'progress-decomposition-edge',pathOptions:{offset:compact?20:80},label:'拆解',labelStyle:{fontSize:11},labelBgStyle:{fill:'var(--surface-editor)'},selectable:false,focusable:false});
  });
  if(selected&&!compact){const node=selected.question.parts[selected.part].node;for(const d of node.dependencies){if(!visible.some(q=>q.id===d.question_id))continue;edges.push({id:'dependency:'+node.id+':'+d.id,source:d.id,target:node.id,sourceHandle:'dependency-out',targetHandle:'dependency-in',type:'smoothstep',pathOptions:{offset:32},label:dependencyNames[d.kind]+' · '+nodeStatusNames[d.status],labelStyle:{fontSize:10},labelBgStyle:{fill:'var(--surface-toolbar)'},className:'progress-completion-edge state-'+d.status,markerEnd:{type:MarkerType.ArrowClosed,width:12,height:12},selectable:false,focusable:false});}}
  return {nodes,edges,visible};
 },[questions,effectiveFilter,expanded,compact,selected,onSelect,expand]);
 const fit=useCallback(()=>{if(!flow)return;const first=graph.visible[0],ids=compact&&first?[{id:first.id+':Q'},{id:first.id+':A'}]:graph.nodes.filter(n=>graph.visible.slice(0,questions.some(q=>q.is_root)?3:2).some(q=>n.data.question.id===q.id)).map(n=>({id:n.id}));void flow.fitView({nodes:ids,padding:.12,minZoom:compact?.85:.7,maxZoom:1,duration:0});},[flow,graph.visible.map(q=>q.id).join('|'),compact,width,height]);
 useEffect(()=>{const frame=requestAnimationFrame(fit);return()=>cancelAnimationFrame(frame);},[fit]);
 useEffect(()=>{if(!flow)return;const frame=requestAnimationFrame(()=>{if(selected){const ids=compact?[{id:selected.question.id+':'+selected.part}]:graph.nodes.filter(n=>n.data.question.id===selected.question.id).map(n=>({id:n.id}));void flow.fitView({nodes:ids,padding:.12,minZoom:.8,maxZoom:1,duration:0});}else fit();});return()=>cancelAnimationFrame(frame);},[selected?.question.id,selected?.part,flow,compact,width,height]);
 function pickPart(part:Part){const q=selected?.question||graph.visible[0];if(q)onSelect({question:q,part,version:currentVersion(q,part),historical:false});}
 return <div className="research-progress-map" ref={host}><div className="progress-map-toolbar"><h2>研究进展 <span className="progress-latest-label">最新保存版</span></h2><label className="progress-filter"><span className="sr-only">显示研究问题</span><select aria-label="显示研究问题" value={effectiveFilter} onChange={e=>setFilter(e.target.value)}><option value="all">全部问题</option>{questions.map(q=><option key={q.id} value={q.id}>{q.number} {q.title}</option>)}</select></label><button className="icon-button" aria-label="适应研究进展图" onClick={fit}><Expand/></button></div>
 <div className="progress-stage-navigation" aria-label="定位QAEC">{parts.map(p=><button key={p} onClick={()=>pickPart(p)} aria-label={'定位 '+p+' '+partNames[p]}>{p}<span>{partNames[p]}</span></button>)}</div>
 <div className="progress-flow" role="region" aria-label="研究进展图"><ReactFlow<ProgressNode> nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} onInit={setFlow} onNodeClick={(_event,node)=>onSelect({question:node.data.question,part:node.data.part,version:node.data.version,historical:false})} colorMode={theme} nodesConnectable={false} nodesDraggable={false} edgesReconnectable={false} elementsSelectable={false} deleteKeyCode={null} minZoom={.45} maxZoom={1.5} zoomOnDoubleClick={false} panOnScroll={false} preventScrolling onPaneClick={()=>{}} aria-label="最新QAEC画布" ariaLabelConfig={{'node.a11yDescription.default':'按Tab到达研究节点，按Enter查看最新内容与历史。','controls.zoomIn.ariaLabel':'放大研究图','controls.zoomOut.ariaLabel':'缩小研究图'}}/>
 <div className="progress-zoom"><button className="icon-button" aria-label="缩小研究图" onClick={()=>void flow?.zoomOut()}><Minus/></button><button className="icon-button" aria-label="放大研究图" onClick={()=>void flow?.zoomIn()}><Plus/></button></div></div>
 <div className="progress-map-legend"><span><i className="organization"/>组织与拆解</span><span className="progress-status-key"><b className="active"/>进行中<b className="review"/>待确认<b className="completed"/>已完成<b className="stale"/>待复核</span><span>点击节点查看依据、状态与历史</span></div>
 </div>;
}
