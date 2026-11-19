import {figureRegionAnchor,figureSavedPreviewSha} from './figure-interaction.js';
import {esc,button,list,pretty,field,select,modal,uid,clone,toast} from './ui.js';
import {sectionFor,sectionNotePanel,tracePanel,projectFilesPanel} from './article-ui.js';
import {manuscriptRoundSubmission} from './manuscript-review.js';

export function createArticleController({ui,action,api,draw,refresh,noteDraftKey=id=>'research-partner:note:'+id,readNoteDraft=id=>localStorage.getItem(noteDraftKey(id)),editorSnapshot,requireEditor,readEditorDetails,finishManuscriptRevision,openManuscriptReview}){
 async function organize(){
  if(ui.dirty)throw new Error('请先保存正文，再登记准确章节。');const source=editorSnapshot();
  const result=await action('article.organize',{object_id:source.id,expected_revision:source.revision,request_key:uid('sections')});
  await finishManuscriptRevision(source,result.manuscript||result.object||result);
  await refresh({render:false});draw();toast('章节已关联。原稿正文与用途保留。');
 }
 async function sectionNote(sectionId){
  if(ui.sectionNoteDirty)throw new Error('当前笔记尚未保存；请先保存或返回核对，内容已保留。');
  const source=editorSnapshot(),section=list(ui.object.metadata?.article?.sections).find(s=>s.id===sectionId);
  if(!section)throw new Error('章节登记已变化，请重新打开。');
  const result=await action('article.section_note',{manuscript_id:source.id,section_id:sectionId,expected_revision:source.revision,request_key:uid('section-note')});requireEditor(source);
  ui.sectionNote=clone(result.note);ui.sectionNoteDirty=false;ui.noteReturnBlock=ui.selectedBlock||section.heading_block_id;
  try{const draft=JSON.parse(readNoteDraft(result.note.id)||'null');if(draft){ui.sectionNote=clone(draft);ui.sectionNoteDirty=true;}}catch{}
  ui.workspacePanel='notes';draw();
 }
 function noteInput(el){const block=ui.sectionNote?.content.blocks.find(b=>b.id===el.dataset.noteBlock);if(!block)return;block.text=el.value;ui.sectionNoteDirty=true;localStorage.setItem(noteDraftKey(ui.sectionNote.id),JSON.stringify(ui.sectionNote));}
 function noteAdd(){if(!ui.sectionNote)return;ui.sectionNote.content.blocks.push({id:uid('BLOCK'),kind:'paragraph',text:''});ui.sectionNoteDirty=true;localStorage.setItem(noteDraftKey(ui.sectionNote.id),JSON.stringify(ui.sectionNote));draw();}
 async function noteSave(){
  const snapshot=clone(ui.sectionNote);if(!snapshot)return;
  const result=await action('object.save',{id:snapshot.id,expected_revision:snapshot.revision,content:snapshot.content});
  if(ui.sectionNote?.id===snapshot.id){
   if(JSON.stringify(ui.sectionNote.content)===JSON.stringify(snapshot.content)){ui.sectionNote=clone(result);ui.sectionNoteDirty=false;localStorage.removeItem(noteDraftKey(snapshot.id));}
   else{ui.sectionNote.revision=result.revision;localStorage.setItem(noteDraftKey(snapshot.id),JSON.stringify(ui.sectionNote));}
   draw();
  }
  toast(result.project_files&&Object.values(result.project_files).some(v=>v.status==='repair_required')?'笔记已入库；文件镜像待修复。':'章节笔记已保存，不进入正文。');
 }
 function noteReturn(){ui.workspacePanel=null;draw();if(ui.noteReturnBlock)document.querySelector(`[data-block="${CSS.escape(ui.noteReturnBlock)}"]`)?.scrollIntoView({block:'center'});}
 async function files(){const result=await action('article.files',{project_id:ui.project});ui.projectFiles=result;modal('项目实际文件',projectFilesPanel(result),{wide:true});}
 async function fileRead(path){const result=await action('article.file_read',{project_id:ui.project,path});modal(path,result.encoding==='utf-8'?`<pre class="source-file">${esc(result.content)}</pre>`:`<p>已核对二进制文件 · ${esc(result.size)} 字节。请从相应成果打开或下载。</p>`,{wide:true});}
 async function trace(data){if(ui.dirty)throw new Error('请先保存当前编辑，再核对对应修订的来源。');const source=editorSnapshot();const view=await action('trace.inspect',{object_id:source.id,revision:source.revision,...(data.block?{block_id:data.block}:{}),...(data.component?{component_id:data.component}:{})});modal('科学内容溯源',tracePanel(view),{wide:true});}
 async function caption(data){
  const source=editorSnapshot(),refs=list(ui.draft.content.components),index=Number(data.index),ref=refs[index];if(!ref||(ref.id||ref.object_id)!==data.id)throw new Error('稿内图已经变化。');
  const adopted=ui.references[`${data.id}@${ref.revision}`],before=ref.caption??adopted?.content?.caption??'';
  modal('在原稿中改图注',field('图注','caption',before,'textarea','required')+'<p class="hint">更新本稿图注，不改变数据、来源图或科学执行权限。</p>',{submit:async v=>{requireEditor(source);ui.undo.push(clone(ui.draft));ref.caption=v.caption;ui.dirty=true;draw();}});
 }
 async function regionComment(data){
  if(data.standalone&&(ui.figurePreviewResult||ui.dirty||['queued','rendering'].includes(ui.figurePreviewStatus)))throw new Error('当前是未采用图形预览。先采用或取消预览，再给正式图添加批注。');
  const source=editorSnapshot(),ref=data.standalone?{id:source.id,revision:source.revision}:list(ui.draft.content.components)[Number(data.index)];if(!ref||(ref.id||ref.object_id)!==(data.standalone?source.id:data.id))throw new Error('图形定位已经变化。');
  const figure=clone(data.standalone?ui.object:ui.references[`${data.id}@${ref.revision}`]),sha=figureSavedPreviewSha(figure);
  if(!/^[a-f0-9]{64}$/.test(sha||''))throw new Error('此采用版本没有可批注的图形快照。');let bbox=[0,0,1,1];
  const dialog=modal('批图 · 整图或拖出区域',`<div class="region-comment-surface"><img src="/api/assets/${sha}" alt="${esc(figure.title)}" draggable="false"><div class="region-comment-box"></div></div><p class="hint">拖动选取区域；不选区域即批注整图。静态图批注不等于元素编辑。</p>${field('具体意见','text','','textarea','required')}`,{wide:true,submit:async v=>{requireEditor(source);await action('annotation.add',{object_id:source.id,revision:source.revision,anchor:data.standalone?figureRegionAnchor(figure,bbox):{component_id:data.id,component_revision:ref.revision,component_region:{bbox,coordinates:'whole_figure_normalized_top_left'},...(ref.after_block_id?{block_id:ref.after_block_id}:{}),quote:ref.caption||figure.content.caption||figure.title},text:v.text});await readEditorDetails(source);ui.workspacePanel='comments';draw();}});
  const surface=dialog.root.querySelector('.region-comment-surface'),box=surface.querySelector('.region-comment-box');let start;
  const point=e=>{const r=surface.querySelector('img').getBoundingClientRect();return [Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),Math.max(0,Math.min(1,(e.clientY-r.top)/r.height))];};
  surface.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();start=point(e);surface.setPointerCapture(e.pointerId);});
  surface.addEventListener('pointermove',e=>{if(!start)return;const p=point(e);bbox=[Math.min(start[0],p[0]),Math.min(start[1],p[1]),Math.abs(p[0]-start[0]),Math.abs(p[1]-start[1])];Object.assign(box.style,{left:bbox[0]*100+'%',top:bbox[1]*100+'%',width:bbox[2]*100+'%',height:bbox[3]*100+'%',display:'block'});});
  surface.addEventListener('pointerup',()=>{start=null;if(bbox[2]<.005||bbox[3]<.005)bbox=[0,0,1,1];});
 }
 async function figureRead(data){
  const ref=list(ui.draft.content.components)[Number(data.index)];if(!ref||(ref.id||ref.object_id)!==data.id)throw new Error('图形定位已变化。');
  const figure=ui.references[`${data.id}@${ref.revision}`],asset=figure?.metadata?.last_export?.assets?.['figure.png']||figure?.metadata?.last_export?.assets?.['figure.svg']||figure?.content?.preview,sha=typeof asset==='object'?asset.sha:asset;
  if(!/^[a-f0-9]{64}$/.test(sha||''))throw new Error('此采用版本尚无可读取的图像。');
  const dialog=modal('放大阅读 · '+figure.title,`<label class="field"><span>图像显示宽度（%）</span><input type="range" min="100" max="300" value="100" data-figure-read-zoom></label><div class="figure-reading-surface"><img src="/api/assets/${sha}" alt="${esc(figure.title)}"></div><p class="hint">采用修订 ${esc(ref.revision)}；仅放大已有图像，不改变成果或数据。</p>`,{wide:true});
  dialog.root.querySelector('[data-figure-read-zoom]').addEventListener('input',e=>dialog.root.querySelector('.figure-reading-surface img').style.width=e.target.value+'%');
 }
 async function round(data={}){
  if(ui.dirty||ui.sectionNoteDirty)throw new Error('请先保存正文和笔记，再发起准确版本的修订回合。');
  if(!['paper','report','note'].includes(ui.object?.kind))throw new Error('请打开一份可审阅稿件。');
  const source=editorSnapshot(),blocks=list(ui.object.content.blocks),annotations=list(ui.object.annotations).filter(a=>a.status!=='resolved'),providers=list(ui.data.providers).sort((a,b)=>Number(b.route==='deepseek_harness')-Number(a.route==='deepseek_harness'));
  const body=`<p>选择要修订的准确内容和原意见。正文与准备笔记的变化将分开决定。</p><details ${ui.selectedBlock?'':'open'}><summary>正文位置</summary>${blocks.map(b=>`<label class="round-target"><input type="checkbox" name="round-block" value="${esc(b.id)}" ${b.id===(data.block||ui.selectedBlock)?'checked':''}>${esc(b.text.slice(0,170)||'空段落')}</label>`).join('')}</details><details><summary>稿内图注</summary>${list(ui.object.content.components).filter(r=>r.caption!==undefined).map(r=>`<label class="round-target"><input type="checkbox" name="round-caption" value="${esc(r.id||r.object_id)}">${esc(r.caption.slice(0,170))}</label>`).join('')||'<p>先在稿内保存显式图注，再交给Agent修订。</p>'}</details><details open><summary>本回合意见</summary>${annotations.map(a=>`<label class="round-opinion"><input type="checkbox" name="round-opinion" value="${esc(a.id)}" ${a.id===data.annotation?'checked':''}><span>${esc(a.text)}</span></label>`).join('')||'<p>可在下面直接提出一条意见。</p>'}</details>${field('本次具体要求','request','','textarea','required')}<label class="round-target"><input type="checkbox" name="include-note">同时允许更新所选正文所属章节的工坊笔记</label>${select('科研搭档','provider',providers.map(p=>[p.id,p.label||p.id]))}<div class="field-grid">${field('最多模型调用','calls',6,'number','min="1" max="12" required')}${field('总执行秒数上限','seconds',180,'number','min="10" max="600" required')}</div><p class="hint">只提出文字/图注/准备笔记修订，不执行绘图、拟合或新科学计算；失败和用量保留。</p>`;
  modal('逐条修订回合',body,{wide:true,label:'提交有限修订',submit:async(v,form)=>{
   requireEditor(source);if(ui.dirty||ui.sectionNoteDirty)throw new Error('内容已经改变，请保存后重新发起。');
   const targets=[...form.querySelectorAll('[name=round-block]:checked')].map(el=>({object_id:source.id,expected_revision:source.revision,kind:'manuscript',block_id:el.value,exists:true}));
   targets.push(...[...form.querySelectorAll('[name=round-caption]:checked')].map(el=>({object_id:source.id,expected_revision:source.revision,kind:'manuscript',field:'caption',component_id:el.value})));
   if(v['include-note']){
    const section=sectionFor({...ui,draft:source.draft},targets.find(t=>t.block_id)?.block_id);
    if(!section)throw new Error('请先关联章节，并选择该章节中的正文。');
    const result=await action('article.section_note',{manuscript_id:source.id,section_id:section.id,expected_revision:source.revision,request_key:uid('round-note')});const note=result.note,b=list(note.content.blocks).find(b=>b.kind!=='heading');
    targets.push({object_id:note.id,expected_revision:note.revision,kind:'workshop_note',block_id:b?.id||uid('BLOCK'),exists:!!b});
   }
   if(!targets.length)throw new Error('请选择具体正文或图注。');
   const selected=[...form.querySelectorAll('[name=round-opinion]:checked')].map(el=>el.value),indices=targets.map((_,i)=>i),opinions=selected.map(id=>({id,annotation_id:id,target_indices:indices}));
   if(!opinions.length)opinions.push({id:uid('OPINION'),text:v.request,target_indices:indices});
   const result=await action('manuscript.revision.submit',manuscriptRoundSubmission({object:ui.object,targets,opinions,annotationIds:[],request:v.request,providerId:v.provider,budget:{max_model_calls:Number(v.calls),timeout_seconds:Number(v.seconds)},requestKey:uid('round')}));
   await refresh({render:false});ui.workspacePanel='review';await openManuscriptReview(result.id||result.task?.id);
  }});
 }
 function citation(key){
  const records=Object.values(ui.references).filter(o=>o.kind==='literature'&&(o.content.citation_key===key||o.metadata?.citation_key===key||o.content.cite_key===key||o.content.key===key||o.content.bibtex_key===key));
  const bib=ui.draft.content.bibtex||ui.draft.content.bibliography||'';
  const entry=typeof bib==='string'?bib.match(new RegExp('@[A-Za-z]+\\s*\\{'+key.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'\\s*,[\\s\\S]*?(?=\\n@|$)'))?.[0]:null;
  modal('引用 '+key,records.length?records.map(o=>`<h3>${esc(o.title)}</h3><p>${esc(o.content.authors?.join(', ')||o.content.author||'')} ${esc(o.content.year||'')}</p><p>实际阅读范围：${esc(o.content.read_scope||'未登记')}</p>${button('打开文献','open-object',{id:o.id},'button')}`).join(''):entry?`<pre>${esc(entry)}</pre><p class="hint">这是稿件中实际保存的BibTeX记录；引用支持范围另需核对。</p>`:'<p class="notice warning">此引用键尚未绑定可读取记录；不会补造作者、DOI或支持关系。</p>',{wide:true});
 }
 return {figureRead,organize,sectionNote,noteInput,noteAdd,noteSave,noteReturn,files,fileRead,trace,caption,regionComment,round,citation,notePanel:()=>sectionNotePanel(ui)};
}
