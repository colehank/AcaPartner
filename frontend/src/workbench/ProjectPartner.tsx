import {useContext,useEffect,useRef,useState} from 'react';
import {ArrowUp,ArrowRight,FileText,PanelRight,Sparkles,ChevronDown} from 'lucide-react';
import {command,CommandError,requestId} from '../api';
import {WorkbenchContext,type WorkbenchValue,type ViewSpec} from './context';
import {Markdown} from './ContentPanels';
import {ResearchExplorationPanel} from './ResearchExplorationPanel';
import {PartnerGraphChange} from './PartnerGraphChange';
import {ResearchWorkPanel,workLabels} from './ResearchWorkPanel';
import {errorText,nativeFormat} from './useManuscript';
import {sourceView,questionLabel} from './researchReading';
import './project-partner.css';

type Attempt={key:string;fields:Record<string,any>};
type Draft={text:string;excluded:string[];extra:string[];provider:string;seconds:string;attempt:Attempt|null;fresh:boolean};
const blank=():Draft=>({text:'',excluded:[],extra:[],provider:'',seconds:'180',attempt:null,fresh:false});
const storageKey=(id:string)=>'acapartner.partner.v1:'+sessionStorage.getItem('acapartner.native-editor-tab')+':'+id;
function stored(key:string):Draft{try{return {...blank(),...JSON.parse(localStorage.getItem(key)||'{}')};}catch{return blank();}}
const pending=(status:string)=>['queued','running'].includes(status);
export const partnerStatus=(status:string)=>status==='generated'?'已回复':workLabels[status]||({blocked:'需要处理阻碍',waiting_authorization:'等待授权'} as any)[status]||'等待处理';
export function startPartner(c:WorkbenchValue,prompt='',questionId=''){
 document.dispatchEvent(new Event('wb-show-agent'));
 window.dispatchEvent(new CustomEvent('wb-partner-seed',{detail:{projectId:c.project.id,prompt,questionId}}));
}
export function openPartnerTurn(c:WorkbenchValue,id:string){c.open({id:'partner:'+id,kind:'partner',title:'搭档回复',value:id},true);}
export function outstanding(item:any){const p=item.proposal?.content;return (p?.research_proposal?.candidates||[]).filter((x:any)=>!item.question_adoptions?.some((a:any)=>a.candidate_id===x.id)).length+(p?.research_update?.changes||[]).filter((x:any)=>!item.work_adoptions?.some((a:any)=>a.change_id===x.id)).length;}
export function usePartnerHistory(c:WorkbenchValue){
 const [items,setItems]=useState<any[]>([]),[error,setError]=useState(''),mounted=useRef(true),context=useRef(c),signature=useRef('');context.current=c;
 const project=c.project?.id;
 async function reload(){if(!project)return [];const value=await command('research.partner.history',{project_id:project});if(!Array.isArray(value?.items)||value.items.some((x:any)=>x.task?.project_id!==project||x.task.payload?.kind!=='research_partner'))throw new Error('搭档记录身份不完整，请重新读取。');if(mounted.current&&context.current.project?.id===project){setItems(value.items);setError('');const next=value.items.map((x:any)=>x.task.id+':'+x.task.status+':'+outstanding(x)+':'+x.task.result?.graph_change?.status).join('|');if(signature.current!==next){signature.current=next;void Promise.all([context.current.refresh(),context.current.refreshResearch()]).catch(context.current.report);}}return value.items;}
 useEffect(()=>{mounted.current=true;let live=true,timer:ReturnType<typeof setTimeout>;const poll=async()=>{try{const rows=await reload();if(live)timer=setTimeout(poll,rows.some((x:any)=>pending(x.task.status))?1500:8000);}catch(e){if(live){setError(errorText(e));timer=setTimeout(poll,8000);}}};void poll();return()=>{mounted.current=false;live=false;clearTimeout(timer);};},[project]);
 return {items,error,reload};
}
function contextOptions(c:WorkbenchValue,questionId=''){
 const active=c.api?.activePanel?.params?.view as ViewSpec|undefined;
 const root=c.project.metadata?.research_root_question_id,questions=(c.research?.questions||[]).filter((q:any)=>q.id!==root),native=[...new Set<string>([
  ...(c.session?.entries||[]).filter((e:any)=>e.relative_path?.endsWith('.md')).map((e:any)=>e.relative_path),
  ...c.manuscript.entries.filter(e=>e.role==='script_working_copy').map(e=>e.path)
 ])];
 const activePath=active?.kind==='note'?active.value:active?.kind==='script'?'scripts/'+active.value:active?.kind==='file'&&native.includes(active.value||'')?active.value:undefined;
 const activeQ=questionId|| (active?.kind==='question'?active.id:'');
 const sources=c.catalog.objects.filter(o=>o.project_id===c.project.id&&!o.archived&&['note','report','literature','concept'].includes(o.kind)&&!o.metadata?.research_exploration&&!o.metadata?.research_work&&!o.metadata?.research_partner&&!o.metadata?.research_context_snapshot&&o.metadata?.research_role!=='research_question_v1');
 const featured:string[]=c.project.metadata?.featured_objects||[];sources.sort((a,b)=>(featured.includes(a.id)?featured.indexOf(a.id):featured.length)-(featured.includes(b.id)?featured.indexOf(b.id):featured.length));
 const choices=[...questions.map((q:any)=>({key:q.id,title:questionLabel(q),type:'question',value:q,detail:'研究问题 · r'+q.revision})),...sources.map(o=>({key:o.id,title:o.title,type:'object',value:o,detail:'保存版 · r'+o.revision})),...native.map(path=>({key:path,title:path,type:'file',value:path,detail:'保存版全文'}))];
 const defaultKeys=[...(activeQ?[activeQ]:(questions.filter((q:any)=>!q.tree_parent_id||q.tree_parent_id===root).length?questions.filter((q:any)=>!q.tree_parent_id||q.tree_parent_id===root):questions).slice(0,4).map((q:any)=>q.id)),...(activePath?[activePath]:[]),...(active?.kind==='object'&&sources.some(o=>o.id===active.value)?[active.value!]:[])];
 for(const item of sources.slice(0,2))if(!defaultKeys.includes(item.id))defaultKeys.push(item.id);
 if(!activePath&&!sources.length)defaultKeys.push(...native.slice(0,2));
 return {choices,defaultKeys:defaultKeys.slice(0,8),active,activePath};
}
export function ProjectPartner(){
 const c=useContext(WorkbenchContext)!,project=c.project?.id;
 if(!project)return <><div className="agent-topbar"><strong><Sparkles/>项目搭档</strong></div><div className="wb-agent-intro"><h2>从一个项目开始</h2><p>打开已有研究，或新建项目写下你的想法。搭档会围绕同一个项目与你讨论、推进工作。</p></div></>;
 return <PartnerComposer key={project}/>;
}
function PartnerComposer(){
 const c=useContext(WorkbenchContext)!,context=useRef(c);context.current=c;
 const project=c.project.id,key=storageKey(project),m=c.manuscript;
 const [draft,setDraft]=useState(()=>stored(key)),[mode,setMode]=useState('conversation'),[busy,setBusy]=useState(false),[error,setError]=useState(''),[authority,setAuthority]=useState<any>(null),[questionId,setQuestionId]=useState('');
 const current=useRef(draft),live=useRef(true),input=useRef<HTMLTextAreaElement>(null),end=useRef<HTMLDivElement>(null);
 const history=usePartnerHistory(c),options=contextOptions(c,questionId);
 const graphFocus=options.active?.kind==='project'&&c.researchFocus?.project_id===project?c.researchFocus:null;
 function save(patch:Partial<Draft>){const next={...current.current,...patch};localStorage.setItem(key,JSON.stringify(next));current.current=next;if(live.current)setDraft(next);}
 const fail=(e:unknown)=>{if(live.current)setError(errorText(e));};
 useEffect(()=>{live.current=true;const seed=(event:Event)=>{const d=(event as CustomEvent).detail;if(d.projectId!==project)return;setMode('conversation');if(current.current.attempt){setError('上一条消息的提交结果尚未确认，先核对原请求。');return;}try{if(d.prompt)save({text:current.current.text.trim()?[current.current.text,d.prompt].join('\n\n'):d.prompt});setQuestionId(d.questionId||'');requestAnimationFrame(()=>input.current?.focus());}catch(e){fail(e);}};window.addEventListener('wb-partner-seed',seed);void command('desk.review.read',{project_id:project}).then(x=>live.current&&setAuthority(x)).catch(fail);return()=>{live.current=false;window.removeEventListener('wb-partner-seed',seed);};},[project]);
 useEffect(()=>{setQuestionId('');},[options.active?.id]);
 useEffect(()=>{end.current?.scrollIntoView({block:'end',behavior:'instant'});},[history.items.length,history.items.at(-1)?.task.status,mode]);
 const selectedKeys=[...new Set([...options.defaultKeys,...draft.extra])].filter(key=>!draft.excluded.includes(key));
 const selected=options.choices.filter(o=>selectedKeys.includes(o.key));
 const providers=(authority?.providers||[]).filter((p:any)=>p.route==='codex'&&p.authorized===true&&p.available!==false),provider=draft.provider||providers[0]?.id||'';
 const seconds=Number(draft.seconds),budgetOK=/^\d+$/.test(draft.seconds)&&seconds>0&&seconds<=900,writable=c.catalog.project_management.writable_project_ids.includes(project);
 const running=history.items.some(x=>pending(x.task.status)),ready=authority?.runtime_running===true&&!!provider&&writable;
 const previous=!draft.fresh?[...history.items].reverse().find(x=>x.task.status==='generated'&&x.proposal)?.task.id:undefined;
 const unsaved=selected.some(o=>o.type==='file'?c.session?.buffers.get(o.key)?.dirty:o.type==='question'?!!localStorage.getItem('acapartner.unified.research-draft:'+sessionStorage.getItem('acapartner.native-editor-tab')+':'+project+':'+o.key):false)||!!c.api?.activePanel?.params?.dirty;
 function toggle(key:string,checked:boolean){try{save({excluded:checked?draft.excluded.filter(x=>x!==key):[...draft.excluded,key],extra:checked?[...new Set([...draft.extra,key])]:draft.extra.filter(x=>x!==key)});}catch(e){fail(e);}}
 async function send(){if(busy)return;setBusy(true);setError('');const uncertain=!!current.current.attempt;try{
  let attempt=current.current.attempt;
  if(!attempt){if(!ready||!budgetOK||!draft.text.trim()||running||selected.length>8)throw new Error('请先检查服务连接、保存来源和执行时限。');
   const fields={project_id:project,request:draft.text,graph_mode:'edit',...(graphFocus?{graph_focus:graphFocus.id}:{}),materials:selected.filter(o=>o.type==='object').map(o=>({id:o.value.id,revision:o.value.revision})),questions:selected.filter(o=>o.type==='question').map(o=>({id:o.value.id,revision:o.value.revision,parts:['A','E','C']})),native_paths:selected.filter(o=>o.type==='file').map(o=>o.key),...(previous?{previous_task_id:previous}:{})};
   const preview=await command('research.partner.preview',fields);
   if(preview?.input?.project?.id!==project||preview.input.request!==fields.request||preview.executed!==false||!/^[a-f0-9]{64}$/.test(preview.input_pin))throw new Error('本次上下文身份不完整，请重新发送。');
   attempt={key:requestId(),fields:{...fields,input_pin:preview.input_pin,provider_id:provider,budget:{max_model_calls:1,timeout_seconds:seconds}}};save({attempt});
  }
  const task=await command('research.partner.submit',{...attempt.fields,request_key:attempt.key});
  if(task?.project_id!==project||task.request_key!==attempt.key||task.payload?.kind!=='research_partner'||task.payload.request!==attempt.fields.request)throw new Error('提交回包身份不完整，请核对同一消息。');
  save({text:'',attempt:null,fresh:false});await history.reload();void context.current.refresh().catch(fail);
 }catch(e){if(!uncertain&&e instanceof CommandError&&['invalid','conflict','context_limit','forbidden','unauthorized','authorization_required','provider_missing','not_ready','unsupported_format','invalid_path','not_found'].includes(e.code)){try{save({attempt:null});}catch(next){fail(next);return;}}fail(e);}finally{if(live.current)setBusy(false);}}
 function seed(text:string){try{save({text:current.current.text.trim()?[current.current.text,text].join('\n\n'):text});setMode('conversation');input.current?.focus();}catch(e){fail(e);}}
 const otherTasks=c.catalog.tasks.filter(t=>t.project_id===project&&t.payload?.kind!=='research_partner');
 return <><div className="agent-topbar"><strong><Sparkles/>项目搭档</strong><button className="icon-button" aria-label="收起项目搭档" onClick={()=>document.dispatchEvent(new Event('wb-toggle-agent'))}><PanelRight/></button></div>
 <div className="pane-heading"><div className="agent-navigation" role="tablist" aria-label="搭档工作"><button role="tab" aria-selected={mode==='conversation'} onClick={()=>setMode('conversation')}>讨论与工作</button><button role="tab" aria-selected={mode==='history'} onClick={()=>setMode('history')}>记录<span className="count">{c.catalog.tasks.filter(t=>t.project_id===project).length}</span></button></div></div>
 <section className="conversation-pane partner-conversation"><div className="messages" aria-label="项目搭档记录">
 {history.error&&<p role="alert" className="partner-error">{history.error}<button className="inline-ref" onClick={()=>void history.reload().catch(fail)}>重新读取</button></p>}
 {mode==='conversation'?<>{!history.items.length&&<div className="wb-agent-intro"><h2>{c.research?.questions.length?'一起接着做':'从你的想法开始'}</h2><p>{c.research?.questions.length?'可以讨论当前判断、补充记录，或直接调整画布上的问题与分析。搭档会读取当前研究图和下方的保存来源。':'说说想研究什么，或先打开已有笔记、脚本。问题与分析会直接整理到画布，可以继续讨论和修改。'}</p><button className="inline-ref" onClick={()=>seed('先看看我已经做了什么，说明当前认识和最值得推进的下一步。')}>先帮我看懂当前研究<ArrowRight/></button></div>}
 {history.items.map(item=><PartnerMessage key={item.task.id} item={item} continueWith={seed} onChanged={history.reload}/>)}
 <div ref={end}/></>:<><h2 className="partner-record-title">{c.project.title}</h2>{[...history.items].reverse().map(x=><button className="wb-task-row" key={x.task.id} onClick={()=>openPartnerTurn(c,x.task.id)}><span>{x.task.payload.request}</span><small>{partnerStatus(x.task.status)}{outstanding(x)>0?' · '+outstanding(x)+' 项建议待查看':''}</small></button>)}{otherTasks.map(t=><button className="wb-task-row" key={t.id} onClick={()=>c.open({id:t.id,kind:'task',title:'工作记录',value:t.id},true)}><span>{t.title||t.payload?.request||t.id}</span><small>{partnerStatus(t.status)}</small></button>)}{!history.items.length&&!otherTasks.length&&<p className="runtime-empty">还没有工作记录。第一条消息可以是一个想法，也可以是一项具体工作。</p>}<button className="inline-ref" onClick={()=>c.open({id:'tasks',kind:'tasks',title:'全部工作记录'},true)}>查看全部工作记录<ArrowRight/></button></>}
 {m.remote&&<div className="wb-version"><strong>项目已有新版 · r{m.remote.revision}</strong><p>当前草稿保留，载入前会存一份备份。</p><button className="button" disabled={m.busy} onClick={()=>void m.reload()}>保留草稿并载入新版</button></div>}
 {m.backup&&<button className="inline-ref" onClick={()=>void m.restore().then(fmt=>fmt&&c.openDocument(fmt,true))}>恢复上一份本地草稿</button>}
 {m.doc&&<details className="wb-file-handoff"><summary>稿件工作副本</summary><p>为本机 Agent 准备受版本约束的副本；编辑后提交仍校验项目版本。</p><button className="button" disabled={m.busy||!nativeFormat(m.doc.source_state.mode)} onClick={()=>void m.prepareCheckout()}>准备工作副本</button>{m.checkout&&<><code>{m.checkout.path}</code><button className="button" disabled={m.busy} onClick={()=>void m.commitCheckout()}>提交工作副本</button></>}</details>}
 </div>
 <div className="compose-area partner-compose"><details className="partner-context"><summary><FileText/><span>{c.project.title} · 背景{selected.length?' + '+selected.length+' 项保存内容':''}</span><ChevronDown/></summary><div className="partner-context-body"><p>本次读取当前研究图与以下保存版。生成的研究结构会直接更新画布，可撤销本轮；完成状态仍需核对。</p>{options.choices.map(o=><label key={o.key}><input type="checkbox" aria-label={'搭档读取 '+o.title} checked={selectedKeys.includes(o.key)} disabled={busy||!!draft.attempt||!selectedKeys.includes(o.key)&&(selected.length>=8||o.type==='question'&&selected.filter(x=>x.type==='question').length>=4||o.type==='file'&&selected.filter(x=>x.type==='file').length>=4)} onChange={e=>toggle(o.key,e.target.checked)}/><span>{o.title}<small>{o.detail}</small></span></label>)}<p>未勾选内容与未保存草稿不会发送。原生正文支持 Markdown 笔记与 Python 脚本；DOCX、图片和数据表尚不自动读取。</p></div></details>
 {unsaved&&<p className="partner-saved-hint">有未保存草稿，本次读取项目保存版。</p>}
 {error&&<p className="partner-error" role="alert">{error}</p>}
 <div className="composer">{graphFocus&&<p className="partner-graph-focus" aria-label="当前研究节点">{graphFocus.label} · {graphFocus.title}</p>}<textarea ref={input} aria-label="与搭档讨论" placeholder="输入研究内容，或说明想怎样调整画布…" rows={3} value={draft.text} disabled={!!draft.attempt||busy} onChange={e=>{try{save({text:e.target.value});}catch(x){fail(x);}}} onKeyDown={e=>{if((e.metaKey||e.ctrlKey)&&e.key==='Enter'&&!e.nativeEvent.isComposing){e.preventDefault();if(!running&&!draft.attempt&&ready&&draft.text.trim())void send();}}}/><div className="composer-tools"><span>{running?'搭档正在处理上一条消息':draft.fresh?'新一轮讨论':'讨论，也可以直接交出工作'}</span><button className="send-button" aria-label="发送给搭档" disabled={busy||running||!!draft.attempt||!ready||!budgetOK||!draft.text.trim()||selected.length>8} onClick={()=>void send()}><ArrowUp/></button></div></div>
 {draft.attempt&&<div className="partner-recovery" role="status"><p>提交结果尚未确认，原消息已保留。</p><button className="button" disabled={busy} onClick={()=>void send()}>核对同一消息</button></div>}
 {!ready&&<p className="partner-saved-hint">{!writable?'此项目只有阅读权限。':authority&&!authority.runtime_running?'任务执行服务尚未启动。':authority&&!provider?'尚无已授权的 Codex 执行路线。':'正在检查服务…'}<button className="inline-ref" onClick={()=>c.setGlobal('agents')}>查看连接</button><button className="inline-ref" onClick={()=>void command('desk.review.read',{project_id:project}).then(setAuthority).catch(fail)}>重新检查</button></p>}
 <details className="partner-execution"><summary>{provider||'执行设置'} · 每条最多 1 次调用</summary><div><label>执行路线<select aria-label="搭档执行路线" value={provider} disabled={busy||!!draft.attempt} onChange={e=>{try{save({provider:e.target.value});}catch(x){fail(x);}}}>{providers.map((p:any)=><option key={p.id} value={p.id}>{p.id}</option>)}</select></label><label>执行时限（秒）<input aria-label="搭档执行时限" type="number" min={1} max={900} value={draft.seconds} disabled={busy||!!draft.attempt} onChange={e=>{try{save({seconds:e.target.value});}catch(x){fail(x);}}}/></label><p>只阅读与分析本次来源；执行脚本、文稿编辑和实验需要各自的执行入口。</p></div></details>
 {history.items.length>0&&<button className="partner-new-thread" disabled={busy||!!draft.attempt||running} onClick={()=>{try{save({fresh:true});input.current?.focus();}catch(e){fail(e);}}}>开始新的讨论</button>}
 </div></section></>;
}
function PartnerMessage({item,continueWith,onChanged}:{item:any;continueWith:(text:string)=>void;onChanged?:()=>Promise<unknown>}){
 const c=useContext(WorkbenchContext)!,t=item.task,p=item.proposal?.content;
 return <article className="partner-turn" aria-label="搭档对话轮次"><div className="partner-user"><span>你</span><p>{t.payload.request}</p></div><div className="partner-reply"><span className="partner-speaker">搭档</span>{p?<><Markdown text={p.partner_reply.text}/><PartnerGraphChange item={item} continueWith={continueWith} onChanged={onChanged}/>{(p.research_proposal||p.research_update)&&<button className="partner-review-link" onClick={()=>openPartnerTurn(c,t.id)}><span>{p.research_proposal?'查看研究问题提案':'比较研究修改建议'}<small>{outstanding(item)>0?outstanding(item)+' 项待你决定':'所选建议已采用'}</small></span><ArrowRight/></button>}{p.partner_reply.next_steps?.map((s:any)=><button className="inline-ref partner-suggestion" key={s.id} onClick={()=>continueWith(s.prompt)}>{s.label}<ArrowRight/></button>)}</>:pending(t.status)?<p role="status" className="partner-wait">{t.status==='queued'?'已收到，等待执行。':'正在阅读保存内容并分析…'}可以继续查看项目。</p>:<div className="partner-error"><p>{typeof t.error==='string'?t.error:t.error?.message||'这次工作尚未形成回复。'}</p><button className="inline-ref" onClick={()=>continueWith(t.payload.request)}>保留原要求，继续讨论</button></div>}
 <details className="partner-receipt"><summary>{partnerStatus(t.status)} · 来源与执行记录</summary><p>每条最多 {t.payload.budget.max_model_calls} 次调用 · {t.payload.budget.timeout_seconds} 秒</p>{t.payload.context.partner.native_files?.map((f:any)=><button className="inline-ref" key={f.path} onClick={()=>f.source_ref&&c.open(sourceView({...f.source_ref,consumer_id:c.project.id},c.project.id,f.path),true)}>{f.path} · {f.sha256.slice(0,8)}</button>)}<button className="inline-ref" onClick={()=>c.open({id:'partner-details:'+t.id,kind:'task',title:'执行记录',value:t.id,data:{raw:true}},true)}>查看完整输入与回执</button></details>
 </div></article>;
}
export function PartnerTurnPanel({view}:{view:ViewSpec}){
 const c=useContext(WorkbenchContext)!,[item,setItem]=useState<any>(null),[error,setError]=useState('');
 useEffect(()=>{let live=true,timer:ReturnType<typeof setTimeout>;const read=async()=>{try{const x=await command('research.partner.read',{project_id:c.project.id,task_id:view.value});if(live){setItem(x);setError('');if(pending(x.task.status))timer=setTimeout(read,1500);}}catch(e){if(live)setError(errorText(e));}};void read();return()=>{live=false;clearTimeout(timer);};},[view.value,c.project.id]);
 if(error)return <article className="document"><p role="alert">{error}</p><button className="button" onClick={()=>startPartner(c)}>回到搭档讨论</button></article>;
 if(!item)return <p className="editor-empty" role="status">正在读取搭档回复…</p>;
 const data={...view.data,partner:true};
 if(item.proposal?.content.research_proposal)return <ResearchExplorationPanel view={{...view,data}}/>;
 if(item.proposal?.content.research_update)return <ResearchWorkPanel view={{...view,data}}/>;
 return <article className="document partner-reading"><h1>{item.proposal?.title||'搭档回复'}</h1><PartnerMessage item={item} continueWith={text=>startPartner(c,text)}/><button className="button" onClick={()=>startPartner(c)}>继续讨论</button></article>;
}
