import {layoutResearchGraph,type LayoutInput} from './researchGraphLayout';
const scope=self as unknown as {onmessage:((event:MessageEvent<{id:number;input:LayoutInput}>)=>void)|null;postMessage:(value:unknown)=>void};
scope.onmessage=async({data})=>{try{scope.postMessage({id:data.id,geometry:await layoutResearchGraph(data.input)});}catch{scope.postMessage({id:data.id,error:true});}};
