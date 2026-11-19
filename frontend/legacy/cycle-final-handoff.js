import {esc,button,date,list,pretty,field,select,status,kinds} from './ui.js';
import {candidateReading} from './cycle-handoff.js';

const sha=value=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const waiting=new Set(['waiting_input','waiting_resource','waiting_authorization']);

export function finalRevisionSources(objects,projectId){
 return list(objects).filter(o=>['report','note'].includes(o.kind)&&o.project_id===projectId&&!o.archived&&Number.isInteger(o.revision)&&o.revision>0);
}

export function canStageFinalRevision(view){
 const stage=view.final_revision_staging;
 return stage?.allowed===true&&waiting.has(view.task?.status)&&stage.parent_status===view.task.status
  &&typeof stage.old_source?.id==='string'&&Number.isInteger(stage.old_source.revision)&&stage.old_source.revision>0&&sha(stage.old_source.sha256)
  &&typeof stage.reviewer_id==='string'&&!!stage.reviewer_id&&(stage.reviewer_candidate_sha256===null||sha(stage.reviewer_candidate_sha256));
}

function budgetBoundary(parentStatus,remaining){
 return `<div class="notice"><p>父协作当前状态：${status(parentStatus)}。保存此次修订的操作新增模型调用 0，不自动继续父任务或重置已用额度。</p>${Number.isInteger(remaining)&&remaining>=0?`<p>父协作尚可预分配调用额度：${esc(remaining)}。</p>`:'<p>剩余预分配额度尚未读取。</p>'}<p>${waiting.has(parentStatus)?'之后在任务列表明确点击“继续”，才能在原有剩余额度内安排新的独立最终审查。':'独立最终审查进展以当前协作记录为准，后续执行沿用已有预算。'}既有分工和整合任务保留。</p></div>`;
}

function sourceLink(ref,label){return ref?.id?button(`${label} · 修订 ${ref.revision}`,'open-reference',{id:ref.id,revision:ref.revision},'button small'):'';}

export function finalRevisionPanel(view){
 const staged=view.final_revision,entry=view.final_revision_staging;
 if(!staged&&!canStageFinalRevision(view))return '';
 return `<section class="panel"><h3>最终稿修订交接</h3>${staged?`<p><strong>${staged.valid===false?'当前不能用于下一次审查：'+esc(staged.invalid_reason||'来源或输入已变化'):'协调者修订已登记；独立最终审查进展见当前协作记录'}</strong></p><p>${esc(staged.reason)}</p><p class="hint">${date(staged.at)} · 本次修订归属协调者；科学接受与用户验收独立确认。</p><div class="button-group">${sourceLink(staged.old_source,'查看原最终稿')}${sourceLink(staged.source_ref,'查看协调者修订')}${staged.reviewer_id?button('查看原最终审查记录','task-detail',{id:staged.reviewer_id},'button small'):''}</div><details><summary>修订正文与差异</summary>${candidateReading(staged.candidate,'协调者修订候选')}<pre>${esc(pretty(staged.diff))}</pre></details>`:'<p>可关联本项目已保存报告或笔记的明确版本，接回当前最终审查交接。</p>'}${budgetBoundary(view.task?.status,entry?.remaining_preallocated_calls)}${canStageFinalRevision(view)?button(staged?'重新预览最终稿修订':'关联最终稿修订并预览','cycle-stage-final-revision',{id:view.task.id},'button small'):''}</section>`;
}

const reportOptions=reports=>[['','请选择报告或笔记版本'],...reports.map(r=>[`${r.id}@${r.revision}`,`${kinds[r.kind]||r.kind} · ${r.title} · 修订 ${r.revision} · ${r.id}`])];
function optionMarkup(reports){return reportOptions(reports).map(([value,label])=>`<option value="${esc(value)}">${esc(label)}</option>`).join('');}

function identityStatus(view){
 const stage=view.final_revision_staging||{};
 return `<p>${canStageFinalRevision(view)?'服务端已核对当前交接资格。':'当前不能提交：'+esc(stage.reason||'服务端未确认最终稿交接资格。')}</p>${budgetBoundary(view.task?.status,stage.remaining_preallocated_calls)}${sourceLink(stage.old_source,'查看原最终稿')}<details><summary>原最终稿与审查身份</summary><pre>${esc(pretty({old_source:stage.old_source,reviewer_id:stage.reviewer_id,reviewer_candidate_sha256:stage.reviewer_candidate_sha256}))}</pre></details>`;
}

export function finalRevisionFields(view,reports){
 const available=finalRevisionSources(reports,view.task?.project_id);
 return `<p>此最终稿修订由协调者提交，可选择原成果的新修订或同项目的另一报告、研讨笔记。成果身份和类型保留，提交后需新的独立最终审查。</p><div id="final-revision-status">${identityStatus(view)}</div>${select('明确采用的报告或笔记版本','source_ref',reportOptions(available),'','required')}${!available.length?'<p class="notice">本项目尚无可选报告或笔记。请先保存成果，再重新打开此入口。</p>':''}${field('修订理由与依据','reason','','textarea','required maxlength="8000"')}<div id="final-revision-preview"><p class="hint">先预览原最终稿、修订正文和差异，再明确提交。</p></div>`;
}

export function finalRevisionPreview(result){
 return `<div class="notice"><strong>${result.ready?'预览已核对，再次点击才会提交。':'当前不能提交：'+esc(result.message||result.error?.message||result.error||'请核对当前状态。')}</strong><p>修订归属：协调者。来源类型：${esc(kinds[result.candidate?.kind]||result.candidate?.kind||'未记录')}。科学接受与用户验收尚未完成。</p></div>${budgetBoundary(result.parent_status,result.resource_boundary?.remaining_parent_preallocated_calls)}${sourceLink(result.source,'查看采用成果版本')}${candidateReading(result.original_candidate,'原最终稿')}${candidateReading(result.candidate,'协调者修订正文')}<details open><summary>最终稿差异</summary><pre>${esc(pretty(result.diff))}</pre></details>${result.materials?`<details open><summary>下一次独立最终审查的材料选择</summary><p>明确采用的材料（对象、修订与 SHA）：</p><pre>${esc(pretty(result.materials.adopted||[]))}</pre><p>保留历史但本次未重新供给的原材料：</p><pre>${esc(pretty(result.materials.omitted_parent||[]))}</pre><p class="hint">这些记录没有被删除。此处说明下一次审查将收到的材料范围。</p>${result.materials.scope?`<p>${esc(result.materials.scope)}</p>`:''}</details>`:''}<details><summary>按结构排除的字段与段落</summary><p class="hint">后端按字段和段落类型排除 review、author_assessment、execution_log 等记录；普通正文中仍可能有评价性文字，需要人工核读。</p><pre>${esc(pretty(result.excluded))}</pre></details>`;
}

export function finalRevisionSubmission({view,reports,action,read,requestKey,saved,valuesFromForm=form=>Object.fromEntries(new FormData(form))}){
 let current=view,available=finalRevisionSources(reports,view.task?.project_id),preview=null,signature='',sequence=0,committing=false,needsRead=false,committed=null;
 const invalidate=form=>{
  if(committed)return;
  sequence++;preview=null;signature='';
  if(form?.isConnected){form.querySelector('button[type=submit]').textContent='重新预览最终稿修订';form.querySelector('#final-revision-preview').innerHTML='<p class="hint">当前预览已失效，草稿保留。请重新预览后提交。</p>';}
 };
 const reread=async form=>{
  const turn=++sequence,next=await read();
  if(!form.isConnected||turn!==sequence)return false;
  current=next.view;available=finalRevisionSources(next.reports,current.task?.project_id);needsRead=false;
  const chooser=form.querySelector('[name=source_ref]'),selected=chooser.value;
  chooser.innerHTML=optionMarkup(available);chooser.value=available.some(r=>`${r.id}@${r.revision}`===selected)?selected:'';
  form.querySelector('#final-revision-status').innerHTML=identityStatus(current);
  const submit=form.querySelector('button[type=submit]');submit.hidden=!canStageFinalRevision(current);submit.textContent='重新预览最终稿修订';
  return false;
 };
 const fields=values=>{
  if(!canStageFinalRevision(current))throw new Error(current.final_revision_staging?.reason||'当前最终稿交接不可用，请保留任务状态。');
  const report=available.find(r=>`${r.id}@${r.revision}`===values.source_ref),reason=String(values.reason||'').trim();
  if(!report)throw new Error('请选择本项目当前已保存的明确报告或笔记版本。');
  if(!reason)throw new Error('请填写最终稿修订理由。');
  const stage=current.final_revision_staging;
  return {id:current.task.id,old_source_sha256:stage.old_source.sha256,reviewer_id:stage.reviewer_id,reviewer_candidate_sha256:stage.reviewer_candidate_sha256,source_id:report.id,source_revision:report.revision,reason};
 };
 const submit=async(values,form)=>{
  if(committing)return false;
  if(needsRead)return reread(form);
  if(committed){if(saved)await saved(committed,form);return committed;}
  const input=fields(values),next=JSON.stringify(input);
  try{
   if(!preview||signature!==next){
    const turn=++sequence;preview=null;signature='';
    const result=await action('cycle.stage_final_revision_preview',input);
    if(!form.isConnected||turn!==sequence)return false;
    if(JSON.stringify(fields(valuesFromForm(form)))!==next){invalidate(form);return false;}
    form.querySelector('#final-revision-preview').innerHTML=finalRevisionPreview(result);
    form.querySelector('button[type=submit]').textContent=result.ready?'提交协调者最终稿修订':'重新预览最终稿修订';
    if(result.ready){if(!result.pin)throw new Error('预览缺少版本校验，尚未提交。');preview=result;signature=next;}return false;
   }
   committing=true;
   const result=await action('cycle.stage_final_revision',{...input,pin:preview.pin,approved:true,request_key:requestKey});committed=result;
   if(saved)await saved(result,form);return result;
  }catch(error){
   if(committed){
    if(form.isConnected){form.querySelector('button[type=submit]').textContent='已保存，重读当前协作';form.querySelector('#final-revision-status').textContent='最终稿修订已保存。再次点击只重读状态；若要另改来源，请重新打开交接入口。';}
    throw new Error('最终稿修订已保存，但刷新当前协作失败：'+error.message);
   }
   if(error.status===409||error.status===403||error.code==='cancelled'){
    invalidate(form);needsRead=true;
    try{await reread(form);}catch(readError){if(form.isConnected)form.querySelector('#final-revision-status').textContent='重读当前状态失败，草稿保留：'+readError.message;}
   }else if(error.status){invalidate(form);}
   throw error;
  }finally{committing=false;}
 };
 submit.invalidate=invalidate;return submit;
}
