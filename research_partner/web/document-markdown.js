import {esc} from './ui.js';

const shaPattern=/^[a-f0-9]{64}$/;
export function registeredDocumentAssetURL(value){
  if(value&&typeof value==='object')value=value.sha||value.asset||value.url||'';
  if(typeof value!=='string')return '';
  const sha=value.match(/^\/api\/assets\/([a-f0-9]{64})$/)?.[1]||(shaPattern.test(value)?value:'');
  return sha?`/api/assets/${sha}`:'';
}
export function documentImageURL(reference,resources={}){
  const direct=String(reference).match(/^\/api\/assets\/([a-f0-9]{64})$/);
  if(direct)return `/api/assets/${direct[1]}`;
  return Object.hasOwn(resources,reference)?registeredDocumentAssetURL(resources[reference]):'';
}
// Positions refer to the original block string. Discovery, rewriting and inline
// rendering share these tokens; code spans/fences are never image occurrences.
export function documentTokens(value){
  const text=String(value),tokens=[];let i=0;
  while(i<text.length){
    if(i===0||text[i-1]==='\n'){
      const lineEnd=text.indexOf('\n',i),end=lineEnd<0?text.length:lineEnd;
      const fence=text.slice(i,end).match(/^[ \t]*(`{3,}|~{3,})/);
      if(fence){let stop=end<text.length?end+1:end;
        while(stop<text.length){const next=text.indexOf('\n',stop),until=next<0?text.length:next;
          const close=text.slice(stop,until).match(/^[ \t]*(`{3,}|~{3,})[ \t]*$/);
          stop=until<text.length?until+1:until;
          if(close&&close[1][0]===fence[1][0]&&close[1].length>=fence[1].length)break;
        }
        tokens.push({kind:'fence',start:i,end:stop,raw:text.slice(i,stop)});i=stop;continue;
      }
    }
    if(text[i]==='\\'&&i+1<text.length){i+=2;continue;}
    if(text[i]==='`'){
      let n=1;while(text[i+n]==='`')n++;
      let j=i+n,found=-1;
      while(j<text.length){if(text[j]!=='`'){j++;continue;}let k=1;while(text[j+k]==='`')k++;if(k===n){found=j;break;}j+=k;}
      if(found>=0){const end=found+n;tokens.push({kind:'code',start:i,end,raw:text.slice(i,end),text:text.slice(i+n,found)});i=end;continue;}i+=n;continue;
    }
    const match=text.slice(i).match(/^(!?)\[((?:\\.|[^\]\\\n])*)\]\(((?:\\.|[^)\\\n])+)\)/);
    if(match){const end=i+match[0].length;tokens.push({kind:match[1]?'image':'link',start:i,end,raw:match[0],alt:match[2],reference:match[3].trim()});i=end;continue;}
    i++;
  }
  return tokens;
}
export function documentImageOccurrences(content){
  return (content.blocks||[]).flatMap(block=>documentTokens(block.text||'').filter(t=>t.kind==='image').map(t=>({...t,block_id:block.id,url:documentImageURL(t.reference,content.resources)})));
}
export function documentImages(content){
  const seen=new Map();
  for(const token of documentImageOccurrences(content))if(!seen.has(token.reference))seen.set(token.reference,{reference:token.reference,alt:token.alt,block_id:token.block_id,url:token.url});
  return [...seen.values()];
}
export function imageBinding(reference,asset){
  const alias=String(reference).trim(),sha=String(asset).trim().replace(/^\/api\/assets\//,'');
  if(!alias||alias.startsWith('/')||/[:\\?#\[\]()\r\n]/.test(alias)||alias.split('/').some(x=>!x||['.','..','__proto__','prototype','constructor'].includes(x)))throw new Error('图片别名应为文稿内相对名称，且不能使用原型保留名称，例如 sources/figure.png。');
  if(!shaPattern.test(sha))throw new Error('请选择图像文件或填写已登记的图像资产 SHA。');
  return {alias,value:{asset:sha}};
}
export function updateDocumentImage(content,selection,binding,alt,{blockId,afterBlock}={}){
  const resources=Object.fromEntries(Object.entries(content.resources||{}));
  Object.defineProperty(resources,binding.alias,{value:binding.value,enumerable:true,writable:true,configurable:true});
  const blocks=(content.blocks||[]).map(b=>({...b}));
  const cleaned=String(alt||'').replace(/[\[\]\r\n]/g,' ').trim();
  if(selection){
    const block=blocks.find(b=>b.id===selection.block_id),token=block&&documentTokens(block.text||'').find(t=>t.kind==='image'&&t.start===selection.start&&t.raw===selection.raw);
    if(!token)throw new Error('所选图片正文已变化，请重新选择；未改写草稿。');
    const text=String(block.text||''),nextAlt=alt===token.alt?token.alt:cleaned;
    block.text=text.slice(0,token.start)+`![${nextAlt}](${binding.alias})`+text.slice(token.end);
  }else{
    if(!blockId)throw new Error('新增图片缺少段落身份。');
    const index=blocks.findIndex(b=>b.id===afterBlock);
    blocks.splice(index<0?blocks.length:index+1,0,{id:blockId,kind:'paragraph',text:`![${cleaned}](${binding.alias})`});
  }
  // Keep the previous alias: other image occurrences, links and code examples
  // retain their original meaning and can still refer to the original asset.
  return {...content,blocks,resources};
}
function emphasis(text){
  const pattern=/\*\*([^*\n]+)\*\*|(?<!\w)\*(?=\S)([^*\n]+?)(?<=\S)\*(?!\w)/g;let html='',last=0;
  for(const m of String(text).matchAll(pattern)){html+=esc(String(text).slice(last,m.index));last=m.index+m[0].length;html+=m[1]!==undefined?`<strong>${esc(m[1])}</strong>`:`<em>${esc(m[2])}</em>`;}
  return html+esc(String(text).slice(last));
}
function inline(text,resources){
  text=String(text);let html='',last=0;
  for(const token of documentTokens(text)){
    html+=emphasis(text.slice(last,token.start));last=token.end;
    if(token.kind==='code'||token.kind==='fence'){html+=`<code>${esc(token.text??token.raw)}</code>`;continue;}
    const ref=token.reference,url=documentImageURL(ref,resources);
    if(token.kind==='image')html+=url?`<img class="document-inline-image" src="${url}" alt="${esc(token.alt)}" loading="lazy">`:`<span class="missing-document-image" role="status">图片未绑定：${esc(token.alt||ref)} · ${esc(ref)}</span>`;
    else {const target=url||(/^(https?:\/\/[^\s\\]+|\/\?object=[A-Za-z0-9_-]+)$/.test(ref)?ref:'');html+=target?`<a href="${esc(target)}" target="_blank" rel="noopener noreferrer">${esc(token.alt)}</a>`:`${esc(token.alt)} <span class="hint">（链接未绑定：${esc(ref)}）</span>`;}
  }
  return html+emphasis(text.slice(last));
}
export function tableCells(line){
  const text=line.trim();let cells=[],value='',code=0,trailingSeparator=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i];
    if(ch==='\\'&&!code&&text[i+1]==='|'){value+='|';i++;trailingSeparator=false;continue;}
    if(ch==='`'){let count=1;while(text[i+count]==='`')count++;if(!code)code=count;else if(code===count)code=0;value+='`'.repeat(count);i+=count-1;trailingSeparator=false;continue;}
    if(ch==='|'&&!code){cells.push(value.trim());value='';trailingSeparator=true;}else{value+=ch;trailingSeparator=false;}
  }
  cells.push(value.trim());
  if(text.startsWith('|'))cells.shift();if(trailingSeparator)cells.pop();return cells;
}
export function documentMarkdown(text,resources={}){
  text=String(text||'');
  // Recognize code spans over the whole block, just as image discovery does.
  // Collapse them before line layout so an image-looking continuation line
  // cannot become a rendered scientific figure or a Markdown table/heading.
  let prefix='RPINLINESPAN';while(text.includes(prefix))prefix+='X';
  const protectedCode=[];let protectedText='',cursor=0;
  for(const token of documentTokens(text).filter(t=>t.kind==='code')){
    const marker=prefix+protectedCode.length+'END';
    protectedText+=text.slice(cursor,token.start)+marker;cursor=token.end;
    protectedCode.push([marker,`<code>${esc(token.text.replace(/\n/g,' '))}</code>`]);
  }
  protectedText+=text.slice(cursor);
  const lines=protectedText.split('\n');let result=[];
  for(let i=0;i<lines.length;){
    const line=lines[i],fence=line.match(/^[ \t]*(`{3,}|~{3,})/);
    if(fence){const code=[];i++;while(i<lines.length){const end=lines[i].match(/^[ \t]*(`{3,}|~{3,})[ \t]*$/);if(end&&end[1][0]===fence[1][0]&&end[1].length>=fence[1].length)break;code.push(lines[i++]);}if(i<lines.length)i++;result.push(`<pre><code>${esc(code.join('\n'))}</code></pre>`);continue;}
    const separator=i+1<lines.length?tableCells(lines[i+1]):[];
    if(line.includes('|')&&separator.length&&separator.every(cell=>/^:?-{3,}:?$/.test(cell))){
      const rows=[tableCells(line)];i+=2;while(i<lines.length&&lines[i].includes('|')&&lines[i].trim())rows.push(tableCells(lines[i++]));
      const width=Math.max(...rows.map(row=>row.length));result.push(`<div class="document-table-scroll"><table><thead><tr>${Array.from({length:width},(_,n)=>`<th>${inline(rows[0][n]||'',resources)}</th>`).join('')}</tr></thead><tbody>${rows.slice(1).map(row=>`<tr>${Array.from({length:width},(_,n)=>`<td>${inline(row[n]||'',resources)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);continue;
    }
    const heading=line.match(/^(#{1,4})\s+(.*)$/);
    result.push(heading?`<h${heading[1].length+1}>${inline(heading[2],resources)}</h${heading[1].length+1}>`:line.trim()?`<p>${inline(line,resources)}</p>`:'');i++;
  }
  let html=result.join('');
  for(const [marker,code] of protectedCode)html=html.replaceAll(marker,code);
  return html;
}
