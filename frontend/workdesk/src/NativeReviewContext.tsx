import {useEffect,useId,useRef,useState,useSyncExternalStore} from 'react';
import {command,noteCommand} from './api';
import {validateNoteHistory} from './NoteHistory';
import {type NativeNoteRef,nativeNotePath,validNativeNoteRef as validRef,nativeNoteRefKey as refKey} from './NativeNoteReference';
export {type NativeNoteRef,nativeNotePath} from './NativeNoteReference';
import {Session} from './session';

type SavedNote={ref:NativeNoteRef,markdown:string,bytes:number,observation:string};
type Preview={note:SavedNote,refsKey:string,replaces?:string};
type Local={owner:Session,project:string,path:string,preview:Preview|null,cache:Record<string,SavedNote>,busy:string|null,busyObservation:string,busyRef:NativeNoteRef|undefined,error:string,notice:string};
const MAX_NOTES=4,MAX_BYTES=128*1024;
const refsKey=(refs:NativeNoteRef[])=>JSON.stringify(refs.map(refKey));
const initial=(owner:Session):Local=>({owner,project:owner.project.id,path:'',preview:null,cache:{},busy:null,busyObservation:'',busyRef:undefined,error:'',notice:''});

function SourceDetails({noteRef:ref}:{noteRef:NativeNoteRef}){
  return <details className="native-context-source">
    <summary>来源详情</summary>
    <dl>
      <dt>文件</dt><dd>{ref.relative_path}</dd>
      <dt>笔记标识</dt><dd>{ref.id}</dd>
      <dt>固定修订</dt><dd>r{ref.revision}</dd>
      <dt>完整原文</dt><dd><code>原文 SHA-256 {ref.content_sha256}</code></dd>
      {ref.fragment&&<><dt>选中范围 · Unicode 码点</dt><dd>[{ref.fragment.start_offset}, {ref.fragment.end_offset})</dd>
        <dt>选中原文</dt><dd><code>片段 SHA-256 {ref.fragment.content_sha256}</code></dd></>}
    </dl>
  </details>;
}

function refsError(refs:NativeNoteRef[]){
  if(refs.length>MAX_NOTES)return '最多选择 4 份笔记，请先取消多余引用。';
  if(refs.some(ref=>!validRef(ref)))return '已有笔记引用身份无效，请取消后重新读取保存版。';
  if(new Set(refs.map(ref=>ref.id)).size!==refs.length||new Set(refs.map(ref=>ref.relative_path)).size!==refs.length)return '同一笔记只能选择一次，请取消重复引用。';
  return '';
}
function observation(s:Session,path:string,ref?:NativeNoteRef){
  // A pinned historical fragment does not follow the live file HEAD. Identity
  // and present access are checked afresh by the revision read and submission.
  if(ref?.fragment)return JSON.stringify([s.project.id,refKey(ref)]);
  const entry=s.entries.find(item=>item.type==='file'&&item.relative_path===path),buffer=s.buffers.get(path);
  return JSON.stringify([entry?.revision,entry?.content_sha256,buffer?.revision,buffer?.base]);
}

// Only the canonical file-service result is eligible. Markdown is never taken
// from Session.buffers, normalized, rendered as HTML, or passed to onChange.
export async function validateNativeNote(note:any,project:string,path:string):Promise<Omit<SavedNote,'observation'>>{
  if(!note||note.project_id!==project||note.relative_path!==path||!validRef(note)||note.authority_kind!=='file'||note.encoding!=='utf-8'||note.offset_unit!=='unicode_code_point'||typeof note.markdown!=='string')throw new Error('保存版笔记的项目、身份或文件格式不匹配；未选择此内容。');
  const bytes=new TextEncoder().encode(note.markdown);
  if(note.bytes!==bytes.byteLength)throw new Error('保存版笔记的 UTF-8 字节数不匹配；未选择此内容。');
  const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),value=>value.toString(16).padStart(2,'0')).join('');
  if(sha!==note.content_sha256)throw new Error('保存版笔记的 SHA-256 与正文不匹配；未选择此内容。');
  return {ref:{id:note.id,relative_path:note.relative_path,revision:note.revision,content_sha256:note.content_sha256},markdown:note.markdown,bytes:bytes.byteLength};
}

export async function validateNativeNoteFragment(raw:any,project:string,ref:NativeNoteRef):Promise<Omit<SavedNote,'observation'>>{
  if(!validRef(ref)||!ref.fragment)throw new Error('固定片段身份或原文位置无效；未选择此内容。');
  const source=await validateNoteHistory(raw,{project_id:project,relative_path:ref.relative_path,note_id:ref.id,revision:ref.revision,content_sha256:ref.content_sha256});
  const characters=Array.from(source.markdown),fragment=ref.fragment;
  if(fragment.end_offset>characters.length)throw new Error('固定片段超出原文码点范围；未选择此内容。');
  const markdown=characters.slice(fragment.start_offset,fragment.end_offset).join(''),bytes=new TextEncoder().encode(markdown);
  const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),value=>value.toString(16).padStart(2,'0')).join('');
  if(sha!==fragment.content_sha256)throw new Error('固定片段的 SHA-256 与原文不匹配；未选择此内容。');
  return {ref:structuredClone(ref),markdown,bytes:bytes.byteLength};
}

export function NativeReviewContext({session:s,refs,onChange,report,disabled=false}:{session:Session,refs:NativeNoteRef[],onChange:(refs:NativeNoteRef[])=>void,report:(error:unknown)=>void,disabled?:boolean}){
  const version=useSyncExternalStore(s.subscribe,s.snapshot),listId=useId();
  const [stored,setStored]=useState<Local>(()=>initial(s));
  const local=stored.owner===s&&stored.project===s.project.id?stored:initial(s);
  const sequence=useRef(0),live=useRef(true),latest=useRef({session:s,project:s.project.id,key:refsKey(refs),path:local.path,disabled});
  const key=refsKey(refs);
  latest.current={session:s,project:s.project.id,key,path:local.path,disabled};
  useEffect(()=>{live.current=true;return()=>{live.current=false;sequence.current++;};},[]);
  useEffect(()=>{sequence.current++;setStored(initial(s));},[s,s.project.id]);
  useEffect(()=>{sequence.current++;setStored(old=>old.owner===s?{...old,busy:null}:old);},[s,key,disabled]);
  useEffect(()=>{if(local.busy&&local.busyObservation!==observation(s,local.busy,local.busyRef)){sequence.current++;setStored(old=>old.owner===s?{...old,busy:null,notice:'读取期间保存身份已变化，请重新读取；已有引用保留。'}:old);}},[s,version,local.busy,local.busyObservation,local.busyRef]);
  const update=(change:(old:Local)=>Local)=>setStored(old=>old.owner===s&&old.project===s.project.id?change(old):old);
  const known=(ref:NativeNoteRef)=>{const note=local.cache[refKey(ref)];return note&&note.observation===observation(s,ref.relative_path,ref)?note:undefined;};
  const selectedBytes=refs.reduce((total,ref)=>total+(known(ref)?.bytes??0),0),allKnown=refs.every(ref=>!!known(ref));
  const error=refsError(refs);
  const preview=local.preview,candidate=preview?.note;
  const previewCurrent=!!preview&&preview.refsKey===key&&candidate!.observation===observation(s,candidate!.ref.relative_path,candidate!.ref);
  const replacement=preview?.replaces?refs.findIndex(ref=>refKey(ref)===preview.replaces):-1;
  const remaining=refs.filter((_,index)=>index!==replacement);
  const remainingKnown=remaining.every(ref=>!!known(ref));
  const nextBytes=remaining.reduce((total,ref)=>total+(known(ref)?.bytes??0),0)+(candidate?.bytes??0);
  const sameSelected=!!candidate&&refs.some(ref=>refKey(ref)===refKey(candidate.ref));
  const chooseBlocked=disabled||!!local.busy||!!error||!previewCurrent||sameSelected||!remainingKnown||nextBytes>MAX_BYTES||(replacement<0&&refs.length>=MAX_NOTES);

  const fail=(message:string)=>{const failure=new Error(message);update(old=>({...old,error:message,notice:''}));report(failure);};
  const read=async(path:string,expected?:NativeNoteRef)=>{
    if(disabled)return;
    if(!nativeNotePath(path)){fail('请输入本项目 notes/ 下的 .md 路径。');return;}
    const owner=s,project=s.project.id,input=local.path,startKey=key,startObservation=observation(s,path,expected),ticket=++sequence.current;
    const current=()=>live.current&&sequence.current===ticket&&latest.current.session===owner&&latest.current.project===project&&latest.current.key===startKey&&latest.current.path===input&&!latest.current.disabled&&observation(owner,path,expected)===startObservation;
    update(old=>{const cache={...old.cache};if(expected)delete cache[refKey(expected)];return {...old,cache,busy:path,busyObservation:startObservation,busyRef:expected,preview:null,error:'',notice:''};});
    try{
      const raw=expected?.fragment
        ?await command('desk.note.revision.read',{project_id:project,relative_path:path,note_id:expected.id,revision:expected.revision,content_sha256:expected.content_sha256})
        :await noteCommand('notes.read',project,{relative_path:path});
      const validated=expected?.fragment?await validateNativeNoteFragment(raw,project,expected):await validateNativeNote(raw,project,path);
      if(!current())return;
      const note={...validated,observation:startObservation};
      const selected=expected||refs.find(ref=>ref.relative_path===path||ref.id===note.ref.id);
      update(old=>({...old,cache:{...old.cache,[refKey(note.ref)]:note},preview:{note,refsKey:startKey,...(selected?{replaces:refKey(selected)}:{})},
        notice:selected&&refKey(selected)===refKey(note.ref)?'已核对所选保存版；引用身份保持不变。':selected?'保存版身份已变化；旧引用保留，请明确选择替换。':'保存版已读取，请明确选择。'}));
    }catch(caught){if(current()){update(old=>({...old,error:String(caught),notice:''}));report(caught);}}
    finally{if(current())update(old=>({...old,busy:null}));}
  };
  const choose=()=>{
    if(chooseBlocked||!candidate||!preview)return;
    const next=[...refs];if(replacement>=0)next[replacement]={...candidate.ref};else next.push({...candidate.ref});
    const invalid=refsError(next);if(invalid){fail(invalid);return;}
    try{onChange(next);update(old=>({...old,preview:null,error:'',notice:'保存版引用已选择；尚未提交整轮任务。'}));}catch(caught){update(old=>({...old,error:String(caught)}));report(caught);}
  };
  const cancel=(index:number)=>{
    if(disabled)return;sequence.current++;
    try{onChange(refs.filter((_,at)=>at!==index).map(ref=>({...ref})));update(old=>({...old,busy:null,preview:null,error:'',notice:'已取消此笔记引用。'}));}catch(caught){update(old=>({...old,error:String(caught)}));report(caught);}
  };

  return <section className="native-review-context" aria-label="整轮原生笔记上下文">
    <h3>原生笔记阅读上下文</h3>
    <p>固定片段只读并绑定所选修订，只发送所选文字，不含未选原文或未保存手改；提交时重新核对来源与权限。</p>
    <p role="status">已选择 {refs.length} / {MAX_NOTES} 份 · {allKnown?`${selectedBytes} / ${MAX_BYTES} UTF-8 字节`:'组合字节数待核对；请读取所选保存版'}</p>
    {error&&<p role="alert">{error}</p>}
    {allKnown&&selectedBytes>MAX_BYTES&&<p role="alert">已选组合超过 {MAX_BYTES} UTF-8 字节，请取消部分笔记；已有引用保留。</p>}
    {refs.length===0&&<p>尚未选择原生笔记。</p>}
    <div className="native-context-selected">{refs.map((ref,index)=><article key={refKey(ref)+':'+index} aria-label={'已选原生笔记 '+(index+1)}>
      <strong>{ref.relative_path}</strong><small>r{ref.revision} · {ref.fragment?'固定片段':'整篇保存版'}</small>
      <p role="status">{known(ref)?`已核对 ${known(ref)!.bytes} UTF-8 字节`:local.cache[refKey(ref)]?'可观察的保存身份已变化，请重新读取核对；原引用保留。':'本次打开尚未核对此保存版；原引用保留。'}</p>
      {s.buffers.get(ref.relative_path)?.dirty&&<p>本地有未保存手改；所选上下文只包含已保存文件。</p>}
      <div className="native-context-actions">
        <button aria-label={(ref.fragment?'核对固定片段':'核对保存版')+' '+ref.relative_path} disabled={disabled||!!local.busy||!validRef(ref)} onClick={()=>read(ref.relative_path,ref)}>{ref.fragment?'核对固定片段':'核对保存版'}</button>
        <button aria-label={'取消笔记 '+ref.relative_path} disabled={disabled} onClick={()=>cancel(index)}>取消引用</button>
      </div>
      <SourceDetails noteRef={ref}/>
    </article>)}</div>
    {local.busy&&<p role="status">读取保存版 {local.busy}…</p>}
    {local.error&&<p role="alert">{local.error}</p>}
    {candidate&&<div className="native-context-preview" aria-label="原生笔记保存版预览">
      <strong>{candidate.ref.relative_path}</strong><small>r{candidate.ref.revision} · {candidate.bytes} UTF-8 字节</small>
      <label>{candidate.ref.fragment?'固定片段原文（只读）':'保存版 Markdown（只读）'}<textarea aria-label="上下文笔记保存版 Markdown" readOnly value={candidate.markdown}/></label>
      {!previewCurrent&&<p role="alert">路径、已选引用或可观察的保存身份已变化；请明确重新读取。</p>}
      {!remainingKnown&&<p>请先核对其他已选笔记，确认组合字节数。</p>}
      {nextBytes>MAX_BYTES&&<p role="alert">组合保存版超过 {MAX_BYTES} UTF-8 字节；未选择此内容。</p>}
      {replacement<0&&refs.length>=MAX_NOTES&&<p>已达 4 份笔记上限，请先取消一份。</p>}
      <button disabled={chooseBlocked} onClick={choose}>{sameSelected?'此保存版已选择':replacement>=0?'用此保存版替换已选引用':'选择此笔记保存版'}</button>
      <SourceDetails noteRef={candidate.ref}/>
    </div>}
    {local.notice&&<p role="status">{local.notice}</p>}
    <label>读取整篇保存版 · 本项目笔记路径<input aria-label="整轮上下文笔记路径" list={listId} placeholder="notes/topics/研究计划.md" value={local.path} disabled={disabled} onChange={event=>{sequence.current++;update(old=>({...old,path:event.target.value,preview:null,busy:null,error:'',notice:''}));}}/></label>
    <datalist id={listId}>{Array.from(new Set(s.entries.filter(entry=>entry.type==='file'&&typeof entry.relative_path==='string'&&nativeNotePath(entry.relative_path)).map(entry=>entry.relative_path as string))).map(path=><option key={path} value={path}/>)}</datalist>
    {s.buffers.get(local.path)?.dirty&&<p role="status">此笔记有未保存手改；读取只取保存版，编辑缓冲保留。</p>}
    <button disabled={disabled||!!local.busy||!local.path} onClick={()=>read(local.path)}>读取笔记保存版</button>
    <details className="native-context-limits"><summary>读取与提交限制</summary>
      <p>笔记组合读取上限为 128 KiB；完整整轮还受 96000 UTF-8 字节保存上限约束，包含稿件、意见和上下文。超过保存上限会拒绝，不会截断；可减少选中笔记。</p>
    </details>
  </section>;
}
