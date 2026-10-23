import {Schema,Fragment,type Node as PMNode} from 'prosemirror-model';
import {Plugin} from 'prosemirror-state';
import {Decoration,DecorationSet} from 'prosemirror-view';
import {manuscriptSchema,manuscriptDocument,manuscriptSource} from './ScientificManuscript';
import {captionDraftText,captionIndex,captionEditsFromDocument,captionDocumentAttributes,createCaptionEditor,type ManuscriptCaptionEdit,type CaptionEditorHandle} from './ManuscriptCaptionEditor';

export type ContinuousBlock={id:string,kind:string,text:string,[key:string]:unknown};
export type ContinuousSegment={block_id:string,start:number,end:number,quote:string};
export type ContinuousSelection={start_block_id:string,end_block_id:string,start:number,end:number,quote:string,offset_unit:'unicode_code_point',segments:ContinuousSegment[]};
export type ManuscriptMark={id:string,block_id:string,start:number,end:number,quote?:string,kind:'insert'|'delete'|'replace'|'opinion',label:string,text?:string};
export type ManuscriptFigureRef={id:string,revision:number,sha256?:string};
export type ManuscriptFigure={key:string,after_block_id:string,caption:string,previewUrl?:string,ref:ManuscriptFigureRef,error?:string,componentIdentity?:string};
export type CaptionReviewMark={key:string,label:string,start:number,end:number,quote:string};
export const newManuscriptBlockId=()=>`BLOCK-${crypto.randomUUID().replaceAll('-','').slice(0,16)}`;
const scientific=Object.fromEntries(Object.entries(manuscriptSchema.nodes).filter(([name])=>name.startsWith('scientific_')).map(([name,node])=>[name,node.spec]));
export const continuousSchema=new Schema({nodes:{
  doc:{content:'manuscript_title source_block+'},
  manuscript_title:{content:'text*',attrs:{caption_edits:{default:[]},caption_sources:{default:[]}},marks:'',toDOM:()=>['h1',{'data-manuscript-title':'true'},0]},
  source_block:{group:'block',content:'inline*',marks:'',whitespace:'pre',attrs:{block_id:{default:''},kind:{default:'paragraph'},data:{default:{}}},
    toDOM:node=>[node.attrs.kind==='heading'?`h${Math.max(2,Math.min(6,Number(node.attrs.data.level)||2))}`:'p',{'data-block-id':node.attrs.block_id,'data-block-kind':node.attrs.kind,style:'white-space:pre-wrap'},0]},
  text:{group:'inline'},...scientific,
}});
function inline(text:string,rich=true):Fragment{return Fragment.fromArray(Array.from(manuscriptDocument(text,{id:'projection',kind:'paragraph'},rich).firstChild!.content.content).map(node=>continuousSchema.nodeFromJSON(node.toJSON())));}
export function continuousDocument(blocks:ContinuousBlock[],title:string,rich=true,captionEdits:ManuscriptCaptionEdit[]=[],figures:ManuscriptFigure[]=[]):PMNode{
  const ids=new Set<string>();
  for(const b of blocks){if(!b.id||ids.has(b.id)||typeof b.text!=='string')throw Error('稿件段落身份缺失、重复或源文本无效。');ids.add(b.id);}
  const source=blocks.length?blocks:[{id:newManuscriptBlockId(),kind:'paragraph',text:''}];
  const doc=continuousSchema.node('doc',null,[continuousSchema.node('manuscript_title',captionDocumentAttributes(captionEdits,figures),title?continuousSchema.text(title):undefined),...source.map(({id,kind,text,...data})=>continuousSchema.node('source_block',{block_id:id,kind,data},inline(text,rich)))]);
  captionEditsFromDocument(doc);return doc;
}
export function continuousProjection(doc:PMNode):{blocks:ContinuousBlock[],title:string}{
  const blocks:ContinuousBlock[]=[];doc.forEach(node=>{if(node.type.name==='source_block')blocks.push({...node.attrs.data,id:node.attrs.block_id,kind:node.attrs.kind,text:manuscriptSource(node)});});
  return {blocks,title:doc.firstChild?.textContent||''};
}
export function continuousClipboard(node:PMNode|Fragment):string{
  const parts:string[]=[];let blocks=false;node.forEach(child=>{blocks ||= child.isBlock;parts.push(manuscriptSource(child));});
  return parts.join(blocks?'\n\n':'');
}
export function blockSourceOffset(node:PMNode,relative:number):number{
  let source=0;relative=Math.max(0,Math.min(node.content.size,relative));
  node.forEach((child,pos)=>{if(relative<=pos)return;const length=manuscriptSource(child).length;source+=child.isText?Math.min(length,relative-pos):length;});return source;
}
function blockPosition(node:PMNode,utf16:number,bias:-1|1):number{
  let source=0,position=node.content.size,done=false;
  node.forEach((child,pos)=>{if(done)return;const length=manuscriptSource(child).length;if(utf16<=source+length){position=pos+(child.isText?Math.min(length,utf16-source):utf16===source?0:utf16===source+length?1:bias<0?0:1);done=true;}source+=length;});return position;
}
export function continuousPosition(doc:PMNode,id:string,offset:number,bias:-1|1=-1):number|null{
  let result:number|null=null;doc.forEach((node,pos)=>{if(node.attrs.block_id===id){const points=Array.from(manuscriptSource(node));if(!Number.isSafeInteger(offset)||offset<0||offset>points.length)return;result=pos+1+blockPosition(node,points.slice(0,offset).join('').length,bias);}});return result;
}
export function continuousSelection(doc:PMNode,from:number,to:number):ContinuousSelection|null{
  if(from===to)return null;const segments:ContinuousSegment[]=[];let titleSelected=false;
  doc.forEach((node,pos)=>{
    if(node.type.name==='manuscript_title'){if(from<pos+node.nodeSize-1)titleSelected=true;return;}
    const left=pos+1,right=left+node.content.size;if(to<left||from>right)return;
    const source=manuscriptSource(node),start=blockSourceOffset(node,from-left),end=blockSourceOffset(node,to-left);
    segments.push({block_id:node.attrs.block_id,start:Array.from(source.slice(0,start)).length,end:Array.from(source.slice(0,end)).length,quote:source.slice(start,end)});
  });
  if(titleSelected||!segments.some(s=>s.quote))return null;
  const first=segments[0],last=segments.at(-1)!;return {start_block_id:first.block_id,end_block_id:last.block_id,start:first.start,end:last.end,quote:segments.map(s=>s.quote).join('\n\n'),offset_unit:'unicode_code_point',segments};
}
export function stableBlockIdentities(makeId=newManuscriptBlockId):Plugin{
  return new Plugin({appendTransaction(transactions,_old,state){
    if(!transactions.some(t=>t.docChanged))return null;
    const used=new Set<string>(),tr=state.tr;state.doc.forEach((node,pos)=>{if(node.type.name!=='source_block')return;let id=node.attrs.block_id;if(!id||used.has(id)){do{id=makeId();}while(used.has(id));tr.setNodeMarkup(pos,undefined,{...node.attrs,block_id:id});}used.add(id);});return tr.docChanged?tr:null;
  }});
}
export function manuscriptDecorations(doc:PMNode,marks:ManuscriptMark[],navigation?:{activeKeys?:string[],interactive?:boolean}):{set:DecorationSet,errors:string[]}{
  const decorations:Decoration[]=[],errors:string[]=[];
  for(const mark of marks){
    const matches:PMNode[]=[];doc.forEach(node=>{if(node.attrs.block_id===mark.block_id)matches.push(node);});const source=matches.length===1?manuscriptSource(matches[0]):null;
    if(source===null||!Number.isSafeInteger(mark.start)||!Number.isSafeInteger(mark.end)||mark.start<0||mark.end<mark.start||mark.end>Array.from(source).length||(mark.quote!==undefined&&Array.from(source).slice(mark.start,mark.end).join('')!==mark.quote)) {errors.push(`未定位 ${mark.label}（${mark.id}）：保存选区已变或身份无效。`);continue;}
    const from=continuousPosition(doc,mark.block_id,mark.start,-1)!,to=continuousPosition(doc,mark.block_id,mark.end,1)!;
    // A partial atomic-token range cannot honestly be painted as exact source.
    const actual=continuousSelection(doc,from,to)?.segments[0];
    if((mark.start===mark.end&&from!==to)||(mark.start!==mark.end&&(!actual||actual.start!==mark.start||actual.end!==mark.end))){errors.push(`未定位 ${mark.label}（${mark.id}）：选区位于科学节点内部，请选择完整节点。`);continue;}
    // Separate decoration layers keep overlapping author/range identities intact
    // and leave scientific atom attributes attached to their original source.
    const kind=mark.kind==='opinion'?'opinion':'change',key=kind+':'+mark.id,active=navigation?.activeKeys?.includes(key),style=mark.kind==='delete'||mark.kind==='replace'?'text-decoration:line-through':mark.kind==='insert'?'text-decoration:underline':'background:rgba(240,200,60,.22)';
    if(from<to)decorations.push(Decoration.inline(from,to,{nodeName:'span',class:`manuscript-mark manuscript-mark-${mark.kind}`,'data-review-id':mark.id,'data-review-kind':kind,'data-review-key':key,...(active?{'data-review-active':'true'}:{}),title:mark.label,style:style+(active?';outline:2px solid currentColor;outline-offset:2px':'')}));
    if(mark.text!==undefined)decorations.push(Decoration.widget(to,()=>{const span=document.createElement('span');span.contentEditable='false';span.className=`manuscript-suggestion manuscript-suggestion-${mark.kind}`;span.dataset.reviewId=mark.id;span.dataset.reviewKind=kind;span.dataset.reviewKey=key;if(active)span.dataset.reviewActive='true';if(navigation?.interactive){span.tabIndex=0;span.setAttribute('role','button');}span.setAttribute('aria-label',mark.label);span.textContent=`［${mark.label}：${mark.text}］`;return span;},{key:JSON.stringify([mark,active,navigation?.interactive]),side:1}));
  }
  return {set:DecorationSet.create(doc,decorations),errors};
}
export function reparsedDocument(doc:PMNode):PMNode{const value=continuousProjection(doc);const next=continuousDocument(value.blocks,value.title,true,captionEditsFromDocument(doc));return next.copy(Fragment.fromArray([next.firstChild!.type.create(doc.firstChild!.attrs,next.firstChild!.content),...next.content.content.slice(1)]));}
export function manuscriptFigureDecorations(doc:PMNode,figures:ManuscriptFigure[],open?:(ref:ManuscriptFigureRef)=>void,navigation?:{marks:(figure:ManuscriptFigure)=>CaptionReviewMark[],activeKeys?:string[],scope?:string,activate?:(keys:string[])=>void,selectCaption?:(figure:ManuscriptFigure,element:HTMLElement)=>void,captionEditing?:{enabled:boolean,canEdit:()=>boolean,owns:()=>boolean,activeKeys?:()=>string[],register:(handle:CaptionEditorHandle)=>void,unregister:(handle:CaptionEditorHandle)=>void,onCompositionEnd?:()=>void}}):{set:DecorationSet,errors:string[]}{
  const decorations:Decoration[]=[],errors:string[]=[],keys=new Set<string>();
  for(const figure of figures){
    let position:number|null=null,count=0;doc.forEach((node,pos)=>{if(node.attrs.block_id===figure.after_block_id){position=pos+node.nodeSize;count++;}});
    if(!figure.key||keys.has(figure.key)||count!==1||!figure.ref.id||!Number.isSafeInteger(figure.ref.revision)||figure.ref.revision<1||(figure.ref.sha256!==undefined&&!/^[a-f0-9]{64}$/.test(figure.ref.sha256))){errors.push(`未定位稿内图 ${figure.key||'（缺少位置身份）'}：位置或固定来源无效。`);continue;}keys.add(figure.key);
    const draft=captionDraftText(doc,figure),captionText=draft??figure.caption;
    if(draft===null)errors.push(`稿内图 ${figure.key} 的图注草稿与固定来源不符；保留草稿，未重新绑定。`);
    const points=Array.from(captionText),marks=(captionText===figure.caption?navigation?.marks(figure)||[]:[]).filter(mark=>Number.isSafeInteger(mark.start)&&Number.isSafeInteger(mark.end)&&mark.start>=0&&mark.end>=mark.start&&mark.end<=points.length&&points.slice(mark.start,mark.end).join('')===mark.quote);
    let child:CaptionEditorHandle|undefined;
    decorations.push(Decoration.widget(position!,(parent)=>{const dom=document.createElement('figure');dom.contentEditable='false';dom.className='manuscript-saved-figure';dom.dataset.componentKey=figure.key;dom.dataset.figureId=figure.ref.id;dom.dataset.figureRevision=String(figure.ref.revision);
      if(figure.previewUrl&&!figure.error){const image=document.createElement('img');image.src=figure.previewUrl;image.alt=figure.caption;image.style.maxWidth='100%';dom.append(image);}
      const caption=document.createElement('figcaption');caption.setAttribute('aria-label','稿内图注 '+figure.key);
      const wrap=(node:Node,mark:CaptionReviewMark)=>{const span=document.createElement('span');span.className='manuscript-caption-mark';span.dataset.reviewKey=mark.key;span.dataset.reviewId=mark.key.slice(mark.key.indexOf(':')+1);span.title=mark.label;if(navigation?.activeKeys?.includes(mark.key))span.dataset.reviewActive='true';span.setAttribute('aria-label','图注审阅话题 '+mark.key);span.append(node);return span;};
      const editing=navigation?.captionEditing;
      if(editing?.enabled&&captionIndex(figure)!==null){
        child=createCaptionEditor(caption,parent,figure,{canEdit:editing.canEdit,owns:editing.owns,onCompositionEnd:editing.onCompositionEnd,marks:()=>navigation?.marks(figure)||[],activeKeys:()=>editing.activeKeys?.()||navigation?.activeKeys||[]});editing.register(child);
      }else {
      const boundaries=[...new Set([0,points.length,...marks.flatMap(mark=>[mark.start,mark.end])])].sort((a,b)=>a-b);
      for(let index=0;index<boundaries.length;index++){
        const start=boundaries[index],end=boundaries[index+1];
        for(const mark of marks.filter(mark=>mark.start===start&&mark.end===start))caption.append(wrap(document.createTextNode(''),mark));
        if(end===undefined)continue;
        let node:Node=document.createTextNode(points.slice(start,end).join(''));for(const mark of marks.filter(mark=>mark.start<=start&&mark.end>=end&&mark.start<mark.end))node=wrap(node,mark);caption.append(node);
      }
      }
      const activate=(event:Event)=>{const keys:string[]=[];for(let element=event.target instanceof Element?event.target:null;element&&element!==caption;element=element.parentElement){const key=element.getAttribute('data-review-key');if(key&&marks.some(mark=>mark.key===key)&&!keys.includes(key))keys.push(key);}const selection=caption.ownerDocument.getSelection();if(selection&&!selection.isCollapsed&&caption.contains(selection.anchorNode)&&caption.contains(selection.focusNode))for(const span of caption.querySelectorAll<HTMLElement>('[data-review-key]')){const key=span.dataset.reviewKey!;if(selection.containsNode(span,true)&&!keys.includes(key))keys.push(key);}if(keys.length){event.preventDefault();navigation?.activate?.(keys);}};
      caption.addEventListener('click',activate);caption.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&(!editing?.enabled||(event.target as Element)?.getAttribute('role')==='button')){activate(event);}});dom.append(caption);
      caption.addEventListener('mouseup',()=>navigation?.selectCaption?.(figure,caption));
      caption.addEventListener('keyup',()=>navigation?.selectCaption?.(figure,caption));
      const ref=document.createElement('small');ref.textContent=`${figure.ref.id} · r${figure.ref.revision}${figure.ref.sha256?' · '+figure.ref.sha256:''}`;dom.append(ref);
      if(figure.error){const error=document.createElement('p');error.setAttribute('role','status');error.textContent=figure.error;dom.append(error);}
      if(open&&!figure.error){const button=document.createElement('button');button.type='button';button.textContent='打开固定来源图';button.setAttribute('aria-label',`打开稿内图 ${figure.key}`);button.addEventListener('click',()=>open(figure.ref));dom.append(button);}
      return dom;},{key:JSON.stringify([figure,navigation?.captionEditing?.enabled?null:marks,navigation?.scope,!!navigation?.captionEditing?.enabled,navigation?.captionEditing?.enabled?null:captionText]),side:1,stopEvent:()=>true,ignoreSelection:true,destroy(){if(child){navigation?.captionEditing?.unregister(child);child.destroy();child=undefined;}}}));
  }
  return {set:DecorationSet.create(doc,decorations),errors};
}
