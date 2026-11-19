import {lazy,Suspense,useContext,useEffect,useRef,useState} from 'react';
import {Save,Play,Download,FileText} from 'lucide-react';
import {CodeEditor} from '../CodeEditor';
import {download} from '../documents/drafts';
import type {SourceFormat} from '../documents/types';
import {errorText,nativeFormat,useManuscript,type ManuscriptController} from './useManuscript';
import {WorkbenchContext,type ViewSpec} from './context';
const Office=lazy(()=>import('../documents/DocxDocumentEditor'));
const Pdf=lazy(()=>import('../documents/PdfPreview'));
export function FileName({name}:{name:string}){const dot=name.endsWith('.univer.json')?name.length-12:name.lastIndexOf('.');return <span className="native-filename"><span>{dot>0?name.slice(0,dot):name}</span>{dot>0&&<span className="native-file-extension">{name.slice(dot)}</span>}</span>;}
export const manuscriptExtension=(format:SourceFormat)=>format==='docx'?'.docx':'.tex';
export function manuscriptView(format:SourceFormat,objectId:string,primaryId:string|undefined,title:string,path?:string):ViewSpec{
 return {id:objectId===primaryId?format:'manuscript:'+objectId+':'+format,kind:format,title,value:path,
  ...(objectId!==primaryId?{data:{object_id:objectId}}:{})};
}
export function AdditionalManuscriptPanel({view,format}:{view:ViewSpec;format:SourceFormat}){
 const ctx=useContext(WorkbenchContext)!,project=ctx.project.id;
 const [error,setError]=useState('');
 const m=useManuscript(ctx.report,()=>{ctx.pin(view.id);ctx.markDirty(view.id,true);},()=>{
  void Promise.all([ctx.refresh(),ctx.manuscript.refreshFiles()]).catch(ctx.report);
 },{id:view.data.object_id,format,filename:view.title});
 useEffect(()=>{
  let active=true;
  void m.load(project).catch(e=>{if(active)setError(errorText(e));});
  ctx.registerFileFlush(view.id,m.flush);
  return()=>{active=false;ctx.registerFileFlush(view.id,null);};
 },[project,view.id]);
 useEffect(()=>{
  if(m.draft)ctx.markDirty(view.id,format==='docx'?m.draft.docxDirty:m.draft.latexDirty);
 },[m.draft,view.id,format]);
 return error?<p className="native-alert" role="alert">{error}</p>:<DocumentPanel format={format} manuscript={m}/>;
}

export function DocumentPanel({format,manuscript}:{format:SourceFormat;manuscript?:ManuscriptController}){
 const ctx=useContext(WorkbenchContext)!,m=manuscript||ctx.manuscript,input=useRef<HTMLInputElement>(null),doc=m.doc,d=m.draft;
 if(!doc||!d)return <p className="editor-empty">读取论文源稿…</p>;
 const primary=!manuscript&&nativeFormat(doc.source_state.mode)===format;
 const dirty=format==='docx'?d.docxDirty:d.latexDirty;
 const saved=format==='docx'?!!doc.sources.docx:!!doc.sources.latex.trim();
 const status=dirty?'草稿未保存到项目':m.notice||(saved?'已保存 · r'+doc.revision:'尚未保存内容');
 return <div className="native-paper-workspace native-content-view">
  {manuscript&&(m.remote||m.backup)&&<div className="native-source-binding">
   {m.remote&&<><span>项目中有新版 · r{m.remote.revision}</span><button className="native-text-button" disabled={m.busy} onClick={()=>void m.reload()}>保留草稿并载入新版</button></>}
   {m.backup&&<button className="native-text-button" disabled={m.busy} onClick={()=>void m.restore()}>恢复上一份本地草稿</button>}
  </div>}
  <input ref={input} type="file" accept=".docx" hidden onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void ctx.openLocalDocx(file).catch(ctx.report);}}/>
  {format==='latex'&&<><div className="native-toolbar"><span className="native-file-label"><FileText/><FileName name={m.filename(format)}/></span><span className="native-save-status" role="status">{status}</span><button className="native-icon" aria-label="下载当前草稿" title="下载当前草稿" onClick={()=>void m.downloadDraft(format)}><Download/></button><button className="native-button" disabled={m.busy} onClick={()=>void m.saveAction(format)}><Save/>保存</button><button className="native-button primary" disabled={m.busy||!doc.adapters.latex.compiler_available} onClick={()=>void m.saveAction(format,true)}><Play/>保存并编译</button></div><div className="native-source-binding"><span>{primary?'论文源稿':'独立稿件 · 保存只更新此文件'}</span>{!manuscript&&!primary&&nativeFormat(doc.source_state.mode)&&<button className="native-text-button" disabled={m.busy} onClick={()=>void m.select(format)}>设为论文源稿</button>}</div></>}
  {format==='latex'?<div className="native-latex-split"><section className="native-latex-source"><div className="native-editor-heading">LaTeX 源码{!doc.adapters.latex.compiler_available&&<span>编译器未配置</span>}</div><CodeEditor text={d.latex} language="latex" viewId={doc.id+':latex'} ariaLabel="LaTeX 论文源码" onPosition={()=>{}} onChange={m.editLatex}/></section><Suspense fallback={<p className="editor-empty">打开 PDF…</p>}><Pdf record={doc.render} revision={doc.revision} dirty={d.latexDirty}/></Suspense></div>:<div className="native-docx-workspace"><Suspense fallback={<p className="editor-empty">加载 DOCX 编辑器…</p>}><Office key={doc.id+':'+m.editorKey} ref={m.editor} initial={m.docxInput} title={m.filename('docx')} theme={ctx.theme} primary={primary} busy={m.busy} onMakePrimary={manuscript?undefined:()=>void m.select('docx')} onReload={()=>void m.reload()}
    status={status} ready={m.ready} onDownload={()=>void m.downloadDraft('docx')}
    onReady={()=>m.setReady(true)} onChange={m.changeDocx} onSnapshot={m.snapshot} onError={ctx.report} onSave={()=>void m.saveAction('docx')} onOpen={()=>input.current?.click()}/></Suspense></div>}
 </div>;
}
export function ChooseManuscript(){const ctx=useContext(WorkbenchContext)!,m=ctx.manuscript,input=useRef<HTMLInputElement>(null);return <div className="native-empty"><h1>选择论文源稿</h1><p>用一份 DOCX 文件或 LaTeX 源稿开始。其他格式的稿件分别保存，不会自动转换。</p><div className="native-create-actions"><button className="native-button primary" onClick={()=>input.current?.click()}>上传 DOCX</button><button className="native-button" onClick={()=>{m.create('docx');ctx.openDocument('docx',false);}}>新建 DOCX</button><button className="native-button" onClick={()=>{m.create('latex');ctx.openDocument('latex',false);}}>新建 LaTeX</button></div><input ref={input} type="file" accept=".docx" hidden onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void m.importDocx(file).then(()=>ctx.openDocument('docx',false));}}/>{m.doc?.sources.univer!=null&&<p><button className="native-text-button" onClick={()=>download(JSON.stringify(m.doc!.sources.univer,null,2),'manuscript-history.univer.json','application/json')}>下载历史 Univer 快照</button></p>}</div>;}
