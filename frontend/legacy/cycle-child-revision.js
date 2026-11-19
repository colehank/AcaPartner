import {esc,button,field,list,pretty} from './ui.js';

export function canOpenFailedPlanner(task){
 return task?.status==='failed'&&task.payload?.cycle_role==='planner'&&!!task.payload?.cycle_parent&&task.result?.failure_code==='invalid_model_output';
}

function allowance(value){
 return `<p>原规划剩余：${esc(value.invocations)} 次 CLI 调用、${esc(Number(value.seconds).toFixed(1))} 秒、${esc(value.attempts)} 次执行尝试。CLI 内部模型请求数和实际账单未知。</p>`;
}

export function failedChildRevisionPanel(view,child){
 const entry=child.failed_child_revision;
 if(!entry)return '';
 return `<section class="notice"><strong>规划输出格式未通过</strong><p>可给原规划补充修订指导。旧被拒候选和原生记录保留。</p>${entry.allowed?allowance(entry.remaining)+button('核对并修订原规划','cycle-revise-failed-child',{id:view.task.id,child:child.id},'button small'):`<p>${esc(entry.reason)}</p>`}</section>`;
}

export function failedChildRevisionFields(child){
 const refs=list(child.task?.payload?.context?.materials).map(ref=>ref.id);
 const guidance=`请修正原规划的输出合同，保持原目标、分工范围和科学边界。cycle_contract.delegates[*].material_ids 只能选择冻结材料 ID：${refs.join('、')}；不得将字段名或其他字符串当作材料 ID。返回完整候选 JSON。`;
 return `<p>先核对原任务、当前回答与指导，再明确使用原剩余额度。提交会恢复当前规划交接并接续同一任务及原生会话；后续协作仍受原合同限制。不会增加额度、替换任务、改写被拒候选或恢复用户暂停的协作。</p>${allowance(child.failed_child_revision.remaining)}${field('给原规划的修订指导','guidance',guidance,'textarea','required maxlength="8000" rows="6"')}<div id="child-revision-preview"><p>尚未预览，未授权新的模型调用。</p></div>`;
}

export function failedChildRevisionPreview(result){
 return `<div class="notice"><strong>原会话与当前输入已核对。再次点击将使用原剩余额度修订。</strong>${allowance(result.remaining)}<p>${esc(result.failure||'规划输出格式失败')}</p><p>原规划：${esc(result.child_id)}；原生会话：${esc(result.native_session_id)}</p></div><h4>本次追加的指导</h4><p>${esc(result.guidance)}</p><h4>已保存的指导与回答</h4>${list(result.input_guidance).map(g=>`<p>指导 ${esc(g.seq)}：${esc(g.data?.text)}</p>`).join('')||'<p>无既有指导。</p>'}${list(result.input_decisions).map(q=>`<p>${esc(q.title)} · 修订 ${esc(q.revision)}：${esc(q.content?.answer)}</p>`).join('')||'<p>无当前回答。</p>'}<details><summary>原被拒候选（只读）</summary><pre>${esc(pretty(result.rejected_candidate))}</pre></details>`;
}

export function failedChildRevisionSubmission({id,childId,action,requestKey,saved,valuesFromForm=form=>Object.fromEntries(new FormData(form))}){
 let preview=null,signature='',busy=false,commit=null,done=null;
 const setText=(form,text)=>{if(form.isConnected)form.querySelector('#child-revision-preview').textContent=text;};
 const invalidate=form=>{
  preview=null;signature='';
  if(form.isConnected)form.querySelector('button[type=submit]').textContent='重新核对本次修订';
 };
 return async(values,form)=>{
  if(busy)return false;
  if(done){if(saved)await saved(done);return done;}
  const guidance=String(values.guidance||'').trim();
  if(!guidance||guidance.length>8000)throw new Error('请填写 1–8000 字的具体修订指导。');
  busy=true;
  try{
   if(commit){
    // A lost response may already have committed. Retry precisely that request
    // with its stable key, even if a textarea was edited while the network hung.
    done=await action('cycle.revise_failed_child',commit);
    if(saved)await saved(done);
    return done;
   }
   if(!preview||signature!==guidance){
    const result=await action('cycle.revise_failed_child_preview',{id,child_id:childId,guidance});
    if(!form.isConnected)return false;
    if(String(valuesFromForm(form).guidance||'').trim()!==guidance){invalidate(form);setText(form,'指导已编辑，旧预览失效；请重新核对。');return false;}
    if(!result.ready||!result.pin)throw new Error('服务端未确认可修订，未提交。');
    preview=result;signature=guidance;
    form.querySelector('#child-revision-preview').innerHTML=failedChildRevisionPreview(result);
    form.querySelector('button[type=submit]').textContent='使用原剩余额度修订并接续';
    return false;
   }
   commit={id,child_id:childId,guidance,pin:preview.pin,approved:true,request_key:requestKey};
   done=await action('cycle.revise_failed_child',commit);
   if(saved)await saved(done);
   return done;
  }catch(error){
   if(done){setText(form,'修订已登记，刷新失败；再次点击只刷新当前状态。');throw error;}
   if(error.status){commit=null;invalidate(form);setText(form,`尚未提交修订：${error.message}。草稿已保留；重新核对后才能提交。`);}
   else if(commit){setText(form,'提交结果暂未确认。再次点击只核对同一次提交，不重复授权；如需改指导，请先核对当前任务状态。');}
   throw error;
  }finally{busy=false;}
 };
}
