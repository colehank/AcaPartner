import {useContext,useEffect,useRef,useState} from 'react';
import {get,set,del} from 'idb-keyval';
import {Save,Download,GitCompareArrows} from 'lucide-react';
import {CodeEditor} from '../CodeEditor';
import {command,requestId} from '../api';
import {editorDraftKey,download} from '../documents/drafts';
import {WorkbenchContext} from './context';
import {errorText} from './useManuscript';
type Saved={code:string;sha256:string};
type Draft={text:string;base:string;before:string};
export function ScriptPanel({filename,panelId,startEditing=false}:{filename:string;panelId:string;startEditing?:boolean}){
 const c=useContext(WorkbenchContext)!,project=c.project.id;
 const [draft,setDraft]=useState<Draft|null>(null),[remote,setRemote]=useState<Saved|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[compare,setCompare]=useState(false),[backup,setBackup]=useState(false);
 const current=useRef(draft),key=useRef(''),pending=useRef<Promise<unknown>>(Promise.resolve());current.current=draft;
 const writable=c.catalog.project_management.writable_project_ids.includes(project),dirty=!!draft&&draft.text!==draft.before;
 const read=()=>command('recipe.script.read',{project_id:project,payload:{filename}}) as Promise<Saved>;
 function keep(next:Draft){current.current=next;setDraft(next);}
 function flush(){const value=current.current,where=key.current;if(!value||!where)return pending.current;pending.current=pending.current.catch(()=>{}).then(()=>value.text!==value.before?set(where,value):del(where));return pending.current;}
 useEffect(()=>{let alive=true;setDraft(null);setError('');setRemote(null);setCompare(false);key.current='';void(async()=>{
  const [saved,where]=await Promise.all([read(),editorDraftKey('script:'+project+':'+filename)]);
  const [local,previous]=await Promise.all([get<Draft>(where),get<Draft>(where+':backup')]);if(!alive)return;
  key.current=where;const restored=local&&typeof local.text==='string'&&typeof local.before==='string'&&/^[a-f0-9]{64}$/.test(local.base)?local:null;
  keep(restored||{text:saved.code,before:saved.code,base:saved.sha256});setBackup(!!previous);if(restored&&restored.base!==saved.sha256)setRemote(saved);
 })().catch(e=>alive&&setError(errorText(e)));return()=>{alive=false;};},[project,filename]);
 useEffect(()=>{c.markDirty(panelId,dirty);},[dirty,panelId]);
 useEffect(()=>{const timer=setTimeout(()=>{void flush().catch(e=>setError('草稿尚未保留：'+errorText(e)));},650);return()=>clearTimeout(timer);},[draft]);
 useEffect(()=>{c.registerFileFlush(panelId,async()=>{await flush();});return()=>c.registerFileFlush(panelId,null);},[panelId,project,filename]);
 async function save(){const sent=current.current;if(!sent||busy||!writable||sent.text===sent.before)return;
  if(new TextEncoder().encode(sent.text).length>1024*1024){setError('脚本超过 1 MiB 保存上限；请下载当前草稿后拆分文件。');return;}
  setBusy(true);setError('');try{
   const value=await command('recipe.script.write',{project_id:project,request_id:requestId(),payload:{filename,code:sent.text,expected_sha256:sent.base}}) as Saved;
   keep({text:current.current?.text??sent.text,before:sent.text,base:value.sha256});setRemote(null);setCompare(false);await flush();
  }catch(e){setError(errorText(e));try{const value=await read();if(value.sha256!==sent.base)setRemote(value);}catch{}await flush().catch(()=>{});}finally{setBusy(false);}
 }
 async function loadRemote(){if(!remote||!draft)return;setBusy(true);try{await set(key.current+':backup',draft);setBackup(true);keep({text:remote.code,before:remote.code,base:remote.sha256});setRemote(null);setError('');setCompare(false);await flush();}catch(e){setError(errorText(e));}finally{setBusy(false);}}
 async function restore(){setBusy(true);try{const value=await get<Draft>(key.current+':backup');if(value){if(current.current)await set(key.current+':backup',current.current);keep(value);const saved=await read();setRemote(value.base!==saved.sha256?saved:null);await flush();}}catch(e){setError(errorText(e));}finally{setBusy(false);}}
 if(!draft)return <p className="editor-empty" role={error?'alert':'status'}>{error||'读取项目工作副本…'}</p>;
 return <div className="wb-note wb-source-panel" onKeyDown={e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='s'){e.preventDefault();void save();}}}>
  <div className="editor-toolbar"><span className="breadcrumbs">scripts/{filename}</span><span className="runtime-caption" role="status">{busy?'保存中…':dirty?'草稿未保存':'项目工作副本 · 已保存'}</span><button className={'button quiet '+(compare?'active':'')} aria-pressed={compare} onClick={()=>setCompare(v=>!v)}><GitCompareArrows/>比较修改</button><button className="button quiet" disabled={!dirty||busy||!writable} onClick={()=>void save()}><Save/>保存</button><button className="icon-button" aria-label="下载脚本草稿" onClick={()=>download(draft.text,filename,'text/x-python')}><Download/></button></div>
  <div className="wb-code-caption">工作副本可编辑；登记源码快照与已有研究结果保持原版本。保存不执行脚本。</div>
  {error&&<p role="alert" className="native-alert">{error}</p>}
  {remote&&<div className="native-alert" role="status">项目工作副本已有新版，当前草稿已保留。<button className="button quiet" onClick={()=>setCompare(true)}>比较项目新版</button><button className="button quiet" disabled={busy} onClick={()=>void loadRemote()}>保留草稿并载入新版</button></div>}
  {backup&&<button className="wb-backup-link" disabled={busy} onClick={()=>void restore()}>恢复保留的脚本草稿</button>}
  {compare&&<div className="wb-diff-caption">{remote?'项目新版':'保存版'} → 当前草稿 · 删除与新增按行标注</div>}
  <CodeEditor jump={startEditing?1:0} text={draft.text} original={compare?(remote?.code??draft.before):undefined} filename={filename} language="python" readOnly={!writable} viewId={panelId} ariaLabel="Python 工作副本" onPosition={()=>{}} onChange={text=>{keep({...current.current!,text});c.pin(panelId);}}/>
 </div>;
}
