/** Research-specific folding; the saved graph and real relation IDs stay intact. */
type ViewNode={id:string;kind:string;label:string;status:string};
type ViewEdge={id:string;src:string;dst:string;kind:string;active:boolean;fulfilled?:boolean};
export type FoldState=Record<string,boolean>;
const structural=new Set(['contains','analyzes','produces','supports','limits','refutes']);

export function initialFolds(nodes:ViewNode[],previous:FoldState={}):FoldState{
 return Object.fromEntries(nodes.filter(n=>n.kind==='Q').map(n=>[n.id,previous[n.id]??n.status==='completed']));
}

export function revealResearchNode(nodes:ViewNode[],edges:ViewEdge[],id:string,folds:FoldState):FoldState{
 const next={...folds},seen=new Set<string>();
 const visit=(key:string)=>{if(seen.has(key))return;seen.add(key);
  // A shared A/E/C needs only one owning route to become visible.
  const incoming=edges.filter(e=>e.active&&structural.has(e.kind)&&e.dst===key)
   .sort((a,b)=>(nodes.find(n=>n.id===a.src)?.label||'').localeCompare(nodes.find(n=>n.id===b.src)?.label||'','en',{numeric:true}));
  const edge=incoming.find(e=>nodes.some(n=>n.id===e.src&&n.kind==='Q'))||incoming[0];
  if(edge){if(nodes.some(n=>n.id===edge.src&&n.kind==='Q'))next[edge.src]=false;visit(edge.src);}
 };visit(id);return next;
}

export function projectResearchGraph<N extends ViewNode,R extends ViewEdge>(nodes:N[],edges:R[],folds:FoldState,answers=false){
 const byId=new Map(nodes.map(n=>[n.id,n])),active=edges.filter(e=>e.active),visible=new Set<string>();
 const tops=nodes.filter(n=>n.kind==='Q'&&!active.some(e=>e.kind==='contains'&&e.dst===n.id&&byId.get(e.src)?.kind==='Q'));
 const visit=(id:string)=>{const n=byId.get(id);if(!n||n.kind==='root'||visible.has(id))return;visible.add(id);
  if(n.kind==='Q'&&folds[id])return;
  for(const e of active)if(e.src===id&&structural.has(e.kind))visit(e.dst);
 };tops.forEach(n=>visit(n.id));
 const representative=(id:string):string|undefined=>{
  const queue=[id],seen=new Set<string>();
  while(queue.length){const key=queue.shift()!;if(seen.has(key))continue;seen.add(key);
   if(visible.has(key))return key;
   queue.push(...active.filter(e=>e.dst===key&&structural.has(e.kind)).map(e=>e.src));
  }
 };
 const relations=active.flatMap(e=>{
  if(!answers&&e.kind==='answers'||byId.get(e.src)?.kind==='root'||byId.get(e.dst)?.kind==='root')return [];
  const src=representative(e.src),dst=representative(e.dst);
  return src&&dst&&src!==dst?[{...e,src,dst,projected:src!==e.src||dst!==e.dst}]:[];
 });
 const pairs=new Map<string,typeof relations>();
 for(const e of relations){const key=JSON.stringify([e.src,e.dst]),group=pairs.get(key)||[];group.push(e);pairs.set(key,group);}
 const routes=[...pairs.values()].flatMap(group=>{
  if(!group.some(e=>e.projected)||group.length===1)return group.map(e=>({...e,relation_ids:[e.id]}));
  const primary=group.find(e=>e.kind==='prerequisite')||group[0];
  return [{...primary,id:'folded:'+group.map(e=>e.id).sort().join('|'),projected:true,fulfilled:group.every(e=>e.fulfilled===true),relation_ids:group.map(e=>e.id)}];
 });
 return {routes,shown:nodes.filter(n=>visible.has(n.id)).sort((a,b)=>a.label.localeCompare(b.label,'en',{numeric:true})),relations,tops};
}
