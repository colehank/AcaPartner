import {useContext,useRef,useState} from 'react';
import {ArrowRight,Undo2} from 'lucide-react';
import {command,requestId} from '../api';
import {WorkbenchContext} from './context';
import {errorText} from './useManuscript';

export function PartnerGraphChange({item,onChanged,continueWith}:{item:any;onChanged?:()=>Promise<unknown>;continueWith:(text:string)=>void}){
 const c=useContext(WorkbenchContext)!,change=item.task.result?.graph_change,key=useRef(requestId()),[busy,setBusy]=useState(false),[error,setError]=useState('');
 if(!change)return null;
 async function undo(){if(busy)return;setBusy(true);setError('');try{await command('research.partner.graph.undo',{project_id:item.task.project_id,task_id:item.task.id,request_key:key.current});await Promise.all([c.refreshResearch(),c.refresh(),onChanged?.()]);}catch(e){setError(errorText(e));}finally{setBusy(false);}}
 const applied=change.status==='applied',undone=change.status==='undone',writable=c.catalog.project_management.writable_project_ids.includes(item.task.project_id);
 return <section className="partner-graph-change" aria-label="本轮研究图变更"><p role="status"><strong>{applied?'研究图已更新':undone?'本轮图变更已撤销':'本轮未修改研究图'}</strong>{applied&&<span>新增 {change.created_ids.length} 个节点{change.updated_ids.length?' · 更新 '+change.updated_ids.length+' 个节点':''}</span>}</p>
 {!applied&&!undone&&<p>{change.summary}</p>}<div><button className="inline-ref" onClick={()=>c.setGlobal('project')}>查看画布<ArrowRight/></button>{applied&&writable&&<button className="inline-ref" disabled={busy} onClick={()=>void undo()}><Undo2/>{busy?'正在撤销…':'撤销本轮'}</button>}{!applied&&!undone&&writable&&<button className="inline-ref" onClick={()=>continueWith(item.task.payload.request)}>按当前图重新整理</button>}</div>{error&&<p role="alert">{error}</p>}</section>;
}
