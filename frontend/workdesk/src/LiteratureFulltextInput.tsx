import {useEffect,useRef,useSyncExternalStore} from 'react';
import {command,CommandError,refreshConnection,requestId} from './api';
import type {Session} from './session';

type Reference={id:string,revision:number,sha256:string,consumer_id:string};
type Props={session:Session,writable:boolean|null,onOpenReference?:(reference:Reference)=>void|Promise<void>,report:(error:unknown)=>void};
type Intent={project_id:string,pmcid:string,request_key:string};
type Receipt={schema:'literature-fulltext-receipt-v1',project_id:string,pmcid:string,request_key:string,
  state:'dispatched'|'received'|'failed'|'uncertain'|'not_found',
  status:'pending'|'body_paragraphs'|'abstract_only'|'metadata_only'|'unavailable'|'forbidden'|'invalid'|'unknown'|'not_found',
  reference:Reference|null,title:string|null,paragraph_count:number,read_scope:string,license_status:string,
  limitations:string[],source:{sha256:string,bytes:number,media_type:string}|null,error:{code:string,message:string}|null};
type Draft={input:string,intent:Intent|null,receipt:Receipt|null,phase:'idle'|'csrf'|'unknown'|'terminal',
  owner:object|null,operation:'fetch'|'status'|'open'|'refresh'|null,visible:boolean,error:string,notice:string};
type Memory={value:Draft,version:number,listeners:Set<()=>void>,set:(patch:Partial<Draft>)=>void,
  subscribe:(listener:()=>void)=>()=>void,snapshot:()=>number};
const memories=new WeakMap<Session,Map<string,Memory>>();
const blank=():Draft=>({input:'',intent:null,receipt:null,phase:'idle',owner:null,operation:null,visible:false,error:'',notice:''});
const record=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const sha=(value:any)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const id=(value:any)=>typeof value==='string'&&/^[A-Z]+-[A-Za-z0-9]+$/.test(value);
const integer=(value:any)=>Number.isSafeInteger(value)&&value>=0;
const errorText=(error:unknown)=>error instanceof Error?error.message:String(error);
const pmcid=(text:string)=>{const value=text.trim().replace(/^pmc/i,'PMC'),normalized=/^[1-9]\d*$/.test(value)?'PMC'+value:value;return /^PMC[1-9]\d{0,11}$/.test(normalized)?normalized:null;};
function memoryFor(session:Session):Memory {
  let projects=memories.get(session);if(!projects){projects=new Map();memories.set(session,projects);}
  const existing=projects.get(session.project.id);if(existing)return existing;
  const memory:Memory={value:blank(),version:0,listeners:new Set(),set(patch){memory.value={...memory.value,...patch};memory.version++;for(const listener of memory.listeners)listener();},
    subscribe(listener){memory.listeners.add(listener);return()=>{memory.listeners.delete(listener);};},snapshot:()=>memory.version};
  projects.set(session.project.id,memory);return memory;
}
function checkedReceipt(value:any,intent:Intent):Receipt {
  const bad=()=>{throw Error('全文获取回执的请求、来源身份或字段不完整；结果尚未确认，请查询原请求状态。');};
  if(!record(value)||value.schema!=='literature-fulltext-receipt-v1'||
    value.project_id!==intent.project_id||value.pmcid!==intent.pmcid||value.request_key!==intent.request_key||
    !['dispatched','received','failed','uncertain','not_found'].includes(value.state)||
    !['pending','body_paragraphs','abstract_only','metadata_only','unavailable','forbidden','invalid','unknown','not_found'].includes(value.status)||
    !(value.title===null||typeof value.title==='string')||!integer(value.paragraph_count)||
    typeof value.read_scope!=='string'||typeof value.license_status!=='string'||
    !Array.isArray(value.limitations)||value.limitations.some((item:any)=>typeof item!=='string'))bad();
  const ref=value.reference;
  if(ref!==null&&(!record(ref)||!id(ref.id)||!integer(ref.revision)||ref.revision<1||!sha(ref.sha256)||ref.consumer_id!==intent.project_id))bad();
  const pendingStatus={dispatched:'pending',uncertain:'unknown',not_found:'not_found'} as Record<string,string>;
  if(pendingStatus[value.state]&&(value.status!==pendingStatus[value.state]||ref!==null||value.paragraph_count!==0))bad();
  if(['body_paragraphs','abstract_only','metadata_only'].includes(value.status)&&(value.state!=='received'||!ref))bad();
  if(value.status==='body_paragraphs'&&value.paragraph_count===0)bad();
  if(['received','failed'].includes(value.state)&&['pending','unknown','not_found'].includes(value.status))bad();
  if(['unavailable','forbidden','invalid'].includes(value.status)&&(ref!==null||value.paragraph_count!==0))bad();
  if(value.source!==null&&(!record(value.source)||!sha(value.source.sha256)||!integer(value.source.bytes)||typeof value.source.media_type!=='string'||!value.source.media_type))bad();
  if(value.error!==null&&(!record(value.error)||typeof value.error.code!=='string'||typeof value.error.message!=='string'))bad();
  return structuredClone(value);
}
const labels:Record<Receipt['status'],string>={pending:'请求正在处理',body_paragraphs:'已获取正文段落',abstract_only:'仅获取到摘要',metadata_only:'仅获取到元数据',
  unavailable:'公开全文不可用',forbidden:'当前访问被拒绝',invalid:'全文输入或内容无效',unknown:'获取结果尚未确认',not_found:'尚未查到原请求'};
function priorUnknown(error:unknown,intent:Intent):Receipt|null {
  if(!(error instanceof CommandError)||error.code!=='fulltext_prior_unknown')return null;
  const prior=error.details?.receipt;
  if(!record(prior)||typeof prior.request_key!=='string'||!/^[A-Za-z0-9_-]{8,128}$/.test(prior.request_key)||
    !['dispatched','uncertain'].includes(prior.state))return null;
  try{return checkedReceipt(prior,{...intent,request_key:prior.request_key});}catch{return null;}
}

/** One explicit public-article request. Unknown outcomes can only be queried, never resent. */
export function LiteratureFulltextInput({session:s,writable,onOpenReference,report}:Props){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const memory=memoryFor(s);useSyncExternalStore(memory.subscribe,memory.snapshot);
  const scope=useRef({session:s,project:s.project.id,writable,memory}),live=useRef(true);
  // A permission transition invalidates an in-flight display even if permission later returns.
  if(scope.current.session!==s||scope.current.project!==s.project.id||scope.current.writable!==writable)
    scope.current={session:s,project:s.project.id,writable,memory};
  const active=scope.current,d=memory.value;
  useEffect(()=>{live.current=true;return()=>{live.current=false;};},[]);
  useEffect(()=>{if(writable!==true&&memory.value.visible)memory.set({visible:false});},[memory,writable]);
  const request=async(operation:'fetch'|'status')=>{
    const old=memory.value,normalized=pmcid(old.input);
    if(old.owner||old.phase==='csrf'||operation==='fetch'&&(writable!==true||old.intent!==null||!normalized)||operation==='status'&&!old.intent)return;
    const origin=active,owner={},intent=operation==='fetch'?{project_id:origin.project,pmcid:normalized!,request_key:requestId()}:old.intent!;
    const current=()=>live.current&&scope.current===origin;
    origin.memory.set({intent,owner,operation,phase:'unknown',visible:false,error:'',notice:''});
    try{
      const receipt=checkedReceipt(await command('literature.fulltext.'+operation,{...intent}),intent);
      if(origin.memory.value.owner!==owner)return;
      origin.memory.set({receipt,phase:receipt.state==='received'||receipt.state==='failed'?'terminal':'unknown',
        visible:current()&&origin.writable===true,error:receipt.error?.message||''});
    }catch(error){
      const prior=operation==='fetch'?priorUnknown(error,intent):null;
      if(origin.memory.value.owner===owner){
        if(prior)origin.memory.set({intent:{...intent,request_key:prior.request_key},receipt:prior,phase:'unknown',visible:false,error:'',notice:'发现此前未确认请求，仅可查询原状态'});
        // server.post_body rejects CSRF before App dispatch. Only this current
        // initial fetch can await connection refresh; a rejected status cannot clear it.
        else if(operation==='fetch'&&error instanceof CommandError&&error.code==='csrf'&&current())
          origin.memory.set({phase:'csrf',visible:false,error:errorText(error)});
        else origin.memory.set({phase:'unknown',visible:false,error:errorText(error)});
      }
      if(!prior&&current())report(error);
    }finally{
      // Pending ownership survives unmount and scope changes; only this call releases its own lock.
      if(origin.memory.value.owner===owner)origin.memory.set({owner:null,operation:null});
    }
  };
  const refresh=async()=>{
    if(memory.value.owner||memory.value.phase!=='csrf'||writable!==true)return;
    const origin=active,owner={};
    const current=()=>live.current&&scope.current===origin&&origin.memory.value.owner===owner;
    origin.memory.set({owner,operation:'refresh',error:''});
    try{
      if(await refreshConnection(current)&&current())
        origin.memory.set({intent:null,receipt:null,phase:'idle',visible:false,error:'',notice:'连接已刷新；请再次明确获取全文。'});
    }catch(error){
      if(current()){origin.memory.set({error:errorText(error)});report(error);}
    }finally{
      if(origin.memory.value.owner===owner)origin.memory.set({owner:null,operation:null});
    }
  };
  const startAnother=()=>{if(memory.value.owner||memory.value.phase!=='terminal'||writable!==true)return;memory.set(blank());};
  const receipt=writable===true&&d.visible?d.receipt:null;
  const reference=receipt?.state==='received'&&['body_paragraphs','abstract_only','metadata_only'].includes(receipt.status)?receipt.reference:null;
  const open=async()=>{
    if(!reference||!onOpenReference||memory.value.owner||writable!==true)return;
    const origin=active,owner={},ref={id:reference.id,revision:reference.revision,sha256:reference.sha256,consumer_id:origin.project};
    origin.memory.set({owner,operation:'open',error:''});
    try{await onOpenReference(ref);}catch(error){if(live.current&&scope.current===origin){origin.memory.set({visible:false,error:errorText(error)});report(error);}}
    finally{if(origin.memory.value.owner===owner)origin.memory.set({owner:null,operation:null});}
  };
  return <section className="review-panel" aria-label="获取公开全文">
    <h3>获取公开全文</h3><p>所属项目：{s.project.title}。每次明确获取一篇 Europe PMC 公开文章并保存来源，不调用模型。</p>
    <label>PMC编号<input aria-label="PMC编号" value={d.input} placeholder="例如 PMC1234567" disabled={!!d.intent||!!d.owner}
      onChange={event=>{if(!memory.value.intent&&!memory.value.owner)memory.set({input:event.target.value,error:''});}}/></label>
    {!d.intent&&d.input.trim()&&!pmcid(d.input)&&<p role="status">请填写正整数 PMC 编号；此处不接受 URL。</p>}
    {writable!==true&&<p role="status">{writable===null?'正在核对当前项目写入权限；暂不能获取。':'当前项目不可写；来源入口已隐藏，原输入与请求保留。'}</p>}
    <button disabled={writable!==true||!!d.intent||!!d.owner||!pmcid(d.input)} onClick={()=>void request('fetch')}>获取公开全文</button>
    {d.intent&&d.phase!=='csrf'&&<><p>原请求：{d.intent.pmcid}</p><p>请求标识：<code aria-label="原请求标识">{d.intent.request_key}</code></p><button disabled={!!d.owner} onClick={()=>void request('status')}>查询原请求状态</button></>}
    {d.phase==='csrf'&&<><p role="status">获取请求在派发前被拒绝。请先刷新连接，再明确获取；不会重新发送原请求。</p><button disabled={!!d.owner||writable!==true} onClick={()=>void refresh()}>刷新连接</button></>}
    {d.owner&&<p role="status">{d.operation==='fetch'?'获取请求已发送，正在等待回执…':d.operation==='status'?'正在查询原请求状态…':d.operation==='refresh'?'正在刷新连接；不会获取全文…':'正在打开固定来源…'}</p>}
    {d.phase==='unknown'&&<p role="status">原获取结果尚未确认；只能查询原请求状态，不会再次获取。尚未查到请求也不能证明原请求未送达。</p>}
    {d.error&&<p role="alert">{d.error}</p>}
    {d.notice&&<p role="status">{d.notice}</p>}
    {receipt&&<div aria-label="公开全文获取结果">
      <p>{labels[receipt.status]} · 正文段落数：{receipt.paragraph_count}</p>
      {receipt.title!==null&&<h4>{receipt.title}</h4>}
      <p>实际范围：{receipt.read_scope||'未说明'}；许可状态：{receipt.license_status||'未知'}。</p>
      <p>可访问不等于获准再次发布；保存来源不代表科学支持已核查。</p>
      {receipt.limitations.map((text,index)=><p key={index} style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{text}</p>)}
      {reference&&<><p>固定来源：<code>{reference.id}@{reference.revision}</code></p><code>规范 SHA-256 {reference.sha256}</code>
        {onOpenReference&&<button disabled={!!d.owner} onClick={()=>void open()}>查看固定来源</button>}
        <p>如需用于研究委托，请将上方 ID@修订号手动加入“补充已登记来源”，再解析保存来源。不会自动纳入或提交。</p></>}
    </div>}
    {d.phase==='terminal'&&<button disabled={!!d.owner||writable!==true} onClick={startAnother}>开始另一篇</button>}
  </section>;
}
