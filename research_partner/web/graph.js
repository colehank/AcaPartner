import {esc,button,kinds} from './ui.js';
import {objectSearchText} from './ui.js';
import {associatedProjectsPanel} from './graph-navigation.js';
import {diagramEndpoints,diagramLabelBox} from './diagram-geometry.js';
const positionsKey='research-partner:graph-positions';
let positions={};try {positions=JSON.parse(localStorage.getItem(positionsKey)||'{}');} catch {}
const validPosition=p=>p&&typeof p.x==='number'&&typeof p.y==='number'&&Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=0&&p.y>=0&&p.x<=100000&&p.y<=100000;
export function position(object,index,level=0) { if(validPosition(object.metadata?.position))return positions[object.id]={...object.metadata.position};if(validPosition(positions[object.id]))return positions[object.id];const x=50+level*260;let y=55;while(Object.values(positions).some(p=>validPosition(p)&&Math.abs(p.x-x)<210&&Math.abs(p.y-y)<90))y+=112;positions[object.id]={x,y};try{localStorage.setItem(positionsKey,JSON.stringify(positions));}catch{}return positions[object.id]; }
const inactiveRelations=new Set(['withdrawn','rejected','superseded']);
const hierarchyRelations=new Set(['contains','parent','composes','组成','产生','研究','produces','studies']);
export const relationNames={contains:'组成',uses:'使用',produces:'产生',cites:'引用',supports:'支持',limits:'限制',studies:'研究',related:'关联',depends_on:'依赖'};
export const activeRelation=edge=>!inactiveRelations.has(edge.status)&&!inactiveRelations.has(edge.review_status||edge.metadata?.review_status);

// Follow saved directed links only. The visited set bounds cyclic hierarchies.
export function graphModel(c){
 const all=c.objects.filter(o=>!o.archived&&(!c.project||o.project_id===c.project||o.id===c.project));
 const byId=new Map(all.map(o=>[o.id,o])),edges=(c.relations||[]).filter(e=>activeRelation(e)&&byId.has(e.src)&&byId.has(e.dst));
 const children=id=>edges.filter(e=>e.src===id&&hierarchyRelations.has(e.type)).map(e=>e.dst);
 const walk=(id,out)=>{for(const child of children(id))if(!out.has(child)){out.add(child);walk(child,out);}return out;};
 const root=c.graphProjectRoot||c.graphDomain;
 const allowed=root?walk(root,new Set([root])):new Set(byId.keys()),hidden=new Set();
 for(const id of c.collapsed||[])for(const child of walk(id,new Set([id])))if(child!==id)hidden.add(child);
 const q=String(c.graphSearch||'').toLowerCase(),matching=all.filter(o=>allowed.has(o.id)&&(!c.graphKind||o.kind===c.graphKind)&&(!q||objectSearchText(o).includes(q)));
 // Searching is a locator: a saved collapsed branch must not hide a matching object.
 const nodes=matching.filter(o=>q||!hidden.has(o.id)),visible=new Set(nodes.map(o=>o.id));
 const incoming=new Set(edges.filter(e=>hierarchyRelations.has(e.type)).map(e=>e.dst));
 const roots=nodes.filter(o=>!incoming.has(o.id)),levels={};
 const queue=roots.map(o=>[o.id,0]);
 for(let i=0;i<queue.length;i++){const [id,depth]=queue[i];if(levels[id]!==undefined)continue;levels[id]=depth;for(const child of children(id))queue.push([child,depth+1]);}
 return {all,nodes,edges:edges.filter(e=>visible.has(e.src)&&visible.has(e.dst)),children,levels,roots,domains:all.filter(o=>o.kind==='concept'&&children(o.id).length)};
}
function directory(model,c){
 const visible=new Set(model.nodes.map(o=>o.id)),byId=new Map(model.nodes.map(o=>[o.id,o])),seen=new Set();
 const row=(o,depth)=>{if(seen.has(o.id))return '';seen.add(o.id);return `<div style="padding-left:${Math.min(depth,8)*10}px"><div class="button-group">${model.children(o.id).length?button(c.collapsed.has(o.id)?'+':'−','graph-collapse',{id:o.id},'icon-button'):''}${button(`${kinds[o.kind]||o.kind} · ${o.title}`,'graph-focus',{id:o.id},'text-button small')}</div>${model.children(o.id).filter(id=>visible.has(id)).map(id=>row(byId.get(id),depth+1)).join('')}</div>`;};
 return [...model.roots,...model.nodes].map(o=>row(o,0)).join('');
}
export function graphView(c) {
 const model=graphModel(c),{all,nodes,edges}=model;
 const nodePos=Object.fromEntries(all.map((o,i)=>[o.id,position(o,i,model.levels[o.id]??(o.kind==='project'?0:o.kind==='concept'||o.kind==='question'?1:2))]));
 const width=Math.max(1050,...nodes.map(o=>nodePos[o.id].x+260)),height=Math.max(570,...nodes.map(o=>nodePos[o.id].y+160));
 const obstacles=nodes.map(o=>[nodePos[o.id].x,nodePos[o.id].y,220,96]);
 return `<div class="view-heading"><div><span class="eyebrow">RESEARCH LANDSCAPE</span><h1>研究图谱</h1><p>沿实际概念与研究关系展开，查看本轮增量的来源和审查。</p></div><div class="button-group">${button('图谱增量与审查','graph-review',{},'button primary')}${button('新建概念 / 问题','new-node',{},'button')}${button('添加关系','graph-relate',{},'button')}</div></div>
 <div class="graph-tools"><label class="search-input"><span>⌕</span><input id="graph-search" type="search" placeholder="搜索标题、分类、别名或标识" value="${esc(c.graphSearch)}" aria-label="搜索研究图谱"></label><select id="graph-kind" aria-label="按对象类型筛选"><option value="">全部类型</option>${Object.entries(kinds).filter(([k])=>k!=='growth').map(([k,v])=>`<option value="${k}" ${k===c.graphKind?'selected':''}>${esc(v)}</option>`).join('')}</select><select id="graph-domain" aria-label="沿概念展开"><option value="">所有概念域</option>${model.domains.map(o=>`<option value="${esc(o.id)}" ${o.id===c.graphDomain?'selected':''}>${esc(o.title)}</option>`).join('')}</select><span class="graph-count">${nodes.length} 个对象</span>${button('−','graph-zoom',{delta:-0.15},'icon-button')}${button(`${Math.round(c.zoom*100)}%`,'graph-reset',{},'button small')}${button('+','graph-zoom',{delta:0.15},'icon-button')}${button(c.graphDirectory?'收起目录':'层级目录','graph-directory',{},'button small')}</div>
 ${associatedProjectsPanel(c,c.graphDomain)}${c.graphProjectRoot?`<p class="hint graph-project-scope">项目的问题与成果：${esc(all.find(o=>o.id===c.graphProjectRoot)?.title||'当前项目')} · 按已保存的层级关系展开</p>`:''}
 <div class="graph-frame">${c.graphDirectory?`<aside class="graph-directory"><h3>实际关系层级</h3>${directory(model,c)||'<p class="hint">无匹配对象。</p>'}<p class="hint">目录按组成、研究、产生关系展开；交叉关系在画布中保留。</p></aside>`:''}<div class="graph-scroll"><div class="graph-surface" style="width:${width*c.zoom}px;height:${height*c.zoom}px"><div class="graph-scale" style="width:${width}px;height:${height}px;transform:scale(${c.zoom})"><svg class="graph-links" width="${width}" height="${height}" aria-label="研究关系"><defs><marker id="graph-arrow" markerWidth="7" markerHeight="7" refX="7" refY="3.5" orient="auto"><path d="M0 0 L7 3.5 L0 7" fill="#9faeaa"/></marker></defs>${edges.map(e=>{
  const p=nodePos[e.src],t=nodePos[e.dst];let ends;try{ends=diagramEndpoints({...p,width:220,height:96},{...t,width:220,height:96},1);}catch{return '';}
  const [x,y]=ends.start,[tx,ty]=ends.end,label=`${relationNames[e.type]||e.type}${e.status==='confirmed'?'':' · 候选'}`,w=Array.from(label).length*12+14;
  const labelBox=diagramLabelBox(label,12,ends.start,ends.end,obstacles,width,height).box;obstacles.push(labelBox);const [lx,ly,lw,lh]=labelBox;
  return `<g class="graph-link ${e.status==='confirmed'?'confirmed':'candidate'}" role="button" tabindex="0" data-action="graph-relation" data-id="${esc(e.id)}" aria-label="查看关系：${esc(label)}" style="pointer-events:all;cursor:pointer"><path d="M${x},${y} L${tx},${ty}" marker-end="url(#graph-arrow)"/><rect x="${lx}" y="${ly}" width="${lw}" height="${lh}" fill="#f5f5ef"/><text x="${lx+lw/2}" y="${ly+16}">${esc(label)}</text></g>`;
 }).join('')}</svg>${nodes.map(o=>{const p=nodePos[o.id];return `<article class="graph-node kind-${esc(o.kind)}" data-graph-node="${esc(o.id)}" style="left:${p.x}px;top:${p.y}px;height:96px"><div class="node-type">${esc(kinds[o.kind]||o.kind)}${model.children(o.id).length?`<button class="node-collapse" data-action="graph-collapse" data-id="${esc(o.id)}" aria-label="展开或折叠子节点">${c.collapsed.has(o.id)?'+':'−'}</button>`:''}</div><button class="node-title" data-action="open-object" data-id="${esc(o.id)}">${esc(o.title)}</button><span class="node-revision">修订 ${esc(o.revision||1)}${o.metadata?.graph_proposal_id?' · '+({reject:'已拒绝',needs_correction:'需纠正'}[o.metadata?.graph_decision]||'独审候选'):''}</span></article>`;}).join('')}${!nodes.length?'<div class="canvas-empty">这里还没有匹配的研究对象</div>':''}</div></div></div></div><div class="graph-legend"><span><i class="legend-line"></i> 已确认关系</span><span><i class="legend-line candidate"></i> 候选关联</span><span>审查接纳不等于科学确认；撤回的关系保留在审查历史中</span><span>拖动节点调整布局；位置随对象保存</span></div>`;
}
export function bindGraph(root,c,{action,rerender}) {
  root.querySelectorAll('[data-graph-node]').forEach(el=>el.addEventListener('pointerdown',e=>{
    if(e.button!==0||e.target.closest('button'))return;const id=el.dataset.graphNode,object=c.objects.find(o=>o.id===id);let sx=Number.parseFloat(el.style.left),sy=Number.parseFloat(el.style.top),x=e.clientX,y=e.clientY,moved=false;
    el.setPointerCapture(e.pointerId);const move=ev=>{const dx=(ev.clientX-x)/c.zoom,dy=(ev.clientY-y)/c.zoom;if(Math.abs(dx)+Math.abs(dy)>2)moved=true;el.style.left=`${sx+dx}px`;el.style.top=`${sy+dy}px`;};
    const end=async ev=>{el.removeEventListener('pointermove',move);el.removeEventListener('pointerup',end);if(!moved)return;const pos={x:Math.min(100000,Math.max(0,Math.round(sx+(ev.clientX-x)/c.zoom))),y:Math.min(100000,Math.max(0,Math.round(sy+(ev.clientY-y)/c.zoom)))};positions[id]=pos;try{localStorage.setItem(positionsKey,JSON.stringify(positions));}catch{}try{await action('graph.move',{id,expected_revision:object.revision,...pos});}catch(error){positions[id]={x:sx,y:sy};try{localStorage.setItem(positionsKey,JSON.stringify(positions));}catch{}}finally{rerender();}};
    el.addEventListener('pointermove',move);el.addEventListener('pointerup',end);
  }));
}
