import { command, noteCommand } from './api';
import type {NativeNoteRef} from './NativeNoteReference';
import {persistentFigurePanelMemory,type FigurePanelMemory} from './figureViewMemory';
const canonicalSource=(value:any):string=>JSON.stringify((function ordered(x:any):any{return Array.isArray(x)?x.map(ordered):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,ordered(x[k])])):x;})(value));
export function manuscriptTextWrite(blocks:any[],savedBlocks:any[]):any[]{
  // The editor keeps complete source nodes. The existing text-write protocol
  // preserves saved metadata server-side and does not authorize editing it.
  const fields=new Set(['id','kind','text','level']),saved=new Map(savedBlocks.map(block=>[block.id,block]));
  return blocks.map(block=>{
    const original=saved.get(block.id);
    for(const [key,value] of Object.entries(block))if(!fields.has(key)&&(!original||!Object.hasOwn(original,key)||canonicalSource(value)!==canonicalSource(original[key])))
      throw new Error('段落含文字保存无法保持的附加字段；当前草稿保留，请先核对来源。');
    return Object.fromEntries(Object.entries(block).filter(([key])=>fields.has(key)));
  });
}
export type Buffer = {id?:string,path:string,text:string,base:string,revision:number,dirty:boolean,outline:any[],savedLength?:number,conflict?:string};
export type ManuscriptCaptionEdit={index:number,component_id:string,component_revision:number,before:string,text:string};
export function manuscriptCaptionWrite(edits:ManuscriptCaptionEdit[],components:any[]):ManuscriptCaptionEdit[]{
  const seen=new Set<number>();
  for(const edit of edits){
    const ref=components[edit.index];
    if(Object.keys(edit).sort().join(',')!=='before,component_id,component_revision,index,text'||
      !Number.isSafeInteger(edit.index)||edit.index<0||seen.has(edit.index)||!ref||
      (ref.id||ref.object_id)!==edit.component_id||!Number.isSafeInteger(edit.component_revision)||ref.revision!==edit.component_revision||
      typeof edit.text!=='string'||typeof edit.before!=='string'||ref.caption!==edit.before)
      throw new Error('保存版图注或所在位置已变化；当前正文和图注草稿保留。');
    seen.add(edit.index);
  }
  return structuredClone(edits.filter(edit=>edit.text!==edit.before));
}
export class Session {
  buffers=new Map<string,Buffer>(); listeners=new Set<()=>void>(); version=0;
  fileBusy=new Set<string>();
  retryingSync=false;
  private syncRetry:Promise<void>|null=null;
  draftRevision=0; layoutRevision=0; persisted=false; error=''; entries:any[]=[]; navigation:any={favorites:[],recent:[]}; paper:any=null; render:any=null;
  paperDraft:{base:number,blocks:any[],dirty:boolean,title?:string,captions?:ManuscriptCaptionEdit[]}|null=null; contentEpoch=0;
  reviewState:any=null; reviewView:any=null;
  // Successful decisions invalidate only the changed current figures. Fixed
  // references and unsaved buffers keep their own identities and bytes.
  figureWriteRevisions:Record<string,number>={};
  reviewComposer:{text?:string,request?:string,block?:string,anchor?:any,dependencyGroups?:{id:string,opinion_ids:string[]}[],slotAdoptions?:{main_opinion_id:string,slot_id:string,leaf_opinion_id:string}[]}={};
  paperReadSequence=0;
  assets:any[]=[]; opening:string|null=null;
  activePath='notes/inbox.md';
  activeView='';
  locations:Record<string,any>={};
  viewLocations:Record<string,Record<string,any>>={};
  private figurePanelMemories=new Map<string,FigurePanelMemory>();
  figurePanelMemory(panelId:string):FigurePanelMemory{
    let memory=this.figurePanelMemories.get(panelId);
    if(!memory){
      const key='figure-camera:'+panelId,projectId=this.project.id;
      memory=persistentFigurePanelMemory(projectId,this.views[key],value=>{
        if(this.project.id===projectId&&this.figurePanelMemories.get(panelId)===memory)this.position(key,value);
      });
      this.figurePanelMemories.set(panelId,memory);
    }
    return memory;
  }
  figureDrafts:Record<string,{base:number,overlays:any[]}>={};
  compositionDrafts:Record<string,{base:number,sha:string,slot:string,box:number[]}|{base:number,sha:string,slots:{id:string,box:number[]}[]}>={};
  captionDrafts:Record<string,any>={};
  reviewNoteRefs:NativeNoteRef[]=[];
  generationLayouts:Record<string,Record<string,{x:number,y:number}>>={};
  viewTimer:ReturnType<typeof setTimeout>|undefined;
  timer:ReturnType<typeof setTimeout>|undefined; pending:Promise<void>=Promise.resolve(); layout:any=null; views:Record<string,any>={};
  constructor(public project:any) {}
  subscribe=(fn:()=>void)=>{this.listeners.add(fn);return()=>{this.listeners.delete(fn);}};
  snapshot=()=>this.version;
  notify(){this.version++;for(const fn of this.listeners)fn();}
  async load(){
    const [draft,layout,paper]=await Promise.all(['drafts','layout','paper'].map(n=>command(`desk.${n}.read`,{project_id:this.project.id})));
    this.draftRevision=draft.revision;this.layoutRevision=layout.revision;this.layout=layout.value.layout;this.views=layout.value.views||{};
    this.figurePanelMemories.clear();
    this.activePath=layout.value.active_path||'notes/inbox.md';
    this.activeView=layout.value.active_view||'';
    this.locations=layout.value.locations||{};
    this.viewLocations=layout.value.view_locations||{};
    this.generationLayouts=layout.value.generation_layouts||{};
    this.paper=paper.object;this.render=paper.render;
    this.paperDraft=draft.value.manuscript||{base:this.paper.revision,blocks:structuredClone(this.paper.content.blocks),dirty:false};
    if(!this.paperDraft!.dirty&&(this.paperDraft!.base!==this.paper.revision||canonicalSource(this.paperDraft!.blocks)!==canonicalSource(this.paper.content.blocks)))this.resetPaperDraft();
    this.figureDrafts=draft.value.figure_drafts||{};
    this.compositionDrafts=draft.value.composition_drafts||{};
    this.captionDrafts=draft.value.caption_drafts||{};
    this.reviewNoteRefs=draft.value.review_note_refs||[];
    this.reviewComposer=draft.value.review_composer||{};
    this.persisted=true;
    for(const [path,b] of Object.entries(draft.value.buffers||{})) this.buffers.set(path,b as Buffer);
    await this.refresh();this.notify();
  }
  async refresh(){
    const navigationVersion=this.navigationVersion,navigationIdle=this.navigationPending===0;
    const [files,nav,assets]=await Promise.all([noteCommand('notes.list',this.project.id,{folder:'notes',include_trash:false}),noteCommand('notes.navigation',this.project.id,{op:'get'}),command('desk.assets.list',{project_id:this.project.id})]);
    this.entries=files.entries;
    if(navigationIdle&&this.navigationPending===0&&navigationVersion===this.navigationVersion){this.navigation=nav;this.navigationKnown=true;}
    this.assets=assets.items;this.notify();
  }
  private navigationVersion=0;
  private navigationPending=0;
  private navigationKnown=true;
  private navigationTail:Promise<void>=Promise.resolve();
  navigate(fields:Record<string,unknown>,previousPosition?:number,previousNavigation=this.navigation){
    const predecessor=this.navigationTail;
    ++this.navigationPending;++this.navigationVersion;
    const operation=(async()=>{
      await predecessor;
      try{
        // A position belongs to the exact navigation source read by its caller.
        // Earlier queued navigation may already have moved the server elsewhere.
        const previous=this.navigationKnown&&this.navigation===previousNavigation?previousPosition:undefined;
        const nav=await noteCommand('notes.navigation',this.project.id,{...fields,...(previous!==undefined?{previous_cursor_offset:previous}:{})});
        this.navigation=nav;this.navigationKnown=true;this.notify();return nav;
      }catch(error){this.navigationKnown=false;throw error;}
      finally{--this.navigationPending;++this.navigationVersion;}
    })();
    this.navigationTail=operation.then(()=>undefined,()=>undefined);
    return operation;
  }
  async open(path:string,record=true,position=0,previousPosition?:number){
    const previousNavigation=this.navigation;
    const disk=await noteCommand('notes.read',this.project.id,{relative_path:path});
    const old=this.buffers.get(path);
    if(!old || !old.dirty)this.buffers.set(path,{id:disk.id,path,text:disk.markdown,base:disk.content_sha256,revision:disk.revision,dirty:false,outline:disk.outline,savedLength:Array.from(disk.markdown).length});
    else if(old.base!==disk.content_sha256)old.conflict='文件已有外部改动。当前缓冲与磁盘均保留；请比较后另存笔记。';
    if(record)await this.navigate({op:'open',relative_path:path,cursor_offset:position},previousPosition,previousNavigation);
    await this.refresh();this.notify();return this.buffers.get(path)!;
  }
  locationOffset(){
    if(this.navigationPending||!this.navigationKnown)return undefined;
    const path=this.navigation.location?.relative_path;
    const b=this.buffers.get(path);if(!b)return undefined;
    // View offsets belong to their source revision. Keep dirty or stale
    // positions in the view state instead of mapping them onto the disk file.
    if(b.dirty||this.navigation.location?.content_sha256!==b.base)return undefined;
    const active=this.views[this.activeView];
    const view=active?.path===path?active:Object.values(this.views).find(v=>v.path===path);
    if(!view)return undefined;
    if(view.readingMode&&view.readingBase===b.base&&typeof view.readingSourceOffset==='number')return Math.min(view.readingSourceOffset,b.savedLength??Array.from(b.text).length);
    return Math.min(Array.from(b.text.slice(0,view.cursor||0)).length,b.savedLength??Array.from(b.text).length);
  }
  edit(path:string,text:string){const b=this.buffers.get(path)!;b.text=text;b.dirty=true;this.persisted=false;this.contentEpoch++;this.notify();this.schedule();}
  moved(old:string,path:string,revisions:any){const b=this.buffers.get(old);if(b){b.path=path;this.buffers.delete(old);this.buffers.set(path,b);}for(const view of Object.values(this.views))if(view.path===old)view.path=path;if(this.locations[old]){this.locations[path]={...this.locations[old],path};delete this.locations[old];}for(const locations of Object.values(this.viewLocations))if(locations[old]){locations[path]={...locations[old],path};delete locations[old];}if(this.activePath===old)this.activePath=path;if(revisions?.drafts!==undefined)this.draftRevision=revisions.drafts;if(revisions?.layout!==undefined)this.layoutRevision=revisions.layout;this.notify();}
  editManuscript(blocks:any[],title:string,captions:ManuscriptCaptionEdit[]=this.paperDraft?.captions||[]){
    const draft=this.paperDraft!;if(JSON.stringify(draft.blocks)===JSON.stringify(blocks)&&(draft.title??this.paper.title)===title&&canonicalSource(draft.captions||[])===canonicalSource(captions))return;
    draft.blocks=structuredClone(blocks);draft.title=title;
    if(captions.length)draft.captions=structuredClone(captions);else delete draft.captions;
    const saved=this.paper.content.blocks;
    draft.dirty=draft.base!==this.paper.revision||title!==this.paper.title||canonicalSource(blocks)!==canonicalSource(saved)||captions.length>0;
    this.persisted=false;this.contentEpoch++;this.notify();this.schedule();
  }
  setReviewComposer(value:Session['reviewComposer']){if(JSON.stringify(this.reviewComposer)===JSON.stringify(value))return;this.reviewComposer=structuredClone(value);this.persisted=false;this.contentEpoch++;this.notify();this.schedule();}
  setReviewProjection(state:any,view?:any){const nextView=view===undefined?this.reviewView:view;if(JSON.stringify([this.reviewState,this.reviewView])===JSON.stringify([state,nextView]))return;this.reviewState=state;this.reviewView=nextView;this.notify();}
  noteFigureWrites(rows:{object_id:string,result_revision:number}[]){
    let changed=false;
    for(const row of rows){
      if(typeof row.object_id==='string'&&Number.isSafeInteger(row.result_revision)&&row.result_revision>(this.figureWriteRevisions[row.object_id]||0)){
        this.figureWriteRevisions[row.object_id]=row.result_revision;changed=true;
      }
    }
    if(changed)this.notify();
  }
  editPaper(id:string,text:string){const draft=this.paperDraft!;draft.blocks=draft.blocks.map(b=>b.id===id?{...b,text}:b);draft.dirty=true;this.persisted=false;this.contentEpoch++;this.notify();this.schedule();}
  editPaperTitle(title:string){this.paperDraft!.title=title;this.paperDraft!.dirty=true;this.persisted=false;this.contentEpoch++;this.notify();this.schedule();}
  insertPaper(after:string){const draft=this.paperDraft!;const at=draft.blocks.findIndex(b=>b.id===after);draft.blocks.splice(at+1,0,{id:crypto.randomUUID(),kind:'paragraph',text:''});draft.dirty=true;this.contentEpoch++;this.persisted=false;this.notify();this.schedule();}
  deletePaper(id:string){const draft=this.paperDraft!;draft.blocks=draft.blocks.filter(b=>b.id!==id);draft.dirty=true;this.contentEpoch++;this.persisted=false;this.notify();this.schedule();}
  resetPaperDraft(){this.paperDraft={base:this.paper.revision,title:this.paper.title,blocks:structuredClone(this.paper.content.blocks),dirty:false};}
  applyPaperWrite(result:any,sent:{kind:'direct'|'propose',paperId:string,draft:NonNullable<Session['paperDraft']>,base:number,blocks:any[],title:string,captions?:ManuscriptCaptionEdit[]}):'applied'|'stale'{
    // A successful write receipt is evidence about that write, not permission
    // to replace a newer source already observed by this session.
    if(this.paper?.id!==sent.paperId||result.object.id!==sent.paperId||this.paper.revision>result.object.revision)return 'stale';
    const sameDraft=this.paperDraft===sent.draft&&sent.draft.base===sent.base;
    const unchanged=sameDraft&&canonicalSource(sent.draft.blocks)===canonicalSource(sent.blocks)&&(sent.draft.title??this.paper.title)===sent.title&&canonicalSource(sent.draft.captions||[])===canonicalSource(sent.captions||[]);
    const previousComponents=this.paper.content.components||[];
    const olderRender=this.render&&this.render.revision>(result.render?.revision??0);
    this.paper=result.object;
    if('render' in result&&!olderRender)this.render=result.render;
    if(sameDraft){
      if(sent.kind==='direct'){
        sent.draft.base=this.paper.revision;sent.draft.dirty=!unchanged;
        // A legacy dirty cache may omit metadata that the text-only server
        // write preserves. Once this exact draft is saved, adopt the complete
        // receipt source; later typing must keep its own blocks untouched.
        if(unchanged){sent.draft.blocks=structuredClone(this.paper.content.blocks);sent.draft.title=this.paper.title;delete sent.draft.captions;}
        else {
          // Later typing OR an undo during the request belongs to the user.
          // Rebase only the captions this receipt actually saved, preserving
          // their desired current text as a fresh edit against the new source.
          const current=new Map((sent.draft.captions||[]).map(edit=>[edit.index,edit]));
          for(const saved of sent.captions||[]){
            const edit=current.get(saved.index),ref=this.paper.content.components?.[saved.index],old=previousComponents[saved.index];
            const desired=edit?.text??old?.caption;
            if(ref&&(ref.id||ref.object_id)===saved.component_id&&ref.revision===saved.component_revision&&ref.caption===saved.text&&
              typeof desired==='string'&&(!edit||edit.before===saved.before&&edit.component_id===saved.component_id&&edit.component_revision===saved.component_revision)){
              if(desired===ref.caption)current.delete(saved.index);
              else current.set(saved.index,{...saved,before:ref.caption,text:desired});
            }
          }
          if(current.size)sent.draft.captions=[...current.values()].sort((a,b)=>a.index-b.index);else delete sent.draft.captions;
          sent.draft.dirty=(sent.draft.captions?.length||0)>0||canonicalSource(sent.draft.blocks)!==canonicalSource(this.paper.content.blocks)||(sent.draft.title??this.paper.title)!==this.paper.title;
        }
      }
      else if(unchanged)this.resetPaperDraft();
    }
    this.contentEpoch++;this.persisted=false;this.notify();return 'applied';
  }
  setCaptionDrafts(rows:Record<string,any>){
    if(JSON.stringify(this.captionDrafts)===JSON.stringify(rows))return;
    this.captionDrafts=structuredClone(rows);this.persisted=false;this.contentEpoch++;this.notify();this.schedule();
  }
  setReviewNoteRefs(refs:NativeNoteRef[]){
    if(JSON.stringify(this.reviewNoteRefs)===JSON.stringify(refs))return;
    this.reviewNoteRefs=structuredClone(refs);this.persisted=false;this.contentEpoch++;this.notify();this.schedule();
  }
  async refreshPaper(){
    const sequence=++this.paperReadSequence;
    const x=await command('desk.paper.read',{project_id:this.project.id});
    if(sequence!==this.paperReadSequence||this.paper?.id===x.object.id&&this.paper.revision>x.object.revision)return;
    const olderRender=this.paper?.id===x.object.id&&this.render&&this.render.revision>(x.render?.revision??0);
    this.paper=x.object;if(!olderRender)this.render=x.render;if(!this.paperDraft?.dirty)this.resetPaperDraft();this.notify();
  }
  position(id:string,value:any){this.views[id]={...this.views[id],...value};if(value.path){const p={...this.views[id],base:this.buffers.get(value.path)?.base};(this.viewLocations[id]??={})[value.path]=p;if(this.activeView===id||!this.locations[value.path])this.locations[value.path]=p;}clearTimeout(this.viewTimer);this.viewTimer=setTimeout(()=>{if(this.layout)void this.saveLayout(this.layout);},220);}
  schedule(){clearTimeout(this.timer);this.timer=setTimeout(()=>this.flush(),180);}
  retrySync():Promise<void>{
    // Only an explicit user action retries failed persistence. Keep the same
    // project, CAS revisions and complete local drafts; never reload over them.
    if(this.syncRetry)return this.syncRetry;
    this.retryingSync=true;
    this.syncRetry=(async()=>{
      if(this.layout&&!await this.saveLayout(this.layout))return;
      await this.flush();
    })().finally(()=>{this.syncRetry=null;this.retryingSync=false;this.notify();});
    this.notify();return this.syncRetry;
  }
  async flush(){
    clearTimeout(this.timer);
    this.pending=this.pending.then(async()=>{
      const revision=this.contentEpoch;
      try{
        const result=await command('desk.drafts.write',{project_id:this.project.id,expected_revision:this.draftRevision,value:{buffers:Object.fromEntries(this.buffers),manuscript:this.paperDraft,figure_drafts:this.figureDrafts,composition_drafts:this.compositionDrafts,caption_drafts:this.captionDrafts,review_note_refs:this.reviewNoteRefs,review_composer:this.reviewComposer}});
        this.draftRevision=result.revision;this.persisted=this.contentEpoch===revision;this.error='';this.notify();
      }catch(e){this.error=String(e);this.persisted=false;this.notify();}
    });await this.pending;
  }
  async save(path:string){
    const b=this.buffers.get(path)!;
    const sent=b.text;
    try{
      const result=await noteCommand('notes.write',this.project.id,{relative_path:path,markdown:sent,encoding:'utf-8',expected_content_sha256:b.base});
      b.base=result.content_sha256;b.revision=result.revision;b.outline=result.outline;b.savedLength=Array.from(sent).length;b.dirty=b.text!==sent;b.conflict=undefined;
      if(this.locations[path])this.locations[path].base=b.base;
      await this.refresh();await this.flush();this.notify();
    }catch(e){b.conflict=String(e);await this.flush();this.notify();throw e;}
  }
  async saveLayout(layout:any){
    layout=structuredClone(layout);
    for(const panel of Object.values(layout.panels||{}) as any[]){if(panel.params){delete panel.params.loading;delete panel.params.readError;delete panel.params.jump;delete panel.params.cursor;}}
    this.layout=layout;
    let saved=false;
    this.pending=this.pending.then(async()=>{
      try{const x=await command('desk.layout.write',{project_id:this.project.id,expected_revision:this.layoutRevision,value:{layout:this.layout,views:this.views,locations:this.locations,view_locations:this.viewLocations,generation_layouts:this.generationLayouts,active_path:this.activePath,active_view:this.activeView}});this.layoutRevision=x.revision;saved=true;}
      catch(e){this.error=String(e);this.notify();}
    });await this.pending;return saved;
  }
}
