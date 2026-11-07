import {esc,pretty,button} from './ui.js';

const array=value=>Array.isArray(value)?value:[];
const axes=[['implementation','实现'],['engineering','工程验证'],['human','用户验收']];
const names={passed:'已记录通过',partial:'部分完成',pending_independent_review:'待独立审查',pending_user_trial:'待用户试用',unverified:'未验证',missing:'缺失',failed:'失败',blocked:'受阻',skipped:'跳过',not_implemented:'未实现'};
const label=value=>names[value]||value||'未记录';
const details=(id,title,body,opened)=>`<details data-development-detail="${esc(id)}" ${opened.has(id)?'open':''}><summary>${title}</summary>${body}</details>`;

// Compare dated observations, never unchecked current files or authority.
export function developmentVerificationBinding(data={}){
 const observed=data.verification?.last_verification,result=observed?.result;if(!result)return null;
 const checkedState=result.recorded_state_sha256,currentState=data.recorded_state_sha256;
 const source=data.source_verification?.last_verification,checkedSource=result.gate?.source?.code_digest;
 const sourceError=data.source_verification?.last_error,sourceFailed=sourceError&&(!source||Date.parse(sourceError.finished_at)>=Date.parse(source.verified_at));
 const newerSource=!sourceFailed&&source&&Number.isFinite(Date.parse(source.verified_at))&&Date.parse(source.verified_at)>=Date.parse(observed.verified_at);
 const sourceDigest=newerSource?source.result?.code_digest:null;
 const state=checkedState&&currentState?(checkedState===currentState?'matched':'mismatch'):'unknown';
 const sourceRelation=checkedSource&&sourceDigest?(checkedSource===sourceDigest?'matched_observation':'mismatch'):'unknown';
 const error=data.verification?.last_error,failedLater=error&&Date.parse(error.finished_at)>=Date.parse(observed.verified_at);
 return {verified_at:observed.verified_at,recorded_state_sha256:checkedState,current_recorded_state_sha256:currentState,
  source_digest:checkedSource,source_observed_at:newerSource?source.verified_at:null,latest_source_digest:sourceDigest,
  state,source:sourceRelation,source_error:sourceFailed?sourceError:null,latest_attempt_failed:Boolean(failedLater),
  historical:state==='mismatch'||sourceRelation==='mismatch'||Boolean(failedLater),authorization:false,current_state:'unknown'};
}
function bindingText(binding){
 const state=binding.state==='matched'?'记录版本与当前记录一致':binding.state==='mismatch'?'记录版本不匹配：这是历史校验':'记录版本无法比较';
 const source=binding.source==='matched_observation'?'源码与最近源码观察一致（当前仍未检查）':binding.source==='mismatch'?'源码版本不匹配：这是历史校验':'当前源码尚无更新的可比较观察';
 return `<p class="hint" data-verification-binding>${esc(binding.historical?'历史校验':'最近完成的校验观察')} · ${esc(binding.verified_at||'时间未记录')}<br>${esc(state)} · ${esc(source)}${binding.source_error?`<br>最近源码观察失败：${esc(binding.source_error.type)} · ${esc(binding.source_error.finished_at)}；源码当前状态未知。`:''}${binding.latest_attempt_failed?'<br>后续完整校验失败，保留本次历史结果。':''}<br>校验记录 SHA：<code style="overflow-wrap:anywhere">${esc(binding.recorded_state_sha256||'未记录')}</code><br>校验源码 SHA：<code style="overflow-wrap:anywhere">${esc(binding.source_digest||'未记录')}</code>${binding.source_observed_at?`<br>源码观察时间：${esc(binding.source_observed_at)}`:''}<br>这次观察不代表当前通过，也不授予执行许可。</p>`;
}
function checkedAxis(value,id,opened,binding){
 if(!value||!binding)return '<p class="hint">该轴尚无完成的校验观察。</p>';
 return `<section data-axis-last-verification><h4>${binding.historical?'历史完整校验':'最近完整校验'}：${value.gate_satisfied===true?'该次门槛满足（不是当前结论）':value.gate_satisfied===false?'该次门槛未满足':'该次结论未知'}</h4>${bindingText(binding)}${array(value.gate_reasons).length?`<ul data-axis-verification-errors>${value.gate_reasons.map(error=>`<li>${esc(error)}</li>`).join('')}</ul>`:''}<h4>该次校验的正式证据（${array(value.evidence).length}）</h4>${array(value.evidence).map((r,i)=>receipt(r,`${id}:checked:formal:${i}`,opened,{formal:true,binding})).join('')||'<p class="hint">该次没有正式证据。</p>'}<h4>该次校验的限定证据（${array(value.bounded_evidence).length}）</h4>${array(value.bounded_evidence).map((r,i)=>receipt(r,`${id}:checked:bounded:${i}`,opened,{binding})).join('')||'<p class="hint">该次没有限定证据。</p>'}</section>`;
}

function receipt(record,id,opened,{formal=false,binding=null}={}){
 const check=record.reference_check,scope=record.scope||record.observation||'未记录支持范围',source=record.source?.code_digest;
 const errors=[...array(record.validation_errors),...array(check?.errors)];
 const result=binding?(errors.length?'该次校验未通过':check?.status==='matched'?'该次引用哈希相符':'该次校验未列出错误'):record.validation_status==='pending'||check?.status==='pending'?'待重新校验':check?check.status==='matched'?'引用文件哈希相符':'引用文件缺失、变化或路径无效':array(record.validation_errors).length?'当前证据校验未通过':'按当前门槛校验';
 return details(id,`${esc(record.receipt_id||record.kind||'证据记录')} · ${esc(binding?'最近校验时的证据':formal?'正式验收记录':'限定观察')} · ${esc(result)}`,
  `${binding?bindingText(binding):''}${errors.length?`<ul data-receipt-verification-errors>${errors.map(error=>`<li>${esc(error)}</li>`).join('')}</ul>`:''}<p>${esc(scope)}</p><p>${formal?'是否满足当前门槛见该轴状态。':'此观察不构成全范围验收。'} ${source?`记录代码：<code>${esc(source)}</code>`:'未记录可比较的代码摘要；以原回执范围为限。'}</p>${record.path?`<p>引用：<code style="overflow-wrap:anywhere">${esc(record.path)}</code><br>SHA256：<code style="overflow-wrap:anywhere">${esc(record.sha256||'未记录')}</code></p>`:''}<pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(pretty(record))}</pre>`,opened);
}

function row(item,opened,checked,binding){
 const id=item.id,summary=axes.map(([key,title])=>`${title}：${label(item.axes?.[key]?.status)}`).join(' · ');
 const axisHTML=axes.map(([key,title])=>{const value=item.axes?.[key]||{};return details(`${id}:${key}`,`${title} · ${esc(label(value.status))} · ${value.gate_satisfied==null?'当前门槛待校验':value.gate_satisfied?'当前门槛满足':'当前门槛未满足'}`,
  `${checkedAxis(checked?.axes?.[key],`${id}:${key}`,opened,binding)}<h4>当前记录（尚待校验）</h4><p>${esc(value.evidence_scope||'尚未记录证据支持范围。')}</p>${array(value.gate_reasons).length?`<ul>${value.gate_reasons.map(r=>`<li>${esc(r)}</li>`).join('')}</ul>`:''}<h4>正式验收证据（${array(value.evidence).length}）</h4>${array(value.evidence).map((r,i)=>receipt(r,`${id}:${key}:formal:${i}`,opened,{formal:true})).join('')||'<p class="hint">没有正式验收回执。</p>'}<h4>限定证据（${array(value.bounded_evidence).length}）</h4>${array(value.bounded_evidence).map((r,i)=>receipt(r,`${id}:${key}:bounded:${i}`,opened)).join('')||'<p class="hint">没有限定证据。</p>'}`,opened);}).join('');
 const blockers=array(item.blockers).map(b=>`<li><strong>${esc(b.id)}</strong> · ${b.active===true?'当前有效':b.active===false?'已解除':'状态未记录'}<br>${esc(b.reason||'未记录原因')}</li>`).join('');
 const actions=array(item.next_actions).map(a=>`<li>${esc(a.action==='supply_current_axis_evidence'?`补齐${axes.find(([key])=>key===a.axis)?.[1]||a.axis}的当前有效证据`:a.action==='refresh_current_evidence_verification'?'重新校验当前证据':a.action==='restore_required_item'?'恢复固定范围中缺失的状态项':a.action==='repair_scope_integrity'?'修复范围完整性':a.action)}${array(a.reasons).length?`<small> · ${esc(a.reasons.join('；'))}</small>`:''}</li>`).join('');
 const index=item.recorded_index;
 return `<details id="development-${esc(encodeURIComponent(id))}" data-development-item="${esc(id)}" data-development-detail="${esc(id)}" ${opened.has(id)?'open':''}><summary><strong>${esc(id)} · ${esc(item.title)}</strong><br><small>${esc(summary)}${item.present===false?' · 必需状态项缺失':''}</small>${checked&&binding?`<br><small>${binding.historical?'历史校验':'最近校验'}：${esc(binding.verified_at)} · ${axes.some(([key])=>checked.axes?.[key]?.gate_satisfied===false)?'含未满足项，展开查看具体原因':'查看各轴的限定结果'}${binding.historical?' · 版本不匹配或后续校验失败':''}</small>`:''}</summary><div style="padding:12px 16px">${axisHTML}<h4>阻塞与下一动作</h4>${blockers?`<ul>${blockers}</ul>`:'<p class="hint">未记录条目阻塞；执行仍受全局停止、权限和预算门槛约束。</p>'}${actions?`<ul>${actions}</ul>`:'<p class="hint">当前门槛未列出本条目的证据缺口。</p>'}${array(item.limitations).length?`<p>限制：${esc(item.limitations.map(v=>typeof v==='string'?v:pretty(v)).join('；'))}</p>`:''}${array(item.related_units).length?details(`${id}:units`,'已关联开发单元（原状态保留）',`<pre style="white-space:pre-wrap">${esc(pretty(item.related_units))}</pre>`,opened):''}${array(item.observations).length?details(`${id}:observations`,'历史观察',item.observations.map((r,i)=>receipt(r,`${id}:observation:${i}`,opened)).join(''),opened):''}${index?details(`${id}:index`,'已记录索引与原下一步（历史范围，非当前动作）',`<p>索引中的 next 仅反映该文件所绑定的版本。当前缺口以上方门槛和限定回执为准。</p><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(pretty(index))}</pre>`,opened):''}</div></details>`;
}

// View-local preferences survive periodic /api/state refreshes. No editor,
// development state or gate is mutated; all evidence comes from the response.
export function createDevelopmentView(){
 const opened=new Set();let query='',group='',selection='',boundRoot=null,restoreGoFocus=false,rechecking=false,recheckError='';
 const verifyButton=data=>data.can_verify===true?`<button type="button" class="button small" data-action="development-verify" ${rechecking?'disabled':''}>${rechecking?'完整重验中…':'完整重验'}</button>`:'';
 const verifyStatus=()=>`<p data-development-verification-status role="status" aria-live="polite">${rechecking?'完整重验进行中；可继续浏览和读取状态。':esc(recheckError)}</p>`;
 const matches=item=>(!group||item.group===group)&&`${item.id} ${item.title}`.toLocaleLowerCase().includes(query.toLocaleLowerCase().trim());
 function render(data={},implementation={},capabilities={}){
  // Capture focus before the caller replaces the rendered subtree. Restore only
  // this view's active command; never take focus from another view or editor.
  restoreGoFocus=Boolean(boundRoot && boundRoot.ownerDocument?.activeElement===boundRoot.querySelector('[data-development-go]'));
  if(!array(data.items).some(item=>item.id===selection))selection='';
  if(data.status==='owner_only')return '<h2>产品建设与实际能力</h2><p class="notice">开发证据仅向研究空间所有者开放。当前项目访问权限不包含开发状态。</p>';
  if(!Array.isArray(data.items))return `<h2>产品建设与实际能力</h2><p class="notice">开发状态暂不可用：${esc(data.message||data.status||'服务端尚未返回逐项状态')}。这不表示功能已通过验收。</p>${button('刷新状态','refresh',{},'button small')}${verifyButton(data)}${verifyStatus()}`;
  const scope=data.projection_scope||{},gate=data.gate||{},binding=developmentVerificationBinding(data),checked=new Map(array(data.verification?.last_verification?.result?.items).map(item=>[item.id,item]));
  return `<section data-development-view><div class="section-heading"><h2>产品建设与实际能力</h2><div class="button-group">${button('刷新状态','refresh',{},'button small')}${verifyButton(data)}</div></div>${verifyStatus()}${data.verification?.last_error?`<p class="notice">最近一次完整校验失败：${esc(data.verification.last_error.type)} · ${esc(data.verification.last_error.finished_at)}。下方保留此前完成的观察。</p>`:''}<p class="notice">实现、工程验证、用户验收分别记录。限定观察不替代正式验收；公开发布单独授权。</p><p>范围：${data.items.length} 项 / 应有 ${esc(scope.required_count)} 项 · 状态已记录 ${esc(scope.present_count)} 项<br>工程就绪：${gate.engineering_ready==null?'待校验':gate.engineering_ready?'是':'否'} · 用户产品验收：${gate.product_accepted==null?'待校验':gate.product_accepted?'是':'否'} · 公开发布：${gate.public_release==null?'待校验':gate.public_release?'是':'否'}<br>自动开发执行器：${esc(gate.decision||'未返回')} · ${esc(gate.reason||'')} · 接续许可：${gate.execution_permitted_now?'有':'无'}</p>${data.verification_mode==='pending'?`<p class="notice">当前源码、证据与依赖关系待完整校验；状态记录不代表当前通过。后台校验：${esc(data.verification?.status||'pending')} · 最近完成：${esc(data.verification?.last_verification?.verified_at||'尚无')}。执行前仍需完整门槛检查。</p>`:''}<p class="hint">这里的额度与停止状态仅约束自动开发执行器；科研任务和手动建设分别遵守各自授权与资源限制。</p>${array(scope.scope_errors).length?`<p class="notice">范围异常：${esc(scope.scope_errors.join('；'))}</p>`:''}<p class="hint">状态时间：${esc(scope.state_updated_at||'未记录')}<br>当前门槛代码：<code style="overflow-wrap:anywhere">${esc(scope.gate_source_digest||'未返回')}</code></p><div class="form-grid"><label class="field"><span>查找编号或标题</span><input type="search" data-development-query value="${esc(query)}" placeholder="C47 / 全类型 / S07:神经数据预处理"></label><label class="field"><span>条目类型</span><select data-development-group>${[['','全部'],['capabilities','能力 C01–C50'],['scenarios','场景 S01–S24'],['subcases','全部 8 个子场景']].map(([v,t])=>`<option value="${v}" ${v===group?'selected':''}>${t}</option>`).join('')}</select></label><label class="field"><span>直接定位并展开</span><select data-development-locate><option value="">选择条目</option>${data.items.map(x=>`<option value="${esc(x.id)}" ${x.id===selection?'selected':''}>${esc(x.id)} · ${esc(x.title)}</option>`).join('')}</select></label></div><button type="button" class="button small" data-development-go>定位并展开</button><p data-development-count aria-live="polite"></p><div data-development-rows>${data.items.map(x=>row(x,opened,checked.get(x.id),binding)).join('')}</div>${details('checkpoint','接续检查点与当前门槛',`<pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(pretty({current_checkpoint:data.current_checkpoint,handoff:data.handoff,runner:data.runner,gate,verification:data.verification}))}</pre>`,opened)}${details('implementation','服务运行实现与能力边界',`<pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(pretty({implementation,capabilities}))}</pre>`,opened)}</section>`;
 }
 function bind(root,data){
  boundRoot=root;
  if(!root){restoreGoFocus=false;return;}
  const rows=[...root.querySelectorAll('[data-development-item]')],items=new Map(array(data.items).map(x=>[x.id,x]));
  const filter=()=>{let visible=0;for(const el of rows){el.hidden=!matches(items.get(el.dataset.developmentItem)||{});if(!el.hidden)visible++;}root.querySelector('[data-development-count]').textContent=`显示 ${visible} / ${rows.length} 项`;};
  root.querySelector('[data-development-query]').addEventListener('input',e=>{query=e.target.value;filter();});
  root.querySelector('[data-development-group]').addEventListener('change',e=>{group=e.target.value;filter();});
  const locator=root.querySelector('[data-development-locate]'),go=root.querySelector('[data-development-go]');
  locator.value=items.has(selection)?selection:'';
  locator.addEventListener('change',()=>{selection=items.has(locator.value)?locator.value:'';});
  const locate=()=>{
   const el=rows.find(x=>x.dataset.developmentItem===locator.value);if(!el)return;
   query='';group='';root.querySelector('[data-development-query]').value='';root.querySelector('[data-development-group]').value='';filter();
   // Native selection stays put; only an explicit command moves to the row.
   el.open=true;opened.add(el.dataset.developmentItem);el.querySelector('summary')?.focus();el.scrollIntoView({block:'start',behavior:'instant'});
  };
  go.addEventListener('click',locate);
  root.addEventListener('toggle',e=>{const id=e.target.dataset.developmentDetail;if(id)e.target.open?opened.add(id):opened.delete(id);},true);
  filter();
  if(restoreGoFocus)go.focus({preventScroll:true});
  restoreGoFocus=false;
 }
 async function recheck({verify,refresh,redraw}){
  if(rechecking)return;
  rechecking=true;recheckError='';redraw();
  try{
   const result=await verify();
   if(result?.development?.status==='unavailable'||result?.development_source?.status==='unavailable')recheckError=`完整重验未完成：${result.development?.message||result.development_source?.message||'开发状态不可用'}`;
   await refresh();
  }catch(error){recheckError=`完整重验失败：${error.message||error}`;}
  finally{rechecking=false;redraw();}
 }
 return {render,bind,recheck};
}
