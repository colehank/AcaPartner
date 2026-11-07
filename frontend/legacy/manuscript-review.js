import {inlineTextDiff} from './text-diff.js';
import {esc,field,select,uid,status} from './ui.js';

// The caller supplies a saved object. Unsaved editor drafts must be saved or
// retained by the host; this module never replaces an editor or its local draft.
export function manuscriptRevisionFields({object,selectedBlockIds=[],annotations=[],annotationIds=[],providers=[]}) {
 const chosen=new Set(selectedBlockIds),aids=new Set(annotationIds);
 return `<p>基于已保存文稿 <strong>${esc(object.title)}</strong> @${esc(object.revision)}。Agent 只提出下方所选段落的文字候选，逐项审阅采用后才写回原稿；批注不会自动标为解决。</p>${field('定向修订要求','request','','textarea','required maxlength="4000"')}<fieldset><legend>允许修订的段落（最多24段）</legend>${(object.content.blocks||[]).filter(b=>chosen.has(b.id)).map(b=>`<label class="field revision-block-option"><span><input type="checkbox" name="block_ids" value="${esc(b.id)}" checked> 已选段落</span><span>${esc(b.text.length>500?b.text.slice(0,500)+'…':b.text)}</span></label>`).join('')}<details ${chosen.size?'':'open'}><summary>选择其他段落</summary>${(object.content.blocks||[]).filter(b=>!chosen.has(b.id)).map((b,i)=>`<label class="field revision-block-option"><span><input type="checkbox" name="block_ids" value="${esc(b.id)}"> ${i+1}. ${b.kind==='heading'?'章节标题':'正文'}</span><span>${esc(b.text.length>240?b.text.slice(0,240)+'…':b.text)}</span></label>`).join('')}</details></fieldset><fieldset><legend>同时交给 Agent 的原始批注（须属于所选段落）</legend>${annotations.filter(a=>!['resolved','orphaned'].includes(a.status)).map(a=>`<label class="field"><span><input type="checkbox" name="annotation_ids" value="${esc(a.id)}" ${aids.has(a.id)?'checked':''}> ${esc(a.text)}</span><small>${esc(a.anchor?.block_id)} · 原批注 @${esc(a.revision)}</small></label>`).join('')||'<p>尚无可选批注。</p>'}</fieldset>${select('执行模型','provider_id',providers.map(p=>[p.id,`${p.id} · ${p.route}${p.available&&p.authorized?'':'（当前不可执行）'}`]),providers.find(p=>p.available&&p.authorized)?.id||providers[0]?.id||'')}${field('模型请求上限（含工具往返）','max_model_calls',6,'number','required min="1" max="20"')}${field('执行时限（秒）','timeout_seconds',300,'number','required min="1" max="900"')}`;
}

export function manuscriptRevisionSubmission(values,form,object,requestKey) {
 const fields=new FormData(form);
 return {object_id:object.id,expected_revision:object.revision,block_ids:fields.getAll('block_ids'),annotation_ids:fields.getAll('annotation_ids'),request:values.request,provider_id:values.provider_id,budget:{max_model_calls:Number(values.max_model_calls),timeout_seconds:Number(values.timeout_seconds)},request_key:requestKey};
}

// Linear-time text comparison retains every character. Prefix/suffix highlights
// are deliberately textual, not a claim to infer semantic or scientific change.
export function manuscriptTextDiff(before,after) {
 return `<div class="manuscript-text-diff"><div class="inline-tracked-diff">${inlineTextDiff(before,after)}</div><details class="diff-original-candidate"><summary>原文与完整候选文字</summary><section><h4>原文</h4><div class="manuscript-paragraph" style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(before)}</div></section><section><h4>候选文字</h4><div class="manuscript-paragraph" style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(after)}</div></section></details></div>`;
}
function reviewedText(row){return row.state==='pending'?manuscriptTextDiff(row.before,row.after):`<div class="manuscript-paragraph" style="white-space:pre-wrap">${esc(row.state==='accepted'?row.after:row.before)}</div><details><summary>修订痕迹与原文</summary>${manuscriptTextDiff(row.before,row.after)}</details>`;}

function decisionButton(label,id,decision,disabled=false,change=false) {
 return `<button class="button ${decision==='accept'?'primary':''}" type="button" data-action="manuscript-decide" ${change?`data-change="${esc(id)}" `:''}data-block="${esc(id)}" data-decision="${decision}" ${disabled?'disabled':''}>${label}</button>`;
}

export function manuscriptReviewPanel(view) {
 if(view.version===2)return manuscriptRoundReviewPanel(view);
 const p=view.proposal,t=view.target;
 return `<section class="manuscript-review" data-manuscript-task="${esc(view.task_id)}"><header><h3>定向修订审阅</h3><p>${esc(t.title)} · 原稿 @${esc(t.base_revision)} → 当前 @${esc(t.current_revision)}</p>${status(view.task_status)}</header>${view.annotations.length?`<details><summary>本次交给 Agent 的批注原话（${view.annotations.length}）</summary>${view.annotations.map(a=>`<blockquote><p style="white-space:pre-wrap">${esc(a.text)}</p><small>${esc(a.id)} · ${esc(a.anchor?.block_id)} · 原批注 @${esc(a.revision)}</small></blockquote>`).join('')}</details>`:''}${!p?`<p role="status">${view.task_error?'此轮未生成候选：'+esc(view.task_error):'候选尚未生成。'}当前原稿保持不变。</p><button class="button small" data-action="task-detail" data-id="${esc(view.task_id)}">执行记录与用量</button>`:`<p style="white-space:pre-wrap">${esc(p.candidate.summary)}</p><p>候选来自 ${esc(p.proposer.provider_id)} · ${esc(p.proposer.route)}。采用是操作者的文字编辑决定，不代表科学批准或用户本人已验收。</p>${view.block_reason?`<p role="status">${esc(view.block_reason)}</p>`:''}${p.changes.map(row=>`<article class="manuscript-change" data-manuscript-block="${esc(row.id)}"><h4>段落 ${esc(row.id)} · ${status(row.state)}</h4>${reviewedText(row)}<p>修订理由：${esc(row.reason)}</p>${row.conflict?`<p role="alert">当前段落已被编辑或移除，本条不能采用；用户改动保留。</p>${row.current_text!==null?`<details><summary>当前已保存文字</summary><p style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(row.current_text)}</p></details>`:''}`:''}${row.state==='pending'?`<div class="button-row">${decisionButton('采用此段',row.id,'accept',!row.can_accept)}${decisionButton('拒绝此段',row.id,'reject',!view.can_decide)}</div>`:`<p>操作者 ${esc(row.decision_receipt?.operator)} · 结果版本 @${esc(row.decision_receipt?.result_revision)}</p>`}</article>`).join('')||`<p>Agent 未提出正文变更。原文保持不变。</p><button class="button" type="button" data-action="manuscript-decide" data-decision="acknowledge" ${view.can_decide?'':'disabled'}>已审阅无变更候选</button>`}<p>批注保持原始记录，需另行明确解决。未采用的段落、标题、引用和其他内容不会被候选覆盖。</p><details><summary>候选身份与审阅记录</summary><p>任务 ${esc(view.task_id)}<br>原生会话 ${esc(p.proposer.session_id)}<br>候选 ${esc(p.candidate_sha256)}<br>提案 ${esc(p.proposal_sha256)}</p>${(view.decisions||[]).map(r=>`<p>第 ${esc(r.decision_version)} 次决定 · ${esc(r.operator)} · ${esc(r.at)}<br>${r.decisions.map(d=>`${esc(d.block_id)}：${d.decision==='accept'?'采用':'拒绝'}`).join('；')||'已审阅无变更候选'}<br>原稿 @${esc(r.base_revision)} → @${esc(r.result_revision)}</p>`).join('')}</details>`}</section>`;
}

// read(params) returns manuscript.revision.view; request(action, payload) returns
// the unwrapped API result. Host onSaved must retain dirty drafts before refresh.
export function createManuscriptReviewController({taskId,read,request,onChange=()=>{},onSaved=()=>{}}) {
 let current=null,epoch=0,disposed=false,busy=false,pending=null;
 const notify=()=>{if(!disposed)onChange(current,{busy});};
 async function load() {
  const mine=++epoch,value=await (read?read({task_id:taskId}):request('manuscript.revision.view',{task_id:taskId}));
  if(value?.task_id!==taskId)throw new Error('返回的审阅任务身份不符');
  if(!disposed&&mine===epoch){current=value;notify();}return value;
 }
 async function decide(blockIds,decision) {
  if(disposed)throw new Error('审阅面板已关闭');
  if(busy)throw new Error('上一项审阅仍在保存');
  if(!current?.proposal||!current.can_decide)throw new Error('请重新读取可审阅候选');
  const snapshot=current,v2=snapshot.version===2;
  const ids=Array.isArray(blockIds)?blockIds:[blockIds],decisions=decision==='acknowledge'?[]:ids.map(id=>({[v2?'change_id':'block_id']:id,decision}));
  const payload={task_id:taskId,candidate_sha256:snapshot.proposal.candidate_sha256,proposal_sha256:snapshot.proposal.proposal_sha256,expected_decision_version:snapshot.decision_version,...(v2?{expected_target_revisions:{...snapshot.current_target_revisions}}:{expected_target_revision:snapshot.target.current_revision}),decisions};
  const targetId=current.target.id,changesSource=decisions.some(d=>d.decision==='accept');
  const signature=JSON.stringify(payload);
  // Keep an uncertain network result retryable with the same idempotency key.
  if(!pending||pending.signature!==signature)pending={signature,payload:{...payload,request_key:uid('MANUSCRIPT-REVIEW')}};
  busy=true;notify();let receipt;
  try { receipt=await request('manuscript.revision.decide',pending.payload);
   if(receipt?.task_id!==taskId||receipt.candidate_sha256!==payload.candidate_sha256||receipt.proposal_sha256!==payload.proposal_sha256||receipt.object_id!==targetId||receipt.decision_version!==payload.expected_decision_version+1||JSON.stringify(receipt.decisions)!==JSON.stringify(decisions)||receipt.source_changed!==changesSource)throw new Error('审阅回执身份不符；请重新读取原任务');
   if(v2)validateRoundReceipt(receipt,payload,snapshot);
   else if(receipt.base_revision!==payload.expected_target_revision||receipt.result_revision!==payload.expected_target_revision+(changesSource?1:0))throw new Error('审阅回执身份不符；请重新读取原任务');
   pending=null;
   if(!disposed&&receipt.source_changed)await onSaved(receipt);
   if(!disposed)await load();return receipt;
  } finally {busy=false;notify();}
 }
 return {load,decide,state:()=>current,isBusy:()=>busy,destroy(){disposed=true;epoch++;}};
}

// The host chooses exact saved targets and original opinions; this helper never
// invents an Agent response, creates a task, or applies an editor draft.
export function manuscriptRoundSubmission({object,targets,opinions=[],annotationIds=[],request,providerId,budget,requestKey}) {
 return {contract_version:2,object_id:object.id,expected_revision:object.revision,targets:structuredClone(targets),opinions:structuredClone(opinions),annotation_ids:[...annotationIds],request,provider_id:providerId,budget:{...budget},request_key:requestKey};
}

function validateRoundReceipt(receipt,payload,snapshot) {
 const fail=()=>{throw new Error('审阅回执身份不符；请重新读取原任务');};
 const changed=new Set();
 for(const decision of payload.decisions){
  const row=snapshot.proposal.changes.find(r=>r.id===decision.change_id);if(!row)fail();
  if(decision.decision==='accept')changed.add(row.target.object_id);
 }
 const expected=payload.expected_target_revisions,rows=receipt.objects;
 if(receipt.version!==2||!Array.isArray(rows)||rows.length!==Object.keys(expected).length||new Set(rows.map(r=>r.object_id)).size!==rows.length)fail();
 for(const row of rows){
  if(!Object.hasOwn(expected,row.object_id)||row.base_revision!==expected[row.object_id]||row.result_revision!==row.base_revision+(changed.has(row.object_id)?1:0)||row.source_changed!==changed.has(row.object_id)||typeof row.result_sha256!=='string'||!/^[a-f0-9]{64}$/.test(row.result_sha256))fail();
 }
 const main=rows.find(r=>r.object_id===snapshot.target.id);
 if(!main||receipt.base_revision!==main.base_revision||receipt.result_revision!==main.result_revision||receipt.result_sha256!==main.result_sha256)fail();
}

function roundState(value) {
 return ({pending:'待决定',accepted:'已采用',rejected:'已拒绝',no_changes:'未提出变化',partially_decided:'部分已决定',mixed_decisions:'分别采用／拒绝'})[value]||'待审阅';
}

export function manuscriptRoundReviewPanel(view) {
 const p=view.proposal,responses=p?.responses||[],changes=p?.changes||[];
 const changeHTML=row=>{
  const target=view.targets.find(t=>JSON.stringify(t.target)===JSON.stringify(row.target));
  const label=row.target.kind==='workshop_note'?'章节工坊笔记':row.target.field==='caption'?'稿内图注':'稿件正文';
  return `<article class="manuscript-change" data-manuscript-change="${esc(row.id)}"><h4>${label} · ${esc(roundState(row.state))}</h4>${target?.title?`<p>${esc(target.title)}</p>`:''}${row.target.exists===false?'<p>新增笔记段落；原文为空。接受后才写入章节笔记。</p>':''}${reviewedText(row)}<p style="white-space:pre-wrap">理由：${esc(row.reason)}</p>${row.conflict?`<p role="alert">${esc(row.conflict_reason||'目标已变化')}。当前用户改动保留。</p>${row.current_text!==null?`<details><summary>当前已保存文字</summary><p style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(row.current_text)}</p></details>`:''}`:''}${row.state==='pending'?`<div class="button-row">${decisionButton('采用此项',row.id,'accept',!row.can_accept,true)}${decisionButton('拒绝此项',row.id,'reject',!view.can_decide,true)}</div>`:`<p>操作者 ${esc(row.decision_receipt?.operator)} · 结果版本 @${esc(row.decision_receipt?.result_revision)}</p>`}</article>`;
 };
 const opinions=view.opinions.map((opinion,index)=>{
  const response=responses.find(r=>r.opinion_id===opinion.id),linked=changes.filter(r=>r.opinion_id===opinion.id);
  return `<section class="manuscript-opinion" data-opinion-id="${esc(opinion.id)}"><h4>意见 ${index+1} · ${esc(roundState(opinion.adoption_state))}</h4><blockquote style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(opinion.text)}</blockquote><small>${opinion.source.kind==='annotation'?'原始批注':'本轮手动意见'}</small>${response?`<p style="white-space:pre-wrap"><strong>Agent 回应</strong><br>${esc(response.text)}</p><details open><summary>验证与限制</summary><p style="white-space:pre-wrap">验证：${esc(response.verification)}</p><p style="white-space:pre-wrap">限制：${esc(response.limitations)}</p></details>${linked.map(changeHTML).join('')||'<p>本条意见没有提出内容变化；回应本身不表示已解决。</p>'}`:'<p>等待 Agent 逐条回应；当前内容保持。</p>'}</section>`;
 }).join('');
 return `<section class="manuscript-review manuscript-round" data-manuscript-task="${esc(view.task_id)}"><header><h3>逐条修订回合</h3><p>${esc(view.target.title)} · 原稿 @${esc(view.target.base_revision)} → 当前 @${esc(view.target.current_revision)}</p>${status(view.task_status)}</header>${p?`<p style="white-space:pre-wrap">${esc(p.candidate.summary)}</p><p>候选来自 ${esc(p.proposer.provider_id)} · ${esc(p.proposer.route)}。每项分别决定，接受笔记变化不会把准备内容写入正文。</p>${p.generation?.recovery_id?'<p class="notice">已接回原执行登记的候选。原任务失败和预算记录保留，未追加模型调用。</p>':''}`:`<p role="status">${view.task_error?'本轮尚无可审阅候选：'+esc(view.task_error):'本轮候选尚未生成。'}</p><button class="button small" data-action="task-detail" data-id="${esc(view.task_id)}">执行记录与用量</button>`}${view.block_reason?`<p role="status">${esc(view.block_reason)}</p>`:''}${opinions}${p&&!changes.length?`<button class="button" type="button" data-action="manuscript-decide" data-decision="acknowledge" ${view.can_decide?'':'disabled'}>已审阅无变更回应</button>`:''}<p>保存、回应、采用与实际解决分别记录。批注不会自动标为解决；文字采用不代表科学批准，也不会运行图形或新计算。</p>${p?`<details><summary>本轮来源与决定记录</summary><p>任务 ${esc(view.task_id)}<br>原生会话 ${esc(p.proposer.session_id)}<br>候选 ${esc(p.candidate_sha256)}</p>${(view.decisions||[]).map(r=>`<p>第 ${esc(r.decision_version)} 次决定 · ${esc(r.operator)} · ${esc(r.at)}<br>${r.decisions.map(d=>`${esc(d.change_id)}：${d.decision==='accept'?'采用':'拒绝'}`).join('；')||'已审阅无变更回应'}<br>${r.objects.filter(o=>o.source_changed).map(o=>`${esc(o.object_id)} @${esc(o.base_revision)} → @${esc(o.result_revision)}`).join('；')||'内容未改变'}</p>`).join('')}</details>`:''}</section>`;
}
