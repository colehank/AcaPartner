import {useContext,useEffect,useRef,useState} from 'react';
import {ArrowRight,GitCompareArrows,History,X} from 'lucide-react';
import {command,CommandError} from '../api';
import {WorkbenchContext} from './context';
import {CodeEditor} from '../CodeEditor';
import {Markdown} from './ContentPanels';
import {startPartner} from './ProjectPartner';
import {openResearchWork} from './ResearchWorkPanel';
import {sourceView} from './researchReading';
import {errorText} from './useManuscript';
import {partNames,parts,currentVersion,nodeLabel,type Part,type Revision,type Progress} from './researchProgress';
import {ResearchNodeControls} from './ResearchNodeControls';
import type {ProgressSelection} from './ResearchProgressGraph';

export function ResearchProgressDetail({selection,onSelect,close,progress,onSaved}:{selection:ProgressSelection;onSelect:(value:ProgressSelection)=>void;close:()=>void;progress:Progress;onSaved:()=>Promise<void>}){
 const c=useContext(WorkbenchContext)!,{question:q,part,version:v}=selection,project=c.project.id;
 const [body,setBody]=useState(''),[old,setOld]=useState(''),[compare,setCompare]=useState(false),[loading,setLoading]=useState(true),[error,setError]=useState(''),[pageError,setPageError]=useState(''),[versions,setVersions]=useState<Record<Part,Revision[]>>(()=>Object.fromEntries(parts.map(p=>[p,q.parts[p].versions])) as Record<Part,Revision[]>),[cursor,setCursor]=useState<number|null>(null),[historyBusy,setHistoryBusy]=useState(false);
 const list=versions[part]||[],index=list.findIndex(x=>x.id===v.id),previous=index>=0?list[index+1]:undefined;
 const historySequence=useRef(0);
 useEffect(()=>setCompare(false),[part]);
 async function history(before?:number){const seq=++historySequence.current;setHistoryBusy(true);setPageError('');try{
  const result=await command('workbench.progress.history',{project_id:project,question_id:q.id,...(before?{before_revision:before}:{})});
  if(seq!==historySequence.current)return;
  if(result?.project_id!==project||result.question_id!==q.id)throw new Error('修订历史不属于当前问题。');
  setVersions(current=>Object.fromEntries(parts.map(p=>[p,[...new Map([...(before?current[p]:[]),...result.versions[p]].map((r:Revision)=>[r.id,r])).values()].sort((a:any,b:any)=>b.revision-a.revision)])) as Record<Part,Revision[]>);setCursor(result.next_before_revision);
 }catch(e){if(seq===historySequence.current)setPageError(errorText(e));}finally{if(seq===historySequence.current)setHistoryBusy(false);}}
 useEffect(()=>{setVersions(Object.fromEntries(parts.map(p=>[p,q.parts[p].versions])) as Record<Part,Revision[]>);setCursor(null);void history();return()=>{historySequence.current++;};},[project,q.id]);
 async function read(r:Revision){const params=new URLSearchParams({revision:String(r.revision),consumer:project}),response=await fetch('/api/objects/'+encodeURIComponent(q.id)+'?'+params),value=await response.json();if(!response.ok||!value.ok)throw new CommandError(value.code,value.error||'这份保存版无法读取。',value.details);const obj=value.result;if(obj.id!==q.id||obj.project_id!==project||obj.revision!==r.revision||typeof obj.content?.qaec?.[part]!=='string')throw new Error('保存版身份不匹配，未展示含混的内容。');return obj.content.qaec[part] as string;}
 useEffect(()=>{let live=true;setLoading(true);setError('');setBody('');setOld('');void Promise.all([read(v),compare&&previous?read(previous):Promise.resolve('')]).then(([text,before])=>{if(live){setBody(text);setOld(before);setLoading(false);}}).catch(e=>{if(live){setError(errorText(e));setLoading(false);}});return()=>{live=false;};},[q.id,part,v.id,v.revision,compare,previous?.id,project]);
 function openCurrent(){c.open({id:q.id,kind:'question',title:q.title,value:q.id,data:{part}},true);requestAnimationFrame(()=>document.dispatchEvent(new CustomEvent('wb-research-jump',{detail:{projectId:project,id:q.id,part}})));}
 return <aside className="progress-inspector" aria-label="节点内容与版本"><div className="progress-inspector-heading"><div><h3>{nodeLabel(q,part)} · {selection.historical?(v.title||partNames[part]):q.parts[part].node.title||partNames[part]}</h3><span>{selection.historical?'历史内容':'最新内容'} · r{v.revision}{!selection.historical&&q.revision!==v.revision?' · 当前Q保存于r'+q.revision:''}</span></div>{selection.historical&&<button className="button quiet" onClick={()=>{setCompare(false);onSelect({question:q,part,version:currentVersion(q,part),historical:false});}}>返回最新</button>}<button className="button quiet" onClick={openCurrent}>打开当前 {part}<ArrowRight/></button><button className="icon-button" aria-label="关闭节点详情" onClick={close}><X/></button></div>
 <div className="progress-inspector-layout"><nav className="progress-revisions" aria-label="内容修订"><h4><History/>修订记录</h4>{list.map(r=><button key={r.id} aria-label={'查看 '+q.number+' '+part+' r'+r.revision} aria-current={r.id===v.id?'true':undefined} onClick={()=>{setCompare(false);onSelect({question:q,part,version:r,historical:r.id!==currentVersion(q,part).id});}}><strong>r{r.revision}</strong><span>{({created:'首次记录',edited:'编辑内容',restored:'恢复旧版',adopted:'采用建议'})[r.change_kind]}</span>{r.id===currentVersion(q,part).id&&<span className="progress-version-latest">最新</span>}<small>{new Intl.DateTimeFormat('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(r.created_at))}</small></button>)}{!list.length&&<p>这一页没有这个阶段的内容改动。</p>}{cursor&&<button className="inline-ref" disabled={historyBusy} onClick={()=>void history(cursor)}>查看更早修订</button>}{pageError&&<p role="alert">{pageError}</p>}</nav>
 <div className="progress-version-body">{!selection.historical&&<ResearchNodeControls key={q.id+':'+part} question={q} part={part} progress={progress} onSaved={onSaved}/>} {error?<p role="alert" className="partner-error">{error}</p>:loading?<p role="status">正在读取固定保存版…</p>:<>{previous&&<button className="button quiet progress-compare" aria-pressed={compare} onClick={()=>setCompare(x=>!x)}><GitCompareArrows/>{compare?'返回正文':'比较 r'+previous.revision+' → r'+v.revision}</button>}{compare&&previous?<div className="progress-diff"><CodeEditor text={body} original={old} readOnly language="markdown" viewId={'progress:'+q.id+':'+part+':'+v.revision} ariaLabel="研究内容版本比较" onChange={()=>{}} onPosition={()=>{}}/></div>:body?<Markdown text={body}/>:<div className="progress-missing-content"><p>这部分还没有记录。</p><button className="inline-ref" onClick={()=>startPartner(c,'围绕「'+q.title+'」，讨论如何补充'+partNames[part]+'，区分需要开展的工作与已有依据。',q.id)}>和搭档补充{partNames[part]}<ArrowRight/></button></div>}
 {v.origin&&(v.origin.available?<div className="progress-version-sources"><span>形成来源</span><button className="inline-ref" onClick={()=>openResearchWork(c,'',v.origin!.task_id)}>查看这次采用的工作建议</button>{v.origin.source_refs?.map(r=><button className="inline-ref" key={r.id+'@'+r.revision} onClick={()=>c.open(sourceView({...r,consumer_id:project},project,r.title),true)}>{r.title} · r{r.revision}</button>)}</div>:<p className="runtime-caption">这次采用仍有记录，来源目前不可读取。</p>)}
 </>}</div></div>
 </aside>;
}
