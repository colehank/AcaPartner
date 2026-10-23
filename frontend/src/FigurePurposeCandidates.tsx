import {useEffect,useRef,useState} from 'react';

type FigureChoice={id:string,title:string,revision:number,composition?:boolean};
type SourceRef={id:string,revision:number,sha256:string};
type PinnedSource={ref:SourceRef,title:string};
type Row={id:string,revision:number|null,pin:PinnedSource|null,purpose:string,title:string,reading:boolean,error:string};
type Candidate={figure:{id:string,title:string,revision:number,project_id:string},source_ref:SourceRef,purpose:string};
export type FigurePurposeCandidatesProps={
  projectId:string,figures:FigureChoice[],runs:any[],
  command:(action:string,data:any)=>Promise<any>,
  onCreated:(id:string)=>Promise<void>|void,busy?:boolean,
};

const blankRow=():Row=>({id:'',revision:null,pin:null,purpose:'',title:'',reading:false,error:''});
const message=(error:unknown)=>error instanceof Error?error.message:String(error);
const sha256=(value:unknown):value is string=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const sameRef=(left:any,right:SourceRef)=>left?.id===right.id&&left?.revision===right.revision&&left?.sha256===right.sha256;

function inputMapping(raw:string):{value:Record<string,string>|null,error:string}{
  try{
    const value=JSON.parse(raw);
    if(!value||typeof value!=='object'||Array.isArray(value)||!Object.keys(value).length)throw Error('请明确填写至少一个输入别名及实际输出 SHA。');
    for(const [alias,sha] of Object.entries(value))if(!alias.trim()||!sha256(sha))throw Error('每个输入别名必须非空，输出 SHA 必须是完整的 64 位小写十六进制。');
    return {value,error:''};
  }catch(error){return {value:null,error:error instanceof SyntaxError?'输入映射必须是有效的 JSON 对象。':message(error)};}
}

/** Saved source pins only. This component never authorizes, renders or adopts. */
export function FigurePurposeCandidates(props:FigurePurposeCandidatesProps){
  const project=useRef(props.projectId);project.current=props.projectId;
  return <CandidatesForm key={props.projectId} {...props} isCurrent={()=>project.current===props.projectId}/>;
}

function CandidatesForm({isCurrent,...props}:FigurePurposeCandidatesProps&{isCurrent:()=>boolean}){
  const [rows,setRows]=useState<Row[]>(()=>[blankRow(),blankRow()]);
  const [runId,setRunId]=useState(''),[inputs,setInputs]=useState('{}');
  const [candidates,setCandidates]=useState<Candidate[]>([]),[error,setError]=useState('');
  const [creating,setCreating]=useState(false),[opening,setOpening]=useState(''),[requestKey,setRequestKey]=useState('');
  const mounted=useRef(true),latest=useRef(props),rowState=useRef(rows);
  const sequence=useRef([0,0]),locked=useRef(false),attempt=useRef<{signature:string,key:string,originalIds:string[]}|null>(null);
  latest.current=props;rowState.current=rows;
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;sequence.current=sequence.current.map(n=>n+1);};},[]);
  const current=()=>mounted.current&&isCurrent();
  const updateRow=(index:number,change:Partial<Row>)=>{
    const next=rowState.current.map((row,i)=>i===index?{...row,...change}:row);
    rowState.current=next;setRows(next);
  };
  const select=(index:number,id:string)=>{
    if(!current()||locked.current||latest.current.busy)return;
    const source=latest.current.figures.find(figure=>figure.id===id&&!figure.composition);
    ++sequence.current[index];updateRow(index,{id:source?.id||'',revision:source?.revision??null,pin:null,reading:false,error:''});setError('');
  };
  const read=async(index:number)=>{
    if(!current()||locked.current||latest.current.busy||rowState.current[index].reading)return;
    const origin=rowState.current[index];if(!origin.id||origin.revision===null)return;
    const serial=++sequence.current[index],projectId=props.projectId;
    const active=()=>current()&&sequence.current[index]===serial&&rowState.current[index].id===origin.id&&rowState.current[index].revision===origin.revision;
    updateRow(index,{reading:true,error:'',pin:null});
    try{
      const view=await latest.current.command('desk.figure.read',{project_id:projectId,id:origin.id,revision:origin.revision});
      if(!active())return;
      const figure=view?.figure,ref=view?.source_ref;
      if(figure?.id!==origin.id||figure?.revision!==origin.revision||figure?.project_id!==projectId||figure?.kind!=='figure'||typeof figure.title!=='string'||view.definition||figure.content?.composition)
        throw Error('读取回执不是本项目所选修订的独立源图。');
      if(!ref||ref.id!==origin.id||ref.revision!==origin.revision||!sha256(ref.sha256))throw Error('读取回执缺少准确的固定来源 id / revision / SHA，不能创建候选。');
      updateRow(index,{pin:{ref:{id:ref.id,revision:ref.revision,sha256:ref.sha256},title:figure.title},error:''});
    }catch(error){if(active())updateRow(index,{pin:null,error:message(error)});}
    finally{if(active())updateRow(index,{reading:false});}
  };
  const mapping=inputMapping(inputs),run=props.runs.find(value=>value.id===runId&&value.status==='generated');
  const purposes=rows.map(row=>row.purpose.trim()),titles=rows.map(row=>row.title.trim());
  const distinct=purposes[0]!==purposes[1];
  const ready=!!run&&!!mapping.value&&rows.every(row=>row.pin&&!row.reading)&&purposes.every(Boolean)&&titles.every(Boolean)&&distinct;
  const blocked=!!props.busy||creating||!!opening;
  const create=async()=>{
    if(!current()||locked.current||latest.current.busy||!ready)return;
    const payload={project_id:props.projectId,run_id:runId,inputs:mapping.value!,variants:rows.map((row,index)=>({...row.pin!.ref,purpose:purposes[index],title:titles[index]}))};
    const signature=JSON.stringify(payload);
    if(attempt.current?.signature!==signature)attempt.current={signature,key:'figure-purposes:'+crypto.randomUUID(),originalIds:latest.current.figures.map(figure=>figure.id)};
    const {key:request_key,originalIds}=attempt.current!;
    locked.current=true;setCreating(true);setError('');setRequestKey(request_key);
    try{
      const result=await latest.current.command('desk.figure.variants.create',{...payload,request_key});
      if(!current())return;
      if(result?.executed!==false||result?.originals_unchanged!==true||result?.script_authorization_required!==true||typeof result?.created!=='boolean'||!Array.isArray(result.candidates)||result.candidates.length!==2)
        throw Error('候选回执缺少未执行、原图保持或授权边界证据，请核对该请求标识；不会自动重试。');
      const ids=new Set<string>();
      for(const [index,candidate] of result.candidates.entries()){
        const figure=candidate?.figure;
        if(!figure||typeof figure.id!=='string'||!figure.id||ids.has(figure.id)||originalIds.includes(figure.id)||figure.project_id!==payload.project_id||figure.kind!=='figure'||!Number.isInteger(figure.revision)||figure.revision<1||figure.content?.composition||!sameRef(candidate.source_ref,payload.variants[index])||candidate.purpose!==payload.variants[index].purpose||figure.title!==payload.variants[index].title)
          throw Error('候选身份、固定来源、用途或标题与本次请求不符，请核对该请求标识；不会自动重试。');
        ids.add(figure.id);
      }
      setCandidates(result.candidates);
    }catch(error){if(current())setError(message(error));}
    finally{if(current()){locked.current=false;setCreating(false);}}
  };
  const open=async(id:string)=>{
    if(!current()||locked.current||latest.current.busy||!candidates.some(candidate=>candidate.figure.id===id))return;
    locked.current=true;setOpening(id);setError('');
    try{await latest.current.onCreated(id);}catch(error){if(current())setError(message(error));}
    finally{if(current()){locked.current=false;setOpening('');}}
  };
  const sources=props.figures.filter(figure=>!figure.composition);
  return <section className="figure-register" aria-label="多用途图候选">
    <h3>从保存版源图建立两个用途候选</h3>
    <p>只创建候选，不改原图、主图图位或稿件采用位置。未保存的源图调整不会复制。</p>
    <form onSubmit={event=>{event.preventDefault();void create();}}>
      {rows.map((row,index)=>{const number=index+1,head=sources.find(figure=>figure.id===row.id);return <fieldset key={index} disabled={blocked}>
        <legend>用途 {number}</legend>
        <label>保存版源图<select aria-label={'用途'+number+'保存版源图'} value={row.id} disabled={row.reading} onChange={event=>select(index,event.target.value)}>
          <option value="">明确选择独立源图</option>{sources.map(source=><option key={source.id} value={source.id}>{source.title} · {source.id} · r{source.revision}</option>)}
        </select></label>
        <button type="button" disabled={!row.id||row.reading} onClick={()=>void read(index)}>读取用途{number}固定源图</button>
        {row.reading&&<p role="status">正在读取用途{number}保存版 r{row.revision}…</p>}
        {row.pin&&<p aria-label={'用途'+number+'固定来源'}>{row.pin.title} · {row.pin.ref.id} · r{row.pin.ref.revision}<br/>SHA：<code>{row.pin.ref.sha256}</code></p>}
        {head&&row.revision!==head.revision&&<p>当前列表是 r{head.revision}，本行仍固定 r{row.revision}。<button type="button" onClick={()=>select(index,row.id)}>明确改选当前列表修订</button></p>}
        {row.error&&<p role="alert">{row.error}</p>}
        <label>用途说明<input aria-label={'用途'+number+'说明'} value={row.purpose} onChange={event=>updateRow(index,{purpose:event.target.value})}/></label>
        <label>候选标题<input aria-label={'用途'+number+'候选标题'} value={row.title} onChange={event=>updateRow(index,{title:event.target.value})}/></label>
      </fieldset>;})}
      {!distinct&&purposes.every(Boolean)&&<p role="alert">两个候选的用途说明必须不同。</p>}
      <label>实际计算运行<select aria-label="候选实际计算运行" disabled={blocked} value={runId} onChange={event=>{setRunId(event.target.value);setError('');}}>
        <option value="">明确选择已完成运行</option>{props.runs.filter(value=>value.status==='generated').map(value=><option key={value.id} value={value.id}>{value.id}</option>)}
      </select></label>
      {run&&<details><summary>所选运行的已登记输出</summary><pre>{JSON.stringify(run.result?.nodes??{},null,2)}</pre></details>}
      <label>输入别名到实际输出 SHA<textarea aria-label="候选输出输入映射" disabled={blocked} value={inputs} onChange={event=>{setInputs(event.target.value);setError('');}}/></label>
      {inputs.trim()!=='{}'&&mapping.error&&<p role="alert">{mapping.error}</p>}
      <p>新输入必须来自所选真实运行，两个保存版来源须满足服务核验的同源条件。读取或创建不执行脚本。</p>
      <button type="submit" disabled={blocked||!ready}>创建两个用途候选</button>
      {creating&&<p role="status">正在创建本次固定来源候选…</p>}
    </form>
    {requestKey&&<p>本次请求标识：<code>{requestKey}</code>。相同输入再次提交沿用该标识，不自动重试。</p>}
    {error&&<p role="alert">{error}</p>}
    {candidates.length>0&&<div aria-label="已创建用途候选"><p>候选脚本尚未授权。请逐个明确授权并重绘，再在主图或稿件位置显式采用。</p>{candidates.map(candidate=><article key={candidate.figure.id} aria-label={'用途候选 '+candidate.figure.id}>
      <strong>{candidate.figure.title}</strong><p>{candidate.purpose} · {candidate.figure.id} · r{candidate.figure.revision}</p>
      <p>固定原来源：{candidate.source_ref.id} · r{candidate.source_ref.revision} · SHA {candidate.source_ref.sha256}</p>
      <button disabled={blocked} onClick={()=>void open(candidate.figure.id)}>打开候选 {candidate.figure.id}</button>
    </article>)}</div>}
  </section>;
}
