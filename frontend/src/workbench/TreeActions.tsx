import React,{createContext,useContext,useEffect,useRef,useState} from 'react';
import * as Menu from '@radix-ui/react-context-menu';
import * as Dropdown from '@radix-ui/react-dropdown-menu';
import {Copy,Plus,Trash2,Pencil,RotateCcw,NotebookPen,FileCode,Microscope,FileText,X} from 'lucide-react';
import {get,del} from 'idb-keyval';
import {WorkbenchContext,type ViewSpec} from './context';
import {command,noteCommand,requestId} from '../api';
import {editorDraftKey} from '../documents/drafts';
import {Modal} from './Modal';
import {errorText} from './useManuscript';
export type TreeItem={id:string;name:string;number?:string;path?:string;view?:ViewSpec;children?:TreeItem[];status?:string;sourceFormat?:string};
type Intent={kind:'note'|'script'|'question'|'delivery'|'root'|'readonly';folder:string;parent?:string;reason?:string};
type Undo={kind:'note'|'script'|'object';trash_id?:string;id?:string;revision?:number;name:string;path?:string};
type NoteRecord={path:string;sha:string;dirty:boolean};
type ScriptDraft={text:string;base:string;before:string};
type Panel={kind:string;item?:TreeItem;intent?:Intent;path?:string;notes?:NoteRecord[];script?:any;draft?:ScriptDraft;object?:any;links?:any;trash?:Undo[]};
type Actions={selected:TreeItem|null;writable:boolean;intent:(item?:TreeItem|null)=>Intent;create:(item?:TreeItem|null)=>void;createKind:(kind:'note'|'script'|'question'|'docx'|'latex')=>void;copy:(item:TreeItem,name?:boolean)=>void;remove:(item:TreeItem)=>void;rename:(item:TreeItem)=>void;trash:()=>void;canRemove:(item:TreeItem)=>boolean;reason:(item:TreeItem)=>string;dialogPending:React.RefObject<boolean>;clearSelection:()=>void};
const ActionsContext=createContext<Actions|null>(null);
const directory=(path:string)=>path.includes('/')?path.slice(0,path.lastIndexOf('/')):'';
const basename=(path:string)=>path.split('/').at(-1)||path;
function pathOf(item:TreeItem){return item.path||(item.view?.kind==='script'?'scripts/'+item.view.value:item.view?.value)||({'notes-root':'notes','research-root':'研究','delivery-root':'交付'} as Record<string,string>)[item.id]||item.name;}
export function TreeActionsProvider({selected,clearSelection,children}:{selected:TreeItem|null;clearSelection:()=>void;children:React.ReactNode}){
 const c=useContext(WorkbenchContext)!,project=c.project?.id,writable=!!project&&c.catalog.project_management.writable_project_ids.includes(project);
 const [panel,setPanel]=useState<Panel|null>(null),[name,setName]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false),[notice,setNotice]=useState<{text:string;undo?:Undo[]}|null>(null);
 const cancelButton=useRef<HTMLButtonElement>(null);
 useEffect(()=>{if(panel?.kind.startsWith('delete-'))cancelButton.current?.focus();},[panel?.kind]);
 const alive=useRef(true),epoch=useRef(0),locked=useRef(false),dialogPending=useRef(false),returnTo=useRef<HTMLElement|null>(null);
 useEffect(()=>()=>{alive.current=false;},[]);
 const close=()=>{if(locked.current)return;epoch.current++;dialogPending.current=false;setPanel(null);setError('');requestAnimationFrame(()=>{const active=document.activeElement;if(active&&active!==document.body&&active.isConnected&&!active.closest('dialog'))return;const prior=returnTo.current;if(prior?.isConnected)prior.focus();else document.querySelector<HTMLElement>('.wb-tree [role=tree]')?.focus();});};
 function show(value:Panel){dialogPending.current=true;returnTo.current=document.querySelector<HTMLElement>('.wb-tree [role=treeitem][aria-selected=true]')||(document.activeElement as HTMLElement|null);setError('');setName('');setPanel(value);}
 async function run(operation:()=>Promise<void>){if(locked.current)return;locked.current=true;setBusy(true);setError('');try{await operation();}catch(e){if(alive.current){setError(errorText(e));if(!panel)c.report(e);}}finally{locked.current=false;if(alive.current)setBusy(false);}}
 function finish(){if(!alive.current)return;locked.current=false;close();}
 function intent(item?:TreeItem|null):Intent{
  if(!item)return {kind:'root',folder:'当前项目'};
  if(item.id==='research-root'||item.view?.kind==='question')return {kind:'question',folder:item.view?.kind==='question'?item.name:'研究',parent:item.view?.kind==='question'?item.id:undefined};
  if(item.id==='delivery-root'||['docx','latex','paper'].includes(item.view?.kind||''))return {kind:'delivery',folder:'交付'};
  const path=pathOf(item),folder=item.children?path:directory(path);
  if(item.id==='notes-root'||folder==='notes'||folder.startsWith('notes/'))return {kind:'note',folder:item.id==='notes-root'?'notes':folder};
  if(folder==='scripts'&&(!item.children||path==='scripts'))return {kind:'script',folder:'scripts'};
  return {kind:'readonly',folder:path,reason:'此位置是登记内容的只读投影，不能直接新建或删除。'};
 }
 function beginCreate(target:Intent){if(!writable)return;if(target.kind==='question'){c.createQuestion(target.parent);return;}if(target.kind==='note'||target.kind==='script')show({kind:'create',intent:target});}
 function create(item?:TreeItem|null){beginCreate(intent(item));}
 function createKind(kind:'note'|'script'|'question'|'docx'|'latex'){
  if(kind==='docx'||kind==='latex'){c.manuscript.create(kind);c.openDocument(kind,true);return;}
  beginCreate({kind,folder:kind==='note'?'notes':kind==='script'?'scripts':'研究'});
 }
 async function copy(item:TreeItem,onlyName=false){const text=onlyName?item.name:item.view?.kind==='question'?item.id:pathOf(item);try{await navigator.clipboard.writeText(text);setNotice({text:onlyName?'已复制名称':'已复制'+(item.view?.kind==='question'?'问题 ID':'项目相对路径')});}catch{show({kind:'copy',path:text});}}
 function canRemove(item:TreeItem){if(!writable)return false;const v=item.view,path=pathOf(item);return v?.kind==='note'||v?.kind==='script'||v?.kind==='question'||!!item.children&&path.startsWith('notes/')||v?.kind==='object'&&c.catalog.objects.some(o=>o.id===v.id&&o.kind==='presentation'&&o.id!==c.manuscript.doc?.id);}
 function reason(item:TreeItem){if(!writable)return '当前项目只读';if(['paper','docx','latex'].includes(item.view?.kind||''))return '论文是项目默认交付，不能从目录删除。';return '系统目录和登记快照由来源对象维护，不能直接删除。';}
 async function prepareRemove(item:TreeItem){if(!canRemove(item))return;const turn=++epoch.current;show({kind:'loading',item});try{
  const v=item.view,path=pathOf(item);
  if(v?.kind==='note'||item.children&&path.startsWith('notes/')){
   const paths=v?.kind==='note'?[v.value!]:((await noteCommand('notes.list',project,{folder:'notes',include_trash:false})).entries||[]).filter((e:any)=>e.relative_path?.startsWith(path+'/')&&e.relative_path.endsWith('.md')&&e.kind!=='directory').map((e:any)=>e.relative_path);
   const records:NoteRecord[]=[];for(const path of paths){const saved=await noteCommand('notes.read',project,{relative_path:path});records.push({path,sha:saved.content_sha256,dirty:!!c.session?.buffers.get(path)?.dirty});}
   if(alive.current&&turn===epoch.current)setPanel({kind:'delete-note',item,notes:records});
  }else if(v?.kind==='script'){
   await c.flushFile(v.id);const [saved,draft]=await Promise.all([command('recipe.script.read',{project_id:project,payload:{filename:v.value}}),editorDraftKey('script:'+project+':'+v.value).then(key=>get<ScriptDraft>(key))]);
   if(alive.current&&turn===epoch.current)setPanel({kind:'delete-script',item,script:saved,draft});
  }else{
   const response=await fetch('/api/objects/'+encodeURIComponent(v!.id));const body=await response.json();if(!response.ok||!body.ok)throw new Error(body.error||'内容无法读取');if(body.result.project_id!==project)throw new Error('内容不属于当前项目');if(alive.current&&turn===epoch.current)setPanel({kind:'delete-object',item,object:body.result});
  }
 }catch(e){if(alive.current&&turn===epoch.current){setPanel({kind:'failure',item});setError(errorText(e));}}}
 async function prepareRename(item:TreeItem){const turn=++epoch.current;show({kind:'loading',item});try{const saved=await noteCommand('notes.read',project,{relative_path:item.view!.value});if(alive.current&&turn===epoch.current){setName(basename(item.view!.value!));setPanel({kind:'rename',item,notes:[{path:item.view!.value!,sha:saved.content_sha256,dirty:!!c.session?.buffers.get(item.view!.value!)?.dirty}]});}}catch(e){if(alive.current&&turn===epoch.current){setPanel({kind:'failure',item});setError(errorText(e));}}}
 function assertCurrent(){if(!alive.current)throw new Error('项目已切换，操作结果保留在原项目。');}
 function closeView(id:string){assertCurrent();const found=c.api?.getPanel(id);if(found)c.api?.removePanel(found);}
 async function refresh(){assertCurrent();await Promise.all([c.session?.refresh(),c.manuscript.refreshFiles()]);assertCurrent();}
 function reveal(path:string){requestAnimationFrame(()=>document.dispatchEvent(new CustomEvent('wb-tree-reveal',{detail:path})));}
 async function restore(item:Undo){await run(async()=>{
  if(item.kind==='note'){const result=await noteCommand('notes.restore',project,{trash_id:item.trash_id});c.session?.fileOperation(result.desk_revisions);await c.session?.refresh();}
  else if(item.kind==='script')await command('recipe.script.restore',{project_id:project,request_id:requestId(),payload:{trash_id:item.trash_id}});
  else {await command('object.save',{id:item.id,expected_revision:item.revision,archived:false});await Promise.all([c.refreshResearch(),c.refresh()]);}
  await refresh();setNotice({text:'已恢复 '+item.name});if(panel?.kind==='trash')await loadTrash();
 });}
 async function loadTrash(){const turn=++epoch.current;show({kind:'loading'});try{const [notes,scripts,state]=await Promise.all([noteCommand('notes.trash.list',project,{}),command('recipe.script.trash.list',{project_id:project,payload:{}}),fetch('/api/state',{cache:'no-store'}).then(async response=>{const value=await response.json();if(!response.ok)throw new Error(value.error||'归档内容无法读取');return value;})]);if(alive.current&&turn===epoch.current)setPanel({kind:'trash',trash:[...notes.items.map((n:any)=>({kind:'note',trash_id:n.trash_id,name:n.relative_path})),...scripts.items.map((n:any)=>({kind:'script',trash_id:n.trash_id,name:'scripts/'+n.filename})),...state.objects.filter((o:any)=>o.project_id===project&&o.archived&&(o.metadata?.research_role==='research_question_v1'||o.kind==='presentation')).map((o:any)=>({kind:'object',id:o.id,revision:o.revision,name:'研究 / '+o.title}))]});}catch(e){if(alive.current&&turn===epoch.current){setPanel({kind:'failure'});setError(errorText(e));}}}
 async function submit(e:React.FormEvent){e.preventDefault();if(!panel)return;await run(async()=>{
  if(panel.kind==='create'){
   const base=name.trim();if(!base||base.startsWith('/')||/[\\\u0000]/.test(base)||base.split('/').some(p=>!p||p==='.'||p==='..'))throw new Error('请输入当前目录中的有效名称或子目录路径。');
   if(panel.intent!.kind==='note'){const file=base.endsWith('.md')?base:base+'.md',path=panel.intent!.folder+'/'+file;await noteCommand('notes.create',project,{relative_path:path,markdown:'# '+basename(file).replace(/\.md$/,'')+'\n\n',if_absent:true});await refresh();c.open({id:'note:'+path,kind:'note',title:basename(path),value:path,data:{edit:true}},true);reveal(path);}
   else {const filename=base.endsWith('.py')?base:base+'.py';if(filename.includes('/'))throw new Error('Python 工作副本目前放在 scripts/ 直属目录。');await command('recipe.script.write',{project_id:project,request_id:requestId(),payload:{filename,code:'# '+filename+'\n',expected_sha256:null}});await refresh();c.open({id:'script:'+filename,kind:'script',title:filename,value:filename,data:{edit:true}},true);reveal('scripts/'+filename);}
   finish();
  }else if(panel.kind==='rename'){
   const old=panel.notes![0],base=name.trim();if(!base||base.includes('/')||/[\\\u0000]/.test(base)||base==='.'||base==='..')throw new Error('请输入文件名称。');const path=directory(old.path)+'/'+(base.endsWith('.md')?base:base+'.md');
   if(old.dirty)throw new Error('笔记有未保存草稿，请先在编辑器保存或处理版本冲突后重命名。');
   if(!panel.links){const inspection=await noteCommand('notes.move.inspect',project,{relative_path:old.path,new_path:path,expected_content_sha256:old.sha});if(inspection.links.incoming.length||inspection.links.outgoing.length){setPanel({...panel,path,links:inspection.links});return;}}
   const result=await noteCommand('notes.move',project,{relative_path:old.path,new_path:panel.path||path,expected_content_sha256:old.sha,links_reviewed:true});c.session?.moved(old.path,result.relative_path,result.desk_revisions);closeView('note:'+old.path);await refresh();c.openNote(result.relative_path,true);reveal(result.relative_path);setNotice({text:'已重命名笔记'});finish();
  }else if(panel.kind==='delete-note'){
   const undone:Undo[]=[];try{for(const record of panel.notes!){let sha=record.sha;if(c.session?.buffers.get(record.path)?.dirty){await c.session.save(record.path);sha=c.session.buffers.get(record.path)!.base;}
    const result=await noteCommand('notes.trash',project,{relative_path:record.path,expected_content_sha256:sha});c.session?.trashed(record.path,result.desk_revisions);closeView('note:'+record.path);undone.push({kind:'note',trash_id:result.trash_id,name:record.path});}
   }catch(e){throw new Error((undone.length?'已移入回收站 '+undone.length+' 篇，其余文件未删除。':'')+errorText(e));}finally{clearSelection();await refresh();await c.session?.flush();if(undone.length)setNotice({text:'已将 '+undone.length+' 篇笔记移到回收站',undo:undone});}
   finish();
  }else if(panel.kind==='delete-script'){
   const filename=panel.item!.view!.value!;let sha=panel.script.sha256;
   if(panel.draft&&panel.draft.text!==panel.draft.before){const saved=await command('recipe.script.write',{project_id:project,request_id:requestId(),payload:{filename,code:panel.draft.text,expected_sha256:panel.draft.base}});sha=saved.sha256;}
   const result=await command('recipe.script.trash',{project_id:project,request_id:requestId(),payload:{filename,expected_sha256:sha}});await c.flushFile(panel.item!.view!.id);closeView(panel.item!.view!.id);await new Promise<void>(r=>requestAnimationFrame(()=>r()));await del(await editorDraftKey('script:'+project+':'+filename));clearSelection();await refresh();setNotice({text:'已将脚本移到回收站',undo:[{kind:'script',trash_id:result.trash_id,name:'scripts/'+filename}]});finish();
  }else if(panel.kind==='delete-object'){
   const result=await command('object.archive',{id:panel.object.id,expected_revision:panel.object.revision});closeView(panel.item!.view!.id);await Promise.all([c.refreshResearch(),c.refresh()]);clearSelection();setNotice({text:'已归档 '+panel.item!.name,undo:[{kind:'object',id:result.id,revision:result.revision,name:result.title}]});finish();
  }
 });}
 const a:Actions={selected,writable,intent,create,createKind,copy:(item,name)=>void copy(item,name),remove:item=>void prepareRemove(item),rename:item=>void prepareRename(item),trash:()=>void loadTrash(),canRemove,reason,dialogPending,clearSelection};
 const isDelete=panel?.kind.startsWith('delete-'),dirty=panel?.notes?.some(n=>n.dirty)||panel?.draft&&panel.draft.text!==panel.draft.before;
 const title=panel?.kind==='create'?(panel.intent?.kind==='script'?'新建 Python 脚本':'新建笔记'):panel?.kind==='rename'?'重命名笔记':isDelete?'删除 '+panel?.item?.name:panel?.kind==='trash'?'回收站':panel?.kind==='copy'?'复制路径':'读取内容';
 return <ActionsContext.Provider value={a}>{children}{notice&&<div className="wb-tree-notice" role="status"><span>{notice.text}</span>{notice.undo?.length===1&&<button disabled={busy||!writable} onClick={()=>void restore(notice.undo![0])}>撤销</button>}{notice.undo&&notice.undo.length>1&&<button disabled={busy||!writable} onClick={()=>void loadTrash()}>打开回收站</button>}<button aria-label="关闭通知" onClick={()=>setNotice(null)}><X/></button></div>}{panel&&<Modal title={title} close={close} busy={busy}><form className="wb-form" onSubmit={submit}>
  {error&&<p className="native-alert" role="alert">{error}</p>}
  {panel.kind==='loading'&&<p role="status">正在读取当前保存版…</p>}
  {panel.kind==='copy'&&<><p>剪贴板不可用，请选中后复制。</p><input aria-label="路径" readOnly autoFocus value={panel.path||''} onFocus={e=>e.currentTarget.select()}/></>}
  {(panel.kind==='create'||panel.kind==='rename')&&<><p className="runtime-caption">位置：{panel.intent?.folder||directory(panel.notes![0].path)}/</p><input aria-label="名称" autoFocus required value={name} disabled={busy||!!panel.links} onChange={e=>setName(e.target.value)}/></>}
  {panel.links&&<p>发现 {panel.links.incoming.length} 处指向此笔记的链接、{panel.links.outgoing.length} 处相对链接可能受影响。正文链接不会自动改写；确认已检查后继续。</p>}
  {isDelete&&<><p>{panel.kind==='delete-object'?'此内容将归档，可撤销。子问题与历史修订保留。':panel.kind==='delete-note'?(panel.notes?.length||0)+' 篇笔记将移到回收站，可恢复。':'Python 工作副本将移到回收站；已登记的源码快照与研究结果保留。'}</p>{dirty&&<p>未保存修改会先保存，再一同移入回收站；保存冲突时停止删除。</p>}</>}
  {panel.kind==='trash'&&<div className="wb-trash-list">{panel.trash?.length?panel.trash.map(t=><div key={t.kind+(t.trash_id||t.id)}><span title={t.name}>{t.name}</span><button type="button" className="button quiet" disabled={busy} aria-label={'恢复 '+t.name} onClick={()=>void restore(t)}><RotateCcw/>恢复</button></div>):<p>回收站为空。</p>}</div>}
  <div className="wb-form-actions"><button ref={cancelButton} type="button" className="button quiet" disabled={busy} autoFocus={!!isDelete} onClick={close}>{panel.kind==='trash'||panel.kind==='copy'||panel.kind==='failure'?'关闭':'取消'}</button>{(panel.kind==='create'||panel.kind==='rename'||isDelete)&&<button type="submit" className={'button '+(isDelete?'danger':'primary')} disabled={busy||panel.kind==='delete-note'&&!panel.notes?.length}>{busy?'处理中…':panel.kind==='create'?'新建':panel.kind==='rename'?(panel.links?'确认重命名':'重命名'):panel.kind==='delete-object'?'归档':dirty?'保存并移到回收站':'移到回收站'}</button>}</div>
 </form></Modal>}</ActionsContext.Provider>;
}
function NewChoices({Item,item}:{Item:any;item?:TreeItem|null}){const a=useContext(ActionsContext)!,c=useContext(WorkbenchContext)!,target=a.intent(item);if(target.kind==='readonly')return <Item disabled><Plus/>新建内容…</Item>;
 if(['note','script','question'].includes(target.kind))return <Item disabled={!a.writable} onSelect={()=>a.create(item)}><Plus/>{target.kind==='note'?'新建笔记…':target.kind==='script'?'新建 Python 脚本…':target.parent?'新建子问题…':'新建研究问题…'}</Item>;
 if(target.kind==='delivery')return <>{(['docx','latex'] as const).map(kind=><Item key={kind} disabled={!a.writable||c.manuscript.has(kind)} onSelect={()=>a.createKind(kind)}><FileText/>{c.manuscript.has(kind)?'已有 ':'添加 '}{kind==='docx'?'DOCX':'LaTeX'} 源稿</Item>)}</>;
 return <><Item disabled={!a.writable} onSelect={()=>a.createKind('question')}><Microscope/>研究问题 · 研究</Item><Item disabled={!a.writable} onSelect={()=>a.createKind('note')}><NotebookPen/>笔记 · notes/</Item><Item disabled={!a.writable} onSelect={()=>a.createKind('script')}><FileCode/>Python 脚本 · scripts/</Item>{(['docx','latex'] as const).map(kind=><Item key={kind} disabled={!a.writable||c.manuscript.has(kind)} onSelect={()=>a.createKind(kind)}><FileText/>{c.manuscript.has(kind)?'已有 ':'添加 '}{kind==='docx'?'DOCX':'LaTeX'} 源稿</Item>)}</>;
}
function NodeItems({item}:{item:TreeItem}){const a=useContext(ActionsContext)!,c=useContext(WorkbenchContext)!;return <><Menu.Label title={pathOf(item)}>{pathOf(item)}</Menu.Label>{item.view&&<Menu.Item onSelect={()=>c.open(item.view!,true)}><FileText/>打开</Menu.Item>}<NewChoices Item={Menu.Item} item={item}/><Menu.Separator/><Menu.Item onSelect={()=>a.copy(item)}><Copy/>{item.view?.kind==='question'?'复制问题 ID':'复制路径'}</Menu.Item><Menu.Item onSelect={()=>a.copy(item,true)}><Copy/>复制名称</Menu.Item>{item.view?.kind==='note'&&<Menu.Item disabled={!a.writable} onSelect={()=>a.rename(item)}><Pencil/>重命名…</Menu.Item>}<Menu.Separator/><Menu.Item className="danger" disabled={!a.canRemove(item)} onSelect={()=>a.remove(item)}><Trash2/>删除…</Menu.Item>{!a.canRemove(item)&&<Menu.Label className="wb-tree-menu-reason">{a.reason(item)}</Menu.Label>}<Menu.Item disabled={!a.writable} onSelect={a.trash}><RotateCcw/>回收站</Menu.Item></>;}
export function TreeNodeMenu({item,select,children}:{item:TreeItem;select:()=>void;children:React.ReactElement}){const a=useContext(ActionsContext)!;return <Menu.Root onOpenChange={open=>{if(open)select();}}><Menu.Trigger asChild onContextMenu={e=>e.stopPropagation()}>{children}</Menu.Trigger><Menu.Portal><Menu.Content className="wb-tree-menu" collisionPadding={8} onEscapeKeyDown={e=>e.stopPropagation()} onCloseAutoFocus={e=>{if(a.dialogPending.current)e.preventDefault();}}><NodeItems item={item}/></Menu.Content></Menu.Portal></Menu.Root>;}
export function TreeEmptyMenu({children}:{children:React.ReactElement}){const a=useContext(ActionsContext)!;return <Menu.Root onOpenChange={open=>{if(open)a.clearSelection();}}><Menu.Trigger asChild onContextMenu={a.clearSelection}>{children}</Menu.Trigger><Menu.Portal><Menu.Content className="wb-tree-menu" collisionPadding={8} onEscapeKeyDown={e=>e.stopPropagation()} onCloseAutoFocus={e=>{if(a.dialogPending.current)e.preventDefault();}}><Menu.Label>当前项目</Menu.Label><NewChoices Item={Menu.Item}/><Menu.Separator/><Menu.Item disabled={!a.writable} onSelect={a.trash}><RotateCcw/>回收站</Menu.Item></Menu.Content></Menu.Portal></Menu.Root>;}
export function TreeNewButton(){const a=useContext(ActionsContext)!,target=a.intent(a.selected);if(['note','script','question'].includes(target.kind))return <button className="icon-button sidebar-tool" aria-label="新建" title={'在 '+target.folder+' 新建内容'} disabled={!a.writable} onClick={()=>a.create(a.selected)}><Plus/></button>;return <Dropdown.Root><Dropdown.Trigger asChild><button className="icon-button sidebar-tool" aria-label="新建" title={'新建到：'+target.folder}><Plus/></button></Dropdown.Trigger><Dropdown.Portal><Dropdown.Content className="wb-tree-menu" align="end" sideOffset={4} collisionPadding={8} onEscapeKeyDown={e=>e.stopPropagation()} onCloseAutoFocus={e=>{if(a.dialogPending.current)e.preventDefault();}}><Dropdown.Label>位置：{target.folder}</Dropdown.Label><NewChoices Item={Dropdown.Item} item={a.selected}/>{target.kind==='readonly'&&<Dropdown.Label>{target.reason}</Dropdown.Label>}</Dropdown.Content></Dropdown.Portal></Dropdown.Root>;}
