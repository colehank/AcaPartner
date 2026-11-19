import {esc,button,clone} from './ui.js';

// Use only server-visible objects and explicit outgoing links. Project membership
// and reverse links never imply that a concept is associated with a project.
export function associatedProjects(c,conceptId){
 const concept=c.objects.find(o=>o.id===conceptId&&o.kind==='concept'&&!o.archived);
 if(!concept)return [];
 const projects=new Map(c.objects.filter(o=>o.kind==='project'&&!o.archived).map(o=>[o.id,o]));
 return (c.relations||[]).filter(r=>r.src===concept.id&&r.type==='related'&&['candidate','confirmed'].includes(r.status)&&!['withdrawn','rejected','reject','superseded','inactive'].includes(r.review_status||r.metadata?.review_status)&&projects.has(r.dst)).map(relation=>({concept,project:projects.get(relation.dst),relation}));
}
export function associatedProjectsPanel(c,conceptId){
 const concept=c.objects.find(o=>o.id===conceptId&&o.kind==='concept'&&!o.archived);
 if(!concept)return '';
 const links=associatedProjects(c,conceptId);
 return `<section class="graph-associated" aria-label="关联项目"><h3>关联项目</h3>${links.length?links.map(({project,relation})=>`<article class="graph-associated-project"><div><strong>${esc(project.title)}</strong><span class="status">${relation.status==='confirmed'?'关联 · 已确认':'关联 · 候选（未科学确认）'}</span></div><div class="button-group">${button('查看项目的问题与成果','graph-project',{concept:conceptId,id:project.id,relation:relation.id},'button small')}${button('关系依据','graph-relation',{id:relation.id},'text-button small')}</div></article>`).join(''):'<p class="hint">当前可读目录中尚无已保存的有效项目关联。</p>'}<p class="hint">关联单独列出，不改变概念层级；候选关联不代表科学确认。</p></section>`;
}
// Navigation belongs to the original route; editable state belongs to the most
// recent session for each object. Neither registry includes graph positions.
const navigationFields=['view','project','graphDomain','graphProjectRoot','graphSearch','graphKind','graphDirectory','zoom','selectedBlock','selectedItem','selectedItems','page','preview','tab'];
const editorFields=['object','draft','dirty','recovered','remoteRevision','references','referenceErrors','undo','redo'];
const pickEditor=c=>Object.fromEntries(editorFields.map(key=>[key,c[key]]));
export function rememberGraphEditor(c,generation){
 const saved=c.graphReturn;if(!saved||c.view!=='workspace'||!c.object||!c.draft)return;
 const previous=saved.editors.get(c.object.id);
 saved.editors.set(c.object.id,{...pickEditor(c),generation:generation??(previous?.object===c.object?previous.generation:undefined)});
}
// A late save receipt may update its departed editor, never a subsequently
// reopened session for the same ID. Local edits retain their actual merge base.
export function settleGraphEditorWrite(c,source,result,{restore=false}={}){
 const saved=c.graphReturn,editor=saved?.editors.get(source.id);
 if(!editor||editor.object!==source.object||editor.generation!==source.generation||editor.object.revision!==source.revision)return false;
 const equal=(a,b)=>a?.title===b?.title&&JSON.stringify(a?.content)===JSON.stringify(b?.content);
 const changed=!equal(editor.draft,source.draft),safeBase=equal(result,source.draft);
 editor.object={...editor.object,...result};
 for(const key of ['canonical_source_sha256','exports','review_records'])delete editor.object[key];
 if(changed&&!safeBase){editor.object.revision=source.revision;editor.remoteRevision=result.revision;}
 else{editor.remoteRevision=null;editor.recovered=false;}
 if(!changed){if(restore&&!equal(editor.draft,result))editor.undo=[...(editor.undo||[]),clone(editor.draft)];editor.draft={title:result.title,content:clone(result.content)};}
 editor.dirty=changed;
 // The same editor can remain parked behind the graph. Keep it in sync so a
 // normal workspace navigation cannot revive its pre-save revision either.
 if(c.object===source.object&&c.view!=='workspace')Object.assign(c,pickEditor(editor));
 return true;
}
export function enterAssociatedProject(c,{concept,id,relation},{generation}={}){
 const link=associatedProjects(c,concept).find(x=>x.project.id===id&&x.relation.id===relation);
 if(!link)throw new Error('关联或目标已不在当前可读目录中，请重新查看概念。');
 const state=Object.fromEntries(navigationFields.map(key=>[key,c[key]]));state.collapsed=new Set(c.collapsed);
 const originEditor=pickEditor(c),editors=new Map();
 if(c.object&&c.draft)editors.set(c.object.id,{...originEditor,generation});
 c.graphReturn={conceptId:concept,state,originEditor,originEditorId:c.object?.id,editors};
 c.project=id;c.view='graph';c.graphDomain='';c.graphProjectRoot=id;c.graphSearch='';c.graphKind='';c.graphDirectory=true;
 const scopedIds=new Set(c.objects.filter(o=>o.id===id||o.project_id===id).map(o=>o.id));
 c.collapsed=new Set([...c.collapsed].filter(x=>!scopedIds.has(x)));
 return link.project;
}
export function returnFromAssociatedProject(c){
 const saved=c.graphReturn;if(!saved)return false;
 rememberGraphEditor(c);
 const readable=new Map(c.objects.filter(o=>!o.archived).map(o=>[o.id,o]));
 const editor=saved.editors.get(saved.originEditorId)||saved.originEditor;
 Object.assign(c,saved.state,pickEditor(editor),{collapsed:new Set(saved.state.collapsed),graphReturn:null});
 if(c.project&&!readable.has(c.project))c.project='';
 if(c.graphDomain&&!readable.has(c.graphDomain))c.graphDomain='';
 if(c.graphProjectRoot&&!readable.has(c.graphProjectRoot))c.graphProjectRoot='';
 if(c.object&&!readable.has(c.object.id)){c.object=null;c.draft=null;c.dirty=false;c.references={};c.referenceErrors={};c.undo=[];c.redo=[];c.selectedBlock='';c.selectedItem='';c.selectedItems=[];c.view='graph';}
 else if(c.object){const current=readable.get(c.object.id);if(current.revision>c.object.revision)c.remoteRevision=Math.max(c.remoteRevision||0,current.revision);}
 return true;
}
export function graphReturnPanel(c){
 if(!c.graphReturn)return '';
 const concept=c.objects.find(o=>o.id===c.graphReturn.conceptId&&!o.archived);
 const suffix=c.graphReturn.state.view==='workspace'?'概念':'概念域';
 return `<div class="graph-return">${button(concept?`返回“${concept.title}”${suffix}`:'返回原浏览位置','graph-project-return',{},'button small')}<span class="hint">本次页面内保留原筛选与编辑状态</span></div>`;
}
