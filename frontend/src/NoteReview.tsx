import {useEffect,useRef,useState} from 'react';
import {command} from './api';
import {Session,type Buffer} from './session';
import type {NoteLocation} from './NotebookNavigator';
import {NoteHistory} from './NoteHistory';
import {type NativeNoteRef,validNativeNoteRef,nativeNoteRefKey} from './NativeNoteReference';

export function noteOpinionLocation(buffer:Buffer|undefined,noteRef:any,opinion:any,originViewId:string):NoteLocation|null {
  if(!buffer||buffer.dirty||buffer.base!==noteRef?.content_sha256||buffer.path!==noteRef?.relative_path||opinion.anchor_status!=='anchored')return null;
  const anchor=opinion.anchor,characters=Array.from(buffer.text);
  if(!anchor||!Number.isInteger(anchor.start_offset)||!Number.isInteger(anchor.end_offset)||anchor.start_offset<0||anchor.end_offset<anchor.start_offset||anchor.end_offset>characters.length||characters.slice(anchor.start_offset,anchor.end_offset).join('')!==anchor.quote)return null;
  return {path:buffer.path,sourceCodePointOffset:anchor.start_offset,endSourceCodePointOffset:anchor.end_offset,
    contentSha256:buffer.base,originViewId,split:false};
}

export function NoteReview({session:s,path,viewId,onLocate,report}:{session:Session,path:string,viewId?:string,
  onLocate?:(location:NoteLocation)=>Promise<void>,report:(e:unknown)=>void}){
  const [state,setState]=useState<any>(null),[text,setText]=useState(''),[busy,setBusy]=useState(false);
  const context=useRef(''),session=useRef(s),owner=useRef<Session|null>(null);context.current=s.project.id+'\n'+path;session.current=s;
  const buffer=s.buffers.get(path),key=context.current;
  useEffect(()=>{
    let alive=true;setState(null);setText('');setBusy(false);
    command('desk.note.review.read',{project_id:s.project.id,relative_path:path})
      .then(value=>{if(alive&&session.current===s&&context.current===key){owner.current=s;setState(value);}})
      .catch(error=>{if(alive&&session.current===s&&context.current===key)report(error);});
    return()=>{alive=false;};
  },[s,s.project.id,path,buffer?.id,buffer?.revision,buffer?.base]);
  const loaded=owner.current===s&&state?.note_ref.project_id===s.project.id&&state?.note_ref.relative_path===path&&(!buffer?.id||state.note_ref.id===buffer.id);
  const quoteFragment=(ref:NativeNoteRef)=>{
    if(session.current!==s||context.current!==key||owner.current!==s||!loaded||!validNativeNoteRef(ref)||!ref.fragment||ref.id!==state.note_ref.id||ref.relative_path!==path||!state.file_revisions.some((row:any)=>row.revision===ref.revision&&row.content_sha256===ref.content_sha256))
      throw new Error('当前笔记或历史身份已变化；未加入整轮上下文。');
    const existing=s.reviewNoteRefs.find(item=>item.id===ref.id||item.relative_path===ref.relative_path);
    if(existing){
      if(nativeNoteRefKey(existing)===nativeNoteRefKey(ref))return;
      throw new Error('整轮上下文已选此笔记的另一引用；请先在整轮意见中取消旧引用，再明确选择片段。');
    }
    if(s.reviewNoteRefs.length>=4)throw new Error('整轮上下文最多选择 4 份笔记，请先取消多余引用。');
    if(s.reviewNoteRefs.some(item=>!validNativeNoteRef(item)))throw new Error('已有笔记引用无效；请在整轮意见中核对并处理。');
    // Selection changes the composer only, never a file, opinion, grant or Task.
    s.setReviewNoteRefs([...s.reviewNoteRefs,structuredClone(ref)]);
  };
  const change=async(op:string,id?:string)=>{try{
    if(!loaded||busy||!buffer)return;
    setBusy(true);const captured=context.current;
    const v=s.views[viewId||s.activeView]||{};const b=buffer;
    const start=Math.min(v.anchor??v.cursor??0,v.cursor??0),end=Math.max(v.anchor??v.cursor??0,v.cursor??0);
    const x=await command('desk.note.review.change',{project_id:s.project.id,relative_path:path,expected_revision:state.revision,expected_content_sha256:state.note_ref.content_sha256,op,
      ...(id?{id}:{text,start_offset:Array.from(b.text.slice(0,start)).length,end_offset:Array.from(b.text.slice(0,end)).length})});
    if(session.current===s&&context.current===captured){setState(x);if(op==='create')setText('');}
  }catch(e){if(session.current===s&&context.current===key)report(e);}finally{if(session.current===s&&context.current===key)setBusy(false);}};
  return <aside className="note-review" aria-label="本笔记批注与修订"><strong>此 Markdown 的批注与文件历史</strong>
    {!loaded&&<p role="status">{owner.current===s&&state?.note_ref.relative_path===path&&buffer?.id&&state.note_ref.id!==buffer.id?'笔记文件身份已改变；当前缓冲保留，请重新读取保存版。':'读取当前笔记批注…'}</p>}
    {loaded&&<><small>{state.note_ref.id} · 文件 r{state.note_ref.revision} · {state.file_revisions.length} 个修订</small>
      <label>批注文字<input aria-label="笔记批注文字" value={text} onChange={e=>setText(e.target.value)}/></label><button disabled={busy||!text.trim()||buffer?.dirty||buffer?.base!==state.note_ref.content_sha256} onClick={()=>change('create')}>添加笔记批注</button>
      {buffer?.dirty&&<small>手改缓冲保留；保存后才能添加或定位文件批注。</small>}
      {state.opinions.map((o:any)=>{const location=noteOpinionLocation(buffer,state.note_ref,o,viewId||s.activeView);return <div key={o.id}><p>{o.text} · {o.anchor_status} · {o.deleted?'已删除':'保留'}</p>
        {o.anchor.quote&&<blockquote>{o.anchor.quote}</blockquote>}
        {onLocate&&<button disabled={busy||!location} onClick={()=>location&&onLocate(location).catch(report)}>定位笔记批注</button>}
        {!location&&<small>当前文件或草稿已变化；原引用仍保留，不猜测新位置。</small>}
        <button disabled={busy} onClick={()=>change(o.deleted?'restore':'delete',o.id)}>{o.deleted?'恢复笔记批注':'删除笔记批注'}</button></div>;})}
      <NoteHistory key={key+'\n'+state.note_ref.id} projectId={s.project.id} path={path} noteId={state.note_ref.id} revisions={state.file_revisions} report={report} onQuoteFragment={quoteFragment}/>
    </>}
  </aside>;
}
