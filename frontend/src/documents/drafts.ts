import {get,set,del,setMany} from 'idb-keyval';
export type Draft={revision:number;initialFormat?:'docx'|'latex';latex:string;docx:Uint8Array|null;latexDirty:boolean;docxDirty:boolean;docxGeneration:number;capturedGeneration:number};
const tabKey='acapartner.native-editor-tab',parentKey=tabKey+':inherited';
/** Web Locks are released by the browser when the document exits, including reload. */
function claim(id:string):Promise<boolean>{
  if(!navigator.locks)return Promise.resolve(false);
  return new Promise(resolve=>{void navigator.locks.request('acapartner.draft-window:'+id,{ifAvailable:true},async lock=>{
    resolve(!!lock);if(lock)await new Promise<void>(()=>{});
  }).catch(()=>resolve(false));});
}
const namespace=(async()=>{
  const previous=sessionStorage.getItem(tabKey),inherited=sessionStorage.getItem(parentKey);
  if(previous&&await claim(previous))return {id:previous,inherited};
  // A duplicated tab inherits sessionStorage, but cannot claim its live parent's lock.
  // On browsers without Web Locks, every document forks safely and recovers by copying.
  const id=crypto.randomUUID();await claim(id);sessionStorage.setItem(tabKey,id);
  if(previous)sessionStorage.setItem(parentKey,previous);
  return {id,inherited:previous};
})();
const key=(windowId:string,id:string)=>'acapartner.native-manuscript.v2:'+windowId+':'+id;
let pending:Promise<unknown>=Promise.resolve();
async function location(id:string){
  const window=await namespace,name=key(window.id,id);
  if(window.inherited&&!await get(name+':inherited-copied')){
    for(const suffix of ['',':backup']){
      const copy=await get<Draft>(key(window.inherited,id)+suffix);
      if(copy&&!await get(name+suffix))await set(name+suffix,copy);
    }
    await set(name+':inherited-copied',true);
  }
  return name;
}
export const editorDraftKey=location;
export async function readDraft(id:string,backup=false):Promise<Draft|undefined>{await pending;return get((await location(id))+(backup?':backup':''));}
export function persistDraft(id:string,value:Draft,backup=false){
  // Serialize writes so an older serialization cannot replace a later capture.
  const write=pending.catch(()=>{}).then(async()=>{
    const name=(await location(id))+(backup?':backup':'');
    return value.latexDirty||value.docxDirty||backup?set(name,value):del(name);
  });
  pending=write.catch(()=>{});return write;
}
/** Swap recovery and active drafts in one IndexedDB transaction. */
export function restoreDraftBackup(id:string,displaced:Draft):Promise<Draft>{
  const write=pending.catch(()=>{}).then(async()=>{
    const name=await location(id),previous=await get<Draft>(name+':backup');
    if(!previous?.docx)throw new Error('没有可恢复的 DOCX 副本。');
    await setMany([[name,previous],[name+':backup',displaced]]);
    return previous;
  });
  pending=write.catch(()=>{});return write;
}
export function bytesBase64(bytes:Uint8Array){let text='';for(let offset=0;offset<bytes.length;offset+=32768)text+=String.fromCharCode(...bytes.subarray(offset,offset+32768));return btoa(text);}
export function download(bytes:Uint8Array|string,name:string,type:string){
  const blob=new Blob([typeof bytes==='string'?bytes:new Uint8Array(bytes).buffer],{type}),url=URL.createObjectURL(blob),a=document.createElement('a');
  a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
