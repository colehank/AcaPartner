import {figureValueKey} from './figure-properties.js';

export function figureSourceState(content={}){
 return figureValueKey(Object.fromEntries(['script_asset','script','spec','parameters','input_assets'].map(key=>[key,content[key]??null])));
}

// Requests are serialized. The newest captured draft owns both bitmap and hit map.
export function createFigurePreviewController({snapshot,request,onResult=()=>{},onState=()=>{},delay=280,setTimer=setTimeout,clearTimer=clearTimeout}){
 let epoch=0,queued=null,timer=null,running=false,disposed=false;
 const same=(a,b)=>a&&b&&a.id===b.id&&a.revision===b.revision&&a.generation===b.generation&&a.selection===b.selection&&a.sourceSha===b.sourceSha&&a.sourceState===b.sourceState&&figureValueKey(a.overlays)===figureValueKey(b.overlays);
 const capture=()=>structuredClone(snapshot());
 const drain=async()=>{
  if(disposed||running||!queued)return;
  const job=queued;queued=null;running=true;onState({status:'rendering',epoch:job.epoch});
  try{
   const result=await request('figure.preview',{id:job.source.id,expected_revision:job.source.revision,overlays:job.source.overlays,request_key:job.key});
   const identity=result?.preview_identity;
   if(result?.status!=='preview'||identity?.object_id!==job.source.id||identity?.base_revision!==job.source.revision||identity?.request_key!==job.key||!identity?.base_source_sha256||!identity?.candidate_source_sha256||!identity?.overlays_sha256||!result.assets||!Array.isArray(result.manifest))throw new Error('预览回执与当前图草稿身份不符；旧图和草稿保留。');
   if(job.source.sourceSha&&identity.base_source_sha256!==job.source.sourceSha)throw new Error('预览来源已变化；请核对服务器修订，草稿保留。');
   if(!disposed&&job.epoch===epoch&&same(job.source,capture())){onResult(result,job.source);onState({status:'preview',epoch,identity});}
  }catch(error){if(!disposed&&job.epoch===epoch&&same(job.source,capture()))onState({status:'error',error,epoch});}
  finally{running=false;if(!disposed&&queued){if(timer)clearTimer(timer);timer=setTimer(()=>{timer=null;drain();},0);}}
 };
 return {
  schedule({immediate=false}={}){if(disposed)return;const source=capture();if(!source?.id||!Number.isInteger(source.revision))return;epoch++;queued={source,epoch,key:`FIG-PREVIEW-${source.id}-${source.generation}-${epoch}-${Math.random().toString(36).slice(2)}`};if(timer)clearTimer(timer);onState({status:running?'rendering':'queued',epoch});timer=setTimer(()=>{timer=null;drain();},immediate?0:delay);},
  cancel(){epoch++;queued=null;if(timer)clearTimer(timer);timer=null;onState({status:'cancelled',epoch});},
  destroy(){disposed=true;epoch++;queued=null;if(timer)clearTimer(timer);timer=null;},
  isBusy(){return running||!!queued;}
 };
}

export function figureDisplayObject(object,preview){
 const identity=preview?.preview_identity;
 if(!identity||identity.object_id!==object?.id||identity.base_revision!==object.revision)return object;
 return {...object,metadata:{...object.metadata,last_export:{...object.metadata?.last_export,...preview,provenance:{object_id:object.id,revision:object.revision,source_sha256:identity.base_source_sha256},preview_identity:identity}}};
}
