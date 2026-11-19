import {esc,button,date,list,pretty,field,select} from './ui.js';
import {documentMarkdown} from './document-markdown.js';

export function canStageRevision(view,child){
 const staging=child.revision_staging,sha=child.candidate?.candidate_sha256;
 if(staging?.allowed!==true||staging.parent_status!==view.task?.status||staging.original_candidate_sha256!==sha||child.role!=='delegate'||child.task?.status!=='generated'||!/^[a-f0-9]{64}$/.test(sha||''))return false;
 return (staging.mode==='control_handoff'&&staging.parent_status==='waiting_input')||(staging.mode==='native_budget_handoff'&&staging.parent_status==='waiting_resource');
}

function resourceNotice(parentStatus,boundary){
 if(parentStatus!=='waiting_resource')return '';
 const remaining=boundary?.remaining_parent_preallocated_calls;
 return `<div class="notice"><strong>原资源等待保留</strong><p>提交只登记修订候选，不解除资源等待，不重置已用额度，不继续父任务。后续明确继续仍受父协作及子任务原有预算限制。</p>${Number.isInteger(remaining)&&remaining>=0?`<p class="hint">父协作尚可预分配调用额度：${esc(remaining)}。此额度不代表已批准新的预算。</p>`:''}</div>`;
}

export function revisionReports(objects,projectId,excluded=[]){
 return list(objects).filter(o=>o.kind==='report'&&o.project_id===projectId&&!excluded.includes(o.id)&&!o.archived&&Number.isInteger(o.revision)&&o.revision>0);
}

function candidateButton(parentId,childId,sha,label='查看原候选'){
 return button(label,'cycle-revision-candidate',{id:parentId,delegate:childId,sha},'button small');
}

export function revisionPanel(view,child){
 const r=child.coordinator_revision,parentId=view.task?.id;
 return `${r?`<section class="panel"><h4>协调者提交的修订报告</h4><p>${r.valid===false?`<strong>当前不能采用：${esc(r.invalid_reason||'来源或任务状态已变化')}</strong>`:'已保存为后续审查的候选输入'} · 科学待审</p><p>${esc(r.reason)}</p><p class="hint">${date(r.at)} · 保存时未继续父任务，未调用模型。关联版本固定；报告后续编辑不会静默替换它。</p>${resourceNotice(view.task?.status)}<div class="button-group">${r.source_ref?button(`查看修订报告 · 修订 ${r.source_ref.revision}`,'open-reference',r.source_ref,'button small'):''}${candidateButton(parentId,child.id,r.original_candidate_sha256)}</div><details><summary>原候选与报告修订的差异</summary><pre>${esc(pretty(r.diff))}</pre></details><details><summary>来源和候选身份</summary><pre>${esc(pretty({source_ref:r.source_ref,source_sha256:r.source_sha256,original_candidate_sha256:r.original_candidate_sha256,candidate_sha256:r.candidate_sha256}))}</pre></details></section>`:''}${canStageRevision(view,child)?button(r?'另选报告版本并预览':'关联修订报告并预览','cycle-stage-revision',{id:parentId,delegate:child.id},'button small'):''}`;
}

export function candidateReading(candidate,label='原候选 · 只读'){
 const content=candidate?.content||candidate||{};
 return `<section class="panel"><h4>${esc(label)}：${esc(candidate?.title||'保存的候选')}</h4><div class="document-reading">${list(content.blocks).map(b=>documentMarkdown(b.text||'',content.resources||{})).join('')||(content.markdown?documentMarkdown(content.markdown,content.resources||{}):'<p class="hint">没有文稿段落。</p>')}</div><details><summary>完整候选与身份</summary><pre>${esc(pretty(candidate))}</pre></details></section>`;
}

export function revisionFields(view,child,reports){
 const selected=revisionReports(reports,view.task?.project_id,child.revision_staging?.excluded_source_ids||[]);
 return `<p>把本项目已保存的报告版本交给此子任务的后续审查。提交保留原候选和修订理由，不代表科学批准。</p>${resourceNotice(view.task?.status)}<p class="hint">子任务 ${esc(child.id)} · 原候选 SHA-256 ${esc(child.candidate?.candidate_sha256)}</p>${selected.length?select('修订报告（固定到列出的版本）','source_ref',[['','请选择报告版本'],...selected.map(o=>[`${o.id}@${o.revision}`,`${o.title} · 修订 ${o.revision} · ${o.id}`])],'','required'):'<div class="notice">本项目尚无可选报告。先保存一份报告，再从此入口选择其明确版本。</div>'}${field('修订理由：改动了什么、依据是什么','reason','','textarea','required maxlength="8000"')}<div id="cycle-revision-preview"><p class="hint">先预览原候选、报告和差异，再明确提交。预览与提交均不调用模型。</p></div>`;
}

export function revisionPreview(result){
 const source=result.source||{};
 return `<div class="notice">${result.ready?'预览已核对。再次点击“提交这份修订供审查”后才会保存。':'当前不能提交：'+esc(result.message||result.error?.message||result.error||'请核对来源与任务状态。')}<p>不会继续父任务；不会新增模型调用；科学待审。</p></div>${resourceNotice(result.parent_status,result.resource_boundary)}${source.id?button(`查看采用报告 · 修订 ${source.revision}`,'open-reference',{id:source.id,revision:source.revision},'button small'):''}${candidateReading(result.original_candidate,'原候选')}${candidateReading(result.revised_candidate||result.candidate,'拟采用的修订正文')}<details open><summary>将保存的差异</summary><pre>${esc(pretty(result.diff))}</pre></details>${result.excluded?`<details><summary>未纳入审查正文的报告字段与段落</summary><p class="hint">完整报告版本保留；作者自评和执行记录等不作为科研证据正文递交。</p><pre>${esc(pretty(result.excluded))}</pre></details>`:''}<details><summary>本次来源关联</summary><pre>${esc(pretty(result.lineage))}</pre></details>`;
}

export function revisionSubmission({view,child,reports,action,requestKey,saved,valuesFromForm=form=>Object.fromEntries(new FormData(form))}){
 const available=revisionReports(reports,view.task?.project_id,child.revision_staging?.excluded_source_ids||[]);
 let preview=null,signature='',sequence=0,committing=false;
 const fields=values=>{
  const report=available.find(r=>`${r.id}@${r.revision}`===values.source_ref),reason=String(values.reason||'').trim();
  if(!report)throw new Error('请选择本项目的已保存报告版本。');
  if(!reason)throw new Error('请填写修订理由。');
  if(!canStageRevision(view,child))throw new Error('当前任务不在可提交修订的交接状态。');
  return {id:view.task.id,delegate_id:child.id,candidate_sha256:child.candidate.candidate_sha256,source_id:report.id,source_revision:report.revision,reason};
 };
 const invalidate=form=>{
  sequence++;preview=null;signature='';
  if(form?.isConnected){form.querySelector('button[type=submit]').textContent='重新预览修订';form.querySelector('#cycle-revision-preview').innerHTML='<p class="hint">选择或理由已变化，请重新预览再提交。</p>';}
 };
 const submit=async(values,form)=>{
  if(committing)return false;
  const input=fields(values),next=JSON.stringify(input);
  if(!preview||next!==signature){
   const turn=++sequence;preview=null;signature='';
   const result=await action('cycle.stage_revision_preview',input);
   if(!form.isConnected||turn!==sequence)return false;
   if(JSON.stringify(fields(valuesFromForm(form)))!==next){invalidate(form);return false;}
   form.querySelector('#cycle-revision-preview').innerHTML=revisionPreview(result);
   form.querySelector('button[type=submit]').textContent=result.ready?'提交这份修订供审查':'重新预览修订';
   if(result.ready){if(!result.pin)throw new Error('预览缺少版本校验，尚未提交。');preview=result;signature=next;}return false;
  }
  committing=true;
  try{
   const result=await action('cycle.stage_revision',{...input,pin:preview.pin,request_key:requestKey,approved:true});
   if(saved)await saved(result,form);return result;
  }catch(error){if(error.status)invalidate(form);throw error;}finally{committing=false;}
 };
 submit.invalidate=invalidate;
 return submit;
}
