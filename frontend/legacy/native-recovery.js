import {esc,button,pretty} from './ui.js';

export function recoveryEntry(task){
 const p=task?.payload||{};
 return p.cycle_role==='delegate'&&p.cycle_provider_route==='deepseek_harness'&&['failed','waiting_input','waiting_resource','waiting_authorization'].includes(task.status)
  ? button('预览已登记候选的零调用接回','task-recover-preview',{id:task.id},'button small'):'';
}
export function recoveryPreview(value){
 const fault=value.syntax_error,change=value.changes||[];
 return `<p>此处只接回同一原生会话已登记的候选。原文件、模型归属和已用额度保留；科学论断仍需独立审查。提交不会继续父任务。</p><p><strong>${value.ready?'可以提交为待审候选':'当前不能提交：'+esc(value.validation_error?.message||'核对失败')}</strong></p>${fault?`<h4>原始 JSON 故障</h4><pre>${esc(pretty(fault))}</pre>`:''}<details open><summary>精确改动</summary><pre>${esc(pretty(change))}</pre><pre>${esc(value.diff||'尚未选择修订；字节未改变。')}</pre></details><details><summary>完整原始候选（UTF-8）</summary><pre>${esc(value.raw_candidate_text)}</pre></details><details open><summary>${change.length?'修复后候选':'登记候选'}（完整 JSON 文本）</summary><pre>${esc(value.candidate_text)}</pre></details>${value.bookkeeping_tail?`<details><summary>写入后的已核验动作（不作为科学证据）</summary><pre>${esc(pretty(value.bookkeeping_tail))}</pre></details>`:''}${value.suggested_revision?`<p>可预览的修复仅删除字节偏移 ${esc(value.suggested_revision.byte_offset)} 的未匹配字符 ${esc(value.suggested_revision.expected)}。</p>`:''}<details><summary>原生来源与用量</summary><pre>${esc(pretty({pin:value.pin,accounting:value.provider_accounting,new_model_requests:value.new_model_requests}))}</pre></details>`;
}
export function recoverySubmission({id,initial,action,requestKey,saved}){
 let pinned=null;
 const submit=async(values,form)=>{
  const reason=String(values.reason||'').trim();if(!reason)throw new Error('请填写具体理由。');
  const revision=initial.suggested_revision?{...initial.suggested_revision,reason}:{kind:'none'};
  const key=JSON.stringify({reason,revision});
  if(pinned?.key===key){
   let result;
   try {result=await action('task.recover_candidate',{id,revision,reason,pin:pinned.preview.pin,approved:true,request_key:requestKey});}
   catch(error){
    // Only a definitive input/state rejection invalidates approval. A lost
    // response may follow a committed recovery: retain the exact idempotent
    // request on transport errors, unknown responses and server failures.
    if(error?.status===409&&['conflict','candidate_revision_required','candidate_checkpoint_invalid','native_accounting_integrity','integrity','cancelled'].includes(error.code)){
     submit.invalidate(form);
     if(form.isConnected)form.querySelector('[data-recovery-preview]').innerHTML='<p class="notice">本次预览已失效。理由已保留，请重新预览当前候选与差异后再确认。</p>';
    }
    throw error;
   }
   if(form.isConnected)await saved(result,form);return false;
  }
  const preview=await action('task.recover_candidate_preview',{id,revision});if(!form.isConnected)return false;
  form.querySelector('[data-recovery-preview]').innerHTML=recoveryPreview(preview);
  const control=form.querySelector('[type="submit"]');
  pinned=preview.ready?{key,preview}:null;
  control.textContent=preview.ready?'确认接回这份候选供独立审查':'重新预览';
  return false;
 };
 submit.invalidate=form=>{pinned=null;const control=form.querySelector('[type="submit"]');if(control)control.textContent='预览接回与精确差异';};
 return submit;
}
