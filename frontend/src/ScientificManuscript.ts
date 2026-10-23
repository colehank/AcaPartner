import {Schema,Fragment,type Node as ProseMirrorNode} from 'prosemirror-model';

export type ScientificKind='formula'|'citation'|'figure'|'table'|'reference';
export type SourceField={label:string,start:number,end:number,multiline?:boolean};
export type ScientificToken={kind:ScientificKind,syntax:string,start:number,end:number,source:string,fields:SourceField[]};
export const scientificLabels:Record<ScientificKind,string>={formula:'公式',citation:'引用',figure:'图',table:'表',reference:'交叉引用'};
const escaped=(source:string,at:number)=>{let n=0;while(at>0&&source[--at]==='\\')n++;return n%2===1;};

// A conservative lexer, not a Markdown/TeX normalizer. Unknown syntax is text.
// Every recognized node owns its EXACT source, including delimiters, optional
// arguments, whitespace and line endings. Persistence only uses that source.
function group(source:string,start:number,open:string,close:string):number|null{
  if(source[start]!==open)return null;
  let depth=1;
  for(let i=start+1;i<source.length;i++){
    if(escaped(source,i))continue;
    if(source[i]===open)depth++;
    if(source[i]===close&&--depth===0)return i;
  }
  return null;
}
function closing(source:string,start:number,delimiter:string):number|null{
  let at=start;
  while((at=source.indexOf(delimiter,at))!==-1){if(!escaped(source,at))return at;at+=delimiter.length;}
  return null;
}
function commandArgument(source:string,start:number,pattern:RegExp):{end:number,start:number,stop:number}|null{
  const name=pattern.exec(source.slice(start));if(!name)return null;
  let at=start+name[0].length;
  while(/\s/.test(source[at]||'')&&at<source.length)at++;
  while(source[at]==='['){const end=group(source,at,'[',']');if(end===null)return null;at=end+1;while(/\s/.test(source[at]||'')&&at<source.length)at++;}
  const stop=group(source,at,'{','}');return stop===null?null:{end:stop+1,start:at+1,stop};
}
function environmentEnd(source:string,start:number,name:string):{body:number,end:number,stop:number}|null{
  const opening=`\\begin{${name}}`,ending=`\\end{${name}}`;
  let depth=1,at=start+opening.length;
  const body=at;
  while(at<source.length){
    if(source[at]==='%'&&!escaped(source,at)){const line=source.indexOf('\n',at);if(line<0)return null;at=line+1;continue;}
    if(!escaped(source,at)&&source.startsWith(opening,at)){depth++;at+=opening.length;continue;}
    if(!escaped(source,at)&&source.startsWith(ending,at)){if(--depth===0)return {body,stop:at,end:at+ending.length};at+=ending.length;continue;}
    at++;
  }
  return null;
}
type Cell={start:number,end:number,text:string};
function pipeCells(line:string,base:number):Cell[]{
  const pipes:number[]=[];let code=0;
  for(let i=0;i<line.length;i++){
    if(line[i]==='`'&&!escaped(line,i)){let n=1;while(line[i+n]==='`')n++;code=code===n?0:code===0?n:code;i+=n-1;continue;}
    if(line[i]==='|'&&!escaped(line,i)&&code===0)pipes.push(i);
  }
  if(!pipes.length)return [];
  const starts=[-1,...pipes,line.length],cells:Cell[]=[];
  for(let i=0;i<starts.length-1;i++){
    let start=starts[i]+1,end=starts[i+1];
    if((i===0||i===starts.length-2)&&!line.slice(start,end).trim())continue;
    while(start<end&&/\s/.test(line[start]))start++;while(end>start&&/\s/.test(line[end-1]))end--;
    cells.push({start:base+start,end:base+end,text:line.slice(start,end)});
  }
  return cells;
}
export function markdownTableRows(source:string):Cell[][]{
  let at=0;const rows:Cell[][]=[];
  for(const line of source.split('\n')){rows.push(pipeCells(line.replace(/\r$/,''),at));at+=line.length+1;}
  return rows;
}
function markdownTable(source:string,start:number):ScientificToken|null{
  const firstEnd=source.indexOf('\n',start);if(firstEnd===-1)return null;
  const secondEnd=source.indexOf('\n',firstEnd+1),separatorEnd=secondEnd===-1?source.length:secondEnd;
  const header=pipeCells(source.slice(start,firstEnd).replace(/\r$/,''),start),separator=pipeCells(source.slice(firstEnd+1,separatorEnd).replace(/\r$/,''),firstEnd+1);
  if(!header.length||separator.length!==header.length||!separator.every(c=>/^:?-{3,}:?$/.test(c.text)))return null;
  let end=separatorEnd,at=secondEnd===-1?source.length:secondEnd+1;
  while(at<source.length){const next=source.indexOf('\n',at),lineEnd=next===-1?source.length:next;const cells=pipeCells(source.slice(at,lineEnd).replace(/\r$/,''),at);if(cells.length!==header.length)break;end=lineEnd;at=next===-1?source.length:next+1;}
  const raw=source.slice(start,end),rows=markdownTableRows(raw),fields:SourceField[]=[];
  rows.forEach((row,r)=>{if(r===1)return;row.forEach((cell,c)=>fields.push({label:`${r===0?'表头':`数据行 ${r-1}`} · 列 ${c+1}`,start:cell.start,end:cell.end}));});
  return {kind:'table',syntax:'markdown-table',start,end,source:raw,fields};
}
export function scientificTokens(source:string):ScientificToken[]{
  const tokens:ScientificToken[]=[];let i=0;
  const token=(kind:ScientificKind,syntax:string,end:number,fields:SourceField[])=>({kind,syntax,start:i,end,source:source.slice(i,end),fields:fields.map(f=>({...f,start:f.start-i,end:f.end-i}))});
  while(i<source.length){
    const lineStart=i===0||source[i-1]==='\n';
    if(lineStart){
      const fence=/^ {0,3}(`{3,}|~{3,})[^\n]*(?:\n|$)/.exec(source.slice(i));
      if(fence){const marker=fence[1][0],length=fence[1].length;let at=i+fence[0].length;while(at<source.length){const end=source.indexOf('\n',at),stop=end===-1?source.length:end;const line=source.slice(at,stop).replace(/\r$/,'');if(new RegExp(`^ {0,3}${marker}{${length},}\\s*$`).test(line)){at=end===-1?source.length:end+1;break;}at=end===-1?source.length:end+1;}i=at;continue;}
      const table=markdownTable(source,i);if(table){tokens.push(table);i=table.end;continue;}
    }
    if(source[i]==='`'&&!escaped(source,i)){let n=1;while(source[i+n]==='`')n++;const end=source.indexOf('`'.repeat(n),i+n);i=end<0?i+n:end+n;continue;}
    if(source[i]==='%'&&!escaped(source,i)){const end=source.indexOf('\n',i);i=end<0?source.length:end+1;continue;}
    if(escaped(source,i)){i++;continue;}
    let found:ScientificToken|null=null;
    if(source[i]==='\\'){
      const verb=/^\\verb\*?([^\s])/.exec(source.slice(i));if(verb){const end=source.indexOf(verb[1],i+verb[0].length);i=end<0?i+verb[0].length:end+1;continue;}
      const env=/^\\begin\{(equation\*?|align\*?|gather\*?|multline\*?|displaymath|figure\*?|table\*?|tabular\*?)\}/.exec(source.slice(i));
      if(env){const end=environmentEnd(source,i,env[1]);if(end){const kind:ScientificKind=/^figure/.test(env[1])?'figure':/^(table|tabular)/.test(env[1])?'table':'formula';found=token(kind,`tex-${env[1]}`,end.end,[{label:kind==='formula'?'公式 TeX':kind==='figure'?'图环境源内容':'表环境源内容',start:end.body,end:end.stop,multiline:true}]);}}
      if(!found&&(source.startsWith('\\(',i)||source.startsWith('\\[',i))){const delimiter=source[i+1]==='('? '\\)':'\\]',end=closing(source,i+2,delimiter);if(end!==null)found=token('formula',source[i+1]==='('?'tex-inline':'tex-display',end+2,[{label:'公式 TeX',start:i+2,end,multiline:true}]);}
      if(!found){const cite=commandArgument(source,i,/^\\(?:cite(?:p|t|alp|alt|author|yearpar|year)?|parencite|textcite|autocite|nocite)\*?(?![a-zA-Z])/);if(cite)found=token('citation','tex-citation',cite.end,[{label:'引用键',start:cite.start,end:cite.stop}]);}
      if(!found){const ref=commandArgument(source,i,/^\\(?:eqref|autoref|[cC]ref|ref)\*?(?![a-zA-Z])/);if(ref)found=token('reference','tex-reference',ref.end,[{label:'目标标签',start:ref.start,end:ref.stop}]);}
      if(!found){const image=commandArgument(source,i,/^\\includegraphics\*?(?![a-zA-Z])/);if(image)found=token('figure','tex-image',image.end,[{label:'图源引用',start:image.start,end:image.stop}]);}
    }
    if(!found&&source[i]==='$'){
      const delimiter=source.startsWith('$$',i)?'$$':'$',end=closing(source,i+delimiter.length,delimiter);
      if(end!==null&&(delimiter==='$$'||!source.slice(i+1,end).includes('\n')))found=token('formula',delimiter==='$$'?'dollar-display':'dollar-inline',end+delimiter.length,[{label:'公式 TeX',start:i+delimiter.length,end,multiline:true}]);
    }
    if(!found&&source.startsWith('![',i)){
      const altEnd=group(source,i+1,'[',']');if(altEnd!==null&&source[altEnd+1]==='('){const end=group(source,altEnd+1,'(',')');if(end!==null){const target=source.slice(altEnd+2,end),path=/^\s*(<[^>]*>|(?:\\.|[^\s])+?)(?=\s+["']|\s*$)/.exec(target);const fields:SourceField[]=[{label:'图替代文本',start:i+2,end:altEnd}];if(path){const start=altEnd+2+path[0].indexOf(path[1]);fields.push({label:'图源引用',start,end:start+path[1].length});}else fields.push({label:'图源与标题',start:altEnd+2,end});found=token('figure','markdown-image',end+1,fields);}}
    }
    if(!found&&source.startsWith('[@',i)){const end=group(source,i,'[',']');if(end!==null&&!source.slice(i,end).includes('\n')){const singleKey=/^\[@[A-Za-z0-9_.:-]*\]$/.test(source.slice(i,end+1));found=token('citation','pandoc-citation',end+1,[{label:singleKey?'引用键':'引用键与定位信息',start:i+(singleKey?2:1),end}]);}}
    if(found){tokens.push(found);i=found.end;}else i++;
  }
  return tokens;
}

const scientificNodes=Object.fromEntries(Object.keys(scientificLabels).map(kind=>[`scientific_${kind}`,{
  inline:true,group:'inline',atom:true,selectable:true,draggable:false,
  attrs:{source:{default:''},syntax:{default:''}},
  toDOM:(node:ProseMirrorNode)=>['span',{'data-scientific-kind':kind,'data-source':node.attrs.source,class:`scientific-node scientific-${kind}`},node.attrs.source],
}]));
export const manuscriptSchema=new Schema({nodes:{doc:{content:'source_block'},source_block:{group:'block',content:'inline*',code:true,marks:'',attrs:{block_id:{default:''},kind:{default:'paragraph'}},parseDOM:[{tag:'pre',preserveWhitespace:'full'}],toDOM:node=>['pre',{'data-block-id':node.attrs.block_id},['code',0]]},text:{group:'inline'},...scientificNodes}});
export function manuscriptDocument(text:string,block:{id:string,kind:string},rich:boolean):ProseMirrorNode{
  const children:ProseMirrorNode[]=[];let at=0;
  for(const token of rich?scientificTokens(text):[]){if(at<token.start)children.push(manuscriptSchema.text(text.slice(at,token.start)));children.push(manuscriptSchema.node(`scientific_${token.kind}`,{source:token.source,syntax:token.syntax}));at=token.end;}
  if(at<text.length)children.push(manuscriptSchema.text(text.slice(at)));
  return manuscriptSchema.node('doc',null,[manuscriptSchema.node('source_block',{block_id:block.id,kind:block.kind},children)]);
}
export function manuscriptSource(node:ProseMirrorNode|Fragment):string{
  if('isText' in node&&node.isText)return node.text||'';
  if('attrs' in node&&node.type.name.startsWith('scientific_'))return node.attrs.source;
  let text='';node.forEach(child=>{text+=manuscriptSource(child);});return text;
}
export function sourceOffsetAtPosition(doc:ProseMirrorNode,position:number):number{
  const block=doc.firstChild!;let source=0;const relative=Math.max(0,Math.min(block.content.size,position-1));
  block.forEach((node,offset)=>{if(relative<=offset)return;const length=manuscriptSource(node).length;source+=node.isText?Math.min(length,relative-offset):length;});
  return source;
}
export function positionAtSourceOffset(doc:ProseMirrorNode,offset:number,bias:-1|1=-1):number{
  const block=doc.firstChild!;let source=0,position=block.content.size+1,done=false;
  offset=Math.max(0,offset);
  block.forEach((node,pos)=>{if(done)return;const length=manuscriptSource(node).length;if(offset<=source+length){position=1+pos+(node.isText?Math.min(length,offset-source):offset===source?0:offset===source+length?1:bias<0?0:1);done=true;}source+=length;});
  return position;
}
export function sourceAnchor(doc:ProseMirrorNode,from:number,to:number,blockId:string){
  const text=manuscriptSource(doc),start=sourceOffsetAtPosition(doc,from),end=sourceOffsetAtPosition(doc,to);
  return {block_id:blockId,start:Array.from(text.slice(0,start)).length,end:Array.from(text.slice(0,end)).length,quote:text.slice(start,end)};
}
export function replaceScientificField(token:ScientificToken,field:SourceField,value:string):string{
  return token.source.slice(0,field.start)+value+token.source.slice(field.end);
}
export function scientificSummary(token:ScientificToken):string{
  if(token.kind==='table'&&token.syntax==='markdown-table'){const rows=markdownTableRows(token.source);return `${rows[0]?.length||0} 列 · ${Math.max(0,rows.length-2)} 数据行`;}
  const field=token.fields[token.kind==='figure'&&token.fields.length>1?1:0];return (field?token.source.slice(field.start,field.end):token.source).trim()||'空白';
}
