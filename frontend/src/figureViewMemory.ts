// A panel's navigation state. This never enters scientific overlays or grants.
export type CanvasCamera = {scale:number,x:number,y:number};
export type CanvasViewMemory = {camera?:CanvasCamera,width?:number,height?:number,changed?:()=>void};
export type FigureViewMemory = {selected?:string[],active?:string,imageSize?:number[],panelScroll?:{top:number,left:number},canvas:CanvasViewMemory,changed?:()=>void};
export type FigurePanelMemory = Map<string,FigureViewMemory>;

// Only camera and panel scroll geometry are persisted. Content, selection and permission results
// are never reconstructed from a layout record. A fresh figure read must supply
// the same project/id/current-or-fixed/revision/source identity before use.
function cameraCopy(value:any):CanvasViewMemory|undefined{
  if(!value||![value.width,value.height].every(n=>typeof n==='number'&&Number.isFinite(n)&&n>0)||
    !value.camera||![value.camera.scale,value.camera.x,value.camera.y].every(n=>typeof n==='number'&&Number.isFinite(n))||
    value.camera.scale<.05||value.camera.scale>8)return;
  return {width:value.width,height:value.height,camera:{scale:value.camera.scale,x:value.camera.x,y:value.camera.y}};
}
function scrollCopy(value:any):FigureViewMemory['panelScroll']{
  if(value&&[value.top,value.left].every(n=>typeof n==='number'&&Number.isFinite(n)&&n>=0))return {top:value.top,left:value.left};
}
function cameraIdentity(key:string,project:string){
  try{const a=JSON.parse(key);return Array.isArray(a)&&a.length===5&&a[0]===project&&typeof a[1]==='string'&&!!a[1]&&
    (a[2]===null||Number.isSafeInteger(a[2])&&a[2]>0)&&Number.isSafeInteger(a[3])&&a[3]>0&&
    typeof a[4]==='string'&&/^[a-f0-9]{64}$/.test(a[4]);}catch{return false;}
}
export function persistedFigureCameras(memory:FigurePanelMemory,project:string){
  return {version:1,cameras:[...memory].flatMap(([key,value])=>{
    const canvas=cameraCopy(value.canvas),panelScroll=scrollCopy(value.panelScroll);
    return cameraIdentity(key,project)&&canvas?[{key,canvas,...(panelScroll?{panelScroll}:{})}]:[];
  })};
}
export function persistentFigurePanelMemory(project:string,saved:any,onChange:(value:ReturnType<typeof persistedFigureCameras>)=>void):FigurePanelMemory{
  class CameraMemory extends Map<string,FigureViewMemory>{
    set(key:string,value:FigureViewMemory){
      value.changed=value.canvas.changed=()=>onChange(persistedFigureCameras(this,project));
      return super.set(key,value);
    }
  }
  const memory=new CameraMemory();
  if(saved?.version===1&&Array.isArray(saved.cameras))for(const entry of saved.cameras){
    if(typeof entry?.key!=='string'||!cameraIdentity(entry.key,project))continue;
    const canvas=cameraCopy(entry.canvas),panelScroll=scrollCopy(entry.panelScroll);
    if(canvas)memory.set(entry.key,{canvas,...(panelScroll?{panelScroll}:{})});
  }
  return memory;
}

export function figureViewMemory(memory:FigurePanelMemory,project:string,id:string,revision?:number,savedRevision?:number,sourceSha?:string){
  const key=JSON.stringify([project,id,revision??null,savedRevision??null,sourceSha??null]);
  let value=memory.get(key);
  if(!value){value={canvas:{}};memory.set(key,value);}
  return value;
}

// A fresh authorized current revision may retain its pane's navigation camera.
// Keep separate revision/source entries; no selection or scientific state moves.
export function inheritCanvasCamera(target:CanvasViewMemory,source:CanvasViewMemory,width:number,height:number){
  const camera=source.camera;
  if(target.camera||source.width!==width||source.height!==height||![width,height].every(value=>Number.isFinite(value)&&value>0)
    ||!camera||![camera.scale,camera.x,camera.y].every(Number.isFinite)||camera.scale<.05||camera.scale>8)return;
  Object.assign(target,{width,height,camera:{...camera}});
  target.changed?.();
}
