import {renderFigureStudio} from './figure-studio.js';
import {renderManuscript} from './manuscript-editor.js';
import {paperSourcePanel,paperSourceMode,latexEditor} from './paper-source.js';
import {esc,button,empty,kinds,assetURL,list,pretty,markdown} from './ui.js';
import {renderClaims} from './claim-evidence.js';
import {figureControls,orphanedFigureOverlays} from './figure-properties.js';
import {diagramArtwork,diagramGeometry,diagramEdgeMarkup} from './diagram-geometry.js';
import {documentMarkdown,documentImageOccurrences,registeredDocumentAssetURL} from './document-markdown.js';

export const canvasKinds = new Set(['poster','slides']);
export const documentKinds = new Set(['report','note','paper','workshop_note','question','concept','literature','growth']);
export function newContent(kind) {
  if (canvasKinds.has(kind)) return {units:kind==='poster'?'cm':'px',pages:[{id:crypto.randomUUID(),width:kind==='poster'?80:1280,height:kind==='poster'?120:720,objects:[],notes:''}]};
  if(kind==='diagram') return {nodes:[],edges:[],width:1000,height:640};
  if(kind==='figure')return {overlays:[],script_asset:'',input_assets:[],caption:'',manifest:[],spec:{kind:'line',x:[],series:[]}};
  if(kind==='workshop')return {category:'stimulus',inputs:[],config:{},acceptance:[],outputs:[]};
  return {blocks:kind==='paper'?['前言','方法','结果','讨论','引用说明'].flatMap(text=>[{id:crypto.randomUUID(),kind:'heading',text},{id:crypto.randomUUID(),kind:'paragraph',text:''}]):[{id:crypto.randomUUID(),kind:'paragraph',text:''}],citations:[],components:[]};
}
export function renderEditor(c) {
  const o=c.object;
  if(!o)return empty('打开一份成果，接着研究','从左侧选择当前成果，或创建新的报告、图与汇报。',button('新建成果','new-artifact',{},'button primary'));
  let body='';
  if(canvasKinds.has(o.kind))body=renderCanvas(c);
  else if(o.kind==='diagram')body=renderDiagram(c);
  else if(o.kind==='figure')body=c.draft.content.composition?`<div class="document-tools">${button('返回统计图设置','figure-composition',{},'button small')}</div>${renderCanvas(c)}`:renderFigureStudio(c);
  else if(o.kind==='workshop')body=renderWorkshopObject(c);
  else if(o.kind==='literature')body=renderLiterature(c);
  else body=renderDocument(c);
  const document=documentKinds.has(o.kind)&&o.kind!=='literature';
  const trail=c.componentTrail?.at(-1),figure=o.kind==='figure'&&!c.draft.content.composition&&c.draft.content.editable_source_available!==false,tracked=['paper','report','note'].includes(o.kind)&&c.trackChanges&&paperSourceMode(c.draft.content)!=='latex'&&JSON.stringify(c.draft.content.blocks)!==JSON.stringify(o.content?.blocks);
  return `<header class="editor-commandbar"><div class="editor-command-title">${trail?`<button class="studio-tool" type="button" data-action="component-return" title="返回稿件：${esc(trail.title)}" aria-label="返回稿件" ${c.returningComponent41?'disabled aria-busy="true"':''}>${c.returningComponent41?'…':'←'}</button>`:''}<strong title="${esc(c.draft.title)}">${esc(c.draft.title)}</strong><span data-editor-base-revision data-object-id="${esc(o.id)}">r${esc(o.revision)}</span><span data-editor-remote-revision data-object-id="${esc(o.id)}" ${c.remoteRevision?'':'hidden'}>服务器 r${esc(c.remoteRevision||'')}</span></div><div class="editor-command-actions"><button type="button" class="studio-tool" data-action="undo" title="撤销" aria-label="撤销" ${c.undo?.length?'':'disabled'}>↶</button><button type="button" class="studio-tool" data-action="redo" title="重做" aria-label="重做" ${c.redo?.length?'':'disabled'}>↷</button><span id="save-status" class="save-status">${c.draftStorageError41===o.id?'本机副本未保存 · 请保留当前页面':c.dirty?'未采用改动':`已保存 · r${esc(o.revision)}`}</span>${figure?button('取消','figure-preview-cancel',{},'button small')+button(trail?'采用并更新本稿':'采用改动','figure-preview-apply',{},'button primary small'):button(tracked?'记录修订':'保存修改',tracked?'manuscript-edit-track':'save',{},'button primary small')}${button('导出','export',{},'button small')}<details class="editor-more"><summary aria-label="成果更多操作">⋯</summary><div>${button('历史','history',{},'text-button')}${c.localHistoryRecovery?.objectId===o.id?button('保留的本机编辑历史','local-history-recovery',{},'text-button'):''}${!document?button('批注','view-annotations',{},'text-button'):''}${button('改名','rename',{},'text-button')}${button('成果来源','provenance',{},'text-button')}${button('成果文件','workbench-files',{},'text-button')}${button('入口链接','artifact-link',{},'text-button')}${button('整理所属模块','workbench-organize',{},'text-button')}${button('提交工作方式反馈','feedback',{},'text-button')}</div></details></div></header>${c.remoteRevision?`<div class="notice warning">服务器已有修订 ${esc(c.remoteRevision)}，本地草稿保留。${button('核对差异','conflict-review',{},'button small')}</div>`:''}${c.recovered?'<div class="notice">已恢复本机未保存草稿。</div>':''}<div class="editor-content">${trail&&figure?`<div class="desk41-figure-context">本稿此处采用 r${esc(trail.adoptedRevision)} · 正在编辑图 r${esc(o.revision)}。采用后更新此稿这一处，其他稿件保持。</div>`:''}${body}</div>`;
}

function renderDocument(c) { return renderManuscript(c); }

function renderCanvas(c) {
  const pages=c.draft.content.pages||[];const page=pages[c.page]||pages[0];if(!page)return empty('当前没有页面','添加页面开始排版。',button('+ 页面','page-add',{},'button primary'));
  const isPoster=c.object.kind==='poster'||c.object.kind==='figure', scale=Math.min(780/page.width,880/page.height,12), objs=page.objects||[], selected=objs.find(o=>o.id===c.selectedItem);
  return `<div class="layout-toolbar"><div class="button-group">${button('+ 文本','canvas-add',{type:'text'},'button small')}${button('+ 图像 / 组件','canvas-add',{type:'image'},'button small')}${button('+ 矩形','canvas-add',{type:'shape'},'button small')}${button('左对齐','canvas-align',{axis:'left'},'button small')}${button('顶对齐','canvas-align',{axis:'top'},'button small')}${button('组合','canvas-group',{},'button small')}${button('取消组合','canvas-ungroup',{},'button small')}</div><span class="hint">Shift 点击多选 · 拖动对象调整位置</span></div>
  <div class="layout-workspace"><aside class="page-list" data-page-list><div class="mini-label">${isPoster?'版面':'幻灯片'}</div>${pages.map((p,i)=>`<button class="page-thumbnail ${i===c.page?'active':''}" data-action="page-select" data-index="${i}"><span>${i+1}</span><strong>${esc(p.title||`${isPoster?'版面':'幻灯片'} ${i+1}`)}</strong><small>${p.objects?.length||0} 个对象</small></button>`).join('')}${button('+ 页面','page-add',{},'button small full')}${button('上移','page-move',{direction:-1},'button small')}${button('下移','page-move',{direction:1},'button small')}${button('删除页','page-delete',{},'button small danger-text')}</aside>
  <div class="canvas-center"><div class="canvas-meta" data-canvas-meta>${esc(page.width)} × ${esc(page.height)} ${esc(c.draft.content.units||'px')} · ${esc(c.page+1)} / ${pages.length}</div><div class="canvas-surface" data-canvas data-scale="${scale}" style="width:${page.width*scale}px;height:${page.height*scale}px">${objs.map(o=>canvasObject(o,scale,c)).join('')}</div>
  <label class="page-notes"><span>${isPoster?'版面说明与阅读顺序':'本页讲稿 / 讲者备注'}</span><textarea data-edit="page-notes" placeholder="${isPoster?'记录版面说明':'讲稿始终随此页移动；每个 {} 可记录一次点击。'}">${esc(page.notes||'')}</textarea></label></div>
  <aside class="object-inspector"><h3>${selected?'对象属性':'页面属性'}</h3>${selected?renderObjectFields(selected):`${editField('宽度','page-width',page.width,'number')}${editField('高度','page-height',page.height,'number')}${editField('页面标题','page-title',page.title||'')}`}<p class="hint">几何尺寸采用 ${esc(c.draft.content.units||'px')}。${isPoster?'海报导出保留设定的物理尺寸。':'导出保留文字、对象与逐页备注。'}</p>${selected?button('删除对象','canvas-delete',{},'button small danger-text'):''}</aside></div>`;
}
function canvasObject(o,scale,c) {
  const chosen=c.selectedItems?.includes(o.id)||c.selectedItem===o.id;
  const color=/^#[0-9a-fA-F]{3,8}$/.test(o.color||'')?o.color:'#253a39';
  const bg=/^#[0-9a-fA-F]{3,8}$/.test(o.fill||'')?o.fill:'transparent';
  const url=assetURL(o.asset||o.src||o.asset_id);
  const item=c.objects.find(it=>it.id===o.component_id);
  return `<div class="canvas-object ${chosen?'selected':''} ${o.type==='shape'?'shape':''}" data-item="${esc(o.id)}" tabindex="0" role="button" aria-label="${esc(o.text||o.type)}" style="left:${Number(o.x||0)*scale}px;top:${Number(o.y||0)*scale}px;width:${Number(o.width||100)*scale}px;height:${Number(o.height||50)*scale}px;font-size:${Number(o.font_size||16)*scale}px;color:${color};background:${bg};text-align:${['left','center','right'].includes(o.align)?o.align:'left'};z-index:${Number(o.z||0)}">${o.type==='image'?url?`<img alt="${esc(o.alt||o.text||'科研图')}" src="${esc(url)}" draggable="false">`:`<div class="image-placeholder">${esc(item?.title||o.text||'请在对象属性中关联图像资产')}</div>`:esc(o.text||'')}${o.group?'<span class="group-mark">⊞</span>':''}</div>`;
}
const editField=(label,key,value,type='text',id='')=>`<label class="field compact"><span>${esc(label)}</span>${type==='textarea'?`<textarea data-edit="${esc(key)}" data-id="${esc(id)}">${esc(value)}</textarea>`:`<input data-edit="${esc(key)}" data-id="${esc(id)}" type="${type}" value="${esc(value)}" ${type==='number'?'step="any"':''}>`}</label>`;
function renderObjectFields(o) {
  return `${editField('文字 / 替代文本','item-text',o.text||'','textarea')}${o.type==='image'?editField('资产 SHA 或已注册资源地址','item-asset',o.asset||o.src||''):''}<div class="field-grid">${['x','y','width','height'].map(k=>editField({x:'横向位置',y:'纵向位置',width:'宽度',height:'高度'}[k],`item-${k}`,o[k]||0,'number')).join('')}</div>${editField('字号','item-font_size',o.font_size||16,'number')}${editField('文字颜色','item-color',o.color||'#253a39','color')}${editField('填充色','item-fill',o.fill||'#ffffff','color')}${editField('层级','item-z',o.z||0,'number')}${editField('来源成果 ID','item-component_id',o.component_id||'')}`;
}

function diagramSources(node) {
  const refs=[...(node.source_ref?[node.source_ref]:[]),...(Array.isArray(node.source_refs)?node.source_refs:[])];
  return `<div class="diagram-source-references" style="overflow-wrap:anywhere"><h3>采用来源</h3>${refs.length?refs.map(ref=>{
    const bound=ref&&typeof ref==='object'&&typeof ref.id==='string'&&Number.isInteger(ref.revision)&&ref.revision>0;
    return bound?`<p>${button(ref.id,'open-reference',{id:ref.id,revision:ref.revision,block_id:ref.block_id||''},'text-button')}<br><small>采用修订 ${esc(ref.revision)}${ref.block_id?` · 段落 ${esc(ref.block_id)}`:''}</small></p>`:`<p class="hint">来源记录未完整绑定：${esc(pretty(ref))}</p>`;
  }).join(''):'<p class="hint">此节点未登记版本绑定的来源。</p>'}${node.source?`<p class="hint">旧来源备注（未绑定修订）：${esc(node.source)}</p>`:''}<p class="hint">此处按登记修订只读显示来源。</p></div>`;
}

function diagramCaption(data) {
  const blocks=Array.isArray(data.blocks)?data.blocks:[];
  return `<article class="document-page diagram-caption"><h2>完整图注与方法范围</h2>${blocks.length?blocks.map(block=>`<section data-block="${esc(block.id)}"><small>${esc(block.id)}${block.kind?` · ${esc(block.kind)}`:''}</small><div class="prose">${markdown(block.text||'')}</div></section>`).join(''):'<p class="hint">这份概念图尚未登记图注。</p>'}${data.rationale?`<details><summary>研究意图</summary><div class="prose">${markdown(data.rationale)}</div></details>`:''}</article>`;
}

function renderDiagram(c) {
  const data=c.draft.content,nodes=data.nodes||[],selected=nodes.find(n=>n.id===c.selectedItem),w=data.width||1000,h=data.height||640;
  let artwork='',warnings=[];
  try{const rendered=diagramArtwork(data,[...(c.selectedItems||[]),c.selectedItem]);artwork=rendered.svg;warnings=rendered.geometry.warnings;}
  catch(error){warnings=[error.message];}
  return `<div class="layout-toolbar"><div class="button-group">${button('+ 节点','diagram-add',{},'button small')}${button('+ 关系','diagram-edge',{},'button small')}${button('左对齐','diagram-align',{axis:'left'},'button small')}${button('顶对齐','diagram-align',{axis:'top'},'button small')}${button('组合','diagram-group',{},'button small')}${button('取消组合','diagram-ungroup',{},'button small')}</div><span class="hint">关系需要明确含义与来源；候选关系用虚线表示</span></div>
  <div data-diagram-warnings>${warnings.length?`<div class="notice warning" role="status">当前草稿的连线布局需要调整：${warnings.map(esc).join('；')}</div>`:''}</div>
  <div class="diagram-layout"><div class="diagram-scroll"><div class="diagram-surface" data-diagram data-scale="1" style="width:${w}px;height:${h}px">${artwork}${!nodes.length?'<div class="canvas-empty">添加节点，组织你的研究框架</div>':''}</div></div><aside class="object-inspector"><h3>${selected?'节点属性':'概念 / 流程图'}</h3>${selected?`${editField('节点文本','node-text',selected.text||selected.label||'','textarea')}<div class="field-grid">${['x','y','width','height'].map(k=>editField({x:'横向位置',y:'纵向位置',width:'宽度',height:'高度'}[k],`node-${k}`,selected[k]||0,'number')).join('')}</div>${selected.group?`<p class="hint">组合：${esc(selected.group)}</p>`:''}${diagramSources(selected)}${button('批注节点','annotate',{},'button small')}${button('删除节点','diagram-delete',{},'button small danger-text')}`:'<p class="hint">选中节点编辑文本与位置。Shift 点击可多选节点。每个节点保留稳定身份。</p>'}</aside></div>${diagramCaption(data)}`;
}

function renderFigure(c) {
  const data=c.draft.content,exported=c.object.metadata?.last_export||{},staticSource=data.editable_source_available===false,manifest=staticSource?[]:list(exported.manifest||data.manifest||data.object_manifest||data.objects),preview=assetURL(exported.assets?.['figure.png']||data.preview||data.preview_asset||data.png||data.rendered?.preview),selected=manifest.find(m=>(m.id||m.object_id)===c.selectedItem),overlays=data.overlays||[],layer=Array.isArray(overlays)?overlays.find(o=>(o.target||o.object_id||o.id)===c.selectedItem)||{}:overlays[c.selectedItem]||{};
  const controls=selected?figureControls(selected,layer):'',orphans=orphanedFigureOverlays(manifest,data),failures=exported.replay?.failures??data.replay_failures??[],provenance=exported.provenance;
  const identity=provenance?.object_id===c.object.id&&provenance.source_sha256?`图像来源：${provenance.object_id} @${provenance.revision} · ${provenance.source_sha256.slice(0,12)}`:'当前显示登记的原图资产；尚无完整可重放的渲染身份。';
  const status=staticSource?'原始图像预览：没有可分解的 Artist 或可执行来源。可阅读、批注和下载；添加脚本后才能编辑图元素。':`${identity}。${c.dirty||provenance?.revision!==c.object.revision?'当前修改尚未渲染。':'属性改动先保存为覆盖，显式重绘后更新图像。'}`;
  const dragHelp=selected?.interaction?.drag?.enabled?'拖动选中轮廓调整位置；右键批注此 Artist。虚线框表示尚未渲染的位置。':selected?.interaction?.drag?.reason||'此输出没有确切拖动坐标。重绘取得新清单后可拖动受支持的 Artist；当前仍可编辑属性。';
  return `<section data-figure-editor><div class="layout-toolbar"><span class="hint">${staticSource?'原图阅读与批注': '选择图元素编辑属性；明确保存与重绘。'}</span><div class="button-group">${!staticSource?`<label class="check-field"><input type="checkbox" data-edit="figure-live-preview" ${(c.figureLivePreview??!(data.script_asset||data.script))?'checked':''}>松开后更新图像</label>`:''}${button('组合子图为主图','figure-composition',{},'button small')}${!staticSource?button('重绘并检查覆盖','figure-render',{},'button small primary'):''}</div></div><p class="notice" data-figure-status role="status">${esc(status)}</p><div class="figure-workspace"><div class="figure-preview">${preview?`<div class="figure-image" data-figure-image><img src="${esc(preview)}" alt="${esc(c.draft.title)}" draggable="false">${manifest.filter(m=>Array.isArray(m.bbox)&&m.bbox.length===4&&m.bbox.every(Number.isFinite)).map(m=>`<button class="figure-hit ${m.id===c.selectedItem?'selected':''}" data-figure-hit data-id="${esc(m.id)}" aria-label="${esc(m.label||m.id)}" title="${esc(m.label||m.id)}" style="left:${m.bbox[0]*100}%;top:${m.bbox[1]*100}%;width:${Math.max(0,m.bbox[2])*100}%;height:${Math.max(0,m.bbox[3])*100}%"></button>`).join('')}</div><div class="button-group"><a class="button small" href="${esc(preview)}" target="_blank" rel="noopener" download>仅下载图像</a>${button('图与说明包','figure-download',{},'button small')}${button('整图 / 区域批注','figure-region',{},'button small')}</div>`:empty('尚无已渲染科研图','配置真实脚本和输入，或填入结构化绘图数据后执行重绘。未产生输出时不会显示示意结果。')}<pre class="notice warning" data-figure-overlay-summary hidden></pre><label class="field"><span>图注 · 定义、分母、方法与限制</span><textarea data-edit="figure-caption">${esc(data.caption||'')}</textarea></label>${orphans.length?`<div class="notice warning">清单中已找不到这些对象，原覆盖仍保留；重绘会逐项报告失败：<pre>${esc(pretty(orphans))}</pre></div>`:''}${failures.length?`<div class="notice warning">以下覆盖未能重放，修改仍保留：<pre>${esc(pretty(failures))}</pre></div>`:''}</div><aside class="object-inspector"><h3>${staticSource?'原图来源':'可编辑图对象'}</h3>${manifest.length?`<select data-edit="figure-select" aria-label="选择图对象"><option value="">选择对象</option>${manifest.map(m=>`<option value="${esc(m.id||m.object_id)}" ${(m.id||m.object_id)===c.selectedItem?'selected':''}>${esc(m.label||m.type||m.id)} · ${esc(m.id||m.object_id)}</option>`).join('')}</select>`:`<p class="hint">${staticSource?'此原图保持完整像素内容；没有登记可逐项修改的图元素。':'后端渲染完成后列出受支持的图对象。'}</p>`}${selected?`<div class="selected-figure-object">${esc(selected.type||'图对象')} · ${esc(selected.label||selected.id)}</div><p class="hint" data-figure-drag-help>${esc(dragHelp)}</p>${controls}${button('批注选中元素','figure-annotate',{},'button small')}${button('清除此对象覆盖','figure-overlay-clear',{},'button small')}`:''}<details ${preview?'':'open'}><summary>${staticSource?'提供可编辑来源':'生成来源与代码'}</summary>${button('上传输入','import-asset',{mode:'figure-input'},'button small')}${button('上传脚本','import-asset',{mode:'figure-script'},'button small')}${button('查看 / 编辑实际代码','figure-code',{},'button small')}${editField('脚本资产 SHA','figure-script_asset',data.script_asset||data.script||'')}${button('授权此脚本','figure-authorize',{},'button small')}${editField('输入资产（JSON 或每行一个 SHA）','figure-input_assets',pretty(data.input_assets||[]),'textarea')}${editField('绘图数据 spec（JSON）','figure-spec',pretty(data.spec||{kind:'line',x:[],series:[]}),'textarea')}${editField('参数（JSON）','figure-parameters',pretty(data.parameters||{}),'textarea')}<p class="hint">代码编辑登记新的不可变脚本资产。改动后须重新授权；保存代码不会执行脚本。结构化 spec 使用你提供的真实数据。</p></details></aside></div></section>`;
}
function renderWorkshopObject(c) {
  const data=c.draft.content;
  return `<div class="notice">此成果由研究工坊维护输入、执行与技术验收。${button('在工坊中打开','open-workshop',{id:c.object.id},'button small')}</div><article class="document-page"><h2>输入与配置</h2><pre>${esc(pretty({category:data.category,inputs:data.inputs,config:data.config}))}</pre><h2>输出</h2>${(data.outputs||[]).length?(data.outputs||[]).map(x=>{const url=assetURL(x.asset||x.sha||x.url);return `<p>${url?`<a href="${esc(url)}" target="_blank" rel="noopener">${esc(x.name||x.path||'输出资产')}</a>`:esc(pretty(x))}</p>`;}).join(''):'<p class="hint">尚无已保存输出。</p>'}<h2>技术验收记录</h2><pre>${esc(pretty(data.acceptance||data.validation||[]))}</pre></article>`;
}

function renderLiterature(c) {
  const d=c.draft.content;
  return `<article class="document-page literature-editor"><h2>文献记录</h2>${editField('题名','literature-title',d.title||c.draft.title)}${editField('作者（每行一位）','literature-authors',Array.isArray(d.authors)?d.authors.join('\n'):d.author||'','textarea')}<div class="field-grid">${editField('出版年份','literature-year',d.year||'')}${editField('期刊 / 出版来源','literature-journal',d.journal||d.venue||'')}</div>${editField('DOI','literature-doi',d.doi||'')}${editField('原始来源 URL','literature-url',d.url||'')}<label class="field"><span>实际阅读范围</span><select data-edit="literature-read_scope">${[['metadata','仅元数据'],['abstract','仅摘要'],['fulltext','已读取全文']].map(([v,label])=>`<option value="${v}" ${d.read_scope===v?'selected':''}>${label}</option>`).join('')}</select></label>${editField('已获取摘要','literature-abstract',d.abstract||'','textarea')}${editField('实际读到的全文内容 / 范围说明','literature-full_text',d.full_text||'','textarea')}<p class="hint">阅读范围由实际可访问的内容决定。补充字段不会自动产生论断支持。</p>${d.missing_fields?.length?`<div class="notice warning">导入时缺失字段：${esc(d.missing_fields.join('、'))}</div>`:''}<details><summary>检索与导入来源</summary><pre>${esc(pretty({source_url:d.source_url,query:d.query,source_asset:d.source_asset,import_source:d.import_source}))}</pre></details></article>`;
}

export function bindCanvasDrag(root,c,{selectItem,mutate,redraw}) {
  root.querySelectorAll('[data-node],[data-edge-label],[data-diagram-lines] [data-action]').forEach(el=>el.addEventListener('keydown',e=>{
    if(!['Enter',' '].includes(e.key))return;e.preventDefault();e.stopPropagation();
    if(el.dataset.node)selectItem(el.dataset.node,e.shiftKey,true);
    else el.dispatchEvent(new MouseEvent('click',{bubbles:true}));
  }));
  root.querySelectorAll('[data-item],[data-node]').forEach(el=>el.addEventListener('pointerdown', e=>{
    if(e.button!==0)return;const id=el.dataset.item||el.dataset.node,isNode=!!el.dataset.node;
    const items=isNode?c.draft.content.nodes:(c.draft.content.pages[c.page]?.objects||[]),item=items.find(n=>n.id===id);if(!item)return;
    e.preventDefault();e.stopPropagation();const keep=e.shiftKey;selectItem(id,keep,false);const selectedIds=c.selectedItems.length?c.selectedItems:[id],group=item.group;
    const moving=items.filter(n=>selectedIds.includes(n.id)||(group&&n.group===group));const starts=moving.map(n=>({id:n.id,x:n.x||0,y:n.y||0}));
    const scale=Number(el.closest('[data-scale]')?.dataset.scale||1),canvas=el.closest('[data-canvas]'),svg=isNode?el.ownerSVGElement:null,rect=canvas?.getBoundingClientRect(),viewScale=canvas&&canvas.offsetWidth?rect.width/canvas.offsetWidth:1,matrix=svg?.getScreenCTM(),pointerScaleX=isNode?(matrix?.a||1):scale*viewScale,pointerScaleY=isNode?(matrix?.d||1):scale*viewScale,startX=e.clientX,startY=e.clientY;let moved=false;
    el.setPointerCapture(e.pointerId);root.querySelectorAll('[data-item],[data-node]').forEach(n=>{
      const chosen=moving.some(m=>m.id===(n.dataset.item||n.dataset.node));n.classList.toggle('selected',chosen);
      n.querySelector('[data-node-outline]')?.setAttribute('visibility',chosen?'visible':'hidden');
    });
    const move=ev=>{
      const dx=(ev.clientX-startX)/pointerScaleX,dy=(ev.clientY-startY)/pointerScaleY;if(Math.abs(dx)+Math.abs(dy)>1)moved=true;if(!moved)return;
      starts.forEach(s=>{const dom=root.querySelector(`[${isNode?'data-node':'data-item'}="${CSS.escape(s.id)}"]`);if(dom){
        if(isNode)dom.setAttribute('transform',`translate(${s.x+dx} ${s.y+dy})`);
        else{dom.style.left=`${(s.x+dx)*scale}px`;dom.style.top=`${(s.y+dy)*scale}px`;}
      }});
      if(isNode){
        const preview={...c.draft.content,nodes:c.draft.content.nodes.map(node=>{const start=starts.find(s=>s.id===node.id);return start?{...node,x:start.x+dx,y:start.y+dy}:node;})};
        const markup=diagramEdgeMarkup(diagramGeometry(preview));
        for(const key of ['defs','lines','labels'])root.querySelector(`[data-diagram-${key}]`).innerHTML=markup[key];
      }
    };
    const end=ev=>{el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',end);el.removeEventListener('pointercancel',end);if(moved&&ev.type!=='pointercancel'){const dx=(ev.clientX-startX)/pointerScaleX,dy=(ev.clientY-startY)/pointerScaleY;mutate(d=>{const list=isNode?d.content.nodes:d.content.pages[c.page].objects;starts.forEach(s=>{const item=list.find(n=>n.id===s.id);item.x=Math.round((s.x+dx)*100)/100;item.y=Math.round((s.y+dy)*100)/100;});},true);}else redraw();};
    el.addEventListener('pointermove',move);el.addEventListener('pointerup',end);el.addEventListener('pointercancel',end);
  }));
}
