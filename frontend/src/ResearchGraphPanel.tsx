import {useEffect,useId,useRef,useState} from 'react';
import {command,CommandError} from './api';
import type {Session} from './session';

type Value=Record<string,any>;
export type GraphObjectLocation={id:string,kind:string,revision:number,projectId:string,ownerProjectId:string|null};
export type GraphPinnedReference={id:string,revision:number,block_id?:string,sha256?:string,consumer_id:string};
export type GraphReferenceState={ref?:GraphPinnedReference,issue?:string,id:string};
export type ResearchGraphSnapshot={projectId:string,project:Value,nodes:Value[],relations:Value[],semanticRelations:Value[],
  proposals:Value[],conflicts:Value[],duplicates:Value[],unresolvedEndpointIds:string[]};
export type ResearchGraphIO={command:(action:string,fields:Value)=>Promise<any>,readCatalog:()=>Promise<any>};
const ident=(value:any)=>typeof value==='string'&&value.length>0&&value.length<=200&&!/[\s/\\\u0000-\u001f]/u.test(value);
const revision=(value:any)=>Number.isInteger(value)&&value>=1;
const record=(value:any)=>!!value&&typeof value==='object'&&!Array.isArray(value);
const owner=(object:Value)=>object.kind==='project'?object.id:object.project_id;
const fail=(message:string):never=>{throw new Error(message);};
const text=(value:any)=>typeof value==='string'?value:'';
const message=(error:unknown)=>error instanceof Error?error.message:String(error);
const statuses=new Set(['candidate','confirmed','rejected','withdrawn','superseded']);
const active=(relation:Value)=>['candidate','confirmed'].includes(relation.status);
const scientificKinds=new Set(['hypothesis','source_supported']);
const relationLabels:Record<string,string>={supports:'支持',limits:'限制',contradicts:'反驳',motivates:'提出动机',studies:'研究',
  related:'关联',depends_on:'依赖',contains:'组成',uses:'使用',produces:'产生',cites:'引用'};
const stateLabels:Record<string,string>={candidate:'候选关联',confirmed:'明确确认的登记',rejected:'已拒绝',withdrawn:'已撤回',superseded:'已替换'};
const decisionLabels:Record<string,string>={pending:'待审查',accept:'接纳',reject:'拒绝',needs_correction:'需纠正',
  accepted:'已接纳',applied:'已落库',awaiting_final_review:'等待最终独立审查',keep:'保留',reuse:'复用',merged:'已合并'};
const decision=(value:any)=>decisionLabels[text(value)]||text(value)||'未登记';
const scientificConfirmation=(metadata:Value)=>metadata.scientific_approval===true?'原记录标记为已确认':metadata.scientific_approval===false?'原记录未确认':'未单独登记';
const hypothesis=(object:Value)=>object.kind==='hypothesis'||object.content?.epistemic_status==='hypothesis'||object.metadata?.epistemic_status==='hypothesis';
const semantic=(relation:Value,objects:Map<string,Value>)=>{
  if(['supports','limits','contradicts','motivates'].includes(relation.type))return true;
  if(relation.type==='studies')return [objects.get(relation.src),objects.get(relation.dst)].some(object=>object?.kind==='question'||object&&hypothesis(object));
  return ['related','depends_on'].includes(relation.type)&&scientificKinds.has(relation.metadata?.epistemic_status);
};

/** Explicit pins only; invalid/missing revisions never become latest reads. */
export function graphReferenceState(raw:any,consumerId:string):GraphReferenceState {
  if(!record(raw)||!ident(raw.id))return {id:text(raw?.id)||'未登记对象',issue:'来源对象身份未登记'};
  if(!revision(raw.revision))return {id:raw.id,issue:'未登记准确来源修订；未改读最新版本'};
  if(raw.block_id!==undefined&&!ident(raw.block_id))return {id:raw.id,issue:'来源段落身份无效'};
  if(raw.sha256!==undefined&&(typeof raw.sha256!=='string'||!/^[a-f0-9]{64}$/.test(raw.sha256)))return {id:raw.id,issue:'来源 SHA256 无效'};
  return {id:raw.id,ref:{id:raw.id,revision:raw.revision,consumer_id:consumerId,
    ...(raw.block_id!==undefined?{block_id:raw.block_id}:{}),...(raw.sha256!==undefined?{sha256:raw.sha256}:{})}};
}
export function checkedGraphProposal(value:any,projectId:string,id:string):Value {
  if(!ident(projectId)||!ident(id)||!record(value)||value.project_id!==projectId||value.id!==id||value.version!==1||!Number.isInteger(value.revision)||value.revision<0||
    typeof value.status!=='string'||!Array.isArray(value.items)||!Array.isArray(value.duplicates)||!Array.isArray(value.history))
    fail('图谱提案身份、项目或版本不符；未显示其他项目提案。');
  const ids=new Set<string>();
  for(const item of value.items){
    if(!record(item)||!ident(item.id)||ids.has(item.id)||!['concept','relation','duplicate'].includes(item.kind)||
      !record(item.proposal)||typeof item.decision!=='string')fail('图谱提案逐项记录无效。');ids.add(item.id);
  }
  return value;
}

/** Join genuine server-visible objects with project-scoped graph.review data. */
export function checkedResearchGraph(review:any,catalog:any,projectId:string):ResearchGraphSnapshot {
  if(!ident(projectId)||!record(review)||!['proposals','relations','duplicates','conflicts'].every(key=>Array.isArray(review[key]))||
    !record(catalog)||!Array.isArray(catalog.projects)||!Array.isArray(catalog.objects))fail('科研图读取缺少实际目录或图谱记录。');
  const objects=new Map<string,Value>();
  for(const object of [...catalog.projects,...catalog.objects]){
    if(!record(object)||!ident(object.id)||typeof object.kind!=='string'||typeof object.title!=='string'||!revision(object.revision)||
      !record(object.content)||!record(object.metadata)||objects.has(object.id))fail('实际对象目录含无效或重复身份。');
    objects.set(object.id,object);
  }
  const project=objects.get(projectId);if(project?.kind!=='project')fail('当前项目不在实际可读目录中。');
  const relationIds=new Set<string>(),included=new Set<string>(),unresolved=new Set<string>();
  for(const relation of review.relations){
    if(!record(relation)||!ident(relation.id)||relationIds.has(relation.id)||!ident(relation.src)||!ident(relation.dst)||
      typeof relation.type!=='string'||!statuses.has(relation.status)||!revision(relation.revision)||!revision(relation.source_revision)||
      !revision(relation.target_revision)||!record(relation.metadata)||!Array.isArray(relation.history))fail('已保存关系缺少准确端点、修订或状态。');
    relationIds.add(relation.id);
    const source=objects.get(relation.src);if(!source||owner(source)!==projectId)fail('图谱关系来源不属于当前项目；未显示其他项目内容。');
    included.add(relation.src);
    if(objects.has(relation.dst))included.add(relation.dst);else unresolved.add(relation.dst);
  }
  for(const proposal of review.proposals)checkedGraphProposal(proposal,projectId,proposal.id);
  if(review.conflicts.some((conflict:any)=>!record(conflict)||conflict.project_id!==projectId))fail('图谱冲突记录属于其他项目。');
  for(const object of objects.values())if(owner(object)===projectId&&!object.archived&&(object.kind==='question'||hypothesis(object)))included.add(object.id);
  const nodes=[...included].map(id=>objects.get(id)!);
  return {projectId,project:project!,nodes,relations:review.relations,semanticRelations:review.relations.filter((relation:Value)=>semantic(relation,objects)),
    proposals:review.proposals,conflicts:review.conflicts,duplicates:review.duplicates,unresolvedEndpointIds:[...unresolved]};
}

async function readCatalog(){
  const response=await fetch('/api/state',{cache:'no-store'}),body=await response.json();
  if(!response.ok)throw new CommandError(body.code,body.error||'实际科研对象目录不可读取',body.details);
  return {projects:body.projects,objects:body.objects};
}
const actualIO:ResearchGraphIO={command,readCatalog};
/** One explicit read; a later load/unmount invalidates each continuation. */
export class ResearchGraphReader {
  private serial=0;
  invalidate(){this.serial++;}
  graph(projectId:string,io:ResearchGraphIO=actualIO){
    const serial=++this.serial,current=()=>serial===this.serial;
    const result=(async()=>{
      try{const review=await io.command('graph.review',{project_id:projectId});if(!current())return null;
        const catalog=await io.readCatalog();if(!current())return null;
        return checkedResearchGraph(review,catalog,projectId);
      }catch(error){if(!current())return null;throw error;}
    })();return {current,result};
  }
  proposal(projectId:string,id:string,io:ResearchGraphIO=actualIO){
    const serial=++this.serial,current=()=>serial===this.serial;
    const result=(async()=>{try{const value=await io.command('graph.proposal_view',{id});if(!current())return null;
      return checkedGraphProposal(value,projectId,id);
    }catch(error){if(!current())return null;throw error;}})();return {current,result};
  }
}

type Callbacks={onOpenObject?:(location:GraphObjectLocation)=>Promise<void>|void,
  onOpenReference?:(reference:GraphPinnedReference)=>Promise<void>|void};
export function ResearchGraphPanel({session:s,report,onOpenObject,onOpenReference}:{session:Session,report:(error:unknown)=>void}&Callbacks){
  const graph=useRef(new ResearchGraphReader()),proposal=useRef(new ResearchGraphReader()),context=useRef({session:s,project:s.project.id}),actions=useRef(0);
  context.current={session:s,project:s.project.id};
  const [read,setRead]=useState<{session:Session,project:string,value:ResearchGraphSnapshot}|null>(null),
    [detail,setDetail]=useState<{session:Session,project:string,value:Value}|null>(null),[loading,setLoading]=useState(false),
    [detailLoading,setDetailLoading]=useState(false),[error,setError]=useState<{session:Session,project:string,text:string}|null>(null);
  const same=(origin:{session:Session,project:string})=>context.current.session===origin.session&&context.current.project===origin.project;
  const load=async()=>{
    const origin=context.current,pending=graph.current.graph(origin.project);proposal.current.invalidate();actions.current++;
    setRead(null);setDetail(null);setDetailLoading(false);setError(null);setLoading(true);
    try{const value=await pending.result;if(pending.current()&&same(origin)&&value)setRead({...origin,value});}
    catch(failure){if(pending.current()&&same(origin)){setError({...origin,text:message(failure)});report(failure);}}
    finally{if(pending.current()&&same(origin))setLoading(false);}
  };
  useEffect(()=>{void load();return()=>{graph.current.invalidate();proposal.current.invalidate();actions.current++;};},[s,s.project.id]);
  const loaded=read&&same(read)?read.value:null,selected=detail&&same(detail)?detail.value:null;
  const openProposal=async(id:string)=>{
    const origin=context.current;if(!loaded?.proposals.some(item=>item.id===id))return;
    const pending=proposal.current.proposal(origin.project,id);setDetail(null);setError(null);setDetailLoading(true);
    try{const value=await pending.result;if(pending.current()&&same(origin)&&value)setDetail({...origin,value});}
    catch(failure){if(pending.current()&&same(origin)){setError({...origin,text:message(failure)});report(failure);}}
    finally{if(pending.current()&&same(origin))setDetailLoading(false);}
  };
  const open=async(callback:()=>Promise<void>|void)=>{
    const origin=context.current,serial=++actions.current;
    try{await callback();}catch(failure){if(serial===actions.current&&same(origin)){setError({...origin,text:message(failure)});report(failure);}}
  };
  return <section className="research-graph-panel" aria-label="科研问题与证据关系">
    <div className="panel-tools"><strong>科研问题与证据关系</strong><button disabled={loading} onClick={()=>void load()}>刷新实际图谱</button></div>
    <p className="research-graph-boundary">按已登记问题、假设和语义关系阅读。候选、审查与科学确认分别保留；连线不替代科学判断。</p>
    {loading&&<p role="status">读取本项目实际关系与对象目录…</p>}
    {error&&same(error)&&<p role="alert">{error.text}</p>}
    {loaded&&<ResearchGraphContent snapshot={loaded} onReadProposal={openProposal} detailLoading={detailLoading}
      onOpenObject={onOpenObject?location=>open(()=>onOpenObject(location)):undefined}
      onOpenReference={onOpenReference?reference=>open(()=>onOpenReference(reference)):undefined}/>}
    {detailLoading&&<p role="status">读取指定图谱提案…</p>}
    {selected&&<GraphProposalContent proposal={selected} projectId={s.project.id}
      onOpenReference={onOpenReference?reference=>open(()=>onOpenReference(reference)):undefined}/>}
  </section>;
}

function References({refs,projectId,onOpenReference}:{refs:any,projectId:string}&Pick<Callbacks,'onOpenReference'>){
  if(!Array.isArray(refs)||!refs.length)return <p className="quiet">未登记固定版本来源。</p>;
  return <ul className="research-graph-references">{refs.map((raw,index)=>{
    const entry=graphReferenceState(raw,projectId);return <li key={index}>{entry.ref?
      <button disabled={!onOpenReference} onClick={()=>onOpenReference?.(entry.ref!)}>读取固定来源 {entry.ref.id} · r{entry.ref.revision}{entry.ref.block_id?' · '+entry.ref.block_id:''}</button>:
      <span role="status">{entry.id} · {entry.issue}</span>}{entry.ref?.sha256&&<small>SHA256 {entry.ref.sha256}</small>}</li>;
  })}</ul>;
}
export function graphObjectLocation(object:Value,projectId:string):GraphObjectLocation{return {id:object.id,kind:object.kind,revision:object.revision,projectId,
  ownerProjectId:typeof owner(object)==='string'?owner(object):null};}
const role=(object:Value)=>object.kind==='project'?'项目上下文':object.kind==='question'?'已登记问题':hypothesis(object)?'已登记假设':object.kind==='concept'?(object.content?.epistemic_status==='candidate'?'候选概念':'概念'):'证据 / 成果对象';
const description=(object:Value)=>text(object.content?.question)||text(object.content?.definition)||text(object.content?.description);
function ScienceDiagram({nodes,relations}:{nodes:Value[],relations:Value[]}){
  const arrow=useId();
  const columns=[nodes.filter(object=>object.kind==='question'||object.kind==='project'),nodes.filter(object=>!['question','project'].includes(object.kind)&&(hypothesis(object)||object.kind==='concept')),
    nodes.filter(object=>!['question','project','concept'].includes(object.kind)&&!hypothesis(object))];
  const positions=new Map<string,{x:number,y:number}>();columns.forEach((column,index)=>column.forEach((object,row)=>positions.set(object.id,{x:24+index*340,y:42+row*128})));
  const height=Math.max(190,...columns.map(column=>column.length*128+45));
  return <div className="research-graph-canvas"><svg width="1020" height={height} viewBox={`0 0 1020 ${height}`} role="img" aria-label="已登记的有向科学关系；候选与确认分别标记">
    <defs><marker id={arrow} markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 Z"/></marker></defs>
    {relations.map((relation,index)=>{const from=positions.get(relation.src)!,to=positions.get(relation.dst)!,right=to.x>=from.x,
      x1=from.x+(right?276:0),x2=to.x+(right?0:276),y1=from.y+43,y2=to.y+43,label=relationLabels[relation.type]||relation.type;
      return <g key={relation.id} className={'research-graph-edge '+relation.status}><title>{`${relation.id} · ${label} · ${stateLabels[relation.status]}`}</title>
        <path d={`M${x1},${y1} C${(x1+x2)/2},${y1} ${(x1+x2)/2},${y2} ${x2},${y2}`} markerEnd={`url(#${arrow})`}/>
        <text x={(x1+x2)/2} y={(y1+y2)/2-8-(index%3)*12} textAnchor="middle">{label} · {relation.status==='candidate'?'候选':'明确确认登记'}</text></g>;})}
    {nodes.map(object=>{const p=positions.get(object.id)!;return <g key={object.id} transform={`translate(${p.x},${p.y})`} className="research-graph-node">
      <rect width="276" height="88" rx="7"/><text x="12" y="23">{role(object)}</text><text x="12" y="47">{Array.from(object.title).slice(0,22).join('')}{Array.from(object.title).length>22?'…':''}</text>
      <text x="12" y="69">{object.id} · 当前 r{object.revision}</text><title>{object.title}</title></g>;})}
  </svg><p className="quiet">阅读排版在本地临时生成；对象及科学关系未修改。下方按钮打开真实对象或明确采用修订。</p></div>;
}

export function ResearchGraphContent({snapshot,onReadProposal,detailLoading=false,onOpenObject,onOpenReference}:{snapshot:ResearchGraphSnapshot,
  onReadProposal:(id:string)=>void,detailLoading?:boolean}&Callbacks){
  const {projectId}=snapshot,objects=new Map(snapshot.nodes.map(object=>[object.id,object]));
  const shown=snapshot.semanticRelations.filter(relation=>active(relation)&&objects.has(relation.src)&&objects.has(relation.dst)&&!objects.get(relation.src)!.archived&&!objects.get(relation.dst)!.archived);
  const diagramIds=new Set(shown.flatMap(relation=>[relation.src,relation.dst]));
  const questions=snapshot.nodes.filter(object=>!object.archived&&(object.kind==='question'||hypothesis(object)));
  return <>
    <h2>{snapshot.project.title}</h2><p>{projectId} · {shown.length} 条当前语义关系 · {questions.length} 个已登记问题或假设</p>
    {shown.length?<ScienceDiagram nodes={snapshot.nodes.filter(object=>diagramIds.has(object.id))} relations={shown}/>:
      <p role="status" className="research-graph-empty">尚无可展示的当前科学语义关系。普通组成、使用和产生关系不构成问题与证据图；已登记问题和历史仍保留在下方。</p>}
    {snapshot.unresolvedEndpointIds.length>0&&<p role="status">端点不在本次实际可读目录中：{snapshot.unresolvedEndpointIds.join('、')}。未猜测标题或替换对象。</p>}
    <div className="research-graph-objects">{snapshot.nodes.filter(object=>!object.archived).map(object=><article key={object.id} aria-label={'科研对象 '+object.id}>
      <h3>{object.title}</h3><small>{role(object)} · {object.kind} · {object.id} · 当前 r{object.revision}{owner(object)!==projectId?' · 共享来源 '+(owner(object)||'未登记项目'):''}</small>
      {description(object)&&<p>{description(object)}</p>}
      <p>科学状态：{text(object.content?.epistemic_status)||text(object.metadata.epistemic_status)||'未单独登记'} · 科学确认：{scientificConfirmation(object.metadata)}</p>
      <p>审查登记：{text(object.metadata.review_status)||(object.metadata.review_identity?'已登记原审查身份':'未登记')}</p>
      <button disabled={!onOpenObject} onClick={()=>onOpenObject?.(graphObjectLocation(object,projectId))}>打开实际对象</button>
    </article>)}</div>
    <h3>已保存语义关系与历史</h3>{snapshot.semanticRelations.map(relation=><article key={relation.id} className="research-graph-relation" aria-label={'科学关系 '+relation.id}>
      <h4>{objects.get(relation.src)?.title||relation.src} → {objects.get(relation.dst)?.title||relation.dst} · {relationLabels[relation.type]||relation.type}</h4>
      <p>关系登记：{stateLabels[relation.status]} · {relation.status} · 关系 r{relation.revision}</p>
      <p>科学说明：{relation.metadata.epistemic_status==='hypothesis'?'候选假说':relation.metadata.epistemic_status==='source_supported'?'登记为来源支持':text(relation.metadata.epistemic_status)||'未单独登记'}</p>
      <p>科学确认：{scientificConfirmation(relation.metadata)}；关系接纳与审查不自动改变此记录。</p>
      <p>独立审查：{relation.metadata.review_identity?'已登记原审查身份；不自动改变科学状态':text(relation.metadata.review_status)||'未登记'}</p>
      {relation.metadata.human_decision&&<p>用户维护决定：{decision(relation.metadata.human_decision.status)} · {text(relation.metadata.human_decision.reason)}</p>}
      <p>{text(relation.metadata.rationale)||text(relation.metadata.evidence)||'未登记关系解释。'}</p>
      <References refs={[{id:relation.src,revision:relation.source_revision},{id:relation.dst,revision:relation.target_revision}]} projectId={projectId} onOpenReference={onOpenReference}/>
      <References refs={relation.metadata.source_refs} projectId={projectId} onOpenReference={onOpenReference}/>
      <details><summary>原关系与保留的修订历史</summary><pre>{JSON.stringify(relation,null,2)}</pre></details>
    </article>)}
    {!snapshot.semanticRelations.length&&<p className="quiet">未登记支持、限制、反驳或有明确科学说明的问题关联。</p>}
    {snapshot.relations.length>snapshot.semanticRelations.length&&<details><summary>其他已保存对象关系（不计作科学证据图）</summary><ul>{snapshot.relations.filter(relation=>!snapshot.semanticRelations.includes(relation)).map(relation=><li key={relation.id}>{relation.src} → {relation.dst} · {relationLabels[relation.type]||relation.type} · {stateLabels[relation.status]}</li>)}</ul></details>}
    <h3>实际图谱提案</h3>{snapshot.proposals.length?snapshot.proposals.map(proposal=><article key={proposal.id}>
      <p>{proposal.id} · r{proposal.revision} · {decision(proposal.status)} · {proposal.items.length} 个原提案项</p>
      <button disabled={detailLoading} onClick={()=>onReadProposal(proposal.id)}>读取此提案实际详情</button>
    </article>):<p role="status">本项目尚无已登记图谱提案；没有生成替代提案。</p>}
    {snapshot.conflicts.length>0&&<details><summary>已保存的冲突（{snapshot.conflicts.length}）</summary><pre>{JSON.stringify(snapshot.conflicts,null,2)}</pre></details>}
    {snapshot.duplicates.length>0&&<details><summary>疑似重复登记（{snapshot.duplicates.length}），同名不代表等价</summary><pre>{JSON.stringify(snapshot.duplicates,null,2)}</pre></details>}
  </>;
}

export function GraphProposalContent({proposal,projectId,onOpenReference}:{proposal:Value,projectId:string}&Pick<Callbacks,'onOpenReference'>){
  checkedGraphProposal(proposal,projectId,proposal.id);
  return <section className="research-graph-proposal" aria-label={'图谱提案 '+proposal.id}>
    <h3>原提案 {proposal.id} · r{proposal.revision} · {decision(proposal.status)}</h3>
    <p>提案接纳、持久化和科学确认分别记录；以下只读。</p>
    <References refs={proposal.artifact_ref?[proposal.artifact_ref]:[]} projectId={projectId} onOpenReference={onOpenReference}/>
    {proposal.items.map((item:any)=><article key={item.id} aria-label={'图谱提案项 '+item.id}>
      <h4>{item.proposal.title||item.proposal.local_id||item.id} · {item.kind==='concept'?'概念':item.kind==='relation'?'关系':'疑似重复'}</h4>
      <p>{text(item.proposal.definition)||text(item.proposal.rationale)||text(item.proposal.reason)||'未登记说明。'}</p>
      {item.kind==='relation'&&<p>{item.proposal.src} → {item.proposal.dst} · {relationLabels[item.proposal.type]||item.proposal.type} · 科学说明 {item.proposal.epistemic_status||'未登记'}</p>}
      <p>逐项审查记录：{decision(item.decision)}{item.reason?' · '+item.reason:''}</p>
      {item.human_decision&&<p>用户原决定：{decision(item.human_decision)}；不替代独立审查。</p>}
      {item.independent_review&&<p>独立审查原决定：{decision(item.independent_review.decision)} · {item.independent_review.reason} · {item.independent_review.review_task_id}</p>}
      {item.applied_id&&<p>实际落库身份：{item.applied_id}；不自动标记科学确认。</p>}
      <References refs={item.proposal.source_refs} projectId={projectId} onOpenReference={onOpenReference}/>
    </article>)}<details><summary>原提案版本与历史</summary><pre>{JSON.stringify(proposal,null,2)}</pre></details>
  </section>;
}
