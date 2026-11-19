import {useContext,useRef,useState} from 'react';
import {Plus} from 'lucide-react';
import {command,CommandError,requestId} from '../api';
import {WorkbenchContext} from './context';
import {errorText} from './useManuscript';
import type {Progress} from './researchProgress';
export function ResearchRootSetup({progress,onSaved}:{progress:Progress;onSaved:()=>Promise<void>}){
 const c=useContext(WorkbenchContext)!,[open,setOpen]=useState(false),[title,setTitle]=useState(''),[chosen,setChosen]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),pending=useRef<any>(null);
 if(progress.root_question_id)return null;
 const roots=progress.questions.filter(q=>!q.parent_id);
 async function save(){setBusy(true);setError('');try{const fields=pending.current||{project_id:c.project.id,expected_project_revision:progress.project.revision,...(chosen?{question_id:chosen}:{title}),attach_roots:true,expected_roots:roots.filter(q=>q.id!==chosen).map(q=>({id:q.id,revision:q.revision})),request_key:requestId()};pending.current=fields;await command('workbench.root.set',fields);pending.current=null;await c.refreshResearch();await c.refresh();await onSaved();setOpen(false);}catch(e){if(e instanceof CommandError)pending.current=null;setError(errorText(e));}finally{setBusy(false);}}
 return <section className="research-root-setup"><div><span>文章研究问题尚未设置</span><button className="inline-ref" aria-expanded={open} onClick={()=>setOpen(v=>!v)}><Plus/>设置根问题</button></div>{open&&<form onSubmit={e=>{e.preventDefault();void save();}}>{roots.length>0&&<label>使用已有问题<select aria-label="选择文章根问题" value={chosen} onChange={e=>{pending.current=null;setChosen(e.target.value);}}><option value="">建立一个总体研究问题</option>{roots.map(q=><option key={q.id} value={q.id}>{q.number} · {q.title}</option>)}</select></label>}{!chosen&&<label>这篇文章希望回答什么？<input aria-label="文章研究问题" required maxLength={500} value={title} onChange={e=>{pending.current=null;setTitle(e.target.value);}} placeholder="用一个研究问题组织这篇文章"/></label>}<p>现有顶层问题将成为它的子问题；各自的正文和历史都会保留。根问题也有自己的 QAEC。</p>{error&&<p role="alert" className="partner-error">{error}</p>}<button className="button" disabled={busy}>{busy?'正在设置…':'建立文章根问题'}</button></form>}</section>;
}
