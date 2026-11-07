import {esc,button,pretty} from './ui.js';
import {documentMarkdown,registeredDocumentAssetURL} from './document-markdown.js';
const array=value=>Array.isArray(value)?value:[];
const objectID=id=>typeof id==='string'&&/^[A-Z]+-[a-zA-Z0-9]+$/.test(id);
export const referenceKey=ref=>`${ref.id}@${ref.revision}`;
export function exactReference(raw){
  const ref=typeof raw==='string'?{id:raw}:raw||{},id=ref.id||ref.object_id;
  if(!objectID(id))return {id:id||String(raw??''),issue:'virtual_or_unknown',message:'未解析：虚拟上下文或未知标识，未绑定成果。'};
  if(!Number.isInteger(ref.revision)||ref.revision<1)return {id,issue:'revision_missing',message:'未解析：没有确切采用修订；不会读取最新版本。'};
  if(Object.hasOwn(ref,'sha256')&&(typeof ref.sha256!=='string'||!/^[a-f0-9]{64}$/.test(ref.sha256)))return {id,revision:ref.revision,issue:'hash_invalid',message:'未解析：登记的 SHA256 无效；不会忽略该身份约束。'};
  return {id,revision:ref.revision,...(ref.sha256?{sha256:ref.sha256}:{}),...(ref.block_id?{block_id:ref.block_id}:{})};
}
function mergeReferences(refs){
  const hashes=new Map();
  const blocked=new Map(refs.filter(ref=>['hash_invalid','hash_conflict'].includes(ref.issue)).map(ref=>[referenceKey(ref),ref]));
  for(const ref of refs)if(!ref.issue&&ref.sha256){const key=referenceKey(ref);if(!hashes.has(key))hashes.set(key,new Set());hashes.get(key).add(ref.sha256);}
  const result=new Map();
  for(let ref of refs){
    const known=hashes.get(referenceKey(ref));
    if(!ref.issue&&blocked.has(referenceKey(ref))){const failure=blocked.get(referenceKey(ref));ref={...ref,issue:failure.issue,message:failure.message};}
    else if(!ref.issue&&known?.size>1)ref={...ref,issue:'hash_conflict',message:'未解析：同一来源修订登记了不同 SHA256；请先核对引用。'};
    else if(!ref.issue&&known?.size===1)ref={...ref,sha256:[...known][0]};
    result.set(`${referenceKey(ref)}#${ref.block_id||''}:${ref.issue||''}`,ref);
  }
  return [...result.values()];
}
export function registeredSourceReferences(object){
  const refs=[];
  for(const container of [object.content,object.metadata]){
    if(!container||!Object.hasOwn(container,'source_refs'))continue;
    if(!Array.isArray(container.source_refs)){refs.push({id:'source_refs',issue:'invalid_reference_list',message:'未解析：来源登记不是固定版本引用列表。'});continue;}
    refs.push(...container.source_refs.map(exactReference));
  }
  return mergeReferences(refs);
}
export function sourceReferencePanel(object,references={},errors={}){
  const refs=registeredSourceReferences(object);
  return `<section class="registered-source-references"><h4>固定版本来源</h4>${refs.length?refs.map(ref=>{
    const failure=ref.issue?ref:errors[referenceKey(ref)],source=references[referenceKey(ref)];
    return `<div class="dependency">${failure?`<p class="reference-unresolved">${esc(failure.message)}</p>`:''}${ref.issue?'':button(source?.title||'阅读采用版本','open-reference',{...ref,consumer_id:object.id},'text-button small')}<small>${esc(ref.id)}${ref.revision?' · 采用修订 '+esc(ref.revision):''}${ref.block_id?' · 段落 '+esc(ref.block_id):''}</small>${ref.sha256?`<small>SHA256 ${esc(ref.sha256)}</small>`:'<small>未登记 SHA256；仅绑定对象与修订。</small>'}</div>`;
  }).join(''):'<p class="hint">没有固定版本来源登记。</p>'}</section>`;
}
export function claimEvidence(claim,object){
  const explicit=[...array(claim.evidence_refs),...array(claim.source_refs)].map(exactReference);
  const adopted=[...array(object.content?.source_refs),...array(object.metadata?.source_refs),...array(object.metadata?.context?.source_refs)].map(exactReference);
  const refs=[...explicit];
  for(const id of array(claim.evidence_ids)){
    if(explicit.some(ref=>ref.id===id))continue;
    const matches=adopted.filter(ref=>ref.id===id&&!ref.issue);
    const revisions=new Set(matches.map(ref=>ref.revision));
    if(revisions.size>1)refs.push({id,issue:'ambiguous_revision',message:'未解析：采用记录含多个修订，论断未明确绑定哪一版。'});
    else if(matches.length)refs.push(...matches);
    else refs.push(exactReference({id}));
  }
  const bound=refs.flatMap(ref=>{
    if(ref.issue)return [ref];
    const pins=adopted.filter(pin=>pin.id===ref.id&&pin.revision===ref.revision);
    const invalid=pins.find(pin=>pin.issue);
    if(invalid)return [{...ref,issue:invalid.issue,message:invalid.message}];
    return [ref,...pins.filter(pin=>pin.sha256).map(pin=>({...ref,sha256:pin.sha256}))];
  });
  return mergeReferences(bound);
}
export function documentReferenceStates(object){
  const content=object.content||{},refs=[...registeredSourceReferences(object),...[...array(content.components),...array(content.citations)].map(exactReference)];
  for(const claim of array(content.claims))refs.push(...claimEvidence(claim,object));
  return [...new Map(mergeReferences(refs).map(ref=>[referenceKey(ref),ref])).values()];
}
export function documentReferences(object){return documentReferenceStates(object).filter(ref=>!ref.issue);
}
export function referenceFailure(error){
  const status=error?.status;
  if(['reference_hash_mismatch','reference_hash_missing','reference_identity_mismatch','hash_invalid','hash_conflict'].includes(error?.code))return {issue:error.code,message:error.message};
  return {issue:status===401||status===403?'access_revoked':status===404?'unknown_object':'read_failed',message:status===401||status===403?'未解析：访问权限已撤回或当前身份不可读取。':status===404?'未解析：指定成果或修订不存在；未改用其他版本。':'未解析：指定修订读取失败；请重试。'};
}
export async function readExactReference(read,raw,{consumerId}={}){
  const ref=exactReference(raw);if(ref.issue)throw Object.assign(new Error(ref.message),{code:ref.issue});
  const result=await read(`/api/objects/${encodeURIComponent(ref.id)}?revision=${ref.revision}${consumerId?'&consumer='+encodeURIComponent(consumerId):''}`),source=result.object||result;
  if(source.id!==ref.id||source.revision!==ref.revision)throw Object.assign(new Error('返回身份与指定采用修订不符；来源未显示。'),{code:'reference_identity_mismatch'});
  if(ref.sha256&&!source.canonical_source_sha256)throw Object.assign(new Error('未解析：服务端未提供该修订的规范 SHA256；来源未显示。'),{code:'reference_hash_missing'});
  if(ref.sha256&&ref.sha256!==source.canonical_source_sha256)throw Object.assign(new Error('未解析：来源 SHA256 与登记值不符；来源未显示，未改用最新版本。'),{code:'reference_hash_mismatch'});
  return {source,ref,missingAnchor:!!ref.block_id&&!array(source.content?.blocks).some(b=>b.id===ref.block_id)};
}
export function renderClaims(object,references={},errors={}){
  const claims=array(object.content?.claims);if(!claims.length)return '';
  return `<section class="document-claims"><h2>论断、依据与限制</h2><p class="hint">以下逐条呈现已保存论断；来源链接表示登记的依据，不代表支持关系已获独立确认。</p>${claims.map((claim,i)=>`<article class="claim-card" data-claim-index="${i}"><h3>论断 ${i+1}</h3><div class="prose">${documentMarkdown(claim.text||'未登记论断文字')}</div><div class="claim-limitation"><strong>限制</strong><div class="prose">${documentMarkdown(claim.limitation||'未登记限制')}</div></div><ul class="claim-evidence">${claimEvidence(claim,object).map(ref=>{const problem=ref.issue?ref:errors[referenceKey(ref)],source=references[referenceKey(ref)];return `<li>${problem?`<span class="reference-unresolved">${esc(ref.id)}${ref.revision?` @${ref.revision}`:''} · ${esc(problem.message)}</span>${!ref.issue?button('重试读取指定版本','open-reference',ref,'text-button'):''}`:`${button(source?.title||ref.id,'open-reference',ref,'text-button')}<small>${esc(ref.id)} · 采用修订 ${ref.revision}${ref.block_id?` · 段落 ${esc(ref.block_id)}`:' · 未登记段落锚点'}</small>`}</li>`;}).join('')||'<li class="reference-unresolved">未登记逐论断证据身份。</li>'}</ul></article>`).join('')}</section>`;
}
export function referenceReading({source,ref,missingAnchor}){
  const content=source.content||{},preview=registeredDocumentAssetURL(source.metadata?.last_export?.assets?.['figure.png']||content.preview),blocks=array(content.blocks);
  return `<p>只读采用来源 · ${esc(ref.id)} @${ref.revision}。${source.canonical_source_sha256?`SHA256 ${esc(source.canonical_source_sha256)}。`:""}关闭后返回原成果；不会恢复或覆盖工作版本。</p>${missingAnchor?`<p class="notice warning">指定段落 ${esc(ref.block_id)} 在此修订中不存在。以下仅展示该修订完整内容，未改用其他段落。</p>`:''}${preview?`<img class="reference-preview" src="${esc(preview)}" alt="${esc(source.title)}">`:''}<article class="reference-document">${blocks.map(b=>`<section class="reference-block ${b.id===ref.block_id?'reference-target':''}" data-reference-block="${esc(b.id)}"><small>段落 ${esc(b.id)}</small><div class="prose">${documentMarkdown(b.text,content.resources)}</div></section>`).join('')}${content.caption?`<div class="prose">${documentMarkdown(content.caption)}</div>`:''}${!blocks.length&&!content.caption?`<dl class="reference-fields">${Object.entries(content).map(([key,value])=>`<dt>${esc(key)}</dt><dd>${esc(typeof value==='string'?value:pretty(value))}</dd>`).join('')}</dl>`:''}</article>`;
}
