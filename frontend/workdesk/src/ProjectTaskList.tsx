import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {CommandError} from './api';
import type {Session} from './session';

type TaskRef={id:string,project_id:string};
type Row=TaskRef&{status:string,attempts:number,priority:number|undefined,request:string,kind:string};
type Scope={session:Session,project:string};
type Reading={scope:Scope,state:'loading'|'ready'|'failed',rows:Row[],error?:string};
type Props={session:Session,onOpenTask:(task:TaskRef)=>Promise<void>|void,report:(error:unknown)=>void};
const record=(x:any)=>x!==null&&typeof x==='object'&&!Array.isArray(x);

function projectRows(value:any,project:string):Row[]{
  if(!record(value)||!Array.isArray(value.tasks)||!Array.isArray(value.projects))throw new Error('任务列表返回结构无效；未显示旧列表或把错误当作空列表。');
  if(!value.projects.some((x:any)=>record(x)&&x.id===project))
    throw new CommandError('forbidden','当前项目不在本次身份可见范围；旧任务列表已清除。',null);
  const seen=new Set<string>(),rows:Row[]=[];
  for(const task of value.tasks){
    if(!record(task)||task.project_id!==project)continue;
    if(typeof task.id!=='string'||!task.id||seen.has(task.id)||typeof task.status!=='string'||!task.status||
      !Number.isSafeInteger(task.attempts)||task.attempts<0||!record(task.payload))
      throw new Error('本项目任务身份或状态字段无效；未省略坏记录后宣称列表完整。');
    const priority=task.payload.priority;
    if(priority!==undefined&&(!Number.isSafeInteger(priority)))
      throw new Error('任务优先级超出本界面可准确表示的整数范围；未显示舍入值。');
    seen.add(task.id);
    rows.push({id:task.id,project_id:project,status:task.status,attempts:task.attempts,priority,
      request:typeof task.payload.request==='string'?task.payload.request:'',
      kind:typeof task.payload.kind==='string'?task.payload.kind:''});
  }
  return rows;
}

/** Current scoped task summaries only. Opening a task never controls its execution. */
export function ProjectTaskList({session:s,onOpenTask,report}:Props){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const scope=useRef<Scope>({session:s,project:s.project.id});
  if(scope.current.session!==s||scope.current.project!==s.project.id)scope.current={session:s,project:s.project.id};
  const active=scope.current,live=useRef(false),serial=useRef(0),request=useRef<AbortController|null>(null);
  const [reload,setReload]=useState(0),[reading,setReading]=useState<Reading|null>(null);
  const [opening,setOpening]=useState<{scope:Scope,id:string}|null>(null),openPending=useRef(false);
  const [openError,setOpenError]=useState<{scope:Scope,text:string}|null>(null);
  useEffect(()=>{
    live.current=true;openPending.current=false;setOpening(null);setOpenError(null);
    const origin=active,ticket=++serial.current,controller=new AbortController();request.current=controller;
    const current=()=>live.current&&scope.current===origin&&serial.current===ticket;
    setReading({scope:origin,state:'loading',rows:[]});
    (async()=>{
      try{
        const response=await fetch('/api/state',{method:'GET',credentials:'same-origin',signal:controller.signal});
        const value=await response.json();
        if(!current())return;
        if(!response.ok)throw new CommandError(value?.code,typeof value?.error==='string'?value.error:'当前项目任务不可读取',value?.details);
        const rows=projectRows(value,origin.project);
        if(current())setReading({scope:origin,state:'ready',rows});
      }catch(error){
        if(current()){setReading({scope:origin,state:'failed',rows:[],error:String(error instanceof Error?error.message:error)});report(error);}
      }
    })();
    return()=>{live.current=false;++serial.current;controller.abort();};
  },[s,s.project.id,reload]);
  const current=reading?.scope===active?reading:null;
  const refresh=()=>{
    request.current?.abort();++serial.current;
    setReading({scope:active,state:'loading',rows:[]});setOpenError(null);setReload(value=>value+1);
  };
  const open=async(row:Row)=>{
    if(openPending.current||current?.state!=='ready'||!current.rows.some(x=>x.id===row.id&&x.project_id===active.project))return;
    const origin=active;openPending.current=true;setOpening({scope:origin,id:row.id});setOpenError(null);
    try{await onOpenTask({id:row.id,project_id:origin.project});}
    catch(error){if(live.current&&scope.current===origin){
      const text=String(error instanceof Error?error.message:error);setOpenError({scope:origin,text});report(error);
      if(error instanceof CommandError&&['forbidden','unauthorized'].includes(error.code))
        setReading({scope:origin,state:'failed',rows:[],error:text});
    }}finally{if(live.current&&scope.current===origin){openPending.current=false;setOpening(null);}}
  };
  const busy=opening?.scope===active;
  return <section className="review-panel" aria-label="项目任务">
    <h2>项目任务</h2><p>{s.project.title} · {active.project}</p>
    <p>仅列出本次读取中当前身份可见的本项目任务。任务状态不代表候选已采用或科学审查通过。</p>
    <button disabled={!!busy} onClick={refresh}>刷新项目任务</button>
    {!current||current.state==='loading'?<p role="status">正在读取项目任务…</p>:null}
    {current?.state==='failed'&&<p role="alert">{current.error}</p>}
    {current?.state==='ready'&&<>
      <p role="status">本次可见任务：{current.rows.length} 项。</p>
      {current.rows.length===0&&<p>本次读取未返回本项目任务。</p>}
      <ul aria-label="本项目可见任务">{current.rows.map(row=>{
        const points=Array.from(row.request),excerpt=points.slice(0,160).join('');
        return <li key={row.id}>
          <h3>{row.id}</h3>
          <p style={{overflowWrap:'anywhere'}}>实际状态：{row.status} · 尝试次数：{row.attempts} · 优先级：{row.priority===undefined?'未登记（按 0 排序）':row.priority}</p>
          {row.kind&&<p>任务类型：{row.kind}</p>}
          {excerpt&&<p style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>委托摘录：{excerpt}{points.length>160?'…':''}</p>}
          <button disabled={!!busy} onClick={()=>void open(row)}>打开任务 {row.id}</button>
        </li>;
      })}</ul>
    </>}
    {openError?.scope===active&&current?.state!=='failed'&&<p role="alert">{openError.text}</p>}
  </section>;
}
