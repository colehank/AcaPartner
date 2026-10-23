import {esc,list,pretty,status,button,field,select,diff,date} from './ui.js';
import {resolutionRequest,resolutionSignature,resolutionPanel,chosenMaterialRefs} from './commission-resolver.js';

export const scopeNames={result:'当前任务与成果',method:'后续工作方式',both:'成果与工作方式'};
export const timingNames={immediate:'明确提交后安排',after_task:'当前相关任务后安排',next_handoff:'下个交接点（原安排）',after_user_trial:'实际试用后再反馈',external_already_saved:'登记此前已保存的改动'};
export function feedbackValues(feedback){
 const content=feedback.content||feedback,view=feedback.feedback_view||{},metadata=feedback.metadata||{};
 const alias={artifact:'result',project:'result',work_method:'method',workstyle:'method',result_and_method:'both'};
 const scope=view.scope||metadata.scope||content.scope||'result';
 const legacyHold=metadata.timing==='after_user_trial'||list(content.actions).some(a=>['deferred_by_user','deferred','defer'].includes(a.status)||a.timing==='after_user_trial');
 return {original:content.original||feedback.text||'',interpretation:content.interpretation||'',scope:alias[scope]||scope,timing:view.timing||metadata.timing||content.timing||'immediate',disposition:view.disposition||content.disposition||metadata.disposition||(legacyHold?'defer':'ready'),reason:content.reason||content.disposition_reason||'',lifecycle:content.lifecycle||'active'};
}
const text=value=>typeof value==='string'?value:pretty(value);
function evidence(value){
 if(value==null||(Array.isArray(value)&&!value.length))return '<p class="hint">尚无登记证据</p>';
 return `<div class="feedback-evidence">${esc(text(value))}</div>`;
}
function changeEvidence(value){
 if(value&&typeof value==='object'&&!Array.isArray(value)&&Array.isArray(value.changed_paths))return `<p>${value.base?`基础修订 ${esc(value.base.revision)} → `:''}结果修订 ${esc(value.result?.revision??'未记录')} · ${esc({revision:'同一成果的新修订',new_candidate:'新候选'}[value.kind]||value.kind||'内容变化')}</p>${value.changed_paths.length?`<ul>${value.changed_paths.map(p=>`<li>${esc(p)}</li>`).join('')}</ul>`:'<p class="hint">没有登记字段差异。</p>'}${evidenceLinks(value)} `;
 return evidence(value);
}
function validationEvidence(value){
 if(value&&typeof value==='object'&&!Array.isArray(value)&&('independent_review' in value||'user_acceptance' in value))return `<p>独立审阅：${esc(value.independent_review===true?'已有审阅记录':value.independent_review===false?'尚未通过':({not_recorded:'尚未记录',pending:'待审阅',pending_independent_review:'待独立审阅',record_linked:'已关联准确版本的审阅记录；不等于通过'}[value.independent_review]||value.independent_review||'尚未记录'))}</p><p>用户验收：${esc(value.user_acceptance===true?'已登记确认':value.user_acceptance===false?'尚未确认':({not_recorded:'尚未记录',pending:'待用户确认'}[value.user_acceptance]||value.user_acceptance||'尚未记录'))}</p>${value.boundary?`<p class="hint">${esc(value.boundary)}</p>`:''}${list(value.records).map(r=>`<div>${evidence(r.summary||r)}${r.scope?`<p class="hint">${esc(r.scope)}</p>`:''}${evidenceLinks(r)}</div>`).join('')}`;
 return evidence(value);
}
function evidenceLinks(value,seen=new Set()){
 if(value==null)return '';
 if(typeof value==='string'){
  if(!/^(ART|TASK|PRJ|QUESTION)-[A-Za-z0-9_-]+$/.test(value)||seen.has(value))return '';
  seen.add(value);return button(value,value.startsWith('TASK-')?'task-detail':'open-object',{id:value},'text-button small');
 }
 if(Array.isArray(value))return value.map(v=>evidenceLinks(v,seen)).join('');
 if(typeof value==='object'){if(value.id&&Number.isInteger(value.revision)&&!seen.has(`${value.id}@${value.revision}`)){seen.add(`${value.id}@${value.revision}`);return button(`${value.title||value.id} · 修订 ${value.revision}`,'open-reference',{id:value.id,revision:value.revision},'text-button small');}return Object.values(value).map(v=>evidenceLinks(v,seen)).join('');}
 return '';
}

const sourceNames={user:'用户意见',coordinator:'协调者记录',independent_review:'独立审阅',independent_agent_review:'独立 Agent 审阅',reviewer:'审阅者',agent:'Agent 记录'};
function provenanceLinks(value){
 if(value==null)return '';
 if(Array.isArray(value))return value.map(provenanceLinks).join('');
 if(typeof value==='object')return Object.values(value).map(provenanceLinks).join('');
 if(typeof value!=='string')return '';
 try{const url=new URL(value);if(!['https:','http:'].includes(url.protocol)||url.username||url.password)return '';return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">打开来源链接</a>`;}catch{return '';}
}
export function feedbackProvenance(content){
 return `<section class="feedback-provenance"><h4>意见来源</h4><p>${esc(sourceNames[content.source]||content.source||'历史记录未声明来源')} · 来源由登记者声明</p>${content.source_reference?`${evidence(content.source_reference)}${evidenceLinks(content.source_reference)}${provenanceLinks(content.source_reference)}<p class="hint">本地文件路径仅供定位；来源标记不认证外部作者，也不代表用户认可。</p>`:''}</section>`;
}
function externalIdentity(action){
 const principal=action.registered_by||{},name={loopback:'本机连接',local_operator:'本地调用者',credential:'已认证凭据'}[principal.kind]||'未登记连接身份';
 return `<p>声称的外部执行者：${esc(action.external_executor?.name||'未登记')}</p>${evidence(action.external_executor?.reference)}${provenanceLinks(action.external_executor?.reference)}<p>登记者：${esc(name)}${principal.credential_sha256?` · ${esc(principal.credential_sha256.slice(0,16))}`:''} · ${date(action.recorded_at)}</p><p class="hint">执行者身份与外部执行过程未经本系统认证；没有关联原生运行。</p>`;
}

export function feedbackCard(feedback,{tasks=[],objects=[],detail=false}={}){
 const f=feedbackValues(feedback),content=feedback.content||feedback,view=feedback.feedback_view||{};
 const actions=list(view.actions||content.actions),target=objects.find(o=>o.id===content.object_id),deferred=f.disposition==='defer',withdrawn=f.lifecycle==='withdrawn';
 return `<article class="panel feedback-card" data-feedback-id="${esc(feedback.id)}"><div class="section-heading"><h${detail?'1':'3'}>${detail?'意见与处理记录':esc(feedback.title||'反馈')}</h${detail?'1':'3'}>${withdrawn||deferred?status(withdrawn?'withdrawn':'deferred'):`<span class="status">已保存 · ${actions.length} 项行动</span>`}</div><small>${esc(feedback.id)} · 修订 ${esc(feedback.revision)} · ${date(feedback.updated_at||feedback.created_at)}</small>${feedbackProvenance(content)}<h4>原话</h4><blockquote>${esc(f.original)}</blockquote><h4>理解与安排</h4><p class="feedback-evidence">${esc(text(f.interpretation||'尚未登记理解；保存原话不代表已处理。'))}</p><div class="feedback-summary"><span>${esc(scopeNames[f.scope]||f.scope)}</span><span>${esc(timingNames[f.timing]||f.timing)}</span></div>${deferred?`<p class="notice">已保留，等待实际试用或后续反馈；不会因刷新或打开而执行。${f.reason?' '+esc(f.reason):''}</p>`:''}${content.object_id?`<p>关联对象：${button(target?.title||content.object_id,'open-object',{id:content.object_id},'text-button small')}${content.object_revision?` · 留言时修订 ${esc(content.object_revision)}`:''}</p>`:''}<h4>行动、改动与验证</h4>${actions.length?actions.map(a=>{
  const task=a.task||tasks.find(t=>t.id===a.task_id),live=task?(a.live_status||task.status):null,external=!task&&a.registration_kind==='external_revision_receipt'&&a.registration_verified===true;
  const output=a.output||task?.result?.object_id,changes=a.changes??task?.result?.changes??a.change,validation=a.validation??task?.result?.validation??a.verification;
  return `<section class="feedback-action"><div class="section-heading"><strong>${esc(scopeNames[a.scope]||a.scope||'登记行动')}</strong>${external?'<span class="status">外部已存改动 · 本地修订已核验</span>':live?status(live):'<span class="status">未关联可读取的运行状态</span>'}</div>${external?externalIdentity(a):''}${external?`<p>${esc(timingNames[a.timing]||a.timing)}</p>`:`<p>由 ${esc(task?.payload?.provider_id||task?.provider||a.owner||'尚未指定')} 执行 · ${esc(timingNames[a.timing]||a.timing||'时机尚未登记')}</p>`}${a.status&&!live&&!external?`<p class="hint">上次登记：${esc(a.status)}；不能据此推定当前执行或完成。</p>`:''}${a.depends_on?.length?`<p>等待：${a.depends_on.map(id=>button(id,'task-detail',{id},'text-button small')).join('')}</p>`:''}${a.task_id?button('查看关联任务','task-detail',{id:a.task_id},'button small'):''}${task?.error||a.unavailable_reason?`<p class="notice">${esc(task?.error||a.unavailable_reason)}</p>`:''}<h5>产生的改动</h5>${changeEvidence(changes??(output?'已登记产物；具体改动见产物与版本记录。':null))}${evidenceLinks(output)}<h5>验证与限制</h5>${validationEvidence(validation)}${evidenceLinks(validation)}${a.evidence?`<h5>行动依据</h5>${evidence(a.evidence)}${evidenceLinks(a.evidence)}`:''}</section>`;
 }).join(''):'<p class="hint">尚未安排执行。可以先保存理解，或明确发起有限委托。</p>'}<div class="button-group">${!detail?button('查看完整意见','open-object',{id:feedback.id},'button small'):''}${!withdrawn?`${button('理解与处理时机','feedback-review',{id:feedback.id},'button small')}${button(deferred?'重新安排执行…':'安排关联行动…','feedback-request',{id:feedback.id},'button primary small')}${button('撤回意见…','feedback-withdraw',{id:feedback.id},'button small subtle')}`:''}</div><details><summary>原始记录</summary><pre>${esc(pretty(feedback))}</pre></details></article>`;
}
export function feedbackFields(feedback=null){
 const f=feedback?feedbackValues(feedback):{scope:'result',timing:'immediate',disposition:'ready',interpretation:'',reason:''};
 return `${feedback?'':field('反馈原话','text','','textarea','required rows="4"')}${field('如何理解这条意见（可留空，后续可纠正）','interpretation',typeof f.interpretation==='string'?f.interpretation:pretty(f.interpretation),'textarea')}${select('意见涉及','scope',Object.entries(scopeNames),f.scope)}${select('结果修订或单独方法工作的安排','timing',Object.entries(timingNames).filter(([key])=>key!=='next_handoff'),f.timing==='next_handoff'?'immediate':f.timing)}${select('当前处理选择','disposition',[['ready','保存，待明确发起行动'],['defer','先保留，稍后或试用后反馈']],f.disposition)}${field('安排说明（可选）','reason',f.reason,'textarea')}<p class="hint">保存不会启动模型。选择两类意见时，成果修订与工作方式候选分别登记；方法候选在成果任务后进行，不自动采用为工作规则。</p>`;
}
export function feedbackComparison(form,before,current,draft){
 form.querySelector('[data-feedback-reconcile]').innerHTML=`<p class="notice">记录已重读；你的草稿仍在表单中。请比较后明确确认，才按当前修订保存或提交。</p>${diff(pretty(before),pretty(current))}<details open><summary>本地草稿</summary><pre>${esc(pretty(draft))}</pre></details><label class="check-field"><input type="checkbox" name="feedback_reconcile" value="yes"><span>已核对当前记录，确认按本地草稿继续</span></label>`;
}
// Used by both review and withdrawal. A 409 never silently rebases a user's choice.
export function feedbackSubmission({base,read,request,saved,compare=feedbackComparison}){
 let current=base,conflict=false,reloaded=false;
 return async(values,form)=>{
  if(conflict&&!reloaded){const latest=await read();if(!form.isConnected)return false;current=latest;reloaded=true;compare(form,base,current,values);return false;}
  if(conflict&&values.feedback_reconcile!=='yes')throw new Error('请先核对当前记录与草稿，并明确确认。');
  try{const result=await request(current,values,form);if(!form.isConnected)return false;if(result!==false)await saved?.(result,form);return result;}
  catch(error){if(error.status===409){conflict=true;reloaded=false;if(form.isConnected){form.querySelector('[data-feedback-reconcile]').innerHTML='<p class="notice">反馈或目标已变化，草稿仍保留。再次点击会先重读比较，不会重复提交旧版本。</p>';form.querySelector('button[type=submit]').textContent='保留草稿并重读比较';}}throw error;}
 };
}

export function feedbackCommission({feedback,target,requestKey,read,action,saved,valuesFromForm=form=>Object.fromEntries(new FormData(form))}){
 let plan=null,previewSignature='',sequence=0;
 const readCurrent=async()=>{plan=null;previewSignature='';return read();};
 return feedbackSubmission({base:{feedback,target},read:readCurrent,saved,request:async(current,v,form)=>{
  const f=current.feedback,values={...v,objective:feedbackValues(f).original},scope=v.scope||feedbackValues(f).scope;
  if(feedbackValues(f).lifecycle==='withdrawn')throw new Error('这条反馈已撤回，不能安排新行动。');
  if(feedbackValues(f).disposition==='defer')throw new Error('这条反馈已保留。请先在“理解与处理时机”明确改为待安排；本次不会执行。');
  const resolvedTarget=scope==='method'||current.target?.kind==='project'?null:current.target;
  const input=resolutionRequest(values,{projectId:f.project_id,target:resolvedTarget});
  const signature=resolutionSignature({...input,feedback_scope:scope,feedback_timing:v.timing});
  if(!plan||signature!==previewSignature||!plan.project){
   const turn=++sequence,result=await action('task.resolve',input);if(!form.isConnected||turn!==sequence)return false;
   const latest=valuesFromForm(form),latestScope=latest.scope||feedbackValues(f).scope;
   const latestInput=resolutionRequest({...latest,objective:feedbackValues(f).original},{projectId:f.project_id,target:latestScope==='method'||current.target?.kind==='project'?null:current.target});
   if(resolutionSignature({...latestInput,feedback_scope:latestScope,feedback_timing:latest.timing})!==signature){plan=null;throw new Error('范围或材料选择已变化，请重新查找。');}
   plan=result;previewSignature=signature;form.querySelector('#commission-resolution').innerHTML=resolutionPanel(result);
   if(input.selected_project_id)form.querySelector('[name=selected_project_id]').value=input.selected_project_id;
   form.querySelector('button[type=submit]').textContent=result.project?'确认采用并发起关联行动':'选择项目后重新查找';return false;
  }
  const calls=Number(v.budget),seconds=Number(v.timeout);
  if(!Number.isInteger(calls)||calls<1||calls>100||!Number.isFinite(seconds)||seconds<1||seconds>900)throw new Error('请设置有限的模型调用次数（1–100）与执行秒数（1–900）。');
  try{return await action('feedback.request',{...input,id:f.id,expected_revision:f.revision,expected_target_revision:resolvedTarget?.revision,scope,timing:v.timing,request_key:requestKey,resolution_pin:plan.pin,selected_materials:chosenMaterialRefs(form),provider_id:v.provider||undefined,output_kind:scope==='method'?'note':resolvedTarget?.kind||'note',constraints:v.constraints,acceptance:v.acceptance,background:v.background,budget:{max_model_calls:calls,timeout_seconds:seconds},priority:Number(v.priority)||0});}
  catch(error){if(error.status===409){plan=null;previewSignature='';}throw error;}
 }});
}
