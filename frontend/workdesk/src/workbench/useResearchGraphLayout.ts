import {useEffect,useRef,useState} from 'react';
import type {GraphGeometry,LayoutInput} from './researchGraphLayout';

/** One local worker per mounted diagram. Late results never change its scope. */
export function useResearchGraphLayout(input:LayoutInput){
 const worker=useRef<Worker|null>(null),generation=useRef(0),[retry,setRetry]=useState(0),[result,setResult]=useState<{key:string;geometry?:GraphGeometry;error?:boolean}>({key:''});
 const key=JSON.stringify(input);
 useEffect(()=>()=>{generation.current++;worker.current?.terminate();worker.current=null;},[]);
 useEffect(()=>{
  const id=++generation.current;
  if(!input.nodes.length){setResult({key,geometry:{nodes:{},edges:{},segments:[],groups:[],memberships:[]}});return()=>{generation.current++;};}
  setResult({key:''});
  try{
   const w=worker.current??=new Worker(new URL('./researchGraphLayout.worker.ts',import.meta.url),{type:'module'});
   w.onmessage=({data})=>{if(data.id===id&&generation.current===id)setResult({key,...(data.error?{error:true}:{geometry:data.geometry})});};
   w.onerror=event=>{event.preventDefault();if(generation.current===id){setResult({key,error:true});w.terminate();worker.current=null;}};
   w.postMessage({id,input});
  }catch{setResult({key,error:true});}
  return()=>{generation.current++;};
 },[key,retry]);
 return {geometry:result.key===key?result.geometry:undefined,error:result.key===key&&result.error,retry:()=>setRetry(n=>n+1)};
}
