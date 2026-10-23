import {figureManifest,figureDragCapability,figurePreviewState,overlayLayers,figurePropertyValue,figureValueKey} from './figure-properties.js';

export function dragFigureValue(drag,dx,dy,width,height){
  if(!drag?.enabled||![dx,dy,width,height].every(Number.isFinite)||width<=0||height<=0)throw new Error('缺少可验证的拖动坐标。');
  const m=drag.delta_matrix,value=[...drag.value];
  value[0]+=m[0][0]*dx/width+m[0][1]*dy/height;
  value[1]+=m[1][0]*dx/width+m[1][1]*dy/height;
  if(value.some(x=>!Number.isFinite(x)))throw new Error('位置超出有限数值范围。');
  return value;
}

// Pointer coordinates use screen pixels; outline transforms use the unscaled
// image's CSS pixels. Keep the renderer's normalized scientific mapping intact.
function figureImageGeometry(root){
  const image=root.querySelector('[data-figure-image]'),box=image?.getBoundingClientRect();
  if(!box?.width||!box.height)return null;
  const width=image.offsetWidth||box.width,height=image.offsetHeight||box.height;
  return {box,width,height,scaleX:box.width/width,scaleY:box.height/height};
}

export function figureArtistAnchor(object,id){
  const output=object.metadata?.last_export,source=output?.provenance;
  if(!source||source.object_id!==object.id||!Number.isInteger(source.revision)||!source.source_sha256||!output.manifest?.some(item=>item.id===id))throw new Error('此元素没有已登记的渲染身份；可以给整张图添加批注。');
  return {artist_id:id,object_id:id,render_source:{object_id:source.object_id,revision:source.revision,source_sha256:source.source_sha256}};
}

// The displayed pixels and the region anchor must identify the same saved image.
export function figureSavedPreviewSha(object){
  const output=object?.metadata?.last_export,source=output?.provenance;
  const current=output?.status==='generated'&&!Object.hasOwn(output,'preview_identity')&&!source?.preview_identity&&!output?.replay?.failures?.length&&source?.object_id===object?.id&&source?.revision===object?.revision&&source?.source_sha256&&(!object.canonical_source_sha256||source.source_sha256===object.canonical_source_sha256);
  const asset=current?output?.assets?.['figure.png']:null,preview=asset||object?.content?.preview;
  return typeof preview==='string'?preview:preview?.sha256||preview?.sha;
}

export function figureRegionAnchor(object,bbox=[0,0,1,1]){
  if(object.kind!=='figure'||!Array.isArray(bbox)||bbox.length!==4||bbox.some(x=>typeof x!=='number'||!Number.isFinite(x)||x<0)||bbox[2]<=0||bbox[3]<=0||bbox[0]+bbox[2]>1+1e-9||bbox[1]+bbox[3]>1+1e-9)throw new Error('区域须位于整幅图像内，使用左上为原点的归一化 [x, y, 宽, 高]。');
  const sha=figureSavedPreviewSha(object);
  if(!sha||!Number.isInteger(object.revision)||!object.canonical_source_sha256)throw new Error('缺少已保存的原图版本或图像身份；请先保存并重新读取。');
  return {figure_region:{bbox:[...bbox],coordinates:'whole_figure_normalized_top_left'},render_source:{object_id:object.id,revision:object.revision,source_sha256:object.canonical_source_sha256,preview_sha256:sha}};
}

// This only moves an explicit outline. It never rewrites the rendered bitmap.
export function updateFigurePreview(root,{object,content,dirty=false}){
  const state=figurePreviewState(object,content,{dirty}),status=root.querySelector('[data-figure-status]');
  if(status){status.textContent=content.editable_source_available===false?'原图 · 无可分解对象':object.metadata?.last_export?.preview_identity?'草稿预览 · 尚未采用':state.pending?'有未采用改动': '已保存图形';status.dataset.pending=String(state.pending);}
  const summary=root.querySelector('[data-figure-overlay-summary]');
  if(summary){summary.textContent=state.changes.map(x=>`${x.id} · ${x.property} = ${JSON.stringify(x.value)}`).join('\n');summary.hidden=!state.changes.length;}
  const manifest=figureManifest(object,content),layers=overlayLayers(content);
  for(const hit of root.querySelectorAll('[data-figure-hit]')){
    const item=manifest.find(x=>x.id===hit.dataset.id);if(!item)continue;
    const drag=figureDragCapability(item,content,object),layer=layers.find(x=>(x.target||x.object_id||x.id)===item.id);
    hit.style.cursor=drag.enabled?'grab':'pointer';hit.style.touchAction=drag.enabled?'none':'auto';
    hit.title=`${item.label||item.id} · ${drag.enabled?'拖动位置；重绘后更新实际图像':drag.reason}`;
    hit.dataset.dragEnabled=String(drag.enabled);hit.style.transform='';hit.style.borderStyle='';hit.style.borderColor='';hit.style.background='';
    const mapping=item.interaction?.drag;
    if(!mapping?.enabled)continue;
    const value=figurePropertyValue(item,layer,mapping.property),base=item[mapping.property],m=mapping.delta_matrix;
    if(!Array.isArray(value)||!Array.isArray(base)||!m||JSON.stringify(value)===JSON.stringify(base))continue;
    const determinant=m[0][0]*m[1][1]-m[0][1]*m[1][0];if(!determinant)continue;
    const x=value[0]-base[0],y=value[1]-base[1],dx=(m[1][1]*x-m[0][1]*y)/determinant,dy=(-m[1][0]*x+m[0][0]*y)/determinant;
    const image=figureImageGeometry(root);
    if(image&&Number.isFinite(dx)&&Number.isFinite(dy)){hit.style.transform=`translate(${dx*image.width}px,${dy*image.height}px)`;hit.style.borderStyle='dashed';hit.style.borderColor='#a05e15';hit.style.background='#f4bc6126';}
  }
  return state;
}

export function bindFigureInteraction(root,{object,content,selectedId,onSelect=()=>{},onOverlay=()=>{},onAnnotate=()=>{},onOpenCode=()=>{},onError=()=>{},isCurrent=()=>true}){
  const disposers=[],manifest=figureManifest(object,content);let cancelDrag=()=>{},suppressClick=false;
  const listen=(node,type,fn)=>{node.addEventListener(type,fn);disposers.push(()=>node.removeEventListener(type,fn));};
  const select=(id,redraw=true)=>{onSelect(id,{redraw});for(const node of root.querySelectorAll('[data-figure-hit]'))node.classList.toggle('selected',node.dataset.id===id);};
  for(const hit of root.querySelectorAll('[data-figure-hit]')){
    const id=hit.dataset.id,item=manifest.find(x=>x.id===id);if(!item)continue;
    listen(hit,'click',e=>{e.preventDefault();e.stopPropagation();if(suppressClick){suppressClick=false;return;}select(id);});
    listen(hit,'dblclick',e=>{e.preventDefault();e.stopPropagation();select(id);root.querySelector('.object-inspector [data-edit^="overlay-"]')?.focus();});
    listen(hit,'contextmenu',e=>{e.preventDefault();e.stopPropagation();select(id);try{onAnnotate(figureArtistAnchor(object,id));}catch(error){onError(error);}});
    listen(hit,'pointerdown',e=>{
      if(e.button!==0||!isCurrent())return;
      const drag=figureDragCapability(item,content,object);if(!drag.enabled)return;
      e.preventDefault();e.stopPropagation();cancelDrag();select(id,false);
      const geometry=figureImageGeometry(root);if(!geometry)return;const {box,scaleX,scaleY}=geometry;
      const x=e.clientX,y=e.clientY,oldTransform=hit.style.transform;let moved=false,dx=0,dy=0;
      hit.setPointerCapture?.(e.pointerId);
      const move=event=>{if(event.pointerId!==e.pointerId)return;dx=event.clientX-x;dy=event.clientY-y;moved ||= Math.abs(dx)+Math.abs(dy)>2;if(moved){hit.style.transform=`${oldTransform} translate(${dx/scaleX}px,${dy/scaleY}px)`;hit.style.borderStyle='dashed';hit.style.borderColor='#a05e15';const status=root.querySelector('[data-figure-status]');if(status)status.textContent='正在预览位置覆盖；松开提交草稿，重绘后更新实际图像。';}};
      const cleanup=()=>{hit.removeEventListener('pointermove',move);hit.removeEventListener('pointerup',end);hit.removeEventListener('pointercancel',cancel);hit.removeEventListener('lostpointercapture',cancel);cancelDrag=()=>{};};
      const cancel=()=>{cleanup();updateFigurePreview(root,{object,content});};
      const end=event=>{if(event.pointerId!==e.pointerId)return;move(event);cleanup();suppressClick=moved;if(moved&&isCurrent())try{onOverlay(id,drag.property,dragFigureValue(drag,dx,dy,box.width,box.height));}catch(error){onError(error);}else updateFigurePreview(root,{object,content});};
      hit.addEventListener('pointermove',move);hit.addEventListener('pointerup',end);hit.addEventListener('pointercancel',cancel);hit.addEventListener('lostpointercapture',cancel);cancelDrag=cancel;
    });
  }
  const code=root.querySelector('[data-action="figure-code"]');if(code)listen(code,'click',e=>{e.preventDefault();e.stopPropagation();onOpenCode();});
  updateFigurePreview(root,{object,content});
  return ()=>{cancelDrag();disposers.forEach(fn=>fn());};
}

const contentOf=source=>source.draft?.content||source.content||source.object?.content;
const sourceObject=source=>source.object||source;
const checkSaved=(saved,source)=>{const object=saved?.object||saved;if(object?.id!==source.id||!Number.isInteger(object.revision)||object.revision<source.revision)throw new Error('保存结果不属于捕获的图对象。');return object;};

export function createFigureRenderSession({source,isCurrent=()=>true,saveSource,request,onResult=()=>{}}){
  const captured=structuredClone(source);let pending=false;
  return {source:structuredClone(captured),async render(){
    if(pending)return null;pending=true;
    try{
      let target=sourceObject(captured);
      if(captured.dirty){if(!saveSource)throw new Error('请先保存图草稿。');target=checkSaved(await saveSource(structuredClone(captured)),captured);}
      if(figureValueKey(target.content)!==figureValueKey(contentOf(captured)))throw new Error('保存内容与捕获的图草稿不一致；未启动重绘。');
      const result=await request('figure.render',{id:target.id,expected_revision:target.revision});
      if(result?.provenance?.object_id!==target.id||result?.provenance?.revision!==target.revision)throw new Error('重绘回执与请求的图修订不一致。');
      const receipt={result,target:{id:target.id,revision:target.revision},active:isCurrent(captured)};
      // The host may present the receipt, but must not force-open a later draft.
      onResult(receipt);return receipt;
    }finally{pending=false;}
  }};
}

export function createFigureCodeSession({source,readAsset,registerAsset,saveSource,isCurrent=()=>true}){
  const captured=structuredClone(source),object=sourceObject(captured),content=structuredClone(contentOf(captured));
  const imported=content.script_asset||content.script,asset=imported||object.metadata?.last_export?.assets?.['plot_source.py'];
  const sha=typeof asset==='object'?asset?.sha:asset;
  let original=null,pending=false;
  return {source:structuredClone(captured),sha,async read(){
    if(!sha||!/^[0-9a-f]{64}$/i.test(sha))throw new Error('没有已登记的脚本资产。请先上传脚本，或重绘结构化数据取得生成脚本。');
    const text=await readAsset(sha);if(typeof text!=='string')throw new Error('脚本读取结果不是文本。');original=text;return {text,sha,generated:!imported};
  },async save(text){
    if(pending)throw new Error('脚本保存仍在进行。');if(original===null)throw new Error('先读取实际脚本再编辑。');if(typeof text!=='string'||!text.trim())throw new Error('脚本不能为空。');
    if(text===original)return {changed:false,sha,requiresAuthorization:false};
    pending=true;
    try{
      const bytes=new TextEncoder().encode(text),expected=Array.from(new Uint8Array(await globalThis.crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
      const registered=await registerAsset({text,filename:'figure_source.py',project_id:object.project_id,source:`Edited figure script ${object.id}@${captured.revision}; previous ${sha}`});
      if(registered?.sha!==expected)throw new Error('登记脚本字节与编辑内容不一致；未关联资产。');
      const receipt={changed:true,sha:registered.sha,previousSha:sha,asset:registered,requiresAuthorization:true,attached:false};
      if(!isCurrent(captured))return receipt;
      const next={...content,script_asset:registered.sha};delete next.script;
      if(!imported)next.parameters={...(next.parameters||{}),spec:structuredClone(next.spec)};
      let saved;
      try{saved=checkSaved(await saveSource(structuredClone(captured),next),captured);}
      catch(error){error.figureScriptReceipt=receipt;throw error;}
      if(saved.content?.script_asset!==registered.sha)throw new Error('保存回执未关联新脚本；请检查已登记资产。');
      return {...receipt,attached:true,object:saved};
    }finally{pending=false;}
  }};
}
