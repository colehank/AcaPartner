import {useEffect,useMemo,useRef,useState,useSyncExternalStore} from 'react';
import MarkdownIt from 'markdown-it';
import {renderNotebookMarkdown} from './NotebookMarkdown';
import {noteCommand} from './api';
import type {Session} from './session';

export type WorkspaceLink = {kind:'task'|'generation'|'figure'|'paper',id:string,projectId:string};
export type NotebookLink =
  | {kind:'note',path:string,fragment?:string}
  | WorkspaceLink
  | {kind:'asset',href:string}
  | {kind:'external',href:string}
  | {kind:'blocked',reason:string};
export type NoteLocation = {path:string,sourceCodePointOffset?:number,endSourceCodePointOffset?:number,
  contentSha256?:string,originViewId:string,split:boolean};
export type WorkspaceLocation = WorkspaceLink & {originViewId:string};
export type NotebookHeading = {title:string,slug:string,level:number,sourceCodePointOffset:number};
export type NotebookPresentation = {readonly isVisible:boolean,
  onDidVisibilityChange:(listener:(event:{isVisible:boolean})=>void)=>{dispose:()=>void}};

const parser=new MarkdownIt({html:false,linkify:false});
const blocked=(reason:string):NotebookLink=>({kind:'blocked',reason});
const validId=(id:string)=>!!id&&id.length<=200&&!/[\s/\\\u0000-\u001f]/u.test(id);

function notePath(value:string,sourcePath:string,alreadyDecoded=false):string|null {
  let decoded:string;
  try{decoded=alreadyDecoded?value:decodeURIComponent(value);}catch{return null;}
  if(decoded.includes('\\')||/[\u0000-\u001f]/u.test(decoded)||decoded.length>1024)return null;
  const rooted=decoded.startsWith('notes/')||decoded.startsWith('/notes/');
  if(decoded.startsWith('/')&&!rooted)return null;
  const parts=rooted?[]:sourcePath.split('/').slice(0,-1);
  for(const part of decoded.replace(/^\//,'').split('/')){
    if(!part||part==='.')continue;
    if(part==='..'){if(parts.length<=1)return null;parts.pop();}
    else parts.push(part);
  }
  if(parts[0]!=='notes'||parts.length<2||parts.some(p=>p==='.trash'||p==='.notebook')||!parts.at(-1)!.endsWith('.md'))return null;
  // The server remains responsible for existence, identity and symlink checks.
  return parts.join('/');
}

export function resolveNotebookLink(href:string,sourcePath:string,projectId:string,origin?:string):NotebookLink {
  if(!href||/[\u0000-\u001f]/u.test(href)||href.includes('\\'))return blocked('链接格式无效。');
  if(/^(?:https?:)?\/\//i.test(href)){
    try{
      const url=new URL(href.startsWith('//')?'https:'+href:href);
      if(origin&&url.origin===origin)return resolveNotebookLink(url.pathname+url.search+url.hash,sourcePath,projectId);
      return {kind:'external',href:url.href};
    }
    catch{return blocked('外部链接格式无效。');}
  }
  if(/^[a-z][a-z\d+.-]*:/i.test(href))return blocked('不执行笔记中的脚本或其他协议。');
  if(href.startsWith('/api/assets/')){
    return /^\/api\/assets\/[a-f0-9]{64}$/.test(href)?{kind:'asset',href}:blocked('素材链接需要明确的已登记内容摘要。');
  }
  if(href.startsWith('/?')||href.startsWith('?')){
    const url=new URL(href,'https://research-partner.invalid/');
    if(url.searchParams.getAll('project').length>1)return blocked('工作桌链接的项目身份不明确。');
    const targetProject=url.searchParams.get('project')??projectId;
    if(targetProject!==projectId)return blocked('此链接属于其他项目；请先明确切换项目。');
    const keys=['note','task','generation_run','figure','main_figure','paper'].filter(k=>url.searchParams.has(k));
    if(keys.length!==1)return blocked('工作桌链接需要一个明确的文件或对象。');
    const key=keys[0],id=url.searchParams.get(key)!;
    if(url.searchParams.getAll(key).length!==1)return blocked('工作桌链接的对象身份不明确。');
    if(key==='note'){
      const path=notePath(id,sourcePath,true);
      if(!path)return blocked('笔记链接必须留在本项目 notes/ 中。');
      try{return {kind:'note',path,...(url.hash?{fragment:decodeURIComponent(url.hash.slice(1))}:{})};}
      catch{return blocked('标题锚点编码无效。');}
    }
    if(!validId(id))return blocked('工作桌对象身份无效。');
    return {kind:key==='task'?'task':key==='generation_run'?'generation':key==='paper'?'paper':'figure',id,projectId};
  }
  const fragmentAt=href.indexOf('#'),pathPart=fragmentAt<0?href:href.slice(0,fragmentAt);
  if(pathPart.includes('?'))return blocked('相对文件链接不能隐含工作桌查询参数。');
  const path=pathPart?notePath(pathPart,sourcePath):notePath(sourcePath,sourcePath,true);
  if(!path)return blocked('此链接不是本项目笔记或已登记素材入口。');
  try{return {kind:'note',path,...(fragmentAt>=0?{fragment:decodeURIComponent(href.slice(fragmentAt+1))}:{})};}
  catch{return blocked('标题锚点编码无效。');}
}

function sourceOffsets(markdown:string):number[]{
  const offsets=[0];let offset=0;
  for(const line of markdown.split('\n').slice(0,-1)){offset+=Array.from(line).length+1;offsets.push(offset);}
  return offsets;
}

function slug(title:string):string {
  return title.toLowerCase().replace(/[^\p{L}\p{N}\p{M}\s_-]/gu,'').trim().replace(/\s+/g,'-')||'section';
}

export function notebookHeadings(markdown:string):NotebookHeading[]{
  const tokens=parser.parse(markdown,{}),offsets=sourceOffsets(markdown),used=new Set<string>();
  const result:NotebookHeading[]=[];
  for(let i=0;i<tokens.length;i++){
    const token=tokens[i];if(token.type!=='heading_open'||!token.map)continue;
    const inline=tokens[i+1];
    const title=(inline.children||[]).map(child=>child.type==='softbreak'?' ':child.content).join('')||inline.content;
    const base=slug(title);let unique=base,number=0;
    while(used.has(unique))unique=base+'-'+(++number);
    used.add(unique);
    result.push({title,slug:unique,level:Number(token.tag.slice(1)),sourceCodePointOffset:offsets[token.map[0]]||0});
  }
  return result;
}

export function headingLocation(markdown:string,fragment:string):number|null {
  if(fragment==='')return 0;
  const heading=notebookHeadings(markdown).find(h=>h.slug===fragment||h.title===fragment);
  return heading?.sourceCodePointOffset??null;
}

/** Exact UTF-16 view selection to original code-point-mapped DOM text. */
export function notebookReadingRange(container:HTMLElement,markdown:string,start:number,end:number):Range|null {
  if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end<=start||end>markdown.length)return null;
  const characters=Array.from(markdown),boundaries=new Set<number>([0]);let length=0;
  for(const character of characters){length+=character.length;boundaries.add(length);}
  if(!boundaries.has(start)||!boundaries.has(end))return null;
  for(const element of container.querySelectorAll<HTMLElement>('[data-source-plain-start][data-source-plain-end]')){
    const from=Number(element.dataset.sourcePlainStart),to=Number(element.dataset.sourcePlainEnd);
    if(!Number.isInteger(from)||!Number.isInteger(to)||from<0||to<from||to>characters.length)continue;
    const text=characters.slice(from,to).join(''),offset=characters.slice(0,from).join('').length;
    if(start<offset||end>offset+text.length||element.textContent!==text)continue;
    const nodes:Text[]=[];const walker=container.ownerDocument.createTreeWalker(element,NodeFilter.SHOW_TEXT);
    let node:Node|null;while((node=walker.nextNode()))nodes.push(node as Text);
    const locate=(index:number):{node:Text,offset:number}|null=>{
      let consumed=0;for(const node of nodes){if(index<=consumed+node.length)return {node,offset:index-consumed};consumed+=node.length;}return null;
    };
    const a=locate(start-offset),b=locate(end-offset);if(!a||!b)return null;
    const range=container.ownerDocument.createRange();range.setStart(a.node,a.offset);range.setEnd(b.node,b.offset);
    return range.toString()===markdown.slice(start,end)?range:null;
  }
  return null;
}

/** Keep Markdown text untouched; route project navigation through the command layer. */
export function NotebookReading({session,path,viewId,jump=0,presentation,onOpenNote,onWorkspaceLink,report}:{session:Session,path:string,viewId:string,jump?:number,presentation?:NotebookPresentation,
  onOpenNote:(location:NoteLocation)=>Promise<void>,onWorkspaceLink?:(location:WorkspaceLocation)=>Promise<void>|void,
  report:(error:unknown)=>void}){
  useSyncExternalStore(session.subscribe,session.snapshot);
  const host=useRef<HTMLElement>(null),restoring=useRef(false),restoration=useRef(0),measurable=useRef(false);
  const placement=useRef(''),focusedJump=useRef(0),selectedJump=useRef('');
  const context=useRef('');context.current=session.project.id+'\n'+path;
  const [pending,setPending]=useState(false),[message,setMessage]=useState(''),[rangeNotice,setRangeNotice]=useState('');
  const buffer=session.buffers.get(path),markdown=buffer?.text||'';
  const html=useMemo(()=>renderNotebookMarkdown(markdown,path,notebookHeadings(markdown)),[markdown,path]);
  const position=session.views[viewId]?.path===path?session.views[viewId]:{};
  const cursor=position.cursor||0,anchor=position.anchor??cursor,restoreScroll=position.restoreScroll;
  const visible=(container:HTMLElement)=>(!presentation||presentation.isVisible)&&container.isConnected&&container.clientWidth>0&&container.clientHeight>0;
  useEffect(()=>{
    const container=host.current;if(!container)return;
    setMessage('');setRangeNotice('');setPending(false);
    const restore=()=>{
      if(!visible(container))return;
      const currentParent=container.closest('.dv-content-container');
      if(currentParent&&currentParent!==contentParent){attachment.disconnect();contentParent=currentParent;attachment.observe(contentParent,{childList:true});}
      const epoch=++restoration.current;restoring.current=true;
      // Session.position updates without a React repaint. Reattachment needs
      // the last actual reading position, rather than the effect's old snapshot.
      const current=session.views[viewId]?.path===path?session.views[viewId]:{};
      const blocks=Array.from(container.querySelectorAll<HTMLElement>('[data-source-codepoint-offset]'));
      const cp=Array.from(markdown.slice(0,cursor)).length;
      const route=[session.project.id,path,cursor,jump,restoreScroll,buffer?.base].join('\n');
      // Shared-buffer repaint and retained-tab reattachment preserve this view.
      // A changed explicit jump still takes precedence over its old viewport.
      const saved=(restoreScroll||placement.current===route)&&current.readingBase===buffer?.base;
      placement.current=route;
      const offset=saved?current.readingSourceOffset:cp;
      const block=[...blocks].reverse().find(element=>Number(element.dataset.sourceCodepointOffset)<=offset);
      if(saved&&block&&typeof current.readingViewportOffset==='number')container.scrollTop+=block.getBoundingClientRect().top-container.getBoundingClientRect().top-current.readingViewportOffset;
      else if(saved&&typeof current.readingScrollTop==='number')container.scrollTop=current.readingScrollTop;
      else if(block)container.scrollTop+=block.getBoundingClientRect().top-container.getBoundingClientRect().top;
      queueMicrotask(()=>{
        if(restoration.current!==epoch||!visible(container))return;
        restoring.current=false;
        // Only a new explicit jump into the active target may reclaim focus.
        if(jump>0&&jump!==focusedJump.current&&session.activeView===viewId){
          focusedJump.current=jump;container.focus({preventScroll:true});
        }
        const selectionKey=[session.project.id,path,viewId,jump,buffer?.base,cursor,anchor].join('\n');
        if(jump>0&&!restoreScroll&&anchor!==cursor&&session.activeView===viewId&&selectedJump.current!==selectionKey){
          selectedJump.current=selectionKey;
          const selection=container.ownerDocument.getSelection();
          if(selection?.anchorNode&&container.contains(selection.anchorNode))selection.removeAllRanges();
          const range=!buffer?.dirty?notebookReadingRange(container,markdown,Math.min(cursor,anchor),Math.max(cursor,anchor)):null;
          if(range&&selection){
            selection.removeAllRanges();selection.addRange(range);
            const target=range.getBoundingClientRect(),viewport=container.getBoundingClientRect();
            if(target.top<viewport.top||target.bottom>viewport.bottom)container.scrollTop+=target.top-viewport.top;
          }else setRangeNotice('阅读视图无法准确映射这段原文选区。请点击笔记工具中的“编辑”定位原始 Markdown；全文与来源偏移保留。');
        }
        record();
      });
    };
    let wasVisible=visible(container);measurable.current=wasVisible;
    const resize=new ResizeObserver(()=>{
      const nowVisible=visible(container);measurable.current=nowVisible;
      if(!nowVisible){restoration.current++;restoring.current=false;}
      if(nowVisible&&!wasVisible)restore();
      wasVisible=nowVisible;
    });
    const visibility=presentation?.onDidVisibilityChange(({isVisible})=>{
      const epoch=++restoration.current;measurable.current=false;restoring.current=false;
      if(!isVisible)return;
      // Dockview's visibility event precedes the final group layout. Its
      // serializer can also show/hide a group synchronously; only the final
      // visible state may restore or record geometry.
      queueMicrotask(()=>{if(restoration.current!==epoch||!visible(container))return;
        measurable.current=true;wasVisible=true;restore();});
    });
    // setActive() on an already selected Dockview tab still removes and
    // appends its renderer within one task. ResizeObserver sees no size change.
    // Observe only this group's direct renderer children, never the whole DOM.
    let contentParent=container.closest('.dv-content-container');
    const attachment=new MutationObserver(changes=>{
      if(!changes.some(change=>[...change.removedNodes,...change.addedNodes].some(node=>node.contains(container))))return;
      if(visible(container)){measurable.current=true;wasVisible=true;restore();}
    });
    if(contentParent)attachment.observe(contentParent,{childList:true});
    resize.observe(container);restore();
    return()=>{restoration.current++;measurable.current=false;resize.disconnect();visibility?.dispose();attachment.disconnect();};
  },[session,viewId,path,html,cursor,anchor,jump,restoreScroll,buffer?.base,presentation]);
  const record=()=>{
    const container=host.current;if(!container||restoring.current||!measurable.current||!visible(container))return;
    const top=container.getBoundingClientRect().top;
    const block=Array.from(container.querySelectorAll<HTMLElement>('[data-source-codepoint-offset]')).find(element=>element.getBoundingClientRect().bottom>top);
    session.position(viewId,{path,readingBase:buffer?.base,readingScrollTop:container.scrollTop,
      readingSourceOffset:block?Number(block.dataset.sourceCodepointOffset):0,readingViewportOffset:block?block.getBoundingClientRect().top-top:0});
  };
  useEffect(()=>{if(rangeNotice)record();},[rangeNotice]);
  return <article ref={host} className="markdown notebook-reading" aria-label="笔记阅读内容" tabIndex={0} aria-busy={pending} onScroll={record}
    onClick={async event=>{
      const anchor=(event.target as Element).closest<HTMLAnchorElement>('a[href]');if(!anchor||!host.current?.contains(anchor))return;
      const target=resolveNotebookLink(anchor.getAttribute('href')||'',path,session.project.id,window.location.origin);
      if(target.kind==='external'||target.kind==='asset')return;
      event.preventDefault();if(pending)return;
      if(target.kind==='blocked'){setMessage(target.reason);return;}
      const split=event.ctrlKey||event.metaKey,epoch=restoration.current,key=context.current;
      setPending(true);setMessage('');record();
      try{
        if(target.kind==='note'){
          let sourceCodePointOffset:number|undefined,contentSha256:string|undefined;
          if(target.fragment!==undefined){
            const disk=await noteCommand('notes.read',session.project.id,{relative_path:target.path});
            if(context.current!==key||restoration.current!==epoch)return;
            const current=session.buffers.get(target.path);
            const text=current?.dirty?current.text:disk.markdown;
            const offset=headingLocation(text,target.fragment);
            if(offset===null)throw new Error('该文件没有此精确标题锚点；正文与草稿保留。');
            sourceCodePointOffset=offset;if(!current?.dirty)contentSha256=disk.content_sha256;
          }
          await onOpenNote({path:target.path,sourceCodePointOffset,contentSha256,originViewId:viewId,split});
        }else{
          if(!onWorkspaceLink)throw new Error('此对象入口尚未接入工作桌。');
          await onWorkspaceLink({...target,originViewId:viewId});
        }
        // A split or entity handoff must not return focus to the source panel.
        if(target.kind==='note'&&target.path===path&&!split&&context.current===key)host.current?.focus({preventScroll:true});
      }catch(error){if(restoration.current===epoch)setMessage(error instanceof Error?error.message:String(error));report(error);}
      finally{if(context.current===key)setPending(false);}
    }}>
    {message&&<p role="alert">{message}</p>}
    {rangeNotice&&<p role="status" aria-label="阅读选区定位">{rangeNotice}</p>}
    <div dangerouslySetInnerHTML={{__html:html}}/>
  </article>;
}
