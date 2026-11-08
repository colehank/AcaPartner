import {useContext,useEffect,useRef,useState} from 'react';
import {ArrowRight,Check,RefreshCw,Sparkles} from 'lucide-react';
import {command,CommandError,requestId} from '../api';
import {WorkbenchContext,type ViewSpec,type WorkbenchValue} from './context';
import {sourceView} from './researchReading';
import {openPartnerTurn,startPartner} from './ProjectPartner';
import {errorText} from './useManuscript';
import './research-exploration.css';

type Ref={id:string;revision:number};
type Candidate={id:string;question:string;unknown:string;rationale:string;assumptions:string[];analysis_plan:string;evidence_needed:string[];source_refs:Ref[]};
type Attempt={key:string;fields:Record<string,any>};
type Draft={request:string;materials:Ref[];provider:string;seconds:string;preview:any;taskId:string;previousTaskId:string;attempt:Attempt|null;adoptAttempt:Attempt|null;choices:string[];titles:Record<string,string>;followup:string};
const blank=():Draft=>({request:'',materials:[],provider:'',seconds:'180',preview:null,taskId:'',previousTaskId:'',attempt:null,adoptAttempt:null,choices:[],titles:{},followup:''});
const draftKey=(project:string,id:string)=>'acapartner.exploration.v1:'+sessionStorage.getItem('acapartner.native-editor-tab')+':'+project+':'+id;
function stored(key:string):Draft{try{return {...blank(),...JSON.parse(localStorage.getItem(key)||'{}')};}catch{return blank();}}
export function openResearchExploration(c:WorkbenchValue,request='',taskId='',previousTaskId='',materials:Ref[]=[]){
 if(taskId&&c.catalog.tasks.some(t=>t.id===taskId&&t.payload?.kind==='research_partner')){openPartnerTurn(c,taskId);return;}
 const slot=draftKey(c.project.id,'active:'+(previousTaskId||'new'));
 let id=taskId?'exploration:'+taskId:previousTaskId?'exploration:from:'+previousTaskId:'exploration:draft';
 try{if(!taskId){id=localStorage.getItem(slot)||id;if(stored(draftKey(c.project.id,id)).taskId)id='exploration:draft:'+requestId();localStorage.setItem(slot,id);}}catch(e){c.report(e);return;}
 const key=draftKey(c.project.id,id),draft=stored(key);
 if(request.trim()&&!draft.request&&!draft.taskId&&!draft.attempt){try{localStorage.setItem(key,JSON.stringify({...draft,request,previousTaskId,materials:materials.map(({id,revision})=>({id,revision}))}));window.dispatchEvent(new CustomEvent('wb-exploration-seed',{detail:key}));}catch(e){c.report(e);return;}}
 c.open({id,kind:'exploration',title:taskId?'问题提案':previousTaskId?'完善问题提案':'探索研究问题',value:taskId||undefined,data:{previousTaskId,projectId:c.project.id}},true);
}
const taskLabels:Record<string,string>={queued:'已排队',running:'正在梳理研究问题',generated:'提案已保存',failed:'探索未完成',cancelled:'已停止',paused:'已暂停',blocked:'需要处理阻碍',waiting_input:'等待补充信息'};
const pending=(status:string)=>['queued','running'].includes(status);
const ident=(s:any)=>typeof s==='string'&&s.length>0;
const sha=(s:any)=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
function checkedRead(value:any,project:string,taskId:string,partner=false){
 const t=value?.task,p=value?.proposal;
 if(t?.id!==taskId||t.project_id!==project||t.payload?.kind!==(partner?'research_partner':'research_exploration')||!Array.isArray(value.adoptions))throw new Error('探索回包与当前项目或任务不符，请重新读取。');
 if(p&&(p.id!==t.result?.object_id||p.revision!==t.result?.revision||p.project_id!==project||!sha(p.sha256)||p.content?.research_proposal?.version!==1))throw new Error('提案未与任务的固定保存版本匹配，请重新读取。');
 return value;
}

/** One finite exploration, followed by explicit revision or adoption. */
export function ResearchExplorationPanel({view}:{view:ViewSpec}){
 const c=useContext(WorkbenchContext)!,project=c.project.id,key=draftKey(project,view.id),partner=!!view.data?.partner;
 const [draft,setDraft]=useState<Draft>(()=>({...stored(key),...(view.value?{taskId:view.value}:{}),...(view.data?.previousTaskId?{previousTaskId:view.data.previousTaskId}:{})}));
 const [result,setResult]=useState<any>(null),[authority,setAuthority]=useState<any>(null),[busy,setBusy]=useState(''),[error,setError]=useState('');
 const latest=useRef(draft),live=useRef(true),context=useRef(c);context.current=c;
 const commit=(patch:Partial<Draft>)=>{const next={...latest.current,...patch};localStorage.setItem(key,JSON.stringify(next));latest.current=next;if(live.current)setDraft(next);return next;};
 const fail=(e:unknown)=>{if(live.current)setError(errorText(e));};
 useEffect(()=>{live.current=true;const seed=(e:Event)=>{if((e as CustomEvent).detail===key&&!latest.current.request&&!latest.current.taskId){const next=stored(key);latest.current=next;setDraft(next);}};window.addEventListener('wb-exploration-seed',seed);
  c.registerFileFlush(view.id,async()=>{localStorage.setItem(key,JSON.stringify(latest.current));});
  return()=>{live.current=false;window.removeEventListener('wb-exploration-seed',seed);c.registerFileFlush(view.id,null);};
 },[key]);
 useEffect(()=>{let active=true;void command('desk.review.read',{project_id:project}).then(x=>{if(active)setAuthority(x);}).catch(fail);return()=>{active=false;};},[project]);
 const read=async(taskId=latest.current.taskId)=>{if(!taskId)return;const value=checkedRead(await command(partner?'research.partner.questions.read':'research.exploration.read',{project_id:project,task_id:taskId}),project,taskId,partner);if(live.current&&latest.current.taskId===taskId)setResult(value);return value;};
 useEffect(()=>{if(!draft.taskId)return;let active=true,timer:ReturnType<typeof setTimeout>;const poll=async()=>{try{const value=await read(draft.taskId);if(active&&value&&pending(value.task.status))timer=setTimeout(poll,2000);else if(active)void context.current.refresh().catch(fail);}catch(e){if(active)fail(e);}};void poll();return()=>{active=false;clearTimeout(timer);};},[draft.taskId]);
 const providers=(authority?.providers||[]).filter((p:any)=>p.route==='codex'&&p.authorized===true&&p.available!==false);
 const provider=draft.provider||providers[0]?.id||'',writable=c.catalog.project_management.writable_project_ids.includes(project);
 const running=authority?.runtime_running===true,seconds=Number(draft.seconds),budgetOK=/^\d+$/.test(draft.seconds)&&seconds>=1&&seconds<=900;
 const sources=c.catalog.objects.filter(o=>o.project_id===project&&!o.archived&&['note','report','concept','literature'].includes(o.kind)&&!o.metadata?.research_exploration);
 const locked=!!draft.taskId||!!draft.attempt||!!busy;
 function edit(patch:Partial<Draft>){try{commit({...patch,preview:null});setError('');}catch(e){fail(e);}}
 async function preview(){if(locked)return;setBusy('preview');setError('');try{const input={project_id:project,request:draft.request,materials:draft.materials,...(draft.previousTaskId?{previous_task_id:draft.previousTaskId}:{})};
  const value=await command('research.exploration.preview',input);
  if(value?.input?.project?.id!==project||value.input.request!==input.request||!sha(value.input_pin)||value.executed!==false)throw new Error('预览身份不完整，请重新核对输入。');
  commit({preview:value});
 }catch(e){fail(e);}finally{if(live.current)setBusy('');}}
 async function submit(){if(busy||draft.taskId)return;setBusy('submit');setError('');const uncertain=!!draft.attempt;
  try{let attempt=latest.current.attempt;
   if(!attempt){if(!draft.preview||!provider||!budgetOK||!running||!writable)throw new Error('请先核对输入、执行路线和有限预算。');
    attempt={key:requestId(),fields:{project_id:project,request:draft.request,materials:draft.materials,...(draft.previousTaskId?{previous_task_id:draft.previousTaskId}:{}),input_pin:draft.preview.input_pin,provider_id:provider,budget:{max_model_calls:1,timeout_seconds:seconds}}};commit({attempt});}
   const task=await command('research.exploration.submit',{...attempt.fields,request_key:attempt.key});
   if(!ident(task?.id)||task.project_id!==project||task.request_key!==attempt.key||task.payload?.kind!=='research_exploration'||task.payload.request!==attempt.fields.request||task.payload.provider_id!==attempt.fields.provider_id||task.payload.context?.exploration?.request!==attempt.fields.request)throw new Error('服务返回的任务身份不完整；请用同一请求核对。');
   commit({taskId:task.id,attempt:null});if(live.current)setResult(null);void context.current.refresh().catch(fail);
  }catch(e){if(e instanceof CommandError&&!uncertain&&['invalid','forbidden','unauthorized','conflict','idempotency_conflict','context_limit','authorization_required','provider_missing','not_ready'].includes(e.code)){try{commit({attempt:null,preview:null});}catch(next){fail(next);return;}}fail(e);}finally{if(live.current)setBusy('');}}
 const proposal=result?.proposal,value=proposal?.content?.research_proposal,task=result?.task;
 const selected=(value?.candidates||[]).filter((x:Candidate)=>draft.choices.includes(x.id)&&!result.adoptions.some((a:any)=>a.candidate_id===x.id));
 const titleKey=(id:string)=>proposal.id+'@'+proposal.revision+':'+id;
 async function adopt(){if(busy||!proposal)return;setBusy('adopt');setError('');const uncertain=!!draft.adoptAttempt;
  try{let attempt=latest.current.adoptAttempt;
   if(!attempt){if(!writable||!selected.length)throw new Error('请选择要加入研究的问题。');attempt={key:requestId(),fields:{project_id:project,task_id:task.id,proposal_ref:{id:proposal.id,revision:proposal.revision,sha256:proposal.sha256},candidates:selected.map((x:Candidate)=>({id:x.id,title:draft.titles[titleKey(x.id)]??x.question}))}};commit({adoptAttempt:attempt});}
   const response=await command(partner?'research.partner.questions.adopt':'research.exploration.adopt',{...attempt.fields,request_key:attempt.key});
   if(!Array.isArray(response?.questions)||response.questions.length!==attempt.fields.candidates.length||response.questions.some((q:any)=>q.project_id!==project||q.metadata?.origin?.task_id!==task.id||q.metadata.origin.proposal_ref?.sha256!==proposal.sha256||!attempt!.fields.candidates.some((x:any)=>x.id===q.metadata.origin.candidate_id&&x.title.trim()===q.title)))throw new Error('采用回包不完整，请核对同一请求。');
   commit({adoptAttempt:null,choices:[]});await read();await context.current.refreshResearch();await context.current.refresh();
  }catch(e){if(e instanceof CommandError&&!uncertain&&['invalid','forbidden','unauthorized','conflict','idempotency_conflict','context_limit','authorization_required','provider_missing','not_ready'].includes(e.code)){try{commit({adoptAttempt:null});}catch(next){fail(next);return;}}fail(e);}finally{if(live.current)setBusy('');}}
 const openTask=(id:string)=>openResearchExploration(c,'',id);
 const openQuestion=(a:any)=>c.open({id:a.question_id,kind:'question',title:a.title,value:a.question_id},true);
 const source=(ref:Ref)=>c.open(sourceView({...ref,consumer_id:project},project,c.catalog.objects.find(o=>o.id===ref.id)?.title),true);
 return <div className="wb-exploration"><div className="editor-toolbar"><span className="breadcrumbs">研究 / 问题探索</span>{task&&<><button className="button quiet" disabled={!!busy||!!draft.adoptAttempt} onClick={()=>partner?startPartner(c):openResearchExploration(c)}>新的研究想法</button><span className="runtime-caption" role="status">{taskLabels[task.status]||task.status}</span><button className="icon-button" aria-label="刷新探索状态" disabled={!!busy} onClick={()=>void read().catch(fail)}><RefreshCw/></button></>}</div>
 <article className="document exploration-document"><h1>{proposal?'研究问题提案':'从一个想法开始'}</h1>
 {error&&<p className="exploration-alert" role="alert">{error}</p>}
 {!draft.taskId?<><p className="doc-lead">描述你想弄清楚什么。搭档会梳理可研究的方向、形成理由，以及还需明确的目标。</p>
 {draft.previousTaskId&&<p className="exploration-lineage">在<button className="inline-ref" onClick={()=>openTask(draft.previousTaskId)}>前一份提案</button>上继续，原提案会保留。</p>}
 <fieldset disabled={locked} className="exploration-fields"><label htmlFor={view.id+'-intent'}>{draft.previousTaskId?'补充目标与边界':'研究想法'}</label><textarea id={view.id+'-intent'} aria-label="研究想法" rows={5} placeholder="例如：我想研究怎么把鸡蛋煮得更好。" value={draft.request} onChange={e=>edit({request:e.target.value})}/>
 <details><summary>采用的保存材料 · {draft.materials.length} 项</summary><p className="runtime-caption">项目背景会一同采用。材料可留空；此处选择已登记文字对象，原生文件与未保存草稿不会自动发送。</p>
 {sources.map(o=><label key={o.id} className="exploration-source"><input type="checkbox" checked={draft.materials.some(r=>r.id===o.id)} disabled={draft.materials.length>=8&&!draft.materials.some(r=>r.id===o.id)} onChange={e=>edit({materials:e.target.checked?[...draft.materials,{id:o.id,revision:o.revision}]:draft.materials.filter(r=>r.id!==o.id)})}/><span>{o.title}<small>保存版 · r{draft.materials.find(r=>r.id===o.id)?.revision||o.revision}</small></span></label>)}
 {!sources.length&&<p className="runtime-caption">暂无可选文字材料，可以直接从研究想法开始。</p>}
 {draft.materials.filter(r=>!sources.some(o=>o.id===r.id)).map(r=><p key={r.id}>已选来源 {r.id} 当前不可见。<button className="inline-ref" onClick={()=>edit({materials:draft.materials.filter(x=>x.id!==r.id)})}>移除此选择</button></p>)}
 </details><button className="button" disabled={!draft.request.trim()||!writable} onClick={()=>void preview()}>核对探索输入</button></fieldset>
 {draft.preview&&<section className="exploration-preview" aria-label="探索输入预览"><h2>本次探索</h2><p>{draft.preview.input.background.title} · 背景 r{draft.preview.input.project.revision} · {draft.preview.input.materials.length} 份固定材料</p>
 <details><summary>查看采用的背景与来源</summary><p>{draft.preview.input.background.description}</p><p>{draft.preview.input.background.text||'背景尚未填写。'}</p>{draft.preview.input.materials.map((r:Ref)=><button className="inline-ref" key={r.id} onClick={()=>source(r)}>{c.catalog.objects.find(o=>o.id===r.id)?.title||r.id} · r{r.revision}</button>)}{draft.preview.input.previous_proposal&&<p>包含前一份提案及原始想法；它仍是待讨论的候选。</p>}</details>
 <div className="exploration-execution"><label>执行路线<select aria-label="探索执行路线" disabled={!!draft.attempt||!!busy} value={provider} onChange={e=>{try{commit({provider:e.target.value});}catch(x){fail(x);}}}>{!providers.length&&<option value="">尚无可用 Codex CLI 路线</option>}{providers.map((p:any)=><option value={p.id} key={p.id}>{p.id}{p.model?' · '+p.model:''}</option>)}</select></label><label>最长执行时间（秒）<input type="number" aria-label="探索执行时限" min="1" max="900" value={draft.seconds} disabled={!!draft.attempt||!!busy} onChange={e=>{try{commit({seconds:e.target.value});}catch(x){fail(x);}}}/></label></div>
 <p className="runtime-caption">最多发起 1 次模型调用。返回提案后，由你选择是否加入研究。</p>
 {!running&&<p className="exploration-alert">任务执行服务尚未启动。</p>}{!providers.length&&<button className="inline-ref" onClick={()=>c.setGlobal('agents')}>前往智能体管理查看执行路线</button>}
 {!draft.attempt&&<button className="button primary" disabled={!!busy||!running||!provider||!budgetOK||!writable} onClick={()=>void submit()}><Sparkles/>{busy==='submit'?'正在提交…':'开始探索'}</button>}</section>}
 {draft.attempt&&<div className="exploration-recovery" role="status"><p>提交结果尚未确认。输入和请求身份已保留，重新核对不会重复创建任务。</p><button className="button" disabled={!!busy} onClick={()=>void submit()}>核对同一探索请求</button></div>}
 </>:<>
 {!result&&<p role="status">正在读取探索任务…<button className="inline-ref" onClick={()=>void read().catch(fail)}>重新读取</button></p>}
 {task&&<details className="exploration-input"><summary>本轮研究想法与执行记录</summary><p>{task.payload.request}</p><p className="runtime-caption">{task.id} · {task.payload.provider_id} · 最多 {task.payload.budget.max_model_calls} 次调用 / {task.payload.budget.timeout_seconds} 秒</p>{task.payload.context.exploration.previous_proposal&&<button className="inline-ref" onClick={()=>openTask(task.payload.context.exploration.previous_proposal.task_id)}>查看前一份提案</button>}{result.history?.length>0&&<details><summary>各轮调用与用量 · {result.history.length} 轮</summary>{result.history.map((h:any)=><div key={h.task_id}><button className="inline-ref" onClick={()=>openTask(h.task_id)}>{h.task_id===task.id?'本轮探索':h.task_id}</button><p className="runtime-caption">预算：最多 {h.budget.max_model_calls} 次 CLI 调用 / {h.budget.timeout_seconds} 秒。{h.provider?.returncode===0?'已取得完成回执。':'用量以实际执行记录为准。'}</p>{Array.isArray(h.provider?.usage)&&h.provider.usage.length>0&&<p className="runtime-caption">输入 Token {h.provider.usage.reduce((n:number,u:any)=>n+(Number.isFinite(u.input_tokens)?u.input_tokens:0),0).toLocaleString()} · 输出 Token {h.provider.usage.reduce((n:number,u:any)=>n+(Number.isFinite(u.output_tokens)?u.output_tokens:0),0).toLocaleString()}</p>}</div>)}<p className="runtime-caption">CLI 调用次数不等于内部 API 请求次数；实际费用未返回时保持未知。</p></details>}<details><summary>固定输入与来源</summary><pre>{JSON.stringify(task.payload.context.exploration,null,2)}</pre></details></details>}
 {task&&pending(task.status)&&<p className="exploration-wait" role="status">{task.status==='queued'?'等待执行。':'搭档正在分析研究意图。'}可以切换内容，任务和结果会保留。</p>}
 {task&&!pending(task.status)&&!proposal&&<div className="exploration-recovery"><p>{typeof task.error==='string'?task.error:task.error?.message||'这次探索尚未形成可采用的提案。'}</p><button className="button" onClick={()=>c.open({id:'exploration-details:'+task.id,kind:'task',title:'任务详情',value:task.id,data:{raw:true}},true)}>查看执行详情</button><button className="inline-ref" onClick={()=>openResearchExploration(c,task.payload.request)}>回到探索草稿</button></div>}
 {value&&<><p className="doc-lead">{value.interpretation}</p><p className="runtime-caption">提案保存版 · r{proposal.revision}。这些方向尚未加入研究，也没有形成实验证据或结论。</p>
 {value.clarifications.length>0&&<section className="exploration-clarifications"><h2>需要你明确</h2>{value.clarifications.map((q:any)=><div key={q.id}><h3>{q.question}</h3><p>{q.why_it_matters}</p></div>)}<p className="runtime-caption">可在下方补充目标，再生成下一份提案。</p></section>}
 {value.candidates.length>0&&<section aria-label="候选研究问题"><h2>候选方向</h2>{value.candidates.map((item:Candidate)=>{const adopted=result.adoptions.find((a:any)=>a.candidate_id===item.id);return <section className="exploration-candidate" key={item.id}><div className="exploration-candidate-heading">{adopted?<Check aria-label="已加入研究"/>:<input type="checkbox" aria-label={'选择候选 '+item.question} disabled={!!busy||!!draft.adoptAttempt||!writable} checked={draft.choices.includes(item.id)} onChange={e=>{try{commit({choices:e.target.checked?[...draft.choices,item.id]:draft.choices.filter(x=>x!==item.id)});}catch(x){fail(x);}}}/>}<h3>{item.question}</h3></div><p>{item.rationale}</p><dl><dt>待回答的未知</dt><dd>{item.unknown}</dd><dt>分析设想</dt><dd>{item.analysis_plan}</dd><dt>需要的证据</dt><dd><ul>{item.evidence_needed.map((x,i)=><li key={i}>{x}</li>)}</ul></dd></dl>{item.assumptions.length>0&&<details><summary>当前假设</summary><ul>{item.assumptions.map((x,i)=><li key={i}>{x}</li>)}</ul></details>}{item.source_refs.length>0&&<div>{item.source_refs.map(r=><button className="inline-ref" key={r.id+'@'+r.revision} onClick={()=>source(r)}>{c.catalog.objects.find(o=>o.id===r.id)?.title||r.id} · r{r.revision}</button>)}</div>}
 {adopted?<button className="inline-ref exploration-adopted" onClick={()=>openQuestion(adopted)}>已加入研究 · {adopted.title}<ArrowRight/></button>:draft.choices.includes(item.id)&&<label className="exploration-title">加入研究的标题<input aria-label={'研究标题 '+item.id} maxLength={500} disabled={!!busy||!!draft.adoptAttempt} value={draft.titles[titleKey(item.id)]??item.question} onChange={e=>{try{commit({titles:{...draft.titles,[titleKey(item.id)]:e.target.value}});}catch(x){fail(x);}}}/></label>}</section>;})}
 <div className="exploration-adopt"><p className="runtime-caption">采用后建立 Q，保留形成缘由和分析设想。E、C 等实际研究展开后再补充。</p><button className="button primary" disabled={!!busy||!writable||(!draft.adoptAttempt&&(!selected.length||selected.some((x:Candidate)=>!(draft.titles[titleKey(x.id)]??x.question).trim())))} onClick={()=>void adopt()}>{busy==='adopt'?'正在加入…':draft.adoptAttempt?'核对同一采用请求':'将所选方向加入研究'+(selected.length?' · '+selected.length:'')}</button>{draft.adoptAttempt&&<p role="status">采用请求已保留；再次核对不会重复创建 Q。</p>}</div></section>}
 {value.limitations.length>0&&<section><h2>这份提案的边界</h2><ul>{value.limitations.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></section>}
 <section className="exploration-followup"><h2>继续完善问题</h2><label htmlFor={view.id+'-followup'}>补充目标、回答上面的澄清，或调整方向</label><textarea id={view.id+'-followup'} aria-label="补充研究目标" rows={4} value={draft.followup} onChange={e=>{try{commit({followup:e.target.value});}catch(x){fail(x);}}} placeholder="例如：关注口感，目标是蛋白凝固、蛋黄柔软。"/><button className="button" disabled={!draft.followup.trim()||!!busy||!!draft.adoptAttempt} onClick={()=>partner?startPartner(c,draft.followup):openResearchExploration(c,draft.followup,'',task.id,task.payload.context.materials)}>{partner?'回到右侧继续讨论':'核对下一轮输入'}<ArrowRight/></button><p className="runtime-caption">{partner?'补充内容会带入同一个搭档输入，本轮提案与采用记录会保留。':'将创建关联的新提案，保留本轮内容与采用记录。'}</p></section>
 </>}
 </>}
 {!writable&&<p className="exploration-alert">当前账号只有项目读取权限。</p>}
 </article></div>;
}
