import {useContext,useState} from 'react';
import {ArrowRight,BookOpen,ChevronRight,FileText,Folder,RefreshCw,Sparkles} from 'lucide-react';
import {WorkbenchContext} from './context';
import {openPartnerTurn,outstanding,partnerStatus,startPartner,usePartnerHistory} from './ProjectPartner';
import {FreeResearchGraph,type GraphSummary} from './FreeResearchGraph';
import {excerpt} from './researchProgress';
import './research-progress.css';

export function ProjectOverview(){
 const c=useContext(WorkbenchContext)!,project=c.project.id,[summary,setSummary]=useState<GraphSummary|null>(null),[resources,setResources]=useState(false);
 const history=usePartnerHistory(c),active=history.items.filter(x=>['queued','running'].includes(x.task.status)),attention=history.items.filter(x=>outstanding(x)>0||['failed','waiting_input','waiting_authorization','blocked'].includes(x.task.status));
 const notes=(c.session?.entries||[]).filter((n:any)=>n.relative_path?.endsWith('.md'));
 const featured=(c.project.metadata?.featured_objects||[]).map((id:string)=>c.catalog.objects.find(o=>o.id===id&&o.project_id===project&&!o.archived)).filter(Boolean);
 const hasWork=(c.research?.questions||[]).length||notes.length>1||featured.length;
 const prompt=hasWork?'先梳理我已有的研究：当前能够回答什么、依据是什么、还有哪些未知？请建议最值得推进的一步，说明理由。':'我有一个还没想清楚的研究想法，想和你一起讨论。';
 return <div className="research-progress-workspace"><header className="progress-project-summary"><div className="progress-project-title"><h1>{c.project.title}</h1><button className="button quiet" onClick={()=>startPartner(c,prompt)}><Sparkles/>{hasWork?'一起确定下一步':'说说研究想法'}<ArrowRight/></button></div>
 <div className="progress-current-summary" aria-label="当前工作摘要">{summary?.conclusions.length?summary.conclusions.slice(0,2).map(item=><p key={item.label}><strong>{item.label}</strong><span>{item.text}</span></p>):<p>{c.project.content?.description||'带着一个想法，或接着已有记录，都可以从这里展开研究。'}</p>}</div>
 <div className="progress-work-status" aria-label="当前工作进度">{active.length?<button className="progress-running" onClick={()=>openPartnerTurn(c,active[0].task.id)}><i/>{partnerStatus(active[0].task.status)} · {excerpt(active[0].task.payload.request,55)}<ArrowRight/></button>:attention.length?<button onClick={()=>openPartnerTurn(c,attention.at(-1)!.task.id)}>{attention.length} 轮工作有建议或结果需要你查看<ArrowRight/></button>:<span>{summary?`${summary.questions} 个研究问题 · ${summary.answered} 个已有回答${summary.review?' · '+summary.review+' 个节点待复核':''}`:'正在读取研究进展…'}</span>}<button className="icon-button" aria-label="刷新研究进展" onClick={()=>void c.refreshResearch()}><RefreshCw/></button></div></header>
 <FreeResearchGraph key={project} onSummary={setSummary}/>
 <footer className="progress-project-resources"><button className="inline-ref" aria-expanded={resources} onClick={()=>setResources(x=>!x)}><Folder/>项目内容<ChevronRight className={resources?'expanded':''}/></button><button className="inline-ref" onClick={()=>c.open({id:'background',kind:'background',title:'背景'},true)}><FileText/>背景</button><button className="inline-ref" onClick={()=>c.open({id:'materials',kind:'materials',title:'研究材料'})}>材料与记录</button><button className="inline-ref" onClick={c.openPaper}><BookOpen/>论文源稿</button>{c.project.metadata?.synthetic&&<span>合成示例</span>}</footer>
 {resources&&<section className="progress-resources-drawer" aria-label="项目内容">{c.project.metadata?.research_root_question_id&&<button className="wb-question-link" onClick={()=>c.open({id:c.project.metadata.research_root_question_id,kind:"question",title:"原有研究记录",data:{legacy:true}})}><span>原有研究记录与历史</span><ChevronRight/></button>}{featured.map((o:any)=><button key={o.id} className="wb-question-link" onClick={()=>o.kind==='paper'?c.openPaper():c.open({id:o.id,kind:'object',title:o.title,value:o.id})}><span>{o.title}</span><ChevronRight/></button>)}{notes.map((n:any)=><button className="wb-question-link" key={n.relative_path} onClick={()=>c.openNote(n.relative_path)}><span>{n.relative_path}</span><ChevronRight/></button>)}{!notes.length&&!featured.length&&<p>还没有笔记或登记成果，可以从左侧新建内容。</p>}</section>}
 </div>;
}
