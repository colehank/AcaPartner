import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {command,requestId} from './api';
import type {Session} from './session';
import './paper-caption-review.css';

export type CaptionSelection={field:'caption',component_id:string,quote:string,start:number,end:number};
// Session owns persistence/serialization. This explicit capability also keeps
// isolated older Session types from pretending that local React state is saved.
export type CaptionDraftSession=Session&{captionDrafts:Record<string,any>,setCaptionDrafts:(rows:Record<string,any>)=>void};
type CaptionDraft={key:string,project:string,paper:string,index:number,component:string,componentRevision:any,
  base:number,binding:string,identity:string,before:string,text:string,opinion:string,anchor:CaptionSelection|null,
  anchorCaption:string,selectedOpinion:string,epoch:number,busy:string|null,error:string,notice:string};
const stable=(value:any):string=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?
  Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item)??'undefined';
const identity=(ref:any)=>stable(Object.fromEntries(Object.entries(ref).filter(([key])=>key!=='caption')));
const componentId=(ref:any)=>ref?.id||ref?.object_id;
const active=(row:CaptionDraft)=>row.text!==row.before||!!row.opinion||!!row.anchor||!!row.selectedOpinion||!!row.busy;
const sourceRef=(s:Session,row:CaptionDraft)=>s.project.id===row.project&&s.paper?.id===row.paper?s.paper.content.components?.[row.index]:undefined;
const matches=(s:Session,row:CaptionDraft)=>{const ref=sourceRef(s,row);return !!ref&&typeof ref.caption==='string'&&stable(ref)===row.binding;};
function capture(s:Session,index:number):CaptionDraft|null{
  const ref=s.paper?.content.components?.[index],id=componentId(ref);
  if(typeof id!=='string'||typeof ref?.caption!=='string')return null;
  return {key:s.project.id+':'+s.paper.id+':'+index,project:s.project.id,paper:s.paper.id,index,component:id,componentRevision:ref.revision,
    base:s.paper.revision,binding:stable(ref),identity:identity(ref),before:ref.caption,text:ref.caption,opinion:'',anchor:null,
    anchorCaption:'',selectedOpinion:'',epoch:0,busy:null,error:'',notice:''};
}
function initialRows(s:CaptionDraftSession){
  const rows:Record<string,CaptionDraft>={};(s.paper?.content.components||[]).forEach((_ref:any,index:number)=>{const row=capture(s,index);if(row)rows[row.key]=row;});
  for(const saved of Object.values(s.captionDrafts||{})){
    if(!saved||saved.project!==s.project.id||saved.paper!==s.paper?.id||!Number.isInteger(saved.index)||saved.index<0||
      saved.key!==saved.project+':'+saved.paper+':'+saved.index||!['component','binding','identity','before','text','opinion','anchorCaption','selectedOpinion','error','notice'].every(key=>typeof saved[key]==='string')||
      !Number.isInteger(saved.base)||!Number.isInteger(saved.epoch))continue;
    const row={...saved,busy:null} as CaptionDraft;
    if(row.anchor&&!(row.anchor.field==='caption'&&row.anchor.component_id===row.component&&typeof row.anchor.quote==='string'&&
      Number.isInteger(row.anchor.start)&&Number.isInteger(row.anchor.end)&&row.anchor.start>=0&&row.anchor.end>row.anchor.start))row.anchor=null;
    const fresh=rows[row.key];
    if(active(row)||row.error)rows[row.key]=fresh&&fresh.binding===row.binding?{...row,base:fresh.base}:row;
  }
  return rows;
}
function persistRows(s:CaptionDraftSession,rows:Record<string,CaptionDraft>){
  // A reopened panel has no ownership of a preceding in-flight request. Keep
  // its inputs/baselines, never a busy token or automatic retry instruction.
  const saved:Record<string,CaptionDraft>={};
  for(const row of Object.values(s.captionDrafts||{}))if(row?.project===s.project.id&&row.paper!==s.paper?.id)saved[row.key]={...row,busy:null};
  for(const row of Object.values(rows))if(row.project===s.project.id&&row.paper===s.paper?.id&&(active(row)||row.error))saved[row.key]={...row,busy:null};
  s.setCaptionDrafts(saved);
}
function isBoundary(text:string,offset:number){return !(offset>0&&offset<text.length&&text.charCodeAt(offset-1)>=0xd800&&text.charCodeAt(offset-1)<=0xdbff&&text.charCodeAt(offset)>=0xdc00&&text.charCodeAt(offset)<=0xdfff);}
export function captionSelection(text:string,start:number,end:number,id:string):CaptionSelection|null{
  if(!Number.isInteger(start)||!Number.isInteger(end)||start<0||end<=start||end>text.length||!isBoundary(text,start)||!isBoundary(text,end))return null;
  return {field:'caption',component_id:id,quote:text.slice(start,end),start:Array.from(text.slice(0,start)).length,end:Array.from(text.slice(0,end)).length};
}
function selectionValid(row:CaptionDraft){return !!row.anchor&&row.anchorCaption===row.before&&Array.from(row.before).slice(row.anchor.start,row.anchor.end).join('')===row.anchor.quote;}

// Each draft belongs to an exact saved occurrence. Object CAS protects the full
// latest manuscript; only this occurrence's caption is changed in its content.
export function PaperCaptionReview({session:s,report,onReview}:{session:CaptionDraftSession,report:(error:unknown)=>void,onReview:()=>void}){
  const version=useSyncExternalStore(s.subscribe,s.snapshot);
  const [rows,setRows]=useState(()=>initialRows(s)),[review,setReview]=useState<any>(null),[reviewError,setReviewError]=useState('');
  const rowsRef=useRef(rows),currentSession=useRef(s),rowsOwner=useRef(s),mounted=useRef(true),reviewRead=useRef(0);
  rowsRef.current=rows;currentSession.current=s;
  const update=(fn:(old:Record<string,CaptionDraft>)=>Record<string,CaptionDraft>)=>{const next=fn(rowsRef.current);rowsRef.current=next;
    // This closure writes only its owning Session. A late old-panel response
    // cannot redirect persisted caption inputs into the newly selected project.
    persistRows(s,next);if(mounted.current)setRows(next);};
  const patch=(key:string,fn:(row:CaptionDraft)=>CaptionDraft)=>update(old=>old[key]?{...old,[key]:fn(old[key])}:old);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{
    const switched=rowsOwner.current!==s;rowsOwner.current=s;
    update(old=>{
      const next={...old},fresh=initialRows(s);
      if(switched){for(const [key,row] of Object.entries(next))if(row.project===s.project.id&&row.paper===s.paper?.id)delete next[key];Object.assign(next,fresh);return next;}
      for(const [key,row] of Object.entries(fresh)){
        const previous=old[key];
        if(!previous||previous.project!==s.project.id||previous.paper!==s.paper?.id)next[key]=row;
        else if(previous.binding===row.binding)next[key]={...previous,base:row.base};
        else if(!active(previous))next[key]=row;
      }
      for(const [key,row] of Object.entries(old))if(row.project===s.project.id&&row.paper===s.paper?.id&&!fresh[key]&&!active(row))delete next[key];
      return next;
    });
  },[s,s.paper?.id,s.paper?.revision,stable(s.paper?.content.components||[])]);
  const loadReview=async()=>{
    const sequence=++reviewRead.current,project=s.project.id;
    try{const value=await command('desk.review.read',{project_id:project});if(mounted.current&&currentSession.current===s&&sequence===reviewRead.current){setReview(value);setReviewError('');}return value;}
    catch(error){if(mounted.current&&currentSession.current===s&&sequence===reviewRead.current)setReviewError(String(error));throw error;}
  };
  useEffect(()=>{setReview(null);void loadReview().catch(report);},[s,s.paper?.id,s.paper?.revision]);
  const fail=(row:CaptionDraft,message:string)=>{patch(row.key,value=>({...value,error:message,notice:''}));throw new Error(message);};
  const guard=(row:CaptionDraft,opinion=false)=>{
    if(currentSession.current!==s||!mounted.current)throw new Error('当前稿件窗口已切换；原草稿保留。');
    if(!s.paperDraft||s.paperDraft.dirty)fail(row,'请先保存或撤销正文草稿；本地图注和意见草稿保留。');
    if(!matches(s,row))fail(row,'保存版图注或所在位置已变化；本地草稿和原选区保留，请比较后明确选择基线。');
    if(opinion){
      if(row.text!==row.before)fail(row,'请先保存此位置的图注草稿，再从保存版选择意见原文。');
      if((s.paper.content.components||[]).filter((ref:any)=>componentId(ref)===row.component).length!==1)fail(row,'同一组件在稿件中出现多次；图注意见需要唯一位置，逐位置手改仍可保存。');
      if(!selectionValid(row))fail(row,'请在保存版图注中重新选择准确原文；意见草稿保留。');
    }
  };
  const currentOperation=(key:string,token:string)=>mounted.current&&currentSession.current===s&&rowsRef.current[key]?.busy===token;
  const finishOperation=(key:string,token:string)=>{if(mounted.current&&rowsRef.current[key]?.busy===token)patch(key,value=>({...value,busy:null,
    ...(currentSession.current===s?{}:{error:'请求期间已切换稿件窗口；原草稿保留，请重新读取保存版。'})}));};
  const save=async(key:string)=>{
    const row=rowsRef.current[key],token=requestId();if(!row)return;
    patch(key,value=>({...value,busy:token,error:'',notice:''}));let returned=false;
    try{
      guard(row);await s.flush();guard(rowsRef.current[key]);if(!s.persisted)fail(row,'当前草稿状态未保存；本地图注草稿保留，请处理保存错误。');
      const sent=rowsRef.current[key].text,paper=structuredClone(s.paper),ref=paper.content.components[row.index];
      const content=structuredClone(paper.content);content.components[row.index]={...ref,caption:sent};
      const result=await command('object.save',{id:paper.id,expected_revision:paper.revision,content});returned=true;
      if(!currentOperation(key,token))return;
      if(result.id!==paper.id||result.revision<=paper.revision||stable(result.content)!==stable(content))throw new Error('保存响应的稿件身份或图注内容不一致；本地草稿保留。');
      // Never put the returned object into Session. A newer visible source wins;
      // the common refresh method also fences late lower-revision read replies.
      if(s.paper?.id!==paper.id)throw new Error('保存期间已切换稿件；原草稿保留。');
      if(s.paper.revision<=result.revision)await s.refreshPaper();
      if(!currentOperation(key,token))return;
      const latest=sourceRef(s,row);
      if(!latest||identity(latest)!==row.identity||latest.caption!==sent)throw new Error('图注已保存，但当前保存版又有变化；本地草稿保留，请比较后继续。');
      patch(key,value=>({...value,base:s.paper.revision,binding:stable(latest),before:sent,error:'',
        notice:value.text===sent?'图注已保存；重新编译可查看本次 PDF。':'已保存发送时的图注；后续输入仍在本地草稿。'}));
      await s.flush();
      if(!s.persisted)patch(key,value=>({...value,error:'图注已保存，但当前草稿状态尚未持久化；本地输入保留。'}));
    }catch(error){if(currentOperation(key,token))patch(key,value=>({...value,error:(returned?'保存请求已返回；':'')+String(error),notice:''}));report(error);}
    finally{finishOperation(key,token);}
  };
  const opinion=async(key:string,op:'create'|'reanchor')=>{
    const row=rowsRef.current[key],token=requestId();if(!row)return;
    patch(key,value=>({...value,busy:token,error:'',notice:''}));
    try{
      guard(row,true);if(op==='create'&&!row.opinion.trim())fail(row,'请填写图注修改意见。');
      if(op==='reanchor'&&!row.selectedOpinion)fail(row,'请选择要重新定位的既有图注意见。');
      const anchor={...row.anchor!},text=row.opinion,selected=row.selectedOpinion;
      await s.flush();guard(rowsRef.current[key],true);if(!s.persisted)fail(row,'当前草稿状态未保存；图注意见草稿保留，请处理保存错误。');
      const latest=await command('desk.review.read',{project_id:s.project.id});guard(rowsRef.current[key],true);
      if(op==='reanchor'){
        const existing=latest.opinions.find((item:any)=>item.id===selected),ann=latest.annotations.find((item:any)=>item.id===selected);
        if(!existing||existing.deleted||ann?.anchor?.field!=='caption'||ann.anchor.component_id!==row.component)fail(row,'既有意见或图注目标已变化；请重新读取和选择。');
      }
      await command('desk.review.change',{project_id:s.project.id,expected_review_revision:latest.revision,expected_manuscript_revision:s.paper.revision,
        op,field:'caption',component_id:row.component,anchor,...(op==='create'?{text}:{id:selected})});
      if(!currentOperation(key,token))return;
      patch(key,value=>({...value,opinion:op==='create'&&value.opinion===text?'':value.opinion,error:'',
        notice:op==='create'?'图注意见已加入本轮；可在整轮意见中删除、恢复或提交。':'已明确重新定位；原意见正文和历史保留。'}));
      await loadReview();
    }catch(error){if(currentOperation(key,token))patch(key,value=>({...value,error:String(error),notice:''}));report(error);}
    finally{finishOperation(key,token);}
  };
  const rebase=(row:CaptionDraft)=>{
    const ref=sourceRef(s,row);if(!ref||identity(ref)!==row.identity||typeof ref.caption!=='string')return;
    patch(row.key,value=>({...value,base:s.paper.revision,binding:stable(ref),before:ref.caption,error:'',notice:'已明确选择当前保存版作为基线；本地输入保留。'}));
  };
  const discard=(row:CaptionDraft)=>{const fresh=capture(s,row.index);update(old=>{const next={...old};if(fresh)next[row.key]=fresh;else delete next[row.key];return next;});};
  const visible=Object.values(rows).filter(row=>row.project===s.project.id&&row.paper===s.paper?.id).sort((a,b)=>a.index-b.index);
  const bodyDirty=!s.paperDraft||s.paperDraft.dirty,busy=visible.some(row=>!!row.busy);
  return <section className="paper-caption-review" aria-label="保存版图注与意见" data-session-version={version}>
    <div className="caption-review-heading"><h2>保存版图注与意见</h2><button onClick={onReview}>查看整轮意见</button><button disabled={busy} onClick={()=>void loadReview().catch(report)}>刷新图注意见</button></div>
    <p>直接修改稿内图注，或从保存版选择原文加入本轮意见。图的保存版本与数据保持原身份。</p>
    {bodyDirty&&<p role="status">正文有未保存草稿；先保存或撤销正文，再保存图注或固定意见选区。</p>}
    {reviewError&&<p role="alert">{reviewError}</p>}
    {!visible.length&&<p>当前保存稿没有明确的稿内图注。请先将保存版图插入稿件并填写图注。</p>}
    {visible.map(row=>{
      const number=row.index+1,ref=sourceRef(s,row),stale=!matches(s,row),dirty=row.text!==row.before;
      const duplicate=(s.paper.content.components||[]).filter((item:any)=>componentId(item)===row.component).length!==1;
      const existing=(review?.opinions||[]).filter((item:any)=>{const ann=review?.annotations?.find((a:any)=>a.id===item.id);return ann?.anchor?.field==='caption'&&ann.anchor.component_id===row.component;});
      const selected=existing.find((item:any)=>item.id===row.selectedOpinion),annotation=review?.annotations?.find((a:any)=>a.id===row.selectedOpinion);
      const canOpinion=!busy&&!bodyDirty&&!stale&&!dirty&&!duplicate&&selectionValid(row);
      return <article className="paper-caption-position" aria-label={'稿内图注位置 '+number} key={row.key}>
        <h3>位置 {number} · 稿内图注</h3><small>组件 {row.component} · 固定图版本 r{row.componentRevision??'未声明'} · 图注基线稿件 r{row.base}</small>
        <label>保存版图注<textarea readOnly aria-label={'保存版图注 '+number} value={row.before} onSelect={event=>{
          const target=event.currentTarget,anchor=captionSelection(row.before,target.selectionStart,target.selectionEnd,row.component);
          patch(row.key,value=>({...value,anchor,anchorCaption:row.before,epoch:value.epoch+1}));
        }}/></label>
        {stale&&<div className="caption-source-conflict"><p role="alert">保存版图注或所在位置已变化；本地草稿和原选区保留。</p>
          {ref&&<><small>当前位置组件 {componentId(ref)} · 图版本 r{ref.revision??'未声明'} · 稿件 r{s.paper.revision}</small><textarea readOnly aria-label={'当前保存版图注 '+number} value={typeof ref.caption==='string'?ref.caption:'当前位置没有明确图注'}/></>}
          <button disabled={busy||!ref||identity(ref)!==row.identity||typeof ref.caption!=='string'} onClick={()=>rebase(row)}>比较后继续编辑当前图注 {number}</button>
          <button disabled={busy} onClick={()=>discard(row)}>放弃此位置草稿并读取保存版 {number}</button></div>}
        <label>图注草稿<textarea disabled={!!s.paperDraft?.captions?.length} aria-label={'图注草稿 '+number} value={row.text} onChange={event=>patch(row.key,value=>({...value,text:event.target.value,epoch:value.epoch+1,notice:''}))}/></label>
        <button disabled={busy||bodyDirty||stale||!dirty} onClick={()=>void save(row.key)}>保存图注 {number}</button>
        {dirty&&<p role="status">此位置图注尚未保存；意见选区使用保存版原文。</p>}
        {duplicate&&<p role="status">同一组件出现多次，当前图注意见目标不唯一；仍可逐位置手改和保存图注。</p>}
        {row.anchor&&<blockquote aria-label={'图注意见选区 '+number}>{row.anchor.quote}</blockquote>}
        {row.anchor&&!selectionValid(row)&&<p role="status">原选区来自旧图注；请在保存版重新选择，意见草稿保留。</p>}
        <label>图注修改意见<textarea aria-label={'图注修改意见 '+number} value={row.opinion} onChange={event=>patch(row.key,value=>({...value,opinion:event.target.value,epoch:value.epoch+1,notice:''}))}/></label>
        <button disabled={!canOpinion||!row.opinion.trim()} onClick={()=>void opinion(row.key,'create')}>添加图注意见 {number}</button>
        <label>既有图注意见<select aria-label={'既有图注意见 '+number} value={row.selectedOpinion} onChange={event=>patch(row.key,value=>({...value,selectedOpinion:event.target.value}))}>
          <option value="">选择既有意见</option>{existing.map((item:any)=><option key={item.id} value={item.id}>{item.text.slice(0,60)} · {item.deleted?'已删除':'保留'} · {item.id}</option>)}</select></label>
        {selected&&<p role="status">意见 r{selected.revision} · {selected.deleted?'已删除，可在整轮意见中恢复':annotation?.status==='anchored'?'当前选区有效':'原选区已变化；需要明确重新定位'}</p>}
        <button disabled={!canOpinion||!selected||selected.deleted} onClick={()=>void opinion(row.key,'reanchor')}>重新定位图注意见 {number}</button>
        {row.notice&&<p role="status">{row.notice}</p>}{row.error&&<p role="alert">{row.error}</p>}
      </article>;
    })}
  </section>;
}
