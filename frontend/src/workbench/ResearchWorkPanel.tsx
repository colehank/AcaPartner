import {useContext,useEffect,useRef,useState} from 'react';
import {ArrowRight,Briefcase,Check,RefreshCw} from 'lucide-react';
import {command,CommandError,requestId} from '../api';
import {CodeEditor} from '../CodeEditor';
import {WorkbenchContext,type ViewSpec,type WorkbenchValue} from './context';
import {Markdown} from './ContentPanels';
import {sourceView,questionLabel} from './researchReading';
import {openPartnerTurn,startPartner} from './ProjectPartner';
import {errorText} from './useManuscript';
import './research-exploration.css';
import './research-work.css';

type Ref={id:string;revision:number};
type Part='A'|'E'|'C';
type Target=Ref&{parts:Part[]};
type Change={id:string;question_id:string;part:Part;mode:'append'|'replace';text:string;rationale:string;basis:'plan'|'supported'|'unresolved';source_refs:Ref[]};
type Reviewed=Ref&{sha256:string;qaec:Record<string,string>};
type Attempt={key:string;fields:Record<string,any>};
type Draft={request:string;questions:Target[];materials:Ref[];provider:string;seconds:string;preview:any;taskId:string;attempt:Attempt|null;adoptAttempt:Attempt|null;choices:string[];texts:Record<string,string>;reviewed:Record<string,Reviewed>;reconciled:Record<string,string>};
const initial=():Draft=>({request:'',questions:[],materials:[],provider:'',seconds:'180',preview:null,taskId:'',attempt:null,adoptAttempt:null,choices:[],texts:{},reviewed:{},reconciled:{}});
const prefix=()=>sessionStorage.getItem('acapartner.native-editor-tab');
const keyFor=(project:string,id:string)=>'acapartner.research-work.v1:'+prefix()+':'+project+':'+id;
function load(key:string):Draft{try{return {...initial(),...JSON.parse(localStorage.getItem(key)||'{}')};}catch{return initial();}}
export const workLabels:Record<string,string>={queued:'已排队',running:'正在执行',generated:'候选已保存',waiting_input:'等待补充',waiting_authorization:'等待授权',failed:'执行未完成',cancelled:'已停止',paused:'已暂停'};
const partLabel:Record<Part,string>={A:'分析',E:'证据',C:'结论'};
const rejection=(e:unknown)=>e instanceof CommandError&&['invalid','forbidden','unauthorized','conflict','idempotency_conflict','context_limit','authorization_required','provider_missing','not_ready'].includes(e.code);
const sha=(s:any)=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);
const pending=(s:string)=>s==='queued'||s==='running';
export function openResearchWork(c:WorkbenchValue,questionId='',taskId=''){
 if(taskId&&c.catalog.tasks.some(t=>t.id===taskId&&t.payload?.kind==='research_partner')){openPartnerTurn(c,taskId);return;}
 try{const slot=keyFor(c.project.id,'active:'+(questionId||'new'));let id=taskId?'research-work:'+taskId:localStorage.getItem(slot)||'research-work:draft:'+(questionId||'new');
  if(!taskId){if(load(keyFor(c.project.id,id)).taskId)id='research-work:draft:'+requestId();localStorage.setItem(slot,id);const draft=load(keyFor(c.project.id,id)),q=c.research?.questions.find((q:any)=>q.id===questionId);if(q&&!draft.questions.length&&!draft.request&&!draft.attempt)localStorage.setItem(keyFor(c.project.id,id),JSON.stringify({...draft,questions:[{id:q.id,revision:q.revision,parts:['A','E','C']}]}));}
  c.open({id,kind:'research-work',title:taskId?'研究工作候选':'推进研究问题',value:taskId||undefined},true);
 }catch(e){c.report(e);}
}
function checkedRead(x:any,project:string,id:string,partner=false){
 const t=x?.task,p=x?.proposal;
 if(t?.id!==id||t.project_id!==project||t.payload?.kind!==(partner?'research_partner':'research_work')||!Array.isArray(x.questions)||!Array.isArray(x.adoptions))throw new Error('工作回包不属于当前项目或任务，请重新读取。');
 if(p&&(p.id!==t.result?.object_id||p.revision!==t.result?.revision||p.project_id!==project||!sha(p.sha256)||p.content?.research_update?.version!==1))throw new Error('候选与固定保存记录不符，请重新读取。');
 if(x.questions.some((q:any)=>q.project_id!==project||!sha(q.sha256)))throw new Error('目标Q的保存身份不完整。');
 return x;
}

export function ResearchWorkPanel({view}:{view:ViewSpec}){
 const c=useContext(WorkbenchContext)!,project=c.project.id,key=keyFor(project,view.id),partner=!!view.data?.partner;
 const [draft,setDraft]=useState<Draft>(()=>({...load(key),...(view.value?{taskId:view.value}:{})})),[result,setResult]=useState<any>(null),[authority,setAuthority]=useState<any>(null),[busy,setBusy]=useState(''),[error,setError]=useState(''),[compare,setCompare]=useState<Record<string,boolean>>({});
 const latest=useRef(draft),live=useRef(true),context=useRef(c);context.current=c;
 function commit(patch:Partial<Draft>){const next={...latest.current,...patch};localStorage.setItem(key,JSON.stringify(next));latest.current=next;if(live.current)setDraft(next);return next;}
 const fail=(e:unknown)=>{if(live.current)setError(errorText(e));};
 const safe=(patch:Partial<Draft>)=>{try{commit(patch);}catch(e){fail(e);}};
 useEffect(()=>{live.current=true;c.registerFileFlush(view.id,async()=>{localStorage.setItem(key,JSON.stringify(latest.current));});return()=>{live.current=false;c.registerFileFlush(view.id,null);};},[key]);
 useEffect(()=>{let active=true;void command('desk.review.read',{project_id:project}).then(x=>active&&setAuthority(x)).catch(fail);return()=>{active=false;};},[project]);
 async function read(){const id=latest.current.taskId;if(!id)return;const value=checkedRead(await command(partner?'research.partner.work.read':'research.work.read',{project_id:project,task_id:id}),project,id,partner);
  if(live.current&&latest.current.taskId===id){setResult(value);if(value.proposal&&!Object.keys(latest.current.reviewed).length){const snapshot=value.task.payload.context.research_work;safe({reviewed:Object.fromEntries(snapshot.research_questions.filter((q:any)=>snapshot.targets.some((t:any)=>t.id===q.id)).map((q:any)=>[q.id,{id:q.id,revision:q.revision,sha256:q.sha256,qaec:q.qaec}]))});}}
  return value;
 }
 useEffect(()=>{if(!draft.taskId)return;let active=true,timer:ReturnType<typeof setTimeout>;async function poll(){try{const value=await read();if(active&&value&&pending(value.task.status))timer=setTimeout(poll,2000);else if(active)void context.current.refresh().catch(fail);}catch(e){if(active)fail(e);}}void poll();return()=>{active=false;clearTimeout(timer);};},[draft.taskId]);
 const writable=c.catalog.project_management.writable_project_ids.includes(project),providers=(authority?.providers||[]).filter((p:any)=>p.route==='codex'&&p.authorized===true&&p.available!==false),provider=draft.provider||providers[0]?.id||'';
 const seconds=Number(draft.seconds),budgetOK=/^\d+$/.test(draft.seconds)&&seconds>=1&&seconds<=900,locked=!!busy||!!draft.taskId||!!draft.attempt;
 const questions=c.research?.questions||[],sources=c.catalog.objects.filter(o=>o.project_id===project&&!o.archived&&['note','report','concept','literature'].includes(o.kind)&&!o.metadata?.research_exploration&&!o.metadata?.research_partner&&!o.metadata?.research_context_snapshot&&!o.metadata?.research_work&&o.metadata?.research_role!=='research_question_v1');
 const unsaved=(id:string)=>localStorage.getItem('acapartner.unified.research-draft:'+prefix()+':'+project+':'+id)!==null;
 function edit(patch:Partial<Draft>){safe({...patch,preview:null});setError('');}
 async function preview(){if(locked)return;setBusy('preview');setError('');try{
  const targets=draft.questions.map(t=>({...t,revision:questions.find((q:any)=>q.id===t.id)?.revision||t.revision}));
  const value=await command('research.work.preview',{project_id:project,request:draft.request,materials:draft.materials,questions:targets});
  if(value?.input?.project?.id!==project||value.input.request!==draft.request||!sha(value.input_pin)||value.executed!==false)throw new Error('委托预览身份不完整，请重新核对。');
  commit({questions:targets,preview:value});
 }catch(e){if(e instanceof CommandError&&e.code==='conflict')void context.current.refreshResearch().catch(fail);fail(e);}finally{if(live.current)setBusy('');}}
 async function submit(){if(busy||draft.taskId)return;setBusy('submit');setError('');const uncertain=!!draft.attempt;try{
  let attempt=latest.current.attempt;if(!attempt){if(!draft.preview||!provider||!budgetOK||!writable||authority?.runtime_running!==true)throw new Error('请核对保存版、执行路线和有限预算。');attempt={key:requestId(),fields:{project_id:project,request:draft.request,materials:draft.materials,questions:draft.questions,input_pin:draft.preview.input_pin,provider_id:provider,budget:{max_model_calls:1,timeout_seconds:seconds}}};commit({attempt});}
  const task=await command('research.work.submit',{...attempt.fields,request_key:attempt.key});
  if(task?.project_id!==project||task.request_key!==attempt.key||task.payload?.kind!=='research_work'||task.payload.request!==attempt.fields.request||task.payload.provider_id!==attempt.fields.provider_id)throw new Error('任务回包身份不完整，请核对同一请求。');
  commit({taskId:task.id,attempt:null});void context.current.refresh().catch(fail);
 }catch(e){if(rejection(e)&&!uncertain)safe({attempt:null,preview:null});fail(e);}finally{if(live.current)setBusy('');}}
 const proposal=result?.proposal,value=proposal?.content?.research_update,task=result?.task,snapshot=task?.payload.context.research_work;
 const changeKey=(item:Change)=>proposal.id+'@'+proposal.revision+':'+item.id;
 const frozen=(id:string)=>snapshot.research_questions.find((q:any)=>q.id===id);
 const current=(id:string)=>result.questions.find((q:any)=>q.id===id);
 const proposed=(item:Change)=>draft.texts[changeKey(item)]??(item.mode==='append'?[frozen(item.question_id).qaec[item.part],item.text].filter(Boolean).join('\n\n'):item.text);
 const selected:Change[]=(value?.changes||[]).filter((i:Change)=>draft.choices.includes(i.id)&&!result.adoptions.some((a:any)=>a.change_id===i.id));
 function changedSinceReview(id:string){return !draft.reviewed[id]||draft.reviewed[id].revision!==current(id).revision||draft.reviewed[id].sha256!==current(id).sha256;}
 function needsReconcile(id:string){return draft.reviewed[id]?.revision!==frozen(id).revision&&draft.reconciled[id]!==draft.reviewed[id]?.sha256;}
 const blocked=selected.some(i=>unsaved(i.question_id)||changedSinceReview(i.question_id)||needsReconcile(i.question_id));
 async function reviewLatest(id:string){if(busy||draft.adoptAttempt)return;setBusy('review');setError('');try{const value=await read(),q=value.questions.find((q:any)=>q.id===id);if(!q)throw new Error('目标Q已不可见，候选仍保留。');commit({reviewed:{...latest.current.reviewed,[id]:{id:q.id,revision:q.revision,sha256:q.sha256,qaec:q.content.qaec}},reconciled:{...latest.current.reconciled,[id]:''}});}catch(e){fail(e);}finally{if(live.current)setBusy('');}}
 async function adopt(){if(busy||!proposal)return;setBusy('adopt');setError('');const uncertain=!!draft.adoptAttempt;try{
  let attempt=latest.current.adoptAttempt;if(!attempt){if(!selected.length||blocked||!writable)throw new Error('请先处理未保存草稿，并核对当前保存版。');const ids=[...new Set(selected.map(x=>x.question_id))];attempt={key:requestId(),fields:{project_id:project,task_id:task.id,proposal_ref:{id:proposal.id,revision:proposal.revision,sha256:proposal.sha256},changes:selected.map(i=>({id:i.id,text:proposed(i)})),expected_questions:ids.map(id=>{const q=draft.reviewed[id];return {id:q.id,revision:q.revision,sha256:q.sha256};})}};commit({adoptAttempt:attempt});}
  const response=await command(partner?'research.partner.work.adopt':'research.work.adopt',{...attempt.fields,request_key:attempt.key});
  if(!Array.isArray(response?.questions)||response.questions.length!==attempt.fields.expected_questions.length||response.questions.some((q:any)=>q.project_id!==project||!attempt!.fields.expected_questions.some((r:any)=>r.id===q.id)))throw new Error('采用回包不完整，请核对同一请求。');
  commit({adoptAttempt:null,choices:[]});const after=await read();
  // Only our just-confirmed revisions can become the comparison base without
  // another reconciliation. A different intervening writer still needs review.
  const owned=(after?.questions||[]).filter((q:any)=>response.questions.some((r:any)=>r.id===q.id&&r.revision===q.revision));
  commit({reviewed:{...latest.current.reviewed,...Object.fromEntries(owned.map((q:any)=>[q.id,{id:q.id,revision:q.revision,sha256:q.sha256,qaec:q.content.qaec}]))},reconciled:{...latest.current.reconciled,...Object.fromEntries(owned.map((q:any)=>[q.id,q.sha256]))}});
  await context.current.refreshResearch();await context.current.refresh();
 }catch(e){if(rejection(e)&&!uncertain){safe({adoptAttempt:null});void read().catch(fail);}fail(e);}finally{if(live.current)setBusy('');}}
 const openQ=(id:string)=>{const q=questions.find((q:any)=>q.id===id)||current(id);c.open({id,kind:'question',title:q?.title||'研究问题',value:id},true);};
 const source=(r:Ref)=>c.open(sourceView({...r,consumer_id:project},project,c.catalog.objects.find(o=>o.id===r.id)?.title),true);
 return <div className="wb-exploration wb-research-work"><div className="editor-toolbar"><span className="breadcrumbs">研究 / {task?'工作候选':'新建工作'}</span>{task&&<><span className="runtime-caption" role="status">{workLabels[task.status]||task.status}</span><button className="icon-button" aria-label="刷新研究工作" disabled={!!busy} onClick={()=>void read().catch(fail)}><RefreshCw/></button></>}</div>
 <article className="document exploration-document"><h1>{proposal?'研究工作候选':'推进研究问题'}</h1>{error&&<p role="alert" className="exploration-alert">{error}</p>}
 {!draft.taskId?<><p className="doc-lead">明确这次要推进的工作，选定 Q、AEC 范围和保存材料。返回候选后，再决定采用哪些内容。</p>
 <fieldset disabled={locked} className="exploration-fields"><label>本次工作<textarea aria-label="本次研究工作" rows={4} placeholder="例如：比较已有结果，说明哪种方法更接近目标、证据和限制。" value={draft.request} onChange={e=>edit({request:e.target.value})}/></label>
 <section aria-label="关联研究问题"><h2>关联 Q 与范围</h2>{questions.map((q:any)=>{const t=draft.questions.find(t=>t.id===q.id);return <div className="research-work-target" key={q.id}><label><input type="checkbox" aria-label={'关联 '+questionLabel(q)} checked={!!t} disabled={!t&&draft.questions.length>=4} onChange={e=>edit({questions:e.target.checked?[...draft.questions,{id:q.id,revision:q.revision,parts:['A','E','C']}]:draft.questions.filter(t=>t.id!==q.id)})}/>{questionLabel(q)}</label>{t&&<div className="research-work-parts">{(['A','E','C'] as Part[]).map(p=><label key={p}><input type="checkbox" aria-label={q.id+' '+p+' '+partLabel[p]} checked={t.parts.includes(p)} onChange={e=>edit({questions:draft.questions.map(x=>x.id===q.id?{...x,parts:e.target.checked?[...x.parts,p]:x.parts.filter(i=>i!==p)}:x)})}/>{p} · {partLabel[p]}</label>)}</div>}{unsaved(q.id)&&t&&<p className="runtime-caption">这个 Q 有本窗口未保存草稿，本次只采用项目保存版。</p>}</div>;})}{draft.questions.filter(t=>!questions.some((q:any)=>q.id===t.id)).map(t=><p key={t.id} className="runtime-caption">所选 Q {t.id} 当前不可见。<button className="inline-ref" onClick={()=>edit({questions:draft.questions.filter(x=>x.id!==t.id)})}>移除此 Q</button></p>)}{!questions.length&&<p>先建立或采用一个研究问题，再从这里发起工作。</p>}</section>
 <details><summary>采用的保存材料 · {draft.materials.length} 项</summary><p className="runtime-caption">背景与选定 Q 的完整 QAEC 一同采用；Q 和材料合计最多 8 项。这里选择已登记文字对象，原生文件与未保存草稿不会自动发送。</p>{sources.map(o=><label className="exploration-source" key={o.id}><input type="checkbox" aria-label={'采用 '+o.title} checked={draft.materials.some(r=>r.id===o.id)} disabled={!draft.materials.some(r=>r.id===o.id)&&draft.materials.length+draft.questions.length>=8} onChange={e=>edit({materials:e.target.checked?[...draft.materials,{id:o.id,revision:o.revision}]:draft.materials.filter(r=>r.id!==o.id)})}/><span>{o.title}<small>保存版 · r{draft.materials.find(r=>r.id===o.id)?.revision||o.revision}</small></span></label>)}{draft.materials.filter(r=>!sources.some(o=>o.id===r.id)).map(r=><p key={r.id}>{r.id} 当前不可见。<button className="inline-ref" onClick={()=>edit({materials:draft.materials.filter(x=>x.id!==r.id)})}>移除选择</button></p>)}</details>
 <button className="button" disabled={!writable||!draft.request.trim()||!draft.questions.length||draft.questions.some(q=>!q.parts.length)} onClick={()=>void preview()}>核对工作输入</button></fieldset>
 {draft.preview&&<section className="exploration-preview" aria-label="研究工作输入预览"><h2>本次采用</h2><p>{draft.preview.input.targets.length} 个 Q · {draft.preview.input.materials.length} 项固定来源</p><details><summary>查看保存版与范围</summary>{draft.preview.input.targets.map((r:any)=><p key={r.id}>{questionLabel(questions.find((q:any)=>q.id===r.id)||r)} · r{r.revision} · {r.parts.join(' / ')}</p>)}{draft.preview.input.materials.map((r:Ref)=><button className="inline-ref" key={r.id} onClick={()=>source(r)}>{c.catalog.objects.find(o=>o.id===r.id)?.title||r.id} · r{r.revision}</button>)}</details>
 <div className="exploration-execution"><label>执行路线<select aria-label="研究工作执行路线" value={provider} disabled={!!draft.attempt||!!busy} onChange={e=>safe({provider:e.target.value})}>{!providers.length&&<option value="">尚无可用 Codex CLI 路线</option>}{providers.map((p:any)=><option key={p.id} value={p.id}>{p.id}</option>)}</select></label><label>最长执行时间（秒）<input aria-label="研究工作时限" type="number" min="1" max="900" value={draft.seconds} disabled={!!draft.attempt||!!busy} onChange={e=>safe({seconds:e.target.value})}/></label></div><p className="runtime-caption">最多 1 次模型调用。仅分析已有材料，不执行脚本或启动新实验。</p>{authority?.runtime_running!==true&&<p className="exploration-alert">任务执行服务尚未启动。</p>}{!providers.length&&<button className="inline-ref" onClick={()=>c.setGlobal('agents')}>查看智能体执行路线</button>}{!draft.attempt&&<button className="button primary" disabled={!!busy||!writable||!provider||!budgetOK||authority?.runtime_running!==true} onClick={()=>void submit()}><Briefcase/>交出这项工作</button>}</section>}
 {draft.attempt&&<div className="exploration-recovery"><p>提交结果尚未确认，输入与原请求身份已保留。</p><button className="button" disabled={!!busy} onClick={()=>void submit()}>核对同一工作请求</button></div>}
 </>:<>
 {!result&&<p role="status">正在读取研究工作…<button className="inline-ref" onClick={()=>void read().catch(fail)}>重新读取</button></p>}
 {task&&<details><summary>委托、保存输入与执行记录</summary><p>{task.payload.request}</p><p className="runtime-caption">{task.id} · {task.payload.provider_id} · 最多 {task.payload.budget.max_model_calls} 次 CLI 调用 / {task.payload.budget.timeout_seconds} 秒</p><button className="inline-ref" onClick={()=>c.open({id:'research-work-details:'+task.id,kind:'task',title:'执行详情',value:task.id,data:{raw:true}},true)}>查看执行回执与实际用量<ArrowRight/></button><details><summary>固定输入与来源</summary><pre>{JSON.stringify(snapshot,null,2)}</pre></details></details>}
 {task&&pending(task.status)&&<p className="exploration-wait" role="status">{task.status==='queued'?'等待执行。':'搭档正在分析选定的材料。'}可以切换内容，任务和候选会保留。</p>}
 {task&&!pending(task.status)&&!proposal&&<p className="exploration-alert">{typeof task.error==='string'?task.error:task.error?.message||'这次工作尚未形成候选。请查看执行记录。'}</p>}
 {value&&<><p className="doc-lead">{value.summary}</p><p className="runtime-caption">候选保存版 · r{proposal.revision}。逐项核对后采用；任务完成不代表判断已获科学确认。</p>
 {snapshot.targets.map((t:Ref)=>{const q=current(t.id),old=frozen(t.id);if(!unsaved(q.id)&&!changedSinceReview(q.id))return null;return <section className="exploration-input-status" key={q.id}><p className="runtime-caption">{questionLabel(questions.find((x:any)=>x.id===q.id)||q)}</p> {unsaved(q.id)&&<p className="exploration-alert">这个 Q 有本窗口未保存草稿。先<button className="inline-ref" onClick={()=>openQ(q.id)}>返回 Q 处理草稿</button>，再采用候选。</p>}
 {changedSinceReview(q.id)&&<div className="exploration-recovery"><p>Q 已有新的保存版 · r{q.revision}。本候选基于 r{old.revision}，当前候选和手改均已保留。</p><button className="button" disabled={!!busy||!!draft.adoptAttempt} onClick={()=>void reviewLatest(q.id)}>重新核对当前保存版</button></div>}
</section>;})}
 {value.changes.map((item:Change)=>{const q=current(item.question_id),old=frozen(item.question_id),reviewed=draft.reviewed[q.id],adopted=result.adoptions.find((a:any)=>a.change_id===item.id);return <section className="research-work-change" key={item.id} aria-label={partLabel[item.part]+'候选'}>
 <div className="exploration-candidate-heading">{adopted?<Check aria-label="已采用"/>:<input type="checkbox" aria-label={'选择 '+item.part+' 候选'} disabled={!!busy||!!draft.adoptAttempt||!writable} checked={draft.choices.includes(item.id)} onChange={e=>safe({choices:e.target.checked?[...draft.choices,item.id]:draft.choices.filter(i=>i!==item.id)})}/>}<h2>{item.part} · {partLabel[item.part]}<small>{questionLabel(questions.find((x:any)=>x.id===q.id)||q)}</small></h2></div>
 <p>{item.rationale}</p><p className="runtime-caption">{({plan:'分析计划',supported:'依据已有材料的候选判断',unresolved:'当前仍未解决'} as any)[item.basis]} · {item.mode==='append'?'增加段落':'替换此部分全文'}</p>
 {item.source_refs.map(r=><button className="inline-ref" key={r.id+'@'+r.revision} onClick={()=>source(r)}>{c.catalog.objects.find(o=>o.id===r.id)?.title||r.id} · r{r.revision}</button>)}
 {adopted?<><p className="runtime-caption">已采用至 Q 保存版 · r{adopted.question_revision}；后续仍可继续编辑。</p><button className="inline-ref" onClick={()=>openQ(q.id)}>打开当前 Q<ArrowRight/></button><Markdown text={adopted.adopted_text}/></>:<>
 <div className="research-work-comparison"><div><h3>对照的保存版 · r{reviewed?.revision||old.revision}</h3><Markdown text={reviewed?.qaec[item.part]||'尚未整理。'}/></div><div><h3>拟采用内容</h3>{!draft.choices.includes(item.id)?<Markdown text={proposed(item)}/>:<><div className="research-work-edit-tools"><span>可以直接编辑后采用</span><button className="button quiet" aria-pressed={!!compare[item.id]} onClick={()=>setCompare({...compare,[item.id]:!compare[item.id]})}>比较修改</button></div><CodeEditor text={proposed(item)} original={compare[item.id]?reviewed?.qaec[item.part]||'':undefined} readOnly={!!busy||!!draft.adoptAttempt} viewId={view.id+':'+changeKey(item)} ariaLabel={item.part+' 拟采用内容'} language="markdown" onPosition={()=>{}} onChange={text=>safe({texts:{...latest.current.texts,[changeKey(item)]:text}})}/></>}</div></div>
 {draft.choices.includes(item.id)&&reviewed?.revision!==old.revision&&!changedSinceReview(q.id)&&<label className="research-work-reconcile"><input type="checkbox" checked={draft.reconciled[q.id]===reviewed?.sha256} disabled={!!busy||!!draft.adoptAttempt} onChange={e=>safe({reconciled:{...draft.reconciled,[q.id]:e.target.checked?reviewed.sha256:''}})}/>已对照新的保存版，保留需要的人工作业</label>}
 <details><summary>查看委托时的原文 · r{old.revision}</summary><Markdown text={old.qaec[item.part]||'当时尚未整理。'}/></details>
 </>}
 </section>;})}
 {!value.changes.length&&<p>本次没有建议改写 AEC，可根据以上工作说明和限制继续研究。</p>}
 {value.changes.length>0&&<div className="exploration-adopt"><p className="runtime-caption">仅保存选中的 AEC 全文；Q 表述、状态和未选择内容保持原样。</p><button className="button primary" disabled={!!busy||!writable||(!draft.adoptAttempt&&(!selected.length||blocked))} onClick={()=>void adopt()}>{busy==='adopt'?'正在保存…':draft.adoptAttempt?'核对同一AEC采用请求':'采用所选修改'+(selected.length?' · '+selected.length:'')}</button>{draft.adoptAttempt&&<p role="status">原采用请求已保留，重新核对不会重复保存。</p>}</div>}
 {value.limitations.length>0&&<section><h2>适用范围与限制</h2><ul>{value.limitations.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></section>}
 <section><h2>继续这个问题</h2>{snapshot.targets.map((t:Ref)=><div key={t.id}><button className="inline-ref" onClick={()=>openQ(t.id)}>查看当前 Q</button><button className="inline-ref" onClick={()=>partner?startPartner(c,'接着这个问题，讨论下一步需要做什么。',t.id):openResearchWork(c,t.id)}>发起后续工作<ArrowRight/></button></div>)}</section>
 </>}
 </>}
 {!writable&&<p className="exploration-alert">当前账号只有项目读取权限。</p>}
 </article></div>;
}
