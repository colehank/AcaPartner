import {useLayoutEffect,useRef,type ReactNode} from 'react';

// Reveal the requested source inside the existing figure pane. The canvas
// stays mounted, so inspecting code does not reset its camera or draft.
export function FigureSourcePanel({children,onClose}:{children:ReactNode,onClose:()=>void}){
  const panel=useRef<HTMLElement>(null),back=useRef<HTMLButtonElement>(null);
  const origin=useRef<{host:HTMLElement,top:number,left:number,focus:HTMLElement|null}|null>(null);
  useLayoutEffect(()=>{
    const element=panel.current,host=element?.closest<HTMLElement>('.figure-panel');
    if(!element||!host)return;
    origin.current={host,top:host.scrollTop,left:host.scrollLeft,focus:document.activeElement instanceof HTMLElement?document.activeElement:null};
    const bounds=host.getBoundingClientRect();
    host.scrollTop+=element.getBoundingClientRect().top-bounds.top-host.clientTop;
    back.current?.focus({preventScroll:true});
  },[]);
  const close=()=>{
    const saved=origin.current;
    if(saved?.host.isConnected){saved.host.scrollTop=saved.top;saved.host.scrollLeft=saved.left;saved.focus?.isConnected&&saved.focus.focus({preventScroll:true});}
    onClose();
  };
  return <article ref={panel} className="figure-source" aria-label="图的实际来源">
    <button ref={back} onClick={close}>返回画布</button>
    {children}
  </article>;
}
