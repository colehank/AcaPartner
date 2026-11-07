import {useEffect,useRef,useState} from 'react';
import {command,CommandError,requestId} from './api';
import {Session} from './session';

const memberFields=['annotation_ref','batch_ref','exclusion_reason','included','member_id','source_member_id'];
function fixedJSON(value:any):string{
  const ordered=(item:any):any=>Array.isArray(item)?item.map(ordered):item&&typeof item==='object'?Object.fromEntries(Object.keys(item).sort().map(key=>[key,ordered(item[key])])):item;
  return JSON.stringify(ordered(value))??'null';
}
function typedRef(value:any){return value&&fixedJSON(Object.keys(value).sort())===fixedJSON(['id','revision'])&&typeof value.id==='string'&&value.id.length>0&&Number.isSafeInteger(value.revision)&&value.revision>=0;}
function validMember(member:any){
  return member&&typeof member==='object'&&fixedJSON(Object.keys(member).sort())===fixedJSON(memberFields)
    &&typeof member.member_id==='string'&&member.member_id.length>0&&typeof member.source_member_id==='string'&&member.source_member_id.length>0&&typedRef(member.batch_ref)
    &&(member.annotation_ref===null||typedRef(member.annotation_ref))&&typeof member.included==='boolean'
    &&(member.exclusion_reason===null||typeof member.exclusion_reason==='string');
}
function ManifestMembers({projectId,dataset,report}:{projectId:string,dataset:any,report:(e:unknown)=>void}){
  const snapshot=dataset.content.snapshot,descriptor=fixedJSON(snapshot),total=snapshot?.member_manifest?.count;
  const [offsets,setOffsets]=useState([0]),[attempt,setAttempt]=useState(0),[state,setState]=useState<any>(null);
  const offset=offsets[offsets.length-1],scope=fixedJSON([projectId,dataset.id,dataset.revision,descriptor,offset,attempt]);
  const currentScope=useRef(scope),sequence=useRef(0);currentScope.current=scope;
  const current=state?.scope===scope?state:null,loading=!current||current.loading,data=current?.data,error=current?.error;
  useEffect(()=>{
    let mounted=true;const token=++sequence.current;
    const active=()=>mounted&&sequence.current===token&&currentScope.current===scope;
    setState({scope,loading:true,data:null,error:null});
    void (async()=>{
      try{
        if(!snapshot||!Number.isSafeInteger(total)||total<0||typeof snapshot.membership_hash!=='string')
          throw new CommandError('invalid_response','固定成员快照描述不完整，未读取成员',null);
        const page=await command('dataset.members.read',{project_id:projectId,payload:{ref:{id:dataset.id,revision:dataset.revision},offset,limit:200}});
        if(!active())return;
        const end=Math.min(offset+200,total);
        if(!typedRef(page?.ref)||page.ref.id!==dataset.id||page.ref.revision!==dataset.revision||fixedJSON(page.snapshot)!==descriptor
          ||page.offset!==offset||page.executed!==false||!Array.isArray(page.members)||page.members.length!==end-offset
          ||!page.members.every(validMember)||!Array.isArray(page.ordinals)||page.ordinals.length!==page.members.length
          ||!page.ordinals.every((ordinal:any,index:number)=>ordinal===offset+index)
          ||page.next_offset!==(end<total?end:null)||!Array.isArray(page.verified_chunk_sha256)
          ||!page.verified_chunk_sha256.every((sha:any)=>typeof sha==='string'&&/^[a-f0-9]{64}$/.test(sha)))
          throw new CommandError('invalid_response','成员页与固定修订、快照或范围不符；未采用返回内容',null);
        setState({scope,loading:false,data:page,error:null});
      }catch(e){if(active()){setState({scope,loading:false,data:null,error:e instanceof Error?e.message:String(e)});report(e);}}
    })();
    return()=>{mounted=false;sequence.current++;};
  },[scope]);
  const reference=(value:any)=>value?value.id+' · r'+value.revision:'无';
  return <section aria-label="固定清单成员阅读">
    <p>固定数据 {dataset.id} · r{dataset.revision}；成员快照 {snapshot?.id||'未就绪'}；共 {Number.isSafeInteger(total)?total:'未核定'} 个成员。</p>
    <p>当前仅支持阅读此清单来源。排除、恢复、追加和标注更正尚未支持；已有纳入、排除记录及原身份保留。</p>
    <nav aria-label="清单成员分页">
      <button type="button" disabled={loading||offsets.length===1} onClick={()=>setOffsets(value=>value.slice(0,-1))}>上一页成员</button>
      <span>{loading?'正在读取固定成员页':data?`显示第 ${data.members.length?offset+1:0}–${offset+data.members.length} 项，共 ${total} 个成员`:'本页读取失败，未呈现成员'}</span>
      <button type="button" disabled={loading||!data||data.next_offset===null} onClick={()=>setOffsets(value=>[...value,data.next_offset])}>下一页成员</button>
    </nav>
    {loading&&<p role="status">正在读取固定成员页…</p>}
    {error&&<div role="alert"><p>{error}</p><button type="button" onClick={()=>setAttempt(value=>value+1)}>重试读取成员页</button></div>}
    {data&&<div className="membership-list" role="list" aria-label="已读取的固定成员">
      {data.members.map((member:any,index:number)=><article key={offset+index} role="listitem" aria-label={'成员 '+member.member_id} style={{overflowWrap:'anywhere'}}>
        <p>成员 ID：{member.member_id}；源 ID：{member.source_member_id}</p>
        <p>批次：{reference(member.batch_ref)}；标注：{reference(member.annotation_ref)}</p>
        <p>{member.included?'已纳入':'已排除'}；排除原因：{member.exclusion_reason===null?'无':member.exclusion_reason}</p>
      </article>)}
      {!data.members.length&&<p>固定清单没有成员。</p>}
    </div>}
    <details><summary>核对固定来源描述</summary><pre>{JSON.stringify(snapshot,null,2)}</pre></details>
  </section>;
}

export function DatasetMembership({session:s,datasets,reload,report}:{session:Session,datasets:any[],reload:()=>Promise<void>,report:(e:unknown)=>void}){
  const [id,setId]=useState(''),[selected,setSelected]=useState<string[]>([]),[reason,setReason]=useState(''),[batch,setBatch]=useState(''),[busy,setBusy]=useState(false),[corrections,setCorrections]=useState('[]'),[revision,setRevision]=useState('1'),[old,setOld]=useState<any>(null),[page,setPage]=useState(0);
  const dataset=datasets.find(d=>d.id===id),manifest=dataset?.content.authority_kind==='immutable_member_manifest',members=dataset?.content.master_snapshot?.members||dataset?.content.snapshot?.members||[];
  const authority=dataset?.content.authority_kind,knownCSV=(authority===undefined||authority==='immutable_asset')
    &&Number.isSafeInteger(dataset?.content.snapshot?.row_count)&&dataset.content.snapshot.row_count>=0
    &&(Array.isArray(dataset.content.master_snapshot?.members)||Array.isArray(dataset.content.snapshot?.members));
  const pageSize=200,lastPage=Math.max(0,Math.ceil(members.length/pageSize)-1),currentPage=Math.min(page,lastPage),start=currentPage*pageSize;
  const excluded=new Set((dataset?.content.excluded_members||[]).map((m:any)=>JSON.stringify(m)));
  const change=async(operation:string)=>{setBusy(true);try{
    const payload={base_ref:{id,revision:dataset.revision},operation,members:['exclude','restore'].includes(operation)?selected.map(x=>JSON.parse(x)):[],asset_sha256:operation==='append'?batch:null,corrections:operation==='correct_labels'?JSON.parse(corrections):[],reason};
    await command('dataset.revise',{project_id:s.project.id,request_id:requestId(),payload});setSelected([]);await reload();await s.refresh();
  }catch(e){report(e);}finally{setBusy(false);}};
  return <section aria-label="数据成员与历史"><h3>成员范围与修订</h3><label>已有数据<select aria-label="成员数据集" value={id} onChange={e=>{setId(e.target.value);setSelected([]);setOld(null);setPage(0);}}><option value="">选择固定数据</option>{datasets.map(d=><option key={d.id} value={d.id}>{d.title} · r{d.revision}</option>)}</select></label>{dataset&&(manifest?<ManifestMembers key={fixedJSON([s.project.id,dataset.id,dataset.revision,dataset.content.snapshot])} projectId={s.project.id} dataset={dataset} report={report}/>:!knownCSV?<section aria-label="成员来源状态"><p>{authority!==undefined&&authority!=='immutable_asset'?'此格式未支持成员阅读与修改。':'此来源尚未登记成员快照。'}</p><p>保留来源身份 {dataset.id} · r{dataset.revision}；请选择已登记的固定数据继续阅读。</p></section>:<>
    <p>当前范围 {dataset.content.snapshot.row_count} 个；主源 {members.length} 个。新修订保留原字节和旧范围，已保存配方仍使用其固定数据修订。</p>
    <nav aria-label="成员分页"><button type="button" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>上一页成员</button><span>显示第 {members.length?start+1:0}–{Math.min(start+pageSize,members.length)} 项，共 {members.length} 个身份；已选 {selected.length} 个</span><button type="button" disabled={currentPage===lastPage} onClick={()=>setPage(currentPage+1)}>下一页成员</button></nav>
    <div className="membership-list">{members.slice(start,start+pageSize).map((m:any)=>{const key=JSON.stringify(m);return <label key={key}><input type="checkbox" checked={selected.includes(key)} onChange={e=>setSelected(v=>e.target.checked?[...v,key]:v.filter(x=>x!==key))}/>{Object.entries(m).map(([k,v])=>k+'='+v).join(' · ')}{excluded.has(key)?' · 已排除':''}</label>;})}</div><p>翻页保留明确勾选的身份，未显示的未选成员不会进入操作；完整范围保留在固定CSV与成员快照。</p>
    <label>本次范围或标注修订原因<input aria-label="数据修订原因" value={reason} onChange={e=>setReason(e.target.value)}/></label>
    <button disabled={busy||!reason.trim()||!selected.length||selected.some(k=>excluded.has(k))} onClick={()=>change('exclude')}>排除选中成员，保留历史</button><button disabled={busy||!reason.trim()||!selected.length||selected.some(k=>!excluded.has(k))} onClick={()=>change('restore')}>恢复选中成员</button>
    <label>追加的真实CSV批次<select aria-label="追加数据批次" value={batch} onChange={e=>setBatch(e.target.value)}><option value="">选择上传文件</option>{s.assets.filter(a=>a.filename.endsWith('.csv')).map(a=><option key={a.sha} value={a.sha}>{a.filename}</option>)}</select></label><button disabled={busy||!reason.trim()||!batch} onClick={()=>change('append')}>追加为新成员快照</button>
    <details><summary>明确标注更正</summary><a href={'/api/assets/'+(dataset.content.master_asset_sha256||dataset.content.asset_sha256)} target="_blank" rel="noreferrer">核对实际主源CSV</a><p>逐项声明 identity、field、before、after；身份字段不能更改，原值必须与实际主源一致。</p><textarea aria-label="明确数据标注更正" value={corrections} onChange={e=>setCorrections(e.target.value)}/><button disabled={busy||!reason.trim()} onClick={()=>change('correct_labels')}>保存明确标注更正</button></details>
    <label>历史数据修订<input type="number" min="1" max={dataset.revision} aria-label="历史数据修订" value={revision} onChange={e=>setRevision(e.target.value)}/></label><button disabled={busy} onClick={async()=>{try{setOld(await command('dataset.read',{project_id:s.project.id,payload:{ref:{id,revision:Number(revision)}}}));}catch(e){report(e);}}}>读取固定历史快照</button>{old&&<div aria-label="固定历史数据"><p>{old.title} · r{old.revision} · {old.content.snapshot.row_count} 个成员</p><a href={'/api/assets/'+old.content.asset_sha256} target="_blank" rel="noreferrer">该修订实际CSV</a><pre>{JSON.stringify(old.content,null,2)}</pre></div>}
  </>)}</section>;
}
