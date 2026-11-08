import {useEffect,type CSSProperties} from 'react';
import {Handle,Position,useStore,useUpdateNodeInternals,type Node,type NodeProps} from '@xyflow/react';
import {Check,ChevronDown,ChevronRight,Circle,Clock3,LockKeyhole,Pause,RotateCcw} from 'lucide-react';
import {nodeStatusNames,type NodeStatus} from './researchProgress';
import type {CardPreview} from './researchCardContent';
import type {Point} from './researchGraphLayout';

export type ResearchCardData=Record<string,unknown>&{
 node:{id:string;kind:string;label:string;title:string;status:NodeStatus};
 selected:boolean;related:boolean;width:number;height:number;preview:CardPreview;caption:string;
 folded?:boolean;foldable:boolean;disclosure:string;ports:{id:string;type:'source'|'target';point:Point}[];
 select:()=>void;toggle:()=>void;
};
export type ResearchCardNode=Node<ResearchCardData,'researchFree'>;

export function ResearchGraphCard({data}:NodeProps<ResearchCardNode>){
 const n=data.node,zoom=useStore(s=>s.transform[2]),compact=zoom<.6,overview=zoom<.4,condensed=!compact&&zoom<.8;
 const Badge=n.status==='completed'?Check:n.status==='stale'?RotateCcw:n.status==='paused'?Pause:n.status==='blocked'?LockKeyhole:['active','review'].includes(n.status)?Clock3:Circle;
 const update=useUpdateNodeInternals(),portKey=JSON.stringify(data.ports);
 useEffect(()=>update(n.id),[n.id,portKey,update]);
 const style={width:data.width,height:data.height,'--card-scale':Math.max(.4,Math.min(1,zoom)),'--card-zoom':zoom} as CSSProperties;
 const table=data.preview.table,tableRows=table&&condensed&&table.rows.length>2?[table.rows[0],table.rows.at(-1)!]:table?.rows;
 return <div className={'free-node free-card state-'+n.status+(data.selected?' selected':data.related?' related':'')+(compact?' is-compact':'')+(overview?' is-overview':'')+(condensed?' is-condensed':'')} style={style}>
  {data.ports.map(p=>{const x=p.point.x-data.width/2,y=p.point.y-data.height/2;const side=Math.abs(x/data.width)>Math.abs(y/data.height)?x<0?Position.Left:Position.Right:y<0?Position.Top:Position.Bottom;return <Handle key={p.id} id={p.id} type={p.type} position={side} style={{left:p.point.x,top:p.point.y,right:'auto',bottom:'auto',transform:'translate(-50%,-50%)'}}/>;})}
  <button className="free-node-main nodrag" aria-label={n.label+' '+n.title+' · '+nodeStatusNames[n.status]} aria-pressed={data.selected} onClick={data.select}>
   <span className="free-card-header"><span className="free-node-number">{n.label}</span><span className="free-card-status"><Badge/><span>{nodeStatusNames[n.status]}</span></span></span>
   <strong className="free-card-title">{n.title}</strong>
   {!compact&&<span className="free-card-preview">{data.preview.table?<span className="free-card-table" role="table" aria-label={n.label+' 保存结果'+(data.preview.table.partial?'节选':'')}>
    <span role="row" className="free-card-table-head">{data.preview.table.headers.map((cell,i)=><span role="columnheader" key={i}>{cell}</span>)}</span>
    {tableRows!.map((row,i)=><span role="row" key={i}>{row.map((cell,j)=><span role="cell" key={j}>{cell}</span>)}</span>)}
   </span>:<span className={'free-card-excerpt'+(!data.preview.text?' is-empty':'')}>{data.preview.text||'尚未记录内容'}</span>}</span>}
   {!compact&&<span className="free-card-caption">{table&&tableRows!.length<table.totalRows?`节选 ${tableRows!.length}/${table.totalRows} 行结果`:data.caption}</span>}
  </button>
  {data.foldable&&<button className="free-card-toggle nodrag nopan" aria-label={(data.folded?'展开 ':'收起 ')+n.label+' 的'+data.disclosure} aria-expanded={!data.folded} onClick={event=>{event.stopPropagation();data.toggle();}}>{data.folded?<ChevronRight/>:<ChevronDown/>}</button>}
 </div>;
}
