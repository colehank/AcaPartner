import {test,expect} from '@playwright/test';
import {layoutResearchGraph,type LayoutNode,type LayoutRelation,type Point,type NodeGeometry} from '../src/workbench/researchGraphLayout';
import {initialFolds,projectResearchGraph} from '../src/workbench/researchGraphView';
import egg from '../../tests/fixtures/research-graph-egg-layout.json' with {type:'json'};
function fixture(){const nodes:LayoutNode[]=[{id:'root',kind:'root',label:'Q'},...['1','1.1','1.2','1.3','2','2.1','2.2','2.3','2.4'].map(n=>({id:'q'+n,kind:'Q',label:'Q'+n}))];const edges:LayoutRelation[]=[];const add=(src:string,dst:string,kind:string)=>edges.push({id:kind+':'+src+':'+dst,src,dst,kind});for(const p of ['1','2']){add('root','q'+p,'contains');const children=p==='1'?['1.1','1.2','1.3']:['2.1','2.2','2.3','2.4'];for(const n of children)add('q'+p,'q'+n,'contains');for(const n of children.slice(0,-1))add('q'+n,'q'+children.at(-1)!,'prerequisite');}add('q1','q2','prerequisite');return {nodes,edges,vertical:false};}
function crossesCard(a:Point,b:Point,n:NodeGeometry){
 let low=0,high=1;
 for(const axis of ['x','y'] as const){const min=n[axis]+.3,max=n[axis]+n[axis==='x'?'width':'height']-.3,d=b[axis]-a[axis];if(Math.abs(d)<.0001){if(a[axis]<min||a[axis]>max)return false;}else{const p=(min-a[axis])/d,q=(max-a[axis])/d;low=Math.max(low,Math.min(p,q));high=Math.min(high,Math.max(p,q));if(low>high)return false;}}
 return low<=high;
}
function checkRoutes(g:Awaited<ReturnType<typeof layoutResearchGraph>>,edges:LayoutRelation[]){
 for(const e of edges)for(const [id,n] of Object.entries(g.nodes)){if(id===e.src||id===e.dst)continue;const ps=g.edges[e.id].points;expect(ps.some((p,i)=>i>0&&crossesCard(ps[i-1],p,n)),e.id+' crosses '+id).toBe(false);}
}
function checkCards(g:Awaited<ReturnType<typeof layoutResearchGraph>>){const ns=Object.entries(g.nodes);for(let i=0;i<ns.length;i++)for(let j=i+1;j<ns.length;j++){const a=ns[i][1],b=ns[j][1];expect(a.x+a.width<=b.x+.1||b.x+b.width<=a.x+.1||a.y+a.height<=b.y+.1||b.y+b.height<=a.y+.1,ns[i][0]+' overlaps '+ns[j][0]).toBe(true);}}
test('question branches share parent columns; joins and parents balance their inputs',async()=>{const f=fixture(),g=await layoutResearchGraph(f),ns=g.nodes;expect(ns.q1.x).toBeCloseTo(ns.q2.x,1);for(const p of ['1','2']){const inputs=p==='1'?['1.1','1.2']:['2.1','2.2','2.3'],join=p==='1'?'q1.3':'q2.4';const ys=inputs.map(i=>ns['q'+i].y),center=(Math.min(...ys)+Math.max(...ys))/2;expect(ns['q'+p].y).toBeCloseTo(center,1);expect(ns[join].y).toBeCloseTo(center,1);for(const i of inputs)expect(ns[join].x).toBeGreaterThan(ns['q'+i].x);for(let i=1;i<ys.length;i++)expect(ys[i]).toBeGreaterThan(ys[i-1]);}expect(g.groups).toHaveLength(2);expect(g.memberships).toEqual(expect.arrayContaining(['contains:q1:q1.3','contains:q2:q2.4']));});
test('every actual relationship retains an obstacle-free engine route around card bounds',async()=>{const f=fixture(),g=await layoutResearchGraph(f);expect(Object.keys(g.edges).sort()).toEqual(f.edges.map(e=>e.id).sort());checkRoutes(g,f.edges);checkCards(g);});
test('portrait question branch retains balanced joins and real relations',async()=>{const f=fixture();f.nodes=f.nodes.filter(n=>n.id.startsWith('q1'));f.edges=f.edges.filter(e=>f.nodes.some(n=>n.id===e.src)&&f.nodes.some(n=>n.id===e.dst));f.vertical=true;const g=await layoutResearchGraph(f);expect(g.nodes['q1.3'].x).toBeCloseTo((g.nodes['q1.1'].x+g.nodes['q1.2'].x)/2,1);expect(g.nodes.q1.x).toBeCloseTo(g.nodes['q1.3'].x,1);expect(g.nodes['q1.3'].y).toBeGreaterThan(g.nodes['q1.2'].y);expect(Object.keys(g.edges)).toHaveLength(f.edges.length);});

test('compatible forks and joins draw common stems once with one final arrow; real identities remain complete',async()=>{const f=fixture(),g=await layoutResearchGraph(f),ids=['prerequisite:q1.1:q1.3','prerequisite:q1.2:q1.3'];const collector=g.segments.filter(s=>s.relations.some(id=>ids.includes(id))&&s.arrow);expect(collector).toHaveLength(1);expect(collector[0].relations.sort()).toEqual(ids.sort());expect(g.segments.some(s=>s.relations.includes('contains:root:q1')&&s.relations.includes('contains:root:q2'))).toBeTruthy();for(const e of f.edges)expect(g.segments.some(s=>s.relations.includes(e.id))).toBeTruthy();expect(g.segments.filter(s=>s.relations.some(id=>ids.includes(id))).some(s=>s.path.includes(' Q '))).toBeTruthy();expect(new Set(g.segments.map(s=>s.id)).size).toBe(g.segments.length);});

test('shared drawing never mixes fulfilled states or kinds and adds no scientific nodes',async()=>{const f=fixture();f.edges=f.edges.map(e=>({...e,fulfilled:e.src==='q1.1'}));const g=await layoutResearchGraph(f);expect(Object.keys(g.nodes).sort()).toEqual(f.nodes.map(n=>n.id).sort());for(const s of g.segments){const relations=f.edges.filter(e=>s.relations.includes(e.id));expect(new Set(relations.map(e=>e.kind)).size).toBe(1);expect(new Set(relations.map(e=>e.fulfilled)).size).toBe(1);}const ends=g.segments.filter(s=>s.arrow&&s.relations.some(id=>id==='prerequisite:q1.1:q1.3'||id==='prerequisite:q1.2:q1.3'));expect(ends).toHaveLength(2);});

test('rootless mixed view keeps each ordered question with its independent analysis route',async()=>{
 const nodes:LayoutNode[]=[{id:'q1',kind:'Q',label:'Q1'},{id:'q2',kind:'Q',label:'Q2'}],edges:LayoutRelation[]=[];
 const add=(src:string,dst:string,kind:string)=>edges.push({id:src+':'+kind+':'+dst,src,dst,kind});
 for(const i of [1,2,3]){for(const kind of ['Q','A','E','C'])nodes.push({id:kind+i,kind,label:kind+'2.'+i});add('q2','Q'+i,'contains');add('Q'+i,'A'+i,'analyzes');add('A'+i,'E'+i,'produces');add('E'+i,'C'+i,'supports');}
 add('q1','q2','prerequisite');add('Q1','Q3','prerequisite');add('Q2','Q3','prerequisite');
 const g=await layoutResearchGraph({nodes,edges,vertical:false});expect(g.nodes.Q1.y).toBeLessThan(g.nodes.Q2.y);
 expect(g.nodes.A1.y).toBeLessThan(g.nodes.A2.y);for(const i of [1,2]){expect(g.nodes['A'+i].x).toBeGreaterThan(g.nodes['Q'+i].x);}
 checkRoutes(g,edges);checkCards(g);
});

test('scientific egg folded and expanded projections keep cards separate and real relations inspectable',async()=>{
 for(const folds of [initialFolds(egg.nodes),{...initialFolds(egg.nodes),Q1:false},{...initialFolds(egg.nodes),Q1:false,'Q1.3':false},Object.fromEntries(egg.nodes.filter(n=>n.kind==='Q').map(n=>[n.id,false]))]){
  const p=projectResearchGraph(egg.nodes,egg.edges,folds),g=await layoutResearchGraph({nodes:p.shown,edges:p.routes,vertical:false}),ns=Object.entries(g.nodes);
  checkCards(g);checkRoutes(g,p.routes);
  for(const [id,n] of ns){expect(n.width).toBe(256);expect(n.height).toBe(id.startsWith('E')?212:180);}
  expect(new Set(p.routes.flatMap(e=>e.relation_ids)).size).toBe(p.relations.length);if(folds.Q1)expect(g.groups.some(group=>group.id==='Q1')).toBe(false);
 }
});

test('shared analysis and evidence keep rectangular routing without inventing ownership',async()=>{const nodes:LayoutNode[]=[{id:'Q1',kind:'Q',label:'Q1'},{id:'Q2',kind:'Q',label:'Q2'},{id:'A',kind:'A',label:'A1'},{id:'E',kind:'E',label:'E1'},{id:'C1',kind:'C',label:'C1'},{id:'C2',kind:'C',label:'C2'}];const edges=[['Q1','A','analyzes'],['Q2','A','analyzes'],['A','E','produces'],['E','C1','supports'],['E','C2','limits']].map(([src,dst,kind])=>({id:src+':'+dst,src,dst,kind}));const g=await layoutResearchGraph({nodes,edges,vertical:false});checkCards(g);checkRoutes(g,edges);expect(Object.keys(g.nodes)).toHaveLength(6);expect(Object.keys(g.edges)).toHaveLength(5);});
