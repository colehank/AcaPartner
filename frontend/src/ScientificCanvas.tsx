import {useEffect,useRef,useState,type ReactNode,type RefObject} from 'react';
import type {CanvasBox} from './figureCanvasGeometry';
import type {CanvasCamera,CanvasViewMemory} from './figureViewMemory';

const validCamera=(value:CanvasCamera|undefined):value is CanvasCamera=>!!value&&[value.scale,value.x,value.y].every(Number.isFinite)&&value.scale>=.05&&value.scale<=8;
const rememberedCamera=(memory:CanvasViewMemory|undefined,width:number,height:number)=>Number.isFinite(width)&&Number.isFinite(height)&&width>0&&height>0&&memory?.width===width&&memory.height===height&&validCamera(memory.camera)?{...memory.camera}:undefined;

export function ScientificCanvas({width,height,label,stageClass,stageRef,scope,children,onBoxSelect,disabled=false,viewMemory}:{width:number,height:number,label:string,stageClass:string,stageRef:RefObject<HTMLDivElement|null>,scope:string,children:ReactNode,onBoxSelect:(box:CanvasBox,add:boolean)=>void,disabled?:boolean,viewMemory?:CanvasViewMemory}){
  const viewport=useRef<HTMLDivElement>(null),gesture=useRef<any>(null),space=useRef(false);
  const [camera,updateCamera]=useState(()=>rememberedCamera(viewMemory,width,height)||{scale:1,x:0,y:0}),[mode,setMode]=useState<'select'|'pan'>('select'),[region,setRegion]=useState<CanvasBox|null>(null);
  const destination=useRef({viewMemory,width,height});destination.current={viewMemory,width,height};
  const setCamera=(next:CanvasCamera|((old:CanvasCamera)=>CanvasCamera))=>{
    const target=destination.current;
    updateCamera(old=>{const value=typeof next==='function'?next(old):next;if(!validCamera(value))return old;
      if(target.viewMemory){
        const memory=target.viewMemory,changed=memory.width!==target.width||memory.height!==target.height||
          memory.camera?.scale!==value.scale||memory.camera?.x!==value.x||memory.camera?.y!==value.y;
        Object.assign(memory,{camera:{...value},width:target.width,height:target.height});
        if(changed)memory.changed?.();
      }return value;});
  };
  const current=useRef(scope);current.current=scope;
  const fit=()=>{const target=destination.current;if(current.current!==scope||target.width!==width||target.height!==height||target.viewMemory!==viewMemory)return false;const el=viewport.current;if(!el||el.clientWidth<=0||el.clientHeight<=0||!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)return false;const scale=Math.max(.05,Math.min(4,(el.clientWidth-40)/width,(el.clientHeight-40)/height));setCamera({scale,x:(el.clientWidth-width*scale)/2,y:(el.clientHeight-height*scale)/2});return true;};
  const zoom=(factor:number,clientX?:number,clientY?:number)=>{
    const el=viewport.current;if(!el)return;const rect=el.getBoundingClientRect(),x=clientX===undefined?el.clientWidth/2:clientX-rect.left,y=clientY===undefined?el.clientHeight/2:clientY-rect.top;
    setCamera(old=>{const scale=Math.min(8,Math.max(.05,old.scale*factor)),ratio=scale/old.scale;return {scale,x:x-(x-old.x)*ratio,y:y-(y-old.y)*ratio};});
  };
  useEffect(()=>{
    // Fit each new graphic at its first usable size. Later viewport changes,
    // including a hidden panel becoming visible, preserve the user's camera.
    const remembered=rememberedCamera(viewMemory,width,height);
    if(remembered)setCamera(remembered);
    let active=true,fitted=!!remembered||fit();
    const observer=new ResizeObserver(()=>{if(active&&!fitted)fitted=fit();});
    if(viewport.current)observer.observe(viewport.current);
    return()=>{active=false;observer.disconnect();};
  },[width,height,scope,viewMemory]);
  useEffect(()=>{gesture.current=null;setRegion(null);space.current=false;},[scope,disabled]);
  useEffect(()=>{const el=viewport.current;if(!el)return;const wheel=(e:WheelEvent)=>{e.preventDefault();zoom(Math.exp(-e.deltaY*.0015),e.clientX,e.clientY);};el.addEventListener('wheel',wheel,{passive:false});return()=>el.removeEventListener('wheel',wheel);},[]);
  const start=(e:React.PointerEvent<HTMLDivElement>)=>{
    if(e.button!==0&&e.button!==1)return;
    const pan=mode==='pan'||space.current||e.button===1;
    if(!pan&&(disabled||(e.target as HTMLElement).closest('[data-canvas-object],button,input,select,textarea')))return;
    if(!stageRef.current)return;
    e.preventDefault();e.stopPropagation();e.currentTarget.focus();e.currentTarget.setPointerCapture(e.pointerId);
    gesture.current={pan,x:e.clientX,y:e.clientY,camera,rect:stageRef.current.getBoundingClientRect(),scope:current.current,add:e.shiftKey};
  };
  const move=(e:React.PointerEvent<HTMLDivElement>)=>{
    const g=gesture.current;if(!g||g.scope!==current.current)return;
    if(g.pan){setCamera({...g.camera,x:g.camera.x+e.clientX-g.x,y:g.camera.y+e.clientY-g.y});return;}
    const x1=(g.x-g.rect.left)/g.rect.width,y1=(g.y-g.rect.top)/g.rect.height,x2=(e.clientX-g.rect.left)/g.rect.width,y2=(e.clientY-g.rect.top)/g.rect.height;
    setRegion([Math.max(0,Math.min(x1,x2)),Math.max(0,Math.min(y1,y2)),Math.max(0,Math.min(1,Math.max(x1,x2))-Math.max(0,Math.min(x1,x2))),Math.max(0,Math.min(1,Math.max(y1,y2))-Math.max(0,Math.min(y1,y2)))]);
  };
  const finish=()=>{const g=gesture.current;gesture.current=null;if(g&&!g.pan&&g.scope===current.current&&region)onBoxSelect(region,g.add);setRegion(null);};
  return <section className="scientific-canvas" aria-label="科学图交互画布"><div className="scientific-canvas-tools" role="toolbar" aria-label="画布视图工具">
    <button aria-pressed={mode==='select'} onClick={()=>setMode('select')}>选择 / 框选</button><button aria-pressed={mode==='pan'} onClick={()=>setMode('pan')}>平移画布</button>
    <button onClick={()=>zoom(.8)} aria-label="缩小画布">−</button><span className="scientific-canvas-zoom" aria-label="画布缩放">{Math.round(camera.scale*100)}%</span><button onClick={()=>zoom(1.25)} aria-label="放大画布">＋</button><button onClick={fit}>适配画布</button><span>滚轮缩放 · 空格拖动平移 · Shift 多选</span>
  </div><div className={'scientific-canvas-viewport '+(mode==='pan'?'panning':'')} ref={viewport} style={{position:'relative',height:'clamp(360px,63vh,850px)',overflow:'hidden',touchAction:'none'}} tabIndex={0} aria-label="画布视口" onPointerDownCapture={start} onPointerMove={move} onPointerUp={finish} onPointerCancel={()=>{gesture.current=null;setRegion(null);}} onKeyDown={e=>{if(e.code==='Space'&&e.target===e.currentTarget){e.preventDefault();space.current=true;}if(e.key==='Escape'){gesture.current=null;setRegion(null);}}} onKeyUp={e=>{if(e.code==='Space')space.current=false;}} onBlur={()=>{space.current=false;}}>
    <div ref={stageRef} className={stageClass+' scientific-canvas-stage'} aria-label={label} style={{position:'absolute',width,height,transformOrigin:'0 0',transform:`translate(${camera.x}px,${camera.y}px) scale(${camera.scale})`}}>{children}{region&&<div className="scientific-canvas-marquee" aria-hidden="true" style={{left:region[0]*100+'%',top:region[1]*100+'%',width:region[2]*100+'%',height:region[3]*100+'%'}}/>}</div>
  </div></section>;
}

export function CanvasHandles({box,label,onStart,onMove,onEnd,onCancel,disabled=false}:{box:number[],label:string,onStart:(e:React.PointerEvent<HTMLButtonElement>,corner:'nw'|'ne'|'sw'|'se')=>void,onMove:(e:React.PointerEvent<HTMLButtonElement>)=>void,onEnd:(e:React.PointerEvent<HTMLButtonElement>)=>void,onCancel?:()=>void,disabled?:boolean}){
  return <div className="scientific-canvas-bounds" aria-label={label+'选区边界'} style={{position:'absolute',pointerEvents:'none',left:box[0]*100+'%',top:box[1]*100+'%',width:box[2]*100+'%',height:box[3]*100+'%'}}>{(['nw','ne','sw','se'] as const).map(corner=><button key={corner} data-canvas-object className={'scientific-resize-handle '+corner} style={{pointerEvents:'auto'}} aria-label={label+'缩放控制柄 '+corner} disabled={disabled} onPointerDown={e=>{e.stopPropagation();onStart(e,corner);}} onPointerMove={onMove} onPointerUp={onEnd} onPointerCancel={onCancel}/>)}</div>;
}
