import {useEffect,useRef,useState} from 'react';
import {getDocument,GlobalWorkerOptions,type PDFDocumentProxy} from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import type {RenderRecord} from './types';
GlobalWorkerOptions.workerSrc=workerUrl;

export default function PdfPreview({record,revision,dirty}:{record:RenderRecord|null;revision:number;dirty:boolean}) {
  const host=useRef<HTMLDivElement>(null),[pdf,setPdf]=useState<PDFDocumentProxy|null>(null),[error,setError]=useState(''),[width,setWidth]=useState(0);
  useEffect(()=>{if(!host.current)return;const observer=new ResizeObserver(([entry])=>setWidth(entry.contentRect.width));observer.observe(host.current);return()=>observer.disconnect();},[]);
  useEffect(()=>{
    setPdf(null);setError('');if(!record)return;
    const sha=typeof record.asset==='string'?record.asset:record.asset.sha;
    const loading=getDocument({url:'/api/assets/'+encodeURIComponent(sha),withCredentials:true,
      cMapUrl:import.meta.env.BASE_URL+'pdfjs/cmaps/',cMapPacked:true,
      standardFontDataUrl:import.meta.env.BASE_URL+'pdfjs/standard_fonts/'});let alive=true;
    loading.promise.then(value=>{if(alive)setPdf(value);}).catch(e=>{if(alive)setError(String(e));});
    return()=>{alive=false;void loading.destroy();};
  },[record?.source_sha256]);
  useEffect(()=>{
    const target=host.current;if(!target||!pdf||!width)return;let cancelled=false;const jobs:{cancel:()=>void}[]=[];
    const render=async()=>{target.replaceChildren();for(let n=1;n<=pdf.numPages;n++){
      if(cancelled)return;const page=await pdf.getPage(n);if(cancelled)return;
      const natural=page.getViewport({scale:1}),scale=Math.min(1.4,Math.max(0.2,(target.clientWidth-32)/natural.width));
      const viewport=page.getViewport({scale}),canvas=document.createElement('canvas'),density=window.devicePixelRatio||1;
      canvas.width=viewport.width*density;canvas.height=viewport.height*density;canvas.style.width=viewport.width+'px';canvas.style.height=viewport.height+'px';canvas.setAttribute('role','img');canvas.setAttribute('aria-label','PDF 第 '+n+' 页');target.append(canvas);
      const job=page.render({canvas,viewport,transform:density===1?undefined:[density,0,0,density,0,0]});jobs.push(job);await job.promise.then(()=>{if(!cancelled)canvas.dataset.rendered='true';}).catch(e=>{if(!cancelled)setError(String(e));});
    }};
    void render().catch(e=>{if(!cancelled)setError(String(e));});return()=>{cancelled=true;jobs.forEach(job=>job.cancel());target.replaceChildren();};
  },[pdf,width]);
  return <section className="native-pdf-preview" aria-label="论文 PDF 预览"><div className="pdf-preview-status">{record?`${dirty||record.revision!==revision?'旧预览 · ':''}源版本 r${record.revision}`:'保存并编译后查看 PDF'}{record&&<a href={'/api/assets/'+encodeURIComponent(typeof record.asset==='string'?record.asset:record.asset.sha)} target="_blank" rel="noreferrer">打开 PDF</a>}</div>{error&&<p role="alert">PDF 打开失败：{error}</p>}<div ref={host} className="native-pdf-pages"/>{!record&&<p className="editor-empty">编译结果会在这里显示，保留对应的源版本。</p>}</section>;
}
