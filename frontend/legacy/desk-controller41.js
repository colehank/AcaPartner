import {readingKey41} from './reading41.js';
import {selectionForRegion} from './selection41.js';
import {editorStorageKey,readEditorDraft,listEditorDraftRecoveries,recoverEditorDraft} from './editor-storage41.js';
import {shell41,home41,readDesk41State,storeDesk41State,icon41} from './workspace41.js';
import {buildObjectTree,bindOutliner} from './outliner41.js';
import {createViewport,viewportControls,viewportStateKey} from './viewport41.js';
import {createRegions,embeddedRegionBridge} from './region41.js';
import {esc,kinds,modal,toast,button} from './ui.js';

/** Visual state is independent of scientific drafts. All source writes use existing editor actions. */
export function createDesk41({getContext,openObject,handle,draw,persist,getManifest,onLogout,onSelection=()=>{},onComponentLink,onComponentLinkCancelled,onComponentCommit,onComponentReturn,onRegionsReady=()=>{}}){
 const query=new URLSearchParams(location.search),embedded=query.get('embedded')==='1';
 const deskStateKey='research-partner:desk41:'+(embedded?'secondary':'primary');
 const state=readDesk41State(localStorage,deskStateKey);const saveState=()=>storeDesk41State(state,localStorage,deskStateKey);let tree=null,binder=null,viewport=null,noteViewport=null,resizeCleanup=null,initialized=false,lastViewportKey='',focusAnchor=null,regionLayout='',fitNext=false,treeOwner='',treeStateKey='',sourceSelection='',layoutRestored=embedded,restoringLayout=false;
 let deskId=embedded?query.get('storage_desk'):null;if(!deskId){try{deskId=sessionStorage.getItem('research-partner:desk41-session');if(!deskId){deskId=crypto.randomUUID();sessionStorage.setItem('research-partner:desk41-session',deskId);}}catch{deskId=crypto.randomUUID();}}
 const regionReadyWaiters=new Set();
 const redraw=()=>{saveState();if(getContext().data)draw();};
 const getRegionSummary=()=>{const c=getContext();return {objectId:c.view==='asset'?c.assetView?.id||'':c.object?.id||'',title:c.view==='asset'?c.assetView?.title||'':c.draft?.title||'',dirty:!!(c.dirty||c.sectionNoteDirty),saving:!!c.deskPending,projectId:c.object?.project_id||c.project||'',projectTitle:(c.objects||[]).find(o=>o.id===(c.object?.project_id||c.project))?.title||'',selectedItem:c.selectedItem||'',selectedBlock:c.selectedBlock||''};};
 const bridge=embedded?embeddedRegionBridge({getState:getRegionSummary,persist,onOpen:id=>openObject(id),onSelect:selectFromHost,onLogout,onComponentLink,onComponentLinkCancelled,onError:error=>toast(error?.message||String(error),'error')}):null;
 const regionUrl=new URL(location.href);regionUrl.searchParams.set('storage_desk',deskId);
 const regions=embedded?null:createRegions({url:regionUrl.href,getPrimaryId:()=>getContext().view==='asset'?getContext().assetView?.id||'':getContext().object?.id||'',onFocusPrimary:()=>document.querySelector('[data-region41-primary]')?.focus(),onOpenPrimary:id=>openObject(id),onComponentCommit,onComponentReturn,onStateChange:(next,reason)=>{for(const check of [...regionReadyWaiters])check(next);if(['ready','secondary-state','primary-state'].includes(reason))Promise.resolve().then(()=>onRegionsReady(reason)).catch(report);if(initialized&&layoutRestored&&getContext().data){try{localStorage.setItem(layoutKey(),JSON.stringify({objectId:next.secondaryObjectId,open:next.open,maximized:next.maximized}));}catch{}}const layout=JSON.stringify([next.open,next.maximized,next.secondaryObjectId]);if(initialized&&layout!==regionLayout){regionLayout=layout;if(!restoringLayout)fitNext=true;redraw();}else{document.querySelector('.desk41-areas')?.setAttribute('data-focused-region',next.focused||'primary');if(initialized&&['focus','secondary-state','primary-state','ready'].includes(reason))refreshOutliner(document);}},onRequestLogout:()=>handle('session-logout',{})});
 function waitComponentReady(descriptor){
  const ready=next=>next.ready&&!next.pendingPrimaryObjectId&&!next.pendingSecondaryObjectId&&!next.secondary.saving&&next.secondaryObjectId===descriptor.objectId&&next.primaryObjectId===descriptor.parentObjectId;
  if(ready(regions.getState()))return Promise.resolve();
  return new Promise((resolve,reject)=>{const timer=setTimeout(()=>done(new Error('副区未及时准备好，当前内容保留；可从原稿重试。')),15000);const check=next=>{if(next.primaryObjectId!==descriptor.parentObjectId)return done(new Error('原稿已切换，本次分区关联未建立。'));if(ready(next))done();};function done(error){clearTimeout(timer);regionReadyWaiters.delete(check);error?reject(error):resolve();}regionReadyWaiters.add(check);check(regions.getState());});
 }
 function layoutKey(){return 'research-partner:areas41:'+(getContext().data?.workspace_id||location.port)+':'+deskId;}
 function savedLayout(){let saved;try{saved=JSON.parse(localStorage.getItem(layoutKey())||'null');}catch{}return saved?.open&&saved.objectId&&saved.objectId!==getContext().object?.id&&((getContext().objects||[]).some(o=>o.id===saved.objectId)||resolveAsset(saved.objectId))?saved:null;}
 async function restoreLayout(){if(embedded)return;const saved=savedLayout();restoringLayout=true;try{if(saved){await regions.openSecondary(saved.objectId);if(['primary','secondary'].includes(saved.maximized))regions.toggleMaximize(saved.maximized);}}finally{restoringLayout=false;layoutRestored=true;}}
 function draftIdentity(id,type='draft'){return {workspace:getContext().data?.workspace_id||location.port||location.origin,desk:deskId,region:embedded?'secondary':'primary',objectId:id,type};}
 function draftKey(id,type='draft',region=embedded?'secondary':'primary'){if(!['primary','secondary'].includes(region))throw new Error('编辑区域无效。');return editorStorageKey({...draftIdentity(id,type),region});}
 function readDraft(id,type='draft'){return readEditorDraft(localStorage,draftIdentity(id,type));}
 function listDraftRecoveries(id,type='draft'){return listEditorDraftRecoveries(localStorage,draftIdentity(id,type));}
 function recoverDraft(candidate,options,id,type='draft'){return recoverEditorDraft(localStorage,draftIdentity(id,type),candidate,options);}
 function editorKey(){const c=getContext();return 'research-partner:editor41:'+(c.data?.workspace_id||location.port)+':'+(c.object?.id||'')+':'+(embedded?'secondary':'primary');}
 function rememberEditor(){const c=getContext();if(!c.object||c.view!=='workspace')return;try{localStorage.setItem(editorKey(),JSON.stringify({selectedBlock:c.selectedBlock,selectedItem:c.selectedItem,selectedItems:c.selectedItems,page:c.page,mode:c.manuscriptMode,panel:c.workspacePanel,noteId:c.sectionNote?.id,noteReturnBlock:c.noteReturnBlock}));}catch{}}
 function restoreEditor(){const c=getContext();let saved;try{saved=JSON.parse(localStorage.getItem(editorKey())||'null');}catch{}if(!saved)return;const blocks=c.draft?.content.blocks||[],items=(c.draft?.content.pages||[]).flatMap(p=>p.objects||[]),manifest=c.object.kind==='figure'?getManifest(c.object,c.draft.content):[],ids=new Set([...items,...manifest,...(c.draft?.content.nodes||[])].map(x=>x.id));c.selectedBlock=blocks.some(b=>b.id===saved.selectedBlock)?saved.selectedBlock:'';c.selectedItem=ids.has(saved.selectedItem)?saved.selectedItem:c.selectedItem;c.selectedItems=(saved.selectedItems||[]).filter(id=>ids.has(id));c.page=Math.max(0,Math.min((c.draft?.content.pages?.length||1)-1,Number(saved.page)||0));if(['read','edit','review'].includes(saved.mode)){c.manuscriptMode=saved.mode;c.preview=saved.mode!=='edit';}if(['comments','sources','format','direct','outline','review'].includes(saved.panel))c.workspacePanel=saved.panel;
 const note=(c.objects||[]).find(o=>o.id===saved.noteId&&o.kind==='workshop_note'&&!o.archived&&o.content?.manuscript_id===c.object.id);if(note){c.sectionNote=structuredClone(note);c.noteReturnBlock=saved.noteReturnBlock;c.sectionNoteDirty=false;try{const draft=JSON.parse(readDraft(note.id,'note')||'null');if(draft?.id===note.id&&draft.content?.manuscript_id===c.object.id){c.sectionNote=draft;c.sectionNoteDirty=true;}}catch{}if(saved.panel==='notes')c.workspacePanel='notes';}}
 function readingKey(id){return readingKey41(getContext().data?.workspace_id||location.port,id,embedded?'secondary':'primary');}
 function navigationKey(region=embedded?'secondary':'primary'){if(!['primary','secondary'].includes(region))throw new Error('编辑区域无效。');return `research-partner:navigation:${getContext().data?.workspace_id||location.port}:${deskId}:${region}`;}
 function componentKey(linkId){return `research-partner:component-link41:${getContext().data?.workspace_id||location.port}:${deskId}:${linkId}`;}
 function activeContext(){const c=getContext(),r=regions?.getState();if(r?.open&&r.focused==='secondary'){const source=resolveAsset(r.secondaryObjectId),object=(c.objects||[]).find(o=>o.id===(source?.ownerId||r.secondaryObjectId));if(object)return {...c,object,draft:null,project:object.project_id,selectedItem:r.secondary.selectedItem||'',selectedBlock:r.secondary.selectedBlock||'',view:source?'asset':'workspace',assetView:source?{...source,id:r.secondaryObjectId}:null,secondary:true,dirty:r.secondary.dirty};}return {...c,secondary:false};}
 function model(c=activeContext()){return buildObjectTree({objects:c.objects||[],projectId:c.project||'',activeObject:c.object,draft:c.draft,figureManifest:getManifest});}

 function resolveAsset(id){const match=/^source:([a-f0-9]{64}):([^:]+)$/i.exec(id||'');if(!match)return null;const c=getContext(),owner=(c.objects||[]).find(o=>o.id===match[2]);if(!owner)return null;const catalog=buildObjectTree({objects:c.objects||[],projectId:owner.project_id,activeObject:owner});const node=[...catalog.byKey.values()].find(n=>n.anchor?.type==='asset'&&n.anchor.assetSha===match[1].toLowerCase()&&n.anchor.ownerObjectIds?.includes(owner.id));return node?{sha:node.anchor.assetSha,title:node.assetFilename||node.assetLabel||node.title,role:node.anchor.role,ownerId:owner.id,ownerTitle:owner.title}:null;}
 function selected(){return state.selectedKeys?.map(key=>tree?.byKey.get(key)).find(Boolean);}
 async function openNode(node,{secondary=false}={}){
  if(!node)return;const c=getContext(),a=node.anchor||{},active=activeContext();
  if(a.type==='group')return;
  if(a.type==='asset'){const id='source:'+a.assetSha+':'+a.ownerObjectId;if((secondary||active.secondary)&&!embedded){await regions.openSecondary(id);redraw();}else await openObject(id);return;}
  if(secondary){
   if(!node.objectId)return;if(embedded){toast('请从主工作桌打开副编辑区。');return;}
   const occurrence=a.type==='component'&&a.parentObjectId===c.object?.id&&a.componentIndex!==undefined?{parent:c.object,parentRevision:c.object.revision,draft:c.draft,ref:c.draft?.content.components?.[a.componentIndex],id:a.componentId,index:a.componentIndex,revision:a.revision}:null;
   const valid=()=>occurrence&&Number.isSafeInteger(occurrence.index)&&occurrence.index>=0&&occurrence.ref&&(occurrence.ref.id||occurrence.ref.object_id)===occurrence.id&&occurrence.ref.revision===occurrence.revision;
   if(occurrence&&!valid())throw new Error('此组件位置或采用版本已变化，请从原稿重新进入。');
   const opened=await regions.openSecondary(node.objectId);
   if(occurrence&&opened){
    // Establish the existing app link only after the requested secondary is
    // ready. A newly created iframe reports open before its editor has loaded.
    const requireOccurrence=()=>{const current=getContext();if(current.object!==occurrence.parent||current.object.revision!==occurrence.parentRevision||current.draft!==occurrence.draft||current.view!=='workspace'||current.draft?.content.components?.[occurrence.index]!==occurrence.ref||!valid()||regions.getState().secondaryObjectId!==occurrence.id)throw new Error('原稿、组件位置或副区已变化；两边内容保留，请从原稿重新进入。');};
    requireOccurrence();await waitComponentReady({objectId:occurrence.id,parentObjectId:occurrence.parent.id});requireOccurrence();
    await handle('workbench-component',{id:occurrence.id,index:occurrence.index,revision:occurrence.revision});
   }
   redraw();return;
  }
  if(active.secondary&&!secondary){await regions.selectSecondary(selectionForRegion(node,true));return;}
  if(state.pinned&&c.object&&node.objectId!==c.object.id){toast('当前区已固定。可取消固定，或在副区打开所选成果。');return;}
  if(a.type==='component'&&a.parentObjectId===c.object?.id){await handle('workbench-component',{id:a.componentId,revision:a.revision,index:a.componentIndex});return;}
  if(node.objectId&&node.objectId!==c.object?.id){await openObject(node.objectId);}
  locate(node);
 }
 function previewNode(node,selection={}){const c=getContext(),a=node?.anchor||{};if(!embedded&&activeContext().secondary){const selection=selectionForRegion(node);if(selection.objectId&&a.type!=='group'&&a.type!=='asset')regions.selectSecondary(selection).catch(report);return;}let element;
  if(a.type==='component'&&a.parentObjectId===c.object?.id){c.selectedComponent={id:a.componentId,index:a.componentIndex,revision:a.revision};c.selectedBlock='';element=[...document.querySelectorAll('.manuscript-component')].find(e=>e.dataset.componentId===a.componentId&&Number(e.dataset.componentIndex)===a.componentIndex);document.querySelectorAll('.manuscript-component').forEach(e=>e.classList.toggle('tree-selected',e===element));}
  else if(node?.objectId===c.object?.id&&a.type==='block'){c.selectedBlock=a.blockId;c.selectedComponent=null;element=document.querySelector(`[data-block="${CSS.escape(a.blockId)}"]`);document.querySelectorAll('.manuscript-block').forEach(e=>e.classList.toggle('selected',e===element));}
  else if(node?.objectId===c.object?.id&&a.type==='artist'){c.selectedItem=a.artistId;c.selectedItems=(selection.nodes||[node]).filter(n=>n.objectId===c.object.id&&n.anchor?.artistId).map(n=>n.anchor.artistId);state.properties=true;document.querySelector('.desk41')?.classList.add('show-properties');document.querySelectorAll('.figure-hit').forEach(e=>e.classList.toggle('selected',c.selectedItems.includes(e.dataset.id)));onSelection();saveState();}
  if(element)element.scrollIntoView({block:'center',inline:'nearest'});rememberEditor();bridge?.publish();
 }
 function locate(node){const c=getContext(),a=node?.anchor||{};if(!node||node.objectId!==c.object?.id)return;
  if(a.type==='block'){c.selectedBlock=a.blockId||a.block_id||a.id;focusAnchor={type:'block',id:c.selectedBlock};draw();}
  else if(a.type==='artist'){c.selectedItem=a.artistId;focusAnchor={type:'artist',id:a.artistId};state.properties=true;draw();}
  else if(a.type==='page'||a.type==='canvas'){c.page=Number(a.pageIndex)||0;if(a.itemId){c.selectedItem=a.itemId;c.selectedItems=[a.itemId];}focusAnchor=a.itemId?{type:'canvas',id:a.itemId}:null;draw();}
 }
 function beforeDraw(){noteViewport?.destroy();noteViewport=null;viewport?.destroy();viewport=null;binder?.destroy();binder=null;resizeCleanup?.();resizeCleanup=null;}
 function attachViewport(){
  const c=getContext();if(!['workspace','asset'].includes(c.view)||!c.object)return;
  let frame=document.querySelector('.manuscript-surface'),surface=frame?.querySelector('.manuscript-page'),representation='manuscript',mode='paper';
  if(!surface){frame=document.querySelector('[data-figure-stage]');surface=frame?.querySelector('[data-figure-image]');representation='figure';mode='canvas';}
  if(!surface){surface=document.querySelector('[data-canvas]');if(surface){frame=surface.parentElement?.closest('.desk41-canvas-frame');if(!frame){frame=document.createElement('div');frame.className='desk41-canvas-frame';surface.before(frame);frame.append(surface);}representation='canvas:'+String(c.page||0);mode='canvas';}}
  if(!surface){frame=document.querySelector('.diagram-scroll');surface=frame?.querySelector('[data-diagram]');representation='diagram';mode='canvas';}
  if(!surface&&c.view==='asset'){frame=document.querySelector('[data-asset41-frame]');surface=frame?.querySelector('[data-asset41-surface]');representation='source:'+c.assetView.sha+':'+frame?.dataset.asset41ViewKind;mode=frame?.dataset.asset41ViewKind==='image'?'canvas':'table';if(['pdf','binary'].includes(frame?.dataset.asset41ViewKind))return;}
  if(!surface||!frame)return;
  const footer=document.createElement('div');footer.dataset.desk41Viewport='';footer.innerHTML=viewportControls();(document.querySelector('.artifact-editor')||document.querySelector('[data-asset41-viewer]'))?.append(footer);
  const key={objectId:(c.data?.workspace_id||location.port)+':'+(c.view==='asset'?c.assetView.id:c.object.id),representation,region:(embedded?'secondary':'primary')};
  let hasView=false;try{hasView=!!localStorage.getItem(viewportStateKey(key));}catch{}
  viewport=createViewport({frame,surface,key,mode,controls:footer.querySelector('.vp41-controls'),getSelection:()=>document.querySelector(c.selectedBlock?`[data-block="${CSS.escape(c.selectedBlock)}"]`:c.selectedItem?`[data-id="${CSS.escape(c.selectedItem)}"].figure-hit,[data-item="${CSS.escape(c.selectedItem)}"],[data-node="${CSS.escape(c.selectedItem)}"]`:':not(*)')});
  const identity=JSON.stringify(key);if(lastViewportKey!==identity){lastViewportKey=identity;}
  // The viewport restores keyed view state; initial views fit the available width.
  if((!hasView||fitNext)&&c.view!=='asset'){if(mode==='paper'){viewport.fitWidth();if(viewport.getState().zoom>1)viewport.setZoom(1);}else viewport.fit();fitNext=false;}
  for(const image of surface.querySelectorAll('img'))if(!image.complete)image.addEventListener('load',()=>viewport?.refresh(),{once:true});
  if(focusAnchor){const selector=focusAnchor.type==='block'?`[data-block="${CSS.escape(focusAnchor.id)}"]`:focusAnchor.type==='artist'?`.figure-hit[data-id="${CSS.escape(focusAnchor.id)}"]`:`[data-item="${CSS.escape(focusAnchor.id)}"]`;surface.querySelector(selector)?.scrollIntoView({block:'center',inline:'nearest'});focusAnchor=null;}
 }
 function attachNotes(root){const c=getContext(),frame=root.querySelector('.context-panel-body[data-panel="notes"]');if(!frame||!c.object)return;const surface=document.createElement('div');surface.className='desk41-note-surface';while(frame.firstChild)surface.append(frame.firstChild);frame.append(surface);const footer=document.createElement('div');footer.className='desk41-note-navigation';footer.innerHTML=viewportControls('notes');frame.parentElement.append(footer);noteViewport=createViewport({frame,surface,mode:'text',key:{objectId:(c.data?.workspace_id||location.port)+':'+(c.sectionNote?.id||c.object.id),representation:'workshop-notes',region:embedded?'secondary-notes':'primary-notes'},controls:footer.querySelector('.vp41-controls')});}
 function refreshOutliner(root){
  const c=activeContext(),owner=(c.project||'')+':'+(c.object?.id||'')+':'+(c.secondary?'secondary':'primary');if(owner!==treeOwner){treeOwner=owner;treeStateKey='research-partner:outliner41:'+(c.data?.workspace_id||location.port)+':'+owner;let saved={};try{saved=JSON.parse(localStorage.getItem(treeStateKey)||'{}');}catch{}Object.assign(state,{query:'',collapsedKeys:saved.collapsedKeys,selectedKeys:saved.selectedKeys||[],focusKey:saved.focusKey||null,rangeAnchorKey:null});sourceSelection='';}
  tree=model(c);const mount=root.querySelector('[data-desk41-tree]');if(!mount)return;
  if(binder)binder.update({tree,state});else binder=bindOutliner(mount,{tree,state,onSelect:(node,selection)=>{state.selectedKeys=selection.keys;state.focusKey=node.key;document.querySelector('[data-desk41-status]')?.replaceChildren(document.createTextNode(node.title));previewNode(node,selection);},onOpen:node=>openNode(node).catch(report),onStateChange:next=>{Object.assign(state,next);try{localStorage.setItem(treeStateKey,JSON.stringify(next));}catch{}saveState();}});
  const label=root.querySelector('.desk41-outliner>header strong');if(label){label.textContent=c.secondary?'副区 · 对象树':'项目内容';label.title=c.secondary?((c.objects||[]).find(o=>o.id===c.project)?.title||'')+(c.dirty?' · 副区有未保存改动，树结构按已保存成果显示':''):'';}
  const selection=(c.object?.id||'')+':'+(c.assetView?.sha||c.selectedBlock||c.selectedItem||'');if(binder&&sourceSelection!==selection){sourceSelection=selection;const node=[...tree.byKey.values()].find(n=>n.objectId===c.object?.id&&((c.assetView?.sha&&n.anchor?.assetSha===c.assetView.sha)||(c.selectedBlock&&n.anchor?.blockId===c.selectedBlock)||(c.selectedItem&&(n.anchor?.artistId===c.selectedItem||n.anchor?.itemId===c.selectedItem))));if(node)binder.setSelection([node.key],{reveal:true});}
 }
 async function selectFromHost({objectId,anchor,open=false}){const c=getContext();if(!objectId||!anchor)return false;
  if(objectId!==(c.view==='asset'?c.assetView?.id:c.object?.id)){if(!open)return false;await openObject(objectId);}
  const current=getContext();if(objectId!==(current.view==='asset'?current.assetView?.id:current.object?.id))return false;
  const a=anchor;let node={objectId,anchor:a};
  if(a.type==='component'){const ref=current.draft?.content.components?.[a.componentIndex];if(a.parentObjectId!==current.object?.id||!ref||(ref.id||ref.object_id)!==a.componentId||ref.revision!==a.revision)return false;node.objectId=a.componentId;if(open){await handle('workbench-component',{id:a.componentId,index:a.componentIndex,revision:a.revision});return true;}}
  else if(a.type==='block'&&!current.draft?.content.blocks?.some(b=>b.id===a.blockId))return false;
  else if(a.type==='artist'&&!getManifest(current.object,current.draft.content).some(x=>x.id===a.artistId))return false;
  else if(['page','canvas'].includes(a.type)){const page=current.draft?.content.pages?.[a.pageIndex];if(!page||a.itemId&&!page.objects?.some(x=>x.id===a.itemId))return false;}
  previewNode(node);if(open||['page','canvas'].includes(a.type))locate(node);publish();return true;
 }
 function afterDraw(root){
  // Seed the real layout before primary-state arrives: cold bootstrap is not a user resize.
  if(!initialized&&regions){const initial=regions.getState();regionLayout=JSON.stringify([initial.open,initial.maximized,initial.secondaryObjectId]);}
  initialized=true;root.querySelector('.desk41-areas')?.setAttribute('data-focused-region',regions?.getState().focused||'primary');refreshOutliner(root);
  root.querySelector('[data-desk41-search]')?.addEventListener('input',event=>{state.query=event.target.value;binder?.update({tree,state});});
  root.querySelectorAll('[data-desk41]').forEach(el=>el.addEventListener('click',()=>command(el.dataset.desk41).catch(report)));
  bindResize(root);attachViewport();attachNotes(root);regions?.attach(root);bridge?.publish();
  const pin=root.querySelector('[data-desk41=pin]');if(pin){pin.classList.toggle('active',state.pinned);pin.setAttribute('aria-pressed',String(!!state.pinned));}
 }
 async function command(name){const c=getContext();
  if(name==='tree'){state.outliner=!state.outliner;fitNext=true;redraw();}
  else if(name==='search'){if(!state.outliner){state.outliner=true;redraw();}document.querySelector('[data-outliner41-action=search]')?.focus();}
  else if(name==='project-picker')modal('切换研究项目',`<div class="desk41-project-picker">${(c.objects||[]).filter(o=>o.kind==='project').map(o=>button(o.title,'select-project',{id:o.id},'button full')).join('')}</div>`,{wide:false});
  else if(name==='sliders'){if(['paper','report','note','workshop_note'].includes(c.object?.kind)){c.workspacePanel=c.workspacePanel==='format'?null:'format';}else state.properties=!state.properties;fitNext=true;redraw();}
  else if(name==='pin'){state.pinned=!state.pinned;state.pinObject=state.pinned?c.object?.id||'':'';redraw();}
  else if(name==='fit'){if(embedded){await bridge?.requestMaximize?.();}else if(regions?.isOpen()){regions.toggleMaximize('primary');redraw();}else {state.outliner=!state.outliner;fitNext=true;redraw();}}
  else if(name==='close'){await bridge?.requestClose?.();}
  else if(name==='split'||name==='open-secondary'){
   if(embedded)return;
   // The global region control restores the retained editor. Opening a newly
   // selected object is the separate, explicit Outliner command below.
   const current=regions?.getState();
   if(name==='split'&&current?.secondaryObjectId&&!current.loggedOut){regions.focus('secondary');return;}
   let node=selected();if(!node||node.objectId===c.object?.id){node=[...tree.byKey.values()].find(n=>n.objectId&&n.objectId!==c.object?.id&&n.anchor?.type==='component'&&n.anchor?.parentObjectId===c.object?.id&&['figure','diagram'].includes(n.kind));}
   if(!node){toast('先在对象树选择另一份成果，再在副区打开。');state.outliner=true;redraw();return;}
   await openNode(node,{secondary:true});
  }else if(name==='open-selected')await openNode(selected());
 }
 function bindResize(root){const cleanups=[];root.querySelectorAll('[data-desk41-resize]').forEach(el=>{
  const isTree=el.dataset.desk41Resize==='outliner',vertical=()=>!isTree&&window.matchMedia('(max-width:1050px)').matches;
  const orient=()=>{el.setAttribute('aria-orientation',vertical()?'horizontal':'vertical');if(!isTree)el.setAttribute('aria-label',vertical()?'调整两个编辑区高度':'调整两个编辑区宽度');};orient();window.addEventListener('resize',orient);cleanups.push(()=>window.removeEventListener('resize',orient));
  const assign=event=>{const r=root.querySelector('.desk41-areas')?.getBoundingClientRect();if(isTree){const rail=root.querySelector('.desk41-rail')?.getBoundingClientRect().right||46;state.outlinerWidth=Math.max(190,Math.min(420,event.clientX-rail));root.querySelector('.desk41')?.style.setProperty('--desk41-outliner',state.outlinerWidth+'px');}else if(r){state.ratio=Math.max(.3,Math.min(.7,vertical()?(event.clientY-r.top)/r.height:(event.clientX-r.left)/r.width));root.querySelector('.desk41-areas').style.setProperty('--desk41-ratio',state.ratio);}regions?.attach(root);};
  el.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();el.setPointerCapture(event.pointerId);const move=e=>assign(e),end=()=>{el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',end);el.removeEventListener('pointercancel',end);saveState();regions?.setSplitRatio(state.ratio);fitNext=true;redraw();};el.addEventListener('pointermove',move);el.addEventListener('pointerup',end);el.addEventListener('pointercancel',end);cleanups.push(()=>{el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',end);el.removeEventListener('pointercancel',end);});});
  el.addEventListener('keydown',event=>{const keys=vertical()?['ArrowUp','ArrowDown']:['ArrowLeft','ArrowRight'];if(![...keys,'Home'].includes(event.key))return;event.preventDefault();const delta=event.key===keys[0]?-1:1;if(isTree)state.outlinerWidth=event.key==='Home'?252:Math.max(190,Math.min(420,state.outlinerWidth+delta*16));else state.ratio=event.key==='Home'?.55:Math.max(.3,Math.min(.7,state.ratio+delta*.025));regions?.setSplitRatio(state.ratio);fitNext=true;redraw();});
 });resizeCleanup=()=>cleanups.forEach(fn=>fn());}
 const report=error=>toast(error?.message||String(error),'error');
 function render(body){const c=getContext(),rs=regions?.getState(),saved=!embedded&&!layoutRestored?savedLayout():null;
  // Restore the saved geometry before mounting the first viewport. A temporary
  // full-width frame would clamp scroll coordinates and overwrite the saved view.
  return shell41(c,{body,state,embedded,split:!!(rs?.open||saved),maximized:rs?.open?rs.maximized:saved?.maximized,restoring:!!saved&&!rs?.ready});}
 async function beforeOpen(id){return embedded?bridge.requestOpen(id):regions.guardOpen(id);}
 function finishOpen(){if(embedded)bridge.finishOpen();else regions.finishPrimaryOpen();publish();}
 function publish(){bridge?.publish();}
 function help(){modal('工作桌操作',`<p>从项目对象树选中对象，双击或按 Enter 打开。树中的章节和图元素可定位到当前成果。</p><p>在副区打开另一份稿件、图或材料，拖动分隔线调整区域；聚焦按钮恢复或最大化区域。副区收起后保留草稿，同一成果不会在两区重复编辑。</p><p>中键拖动，或按住空格后拖动平移；Ctrl / Command + 滚轮缩放；底部可适合页面、宽度、选区或回到 100%。输入文字时空格与快捷键保留原意。</p><p>导航、缩放和面板状态不改变科研内容。正文、图形和笔记仍通过真实服务保存；源稿编译、Agent 执行和科学授权状态分别核对。</p>`,{wide:true});}
 return {state,embedded,render,restoreLayout,componentKey,regionsState:()=>regions?.getState(),focusPrimary:()=>regions?.focus('primary'),attachComponentLink:async(d,options)=>{if(!regions)return false;await regions.openSecondary(d.objectId);await waitComponentReady(d);return regions.attachComponentLink(d,options);},restoreComponentLink:async(d,options)=>{if(!regions)return false;await waitComponentReady(d);return regions.restoreComponentLink(d,options);},notifyComponentCommit:d=>bridge?.notifyComponentCommit(d),requestComponentReturn:d=>bridge?.requestComponentReturn(d),resolveAsset,draftKey,readDraft,listDraftRecoveries,recoverDraft,rememberEditor,restoreEditor,home:()=>home41(getContext()),navigationKey,readingKey,beforeDraw,afterDraw,beforeOpen,finishOpen,publish,help,
  detachViewport:()=>{viewport?.destroy();viewport=null;document.querySelector('[data-desk41-viewport]')?.remove();},
  reattachViewport:attachViewport,
  prepareLogout:async()=>{if(embedded){bridge.requestLogout?.();return false;}const s=await regions.prepareClose();if(s?.dirty||s?.saving||s?.secondary?.dirty||s?.secondary?.saving){regions.resume();toast('副编辑区还有未保存内容或正在保存，请先处理后退出。');return false;}return true;},
  loggedOut:()=>regions?.logout(),resume:()=>regions?.resume(),hide:()=>regions?.close(),
  getViewport:()=>viewport,getRegions:()=>regions,getTree:()=>tree};
}
