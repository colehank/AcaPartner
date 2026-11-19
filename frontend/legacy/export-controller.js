// An export is a server-side receipt for a captured source, never an editor save.
// No completion callback in this controller mutates the selected object/draft.
export function createExportSession({source,projectId,request,read,isActive,present,receipts,receiptError}){
 const target=Object.freeze({id:source.id,revision:source.revision,kind:source.kind,projectId:source.project_id||projectId});
 let pending=false,receiptRead=0,receiptRevision=target.revision;
 const belongs=(result,revision=target.revision)=>result?.provenance?.object_id===target.id&&result?.provenance?.revision===revision;
 const matching=(object,revision=target.revision)=>{
  if(object?.id!==target.id||object?.revision!==revision)throw new Error('导出回执与所选成果修订不一致，请重新打开该成果。');
  return (object.exports||[]).filter(entry=>entry.revision===revision&&belongs(entry.result,revision));
 };
 const reload=async(revision=receiptRevision)=>{
  if(!isActive())return false;
  if(!Number.isInteger(revision)||revision<1){receiptError(new Error('请选择有效的来源修订。'));return false;}
  receiptRevision=revision;const sequence=++receiptRead;
  try{
   const object=await read(`/api/objects/${encodeURIComponent(target.id)}?revision=${revision}`);
   if(!isActive()||sequence!==receiptRead)return false;
   receipts(matching(object,revision),revision);return true;
  }catch(error){if(isActive()&&sequence===receiptRead)receiptError(error);return false;}
 };
 const submit=async values=>{
  if(!isActive()||pending)return false;
  pending=true;++receiptRead;
  try{
   const bibliography=target.kind==='literature'&&values.format==='bib';
   const result=bibliography?await request('literature.export',{project_id:target.projectId}):await request('object.export',{id:target.id,expected_revision:target.revision,revision:target.revision,format:values.format});
   // Closing/replacing the modal relinquishes all UI ownership. The successful
   // server export still exists in the source's persistent export registry.
   if(!isActive())return false;
   if(!bibliography&&!belongs(result))throw new Error('导出结果来源与打开弹窗时的成果修订不一致，未显示该结果。');
   ++receiptRead;present(result);
   if(!bibliography&&result.object&&receiptRevision===target.revision)receipts(matching(result.object),target.revision);
   return false;
  }catch(error){if(isActive())throw error;return false;}
  finally{pending=false;}
 };
 return {target,submit,reload};
}
