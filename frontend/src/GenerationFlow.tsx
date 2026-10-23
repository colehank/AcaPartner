import {useMemo,useState} from 'react';
import {ReactFlow,Background,Controls,Handle,Position,NodeProps,Node,Connection} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import {GenerationEvidence} from './GenerationEvidence';
import {datasetReference,datasetSources,inputReferences,logicalSources,nodeEvidence} from './GenerationEvidenceModel';
type FlowNode=Node<{label:string,script?:string,inputs:string[],outputs:string[],detail:string,evidence?:string},'step'>;
function StepNode({data}:NodeProps<FlowNode>){return <div className="generation-flow-node" data-evidence={data.evidence}><strong>{data.label}</strong><p>{data.script}</p><small>{data.detail}</small>{data.inputs.map((alias,i)=><div className="flow-port" key={alias}><Handle type="target" position={Position.Left} id={alias} style={{top:75+i*18}}/><span>{alias}</span></div>)}{data.outputs.map((name,i)=><Handle key={name} type="source" position={Position.Right} id={name} style={{top:42+i*18}}/>)}</div>;}
const nodeTypes={step:StepNode};
export function GenerationFlow({steps:givenSteps,datasets,positions,onPositions,onChange,parameterDrafts,onParameterDraft,onParameterCommit,onParameterDiscard,report,mode,plan,actual}:{steps:any[],datasets:any[],positions:Record<string,{x:number,y:number}>,onPositions:(p:Record<string,{x:number,y:number}>)=>void,onChange?:(steps:any[])=>void,parameterDrafts?:Record<string,string>,onParameterDraft?:(id:string,text:string)=>void,onParameterCommit?:(id:string,parameters:Record<string,unknown>)=>void,onParameterDiscard?:(id:string)=>void,report:(e:unknown)=>void,mode:'definition'|'planned'|'actual',plan?:any,actual?:any}){
  const [selected,setSelected]=useState('');
  const [dragPositions,setDragPositions]=useState<Record<string,{x:number,y:number}>>({});
  const actualPositions={...positions,...dragPositions};
  const frozenPlan=mode==='actual'?actual?.run?.payload?.generation_plan||plan:plan;
  const steps:any[]=mode!=='definition'&&Array.isArray(frozenPlan?.nodes)?frozenPlan.nodes:givenSteps;
  const fixedDatasets=useMemo(()=>datasetSources(steps,mode,datasets),[steps,mode,datasets]);
  const selectableDatasets=mode==='definition'?[...fixedDatasets,...datasets.filter(d=>!fixedDatasets.some(f=>f.id===d.id+'@'+d.revision)).map(d=>({id:d.id+'@'+d.revision,ref:{dataset_id:d.id,revision:d.revision},title:d.title,snapshot:d.content?.snapshot,asset_sha256:d.content?.asset_sha256,contract:d.content?.snapshot?.contract,consumers:[],frozen:false}))]:fixedDatasets;
  const selectNode=(id:string)=>setSelected(id);
  const selectedStep=steps.find(n=>n.id===selected),selectedDataset=selectableDatasets.find(d=>d.id===selected);
  const selectedParameters=JSON.stringify(selectedStep?.parameters||{},null,2);
  const parameters=parameterDrafts?.[selected]??selectedParameters;
  const graph=useMemo(()=>{
    const nodes:FlowNode[]=[],edges:any[]=[],seen=new Set<string>();
    steps.forEach((step,i)=>{
      const evidence=nodeEvidence(step,mode,actual),sources=logicalSources(step,frozenPlan);
      nodes.push({id:step.id,type:'step',position:actualPositions[step.id]||{x:330+i*330,y:80},data:{label:step.id+' · '+step.role,script:step.script_snapshot?.relative_path||step.script,inputs:inputReferences(step,mode).map(([alias])=>alias),outputs:Object.keys(step.io.outputs),detail:evidence.label+(sources.length>1?' · '+sources.length+' 个成果步骤共享':''),evidence:evidence.kind}});
      inputReferences(step,mode).forEach(([alias,ref])=>{
        let source=ref.node_id,output=ref.output;
        const datasetRef=datasetReference(ref);
        if(datasetRef){source=datasetRef.dataset_id+'@'+datasetRef.revision;output='data';if(!seen.has(source)){
          seen.add(source);const dataset=fixedDatasets.find(d=>d.id===source);
          nodes.push({id:source,type:'step',position:actualPositions[source]||{x:30,y:80+(seen.size-1)*160},data:{label:dataset?.title||datasetRef.dataset_id,inputs:[],outputs:['data'],detail:'固定数据 r'+datasetRef.revision+(dataset?.snapshot?' · '+dataset.snapshot.row_count+' 行':' · 固定快照尚未提供')}});
        }}
        edges.push({id:step.id+':'+alias,source,target:step.id,sourceHandle:output,targetHandle:alias,label:alias,style:mode==='actual'&&evidence.kind==='unverified'?{strokeDasharray:'5 4'}:undefined});
      });
    });
    if(mode==='definition')for(const dataset of datasets){
      const key=dataset.id+'@'+dataset.revision;if(seen.has(key))continue;seen.add(key);
      nodes.push({id:key,type:'step',position:actualPositions[key]||{x:30,y:80+(seen.size-1)*160},data:{label:dataset.title,inputs:[],outputs:['data'],detail:'可连接数据 r'+dataset.revision}});
    }
    return {nodes,edges};
  },[steps,datasets,positions,dragPositions,mode,actual,frozenPlan,fixedDatasets]);
  const connect=(c:Connection)=>{if(!onChange)return;try{
    const next=structuredClone(steps),target=next.find(n=>n.id===c.target);
    if(!target||!c.targetHandle||!target.io.inputs[c.targetHandle])throw new Error('请选择已声明的输入端口。');
    const source=next.find(n=>n.id===c.source);
    let ref:any,contract:any;
    if(source){if(next.indexOf(source)>=next.indexOf(target))throw new Error('上游必须位于目标之前；不能创建循环。');contract=source.io.outputs[c.sourceHandle||''];ref={node_id:source.id,output:c.sourceHandle};}
    else{const match=(c.source||'').match(/^(.+)@(\d+)$/),dataset=match&&datasets.find(d=>d.id===match[1]&&d.revision===Number(match[2]));if(!dataset)throw new Error('此固定数据修订不可访问。');contract=dataset.content.snapshot.contract;ref={dataset_id:dataset.id,revision:dataset.revision};}
    const canonical=(x:any):any=>Array.isArray(x)?x.map(canonical):x&&typeof x==='object'?Object.fromEntries(Object.keys(x).sort().map(k=>[k,canonical(x[k])])):x;
    if(!contract||JSON.stringify(canonical(contract))!==JSON.stringify(canonical(target.io.inputs[c.targetHandle])))throw new Error('字段、身份或单位合同不同；连线未保存。');
    target.inputs[c.targetHandle]=ref;onChange(next);
  }catch(e){report(e);}};
  return <><p className="generation-flow-caption">{mode==='actual'?'图中连线来自该历史运行的固定依赖。节点状态来自实际输出或检查点；虚线目标尚无核验输出。':mode==='planned'?'此图是待执行计划；固定输入与核验复用不表示本计划已经运行。':'编辑待保存定义。拖动只保存布局；参数与合法连线修改需保存配方。'}</p>
    <div className="generation-flow" role="region" aria-label={mode==='actual'?'实际计算来源图':'生成定义图'} data-generation-mode={mode} data-plan-hash={frozenPlan?.plan_hash} data-run-id={mode==='actual'?actual?.run?.id:undefined}><ReactFlow<FlowNode> nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes} fitView minZoom={.2} maxZoom={1.5} nodesConnectable={!!onChange} onConnect={connect}
    onNodesChange={changes=>{for(const change of changes)if(change.type==='position'&&change.position)setDragPositions(previous=>({...previous,[change.id]:change.position!}));}}
    onNodeDragStop={(_,node)=>{onPositions({...positions,...dragPositions,[node.id]:node.position});setDragPositions({});}} onNodeClick={(_,node)=>selectNode(node.id)}><Background/><Controls/></ReactFlow></div>
    <div className="generation-node-select" role="group" aria-label="选择生成来源节点">{[...selectableDatasets.map(d=>({id:d.id,label:d.title+' · r'+d.ref.revision})),...steps.map(n=>({id:n.id,label:n.id}))].map(n=><button key={n.id} type="button" aria-pressed={selected===n.id} onClick={()=>selectNode(n.id)}>{n.label}</button>)}</div>
    {selectedStep&&onChange&&<div className="flow-selection"><strong>{selected}</strong><label>该步骤的参数<textarea aria-label="所选生成步骤参数" value={parameters} onChange={e=>onParameterDraft?.(selected,e.target.value)}/></label><button onClick={()=>{try{const p=JSON.parse(parameters);if(!p||Array.isArray(p)||typeof p!=='object')throw new Error('参数需要键值对象。');onParameterCommit?.(selected,p);}catch(e){report(e);}}}>更新待保存参数</button>{parameterDrafts?.[selected]!==undefined&&<button type="button" onClick={()=>onParameterDiscard?.(selected)}>撤销此步骤参数草稿</button>}</div>}
    <GenerationEvidence mode={mode} plan={frozenPlan} actual={actual} selectedStep={selectedStep} selectedDataset={selectedDataset} onSelectNode={selectNode}/>
  </>;
}
