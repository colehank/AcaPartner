// Read-only location discovery over the current server-visible catalog.
import {esc,button} from './ui.js';
import {exactReference,documentReferences} from './claim-evidence.js';
const array=x=>Array.isArray(x)?x:[];
const fingerprint=x=>JSON.stringify(x);
export function impactLocations(consumer,sourceId){
 const c=consumer.content||{},rows=[];
 function add(raw,locator,label){
  if(!raw||typeof raw!=='object'||(raw.id||raw.object_id)!==sourceId)return;
  let ref=exactReference(raw);
  if(!ref.issue){const merged=documentReferences({...consumer,content:{...c,components:[...array(c.components),raw]}}).find(x=>x.id===ref.id&&x.revision===ref.revision);ref=merged||{...ref,issue:'source_reference_conflict'};}
  rows.push({consumer_id:consumer.id,consumer_revision:consumer.revision,source_id:sourceId,ref,locator,label,
   fingerprint:fingerprint(raw),issue:ref.issue||null});
 }
 array(c.components).forEach((ref,index)=>add(ref,{kind:'component',index},`组成成果 · 第 ${index+1} 项`));
 array(c.pages).forEach((page,pageIndex)=>array(page.objects).forEach(item=>{
  if(item.component_id!==sourceId)return;
  const duplicate=!page.id||!item.id||array(c.pages).filter(x=>x.id===page.id).length!==1||array(page.objects).filter(x=>x.id===item.id).length!==1;
  add({id:item.component_id,revision:item.component_revision},
   {kind:'canvas',page_id:page.id,item_id:item.id,asset:item.asset||item.src||item.asset_id||null},
   `第 ${pageIndex+1} 页 · ${page.title||page.id||'未登记页身份'} · 对象 ${item.id||'未登记身份'}`);
  if(duplicate)rows.at(-1).issue='ambiguous_location';
 }));
 return rows;
}
export function assertImpactLocation(consumer,pin){
 if(consumer?.id!==pin.consumer_id||consumer.revision!==pin.consumer_revision)throw new Error('成果修订已变化；请重新查看影响位置。当前草稿保留。');
 const found=impactLocations(consumer,pin.source_id).find(row=>fingerprint(row.locator)===fingerprint(pin.locator)&&row.fingerprint===pin.fingerprint&&fingerprint(row.ref)===fingerprint(pin.ref));
 if(!found||found.issue)throw new Error('引用或页／对象位置已经变化或无法唯一识别；未跳到其他位置。请重新查看影响位置。');
 return found;
}
export function sourceImpacts(source,objects,relations=[]){
 return array(objects).flatMap(consumer=>{
  if(consumer.id===source.id)return [];
  const locations=impactLocations(consumer,source.id);if(!locations.length)return [];
  const relation=array(relations).find(r=>r.src===consumer.id&&r.dst===source.id&&r.type==='uses');
  return [{consumer:{id:consumer.id,title:consumer.title,revision:consumer.revision,kind:consumer.kind,archived:consumer.archived},locations,relation}];
 });
}
export function locationButton(row){
 const problem=row.issue?`<p class="reference-unresolved">位置或采用身份不完整（${esc(row.issue)}）；不会定位到替代位置。</p>`:'';
 return `<div class="impact-location"><small>${esc(row.label)} · 来源 ${esc(row.source_id)} @${esc(row.ref.revision||'未登记')}</small>${row.locator.asset?`<small>当前图像 SHA ${esc(row.locator.asset)}</small>`:''}${problem}${!row.issue?button('定位引用位置','source-impact-locate',{pin:fingerprint(row)},'text-button small'):''}</div>`;
}
export function consumerImpactLocations(consumer,sourceId){
 const rows=impactLocations(consumer,sourceId);return rows.length?`<div data-consumer-impact>${rows.map(locationButton).join('')}</div>`:'<small>仅登记关系；未发现受支持的组成组件或画布引用位置。</small>';
}
export function impactPanel(source,groups){
 return `<p>源成果 ${esc(source.id)} · 服务器修订 ${esc(source.revision)}。以下列出当前访问范围内已保存的组成组件与画布引用，不包含纯文字提及或未登记的引用。打开位置不会采用新版；采用仍需在目标成果明确操作。</p>${groups.length?groups.map(group=>`<article class="dependency" data-impact-consumer="${esc(group.consumer.id)}"><strong>${esc(group.consumer.title)}</strong><small>${esc(group.consumer.id)} · 修订 ${esc(group.consumer.revision)}${group.consumer.archived?' · 已归档':''}</small>${group.locations.map(row=>`${locationButton(row)}<small>${row.ref.revision===source.revision?'采用当前源修订':'采用旧版或不同源修订；未自动替换'}</small>`).join('')}${group.relation?.metadata?.decision?`<p class="hint">最近显式决定：${group.relation.metadata.decision.action==='retain'?'保留旧版':'接纳新版'}；当时看到源修订 ${esc(group.relation.metadata.decision.observed_revision)}。</p>`:''}</article>`).join(''):'<p>当前可读范围内未发现受支持的采用位置；不能据此断言其他项目或未登记引用没有使用本成果。</p>'}`;
}
