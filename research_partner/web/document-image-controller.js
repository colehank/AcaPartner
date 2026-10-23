import {imageBinding,registeredDocumentAssetURL,updateDocumentImage} from './document-markdown.js';

export function captureDocumentTarget(state){
  return {project_id:state.project,object_id:state.object?.id||null,revision:state.object?.revision||null,
    draft:state.draft,serialized:JSON.stringify(state.draft),view:state.view,selectedBlock:state.selectedBlock};
}
export function documentTargetIsCurrent(state,target){
  return !state.authGate&&state.project===target.project_id&&(state.object?.id||null)===target.object_id&&
    (state.object?.revision||null)===target.revision&&state.draft===target.draft&&JSON.stringify(state.draft)===target.serialized&&state.view===target.view;
}
export async function uploadAssetFile(file,metadata,projectId,action){
  if(!projectId)throw new Error('上传缺少发起项目；未登记文件。');
  const buffer=new Uint8Array(await file.arrayBuffer());let binary='';
  for(let i=0;i<buffer.length;i+=32768)binary+=String.fromCharCode(...buffer.subarray(i,i+32768));
  return action('asset.import',{...metadata,project_id:projectId,filename:file.name,base64:btoa(binary),source:metadata.source||'user selected upload'});
}
export function decodeDocumentImage(url,ImageType=globalThis.Image){
  if(!/^\/api\/assets\/[a-f0-9]{64}$/.test(url))return Promise.reject(new Error('图像必须是本研究空间已登记的资产。'));
  if(!ImageType)return Promise.reject(new Error('当前客户端无法解码图像；未应用图片绑定。'));
  return new Promise((resolve,reject)=>{
    const image=new ImageType();let done=false;
    const finish=error=>{if(done)return;done=true;clearTimeout(timer);image.onload=null;image.onerror=null;if(error){image.src='';reject(error);}else resolve({width:image.naturalWidth,height:image.naturalHeight});};
    const accept=()=>finish(image.naturalWidth>0&&image.naturalHeight>0?null:new Error('图像没有可用尺寸；未应用图片绑定。'));
    const timer=setTimeout(()=>finish(new Error('图像解码超时；资产回执保留，未应用绑定。')),15000);
    image.onerror=()=>finish(new Error('登记文件无法解码为图像；未应用图片绑定。'));
    if(typeof image.decode!=='function')image.onload=accept;
    image.src=url;
    if(typeof image.decode==='function')image.decode().then(accept,()=>finish(new Error('登记文件无法解码为图像；未应用图片绑定。')));
  });
}
export async function applyDocumentImage({state,target,selection,values,file,upload,inspect,decode=decodeDocumentImage,retain=()=>{},commit,newBlockId,isActive=()=>true}){
  const current=()=>documentTargetIsCurrent(state,target)&&isActive();
  const stale=receipt=>{if(receipt)retain({...receipt,outcome:'not_applied'});return {applied:false,reason:'target_changed',receipt};};
  if(!current())return stale(null);
  // Validate alias syntax before an upload. This placeholder is never used as a
  // resource: an actual registered and decoded asset is mandatory below.
  imageBinding(values.reference,file?'0'.repeat(64):values.asset);
  let receipt=null;
  try{
    let sha=values.asset;
    if(file){
      const result=await upload(file,{provenance:'unverified_import',source:'User selected image for this document'},target.project_id);
      sha=result.sha;receipt={sha,filename:result.filename||file.name,project_id:target.project_id,object_id:target.object_id,outcome:'registered'};retain(receipt);
      if(!current())return stale(receipt);
    }
    const binding=imageBinding(values.reference,sha),info=await inspect(binding.value.asset,target.project_id);
    receipt={sha:binding.value.asset,filename:info.filename||file?.name||'',project_id:target.project_id,object_id:target.object_id,outcome:'inspected'};retain(receipt);
    if(!current())return stale(receipt);
    const url=registeredDocumentAssetURL(info.url);
    if(info.sha!==binding.value.asset||info.project_id!==target.project_id||url!==`/api/assets/${binding.value.asset}`||!['image/png','image/jpeg'].includes(info.media_type)||info.supported_image!==true)throw new Error('请选择本项目已登记、类型与文件字节一致的 PNG 或 JPEG 图像；未应用绑定。');
    const decoded=await decode(url);
    if(!current())return stale(receipt);
    const blockId=selection?null:newBlockId();
    const content=updateDocumentImage(target.draft.content,selection,binding,values.alt,{blockId,afterBlock:target.selectedBlock});
    commit(content,blockId);
    receipt={...receipt,outcome:'applied_to_local_draft',width:decoded.width,height:decoded.height};retain(receipt);
    return {applied:true,receipt};
  }catch(error){
    if(receipt){receipt={...receipt,outcome:'not_applied',error:error.message};retain(receipt);}
    if(!current())return {applied:false,reason:'target_changed',receipt,error:error.message};
    throw error;
  }
}
