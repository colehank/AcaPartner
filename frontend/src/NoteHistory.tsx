import {useEffect,useLayoutEffect,useMemo,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {command} from './api';
import {notebookHeadings} from './NotebookNavigator';
import {renderNotebookMarkdown} from './NotebookMarkdown';
import {nativeNotePath,type NativeNoteRef} from './NativeNoteReference';
import {nativeTextSelection,type NativeTextSelection} from './NativeNoteFragment';

export type NoteHistoryRef={project_id:string,relative_path:string,note_id:string,revision:number,content_sha256:string};
type Snapshot={id:string,project_id:string,relative_path:string,revision:number,content_sha256:string,markdown:string,encoding:'utf-8',bytes:number,offset_unit:'unicode_code_point',outline:any[],authority_kind:'file_snapshot',read_only:true};
const fields=['id','project_id','relative_path','revision','content_sha256','markdown','encoding','bytes','offset_unit','outline','authority_kind','read_only'];
const refKey=(ref:NoteHistoryRef)=>JSON.stringify([ref.project_id,ref.relative_path,ref.note_id,ref.revision,ref.content_sha256]);
function validRef(ref:NoteHistoryRef){return typeof ref.project_id==='string'&&!!ref.project_id&&typeof ref.note_id==='string'&&!!ref.note_id&&typeof ref.relative_path==='string'&&nativeNotePath(ref.relative_path)&&Number.isSafeInteger(ref.revision)&&ref.revision>=1&&typeof ref.content_sha256==='string'&&/^[a-f0-9]{64}$/.test(ref.content_sha256);}

export async function validateNoteHistory(value:any,ref:NoteHistoryRef):Promise<Snapshot>{
  if(!validRef(ref)||!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==fields.length||fields.some(field=>!Object.hasOwn(value,field))
    ||value.id!==ref.note_id||value.project_id!==ref.project_id||value.relative_path!==ref.relative_path||value.revision!==ref.revision||value.content_sha256!==ref.content_sha256
    ||value.encoding!=='utf-8'||value.authority_kind!=='file_snapshot'||value.read_only!==true||value.offset_unit!=='unicode_code_point'||typeof value.markdown!=='string'||!Array.isArray(value.outline))
    throw new Error('历史笔记的项目、文件身份、修订或只读格式不匹配；未显示此正文。');
  const length=Array.from(value.markdown).length;
  if(value.outline.some((entry:any)=>!entry||typeof entry.title!=='string'||!Number.isSafeInteger(entry.level)||entry.level<1||entry.level>6||!Number.isSafeInteger(entry.start_offset)||!Number.isSafeInteger(entry.end_offset)||entry.start_offset<0||entry.end_offset<entry.start_offset||entry.end_offset>length))throw new Error('历史笔记的原文位置无效；未显示此正文。');
  const bytes=new TextEncoder().encode(value.markdown);
  if(!Number.isSafeInteger(value.bytes)||value.bytes!==bytes.byteLength)throw new Error('历史笔记的 UTF-8 字节数不匹配；未显示此正文。');
  const sha=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(sha!==ref.content_sha256)throw new Error('历史笔记的正文与 SHA-256 不匹配；未显示此正文。');
  return value;
}

export function NoteHistory({projectId,path,noteId,revisions,report,onQuoteFragment}:{projectId:string,path:string,noteId:string,revisions:any[],report:(error:unknown)=>void,onQuoteFragment?:(ref:NativeNoteRef)=>void|Promise<void>}){
  const key=JSON.stringify([projectId,path,noteId]),context=useRef(key),currentRows=useRef(revisions),alive=useRef(true),epoch=useRef(0);context.current=key;currentRows.current=revisions;
  const [selected,setSelected]=useState<{context:string,ref:NoteHistoryRef}|null>(null),[snapshot,setSnapshot]=useState<{context:string,ref:string,value:Snapshot}|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const selection=useRef(selected),container=useRef<HTMLDetailsElement>(null),layer=useRef<HTMLElement>(null);
  const returnFocus=useRef<{context:string,element:HTMLElement}|null>(null),pendingFocus=useRef<HTMLElement|null>(null);selection.current=selected;
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;epoch.current++;};},[]);
  const current=selected?.context===key&&currentRows.current.some(r=>r.revision===selected.ref.revision&&r.content_sha256===selected.ref.content_sha256)?selected:null;
  const preview=current&&snapshot?.context===key&&snapshot.ref===refKey(current.ref)?snapshot.value:null;
  const html=useMemo(()=>preview?renderNotebookMarkdown(preview.markdown,path,notebookHeadings(preview.markdown),{links:false}):'',[preview,path]);
  const source=useRef<HTMLPreElement>(null),fragmentEpoch=useRef(0),quoteEpoch=useRef(0);
  const [fragment,setFragment]=useState<{snapshot:Snapshot,selection:NativeTextSelection,sha:string}|null>(null),[quoting,setQuoting]=useState(false),[quoteError,setQuoteError]=useState(''),[quoteNotice,setQuoteNotice]=useState('');
  const latest=useRef({key,preview,ref:current?.ref,onQuoteFragment});latest.current={key,preview,ref:current?.ref,onQuoteFragment};
  const clearFragment=()=>{fragmentEpoch.current++;quoteEpoch.current++;setFragment(null);setQuoting(false);setQuoteError('');setQuoteNotice('');};
  useEffect(()=>{
    clearFragment();
    if(!preview||!current||!onQuoteFragment)return;
    const captured=preview,capturedKey=key,capturedRef=refKey(current.ref);
    const valid=()=>alive.current&&latest.current.key===capturedKey&&latest.current.preview===captured&&latest.current.ref&&refKey(latest.current.ref)===capturedRef&&!!latest.current.onQuoteFragment;
    const readSelection=()=>source.current&&source.current.getClientRects().length?nativeTextSelection(source.current,captured.markdown,window.getSelection()):null;
    const changed=()=>{
      const ticket=++fragmentEpoch.current;setFragment(null);const selected=valid()?readSelection():null;if(!selected)return;
      void crypto.subtle.digest('SHA-256',new TextEncoder().encode(selected.text)).then(hash=>{
        const now=readSelection();
        if(valid()&&fragmentEpoch.current===ticket&&now&&now.start_offset===selected.start_offset&&now.end_offset===selected.end_offset&&now.text===selected.text)
          setFragment({snapshot:captured,selection:selected,sha:Array.from(new Uint8Array(hash),x=>x.toString(16).padStart(2,'0')).join('')});
      }).catch(problem=>{if(valid()&&fragmentEpoch.current===ticket){setQuoteError(String(problem));report(problem);}});
    };
    document.addEventListener('selectionchange',changed);changed();
    return()=>{document.removeEventListener('selectionchange',changed);fragmentEpoch.current++;quoteEpoch.current++;};
  },[key,preview,current?refKey(current.ref):'',!!onQuoteFragment]);
  const quote=async()=>{
    if(!fragment||fragment.snapshot!==preview||!current||!onQuoteFragment||quoting||!source.current||!source.current.getClientRects().length)return;
    const now=nativeTextSelection(source.current,preview.markdown,window.getSelection());
    if(!now||now.start_offset!==fragment.selection.start_offset||now.end_offset!==fragment.selection.end_offset||now.text!==fragment.selection.text){setFragment(null);return;}
    const captured=preview,capturedKey=key,capturedRef=refKey(current.ref),ticket=++quoteEpoch.current;
    const valid=()=>alive.current&&quoteEpoch.current===ticket&&latest.current.key===capturedKey&&latest.current.preview===captured&&!!latest.current.onQuoteFragment&&!!latest.current.ref&&refKey(latest.current.ref)===capturedRef;
    const ref:NativeNoteRef={id:current.ref.note_id,relative_path:current.ref.relative_path,revision:current.ref.revision,content_sha256:current.ref.content_sha256,fragment:{start_offset:now.start_offset,end_offset:now.end_offset,content_sha256:fragment.sha}};
    if(!valid())return;
    setQuoting(true);setQuoteError('');setQuoteNotice('');
    try{await onQuoteFragment(ref);if(valid())setQuoteNotice('原文片段已加入下一轮原生上下文；尚未提交整轮任务。');}
    catch(problem){if(valid()){setQuoteError(problem instanceof Error?problem.message:String(problem));report(problem);}}
    finally{if(valid())setQuoting(false);}
  };
  const panel=container.current?.closest<HTMLElement>('.note-panel');
  useLayoutEffect(()=>{
    if(!current||!panel||!layer.current)return;
    const peers=Array.from(panel.children).filter((element):element is HTMLElement=>element instanceof HTMLElement&&element!==layer.current);
    const previous=peers.map(element=>({element,inert:element.getAttribute('inert')}));
    // The editor remains mounted and measured; only covered controls become
    // unavailable to keyboard input while this read-only layer is open.
    peers.forEach(element=>{element.inert=true;});
    return()=>previous.forEach(({element,inert})=>{if(inert===null)element.removeAttribute('inert');else element.setAttribute('inert',inert);});
  },[key,!!current,panel]);
  useLayoutEffect(()=>{
    if(current){
      const active=document.activeElement;
      if(layer.current&&(panel?.contains(active)||active===document.body))layer.current.focus({preventScroll:true});
    }else if(pendingFocus.current){
      const target=pendingFocus.current;pendingFocus.current=null;
      if(target.isConnected&&container.current?.closest('.note-panel')?.contains(target))target.focus({preventScroll:true});
    }
  },[key,current?refKey(current.ref):'',panel]);
  const rememberFocus=()=>{
    if(current)return;
    const active=document.activeElement;
    if(active instanceof HTMLElement&&container.current?.closest('.note-panel')?.contains(active))returnFocus.current={context:key,element:active};
  };
  const open=async(ref:NoteHistoryRef)=>{
    if(!returnFocus.current||returnFocus.current.context!==key)rememberFocus();
    clearFragment();
    const captured=key,sequence=++epoch.current,chosen={context:captured,ref};selection.current=chosen;setSelected(chosen);setSnapshot(null);setError('');setBusy(true);
    const active=()=>alive.current&&context.current===captured&&epoch.current===sequence&&selection.current?.context===captured&&refKey(selection.current.ref)===refKey(ref)&&currentRows.current.some(r=>r.revision===ref.revision&&r.content_sha256===ref.content_sha256);
    try{
      if(!validRef(ref))throw new Error('文件历史引用不完整，请重新读取笔记历史。');
      const value=await command('desk.note.revision.read',ref);if(!active())return;
      const checked=await validateNoteHistory(value,ref);if(active())setSnapshot({context:captured,ref:refKey(ref),value:checked});
    }catch(problem){if(active()){setError((problem instanceof Error?problem.message:String(problem))+((problem as any)?.code?' · '+(problem as any).code:''));report(problem);}}
    finally{if(active())setBusy(false);}
  };
  const close=()=>{clearFragment();epoch.current++;selection.current=null;pendingFocus.current=returnFocus.current?.context===key?returnFocus.current.element:null;returnFocus.current=null;setSelected(null);setSnapshot(null);setError('');setBusy(false);};
  const revisionButton=(r:any,compact=false)=>{const ref={project_id:projectId,relative_path:path,note_id:noteId,revision:r.revision,content_sha256:r.content_sha256};return <button key={r.revision} aria-label={`预览笔记文件修订 r${r.revision}`} aria-pressed={!!current&&refKey(current.ref)===refKey(ref)} onPointerDown={rememberFocus} onClick={()=>void open(ref)}>{compact?`r${r.revision}`:'阅读此修订'}</button>;};
  const reading=current&&<section ref={layer} className="note-history-layer" aria-label="历史笔记正文" tabIndex={-1} onKeyDown={event=>{if(event.key==='Escape'){event.stopPropagation();close();}}}>
    <div className="note-history-header">
      <div className="note-history-heading"><strong>文件历史 r{current.ref.revision} · 只读</strong><button onClick={close}>返回当前笔记</button></div>
      <span className="note-history-path">{path}</span>
      <p>当前笔记和未保存草稿保留；此处仅阅读固定修订。</p>
      <div className="note-history-versions" role="group" aria-label="选择历史修订">{revisions.map(r=>revisionButton(r,true))}</div>
      <details className="note-history-identity"><summary>固定来源身份</summary><small>{noteId} · SHA-256 {current.ref.content_sha256}</small></details>
    </div>
    <div className="note-history-content">
      {busy&&<p role="status">读取历史 r{current.ref.revision}…</p>}
      {error&&<div role="alert"><p>{error}</p><button disabled={busy} onClick={()=>void open(current.ref)}>重试读取此修订</button></div>}
      {preview&&<><article aria-label="历史笔记阅读内容" className="markdown" tabIndex={0} dangerouslySetInnerHTML={{__html:html}}/>
        <details className="note-history-source"><summary>查看历史 Markdown 原文</summary>
          {onQuoteFragment&&<><p>在此原文中选择文字，明确加入下一轮阅读上下文；当前笔记保持不变。</p><button disabled={!fragment||fragment.snapshot!==preview||quoting} onPointerDown={event=>event.preventDefault()} onClick={()=>void quote()}>引用选中的原文片段</button>{quoteError&&<p role="alert">{quoteError}</p>}{quoteNotice&&<p role="status">{quoteNotice}</p>}</>}
          <pre ref={source} aria-label="历史 Markdown 原文">{preview.markdown}</pre></details></>}
    </div>
  </section>;
  return <details ref={container}><summary>文件修订历史</summary>
    <div style={{visibility:current?'hidden':undefined}}>{revisions.map(r=><p key={r.revision}>r{r.revision} · {r.reason} · {r.content_sha256}{revisionButton(r)}</p>)}</div>
    {reading&&(panel?createPortal(reading,panel):reading)}
  </details>;
}
