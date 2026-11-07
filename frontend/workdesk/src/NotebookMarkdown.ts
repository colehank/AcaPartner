import MarkdownIt from 'markdown-it';
import DOMPurify from 'dompurify';
import type {NotebookHeading} from './NotebookNavigator';

/** Same safe Markdown/token-map contract as the native notebook reader.
 * links=false is a fixed historical preview: no current-head navigation.
 */
export function renderNotebookMarkdown(markdown:string,path:string,headings:NotebookHeading[],options:{links?:boolean}={}){
  const parser=new MarkdownIt({html:false,linkify:false});let tokens=parser.parse(markdown,{});
  if(/^notes\/tasks\/TASK-[a-f0-9]{16}\.md$/.test(path)){
    const lines=markdown.split('\n'),hidden=new Set<number>();
    for(let i=0;i<tokens.length-2;i++){
      const open=tokens[i],inline=tokens[i+1],close=tokens[i+2];
      const line=open.map?lines[open.map[0]].replace(/\r$/,''):'';
      if(open.type==='paragraph_open'&&open.level===0&&open.map&&open.map[1]===open.map[0]+1
        &&inline.type==='inline'&&close.type==='paragraph_close'&&close.level===0
        &&/^<!-- rp-task-report:[a-f0-9]{64} -->$/.test(line)
        &&inline.content===line){hidden.add(i);hidden.add(i+1);hidden.add(i+2);i+=2;}
    }
    tokens=tokens.filter((_,i)=>!hidden.has(i));
  }
  const offsets=[0];let offset=0,index=0;
  for(const line of markdown.split('\n').slice(0,-1)){offset+=Array.from(line).length+1;offsets.push(offset);}
  const characters=Array.from(markdown);
  for(let i=0;i<tokens.length;i++){
    const token=tokens[i];
    if(token.type==='heading_open'&&token.map)token.attrSet('id',headings[index++].slug);
    if(token.nesting===1&&token.map)token.attrSet('data-source-codepoint-offset',String(offsets[token.map[0]]||0));
    // A source range is mapped only when this exact inline string survives
    // rendering unchanged. Formatting, entities, images and removed prefixes
    // are deliberately not located by searching for a repeated visible quote.
    const inline=tokens[i+1];
    if(token.type==='paragraph_open'&&token.map&&inline?.type==='inline'
      &&inline.children?.every(child=>child.type==='text'||child.type==='softbreak')
      &&inline.children.map(child=>child.type==='softbreak'?'\n':child.content).join('')===inline.content){
      const start=offsets[token.map[0]]||0,raw=characters.slice(start,start+Array.from(inline.content).length).join('');
      if(raw===inline.content){
        token.attrSet('data-source-plain-start',String(start));
        token.attrSet('data-source-plain-end',String(start+Array.from(raw).length));
      }
    }
    if(token.type==='inline')for(const child of token.children||[])if(child.type==='link_open'){
      child.attrSet('target','_blank');child.attrSet('rel','noopener noreferrer');
    }
  }
  const renderer=new MarkdownIt({html:false,linkify:false});
  renderer.renderer.rules.image=(items,i)=>`<span class="attachment">[图片：${renderer.utils.escapeHtml(items[i].content)}]</span>`;
  if(options.links===false){renderer.renderer.rules.link_open=()=>'<span>';renderer.renderer.rules.link_close=()=>'</span>';}
  return DOMPurify.sanitize(renderer.renderer.render(tokens,renderer.options,{}),{ALLOW_DATA_ATTR:true,ADD_ATTR:['target']});
}
