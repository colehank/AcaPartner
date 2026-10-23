import {useEffect,useRef,useState,type ReactNode} from 'react';
import {CommandError} from './api';

export type TaskExecutionAuthority={workspaceOwner:boolean,writableProjectIds:string[],runtimeRunning:boolean,
  providers:{id:string,route:string,authorized:boolean}[]};
const record=(value:any)=>value!==null&&typeof value==='object'&&!Array.isArray(value);

/** Configuration and current scope only; never a connectivity or fee grant. */
export function projectTaskAuthority(value:any,projectId:string):TaskExecutionAuthority {
  if(!record(value)||!Array.isArray(value.projects)||!value.projects.some((p:any)=>p?.id===projectId))
    throw new Error('当前身份未返回此项目；任务执行权限不可用。');
  const scope=value.project_management;
  if(!record(scope)||typeof scope.can_create!=='boolean'||!Array.isArray(scope.writable_project_ids)||
    scope.writable_project_ids.some((id:any)=>typeof id!=='string'||!id)||
    !record(value.runtime)||typeof value.runtime.running!=='boolean'||!Array.isArray(value.providers))
    throw new Error('任务执行权限返回不完整；未推定所有者或运行状态。');
  const seen=new Set<string>();
  const providers=value.providers.map((p:any)=>{
    if(!record(p)||typeof p.id!=='string'||!p.id||seen.has(p.id)||typeof p.route!=='string'||!p.route||typeof p.authorized!=='boolean')
      throw new Error('任务执行路线身份或授权状态无效。');
    seen.add(p.id);return {id:p.id,route:p.route,authorized:p.authorized};
  });
  return {workspaceOwner:scope.can_create,writableProjectIds:[...scope.writable_project_ids],
    runtimeRunning:value.runtime.running,providers};
}

/** Read once per mounted context, and only again on an explicit refresh. */
export function TaskAuthority({session,projectId,report,children}:{session:object,projectId:string,
  report:(error:unknown)=>void,children:(authority:TaskExecutionAuthority|undefined)=>ReactNode}){
  const scope=useRef({session,projectId});
  if(scope.current.session!==session||scope.current.projectId!==projectId)scope.current={session,projectId};
  const active=scope.current,sequence=useRef(0),abort=useRef<AbortController|null>(null);
  const [refresh,setRefresh]=useState(0),[state,setState]=useState<{scope:typeof active,authority?:TaskExecutionAuthority,error?:string}|null>(null);
  useEffect(()=>{
    const origin=active,ticket=++sequence.current,controller=new AbortController();abort.current=controller;
    const current=()=>scope.current===origin&&sequence.current===ticket;
    setState(null);
    void (async()=>{
      try{
        const response=await fetch('/api/state',{method:'GET',credentials:'same-origin',signal:controller.signal});
        const value=await response.json();
        if(!current())return;
        if(!response.ok)throw new CommandError(value?.code,typeof value?.error==='string'?value.error:'无法读取任务执行权限',value?.details);
        const authority=projectTaskAuthority(value,origin.projectId);
        if(current())setState({scope:origin,authority});
      }catch(error){
        if(current()){setState({scope:origin,error:error instanceof Error?error.message:String(error)});report(error);}
      }
    })();
    return()=>{++sequence.current;controller.abort();};
  },[session,projectId,refresh]);
  const latest=state?.scope===active?state:null;
  return <>
    <div className="panel-tools">
      <button onClick={()=>{++sequence.current;abort.current?.abort();setState(null);setRefresh(n=>n+1);}}>刷新执行权限</button>
      {!latest&&<span role="status">读取当前身份与执行状态…</span>}
      {latest?.error&&<span role="alert">{latest.error}</span>}
    </div>
    {children(latest?.authority)}
  </>;
}
