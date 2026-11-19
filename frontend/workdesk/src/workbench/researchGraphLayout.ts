/** Research-specific constraints; Graphviz owns ranking and obstacle routing. */
import {planResearchWires,researchWireSegments,wireGeometry,type WireSegment} from './researchGraphWires';
import {researchNodeDimensions} from './researchGraphDimensions';
export type LayoutNode={id:string;kind:string;label:string};
export type LayoutRelation={id:string;src:string;dst:string;kind:string;fulfilled?:boolean;projected?:boolean};
export type Point={x:number;y:number};
export type NodeGeometry=Point&{width:number;height:number};
export type EdgeGeometry={path:string;points:Point[];start:Point;end:Point;middle:Point};
export type GraphGeometry={nodes:Record<string,NodeGeometry>;edges:Record<string,EdgeGeometry>;segments:WireSegment[];groups:{id:string;x:number;y:number;width:number;height:number}[];memberships:string[]};
export type LayoutInput={nodes:LayoutNode[];edges:LayoutRelation[];vertical:boolean};
type Draw={op:string;points?:number[][]};
type GvNode={name:string;pos?:string};
type GvEdge={id:string;_draw_?:Draw[]};
type GvGraph={bb:string;objects?:GvNode[];edges?:GvEdge[]};
const quote=(s:string)=>JSON.stringify(s);
let engine:Promise<import('@viz-js/viz').Viz>|undefined;

export async function layoutResearchGraph(input:LayoutInput):Promise<GraphGeometry>{
 const viz=await (engine??=import('@viz-js/viz').then(v=>v.instance()));
 const nodes=[...input.nodes].sort((a,b)=>a.label.localeCompare(b.label,'en',{numeric:true}));
 if(!nodes.length)return {nodes:{},edges:{},segments:[],groups:[],memberships:[]};
 const byId=new Map(nodes.map(n=>[n.id,n])),edges=input.edges.filter(e=>byId.has(e.src)&&byId.has(e.dst));
 const half=(id:string,axis:'x'|'y')=>researchNodeDimensions(byId.get(id)!)[axis==='x'?'width':'height']/2;
 const children=(id:string)=>edges.filter(e=>e.kind==='contains'&&e.src===id).map(e=>e.dst);
 const roots=nodes.filter(n=>n.kind==='Q'&&!edges.some(e=>e.kind==='contains'&&e.dst===n.id&&byId.get(e.src)?.kind==='Q'));
 const owners=new Map<string,string>(),groups=new Map<string,string[]>();
 for(const root of roots){const members:string[]=[];
  const visit=(id:string)=>{if(owners.has(id))return;owners.set(id,root.id);members.push(id);edges.filter(e=>e.src===id&&!e.projected&&['contains','analyzes','produces','supports','limits','refutes'].includes(e.kind)).forEach(e=>visit(e.dst));};visit(root.id);if(members.length>1)groups.set(root.id,members);
 }
 // The lane itself expresses ownership of later synthesis questions. Drawing
 // another parent→join wire would duplicate membership and obscure the proof.
 // Its real relation and routed geometry remain available in the inspector.
 const memberships=edges.filter(e=>e.kind==='contains'&&byId.get(e.src)?.kind==='Q'&&edges.some(d=>d.kind==='prerequisite'&&d.dst===e.dst&&children(e.src).includes(d.src))).map(e=>e.id);
 const visible=edges.filter(e=>!memberships.includes(e.id));
 const axis=input.vertical?'x':'y',positions=new Map<string,Point>();
 const orderGroups:string[][]=[];
 if(roots.length>1)orderGroups.push(roots.map(n=>n.id));
 for(const p of nodes.filter(n=>children(n.id).length)){
  const ids=children(p.id),levels=new Map<string,number>();
  const level=(id:string,seen=new Set<string>()):number=>{if(levels.has(id))return levels.get(id)!;if(seen.has(id))return 0;const next=new Set(seen).add(id),deps=edges.filter(e=>e.kind==='prerequisite'&&e.dst===id&&ids.includes(e.src));const value=deps.length?1+Math.max(...deps.map(e=>level(e.src,next))):0;levels.set(id,value);return value;};
  ids.forEach(id=>level(id));
  for(const depth of new Set(levels.values())){const same=nodes.filter(n=>ids.includes(n.id)&&levels.get(n.id)===depth).map(n=>n.id);if(same.length>1)orderGroups.push(same);}
 }
 const declarations=nodes.map(n=>{const d=researchNodeDimensions(n);return `${quote(n.id)} [width=${d.width/72},height=${d.height/72}];`;});
 const clusterText=[...groups].map(([id,members],i)=>`subgraph cluster_${i} {graph[margin=24,style=invis];${members.map(quote).join(';')};}`);
 const constraints=orderGroups.map(ids=>`{rank=same;${ids.map(quote).join(';')};${ids.slice(1).map((id,i)=>`${quote(ids[i])}->${quote(id)} [style=invis,constraint=false,weight=100];`).join('')}}`);
 const relation=(e:LayoutRelation)=>`${quote(e.src)} -> ${quote(e.dst)} [id=${quote(e.id)},constraint=${e.kind==='answers'||(e.kind==='prerequisite'&&owners.get(e.src)!==owners.get(e.dst))?'false':'true'}];`;
 const common=`node[shape=box,fixedsize=true,label="",margin=0];edge[arrowhead=none];`;
 const initial=viz.renderJSON(`digraph {graph[rankdir=${input.vertical?'TB':'LR'},newrank=true,splines=ortho,nodesep=.44,ranksep=1.11,pad=0,compound=true];${common}${declarations.join('')}${clusterText.join('')}${constraints.join('')}${visible.map(relation).join('')}}`) as GvGraph;
 for(const n of initial.objects||[])if(n.pos){const [x,y]=n.pos.split(',').map(Number);positions.set(n.name,{x,y:-y});}
 const workMembers=(id:string)=>{const members=new Set<string>();const visit=(key:string)=>{if(members.has(key))return;members.add(key);edges.filter(e=>e.src===key&&!e.projected&&['analyzes','produces','supports','limits','refutes'].includes(e.kind)).forEach(e=>visit(e.dst));};visit(id);return [...members];};
 // A leaf's independent scientific route reads along one row. Parallel
 // analyses keep separate ordered rows, and their shared conclusion joins
 // the actual evidence inputs. Shared work retains native placement.
 for(const q of nodes.filter(n=>n.kind==='Q'&&!children(n.id).length)){
  const members=workMembers(q.id),analyses=nodes.filter(n=>edges.some(e=>!e.projected&&e.kind==='analyzes'&&e.src===q.id&&e.dst===n.id));
  if(!analyses.length||members.some(id=>id!==q.id&&edges.some(e=>!e.projected&&e.dst===id&&['analyzes','produces','supports','limits','refutes'].includes(e.kind)&&!members.includes(e.src))))continue;
  if(analyses.length===1&&members.filter(id=>byId.get(id)?.kind==='E').length<=1&&members.filter(id=>byId.get(id)?.kind==='C').length<=1){const value=positions.get(q.id)![axis];for(const id of members){const p=positions.get(id)!;positions.set(id,{...p,[axis]:value});}}
  else if(analyses.length>1){
   const branches=analyses.map(a=>[a.id,...edges.filter(e=>e.src===a.id&&e.kind==='produces').map(e=>e.dst)]);
   let cursor=Math.min(...branches.flat().map(id=>positions.get(id)![axis]-half(id,axis)));
   const centers:number[]=[];
   for(const branch of branches){const radius=Math.max(...branch.map(id=>half(id,axis))),value=cursor+radius;centers.push(value);for(const id of branch){const p=positions.get(id)!;positions.set(id,{...p,[axis]:value});}cursor+=radius*2+32;}
   const p=positions.get(q.id)!;positions.set(q.id,{...p,[axis]:(centers[0]+centers.at(-1)!)/2});
   for(const id of members.filter(id=>byId.get(id)?.kind==='C')){const inputs=edges.filter(e=>e.dst===id&&['supports','limits','refutes'].includes(e.kind)).map(e=>positions.get(e.src)![axis]);if(inputs.length){const p=positions.get(id)!;positions.set(id,{...p,[axis]:(Math.min(...inputs)+Math.max(...inputs))/2});}}
  }
 }
 // Top-level questions share a parent column and occupy ordered, separate
 // research lanes. This is a domain constraint, not a scientific dependency.
 if(roots.length>1){
  const forward=input.vertical?'y':'x',sameColumn=Math.max(...roots.map(n=>positions.get(n.id)![forward]));
  const areas=roots.map(n=>{const ids=nodes.filter(m=>owners.get(m.id)===n.id).map(m=>m.id);return {id:n.id,ids,min:Math.min(...ids.map(id=>positions.get(id)![axis]-half(id,axis))),max:Math.max(...ids.map(id=>positions.get(id)![axis]+half(id,axis)))};});
  let cursor=Math.min(...areas.map(a=>a.min));
  for(const area of areas){const offset=cursor-area.min,advance=sameColumn-positions.get(area.id)![forward];for(const id of area.ids){const p=positions.get(id)!;positions.set(id,{...p,[axis]:p[axis]+offset,[forward]:p[forward]+advance});}cursor+=area.max-area.min+80;}
 }
 for(const ids of orderGroups){if(!ids.every(id=>!children(id).length))continue;
  const members=ids.map(workMembers);
  // Independent leaf routes occupy ordered lanes as a whole. Shared work
  // retains native placement rather than being moved by several owners.
  if(new Set(members.flat()).size!==members.flat().length)continue;
  const bands=members.map(keys=>({keys,min:Math.min(...keys.map(id=>positions.get(id)![axis]-half(id,axis))),max:Math.max(...keys.map(id=>positions.get(id)![axis]+half(id,axis)))}));
  let cursor=Math.min(...bands.map(b=>b.min));
  for(const band of bands){const offset=cursor-band.min;for(const id of band.keys){const p=positions.get(id)!;positions.set(id,{...p,[axis]:p[axis]+offset});}cursor+=band.max-band.min+32;}
 }
 // An expanded prerequisite includes its visible work. Place a subsequent
 // sibling question after that whole route, keeping synthesis out of A/E lanes.
 const forward=input.vertical?'y':'x';
 for(const n of [...nodes].sort((a,b)=>positions.get(a.id)![forward]-positions.get(b.id)![forward])){
  if(n.kind!=='Q')continue;const deps=edges.filter(e=>e.kind==='prerequisite'&&e.dst===n.id&&owners.get(e.src)===owners.get(n.id));if(!deps.length)continue;
  const preceding=[...new Set(deps.flatMap(e=>workMembers(e.src)))],extent=Math.max(...preceding.map(id=>positions.get(id)![forward]+half(id,forward)));
  const offset=Math.max(0,extent+80+half(n.id,forward)-positions.get(n.id)![forward]);
  for(const id of workMembers(n.id)){const p=positions.get(id)!;positions.set(id,{...p,[forward]:p[forward]+offset});}
 }
 const center=(ids:string[])=>{const values=ids.map(id=>positions.get(id)?.[axis]).filter((n):n is number=>n!==undefined);return (Math.min(...values)+Math.max(...values))/2;};
 const align=(id:string,value:number)=>{const p=positions.get(id);if(!p||!Number.isFinite(value))return;
  const members=byId.get(id)?.kind==='Q'&&!children(id).length?workMembers(id):[id],offset=value-p[axis];
  const collision=members.some(key=>{const old=positions.get(key)!,candidate={...old,[axis]:old[axis]+offset};return nodes.some(n=>!members.includes(n.id)&&positions.has(n.id)&&Math.abs(positions.get(n.id)!.x-candidate.x)<half(key,'x')+half(n.id,'x')+12&&Math.abs(positions.get(n.id)!.y-candidate.y)<half(key,'y')+half(n.id,'y')+12);});
  if(collision)return;for(const key of members){const old=positions.get(key)!;positions.set(key,{...old,[axis]:old[axis]+offset});}
 };
 // Explicit domain alignment is pinned before the routing pass. No routed
 // path is retained from the earlier geometry or redrawn independently.
 for(const root of roots){const ids=children(root.id);if(ids.length){const first=ids.filter(id=>!edges.some(e=>e.kind==='prerequisite'&&e.dst===id&&ids.includes(e.src)));if(first.length)align(root.id,center(first));}}
 for(const n of nodes){const deps=edges.filter(e=>e.kind==='prerequisite'&&e.dst===n.id&&owners.get(e.src)===owners.get(n.id)).map(e=>e.src);if(deps.length>1)align(n.id,center(deps));}
 for(const n of nodes.filter(n=>n.kind==='root'))if(children(n.id).length)align(n.id,center(children(n.id)));
 // Internal work expansion can enlarge a lane; keep neighboring top-level
 // research scopes separate after those domain alignments as well.
 if(roots.length>1){const bands=roots.map(root=>{const ids=nodes.filter(n=>owners.get(n.id)===root.id).map(n=>n.id);return {ids,min:Math.min(...ids.map(id=>positions.get(id)![axis]-half(id,axis))),max:Math.max(...ids.map(id=>positions.get(id)![axis]+half(id,axis)))};});let cursor=Math.min(...bands.map(b=>b.min));for(const band of bands){const offset=cursor-band.min;for(const id of band.ids){const p=positions.get(id)!;positions.set(id,{...p,[axis]:p[axis]+offset});}cursor+=band.max-band.min+80;}}
 for(const n of nodes.filter(n=>n.kind==='root'))if(children(n.id).length)align(n.id,center(children(n.id)));
 // nop2 keeps these positions and computes every real edge around the final
 // node bounds. Cross-lane dependencies cannot move a sibling's rank.
 const plan=planResearchWires(nodes,edges,positions,memberships,input.vertical);
 const fixed=nodes.map(n=>{const p=positions.get(n.id)!,d=researchNodeDimensions(n);return `${quote(n.id)} [width=${d.width/72},height=${d.height/72},pos="${p.x},${-p.y}!"];`;});
 for(const [id,p] of plan.junctions)fixed.push(`${quote(id)} [shape=point,width=0,height=0,pos="${p.x},${-p.y}!"];`);
 const routes=(smooth:boolean)=>viz.renderJSON(`digraph {graph[splines=${smooth?'spline':'ortho'},notranslate=true];${common}${fixed.join('')}${plan.pieces.map(piece=>{
  const e=edges.find(e=>e.id===piece.relations[0])!,a=positions.get(e.src)!,b=positions.get(e.dst)!;let tail=input.vertical?'s':'e',head=input.vertical?(a.x<b.x-2?'nw':a.x>b.x+2?'ne':'n'):(a.y<b.y-2?'nw':a.y>b.y+2?'sw':'w');
  if(e.kind==='prerequisite'&&owners.get(e.src)!==owners.get(e.dst)){tail=input.vertical?(b.x>a.x?'e':'w'):(b.y>a.y?'s':'n');head=input.vertical?(b.x>a.x?'w':'e'):(b.y>a.y?'n':'s');}
  if(e.kind==='answers'){tail=input.vertical?'e':'s';head=tail;}
  if(piece.bundled){tail=input.vertical?'s':'e';head=input.vertical?'n':'w';}
  return `${quote(piece.src)}->${quote(piece.dst)}[id=${quote(piece.id)}${smooth?',tailport='+tail+',headport='+head:''}${plan.junctions.has(piece.src)?',tailclip=false':''}${plan.junctions.has(piece.dst)?',headclip=false':''}];`;
 }).join('')}}`,{engine:'nop2'}) as GvGraph;
 const routed=routes(false),smooth=routes(true);
 const [left,,,top]=routed.bb.split(',').map(Number),point=(p:number[]):Point=>({x:p[0]-left+24,y:top-p[1]+24});
 const result:GraphGeometry={nodes:{},edges:{},segments:[],groups:[],memberships};
 for(const n of routed.objects||[]){if(!n.pos||!byId.has(n.name))continue;const center=point(n.pos.split(',').map(Number)),d=researchNodeDimensions(byId.get(n.name)!);result.nodes[n.name]={x:center.x-d.width/2,y:center.y-d.height/2,...d};}
 const pieceGeometry=new Map<string,EdgeGeometry>();
 for(const piece of plan.pieces){const original=edges.find(e=>e.id===piece.relations[0])!,e=(piece.bundled||original.kind==='contains'?routed:smooth).edges?.find(e=>e.id===piece.id);if(!e)continue;const draw=e._draw_?.find(d=>['b','B','L'].includes(d.op)&&d.points?.length);if(!draw?.points)continue;const controls=draw.points.map(point);let path=`M ${controls[0].x},${controls[0].y}`;const ps:Point[]=[controls[0]];
  if(draw.op==='L')for(const p of controls.slice(1)){path+=` L ${p.x},${p.y}`;ps.push(p);}
  else for(let i=1;i+2<controls.length;i+=3){const [a,b,c,d]=controls.slice(i-1,i+3);path+=` C ${b.x},${b.y} ${c.x},${c.y} ${d.x},${d.y}`;for(let k=1;k<=32;k++){const t=k/32,u=1-t;ps.push({x:u*u*u*a.x+3*u*u*t*b.x+3*u*t*t*c.x+t*t*t*d.x,y:u*u*u*a.y+3*u*u*t*b.y+3*u*t*t*c.y+t*t*t*d.y});}}
  pieceGeometry.set(piece.id,wireGeometry(path,ps));
 }
 if(plan.pieces.some(p=>!pieceGeometry.has(p.id)))throw new Error('Incomplete wire routing');
 result.segments=researchWireSegments(plan.pieces,pieceGeometry,edges,new Set(nodes.map(n=>n.id)));
 for(const e of edges){const parts=plan.paths.get(e.id)!.map(id=>pieceGeometry.get(id)!);result.edges[e.id]=wireGeometry(parts.map(p=>p.path).join(' '),parts.flatMap(p=>p.points));}
 for(const [id,members] of groups){const ns=members.map(i=>result.nodes[i]).filter(Boolean);if(ns.length<2)continue;const x=Math.min(...ns.map(n=>n.x))-22,y=Math.min(...ns.map(n=>n.y))-22;result.groups.push({id,x,y,width:Math.max(...ns.map(n=>n.x+n.width))-x+22,height:Math.max(...ns.map(n=>n.y+n.height))-y+22});}
 if(Object.keys(result.nodes).length!==nodes.length||edges.some(e=>!result.edges[e.id]))throw new Error('Incomplete graph layout');
 return result;
}
