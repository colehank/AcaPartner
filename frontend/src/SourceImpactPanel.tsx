import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {command} from './api';
import {Session} from './session';

type Source={kind:'object'|'run',id:string};
type Location={key:string,label:string,raw:any,ref?:{id:string,revision:number,sha256?:string},issue?:string};
type Group={consumer:any,locations:Location[]};
const array=(value:any):any[]=>Array.isArray(value)?value:[];
const record=(value:any)=>!!value&&typeof value==='object'&&!Array.isArray(value);
const hash=(value:any)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const revision=(value:any)=>Number.isSafeInteger(value)&&value>0;
const stable=(value:any):string=>JSON.stringify(value,(_key,v)=>record(v)?Object.fromEntries(Object.keys(v).sort().map(k=>[k,v[k]])):v);
const sourceKey=(source:Source|null)=>source?source.kind+':'+source.id:'';
const same=(left:any,right:any)=>stable(left)===stable(right);
function object(value:any,id:string,project:string){
  if(!value||value.id!==id||value.project_id!==project||!revision(value.revision)||typeof value.title!=='string'||!record(value.content))throw Error('来源或成果不属于当前项目，或保存身份不完整；未显示旧缓存。');
  return value;
}
function run(value:any,id:string,project:string){
  if(value?.id!==id||value.project_id!==project||value.payload?.kind!=='generation'||!hash(value.payload.generation_plan?.plan_hash))throw Error('生成运行身份未能确认。');
  return value;
}
function recipeRefs(task:any){const p=task.payload?.generation_plan;return array(p?.recipe_refs||[p?.recipe_ref]).filter(r=>r&&typeof r.id==='string'&&revision(r.revision));}
function outputs(task:any){
  return Object.entries(task.result?.nodes||{}).flatMap(([node,value]:any)=>Object.entries(value.outputs||{}).filter(([,out]:any)=>hash(out?.asset_sha256)).map(([name,out]:any)=>({node,name,sha:out.asset_sha256})));
}
// Only explicit saved fields are locations. Prose and graph edges are never
// promoted to an exact pin. Main pages mirror slots, so count each slot once.
function locations(consumer:any,source:Source,sourceValue:any):Location[]{
  const c=consumer.content,rows:Location[]=[];
  const add=(raw:any,key:string,label:string)=>{
    if(!record(raw)||(raw.id||raw.object_id)!==source.id)return;
    const ref={id:source.id,revision:raw.revision,...(raw.sha256!==undefined?{sha256:raw.sha256}:{})};
    const issue=!revision(ref.revision)?'未能确认固定修订':ref.sha256!==undefined&&!hash(ref.sha256)?'未能确认来源 SHA':undefined;
    rows.push({key,label,raw,ref,issue});
  };
  if(source.kind==='run'){
    const path=c.computation_path;
    if(consumer.kind!=='figure'||path?.run_id!==source.id)return rows;
    for(const [alias,input] of Object.entries(c.input_assets||{})){
      const sha=record(input)?(input as any).sha||(input as any).asset:input;
      const matches=outputs(sourceValue).filter(out=>out.sha===sha);
      rows.push({key:'input:'+alias,label:'图输入 '+alias,raw:{input,computation_path:path,outputs:matches},issue:path.plan_hash!==sourceValue.payload.generation_plan.plan_hash||!matches.length?'未能确认此输入来自该运行':undefined});
    }
    return rows;
  }
  array(c.components).forEach((raw,i)=>add(raw,'component:'+i,'组成成果 · 第 '+(i+1)+' 项'));
  if(c.definition_schema==='research-partner-main-figure/1')array(c.slots).forEach((slot,i)=>{
    add(slot.source,'slot:'+i,'图位 '+slot.id);
    if(rows.at(-1)?.key==='slot:'+i&&(!slot.id||array(c.slots).filter(s=>s.id===slot.id).length!==1))rows.at(-1)!.issue='未能确认唯一图位';
  });
  else array(c.pages).forEach((page,pi)=>array(page.objects).forEach((item,ii)=>{
    const raw=item.source_ref||{id:item.component_id,revision:item.component_revision};
    const key='page:'+pi+':'+ii;add(raw,key,'第 '+(pi+1)+' 页 · 对象 '+(item.id||'未登记'));
    if(rows.at(-1)?.key===key&&(!page.id||!item.id||array(c.pages).filter(p=>p.id===page.id).length!==1||array(page.objects).filter(x=>x.id===item.id).length!==1))rows.at(-1)!.issue='未能确认唯一画布位置';
  }));
  if(consumer.kind==='recipe')array(c.steps).forEach((step,si)=>Object.entries(step.inputs||{}).forEach(([alias,raw]:any)=>{
    const key='step:'+si+':'+alias;add({id:raw.dataset_id,revision:raw.revision},key,'步骤 '+step.id+' · 输入 '+alias);
    if(rows.at(-1)?.key===key&&(!step.id||array(c.steps).filter(s=>s.id===step.id).length!==1))rows.at(-1)!.issue='未能确认唯一步骤';
  }));
  for(const [container,value] of [['正文',c],['元数据',consumer.metadata]] as const)array(value?.source_refs).forEach((raw,i)=>add(raw,'reference:'+container+':'+i,container+' · 来源 '+(i+1)));
  // Legacy documentReferences also binds hashes registered by citations and
  // claims. These constrain a pin without inventing another adoption position.
  const registered=[...array(c.components),...array(c.citations),...array(c.source_refs),...array(consumer.metadata?.source_refs),...array(consumer.metadata?.context?.source_refs),
    ...array(c.claims).flatMap(claim=>[...array(claim.evidence_refs),...array(claim.source_refs)])];
  for(const row of rows){
    const pins=[...rows.map(x=>x.ref),...registered].filter(x=>record(x)&&(x.id||x.object_id)===source.id&&x.revision===row.ref?.revision);
    if(pins.some(x=>Object.hasOwn(x,'sha256')&&!hash(x.sha256)))row.issue='未能确认来源 SHA';
    const hashes=new Set<string>(pins.map(x=>x.sha256).filter(hash));
    if(hashes.size>1)row.issue='同一修订的来源 SHA 不一致';
    else if(hashes.size===1&&!row.issue)row.ref={...row.ref!,sha256:[...hashes][0]};
  }
  return rows;
}
async function get(path:string,signal:AbortSignal){
  const response=await fetch(path,{credentials:'same-origin',signal});
  const body=await response.json();
  if(!response.ok||(path!=='/api/state'&&body?.ok!==true))throw Error(body?.error||'当前来源不可读取；未显示旧缓存。');
  return path==='/api/state'?body:body.result;
}

export function SourceImpactPanel({session:s,initialSource,onClose}:{session:Session,initialSource?:Source,onClose:()=>void}){
  useSyncExternalStore(s.subscribe,s.snapshot);
  const [selection,setSelection]=useState({s,project:s.project.id,source:initialSource||null as Source|null});
  const choice=selection.s===s&&selection.project===s.project.id?selection.source:null;
  const setChoice=(source:Source|null)=>setSelection({s,project:s.project.id,source});
  const [reload,setReload]=useState(0),[receipt,setReceipt]=useState<any>(null),[detail,setDetail]=useState<any>(null);
  const owner=useRef({s,project:s.project.id,epoch:0,serial:0,live:true});
  if(owner.current.s!==s||owner.current.project!==s.project.id){owner.current={s,project:s.project.id,epoch:owner.current.epoch+1,serial:owner.current.serial+1,live:true};}
  const epoch=owner.current.epoch,project=s.project.id,key=sourceKey(choice),scope=useRef({s,project,key,epoch});scope.current={s,project,key,epoch};
  const visible=receipt?.s===s&&receipt.project===project&&receipt.epoch===epoch&&receipt.key===key&&receipt.reload===reload?receipt:null;
  const selectedDetail=visible?.status==='ready'&&detail?.owner===visible?detail:null;
  useEffect(()=>{owner.current.live=true;return()=>{owner.current.live=false;++owner.current.serial;};},[s,project]);
  useEffect(()=>{
    const serial=++owner.current.serial,controller=new AbortController();let live=true;
    const current=()=>live&&owner.current.live&&owner.current.serial===serial&&scope.current.s===s&&s.project.id===project&&scope.current.project===project&&scope.current.key===key&&scope.current.epoch===epoch;
    const publish=(value:any)=>{if(current())setReceipt({s,project,key,epoch,reload,...value});};
    setDetail(null);publish({status:'loading'});
    (async()=>{
      try{
        const state=await get('/api/state',controller.signal);if(!current())return;
        if(!array(state.projects).some(p=>p.id===project)||!Array.isArray(state.objects)||!Array.isArray(state.tasks)||!Array.isArray(state.relations))throw Error('当前项目或来源目录不可读取。');
        const objects=state.objects.filter((o:any)=>o.project_id===project),tasks=state.tasks.filter((t:any)=>t.project_id===project&&t.payload?.kind==='generation');
        if(!choice){publish({status:'ready',objects,tasks,groups:[],gaps:[]});return;}
        let source=choice.kind==='object'?object(await get('/api/objects/'+encodeURIComponent(choice.id),controller.signal),choice.id,project):run(await get('/api/tasks/'+encodeURIComponent(choice.id),controller.signal),choice.id,project);
        if(!current())return;
        const groups:Group[]=[],gaps:string[]=[];
        for(const saved of objects){
          if(saved.id===choice.id||!record(saved.content)||!locations(saved,choice,source).length)continue;
          try{
            const fresh=object(await get('/api/objects/'+encodeURIComponent(saved.id),controller.signal),saved.id,project);if(!current())return;
            const rows=locations(fresh,choice,source);
            if(!rows.length){gaps.push(saved.id+'：采用位置已变化，请刷新目录。');continue;}
            if(choice.kind==='run'&&rows.some(row=>!row.issue)){
              const view=await command('desk.figure.read',{project_id:project,id:fresh.id,revision:fresh.revision});if(!current())return;
              if(view?.figure?.id!==fresh.id||view.figure.project_id!==project||view.figure.revision!==fresh.revision||!hash(fresh.canonical_source_sha256)||view.source_ref?.sha256!==fresh.canonical_source_sha256||view.generation?.source_unavailable||view.generation?.run_id!==source.id||view.generation.plan_hash!==source.payload.generation_plan.plan_hash)throw Error('图来源未能确认');
              for(const row of rows)if(!row.issue){const alias=row.key.slice(6),links=array(view.generation.figure_input_links).filter(x=>x.figure_input===alias).flatMap(x=>array(x.outputs));if(!row.raw.outputs.every((out:any)=>links.some(x=>x.node_id===out.node&&x.output===out.name&&x.asset_sha256===out.sha)))row.issue='未能确认此输入来自该运行';}
            }
            groups.push({consumer:fresh,locations:rows});
          }catch(error){if(!current())return;gaps.push(saved.id+'：未能确认当前采用位置。'+String(error));}
        }
        for(const rel of state.relations.filter((r:any)=>r.dst===choice.id&&r.type==='uses'&&objects.some((o:any)=>o.id===r.src)))if(!groups.some(g=>g.consumer.id===rel.src))gaps.push(rel.src+'：仅有关系登记，未能确认具体采用位置。');
        publish({status:'ready',objects,tasks,source,groups,gaps});
      }catch(error){publish({status:'failed',error:String(error)});}
    })();
    return()=>{live=false;controller.abort();};
  },[s,project,epoch,key,reload]);
  const inspect=async(group:Group,location:Location)=>{
    const original=visible,serial=++owner.current.serial;setDetail(null);setReceipt({...original,inspecting:true});
    const current=()=>owner.current.live&&owner.current.serial===serial&&scope.current.s===s&&s.project.id===project&&scope.current.project===project&&scope.current.epoch===epoch&&scope.current.key===key;
    const controller=new AbortController();
    try{
      const consumer=object(await get('/api/objects/'+encodeURIComponent(group.consumer.id),controller.signal),group.consumer.id,project);if(!current())return;
      const row=locations(consumer,choice!,original.source).find(x=>x.key===location.key);
      if(consumer.revision!==group.consumer.revision||!row||row.issue||!same(row,location))throw Error('采用位置或成果修订已变化；请刷新采用位置。');
      const ref=row.ref!;
      const fixed=object(await get('/api/objects/'+encodeURIComponent(ref.id)+'?'+new URLSearchParams({revision:String(ref.revision),consumer:consumer.id}),controller.signal),ref.id,project);if(!current())return;
      if(fixed.revision!==ref.revision)throw Error('固定修订不一致；未改用当前版本。');
      if(ref.sha256&&fixed.canonical_source_sha256!==ref.sha256)throw Error('固定来源 SHA 不一致；来源未显示。');
      const checked=object(await get('/api/objects/'+encodeURIComponent(consumer.id),controller.signal),consumer.id,project);if(!current())return;
      if(checked.revision!==consumer.revision||!same(locations(checked,choice!,original.source).find(x=>x.key===location.key),row))throw Error('读取期间采用位置已变化；请刷新采用位置。');
      const next={...original,inspecting:false};setReceipt(next);setDetail({owner:next,location:row,fixed});
    }catch(error){if(current()){setReceipt({s,project,key,epoch,reload,status:'failed',error:String(error)});setDetail(null);}}
  };
  const data=visible?.status==='ready'?visible:null;
  const tasks=array(data?.tasks),source=data?.source;
  const runs=source&&choice?.kind==='object'?tasks.filter(t=>recipeRefs(t).some(r=>r.id===source.id)):source?tasks.filter(t=>t.id!==source.id&&recipeRefs(t).some(r=>recipeRefs(source).some(p=>p.id===r.id))):[];
  return <section className="review-panel" aria-label="来源变化影响">
    <div className="panel-tools"><h3>哪些成果采用了这份来源</h3><button onClick={()=>{setDetail(null);setReload(n=>n+1);}}>刷新采用位置</button><button onClick={onClose}>关闭来源变化影响</button></div>
    <p>只读当前项目可见的保存记录。固定版本保留；新版本不表示旧结果有科学错误。未保存草稿不参与此列表。</p>
    {data&&<label>查看哪份来源<select aria-label="查看哪份来源" value={key} onChange={e=>{const [kind,id]=e.target.value.split(':');setChoice(id?{kind:kind as Source['kind'],id}:null);setDetail(null);}}><option value="">选择已保存来源</option>{data.objects.map((o:any)=><option key={o.id} value={'object:'+o.id}>{o.title} · r{o.revision}</option>)}{tasks.map(t=><option key={t.id} value={'run:'+t.id}>生成运行 {t.id}</option>)}</select></label>}
    {!visible||visible.status==='loading'?<p role="status">正在核对保存来源…</p>:visible.status==='failed'?<p role="alert">{visible.error}</p>:null}
    {source&&<><h4>{choice?.kind==='object'?source.title:'生成运行 '+source.id}</h4><p>{choice?.kind==='object'?'当前版本 r'+source.revision:'仅匹配本运行已登记的输出与图输入'}</p>
      {data.groups.map((group:Group)=><article key={group.consumer.id} aria-label={'采用成果 '+group.consumer.id}><h4>{group.consumer.title} · r{group.consumer.revision}{group.consumer.archived?' · 已归档':''}</h4>{group.locations.map(row=><div key={row.key}><p>{row.label}</p>{row.ref&&revision(row.ref.revision)&&<p>固定版本 r{row.ref.revision} · 当前版本 r{source.revision}</p>}{row.issue?<p role="status">{row.issue}</p>:null}{row.ref&&<button disabled={!!row.issue||data.inspecting} onClick={()=>void inspect(group,row)}>查看采用位置 {row.label}</button>}<details><summary>保存的引用</summary><pre>{JSON.stringify(row.raw,null,2)}</pre></details></div>)}<button onClick={()=>setChoice({kind:'object',id:group.consumer.id})}>继续查看 {group.consumer.title} 的采用位置</button></article>)}
      {!data.groups.length&&<p>{choice?.kind==='run'?'尚未确认本运行输出的采用位置':'当前可见记录中未能确认采用位置'}；未登记或不可访问的引用不在此列表。</p>}
      {runs.length>0&&<details open><summary>{choice?.kind==='run'?'同配方的其他运行（分别保留固定输入）':'采用此配方的固定运行'}</summary>{runs.map(t=><p key={t.id}>{recipeRefs(t).map(r=>r.id+' @r'+r.revision).join('、')} <button onClick={()=>setChoice({kind:'run',id:t.id})}>查看运行 {t.id}</button></p>)}</details>}
      {data.gaps.map((gap:string,i:number)=><p role="status" key={i}>{gap}</p>)}
      {selectedDetail&&<aside aria-label="采用位置详情"><h4>{selectedDetail.location.label}</h4><p>{selectedDetail.location.raw.caption||'此位置未登记图注。'}</p><details><summary>采用位置保存字段</summary><pre aria-label="采用位置保存字段">{JSON.stringify(selectedDetail.location.raw,null,2)}</pre></details><h4>固定来源 · {selectedDetail.fixed.title} · r{selectedDetail.fixed.revision}</h4><p>{selectedDetail.fixed.content.caption}</p>{array(selectedDetail.fixed.content.blocks).map((block:any,i:number)=><p key={i}>{typeof block.text==='string'?block.text:'未能确认段落正文'}</p>)}<details><summary>固定来源保存字段</summary><pre aria-label="固定来源保存字段">{JSON.stringify(selectedDetail.fixed.content,null,2)}</pre></details></aside>}
    </>}
  </section>;
}
