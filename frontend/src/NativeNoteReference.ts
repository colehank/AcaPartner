export type NativeNoteFragment={start_offset:number,end_offset:number,content_sha256:string};
export type NativeNoteRef={id:string,relative_path:string,revision:number,content_sha256:string,fragment?:NativeNoteFragment};

export function nativeNotePath(path:string){
  const parts=path.split('/');
  return path.length>0&&path.length<=1024&&!/[\\\u0000]/.test(path)&&parts[0]==='notes'&&parts.length>1&&path.endsWith('.md')&&parts.every(part=>part!==''&&part!=='.'&&part!=='..')&&!parts.slice(1).some(part=>part==='.trash'||part==='.notebook');
}

export function validNativeNoteRef(ref:NativeNoteRef){
  if(!ref||typeof ref.id!=='string'||!ref.id.trim()||typeof ref.relative_path!=='string'||!nativeNotePath(ref.relative_path)||!Number.isSafeInteger(ref.revision)||ref.revision<1||typeof ref.content_sha256!=='string'||!/^[a-f0-9]{64}$/.test(ref.content_sha256))return false;
  if(!Object.hasOwn(ref,'fragment'))return true;
  const f=ref.fragment;
  return !!f&&typeof f==='object'&&!Array.isArray(f)&&Object.keys(f).sort().join(',')==='content_sha256,end_offset,start_offset'&&Number.isSafeInteger(f.start_offset)&&Number.isSafeInteger(f.end_offset)&&f.start_offset>=0&&f.end_offset>f.start_offset&&typeof f.content_sha256==='string'&&/^[a-f0-9]{64}$/.test(f.content_sha256);
}

export const nativeNoteRefKey=(ref:NativeNoteRef)=>JSON.stringify([ref.id,ref.relative_path,ref.revision,ref.content_sha256,ref.fragment??null]);
