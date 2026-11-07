import {useEffect,useRef,useState} from 'react';
import './ReviewVisualPreview.css';

export type ReviewVisualPreviewIdentity={
  project_id:string;task_id:string;candidate_sha256:string;proposal_sha256:string;
  decision_version:number;target_revisions:Record<string,number>;change_ids:string[];
};
export type ReviewVisualPreviewFigure={
  object_id:string;title:string;base_revision:number;base_source_sha256:string;candidate_source_sha256:string;
  asset:{url:string;sha:string;media_type:string};numeric_preserved:true;
};
export type ReviewVisualPreviewResult={
  preview_identity:ReviewVisualPreviewIdentity&{saved:false;official_export_recorded:false};
  figures:ReviewVisualPreviewFigure[];
};
export type ReviewVisualPreviewProps={
  identity:ReviewVisualPreviewIdentity;disabled:boolean;load:()=>Promise<ReviewVisualPreviewResult>;onError?:(error:Error)=>void;
};

const sha=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const positive=(value:unknown)=>Number.isSafeInteger(value)&&Number(value)>0;
function identityKey(value:ReviewVisualPreviewIdentity):string{
  if(!value||typeof value.project_id!=='string'||!value.project_id||typeof value.task_id!=='string'||!value.task_id||
    !sha(value.candidate_sha256)||!sha(value.proposal_sha256)||!Number.isSafeInteger(value.decision_version)||value.decision_version<0||
    !value.target_revisions||Array.isArray(value.target_revisions)||typeof value.target_revisions!=='object'||
    !Object.keys(value.target_revisions).length||Object.entries(value.target_revisions).some(([id,r])=>!id||!positive(r))||
    !Array.isArray(value.change_ids)||!value.change_ids.length||value.change_ids.some(id=>typeof id!=='string'||!id)||new Set(value.change_ids).size!==value.change_ids.length)return '';
  return JSON.stringify([value.project_id,value.task_id,value.candidate_sha256,value.proposal_sha256,value.decision_version,
    Object.entries(value.target_revisions).sort(([a],[b])=>a.localeCompare(b)),value.change_ids]);
}
function checkedResult(value:ReviewVisualPreviewResult,expected:ReviewVisualPreviewIdentity):ReviewVisualPreviewFigure[]{
  if(!value?.preview_identity||identityKey(value.preview_identity)!==identityKey(expected)||value.preview_identity.saved!==false||value.preview_identity.official_export_recorded!==false)
    throw Error('候选图回执与当前固定候选不一致；未展示其他版本。');
  if(!Array.isArray(value.figures)||!value.figures.length)throw Error('本次没有返回实际候选图。');
  const seen=new Set<string>();
  for(const row of value.figures){
    if(!row||typeof row.object_id!=='string'||seen.has(row.object_id)||typeof row.title!=='string'||
      row.base_revision!==expected.target_revisions[row.object_id]||!positive(row.base_revision)||!sha(row.base_source_sha256)||!sha(row.candidate_source_sha256)||
      row.numeric_preserved!==true||!row.asset||!sha(row.asset.sha)||row.asset.url!=='/api/assets/'+row.asset.sha||
      !['image/svg+xml','image/png'].includes(row.asset.media_type))throw Error('实际候选图的来源、范围或数值保护不完整；预览已清除。');
    seen.add(row.object_id);
  }
  return value.figures;
}

// The same authenticated asset route used by FigureBody, displayed strictly as
// an image. Never place renderer SVG/HTML into the document's live DOM.
async function readImage(row:ReviewVisualPreviewFigure,signal:AbortSignal):Promise<Uint8Array>{
  const response=await fetch(row.asset.url,{credentials:'same-origin',redirect:'error',signal});
  if(response.status===403)throw Error('当前无权读取候选图；预览已清除。');
  if(!response.ok)throw Error('候选图读取失败（'+response.status+'）；原稿与候选保留。');
  if(response.headers.get('content-type')?.split(';')[0].trim()!==row.asset.media_type)throw Error('候选图实际媒体类型不一致；未显示返回内容。');
  // Match the existing staged preview output bound, including streamed bodies.
  const maximum=128000000,reader=response.body?.getReader(),parts:Uint8Array[]=[];let size=0;
  if(!reader)throw Error('候选图没有可校验的实际字节。');
  try{while(true){const part=await reader.read();if(part.done)break;size+=part.value.length;if(size>maximum)throw Error('候选图超出本次预览大小限制。');parts.push(part.value);}}
  catch(error){await reader.cancel().catch(()=>{});throw error;}
  const bytes=new Uint8Array(size);let offset=0;for(const part of parts){bytes.set(part,offset);offset+=part.length;}
  const actual=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),b=>b.toString(16).padStart(2,'0')).join('');
  if(actual!==row.asset.sha)throw Error('候选图实际字节与固定资产摘要不一致；预览已清除。');
  return bytes;
}

type ImageRow=ReviewVisualPreviewFigure&{imageUrl:string};
type State={key:string;status:'idle'|'loading'|'ready'|'error';rows:ImageRow[];loaded:string[];error?:string};
type Job={key:string;controller:AbortController;urls:string[]};

export function ReviewVisualPreview({identity,disabled,load,onError}:ReviewVisualPreviewProps){
  const key=identityKey(identity),latest=useRef({key,disabled,load,onError});latest.current={key,disabled,load,onError};
  const job=useRef<Job|null>(null),[state,setState]=useState<State>({key,status:'idle',rows:[],loaded:[]});
  const cancel=()=>{const prior=job.current;job.current=null;if(prior){prior.controller.abort();prior.urls.forEach(url=>URL.revokeObjectURL(url));}};
  useEffect(()=>{cancel();setState({key,status:'idle',rows:[],loaded:[]});return cancel;},[key,disabled]);
  const visible=!disabled&&!!key&&state.key===key;
  const run=async()=>{
    if(latest.current.disabled||!key||state.status==='loading'&&state.key===key)return;
    cancel();const currentJob:Job={key,controller:new AbortController(),urls:[]};job.current=currentJob;
    const current=()=>job.current===currentJob&&latest.current.key===key&&!latest.current.disabled;
    const fail=(error:unknown)=>{if(!current())return;cancel();const problem=error instanceof Error?error:Error('候选图预览失败。');setState({key,status:'error',rows:[],loaded:[],error:problem.message});latest.current.onError?.(problem);};
    setState({key,status:'loading',rows:[],loaded:[]});const expected=structuredClone(identity);
    try{
      const value=await latest.current.load();if(!current())return;
      const figures=checkedResult(value,expected),images=await Promise.all(figures.map(row=>readImage(row,currentJob.controller.signal)));
      if(!current())return;
      const rows=figures.map((row,index)=>{const imageUrl=URL.createObjectURL(new Blob([images[index].slice().buffer],{type:row.asset.media_type}));currentJob.urls.push(imageUrl);return {...row,imageUrl};});
      setState({key,status:'loading',rows,loaded:[]});
    }catch(error){fail(error);}
  };
  const imageFailed=(url:string)=>{
    if(!job.current||job.current.key!==key||!job.current.urls.includes(url)||latest.current.disabled)return;
    cancel();const error=Error('实际候选图不能显示；预览已清除。');setState({key,status:'error',rows:[],loaded:[],error:error.message});latest.current.onError?.(error);
  };
  const imageLoaded=(id:string,url:string)=>setState(value=>{
    if(!job.current||job.current.key!==key||!job.current.urls.includes(url)||latest.current.key!==key||latest.current.disabled||value.key!==key||!value.rows.some(row=>row.object_id===id))return value;
    const loaded=[...new Set([...value.loaded,id])];return {...value,loaded,status:loaded.length===value.rows.length?'ready':'loading'};
  });
  return <section className="review-visual-preview" aria-label="固定候选图预览" data-preview-state={visible?state.status:'idle'}>
    <button type="button" disabled={disabled||!key||visible&&state.status==='loading'} onClick={()=>void run()}>预览此候选图/关联组</button>
    <p className="quiet">预览尚未采用；只展示此固定候选中的图，原稿保持保存版。</p>
    {visible&&state.status==='loading'&&<p role="status">正在读取实际候选图…</p>}
    {visible&&state.error&&<p role="alert">{state.error}</p>}
    {visible&&state.rows.length>0&&<div className="review-visual-preview-images">{state.rows.map(row=><figure key={row.object_id} data-object-id={row.object_id} data-asset-sha={row.asset.sha}>
      <figcaption>{row.title} · 基于保存版 r{row.base_revision} · 未采用</figcaption>
      <img src={row.imageUrl} alt={'实际候选图 '+row.title} onLoad={()=>imageLoaded(row.object_id,row.imageUrl)} onError={()=>imageFailed(row.imageUrl)}/>
    </figure>)}</div>}
    {visible&&state.status==='ready'&&<p role="status">实际候选图已显示 · 未采用</p>}
  </section>;
}
