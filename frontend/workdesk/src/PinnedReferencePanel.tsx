import {useEffect,useLayoutEffect,useRef,useState} from 'react';
import {ReportRevisionForm,type ReportRevisionActions} from './ReportRevisionForm';
export type {ReportRevisionActions} from './ReportRevisionForm';

export type PinnedReference={id:string,revision:number,sha256?:string,block_id?:string,start?:number,end?:number,quote?:string,consumer_id?:string};
type Block={id:string,text:string,kind?:string,[key:string]:unknown};
type Source={id:string,revision:number,project_id?:string|null,title:string,kind:string,content:Record<string,unknown>,canonical_source_sha256?:string};
type Anchor={block?:Block,start?:number,end?:number,error?:string};
type Reading={key:string,status:'loading'|'ready'|'failed',source?:Source,error?:string};
const MAX_RESPONSE_BYTES=1024*1024;
const objectId=(id:unknown):id is string=>typeof id==='string'&&/^[A-Z]+-[A-Za-z0-9]+$/.test(id);
const hash=(sha:unknown)=>typeof sha==='string'&&/^[a-f0-9]{64}$/.test(sha);
function descriptorError(reference:PinnedReference,consumerId:string,projectId:string){
  if(!objectId(reference?.id)||!objectId(consumerId)||!objectId(projectId))return '引用、消费者或项目身份无效；未读取来源。';
  if(reference.consumer_id!==undefined&&reference.consumer_id!==consumerId)return '引用登记的消费者与当前消费身份不匹配；未读取来源。';
  if(!Number.isSafeInteger(reference.revision)||reference.revision<1)return '引用缺少准确修订；未读取最新版本。';
  if(reference.sha256!==undefined&&!hash(reference.sha256))return '登记的 SHA-256 无效；未忽略此身份约束。';
  if(reference.block_id!==undefined&&(typeof reference.block_id!=='string'||!reference.block_id))return '段落身份无效；未替换为其他段落。';
  const range=reference.start!==undefined||reference.end!==undefined,quote=reference.quote!==undefined;
  if((range||quote)&&!reference.block_id)return '文本选区必须绑定准确段落；未猜测其他位置。';
  if(range&&(!Number.isSafeInteger(reference.start)||!Number.isSafeInteger(reference.end)||reference.start!<0||reference.end!<=reference.start!))return '选区需要完整、有效的 Unicode 码点范围。';
  if(quote&&(typeof reference.quote!=='string'||!reference.quote))return '引用原文不能为空；未猜测其他选区。';
  return '';
}
function blocksOf(source:Source):Block[]{return Array.isArray(source.content.blocks)?source.content.blocks as Block[]:[];}

export function locatePinnedText(source:Source,reference:PinnedReference):Anchor{
  if(!reference.block_id)return {};
  const matches=blocksOf(source).filter(block=>block.id===reference.block_id);
  if(matches.length!==1)return {error:matches.length?'指定段落身份重复，无法准确定位；未选择其中一处。':'指定段落在此修订中不存在；未改用其他段落或修订。'};
  const block=matches[0],points=Array.from(block.text);
  if(reference.start!==undefined){
    if(reference.end!>points.length)return {error:'指定 Unicode 码点范围超出此修订原文；未显示其他选区。'};
    const quote=points.slice(reference.start,reference.end).join('');
    if(reference.quote!==undefined&&quote!==reference.quote)return {error:'指定范围与引用原文不匹配；未自动重新定位。'};
    return {block,start:reference.start,end:reference.end};
  }
  if(reference.quote!==undefined){
    const at=block.text.indexOf(reference.quote);
    if(at<0)return {error:'引用原文在指定段落中不存在；未自动重新定位。'};
    if(block.text.indexOf(reference.quote,at+1)>=0)return {error:'引用原文在指定段落中出现多次；请提供准确码点范围。'};
    const start=Array.from(block.text.slice(0,at)).length;
    return {block,start,end:start+Array.from(reference.quote).length};
  }
  return {block};
}
function validateSource(source:any,reference:PinnedReference):Source{
  if(!source||source.id!==reference.id||source.revision!==reference.revision)throw new Error('返回对象或修订与固定引用不符；来源未显示，未改用最新版本。');
  if(typeof source.title!=='string'||typeof source.kind!=='string'||!source.content||typeof source.content!=='object'||Array.isArray(source.content)||!objectId(source.kind==='project'?source.id:source.project_id))throw new Error('指定修订的来源字段无效；内容未显示。');
  if(source.canonical_source_sha256!==undefined&&!hash(source.canonical_source_sha256))throw new Error('服务返回的规范 SHA-256 无效；来源未显示。');
  if(reference.sha256&&source.canonical_source_sha256!==reference.sha256)throw new Error(source.canonical_source_sha256?'规范 SHA-256 与固定引用不符；来源未显示。':'服务未提供该修订的规范 SHA-256；来源未显示。');
  if(source.content.blocks!==undefined&&(!Array.isArray(source.content.blocks)||source.content.blocks.some((block:any)=>!block||typeof block.id!=='string'||!block.id||typeof block.text!=='string')))throw new Error('指定修订的正文块格式无效；未省略坏块后显示为完整内容。');
  return source;
}
async function getObject(url:string,signal:AbortSignal){
  const response=await fetch(url,{method:'GET',credentials:'same-origin',signal});
  const announced=response.headers.get('Content-Length');
  if(announced&&Number(announced)>MAX_RESPONSE_BYTES){await response.body?.cancel();throw new Error('来源响应超过本面板 1 MiB 显示限制，内容未展示；未截断成完整读取结果。');}
  const raw=await response.text();
  if(new TextEncoder().encode(raw).byteLength>MAX_RESPONSE_BYTES)throw new Error('来源响应超过本面板 1 MiB 显示限制，内容未展示；未截断成完整读取结果。');
  let body:any;try{body=JSON.parse(raw);}catch{throw new Error('指定修订响应不是有效 JSON；内容未显示。');}
  if(!response.ok||body?.ok!==true){
    if(response.status===401||response.status===403)throw new Error('当前身份或消费者没有此来源权限；内容未显示。');
    if(response.status===404)throw new Error('指定对象或修订不存在；未改用最新版本。');
    throw new Error(typeof body?.error==='string'?body.error:'指定修订读取失败；内容未显示。');
  }
  return body.result;
}

export function PinnedReferencePanel({reference,consumerId,projectId,onClose,report,revisionActions}:{reference:PinnedReference,consumerId:string,projectId:string,onClose?:()=>void,report:(error:unknown)=>void,revisionActions?:ReportRevisionActions}){
  const key=JSON.stringify([reference,consumerId,projectId]);
  const [reading,setReading]=useState<Reading>({key,status:'loading'}),[reload,setReload]=useState(0);
  const sequence=useRef(0),latest=useRef(key);latest.current=key;
  const targetElement=useRef<HTMLElement|null>(null);
  const invalid=descriptorError(reference,consumerId,projectId);
  useEffect(()=>{
    const ticket=++sequence.current,controller=new AbortController();let live=true;
    const current=()=>live&&ticket===sequence.current&&latest.current===key;
    setReading({key,status:'loading'});
    if(invalid){setReading({key,status:'failed',error:invalid});return()=>{live=false;controller.abort();};}
    (async()=>{
      try{
        // The API does not echo the consumer. Read its current identity first;
        // the pinned source GET then independently enforces current shared ACL.
        const consumer=await getObject('/api/objects/'+encodeURIComponent(consumerId),controller.signal);
        if(!current())return;
        if(consumer?.id!==consumerId||typeof consumer.kind!=='string'||!consumer.kind||(consumer.kind==='project'?consumer.id:consumer.project_id)!==projectId)throw new Error('消费者与当前项目身份不匹配；未读取来源。');
        const query=new URLSearchParams({revision:String(reference.revision),consumer:consumerId});
        const result=await getObject('/api/objects/'+encodeURIComponent(reference.id)+'?'+query,controller.signal);
        if(!current())return;
        // Shared sources may belong to another project. Do not replace the
        // server's consumer access decision with an owner-project equality test.
        const source=validateSource(result,reference);
        if(current())setReading({key,status:'ready',source});
      }catch(error){if(current()){setReading({key,status:'failed',error:String(error)});report(error);}}
    })();
    return()=>{live=false;controller.abort();};
  },[key,reload,invalid]);
  const source=reading.key===key&&reading.status==='ready'?reading.source:undefined;
  const anchor=source?locatePinnedText(source,reference):{};
  const blocks=source?blocksOf(source):[];
  useLayoutEffect(()=>{
    if(reading.key===key&&reading.status==='ready'&&!anchor.error)
      targetElement.current?.scrollIntoView({block:'nearest',inline:'nearest'});
  },[key,reading.key,reading.status]);
  if(source?.kind==='report')return <section className="pinned-reference-panel pinned-reference-panel--report" aria-label="固定修订来源阅读">
    <div className="pinned-report-toolbar">
      <strong>只读报告 · 固定 r{source.revision}</strong>
      <button onClick={()=>setReload(value=>value+1)}>重新读取固定修订</button>
      {onClose&&<button onClick={onClose}>关闭来源阅读</button>}
    </div>
    {revisionActions&&<ReportRevisionForm key={key} projectId={projectId} actions={revisionActions} report={report}
      target={{id:source.id,revision:source.revision,sha256:source.canonical_source_sha256||'',title:source.title,project_id:source.project_id||'',source_refs:source.content.source_refs}}/>}
    <article className="pinned-report-reading" aria-label="报告连续正文">
      <h2>{source.title}</h2>
      <p className="pinned-report-boundary">登记来源关系不代表证据支持已核查；关闭后返回现稿，当前草稿保留。</p>
      {!reference.sha256&&<p role="status">未登记引用 SHA-256；本次绑定对象与指定修订。</p>}
      {anchor.error&&<p role="alert">{anchor.error} 以下保留该修订原文，尚未定位指定选区。</p>}
      {anchor.block&&<p role="status">已定位段落 {anchor.block.id}{anchor.start!==undefined?` · Unicode 码点 ${anchor.start}–${anchor.end}`:''}</p>}
      {!blocks.length&&<p>此修订未登记正文块；保存字段见下方。</p>}
      {blocks.map((block,index)=>{
        const target=anchor.block===block,points=target&&anchor.start!==undefined?Array.from(block.text):null;
        return <section key={index} data-report-block={block.id} data-block-kind={block.kind} ref={target&&!points?targetElement:undefined}
          aria-label={'历史段落 '+block.id} className={'pinned-report-block'+(target?' pinned-reference-target':'')}>
          <p data-report-text aria-label={'历史段落原文 '+block.id}>{points?<>{points.slice(0,anchor.start).join('')}<mark ref={targetElement} aria-label="引用选区">{points.slice(anchor.start,anchor.end).join('')}</mark>{points.slice(anchor.end).join('')}</>:block.text}</p>
        </section>;
      })}
      {['claims','rationale'].filter(field=>source.content[field]!==undefined).map(field=><details className="pinned-report-field" key={field}>
        <summary>原保存字段：{field}</summary><pre>{typeof source.content[field]==='string'?source.content[field] as string:JSON.stringify(source.content[field],null,2)}</pre>
      </details>)}
      <details className="pinned-report-identity">
        <summary>该修订保存字段（JSON）</summary>
        <small>引用 {reference.id} · r{source.revision} · 消费者 {consumerId} · 项目 {projectId}</small>
        <small>{source.kind} · 来源项目 {source.project_id}</small>
        {source.canonical_source_sha256&&<code>规范 SHA-256 {source.canonical_source_sha256}</code>}
        <pre aria-label="历史保存字段">{JSON.stringify(source.content,null,2)}</pre>
      </details>
    </article>
  </section>;
  return <section className="pinned-reference-panel" aria-label="固定修订来源阅读">
    <div className="pinned-reference-heading"><h2>固定修订来源</h2>{onClose&&<button onClick={onClose}>关闭来源阅读</button>}</div>
    <p>只读指定修订；关闭后返回现稿，当前草稿保留。登记来源关系不代表证据支持已核查。</p>
    <small>引用 {reference.id} · r{String(reference.revision)} · 消费者 {consumerId} · 项目 {projectId}</small>
    <button disabled={!!invalid} onClick={()=>setReload(value=>value+1)}>重新读取固定修订</button>
    {invalid?<p role="alert">{invalid}</p>:reading.key!==key||reading.status==='loading'?<p role="status">读取固定修订…</p>:reading.status==='failed'?<p role="alert">{reading.error}</p>:null}
    {source&&<>
      <h3>{source.title}</h3><small>{source.kind} · {source.id} · r{source.revision} · 来源项目 {source.kind==='project'?source.id:source.project_id}</small>
      {source.canonical_source_sha256&&<code>规范 SHA-256 {source.canonical_source_sha256}</code>}
      {!reference.sha256&&<p role="status">未登记引用 SHA-256；本次绑定对象与指定修订。</p>}
      {anchor.error&&<p role="alert">{anchor.error} 以下保留该修订原文，尚未定位指定选区。</p>}
      {anchor.block&&<p role="status">已定位段落 {anchor.block.id}{anchor.start!==undefined?` · Unicode 码点 ${anchor.start}–${anchor.end}`:''}</p>}
      {!blocks.length&&<p>此修订未登记正文块；保存字段见下方。</p>}
      <div className="pinned-reference-blocks">{blocks.map((block,index)=>{
        const target=anchor.block===block,points=target&&anchor.start!==undefined?Array.from(block.text):null;
        return <article key={index} ref={target&&!points?targetElement:undefined} aria-label={'历史段落 '+block.id} className={target?'pinned-reference-target':''}>
          <small>段落 {block.id}{block.kind?' · '+block.kind:''}</small>
          <pre tabIndex={0} aria-label={'历史段落原文 '+block.id}>{points?<>{points.slice(0,anchor.start).join('')}<mark ref={targetElement} aria-label="引用选区">{points.slice(anchor.start,anchor.end).join('')}</mark>{points.slice(anchor.end).join('')}</>:block.text}</pre>
        </article>;
      })}</div>
      <details><summary>该修订保存字段（JSON）</summary><pre aria-label="历史保存字段">{JSON.stringify(source.content,null,2)}</pre></details>
    </>}
  </section>;
}
