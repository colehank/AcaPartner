import {esc,button,empty,status,field,select,list} from './ui.js';

const content=q=>q.content||q;
export function questionScope(q){return q.question_view?.scope||content(q).scope||(content(q).blocking?'current_task':'optional');}
export function questionNeedsAttention(q){
  if(typeof q.question_view?.needs_attention==='boolean')return q.question_view.needs_attention;
  const c=content(q);return !q.archived&&!q.question_view?.source_stale&&questionScope(q)!=='historical'&&(c.status||'open')==='open';
}
export function questionSources(q){
  const view=q.question_view||{},sources=view.sources||[];
  return `<div class="reference-meta">${sources.length?sources.map(source=>source.kind==='artifact'?`${button(source.id,'open-reference',{id:source.id,revision:source.revision},'text-button')}<span>采用 r${esc(source.revision)}${source.current_revision!==undefined?` · 当前 r${esc(source.current_revision)}`:''}</span>`:`${button('只读查看候选','question-candidate',{id:q.id},'text-button')}<span>候选 ${esc((source.sha256||'').slice(0,12))}</span>`).join(''):'<span>来源版本未确定；保留历史记录，不推断为当前成果。</span>'}</div>${list(view.base_sources).length?`<p class="hint">生成时采用的底稿：${view.base_sources.map(ref=>`${esc(ref.id)} r${esc(ref.revision)}`).join('；')}。问题对应的保存成果见上方采用版本。</p>`:''}${view.source_stale?`<div class="notice warning">来源已经更新。这是旧版本的问题，不代表当前成果仍有相同结论或缺口。${view.source_reassessed?'已明确复核当前变化并保留原采用版本；再次变化将要求重新评估。':view.source_addressed?'后续候选已记录此问题的准确回答版本；原题保留供追溯。':'必要题在明确重新评估前保持等待。'}</div>`:''}`;
}
function optionsHTML(options){
  return list(options).length?`<ol>${list(options).map(option=>typeof option==='string'?`<li>${esc(option)}</li>`:`<li><strong>${esc(option.label||option.id||'选项')}</strong><p>${esc(option.consequence||'后果未记录')}</p></li>`).join('')}</ol>`:'';
}
export function questionDetails(q){
  const c=content(q),view=q.question_view||{},scope=questionScope(q);
  const scopeLabel={current_task:'当前任务问题',followup:'后续研究建议',optional:'可选反馈',historical:'历史建议 · 需重新评估'}[scope]||scope;
  return `<h3>${esc(c.question||q.title||'研究问题')}</h3><p class="hint">${esc(scopeLabel)}${view.effective_blocking||c.blocking?` · 当前绑定动作 ${esc(c.task_id||'项目范围')}`:' · 不阻断当前任务'}</p>${questionSources(q)}<p>${esc(c.background||'背景未记录')}</p>${optionsHTML(c.options)}${c.recommendation?`<p>建议与理由：${esc(c.recommendation)}</p>`:''}${c.answer?`<blockquote>已保存回答：${esc(c.answer)}<br>${esc(c.disposition||c.status||'处理方式未记录')}</blockquote>`:''}${c.source_reassessment?`<p>明确复核来源的理由：${esc(c.source_reassessment.reason)}</p>`:''}${c.inherited_answer?`<p class="hint">保留父问题 ${esc(c.inherited_answer.id)} r${esc(c.inherited_answer.revision)} 的已有回答；展开不代表重新请求答复。</p>`:''}`;
}
export function questionsPanel(questions,project=''){
  const filtered=list(questions).filter(q=>!q.archived&&(!project||q.project_id===project));
  if(!filtered.length)return empty('没有已登记问题','必要裁决、后续研究建议和可选反馈会分别保留。');
  const groups=[['current_task','当前任务问题'],['followup','后续研究建议'],['optional','可选反馈'],['historical','历史建议与过时问题']];
  return groups.map(([scope,title])=>{
    const rows=filtered.filter(q=>(q.question_view?.source_stale?'historical':questionScope(q))===scope);
    return rows.length?`<section><h2>${title}</h2>${rows.map(q=>{const c=content(q),view=q.question_view||{};return `<article class="panel decision-card"><div class="section-heading"><span>${esc(q.id)} · r${esc(q.revision)}</span>${status(c.status||'open')}</div>${questionDetails(q)}<div class="button-group">${button(c.answer?'查看 / 更新回答':'查看问题','decision',{id:q.id},'button small')}${view.materializable?button('展开原始建议','question-materialize',{id:q.id},'button small subtle'):''}${view.source_stale&&!view.source_valid?button('明确重新评估来源','question-reassess',{id:q.id},'button small subtle'):''}${['followup','optional','historical'].includes(questionScope(q))&&(view.source_valid??!view.source_stale)&&view.source_bound?button('明确绑定后续任务','question-bind',{id:q.id},'button small subtle'):''}</div></article>`;}).join('')}</section>`:'';
  }).join('');
}
export function questionAnswerFields(q){
  const c=content(q),binding=!!(q.question_view?.effective_blocking||c.blocking);
  return `${questionDetails(q)}<p class="hint">回答只记录你对${binding?'已绑定动作':'这条建议'}的裁决，不授予代码、数据处理或费用权限。${binding?'暂缓保留等待；继续后仍需核对候选是否已消费新回答。':'不会自动启动、继续或重新分派任务。'}</p>${select('处理方式','disposition',[['defer','暂缓，保留当前安排'],['continue',binding?'在已有授权范围继续':'记录同意 / 条件，不启动任务'],['deny',binding?'拒绝并停止绑定动作':'不采纳这条建议']],'defer')}${field('你的选择、条件与边界','answer',c.answer||'','textarea','required')}`;
}

export function questionReassessFields(q){
 const refs=list(q.question_view?.sources).filter(ref=>ref.kind==='artifact'&&ref.current_revision!==undefined);
 return `${questionDetails(q)}<h3>请读取当前来源变化</h3>${refs.map(ref=>`${button(`${ref.id} 当前 r${ref.current_revision}`,'open-reference',{id:ref.id,revision:ref.current_revision},'text-button')}`).join('')}<p>这次答复保留旧问题和原采用版本；请说明当前版本的变化为何允许保留、拒绝或暂缓旧判断。不会自动采用新版本，也不授予科学、代码或费用权限。旧候选仍须核验是否消费本次回答。</p>${field('看到的变化与保留原采用版本的理由','reason','','textarea','required')}${field('重新评估后的具体回答与条件','answer','','textarea','required')}${select('处理方式','disposition',[['defer','暂缓，保留当前安排'],['continue','在既有范围继续'],['deny','拒绝绑定动作']],'defer')}<label class="check-field"><input type="checkbox" name="approved" required><span>已阅读当前来源，并明确记录这次重新评估</span></label>`;
}
