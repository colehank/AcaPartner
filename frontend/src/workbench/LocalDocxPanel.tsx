import {lazy,Suspense,useContext,useEffect,useRef,useState} from 'react';
import {WorkbenchContext,type ViewSpec} from './context';
import {readDraft,persistDraft,download,type Draft} from '../documents/drafts';
import type {DocxHandle,Capture} from '../documents/DocxDocumentEditor';
import {errorText} from './useManuscript';
const Office=lazy(()=>import('../documents/DocxDocumentEditor'));
const mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document';
export function LocalDocxPanel({view}:{view:ViewSpec}){
 const c=useContext(WorkbenchContext)!,editor=useRef<DocxHandle>(null),input=useRef<HTMLInputElement>(null);
 const [initial,setInitial]=useState<Uint8Array|null>(null),[error,setError]=useState(''),[ready,setReady]=useState(false),[changed,setChanged]=useState(false);
 const draft=useRef<Draft|null>(null),generation=useRef(0),captured=useRef(0),engineReady=useRef(false);
 async function snapshot(value:Capture){
  if(!draft.current||value.generation<captured.current)return;
  captured.current=value.generation;draft.current={...draft.current,docx:value.bytes,docxGeneration:value.generation,capturedGeneration:value.generation};
  await persistDraft(view.id,draft.current);
 }
 // Capture the current engine even if its deferred change notification has not
 // reached React yet (for example, typing immediately followed by Cmd+S).
 async function flush(){if(editor.current&&engineReady.current)await snapshot(await editor.current.capture());}
 async function saveCopy(){try{await flush();if(!draft.current?.docx)throw new Error('文件尚未就绪');download(draft.current.docx,view.title,mime);setChanged(false);c.markDirty(view.id,false);}catch(e){setError(errorText(e));}}
 useEffect(()=>{let live=true;void readDraft(view.id).then(value=>{if(!live)return;if(!value?.docx)throw new Error('本地文件草稿无法读取，请重新打开原文件。');draft.current={...value,docxGeneration:0,capturedGeneration:0};setInitial(value.docx);}).catch(e=>live&&setError(errorText(e)));c.registerFileFlush(view.id,flush);const protect=(e:BeforeUnloadEvent)=>{if(generation.current>captured.current)e.preventDefault();};window.addEventListener('beforeunload',protect);return()=>{live=false;c.registerFileFlush(view.id,null);window.removeEventListener('beforeunload',protect);};},[view.id]);
 return <div className="native-paper-workspace native-content-view">
  <input ref={input} type="file" accept=".docx" hidden onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void c.openLocalDocx(file).catch(c.report);}}/>
  {error&&<p role="alert" className="native-alert">{error}</p>}
  {!initial?<p className="editor-empty">{error?'原项目论文保持不变。':'打开本地文件…'}</p>:<div className="native-docx-workspace"><Suspense fallback={<p className="editor-empty">打开 DOCX 编辑器…</p>}><Office ref={editor} initial={initial} title={view.title} theme={c.theme}
   local ready={ready} status={'本地文件 · '+(changed?'草稿自动保留':'未写入项目')}
   onReady={()=>{engineReady.current=true;setReady(true);}} onChange={value=>{generation.current=value;setChanged(true);c.markDirty(view.id,true);}} onSnapshot={value=>void snapshot(value).catch(e=>setError(errorText(e)))} onError={c.report} onSave={()=>void saveCopy()} onOpen={()=>input.current?.click()}/></Suspense></div>}
 </div>;
}
