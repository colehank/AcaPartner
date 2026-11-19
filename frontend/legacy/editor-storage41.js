/** Per-workspace, browser-desk and region draft keys; scientific identity stays unchanged. */
export function editorStorageKey({workspace,desk,region,objectId,type='draft'}){
 if(!['draft','note'].includes(type)||[workspace,desk,region,objectId].some(v=>typeof v!=='string'||!v))throw new TypeError('Draft storage requires workspace, desk, region and object identities.');
 return 'research-partner:'+type+':v41:'+JSON.stringify([workspace,desk,region,objectId]);
}

/** Separate from the live draft namespace so accepting/removing a draft keeps
 * the migration decision. A marker never contains source or legacy bytes.
 */
export function editorLegacyMigrationKey(identity){
 editorStorageKey(identity);
 return 'research-partner:legacy-migration:v41:'+JSON.stringify([identity.type||'draft',identity.workspace,identity.desk,identity.region,identity.objectId]);
}

export function readEditorDraft(storage,identity){
 const key=editorStorageKey(identity),marker=editorLegacyMigrationKey(identity);
 const current=storage.getItem(key),resolved=storage.getItem(marker)!==null;
 if(current!==null){
  // Also cover current keys created before this migration guard was introduced.
  if(!resolved)storage.setItem(marker,'complete');
  return current;
 }
 if(resolved)return null;
 // Preserve the original bytes for explicit recovery. Each namespace gets one
 // migration decision, including an empty legacy lookup; a later remove of the
 // current key must never resurrect its accepted/cancelled predecessor.
 const legacy=storage.getItem('research-partner:'+(identity.type||'draft')+':'+identity.objectId);
 if(legacy!==null)storage.setItem(key,legacy);
 // Copy before marking: a failed copy leaves migration retryable. A failed
 // marker write throws with both copies retained; the next read completes the
 // marker before returning current bytes. Storage failures are never swallowed.
 storage.setItem(marker,'complete');
 return legacy;
}

const recoveryPrefix='research-partner:draft-recovery:v41:';
const recoveryArchivePrefix='research-partner:draft-recovery-archive:v41:';
const jsonObject=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
function recoveryError(message,code='DRAFT_RECOVERY_CHANGED'){
 const error=new Error(message);error.code=code;return error;
}
function recoveryIdentity(key,identity){
 const prefix='research-partner:'+(identity.type||'draft')+':v41:';
 if(typeof key!=='string'||!key.startsWith(prefix))return null;
 try{
  const parts=JSON.parse(key.slice(prefix.length));
  if(!Array.isArray(parts)||parts.length!==4||!parts.every(x=>typeof x==='string'&&x)||!['primary','secondary'].includes(parts[2]))return null;
  const [workspace,desk,region,objectId]=parts;
  if(workspace!==identity.workspace||objectId!==identity.objectId||desk===identity.desk)return null;
  const source={workspace,desk,region,objectId,type:identity.type||'draft'};
  return editorStorageKey(source)===key?source:null;
 }catch{return null;}
}
function recoveryDraft(raw,identity){
 try{
  const draft=JSON.parse(raw);
  if(!jsonObject(draft)||typeof draft.title!=='string'||!jsonObject(draft.content))return null;
  const revision=(identity.type||'draft')==='note'?draft.revision:draft.base_revision;
  if(!Number.isSafeInteger(revision)||revision<0)return null;
  if(identity.type==='note'&&(draft.id!==identity.objectId||typeof draft.content.manuscript_id!=='string'))return null;
  return draft;
 }catch{return null;}
}
async function recoveryFingerprint(raw,ignoreSavedAt=true){
 // Closing a page may refresh saved_at without changing any recoverable edit.
 // Everything else, including the lossless history envelope, is significant.
 const draft=JSON.parse(raw);if(ignoreSavedAt)delete draft.saved_at;
 const bytes=new TextEncoder().encode(ignoreSavedAt?JSON.stringify(draft):raw);
 const digest=await globalThis.crypto.subtle.digest('SHA-256',bytes);
 return Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
}
function recoveryReceiptKey(identity,key,fingerprint){
 return recoveryPrefix+JSON.stringify([identity.workspace,identity.type||'draft',identity.objectId,key,fingerprint]);
}

/** Read-only discovery. Other desks may still be live: discovery never adopts
 * their identity, deletes their bytes, or changes the current editor draft. */
export async function listEditorDraftRecoveries(storage,identity){
 editorStorageKey(identity);
 const keys=[];for(let index=0;index<storage.length;index++)keys.push(storage.key(index));
 const candidates=[];
 for(const key of keys){
  const source=recoveryIdentity(key,identity);if(!source)continue;
  const raw=storage.getItem(key);if(raw===null)continue;
  const draft=recoveryDraft(raw,identity);if(!draft)continue;
  const fingerprint=await recoveryFingerprint(raw);
  if(storage.getItem(key)!==raw)continue;
  if(storage.getItem(recoveryReceiptKey(identity,key,fingerprint))!==null)continue;
  candidates.push({key,raw,fingerprint,desk:source.desk,region:source.region,draft,title:draft.title,baseRevision:identity.type==='note'?draft.revision:draft.base_revision,savedAt:draft.saved_at||null});
 }
 return candidates;
}

/** Explicitly copy one inspected snapshot into this desk. The app must reject
 * dirty/in-flight editors in beforeCopy; it runs after hashing and before any
 * writes. Source comparison and expectedCurrentRaw also protect concurrent
 * source edits and changes to this desk while the recovery dialog was open. */
export async function recoverEditorDraft(storage,identity,candidate,options={}){
 const targetKey=editorStorageKey(identity),source=recoveryIdentity(candidate?.key,identity);
 if(!source||typeof candidate?.raw!=='string'||!recoveryDraft(candidate.raw,identity))throw recoveryError('此本机副本不属于当前成果。','DRAFT_RECOVERY_INVALID');
 if(!Object.hasOwn(options,'expectedCurrentRaw')||(options.expectedCurrentRaw!==null&&typeof options.expectedCurrentRaw!=='string'))throw new TypeError('Recovery requires the exact current draft bytes or null.');
 const fingerprint=await recoveryFingerprint(candidate.raw);
 if(fingerprint!==candidate.fingerprint)throw recoveryError('本机副本身份已变化，请重新查看。');
 const receiptKey=recoveryReceiptKey(identity,candidate.key,fingerprint),expected=options.expectedCurrentRaw;
 const archiveKey=expected===null?null:recoveryArchivePrefix+JSON.stringify([identity.workspace,identity.type||'draft',identity.objectId,targetKey,await recoveryFingerprint(expected,false)]);
 if(options.beforeCopy){const result=options.beforeCopy();if(result?.then||result===false)throw recoveryError('当前编辑状态已变化，请重新查看本机副本。');}
 if(storage.getItem(candidate.key)!==candidate.raw)throw recoveryError('另一编辑页已更新此本机副本，请重新查看后恢复。');
 if(storage.getItem(targetKey)!==expected)throw recoveryError('当前页面的本机草稿已变化，请先处理当前改动。');
 if(storage.getItem(receiptKey)!==null)throw recoveryError('此版本的本机副本已经恢复，请重新查看其他副本。');
 if(archiveKey){
  const archived=storage.getItem(archiveKey);
  if(archived!==null&&archived!==expected)throw recoveryError('当前稿的保留记录已变化，恢复已停止。');
  storage.setItem(archiveKey,expected);
  if(storage.getItem(archiveKey)!==expected)throw recoveryError('无法核对当前稿的保留副本。','DRAFT_RECOVERY_STORAGE');
 }
 const receipt=JSON.stringify({sourceKey:candidate.key,fingerprint,targetKey,recovered_at:new Date().toISOString()});
 let copied=false;
 try{
  if(storage.getItem(candidate.key)!==candidate.raw||storage.getItem(targetKey)!==expected)throw recoveryError('编辑页的本机副本已变化，请重新查看。');
  storage.setItem(targetKey,candidate.raw);copied=true;
  if(storage.getItem(targetKey)!==candidate.raw)throw recoveryError('无法核对恢复后的本机副本。','DRAFT_RECOVERY_STORAGE');
  storage.setItem(receiptKey,receipt);
  if(storage.getItem(receiptKey)!==receipt)throw recoveryError('无法核对本机副本的恢复记录。','DRAFT_RECOVERY_STORAGE');
 }catch(error){
  // Do not undo a different page's intervening write. Both original records
  // remain available even if storage also rejects the rollback.
  try{if(storage.getItem(receiptKey)===receipt)storage.removeItem(receiptKey);}catch{}
  try{if(copied&&storage.getItem(targetKey)===candidate.raw){if(expected===null)storage.removeItem(targetKey);else storage.setItem(targetKey,expected);}}catch{}
  throw error;
 }
 return candidate.raw;
}
