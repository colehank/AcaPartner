import {captionTextRange,type CaptionTextSelection} from './PaperCaptionSelection';
import {captionEditsFromDocument,preserveCaptionEdits,refreshCaptionBaseline,type ManuscriptCaptionEdit,type CaptionEditorHandle} from './ManuscriptCaptionEditor';
export type {ManuscriptCaptionEdit} from './ManuscriptCaptionEditor';
import {useLayoutEffect,useRef,useState} from 'react';
import {EditorState,TextSelection,NodeSelection,AllSelection,Plugin,type Selection} from 'prosemirror-state';
import {EditorView,type NodeView} from 'prosemirror-view';
import {Slice,Fragment,type Node as PMNode} from 'prosemirror-model';
import {history,undo,redo,closeHistory,isHistoryTransaction} from 'prosemirror-history';
import {keymap} from 'prosemirror-keymap';
import {baseKeymap,splitBlockAs} from 'prosemirror-commands';
import {scientificLabels,scientificTokens,replaceScientificField,manuscriptSource,type ScientificToken,type ScientificKind} from './ScientificManuscript';
import {continuousSchema,continuousDocument,continuousProjection,continuousClipboard,continuousSelection,continuousPosition,blockSourceOffset,stableBlockIdentities,manuscriptDecorations,manuscriptFigureDecorations,newManuscriptBlockId,type ContinuousBlock,type ContinuousSelection,type ManuscriptMark,type ManuscriptFigure,type ManuscriptFigureRef} from './ContinuousManuscriptModel';
import {reviewFocusRange,reviewMarkKey,type ReviewFocus,type ReviewNavigationResult,type ReviewNavigationItem} from './ReviewNavigation';
export type {ContinuousBlock,ContinuousSelection,ManuscriptMark,ManuscriptFigure,ManuscriptFigureRef} from './ContinuousManuscriptModel';

export type FixedFigureRef={source:string,id:string,revision:number,sha256?:string};
export type ContinuousManuscriptProps={blocks:ContinuousBlock[],title:string,mode:'read'|'review'|'edit',editable?:boolean,captionEditable?:boolean,captionEdits?:ManuscriptCaptionEdit[],onChange:(blocks:ContinuousBlock[],title:string,captionEdits?:ManuscriptCaptionEdit[])=>void,onSelection:(selection:ContinuousSelection|null)=>void,onCaptionSelection?:(selection:CaptionTextSelection|null)=>void,documentKey?:string,version?:string|number,marks?:ManuscriptMark[],figures?:ManuscriptFigure[],figureRefs?:FixedFigureRef[],onOpenFigure?:(reference:ManuscriptFigureRef)=>void,reviewScope?:string,reviewFocus?:ReviewFocus|null,activeReviewKeys?:string[],reviewItems?:ReviewNavigationItem[],onReviewActivate?:(keys:string[])=>void,onReviewNavigationResult?:(result:ReviewNavigationResult)=>void};
type Chosen={blockId:string,start:number,end:number,token:ScientificToken};
type Incoming={blocks:ContinuousBlock[],title:string,captionEdits?:ManuscriptCaptionEdit[]};
const documentProjection=(doc:PMNode):Incoming=>({...continuousProjection(doc),captionEdits:captionEditsFromDocument(doc)});
const contentKey=(value:Incoming)=>JSON.stringify([value.title,value.blocks.map(({id,kind,text,...data})=>[id,kind,text,Object.entries(data).sort(([a],[b])=>a.localeCompare(b))]),value.captionEdits||[]]);
function cursor(doc:PMNode,position:number):{id:string|null,offset:number}|null{let result:{id:string|null,offset:number}|null=null;doc.forEach((node,pos)=>{if(position>=pos+1&&position<=pos+node.nodeSize-1){const source=manuscriptSource(node),utf16=blockSourceOffset(node,position-pos-1);result={id:node.type.name==='manuscript_title'?null:node.attrs.block_id,offset:Array.from(source.slice(0,utf16)).length};}});return result;}
function mappedSelection(before:PMNode,next:PMNode,selection:Selection):Selection{
  if(selection instanceof AllSelection)return new AllSelection(next);
  const at=(position:number,bias:-1|1)=>{const point=cursor(before,position);if(!point)return 1;if(point.id===null)return 1+Math.min(next.firstChild!.content.size,Array.from(next.firstChild!.textContent).slice(0,point.offset).join('').length);return continuousPosition(next,point.id,point.offset,bias)??Math.min(next.content.size-1,position);};
  const from=at(selection.from,-1),to=at(selection.to,1);return selection instanceof NodeSelection&&next.nodeAt(from)?.isAtom?NodeSelection.create(next,from):TextSelection.create(next,from,to);
}

// A single editing authority. Scientific nodes are exact-source projections;
// saved text never comes from HTML, Markdown serialization or review widgets.
export function ContinuousManuscript(props:ContinuousManuscriptProps){
  const mount=useRef<HTMLDivElement>(null),editor=useRef<EditorView|null>(null),latest=useRef(props);latest.current=props;
  const [chosen,setChosen]=useState<Chosen|null>(null),[field,setField]=useState(0),[fieldText,setFieldText]=useState(''),[error,setError]=useState(''),[pending,setPending]=useState<Incoming|null>(null),[markerErrors,setMarkerErrors]=useState<string[]>([]);
  const accepted=useRef(''),acceptedVersion=useRef(props.version),emitted=useRef(''),external=useRef<Incoming|null>(null),conflict=useRef<Incoming|null>(null),alive=useRef(false);
  const handledFocus=useRef(''),captionEditors=useRef(new Set<CaptionEditorHandle>());
  const composing=()=>!!editor.current?.composing||Array.from(captionEditors.current).some(child=>child.view.composing);
  const choose=(item:Chosen|null)=>{setChosen(item);setField(0);setFieldText(item?item.token.source.slice(item.token.fields[0].start,item.token.fields[0].end):'');setError('');};
  const decorationResult=(doc:PMNode)=>{const identity=latest.current.documentKey,scope=latest.current.reviewScope,marks=manuscriptDecorations(doc,latest.current.marks||[],{activeKeys:latest.current.activeReviewKeys,interactive:!!latest.current.onReviewActivate}),figures=manuscriptFigureDecorations(doc,latest.current.figures||[],ref=>{if(latest.current.documentKey===identity)latest.current.onOpenFigure?.(ref);},{
    marks:figure=>(latest.current.reviewItems||[]).filter(item=>item.available&&item.caption?.key===figure.key&&item.caption.componentIdentity===figure.componentIdentity&&item.caption.caption===figure.caption).map(item=>({key:item.key,label:item.label,start:item.caption!.start,end:item.caption!.end,quote:item.caption!.quote})),
    selectCaption:(figure,element)=>{if(latest.current.documentKey!==identity||latest.current.reviewScope!==scope)return;const range=captionTextRange(element,figure.caption);latest.current.onSelection(null);latest.current.onCaptionSelection?.(range&&figure.componentIdentity?{...range,key:figure.key,componentId:figure.ref.id,componentIdentity:figure.componentIdentity,caption:figure.caption}:null);},
    captionEditing:{enabled:latest.current.mode==='edit',canEdit:()=>latest.current.mode==='edit'&&isEditable(latest.current)&&latest.current.captionEditable!==false,owns:()=>alive.current&&latest.current.documentKey===identity,activeKeys:()=>latest.current.activeReviewKeys||[],register:handle=>captionEditors.current.add(handle),unregister:handle=>captionEditors.current.delete(handle),onCompositionEnd:()=>{requestAnimationFrame(()=>{if(!alive.current||latest.current.documentKey!==identity)return;const incoming=external.current;external.current=null;if(incoming)consider(incoming);});}},
    activeKeys:latest.current.activeReviewKeys,scope,activate:keys=>{if(latest.current.documentKey===identity&&latest.current.reviewScope===scope){latest.current.onSelection(null);latest.current.onReviewActivate?.(keys);}},
  });return {set:marks.set.add(doc,figures.set.find()),errors:[...marks.errors,...figures.errors]};};
  const markers=(view:EditorView)=>setMarkerErrors(decorationResult(view.state.doc).errors);
  const publish=(view:EditorView)=>{const result=documentProjection(view.state.doc);emitted.current=contentKey(result);latest.current.onChange(result.blocks,result.title,result.captionEdits);};
  const replace=(incoming:Incoming,historyEdit:boolean)=>{
    const view=editor.current;if(!view)return;const doc=continuousDocument(incoming.blocks,incoming.title,true,incoming.captionEdits||[],latest.current.figures||[]);
    if(historyEdit){const tr=closeHistory(view.state.tr).replaceWith(0,view.state.doc.content.size,doc.content).setMeta('caption_edit',true);view.dispatch(tr.setSelection(mappedSelection(view.state.doc,tr.doc,view.state.selection)));}
    else {view.updateState(EditorState.create({doc,selection:mappedSelection(view.state.doc,doc,view.state.selection),plugins:view.state.plugins}));for(const child of captionEditors.current)child.sync();markers(view);latest.current.onSelection(null);}
    choose(null);
  };
  const consider=(incoming:Incoming)=>{
    const view=editor.current;if(!view)return;const key=contentKey(incoming),current=contentKey(documentProjection(view.state.doc));
    if(key===current){if(!composing())refreshCaptionBaseline(view,latest.current.figures||[],incoming.captionEdits||[]);if(!external.current&&!conflict.current&&latest.current.version!==acceptedVersion.current){accepted.current=key;acceptedVersion.current=latest.current.version;setPending(null);}return;}
    if(composing()){external.current=incoming;conflict.current=incoming;setPending(incoming);return;}
    // Same saved receipt may rebase caption before/text without changing the
    // user's desired characters. Retain parent history and child caret.
    if(contentKey({...incoming,captionEdits:[]})===contentKey({...documentProjection(view.state.doc),captionEdits:[]})&&refreshCaptionBaseline(view,latest.current.figures||[],incoming.captionEdits||[])){
      if(latest.current.version!==acceptedVersion.current){accepted.current=contentKey({...incoming,captionEdits:[]});acceptedVersion.current=latest.current.version;}
      emitted.current=key;external.current=null;conflict.current=null;setPending(null);for(const child of captionEditors.current)child.sync();markers(view);return;
    }
    if(current!==accepted.current&&key!==emitted.current){conflict.current=incoming;setPending(incoming);return;}
    replace(incoming,false);accepted.current=key;acceptedVersion.current=latest.current.version;emitted.current=key;conflict.current=null;setPending(null);
  };
  useLayoutEffect(()=>{
    alive.current=true;const ownedKey=props.documentKey;let frame:number|undefined;
    const nodeViews=Object.fromEntries(Object.keys(scientificLabels).map(kind=>[`scientific_${kind}`,(initial:PMNode,view:EditorView,getPos:()=>number|undefined):NodeView=>{
      let node=initial;const dom=document.createElement('span');dom.contentEditable='false';dom.className=`scientific-node scientific-${kind}`;dom.dataset.scientificKind=kind;dom.tabIndex=0;dom.setAttribute('role','button');
      const render=()=>{dom.textContent=node.attrs.source;dom.title=node.attrs.source;dom.setAttribute('aria-label',`${scientificLabels[kind as ScientificKind]}：${node.attrs.source}`);};render();
      const open=()=>{if(latest.current.documentKey!==ownedKey)return;const pos=getPos();if(pos===undefined)return;const current=view.state.doc.nodeAt(pos);if(!current)return;const $pos=view.state.doc.resolve(pos),block=$pos.parent;if(block.type.name!=='source_block')return;const token=scientificTokens(current.attrs.source)[0];if(!token)return;const start=blockSourceOffset(block,pos-$pos.start());view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc,pos)));choose({blockId:block.attrs.block_id,start,end:start+token.source.length,token});};
      const down=(event:MouseEvent)=>{event.preventDefault();view.focus();open();};const key=(event:KeyboardEvent)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open();}};dom.addEventListener('mousedown',down);dom.addEventListener('keydown',key);
      return {dom,stopEvent:event=>event.type==='mousedown'||(event.type==='keydown'&&['Enter',' '].includes((event as KeyboardEvent).key)),ignoreMutation:()=>true,update(current){if(current.type!==node.type)return false;node=current;render();return true;},selectNode(){dom.classList.add('ProseMirror-selectednode');},deselectNode(){dom.classList.remove('ProseMirror-selectednode');},destroy(){dom.removeEventListener('mousedown',down);dom.removeEventListener('keydown',key);}};
    }]));
    const enter=splitBlockAs(()=>({type:continuousSchema.nodes.source_block,attrs:{block_id:newManuscriptBlockId(),kind:'paragraph',data:{}}}));
    const view=new EditorView(mount.current!,{state:EditorState.create({doc:continuousDocument(props.blocks,props.title,true,props.captionEdits||[],props.figures||[]),plugins:[history(),stableBlockIdentities(),preserveCaptionEdits(),new Plugin({props:{decorations:state=>decorationResult(state.doc).set}}),keymap({
      'Mod-z':undo,'Mod-Shift-z':redo,'Mod-y':redo,
      // A native document boundary can stop at a noneditable figure widget
      // while the parent still selects a scientific atom. Resolve the boundary
      // in this document so the next input cannot replace that stale selection.
      'Mod-Home':(state,dispatch)=>{if(dispatch)dispatch(state.tr.setSelection(TextSelection.atStart(state.doc)).scrollIntoView());return true;},
      'Mod-End':(state,dispatch)=>{if(dispatch)dispatch(state.tr.setSelection(TextSelection.atEnd(state.doc)).scrollIntoView());return true;},
      'Shift-Mod-Home':(state,dispatch)=>{if(dispatch)dispatch(state.tr.setSelection(TextSelection.create(state.doc,state.selection.anchor,TextSelection.atStart(state.doc).from)).scrollIntoView());return true;},
      'Shift-Mod-End':(state,dispatch)=>{if(dispatch)dispatch(state.tr.setSelection(TextSelection.create(state.doc,state.selection.anchor,TextSelection.atEnd(state.doc).to)).scrollIntoView());return true;},
      Enter:(state,dispatch,view)=>{if(state.selection.$from.parent.type.name==='manuscript_title'){if(dispatch)dispatch(state.tr.setSelection(TextSelection.create(state.doc,state.doc.firstChild!.nodeSize+1)));return true;}return enter(state,dispatch,view);},
      'Shift-Enter':(state,dispatch)=>{if(state.selection.$from.parent.type.name==='manuscript_title')return true;if(dispatch)dispatch(state.tr.insertText('\n'));return true;},
      Backspace:state=>state.selection.empty&&state.selection.$from.parent.type.name==='source_block'&&state.selection.$from.parentOffset===0&&state.selection.$from.index(0)===1,
      Delete:state=>state.selection.empty&&state.selection.$from.parent.type.name==='manuscript_title'&&state.selection.$from.parentOffset===state.selection.$from.parent.content.size,
    }),keymap(baseKeymap)]}),nodeViews,
      editable:()=>isEditable(latest.current),attributes:{role:'textbox','aria-label':'连续稿件','aria-multiline':'true',class:'continuous-manuscript-document'},
      clipboardTextSerializer:slice=>continuousClipboard(slice.content),
      handlePaste:(view,event)=>{
        if(!isEditable(latest.current))return true;const data=event.clipboardData,text=data?.getData('text/plain');if(text===undefined)return false;
        syncNativeSelection(view);
        const structured=data?.getData('application/x-research-partner-blocks');
        if(structured){try{const blocks=JSON.parse(structured);if(!Array.isArray(blocks)||!blocks.length||blocks.some(b=>typeof b.text!=='string'||typeof b.kind!=='string'))throw Error();
          // A pasted paragraph has a new identity. The text-write contract can
          // carry its text/structure, but cannot confer the copied paragraph's
          // saved source or opaque metadata on that new identity. Existing
          // destination and source nodes keep their full metadata in PM.
          const nodes=continuousDocument(blocks.map(b=>({id:newManuscriptBlockId(),kind:b.kind,text:b.text,...(b.kind==='heading'&&b.level!==undefined?{level:b.level}:{})})),'').content.content.slice(1);
          view.dispatch(view.state.tr.replaceSelection(new Slice(Fragment.fromArray(nodes),1,1)));return true;
        }catch{setError('剪贴板段落结构无效；未覆盖稿件。');return true;}}
        if(view.state.selection.$from.parent.type.name==='manuscript_title'&&text.includes('\n')){setError('标题不接受多行粘贴；正文和剪贴板仍保留。');return true;}
        // Blank lines outside scientific tokens delimit paragraphs; single
        // newlines remain exact source soft breaks (including TeX/CRLF).
        const paragraphs=plainSourceParagraphs(text);
        if(paragraphs.length>1){const nodes=continuousDocument(paragraphs.map(text=>({id:newManuscriptBlockId(),kind:'paragraph',text})),'').content.content.slice(1);view.dispatch(view.state.tr.replaceSelection(new Slice(Fragment.fromArray(nodes),1,1)));}
        else view.dispatch(view.state.tr.insertText(text));return true;
      },
      handleDOMEvents:{
        click:(_view,event)=>{if(latest.current.documentKey!==ownedKey)return false;const keys:string[]=[];for(let element=event.target instanceof Element?event.target:null;element&&element!==view.dom;element=element.parentElement){const key=element.getAttribute('data-review-key');if(key&&!keys.includes(key)&&latest.current.marks?.some(mark=>reviewMarkKey(mark)===key))keys.push(key);}if(keys.length)latest.current.onReviewActivate?.(keys);return false;},
        // Native pointer selection can precede PM's asynchronous selectionchange
        // observer. Structural keymaps must consume the visible native caret,
        // rather than a stale title/block selection from the previous event.
        keydown:(view,event)=>{const key=event as KeyboardEvent,target=event.target instanceof Element?event.target:null,reviewKey=target?.getAttribute('data-review-key');if(!key.isComposing&&!view.composing&&['Enter',' '].includes(key.key)&&target?.getAttribute('role')==='button'&&reviewKey&&latest.current.marks?.some(mark=>reviewMarkKey(mark)===reviewKey)){if(latest.current.onReviewActivate){event.preventDefault();latest.current.onReviewActivate([reviewKey]);return true;}}if(!key.isComposing&&!view.composing&&['Enter','Backspace','Delete'].includes(key.key))syncNativeSelection(view);return false;},
        copy:(view,event)=>{syncNativeSelection(view);const e=event as ClipboardEvent;if(view.state.selection.empty||!e.clipboardData)return false;const selection=continuousSelection(view.state.doc,view.state.selection.from,view.state.selection.to),slice=view.state.selection.content();e.clipboardData.setData('text/plain',continuousClipboard(slice.content));if(selection)e.clipboardData.setData('application/x-research-partner-blocks',JSON.stringify(selection.segments.map(segment=>({...continuousProjection(view.state.doc).blocks.find(b=>b.id===segment.block_id),text:segment.quote}))));event.preventDefault();return true;},
        cut:(view,event)=>{if(!isEditable(latest.current))return true;const handler=view.props.handleDOMEvents?.copy;if(!handler?.(view,event))return false;view.dispatch(view.state.tr.deleteSelection());return true;},
        compositionend:()=>{frame=requestAnimationFrame(()=>{if(!alive.current||latest.current.documentKey!==ownedKey)return;const incoming=external.current;external.current=null;if(incoming)consider(incoming);});return false;},
      },
      dispatchTransaction(tr){
        if(latest.current.documentKey!==ownedKey)return;
        if(tr.docChanged&&!isEditable(latest.current))return;
        if(tr.docChanged||tr.selectionSet)latest.current.onCaptionSelection?.(null);
        if(tr.docChanged&&!isHistoryTransaction(tr)&&tr.doc.childCount!==view.state.doc.childCount)closeHistory(tr);
        const oldKey=contentKey(documentProjection(view.state.doc)),result=view.state.applyTransaction(tr);view.updateState(result.state);for(const child of captionEditors.current)child.sync();
        const nextKey=contentKey(documentProjection(view.state.doc));if(oldKey!==nextKey)publish(view);
        latest.current.onSelection(tr.getMeta('caption_edit')?null:continuousSelection(view.state.doc,view.state.selection.from,view.state.selection.to));markers(view);
      },
    });editor.current=view;accepted.current=contentKey(documentProjection(view.state.doc));acceptedVersion.current=props.version;emitted.current=accepted.current;conflict.current=null;setPending(null);choose(null);for(const child of captionEditors.current)child.sync();markers(view);
    return()=>{alive.current=false;if(frame!==undefined)cancelAnimationFrame(frame);view.destroy();captionEditors.current.clear();if(editor.current===view)editor.current=null;external.current=null;};
  },[props.documentKey]);
  useLayoutEffect(()=>{
    const host=mount.current?.closest<HTMLElement>('.continuous-manuscript');
    if(!host)return;
    return keepCaptionLineUnderPointer(host,composing);
  },[props.documentKey]);
  const inputKey=contentKey({blocks:props.blocks,title:props.title,captionEdits:props.captionEdits});
  const captionSourcesKey=JSON.stringify((props.figures||[]).map(({key,caption,ref,after_block_id,componentIdentity})=>[key,caption,ref,after_block_id,componentIdentity]));
  useLayoutEffect(()=>{consider({blocks:props.blocks,title:props.title,captionEdits:props.captionEdits});},[inputKey,props.version,props.documentKey,captionSourcesKey]);
  useLayoutEffect(()=>{const view=editor.current;if(view){view.setProps({editable:()=>isEditable(latest.current)});markers(view);view.updateState(view.state);for(const child of captionEditors.current)child.sync();
    // Highlighting must not recreate the read-only widget and destroy the
    // user's native caption selection. Only display attributes change here.
    for(const span of view.dom.querySelectorAll<HTMLElement>('figcaption [data-review-key]')){
      const active=props.activeReviewKeys?.includes(span.dataset.reviewKey!);if(active)span.dataset.reviewActive='true';else delete span.dataset.reviewActive;
    }
  }},[props.mode,props.editable,props.captionEditable,props.marks,props.figures,props.activeReviewKeys,props.reviewItems,props.onReviewActivate]);
  useLayoutEffect(()=>{
    const view=editor.current,focus=props.reviewFocus;if(!view||!focus)return;
    const signature=JSON.stringify([props.documentKey,props.reviewScope,focus.requestId]);if(signature===handledFocus.current)return;handledFocus.current=signature;
    const result=(status:'located'|'unavailable',reason?:string)=>latest.current.onReviewNavigationResult?.({requestId:focus.requestId,scope:focus.scope,key:focus.item.key,status,...(reason?{reason}:{})});
    if(!props.reviewScope||focus.scope!==props.reviewScope){result('unavailable','项目、稿件或候选基线已变化；未定位旧请求。');return;}
    if(composing()||external.current||conflict.current){result('unavailable','正在输入或比较外部保存版；当前输入保留，请稍后明确定位。');return;}
    if(focus.item.caption){
      const target=focus.item.caption,current=props.reviewItems?.find(item=>item.key===focus.item.key&&item.available),figures=props.figures?.filter(figure=>figure.key===target.key)||[];
      if(!current?.caption||JSON.stringify(current.caption)!==JSON.stringify(target)||figures.length!==1||figures[0].componentIdentity!==target.componentIdentity||figures[0].caption!==target.caption){result('unavailable','图注或固定来源已变化；保留当前草稿，请明确重新定位。');return;}
      const figure=Array.from(view.dom.querySelectorAll<HTMLElement>('.manuscript-saved-figure')).find(element=>element.dataset.componentKey===target.key),caption=figure?.querySelector<HTMLElement>('figcaption');
      const mark=caption&&Array.from(caption.querySelectorAll<HTMLElement>('[data-review-key]')).find(element=>element.dataset.reviewKey===focus.item.key);
      if(!caption||!mark){result('unavailable','当前稿内没有准确的图注位置；未打开其他对象。');return;}
      const selectedDocument=view.state.doc,documentKey=props.documentKey;
      mark.focus({preventScroll:true});mark.scrollIntoView({block:'nearest',inline:'nearest'});latest.current.onSelection(null);result('located');
      const window=view.dom.ownerDocument.defaultView!,frame=window.requestAnimationFrame(()=>{
        if(editor.current===view&&latest.current.documentKey===documentKey&&latest.current.reviewScope===focus.scope&&latest.current.reviewFocus?.requestId===focus.requestId&&view.state.doc===selectedDocument&&mark.isConnected&&latest.current.reviewItems?.some(item=>item.key===focus.item.key&&item.available&&JSON.stringify(item.caption)===JSON.stringify(target)))mark.scrollIntoView({block:'nearest',inline:'nearest'});
      });
      return()=>window.cancelAnimationFrame(frame);
    }
    const range=reviewFocusRange(view.state.doc,focus.item);
    if('reason' in range){result('unavailable',range.reason);return;}
    if(!focus.item.segments.every(segment=>props.marks?.some(mark=>reviewMarkKey(mark)===focus.item.key&&mark.block_id===segment.block_id&&mark.start===segment.start&&mark.end===segment.end&&mark.quote===segment.quote))){result('unavailable','当前审阅项与原选区已不一致，请明确重新定位。');return;}
    view.focus();view.dispatch(view.state.tr.setSelection(TextSelection.create(view.state.doc,range.from,range.to)).setMeta('addToHistory',false).scrollIntoView());
    const selectedDocument=view.state.doc,selectedRange=view.state.selection,documentKey=props.documentKey;
    result('located');
    // The workdesk's navigation notice can resize the document scrollport.
    // Finish this explicit navigation after that layout, without moving a
    // selection that the user changed or borrowing a newer request's scope.
    const window=view.dom.ownerDocument.defaultView!;
    const frame=window.requestAnimationFrame(()=>{
      if(editor.current!==view||latest.current.documentKey!==documentKey||latest.current.reviewScope!==focus.scope||latest.current.reviewFocus?.requestId!==focus.requestId||view.state.doc!==selectedDocument||!view.state.selection.eq(selectedRange))return;
      view.dispatch(view.state.tr.setMeta('addToHistory',false).scrollIntoView());
    });
    return()=>window.cancelAnimationFrame(frame);
  },[props.reviewFocus,props.reviewScope,props.documentKey,props.version]);
  const insert=(kind:ScientificKind)=>{const view=editor.current;if(!view||!isEditable(props))return;if(view.state.selection.$from.parent.type.name!=='source_block'){setError('请选择正文中的插入位置；标题和原稿保留。');return;}const sources:Record<ScientificKind,string>={formula:'\\( \\)',citation:'[@]',figure:'![]()',table:'|  |  |\n| --- | --- |\n|  |  |',reference:'\\ref{}'},source=sources[kind],node=continuousSchema.node(`scientific_${kind}`,{source,syntax:scientificTokens(source)[0].syntax}),position=view.state.selection.from,tr=view.state.tr.replaceSelectionWith(node);view.dispatch(tr.setSelection(NodeSelection.create(tr.doc,position)));const $pos=view.state.doc.resolve(position),start=blockSourceOffset($pos.parent,position-$pos.start());choose({blockId:$pos.parent.attrs.block_id,start,end:start+source.length,token:scientificTokens(source)[0]});};
  const applyField=()=>{
    const view=editor.current;if(!view||!chosen||!isEditable(props))return;const value=documentProjection(view.state.doc),block=value.blocks.find(b=>b.id===chosen.blockId);
    if(!block||block.text.slice(chosen.start,chosen.end)!==chosen.token.source){setError('此科学节点已改变；字段草稿保留，请重新选择当前节点。');return;}
    const replacement=replaceScientificField(chosen.token,chosen.token.fields[field],fieldText),tokens=scientificTokens(replacement);
    if(tokens.length!==1||tokens[0].start!==0||tokens[0].end!==replacement.length||tokens[0].kind!==chosen.token.kind||tokens[0].syntax!==chosen.token.syntax){setError('字段改变了科学节点边界；原稿保留，请检查源分隔符。');return;}
    block.text=block.text.slice(0,chosen.start)+replacement+block.text.slice(chosen.end);replace(value,true);choose({...chosen,end:chosen.start+replacement.length,token:tokens[0]});view.focus();
  };
  const figureMatches=chosen?.token.kind==='figure'?(props.figureRefs||[]).filter(r=>r.source===chosen.token.source&&Number.isSafeInteger(r.revision)&&r.revision>0&&!!r.id):[];
  return <section className="continuous-manuscript" aria-label="连续科研稿件" data-mode={props.mode}>
    {isEditable(props)&&<div role="toolbar" aria-label="稿件科学内容">{(['formula','citation','figure','table'] as const).map(kind=><button type="button" key={kind} onMouseDown={event=>event.preventDefault()} onClick={()=>insert(kind)}>插入{scientificLabels[kind]}</button>)}</div>}
    {pending&&<div role="alert">外部保存版已变化；当前输入保留。<button type="button" disabled={!isEditable(props)||composing()} onClick={()=>{const next=pending;accepted.current=contentKey(next);acceptedVersion.current=props.version;setPending(null);external.current=null;conflict.current=null;replace(next,true);}}>采用外部保存版（可撤销）</button><button type="button" disabled={!isEditable(props)} onClick={()=>{setPending(null);external.current=null;conflict.current=null;if(editor.current)publish(editor.current);}}>保留当前编辑</button></div>}
    {markerErrors.map(message=><p role="status" key={message}>{message}</p>)}
    <div ref={mount}/>
    {chosen&&<aside aria-label="连续稿件科学节点">
      <strong>{scientificLabels[chosen.token.kind]}</strong><button type="button" onClick={()=>choose(null)}>关闭科学节点</button>
      {isEditable(props)?<><label>科学节点字段<select aria-label="连续科学节点字段" value={field} onChange={event=>{const index=Number(event.target.value);setField(index);const f=chosen.token.fields[index];setFieldText(chosen.token.source.slice(f.start,f.end));setError('');}}>{chosen.token.fields.map((f,index)=><option key={index} value={index}>{f.label}</option>)}</select></label><textarea aria-label={chosen.token.fields[field].label} value={fieldText} onChange={event=>setFieldText(event.target.value)}/><button type="button" onClick={applyField}>应用科学节点修改</button></>:<pre>{chosen.token.source}</pre>}
      {figureMatches.length===1&&props.onOpenFigure&&<button type="button" onClick={()=>props.onOpenFigure?.(figureMatches[0])}>打开固定来源图</button>}
      {chosen.token.kind==='figure'&&figureMatches.length!==1&&<p>未登记唯一固定图来源；源字符保留，未读取最新图。</p>}
      {error&&<p role="alert">{error}</p>}
    </aside>}
    {!chosen&&error&&<p role="alert">{error}</p>}
  </section>;
}
function isEditable(props:ContinuousManuscriptProps){return props.mode!=='read'&&(props.editable??true);}
function syncNativeSelection(view:EditorView){
  const selection=view.dom.ownerDocument.getSelection();if(!selection?.anchorNode||!selection.focusNode||!view.dom.contains(selection.anchorNode)||!view.dom.contains(selection.focusNode))return;
  const anchor=view.posAtDOM(selection.anchorNode,selection.anchorOffset),head=view.posAtDOM(selection.focusNode,selection.focusOffset);
  const next=TextSelection.between(view.state.doc.resolve(anchor),view.state.doc.resolve(head));if(!next.eq(view.state.selection))view.dispatch(view.state.tr.setSelection(next));
}
export function plainSourceParagraphs(text:string):string[]{
  const protectedRanges=scientificTokens(text).map(token=>[token.start,token.end]);
  const fences=/^ {0,3}(`{3,}|~{3,})[^\n]*(?:\n|$)/gm;let fence:RegExpExecArray|null;
  while((fence=fences.exec(text))){const marker=fence[1][0],end=new RegExp(`^ {0,3}${marker}{${fence[1].length},}[ \\t\\r]*$`,'gm');end.lastIndex=fences.lastIndex;const closing=end.exec(text);const stop=closing?closing.index+closing[0].length:text.length;protectedRanges.push([fence.index,stop]);fences.lastIndex=stop;}
  const paragraphs:string[]=[];let at=0;const boundaries=/(?:\r\n|\n){2,}/g;let match:RegExpExecArray|null;
  while((match=boundaries.exec(text))){if(protectedRanges.some(([start,end])=>match!.index>=start&&match!.index<end))continue;paragraphs.push(text.slice(at,match.index));at=match.index+match[0].length;}
  paragraphs.push(text.slice(at));return paragraphs;
}

// A horizontal drag within a visible caption line expresses a text range, not
// a request to scroll merely because that line is in the browser's edge band.
// Keep native hit testing/Selection. Release immediately on a vertical gesture,
// a clipped boundary, explicit scrolling/input, or a changed layout/document.
function keepCaptionLineUnderPointer(host:HTMLElement,composing:()=>boolean){
  const doc=host.ownerDocument,win=doc.defaultView!;
  type Port={element:HTMLElement,top:number,left:number,rect:DOMRect,width:number,height:number,scrollWidth:number,scrollHeight:number};
  let gesture:{caption:HTMLElement,line:Range,rect:DOMRect,captionRect:DOMRect,ports:Port[],startX:number,moved:boolean}|null=null;
  const stop=()=>{gesture=null;};
  const rectSame=(a:DOMRect,b:DOMRect)=>a.x===b.x&&a.y===b.y&&a.width===b.width&&a.height===b.height;
  const valid=()=>{
    if(!gesture||!gesture.caption.isConnected||composing())return false;
    const {caption,line,rect,captionRect,ports}=gesture;
    if(!host.contains(caption)||!caption.isContentEditable)return false;
    let dy=0,dx=0;
    for(const p of ports){
      if(!rectSame(p.rect,p.element.getBoundingClientRect())||p.width!==p.element.clientWidth||p.height!==p.element.clientHeight||p.scrollWidth!==p.element.scrollWidth||p.scrollHeight!==p.element.scrollHeight)return false;
      dy+=p.element.scrollTop-p.top;dx+=p.element.scrollLeft-p.left;
    }
    const current=line.getBoundingClientRect(),box=caption.getBoundingClientRect();
    return current.x+dx===rect.x&&current.y+dy===rect.y&&current.height===rect.height&&box.x+dx===captionRect.x&&box.y+dy===captionRect.y&&box.width===captionRect.width&&box.height===captionRect.height;
  };
  const down=(event:PointerEvent)=>{
    stop();if(event.pointerType!=='mouse'||event.button!==0||event.detail>1||event.shiftKey||event.ctrlKey||event.metaKey||event.altKey||composing())return;
    const caption=event.target instanceof Element?event.target.closest<HTMLElement>('figcaption[contenteditable=true]'):null;
    if(!caption||!host.contains(caption))return;
    const line=doc.caretRangeFromPoint?.(event.clientX,event.clientY);
    if(!line||!caption.contains(line.startContainer))return;
    const rect=line.getBoundingClientRect(),ports:Port[]=[];
    if(!rect.height||event.clientY<rect.top||event.clientY>rect.bottom)return;
    for(let p=caption.parentElement;p;p=p.parentElement){
      const style=win.getComputedStyle(p);
      if(/auto|scroll|hidden/.test(style.overflowY+style.overflowX)&&(p.scrollHeight>p.clientHeight||p.scrollWidth>p.clientWidth)){
        const box=p.getBoundingClientRect();
        if(rect.top<box.top+p.clientTop||rect.bottom>box.top+p.clientTop+p.clientHeight||event.clientX<box.left||event.clientX>box.right)return;
        ports.push({element:p,top:p.scrollTop,left:p.scrollLeft,rect:box,width:p.clientWidth,height:p.clientHeight,scrollWidth:p.scrollWidth,scrollHeight:p.scrollHeight});
      }
    }
    if(ports.length)gesture={caption,line,rect,captionRect:caption.getBoundingClientRect(),ports,startX:event.clientX,moved:false};
  };
  const move=(event:PointerEvent)=>{
    if(!gesture)return;
    if(event.buttons!==1||!valid()||event.clientY<gesture.rect.top||event.clientY>gesture.rect.bottom||gesture.ports.some(p=>event.clientX<p.rect.left||event.clientX>p.rect.right)){stop();return;}
    if(event.clientX!==gesture.startX)gesture.moved=true;
  };
  const scroll=(event:Event)=>{
    if(!gesture)return;
    if(!gesture.moved||!valid()){stop();return;}
    const port=gesture.ports.find(p=>p.element===event.target);
    if(port){port.element.scrollTop=port.top;port.element.scrollLeft=port.left;}
    else stop();
  };
  host.addEventListener('pointerdown',down,true);doc.addEventListener('pointermove',move,true);doc.addEventListener('scroll',scroll,true);
  const cancel=['pointerup','pointercancel','wheel','keydown','beforeinput','compositionstart'] as const;
  for(const type of cancel)doc.addEventListener(type,stop,true);
  win.addEventListener('blur',stop);
  return()=>{stop();host.removeEventListener('pointerdown',down,true);doc.removeEventListener('pointermove',move,true);doc.removeEventListener('scroll',scroll,true);for(const type of cancel)doc.removeEventListener(type,stop,true);win.removeEventListener('blur',stop);};
}
