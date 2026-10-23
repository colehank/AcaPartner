import {useEffect,useLayoutEffect,useRef} from 'react';
import {EditorView,keymap,lineNumbers} from '@codemirror/view';
import {Compartment,EditorState,Transaction} from '@codemirror/state';
import {markdown} from '@codemirror/lang-markdown';
import {defaultKeymap,history,historyKeymap} from '@codemirror/commands';
import {search,searchKeymap} from '@codemirror/search';

export type TextPosition={cursor:number,anchor?:number,scrollTop?:number,scrollLeft?:number,restoreScroll?:boolean,viewportFrom?:number,viewportOffset?:number};

export function CodeEditor({text,onChange,onPosition,initial={},viewId,jump=0,readOnly=false,language='markdown',ariaLabel='Markdown 编辑器'}:{
  text:string,onChange:(value:string)=>void,onPosition:(value:TextPosition)=>void,
  initial?:Partial<TextPosition>,viewId:string,jump?:number,readOnly?:boolean,
  language?:'markdown'|'plain',ariaLabel?:string,
}){
  const host=useRef<HTMLDivElement>(null),view=useRef<EditorView|null>(null);
  const handlers=useRef({onChange,onPosition});handlers.current={onChange,onPosition};
  const position=useRef(initial);position.current=initial;
  const restoring=useRef(false);
  const restoreEpoch=useRef(0);
  const focusedJump=useRef(0);
  const editing=useRef(new Compartment());
  const presentation=useRef(new Compartment());
  const visible=(v:EditorView)=>v.dom.isConnected&&v.scrollDOM.clientWidth>0&&v.scrollDOM.clientHeight>0;
  const record=(v:EditorView)=>{
    if(restoring.current||!visible(v))return;
    // Read after CodeMirror has measured its virtualized lines. A pixel scroll
    // offset alone moves to a different line when estimated heights change.
    v.requestMeasure({key:'record-position',read:()=>{
      if(!visible(v))return null;
      const top=v.scrollDOM.getBoundingClientRect().top;
      let from=v.scrollSnapshot().value.range.head;
      let rect=v.coordsAtPos(from,1);
      // A single long wrapped paragraph may begin outside the viewport.
      if(!rect||Math.abs(rect.top-top)>=v.scrollDOM.clientHeight){
        from=v.posAtCoords({x:v.contentDOM.getBoundingClientRect().left+2,y:top+8})??from;
        rect=v.coordsAtPos(from,1);
      }
      return {cursor:v.state.selection.main.head,anchor:v.state.selection.main.anchor,
        scrollTop:v.scrollDOM.scrollTop,scrollLeft:v.scrollDOM.scrollLeft,restoreScroll:true,
        viewportFrom:from,viewportOffset:rect?rect.top-top:undefined};
    },write:value=>{if(value&&!restoring.current&&visible(v))handlers.current.onPosition(value);}});
  };
  const restore=()=>{
    const v=view.current;if(!v||!visible(v))return;const p={...position.current},epoch=++restoreEpoch.current;
    restoring.current=true;
    const logical=p.restoreScroll&&p.viewportFrom!==undefined&&p.viewportOffset!==undefined;
    v.dispatch({selection:{anchor:Math.min(p.anchor??p.cursor??0,v.state.doc.length),head:Math.min(p.cursor??0,v.state.doc.length)},scrollIntoView:!p.restoreScroll,
      effects:logical?EditorView.scrollIntoView(Math.min(p.viewportFrom!,v.state.doc.length),{y:'start',yMargin:p.viewportOffset!}):[]});
    if(!p.restoreScroll&&jump>0&&p.anchor!==p.cursor)v.focus();
    v.requestMeasure({key:'restore-position',read:()=>null,write:()=>{
      if(p.restoreScroll&&!logical)v.scrollDOM.scrollTop=p.scrollTop||0;
      // The native scroll effect runs at the end of the measure cycle. Do not
      // record the temporary position before it has been applied.
      queueMicrotask(()=>{if(view.current!==v||epoch!==restoreEpoch.current||!visible(v))return;
        // Activate only this explicit navigation target, after restoration.
        // Focus must not scroll from a saved viewport back to the caret.
        if(jump>0&&focusedJump.current!==jump){focusedJump.current=jump;v.contentDOM.focus({preventScroll:true});}
        if(p.restoreScroll)v.scrollDOM.scrollLeft=p.scrollLeft||0;
        restoring.current=false;record(v);
      });
    }});
  };
  useEffect(()=>{
    const v=new EditorView({parent:host.current!,state:EditorState.create({doc:text,extensions:[
      lineNumbers(),history(),search(),EditorView.lineWrapping,
      editing.current.of([EditorState.readOnly.of(readOnly),EditorView.editable.of(!readOnly)]),
      presentation.current.of([language==='markdown'?markdown():[],EditorView.contentAttributes.of({'aria-label':ariaLabel,'spellcheck':'false'})]),
      keymap.of([...defaultKeymap,...historyKeymap,...searchKeymap]),
      EditorView.updateListener.of(u=>{
        if(u.docChanged&&!u.transactions.every(t=>t.annotation(Transaction.addToHistory)===false))handlers.current.onChange(u.state.doc.toString());
        if(u.selectionSet)record(u.view);
      }),
    ]})});
    view.current=v;const scroll=()=>record(v);v.scrollDOM.addEventListener('scroll',scroll);
    // Dockview's default renderer detaches an inactive tab without destroying
    // this editor. Reattachment resets the browser's scroll offset; reapply the
    // last real logical viewport once this same view has measurable geometry.
    let wasVisible=visible(v);
    const resize=new ResizeObserver(()=>{
      const nowVisible=visible(v);
      if(!nowVisible){restoreEpoch.current++;restoring.current=false;}
      if(nowVisible&&!wasVisible)restore();
      wasVisible=nowVisible;
    });
    resize.observe(host.current!);restore();
    return()=>{restoreEpoch.current++;resize.disconnect();v.scrollDOM.removeEventListener('scroll',scroll);v.destroy();view.current=null;};
  },[viewId]);
  useLayoutEffect(()=>{view.current?.dispatch({effects:editing.current.reconfigure([EditorState.readOnly.of(readOnly),EditorView.editable.of(!readOnly)])});},[readOnly,viewId]);
  useLayoutEffect(()=>{view.current?.dispatch({effects:presentation.current.reconfigure([language==='markdown'?markdown():[],EditorView.contentAttributes.of({'aria-label':ariaLabel,'spellcheck':'false'})])});},[language,ariaLabel,viewId]);
  useEffect(()=>{const v=view.current;if(v&&v.state.doc.toString()!==text)v.dispatch({changes:{from:0,to:v.state.doc.length,insert:text},annotations:Transaction.addToHistory.of(false)});},[text]);
  useEffect(restore,[jump]);
  return <div className="editor-host" ref={host}/>;
}
