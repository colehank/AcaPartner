import {useLayoutEffect,useRef,useState} from 'react';
import {EditorState,TextSelection,NodeSelection} from 'prosemirror-state';
import {EditorView,type NodeView} from 'prosemirror-view';
import {keymap} from 'prosemirror-keymap';
import {history,undo,redo,isHistoryTransaction} from 'prosemirror-history';
import {baseKeymap,newlineInCode} from 'prosemirror-commands';
import {manuscriptSchema,manuscriptDocument,manuscriptSource,positionAtSourceOffset,sourceOffsetAtPosition,sourceAnchor,scientificTokens,scientificLabels,scientificSummary,markdownTableRows,replaceScientificField,type ScientificToken,type ScientificKind} from './ScientificManuscript';
import './scientific-manuscript.css';

export type PaperSelection={block_id:string,start:number,end:number,quote:string};
type SelectedNode={token:ScientificToken,start:number,end:number};
const insertSources:Record<Exclude<ScientificKind,'reference'>,string>={formula:'\\( \\)',citation:'[@]',figure:'![]()',table:'|  |  |\n| --- | --- |\n|  |  |'};

// The existing block source is authoritative. Rich nodes are a lossless editing
// projection; no ordinary Markdown serializer can rewrite that source.
export function PaperSourceEditor({block,label,onChange,onSelection}:{block:{id:string,kind:string,text:string},label:string,onChange:(text:string)=>void,onSelection:(s:PaperSelection|null)=>void}){
  const mount=useRef<HTMLDivElement>(null),editor=useRef<EditorView|null>(null);
  const [rich,setRich]=useState(false),[selected,setSelected]=useState<SelectedNode|null>(null),[fieldIndex,setFieldIndex]=useState(0),[fieldText,setFieldText]=useState(''),[error,setError]=useState('');
  const callbacks=useRef({onChange,onSelection});callbacks.current={onChange,onSelection};
  const mode=useRef(rich);mode.current=rich;
  const choose=(item:SelectedNode|null)=>{setSelected(item);setFieldIndex(0);setFieldText(item?item.token.source.slice(item.token.fields[0].start,item.token.fields[0].end):'');setError('');};
  const rebuild=(text:string,start:number,end=start,addToHistory=true)=>{
    const view=editor.current;if(!view)return;
    const doc=manuscriptDocument(text,block,mode.current),tr=view.state.tr.replaceWith(0,view.state.doc.content.size,doc.content);
    tr.setSelection(TextSelection.create(tr.doc,positionAtSourceOffset(tr.doc,start,-1),positionAtSourceOffset(tr.doc,end,1)));if(!addToHistory)tr.setMeta('addToHistory',false);view.dispatch(tr);
  };
  useLayoutEffect(()=>{
    let queued=false,alive=true;
    const nodeViews=Object.fromEntries(Object.keys(scientificLabels).map(kind=>[`scientific_${kind}`,(node:any,view:EditorView,getPos:()=>number|undefined):NodeView=>{
      const dom=document.createElement('span');dom.className=`scientific-node scientific-${kind}`;dom.contentEditable='false';dom.dataset.scientificKind=kind;dom.tabIndex=0;dom.setAttribute('role','button');
      const labelNode=document.createElement('span');labelNode.className='scientific-node-label';labelNode.textContent=scientificLabels[kind as ScientificKind];dom.append(labelNode);
      const content=document.createElement('span');content.className='scientific-node-content';dom.append(content);
      const render=(current:any)=>{const token=scientificTokens(current.attrs.source)[0],summary=token?scientificSummary(token):current.attrs.source;content.textContent=summary;
        if(token?.syntax==='markdown-table'){const table=document.createElement('table');table.className='scientific-table-preview';markdownTableRows(token.source).forEach((row,r)=>{if(r===1)return;const tr=document.createElement('tr');row.forEach(cell=>{const td=document.createElement(r===0?'th':'td');td.textContent=cell.text;tr.append(td);});table.append(tr);});content.append(table);}
        dom.title=current.attrs.source;dom.setAttribute('aria-label',`${scientificLabels[kind as ScientificKind]}：${summary}`);};render(node);
      const open=()=>{const pos=getPos();if(pos===undefined)return;const current=view.state.doc.nodeAt(pos);if(!current)return;const token=scientificTokens(current.attrs.source)[0];if(!token)return;const start=sourceOffsetAtPosition(view.state.doc,pos);view.dispatch(view.state.tr.setSelection(NodeSelection.create(view.state.doc,pos)));choose({token,start,end:start+current.attrs.source.length});};
      const down=(event:MouseEvent)=>{event.preventDefault();view.focus();open();};dom.addEventListener('mousedown',down);
      const key=(event:KeyboardEvent)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();view.focus();open();}};dom.addEventListener('keydown',key);
      return {dom,stopEvent:event=>event.type==='mousedown'||(event.type==='keydown'&&((event as KeyboardEvent).key==='Enter'||(event as KeyboardEvent).key===' ')),ignoreMutation:()=>true,selectNode(){dom.classList.add('ProseMirror-selectednode');},deselectNode(){dom.classList.remove('ProseMirror-selectednode');},update(current){if(current.type!==node.type)return false;node=current;render(current);return true;},destroy(){dom.removeEventListener('mousedown',down);dom.removeEventListener('keydown',key);}};
    }]));
    const view=new EditorView(mount.current!,{state:EditorState.create({schema:manuscriptSchema,doc:manuscriptDocument(block.text,block,mode.current),plugins:[history(),keymap({'Mod-z':undo,'Mod-Shift-z':redo,'Mod-y':redo,Enter:newlineInCode}),keymap(baseKeymap)]}),
      nodeViews,attributes:{role:'textbox','aria-label':label,'aria-multiline':'true',class:'paper-source-document'},
      clipboardTextSerializer:slice=>manuscriptSource(slice.content),
      handleDOMEvents:{beforeinput:(view,event)=>{
        const input=event as InputEvent;
        if(input.inputType!=='insertText'||input.data===null||input.isComposing)return false;
        const target=input.getTargetRanges?.()[0],selection=window.getSelection();
        const anchor=target?.startContainer||selection?.anchorNode,focus=target?.endContainer||selection?.focusNode;
        if(!anchor||!focus||!view.dom.contains(anchor)||!view.dom.contains(focus))return false;
        const from=view.posAtDOM(anchor,target?.startOffset??selection!.anchorOffset),to=view.posAtDOM(focus,target?.endOffset??selection!.focusOffset);
        const low=Math.max(1,Math.min(from,to)),high=Math.min(view.state.doc.content.size-1,Math.max(from,to));
        event.preventDefault();const transaction=view.state.tr.insertText(input.data,low,high);
        view.dispatch(transaction.setSelection(TextSelection.create(transaction.doc,low+input.data.length)));return true;
      }},
      handlePaste:(view,event)=>{const text=event.clipboardData?.getData('text/plain');if(text===undefined)return false;view.dispatch(view.state.tr.insertText(text));return true;},
      dispatchTransaction(tr){const before=manuscriptSource(view.state.doc);let state=view.state.apply(tr);
        // Undo/redo can restore the projection from the other view. Restore the
        // requested view without adding an edit, while keeping source history.
        if(isHistoryTransaction(tr)){const text=manuscriptSource(state.doc),start=sourceOffsetAtPosition(state.doc,state.selection.from),end=sourceOffsetAtPosition(state.doc,state.selection.to),doc=manuscriptDocument(text,block,mode.current);
          if(!state.doc.eq(doc)){const projection=state.tr.replaceWith(0,state.doc.content.size,doc.content).setMeta('addToHistory',false);projection.setSelection(TextSelection.create(projection.doc,positionAtSourceOffset(projection.doc,start,-1),positionAtSourceOffset(projection.doc,end,1)));state=state.apply(projection);}}
        view.updateState(state);const text=manuscriptSource(view.state.doc);
        // React session subscriptions are synchronous. Publish after native edit
        // observation/IME completes; a view toggle must not dirty the draft.
        if(tr.docChanged&&text!==before&&!queued){queued=true;queueMicrotask(()=>{queued=false;if(alive)callbacks.current.onChange(manuscriptSource(view.state.doc));});}
        const {from,to}=view.state.selection;callbacks.current.onSelection(from===to?null:sourceAnchor(view.state.doc,from,to,block.id));
      }});editor.current=view;return()=>{if(queued)callbacks.current.onChange(manuscriptSource(view.state.doc));alive=false;editor.current=null;view.destroy();};
  },[block.id]);
  useLayoutEffect(()=>{const view=editor.current;if(!view||manuscriptSource(view.state.doc)===block.text)return;
    const offset=sourceOffsetAtPosition(view.state.doc,view.state.selection.head),doc=manuscriptDocument(block.text,block,mode.current);
    view.updateState(EditorState.create({schema:manuscriptSchema,doc,selection:TextSelection.create(doc,positionAtSourceOffset(doc,offset)),plugins:view.state.plugins}));callbacks.current.onSelection(null);
  },[block.text,block.kind]);
  useLayoutEffect(()=>{const view=editor.current;if(!view)return;const text=manuscriptSource(view.state.doc),start=sourceOffsetAtPosition(view.state.doc,view.state.selection.from),end=sourceOffsetAtPosition(view.state.doc,view.state.selection.to);rebuild(text,start,end,false);choose(null);},[rich]);
  const insert=(kind:Exclude<ScientificKind,'reference'>)=>{
    const view=editor.current;if(!view)return;const text=manuscriptSource(view.state.doc),start=sourceOffsetAtPosition(view.state.doc,view.state.selection.from),end=sourceOffsetAtPosition(view.state.doc,view.state.selection.to);
    const source=insertSources[kind],separator=kind==='table'?(start>0&&text[start-1]!=='\n'?'\n':''):'';
    const trailing=kind==='table'&&end<text.length&&text[end]!=='\n'?'\n':'';const inserted=separator+source+trailing;
    rebuild(text.slice(0,start)+inserted+text.slice(end),start+separator.length,start+separator.length+source.length);
    const token=scientificTokens(source)[0];if(token)choose({token,start:start+separator.length,end:start+separator.length+source.length});view.focus();
  };
  const applyField=()=>{
    const view=editor.current;if(!view||!selected)return;const text=manuscriptSource(view.state.doc),token=selected.token;
    if(text.slice(selected.start,selected.end)!==token.source){setError('此节点已改变。请重新选中当前节点；字段草稿仍保留。');return;}
    const replacement=replaceScientificField(token,token.fields[fieldIndex],fieldText),parsed=scientificTokens(replacement);
    if(parsed.length!==1||parsed[0].start!==0||parsed[0].end!==replacement.length||parsed[0].kind!==token.kind||parsed[0].syntax!==token.syntax){setError('字段内容改变了节点边界。请检查分隔符，或在源码视图编辑完整内容。');return;}
    rebuild(text.slice(0,selected.start)+replacement+text.slice(selected.end),selected.start,selected.start+replacement.length);
    choose({token:parsed[0],start:selected.start,end:selected.start+replacement.length});view.focus();
  };
  return <div className="paper-source-editor">
    <div className="scientific-toolbar" role="toolbar" aria-label={`${label.replace(/文字$/,'').trim()}编辑模式`}>
      <button type="button" aria-pressed={!rich} onClick={()=>setRich(false)}>源码</button><button type="button" aria-pressed={rich} onClick={()=>setRich(true)}>科学节点</button>
      {rich&&<><button type="button" onClick={()=>{const view=editor.current;if(view){const text=manuscriptSource(view.state.doc);rebuild(text,sourceOffsetAtPosition(view.state.doc,view.state.selection.from),undefined,false);choose(null);}}}>识别新节点</button>{(['formula','citation','figure','table'] as const).map(kind=><button type="button" key={kind} onClick={()=>insert(kind)}>插入{scientificLabels[kind]}</button>)}</>}
    </div>
    {rich&&<p className="scientific-help">选择公式、引用、图或表修改其内容；未识别内容可直接编辑。</p>}
    <div className="paper-source-mount" ref={mount}/>
    {rich&&selected&&<section className="scientific-inspector" aria-label={`${scientificLabels[selected.token.kind]}节点编辑`}>
      <div className="scientific-inspector-heading"><strong>{scientificLabels[selected.token.kind]}</strong><button type="button" onClick={()=>choose(null)}>关闭节点编辑</button></div>
      {selected.token.fields.length>1&&<label>编辑字段<select aria-label="科学节点字段" value={fieldIndex} onChange={event=>{const index=Number(event.target.value);setFieldIndex(index);const field=selected.token.fields[index];setFieldText(selected.token.source.slice(field.start,field.end));setError('');}}>{selected.token.fields.map((field,index)=><option key={index} value={index}>{field.label}</option>)}</select></label>}
      <label>{selected.token.fields[fieldIndex].label}<textarea aria-label={selected.token.fields[fieldIndex].label} value={fieldText} onChange={event=>setFieldText(event.target.value)} rows={selected.token.fields[fieldIndex].multiline?4:2}/></label>
      {selected.token.kind==='citation'&&<p>此处编辑引用键；文献对应关系须由引用库核对。</p>}
      {selected.token.kind==='figure'&&<p>图源引用保留在稿件中；实际素材与图号由稿件图位管理。</p>}
      {error&&<p role="alert">{error}</p>}
      <button type="button" onClick={applyField}>应用节点修改</button><button type="button" onClick={()=>{const field=selected.token.fields[fieldIndex];setFieldText(selected.token.source.slice(field.start,field.end));setError('');}}>重置字段</button>
      <details><summary>节点原文</summary><pre>{selected.token.source}</pre></details>
    </section>}
  </div>;
}
