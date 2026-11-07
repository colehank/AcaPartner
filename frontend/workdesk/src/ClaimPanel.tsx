import {useEffect,useRef,useState} from 'react';
import {command,requestId} from './api';

type Reference={id:string,revision:number,sha256?:string,consumer_id?:string,block_id?:string};
type SourceChoice={id:string,revision:number,head:string};
type Local={key:string,view:any|null,catalog:any[],ready:boolean,busy:string|null,error:string,notice:string,
  blockId:string,start:string,end:string,sources:SourceChoice[],relation:string,explanation:string,selected:string[]};
const RELATIONS=[['supports','支持'],['limits','限制'],['contradicts','反驳'],['motivates','启发下一问题']] as const;
const STATUSES:Record<string,string>={proposed:'候选关系',registered:'操作者已登记',needs_review:'需重新核对',rejected:'已拒绝'};
const stable=(value:any):string=>JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);
const dirty=(object:any)=>object?.dirty===true||object?.draft_dirty===true||object?.unsaved===true;
const identity=(object:any,project:string)=>stable([project,object?.id,object?.project_id,object?.kind,object?.revision,object?.content,dirty(object)]);
const head=(object:any)=>stable([object.id,object.project_id,object.kind,object.revision,object.archived,object.content,object.metadata]);
const initial=(key:string):Local=>({key,view:null,catalog:[],ready:false,busy:null,error:'',notice:'',blockId:'',start:'',end:'',sources:[],relation:'supports',explanation:'',selected:[]});
const integer=(value:string)=>/^\d+$/.test(value)&&Number.isSafeInteger(Number(value))?Number(value):null;

function manuscript(object:any,project:string){
  const blocks=object?.content?.blocks;
  return object?.project_id===project&&typeof object.id==='string'&&['paper','report'].includes(object.kind)&&Number.isSafeInteger(object.revision)&&object.revision>=1&&
    !object.archived&&Array.isArray(blocks)&&blocks.every((block:any)=>typeof block?.id==='string'&&block.id&&typeof block.text==='string')&&
    new Set(blocks.map((block:any)=>block.id)).size===blocks.length&&
    (object.kind!=='paper'||object.content.paper_source_mode==='structured'||
      (!object.content.paper_source_mode&&!String(object.content.latex||'').trim()));
}

// DOM textareas use UTF-16 offsets; the Claim service requires code points.
export function claimCodePointOffset(text:string,offset:number){
  if(!Number.isInteger(offset)||offset<0||offset>text.length)return null;
  if(offset>0&&offset<text.length&&/[\uD800-\uDBFF]/.test(text[offset-1])&&/[\uDC00-\uDFFF]/.test(text[offset]))return null;
  return Array.from(text.slice(0,offset)).length;
}

function validateView(view:any,object:any,project:string){
  if(!view||view.object_id!==object.id||view.project_id!==project||view.manuscript_revision!==object.revision||
      !Number.isSafeInteger(view.registry_revision)||view.registry_revision<0||!Array.isArray(view.claims)||!Array.isArray(view.observations)||
        !Array.isArray(view.history)||view.scientific_approval!==false)throw Error('Claim 读取的稿件、修订或合同不匹配；请重开当前保存版。');
  if(view.history.some((entry:any)=>!entry||!Number.isSafeInteger(entry.revision)||entry.revision<1||
      !['claim.propose','claim.accept'].includes(entry.action)||typeof entry.actor!=='string'||
      !Array.isArray(entry.claim_ids)||entry.claim_ids.some((id:any)=>typeof id!=='string')||entry.scientific_confirmation!==false))throw Error('Claim 原登记历史合同不完整；未启用登记。');
  const ids=new Set<string>();
  for(const claim of view.claims){
    const observations=view.observations.filter((row:any)=>row.claim_id===claim?.id),anchor=claim?.anchor;
    if(typeof claim?.id!=='string'||!claim.id||ids.has(claim.id)||claim.project_id!==project||!STATUSES[claim.status]||
        !RELATIONS.some(([value])=>value===claim.relation)||typeof claim.explanation!=='string'||!anchor||anchor.object_id!==object.id||
        !Number.isSafeInteger(anchor.revision)||anchor.revision<1||anchor.offset_unit!=='unicode_code_point'||typeof anchor.block_id!=='string'||
        !Number.isSafeInteger(anchor.start)||!Number.isSafeInteger(anchor.end)||anchor.start<0||anchor.end<=anchor.start||typeof anchor.quote!=='string'||
        !Array.isArray(claim.result_or_source_refs)||!claim.result_or_source_refs.length||observations.length!==1)throw Error('Claim 的固定锚点或来源身份不完整；未启用登记。');
    const observation=observations[0];
    if(!STATUSES[observation.stored_status]||observation.scientific_confirmation!==false||!Array.isArray(observation.gaps)||
        observation.gaps.some((gap:any)=>!gap||typeof gap.kind!=='string')||
        !Array.isArray(observation.source_pins)||observation.source_pins.length!==claim.result_or_source_refs.length||
        observation.source_pins.some((pin:any,index:number)=>typeof pin.id!=='string'||!Number.isSafeInteger(pin.revision)||pin.revision<0||
          typeof pin.sha256!=='string'||!/^[a-f0-9]{64}$/.test(pin.sha256)||pin.id!==claim.result_or_source_refs[index]?.id||pin.revision!==claim.result_or_source_refs[index]?.revision))throw Error('Claim 来源固定摘要或观察合同不完整；未启用登记。');
    ids.add(claim.id);
  }
  return view;
}

async function readContext(object:any,project:string){
  // The canonical Claim reader may observe and synchronize file-backed object
  // heads. Read the catalog after that observation, never before its updates.
  const view=await command('claim.read',{project_id:project,object_id:object.id});
  const response=await fetch('/api/state');
  const state=await response.json();
  if(!response.ok||!Array.isArray(state.objects))throw Error(state.error||'当前可读对象目录无法读取。');
  const saved=state.objects.find((item:any)=>item.id===object.id);
  if(!saved||saved.project_id!==project||saved.revision!==object.revision||stable(saved.content)!==stable(object.content)||saved.archived)throw Error('稿件含未保存内容、保存版已改变或权限已变化；请先保存或重开。');
  const catalog=state.objects.filter((item:any)=>item&&typeof item.id==='string'&&typeof item.project_id==='string'&&
    typeof item.kind==='string'&&!['project','task','asset','rawasset'].includes(item.kind)&&!item.archived&&
    Number.isSafeInteger(item.revision)&&item.revision>=1&&item.content&&typeof item.content==='object'&&
    (item.project_id===project||Array.isArray(item.metadata?.shared_with)&&item.metadata.shared_with.includes(project)));
  return {view:validateView(view,object,project),catalog};
}

export function ClaimPanel({object,projectId,report,onOpenReference}:{object:any,projectId:string,report:(message:string)=>void,onOpenReference?:(ref:Reference)=>void}){
  const key=identity(object,projectId),usable=manuscript(object,projectId)&&!dirty(object);
  const [stored,setStored]=useState<Local>(()=>initial(key));
  const local=stored.key===key?stored:initial(key);
  const live=useRef(true),sequence=useRef(0),latest=useRef({key,object,projectId,usable});
  latest.current={key,object,projectId,usable};
  useEffect(()=>{live.current=true;return()=>{live.current=false;sequence.current++;};},[]);
  const update=(change:(old:Local)=>Local)=>setStored(old=>old.key===key?change(old):old);
  const active=(ticket:number,expected:string)=>live.current&&sequence.current===ticket&&latest.current.key===expected&&latest.current.usable;
  const failure=(error:unknown,ticket:number,expected:string)=>{
    if(!active(ticket,expected))return;
    const message=String(error instanceof Error?error.message:error);
    update(old=>({...old,view:null,catalog:[],ready:false,busy:null,selected:[],sources:[],error:message,notice:''}));report(message);
  };
  const load=async()=>{
    const context=latest.current,ticket=++sequence.current;
    setStored(initial(context.key));
    if(!context.usable)return;
    setStored(old=>({...old,busy:'read'}));
    try{
      const value=await readContext(context.object,context.projectId);
      if(!active(ticket,context.key))return;
      setStored(old=>old.key===context.key?{...old,...value,ready:true,busy:null,notice:'已读取当前保存版和来源权限；尚无科学确认。'}:old);
    }catch(error){failure(error,ticket,context.key);}
  };
  useEffect(()=>{void load();return()=>{sequence.current++;};},[key]);

  const savedBlocks=Array.isArray(object?.content?.blocks)?object.content.blocks:[];
  const block=savedBlocks.find((item:any)=>item?.id===local.blockId),points=Array.from(String(block?.text||''));
  const start=integer(local.start),end=integer(local.end);
  const range=!!block&&start!==null&&end!==null&&start>=0&&start<end&&end<=points.length;
  const quote=range?points.slice(start!,end!).join(''):'';
  const observation=(claim:any,view=local.view)=>view?.observations.find((row:any)=>row.claim_id===claim.id);
  const eligible=(claim:any,view=local.view)=>claim.status==='proposed'&&observation(claim,view)?.stored_status==='proposed'&&observation(claim,view)?.gaps.length===0;
  const blocked=!usable||!local.ready||!!local.busy;
  const proposalReady=!blocked&&range&&local.sources.length>0&&local.sources.length<=32&&
    local.sources.every(ref=>Number.isSafeInteger(ref.revision)&&ref.revision>=0)&&local.explanation.trim().length>0&&local.explanation.length<=4000;
  const groupReady=!blocked&&local.selected.length>0&&local.selected.length<=32&&local.selected.every(id=>local.view?.claims.some((claim:any)=>claim.id===id&&eligible(claim)));

  const mutate=async(action:'claim.propose'|'claim.accept')=>{
    if(action==='claim.propose'?!proposalReady:!groupReady)return;
    const context=latest.current,ticket=++sequence.current;
    const sources=local.sources.map(ref=>({...ref})),selected=[...local.selected];
    const payload=action==='claim.propose'?{anchor:{block_id:local.blockId,start,end,quote,offset_unit:'unicode_code_point'},
      result_or_source_refs:sources.map(({id,revision})=>({id,revision})),relation:local.relation,explanation:local.explanation}:{claim_ids:selected};
    update(old=>({...old,busy:action,error:'',notice:''}));
    try{
      const fresh=await readContext(context.object,context.projectId);
      if(!active(ticket,context.key))return;
      const changed=action==='claim.propose'?sources.some(ref=>{
        const current=fresh.catalog.find((item:any)=>item.id===ref.id);return !current||head(current)!==ref.head;
      }):selected.some(id=>!fresh.view.claims.some((claim:any)=>claim.id===id&&eligible(claim,fresh.view)));
      if(changed){
        update(old=>({...old,...fresh,ready:false,busy:null,selected:[],sources:[],error:'来源、权限或候选状态已变化；未发送提议或登记。请重新读取并明确选择。'}));
        report('来源、权限或候选状态已变化；未发送提议或登记。');return;
      }
      const result=await command(action,{project_id:context.projectId,object_id:context.object.id,expected_revision:context.object.revision,request_id:requestId(),payload});
      if(!active(ticket,context.key))return;
      validateView(result,context.object,context.projectId);
      if(result.manuscript_changed!==false||!Array.isArray(result.changed_claim_ids)||
          (action==='claim.accept'&&stable(result.changed_claim_ids)!==stable(selected))||
          (action==='claim.propose'&&result.changed_claim_ids.length!==1))throw Error('Claim 操作回执与明确选择不同；请重新读取核对。');
      for(const id of result.changed_claim_ids){
        const claim=result.claims.find((item:any)=>item.id===id);
        if(!claim||observation(claim,result)?.stored_status!==(action==='claim.propose'?'proposed':'registered')||
            (action==='claim.propose'&&(claim.anchor.block_id!==local.blockId||claim.anchor.start!==start||claim.anchor.end!==end||claim.anchor.quote!==quote||
              claim.relation!==local.relation||claim.explanation!==local.explanation||stable(claim.result_or_source_refs)!==stable(sources.map(({id,revision})=>({id,revision}))))))throw Error('Claim 操作回执没有登记准确选区、来源或候选组；请重新读取核对。');
      }
      update(old=>({...old,view:result,catalog:fresh.catalog,ready:true,busy:null,selected:[],sources:[],start:'',end:'',explanation:'',error:'',
        notice:action==='claim.propose'?'已保存候选关系；仍需操作者明确登记。':'所选组已由服务登记；登记不代表科学确认。'}));
    }catch(error){failure(error,ticket,context.key);}
  };
  const chooseSource=(source:any,checked:boolean)=>update(old=>({...old,sources:checked&&old.sources.length<32?
    [...old.sources,{id:source.id,revision:source.revision,head:head(source)}]:old.sources.filter(ref=>ref.id!==source.id),error:'',notice:''}));
  const gapText=(gap:any)=>gap.kind==='source_head_changed'?`来源 ${gap.id} 已从固定 r${gap.fixed_revision} 变为 r${gap.current_revision}`:
    gap.kind==='source_unavailable'?`来源 ${gap.id} 当前不可读取（${gap.code}）`:
    gap.kind==='manuscript_anchor_changed'?`稿件段落 ${gap.block_id} 的原保存选区已变化`:stable(gap);

  return <section className="claim-panel" aria-label="稿件 Claim 关系">
    <h3>稿件 Claim 关系</h3>
    <p>固定保存稿件选区与来源修订，先提出关系，再由操作者明确登记。候选、登记和科学确认分别处理；此操作不会修改稿件或启动模型。</p>
    {!usable&&<p role="alert">{dirty(object)?'正文有未保存草稿；先保存或撤销草稿，再读取 Claim。':'请选择本项目可写的结构稿件保存版。'}</p>}
    <button disabled={!usable||!!local.busy} onClick={()=>void load()}>重新读取 Claim 与来源</button>
    {local.busy&&<p role="status">{local.busy==='read'?'读取保存版与 Claim…':'核对当前权限与来源并提交明确操作…'}</p>}
    {local.error&&<p role="alert">{local.error}</p>}{local.notice&&<p role="status">{local.notice}</p>}
    <fieldset disabled={blocked}>
      <legend>提出候选关系</legend>
      <label>保存稿件段落<select aria-label="Claim 保存稿件段落" value={local.blockId} onChange={event=>update(old=>({...old,blockId:event.target.value,start:'',end:'',error:'',notice:''}))}>
        <option value="">明确选择保存段落</option>{savedBlocks.map((item:any,index:number)=><option key={item?.id||index} value={item?.id||''}>{item?.id} · {String(item?.text||'').slice(0,80)}</option>)}
      </select></label>
      {block&&<label>保存版原文<textarea aria-label="Claim 保存版段落原文" readOnly value={block.text} onSelect={event=>{
        const element=event.currentTarget,a=claimCodePointOffset(block.text,element.selectionStart),b=claimCodePointOffset(block.text,element.selectionEnd);
        update(old=>({...old,start:a===null?'':String(a),end:b===null?'':String(b),error:'',notice:''}));
      }}/></label>}
      <div className="claim-range"><label>起点（Unicode code point）<input aria-label="Claim 起点" inputMode="numeric" value={local.start} onChange={event=>update(old=>({...old,start:event.target.value}))}/></label>
        <label>终点（Unicode code point）<input aria-label="Claim 终点" inputMode="numeric" value={local.end} onChange={event=>update(old=>({...old,end:event.target.value}))}/></label></div>
      <blockquote aria-label="Claim 准确保存引文">{quote||'尚未选择准确保存引文。'}</blockquote>
      <p>起点包含、终点不包含；选区按 Unicode code point 计数。可在保存版原文中选择，或填写准确起止位置。</p>
      <div className="claim-source-choices" aria-label="Claim 可读保存对象来源">
        <p>明确选择 1–32 个固定对象来源。此服务支持可读取的 Store 保存对象；任务、原始资产地址与原生文件不作为来源。</p>
        {local.catalog.map(source=>{
          const chosen=local.sources.find(ref=>ref.id===source.id);
          return <div key={source.id}><label><input type="checkbox" aria-label={'选择 Claim 来源 '+source.id} checked={!!chosen} disabled={!chosen&&local.sources.length>=32} onChange={event=>chooseSource(source,event.target.checked)}/>
            {source.title||source.id} · {source.kind} · {source.id} · 当前 r{source.revision}</label>
            {chosen&&<label>明确固定修订<input aria-label={'Claim 来源修订 '+source.id} inputMode="numeric" value={chosen.revision} onChange={event=>{
              const value=integer(event.target.value);update(old=>({...old,sources:old.sources.map(ref=>ref.id===source.id?{...ref,revision:value??-1}:ref)}));
            }}/></label>}
          </div>;
        })}
      </div>
      {local.sources.some(ref=>!Number.isSafeInteger(ref.revision)||ref.revision<0)&&<p role="alert">来源修订需为明确非负整数。</p>}
      <p>已选 {local.sources.length} / 32 个来源；历史修订由服务读取固定。与当前来源不同的旧修订会显示缺口，不能直接登记。</p>
      <label>关系<select aria-label="Claim 关系" value={local.relation} onChange={event=>update(old=>({...old,relation:event.target.value}))}>{RELATIONS.map(([value,label])=><option key={value} value={value}>{label}（{value}）</option>)}</select></label>
      <label>关系解释<textarea aria-label="Claim 关系解释" value={local.explanation} onChange={event=>update(old=>({...old,explanation:event.target.value}))}/></label>
      <button disabled={!proposalReady||local.sources.some(ref=>ref.revision<0)} onClick={()=>void mutate('claim.propose')}>提出 Claim 候选</button>
    </fieldset>
    <div className="claim-registry" aria-label="保存的 Claim 登记">
      {local.view&&<p>登记表 r{local.view.registry_revision} · 当前保存稿件 r{local.view.manuscript_revision} · 无科学确认</p>}
      {local.view?.claims.length===0&&<p>尚无保存的 Claim。</p>}
      {local.view?.claims.map((claim:any)=>{
        const observed=observation(claim);
        return <article key={claim.id} aria-label={'Claim '+claim.id}>
          <strong>{claim.id} · {claim.relation}</strong><p>当前：{STATUSES[claim.status]}（{claim.status}） · 原登记状态：{observed.stored_status}</p>
          <p>{claim.explanation}</p><blockquote>{claim.anchor.quote}</blockquote>
          <p>固定稿件 r{claim.anchor.revision} · 段落 {claim.anchor.block_id} · CP [{claim.anchor.start}, {claim.anchor.end})</p>
          {onOpenReference&&<button onClick={()=>onOpenReference({id:object.id,revision:claim.anchor.revision,consumer_id:object.id,block_id:claim.anchor.block_id})}>查看 Claim 固定稿件 {claim.id}</button>}
          <label><input type="checkbox" aria-label={'登记 Claim '+claim.id} disabled={blocked||!eligible(claim)} checked={local.selected.includes(claim.id)} onChange={event=>update(old=>({...old,selected:event.target.checked?[...old.selected,claim.id]:old.selected.filter(id=>id!==claim.id)}))}/>选择此候选登记</label>
          {observed.gaps.length>0&&<ul aria-label={'Claim 来源缺口 '+claim.id}>{observed.gaps.map((gap:any,index:number)=><li key={index}>{gapText(gap)}</li>)}</ul>}
          <div className="claim-fixed-pins">{observed.source_pins.map((pin:any,index:number)=><div key={pin.id+':'+pin.revision+':'+index}>
            <span>{pin.id} · 固定 r{pin.revision}</span><code>SHA-256 {pin.sha256}</code>
            {onOpenReference&&<button onClick={()=>onOpenReference({...pin,consumer_id:object.id})}>查看 Claim 固定来源 {claim.id} {index+1}</button>}
          </div>)}</div>
          <small>来源 pin 与原登记历史保留。登记关系不等于科学确认。</small>
        </article>;
      })}
      <button disabled={!groupReady} onClick={()=>void mutate('claim.accept')}>明确登记选中 Claim 组</button>
      <p>已选 {local.selected.length} / 32 条。整组是否登记由服务原子合同决定；前端不会逐条补写。</p>
      {local.view?.history.length>0&&<details><summary>Claim 原登记历史</summary><ol>{local.view.history.map((entry:any,index:number)=><li key={index}>r{entry.revision} · {entry.action} · {entry.actor} · {entry.claim_ids.join(', ')} · 无科学确认</li>)}</ol></details>}
    </div>
  </section>;
}
