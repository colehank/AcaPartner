import {esc,button,list,pretty} from './ui.js';
import {documentMarkdown,documentTokens} from './document-markdown.js';

export function manuscriptCitationLabel41(c,key){
 const matches=[];
 for(const [index,ref] of list(c.draft?.content?.citations).entries()){
  const id=ref?.id||ref?.object_id,revision=ref?.revision,item=c.references?.[`${id}@${revision}`];
  if(!item||item.id!==id||item.revision!==revision||item.kind!=='literature'||c.referenceErrors?.[`${id}@${revision}`]||c.referencePins?.[`${id}@${revision}`]?.issue)continue;
  const content=item.content||{},keys=[content.citation_key,item.metadata?.citation_key,content.cite_key,content.key,content.bibtex_key];
  if(keys.includes(key))matches.push({label:String(index+1),title:item.title||key});
 }
 return matches.length===1?matches[0]:{label:key,title:matches.length?'引用键对应多条记录，需核对':'引用尚未对应到可核验的登记版本'};
}

export function scientificMarkdown(text,c){
 text=String(text||'');const protectedRanges=documentTokens(text).filter(t=>['code','fence'].includes(t.kind));
 const protectedAt=(start,end)=>protectedRanges.some(t=>start<t.end&&end>t.start);
 let marker='RPMATHCITE';while(text.includes(marker))marker+='X';const slots=[],tokens=[];
 for(const m of text.matchAll(/(?<!\\)\$\$([\s\S]+?)\$\$|(?<![\\$])\$(?!\$)([^\n$]+)\$(?!\$)|\\\[([\s\S]+?)\\\]|\\\(([^\n]+?)\\\)/g)){
  if(protectedAt(m.index,m.index+m[0].length))continue;
  const formula=m[1]??m[2]??m[3]??m[4],url=c.renderedMath?.math?.[formula],failure=c.renderedMath?.failures?.find(x=>x.formula===formula);
  tokens.push({start:m.index,end:m.index+m[0].length,html:url?`<span class="rendered-math ${(m[1]||m[3])?'display-math':''}" data-formula="${esc(formula)}"><img src="${esc(url)}" alt="${esc(formula)}"></span>`:`<code class="math-source" title="${esc(failure?.error||'正在渲染公式')}">${esc(m[0])}</code>`});
 }
 for(const m of text.matchAll(/\[@([^\]\n]+)\]/g)){
  if(protectedAt(m.index,m.index+m[0].length)||tokens.some(t=>m.index<t.end&&m.index+m[0].length>t.start))continue;
  const keys=m[1].split(/;\s*@?/).map(s=>s.trim());
  tokens.push({start:m.index,end:m.index+m[0].length,html:keys.map(key=>{const display=manuscriptCitationLabel41(c,key);return `<button type="button" class="inline-citation" data-action="citation-inspect" data-key="${esc(key)}" title="${esc(display.title)}">[${esc(display.label)}]</button>`;}).join(' ')});
 }
 tokens.sort((a,b)=>a.start-b.start);let source='',last=0;
 for(const token of tokens){const id=marker+slots.length+'END';source+=text.slice(last,token.start)+id;slots.push([id,token.html]);last=token.end;}
 source+=text.slice(last);let html=documentMarkdown(source,c.draft.content.resources);
 for(const [id,value] of slots)html=html.replaceAll(id,value);return html;
}
export function sectionFor(c,blockId){
 const blocks=list(c.draft?.content?.blocks),sections=list(c.object?.metadata?.article?.sections);let current=null;
 for(const block of blocks){const section=sections.find(s=>s.heading_block_id===block.id);if(section)current=section;if(block.id===blockId)return current;}
 return null;
}
export function sectionNotePanel(c){
 const note=c.sectionNote;if(!note){const sections=list(c.object?.metadata?.article?.sections);return sections.length?`<p>选择要准备的章节，笔记与原稿保持关联。</p><div class="section-note-choices">${sections.map(section=>button(section.title||section.id,'section-note',{section:section.id},'button full')).join('')}</div>`:'<p>此成果还没有登记章节。稿件关联章节后，可在阅读位置打开准备笔记。</p>'; }
 return `<div class="section-note-heading"><span>章节准备 · 不进入成果正文</span><h2>${esc(note.title)}</h2></div><p class="hint">缺口、计划、待决事项与准备材料留在这里。形成成果后，经修订进入正文。</p>${list(note.content.blocks).map(b=>`<label class="field"><span>准备内容</span><textarea data-note-block="${esc(b.id)}">${esc(b.text)}</textarea></label>`).join('')||'<p>本章节尚无准备内容。</p>'}<div class="button-group">${button('添加笔记','section-note-add',{},'button small')}${button('保存笔记','section-note-save',{},'button primary small')}${button('返回原稿','section-note-return',{},'button small')}</div><p class="hint" data-note-save-status>基础修订 ${esc(note.revision)}${c.sectionNoteDirty?' · 未保存':''}</p>`;
}
export function tracePanel(view){
 return `<p class="hint">溯源说明当前表达由哪些观察和计算支持；来源存在不等于科学结论已批准。</p>${view.relations.map(r=>`<article class="trace-relation"><h3>科学支持关系</h3><details class="trace-expression"><summary>所解释的科学表述</summary><p>${esc(r.statement||'未登记具体表达')}</p></details><p>${esc(r.supports||'支持范围尚未说明')}</p>${r.computation?`<p>计算路径：${esc(typeof r.computation==='string'?r.computation:pretty(r.computation))}</p>`:''}<p class="hint">${esc(r.limitations||'限制尚未登记')}</p></article>`).join('')}${view.sources.map(s=>`<article class="trace-source"><h3>${esc(s.title)}</h3><p>${esc(s.supports||'具体支持关系尚未登记')}</p><small>采用修订 ${esc(s.revision)}</small>${s.scientific_relations.map(r=>`<p>${esc(r.statement||'')}: ${esc(r.supports||'')} <span class="hint">${esc(r.limitations||'')}</span></p>`).join('')}${s.computation?`<p>计算：${esc(typeof s.computation==='string'?s.computation:pretty(s.computation))}</p>`:''}<ul>${s.assets.map(a=>`<li>${esc({plot_code:'绘图代码',saved_data:'保存的数据',result:'渲染结果'}[a.role]||a.role)}：<a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.name)}</a></li>`).join('')}</ul>${button('打开来源成果','open-object',{id:s.object_id},'button small')}</article>`).join('')}${view.missing.length?`<div class="notice warning">${view.missing.map(x=>`<p>${esc(x)}</p>`).join('')}</div>`:''}`;
}
export function projectFilesPanel(view){
 return `<p>实际目录：<code>${esc(view.root)}</code></p><p class="hint">源稿、代码和章节工坊笔记分开保存。外部文件改动不会被静默覆盖。</p>${view.status==='repair_required'?`<div class="notice warning">文件镜像尚需修复：${esc(pretty(view.errors))}。数据库保存与文件镜像状态分开。</div>`:''}<div class="project-file-list">${list(view.entries).map(f=>`<div><span>${esc(f.role)}</span>${button(f.path,'project-file-read',{path:f.path},'text-button')}</div>`).join('')}</div>`;
}
