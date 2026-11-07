import {recoveryEntry} from './native-recovery.js';
import {failedChildRevisionPanel} from './cycle-child-revision.js';
import {esc,button,date,list,pretty,status} from './ui.js';
import {acquisitionPanel} from './commission-resolver.js';
import {documentMarkdown} from './document-markdown.js';
import {proposalView} from './graph-review.js';
import {revisionPanel} from './cycle-handoff.js';

const roles={acquisition:'文献获取',planner:'研究分工',delegate:'分派研究',reviewer:'独立审查',integrator:'整合成果',final_reviewer:'成稿复审'};
export const phases={acquiring:'获取有限文献',new:'准备分工',planning:'正在规划',delegating:'子任务执行',reviewing:'审查返回',reworking:'按意见返工',integrating:'整合成果',final_reviewing:'审查整合稿',final_revision_staged:'最终稿修订已登记，等待独立复审',complete:'本轮形成候选与审查记录',handoff:'等待接手'};
const seconds=value=>Number.isFinite(Number(value))?Number(value).toFixed(1):'未记录';

export function timeAccounting(value){
 if(!value||!Object.hasOwn(value,'settled_elapsed_seconds'))return '<span>已结算实际耗时未记录；预算占用不能当作执行时长。</span>';
 return `<span>已结算实际耗时 ${seconds(value.settled_elapsed_seconds)} 秒；预算扣留 ${seconds(value.budget_charged_seconds)} 秒；在途预留 ${seconds(value.reserved_seconds)} 秒；恢复后或旧账本实际时长未知的扣留 ${seconds(value.uncertain_charged_seconds)} 秒。</span>`;
}

function candidateView(candidate){
 if(!candidate)return '<p class="hint">尚无保存的候选；等待与失败不算研究产出。</p>';
 const content=candidate.content||{};
 return `<h4>${esc(candidate.title||'保存的候选')}</h4><div class="document-reading">${list(content.blocks).map(b=>documentMarkdown(b.text||'',content.resources||{})).join('')||'<p class="hint">本候选没有文稿段落。</p>'}</div>${list(content.claims).length?`<details><summary>论断、来源与限制</summary>${list(content.claims).map(c=>`<p>${esc(c.text||'')}</p><p class="hint">${esc(c.limitation||'')} ${esc((c.evidence_ids||[]).join(' · '))}</p>`).join('')}</details>`:''}<details><summary>此候选的身份</summary><pre>${esc(pretty({task_id:candidate.task_id,candidate_sha256:candidate.candidate_sha256}))}</pre></details>`;
}

function inputHandoff(view){
 const current=view.parent_inputs_current||{decisions:[],guidance:[]},integrated=view.integration_inputs;
 if(!list(current.decisions).length&&!list(current.guidance).length&&!integrated)return '';
 const describe=input=>`裁决：${list(input.decisions).map(d=>`${esc(d.id)} · 修订 ${esc(d.revision)}`).join('；')||'无'}；指导记录：${list(input.guidance).map(esc).join('、')||'无'}`;
 return `<section class="panel"><h4>本轮意见的交接</h4><p>当前保存：${describe(current)}</p>${integrated?`<p>进入整合提示：${describe(integrated)}</p>`:'<p>尚未启动整合，已保存意见将在相应阶段递交。</p>'}${integrated&&view.unincorporated_parent_inputs?'<div class="notice">有新意见尚未进入这份整合稿，需安排后续修订。</div>':''}<p class="hint">${esc(view.handoff_meaning||'输入记录说明何时递交；是否充分采用需结合产物和审查判断。')}</p></section>`;
}

export function cycleDetail(view){
 const task=view.task||{},state=view.cycle||{},limits=task.payload?.cycle_config?.limits||{},used=view.actual_consumption||{},children=list(view.children);
 return `<div class="section-heading"><h3>${esc(task.payload?.request||task.id)}</h3>${status(task.status)}</div><p><strong>${esc(phases[state.phase]||state.phase||'尚未开始')}</strong> · 返工 ${esc(state.round??0)} / ${esc(limits.max_rework??0)}</p><p class="hint">审查记录与用户验收分别保留。本轮停止后不会自行启动新的付费循环。</p>${state.last_failure?`<div class="notice">${esc(state.last_failure.message)}<small> · ${esc(state.last_failure.phase)}</small></div>`:''}<section class="panel"><h4>执行范围与资源</h4><p>已分配调用额度 ${esc(state.reserved_calls??0)} / ${esc(limits.max_model_calls??'未记录')}；时限 ${seconds(state.reserved_seconds)} / ${seconds(limits.timeout_seconds)} 秒；步骤 ${esc(state.steps_used??0)} / ${esc(limits.max_steps??'未记录')}。</p><p>已记录 Codex CLI 调用 ${esc(used.codex_cli_invocations??0)}，DeepSeek Harness 调用 ${esc(used.deepseek_harness_invocations??0)}。${timeAccounting(used)}</p><p class="hint">${esc(view.accounting_note||'')} 实际账单费用未在这里结算。</p><details><summary>冻结的研究约定与材料选择</summary><pre>${esc(pretty({conventions:task.payload?.context?.working_conventions,material_resolution:task.payload?.context?.material_resolution,materials:task.payload?.context?.materials}))}</pre></details></section>${acquisitionPanel(task.payload?.literature_plan,view.literature_acquisition)}${inputHandoff(view)}${state.plan?`<section class="panel"><h4>已形成的研究分工</h4><p>${esc(state.plan.question)}</p>${list(state.plan.delegates).map(d=>`<p><strong>${esc(d.id)}</strong> · ${esc(d.request)}</p><small>${esc((d.material_ids||[]).join(' · '))}</small>`).join('')}</section>`:''}<section><h4>分派、返回与指导</h4>${children.map(child=>{
  const t=child.task||{},contract=child.contract;
  return `<article class="panel"><div class="section-heading"><h4>${esc(roles[child.role]||child.role)} · ${esc(t.payload?.provider_id||child.route)}</h4>${status(t.status)}</div><p>${esc(t.payload?.request||'')}</p><small>${esc(child.id)} · ${date(t.updated_at)}</small><p class="hint">${timeAccounting(child.time_accounting)}</p><small></small>${contract?.phase==='review'?`<div class="notice"><strong>${esc({accept:'本轮可用，仍保留审查边界',rework:'需要具体修订',handoff:'需要接手'}[contract.verdict]||contract.verdict)}</strong><p>${esc(contract.assessment)}</p>${list(contract.findings).map(f=>`<p><strong>${esc(f.target_task_id)}</strong>：${esc(f.issue)}<br>指导：${esc(f.instruction)}</p>`).join('')}</div>`:''}${list(child.guidance).length?`<details open><summary>实际保存的指导</summary>${list(child.guidance).map(g=>`<p>${esc(g.text)}<small> · ${esc(g.source)} · 记录 ${esc(g.sequence)}</small></p>`).join('')}</details>`:''}<details ${child.role==='integrator'?'open':''}><summary>查看当前候选正文</summary>${child.candidate?candidateView(child.candidate):t.result?.object_id?`<p>已保存整合成果 ${esc(t.result.object_id)} · 修订 ${esc(t.result.revision)}。此记录保留当时版本。</p>${button('查看这次保存的版本','open-reference',{id:t.result.object_id,revision:t.result.revision},'button small')}`:candidateView(null)}</details>${list(child.candidate_history).length>1?`<details><summary>保留的历次候选（${child.candidate_history.length}）</summary>${child.candidate_history.map(candidateView).join('')}</details>`:''}${failedChildRevisionPanel(view,child)}${revisionPanel(view,child)}${recoveryEntry(t)}${button('该子任务的执行记录','task-detail',{id:child.id},'button small subtle')}</article>`;
 }).join('')||'<p class="hint">尚未分派子任务。</p>'}</section>${state.final_source?`<section class="panel"><h4>整合产物与审查</h4><p>采用成果 ${esc(state.final_source.id)} · 修订 ${esc(state.final_source.revision)}</p>${button('查看本轮采用版本','open-reference',{id:state.final_source.id,revision:state.final_source.revision},'button primary')}<p class="hint">审查仅覆盖这份采用版本；之后的编辑有独立修订记录。</p><details><summary>对应版本的最终审查</summary><pre>${esc(pretty(state.final_review||{status:'等待审查'}))}</pre></details></section>`:''}<section class="panel"><h4>本轮图谱增量与采用</h4>${list(view.graph_proposals).map(p=>proposalView(p)).join('')||'<p class="hint">本轮没有已登记的图谱增量；无提案不等于执行失败。</p>'}${button('查看项目图谱与关系历史','graph-review',{project:task.project_id||''},'button small')}</section><details><summary>实际阶段记录</summary>${list(state.history).map(h=>`<p>${date(h.at)} · ${esc(phases[h.phase]||h.phase)} · ${esc(h.status)}${h.error?' · '+esc(h.error):''}</p>`).join('')}</details>`;
}
