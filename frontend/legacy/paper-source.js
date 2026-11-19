import {esc,button,assetURL} from './ui.js';
export function paperSourceMode(content){
 if(['structured','latex'].includes(content.paper_source_mode))return content.paper_source_mode;
 const manual=typeof content.latex==='string'&&content.latex.trim();
 return manual?(content.blocks?.length||content.components?.length?'unselected':'latex'):'structured';
}
export function paperSourcePanel(c){
 const d=c.draft.content,mode=paperSourceMode(d),state=c.object.paper_source_state,previous=state?.previous_revision;
 return `<section class="notice" data-paper-source><strong>论文来源</strong><p>结构稿用于阅读预览、DOCX、Markdown 与纯文本；TEX/PDF 使用下方明确选择的来源。手写 LaTeX 与结构稿分别保存，不自动互译或判定内容一致。</p><label class="field"><span>TEX/PDF 与当前编辑来源</span><select data-edit="paper-source-mode" aria-label="论文编辑与编译来源">${mode==='unselected'?'<option value="">尚未选择：同时存在结构稿与手写 LaTeX</option>':''}<option value="structured" ${mode==='structured'?'selected':''}>结构稿：由正文、组件与引用生成 TEX</option><option value="latex" ${mode==='latex'?'selected':''}>手写 LaTeX：直接编辑并导出保存的源稿</option></select></label>${mode==='unselected'?'<p class="warning-text">下方是结构稿。TEX/PDF 导出前必须明确选择并保存来源；旧手写稿不会覆盖下方的编辑。</p>':''}<div data-paper-source-identity data-object-id="${esc(c.object.id)}">${paperSavedIdentity(c.object)}</div></section>`;
}
export function latexEditor(c){
 const d=c.draft.content,refs=[...(d.components||[]),...(d.citations||[])];
 return `<div class="manuscript-ribbon"><div>手写 LaTeX</div><div class="manuscript-ribbon-tools">${button('格式','workspace-panel',{panel:'format'},'button subtle small')}${button('生成最新源稿','manuscript-format-source',{},'button subtle small')}${button('渲染最新稿','manuscript-format-render',{},'button primary small')}</div></div><div class="latex-workspace"><section class="latex-source-pane"><label class="field"><span>LaTeX 源稿 · 保存后编译</span></label><textarea data-edit="paper-latex" spellcheck="false" aria-label="LaTeX 源稿">${esc(d.latex||'')}</textarea><details><summary>结构稿（只读；DOCX 来源）与采用来源</summary><pre>${esc((d.blocks||[]).map(b=>b.text||'').join('\n\n'))}</pre>${refs.map(r=>button(`${r.id||r.object_id} @${r.revision}`,'open-reference',{id:r.id||r.object_id,revision:r.revision},'text-button')).join('')}</details></section><section class="latex-result-pane">${paperRenderedPreview(c.manuscriptRendered)||`<div class="quiet-empty">${esc(c.manuscriptFormatError||'保存源稿后渲染实际稿件。尚无已编译输出。')}</div>`}</section></div>`;
}
export function paperRenderedPreview(result){
 if(result?.provenance?.compiled!==true)return '';
 const assets=result.assets||{},pdf=Object.entries(assets).find(([name])=>/\.pdf$/i.test(name))?.[1]||result.asset,png=Object.entries(assets).find(([name])=>/\.png$/i.test(name))?.[1];
 const url=assetURL(pdf),image=assetURL(png);if(!url&&!image)return '';
 return `<section class="compiled-manuscript" data-compiled-manuscript><div class="compiled-manuscript-identity">实际 LaTeX 输出 · ${esc(result.provenance.object_id)} @${esc(result.provenance.base_revision)}${result.provenance.proposal_id?' · 最新候选（未采用）':''}</div>${image?`<img src="${esc(image)}" alt="实际编译稿件">`:`<iframe src="${esc(url)}" title="实际 LaTeX 稿件"></iframe>`}<a href="${esc(url||image)}" target="_blank" download>下载实际编译输出</a></section>`;
}
export function paperExportNotice(source){
 if(source.kind!=='paper')return '';
 const mode=paperSourceMode(source.content||{}),label={structured:'结构稿',latex:'手写 LaTeX',unselected:'尚未选择'}[mode];
 return `<div class="notice" data-paper-export-source>本次已保存修订的 TEX/PDF 来源：<strong>${esc(label)}</strong>。DOCX / Markdown / 纯文本读取结构稿；BibTeX 读取登记引用。两种文稿不自动同步。${mode==='unselected'?'返回论文编辑区选择并保存后才能生成 TEX/PDF。':''}</div>`;
}

export function paperSavedIdentity(object){
 const state=object.paper_source_state;
 if(!state||state.revision!==object.revision)return '<p class="hint">正在读取当前基础修订的保存来源身份；未保存编辑尚未纳入。</p>';
 const previous=state.previous_revision;
 return `<details><summary>已保存来源身份 · 修订 ${esc(state.revision)}</summary><p>结构稿 SHA256 <code>${esc(state.structured_sha256)}</code><br>手写 LaTeX SHA256 <code>${esc(state.latex_sha256)}</code> · ${esc(state.latex_characters)} 字符</p>${previous?`<p>与修订 ${esc(previous.revision)} 相比：${esc(previous.changed.length?previous.changed.map(k=>({mode:'导出源选择',structured_sha256:'结构稿',latex_sha256:'手写 LaTeX'}[k])).join('、')+' 已变化':'两份来源及选择均未变化')}。仅比较保存的字段，不证明两种文稿语义一致。</p>`:''}<p>未保存编辑尚未包含在上述身份中。切换模式保留两份原文；修订历史可比较和恢复。</p></details>`;
}
export function syncPaperSourceIdentity(root,object){
 const node=root.querySelector('[data-paper-source-identity]');if(node?.dataset.objectId===object.id)node.innerHTML=paperSavedIdentity(object);
}
