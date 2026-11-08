import * as Menu from '@radix-ui/react-dropdown-menu';
import {createPortal} from 'react-dom';

export type RelationChoice={id:string;from:string;to:string;title:string;kind:string;fulfilled:boolean};
export function ResearchRelationMenu({choices,point,onSelect,onClose,restoreFocus}:{choices:RelationChoice[];point:{x:number;y:number};onSelect:(id:string)=>void;onClose:()=>void;restoreFocus:()=>void}){
 return createPortal(<Menu.Root open modal={false} onOpenChange={open=>{if(!open)onClose();}}>
 <Menu.Trigger asChild><button className="free-wire-anchor" style={{left:point.x,top:point.y}} tabIndex={-1} aria-label="研究关系入口"/></Menu.Trigger>
 <Menu.Portal><Menu.Content className="wb-tree-menu free-wire-menu" aria-label="选择研究关系" aria-labelledby={undefined} sideOffset={6} align="start" collisionPadding={12} onCloseAutoFocus={e=>{e.preventDefault();restoreFocus();}}>
 <Menu.Label>{choices[0]?.kind} · {choices.length} 条关系</Menu.Label>
 {[...choices].sort((a,b)=>(a.from+' '+a.to).localeCompare(b.from+' '+b.to,'en',{numeric:true})).map(choice=><Menu.Item key={choice.id} onSelect={()=>onSelect(choice.id)} title={choice.title}><span className="free-wire-choice"><span>{choice.from} → {choice.to}</span><small>{choice.fulfilled?'已兑现':'待推进或复核'}</small></span></Menu.Item>)}
 </Menu.Content></Menu.Portal></Menu.Root>,document.body);
}
