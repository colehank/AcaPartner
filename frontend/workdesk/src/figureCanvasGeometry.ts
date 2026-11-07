// Visual layout coordinates only. Scientific coordinates are changed solely
// through a render manifest's explicit, supported interaction matrix.
export type CanvasBox=[number,number,number,number];
export type CanvasItem={id:string,box:number[]};
export type Alignment='left'|'right'|'top'|'bottom'|'horizontal-center'|'vertical-center'|'horizontal-distribute'|'vertical-distribute';
export type Corner='nw'|'ne'|'sw'|'se';
// Browser PointerEvent coordinates use a different float precision from CSS
// transformed rectangles. Resolve that subpixel noise to a stable visual unit;
// numeric property inputs and stored/scientific values are never rounded here.
export function pointerLayoutDelta(pixels:number,extent:number){
  if(!Number.isFinite(pixels)||!Number.isFinite(extent)||extent<=0)throw new Error('画布屏幕尺寸无效。');
  return Math.round(pixels/extent*1e6)/1e6;
}
export function validCanvasBox(box:unknown):box is CanvasBox{
  return Array.isArray(box)&&box.length===4&&box.every(x=>typeof x==='number'&&Number.isFinite(x))&&box[0]>=0&&box[1]>=0&&box[2]>0&&box[3]>0&&box[0]+box[2]<=1&&box[1]+box[3]<=1;
}
export function layoutBounds(items:CanvasItem[]):CanvasBox{
  if(!items.length||new Set(items.map(item=>item.id)).size!==items.length||items.some(item=>!validCanvasBox(item.box)))throw new Error('布局需要唯一图位和完整有效边界。');
  const x=Math.min(...items.map(item=>item.box[0])),y=Math.min(...items.map(item=>item.box[1]));
  return [x,y,Math.max(...items.map(item=>item.box[0]+item.box[2]))-x,Math.max(...items.map(item=>item.box[1]+item.box[3]))-y];
}
export function translateLayout(items:CanvasItem[],dx:number,dy:number):CanvasItem[]{
  layoutBounds(items);if(!Number.isFinite(dx)||!Number.isFinite(dy))throw new Error('位移必须是有限数值。');
  const x=Math.max(Math.max(...items.map(p=>-p.box[0])),Math.min(dx,Math.min(...items.map(p=>1-p.box[0]-p.box[2]))));
  const y=Math.max(Math.max(...items.map(p=>-p.box[1])),Math.min(dy,Math.min(...items.map(p=>1-p.box[1]-p.box[3]))));
  return items.map(p=>({id:p.id,box:[p.box[0]+x,p.box[1]+y,p.box[2],p.box[3]]}));
}
export function resizeLayout(items:CanvasItem[],corner:Corner,dx:number,dy:number):CanvasItem[]{
  const [x,y,w,h]=layoutBounds(items);
  if(!['nw','ne','sw','se'].includes(corner)||!Number.isFinite(dx)||!Number.isFinite(dy))throw new Error('控制柄及位移无效。');
  const minW=Math.min(w,Math.max(...items.map(p=>w*.005/p.box[2]))),minH=Math.min(h,Math.max(...items.map(p=>h*.005/p.box[3])));
  const west=corner.endsWith('w'),north=corner.startsWith('n');
  const left=west?Math.min(x+w-minW,Math.max(0,x+dx)):x;
  const top=north?Math.min(y+h-minH,Math.max(0,y+dy)):y;
  const right=west?x+w:Math.max(x+minW,Math.min(1,x+w+dx));
  const bottom=north?y+h:Math.max(y+minH,Math.min(1,y+h+dy));
  const sx=(right-left)/w,sy=(bottom-top)/h;
  return items.map(p=>({id:p.id,box:[left+(p.box[0]-x)*sx,top+(p.box[1]-y)*sy,p.box[2]*sx,p.box[3]*sy]}));
}
export function alignLayout(items:CanvasItem[],mode:Alignment):CanvasItem[]{
  if(items.length<2)throw new Error('请选择至少两个布局图位。');
  const [x,y,w,h]=layoutBounds(items),next=items.map(p=>({id:p.id,box:[...p.box]}));
  if(mode==='horizontal-distribute'||mode==='vertical-distribute'){
    if(items.length<3)throw new Error('等距分布需要至少三个图位。');
    const axis=mode==='horizontal-distribute'?0:1,size=axis+2;
    const sorted=[...next].sort((a,b)=>a.box[axis]-b.box[axis]||a.id.localeCompare(b.id));
    const first=sorted[0].box[axis],end=sorted.at(-1)!.box[axis]+sorted.at(-1)!.box[size];
    const gap=(end-first-sorted.reduce((sum,p)=>sum+p.box[size],0))/(sorted.length-1);
    let cursor=first;for(const p of sorted){p.box[axis]=cursor;cursor+=p.box[size]+gap;}
  }else for(const p of next){
    if(mode==='left')p.box[0]=x;else if(mode==='right')p.box[0]=x+w-p.box[2];
    else if(mode==='top')p.box[1]=y;else if(mode==='bottom')p.box[1]=y+h-p.box[3];
    else if(mode==='horizontal-center')p.box[0]=x+(w-p.box[2])/2;
    else if(mode==='vertical-center')p.box[1]=y+(h-p.box[3])/2;
    else throw new Error('未知对齐动作。');
  }
  return next;
}
export function boxSelection(items:CanvasItem[],region:number[]):string[]{
  if(region.length!==4||region.some(x=>!Number.isFinite(x))||region[2]<0||region[3]<0)throw new Error('框选范围无效。');
  return items.filter(p=>p.box.length===4&&p.box.every(Number.isFinite)&&p.box[0]<region[0]+region[2]&&p.box[0]+p.box[2]>region[0]&&p.box[1]<region[1]+region[3]&&p.box[1]+p.box[3]>region[1]).map(p=>p.id);
}

export function artistDelta(member:any,layers:{target:string,properties:Record<string,any>}[],dx:number,dy:number):{target:string,property:string,value:number[]}|null{
  const drag=member?.interaction?.drag;
  if(!drag?.enabled||drag.screen_coordinates!=='whole_figure_normalized_top_left'||!member.supported_properties?.includes(drag.property))return null;
  const matrix=drag.delta_matrix,existing=layers.find(p=>p.target===member.id)?.properties;
  const value=existing&&Object.hasOwn(existing,drag.property)?existing[drag.property]:drag.value;
  if(!Number.isFinite(dx)||!Number.isFinite(dy)||!Array.isArray(value)||![2,4].includes(value.length)||value.some(n=>typeof n!=='number'||!Number.isFinite(n))||!Array.isArray(matrix)||matrix.length!==2||matrix.some(row=>!Array.isArray(row)||row.length!==2||row.some(n=>typeof n!=='number'||!Number.isFinite(n))))throw new Error('元素缺少可重放的明确坐标变换。');
  const next=[...value];next[0]+=matrix[0][0]*dx+matrix[0][1]*dy;next[1]+=matrix[1][0]*dx+matrix[1][1]*dy;
  if(next.some(n=>!Number.isFinite(n)))throw new Error('元素位移超出有限坐标。');
  return {target:member.id,property:drag.property,value:next};
}

export function artistResize(member:any,layers:{target:string,properties:Record<string,any>}[],corner:Corner,dx:number,dy:number){
  const initial=artistDelta(member,layers,0,0),drag=member?.interaction?.drag;
  if(!initial||member.type!=='axes'||initial.property!=='position'||initial.value.length!==4||drag.delta_matrix[0][1]!==0||drag.delta_matrix[1][0]!==0)return null;
  if(!['nw','ne','sw','se'].includes(corner)||!Number.isFinite(dx)||!Number.isFinite(dy))throw new Error('轴区控制柄位移无效。');
  const value=[...initial.value],x=drag.delta_matrix[0][0]*dx,y=drag.delta_matrix[1][1]*dy;
  if(corner.endsWith('w')){value[0]+=x;value[2]-=x;}else value[2]+=x;
  if(corner.startsWith('n'))value[3]+=y;else{value[1]+=y;value[3]-=y;}
  if(value.some(n=>!Number.isFinite(n))||value[2]<=0||value[3]<=0)throw new Error('轴区宽高必须为正；原布局保留。');
  return {...initial,value};
}
