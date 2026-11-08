import {useContext,useRef,useState} from 'react';
import {Check,Link2,Plus,Save,X} from 'lucide-react';
import {command,CommandError,requestId} from '../api';
import {WorkbenchContext} from './context';
import {errorText} from './useManuscript';
import {dependencyNames,nodeLabel,nodeStatusNames,parts,partNames,type NodeStatus,type Part,type Progress,type ProgressQuestion,type NodeDependency} from './researchProgress';

type Link=Pick<NodeDependency,'question_id'|'part'|'kind'>;
export function ResearchNodeControls({question:q,part,progress,onSaved}:{question:ProgressQuestion;part:Part;progress:Progress;onSaved:()=>Promise<void>}){
 const c=useContext(WorkbenchContext)!,node=q.parts[part].node;
 const [open,setOpen]=useState(false);
 return <section className="research-node-management"><div className="node-current-state"><span className={'node-state-label state-'+node.status}>{nodeStatusNames[node.status]}</span>{node.flags.includes('blocked')&&node.status!=='blocked'&&<span className="node-dependency-warning">{node.blockers.length} 项完成条件未满足</span>}<button className="inline-ref" aria-expanded={open} onClick={()=>setOpen(x=>!x)}>{open?'收起配置':'标题、状态与依赖'}</button></div>
 {node.confirmation&&<p className="node-confirmation-note">{node.status==='stale'?'此前确认':'确认记录'} · {node.confirmation.note}</p>}
 {node.dependencies.length>0&&<div className="node-dependency-list" aria-label="节点完成条件">{node.dependencies.map(d=>{const source=progress.questions.find(x=>x.id===d.question_id);return <button key={d.id} className={'node-dependency-item state-'+d.status} disabled={!d.available} onClick={()=>{if(source)c.open({id:source.id,kind:'question',title:source.title,value:source.id,data:{part:d.part}},true);}}><Link2/><span>{source?nodeLabel(source,d.part):'不可用节点'} · {d.title||partNames[d.part]}</span><small>{dependencyNames[d.kind]} · {nodeStatusNames[d.status]}</small></button>;})}</div>}
 {open&&<NodeForm key={q.id+':'+part} question={q} part={part} progress={progress} onSaved={async()=>{await onSaved();setOpen(false);}}/>}
 </section>;
}
function NodeForm({question:q,part,progress,onSaved}:{question:ProgressQuestion;part:Part;progress:Progress;onSaved:()=>Promise<void>}){
 const c=useContext(WorkbenchContext)!,node=q.parts[part].node,[snapshot]=useState(progress),[base]=useState(q.revision);
 const [title,setTitle]=useState(node.title),[status,setStatus]=useState<NodeStatus>(node.stored_status),[links,setLinks]=useState<Link[]>(node.dependencies.filter(d=>!d.builtin).map(({question_id,part,kind})=>({question_id,part,kind}))),[source,setSource]=useState(''),[kind,setKind]=useState<Link['kind']>('requires'),[note,setNote]=useState(''),[answers,setAnswers]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const pending=useRef<any>(null),candidates=snapshot.questions.flatMap(q=>parts.map(p=>({q,p,node:q.parts[p].node}))),builtin=node.dependencies.filter(d=>d.builtin),selected=[...builtin,...links];
 function change(fn:()=>void){pending.current=null;setError('');fn();}
 async function save(){if(busy)return;setBusy(true);setError('');try{
  const fields=pending.current||{project_id:c.project.id,question_id:q.id,part,expected_revision:base,title,status,dependencies:links,
   expected_dependencies:selected.map(d=>{const item=candidates.find(x=>x.q.id===d.question_id&&x.p===d.part);return {id:d.question_id+':'+d.part,signature:item?.node.signature||'unavailable'};}),confirmation_note:note,answers_question:answers,request_key:requestId()};pending.current=fields;
  await command('workbench.node.save',fields);pending.current=null;await c.refreshResearch();await c.refresh();await onSaved();
 }catch(e){if(e instanceof CommandError)pending.current=null;setError(errorText(e));}finally{setBusy(false);}}
 return <form className="research-node-form" onSubmit={e=>{e.preventDefault();void save();}} aria-label="编辑节点配置"><label>具体标题<input aria-label="节点标题" value={title} readOnly={part==='Q'} maxLength={500} required onChange={e=>change(()=>setTitle(e.target.value))} placeholder={'为这项'+partNames[part]+'命名'}/></label>{part==='Q'&&<p>问题表述在研究正文中编辑，这里管理它的研究进度。</p>}<label>进度<select aria-label="节点状态" value={status} onChange={e=>change(()=>setStatus(e.target.value as NodeStatus))}>{(['unmarked','not_started','active','review','completed','paused'] as NodeStatus[]).map(s=><option key={s} value={s}>{nodeStatusNames[s]}</option>)}</select></label>
 <fieldset><legend>完成与复核的依据</legend>{selected.map((d,i)=>{const item=candidates.find(x=>x.q.id===d.question_id&&x.p===d.part);return <div key={d.question_id+':'+d.part} className="node-config-dependency"><span>{item?nodeLabel(item.q,item.p)+' · '+(item.node.title||partNames[item.p]):'节点不可用'}<small>{dependencyNames[d.kind]} · {item?nodeStatusNames[item.node.status]:'不可用'}</small></span>{i<builtin.length?<small>固定条件</small>:<button type="button" className="icon-button" aria-label={'移除依赖 '+(item?nodeLabel(item.q,item.p):i)} onClick={()=>change(()=>setLinks(links.filter((_,j)=>j!==i-builtin.length)))}><X/></button>}</div>;})}
 <div className="node-add-dependency"><select aria-label="依赖节点" value={source} onChange={e=>setSource(e.target.value)}><option value="">选择依据节点…</option>{candidates.filter(x=>x.node.id!==node.id&&!selected.some(d=>d.question_id===x.q.id&&d.part===x.p)).map(x=><option key={x.node.id} value={x.node.id}>{nodeLabel(x.q,x.p)} · {x.node.title||partNames[x.p]}</option>)}</select><select aria-label="依赖关系" value={kind} onChange={e=>setKind(e.target.value as Link['kind'])}>{Object.entries(dependencyNames).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select><button type="button" className="icon-button" disabled={!source} aria-label="添加依赖" onClick={()=>change(()=>{const item=candidates.find(x=>x.node.id===source);if(item)setLinks([...links,{question_id:item.q.id,part:item.p,kind}]);setSource('');})}><Plus/></button></div><p>所选依据需要完成并保持当前版本；拆解关系不自动成为完成条件。</p></fieldset>
 {status==='completed'&&<><label>核对说明<textarea aria-label="节点完成说明" value={note} maxLength={4000} required onChange={e=>change(()=>setNote(e.target.value))} placeholder={part==='Q'?'说明结论怎样回答这个问题':'说明已核对的内容、依据与适用范围'}/></label>{part==='Q'&&<label className="node-answer-confirmation"><input type="checkbox" aria-label="确认结论足以回答问题" checked={answers} required onChange={e=>change(()=>setAnswers(e.target.checked))}/>已核对：结论足以回答这个问题，包括阴性结果。</label>}</>}
 <p>本次核对项目保存版 r{base}，不包含尚未保存的正文草稿。{base!==q.revision?' 保存版已有变化，请保留输入并重新打开配置核对。':''}</p>{error&&<p className="partner-error" role="alert">{error} 输入仍保留。</p>}<button className="button" type="submit" disabled={busy}>{status==='completed'?<Check/>:<Save/>}{busy?'正在保存…':status==='completed'?'确认完成':'保存节点配置'}</button>
 </form>;
}
