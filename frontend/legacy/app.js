import {locateFigureAnnotation41,clearFigureAnnotation41} from './figure-annotation41.js';
import {packTrail41,unpackTrail41} from './trail-codec41.js';
import {createVisualIntentStore} from './visual-intent41.js';
import {sameJSON41,visualCommitRequest41,rebaseVisualDraft41,rebaseVisualHistory41} from './visual-commit41.js';
import {captureReading41,restoreReading41} from './reading41.js';
import {renderAssetViewer,bindAssetViewer} from './asset-viewer41.js';
import {createDesk41} from './desk-controller41.js';
import {areaTools41} from './workspace41.js';
import {createArticleController} from './article-controller.js';
import {sectionFor} from './article-ui.js';
import {createFigurePreviewController,figureDisplayObject,figureSourceState} from './figure-preview-controller.js';
import {bindColorControls} from './color-controls.js';
import {cmapScopeTargets} from './cmap-scope.js';
import {manuscriptDraftChanges,manuscriptDirectEditPanel,manuscriptFormatPanel,defaultManuscriptFormat} from './manuscript-direct-edit.js';
import {bindFigureInteraction,updateFigurePreview,figureArtistAnchor,createFigureRenderSession,createFigureCodeSession} from './figure-interaction.js';
import {workbenchHome,workbenchAll,shellNavigation,documentOutline,workbenchGroups,scholarlyKinds,workbenchRole} from './workbench.js';
import {manuscriptRevisionFields,manuscriptRevisionSubmission,manuscriptReviewPanel,createManuscriptReviewController} from './manuscript-review.js';
import {isExtensionWorkshop,workshopIdentity,extensionExecutionLabel,extensionWorkshopPanel} from './extension-workshop.js';
import {editConventions} from './conventions-editor.js';
import {recoveryEntry,recoveryPreview,recoverySubmission} from './native-recovery.js';
import {canOpenFailedPlanner,failedChildRevisionFields,failedChildRevisionSubmission} from './cycle-child-revision.js';
import {managementFields,managementSubmission,managementPanel} from './project-management.js';
import {sourceImpacts,impactPanel,consumerImpactLocations,assertImpactLocation} from './source-impact.js';
import {paperExportNotice,syncPaperSourceIdentity} from './paper-source.js';
import {createDevelopmentView} from './development-status.js';
import {createExportSession} from './export-controller.js';
import {documentReferences,referenceKey,readExactReference,referenceFailure,referenceReading,sourceReferencePanel} from './claim-evidence.js';
import {figureManifest,updatedFigureOverlays,overlayLayers} from './figure-properties.js';
import {executionFields,executionSubmission} from './growth-execution.js';
import {assessmentFields,assessmentSubmission} from './growth-assessment.js';
import {growthCard,growthFields,growthSubmission} from './growth.js';
import {cycleDetail,phases as cyclePhases} from './cycle-view.js';
import {finalRevisionPanel,canStageFinalRevision,finalRevisionFields,finalRevisionSubmission} from './cycle-final-handoff.js';
import {revisionFields,revisionSubmission,revisionReports,candidateReading,canStageRevision} from './cycle-handoff.js';
import {projectArtifacts,entryNavigation,objectLink} from './navigation.js';
import {resolutionRequest,resolutionSignature,resolutionPanel,chosenMaterialRefs,cycleFields,cycleParameters,acquisitionFields,acquisitionPanel} from './commission-resolver.js';
import {esc,clone,uid,kinds,status,date,button,empty,list,pretty,errorMessage,assetURL,safeURL,toast,modal,field,select,diff} from './ui.js';
import {renderEditor,newContent,canvasKinds,bindCanvasDrag} from './editors.js';
import {documentImageOccurrences,registeredDocumentAssetURL} from './document-markdown.js';
import {captureDocumentTarget,documentTargetIsCurrent,uploadAssetFile,applyDocumentImage} from './document-image-controller.js';
import {objectSearchText} from './ui.js';
import {graphView,bindGraph} from './graph.js';
import {associatedProjectsPanel,enterAssociatedProject,returnFromAssociatedProject,graphReturnPanel,rememberGraphEditor,settleGraphEditorWrite} from './graph-navigation.js';
import {graphSubmission,reconciliationSlot,fillGraphDraft} from './graph-dialog.js';
import {graphReviewPanel,proposalView,relationView,mergePreview,mergeRequest,relationEditFields,relationUpdate} from './graph-review.js';
import {accessStatus,login,logout,accessForm} from './auth.js';
import {workshopRecipes,workshopKey,workshopHelp,workshopRequest,registeredSHA,canGuide,canExtendBudget,canReviseCandidate,diagramReference,budgetExtension,exportFormats,growthStatus,packageExtension} from './workflows.js';
import {feedbackCard,feedbackFields,feedbackValues,feedbackSubmission,feedbackCommission,scopeNames,timingNames} from './feedback.js';
import {questionNeedsAttention,questionsPanel,questionAnswerFields,questionDetails,questionReassessFields} from './questions.js';

const app=document.querySelector('#app');
const developmentView=createDevelopmentView();
const ui={trackChanges:true,navExpanded:false,figurePropertyTab:'layout',figureZoom:1,figurePreviewResult:null,figurePreviewStatus:'saved',auth:null,authGate:false,data:null,view:'projects',project:'',object:null,draft:null,dirty:false,recovered:false,remoteRevision:null,selectedBlock:'',selectedItem:'',selectedItems:[],references:{},page:0,preview:true,manuscriptMode:'read',workspacePanel:null,workbenchFilter:'all',expandedCollections:new Set(),componentTrail:[],textSelection:null,tab:'tasks',graphSearch:'',graphKind:'',graphDomain:'',graphProjectRoot:'',graphReturn:null,graphDirectory:false,collapsed:new Set(),zoom:1,workshopRequestKey:uid('workshop'),undo:[],redo:[],workshop:null,literatureResults:[],online:true};
let pending=0,typingTimer=null,loadCounter=0,assetDisposer=null,assetAbort=null;
function persistWorkspaceDrafts(){rememberReadingPosition();if(ui.object)rememberComponentTrail();if((ui.dirty||ui.object&&ui.draftStorageError41===ui.object.id)&&persistDraft()===false)throw new Error('无法保留正文草稿及编辑历史，当前编辑区保持打开。');if(ui.sectionNoteDirty&&ui.sectionNote)localStorage.setItem(desk.draftKey(ui.sectionNote.id,'note'),JSON.stringify(ui.sectionNote));return {objectId:ui.object?.id||'',dirty:!!(ui.dirty||ui.sectionNoteDirty),saving:pending>0};}

let manuscriptReviewController=null;
let figurePreviewController=null,figureInteractionDisposer=null,colorDisposer=null;
function updateDeskSelection(){if(ui.object?.kind!=='figure')return;const fragment=document.createElement('template');fragment.innerHTML=renderEditor(context());for(const selector of ['[data-figure-properties]','.selected-figure-object']){const old=app.querySelector(selector),fresh=fragment.content.querySelector(selector);if(old&&fresh)old.replaceWith(fresh);}const select=app.querySelector('[data-edit=figure-select]');if(select)select.value=ui.selectedItem;bindEditorCanvas(app);}
function figureVisualObject(){return figureDisplayObject(ui.object,ui.figurePreviewResult);}
function writeFigurePreviewStatus(){const el=document.querySelector('[data-figure-status]');if(!el)return;el.textContent=ui.figurePreviewError?`${ui.figurePreviewStatus==='source_changed'?'预览暂停':'预览失败'}：${ui.figurePreviewError} · 草稿保留`:['queued','rendering'].includes(ui.figurePreviewStatus)?'正在渲染草稿 · 旧图保留':ui.figurePreviewResult?'草稿预览 · 尚未采用':ui.dirty?'有未采用改动':'已保存图形';}
function ensureFigurePreviewController(){
 if(figurePreviewController)return figurePreviewController;
 const source=editorSnapshot();
 figurePreviewController=createFigurePreviewController({snapshot:()=>({id:ui.object?.id,revision:ui.object?.revision,generation:loadCounter,selection:ui.selectedItem,sourceSha:ui.object?.canonical_source_sha256,sourceState:figureSourceState(ui.draft?.content),overlays:overlayLayers(ui.draft?.content||{})}),request:(...args)=>action(...args,{notifyError:false}),onState:state=>{if(!sameEditor(source))return;ui.figurePreviewStatus=state.status;ui.figurePreviewError=state.error?.message||'';writeFigurePreviewStatus();},onResult:result=>{if(!sameEditor(source))return;ui.figurePreviewResult=result;ui.figurePreviewError='';refreshFigureSurface();}});
 return figurePreviewController;
}
function scheduleFigurePreview({immediate=false}={}){
 if(ui.object?.kind!=='figure'||ui.draft.content.composition||ui.draft.content.editable_source_available===false)return;
 for(const key of ['script_asset','script','spec','parameters','input_assets'])if(JSON.stringify(ui.draft.content[key])!==JSON.stringify(ui.object.content[key])){ui.figurePreviewError='绘图来源已修改；先保存和授权，再重绘此来源。';writeFigurePreviewStatus();return;}
 ensureFigurePreviewController().schedule({immediate});
}
function refreshFigureSurface(){
 if(ui.object?.kind!=='figure')return;const current=app.querySelector('[data-figure-image]');if(!current){draw();return;}
 desk.detachViewport();const stage=app.querySelector('[data-figure-stage]'),position={x:stage?.scrollLeft||0,y:stage?.scrollTop||0},fragment=document.createElement('template');fragment.innerHTML=renderEditor(context());const next=fragment.content.querySelector('[data-figure-image]');if(!next)return;current.replaceWith(next);
 const picker=app.querySelector('[data-edit=figure-select]'),fresh=fragment.content.querySelector('[data-edit=figure-select]');if(picker&&fresh)picker.innerHTML=fresh.innerHTML;
 const tree=app.querySelector('.figure-object-tree'),freshTree=fragment.content.querySelector('.figure-object-tree');if(tree&&freshTree)tree.innerHTML=freshTree.innerHTML;
 const properties=app.querySelector('[data-figure-properties]'),freshProperties=fragment.content.querySelector('[data-figure-properties]'),inspector=app.querySelector('.figure-inspector'),scroll=inspector?.scrollTop||0;
 if(properties&&freshProperties){if(!properties.contains(document.activeElement))properties.replaceWith(freshProperties);else{const scope=properties.querySelector('.cmap-targets'),freshScope=freshProperties.querySelector('.cmap-targets');if(scope&&freshScope)scope.innerHTML=freshScope.innerHTML;}}
 bindEditorCanvas(app);desk.reattachViewport();if(stage){stage.scrollLeft=position.x;stage.scrollTop=position.y;}writeFigurePreviewStatus();
 if(inspector)inspector.scrollTop=scroll;
}
function setFigureOverlay(key,value,{redraw=false}={}){
 const manifest=figureManifest(figureVisualObject(),ui.draft.content),item=manifest.find(x=>x.id===ui.selectedItem);let content=ui.draft.content;
 const scope=key==='cmap'?cmapScopeTargets(manifest,item,content,ui.figureCmapScope||'matching'):null;
 if(scope?.needsEncoding)throw new Error('尚无当前来源的可核验数值编码。请等图形预览完成；若仍不可核验，请明确选择“仅当前”并核对整图。');
 const targets=scope?scope.targets:[item];
 for(const target of targets)content={...content,overlays:updatedFigureOverlays(content,target,key,value)};
 mutate(o=>o.content.overlays=content.overlays,redraw);
 for(const input of document.querySelectorAll(`[data-edit="overlay-${CSS.escape(key)}"]`)){if(document.activeElement!==input)input.value=Array.isArray(value)?JSON.stringify(value):String(value);}
 const native=document.querySelector(`[data-color-native="${CSS.escape(key)}"]`);if(native&&/^#[a-f0-9]{6}$/i.test(value))native.value=value;
 if(key==='cmap')for(const option of app.querySelectorAll('[data-action="figure-cmap"]')){const active=option.dataset.value===value;option.classList.toggle('active',active);option.setAttribute('aria-pressed',String(active));}
 updateFigurePreview(app,{object:figureVisualObject(),content:ui.draft.content,dirty:ui.dirty});scheduleFigurePreview();
}
function requireSavedFigureAnchor(){if(ui.figurePreviewResult||ui.dirty||figurePreviewController?.isBusy())throw new Error('当前是未采用图形预览。先采用或取消预览，再给正式图添加批注。');if(ui.object.content.editable_source_available!==false&&!ui.object.content.composition){const source=ui.object.metadata?.last_export?.provenance;if(!source||source.object_id!==ui.object.id||source.revision!==ui.object.revision)throw new Error('当前图像仍是旧来源的渲染；请明确重绘当前保存版本后批注。');}}
let manuscriptEditingRead=0;
function invalidateManuscriptEditing(){manuscriptEditingRead++;ui.manuscriptDirectState=null;ui.manuscriptDirectLoading=false;ui.manuscriptDirectError='';}
function manuscriptEditingCurrent(){const view=ui.manuscriptDirectState;return view?.object_id===ui.object?.id&&Number.isInteger(view.current_revision)&&view.current_revision>=knownEditorRevision();}
async function loadManuscriptEditing({proposalId=null}={}){
 if(!ui.object?.content?.blocks||!['paper','report','note'].includes(ui.object.kind))return;const source=editorSnapshot();
 invalidateManuscriptEditing();const token=manuscriptEditingRead;ui.manuscriptDirectLoading=true;if(ui.workspacePanel==='direct')draw();
 const requests=[action('manuscript.edit.view',{object_id:source.id,...(proposalId?{proposal_id:proposalId}:{})},{notifyError:false})];
 // Format controls are a separate local draft. A revision refresh may only
 // initialize them; it must not replace values the operator has already edited.
 if(ui.manuscriptFormat==null)requests.push(action('manuscript.format.view',{object_id:source.id},{notifyError:false}));
 const values=await Promise.allSettled(requests);
 if(token!==manuscriptEditingRead||!sameEditor(source))return;
 ui.manuscriptDirectLoading=false;
 if(ui.object.revision!==source.revision){ui.manuscriptDirectError='稿件版本已变化，请重新读取';draw();return;}
 const view=values[0].status==='fulfilled'?values[0].value:null;
 if(view?.object_id===source.id&&Number.isInteger(view.current_revision)&&view.current_revision>=knownEditorRevision()&&(!proposalId||view.proposal_id===proposalId))ui.manuscriptDirectState=view;
 else ui.manuscriptDirectError=values[0].status==='rejected'?values[0].reason?.message||'无法读取修订':'修订来源或当前版本不匹配，请重新读取';
 if(values[1]?.status==='fulfilled'&&ui.manuscriptFormat==null)ui.manuscriptFormat=values[1].value.format;
 draw();
}
async function trackManuscriptDraft(){
 const source=editorSnapshot(),changes=manuscriptDraftChanges(source.object.content.blocks||[],source.draft.content.blocks||[]);
 if(!changes.length){ui.workspacePanel='direct';draw();toast('尚无文字增删改动。');return;}
 const rest=content=>Object.fromEntries(Object.entries(content).filter(([k])=>k!=='blocks'));
 if(JSON.stringify(rest(source.object.content))!==JSON.stringify(rest(source.draft.content)))throw new Error('还有引用、图或其他改动，请与文字修订分别保存；当前草稿保留。');
 const view=await action('manuscript.edit.track',{object_id:source.id,expected_revision:source.revision,changes,request_key:uid('TEXT-TRACK')});
 if(!sameEditor(source))return;
 if(ui.object.revision!==source.revision){if(!manuscriptEditingCurrent())invalidateManuscriptEditing();toast('文字候选已记录，但稿件版本又有变化；本机编辑保留，请重新读取修订。');return;}
 invalidateManuscriptEditing();
 ui.manuscriptDirectState=view;ui.manuscriptRevisionView='marked';ui.workspacePanel='direct';
 if(draftEqual(ui.draft,source.draft)){ui.draft={title:ui.object.title,content:clone(ui.object.content)};ui.dirty=false;ui.recovered=false;localStorage.removeItem(draftKey(source.id));}
 draw();toast('完整文字候选已记录；逐项接受后才更新正文。');
}
async function decideDirectText(data){
 const source=editorSnapshot(),view=ui.manuscriptDirectState;if(!view?.proposal_id||!manuscriptEditingCurrent())throw new Error('请先读取当前文字修订。');
 const result=await action('manuscript.edit.decide',{object_id:source.id,proposal_id:view.proposal_id,expected_revision:source.revision,expected_decision_version:view.decision_version,decisions:[{change_id:data.change,decision:data.decision}],request_key:uid('TEXT-DECIDE')});
 if(sameEditor(source))invalidateManuscriptEditing();
 if(result.source_changed&&result.object)await finishManuscriptRevision(source,result.object);
 if(sameEditor(source)){ui.manuscriptRevisionView='clean';await loadManuscriptEditing({proposalId:view.proposal_id});}
}
async function saveManuscriptFormat(){
 const source=editorSnapshot(),format={...defaultManuscriptFormat,...ui.manuscriptFormat};
 const result=await action('manuscript.format.save',{object_id:source.id,expected_revision:source.revision,format});
 if(result.object)await finishManuscriptRevision(source,result.object);
 if(sameEditor(source)){ui.manuscriptFormat=result.format;draw();}
}
async function renderManuscriptFormat(kind){
 if(ui.dirty)throw new Error('先记录文字修订或保存源稿，再生成准确的最新稿。');
 const source=editorSnapshot();ui.manuscriptFormatBusy=true;ui.manuscriptFormatError='';draw();
 try{
  // Saving format or adopting a figure can invalidate the cached proposal.
  // Resolve the complete current projection before choosing the render source;
  // a failed read must not silently turn "latest candidate" into saved prose.
  if(!manuscriptEditingCurrent())await loadManuscriptEditing();
  if(!sameEditor(source)||ui.object.revision!==source.revision)return;
  if(ui.dirty)throw new Error('读取修订期间又有本地修改；草稿保留，请先记录修订或保存。');
  if(!manuscriptEditingCurrent())throw new Error('无法核对当前文字修订，请重新读取后再生成最新稿。'+(ui.manuscriptDirectError||''));
  const proposal=ui.manuscriptDirectState;
  const result=await action('manuscript.format.'+kind,{object_id:source.id,expected_revision:source.revision,format_config:{...defaultManuscriptFormat,...ui.manuscriptFormat},...(proposal?.proposal_id&&!proposal.settled?{proposal_id:proposal.proposal_id}:ui.manuscriptReviewTask?{revision_task_id:ui.manuscriptReviewTask}:{})},{notifyError:false});
  if(!sameEditor(source))return;
  if(kind==='render'&&result.provenance?.compiled!==true)throw new Error('没有返回已编译的实际稿件；源稿生成不代表渲染成功。');
  ui.manuscriptRendered=result;
 }catch(error){if(sameEditor(source)){ui.manuscriptFormatError=error.message;ui.manuscriptRendered=null;}}
 finally{if(sameEditor(source)){ui.manuscriptFormatBusy=false;draw();}}
}
const article=createArticleController({ui,action,api,draw,refresh,noteDraftKey:id=>desk.draftKey(id,'note'),readNoteDraft:id=>desk.readDraft(id,'note'),editorSnapshot,requireEditor,readEditorDetails,finishManuscriptRevision,openManuscriptReview});
const draftKey=id=>desk.draftKey(id);
const objects=()=>[...new Map([...list(ui.data?.projects),...list(ui.data?.objects)].map(o=>[o.id,o])).values()];
const projects=()=>list(ui.data?.projects).length?list(ui.data.projects):objects().filter(o=>o.kind==='project');
const currentProject=()=>projects().find(p=>p.id===ui.project);
const currentObjects=()=>objects().filter(o=>o.kind!=='project'&&(!ui.project||o.project_id===ui.project)&&!o.archived);
const objectOptions=()=>currentObjects().map(o=>[o.id,`${kinds[o.kind]||o.kind} · ${o.title}`]);
const context=()=>Object.assign(ui,{objects:objects(),relations:list(ui.data?.relations),projectTitle:currentProject()?.title||'',graphDirectory:ui.graphDirectory});
const desk=createDesk41({getContext:context,openObject,handle,draw,persist:persistWorkspaceDrafts,getManifest:figureManifest,onSelection:updateDeskSelection,onComponentLink:receiveComponentLink41,onComponentLinkCancelled:cancelComponentLink41,onComponentCommit:receiveComponentCommit41,onComponentReturn:receiveComponentReturn41,onRegionsReady:restoreLinkedComponent41,onLogout:()=>showAccess('当前访问已退出，请重新连接。')});

async function api(path,options={}) {
  let response;try{response=await fetch(path,{...options,headers:{'Content-Type':'application/json','X-CSRF-Token':ui.data?.csrf||'',...(options.headers||{})}});}catch{throw new Error('无法连接研究空间。此浏览器中的草稿仍然保留。');}
  let body;try{body=await response.json();}catch{throw new Error(`服务器返回不可读取的响应（${response.status}）。`);}
  if(response.status===401)showAccess('访问身份已失效，请重新连接。');
  if(!response.ok||body.ok===false){const error=new Error(body.error||body.message||`请求失败（${response.status}）`);error.status=response.status;error.code=body.code;error.details=body.details;throw error;}
  return body.ok===true&&Object.hasOwn(body,'result')?body.result:body;
}
async function action(name,fields={}, {notifyError=true}={}) {
  pending++;ui.deskPending=pending;desk.publish();document.body.classList.add('busy');
  try {const result=await api('/api/action',{method:'POST',body:JSON.stringify({action:name,...fields})});return result;}
  catch(error){if(notifyError)toast(error.message,'error');throw error;}
  finally{pending--;ui.deskPending=pending;desk.publish();if(!pending)document.body.classList.remove('busy');}
}
async function refresh({render=true}={}) {
  if(ui.authGate)return;
  try {const data=await api('/api/state');ui.data=data; for(const key of ['questions','feedback','growth'])ui.data[key]=list(data[key]).map(o=>({...o,...(o.content||{}),text:o.content?.original||o.text,status:o.content?.status||o.content?.lifecycle||o.status}));ui.online=true;const item=objects().find(o=>o.id===ui.object?.id);if(item&&item.revision>ui.object.revision&&item.revision>=knownEditorRevision()){ui.remoteRevision=item.revision;syncEditorIdentity(editorSnapshot());if(ui.view==='workspace'&&!ui.dirty&&!editorWrites.has(item.id)&&!figureRenders.has(item.id)&&!manuscriptReviewController?.isBusy()&&!document.querySelector('#modal-root').children.length){await openObject(item.id,{force:true});return;}if(ui.dirty)document.querySelector('#save-status')?.replaceChildren(document.createTextNode(`服务器已到修订 ${item.revision} · 本地草稿保留`));}
    if(render)draw();else updateConnection();
  }catch(error){ui.online=false;if(ui.authGate)return;if(!ui.data)app.innerHTML=`<div class="startup"><div class="brand-symbol">r.</div><h1>研究空间暂时无法连接</h1><p>${esc(error.message)}</p>${button('重新连接','refresh',{},'button primary')}</div>`;else updateConnection();}
}
function showAccess(message=''){
  persistWorkspaceDrafts();desk.hide();desk.beforeDraw();
  ui.authGate=true;ui.online=false;document.querySelector('#modal-root').innerHTML='';
  if(document.querySelector('#access-form')){document.querySelector('#access-error').textContent=message;return;}
  app.innerHTML=accessForm(message);
}
async function endSession(){
  if(desk.embedded){await desk.prepareLogout();return;}
  const storedKeys=Object.keys(localStorage);
  if(storedKeys.some(k=>k.startsWith('research-partner:')&&k.includes(':visual-intent41:active:'))){toast('还有尚未核对的图形采用。请先从对应图形核对回执或保留恢复记录，再退出。','error');return;}
  const draftKeys=storedKeys.filter(k=>k.startsWith('research-partner:draft:')||k.startsWith('research-partner:note:')||k.includes(':history-recovery:')||k.includes(':visual-intent41:archive:'));
  if(ui.dirty||ui.sectionNoteDirty){toast('请先保存当前成果和章节笔记的修改，再退出。');return;}
  if(pending||figureRenders.size||editorWrites.size){toast('还有保存或渲染在途，请等待回执后退出。');return;}
  const finish=async()=>{if(!await desk.prepareLogout())return;try{ui.auth=await logout(ui.data?.csrf);await desk.loggedOut();}catch(error){desk.resume();throw error;}for(const key of Object.keys(localStorage))if(key.startsWith('research-partner:'))localStorage.removeItem(key);ui.data=null;ui.graphReturn=null;ui.graphProjectRoot='';ui.object=null;ui.draft=null;ui.project='';ui.view='projects';ui.references={};ui.literatureResults=[];ui.undo=[];ui.redo=[];showAccess();};
  if(draftKeys.length){modal('退出研究空间',`<p>此浏览器另有 ${draftKeys.length} 份未提交草稿。退出会清除本机草稿；已保存的服务器成果保留。可取消并先保存这些草稿。</p>`,{label:'退出并清除本机草稿',submit:finish});return;}
  await finish();
}
function updateConnection(){const el=document.querySelector('#connection');if(el){el.textContent=ui.online?'研究空间已连接':'连接中断 · 草稿保留';el.classList.toggle('offline',!ui.online);}}
function storeNavigation(){desk.rememberEditor();try{const url=new URL(location.href);if(ui.view==='asset'&&ui.assetView){url.searchParams.set('object',ui.assetView.id);url.searchParams.delete('project');}else if(ui.object&&ui.view==='workspace'){url.searchParams.set('object',ui.object.id);url.searchParams.delete('project');}else{url.searchParams.delete('object');if(ui.project)url.searchParams.set('project',ui.project);else url.searchParams.delete('project');}history.replaceState(null,'',url);localStorage.setItem(desk.navigationKey(),JSON.stringify({view:ui.view,project:ui.project,object:ui.view==='asset'?ui.assetView?.id:ui.object?.id,tab:ui.tab}));}catch{}}
function updateHistoryControls41(){
 for(const name of ['undo','redo'])for(const button of document.querySelectorAll(`[data-action="${name}"]`))button.disabled=!ui[name]?.length;
}
function persistDraft(){
 if(!ui.object||!ui.draft)return;
 updateHistoryControls41();if(ui.graphReturn)rememberGraphEditor(ui,loadCounter);
 try{
  if(ui.draftHistoryStorageBlock41===ui.object.id)throw new Error('原编辑历史尚未安全保留');
  const history=packTrail41({objectId:ui.object.id,baseRevision:ui.object.revision,undo:ui.undo,redo:ui.redo});
  const raw=JSON.stringify({base_revision:ui.object.revision,title:ui.draft.title,content:ui.draft.content,history,saved_at:new Date().toISOString()});
  localStorage.setItem(draftKey(ui.object.id),raw);
  if(localStorage.getItem(draftKey(ui.object.id))!==raw)throw new Error('无法核对本机草稿');
 }catch{
  if(ui.draftStorageError41!==ui.object.id)toast('浏览器无法保存完整草稿及撤销历史，请及时保存到研究空间并保留当前页面。','error');
  ui.draftStorageError41=ui.object.id;document.querySelector('#save-status')?.replaceChildren(document.createTextNode('本机副本未保存 · 请保留当前页面'));return false;
 }
 if(ui.draftStorageError41===ui.object.id)ui.draftStorageError41=null;
 document.querySelector('#save-status')?.replaceChildren(document.createTextNode(ui.dirty?'本地草稿 · 未提交':`已保存 · r${ui.object.revision}`));desk.publish();return true;
}
function restoreDraftHistory41(draft,server,raw){
 if(!Object.hasOwn(draft,'history'))return;
 try{
  const history=unpackTrail41(draft.history),validDraft=d=>d&&typeof d.title==='string'&&d.content&&typeof d.content==='object'&&!Array.isArray(d.content);
  if(!history||history.objectId!==server.id||!Number.isInteger(history.baseRevision)||!Array.isArray(history.undo)||!Array.isArray(history.redo)||![...history.undo,...history.redo].every(validDraft))throw new Error('历史身份或内容无效');
  if(history.baseRevision===draft.base_revision&&draft.base_revision===server.revision){ui.undo=history.undo;ui.redo=history.redo;return;}
  retainLocalHistory41({...history,reason:'本机编辑历史的基础版本与当前服务器或草稿版本不同，单独保留供核对，不能直接撤回当前成果。'});
 }catch{
  try{retainLocalHistory41({objectId:server.id,baseRevision:draft.base_revision,undo:[],redo:[],rawDraft:raw,reason:'本机撤销历史无法安全读取；完整原始草稿记录已保留，可下载核对。'});}
  catch{ui.draftHistoryStorageBlock41=server.id;}
  toast('本机文字已恢复，但撤销历史无法安全读取；原记录保留，请从成果更多操作核对。','error');
 }
}

function settleLocalHistory41(){
 ui.dirty=!draftEqual(ui.draft,ui.object);if(!ui.dirty)ui.recovered=false;
 let preview=false;
 if(ui.object?.kind==='figure'){
  // A completed preview belongs to the overlays that produced it. Restoring
  // draft history must invalidate both its bitmap/hit map and any late reply.
  figurePreviewController?.cancel();ui.figurePreviewResult=null;ui.figurePreviewError='';
  const sourceChanged=figureSourceState(ui.draft.content)!==figureSourceState(ui.object.content),stale=!!ui.object.metadata?.render_stale;
  preview=!sourceChanged&&!stale&&!ui.draft.content.composition&&ui.draft.content.editable_source_available!==false&&!sameJSON41(overlayLayers(ui.draft.content),overlayLayers(ui.object.content));
  ui.figurePreviewStatus=sourceChanged||stale?'source_changed':preview?'queued':'saved';
  if(sourceChanged||stale)ui.figurePreviewError='绘图来源已修改或当前图像不是该来源的渲染；请核对授权后再明确重绘。';
 }
 persistDraft();draw();if(preview)scheduleFigurePreview({immediate:true});
}
function mutate(fn,redraw=false){if(!ui.draft)return;const before=ui.object?.kind==='figure'?figureSourceState(ui.draft.content):null;ui.undo.push(clone(ui.draft));if(ui.undo.length>80)ui.undo.shift();ui.redo=[];fn(ui.draft);ui.dirty=true;persistDraft();if(before!==null&&before!==figureSourceState(ui.draft.content)){figurePreviewController?.cancel();ui.figurePreviewResult=null;ui.figurePreviewStatus='source_changed';ui.figurePreviewError='绘图来源已修改；旧预览已取消。请单独保存来源并核对授权，再明确重绘。';writeFigurePreviewStatus();}if(redraw)draw();}
async function openObject(id,{force=false}={}) {
  if(!await desk.beforeOpen(id))return;try{
  // Persist before retiring view state: a quota failure must leave the live editor intact.
  persistWorkspaceDrafts();pendingReadingRestore=null;
  const activeTrail=ui.componentTrail?.at(-1);if(activeTrail&&id!==activeTrail.id&&id!==activeTrail.location?.id&&!id.startsWith('source:')){ui.componentTrail=[];rememberComponentTrail();}
  assetAbort?.abort();assetAbort=null;
  figurePreviewController?.destroy();figurePreviewController=null;figureInteractionDisposer?.();figureInteractionDisposer=null;colorDisposer?.();colorDisposer=null;ui.figurePreviewResult=null;ui.figurePreviewStatus='saved';ui.figurePreviewError='';invalidateManuscriptEditing();ui.manuscriptRevisionView='clean';ui.manuscriptFormat=null;ui.manuscriptRendered=null;ui.manuscriptFormatError='';ui.manuscriptFormatBusy=false;
  if(ui.graphReturn)rememberGraphEditor(ui,loadCounter);
  ui.sectionNote=null;ui.sectionNoteDirty=false;manuscriptReviewController?.destroy();manuscriptReviewController=null;const count=++loadCounter;
  if(id.startsWith('source:'))return await openRegisteredSource(id,count);
  const raw=await api(`/api/objects/${encodeURIComponent(id)}`);if(count!==loadCounter)return;
  ui.assetView=null;
  const o=raw.object?{...raw.object,revisions:raw.revisions,annotations:raw.annotations,dependencies:raw.dependencies}:raw;
  if(ui.graphReturn)rememberGraphEditor(ui);
  if(o.kind==='project'){ui.project=id;ui.view='projects';ui.object=null;ui.draft=null;storeNavigation();draw();return;}
  ui.object=o;ui.project=o.project_id||ui.project;ui.draft={title:o.title,content:clone(o.content||newContent(o.kind))};ui.dirty=false;ui.remoteRevision=null;ui.recovered=false;ui.selectedBlock='';ui.selectedComponent=null;ui.selectedItem='';ui.selectedItems=[];ui.textSelection=null;ui.figureLivePreview=undefined;ui.manuscriptReviewHTML='';ui.renderedMath=null;ui.mathLoading='';ui.page=0;ui.undo=[];ui.redo=[];
  if(o.kind==='figure'&&o.metadata?.render_stale){ui.figurePreviewStatus='source_changed';ui.figurePreviewError='来源已保存，当前图像仍是旧渲染；核对科学执行授权后再明确重绘。';}
  restoreLocalHistory41(id);ui.draftHistoryStorageBlock41=null;
  if(!force){try{const raw=desk.readDraft(id),draft=JSON.parse(raw||'null');if(draft){if(!draftEqual(draft,o)){ui.draft={title:draft.title,content:draft.content};ui.dirty=true;ui.recovered=true;if(draft.base_revision!==o.revision){ui.remoteRevision=o.revision;ui.object={...o,revision:draft.base_revision};}}restoreDraftHistory41(draft,o,raw);}}catch{}}
  ui.draftRecoveries41=[];ui.draftRecoveryError41='';ui.draftRecoveryChoice41=null;ui.draftRecoveryLoading41=false;
  updateHistoryControls41();desk.restoreEditor();try{pendingReadingRestore=JSON.parse(localStorage.getItem(desk.readingKey(id))||'null');}catch{pendingReadingRestore=null;}ui.references={};ui.referenceErrors={};ui.view='workspace';if(ui.graphReturn)rememberGraphEditor(ui,count);storeNavigation();draw();startDraftRecoveryDiscovery41(ui.object,count);loadReferences().catch(error=>{if(ui.object?.id===o.id)toast('来源读取未完成：'+error.message,'error');});if(ui.object===o&&['paper','report','note'].includes(o.kind))loadManuscriptEditing().catch(()=>{});
  }finally{desk.finishOpen();}
}
function usefulDraftRecovery41(candidate,server){
 if(!draftEqual(candidate.draft,server))return true;
 try{const history=unpackTrail41(candidate.draft.history);return !!(history?.undo?.length||history?.redo?.length);}catch{return true;}
}
function startDraftRecoveryDiscovery41(owner,count){
 if(!desk.listDraftRecoveries)return;
 // Do not await discovery between switching the editor identity and rendering
 // its DOM. Hashing old records must never leave old input bound to a new object.
 const current=()=>ui.object===owner&&loadCounter===count&&ui.view==='workspace'&&!ui.authGate;
 ui.draftRecoveryLoading41=true;
 Promise.resolve().then(()=>desk.listDraftRecoveries(owner.id)).then(candidates=>{
  if(!current())return;ui.draftRecoveries41=candidates.filter(c=>usefulDraftRecovery41(c,owner));ui.draftRecoveryError41='';writeDraftRecoveryNotice41();
 }).catch(error=>{if(current()){ui.draftRecoveryError41=error.message;writeDraftRecoveryNotice41();}}).finally(()=>{if(current())ui.draftRecoveryLoading41=false;});
}
function writeDraftRecoveryNotice41(){
 const slot=document.querySelector('[data-draft-recovery-slot]');if(!slot)return;
 const body=draftRecoveryNoticeBody41();slot.hidden=!body;slot.innerHTML=body;
}
function draftRecoveryNotice41(){const body=draftRecoveryNoticeBody41();return `<div data-draft-recovery-slot ${body?'':'hidden'}>${body}</div>`;}
function draftRecoveryNoticeBody41(){
 if(ui.draftRecoveryError41)return `<div class="notice warning" role="status">本机草稿读取未完成。${button('重新检查','draft-recovery-list',{},'button small')}</div>`;
 const count=ui.draftRecoveries41?.length||0;
 return count?`<div class="notice" data-draft-recovery-notice role="status">发现此成果的其他本机草稿。${button(`查看并恢复（${count}）`,'draft-recovery-list',{},'button small')}</div>`:'';
}
async function showDraftRecoveries41(){
 const source=editorSnapshot(),candidates=await desk.listDraftRecoveries(source.id);requireEditor(source);
 ui.draftRecoveries41=candidates.filter(c=>usefulDraftRecovery41(c,source.object));ui.draftRecoveryError41='';
 ui.draftRecoveryChoice41={source,candidates:ui.draftRecoveries41};
 modal('本机草稿',`<p>这些副本来自此浏览器的其他编辑区，原编辑区可能仍打开。先查看，再明确恢复一份副本；不会自动合并或提交。</p>${ui.draftRecoveries41.length?ui.draftRecoveries41.map((c,i)=>`<article class="panel"><strong>${esc(c.draft.title)}</strong><p class="hint">${esc(c.draft.saved_at?date(c.draft.saved_at):'保存时间未记录')} · 基于 r${esc(c.draft.base_revision)} · ${c.region==='secondary'?'副编辑区':'主编辑区'}</p>${button('查看这份草稿','draft-recovery-preview',{index:i},'button small')}</article>`).join(''):'<p>没有其他可恢复副本。原有编辑记录仍保留。</p>'}`,{wide:true});
}
function guardDraftRecovery41(source){
 requireEditor(source);
 if(ui.dirty||ui.sectionNoteDirty||ui.undo.length||ui.redo.length||ui.draftStorageError41===source.id||ui.draftHistoryStorageBlock41===source.id)throw new Error('当前编辑区还有本机改动或编辑历史。请先处理当前编辑，再恢复另一份草稿；两份记录均保留。');
 if(pending||editorWrites.has(source.id)||figureRenders.has(source.id)||manuscriptReviewController?.isBusy())throw new Error('当前成果仍在保存或处理，请等待回执后再恢复草稿。');
}
function draftRecoveryComparison41(candidate){
 const before=ui.object.content||{},after=candidate.draft.content||{};
 if(Array.isArray(before.blocks)&&Array.isArray(after.blocks)){
  const changes=manuscriptDraftChanges(before.blocks,after.blocks);
  return changes.length?changes.map(change=>`<details open><summary>${esc({replace:'修改文字',delete:'删除段落',insert:'新增段落'}[change.op])}</summary>${diff(before.blocks.find(b=>b.id===change.block_id)?.text||'',change.op==='delete'?'':change.text??change.block?.text??'')}</details>`).join(''):'<p>段落文字与当前保存稿相同；标题、其他内容及编辑历史请在完整记录中核对。</p>';
 }
 return `<details><summary>查看内容差异</summary>${diff(pretty(before),pretty(after))}</details>`;
}
function showDraftRecoveryPreview41(index){
 const choice=ui.draftRecoveryChoice41,candidate=choice?.candidates?.[Number(index)];if(!candidate)throw new Error('草稿列表已变化，请重新查看。');requireEditor(choice.source);
 let historyLabel='编辑历史需核对';try{const h=unpackTrail41(candidate.draft.history);historyLabel=`可撤销 ${h?.undo?.length||0} 步 · 可重做 ${h?.redo?.length||0} 步`;}catch{}
 const expectedCurrentRaw=localStorage.getItem(desk.draftKey(choice.source.id));
 modal('恢复这份本机草稿',`<p><strong>${esc(candidate.draft.title)}</strong> · 基于 r${esc(candidate.draft.base_revision)}；服务器当前 r${esc(knownEditorRevision())}。</p><p>${esc(historyLabel)}。恢复后仍是未提交草稿，原副本保留；版本不一致时需先核对差异。</p>${draftRecoveryComparison41(candidate)}<details><summary>完整草稿内容</summary><pre>${esc(pretty({title:candidate.draft.title,content:candidate.draft.content}))}</pre></details>`,{wide:true,label:'恢复副本到当前编辑区',submit:()=>applyDraftRecovery41(choice.source,candidate,expectedCurrentRaw)});
}
async function applyDraftRecovery41(source,candidate,expectedCurrentRaw){
 guardDraftRecovery41(source);
 const raw=await desk.recoverDraft(candidate,{expectedCurrentRaw,beforeCopy:()=>guardDraftRecovery41(source)},source.id);
 requireEditor(source);
 // Activate in the already guarded editor; a second navigation could be denied
 // by its host after the durable copy and must not produce a false success.
 const recovered=JSON.parse(raw),server=ui.object;
 ui.draft={title:recovered.title,content:clone(recovered.content)};ui.dirty=!draftEqual(recovered,server);ui.recovered=ui.dirty;ui.undo=[];ui.redo=[];
 if(ui.dirty&&recovered.base_revision!==server.revision){ui.remoteRevision=Math.max(knownEditorRevision(),server.revision);ui.object={...server,revision:recovered.base_revision};}
 restoreDraftHistory41(recovered,server,raw);updateHistoryControls41();ui.draftRecoveryChoice41=null;ui.draftRecoveries41=[];
 ui.textSelection=null;ui.selectedBlock=ui.draft.content.blocks?.some(b=>b.id===ui.selectedBlock)?ui.selectedBlock:'';
 invalidateManuscriptEditing();ui.manuscriptRendered=null;ui.manuscriptReviewHTML='';ui.renderedMath=null;ui.mathLoading='';ui.references={};ui.referenceErrors={};
 if(ui.object.kind==='figure')settleLocalHistory41();else draw();
 startDraftRecoveryDiscovery41(ui.object,loadCounter);loadReferences().catch(error=>{if(ui.object?.id===source.id)toast('来源读取未完成：'+error.message,'error');});
 if(['paper','report','note'].includes(ui.object.kind))loadManuscriptEditing().catch(()=>{});
 toast('本机草稿及可用编辑历史已恢复；尚未提交到成果。');
}
async function openRegisteredSource(id,count){
 const ref=desk.resolveAsset(id);if(!ref)throw new Error('此来源没有当前可访问成果的登记关系。请从对象树重新选择。');
 const back=ui.assetView?.returnId||ui.object?.id||ref.ownerId,owner=objects().find(o=>o.id===ref.ownerId);assetAbort=new AbortController();
 const {loadRegisteredAsset}=await import('./asset-loader41.js');const asset=await loadRegisteredAsset(ref,{signal:assetAbort.signal});if(count!==loadCounter)return;
 ui.assetView={...asset,id,returnId:back,ownerRevision:owner.revision};ui.object=owner;ui.project=owner.project_id;ui.draft={title:owner.title,content:clone(owner.content)};ui.dirty=false;ui.recovered=false;ui.remoteRevision=null;ui.selectedBlock='';ui.selectedItem='';ui.selectedComponent=null;ui.view='asset';storeNavigation();draw();
}
function bindRegisteredSource(){
 const viewer=app.querySelector('[data-asset41-viewer]');let restoreView=false;
 viewer?.addEventListener('asset41:beforeviewchange',()=>{restoreView=!!desk.getViewport();if(restoreView)desk.detachViewport();});
 viewer?.addEventListener('asset41:viewchange',()=>{if(restoreView||desk.getViewport()){desk.detachViewport();desk.reattachViewport();}restoreView=false;});
 assetDisposer=bindAssetViewer(app,{asset:ui.assetView,stateKey:desk.navigationKey()+':source:'+ui.assetView.sha,storage:localStorage,onReturn:()=>openObject(ui.assetView.returnId||ui.assetView.ownerId).catch(error=>toast(error.message,'error')),onTrace:()=>article.trace({}).catch(error=>toast(error.message,'error'))});
}
// Requests own a source object and editor session; server completion never navigates.
const editorWrites=new Map(),editorReads=new Map(),figureRenders=new Map();
let manuscriptReturn=null;let readingLayoutToken=0,pendingReadingRestore=null;
const draftEqual=(a,b)=>a?.title===b?.title&&sameJSON41(a?.content,b?.content);
function editorSnapshot(){return {object:ui.object,id:ui.object.id,revision:ui.object.revision,generation:loadCounter,auth:ui.auth,draft:clone(ui.draft)};}
function sameEditor(source){return !ui.authGate&&ui.auth===source.auth&&ui.view==='workspace'&&ui.object===source.object&&loadCounter===source.generation;}
function requireEditor(source){if(!source||!sameEditor(source))throw new Error('当前成果已切换，请回到原成果重新操作。');}
function writeStatus(message){document.querySelector('#save-status')?.replaceChildren(document.createTextNode(message));}
// Server revisions are monotonic within an editor; delayed polling cannot lower known state.
function knownEditorRevision(){return Math.max(Number(ui.object?.revision)||0,Number(ui.remoteRevision)||0);}
function syncEditorIdentity(source){
 if(!sameEditor(source))return;
 if(ui.object.kind==='paper')syncPaperSourceIdentity(document,ui.object);
 const base=document.querySelector('[data-editor-base-revision]'),remote=document.querySelector('[data-editor-remote-revision]');
 if(base?.dataset.objectId===source.id)base.textContent=`基础修订 ${ui.object.revision}`;
 if(remote?.dataset.objectId===source.id){remote.hidden=!ui.remoteRevision;remote.textContent=ui.remoteRevision?`· 服务器修订 ${ui.remoteRevision}，本地基础保留`:'';}
}

async function readEditorDetails(source){
 const turn=(editorReads.get(source.id)||0)+1;editorReads.set(source.id,turn);
 const raw=await api(`/api/objects/${encodeURIComponent(source.id)}`),latest=raw.object?{...raw.object,annotations:raw.annotations,revisions:raw.revisions,dependencies:raw.dependencies}:raw;
 if(latest.id!==source.id)throw new Error('服务端返回的成果身份不匹配；当前草稿保留。');
 if(!sameEditor(source)||editorReads.get(source.id)!==turn)return;
 // Refresh the side panel/history only. Never replace an editable document or its undo stack.
 for(const key of ['annotations','revisions','dependencies'])if(latest[key]!==undefined)ui.object[key]=latest[key];
 if(latest.revision===ui.object.revision){ui.object.metadata=latest.metadata;for(const key of ['canonical_source_sha256','exports','previous_render_record','review_records','paper_source_state']){if(latest[key]!==undefined)ui.object[key]=latest[key];else delete ui.object[key];}}
 if(latest.revision>ui.object.revision&&latest.revision>=knownEditorRevision()){ui.remoteRevision=latest.revision;writeStatus(`服务器已到修订 ${latest.revision} · 当前内容保留，请核对差异`);}
 syncEditorIdentity(source);
 const panel=document.querySelector('.context-panel-body');if(panel&&['sources','outline','comments'].includes(ui.workspacePanel)){const scroll=panel.scrollTop;panel.innerHTML=ui.workspacePanel==='sources'?annotationPanel():ui.workspacePanel==='outline'?documentOutline(context()):commentsWorkspace();panel.scrollTop=scroll;}
}
function settleDraftStorage(source,result,active,changed,safeBase){
 if(ui.authGate||ui.auth!==source.auth)return;
 try{
  const key=draftKey(source.id),raw=localStorage.getItem(key),stored=JSON.parse(raw||'null');
  // A different editor/tab may have written a newer draft. Completion is not permission to erase it.
  if(!stored||stored.base_revision!==source.revision)return;
  if(active&&!changed&&draftEqual(stored,source.draft))localStorage.removeItem(key);
  else if(active&&draftEqual(stored,ui.draft)){
   if(!ui.dirty)localStorage.removeItem(key);
   else if(safeBase)localStorage.setItem(key,JSON.stringify({...stored,base_revision:result.revision}));
  }else if(!active&&draftEqual(stored,source.draft))localStorage.removeItem(key);
 }catch{toast('服务器已保存，但浏览器草稿记录未能更新；请保留当前内容。','error');}
}
async function finishEditorWrite(source,result,{restore=false}={}){
 if(result?.id!==source.id||!Number.isInteger(result.revision))throw new Error('写入回执身份不匹配；请从原成果修订历史核对，草稿保留。');
 const active=sameEditor(source)&&ui.object.revision===source.revision,changed=active&&!draftEqual(ui.draft,source.draft),safeBase=draftEqual(result,source.draft);
 if(!ui.authGate&&ui.auth===source.auth&&ui.data){ui.data.objects=list(ui.data.objects).map(o=>o.id===result.id&&o.revision<=result.revision?{...o,...result}:o);}
 if(active){
  if(!changed&&!safeBase&&!restore&&(ui.undo.length||ui.redo.length)){
   retainLocalHistory41({objectId:source.id,baseRevision:source.revision,undo:clone(ui.undo),redo:clone(ui.redo),reason:'服务器采用的内容不同于原本机草稿；旧编辑历史单独保留，不能直接撤回新成果。'});
   ui.undo=[];ui.redo=[];updateHistoryControls41();
  }
  // Concurrent remote merges can differ from the sent snapshot. Keep the old merge base
  // for newer local edits in that case, rather than silently treating them as based on the merged body.
  Object.assign(ui.object,result);
  for(const key of ['canonical_source_sha256','exports','review_records'])delete ui.object[key];
  if(changed&&!safeBase){ui.object.revision=source.revision;ui.remoteRevision=result.revision;}
  else{ui.remoteRevision=null;ui.recovered=false;}
  if(!changed){
   if(!draftEqual(ui.draft,result)){
    if(restore)ui.undo.push(clone(ui.draft));
    ui.draft={title:result.title,content:clone(result.content)};
   }
   ui.dirty=false;ui.draftStorageError41=null;
  }else ui.dirty=true;
  settleDraftStorage(source,result,true,changed,safeBase);
  if(ui.object.content?.blocks&&['paper','report','note'].includes(ui.object.kind)){
   invalidateManuscriptEditing();if(ui.workspacePanel==='direct')loadManuscriptEditing().catch(()=>{});
  }
  if(!changed&&!draftEqual(source.draft,result))draw();
  writeStatus(`已${restore?'恢复':'保存'} ${source.id} · 修订 ${result.revision}${changed?' · 新编辑仍在本地，尚未提交':''}`);
  syncEditorIdentity(source);
  if(ui.graphReturn)rememberGraphEditor(ui,source.generation);
 }else{if(ui.graphReturn&&!ui.authGate&&ui.auth===source.auth)settleGraphEditorWrite(ui,source,result,{restore});settleDraftStorage(source,result,false,false,safeBase);}
 toast(`${source.id} · 修订 ${result.revision} 已${restore?'恢复':'保存'}${active&&changed?'；请求之后的新编辑仍需保存':!active?'；当前界面保留':''}。可在原成果修订历史核对。`);
 if(active){try{await readEditorDetails(source);}catch(error){toast(`${source.id} · 修订 ${result.revision} 已写入；读取批注／历史失败：${error.message}`,'error');}}
 return result;
}
async function editorWrite(source,name,fields,options={}){
 if(editorWrites.has(source.id))throw new Error('此成果仍有保存或恢复请求在途；新编辑已保留，请等待回执后再保存。');
 let settle;const done=new Promise(resolve=>settle=resolve);editorWrites.set(source.id,{done});
 try{
  let result;
  try{result=await action(name,fields);}catch(error){
   if(sameEditor(source)&&(error.status===409||error.code==='conflict')){
    ui.remoteRevision=error.details?.current_revision||'有更新';persistDraft();draw();
    // The conflict reader itself is session-bound, including its later explicit choices.
    await showConflict(error,source);
   }
   throw error;
  }
  return await finishEditorWrite(source,result,options);
 }finally{editorWrites.delete(source.id);settle();}
}
async function save(){
 if(!ui.object||!ui.draft)return;
 // A manual save during automatic preview shares its save receipt. Do not create
 // another revision merely because the render is still running.
 const waiting=figureRenders.get(ui.object.id);if(waiting){const source=editorSnapshot();await waiting.promise;requireEditor(source);if(!draftEqual(ui.draft,source.draft))throw new Error('等待重绘期间有新编辑，内容保留；请再次保存。');if(!ui.dirty)return ui.object;}
 const invalid=document.querySelector('[data-edit]:invalid,[data-overlay-tuple]:invalid');if(invalid){invalid.reportValidity();throw new Error('请先修正无效属性；当前草稿尚未提交。');}
 clearTimeout(typingTimer);const source=editorSnapshot();
 const result=await editorWrite(source,'object.save',{id:source.id,expected_revision:source.revision,title:source.draft.title,content:source.draft.content});if(sameEditor(source)&&!ui.dirty)draw();return result;
}

function readingPosition(){return captureReading41(document,ui.object?.id);}
function rememberReadingPosition(){
 const position=pendingReadingRestore?.objectId===ui.object?.id?pendingReadingRestore:readingPosition();
 if(position)try{localStorage.setItem(desk.readingKey(position.objectId),JSON.stringify(position));}catch{}
}
function keepReadingPosition(position,token){
 if(!position)return;const restore=()=>{if(token!==readingLayoutToken||ui.object?.id!==position.objectId)return;restoreReading41(document,position);};
 restore();document.querySelectorAll('.manuscript-page img').forEach(img=>{if(!img.complete)img.addEventListener('load',restore,{once:true});});
}
function draw(){if(!ui.data)return;
  clearFigureAnnotation41(app);
  if(ui.object?.kind==='figure'){const manifest=figureManifest(figureVisualObject(),ui.draft.content);if(!manifest.some(x=>x.id===ui.selectedItem))ui.selectedItem=manifest.find(x=>x.id==='figure:root')?.id||manifest.find(x=>x.type==='axes')?.id||manifest[0]?.id||'';}
  const position=pendingReadingRestore?.objectId===ui.object?.id?pendingReadingRestore:readingPosition(),layoutToken=++readingLayoutToken;
  const previousPanel=document.querySelector('.context-panel-body'),panelScroll=previousPanel?.scrollTop||0,panelOwner=previousPanel?.dataset.owner,panelKind=previousPanel?.dataset.panel;
  const c=context(),p=currentProject(),editing=ui.view==='workspace'&&ui.object;
  assetDisposer?.();assetDisposer=null;desk.beforeDraw();
  app.innerHTML=desk.render(graphReturnPanel(c)+view());
  document.querySelectorAll('.studio-sidebar .nav-item').forEach(b=>{b.title=b.textContent.trim();b.setAttribute('aria-label',b.textContent.trim());});
  if(ui.view==='asset'&&ui.assetView)bindRegisteredSource();
  desk.afterDraw(app);
  if(ui.view==='workspace'){autoSize();bindEditorCanvas(app);scheduleManuscriptRender();const panel=document.querySelector('.context-panel-body');if(panel&&panelOwner===ui.object?.id&&panelKind===ui.workspacePanel)panel.scrollTop=panelScroll;if(manuscriptReturn)restoreManuscriptReading();else keepReadingPosition(position,layoutToken);syncFigureRenderStatus();}
  if(ui.view==='graph')bindGraph(app,context(),{action:async (...args)=>{const r=await action(...args);const obj=objects().find(x=>x.id===r.id);if(obj)Object.assign(obj,r);return r;},rerender:draw});
  if(ui.view==='activity'&&ui.tab==='development')developmentView.bind(app.querySelector('[data-development-view]'),ui.data.development);
  storeNavigation();
}
function view(){switch(ui.view){case'asset':return ui.assetView?renderAssetViewer(ui.assetView):desk.home();case'graph':return graphView(context());case'workspace':return workspaceView();case'workshop':return workshopView();case'literature':return literatureView();case'activity':return activityView();case'settings':return settingsView();default:return projectsView();}}
function projectsView(){return desk.home();}

function artifactCard(o){return `<button class="artifact-card" data-action="open-object" data-id="${esc(o.id)}"><span class="artifact-kind">${esc(kinds[o.kind]||o.kind)}</span><h3>${esc(o.title)}</h3><p>${esc(o.content?.blocks?.find(b=>b.text)?.text?.slice(0,95)||o.content?.caption||'打开并继续编辑')}</p><footer><span>修订 ${esc(o.revision)}</span><time>${date(o.updated_at)}</time></footer></button>`;}
function decisionSummary(){const questions=list(ui.data.questions).filter(q=>(!ui.project||q.project_id===ui.project)&&questionNeedsAttention(q));return questions.length?`<div>${questions.slice(0,3).map(q=>`<button class="decision-link" data-action="decision" data-id="${esc(q.id)}">${esc(q.question||q.title||q.prompt)}<span>查看问题 →</span></button>`).join('')}</div>`:'<p class="hint">目前没有新待答问题。已经暂缓的安排会保留，可以继续独立工作。</p>';}
function workspaceActions(){const o=ui.object,p=currentProject();if(!o||!p)return '';const featured=(p.metadata?.featured_objects||[]).includes(o.id);return `<div class="button-group artifact-context-actions">${button(featured?'取消项目置顶':'置顶到项目','artifact-feature',{},'text-button small')}${button('成果入口链接','artifact-link',{},'text-button small')}</div>`;}
function reviewSummary(){const records=ui.object?.review_records||[];if(!records.length)return '';const r=records[records.length-1];const verdict={needs_revision:'需修订',usable_for_discussion:'可用于限定讨论',reviewed_with_limits:'已审阅，附限制'}[r.verdict]||r.verdict;return `<div class="notice"><strong>修订 ${esc(r.revision)} · ${esc(verdict)}</strong><p>${esc(r.summary)}</p><small>${esc(r.scope)} · 科学批准与用户验收另行确认</small>${button('查看审阅依据','review-open',{id:r.review_object_id,revision:r.review_revision},'text-button small')}</div>`;}
function renderDeskEditor(){const html=visualPendingPanel41()+renderEditor(context()).replace('</header>','</header>'+draftRecoveryNotice41()),tools=areaTools41(context());return html.includes('class="manuscript-ribbon"')?html.replace('</div><div class="manuscript-ribbon-tools">','</div>'+tools+'<div class="manuscript-ribbon-tools">'):html.replace('<div class="editor-content">',tools+'<div class="editor-content">');}
function workspaceView(){
 if(!ui.object)return `<div class="workbench-project-view">${workbenchHome(context())}</div>`;
 const trail=ui.componentTrail?.at(-1),panel=ui.workspacePanel;
 const panelBody=!panel?'':panel==='outline'?documentOutline(context()):panel==='direct'?manuscriptDirectEditPanel(ui.manuscriptDirectState,ui.manuscriptRevisionView,{currentRevision:ui.object.revision,loading:ui.manuscriptDirectLoading,error:ui.manuscriptDirectError}):panel==='format'?manuscriptFormatPanel(ui.manuscriptFormat||defaultManuscriptFormat,{busy:ui.manuscriptFormatBusy,error:ui.manuscriptFormatError,rendered:ui.manuscriptRendered}):panel==='notes'?article.notePanel():panel==='sources'?annotationPanel():panel==='review'?manuscriptReviewWorkspace():commentsWorkspace();
 return `<div class="workspace-layout studio-workspace ${panel?'has-context-panel':''}"><section class="artifact-editor">${ui.object.kind==='feedback'?feedbackCard(list(ui.data.feedback).find(f=>f.id===ui.object.id)||ui.object,{tasks:list(ui.data.tasks),objects:objects(),detail:true}):renderDeskEditor()}</section>${panel?`<aside class="annotation-panel context-panel"><header class="context-panel-header"><div class="context-tabs">${[['comments','批注'],['review','修订'],['notes','工坊笔记'],['sources','来源']].map(([id,label])=>button(label,'workspace-panel',{panel:id},'context-tab '+(panel===id?'active':''))).join('')}</div>${button('×','workspace-panel-close',{},'icon-button')}</header><div class="context-panel-body" data-owner="${esc(ui.object.id)}" data-panel="${esc(panel)}">${panelBody}</div></aside>`:''}</div>`;
}
function commentsWorkspace(){const o=ui.object,annotations=list(o?.annotations),manuscript=['paper','report','note'].includes(o?.kind),intro=o?.kind==='figure'?'可对整图或选定区域留下具体意见。':manuscript?'选中文稿中的段落或文字，留下具体意见。':'选择成果中的内容或位置，留下具体意见。',emptyText=o?.kind==='figure'?'批注将保留在这幅图旁。':manuscript?'批注将保留在这份稿件旁。':'批注将保留在这份成果旁。';return `<div class="review-panel-intro"><h2>批注</h2><p>${intro}</p>${button('添加批注','annotate',{},'button small')}</div><div class="annotations">${annotations.map(a=>`<article class="annotation ${a.status==='orphaned'?'orphaned':''}"><header><strong>${a.status==='resolved'?'已处理':'研究批注'}</strong><span>${date(a.created_at)}</span></header>${a.anchor?.quote?`<blockquote>${esc(a.anchor.quote)}</blockquote>`:''}<p>${esc(a.text)}</p>${status(a.status)}<div class="annotation-controls">${button('定位','annotation-locate',{id:a.id},'text-button small')}${(a.anchor?.block_id||a.anchor?.component_id)?button('按此批注修订','manuscript-round',{annotation:a.id,block:a.anchor.block_id},'text-button small'):''}${button(a.status==='resolved'?'重新打开':'标记已处理','annotation-resolve',{id:a.id,status:a.status==='resolved'?'open':'resolved'},'text-button small')}</div></article>`).join('')||`<div class="quiet-empty">${emptyText}</div>`}</div>`;}
function manuscriptReviewWorkspace(){const tasks=list(ui.data?.tasks).filter(t=>t.payload?.kind==='manuscript_revision'&&t.payload?.context?.manuscript_revision?.object_id===ui.object?.id);return `<div class="review-panel-intro"><h2>定向修订</h2><p>选择段落或批注，科研搭档提出改动后，由你逐项决定。</p>${button('修订所选段落','manuscript-revision',{},'button primary small')}</div>${tasks.length?`<div class="revision-task-list">${tasks.map(t=>`<div>${button(`${t.payload.provider_id||'Agent'} · ${t.payload.context?.manuscript_revision?.opinions?.length?`${t.payload.context.manuscript_revision.opinions.length} 条意见`:'段落修订'} · ${date(t.created_at)}`,'manuscript-review-open',{id:t.id},'text-button small')}${status(t.status)}</div>`).join('')}</div>`:''}<div id="manuscript-review-panel">${ui.manuscriptReviewHTML||'<p class="hint">尚未打开修订候选。当前正文不会因模型返回而自动替换。</p>'}</div>${ui.manuscriptReviewTask?button('刷新候选状态','manuscript-review-open',{id:ui.manuscriptReviewTask},'button small'):''}`;}

function assemblySourcesPanel(){
 const modules=list(ui.object?.metadata?.workbench?.assembly?.modules);if(!modules.length)return '';
 return '<section class="assembly-sources"><h3>组成此稿的独立模块</h3>'+modules.map(m=>{const current=objects().find(o=>o.id===m.id),updated=current&&current.revision!==m.revision;return `<article><strong>${esc(m.heading||current?.title||m.id)}</strong><p>采用修订 ${esc(m.revision)}${current?' · 当前 '+current.revision:''}</p>${m.decision?.action==='retain'?`<small>已选择保留旧版；当时核读来源修订 ${esc(m.decision.observed_revision)}</small>`:''}<div>${button('查看采用文本','open-reference',{id:m.id,revision:m.revision},'text-button small')}${button('打开独立模块','open-object',{id:m.id},'text-button small')}</div>${updated?`<div class="module-update"><p>来源有新修订。更新仅替换未经编辑的原整合段落；已有手动修改会保留并提示人工合并。</p>${button('更新这个模块','workbench-module-decision',{id:m.id,revision:current.revision,decision:'refresh'},'button small')}${button('保留已采用版','workbench-module-decision',{id:m.id,revision:current.revision,decision:'retain'},'button subtle small')}</div>`:''}</article>`;}).join('')+'</section>';
}
async function decideWorkbenchModule(data){
 if(ui.dirty)throw new Error('请先保存稿件草稿，再决定来源更新。');const source=editorSnapshot();const result=await action('workbench.'+(data.decision==='refresh'?'refresh_module':'retain_module'),{object_id:source.id,expected_revision:source.revision,module_id:data.id,revision:Number(data.revision),request_key:uid('module-decision')});await finishEditorWrite(source,result.object);await refresh({render:false});if(ui.object?.id===source.id)await loadReferences();toast(data.decision==='refresh'?'模块来源已更新；其他正文保留。':'已记录保留采用版本。');
}
function annotationPanel(){const o=ui.object,annotations=list(o.annotations),blocks=ui.draft.content.blocks||[],nodes=ui.draft.content.nodes||[],items=(ui.draft.content.pages||[]).flatMap(p=>p.objects||[]);const anchorExists=a=>a?.artist_id?figureManifest(o,ui.draft.content).some(m=>m.id===a.artist_id):!a?true:a.block_id?blocks.some(b=>b.id===a.block_id):a.node_id?nodes.some(n=>n.id===a.node_id):a.object_id?items.some(n=>n.id===a.object_id)||a.object_id===o.id:true;return `<div class="section-heading"><h3>批注与依据</h3>${button('+ 批注','annotate',{},'icon-button')}</div><p class="hint">${ui.selectedBlock?'当前已选中段落。':ui.selectedItem?'当前已选中画布对象。':'选中段落或对象后，批注会绑定其稳定身份。'}</p><div class="annotations">${annotations.map(a=>`<article class="annotation ${!anchorExists(a.anchor)?'orphaned':''}"><header><strong>${esc(a.author||'研究者')}</strong><span>${date(a.created_at)}</span></header>${a.anchor?.quote?`<blockquote>${esc(a.anchor.quote)}</blockquote>`:''}<p>${esc(a.text)}</p>${!anchorExists(a.anchor)?'<span class="warning-text">锚点已移除 · 请重新定位</span>':button('定位','annotation-locate',{id:a.id},'text-button small')}<div class="annotation-controls">${status(a.status||'pending')}${button(a.status==='resolved'?'重新打开':'标记已处理','annotation-resolve',{id:a.id,status:a.status==='resolved'?'open':'resolved'},'text-button small')}</div></article>`).join('')||'<div class="quiet-empty">批注会留在对应成果中。恢复历史内容也会保留反馈记录。</div>'}</div>${assemblySourcesPanel()}<div class="section-heading"><h3>依赖与引用版本</h3></div>${sourceReferencePanel(o,ui.references,ui.referenceErrors)}<h4>作为源组件</h4>${button('查看采用位置','source-impacts',{},'button small')}${o.kind==='concept'?associatedProjectsPanel(context(),o.id):''}<h4>图谱关系</h4>${list(o.dependencies).filter(d=>d.src===o.id).map(d=>`<div class="dependency"><strong>${esc(d.title||d.target_title||objects().find(x=>x.id===d.dst)?.title||d.dst||d.target_id||'关联对象')}</strong><small>采用修订 ${esc(d.target_revision||d.revision||'未指定')}</small>${consumerImpactLocations({...o,content:ui.draft.content},d.dst)}${d.metadata?.decision?`<small>最近决定：${d.metadata.decision.action==='retain'?'保留旧版':'接纳新版'} · 当时看到源修订 ${esc(d.metadata.decision.observed_revision)}</small>`:''}${d.stale||d.needs_update||d.update_available?`<div class="notice warning">来源有新修订</div><div class="button-group">${button('接纳新版','dependency-accept',{id:d.id||d.target_id||d.dst},'button small')}${button('保留旧版','dependency-retain',{id:d.id||d.target_id||d.dst},'button small')}</div>`:status(d.status||'unverified')}</div>`).join('')||'<p class="hint">没有已登记图谱关系。</p>'}<div class="section-heading"><h3>此成果的意见</h3></div>${list(ui.data.feedback).filter(f=>(f.content?.object_id||f.object_id)===o.id).map(f=>button(f.content?.original||f.text||f.title,'open-object',{id:f.id},'feedback-related text-button small')).join('')||'<p class="hint">尚无关联意见。</p>'}<div class="aside-bottom">${button('导出成果','export',{},'button full')}${button('提交反馈','feedback',{},'button subtle full')}</div>`;}
function autoSize(){document.querySelectorAll('.block-editor').forEach(el=>{el.style.height='auto';el.style.height=`${Math.max(54,el.scrollHeight)}px`;});}

const workshopCategories=[['stimulus','刺激准备'],['annotations','图像与标注清洗'],['neural','神经数据预处理'],['visualization','可视化工具'],['experiment','实验软件']];
function workshopView(){const work=currentObjects().filter(o=>o.kind==='workshop'),selected=ui.workshop===false?null:ui.workshop||work[0],content=selected?.content||{};return `<div class="view-heading"><div><span class="eyebrow">RESEARCH WORKSHOP</span><h1>研究工坊</h1><p>把材料、数据与工具准备好，让学术工作有可靠的依托。</p></div>${button('新建准备任务','workshop-new',{},'button primary')}</div><div class="workshop-grid"><section class="panel">${isExtensionWorkshop(selected)?extensionWorkshopPanel(selected,list(ui.data.extensions)):`<div class="section-heading"><h2>输入与运行配置</h2></div><form id="workshop-form">${field('任务标题','title',content.title||selected?.title||'','text','required placeholder="例如：刺激图像尺寸检查"')}${select('准备任务类型','category',workshopCategories,workshopKey(content.category||'stimulus'))}<div id="workshop-config-help">${workshopHelp(content.category||'stimulus')}</div>${button('上传输入文件','import-asset',{mode:'workshop'},'button small')}${field('输入引用（JSON 数组）','inputs',pretty(content.inputs||[]),'textarea','required placeholder="[{&quot;sha&quot;:&quot;登记的SHA256&quot;,&quot;alias&quot;:&quot;input.csv&quot;}]"')}${field('处理配置（JSON）','config',pretty(content.config||{}),'textarea','required')}<div class="field-grid">${field('执行时限（秒）','timeout_seconds','60','number','required min="1" max="600"')}${field('远端执行器名称（可留空）','remote_host',content.config?.remote_host||'')}</div><p class="hint">只填写服务端已配置的执行器名称，不在此输入凭据或地址。留空在本机执行。</p>${field('预期输出与技术验收','acceptance',content.acceptance_description||'','textarea','placeholder="要检查的输出、质量条件和已知边界"')}<label class="check-field"><input type="checkbox" name="execute_code" required><span>授权按当前配置执行此准备任务，生成新的输出资产</span></label><label class="check-field"><input type="checkbox" name="scientific_preprocessing" ${workshopKey(content.category)==='neural'?'required':''}><span>若为神经数据任务，另授权当前输入与参数范围内的预处理</span></label><label class="check-field"><input type="checkbox" name="remote_execution"><span>若选择远端执行，授权把当前登记输入发送到该已配置执行器</span></label><p class="hint">授权范围以登记输入和配置为限，不包含拟合训练、改写原始数据、物理设备控制或未经验证的精确时序。</p><div class="form-actions"><button type="submit" class="button primary">提交并运行</button>${button('查看工具与权限','navigate',{view:'settings'},'button subtle')}</div><p id="workshop-error" class="form-error"></p></form>`}</section><section class="panel"><div class="section-heading"><h2>产物与技术验收</h2></div>${work.length?`<div class="workshop-picker">${work.map(o=>`<button data-action="workshop-select" data-id="${esc(o.id)}" class="workshop-entry ${selected?.id===o.id?'active':''}"><strong>${esc(o.title)}</strong><span>${workshopIdentity(o)}</span></button>`).join('')}</div>`:'<p class="hint">尚未产生工坊成果。提交真实输入后，执行结果会显示在这里。</p>'}${selected?workshopPreview(selected):empty('等待可检查的产物','输入、执行与输出对应起来后，才能进行技术验收。')}</section></div><section class="panel"><div class="section-heading"><h2>有关运行</h2></div>${taskList(list(ui.data.tasks).filter(t=>t.kind==='workshop'||t.type==='workshop'||t.payload?.category||t.metadata?.category))}</section>`;}
function workshopPreview(o){const c=o.content||{},outputs=list(c.outputs),run=c.run||{};return `<div class="workshop-preview"><div class="section-heading"><h3>${esc(o.title)}</h3><span>${isExtensionWorkshop(o)?'执行 '+esc(extensionExecutionLabel(o)):'生成 '+status(c.status||run.status||'unverified')}</span><span>技术验收 ${status(o.workshop_readiness?.technical_status||o.metadata?.technical_status||'pending')}</span></div>${outputs.map(x=>{const url=assetURL(x.asset||x.sha||x.sha256||x.url);return `<article class="output-item"><strong>${esc(x.name||x.path||x.type||'输出')}</strong>${url&&/image|png|jpg|svg/i.test(x.mime||x.type||x.name||'')?`<img src="${esc(url)}" alt="${esc(x.name||'输出预览')}">`:''}${url?`<a class="button small" target="_blank" rel="noopener" href="${esc(url)}">打开资产</a>`:`<pre>${esc(pretty(x))}</pre>`}</article>`;}).join('')||'<p class="hint">此成果尚无已登记输出。</p>'}<details><summary>质量摘要与执行来源</summary><pre>${esc(pretty({validation:c.validation||c.quality,inputs:c.inputs,config:c.config,run:c.run,limitations:c.limitations}))}</pre></details><div class="technical-acceptance"><h4>技术验收</h4><p class="hint">验收绑定当前产物与修订；技术通过不代表科学批准。失败后须明确重新验收，历史记录保留。</p><pre>${esc(pretty(c.acceptance||[]))}</pre>${button('登记验收结果','workshop-accept',{id:o.id},'button small')}${button('在工作台查看','open-object',{id:o.id},'button small subtle')}</div></div>`;}
function literatureView(){const refs=currentObjects().filter(o=>o.kind==='literature');return `<div class="view-heading"><div><span class="eyebrow">SOURCES & CONTEXT</span><h1>文献资料</h1><p>保留出处与实际阅读范围，让论断能回到原材料。</p></div>${button('导入文献','literature-import',{},'button primary')}</div><form id="literature-search" class="literature-search"><input name="query" type="search" required placeholder="题名、作者、DOI 或研究主题" aria-label="检索文献"><button class="button primary" type="submit">检索</button><p class="hint">检索使用服务端已接入的文献来源；不可用时显示实际错误。</p></form>${ui.literatureResults.length?`<section class="panel"><h2>检索结果</h2>${ui.literatureResults.map((r,i)=>literatureCard(r,i,true)).join('')}</section>`:''}<div class="section-heading"><h2>项目文献</h2><span class="hint">${refs.length} 条记录</span></div>${refs.length?`<div class="literature-list">${refs.map(r=>literatureCard(r,null,false)).join('')}</div>`:empty('给研究留下可追溯的出处','导入 BibTeX、RIS 或文献元数据。仅有题名不会被标记为已读全文。')}`;}
function literatureCard(r,index,isResult){const c=r.content||r,m=r.metadata||{},authors=c.authors||c.author||r.authors||[],url=safeURL(c.url||c.doi&&`https://doi.org/${c.doi}`||r.url);return `<article class="literature-card"><div><span class="eyebrow">${esc(c.year||r.year||'年份未记录')} · ${esc(c.journal||c.venue||r.venue||'出版信息未记录')}</span><h3>${esc(r.title||c.title||'未命名文献')}</h3><p>${esc(Array.isArray(authors)?authors.map(a=>typeof a==='string'?a:a.name||`${a.given||''} ${a.family||''}`).join(', '):authors)}</p><div class="reference-meta"><span class="status">${esc({metadata:'仅元数据',abstract:'仅摘要',fulltext:'已读取全文'}[c.read_scope||c.access_scope||m.read_scope]||c.read_scope||'阅读范围未核对')}</span>${c.doi?`<span>DOI: ${esc(c.doi)}</span>`:''}</div>${c.abstract?`<details><summary>查看摘要</summary><p>${esc(c.abstract)}</p></details>`:''}</div><div class="literature-actions">${isResult?button('加入项目','literature-add',{index},'button small'):button('打开记录','open-object',{id:r.id},'button small')}${url?`<a class="button subtle small" href="${esc(url)}" target="_blank" rel="noopener">原始来源 ↗</a>`:''}</div></article>`;}
function taskList(tasks){return tasks.length?tasks.map(t=>`<article class="task-row"><div><div class="task-title">${button(t.title||t.objective||t.payload?.request?.slice(0,70)||t.prompt?.slice(0,70)||t.id,'task-detail',{id:t.id},'text-button')}${t.payload?.kind==='research_cycle'&&t.status==='queued'?`<span class="status status-running">${esc(cyclePhases[t.result?.cycle?.phase]||'协作准备中')}</span>`:status(t.status)}</div><p>${esc(t.error||t.message||t.progress?.message||t.blocked_reason||'')}</p><small>${date(t.updated_at||t.created_at)}${t.provider?` · ${esc(t.provider)}`:''}${t.cost!=null?` · 已记录成本 ${esc(t.cost)}`:''}</small></div><div class="task-controls">${t.payload?.kind==='manuscript_revision'?button('审阅稿件修订','manuscript-task-open',{id:t.id},'button small'):''}${t.result?.project_management?button('审阅项目提案','management-review',{id:t.id},'button small'):''}${t.payload?.kind==='project_management'&&!['cancelled','deliverable'].includes(t.status)?button('撤回管理授权','management-revoke',{id:t.id},'button small danger-text'):''}${t.result?.object_id?button('打开产物','open-object',{id:t.result.object_id},'button small'):''}${canGuide(t)&&!(t.payload?.kind==='research_cycle'&&['generated','cancelled','deliverable'].includes(t.status))?button('补充指导','task-guide',{id:t.id},'button small'):''}${canOpenFailedPlanner(t)?button('修订原规划','cycle-revise-failed-child',{id:t.payload.cycle_parent,child:t.id},'button small'):''}${canReviseCandidate(t)?button('按当前回答修订候选','task-revise-candidate',{id:t.id},'button small'):''}${t.payload?.kind!=='research_cycle'&&!t.payload?.cycle_parent&&canExtendBudget(t,list(ui.data.providers))?button('追加有限额度','task-budget',{id:t.id},'button small'):''}${button('优先级','task-priority',{id:t.id},'button small subtle')}${['queued','running','waiting','waiting_input','waiting_resource','waiting_authorization'].includes(t.status)?button('暂停','task-control',{id:t.id,command:'pause'},'button small'):''}${['paused','failed','waiting_input','waiting_resource','waiting_authorization'].includes(t.status)&&t.attempts<3?button('继续','task-control',{id:t.id,command:'resume'},'button small'):''}${!['completed','succeeded','cancelled','canceled','deliverable'].includes(t.status)&&!(t.payload?.kind==='research_cycle'&&t.status==='generated')?button('取消','task-control',{id:t.id,command:'cancel'},'button small danger-text'):''}</div></article>`).join(''):empty('当前没有相关任务','发起委托后可以查看接收、执行、等待与完成的真实状态。');}
function activityView(){const tabs=[['tasks','研究任务'],['decisions','研究问题'],['feedback','意见与反馈'],['growth','成长比较'],['development','产品建设']];let body='';
 if(ui.tab==='tasks')body=`<div class="section-heading"><h2>任务执行</h2><div class="button-group">${button('发起委托','new-task',{},'button')}${button('协作委托','new-cycle',{},'button primary')}</div></div>${taskList(list(ui.data.tasks).filter(t=>!ui.project||!t.project_id||t.project_id===ui.project||t.payload?.context?.project_management?.project_ids?.includes(ui.project)))}`;
 if(ui.tab==='decisions')body=questionsPanel(list(ui.data.questions),ui.project);
 if(ui.tab==='feedback')body=`<div class="section-heading"><h2>意见与反馈</h2>${button('记录反馈','feedback',{},'button primary')}</div><p class="hint">原话、理解、任务结果与工作方式行动保持关联。保存或暂缓意见不会发起执行。</p>${list(ui.data.feedback).filter(f=>!ui.project||f.project_id===ui.project).map(f=>feedbackCard(f,{tasks:list(ui.data.tasks),objects:objects()})).join('')||empty('尚无已登记反馈','在成果旁或这里留言，再明确安排有关行动。')}`;
 if(ui.tab==='growth')body=`<div class="section-heading"><h2>成长候选与比较</h2>${button('提出候选','growth-propose',{},'button primary')}</div><p class="hint">规则登记、单任务试用、真实介入、配对观察和限定采用分别留证。不会自动派活；科研质量与跨任务有效性需另外验证。</p>${list(ui.data.growth).filter(g=>!ui.project||g.project_id===ui.project).map(g=>growthCard(g,list(ui.data.tasks))).join('')||empty('改进需要后续工作的证据','从真实反馈提出最小改动，也可明确保存未验证偏好。')}`;
 if(ui.tab==='development')body=developmentView.render(ui.data.development,ui.data.implementation,ui.data.capabilities);
 return `<div class="view-heading"><div><span class="eyebrow">WORK & LEARNING</span><h1>任务与成长</h1><p>成果持续推进，改进保留依据。</p></div></div><div class="tabs">${tabs.map(([t,label])=>button(label,'activity-tab',{tab:t},`tab ${ui.tab===t?'active':''}`)).join('')}</div><div class="activity-content">${body}</div>`;}
function settingsView(){return `<div class="view-heading"><div><span class="eyebrow">YOUR ENVIRONMENT</span><h1>设置与扩展</h1><p>数据与运行环境由你掌握，服务能力有明确边界。</p></div></div><div class="settings-grid"><section class="panel"><h2>模型与执行环境</h2>${list(ui.data.providers).map(p=>`<div class="provider-item"><div class="section-heading"><h3>${esc(p.name||p.id||p.provider)}</h3>${status(p.status||(p.available?'available':'unavailable'))}</div><p>${esc(p.model||p.description||'')}</p><p class="hint">${esc(p.reason||p.error||'')}</p><p class="hint">${esc(p.note||'')} · ${p.authorized?'已有调用授权':'尚未授权实际调用'}</p></div>`).join('')||'<p class="hint">服务端没有返回可用模型提供者。此时仍可编辑与导出本地成果。</p>'}<p class="hint">提供者、运行入口和凭据通过自有主机配置文件设置；修改后重启服务。此页面只显示探测状态，实际调用以任务记录为准。</p><details><summary>运行实现</summary><pre>${esc(pretty(ui.data.implementation||{}))}</pre></details></section><section class="panel"><div class="section-heading"><h2>已注册扩展</h2>${button('注册扩展','extension-register',{},'button small')}</div>${list(ui.data.extensions).map(e=>`<article class="extension-item" data-extension-id="${esc(e.id)}"><h3>${esc(e.name||e.id)}</h3><p>${esc(e.description||'')}</p>${status(e.status||'unverified')} ${status(e.authorized?'authorized':'unauthorized')}<p class="hint">版本 ${esc(e.version)} · 清单 SHA ${esc(e.manifest_sha256)}</p><details><summary>权限与兼容信息</summary><pre>${esc(pretty(e))}</pre></details><div class="button-group">${e.status==='installed'?`${button('管理授权','extension-authorize',{id:e.id},'button small')}${e.authorized?button('调用','extension-call',{id:e.id},'button small'):''}${e.permissions?.length?button('撤销授权','extension-revoke',{id:e.id},'button small subtle'):''}${button('升级','extension-upgrade',{id:e.id},'button small')}${button('卸载','extension-uninstall',{id:e.id},'button small danger-text')}`:''}${e.versions?.some(v=>v.sha256!==e.manifest_sha256)?button('回退版本','extension-rollback',{id:e.id},'button small subtle'):''}</div></article>`).join('')||'<p class="hint">没有已注册扩展。注册与授予权限是两个独立步骤。</p>'}</section><section class="panel"><h2>研究约定与偏好</h2><p class="hint">限定作用范围，保留可纠正的记录。单次意见不会自动成为全局规则。</p>${button('记录项目约定','preference',{},'button small')}${button('编辑偏好','setting-edit',{key:'preferences'},'button small')}${button('编辑领域约定','setting-edit',{key:'domain'},'button small')}<pre>${esc(pretty(ui.data.preferences||ui.data.conventions||{}))}</pre></section><section class="panel"><h2>数据与迁移</h2><p>备份包含成果身份、修订、批注与关系。缺失依赖和凭据由服务端按实际范围说明。</p>${button('导出工作空间备份','backup',{},'button small')}<details><summary>网络与访问边界</summary><pre>${esc(pretty(ui.data.security||ui.data.capabilities?.security||{}))}</pre></details></section></div>`;}

function ensureProject(){if(ui.project)return true;toast('请先选择或创建所属研究项目。');newProject();return false;}
function newProject(){modal('创建研究项目',`${field('项目名称','title','','text','required')}${field('核心问题与研究来由','description','','textarea','required')}`,{label:'创建项目',submit:async v=>{const r=await action('project.create',{title:v.title,description:v.description,content:{description:v.description}});await refresh({render:false});ui.project=r.id||r.object?.id||r.project?.id||'';ui.view='projects';draw();toast('项目已创建。');}});}
function newArtifact(forcedKind){if(!ensureProject())return;const options=Object.entries(kinds).filter(([k])=>!['project','workshop','literature','growth','feedback'].includes(k));modal('新建学术成果',`${field('成果标题','title','','text','required')}${select('成果类型','kind',options,forcedKind||'report')}${field('研究问题与用途','purpose','','textarea')}`,{label:'创建并打开',submit:async v=>{const r=await action('object.create',{project_id:ui.project,title:v.title,kind:v.kind,content:newContent(v.kind),metadata:{purpose:v.purpose}});await refresh({render:false});const id=r.id||r.object?.id;if(id)await openObject(id);else{draw();toast('服务端已接收创建请求；请从项目成果中查看返回对象。');}}});}
function newTask(revision=false,collaborative=false){
  if(revision)return feedback('revision');
  const target=null;
  const projectId=ui.project||undefined,requestKey=uid(collaborative?'cycle':'commission');let plan=null,previewSignature='',sequence=0;
  const dialog=modal(revision?'请求 Agent 修订':collaborative?'发起协作研究委托':'发起研究委托',`${target?`<div class="notice">目标：${esc(target.title)} · 修订 ${esc(target.revision)}。先保存需要纳入修订的本地草稿。</div>`:''}${field('研究目的：希望得到什么、用来判断什么','objective','','textarea','required')}<p class="hint">直接写项目、材料名称或研究领域。预览本站材料与明确要求的有限文献查询，不调用模型或联网；当前项目只是上下文，明确提到的另一项目会优先核对。</p><div id="commission-resolution"></div><details><summary>补充来源、范围、产出与有限额度</summary>${acquisitionFields()}${field('明确补充成果 ID（可加 @修订号，每行一项）','additional_materials','','textarea')}${field('补充研究背景','background','','textarea')}${field('方法与授权边界','constraints','读取采用材料，保留来源和不确定性；不改原始数据，不启动新拟合或未经授权的服务。','textarea')}${field('如何判断产出可用','acceptance','形成可编辑成果，说明问题、证据、限制和下一步，进入独立审阅；不以模型返回代替验收。','textarea')}${select('成果类型','output_kind',[['','按研究目的选择'],['report','分析或调研报告'],['note','研讨笔记'],['paper','论文'],['diagram','概念图 / 流程图'],['poster','海报'],['slides','汇报与逐页讲稿']],target?.kind||'')}${field('未决事项','open_questions','','textarea')}${collaborative?cycleFields(list(ui.data.providers)):`${select('模型提供者','provider',[['','使用空间默认路线'],...list(ui.data.providers).map(p=>[p.id,p.name||p.id])])}<div class="field-grid">${field('模型调用次数上限','budget','4','number','min="1" max="100" step="1" required')}${field('执行秒数上限','timeout','300','number','min="1" max="900" required')}${field('优先级','priority','0','number','step="1"')}</div>`}</details>`,{wide:true,label:'查找项目与材料',submit:async(v,form)=>{
    const input=resolutionRequest(v,{projectId,target}),signature=resolutionSignature(input),active=()=>form.isConnected&&!ui.authGate;
    if(!plan||signature!==previewSignature||!plan.project){
      const turn=++sequence;let result;
      try{result=await action('task.resolve',input);}catch(error){if(!active())return false;throw error;}
      if(!active()||turn!==sequence)return false;
      // Input changes while a lookup is pending cannot authorize its old preview.
      const latest=resolutionRequest(Object.fromEntries(new FormData(form)),{projectId,target});
      if(resolutionSignature(latest)!==signature){plan=null;toast('目的或项目选择已变化，请重新查找。');return false;}
      plan=result;previewSignature=signature;form.querySelector('#commission-resolution').innerHTML=resolutionPanel(result);
      if(input.selected_project_id)form.querySelector('[name=selected_project_id]').value=input.selected_project_id;
      form.querySelector('button[type=submit]').textContent=result.project?'确认采用并提交':'选择项目后重新查找';return false;
    }
    if(!active())return false;
    const fields={...input,resolution_pin:plan.pin,selected_materials:chosenMaterialRefs(form),request_key:requestKey,expected_revision:target?.revision,provider_id:v.provider||undefined,output_kind:v.output_kind||undefined,constraints:v.constraints,acceptance:v.acceptance,budget:{max_model_calls:Number(v.budget)||4,timeout_seconds:Number(v.timeout)||300},priority:Number(v.priority)||0,unresolved:v.open_questions?[v.open_questions]:[],background:v.background};
    let r;try{
      r=await action(collaborative?'cycle.submit':'task.submit',collaborative?{...fields,...cycleParameters(v)}:fields);
    }catch(error){if(error.status===409){plan=null;previewSignature='';if(active()){form.querySelector('#commission-resolution').innerHTML='<p class="notice">来源、项目或采用选择需要重新核对；目的与补充内容保留。请重新查找。</p>';form.querySelector('button[type=submit]').textContent='重新查找项目与材料';}}if(!active())return false;throw error;}
    if(!active()){toast(`委托已接收 ${r.id||r.task?.id}，当前界面保留。`);return false;}
    await refresh({render:false});if(!active())return false;toast(`已接收委托 · ${r.id||r.task?.id}`);ui.view='activity';ui.tab='tasks';draw();
  }});
}

// Updating a property must not replace the inspector that is receiving the next click.
function bindEditorCanvas(root){
 bindCanvasDrag(root,context(),{selectItem:(id,multi,redraw=true)=>{if(multi){ui.selectedItems=ui.selectedItems.includes(id)?ui.selectedItems.filter(i=>i!==id):[...ui.selectedItems,id];}else ui.selectedItems=[id];ui.selectedItem=ui.selectedItems.includes(id)?id:ui.selectedItems.at(-1)||'';if(redraw)draw();},mutate,redraw:draw});
 if(ui.object?.kind==='figure'&&!ui.draft?.content?.composition){
  figureInteractionDisposer?.();colorDisposer?.();const source=editorSnapshot();
  figureInteractionDisposer=bindFigureInteraction(root,{object:figureVisualObject(),content:ui.draft.content,selectedId:ui.selectedItem,isCurrent:()=>sameEditor(source),onSelect:(id,{redraw}={})=>{if(ui.selectedItem!==id)ui.figureCmapScope='matching';ui.selectedItem=id;if(redraw)draw();if(ui.dirty||figurePreviewController?.isBusy())scheduleFigurePreview();},onOverlay:(id,key,value)=>{requireEditor(source);ui.selectedItem=id;setFigureOverlay(key,value,{redraw:true});},onAnnotate:anchor=>{requireSavedFigureAnchor();annotate(anchor);},onOpenCode:()=>editFigureCode().catch(e=>toast(errorMessage(e),'error')),onError:e=>toast(errorMessage(e),'error')});
  colorDisposer=bindColorControls(root,(key,value)=>{try{setFigureOverlay(key,value);}catch(error){toast(errorMessage(error),'error');}});writeFigurePreviewStatus();
 }
}
function refreshEditorPreview(){
 if(ui.view!=='workspace'||!ui.object||!ui.draft)return false;
 const selector=ui.object.kind==='diagram'?'[data-diagram]':'[data-canvas]',current=app.querySelector(selector);
 if(!current)return false;
 const fragment=document.createElement('template');fragment.innerHTML=renderEditor(context());
 const next=fragment.content.querySelector(selector);if(!next)return false;
 desk.detachViewport();current.replaceWith(next);bindEditorCanvas(next);desk.reattachViewport();
 const meta=app.querySelector('[data-canvas-meta]'),nextMeta=fragment.content.querySelector('[data-canvas-meta]');
 if(meta&&nextMeta)meta.textContent=nextMeta.textContent;
 // A blur may precede a page-thumbnail click. Keep the actual receiving button.
 const pages=app.querySelector('[data-page-list]'),nextPages=fragment.content.querySelector('[data-page-list]');
 if(pages&&nextPages)for(const page of pages.querySelectorAll('[data-action="page-select"]')){
  const fresh=nextPages.querySelector(`[data-action="page-select"][data-index="${CSS.escape(page.dataset.index)}"]`);
  if(fresh)for(const tag of ['strong','small']){const label=page.querySelector(tag),updated=fresh.querySelector(tag);if(label&&updated&&label.textContent!==updated.textContent)label.textContent=updated.textContent;}
 }
 const warnings=app.querySelector('[data-diagram-warnings]'),updated=fragment.content.querySelector('[data-diagram-warnings]');
 if(warnings&&updated)warnings.innerHTML=updated.innerHTML;
 return true;
}
function annotate(explicitAnchor=null){
 if(ui.object?.kind==='figure')requireSavedFigureAnchor();
 if(ui.manuscriptRevisionView&&ui.manuscriptRevisionView!=='clean')throw new Error('正在查看未采用候选或冻结原稿。请回当前正文批注，或先采用候选。');
 if(ui.selectedBlock&&!ui.object?.content?.blocks?.some(b=>b.id===ui.selectedBlock))throw new Error('这是尚未采用的新增段落。先记录并采用修订，或回原文批注。');
 if(!ui.object||!ui.draft)return;
 const source=editorSnapshot(),block=ui.draft.content.blocks?.find(b=>b.id===ui.selectedBlock),node=ui.draft.content.nodes?.find(n=>n.id===ui.selectedItem);
 if(block&&JSON.stringify(block)!==JSON.stringify(ui.object.content.blocks.find(b=>b.id===block.id)))throw new Error('当前段落有未采用编辑。先记录并采用修订，或回已保存原文批注。');
 const anchor=explicitAnchor||(block?{block_id:block.id}:node?{node_id:node.id}:ui.selectedItem&&ui.object.kind==='figure'&&!ui.draft.content.composition?figureArtistAnchor(ui.object,ui.selectedItem):ui.selectedItem?{object_id:ui.selectedItem}:{object_id:source.id});
 let quote='';const active=document.activeElement;if(active?.matches('.block-editor'))quote=active.value.slice(active.selectionStart,active.selectionEnd);if(!quote&&ui.textSelection?.objectId===source.id&&ui.textSelection?.blockId===block?.id)quote=ui.textSelection.quote;if(!quote&&block)quote=block.text.slice(0,120);if(quote)anchor.quote=quote;
 modal('添加对象批注',`${quote?`<blockquote>${esc(quote)}</blockquote>`:''}${field('批注','text','','textarea','required')}<p class="hint">批注绑定 ${esc(source.id)} · 修订 ${source.revision} 的${esc(block?'当前段落':node?'当前节点':ui.selectedItem?'当前画布对象':'整个成果')}。</p>`,{submit:async v=>{
  requireEditor(source);await action('annotation.add',{object_id:source.id,revision:source.revision,anchor,text:v.text});
  toast(`${source.id} · 修订 ${source.revision} 的批注已保存。`);
  try{await readEditorDetails(source);if(sameEditor(source)){ui.workspacePanel='comments';draw();}}catch(error){toast(`批注已保存；读取 ${source.id} 的批注列表失败：${error.message}`,'error');}
 }});
}
async function resolveAnnotation(d){
 if(!ui.object)return;const source=editorSnapshot();
 // A status change must not resubmit a stale copy of the annotation's text.
 await action('annotation.update',{id:d.id,object_id:source.id,status:d.status});
 toast(`${source.id} 的批注状态已保存。`);
 try{await readEditorDetails(source);}catch(error){toast(`批注状态已保存；读取 ${source.id} 的列表失败：${error.message}`,'error');}
}
function restoreRevision(revision){
 if(!ui.object)return;const opened=editorSnapshot();
 modal('恢复历史内容',`<p>将 ${esc(opened.id)} 修订 ${revision} 恢复为新修订。当前草稿${ui.dirty?'会先下载保留':'没有未保存修改'}；请求之后的新编辑、历史和反馈均保留。</p>`,{label:'恢复为新修订',submit:async()=>{
  requireEditor(opened);if(ui.object.revision!==opened.revision)throw new Error('成果基础修订已变化，请重开历史并核对。');
  const source=editorSnapshot();if(ui.dirty)downloadJSON(`${source.id}-draft.json`,source.draft);
  return editorWrite(source,'object.restore',{id:source.id,expected_revision:source.revision,revision},{restore:true});
 }});
}

let revisionComparisonTurn=0;
function showHistory(){
 if(!ui.object)return;const source=editorSnapshot(),revisions=list(ui.object.revisions);
 const dialog=modal(`修订历史 · ${source.id}`,`<p class="hint">${esc(source.id)} · 当前基础修订 ${source.revision}。恢复历史内容会创建同一成果的新修订，批注与反馈保留。</p><div class="revision-list">${revisions.map(r=>`<div class="list-row"><div><strong>修订 ${esc(r.revision||r.version)}</strong><small>${date(r.created_at)} · ${esc(r.author||r.source||'')}</small></div><div>${button('比较','revision-diff',{revision:r.revision||r.version},'button small')}${button('恢复','revision-restore',{revision:r.revision||r.version},'button small')}</div></div>`).join('')||'<p>服务端没有返回历史内容。</p>'}</div>`,{wide:true});
 ui.historySession={source,dialog};
}
async function showRevisionDiff(revision){
 const history=ui.historySession;
 if(!history?.dialog.active())throw new Error('历史窗口已关闭，请重新打开原成果的修订历史。');
 requireEditor(history.source);
 if(!Number.isInteger(revision)||revision<1)throw new Error('请选择确切的历史修订。');
 // Capture both sides' identity before I/O. A later draft is never substituted.
 const source=editorSnapshot(),capturedAt=new Date().toISOString(),turn=++revisionComparisonTurn;
 const identity=`${source.id} · 历史修订 ${revision} ↔ 点击比较时的本地草稿（基础修订 ${source.revision}）`;
 const dialog=modal(`修订比较 · ${source.id}`,`<p>${esc(identity)}</p><div id="revision-comparison"><p>正在读取确切历史修订…</p></div>`,{wide:true});
 const active=()=>dialog.active()&&sameEditor(source)&&turn===revisionComparisonTurn;
 const show=html=>{if(active()){const node=dialog.root.querySelector('#revision-comparison');if(node)node.innerHTML=html;}};
 try{
  const raw=await api(`/api/objects/${encodeURIComponent(source.id)}?revision=${revision}`);
  if(!active())return;
  const historical=raw.object||raw;
  if(historical.id!==source.id||historical.revision!==revision||!historical.content)throw new Error('历史内容的成果／修订身份不匹配；未采用其他版本。');
  const newer=!draftEqual(ui.draft,source.draft)||ui.object.revision!==source.revision;
  const compared=diff(pretty({title:historical.title,content:historical.content}),pretty(source.draft))
   .replace('<b>历史 / 服务器版本</b>',`<b>${esc(source.id)} · 历史修订 ${revision}</b>`)
   .replace('<b>当前版本 / 本地草稿</b>',`<b>点击比较时的本地草稿 · 基础修订 ${source.revision}</b>`);
  show(`<p>${esc(identity)}</p><p class="hint">草稿快照捕获于 ${esc(capturedAt)}；包含当时的标题与正文。${newer?'当前编辑区在点击之后已变化；本窗仍使用点击时的快照，不包含后续编辑。':'后续编辑不会自动进入本次比较。'}</p>${historical.canonical_source_sha256?`<p class="hint">历史来源 SHA256：${esc(historical.canonical_source_sha256)}</p>`:''}${compared}`);
 }catch(error){show(`<p class="warning-text">无法读取 ${esc(source.id)} · 修订 ${revision}：${esc(error.message)}</p><p>没有回退到最新版本；请重新打开历史并重试。</p>`);}
}

async function showConflict(error,source=editorSnapshot()){
 const raw=await api(`/api/objects/${encodeURIComponent(source.id)}`);if(!sameEditor(source))return;
 const latest=raw.object||raw;let dialog;
 dialog=modal('并行修订：你的草稿已保留',`<p>${esc(source.id)} 服务器修订 ${esc(latest.revision)} 与本地基础修订 ${esc(ui.object.revision)} 不同。请比较后选择。重新载入之前可下载草稿，任何选择均不会删除反馈。</p>${error?`<p class="warning-text">${esc(error.message)}</p>`:''}${diff(pretty(latest.content),pretty(ui.draft.content))}<div class="button-group">${button('下载本地草稿','draft-download',{},'button')}${button('保留草稿，以新修订为基础继续','conflict-rebase',{revision:latest.revision},'button')}${button('载入服务器内容','conflict-reload',{},'button')}</div>`,{wide:true});
 // Choices are valid only for the editor for which this comparison was opened.
 ui.conflictSource=source;
}

function modalActionOnce(e){const b=e.target.closest('[data-action]');if(b)handle(b.dataset.action,b.dataset,e).catch(()=>{});}
function downloadJSON(name,data){const blob=new Blob([pretty(data)],{type:'application/json;charset=utf-8'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function showExport(){
 if(!ui.object)return;
 const source={id:ui.object.id,revision:ui.object.revision,kind:ui.object.kind,project_id:ui.object.project_id,title:ui.object.title,content:clone(ui.object.content)};
 const projectId=source.project_id||ui.project;
 const receiptRevisions=[...new Set([source.revision,...list(ui.object.revisions).map(entry=>entry.revision)])].filter(Number.isInteger).sort((a,b)=>b-a);
 let dialog,session;
 const link=(x,label)=>{const url=assetURL(x.url||x.asset||x.sha||x.sha256||x.asset_id||x);return url?`<p><a class="button" href="${esc(url)}" target="_blank" rel="noopener" download="${esc(x.name||x.filename||'')}">${esc(label||x.name||x.filename||'下载导出件')}</a></p>`:`<pre>${esc(pretty(x))}</pre>`;};
 const renderResult=r=>{
  const files=r.assets?Object.entries(r.assets).map(([name,x])=>({...x,name})):list(r.files||[r.asset||r]);
  const packed=r.provenance?.document_package;
  const notice=packed?`请下载并完整解压${packed.format==='markdown'?' Markdown':'纯文本'}交付包。单独下载文稿时，图片仍需包内 assets/ 目录。`:'文件已由服务端生成，请打开检查内容与版面。';
  return `<div class="notice">${notice}</div>${r.warnings?.length?r.warnings.map(w=>typeof w==='string'&&w.startsWith('Supported Markdown:')?`<details class="notice"><summary>Word 格式说明：公式以图片呈现，原公式源稿随附</summary><p>这份文件供阅读和内容编辑。公式不是可直接编辑的 Word 公式，也不是 LaTeX 编译结果。</p><p>${esc(w)}</p></details>`:`<div class="notice warning">${esc(typeof w==='string'?w:pretty(w))}</div>`).join(''):''}${packed?`${link(r.asset,packed.format==='markdown'?'下载完整 Markdown 交付包 (.zip)':'下载纯文本与图片交付包 (.zip)')}<details><summary>单独文件与确切资源清单</summary>${files.filter(x=>x.sha!==r.asset?.sha).map(x=>link(x)).join('')}</details>`:r.asset?.filename?.endsWith('.zip')?`${link(r.asset,'下载完整移交包 (.zip)')}<details><summary>单独文件与来源清单</summary>${files.filter(x=>x.sha!==r.asset.sha).map(x=>link(x)).join('')}</details>`:r.asset?`${link(r.asset,'下载 '+(r.asset.filename||'导出成果'))}${files.some(x=>x.sha!==r.asset.sha)?`<details><summary>源稿、代码与其他附件</summary>${files.filter(x=>x.sha!==r.asset.sha).map(x=>link(x)).join('')}</details>`:''}`:files.map(x=>link(x)).join('')}<details><summary>导出来源与检查记录</summary><pre>${esc(pretty(r.provenance||r.metadata||{}))}</pre></details>`;
 };
 dialog=modal(`导出成果 · ${source.title||source.id}`,`<p>导出已保存的修订 ${esc(source.revision)}。${ui.dirty?'<strong>本地未保存的修改不包含在这次服务器修订导出中。</strong>':''}</p>${select('格式','format',exportFormats(source.kind).map(f=>[f,{md:source.kind==='slides'?'逐页 Markdown 讲稿':'Markdown 文稿（含图时附资源 ZIP）',txt:source.kind==='slides'?'逐页纯文本讲稿':'纯文本文稿（图片引用保留为文字）',docx:'Word 内容稿 (.docx)',pdf:'阅读 / 布局 PDF',zip:'完整移交 ZIP（采用版本、源码、输入与依赖）',tex:'LaTeX 源稿',bib:'BibTeX 引用',svg:'矢量 SVG',png:'PNG 预览',json:'可编辑结构源',pptx:'可编辑 PowerPoint'}[f]]))}<div id="export-result"></div><details><summary>格式与来源说明</summary>${paperExportNotice(source)}<p>来源 ${esc(source.id)} · 修订 ${esc(source.revision)}。</p><p>含图 Markdown 需下载并完整解压资源 ZIP。完整移交包另含采用版本、源码与依赖。</p><p>关闭弹窗不取消已提交的导出；下方可重新读取完成回执。文件生成不代表科学或接收环境验收。</p></details><details><summary>此成果的已完成导出</summary>${select('回执来源修订','receipt_revision',receiptRevisions.map(revision=>[revision,'修订 '+revision]),source.revision)}<button type="button" class="button small" data-export-receipts>重新读取导出回执</button><div id="export-receipts">正在读取服务器回执。</div></details>`,{label:'生成导出文件',submit:v=>session.submit(v)});
 const active=()=>!ui.authGate&&dialog.active();
 session=createExportSession({source,projectId,isActive:active,
  request:(name,fields)=>api('/api/action',{method:'POST',body:JSON.stringify({action:name,...fields})}),read:api,
  present:r=>{const node=dialog.form.querySelector('#export-result');if(node)node.innerHTML=renderResult(r);},
  receipts:(records,revision)=>{const node=dialog.form.querySelector('#export-receipts');if(node)node.innerHTML=`<p class="hint">${esc(source.id)} · 修订 ${esc(revision)}</p>`+(records.length?[...records].reverse().map(record=>`<details><summary>${esc(record.created_at||'已完成')} · ${esc(record.result.asset?.filename||'导出件')}</summary>${renderResult(record.result)}</details>`).join(''):'该修订暂未登记已完成导出。');},
  receiptError:error=>{const node=dialog.form.querySelector('#export-receipts');if(node)node.textContent=`读取回执失败：${error.message}`;}
 });
 dialog.form.querySelector('[data-export-receipts]')?.addEventListener('click',()=>session.reload());
 dialog.form.querySelector('[name=receipt_revision]')?.addEventListener('change',event=>session.reload(Number(event.target.value)));
 void session.reload();
}
function literatureImport(record){if(!ensureProject())return;if(record){return action('literature.import',{project_id:ui.project,format:'json',records:[record],text:pretty([record])}).then(()=>refresh()).then(()=>toast('文献已导入，来源与阅读范围请核对。'));}const dialog=modal('导入文献',`${select('格式','format',[['bibtex','BibTeX'],['ris','RIS'],['json','JSON 文献记录']])}<label class="field"><span>从本机文件读取</span><input type="file" id="bib-file" accept=".bib,.ris,.json,.txt"></label>${field('文献原始内容','text','','textarea','required rows="12"')}<p class="hint">实际导入结果由服务端去重与字段核对决定；仅有元数据不会被标记为已读全文。</p>`,{wide:true,label:'导入并核对',submit:async v=>{const r=await action('literature.import',{project_id:ui.project,...v});await refresh();toast(`文献已处理 · 新增 ${r.created?.length||0} 条，重复 ${r.duplicates?.length||0} 条，待补字段 ${r.warnings?.length||0} 条`);}});dialog.root.querySelector('#bib-file').addEventListener('change',async e=>{const file=e.target.files[0];if(file)dialog.root.querySelector('[name=text]').value=await file.text();});}
function graphRelate(){if(!ensureProject())return;const opts=objects().filter(o=>!o.archived).map(o=>[o.id,o.title]);modal('建立研究关系',`${select('来源对象','src',opts)}${select('目标对象','dst',opts)}${select('关系含义','type',[['studies','研究'],['uses','使用'],['produces','产生'],['contains','组成'],['cites','引用'],['supports','支持'],['limits','限制'],['related','关联']])}${select('证据状态','status',[['candidate','候选关联'],['confirmed','已确认']])}${field('关系依据','evidence','','textarea')}`,{submit:async v=>{if(v.src===v.dst)throw new Error('请选择两个不同对象。');await action('graph.relate',{...v,metadata:{evidence:v.evidence}});await refresh();}});}
async function loadReferences(){
 if(!ui.object)return;
 const requestToken=Symbol('reference-read');ui.referenceReadToken41=requestToken;
 const owner=ui.object,refs=documentReferences({...owner,content:ui.draft.content});
 const results=await Promise.all(refs.map(async ref=>{try{const {source}=await readExactReference(api,ref,{consumerId:owner.id});return [referenceKey(ref),source,null];}catch(error){return [referenceKey(ref),null,referenceFailure(error)];}}));
 if(ui.referenceReadToken41!==requestToken||ui.object!==owner||ui.authGate||!sameJSON41(documentReferences({...owner,content:ui.draft.content}),refs))return;
 ui.references=Object.fromEntries(results.map(([key,source])=>[key,source]));ui.referenceErrors=Object.fromEntries(results.filter(r=>r[2]).map(([key,,error])=>[key,error]));
 if(ui.view==='workspace'&&refs.length&&!(owner.kind==='figure'&&!owner.content?.composition)&&!document.activeElement?.matches('input,textarea'))draw();
}
async function showSourceImpacts(){
 const source=editorSnapshot(),dialog=modal('源组件的采用位置','<p data-impact-results>正在核对当前可读范围内的采用位置…</p>',{wide:true});
 try{
  const state=await api('/api/state');if(!dialog.active()||!sameEditor(source))return;
  const current=list(state.objects).find(o=>o.id===source.id);
  if(!current)throw new Error('当前访问范围已不能读取该源成果；未显示旧缓存位置。');
  dialog.form.querySelector('[data-impact-results]').outerHTML=`<div data-impact-results>${impactPanel(current,sourceImpacts(current,state.objects,state.relations))}</div>`;
 }catch(error){if(dialog.active()&&sameEditor(source))dialog.form.querySelector('[data-impact-results]').textContent=error.message;}
}
async function locateSourceImpact(pin,trigger){
 const origin=editorSnapshot(),dialog=trigger?.closest('.modal'),active=()=>sameEditor(origin)&&(!dialog||dialog.isConnected);
 const current=await api(`/api/objects/${encodeURIComponent(pin.consumer_id)}`);
 if(!active())return;
 const bound=assertImpactLocation(current,pin);
 // Recheck current permission and any exact adopted hash; never substitute the source head.
 await readExactReference(api,bound.ref,{consumerId:current.id});if(!active())return;
 if(dialog)document.querySelector('#modal-root').innerHTML='';
 let destinationGeneration=loadCounter;
 if(ui.object.id!==current.id){destinationGeneration=loadCounter+1;await openObject(current.id);}
 if(ui.authGate||ui.auth!==origin.auth||loadCounter!==destinationGeneration||ui.view!=='workspace'||ui.object?.id!==current.id)return;
 assertImpactLocation({...ui.object,content:ui.draft.content},pin);
 const location=pin.locator;
 if(location.kind==='canvas'){
  ui.page=ui.draft.content.pages.findIndex(p=>p.id===location.page_id);ui.selectedItem=location.item_id;ui.selectedItems=[location.item_id];draw();
  document.querySelector(`[data-item="${CSS.escape(location.item_id)}"]`)?.scrollIntoView({block:'center',inline:'center'});
  document.querySelector(`[data-item="${CSS.escape(location.item_id)}"]`)?.focus({preventScroll:true});
 }else{
  const node=document.querySelector(`[data-component-index="${location.index}"]`);
  if(!node){modal('组成组件的只读位置说明',`<p>${esc(current.id)} · 以修订 ${esc(pin.consumer_revision)} 为基础 · ${esc(bound.label)}。</p><p>当前编辑模式未展示结构稿的组成组件；本次未切换编辑或导出来源，也未改写任何文稿。可只读查看已登记的确切来源。</p>${button('只读查看采用来源','open-reference',{...bound.ref,consumer_id:current.id},'button small')}`,{wide:true});return;}
  node.scrollIntoView({block:'center',inline:'center'});node.focus({preventScroll:true});
 }
 toast(`已定位 ${current.id} 以修订 ${pin.consumer_revision} 为基础的采用位置；来源仍为 ${pin.source_id} @${bound.ref.revision}${ui.dirty?'，未保存编辑保留在本地':''}。`);
}
async function showReference(id,revision,block_id,sha256,consumerId){
 // Always recheck current permission. A previously cached adopted source is not an access grant.
 if(ui.dirty)persistDraft();const owner=ui.object;
 const loading=modal('读取采用来源','<p>正在读取指定修订。当前草稿与冲突状态保留。</p>');
 try{
  const result=await readExactReference(api,{id,revision,...(block_id?{block_id}:{}),...(sha256?{sha256}:{})},{consumerId:consumerId||(ui.view==='workspace'?owner?.id:undefined)});
  if(!loading.active()||ui.object!==owner||ui.authGate)return;
  const dialog=modal(`采用版本 · ${result.source.title}`,referenceReading(result),{wide:true});
  if(block_id&&!result.missingAnchor)dialog.root.querySelector(`[data-reference-block="${CSS.escape(block_id)}"]`)?.scrollIntoView({block:'center'});
 }catch(error){
  if(!loading.active()||ui.object!==owner||ui.authGate)return;
  const failure=referenceFailure(error);ui.references[`${id}@${revision}`]=null;ui.referenceErrors||={};ui.referenceErrors[`${id}@${revision}`]=failure;
  modal('采用来源未解析',`<p>${esc(failure.message)}</p><p>${esc(id)} @${esc(revision)}。原稿与草稿保持原状。</p>`,{wide:true});
 }
}
async function graphReview(projectId=ui.project){
 const view=await action('graph.review',projectId?{project_id:projectId}:{});
 modal('图谱增量、依据与审查',graphReviewPanel(view,objects()),{wide:true});
}
async function graphProposalItem(id,itemId,draft=null){
 const proposal=await action('graph.proposal_view',{id}),item=proposal.items.find(i=>i.id===itemId);
 if(!item)throw new Error('此提案条目已变化，请重新打开审查。');
 const submit=graphSubmission({base:proposal,conflicted:!!draft,read:()=>action('graph.proposal_view',{id}),request:(p,v)=>action('graph.proposal_review',{id,expected_revision:p.revision,item_id:itemId,decision:v.decision,reason:v.reason}),onSaved:async()=>{await refresh();toast('逐项审查已保存；采用状态以本轮实际记录为准。');}});
 const dialog=modal('逐项审查图谱增量',`${proposalView({...proposal,items:[item],duplicates:[]},{controls:false})}${select('审查判断','decision',[['needs_correction','需要纠正'],['accept','内容可接纳'],['reject','拒绝此项']])}${field('依据与具体修改要求','reason','','textarea','required')}${reconciliationSlot()}<p class="hint">本操作保存审查意见，不绕过协作委托的独立终审或自动授予科学确认。</p>`,{wide:true,label:draft?'保留草稿并重读比较':'记录审查',submit});
 if(draft)fillGraphDraft(dialog.form,draft);
}
async function stageCycleFinalRevision(parentId){
 const loading=modal('读取最终稿交接','<p>正在核对原最终稿、审查与成果版本。</p>');
 const read=async()=>{const view=await action('cycle.view',{id:parentId});const state=await api('/api/state');return {view,reports:state.objects};};
 const current=await read();if(!loading.active())return;
 if(!canStageFinalRevision(current.view)){modal('当前不能提交最终稿修订',`<p>${esc(current.view.final_revision_staging?.reason||'服务端未确认最终稿交接资格。')}</p>`,{wide:true});return;}
 const submit=finalRevisionSubmission({...current,read,action,requestKey:uid('cycle-final-revision'),saved:async(result,form)=>{
  await refresh();if(!form.isConnected)return;
  const view=await action('cycle.view',{id:parentId});if(!form.isConnected)return;
  modal('科研协作',cycleDetail(view)+finalRevisionPanel(view),{wide:true});toast('协调者最终稿修订已登记；原等待与预算保留，请另行明确继续安排独立最终审查。');
 }});
 const dialog=modal('预览协调者最终稿修订',finalRevisionFields(current.view,current.reports),{wide:true,label:'预览最终稿与差异',submit});
 dialog.form.addEventListener('input',()=>submit.invalidate(dialog.form));
 dialog.form.addEventListener('change',()=>submit.invalidate(dialog.form));
}
async function stageCycleRevision(parentId,delegateId){
 const loading=modal('读取修订交接状态','<p>正在读取当前协作与报告版本。</p>');
 const view=await action('cycle.view',{id:parentId});if(!loading.active())return;
 const state=await api('/api/state');if(!loading.active())return;
 const child=list(view.children).find(c=>c.id===delegateId);
 if(!child)throw new Error('当前协作中没有这项委托。');
 if(!canStageRevision(view,child)){modal('当前不能提交修订',`<p>${esc(child.revision_staging?.reason||'服务端未确认这项委托可以接收修订。请保留当前任务状态。')}</p>`,{wide:true});return;}
 const reports=revisionReports(state.objects,view.task.project_id);
 const submit=revisionSubmission({view,child,reports,action,requestKey:uid('cycle-revision'),saved:async(result,form)=>{
  await refresh();if(!form.isConnected)return;
  const current=await action('cycle.view',{id:parentId});if(!form.isConnected)return;
  modal('科研协作',cycleDetail(current),{wide:true});toast(result.parent_status==='waiting_resource'?'修订已登记供审查；原资源等待和已用额度保留，未继续父任务。':'修订已登记供审查；父任务保持等待，未调用模型。');
 }});
 const dialog=modal('关联修订报告',revisionFields(view,child,reports),{wide:true,label:'预览原候选与报告差异',submit:reports.length?submit:undefined});
 dialog.form.addEventListener('input',()=>submit.invalidate(dialog.form));
 dialog.form.addEventListener('change',()=>submit.invalidate(dialog.form));
}
async function recoverNativeCandidate(id){
 const loading=modal('读取原生候选','<p>正在核对同一任务、原生登记、用量与输入。不会调用模型。</p>');
 const initial=await action('task.recover_candidate_preview',{id});if(!loading.active())return;
 const canPreview=initial.ready||initial.suggested_revision;
 const submit=recoverySubmission({id,initial,action,requestKey:uid('native-recovery'),saved:async(result,form)=>{
  await refresh();if(!form.isConnected)return;
  modal('候选已接回',`<p>原生候选已保存供独立审查，模型归属和预算保留。父任务仍等待明确继续。</p><pre>${esc(pretty(result))}</pre>`,{wide:true});
 }});
 const dialog=modal('零调用候选接回预览',`<div data-recovery-preview>${recoveryPreview(initial)}</div>${canPreview?field('技术修复 / 接回理由','reason','','textarea','required maxlength="8000"'):''}`,{wide:true,label:'预览接回与精确差异',submit:canPreview?submit:undefined});
 dialog.form.addEventListener('input',()=>submit.invalidate(dialog.form));
 dialog.form.addEventListener('change',()=>submit.invalidate(dialog.form));
}
async function showCycleCandidate(parentId,delegateId,sha){
 const loading=modal('读取原候选','<p>正在核对候选身份。</p>');
 const view=await action('cycle.view',{id:parentId});if(!loading.active())return;
 const child=list(view.children).find(c=>c.id===delegateId);
 const candidate=[child?.candidate,...list(child?.candidate_history)].find(c=>c?.candidate_sha256===sha);
 if(!candidate)throw new Error('该候选当前不可读取；没有改用其他版本。');
 modal('原候选 · 只读',`<p class="hint">${esc(delegateId)} · ${esc(sha)}。查看不会调用模型。</p>${candidateReading(candidate)}`,{wide:true});
}
async function readGraphRelation(id){const view=await action('graph.review',{}),r=view.relations.find(r=>r.id===id);if(!r)throw new Error('关系不存在或当前身份无权读取。');return r;}
async function graphRelation(id,edit=false,draft=null){
 const r=await readGraphRelation(id);
 if(!edit){modal('关系依据与历史',relationView(r,objects()),{wide:true});return;}
 const choices=objects().map(o=>({...o}));
 const submit=graphSubmission({base:r,conflicted:!!draft,read:()=>readGraphRelation(id),request:(current,v)=>action('graph.relation_update',relationUpdate(current,v,choices)),onSaved:async()=>{await refresh();toast('关系新修订与原始历史已保存。');}});
 const dialog=modal('纠正或撤回关系',`${relationView({...r,revision:null},objects())}${relationEditFields(r,choices)}${reconciliationSlot()}`,{wide:true,label:draft?'保留草稿并重读比较':'保存关系新修订',submit});
 if(draft)fillGraphDraft(dialog.form,draft);
}
async function graphMerge(sourceId='',targetId='',draft=null){
 let preview=null;const opts=objectOptions();
 const dialog=modal('对照并合并重复研究对象',`${select('待合并对象','source_id',opts,sourceId)}${select('保留身份的对象','target_id',opts,targetId)}<div id="graph-merge-preview"><p class="hint">先读取双方定义、采用来源与当前版本，再确认合并。旧身份和布局会保留。</p></div>${field('为何可以合并','reason',draft?.reason||'','textarea')}`,{wide:true,label:'读取合并预览',submit:async(v,form)=>{
  if(v.source_id===v.target_id)throw new Error('两个对象不能相同。');
  if(!preview||preview.source.id!==v.source_id||preview.target.id!==v.target_id){
   const result=await action('graph.merge_preview',{source_id:v.source_id,target_id:v.target_id});
   if(!form.isConnected)return false;
   if(form.elements.source_id.value!==v.source_id||form.elements.target_id.value!==v.target_id)throw new Error('选择已变化，请重新预览。');
   preview=result;form.elements.reason.required=true;form.querySelector('#graph-merge-preview').innerHTML=mergePreview(preview);form.querySelector('button[type=submit]').textContent='确认合并这两个版本';return false;
  }
  try{await action('graph.merge',mergeRequest(preview,v.reason));}catch(error){if(error.status===409){preview=null;if(form.isConnected){form.querySelector('#graph-merge-preview').innerHTML='<p class="notice">对象或关系已变化。原判断保留，请重新读取双方版本与迁移预览。</p>';form.querySelector('button[type=submit]').textContent='重新读取合并预览';}}throw error;}await refresh();toast('重复对象已原子合并，旧身份和历史仍可读取。');
 }});
}
async function graphDuplicate(data,draft=null){
 const load=async()=>{const proposal=data.proposal?await action('graph.proposal_view',{id:data.proposal}):null;
  const duplicate=proposal?.duplicates?.find(d=>d.item_id===data.item&&(!data.target||d.target_id===data.target));
  const sourceId=duplicate?.source_id||data.source,targetId=duplicate?.target_id||data.target;
  if(!sourceId||!targetId)throw new Error('候选概念尚未形成可比较的对象；请查看逐项审查，不能提前合并。');
  return {proposal,duplicate,preview:await action('graph.merge_preview',{source_id:sourceId,target_id:targetId})};};
 const base=await load();
 const submit=graphSubmission({base,conflicted:!!draft,read:load,request:async(current,v)=>{
  if(!current.proposal){if(v.decision==='keep')throw new Error('此重复提示没有登记提案，请在有来源提案中记录保留判断。');return action('graph.merge',mergeRequest(current.preview,v.reason));}
  return action('graph.duplicate_resolve',{proposal_id:current.proposal.id,expected_revision:current.proposal.revision,item_id:current.duplicate?.item_id||data.item,...mergeRequest(current.preview,v.reason),decision:v.decision});
 },onSaved:async(result,v)=>{await refresh();toast(v.decision==='keep'?'已保留两种概念，并记录差异。':'已按明确判断合并，保留旧身份与关系历史。');}});
 const dialog=modal('疑似重复概念：对照与处理',`${mergePreview(base.preview)}${select('处理方式','decision',[['keep','保留为不同概念'],['reuse','确认等价，合并后复用右侧身份']])}${field('定义与来源比较理由','reason','','textarea','required')}${reconciliationSlot()}`,{wide:true,label:draft?'保留草稿并重读比较':'保存明确判断',submit});
 if(draft)fillGraphDraft(dialog.form,draft);
}
async function resumeGraphConflict(id){
 const view=await action('graph.review',{}),entry=list(view.conflicts).find(c=>c.id===id);
 if(!entry)throw new Error('冲突记录不存在或不可读取。');
 const d=entry.candidate||{},draft={...d,sources:list(d.source_refs).map(s=>`${s.id}@${s.revision}${s.block_id?'#'+s.block_id:''}`).join('\n')};
 if(entry.action==='graph.relation_update')return graphRelation(d.id,true,draft);
 if(entry.action==='graph.proposal_review')return graphProposalItem(d.id,d.item_id,draft);
 if(entry.action==='graph.duplicate_resolve')return graphDuplicate({proposal:d.proposal_id,item:d.item_id,source:d.source_id,target:d.target_id},draft);
 if(entry.action==='graph.merge')return graphMerge(d.source_id,d.target_id,draft);
 if(entry.action==='graph.relate'){const relation=view.relations.find(r=>r.src===d.src&&r.dst===d.dst&&r.type===d.type);if(relation)return graphRelation(relation.id,true,{...draft,reason:d.metadata?.evidence||'核对已存在关系后协调',sources:list(d.metadata?.source_refs).map(r=>`${r.id}@${r.revision}${r.block_id?'#'+r.block_id:''}`).join('\n')});}
 throw new Error('此冲突不能自动转换为当前编辑，请查看原候选与当前记录。');
}
function saveSharedComponentTrail41(trail){const key=desk.componentKey(trail.link.linkId),raw=JSON.stringify(packTrail41(JSON.parse(JSON.stringify(trail))));localStorage.setItem(key,raw);if(localStorage.getItem(key)!==raw)throw new Error('稿内分区返回路径未能保存。');}
function readSharedComponentTrail41(descriptor){
 const trail=unpackTrail41(JSON.parse(localStorage.getItem(desk.componentKey(descriptor.linkId))||'null'));
 if(!trail||trail.originRegion!=='primary'||trail.id!==descriptor.parentObjectId||trail.location?.id!==descriptor.objectId||trail.location?.index!==descriptor.componentIndex||trail.link?.linkId!==descriptor.linkId||trail.manuscriptBase?.id!==trail.id)throw new Error('此分区原稿上下文已变化，请从稿件中的准确位置重新进入。');
 return trail;
}
async function receiveComponentLink41(descriptor,{linkEpoch}={}){
 if(!desk.embedded||ui.view!=='workspace'||ui.object?.id!==descriptor.objectId||figureRenders.has(descriptor.objectId)||editorWrites.has(descriptor.objectId))return false;
 const pendingIntent=visualIntentStore41().read(descriptor.objectId);if(pendingIntent&&unpackTrail41(pendingIntent.trail)?.link?.linkId!==descriptor.linkId)throw new Error('副区有另一次尚未核对的采用，请先核对。');
 const trail=readSharedComponentTrail41(descriptor),parent=objects().find(o=>o.id===trail.id);
 if(!parent||parent.project_id!==ui.object.project_id)throw new Error('当前原稿不在可核对项目中。');
 ui.componentTrail=[trail];ui.componentLinkEpoch41={linkId:descriptor.linkId,linkEpoch};rememberComponentTrail();draw();return true;
}
function cancelComponentLink41(descriptor,{linkEpoch}={}){
 // A late cancellation must not retire a restored association with a new epoch.
 if(!Number.isSafeInteger(linkEpoch)||linkEpoch<=0||ui.componentLinkEpoch41?.linkId!==descriptor.linkId||ui.componentLinkEpoch41?.linkEpoch!==linkEpoch)return false;
 ui.componentLinkEpoch41=null;const before=ui.componentTrail||[];
 ui.componentTrail=before.filter(t=>t.link?.linkId!==descriptor.linkId);rememberComponentTrail();
 const key=desk.componentKey('latest');try{const latest=JSON.parse(localStorage.getItem(key)||'null');if(latest?.linkId===descriptor.linkId)localStorage.removeItem(key);}catch{}
 // Frozen shared trails, current drafts, notes, undo and pending visual receipts
 // remain intact. Cancellation is not a rollback of an explicit server commit.
 if(ui.componentTrail.length!==before.length){draw();toast('原稿关联已取消；图形草稿和编辑记录保留，请从原稿重新进入。','error');}
 return true;
}
async function receiveComponentCommit41(descriptor){
 if(desk.embedded||ui.view!=='workspace'||ui.object?.id!==descriptor.parentObjectId)return false;
 const intent=createVisualIntentStore({storage:localStorage,prefix:desk.navigationKey('secondary')}).read(descriptor.objectId);
 if(!intent||intent.request.request_key!==descriptor.requestKey)throw new Error('副区采用请求未能核对，原稿保留。');
 const trail=unpackTrail41(intent.trail);readSharedComponentTrail41(descriptor);
 if(trail?.link?.linkId!==descriptor.linkId||trail.id!==descriptor.parentObjectId||trail.location?.index!==descriptor.componentIndex)throw new Error('副区采用不属于本稿此处。');
 const receipt=await action('figure.visual.receipt',{id:descriptor.objectId,request_key:descriptor.requestKey});
 const result=await finishVisualReceipt41(receipt,intent,null,{hostCallback:true});return result.local_sync_complete;
}
async function receiveComponentReturn41(descriptor){
 if(desk.embedded||ui.view!=='workspace'||ui.object?.id!==descriptor.parentObjectId)return false;
 const trail=readSharedComponentTrail41(descriptor),ref=ui.draft?.content?.components?.[descriptor.componentIndex];
 if((ref?.id||ref?.object_id)!==descriptor.objectId)return false;
 manuscriptReturn={source:editorSnapshot(),location:trail.location,scroll:trail.scroll};draw();desk.focusPrimary();return true;
}
let restoringComponent41=false;
async function restoreLinkedComponent41(reason){
 if(desk.embedded||restoringComponent41)return;let descriptor;try{descriptor=JSON.parse(localStorage.getItem(desk.componentKey('latest'))||'null');}catch{return;}
 const region=desk.regionsState(),active=region?.componentLink;
 if(!descriptor||ui.object?.id!==descriptor.parentObjectId||region?.secondaryObjectId!==descriptor.objectId||!region?.ready||region?.pendingSecondaryObjectId||region?.pendingPrimaryObjectId||region?.componentBusy||region?.secondary?.saving||active&&active.linkId===descriptor.linkId&&active.objectId===descriptor.objectId&&active.parentObjectId===descriptor.parentObjectId&&active.componentIndex===descriptor.componentIndex)return;
 // Restore the exact prior desk link after both real editor identities are ready.
 restoringComponent41=true;try{readSharedComponentTrail41(descriptor);const pendingIntent=createVisualIntentStore({storage:localStorage,prefix:desk.navigationKey('secondary')}).read(descriptor.objectId);if(pendingIntent){const trail=unpackTrail41(pendingIntent.trail);if(!sameTrail41(trail,readSharedComponentTrail41(descriptor))||trail.link?.linkId!==descriptor.linkId)throw new Error('未决采用与原稿关联不一致；记录保留。');}const source=editorSnapshot(),refs=clone(ui.draft.content.components||[]),known=knownEditorRevision();
  const isCurrent=()=>sameEditor(source)&&ui.object.revision===source.revision&&knownEditorRevision()===known&&sameJSON41(ui.draft.content.components||[],refs);
  if(!await desk.restoreComponentLink(descriptor,{isCurrent}))throw new Error('原稿或引用在恢复期间变化，原记录保留，请从稿件重新进入。');}catch(error){toast('分区原稿关联未恢复：'+error.message,'error');}finally{restoringComponent41=false;}
}

function componentAdd(){const opts=objectOptions().filter(([id])=>id!==ui.object.id);if(!opts.length){toast('当前项目没有可引用的其他成果。');return;}const source=editorSnapshot(),selectedBlock=ui.selectedBlock;modal('插入已有图或模块',`${select('选择已有成果','id',opts)}${select('关联方式','type',[['components','组成组件'],['citations','文献引用']])}<p class="hint">采用所选成果的准确修订。组件插入当前选中段落后；后续来源更新需明确接纳。</p>`,{submit:async v=>{requireEditor(source);const item=objects().find(o=>o.id===v.id);if(v.type==='citations'&&item.kind!=='literature')throw new Error('文献引用只能指向文献记录。');if(v.type==='components'&&!['report','note','paper','figure','diagram','poster'].includes(item.kind))throw new Error('所选类型不能作为文稿组件。');await action('graph.relate',{src:source.id,dst:v.id,type:v.type==='citations'?'cites':'uses',status:'confirmed',target_revision:item.revision});requireEditor(source);mutate(d=>{d.content[v.type]||=[];if(!d.content[v.type].some(ref=>(ref.id||ref)===v.id))d.content[v.type].push({id:v.id,revision:item.revision,...(v.type==='components'?{after_block_id:selectedBlock||'end'}:{})});},true);await loadReferences();}});}

function organizeWorkbench(){
 if(!ensureProject())return;const projectId=ui.project,items=currentObjects().filter(o=>scholarlyKinds.has(o.kind)),sections=[['manuscript','稿件与整合产出'],['literature','综述与问题'],['methods','方法'],['results','结果批次'],['figures','图形'],['drafts','独立文稿']];
 const key=uid('organize');modal('整理项目产出',`<p class="hint">按研究内容归类。这里只改变组织位置和顺序，正文、批注、来源与身份保持。</p>${items.map((o,i)=>`<div class="organization-row" data-organize-id="${esc(o.id)}"><label><input type="checkbox" name="selected" value="${esc(o.id)}"> ${esc(o.title)}<small>${esc(kinds[o.kind])} · 修订 ${o.revision}</small></label><select aria-label="${esc(o.title)} 所属层级" name="section-${esc(o.id)}">${sections.map(([id,label])=>`<option value="${id}" ${workbenchRole(o)===id?'selected':''}>${label}</option>`).join('')}</select><input aria-label="${esc(o.title)} 排序" type="number" name="order-${esc(o.id)}" value="${o.metadata?.workbench?.order??i}" min="0" max="10000"></div>`).join('')}`,{wide:true,label:'保存所选模块位置',submit:async(v,form)=>{const f=new FormData(form),selected=f.getAll('selected');if(!selected.length)throw new Error('勾选需要整理的模块。');const assignments=selected.map(id=>({id,expected_revision:items.find(o=>o.id===id).revision,section:f.get('section-'+id),order:Number(f.get('order-'+id))}));await action('workbench.organize',{project_id:projectId,assignments,request_key:key});await refresh({render:false});draw();toast('模块位置已保存，正文及来源保持。');}});
}
function assembleWorkbench(){
 if(!ensureProject())return;const projectId=ui.project,items=currentObjects().filter(o=>['report','note','figure','diagram'].includes(o.kind)),key=uid('assemble');
 modal('把已有模块整合为稿件',`${field('稿件标题','title','','text','required')}${select('整合产出','kind',[['paper','Manuscript / 论文工作稿'],['report','图文研究报告']])}<p class="hint">明确选择并排列模块。新稿保留准确来源版本；原模块独立存在，不会被移走或改写。</p>${items.map((o,i)=>`<div class="assembly-row"><label><input type="checkbox" name="modules" value="${esc(o.id)}"> ${esc(o.title)}<small>${esc(kinds[o.kind])} · 采用修订 ${o.revision}</small></label><input aria-label="${esc(o.title)} 顺序" name="order-${esc(o.id)}" type="number" value="${i+1}" min="1" max="1000"></div>`).join('')||'<p>先创建或导入独立研究模块。</p>'}`,{wide:true,label:'按选择整合并打开',submit:async(v,form)=>{const f=new FormData(form),chosen=f.getAll('modules');if(!chosen.length)throw new Error('至少选择一个已有模块。');const modules=chosen.map(id=>({id,revision:items.find(o=>o.id===id).revision,order:Number(f.get('order-'+id))})).sort((a,b)=>a.order-b.order).map(({id,revision})=>({id,revision}));const result=await action('workbench.assemble',{project_id:projectId,title:v.title,kind:v.kind,modules,request_key:key});await refresh({render:false});const id=result.object?.id||result.id;if(!id)throw new Error('整合回执缺少成果身份，请从项目核对。');ui.componentTrail=[];rememberComponentTrail();await openObject(id);}});
}
async function showWorkbenchFiles(){
 const target=ui.object?{object_id:ui.object.id,revision:ui.object.revision}:{project_id:ui.project,expected_revision:currentProject()?.revision};ui.fileSelection=target;
 const tree=await action('workbench.files',target.object_id?target:{project_id:target.project_id});ui.fileTree=tree;
 const entries=list(tree.entries||tree.files);modal('成果文件',`<p class="hint">源稿、依据、图和导出件按准确版本组织；下载目录不会启动科研计算。</p><div class="source-file-tree">${entries.map(entry=>`<div><strong>${esc(entry.path||entry.name||entry.title||'文件')}</strong><small>${esc(entry.role||entry.kind||'')}${entry.revision?' · 修订 '+esc(entry.revision):''}</small>${entry.download_url?`<a href="${esc(entry.download_url)}" download>下载</a>`:''}</div>`).join('')||'<p>此成果的目录由导出时的准确快照生成。</p>'}</div>${button('下载源目录包','workbench-export-files',{},'button primary')}`,{wide:true});
}
async function exportWorkbenchFiles(){const result=await action('workbench.export_files',{...ui.fileSelection,request_key:uid('source-files')});const sha=result.sha||result.asset?.sha||result.asset||result.sha256,url=result.url||assetURL(sha);if(!url)throw new Error('导出回执没有可下载文件。');modal('源目录已生成',`<p>目录绑定本次采用版本；原研究材料保持。此包的支持范围与缺失依赖见包内清单。</p><a class="button primary" href="${esc(url)}" download>下载源目录包</a>`,{wide:true});}
// Capture the clicked occurrence, not whichever paragraph was selected earlier.
function componentEntryData(element){return {id:element.dataset.componentId,index:element.dataset.componentIndex,revision:element.dataset.componentRevision};}
function componentElement(location){
 return [...document.querySelectorAll('.manuscript-component')].find(el=>el.dataset.componentId===location.id&&Number(el.dataset.componentIndex)===location.index);
}
function restoreManuscriptReading(){
 const returnState=manuscriptReturn;if(!returnState||!sameEditor(returnState.source))return;
 const restore=()=>{if(manuscriptReturn!==returnState||!sameEditor(returnState.source))return;const el=componentElement(returnState.location);const frame=document.querySelector('.manuscript-surface');if(frame)frame.scrollTop=el&&Number.isFinite(returnState.location.top)?frame.scrollTop+el.getBoundingClientRect().top-returnState.location.top:returnState.scroll;};
 restore();
 // Cached image loads and the math renderer can still change page height after
 // draw. Stop restoring as soon as the researcher resumes interacting.
 document.querySelectorAll('.manuscript-page img').forEach(img=>{if(!img.complete)img.addEventListener('load',restore,{once:true});});
}
function manuscriptBaseForTrail(object){return {id:object.id,revision:object.revision,title:object.title,kind:object.kind,project_id:object.project_id,content:clone(object.content)};}
function rememberComponentTrail(){try{localStorage.setItem(desk.navigationKey()+':component-trail',JSON.stringify((ui.componentTrail||[]).slice(-8).map(t=>packTrail41(JSON.parse(JSON.stringify(t))))));}catch{toast('本机无法保留图形返回路径；请在离开前返回原稿。','error');}}
function restoreComponentTrail(){
 if(!ui.object||!['figure','diagram'].includes(ui.object.kind))return;
 try{const raw=JSON.parse(localStorage.getItem(desk.navigationKey()+':component-trail')||'[]'),saved=Array.isArray(raw)?raw.map(unpackTrail41):raw;
  if(Array.isArray(saved)&&saved.length<=8&&saved.at(-1)?.location?.id===ui.object.id&&saved.every(t=>objects().some(o=>o.id===t.id)&&t.manuscriptBase?.id===t.id&&Number.isInteger(t.location?.index))){ui.componentTrail=saved;draw();}
 }catch{toast('原稿返回记录无法读取，已保留；可从对象树打开原稿。','error');}
}
async function enterWorkbenchComponent(data){
 if(!ui.object)return;const source=editorSnapshot(),refs=list(ui.draft.content.components),matches=refs.map((r,index)=>({r,index})).filter(({r})=>(r.id||r.object_id)===data.id),index=data.index===undefined?(matches.length===1?matches[0].index:-1):Number(data.index),ref=refs[index];
 if(!ref||(ref.id||ref.object_id)!==data.id||(data.revision!==undefined&&Number(data.revision)!==ref.revision))throw new Error('此组件位置或采用版本已变化，请从原稿重新进入。');
 const location={id:data.id,index},element=componentElement(location);location.top=element?.getBoundingClientRect().top;
 if(ui.dirty)persistDraft();manuscriptReturn=null;
 const trail={id:source.id,manuscriptBase:manuscriptBaseForTrail(source.object),entryComponents:clone(source.draft.content.components||[]),title:source.draft.title,block:ui.selectedBlock,location,mode:ui.manuscriptMode,panel:ui.workspacePanel,note:ui.sectionNote?clone(ui.sectionNote):null,noteDirty:ui.sectionNoteDirty,noteReturnBlock:ui.noteReturnBlock,scroll:document.querySelector('.manuscript-surface')?.scrollTop||0,adoptedRevision:ref.revision,baseRevision:source.revision,undo:clone(ui.undo),redo:clone(ui.redo)};
 if(!desk.embedded&&desk.regionsState()?.secondaryObjectId===data.id){
  persistWorkspaceDrafts();const link={objectId:data.id,parentObjectId:trail.id,componentIndex:index,linkId:uid('component-link')};trail.originRegion='primary';trail.link=link;saveSharedComponentTrail41(trail);
  const isCurrent=()=>sameEditor(source)&&ui.object.revision===source.revision&&knownEditorRevision()===source.revision&&draftEqual(source.draft,ui.draft)&&sameJSON41(ui.undo,trail.undo)&&sameJSON41(ui.redo,trail.redo)&&sameJSON41(ui.sectionNote||null,trail.note)&&ui.sectionNoteDirty===trail.noteDirty;
  if(!await desk.attachComponentLink(link,{isCurrent}))throw new Error('原稿、引用或副区状态已变化，尚未确认关联；两边草稿已保留，请从原稿重新进入。');
  localStorage.setItem(desk.componentKey('latest'),JSON.stringify(link));return;
 }
 await openObject(data.id);if(ui.object?.id!==data.id)return;ui.componentTrail.push(trail);rememberComponentTrail();ui.workspacePanel=null;draw();window.scrollTo(0,0);
}
async function returnToManuscript(){
 const trail=ui.componentTrail.at(-1);if(!trail)return;if(ui.dirty)persistDraft();if(trail.link&&desk.embedded){if(ui.returningComponent41)return;ui.returningComponent41=true;const b=document.querySelector('[data-action=component-return]');if(b){b.disabled=true;b.textContent='…';}try{if(!await desk.requestComponentReturn(trail.link))throw new Error('主区原稿已切换或尚在处理；返回路径保留，请在主区打开原稿后重试。');return;}finally{ui.returningComponent41=false;const current=document.querySelector('[data-action=component-return]');if(current){current.disabled=false;current.textContent='←';}}}await openObject(trail.id);if(ui.object?.id!==trail.id)return;
 ui.componentTrail.pop();rememberComponentTrail();if(trail.historyRecovery)retainLocalHistory41(trail.historyRecovery);restoreLocalHistory41(trail.id);if(ui.object.revision===trail.baseRevision){ui.undo=trail.undo;ui.redo=trail.redo;}
 ui.manuscriptMode=trail.mode;ui.preview=trail.mode!=='edit';ui.selectedBlock=trail.block;ui.workspacePanel=trail.panel;ui.sectionNote=trail.noteDirty?trail.note:(objects().find(o=>o.id===trail.note?.id)||trail.note);ui.sectionNoteDirty=trail.noteDirty;ui.noteReturnBlock=trail.noteReturnBlock;
 manuscriptReturn={source:editorSnapshot(),location:trail.location||{},scroll:trail.scroll};draw();
}

function positionComponent(index){const source=editorSnapshot(),ref=ui.draft.content.components?.[index];if(!ref)return;const blocks=list(ui.draft.content.blocks);modal('图或模块在稿件中的位置',select('放在下方段落之后','after',[['start','正文开始前'],...blocks.map((b,i)=>[b.id,`${i+1}. ${b.text.slice(0,70)||'空段落'}`]),['end','正文末尾']],ref.after_block_id||'end'),{submit:v=>{requireEditor(source);mutate(o=>o.content.components[index].after_block_id=v.after,true);}});}
async function requestManuscriptRevision(data={}){
 if(!ui.object||!['paper','report','note'].includes(ui.object.kind)){toast('先打开一份结构化稿件或报告。');return;}
 if(ui.dirty){toast('请先保存当前修改，再把准确版本交给科研搭档。');return;}
 const source=editorSnapshot(),selected=data.block||ui.selectedBlock,key=uid('manuscript-revision'),providers=[...list(ui.data.providers)].sort((a,b)=>Number(b.route==='deepseek_harness')-Number(a.route==='deepseek_harness'));
 const dialog=modal('请科研搭档定向修订',manuscriptRevisionFields({object:ui.object,selectedBlockIds:selected?[selected]:[],annotations:list(ui.object.annotations),annotationIds:data.annotation?[data.annotation]:[],providers}),{wide:true,label:'提交有限修订任务',submit:async(v,form)=>{requireEditor(source);if(ui.dirty||ui.object.revision!==source.revision)throw new Error('原稿已有新修改，请保存后重新提交。');const result=await action('manuscript.revision.submit',manuscriptRevisionSubmission(v,form,ui.object,key));await refresh({render:false});if(sameEditor(source)){ui.workspacePanel='review';ui.manuscriptMode='review';await openManuscriptReview(result.id||result.task?.id);}else toast('修订任务已接收，当前页面保留。');}});
 if(data.annotation){const annotation=ui.object.annotations.find(a=>a.id===data.annotation);if(annotation)dialog.form.querySelector('[name=request]').value=annotation.text;}
}
async function finishManuscriptRevision(source,result){
 if(result?.id!==source.id||!Number.isInteger(result.revision))throw new Error('修订结果身份不符；本地草稿保留。');
 // Candidate adoption did not submit this browser's draft. Never use ordinary
 // save completion to discard text already dirty when the review was opened.
 if(!sameEditor(source)){toast('原稿修订已保存；当前页面与本地草稿保留。');return;}
 if(ui.dirty){
  ui.remoteRevision=Math.max(knownEditorRevision(),result.revision);persistDraft();
  writeStatus(`服务器修订 ${result.revision} · 本地编辑保留，请核对差异后保存`);syncEditorIdentity(source);
  await readEditorDetails(source);toast('候选已采用；未提交的本地编辑和基础版本完整保留，请核对差异。');return;
 }
 await finishEditorWrite(source,result);
}
async function openManuscriptReview(taskId){
 if(!ui.object)return;let source=editorSnapshot();manuscriptReviewController?.destroy();ui.manuscriptReviewTask=taskId;ui.workspacePanel='review';
 manuscriptReviewController=createManuscriptReviewController({taskId,request:action,onChange:(view,{busy}={})=>{if(!view||!sameEditor(source))return;ui.manuscriptReviewHTML=manuscriptReviewPanel(view);const panel=document.querySelector('#manuscript-review-panel');if(panel){panel.innerHTML=ui.manuscriptReviewHTML;panel.querySelectorAll('[data-action=manuscript-decide]').forEach(b=>b.disabled=busy||b.disabled);}else draw();},onSaved:async receipt=>{const records=receipt.objects||[{object_id:receipt.object_id,result_revision:receipt.result_revision,source_changed:receipt.source_changed}];for(const record of records){if(!record.source_changed)continue;const current=await api(`/api/objects/${encodeURIComponent(record.object_id)}`),result=current.object||current;if(result.id===source.id&&result.revision===record.result_revision){await finishManuscriptRevision(source,result);if(ui.object?.id===source.id&&!ui.dirty)source=editorSnapshot();}else if(ui.sectionNote?.id===result.id){if(ui.sectionNoteDirty)toast('服务器笔记已有修订，本地笔记完整保留；请核对后保存。');else ui.sectionNote=clone(result);}}await refresh({render:false});}});
 draw();await manuscriptReviewController.load();
}

function syncFigureRenderStatus(message){
 if(ui.object?.kind!=='figure')return;const job=figureRenders.get(ui.object.id);if(job&&!sameEditor(job.source))return;
 const status=document.querySelector('[data-figure-status]');if(status&&(message||job))status.textContent=message||'正在保存并更新实际图像…';
}
function visualIntentStore41(){return createVisualIntentStore({storage:localStorage,prefix:desk.navigationKey()});}
function restoreLocalHistory41(id){
 ui.localHistoryRecovery=null;
 try{const value=unpackTrail41(JSON.parse(localStorage.getItem(desk.navigationKey()+':history-recovery:'+id)||'null'));if(value?.objectId===id)ui.localHistoryRecovery=value;}
 catch{toast('保留的编辑历史无法读取；原记录仍在本机。','error');}
}
function retainLocalHistory41(history,region){
 const key=desk.navigationKey(region)+':history-recovery:'+history.objectId,old=unpackTrail41(JSON.parse(localStorage.getItem(key)||'null'));
 if(old&&JSON.stringify(old)!==JSON.stringify(history))localStorage.setItem(key+':'+uid('retained'),JSON.stringify(packTrail41(old)));
 const raw=JSON.stringify(packTrail41(history));localStorage.setItem(key,raw);if(localStorage.getItem(key)!==raw)throw new Error('较早编辑历史未能确认保存，采用回执仍保留。');
 if(!region||desk.navigationKey(region)===desk.navigationKey())ui.localHistoryRecovery=history;
}
function visualPendingPanel41(){
 if(ui.object?.kind!=='figure')return '';
 try{const intent=visualIntentStore41().read(ui.object.id);if(!intent)return '';return `<div class="notice warning" data-visual-intent41>上次采用尚未核对。${button('核对上次采用','figure-visual-recover',{},'button small')}</div>`;}
 catch(error){return `<div class="notice warning" data-visual-intent41>${esc(error.message)}</div>`;}
}
function sameTrail41(a,b){return a?.id===b?.id&&a?.location?.id===b?.location?.id&&a?.location?.index===b?.location?.index;}
function syncActiveVisualManuscript41(base,updated,index){
 if(ui.view!=='workspace'||ui.object?.id!==updated.id)return false;
 const rebased=rebaseVisualDraft41({base,updated,index,local:{base_revision:ui.object.revision,title:ui.draft.title,content:ui.draft.content}});
 if(!rebased.ok)throw new Error(rebased.reason);
 if(ui.object.revision===base.revision){
  const undo=rebaseVisualHistory41({base,updated,index,history:ui.undo}),redo=rebaseVisualHistory41({base,updated,index,history:ui.redo});
  if(undo.retained.length||redo.retained.length)retainLocalHistory41({objectId:base.id,undo:clone(ui.undo),redo:clone(ui.redo),reason:'较早的图位置撤销历史单独保留；当前正文撤销保持刚采用的图。'});
  ui.undo=undo.history;ui.redo=redo.history;
 }
 const known=knownEditorRevision();Object.assign(ui.object,updated);ui.draft={title:rebased.local.title,content:clone(rebased.local.content)};
 invalidateManuscriptEditing();
 ui.dirty=rebased.changed;ui.remoteRevision=known>updated.revision?known:null;ui.recovered=false;
 if((ui.dirty||ui.undo.length||ui.redo.length)&&persistDraft()===false)throw new Error('当前原稿已显示新图，但未提交正文的本机副本未能保存。');
 return true;
}
async function finishVisualReceipt41(receipt,intent,source,{hostCallback=false}={}){
 const frozen=unpackTrail41(intent.trail),figureId=intent.objectId;
 if(receipt.status!=='committed'||receipt.request_key!==intent.request.request_key||receipt.figure?.id!==figureId||frozen&&receipt.manuscript?.id!==frozen.id)
  throw new Error('采用回执身份不完整；原请求和草稿保留，请核对同一次请求。');
 let note='',complete=true,parentUpdated=false;
 if(frozen?.link&&desk.embedded&&!hostCallback){
  const synced=await desk.notifyComponentCommit({...frozen.link,requestKey:intent.request.request_key});
  if(!synced){complete=false;note='图和原稿引用已保存，主区尚未核对显示；原请求保留，请回到原稿后再核对。';}
  else{const trail=ui.componentTrail?.at(-1);if(sameTrail41(trail,frozen)){trail.baseRevision=receipt.manuscript.revision;trail.manuscriptBase=manuscriptBaseForTrail(receipt.manuscript);trail.adoptedRevision=receipt.figure.revision;trail.entryComponents=clone(receipt.manuscript.content.components);rememberComponentTrail();saveSharedComponentTrail41(trail);}}
 }else if(frozen&&receipt.manuscript){
  try{
   const key=desk.draftKey(frozen.id,'draft',frozen.originRegion||(desk.embedded?'secondary':'primary')),raw=localStorage.getItem(key),local=ui.view==='workspace'&&ui.object?.id===frozen.id?{base_revision:ui.object.revision,title:ui.draft.title,content:clone(ui.draft.content)}:JSON.parse(raw||'null');
   const rebased=rebaseVisualDraft41({base:frozen.manuscriptBase,updated:receipt.manuscript,index:frozen.location.index,local});
   if(!rebased.ok)throw new Error(rebased.reason);
   if(rebased.local&&rebased.changed){const next=JSON.stringify({...rebased.local,saved_at:new Date().toISOString()});localStorage.setItem(key,next);if(localStorage.getItem(key)!==next)throw new Error('本机原稿草稿未能确认更新。');}
   else if(raw!==null){
    const stored=JSON.parse(raw);if(stored&&Object.hasOwn(stored,'history')){
     let history;try{history=unpackTrail41(stored.history);}catch{history=null;}
     retainLocalHistory41({objectId:frozen.id,baseRevision:stored.base_revision,undo:Array.isArray(history?.undo)?history.undo:[],redo:Array.isArray(history?.redo)?history.redo:[],rawDraft:raw,reason:'图已采用；较早本机编辑历史单独保留，避免撤回刚采用的图。'},frozen.originRegion||(desk.embedded?'secondary':'primary'));
    }
    localStorage.removeItem(key);if(localStorage.getItem(key)!==null)throw new Error('本机草稿记录未能确认更新。');
   }
   parentUpdated=syncActiveVisualManuscript41(frozen.manuscriptBase,receipt.manuscript,frozen.location.index);
   const trail=ui.componentTrail?.at(-1);
   // Replaying a receipt must not overwrite a later return path or later undo history.
   if(sameTrail41(trail,frozen)&&trail.baseRevision===frozen.baseRevision){
    const undo=rebaseVisualHistory41({base:frozen.manuscriptBase,updated:receipt.manuscript,index:frozen.location.index,history:trail.undo}),redo=rebaseVisualHistory41({base:frozen.manuscriptBase,updated:receipt.manuscript,index:frozen.location.index,history:trail.redo});
    if(undo.retained.length||redo.retained.length){trail.historyRecovery={objectId:trail.id,undo:trail.undo,redo:trail.redo,reason:'较早历史含不同的图引用位置，无法安全跨过这次图采用。'};retainLocalHistory41(trail.historyRecovery);note='图和原稿已保存；较早的结构撤销历史单独保留，可从成果更多操作查看。';}
    trail.undo=undo.history;trail.redo=redo.history;trail.baseRevision=receipt.manuscript.revision;trail.manuscriptBase=manuscriptBaseForTrail(receipt.manuscript);trail.adoptedRevision=receipt.figure.revision;trail.entryComponents=clone(receipt.manuscript.content.components);rememberComponentTrail();
   }
  }catch(error){complete=false;note='服务器已保存图和本稿引用；'+error.message+'原采用请求仍保留，可核对后保留恢复记录。';}
  if(ui.data)ui.data.objects=list(ui.data.objects).map(o=>o.id===receipt.manuscript.id&&o.revision<=receipt.manuscript.revision?receipt.manuscript:o);
 }
 // Recovery may occur after another editor has advanced the figure. Never apply
 // an old receipt over that newer revision or treat later typing as submitted.
 if(source&&source.revision===intent.request.expected_revision&&(!sameEditor(source)||ui.object.revision<=receipt.figure.revision))await finishEditorWrite(source,receipt.figure);
 if(complete&&!hostCallback)visualIntentStore41().settle(figureId,intent.request.request_key);
 if(ui.object?.id===figureId){ui.figurePreviewStatus='saved';draw();}
 if(parentUpdated&&ui.object?.id===receipt.manuscript?.id){draw();loadManuscriptEditing().catch(()=>{});await loadReferences();}
 toast(note||receipt.post_commit_warning||(frozen?'图形与本稿这一处引用已一起保存；未提交正文和章节笔记保留，可直接返回原稿。':'视觉改动已保存并完成实际重绘。'),complete?undefined:'error');
 return {...receipt,local_sync_complete:complete};
}
function visualRecoverySource41(intent){
 if(ui.object?.id!==intent.objectId)return null;
 return {...editorSnapshot(),draft:clone(intent.draft),revision:ui.object.revision};
}
async function recoverVisualFigure41(){
 if(!ui.object||figureRenders.has(ui.object.id)){toast('采用仍在进行，请等待当前回执。');return;}
 const store=visualIntentStore41(),intent=store.read(ui.object.id);if(!intent){draw();return;}
 const source=visualRecoverySource41(intent),receipt=await action('figure.visual.receipt',{id:intent.objectId,request_key:intent.request.request_key});
 if(receipt.status==='committed'){await finishVisualReceipt41(receipt,intent,source);if(store.read(intent.objectId))showVisualRecovery41(intent,true);return;}
 if(receipt.status!=='not_committed')throw new Error('服务端未返回可核对的采用状态，原请求保留。');
 showVisualRecovery41(intent,false);
}
function showVisualRecovery41(intent,committed){
 modal('核对上次图形采用',`<p>${committed?'服务器已保存图形及原稿，但本机另有变化，未覆盖本机内容。':'目前没有已提交回执；原请求可能尚在处理，也可能未成功提交。'}</p><p>保存时间：${esc(intent.createdAt)}。${committed?'可保留完整恢复记录后，从原稿核对差异。':'可用同一请求重试，或保留恢复记录后继续编辑。'}重复请求沿用原版本和原改动。</p>${committed?'':button('重试原采用请求','figure-visual-retry',{},'button primary')}${button('下载并保留恢复记录','figure-visual-archive',{},'button')}`);
}
async function archiveVisualFigure41(){
 if(!ui.object||figureRenders.has(ui.object.id))throw new Error('当前采用仍在等待，请先等待回执。');
 const store=visualIntentStore41(),intent=store.read(ui.object.id);if(!intent)return;
 downloadJSON('figure-adoption-recovery.json',intent);
 if(!store.archive(intent.objectId,intent.request.request_key,'user-preserved'))throw new Error('待核对记录已变化，未清除；请重新核对。');
 document.querySelector('#modal-root').innerHTML='';draw();toast('原请求已下载并保留在本机恢复记录。若原提交仍在运行，它可能稍后完成；下一次保存仍核对服务器版本。');
}
async function retryVisualFigure41(){
 const intent=ui.object&&visualIntentStore41().read(ui.object.id);if(!intent)return;
 document.querySelector('#modal-root').innerHTML='';return submitVisualIntent41(intent,visualRecoverySource41(intent));
}
async function applyVisualFigure41(){
 if(!ui.object||ui.object.kind!=='figure')return;
 const source=editorSnapshot(),previous=figureRenders.get(source.id);if(previous){await previous.promise;return;}
 if(visualIntentStore41().read(source.id))return recoverVisualFigure41();
 if(editorWrites.has(source.id))throw new Error('当前图形仍在保存，请等待回执；新增编辑保留。');
 const invalid=document.querySelector('[data-edit]:invalid,[data-overlay-tuple]:invalid');if(invalid){invalid.reportValidity();return;}
 if(!ui.dirty){toast('没有未采用的视觉改动。');return;}
 const trail=ui.componentTrail?.at(-1),request=visualCommitRequest41({object:ui.object,draft:source.draft,trail,requestKey:uid('visual-commit')});
 // Trail fields are UI-owned JSON; omit optional undefined before the strict store.
 const intent=visualIntentStore41().begin({objectId:source.id,request,draft:source.draft,trail:trail?packTrail41(JSON.parse(JSON.stringify(trail))):null});
 return submitVisualIntent41(intent,source);
}
async function submitVisualIntent41(intent,source){
 if(!source||ui.object?.id!==intent.objectId)throw new Error('请回到原图形重试。');
 const previous=figureRenders.get(source.id);if(previous)return previous.promise;
 if(editorWrites.has(source.id))throw new Error('此图形仍在保存，请等待回执。');
 figurePreviewController?.cancel();ui.figurePreviewResult=null;ui.figurePreviewError='';
 const job={source,draft:clone(intent.draft)};
 job.promise=Promise.resolve().then(async()=>finishVisualReceipt41(await action('figure.visual.commit',intent.request),intent,source))
 .catch(error=>{job.error=error;throw error;}).finally(()=>{if(figureRenders.get(source.id)===job){figureRenders.delete(source.id);if(sameEditor(source)){draw();writeFigurePreviewStatus();if(job.error)syncFigureRenderStatus('尚未完成回执核对：'+errorMessage(job.error)+'；草稿与原请求保留。');}}});
 figureRenders.set(source.id,job);syncFigureRenderStatus();return job.promise;
}

async function renderFigureSaved(){
 if(!ui.object||ui.object.kind!=='figure')return;
 const requested=editorSnapshot(),previous=figureRenders.get(requested.id);
 if(previous){
  const receipt=await previous.promise;
  if(!sameEditor(requested))return receipt;
  if(sameEditor(previous.source)&&draftEqual(requested.draft,previous.draft))return receipt;
  // A later gesture supersedes an earlier queued request; only render the
  // explicit snapshot still present in this editor, never new unseen edits.
  if(!draftEqual(requested.draft,ui.draft))return null;
  return renderFigureSaved();
 }
 const job={source:requested,draft:clone(requested.draft)};
 job.promise=Promise.resolve().then(async()=>{
  let source=requested;
  const writing=editorWrites.get(source.id);if(writing){await writing.done;if(!sameEditor(source)||!draftEqual(source.draft,ui.draft))return null;source=editorSnapshot();}
  const captured={...source,dirty:ui.dirty};
  const invalid=document.querySelector('[data-edit]:invalid');if(invalid){invalid.reportValidity();throw new Error('请先修正无效属性；尚未启动重绘。');}
  const session=createFigureRenderSession({source:captured,isCurrent:()=>sameEditor(source),saveSource:async()=>{const result=await editorWrite(source,'object.save',{id:source.id,expected_revision:source.revision,title:source.draft.title,content:source.draft.content});if(sameEditor(source))source={...source,revision:result.revision};return result;},request:action});
  const receipt=await session.render();if(!receipt)return;
  if(sameEditor(source)){await readEditorDetails(source);if(sameEditor(source)){if(draftEqual(ui.draft,source.draft)){draw();await loadReferences();}else updateFigurePreview(app,{object:ui.object,content:ui.draft.content,dirty:ui.dirty});}}
  const failures=receipt.result.replay?.failures||receipt.result.replay_failures||[];toast(failures.length?'重绘已返回，部分覆盖未能重放；请查看图中说明。':'图形已按保存版本重绘。稿件需明确采用新版。');return receipt;
 }).catch(error=>{job.error=error;throw error;}).finally(()=>{if(figureRenders.get(requested.id)===job){figureRenders.delete(requested.id);if(sameEditor(requested)){updateFigurePreview(app,{object:ui.object,content:ui.draft.content,dirty:ui.dirty});if(job.error)syncFigureRenderStatus('更新图像失败：'+errorMessage(job.error)+'；草稿与旧图保留，可重试。');}}});
 figureRenders.set(requested.id,job);syncFigureRenderStatus();return job.promise;
}

async function editFigureCode(){
 if(!ui.object||ui.object.kind!=='figure')return;if(ui.dirty)throw new Error('请先保存图形草稿，再编辑其实际生成代码。');const source=editorSnapshot();
 const session=createFigureCodeSession({source,isCurrent:()=>sameEditor(source)&&!ui.dirty&&ui.object.revision===source.revision,readAsset:async sha=>{const response=await fetch(assetURL(sha));if(!response.ok)throw new Error('无法读取已登记的脚本。');return response.text();},registerAsset:async input=>{const bytes=new TextEncoder().encode(input.text);let binary='';for(const byte of bytes)binary+=String.fromCharCode(byte);return action('asset.import',{project_id:input.project_id,filename:input.filename,base64:btoa(binary),source:input.source});},saveSource:(_capture,content)=>editorWrite(source,'object.save',{id:source.id,expected_revision:source.revision,title:source.draft.title,content})});
 const actual=await session.read();requireEditor(source);modal('图形生成代码',`<p class="hint">${actual.generated?'结构化数据生成的真实绘图脚本':'已登记的真实绘图脚本'} · ${esc(actual.sha.slice(0,16))}</p><label class="field"><span>Python 源码</span><textarea name="code" class="figure-code-editor" spellcheck="false" rows="22" required>${esc(actual.text)}</textarea></label><p>保存将登记新脚本并关联到此图。新代码须单独授权后才可重绘。</p>`,{wide:true,label:'保存为新脚本修订',submit:async v=>{requireEditor(source);if(ui.dirty)throw new Error('图形已有其他修改，请先保存后重新打开代码。');const receipt=await session.save(v.code);if(receipt.changed&&!receipt.attached)throw new Error('新脚本已登记，但编辑页面变化，因此未关联。原图保持。');toast(receipt.changed?'代码已保存为新修订；授权后方可运行。':'代码未变化。');if(sameEditor(source))draw();}});
}

async function handle(name,d={},event){
  switch(name){
    case'workbench-filter':ui.workbenchFilter=d.section;draw();return;
    case'workbench-expand':if(ui.expandedCollections.has(d.section))ui.expandedCollections.delete(d.section);else ui.expandedCollections.add(d.section);draw();return;
    case'workbench-all':return modal('项目文件与记录',`<p class="hint">研究产出与辅助记录都有稳定身份；这里保留完整入口。</p>${workbenchAll(context())}`,{wide:true});
    case'workbench-organize':return organizeWorkbench();
    case'workbench-assemble':return assembleWorkbench();
    case'workbench-files':return article.files();
    case'project-file-read':return article.fileRead(d.path);
    case'article-organize':return article.organize();
    case'section-note':return article.sectionNote(d.section);
    case'section-note-add':return article.noteAdd();
    case'section-note-save':return article.noteSave();
    case'section-note-return':return article.noteReturn();
    case'scientific-trace':return article.trace(d);
    case'component-enlarge':return article.figureRead(d);
    case'component-caption':return article.caption(d);
    case'component-annotate':return article.regionComment(d);
    case'figure-region':requireSavedFigureAnchor();return article.regionComment({standalone:true});
    case'manuscript-round':return article.round(d);
    case'citation-inspect':return article.citation(d.key);
    case'workbench-export-files':return exportWorkbenchFiles();
    case'workbench-partner':if(ui.data?.runtime?.running===false)return modal('科研搭档',`<p>当前执行服务未运行。你仍可阅读、批注、手动修订和导出成果。</p><p>本次工作台试用不会自动恢复旧任务或调用模型。</p>${button('查看已有任务与反馈','partner-tasks',{},'button')}${button('查看连接状态','navigate',{view:'settings'},'button')}`);return modal('科研搭档',`<p>从具体目标发起任务，或在稿件中选段批注，请搭档提出修订。</p><div class="partner-options">${button('发起研究委托','new-task',{},'button primary')}${button('组织协作研究','new-cycle',{},'button')}${button('查看任务与反馈','partner-tasks',{},'button')}${button('Agent 管理项目','management-new',{},'button')}</div><p class="hint">使用已配置的原生 DeepSeek Harness 或 Codex 路线。保存文字不会自动调用模型。</p>`);
    case'partner-tasks':document.querySelector('#modal-root').innerHTML='';ui.view='activity';ui.tab='tasks';draw();return;
    case'manuscript-view-mode':ui.manuscriptRevisionView=d.mode;if(d.mode!=='clean'&&!manuscriptEditingCurrent())return loadManuscriptEditing();draw();return;
    case'manuscript-edit-track':return trackManuscriptDraft();
    case'manuscript-edit-load':ui.workspacePanel='direct';return loadManuscriptEditing();
    case'manuscript-direct-decide':return decideDirectText(d);
    case'manuscript-format-save':return saveManuscriptFormat();
    case'manuscript-format-source':return renderManuscriptFormat('source');
    case'manuscript-format-render':return renderManuscriptFormat('render');
    case'manuscript-mode':if(d.mode==='edit')ui.manuscriptRevisionView='clean';ui.manuscriptMode=d.mode;ui.preview=d.mode!=='edit';if(d.mode==='review')ui.workspacePanel='review';draw();return;
    case'manuscript-edit-block':ui.manuscriptMode='edit';ui.preview=false;ui.selectedBlock=d.id;draw();document.querySelector(`[data-edit="block"][data-id="${CSS.escape(d.id)}"]`)?.focus();return;
    case'workspace-panel':{
      if(d.panel==='notes'&&ui.workspacePanel!=='notes'){
        if(ui.sectionNoteDirty&&ui.sectionNote){ui.workspacePanel='notes';draw();return;}
        const frame=document.querySelector('.manuscript-surface'),box=frame?.getBoundingClientRect(),blocks=[...document.querySelectorAll('.manuscript-block[data-block]')];
        const visible=blocks.filter(el=>{const r=el.getBoundingClientRect();return box&&r.bottom>box.top&&r.top<box.bottom;}),selected=visible.find(el=>el.dataset.block===ui.selectedBlock),at=selected||visible[0];
        const section=sectionFor(context(),at?.dataset.block||ui.selectedBlock);
        if(section){if(at)ui.selectedBlock=at.dataset.block;return article.sectionNote(section.id);}
      }
      ui.workspacePanel=ui.workspacePanel===d.panel?null:d.panel;if(ui.workspacePanel==='direct'&&!manuscriptEditingCurrent())return loadManuscriptEditing();draw();return;
    }
    case'workspace-panel-close':ui.workspacePanel=null;draw();return;
    case'references-reload':await loadReferences();draw();return;
    case'outline-locate':ui.selectedBlock=d.id;draw();document.querySelector(`[data-block="${CSS.escape(d.id)}"]`)?.scrollIntoView({block:'center',behavior:'smooth'});return;
    case'workbench-component':return enterWorkbenchComponent(d);
    case'component-return':return returnToManuscript();
    case'component-position':return positionComponent(Number(d.index));
    case'figure-visual-recover':return recoverVisualFigure41();
    case'figure-visual-retry':return retryVisualFigure41();
    case'figure-visual-archive':return archiveVisualFigure41();
    case'draft-recovery-list':return showDraftRecoveries41();
    case'draft-recovery-preview':return showDraftRecoveryPreview41(d.index);
    case'local-history-recovery':{
      const history=ui.localHistoryRecovery;if(!history||history.objectId!==ui.object?.id)return;
      modal('保留的本机编辑历史',`<p>${esc(history.reason)}</p><p>这些较早草稿没有覆盖当前正文或刚采用的图。你可下载完整记录核对，或从展开的正文中取回文字。</p>${button('下载保留记录','local-history-download',{},'button')}${[...(history.undo||[]),...(history.redo||[])].map((draft,i)=>`<details><summary>本机草稿 ${i+1} · ${esc(draft.title)}</summary><pre>${esc((draft.content.blocks||[]).map(b=>b.text).join('\n\n'))}</pre></details>`).join('')}`,{wide:true});return;
    }
    case'local-history-download':if(ui.localHistoryRecovery)downloadJSON('local-edit-history.json',ui.localHistoryRecovery);return;
    case'component-adopt':{const item=objects().find(o=>o.id===d.id),ref=ui.draft.content.components?.[Number(d.index)];if(!item||item.revision!==Number(d.revision)||(ref?.id||ref?.object_id)!==d.id)throw new Error('来源或位置已变化，请重新选择。');mutate(o=>{const r=o.content.components[Number(d.index)];r.revision=item.revision;delete r.sha256;},true);await loadReferences();toast('草稿已采用所选图形修订；保存后成为稿件新版本。');return;}
    case'workbench-module-decision':return decideWorkbenchModule(d);
    case'manuscript-revision':return requestManuscriptRevision(d);
    case'manuscript-review-open':return openManuscriptReview(d.id);
    case'manuscript-task-open':{const task=await api('/api/tasks/'+encodeURIComponent(d.id)),id=task.payload?.context?.manuscript_revision?.object_id;if(!id)throw new Error('此任务没有稿件修订合同。');await openObject(id);return openManuscriptReview(d.id);}
    case'manuscript-decide':if(ui.dirty)throw new Error('请先保存当前手工编辑，再刷新候选并决定；本地草稿保持。');if(!manuscriptReviewController)throw new Error('请重新打开修订候选。');return manuscriptReviewController.decide(d.block?[d.block]:[],d.decision);
    case'artifact-feature':{const p=currentProject();await action('project.feature',{project_id:p.id,expected_revision:p.revision,object_id:ui.object.id,featured:!(p.metadata?.featured_objects||[]).includes(ui.object.id)});await refresh();return;}
    case'artifact-link':return modal('成果入口链接',`<p>在具有此研究空间访问权限的客户端打开；链接不包含登录令牌。</p><a href="${esc(objectLink(location.origin,ui.object.id))}">${esc(objectLink(location.origin,ui.object.id))}</a>`);
    case'refresh':return ui.authGate||!ui.data?boot():refresh();
    case'development-verify':
      if(ui.data?.development?.can_verify!==true)throw new Error('完整重验仅限研究空间所有者。');
      return developmentView.recheck({verify:()=>api('/api/action',{method:'POST',body:JSON.stringify({action:'system.verify'})}),refresh,redraw:draw});
    case'navigate':persistWorkspaceDrafts();if(d.view==='workspace'&&!ui.project){ui.view='projects';}else ui.view=d.view;draw();return;
    case'desk-help':return desk.help();
    case'workbench-project-details':return modal('项目概览',workbenchHome(context()),{wide:true});
    case'workbench-import':return importAsset('document');
    case'select-project':document.querySelector('#modal-root').innerHTML='';persistWorkspaceDrafts();desk.state.pinned=false;ui.graphProjectRoot='';ui.project=d.id;ui.assetView=null;ui.view='projects';ui.object=null;ui.draft=null;ui.dirty=false;ui.componentTrail=[];rememberComponentTrail();ui.workbenchFilter='all';draw();return;
    case'open-object':return openObject(d.id);
    case'new-project':return newProject();
    case'new-artifact':return newArtifact();
    case'new-node':return newArtifact('concept');
    case'new-task':return newTask();
    case'new-cycle':return newTask(false,true);
    case'request-revision':return ['paper','report','note'].includes(ui.object?.kind)?requestManuscriptRevision():newTask(true);
    case'save':return save();
    case'annotate':return ui.selectedComponent?article.regionComment(ui.selectedComponent):annotate();
    case'view-annotations':ui.workspacePanel='comments';draw();return;
    case'export':return showExport();
    case'history':return showHistory();
    case'toggle-preview':ui.preview=!ui.preview;ui.manuscriptMode=ui.preview?'read':'edit';draw();return;
    case'document-image':return editDocumentImage(d.reference||'',d.block,d.offset);
    case'document-upload-receipts':return showUploadReceipts();
    case'select-block':ui.selectedComponent=null;ui.selectedBlock=d.id;if(window.getSelection()?.toString())return;draw();return;
    case'undo':if(ui.undo.length){ui.redo.push(clone(ui.draft));ui.draft=ui.undo.pop();settleLocalHistory41();}return;
    case'redo':if(ui.redo.length){ui.undo.push(clone(ui.draft));ui.draft=ui.redo.pop();settleLocalHistory41();}return;
    case'block-add':ui.manuscriptMode='edit';ui.preview=false;mutate(o=>{o.content.blocks||=[];const b={id:uid('block'),kind:d.kind||'paragraph',text:''};const i=o.content.blocks.findIndex(b=>b.id===ui.selectedBlock);o.content.blocks.splice(i<0?o.content.blocks.length:i+1,0,b);ui.selectedBlock=b.id;},true);document.querySelector(`[data-edit="block"][data-id="${CSS.escape(ui.selectedBlock)}"]`)?.focus();return;
    case'block-delete':mutate(o=>{o.content.blocks=o.content.blocks.filter(b=>b.id!==ui.selectedBlock);ui.selectedBlock='';},true);return;
    case'block-move':mutate(o=>{const a=o.content.blocks,i=a.findIndex(b=>b.id===ui.selectedBlock),j=i+Number(d.direction);if(i>=0&&j>=0&&j<a.length)[a[i],a[j]]=[a[j],a[i]];},true);return;
    case'rename':modal('修改成果标题',field('标题','title',ui.draft.title,'text','required'),{submit:v=>{mutate(o=>o.title=v.title,true);toast('标题已加入本地草稿；保存后写入研究空间。');}});return;
    case'management-open-project':document.querySelector('#modal-root').innerHTML='';ui.project=d.id;ui.assetView=null;ui.view='projects';draw();return;
    case'management-new':{const requestKey=uid('REQUEST');modal('委托 Agent 管理项目',managementFields(projects(),list(ui.data.providers),ui.data.project_management,ui.project),{wide:true,label:'提交有限管理委托',submit:async(values,form)=>{const task=await action('project.management.submit',managementSubmission(values,form,requestKey));toast('管理委托已接收；任务 '+task.id);ui.view='activity';ui.tab='tasks';await refresh();}});return;}
    case'management-review':{const view=await action('project.management.view',{task_id:d.id});modal('审阅项目管理提案',managementPanel(view),{wide:true,label:view.changes.length?'审阅并应用这些变更':'确认这些检索结果',...(view.state==='proposed'&&view.authorization_active?{submit:async()=>{await action('project.management.apply',{task_id:view.task_id,candidate_sha256:view.candidate_sha256,proposal_sha256:view.proposal_sha256,approved:true});await refresh();toast('项目管理提案已应用；可以从任务记录查看实际结果。');}}:{})});return;}
    case'management-revoke':modal('撤回管理授权','<p>立即停止本次管理任务，并阻止尚未应用的提案。已应用的变更与历史保留。</p>',{label:'撤回本次授权',submit:async()=>{await action('project.management.revoke',{task_id:d.id});await refresh();}});return;
    case'project-settings':{const p=currentProject();modal('项目设置',`${field('项目名称','title',p.title,'text','required')}${field('项目分类','category',p.metadata?.category||'')}${field('核心问题与背景','description',p.content?.description||'','textarea')}<p class="hint">分类可用于图谱和全局搜索；改名后保留原名称作为别名。</p><div class="button-group">${button('归档项目','project-archive',{id:p.id},'button small danger-text')}${button('合并重复对象','graph-merge',{},'button small')}</div>`,{submit:async v=>{await action('project.update',{id:p.id,expected_revision:p.revision,title:v.title,metadata:{...p.metadata,category:v.category.trim()},content:{...p.content,description:v.description}});await refresh();}});return;}
    case'project-archive':{const p=projects().find(p=>p.id===d.id);modal('归档项目',`<p>归档仅改变可见性。在途任务继续；停止请暂停或取消。</p>${button('查看该项目活动任务','archive-tasks',{project:p.id},'button')}`,{label:'仅归档项目',submit:async()=>{await action('project.archive',{id:p.id,expected_revision:p.revision});ui.project='';await refresh();}});return;}
    case'project-restore':await action('project.restore',{id:d.id,expected_revision:projects().find(p=>p.id===d.id)?.revision});await refresh();return;
    case'object-archive':{const obj=ui.object;modal('归档成果',`<p>归档仅改变可见性。在途任务继续；停止请暂停或取消。</p>${button('查看该项目活动任务','archive-tasks',{project:obj.project_id},'button')}`,{label:'仅归档成果',submit:async()=>{await action('object.archive',{id:obj.id,expected_revision:obj.revision});if(ui.object?.id===obj.id){ui.object=null;ui.draft=null;ui.view='projects';}await refresh();}});return;}
    case'archive-tasks':document.querySelector('#modal-root').innerHTML='';ui.project=d.project;ui.view='activity';ui.tab='tasks';draw();return;
    case'object-unarchive':{const o=objects().find(x=>x.id===d.id);await action('object.save',{id:o.id,expected_revision:o.revision,archived:false});await refresh({render:false});await openObject(o.id);return;}
    case'review-open':{const r=await api(`/api/objects/${encodeURIComponent(d.id)}?revision=${encodeURIComponent(d.revision)}`);modal(`审阅依据 · 修订 ${d.revision}`,`<h3>${esc(r.title)}</h3>${(r.content.blocks||[]).map(b=>`<p style="white-space:pre-wrap">${esc(b.text||'')}</p>`).join('')}`,{wide:true});return;}
    case'source-impacts':return showSourceImpacts();
    case'source-impact-locate':return locateSourceImpact(JSON.parse(d.pin),event?.target);
    case'provenance':modal('成果来源与复现边界',`<p>以下内容直接来自当前成果记录。未登记的源材料不被视为完整可复现。</p>${sourceReferencePanel(ui.object,ui.references,ui.referenceErrors)}${button('归档当前成果','object-archive',{},'button small danger-text')}<pre>${esc(pretty({id:ui.object.id,revision:ui.object.revision,project_id:ui.object.project_id,metadata:ui.object.metadata,dependencies:ui.object.dependencies,source_refs:ui.object.content?.source_refs,source:ui.object.content?.source||ui.object.content?.provenance}))}</pre>`,{wide:true});return;
    case'annotation-locate':{const a=list(ui.object.annotations).find(a=>a.id===d.id),anchor=a?.anchor||{};if(ui.object.kind==='figure'){requireSavedFigureAnchor();return locateFigureAnnotation41({root:app,object:ui.object,annotation:a,dirty:ui.dirty,preview:!!ui.figurePreviewResult||!!figurePreviewController?.isBusy()});}if(anchor.block_id){ui.selectedBlock=anchor.block_id;draw();document.querySelector(`[data-block="${CSS.escape(anchor.block_id)}"]`)?.scrollIntoView({block:'center',behavior:'smooth'});}else{ui.selectedItem=anchor.node_id||anchor.object_id;ui.selectedItems=[ui.selectedItem];const i=ui.draft.content.pages?.findIndex(p=>p.objects.some(o=>o.id===ui.selectedItem));if(i>=0)ui.page=i;draw();}return;}
    case'annotation-resolve':return resolveAnnotation(d);
    case'revision-diff':return showRevisionDiff(Number(d.revision));
    case'revision-restore':return restoreRevision(Number(d.revision));
    case'conflict-review':return showConflict();
    case'draft-download':downloadJSON(`${ui.object.id}-draft.json`,{id:ui.object.id,base_revision:ui.object.revision,...ui.draft});return;
    case'conflict-rebase':requireEditor(ui.conflictSource);ui.object.revision=Number(d.revision);ui.remoteRevision=null;ui.recovered=false;persistDraft();document.querySelector('#modal-root').innerHTML='';draw();toast('已更新草稿基础版本。请核对差异后显式保存。');return;
    case'conflict-reload':requireEditor(ui.conflictSource);downloadJSON(`${ui.object.id}-draft.json`,ui.draft);localStorage.removeItem(draftKey(ui.object.id));document.querySelector('#modal-root').innerHTML='';return openObject(ui.object.id,{force:true});
    case'open-reference':return showReference(d.id,Number(d.revision),d.block_id,d.sha256,d.consumer_id);
    case'component-add':return componentAdd();
    case'component-remove':case'citation-remove':mutate(o=>{const key=name==='component-remove'?'components':'citations';o.content[key]=(o.content[key]||[]).filter(r=>(r.id||r.object_id||r)!==d.id);},true);return;
    case'dependency-accept':case'dependency-retain':{const dependency=list(ui.object.dependencies).find(r=>r.id===d.id);if(!dependency)throw new Error('依赖已变化，请重读当前成果。');await action(name==='dependency-accept'?'dependency.accept':'dependency.retain',{id:d.id,object_id:ui.object.id,expected_revision:ui.object.revision,relation_revision:dependency.metadata?.graph_revision||dependency.revision||1,target_revision:dependency.current_target_revision||objects().find(x=>x.id===dependency.dst)?.revision});}await refresh({render:false});if(!ui.dirty)await openObject(ui.object.id);else toast('依赖处理已记录；本地草稿保留，保存时将检查版本。');return;
    case'graph-relate':return graphRelate();
    case'graph-review':return graphReview(d.project||ui.project);
    case'graph-conflict-resume':return resumeGraphConflict(d.id);
    case'graph-proposal-item':return graphProposalItem(d.id,d.item);
    case'graph-relation':return graphRelation(d.id);
    case'graph-relation-edit':return graphRelation(d.id,true);
    case'graph-duplicate':return graphDuplicate(d);
    case'graph-project':{if(ui.dirty)persistDraft();const target=enterAssociatedProject(context(),d,{generation:loadCounter});loadCounter++;clearTimeout(typingTimer);document.querySelector('#modal-root').innerHTML='';draw();document.querySelector(`[data-graph-node="${CSS.escape(target.id)}"]`)?.scrollIntoView({block:'center',inline:'center'});return;}
    case'graph-project-return':{if(ui.dirty)persistDraft();if(ui.graphReturn)rememberGraphEditor(ui,loadCounter);loadCounter++;clearTimeout(typingTimer);returnFromAssociatedProject(context());draw();return;}
    case'graph-focus':{const obj=objects().find(o=>o.id===d.id);if(!obj)throw new Error('对象不在当前可读目录中。');document.querySelector('#modal-root').innerHTML='';ui.project=obj.project_id||obj.id;ui.view='graph';ui.graphDomain='';ui.graphProjectRoot='';ui.graphSearch=obj.id;ui.graphKind='';draw();document.querySelector(`[data-graph-node="${CSS.escape(obj.id)}"]`)?.scrollIntoView({block:'center',inline:'center'});return;}
    case'graph-collapse':ui.collapsed.has(d.id)?ui.collapsed.delete(d.id):ui.collapsed.add(d.id);draw();return;
    case'graph-directory':ui.graphDirectory=!ui.graphDirectory;draw();return;
    case'graph-zoom':ui.zoom=Math.max(.35,Math.min(1.8,ui.zoom+Number(d.delta)));draw();return;
    case'graph-reset':ui.zoom=1;draw();return;
    case'graph-merge':return graphMerge(d.source,d.target);
    case'page-select':ui.page=Number(d.index);ui.selectedItem='';ui.selectedItems=[];draw();return;
    case'page-add':mutate(o=>{o.content.pages||=[];const p=o.content.pages[ui.page]||newContent(ui.object.kind).pages[0];o.content.pages.splice(ui.page+1,0,{id:uid('page'),width:p.width,height:p.height,objects:[],notes:''});ui.page=Math.min(ui.page+1,o.content.pages.length-1);ui.selectedItem='';ui.selectedItems=[];},true);return;
    case'page-move':mutate(o=>{const a=o.content.pages,j=ui.page+Number(d.direction);if(j>=0&&j<a.length){[a[ui.page],a[j]]=[a[j],a[ui.page]];ui.page=j;}},true);return;
    case'page-delete':mutate(o=>{o.content.pages.splice(ui.page,1);ui.page=Math.max(0,ui.page-1);ui.selectedItem='';ui.selectedItems=[];},true);return;
    case'canvas-add':return addCanvasItem(d.type);
    case'canvas-delete':mutate(o=>{const page=o.content.pages[ui.page];page.objects=page.objects.filter(x=>!ui.selectedItems.includes(x.id)&&x.id!==ui.selectedItem);ui.selectedItems=[];ui.selectedItem='';},true);return;
    case'canvas-align':case'diagram-align':mutate(o=>{const items=name==='diagram-align'?o.content.nodes:o.content.pages[ui.page].objects;const selected=items.filter(x=>ui.selectedItems.includes(x.id));if(selected.length<2)return;const k=d.axis==='left'?'x':'y',value=Math.min(...selected.map(x=>Number(x[k]||0)));selected.forEach(x=>x[k]=value);},true);return;
    case'canvas-group':case'diagram-group':case'canvas-ungroup':case'diagram-ungroup':mutate(o=>{const items=name.startsWith('diagram')?o.content.nodes:o.content.pages[ui.page].objects;const group=name.endsWith('ungroup')?null:uid('group');items.filter(x=>ui.selectedItems.includes(x.id)||x.id===ui.selectedItem).forEach(x=>{if(group)x.group=group;else delete x.group;});},true);return;
    case'diagram-add':mutate(o=>{o.content.nodes||=[];const n={id:uid('node'),text:'新节点',x:70+o.content.nodes.length%4*210,y:70+Math.floor(o.content.nodes.length/4)*130,width:160,height:70,source:''};o.content.nodes.push(n);ui.selectedItem=n.id;ui.selectedItems=[n.id];},true);return;
    case'diagram-delete':mutate(o=>{const ids=new Set([...ui.selectedItems,ui.selectedItem]);o.content.nodes=o.content.nodes.filter(n=>!ids.has(n.id));o.content.edges=(o.content.edges||[]).filter(e=>!ids.has(e.source||e.src)&&!ids.has(e.target||e.dst));ui.selectedItem='';ui.selectedItems=[];},true);return;
    case'diagram-edge':case'diagram-edge-edit':return editDiagramEdge(d.id);
    case'diagram-edge-delete':mutate(o=>o.content.edges=o.content.edges.filter(e=>e.id!==d.id),true);document.querySelector('#modal-root').innerHTML='';return;
    case'workspace-nav-toggle':ui.navExpanded=!ui.navExpanded;draw();return;
    case'figure-property-tab':ui.figurePropertyTab=d.tab;draw();return;
    case'figure-tool':return;
    case'figure-color':case'figure-cmap':setFigureOverlay(d.key,d.value);return;
    case'figure-zoom':ui.figureZoom=d.value?Number(d.value):Math.max(.35,Math.min(3,(ui.figureZoom||1)+Number(d.delta)));refreshFigureSurface();return;
    case'figure-preview-cancel':if(figureRenders.has(ui.object?.id))throw new Error('保存或采用仍在进行；请等待回执。取消预览不会撤回已提交的保存。');figurePreviewController?.cancel();ui.figurePreviewResult=null;ui.figurePreviewError='';ui.draft={title:ui.object.title,content:clone(ui.object.content)};ui.dirty=false;ui.recovered=false;localStorage.removeItem(draftKey(ui.object.id));draw();return;
    case'figure-preview-apply':if(ui.figurePreviewError)throw new Error('预览未完成有效校验：'+ui.figurePreviewError+'；请先修正属性。');return applyVisualFigure41();
    case'figure-source-save':{
      const source=editorSnapshot();figurePreviewController?.destroy();figurePreviewController=null;ui.figurePreviewResult=null;
      await save();
      if(sameEditor(source)){
        // save() refreshes the decorated saved details; redraw those pixels without executing source.
        ui.figurePreviewStatus='source_changed';ui.figurePreviewError='来源已保存，当前图像仍是旧渲染；核对科学执行授权后再明确重绘。';draw();
      }
      return;
    }
    case'figure-composition':mutate(o=>{o.content.composition=!o.content.composition;if(o.content.composition){o.content.units||='px';o.content.pages||=[{id:uid('page'),width:1000,height:800,objects:[],notes:''}];}},true);return;
    case'figure-select':ui.selectedItem=d.id;ui.figureCmapScope='matching';draw();if(ui.dirty||figurePreviewController?.isBusy())scheduleFigurePreview();return;
    case'figure-overlay-clear':mutate(o=>{o.content.overlays=overlayLayers(o.content).filter(v=>(v.target||v.object_id||v.id)!==ui.selectedItem);},true);scheduleFigurePreview();return;
    case'figure-download':showExport();document.querySelector('#modal-root [name=format]').value='zip';return;
    case'figure-render':return renderFigureSaved();
    case'figure-code':return editFigureCode();
    case'figure-annotate':requireSavedFigureAnchor();return annotate(figureArtistAnchor(ui.object,ui.selectedItem));
    case'open-workshop':{const raw=await api(`/api/objects/${encodeURIComponent(d.id)}`);ui.workshop=raw.object||raw;ui.view='workshop';draw();return;}
    case'extension-settings':{ui.view='settings';draw();const entry=[...document.querySelectorAll('[data-extension-id]')].find(e=>e.dataset.extensionId===d.id);if(entry){entry.querySelector('details').open=true;entry.scrollIntoView({block:'center'});entry.querySelector('summary').focus();}return;}
    case'workshop-select':{const raw=await api(`/api/objects/${encodeURIComponent(d.id)}`);ui.workshop=raw.object||raw;draw();document.querySelector('.workshop-entry.active')?.scrollIntoView({block:'nearest',inline:'nearest'});return;}
    case'workshop-new':ui.workshop=false;ui.workshopRequestKey=uid('workshop');draw();return;
    case'workshop-example':{const form=document.querySelector('#workshop-form');form.elements.config.value=pretty(workshopRecipes[workshopKey(d.category)].config);form.querySelectorAll('input[type=checkbox]').forEach(el=>el.checked=false);return;}
    case'workshop-accept':{const raw=await api(`/api/objects/${encodeURIComponent(d.id)}`);const o=raw.object||raw;modal('登记技术验收',`<p>对象 ${esc(o.id)} · 修订 ${esc(o.revision)}；本次检查绑定此产物。</p>${select('验收结果','status',[['failed','未通过'],['accepted','通过已检查的技术条件'],['pending','尚待检查']])}${field('实际检查与证据','evidence','','textarea','required')}${field('限制与未检查项','limitations','','textarea')}`,{submit:async v=>{await action('workshop.accept',{id:o.id,expected_revision:o.revision,...v});await refresh({render:false});const latest=await api(`/api/objects/${encodeURIComponent(d.id)}`);ui.workshop=latest.object||latest;draw();}});return;}
    case'literature-import':return literatureImport();
    case'literature-add':return literatureImport(ui.literatureResults[Number(d.index)]);
    case'activity-tab':ui.tab=d.tab;draw();return;
    case'task-priority':modal('调整任务优先级',field('优先级（越高越先执行）','priority','0','number','required step="1"'),{submit:async v=>{await action('task.control',{id:d.id,operation:`priority:${Number(v.priority)}`});await refresh();}});return;
    case'cycle-revise-failed-child':return reviseFailedChild(d.id,d.child);
    case'task-control':{const task=list(ui.data.tasks).find(t=>t.id===d.id);await action(task?.payload?.kind==='research_cycle'?'cycle.control':'task.control',{id:d.id,operation:d.command});await refresh();return;}
    case'task-guide':return taskGuidance(d.id);
    case'task-revise-candidate':return reviseCandidate(d.id);
    case'task-budget':return taskBudget(d.id);
    case'cycle-stage-final-revision':return stageCycleFinalRevision(d.id);
    case'cycle-stage-revision':return stageCycleRevision(d.id,d.delegate);
    case'cycle-revision-candidate':return showCycleCandidate(d.id,d.delegate,d.sha);
    case'task-recover-preview':return recoverNativeCandidate(d.id);
    case'task-detail':{const task=await api(`/api/tasks/${encodeURIComponent(d.id)}`);if(task.payload?.kind==='project_management'&&task.result?.project_management){return handle('management-review',{id:d.id});}if(task.payload?.kind==='research_cycle'){const view=await action('cycle.view',{id:d.id});modal('科研协作',cycleDetail(view)+finalRevisionPanel(view),{wide:true});return;}modal('任务记录',`<div class="section-heading"><h3>${esc(task?.title||task?.objective||task?.payload?.request||task?.id)}</h3>${status(task?.status)}</div><p>${esc(task?.error||task?.message||'')}</p>${task.payload?.cycle_parent?button('返回所属科研协作','task-detail',{id:task.payload.cycle_parent},'button small'):''}${recoveryEntry(task)}${acquisitionPanel(task.payload?.literature_plan,task.acquisition)}<pre>${esc(pretty(task))}</pre>`,{wide:true});return;}
    case'decision':return decision(d.id);
    case'question-materialize':{const q=await api(`/api/objects/${encodeURIComponent(d.id)}`);await action('question.materialize',{id:q.id,expected_revision:q.revision});await refresh();toast('已展开独立历史建议；已有回答与暂缓安排保留。');return;}
    case'question-bind':return bindQuestion(d.id);
    case'question-reassess':{const q=await api(`/api/objects/${encodeURIComponent(d.id)}`);modal('明确重新评估旧问题的来源',questionReassessFields(q),{wide:true,label:'保存这次明确评估',submit:async v=>{await action('question.reassess',{id:q.id,expected_revision:q.revision,source_snapshot:q.question_view.sources,reason:v.reason,answer:v.answer,disposition:v.disposition,approved:v.approved==='on'});await refresh();toast('旧题与采用版本保留；已记录本次评估，未增加权限。');}});return;}
    case'question-candidate':{const result=await action('question.candidate_preview',{id:d.id});modal('已保存候选 · 只读',`<p class="hint">${esc(result.task_id)} · ${esc(result.sha256)}。尚未保存为正式成果；查看不会调用模型。</p><pre>${esc(pretty(result.candidate))}</pre>`,{wide:true});return;}
    case'feedback':return feedback();
    case'feedback-review':return editFeedback(d.id);
    case'feedback-request':return requestFeedback(d.id);
    case'feedback-withdraw':return withdrawFeedback(d.id);
    case'growth-execution-create':return growthExecution('create',d.id);
    case'growth-execution-register':return growthExecution('register',d.id);
    case'growth-method-assess':return methodAssessment(d.id);
    case'growth-propose':return growthForm('propose');
    case'growth-trial_bind':case'growth-trial_create':case'growth-preference':case'growth-compare':case'growth-adopt':case'growth-revert':case'growth-reject':return growthForm(name.slice(7),d.id);
    case'provider-configure':return;
    case'session-logout':return endSession();
    case'extension-register':case'extension-authorize':case'extension-revoke':case'extension-call':case'extension-uninstall':case'extension-upgrade':case'extension-rollback':return extensionForm(name.slice(10),d.id);
    case'setting-edit':return editConventions({key:d.key,projectId:ui.project,action,refresh});
    case'preference':return feedback('convention');
    case'backup':{const r=await action('workspace.backup');const url=assetURL(r.url||r.asset||r.sha||r.sha256);modal('研究空间备份',url?`<p>备份由服务端生成。迁移前请核对清单中的缺失依赖。</p><a class="button primary" href="${esc(url)}" download>下载备份</a><pre>${esc(pretty(r.manifest||r.limitations||{}))}</pre>`:`<pre>${esc(pretty(r))}</pre>`);return;}
    case'quick-search':return quickSearch();
  }
}
function addCanvasItem(type){const page=ui.draft.content.pages[ui.page];if(!page)return;const add=extra=>mutate(o=>{const p=o.content.pages[ui.page],cm=o.content.units==='cm',item={id:uid('item'),type,text:type==='text'?'编辑文本':'',x:p.width*.1,y:p.height*.1,width:p.width*.4,height:type==='text'?p.height*.12:p.height*.3,font_size:cm?1:28,color:'#253a39',fill:type==='shape'?'#e8efeb':'#ffffff',...extra};p.objects.push(item);ui.selectedItem=item.id;ui.selectedItems=[item.id];},true);if(type==='image'){modal('插入图像或已有科研图',`${field('资产 SHA / 已注册资源地址','asset')}${select('关联来源成果','component_id',[['','无'],...objectOptions().filter(([id])=>id!==ui.object.id)])}${field('替代文本 / 内容说明','text')}`,{submit:v=>{const ref=objects().find(o=>o.id===v.component_id);add({...v,asset:registeredSHA(v.asset||ref?.metadata?.last_export?.assets?.['figure.png']||ref?.content?.preview||ref?.content?.preview_asset),component_revision:ref?.revision});}});}else add({});}
function retainUploadReceipt(receipt){
 try{const key='research-partner:asset-receipts',old=JSON.parse(localStorage.getItem(key)||'[]');const records=old.filter(x=>!(x.sha===receipt.sha&&x.project_id===receipt.project_id&&x.object_id===receipt.object_id));records.unshift({...receipt,at:new Date().toISOString()});localStorage.setItem(key,JSON.stringify(records.slice(0,40)));}catch{toast(`资产回执：${receipt.sha} · 原项目 ${receipt.project_id}；浏览器未能保存回执，请复制此身份。`,'error');}
}
function showUploadReceipts(){
 let receipts=[];try{receipts=JSON.parse(localStorage.getItem('research-partner:asset-receipts')||'[]');}catch{}
 modal('此浏览器的资产回执',receipts.length?receipts.map(r=>`<article class="panel"><strong>${esc(r.filename||r.sha)}</strong><p>原项目 ${esc(r.project_id)} · 原成果 ${esc(r.object_id||'未绑定')}</p><p>${esc(r.outcome==='applied_to_local_draft'?'已应用到当时的本地草稿，仍需保存':r.outcome==='not_applied'?'未应用到稿件；可回到原项目后用 SHA 重新绑定':'资产已登记 / 检查，未提交文稿修改')}</p><code>${esc(r.sha)}</code>${r.imported_object_id?`<p>${button('打开导入成果','open-object',{id:r.imported_object_id},'button small')}</p>`:''}${r.error?`<p>${esc(r.error)}</p>`:''}${registeredDocumentAssetURL(r.sha)?`<p><a href="${registeredDocumentAssetURL(r.sha)}" target="_blank" rel="noopener">打开已登记资产</a></p>`:''}</article>`).join(''):empty('尚无本机上传回执','上传完成后会保留原项目、资产 SHA 与是否应用到草稿的状态。'),{wide:true});
}
function editDocumentImage(reference='',blockId,offset){
 if(!ui.object||!ui.draft)return;
 const target=captureDocumentTarget(ui),occurrences=documentImageOccurrences(target.draft.content);
 const image=occurrences.find(x=>x.reference===reference&&(!blockId||x.block_id===blockId)&&(offset===undefined||x.start===Number(offset)));
 if(reference&&!image){toast('图片正文已变化，请重新选择。','error');return;}
 const resources=target.draft.content.resources||{},existing=Object.hasOwn(resources,reference)?resources[reference]:null;
 const asset=typeof existing==='string'?existing:existing?.asset||existing?.sha||reference.match(/^\/api\/assets\/([a-f0-9]{64})$/)?.[1]||'';
 modal(reference?'绑定所选文稿图片':'插入文稿图片',`${field('文稿内图片名称','reference',reference.startsWith('/api/assets/')?'sources/figure.png':reference||'sources/figure.png','text','required')}${field('这处图片的说明','alt',image?.alt||'')}${field('本项目已登记图像 SHA（或在下面选取文件）','asset',asset)}<label class="field"><span>选取 PNG 或 JPEG 文件</span><input type="file" name="file" accept="image/png,image/jpeg,.png,.jpg,.jpeg"></label><p class="hint">只改所选图片的正文位置；其他说明、代码与旧名称链接保留。同名资源共用资产，要只更换这一处图像请使用新名称。应用前核验原项目权限、文件类型并在客户端解码。等待期间换稿、关闭窗口或编辑草稿，会保留回执且不应用。</p>`,{label:reference?'更新所选图片绑定':'加入图片段落',submit:async(v,form)=>{
   const file=form.querySelector('[name=file]').files[0];
   const result=await applyDocumentImage({state:ui,target,selection:image,values:v,file,upload,inspect:(sha,project_id)=>action('asset.inspect',{sha,project_id}),retain:retainUploadReceipt,newBlockId:()=>uid('block'),isActive:()=>form.isConnected!==false,commit:(content,newId)=>mutate(o=>{o.content=content;if(newId)ui.selectedBlock=newId;},true)});
   if(!result.applied){toast(`原稿或窗口状态已变化，未应用图片。${result.receipt?`资产 ${result.receipt.sha} 保存在原项目，可从“上传回执”找回。`:''}`);return false;}
   toast('图像已核验并加入原稿草稿；保存后才形成服务器修订。');
 }});
}

function editDiagramEdge(id){
 const edges=ui.draft.content.edges||[],edge=edges.find(e=>e.id===id)||{},nodes=ui.draft.content.nodes||[];
 if(nodes.length<2){toast('请先添加至少两个节点。');return;}
 const ref=edge.source_ref&&typeof edge.source_ref==='object'?edge.source_ref:{};
 const references=objects().filter(o=>o.kind!=='project').map(o=>[o.id,o.title]);
 if(ref.id&&!references.some(([ident])=>ident===ref.id))references.push([ref.id,ref.id+'（原采用来源）']);
 modal(id?'编辑节点关系':'添加节点关系',`${select('起点','source',nodes.map(n=>[n.id,n.text||n.label]),edge.source||'')}${select('终点','target',nodes.map(n=>[n.id,n.text||n.label]),edge.target||'')}${field('关系含义','label',edge.label||'','text','required')}${select('证据状态','status',[['candidate','候选 / 待验证'],['confirmed','已有依据']],edge.status||'candidate')}${select('来源成果','reference_id',[['','尚未登记'],...references],ref.id||'')}${field('采用来源修订','reference_revision',ref.revision||'','number','min="1" step="1"')}${field('来源段落标识（可选）','reference_block',ref.block_id||'')}<p class="hint">已有来源保持其采用修订。要更换来源，请填写准确修订；清空全部来源字段可移除引用。</p>${id?button('删除关系','diagram-edge-delete',{id},'button danger-text'):''}`,{submit:v=>{
  if(v.source===v.target)throw new Error('请选择两个不同节点。');
  const reference=diagramReference(v);
  const update={source:v.source,target:v.target,label:v.label,status:v.status};
  mutate(o=>{o.content.edges||=[];const item=id?o.content.edges.find(e=>e.id===id):{id:uid('edge')};Object.assign(item,update);if(reference)item.source_ref=reference;else delete item.source_ref;if(!id)o.content.edges.push(item);},true);
 }});
}
async function decision(id){const q=await api(`/api/objects/${encodeURIComponent(id)}`);modal('研究问题',questionAnswerFields(q),{label:'保存回答',submit:async v=>{await action('decision.answer',{id,expected_revision:q.revision,...v});await refresh();}});}
async function bindQuestion(id){
 const q=await api(`/api/objects/${encodeURIComponent(id)}`),tasks=list(ui.data.tasks).filter(t=>t.project_id===q.project_id&&['queued','paused','waiting_input','waiting_resource','waiting_authorization','failed'].includes(t.status));
 if(!tasks.length){toast('请先创建或停止一项同项目任务，再明确绑定问题。');return;}
 modal('明确绑定后续任务',`${questionDetails(q)}${select('受到这条问题影响的具体任务','task_id',tasks.map(t=>[t.id,t.payload?.request||t.id]))}${select('是否必须先回答','blocking',[['false','只作为任务输入，不阻断'],['true','必要裁决，未继续前等待']],'false')}<p class="hint">只绑定所选任务；保留已有回答，不增加代码、科学或费用权限。</p>`,{label:'确认绑定',submit:async v=>{await action('question.bind',{id,expected_revision:q.revision,task_id:v.task_id,blocking:v.blocking==='true',approved:true});await refresh();}});
}
function feedback(scope){
 if(!ensureProject())return;
 const projectId=ui.project,target=ui.view==='workspace'&&ui.object?.project_id===projectId&&ui.object.kind!=='feedback'?{id:ui.object.id,title:ui.object.title,revision:ui.object.revision}:null;
 if(scope==='revision'&&!target)return;
 modal(scope==='convention'?'登记项目约定':scope==='revision'?'记录修订意见':'记录反馈',`${target?`<p>关联：${esc(target.title)} · 当前修订 ${target.revision}（留言采用此版本）</p>`:'<p>意见关联当前项目。</p>'}${feedbackFields()}${scope==='revision'?'<p class="notice">先保存意见，随后打开材料与有限额度安排；在下一步明确提交前不会启动模型。</p>':''}`,{wide:true,label:scope==='revision'?'保存意见并查看执行安排':'仅保存意见',submit:async(v,form)=>{
  const result=await action('feedback.add',{...v,project_id:projectId,object_id:target?.id,object_revision:target?.revision,kind:scope==='convention'?'convention':'feedback'});
  await refresh({render:false});if(!form.isConnected)return false;
  toast('意见已保存，尚未发起行动。');if(scope==='revision'&&v.disposition!=='defer'){await requestFeedback(result.id);return false;}await openObject(result.id);return result;
 }});
}
async function readFeedback(id){const raw=await api(`/api/objects/${encodeURIComponent(id)}`);const item=raw.object||raw;if(item.kind!=='feedback')throw new Error('此对象不是反馈。');return item;}
async function feedbackDialogRecord(id){
 const loading=modal('读取意见','<p>正在读取当前原话、安排和行动状态。</p>');
 try{const item=await readFeedback(id);if(!loading.active())return null;return {record:item,active:loading.active};}
 catch(error){if(loading.active())modal('无法读取意见',`<p>${esc(error.message)}</p>`);throw error;}
}
async function editFeedback(id){
 const loaded=await feedbackDialogRecord(id);if(!loaded)return;const f=loaded.record;
 const submit=feedbackSubmission({base:f,read:()=>readFeedback(id),request:(current,v)=>action('feedback.review',{id,expected_revision:current.revision,...v}),saved:async(result,form)=>{await refresh({render:false});if(!form.isConnected)return;await openObject(id,{force:true});toast('理解与安排已保存；未发起或恢复任务。');}});
 modal('理解与处理时机',`<h3>原话</h3><blockquote>${esc(feedbackValues(f).original)}</blockquote>${feedbackFields(f)}<p class="hint">范围和时机用于后续新行动。修正理解会送至关联未完成任务的下个交接点；保存不会新建、恢复任务或增加额度。暂停或取消请进入关联任务。</p><div data-feedback-reconcile></div>`,{wide:true,label:'仅保存理解与安排',submit});
}
async function withdrawFeedback(id){
 const loaded=await feedbackDialogRecord(id);if(!loaded)return;const f=loaded.record;
 const submit=feedbackSubmission({base:f,read:()=>readFeedback(id),request:current=>action('feedback.withdraw',{id,expected_revision:current.revision}),saved:async(result,form)=>{await refresh({render:false});if(!form.isConnected)return;await openObject(id,{force:true});toast('意见已撤回；关联任务按实际撤回结果显示。');}});
 modal('撤回意见',`<blockquote>${esc(feedbackValues(f).original)}</blockquote><p>撤回会停止关联的可撤回任务，并保留原话、已有成果和处理历史。</p><div data-feedback-reconcile></div>`,{label:'确认撤回这条意见',wide:true,submit});
}
async function requestFeedback(id){
 const loaded=await feedbackDialogRecord(id);if(!loaded)return;const f=loaded.record;
 if(feedbackValues(f).disposition==='defer')return editFeedback(id);
 const source=f.content?.object_id;let target=null;
 try{target=source?await api(`/api/objects/${encodeURIComponent(source)}`).then(x=>x.object||x):null;}catch(error){if(loaded.active())modal('无法读取关联成果',`<p>${esc(error.message)}</p><p>反馈仍然保存；未提交任务。</p>`);throw error;}
 if(!loaded.active())return;
 // Fetching the target cannot submit a task. Its exact revision is separately checked at submission.
 const original=feedbackValues(f),read=async()=>{const feedback=await readFeedback(id),targetId=feedback.content?.object_id;return {feedback,target:targetId?await api(`/api/objects/${encodeURIComponent(targetId)}`).then(x=>x.object||x):null};};
 const submit=feedbackCommission({feedback:f,target,requestKey:uid('feedback-request'),read,action,saved:async(result,form)=>{await refresh({render:false});if(!form.isConnected)return;await openObject(id,{force:true});toast(`已登记关联任务 ${result.id}；请查看真实执行状态。`);}});
 modal('按已有意见安排关联行动',`<h3>保留的原话</h3><blockquote>${esc(original.original)}</blockquote><p class="hint">沿用这条意见的身份，无需重录。查找材料仅预览；再次明确提交才创建任务。</p>${select('这次安排','scope',Object.entries(scopeNames),original.scope)}${select('结果或单独方法任务的时机','timing',Object.entries(timingNames).filter(([key])=>key!=='next_handoff'),original.timing==='next_handoff'?'immediate':original.timing)}<p class="hint">同时安排两类意见时，先处理成果，再由独立关联任务分析工作方式；不会自动采用策略。任务后执行会等待提交时已存在的相关任务，不自动恢复暂停的任务。</p><div id="commission-resolution"></div>${select('执行提供者','provider',[['','使用空间默认路线'],...list(ui.data.providers).map(p=>[p.id,p.name||p.id])])}<div class="field-grid">${field('每个行动的模型调用上限','budget','4','number','min="1" max="100" step="1" required')}${field('每个行动的执行秒数上限','timeout','300','number','min="1" max="900" required')}</div><p class="hint">同时安排两类行动会创建两个任务，合计上限是每项所填额度的两倍。每项分别计费，不会无限续跑。</p><details><summary>材料与执行边界</summary>${acquisitionFields()}${field('采用的成果 ID（可加 @修订号，每行一项）','additional_materials',target&&target.kind!=='project'?`${target.id}@${target.revision}`:'','textarea')}${field('补充背景','background','','textarea')}${field('方法与授权边界','constraints','读取采用材料，保留来源和不确定性；不改原始数据，不启动新拟合或未经授权的服务。','textarea')}${field('验收要求','acceptance','说明具体改动、验证证据和限制；形成候选后审查，不把模型返回视为验收。','textarea')}</details><div data-feedback-reconcile></div>`,{wide:true,label:'查找项目与材料',submit});
}

function growthExecution(mode,id){
 const growth=list(ui.data.growth).find(g=>g.id===id);if(!growth)throw Error('成长候选不可读取。');
 modal(mode==='create'?'登记独立上下文的有限评估任务':'绑定真实评估执行与两侧审阅',executionFields(mode,growth,list(ui.data.tasks),list(ui.data.providers)),{wide:true,label:'预览精确输入与执行身份',submit:executionSubmission({mode,growth,requestKey:uid('growth-evaluation'),action,read:async()=>{const r=await api(`/api/objects/${encodeURIComponent(id)}`);return r.object||r;},saved:async r=>{await refresh();toast(r.task_id?`评估 ${r.task_id} 保持等待；请在任务详情明确继续。`:`已绑定评估 ${r.assessment.id}，尚未比较或采用。`);}})});
}

function methodAssessment(id){
 const growth=list(ui.data.growth).find(g=>g.id===id);if(!growth)throw Error('成长候选不可读取。');
 modal('科研方法结果的明确配对评价',assessmentFields(),{wide:true,label:'读取两侧实际输出与中性审查包',submit:assessmentSubmission({growth,requestKey:uid('method-assessment'),action,read:async()=>{const r=await api(`/api/objects/${encodeURIComponent(id)}`);return r.object||r;},saved:async result=>{await refresh();toast(`已保存评价 ${result.assessment.id}；尚未比较或采用。请回成长卡明确登记比较。`);}})});
}

function growthForm(operation,id){
 const labels={propose:'提出成长候选',trial_bind:'现有任务有限试用',trial_create:'新建单任务有限试用',compare:'比较实际执行',adopt:'限定范围采用',preference:'保存未验证偏好',reject:'不采用候选',revert:'撤回后续注入'};
 if(operation==='propose'&&!ensureProject())return;
 const growth=list(ui.data.growth).find(g=>g.id===id),feedback=list(ui.data.feedback).filter(f=>f.project_id===(growth?.project_id||ui.project));
 if(operation==='propose'&&!feedback.length){toast('请先登记真实反馈作为候选来源。');return;}
 const submit=growthSubmission({operation,growth,projectId:ui.project,requestKey:uid('growth-action'),action,read:async()=>{const r=await api(`/api/objects/${encodeURIComponent(id)}`);return r.object||r;},saved:async result=>{await refresh();toast(result.task_id?`有限试用已登记，任务 ${result.task_id} 等待明确继续。`:'成长记录已保存；请查看证据与当前作用范围。');}});
 modal(labels[operation],growthFields(operation,{growth,feedback,tasks:list(ui.data.tasks),providers:list(ui.data.providers)}),{wide:true,label:['trial_bind','trial_create','compare'].includes(operation)?'预览精确输入与证据':labels[operation],submit});
}

async function taskGuidance(id){
 const task=await api(`/api/tasks/${encodeURIComponent(id)}`);
 if(!canGuide(task))throw new Error('该任务已结束，不能接收新的指导。');
 modal('补充任务指导',`<p>${esc(task.payload?.request||task.id)}</p><p class="hint">指导保留在同一任务记录中，在下一次执行交接时生效。如果已有候选未包含新指导，执行会保留旧候选并等待明确修订；此处不会改变权限或自动恢复任务。</p>${field('指导内容与边界','text','','textarea','required rows="6"')}`,{label:'保存指导',submit:async v=>{const r=await action('task.guide',{id,text:v.text.trim()});await refresh();toast(r.guidance_saved?'指导已记录；在下一次执行交接时读取。':'已收到服务端返回，请查看任务记录。');}});
}
async function taskBudget(id){
 const task=await api(`/api/tasks/${encodeURIComponent(id)}`),providers=list(ui.data.providers);
 if(!canExtendBudget(task,providers))throw new Error('仅停止后的 Codex 路线任务可从此入口追加。');
 modal('明确追加有限额度',`<div class="notice warning">额度会累加，既有消耗保留。不会自动继续任务，也不会增加三次执行尝试上限。</div><p>${esc(task.payload?.request||task.id)} · ${status(task.status)}</p><p>原请求上限：${esc(task.payload?.budget?.max_model_calls)} 次调用，${esc(task.payload?.budget?.timeout_seconds)} 秒；已进入执行 ${esc(task.attempts)} 次。</p><p class="hint">这里的调用单位为 Codex CLI 调用，不等于内部 API 请求数；实际费用未由此界面核定。消费记录以任务执行证据为准。</p><div class="field-grid">${field('本次新增 CLI 调用次数','additional_invocations','0','number','required min="0" max="5" step="1"')}${field('本次新增累计执行时限（秒）','additional_seconds','0','number','required min="0" max="900" step="1"')}</div>${field('追加理由、成本与工作范围','reason','','textarea','required')}<label class="check-field"><input type="checkbox" name="approved" required><span>我明确批准上面填写的有限新增额度，并理解这会允许后续额外调用；提交后仍需另行继续任务</span></label><div id="budget-extension-result"></div>`,{wide:true,label:'确认追加所填额度',submit:async(v,form)=>{const r=await action('task.extend_budget',budgetExtension(task,v,providers));await refresh({render:false});form.querySelector('#budget-extension-result').innerHTML=`<div class="notice">服务端已登记累计追加 ${esc(r.extension?.invocations)} 次、${esc(r.extension?.seconds)} 秒。既有消耗${r.consumption_preserved?'已保留':'请核对'}；${r.automatically_resumed===false?'任务未自动继续。':'请核对任务状态。'}</div>`;const summary=form.querySelector('#budget-extension-result').innerHTML;setTimeout(()=>modal('新增额度已登记',summary),0);}});
}
function extensionForm(operation,id){
 const entry=list(ui.data.extensions).find(e=>e.id===id),texts={register:'注册外部扩展',upgrade:'升级扩展版本',authorize:'管理当前版本授权',revoke:'撤销全部授权',call:'执行已授权扩展',rollback:'回退扩展版本',uninstall:'卸载扩展'};
 if(operation==='call'&&!ensureProject())return;
 const versionInfo=entry?`<p><strong>${esc(entry.name||entry.id)}</strong> · ${esc(entry.version)}</p><p class="hint">当前清单 SHA：${esc(entry.manifest_sha256)}</p>`:'';
 let body=versionInfo;
 if(['register','upgrade'].includes(operation)){
  const sample={id:id||'my-extension',name:entry?.name||'我的扩展',version:operation==='upgrade'?'填写新语义版本':'1.0.0',api_version:1,entrypoint:'main.py',permissions:['execute_code','read_inputs','write_outputs'],operations:entry?.operations||['run'],files:{'main.py':{}}};
  body+=`${field('扩展清单（JSON）','manifest',pretty(sample),'textarea','required rows="13"')}<label class="field"><span>读取本机 manifest.json（可选）</span><input type="file" name="manifest_file" accept=".json"></label><label class="field"><span>选择清单中的实际源码文件</span><input type="file" name="source_files" multiple></label><label class="field"><span>或选择包含子目录的源码文件夹</span><input type="file" name="source_directory" webkitdirectory multiple></label><p class="hint">只发送 files 明确列出的 1–32 个文件，总量最多 1 MB。浏览器计算 SHA256 并携带源码；已声明的哈希不匹配会被拒绝。嵌入 base64 的完整清单也可直接使用。注册、升级均不授予执行权限。</p><div id="extension-package-summary"></div>`;
 }else if(operation==='authorize'){
  body+=`<p>逐项选择当前版本所需权限。提交会替换已有授权集合，未选中的权限会撤销。</p>${(entry.required_permissions||[]).map(p=>`<label class="check-field"><input type="checkbox" name="permission" value="${esc(p)}" ${entry.permissions?.includes(p)?'checked':''}><span>${esc({execute_code:'执行信任的本机 Python 代码',read_inputs:'读取本次登记的输入副本',write_outputs:'写入并登记新的输出'}[p]||p)}</span></label>`).join('')}<div class="notice warning">Python 以服务用户权限运行，不是操作系统安全沙箱。这里只授予已核对来源的代码。</div><label class="check-field"><input type="checkbox" name="approved" required><span>我确认当前清单版本与所选权限范围</span></label>`;
 }else if(operation==='call'){
  if(!entry?.authorized||entry.status!=='installed')throw new Error('此版本尚未获得完整授权，或已卸载。');
  body+=`${select('已声明操作','operation',(entry.operations||[]).map(x=>[x,x]))}${field('登记输入的 SHA 数组','assets','[]','textarea','required')}${field('本次操作参数（JSON 对象）','params','{}','textarea','required')}<p class="hint">输出会登记为本项目的工坊成果；执行成功不代表技术或科学验收。</p><label class="check-field"><input type="checkbox" name="approved" required><span>按所选操作与以上输入执行当前已授权版本</span></label>`;
 }else if(operation==='rollback'){
  body+=`${select('回退到已登记版本','manifest_sha256',(entry.versions||[]).filter(v=>v.sha256!==entry.manifest_sha256).map(v=>[v.sha256,`${v.version} · ${v.sha256}`]))}<p>回退会清除当前授权，需要核对旧版本后重新授予权限；既有产物和记录保留。</p>`;
 }else body+=`<p>${operation==='revoke'?'撤销此扩展的全部执行与数据权限；进行中的调用会被停止。':'卸载会停止执行并撤销授权；保留版本档案、已产生的成果和执行记录。'}</p>`;
 const dialog=modal(texts[operation],body,{wide:true,label:texts[operation],submit:async(v,form)=>{
  let fields={id},actionName=`extension.${operation}`;
  if(['register','upgrade'].includes(operation)){
   const manifest=await packageExtension(v.manifest,[...form.elements.source_files.files,...form.elements.source_directory.files]);
   if(operation==='upgrade'&&manifest.id!==id)throw new Error('升级清单的 id 必须与当前扩展一致。');
   fields={manifest};form.querySelector('#extension-package-summary').innerHTML=`<p>已核对 ${Object.keys(manifest.files).length} 个源文件；正在登记。</p><pre>${esc(pretty(Object.fromEntries(Object.entries(manifest.files).map(([n,x])=>[n,x.sha256]))))}</pre>`;
  }else if(operation==='authorize'){
   if(v.approved!=='on')throw new Error('请确认此版本授权。');fields.permissions=Array.from(form.querySelectorAll('[name=permission]:checked'),x=>x.value);
  }else if(operation==='revoke'){actionName='extension.authorize';fields.permissions=[];}
  else if(operation==='rollback')fields.manifest_sha256=v.manifest_sha256;
  else if(operation==='call'){
   if(v.approved!=='on')throw new Error('请确认本次执行。');const assets=JSON.parse(v.assets),params=JSON.parse(v.params);
   if(!Array.isArray(assets)||!params||typeof params!=='object'||Array.isArray(params))throw new Error('输入需为 SHA 数组，参数需为 JSON 对象。');
   fields={id,project_id:ui.project,operation:v.operation,input:{assets:assets.map(registeredSHA),params}};
  }
  const r=await action(actionName,fields);await refresh();
  if(operation==='call')setTimeout(()=>modal('扩展实际产物',`${r.object_id?button('打开工坊成果','open-object',{id:r.object_id},'button primary'):''}<pre>${esc(pretty(r))}</pre>`,{wide:true}),0);
  else toast(['register','upgrade','rollback'].includes(operation)?'版本已登记，执行前需单独核对并授权。':'扩展状态已按服务器返回更新。');
 }});
 if(['register','upgrade'].includes(operation))dialog.root.querySelector('[name=manifest_file]').addEventListener('change',async e=>{try{const file=e.target.files[0];if(file){const value=JSON.parse(await file.text());dialog.root.querySelector('[name=manifest]').value=pretty(value);}}catch(error){dialog.root.querySelector('.form-error').textContent=errorMessage(error);}});
}
function quickSearch(){const dialog=modal('定位研究对象','<label class="field"><span>标题、分类、别名或标识</span><input id="quick-search-input" type="search" autofocus></label><div id="quick-results"></div>');const show=q=>{const hits=objects().filter(o=>objectSearchText(o).includes(q.toLowerCase())).slice(0,30);dialog.root.querySelector('#quick-results').innerHTML=hits.map(o=>`<button class="quick-result" data-action="open-object" data-id="${esc(o.id)}"><span>${esc(kinds[o.kind])}</span><strong>${esc(o.title)}</strong><small>${esc(o.id)}</small></button>`).join('');};show('');dialog.root.querySelector('#quick-search-input').addEventListener('input',e=>show(e.target.value));}

async function upload(file,metadata={},projectId=ui.project){return uploadAssetFile(file,metadata,projectId,action);}
function importAsset(mode='asset'){
 if(!ensureProject())return;
 const target=captureDocumentTarget(ui),workshopField=mode==='workshop'?document.querySelector('#workshop-form [name=inputs]'):null,workshopValue=workshopField?.value;
 modal(mode==='document'?'导入 Markdown 成果':'登记输入资产',`<label class="field"><span>选择授权使用的本机文件</span><input type="file" name="file" required ${mode==='document'?'accept=".md,.markdown,.txt"':''}></label>${select('输入来源类别','provenance',[['unverified_import','未核对来源的导入'],['authorized_real','已授权的真实研究材料'],['public_real','公开真实材料'],['synthetic','合成 / 工程试用材料']])}${field('可核对的来源说明','source')}${field('真实材料的授权或公开来源依据','authorization_reference')}${mode==='document'?`${field('成果标题（可留空采用文件名）','title')}${select('成果类型','kind',[['report','研究报告'],['note','研讨笔记'],['paper','论文']])}`:''}<p class="hint">文件作为不可变输入登记，原文件不改写。内容保留在本研究空间。</p><div id="asset-result"></div>`,{label:'上传并登记',submit:async(v,form)=>{
  const current=()=>documentTargetIsCurrent(ui,target)&&form.isConnected!==false&&(mode!=='workshop'||(workshopField?.isConnected!==false&&workshopField?.value===workshopValue));
  if(!current()){toast('原项目、稿件或表单已变化；未开始上传。');return false;}
  const file=form.querySelector('[name=file]').files[0];if(!file)throw new Error('请选择文件。');
  if(['authorized_real','public_real'].includes(v.provenance)&&(!v.source.trim()||!v.authorization_reference.trim()))throw new Error('真实来源登记需要来源说明与授权/公开依据；此登记仍不代表科学验收。');
  let receipt=null;
  try{
   const asset=await upload(file,{provenance:v.provenance,source:v.source||'user selected upload',authorization_reference:v.authorization_reference||undefined},target.project_id);
   receipt={sha:asset.sha,filename:file.name,project_id:target.project_id,object_id:target.object_id,outcome:'registered'};retainUploadReceipt(receipt);
   if(!current()){retainUploadReceipt({...receipt,outcome:'not_applied'});toast(`文件已登记到原项目 ${target.project_id}，未应用到已变化的稿件；可从上传回执找回。`);return false;}
   if(mode==='document'){
    const r=await action('object.import',{project_id:target.project_id,asset_sha:asset.sha,title:v.title||file.name,kind:v.kind});
    receipt={...receipt,imported_object_id:r.id||r.object?.id};retainUploadReceipt(receipt);
    if(!current()){toast('文稿已导入原项目；当前界面保留，结果身份保存在上传回执。');return false;}
    form.querySelector('#asset-result').innerHTML=`<div class="notice">文稿已导入原项目，当前稿件保持原样。</div>${button('打开导入成果','open-object',{id:receipt.imported_object_id},'button small')}`;return false;
   }
   if(mode==='workshop'){const inputs=JSON.parse(workshopValue);inputs.push({alias:file.name,sha:asset.sha});workshopField.value=pretty(inputs);}
   if(mode==='figure-input')mutate(o=>{o.content.input_assets||=[];if(Array.isArray(o.content.input_assets))o.content.input_assets.push({name:file.name,sha:asset.sha});else o.content.input_assets[file.name]=asset.sha;},true);
   if(mode==='figure-script')mutate(o=>o.content.script_asset=asset.sha,true);
   form.querySelector('#asset-result').innerHTML=`<div class="notice">已登记资产：${esc(file.name)}</div><pre>${esc(asset.sha)}</pre>`;return false;
  }catch(error){if(receipt)retainUploadReceipt({...receipt,outcome:'not_applied',error:error.message});if(!current()){toast(error.message,'error');return false;}throw error;}
 }});
}
function authorizeFigure(){const script=ui.draft?.content.script_asset;if(!script){toast('请先登记脚本资产并保存成果。');return;}modal('授权当前脚本执行',`<p>脚本资产：<code>${esc(script)}</code></p><p>服务端会以服务用户权限调用配置的科学 Python 环境；临时目录不是操作系统安全沙箱。仅在核对脚本来源与输入范围后授权。变更脚本需重新授权。</p><label class="check-field"><input type="checkbox" name="approved" required><span>我授权执行这一脚本及当前登记的输入</span></label>${field('授权范围与理由','reason','','textarea','required')}`,{label:'保存并授权此脚本',submit:async v=>{if(ui.dirty)await save();await action('object.authorize_code',{id:ui.object.id,expected_revision:ui.object.revision,approved:v.approved==='on',reason:v.reason});toast('服务端已记录此脚本授权；可显式运行重绘。');}});}
function applyInput(el){if(!ui.draft)return;const key=el.dataset.edit;if(!key)return;if(key==='figure-live-preview'){ui.figureLivePreview=el.checked;return;}const value=el.type==='number'?Number(el.value):el.value;if(key==='figure-select'){ui.selectedItem=value;ui.figureCmapScope='matching';draw();if(ui.dirty||figurePreviewController?.isBusy())scheduleFigurePreview();return;}if(key==='figure-cmap-scope'){ui.figureCmapScope=value;draw();return;}
  if(key==='manuscript-track-changes'){ui.trackChanges=el.checked;draw();return;}
  if(key==='manuscript-format'){ui.manuscriptFormat={...defaultManuscriptFormat,...ui.manuscriptFormat,[el.dataset.key]:el.type==='number'?Number(el.value):el.value};const page=document.querySelector('.manuscript-page');if(page){page.style.setProperty('--manuscript-font-size',ui.manuscriptFormat.font_size_pt+'pt');page.style.setProperty('--manuscript-line-spacing',ui.manuscriptFormat.line_spacing);page.style.setProperty('--manuscript-paragraph-spacing',ui.manuscriptFormat.paragraph_spacing_pt+'pt');page.style.fontFamily=ui.manuscriptFormat.font_family;}return;}
  if(key==='paper-source-mode'){if(!['structured','latex'].includes(value))return;mutate(o=>o.content.paper_source_mode=value,true);return;}
  if(key==='paper-latex'){mutate(o=>o.content.latex=String(value));return;}
  if(key==='block'){mutate(o=>{const b=o.content.blocks.find(b=>b.id===el.dataset.id);if(b)b.text=value;});ui.selectedBlock=el.dataset.id;el.style.height='auto';el.style.height=`${Math.max(54,el.scrollHeight)}px`;return;}
  if(key.startsWith('overlay-')){try{setFigureOverlay(key.slice(8),el.value);el.setCustomValidity('');}catch(error){el.setCustomValidity(error.message);}return;}
  if(key==='figure-parameters'||key==='figure-spec'){try{const parsed=JSON.parse(value);mutate(o=>o.content[key==='figure-spec'?'spec':'parameters']=parsed);el.setCustomValidity('');}catch{el.setCustomValidity('请输入有效 JSON；无效内容尚未写入草稿。');}return;}
  mutate(o=>{if(key==='page-notes')o.content.pages[ui.page].notes=value;
    else if(key.startsWith('page-')){const property=key.slice(5);o.content.pages[ui.page][property]=['width','height'].includes(property)?Math.max(.1,value):value;}
    else if(key.startsWith('item-')){const item=o.content.pages[ui.page]?.objects.find(x=>x.id===ui.selectedItem);if(item)item[key.slice(5)]=value;}
    else if(key.startsWith('node-')){const item=o.content.nodes?.find(x=>x.id===ui.selectedItem);if(item)item[key.slice(5)]=value;}

    else if(key==='figure-input_assets'){try{o.content.input_assets=JSON.parse(value);el.setCustomValidity('');}catch{o.content.input_assets=value.split('\n').filter(Boolean);}}
    else if(key.startsWith('literature-')){const property=key.slice(11);o.content[property]=property==='authors'?value.split('\n').filter(Boolean):value;if(property==='title')o.title=value;}
    else if(key.startsWith('figure-')){o.content[key.slice(7)]=value;if(['figure-script_asset','figure-spec'].includes(key)&&value)delete o.content.editable_source_available;}
  });
}

function rememberManuscriptSelection(){
 const selection=window.getSelection();if(!selection||selection.isCollapsed||!selection.rangeCount)return;
 const range=selection.getRangeAt(0),start=(range.startContainer.nodeType===1?range.startContainer:range.startContainer.parentElement)?.closest?.('.manuscript-block'),end=(range.endContainer.nodeType===1?range.endContainer:range.endContainer.parentElement)?.closest?.('.manuscript-block');
 if(!start||start!==end||!ui.object)return;const quote=selection.toString().slice(0,6000);if(!quote.trim())return;ui.selectedBlock=start.dataset.block;ui.textSelection={objectId:ui.object.id,blockId:start.dataset.block,quote};
}
for(const event of ['wheel','touchstart','pointerdown','keydown'])document.addEventListener(event,()=>{manuscriptReturn=null;pendingReadingRestore=null;readingLayoutToken++;},{passive:true});
document.addEventListener('mouseup',rememberManuscriptSelection);
document.addEventListener('keyup',rememberManuscriptSelection);
document.addEventListener('dblclick',e=>{const figure=e.target.closest('.manuscript-component.editable-figure');if(!figure||e.target.closest('button,a'))return;e.preventDefault();enterWorkbenchComponent(componentEntryData(figure)).catch(error=>toast(errorMessage(error),'error'));});
document.addEventListener('contextmenu',e=>{const figure=e.target.closest('.manuscript-component.editable-figure');if(!figure)return;e.preventDefault();modal('稿件中的图形',`${button('进入图形编辑','workbench-component',componentEntryData(figure),'button primary')}${!figure.dataset.componentIssue?button('查看稿件采用的版本','open-reference',{id:figure.dataset.componentId,revision:figure.dataset.componentRevision,...(figure.dataset.componentBlock?{block_id:figure.dataset.componentBlock}:{}),...(figure.dataset.componentSha?{sha256:figure.dataset.componentSha}:{})},'button'):'<p>采用来源身份需核对。</p>'}<p class="hint">编辑图形的当前版本；采用视觉改动会一并更新本稿此处引用，然后返回原稿继续阅读。</p>`);});
document.addEventListener('click',async e=>{
  // A prose link keeps its native navigation/download behavior even when its
  // containing paragraph has a selection action. Explicit action links still
  // use the delegated handler, including clicks on their nested text elements.
  const link=e.target.closest('a[href]');if(link&&!link.hasAttribute('data-action'))return;
  const target=e.target.closest('[data-action]');if(!target)return;const name=target.dataset.action;e.preventDefault();
  if(name==='import-asset'){importAsset(target.dataset.mode);return;}if(name==='figure-authorize'){authorizeFigure();return;}
  if(['open-object','workbench-component'].includes(name)&&target.closest('#modal-root'))document.querySelector('#modal-root').innerHTML='';
  target.disabled=true;try{await handle(name,target.dataset,e);}catch(error){if(!error.status)toast(errorMessage(error),'error');}finally{if(target.isConnected)target.disabled=false;}});
document.addEventListener('input',e=>{const el=e.target;if(el.dataset.overlayTuple){const key=el.dataset.overlayTuple,group=el.closest('[data-tuple]'),value=[...group.querySelectorAll('input')].map(x=>Number(x.value));if([...group.querySelectorAll('input')].some(x=>x.value===''||!Number.isFinite(Number(x.value))))return;try{setFigureOverlay(key,value);el.setCustomValidity('');}catch(error){el.setCustomValidity(error.message);}return;}if(el.id==='graph-search'){ui.graphSearch=el.value;clearTimeout(typingTimer);typingTimer=setTimeout(()=>{const position=el.selectionStart;draw();const next=document.querySelector('#graph-search');next?.focus();next?.setSelectionRange(position,position);},220);return;}if(el.dataset.edit){try{applyInput(el);}catch(error){toast(errorMessage(error),'error');}}});
document.addEventListener('change',e=>{const el=e.target;if(el.matches('#workshop-form [name=category]')){document.querySelector('#workshop-config-help').innerHTML=workshopHelp(el.value);const check=document.querySelector('#workshop-form [name=scientific_preprocessing]');check.required=workshopKey(el.value)==='neural';document.querySelectorAll('#workshop-form input[type=checkbox]').forEach(x=>x.checked=false);return;}if(el.id==='graph-domain'){ui.graphProjectRoot='';ui.graphDomain=el.value;ui.graphSearch='';ui.collapsed.clear();draw();return;}if(el.id==='graph-kind'){ui.graphKind=el.value;draw();return;}if(el.matches('select[data-edit]'))applyInput(el);else if(el.dataset.edit&&!['block','page-notes','figure-caption','paper-latex'].includes(el.dataset.edit)){if(!el.checkValidity()){el.reportValidity();return;}if(el.dataset.edit.startsWith('overlay-')||el.dataset.edit==='figure-live-preview')return;if((el.dataset.edit.startsWith('node-')||el.dataset.edit.startsWith('item-')||['page-width','page-height','page-title'].includes(el.dataset.edit))&&refreshEditorPreview())return;draw();}});
document.addEventListener('submit',async e=>{
  if(e.target.id!=='access-form')return;e.preventDefault();const form=e.target,input=form.elements.token,submit=e.submitter;submit.disabled=true;
  try{ui.auth=await login(input.value);input.value='';ui.authGate=false;const old=ui.object?.id;await refresh({render:false});if(old&&!objects().some(o=>o.id===old)){ui.object=null;ui.draft=null;ui.dirty=false;ui.project='';ui.view='projects';ui.references={};}await boot();}
  catch(error){input.value='';document.querySelector('#access-error').textContent=error.message;}
  finally{if(submit.isConnected)submit.disabled=false;}
});
document.addEventListener('submit',async e=>{if(!['workshop-form','literature-search'].includes(e.target.id))return;e.preventDefault();if(!ensureProject())return;const form=e.target,v=Object.fromEntries(new FormData(form)),btn=e.submitter;btn.disabled=true;
  try{if(form.id==='literature-search'){const result=await action('literature.search',{project_id:ui.project,query:v.query,limit:20});ui.literatureResults=list(result.records||result.results||result);draw();toast(ui.literatureResults.length?`检索返回 ${ui.literatureResults.length} 条记录；尚未自动加入项目。`:'本次检索没有返回记录。');}
    else{const selected=ui.workshop===false?null:ui.workshop||currentObjects().find(o=>o.kind==='workshop');if(isExtensionWorkshop(selected))throw new Error('扩展产物不能作为准备任务重新提交；请新建准备任务，或进入扩展设置重新指定输入。');const r=await action('workshop.submit',workshopRequest(v,ui.project,ui.workshopRequestKey));ui.workshopRequestKey=uid('workshop');await refresh({render:false});toast(`工坊任务已由服务端接收 · ${r.id||r.task?.id||''}`);ui.view='activity';ui.tab='tasks';draw();}}
  catch(error){if(form.id==='workshop-form'){const err=document.querySelector('#workshop-error');if(err)err.textContent=errorMessage(error);}else toast(errorMessage(error),'error');}finally{if(btn.isConnected)btn.disabled=false;}});
document.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)&&e.target.matches('g[data-action=graph-relation]')){e.preventDefault();handle('graph-relation',e.target.dataset).catch(error=>toast(errorMessage(error),'error'));return;}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'&&ui.view==='workspace'&&ui.object){e.preventDefault();save().catch(()=>{});}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'&&ui.view==='workspace'&&!document.querySelector('#modal-root').children.length){if(!e.target.matches('input,textarea')){e.preventDefault();handle(e.shiftKey?'redo':'undo');}}});
window.addEventListener('pagehide',()=>{rememberReadingPosition();persistWorkspaceDrafts();});
window.addEventListener('beforeunload',e=>{try{persistWorkspaceDrafts();}catch{e.preventDefault();e.returnValue='';}});
window.addEventListener('online',()=>refresh({render:false}));
async function boot(){try{ui.auth=await accessStatus();if(!ui.auth.authenticated){showAccess();return;}ui.authGate=false;}catch(error){ui.online=false;app.innerHTML=`<div class="startup"><h1>研究空间暂时无法连接</h1><p>${esc(error.message)}</p>${button('重新连接','refresh',{},'button primary')}</div>`;return;}try{await refresh({render:false});const requested=new URLSearchParams(location.search).get('object'),sourceEntry=requested?.startsWith('source:')&&desk.resolveAsset(requested)?{view:'asset',object:requested}:null;const navigation=sourceEntry||entryNavigation(location.search,objects())||JSON.parse(localStorage.getItem(desk.navigationKey())||(!desk.embedded?localStorage.getItem('research-partner:navigation'):'')||'null');if(navigation){ui.view=navigation.view||'projects';ui.project=navigation.project||'';ui.tab=navigation.tab||'tasks';await refresh({render:false});if(ui.project&&!projects().some(p=>p.id===ui.project))ui.project='';if(navigation.object&&['workspace','asset'].includes(ui.view)){try{await openObject(navigation.object);return;}catch{ui.view='projects';}}}}catch{}await refresh();}
await boot();
restoreComponentTrail();
await desk.restoreLayout().catch(error=>toast('分区恢复未完成：'+error.message,'error'));
setInterval(async()=>{if(document.hidden)return;await refresh({render:ui.view==='activity'&&!document.querySelector('#modal-root').children.length&&!document.activeElement?.matches('input,textarea,select')});if(ui.view==='workspace'&&ui.workspacePanel==='review'&&manuscriptReviewController&&!manuscriptReviewController.isBusy()&&!document.querySelector('#modal-root').children.length){try{await manuscriptReviewController.load();}catch{}}},8000);

async function reviseCandidate(id){
 const task=await api('/api/tasks/'+encodeURIComponent(id));
 if(!canReviseCandidate(task))throw new Error('该任务当前没有等待修订的旧候选。');
 const decisions=list(task.input_decisions).map(q=>`<article><strong>${esc(q.title)} · r${esc(q.revision)}</strong><p>${esc(q.content.answer)}</p>${status(q.content.disposition)}</article>`).join('');
 const guidance=list(task.input_guidance).map(g=>`<article><strong>指导 ${esc(g.seq)}</strong><p>${esc(g.data.text)}</p></article>`).join('');
 modal('按当前回答修订候选',`<p>旧候选及其来源记录会保留。修订将继续同一任务，可能调用模型并消耗原任务剩余额度；不会增加费用额度、科学或工具权限。</p><p>${esc(task.payload.request)}</p><h3>本次将读取的回答与指导</h3>${decisions}${guidance}`,{label:'使用既定剩余额度修订',submit:async()=>{await action('task.revise_candidate',{id,approved:true,input_snapshot:task.input_snapshot});await refresh();toast('已登记一次候选修订，执行与额度状态见任务记录。');}});
}

async function reviseFailedChild(id,child){
 const view=await action('cycle.view',{id});
 const current=list(view.children).find(c=>c.id===child);
 if(!current?.failed_child_revision?.allowed)throw new Error(current?.failed_child_revision?.reason||'当前不能接续此规划。');
 const submission=failedChildRevisionSubmission({id,childId:child,action,requestKey:uid('planner-revision'),saved:async()=>{await refresh();toast('原规划修订已登记，沿用原会话与剩余额度。');}});
 modal('修订原失败规划',failedChildRevisionFields(current),{label:'核对本次修订',submit:submission,wide:true});
}

document.addEventListener('input',e=>{if(e.target.matches('[data-note-block]')){article.noteInput(e.target);desk.publish();}});

function scheduleManuscriptRender(){
 if(!ui.object||ui.dirty||!['paper','report','note','workshop_note'].includes(ui.object.kind))return;
 const id=ui.object.id,revision=ui.object.revision,key=id+'@'+revision;
 if(ui.mathLoading===key||ui.renderedMath?.object_id===id&&ui.renderedMath?.revision===revision)return;
 ui.mathLoading=key;
 action('manuscript.render',{object_id:id,expected_revision:revision},{notifyError:false}).then(result=>{
  if(ui.object?.id===id&&ui.object.revision===revision){ui.renderedMath=result;ui.mathLoading='';if(!document.activeElement?.matches('textarea,input'))draw();}
 }).catch(error=>{if(ui.object?.id===id&&ui.object.revision===revision){ui.renderedMath={object_id:id,revision,math:{},failures:[{error:error.message}]};ui.mathLoading='';}});
}
