import {useEffect,useRef,useState} from 'react';
import {requestId} from './api';

type Subject={origin_run_id:string,plan_hash:string,node_id:string,node_key:string,output_name:string,asset_sha256:string};
type Observation={subject:Subject,revision:number,status:'unmarked'|'confirmed_error'|'retracted',history:any[],scientific_approval:false,reason?:string,actor?:string|Record<string,unknown>,recorded_at?:string};
type Row={node_id:string,output_name:string,subject:Subject,observation:Observation};
type Read={run_id:string,plan_hash:string,rows:Row[],executed:false};
export type GenerationResultErrorsProps={projectId:string,runId:string,command:(action:string,fields:any)=>Promise<any>,onChanged?:()=>void};
const statuses={unmarked:'未登记',confirmed_error:'已确认有误',retracted:'已撤销错误登记'};
const text=(value:unknown):value is string=>typeof value==='string'&&value.length>0;
const sha=(value:unknown)=>typeof value==='string'&&/^[0-9a-f]{64}$/.test(value);
function subjectKey(value:Subject){return JSON.stringify([value.origin_run_id,value.plan_hash,value.node_id,value.node_key,value.output_name,value.asset_sha256]);}
function validSubject(value:any):value is Subject{
  return value&&['origin_run_id','node_id','node_key','output_name'].every(key=>text(value[key]))&&sha(value.plan_hash)&&sha(value.asset_sha256);
}
function observation(value:any,subject:Subject):Observation{
  if(!value||!validSubject(value.subject)||subjectKey(value.subject)!==subjectKey(subject)||!Number.isInteger(value.revision)||value.revision<0
    ||!Object.hasOwn(statuses,value.status)||!Array.isArray(value.history)||value.scientific_approval!==false)
    throw Error('错误登记回执与本次固定输出身份或登记版本不符。');
  return value;
}
function readResult(value:any,runId:string):Read{
  if(!value||value.run_id!==runId||!sha(value.plan_hash)||value.executed!==false||!Array.isArray(value.rows))
    throw Error('结果错误读取回执与当前运行不符，或缺少未执行声明。');
  const seen=new Set<string>();
  for(const row of value.rows){
    if(!row||!text(row.node_id)||!text(row.output_name)||!validSubject(row.subject)||seen.has(subjectKey(row.subject)))
      throw Error('结果错误列表缺少唯一、完整的固定输出身份。');
    seen.add(subjectKey(row.subject));observation(row.observation,row.subject);
  }
  return value;
}
function failure(error:unknown){
  const e=error as {code?:string,status?:number,message?:string};
  const message=error instanceof Error?error.message:String(error);
  return e?.status===409||['conflict','revision_conflict'].includes(e?.code||'')
    ?'登记版本冲突（409）。理由已保留；请刷新实际登记后再决定。'+message
    :'读取或保存失败：'+message;
}

/** Explicit owner observations on fixed outputs; no execution or automatic undo. */
export function GenerationResultErrors(props:GenerationResultErrorsProps){
  const scope=JSON.stringify([props.projectId,props.runId]);
  const context=useRef({scope,sequence:0,mounted:false});
  // Fence the render before the old scope's effect cleanup runs.
  if(context.current.scope!==scope){context.current.scope=scope;++context.current.sequence;}
  const latest=useRef(props);latest.current=props;
  const operation=useRef<{scope:string,sequence:number}|null>(null);
  const [receipt,setReceipt]=useState<{scope:string,value:Read}|null>(null);
  const [form,setForm]=useState({scope,selected:'',reason:''});
  const [pending,setPending]=useState<{scope:string,sequence:number,kind:'read'|'record'}|null>(null);
  const [error,setError]=useState<{scope:string,message:string}|null>(null);
  const [notice,setNotice]=useState<{scope:string,message:string}|null>(null);
  const value=receipt?.scope===scope?receipt.value:null;
  const currentForm=form.scope===scope?form:{scope,selected:'',reason:''};
  const busy=pending?.scope===scope&&pending.sequence===context.current.sequence;
  const row=value?.rows.find(entry=>subjectKey(entry.subject)===currentForm.selected);
  const change=(fields:Partial<typeof form>)=>setForm({...currentForm,...fields,scope});
  const load=async()=>{
    if(!context.current.mounted||context.current.scope!==scope||operation.current?.scope===scope||!props.projectId||!props.runId)return;
    const sequence=++context.current.sequence,projectId=props.projectId,runId=props.runId;
    const current=()=>context.current.mounted&&context.current.scope===scope&&context.current.sequence===sequence;
    operation.current={scope,sequence};setPending({scope,sequence,kind:'read'});setError(null);setNotice(null);
    try{
      const result=await latest.current.command('build.result_errors.read',{project_id:projectId,payload:{run_id:runId}});
      if(!current())return;
      setReceipt({scope,value:readResult(result,runId)});
    }catch(error){if(current()){setReceipt(null);setError({scope,message:failure(error)});}}
    finally{if(current()){operation.current=null;setPending(null);}}
  };
  useEffect(()=>{
    context.current.mounted=true;setReceipt(null);setForm({scope,selected:'',reason:''});setError(null);setNotice(null);
    void load();
    return()=>{context.current.mounted=false;++context.current.sequence;if(operation.current?.scope===scope)operation.current=null;};
  },[props.projectId,props.runId]);
  const record=async(status:'confirmed_error'|'retracted')=>{
    if(!context.current.mounted||context.current.scope!==scope||operation.current?.scope===scope||busy||!row||!currentForm.reason.trim()
      ||status==='confirmed_error'&&row.observation.status==='confirmed_error'
      ||status==='retracted'&&row.observation.status!=='confirmed_error')return;
    const sequence=++context.current.sequence,projectId=props.projectId;
    const target=structuredClone(row.subject),expected=row.observation.revision,reason=currentForm.reason;
    const current=()=>context.current.mounted&&context.current.scope===scope&&context.current.sequence===sequence;
    operation.current={scope,sequence};setPending({scope,sequence,kind:'record'});setError(null);setNotice(null);
    try{
      // No retry and no control/start/undo command. The server owns permission,
      // current revision and formal-delivery blocking for this exact subject.
      if(!current())return;
      const result=await latest.current.command('build.result_errors.record',{project_id:projectId,request_id:requestId(),
        payload:{subject:target,expected_revision:expected,status,reason}});
      if(!current())return;
      const saved=observation(result,target);
      if(saved.revision<=expected||saved.status!==status)throw Error('错误登记回执没有保存本次状态和新的登记版本。');
      setReceipt(old=>old?.scope===scope?{scope,value:{...old.value,rows:old.value.rows.map(entry=>subjectKey(entry.subject)===subjectKey(target)?{...entry,observation:saved}:entry)}}:old);
      setForm(old=>old.scope===scope?{...old,reason:''}:old);
      setNotice({scope,message:status==='confirmed_error'?'已保存此固定输出的错误登记。':'已保存撤销记录，原错误登记历史保留。'});
      try{latest.current.onChanged?.();}catch(error){if(current())setError({scope,message:'登记已保存，但界面通知失败：'+String(error)});}
    }catch(error){if(current())setError({scope,message:failure(error)});}
    finally{if(current()){operation.current=null;setPending(null);}}
  };
  return <section className="generation-result-errors" aria-label="计算结果错误登记" style={{minWidth:0,maxWidth:'100%',overflowWrap:'anywhere'}}>
    <h3>固定输出的错误登记</h3>
    <p>请选择具体输出并说明理由。登记或撤销保留历史，不自动重做计算、撤回采用或授予科学批准。</p>
    <p>当前运行：{props.runId||'未选择运行'}</p>
    <button type="button" disabled={!!busy||!props.projectId||!props.runId} onClick={()=>void load()}>刷新错误登记</button>
    {busy&&<p role="status">{pending?.kind==='record'?'正在保存错误登记…':'正在读取输出错误登记…'}</p>}
    {error?.scope===scope&&<p role="alert">{error.message}</p>}
    {notice?.scope===scope&&<p role="status">{notice.message}</p>}
    {value&&<>
      {!value.rows.length?<p>此运行没有已登记的实际输出。</p>:<>
        <label>实际输出<select aria-label="错误登记实际输出" style={{minWidth:0,width:'100%',maxWidth:'100%',boxSizing:'border-box'}} disabled={!!busy} value={currentForm.selected} onChange={event=>{change({selected:event.target.value});setError(null);setNotice(null);}}>
          <option value="">明确选择固定输出</option>{value.rows.map(entry=><option key={subjectKey(entry.subject)} value={subjectKey(entry.subject)}>{entry.node_id} / {entry.output_name}</option>)}
        </select></label>
        {row&&<article aria-label="所选输出错误记录">
          <p>当前登记：{statuses[row.observation.status]} · 登记版本 {row.observation.revision}</p>
          <dl><dt>原运行</dt><dd>{row.subject.origin_run_id}</dd><dt>计划</dt><dd>{row.subject.plan_hash}</dd><dt>节点 / 固定节点键</dt><dd>{row.subject.node_id} / {row.subject.node_key}</dd><dt>输出 / 资产 SHA</dt><dd>{row.subject.output_name} / {row.subject.asset_sha256}</dd></dl>
          {row.observation.reason&&<p>登记理由：{row.observation.reason}</p>}
          {row.observation.actor&&<p>记录者：{typeof row.observation.actor==='string'?row.observation.actor:JSON.stringify(row.observation.actor)}</p>}
          {row.observation.recorded_at&&<p>记录时间：{row.observation.recorded_at}</p>}
          <details><summary>错误登记历史（{row.observation.history.length}）</summary><pre style={{maxWidth:'100%',whiteSpace:'pre-wrap',overflowWrap:'anywhere',overflow:'auto'}}>{JSON.stringify(row.observation.history,null,2)}</pre></details>
        </article>}
        <label>登记或撤销理由<textarea aria-label="结果错误登记理由" style={{minWidth:0,width:'100%',maxWidth:'100%',boxSizing:'border-box'}} disabled={!!busy} value={currentForm.reason} onChange={event=>change({reason:event.target.value})}/></label>
        <button type="button" disabled={!!busy||!row||!currentForm.reason.trim()||row.observation.status==='confirmed_error'} onClick={()=>void record('confirmed_error')}>确认此结果有误</button>
        <button type="button" disabled={!!busy||!row||!currentForm.reason.trim()||row.observation.status!=='confirmed_error'} onClick={()=>void record('retracted')}>撤销此错误登记</button>
      </>}
    </>}
  </section>;
}
