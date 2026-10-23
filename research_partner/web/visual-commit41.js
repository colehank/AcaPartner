const clone=value=>structuredClone(value);
/** JSON object order is transport formatting; array order and values are content. */
export function sameJSON41(a,b){
  if(a===b)return true;
  if(!a||!b||typeof a!=='object'||typeof b!=='object'||Array.isArray(a)!==Array.isArray(b))return false;
  if(Array.isArray(a))return a.length===b.length&&a.every((value,index)=>sameJSON41(value,b[index]));
  const keys=Object.keys(a).filter(key=>a[key]!==undefined),other=Object.keys(b).filter(key=>b[key]!==undefined);
  return keys.length===other.length&&keys.every(key=>Object.hasOwn(b,key)&&sameJSON41(a[key],b[key]));
}
const same=sameJSON41;
const id=ref=>ref?.id||ref?.object_id;
const sourceContent=content=>Object.fromEntries(Object.entries(content||{}).filter(([key])=>!['overlays','caption'].includes(key)));

/** The visual button cannot authorize a changed script, input, spec or configuration. */
export function visualCommitRequest41({object,draft,trail,requestKey}) {
  if(object?.kind!=='figure'||!same(sourceContent(object.content),sourceContent(draft?.content)))
    throw new Error('生成来源已有改动。请先单独保存来源并核对执行授权；“采用视觉改动”不会执行新的来源。');
  const value={id:object.id,expected_revision:object.revision,overlays:clone(draft.content.overlays||[]),request_key:requestKey};
  if(draft.title!==object.title)value.title=draft.title;
  if(draft.content.caption!==object.content.caption)value.caption=draft.content.caption||'';
  if(trail){
    const base=trail.manuscriptBase,index=trail.location?.index,ref=base?.content?.components?.[index];
    const entry=trail.entryComponents,entryRef=entry?.[index];
    if(!base||!Number.isInteger(index)||!Array.isArray(entry)||id(ref)!==object.id||ref.revision!==trail.adoptedRevision||id(entryRef)!==id(ref)||entryRef.revision!==ref.revision)
      throw new Error('原稿中这一处图的保存身份与编辑入口不一致，草稿保留；请返回原稿核对位置。');
    if(base.content.components.filter(item=>id(item)===object.id).length>1&&!same(base.content.components,entry))
      throw new Error('本稿重复引用此图，且本机引用位置另有未保存改动。请先保存这些位置，再从所需位置进入，避免更新另一处引用。');
    value.manuscript={id:base.id,expected_revision:base.revision,component_index:index,
      component_id:object.id,component_revision:ref.revision,component_ref:clone(ref)};
  }
  return value;
}

/** Advance only the committed figure pin; never submit or replace pending prose. */
export function rebaseVisualDraft41({base,updated,index,local}) {
  const before=base?.content?.components?.[index],after=updated?.content?.components?.[index];
  if(!before||!after||base.id!==updated.id||updated.revision<=base.revision||id(before)!==id(after))
    return {ok:false,reason:'原稿回执的图位置或版本不符，本机草稿保留。'};
  const expected=clone(base.content);expected.components[index]=clone(after);
  if(!same(expected,updated.content)||base.title!==updated.title)
    return {ok:false,reason:'原稿还有此次图修改以外的变化，本机草稿保留。'};
  if(!local)return {ok:true,local:null,changed:false};
  if(local.base_revision===updated.revision)return {ok:true,local:clone(local),changed:!same(local.content,updated.content)||local.title!==updated.title};
  const ref=local.content?.components?.[index];
  if(local.base_revision!==base.revision||id(ref)!==id(before)||ref?.revision!==before.revision||
    local.content.components.length!==base.content.components.length||
    base.content.components.some((item,i)=>id(item)!==id(local.content.components[i]))||
    base.content.components.filter(item=>id(item)===id(before)).length>1&&!same(base.content.components,local.content.components))
    return {ok:false,reason:'本机稿件的基础版本或图顺序另有变化；服务器已保存图修改，本机内容完整保留，请核对差异。'};
  const next=clone(local),pin=next.content.components[index];
  pin.revision=after.revision;
  for(const key of ['sha256','source_sha256']){if(Object.hasOwn(after,key))pin[key]=after[key];else delete pin[key];}
  next.base_revision=updated.revision;
  return {ok:true,local:next,changed:!same(next.content,updated.content)||next.title!==updated.title};
}

/** Keep undo/redo for prose without silently undoing the newly committed pin.
 * An ambiguous older structural snapshot forms a boundary; retain it separately.
 */
export function rebaseVisualHistory41({base,updated,index,history=[]}) {
  const rebased=[];
  for(let i=history.length-1;i>=0;i--){
    const result=rebaseVisualDraft41({base,updated,index,local:{...history[i],base_revision:base.revision}});
    if(!result.ok)return {history:rebased,retained:clone(history.slice(0,i+1))};
    const {base_revision,...draft}=result.local;rebased.unshift(draft);
  }
  return {history:rebased,retained:[]};
}
