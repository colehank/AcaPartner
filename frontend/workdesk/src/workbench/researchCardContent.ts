import {markdownParser} from '../editors/markdown';
import {excerpt} from './researchProgress';

export type CardPreview={text:string;table?:{headers:string[];rows:string[][];totalRows:number;partial:boolean}};

/** Saved Markdown projected as text, never an inferred scientific summary. */
export function researchCardPreview(body:string,kind:string):CardPreview{
 const tokens=markdownParser().parse(body||'',{}),paragraphs:string[]=[],rows:string[][]=[];
 let table=false,heading=false,firstTable=true,row:string[]|null=null;
 for(const token of tokens){
  if(token.type==='heading_open')heading=true;
  if(token.type==='heading_close')heading=false;
  if(token.type==='table_open'&&firstTable)table=true;
  if(token.type==='tr_open'&&table)row=[];
  if(token.type==='inline'){
   const text=(token.children||[]).filter(t=>['text','code_inline','image','softbreak','hardbreak'].includes(t.type)).map(t=>['softbreak','hardbreak'].includes(t.type)?' ':t.content).join('').trim();
   if(table&&row)row.push(text);
   else if(!heading&&!table&&text)paragraphs.push(text);
  }
  if(token.type==='tr_close'&&row){rows.push(row);row=null;}
  if(token.type==='table_close'){table=false;firstTable=false;}
 }
 if(kind==='E'&&rows.length>1){
  const headers=rows[0],columns=headers.length>2?[0,headers.length-1]:headers.map((_,i)=>i);
  return {text:'',table:{headers:columns.map(i=>headers[i]),rows:rows.slice(1,5).map(row=>columns.map(i=>row[i]||'')),totalRows:rows.length-1,partial:rows.length>5||headers.length>2}};
 }
 const tableText=rows.length>1?rows[0].map((h,i)=>h+'：'+(rows[1][i]||'')).join('；'):'';
 return {text:excerpt(paragraphs[0]||tableText,120)||(body.trim()?'正文包含代码、公式或图表，点击查看。':'')};
}

type CardNode={id:string;kind:string;status:string;child_question_ids?:string[]};
type CardEdge={src:string;dst:string;kind:string;active:boolean};
export function researchCardCaption(node:CardNode,nodes:CardNode[],edges:CardEdge[],preview:CardPreview){
 const active=edges.filter(e=>e.active),count=(kind:string)=>active.filter(e=>e.src===node.id&&e.kind===kind).length;
 if(node.kind==='Q'){
  const children=nodes.filter(n=>node.child_question_ids?.includes(n.id));
  return children.length?`${children.length} 个子问题 · ${children.filter(n=>n.status==='completed').length} 个已回答`:
   `${count('analyzes')} 项分析 · ${active.filter(e=>e.dst===node.id&&e.kind==='answers').length} 项结论`;
 }
 if(node.kind==='A')return count('produces')?'1 项证据 · 正文摘录':'暂无结果 · 正文摘录';
 if(preview.table)return `${preview.table.totalRows} 行结果${preview.table.partial?' · 节选':''}`;
 if(node.kind==='C')return `${active.filter(e=>e.dst===node.id&&['supports','limits','refutes'].includes(e.kind)).length} 项依据 · 正文摘录`;
 return preview.text?'正文摘录':'尚未记录内容';
}
