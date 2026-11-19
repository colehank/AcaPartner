import {test,expect} from '@playwright/test';
import {initialFolds,projectResearchGraph,revealResearchNode} from '../src/workbench/researchGraphView';
const node=(id:string,kind:string,status='active')=>({id,kind,label:id,status});
const edge=(src:string,dst:string,kind:string)=>({id:src+':'+kind+':'+dst,src,dst,kind,active:true});
test('fold defaults are status-based once; manual choices survive status changes',()=>{
 const ns=[node('p','root'),node('q1','Q','completed'),node('q2','Q')];const saved=initialFolds(ns);expect(saved).toEqual({q1:true,q2:false});
 expect(initialFolds([node('q1','Q','stale'),node('q2','Q','completed'),node('q3','Q','completed')],saved)).toEqual({q1:true,q2:false,q3:true});
});
test('collapsed cross-boundary edges retain scientific identity and real endpoints in source',()=>{
 const ns=[node('p','root'),node('q1','Q'),node('q11','Q'),node('a1','A'),node('e1','E'),node('q2','Q'),node('a2','A'),node('e2','E'),node('c2','C')];
 const es=[edge('p','q1','contains'),edge('p','q2','contains'),edge('q1','q11','contains'),edge('q11','a1','analyzes'),edge('a1','e1','produces'),edge('q2','a2','analyzes'),edge('a2','e2','produces'),edge('e2','c2','supports'),edge('e1','c2','supports')],before=JSON.stringify({ns,es});
 const p=projectResearchGraph(ns,es,{q1:true});expect(p.shown.map(n=>n.id)).toEqual(['a2','c2','e2','q1','q2']);
 expect(p.relations.find(e=>e.id==='e1:supports:c2')).toMatchObject({src:'q1',dst:'c2',projected:true});expect(JSON.stringify({ns,es})).toBe(before);
});
test('a shared analysis remains visible through another unfolded owning question',()=>{
 const ns=[node('q1','Q'),node('q2','Q'),node('a','A')],es=[edge('q1','a','analyzes'),edge('q2','a','analyzes')];
 expect(projectResearchGraph(ns,es,{q1:true}).shown.map(n=>n.id)).toContain('a');expect(projectResearchGraph(ns,es,{q1:true,q2:true}).shown.map(n=>n.id)).not.toContain('a');
 expect(revealResearchNode(ns,es,'a',{q1:true,q2:true})).toEqual({q1:false,q2:true});
});
