import {lazy,Suspense,useContext,useRef} from 'react';
import {Save,Play,Download,FileText} from 'lucide-react';
import {CodeEditor} from '../CodeEditor';
import {download} from '../documents/drafts';
import type {SourceFormat} from '../documents/types';
import {nativeFormat} from './useManuscript';
import {WorkbenchContext} from './context';
const Office=lazy(()=>import('../documents/DocxDocumentEditor'));
const Pdf=lazy(()=>import('../documents/PdfPreview'));
export function FileName({name}:{name:string}){const dot=name.endsWith('.univer.json')?name.length-12:name.lastIndexOf('.');return <span className="native-filename"><span>{dot>0?name.slice(0,dot):name}</span>{dot>0&&<span className="native-file-extension">{name.slice(dot)}</span>}</span>;}
export function DocumentPanel({format}:{format:SourceFormat}){
 const ctx=useContext(WorkbenchContext)!,m=ctx.manuscript,input=useRef<HTMLInputElement>(null),doc=m.doc,d=m.draft;
 if(!doc||!d)return <p className="editor-empty">读取论文源稿…</p>;
 const primary=nativeFormat(doc.source_state.mode)===format,dirty=format==='docx'?d.docxDirty:d.latexDirty;
 return <div className="native-paper-workspace native-content-view">
  <input ref={input} type="file" accept=".docx" hidden onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void ctx.openLocalDocx(file).catch(ctx.report);}}/>
  {format==='latex'&&<><div className="native-toolbar"><span className="native-file-label"><FileText/><FileName name={m.filename(format)}/></span><span className="native-save-status" role="status">{dirty?'草稿未保存到项目':m.notice||'已保存 · r'+doc.revision}</span><button className="native-icon" aria-label="下载当前草稿" title="下载当前草稿" onClick={()=>void m.downloadDraft(format)}><Download/></button><button className="native-button" disabled={m.busy} onClick={()=>void m.saveAction(format)}><Save/>保存</button><button className="native-button primary" disabled={m.busy||!doc.adapters.latex.compiler_available} onClick={()=>void m.saveAction(format,true)}><Play/>保存并编译</button></div><div className="native-source-binding"><span>{primary?'论文源稿':'独立稿件 · 保存只更新此文件'}</span>{!primary&&nativeFormat(doc.source_state.mode)&&<button className="native-text-button" disabled={m.busy} onClick={()=>void m.select(format)}>设为论文源稿</button>}</div></>}
  {format==='latex'?<div className="native-latex-split"><section className="native-latex-source"><div className="native-editor-heading">LaTeX 源码{!doc.adapters.latex.compiler_available&&<span>编译器未配置</span>}</div><CodeEditor text={d.latex} language="latex" viewId={doc.id+':latex'} ariaLabel="LaTeX 论文源码" onPosition={()=>{}} onChange={m.editLatex}/></section><Suspense fallback={<p className="editor-empty">打开 PDF…</p>}><Pdf record={doc.render} revision={doc.revision} dirty={d.latexDirty}/></Suspense></div>:<div className="native-docx-workspace"><Suspense fallback={<p className="editor-empty">加载 DOCX 编辑器…</p>}><Office key={doc.id+':'+m.editorKey} ref={m.editor} initial={m.docxInput} title={m.filename('docx')} theme={ctx.theme} primary={primary} busy={m.busy} onMakePrimary={()=>void m.select('docx')} onReload={()=>void m.reload()}
    status={dirty?'草稿未保存到项目':m.notice||'已保存 · r'+doc.revision} ready={m.ready} onDownload={()=>void m.downloadDraft('docx')}
    onReady={()=>m.setReady(true)} onChange={m.changeDocx} onSnapshot={m.snapshot} onError={ctx.report} onSave={()=>void m.saveAction('docx')} onOpen={()=>input.current?.click()}/></Suspense></div>}
 </div>;
}
export function ChooseManuscript(){const ctx=useContext(WorkbenchContext)!,m=ctx.manuscript,input=useRef<HTMLInputElement>(null);return <div className="native-empty"><h1>选择论文源稿</h1><p>用一份 DOCX 文件或 LaTeX 源稿开始。其他格式的稿件分别保存，不会自动转换。</p><div className="native-create-actions"><button className="native-button primary" onClick={()=>input.current?.click()}>上传 DOCX</button><button className="native-button" onClick={()=>{m.create('docx');ctx.openDocument('docx',false);}}>新建 DOCX</button><button className="native-button" onClick={()=>{m.create('latex');ctx.openDocument('latex',false);}}>新建 LaTeX</button></div><input ref={input} type="file" accept=".docx" hidden onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(file)void m.importDocx(file).then(()=>ctx.openDocument('docx',false));}}/>{m.doc?.sources.univer!=null&&<p><button className="native-text-button" onClick={()=>download(JSON.stringify(m.doc!.sources.univer,null,2),'manuscript-history.univer.json','application/json')}>下载历史 Univer 快照</button></p>}</div>;}
