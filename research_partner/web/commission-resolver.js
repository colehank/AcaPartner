import {esc,field,select,kinds} from './ui.js';

export function additionalMaterialRefs(value){
 return String(value||'').split(/[\n,]+/).map(x=>x.trim()).filter(Boolean).map(line=>{
  const match=line.match(/^([A-Za-z][A-Za-z0-9_-]*)(?:\s*(?:@|r)\s*([1-9][0-9]*))?$/);
  if(!match)throw new Error('补充来源使用成果 ID，可加 @修订号；名称或领域线索可直接写进研究目的。');
  return {id:match[1],...(match[2]?{revision:Number(match[2])}:{})};
 });
}
export function resolutionRequest(values,{projectId,target}={}){
 return {request:values.objective,material_mode:'auto',...(projectId?{project_id:projectId}:{}),...(target?{object_id:target.id}:{}),
  ...(values.selected_project_id?{selected_project_id:values.selected_project_id}:{}),additional_materials:additionalMaterialRefs(values.additional_materials),
  ...(values.literature_mode==='disabled'?{literature_plan:false}:String(values.literature_query||'').trim()?{literature_plan:{source:'crossref',query:values.literature_query.trim(),limit:Number(values.literature_limit)||3}}:{})};
}
export function resolutionSignature(request){return JSON.stringify(request);}
export function chosenMaterialRefs(form){return [...form.querySelectorAll('[name=resolved_material]:checked')].map(el=>({id:el.dataset.id,revision:Number(el.dataset.revision)}));}
export function acquisitionFields(){return `<fieldset><legend>有界文献获取</legend>${select('联网检索','literature_mode',[['auto','仅研究目的明确要求时检索'],['disabled','本次不检索']],'auto')}${field('覆盖自动查询词（可留空）','literature_query','','text','maxlength="600"')}${field('自定查询的最多记录数','literature_limit','3','number','min="1" max="8"')}<p class="hint">单条 Crossref 查询，最多 1 次 HTTP、1 MiB 响应、20 秒（计入总时限），只读取元数据和可用摘要。预览不联网；提交才执行。无全文获取、任意 URL 或自动重试。</p></fieldset>`;}
export function acquisitionPanel(plan,receipt){
 if(!plan)return '';
 return `<section class="panel"><h4>本次文献获取范围</h4><p>Crossref：${esc(plan.query)}</p><p>最多 ${esc(plan.limit)} 条；${esc(plan.max_requests)} 次 HTTP；${esc(plan.max_bytes)} bytes；${esc(plan.timeout_seconds)} 秒（计入任务总额）。</p><p class="hint">${esc(plan.scope_note)} 读取范围：元数据与实际提供的摘要。费用未核定。</p>${receipt?`<p>状态：${esc(receipt.state)}；已预留 ${esc(receipt.requests_reserved)} 次 HTTP；读取 ${esc(receipt.bytes_read??'未知')} bytes；实测 ${esc(receipt.elapsed_seconds??'未知')} 秒。</p>${receipt.error?`<p class="notice">${esc(receipt.error)}</p>`:''}<p class="hint">响应 SHA：${esc(receipt.raw_response_sha256||'尚无成功回执')}。状态不明不会自动重发。</p>`:''}</section>`;
}
export function resolutionPanel(plan){
 const options=[['','采用当前解析建议'],...(plan.project_candidates||[]).map(p=>[p.id,p.title+' · '+p.reason])];
 return `${plan.project?`<div class="notice"><strong>所属项目：${esc(plan.project.title)}</strong><p>项目修订 ${esc(plan.project.revision)}。只使用已授权来源；预览不启动模型。</p></div>`:'<div class="notice">尚需明确所属项目，不会自动选第一个项目。</div>'}${select('明确选择其他匹配项目（改变后先重新预览）','selected_project_id',options)}
 ${acquisitionPanel(plan.literature_plan)}
 ${(plan.ambiguities||[]).map(a=>`<p class="notice warning">${esc(a.label)}</p>`).join('')}
 <fieldset><legend>实际采用材料 · 可取消或选择同名来源</legend>${(plan.materials||[]).map(m=>`<label class="check-field"><input type="checkbox" name="resolved_material" data-id="${esc(m.id)}" data-revision="${esc(m.revision)}" ${m.selected?'checked':''}><span><strong>${esc(m.title)}</strong> · ${esc(kinds[m.kind]||m.kind)} r${esc(m.revision)}<br><small>${esc(m.reason)} · ${esc(m.bytes)} bytes · ${esc(m.id)}</small>${m.current_revision!==m.revision?`<br><small>采用历史修订 ${esc(m.revision)}，当前为 ${esc(m.current_revision)}；不会静默更新。</small>`:''}</span></label>`).join('')||'<p class="hint">没有自动采用材料。可补充来源，或明确提交无证据材料的概念性委托。</p>'}</fieldset>
 <p class="hint">完整材料最多 ${esc(plan.limits?.max_materials)} 份、${esc(plan.limits?.max_bytes)} UTF-8 字节。不截断科学正文；提交时冻结实际采用修订。</p>
 ${(plan.gaps||[]).map(x=>`<p class="hint">${esc(x)}</p>`).join('')}
 ${(plan.excluded||[]).length?`<details><summary>未纳入材料及原因</summary>${plan.excluded.map(x=>`<p>${esc(x.id||'')} ${esc(x.revision?'r'+x.revision:'')} · ${esc(x.reason)}</p>`).join('')}</details>`:''}`;
}
export function cycleFields(providers){
 const available=(providers||[]).filter(p=>p.available&&p.authorized),main=available[0]?.id||'',delegate=available[1]?.id||main;
 const options=[['','选择已配置并授权的路线'],...available.map(p=>[p.id,p.name||p.id])];
 return `<fieldset><legend>有限协作分工</legend>${[['planner','规划'],['delegate','具体工作'],['reviewer','独立复核'],['integrator','整合'],['final_reviewer','最终复核']].map(([key,label])=>select(label,'role_'+key,options,key==='delegate'?delegate:main)).join('')}<p class="hint">同一路线的不同上下文不是跨模型共识；来源、修订与复核身份会记录。点击提交才启动协作，角色选择不扩大科学或工具权限。</p><div class="field-grid">${field('合计模型调用上限','cycle_calls',30,'number','min="1" max="100" step="1" required')}${field('合计执行秒数','cycle_seconds',900,'number','min="1" max="7200" required')}${field('步骤上限','cycle_steps',16,'number','min="1" max="24" step="1" required')}${field('返工轮数上限','cycle_rework',1,'number','min="0" max="1" step="1" required')}${field('单步骤调用上限','child_calls',4,'number','min="1" max="10" step="1" required')}${field('单步骤秒数','child_seconds',120,'number','min="1" max="900" required')}</div></fieldset>`;
}
export function cycleParameters(values){
 const roles=Object.fromEntries(['planner','delegate','reviewer','integrator','final_reviewer'].map(k=>[k,values['role_'+k]]));
 if(Object.values(roles).some(x=>!x))throw new Error('请为每个协作角色选择已授权模型路线。');
 const limits={max_model_calls:Number(values.cycle_calls),timeout_seconds:Number(values.cycle_seconds),max_steps:Number(values.cycle_steps),max_rework:Number(values.cycle_rework),child_max_model_calls:Number(values.child_calls),child_timeout_seconds:Number(values.child_seconds)};
 if(Object.values(limits).some(x=>!Number.isFinite(x)))throw new Error('协作额度必须是有限数值。');
 return {roles,limits};
}
