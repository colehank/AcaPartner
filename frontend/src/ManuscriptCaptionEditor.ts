import {Schema,type Node as PMNode} from 'prosemirror-model';
import {EditorState,TextSelection,Plugin,type Transaction} from 'prosemirror-state';
import {EditorView,Decoration,DecorationSet} from 'prosemirror-view';
import {keymap} from 'prosemirror-keymap';
import {baseKeymap} from 'prosemirror-commands';
import {undo,redo,isHistoryTransaction} from 'prosemirror-history';

export type ManuscriptCaptionEdit={index:number,component_id:string,component_revision:number,before:string,text:string};
export type CaptionSource={key:string,caption:string,ref:{id:string,revision:number,sha256?:string},after_block_id?:string,componentIdentity?:string};
type SavedCaption={index:number,component_id:string,component_revision:number,before:string,identity:string};
export type CaptionEditorHandle={view:EditorView,sync:()=>void,destroy:()=>void};
type CaptionEditorMark={key:string,label:string,start:number,end:number,quote:string};
// The child is a text editor, not a second draft/history authority. Caption
// characters (including TeX and references) remain literal source characters.
const captionSchema=new Schema({nodes:{doc:{content:'text*',whitespace:'pre'},text:{}}});
const document=(text:string)=>captionSchema.node('doc',null,text?captionSchema.text(text):undefined);

function checkedEdits(edits:unknown):ManuscriptCaptionEdit[]{
  if(!Array.isArray(edits))throw Error('图注草稿结构无效；未覆盖保存版。');
  const indices=new Set<number>();
  for(const e of edits){
    if(!e||Object.keys(e).sort().join(',')!=='before,component_id,component_revision,index,text'||!Number.isSafeInteger(e.index)||e.index<0||indices.has(e.index)||typeof e.component_id!=='string'||!e.component_id||!Number.isSafeInteger(e.component_revision)||e.component_revision<1||typeof e.before!=='string'||typeof e.text!=='string')throw Error('图注草稿身份缺失、重复或源文本无效。');
    indices.add(e.index);
  }
  return edits.map(e=>({...e}));
}
const values=(doc:PMNode)=>checkedEdits(doc.firstChild?.attrs.caption_edits??[]);
const sources=(doc:PMNode):SavedCaption[]=>doc.firstChild?.attrs.caption_sources??[];
export function captionIndex(source:CaptionSource):number|null{
  const match=/:([0-9]+)$/.exec(source.key),index=match?Number(match[1]):NaN;
  return Number.isSafeInteger(index)&&index>=0?index:null;
}
function sourceIdentity(source:CaptionSource):string{
  let component=source.componentIdentity;
  // PaperFigureIdentity is a typed value encoding, preserving -0. Only the
  // caption pair may change at a caption save; all other pairs stay exact.
  if(component){try{const encoded=JSON.parse(component);if(Array.isArray(encoded)&&encoded[0]==='object'&&Array.isArray(encoded[1])){
    const caption=encoded[1].filter((pair:any)=>Array.isArray(pair)&&pair[0]==='caption');
    if(caption.length!==1||JSON.stringify(caption[0][1])!==JSON.stringify(['string',source.caption]))throw Error('图注组件原文身份不符。');
    component=JSON.stringify(['object',encoded[1].filter((pair:any)=>pair[0]!=='caption')]);
  }}catch(error){if(error instanceof SyntaxError){/* Legacy opaque identity remains exact. */}else throw error;}}
  return JSON.stringify([source.key,source.ref.id,source.ref.revision,source.ref.sha256??null,source.after_block_id??null,component??null]);
}
function saved(source:CaptionSource):SavedCaption|null{
  const index=captionIndex(source);return index===null?null:{index,component_id:source.ref.id,component_revision:source.ref.revision,before:source.caption,identity:sourceIdentity(source)};
}
const sameRef=(a:{component_id:string,component_revision:number},b:{component_id:string,component_revision:number})=>a.component_id===b.component_id&&a.component_revision===b.component_revision;
export function captionDocumentAttributes(edits:ManuscriptCaptionEdit[],figures:CaptionSource[]=[]):{caption_edits:ManuscriptCaptionEdit[],caption_sources:SavedCaption[]}{
  const full=checkedEdits(edits),base:SavedCaption[]=full.map(({index,component_id,component_revision,before})=>({index,component_id,component_revision,before,identity:''}));
  const indices=new Set<number>();
  for(const figure of figures){const entry=saved(figure);if(!entry)continue;if(indices.has(entry.index))throw Error('图注位置身份重复。');indices.add(entry.index);
    const old=base.find(e=>e.index===entry.index);
    if(old){if(sameRef(old,entry)&&old.before===entry.before)Object.assign(old,entry);}
    else{base.push(entry);full.push({...entry,text:entry.before});delete (full.at(-1)! as any).identity;}
  }
  full.sort((a,b)=>a.index-b.index);base.sort((a,b)=>a.index-b.index);
  return {caption_edits:full,caption_sources:base};
}
export function captionEditsFromDocument(doc:PMNode):ManuscriptCaptionEdit[]{
  return values(doc).flatMap(value=>{const base=sources(doc).find(e=>e.index===value.index);
    const before=base&&sameRef(base,value)?base.before:value.before;
    return value.text===before?[]:[{...value,before}];
  });
}
// Full desired values live in the parent title node, including unchanged
// captions. This lets parent history undo an edit after its successful save.
// Saved baselines are read-only identity metadata, updated without history.
export function preserveCaptionEdits():Plugin{
  return new Plugin({appendTransaction(transactions,old,state){
    if(!transactions.some(tr=>tr.docChanged)||transactions.some(tr=>tr.getMeta('caption_edit')||tr.getMeta('caption_baseline')||isHistoryTransaction(tr)))return null;
    let tr=state.tr;
    for(const name of ['caption_edits','caption_sources'])if(JSON.stringify(old.doc.firstChild?.attrs[name])!==JSON.stringify(state.doc.firstChild?.attrs[name]))tr=tr.setNodeAttribute(0,name,old.doc.firstChild?.attrs[name]??[]);
    return tr.docChanged?tr:null;
  }});
}
export function captionDraftText(doc:PMNode,source:CaptionSource):string|null{
  const index=captionIndex(source);if(index===null)return source.caption;
  const value=values(doc).find(e=>e.index===index),base=sources(doc).find(e=>e.index===index);
  if(!value)return source.caption;
  const entry=saved(source)!;
  return base&&sameRef(base,entry)&&base.before===source.caption&&(!base.identity||base.identity===entry.identity)?value.text:null;
}
// Adopt only an exact same-document/ref receipt whose desired caption text
// already equals the live parent draft. This never imports external new text.
export function refreshCaptionBaseline(view:EditorView,figures:CaptionSource[],incoming:ManuscriptCaptionEdit[]):boolean{
  const wanted=checkedEdits(incoming),full=values(view.state.doc),old=sources(view.state.doc),current=new Map<number,SavedCaption>();
  for(const figure of figures){const entry=saved(figure);if(!entry)continue;if(current.has(entry.index))return false;current.set(entry.index,entry);}
  if(wanted.some(e=>!current.has(e.index)))return false;
  const next=full.map(e=>({...e})),base:SavedCaption[]=[];
  for(const [index,entry] of current){const previous=old.find(e=>e.index===index),value=full.find(e=>e.index===index),expected=wanted.find(e=>e.index===index);
    if(previous&&(!sameRef(previous,entry)||(previous.identity?previous.identity!==entry.identity:previous.before!==entry.before)))return false;
    if(expected&&(!sameRef(expected,entry)||expected.before!==entry.before))return false;
    const desired=expected?.text??entry.before;
    if(value&&(!sameRef(value,entry)||value.text!==desired))return false;
    if(!value)next.push({index,component_id:entry.component_id,component_revision:entry.component_revision,before:entry.before,text:desired});
    base.push(entry);
  }
  if(full.some(e=>!current.has(e.index))||old.some(e=>!current.has(e.index)))return false;
  next.sort((a,b)=>a.index-b.index);base.sort((a,b)=>a.index-b.index);
  const tr=view.state.tr;
  if(JSON.stringify(next)!==JSON.stringify(full))tr.setNodeAttribute(0,'caption_edits',next);
  if(JSON.stringify(base)!==JSON.stringify(old))tr.setNodeAttribute(0,'caption_sources',base);
  if(tr.docChanged){view.updateState(view.state.apply(tr.setMeta('caption_baseline',true).setMeta('addToHistory',false)));}
  return true;
}
export function captionEditTransaction(view:EditorView,source:CaptionSource,text:string):Transaction|null{
  const index=captionIndex(source),full=values(view.state.doc);
  if(index===null||captionDraftText(view.state.doc,source)===null)return null;
  const next=full.filter(e=>e.index!==index);
  next.push({index,component_id:source.ref.id,component_revision:source.ref.revision,before:source.caption,text});next.sort((a,b)=>a.index-b.index);
  if(JSON.stringify(next)===JSON.stringify(full))return null;
  return view.state.tr.setNodeAttribute(0,'caption_edits',next).setMeta('caption_edit',true);
}

function syncCaptionSelection(view:EditorView){
  const selection=view.dom.ownerDocument.getSelection();
  if(!view.hasFocus()||!selection?.anchorNode||!selection.focusNode||!view.dom.contains(selection.anchorNode)||!view.dom.contains(selection.focusNode))return;
  const anchor=view.posAtDOM(selection.anchorNode,selection.anchorOffset),head=view.posAtDOM(selection.focusNode,selection.focusOffset);
  const next=TextSelection.create(view.state.doc,anchor,head);
  if(!next.eq(view.state.selection))view.dispatch(view.state.tr.setSelection(next));
}

export function createCaptionEditor(element:HTMLElement,parent:EditorView,source:CaptionSource,options:{canEdit:()=>boolean,owns:()=>boolean,marks?:()=>CaptionEditorMark[],activeKeys?:()=>string[],onCompositionEnd?:()=>void}):CaptionEditorHandle{
  let destroyed=false;
  const valid=()=>!destroyed&&options.owns()&&captionDraftText(parent.state.doc,source)!==null;
  const canEdit=()=>valid()&&options.canEdit();
  const parentHistory=(command:typeof undo)=>(()=>{
    if(!canEdit())return true;
    const changed=command(parent.state,parent.dispatch,parent);if(changed){sync();child.focus();}return true;
  });
  const child=new EditorView({mount:element},{
    state:EditorState.create({doc:document(captionDraftText(parent.state.doc,source)??source.caption),plugins:[keymap({
      'Mod-z':parentHistory(undo),'Mod-Shift-z':parentHistory(redo),'Mod-y':parentHistory(redo),
      // Keep document boundaries and range extension inside this caption.
      // Plain Home/End retain the browser's visual-line navigation.
      'Mod-Home':(state,dispatch)=>{if(dispatch)dispatch(state.tr.setSelection(TextSelection.create(state.doc,0)).scrollIntoView());return true;},
      'Mod-End':(state,dispatch)=>{if(dispatch)dispatch(state.tr.setSelection(TextSelection.create(state.doc,state.doc.content.size)).scrollIntoView());return true;},
      'Shift-Mod-Home':(state,dispatch)=>{if(dispatch)dispatch(state.tr.setSelection(TextSelection.create(state.doc,state.selection.anchor,0)).scrollIntoView());return true;},
      'Shift-Mod-End':(state,dispatch)=>{if(dispatch)dispatch(state.tr.setSelection(TextSelection.create(state.doc,state.selection.anchor,state.doc.content.size)).scrollIntoView());return true;},
      Backspace:state=>state.selection.empty&&state.selection.from===0,
      Delete:state=>state.selection.empty&&state.selection.to===state.doc.content.size,
      Enter:(state,dispatch)=>{if(dispatch)dispatch(state.tr.insertText('\n'));return true;},
      'Shift-Enter':(state,dispatch)=>{if(dispatch)dispatch(state.tr.insertText('\n'));return true;},
    }),keymap(baseKeymap),new Plugin({props:{decorations:state=>{
      if(state.doc.textContent!==source.caption)return DecorationSet.empty;
      const points=Array.from(source.caption),decorations:Decoration[]=[];
      for(const mark of options.marks?.()||[]){
        if(!Number.isSafeInteger(mark.start)||!Number.isSafeInteger(mark.end)||mark.start<0||mark.end<mark.start||mark.end>points.length||points.slice(mark.start,mark.end).join('')!==mark.quote)continue;
        const from=points.slice(0,mark.start).join('').length,to=points.slice(0,mark.end).join('').length,active=options.activeKeys?.().includes(mark.key);
        const attrs={nodeName:'span',class:'manuscript-caption-mark','data-review-key':mark.key,'data-review-id':mark.key.slice(mark.key.indexOf(':')+1),title:mark.label,'aria-label':'图注审阅话题 '+mark.key,...(active?{'data-review-active':'true'}:{})};
        if(from<to)decorations.push(Decoration.inline(from,to,attrs));
        else decorations.push(Decoration.widget(from,()=>{const span=element.ownerDocument.createElement('span');for(const [key,value] of Object.entries(attrs))if(key!=='nodeName')span.setAttribute(key,value);return span;},{key:JSON.stringify([mark,active]),side:1}));
      }
      return DecorationSet.create(state.doc,decorations);
    }}})]}),
    editable:canEdit,attributes:{role:'textbox','aria-label':'编辑稿内图注 '+source.key,'aria-multiline':'true',style:'white-space:pre-wrap'},
    clipboardTextSerializer:slice=>slice.content.textBetween(0,slice.content.size,'',''),
    handlePaste:(view,event)=>{if(!canEdit())return true;const text=event.clipboardData?.getData('text/plain');if(text===undefined)return false;view.dispatch(view.state.tr.insertText(text));return true;},
    handleDOMEvents:{
      keydown:(view,event)=>{
        // Native click/Home can move the DOM caret before selectionchange has
        // updated the child state. A stale 0 -> 0 Mod-Home transaction would
        // otherwise skip ProseMirror's DOM selection update entirely.
        if(valid()&&!event.isComposing&&!view.composing&&(['Home','End'].includes(event.key)||((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='a')))syncCaptionSelection(view);
        return false;
      },
      compositionend:()=>{options.onCompositionEnd?.();return false;},
    },
    dispatchTransaction(tr){
      if(!valid()||(tr.docChanged&&!canEdit()))return;
      child.updateState(child.state.apply(tr));
      if(tr.docChanged){const next=captionEditTransaction(parent,source,child.state.doc.textContent);if(next){const composition=tr.getMeta('composition');if(composition!==undefined)next.setMeta('composition',source.key+':'+String(composition));parent.dispatch(next);}}
    },
  });
  function sync(){
    if(destroyed)return;child.setProps({editable:canEdit});
    const text=captionDraftText(parent.state.doc,source);if(text===null||child.state.doc.textContent===text||child.composing)return;
    const next=document(text),selection=TextSelection.create(next,Math.min(child.state.selection.anchor,next.content.size),Math.min(child.state.selection.head,next.content.size));
    child.updateState(EditorState.create({doc:next,selection,plugins:child.state.plugins}));
  }
  return {view:child,sync,destroy(){if(!destroyed){destroyed=true;child.destroy();}}};
}
