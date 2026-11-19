import type {LayoutNode,LayoutRelation,Point,EdgeGeometry} from './researchGraphLayout';
import {researchNodeDimensions} from './researchGraphDimensions';

export type WirePiece={id:string;src:string;dst:string;relations:string[];bundled:boolean};
export type WireSegment=EdgeGeometry&{id:string;relations:string[];arrow:boolean};

/** Routing junctions are a view projection, never research nodes or relations. */
export function planResearchWires(nodes:LayoutNode[],edges:LayoutRelation[],positions:Map<string,Point>,memberships:string[],vertical:boolean){
 const forward=vertical?'y':'x',cross=vertical?'x':'y',byId=new Map(nodes.map(n=>[n.id,n]));
 const half=(id:string,axis:'x'|'y')=>researchNodeDimensions(byId.get(id)!)[axis==='x'?'width':'height']/2;
 const junctions=new Map<string,Point>(),pieces=new Map<string,WirePiece>(),paths=new Map<string,string[]>();
 const eligible=edges.filter(e=>!memberships.includes(e.id)&&e.kind!=='answers'&&positions.get(e.dst)![forward]-positions.get(e.src)![forward]>half(e.src,forward)+half(e.dst,forward)+32);
 type Bus={id:string;center:string;tap:Map<string,string>;slots:string[]};
 const buses={out:new Map<string,Bus>(),in:new Map<string,Bus>()};
 for(const direction of ['out','in'] as const){
  const groups=new Map<string,LayoutRelation[]>();
  for(const e of eligible){const anchor=direction==='out'?e.src:e.dst,other=direction==='out'?e.dst:e.src,p=positions.get(other)!;
   const key=JSON.stringify([anchor,e.kind,!!e.fulfilled,Math.round(p[forward]*10)]);const group=groups.get(key)||[];group.push(e);groups.set(key,group);
  }
  for(const [key,group] of groups){if(group.length<2)continue;const anchor=direction==='out'?group[0].src:group[0].dst,p=positions.get(anchor)!;
   const others=group.map(e=>positions.get(direction==='out'?e.dst:e.src)!);
   const gap=Math.min(...group.map(e=>positions.get(e.dst)![forward]-positions.get(e.src)![forward]-half(e.src,forward)-half(e.dst,forward)));
   const rail=p[forward]+(direction==='out'?1:-1)*(half(anchor,forward)+gap/3),values=[p[cross],...others.map(o=>o[cross])].sort((a,b)=>a-b),low=values[0],high=values.at(-1)!;
   // A bus may not cut through another lane's cards. Irregular graphs retain
   // independent native routing when this compact concentration is unsuitable.
   if(nodes.some(n=>{const q=positions.get(n.id)!;return Math.abs(q[forward]-rail)<half(n.id,forward)+7&&q[cross]+half(n.id,cross)+7>low&&q[cross]-half(n.id,cross)-7<high;}))continue;
   const id='wire:'+direction+':'+key,slots=[...new Set(values)].map((value,i)=>{const name=id+':'+i;junctions.set(name,{[forward]:rail,[cross]:value} as Point);return name;});
   const tap=new Map(group.map(e=>{const other=positions.get(direction==='out'?e.dst:e.src)!;return[e.id,slots[values.filter((v,i)=>i===0||v!==values[i-1]).indexOf(other[cross])]];}));
   const center=slots[[...new Set(values)].indexOf(p[cross])],bus={id,center,tap,slots};for(const e of group)buses[direction].set(e.id,bus);
  }
 }
 const add=(id:string,src:string,dst:string,edge:LayoutRelation,bundled:boolean)=>{let piece=pieces.get(id);if(!piece){piece={id,src,dst,relations:[],bundled};pieces.set(id,piece);}if(!piece.relations.includes(edge.id))piece.relations.push(edge.id);return id;};
 const walk=(bus:Bus,from:string,to:string,e:LayoutRelation)=>{const ids:string[]=[],start=bus.slots.indexOf(from),end=bus.slots.indexOf(to),step=Math.sign(end-start);for(let i=start;i!==end;i+=step)ids.push(add(bus.id+':rail:'+Math.min(i,i+step),bus.slots[i],bus.slots[i+step],e,true));return ids;};
 for(const e of edges){const out=buses.out.get(e.id),into=buses.in.get(e.id),path:string[]=[];
  if(out){path.push(add(out.id+':stem',e.src,out.center,e,true),...walk(out,out.center,out.tap.get(e.id)!,e));}
  path.push(add(e.id,out?.tap.get(e.id)||e.src,into?.tap.get(e.id)||e.dst,e,!!(out||into)));
  if(into){path.push(...walk(into,into.tap.get(e.id)!,into.center,e),add(into.id+':stem',into.center,e.dst,e,true));}
  paths.set(e.id,path);
 }
 return {junctions,pieces:[...pieces.values()],paths};
}

/** Round the engine's orthogonal vertices; this never chooses a route. */
export function roundedWire(points:Point[]):EdgeGeometry{
 const ps=points.filter((p,i)=>!i||Math.hypot(p.x-points[i-1].x,p.y-points[i-1].y)>.01);
 const vertices=ps.filter((p,i)=>!i||i===ps.length-1||Math.abs((p.x-ps[i-1].x)*(ps[i+1].y-p.y)-(p.y-ps[i-1].y)*(ps[i+1].x-p.x))>Math.hypot(p.x-ps[i-1].x,p.y-ps[i-1].y)*Math.hypot(ps[i+1].x-p.x,ps[i+1].y-p.y)*.001);
 let path=`M ${vertices[0].x},${vertices[0].y}`;const samples:Point[]=[vertices[0]];
 for(let i=1;i<vertices.length-1;i++){const a=vertices[i-1],b=vertices[i],c=vertices[i+1],ab=Math.hypot(b.x-a.x,b.y-a.y),bc=Math.hypot(c.x-b.x,c.y-b.y),r=Math.min(5,ab/2,bc/2),u={x:b.x+(a.x-b.x)*r/ab,y:b.y+(a.y-b.y)*r/ab},v={x:b.x+(c.x-b.x)*r/bc,y:b.y+(c.y-b.y)*r/bc};path+=` L ${u.x},${u.y} Q ${b.x},${b.y} ${v.x},${v.y}`;samples.push(u);for(let k=1;k<=8;k++){const t=k/8,s=1-t;samples.push({x:s*s*u.x+2*s*t*b.x+t*t*v.x,y:s*s*u.y+2*s*t*b.y+t*t*v.y});}}
 const end=vertices.at(-1)!;path+=` L ${end.x},${end.y}`;samples.push(end);return wireGeometry(path,samples);
}

export function wireGeometry(path:string,points:Point[]):EdgeGeometry{
 const lengths=points.slice(1).map((p,i)=>Math.hypot(p.x-points[i].x,p.y-points[i].y));let remaining=lengths.reduce((a,b)=>a+b,0)/2,middle=points[0];
 for(let i=0;i<lengths.length;i++){if(remaining<=lengths[i]&&lengths[i]){const f=remaining/lengths[i];middle={x:points[i].x+(points[i+1].x-points[i].x)*f,y:points[i].y+(points[i+1].y-points[i].y)*f};break;}remaining-=lengths[i];}
 return {path,points,start:points[0],end:points.at(-1)!,middle};
}

/** Draw shared pieces once; concatenate same-membership arms through elbows. */
export function researchWireSegments(pieces:WirePiece[],geometry:Map<string,EdgeGeometry>,edges:LayoutRelation[],nodeIds:Set<string>):WireSegment[]{
 const used=new Set<string>(),result:WireSegment[]=[],key=(p:WirePiece)=>[...p.relations].sort().join('|');
 const previous=(p:WirePiece)=>!nodeIds.has(p.src)?pieces.find(q=>q.dst===p.src&&key(q)===key(p)):undefined;
 const next=(p:WirePiece)=>!nodeIds.has(p.dst)?pieces.find(q=>q.src===p.dst&&key(q)===key(p)):undefined;
 for(const piece of pieces){if(used.has(piece.id))continue;let head=piece;const seen=new Set<string>();while(previous(head)&&!seen.has(head.id)){seen.add(head.id);head=previous(head)!;}
  const chain:WirePiece[]=[];let p:WirePiece|undefined=head;while(p&&!used.has(p.id)){chain.push(p);used.add(p.id);p=next(p);}
  const points=chain.flatMap(p=>geometry.get(p.id)!.points),route=head.bundled?roundedWire(points):geometry.get(head.id)!;
  const last=chain.at(-1)!,arrow=last.relations.some(id=>{const e=edges.find(e=>e.id===id)!;return e.kind!=='contains'&&e.dst===last.dst;});
  const id=head.relations.length===1?head.relations[0]:'shared:'+head.id;
  result.push({...route,id:result.some(s=>s.id===id)?head.id+':part':id,relations:head.relations,arrow});
 }
 return result;
}
