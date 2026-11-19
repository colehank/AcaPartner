/* Canvas-unit geometry kept in parity with render_worker.py's SVG exporter.
 * Pure functions: no browser, storage, server mutation or scientific inference.
 */
import {esc} from './ui.js';

const number=(value,fallback)=>value===undefined?fallback:Number(value);
const length=value=>Array.from(value).length;
const paint=(value,fallback)=>typeof value==='string'&&/^(?:#[0-9a-fA-F]{3,8}|transparent|none|white|black)$/.test(value)?value:fallback;

export function nodeBox(node) {
  const box=['x','y','width','height'].map((key,i)=>number(node[key],[0,0,160,70][i]));
  if(box.some(v=>!Number.isFinite(v))||box[2]<=0||box[3]<=0)throw new Error(`节点尺寸无效：${node.id}`);
  return box;
}

export function diagramEndpoints(source,target,linewidth=2) {
  const a=nodeBox(source),b=nodeBox(target),ac=[a[0]+a[2]/2,a[1]+a[3]/2],bc=[b[0]+b[2]/2,b[1]+b[3]/2];
  const dx=bc[0]-ac[0],dy=bc[1]-ac[1],distance=Math.hypot(dx,dy);
  if(!distance)throw new Error(`连接节点中心重合：${source.id} → ${target.id}`);
  const ux=dx/distance,uy=dy/distance,boundary=box=>Math.min(ux?box[2]/(2*Math.abs(ux)):Infinity,uy?box[3]/(2*Math.abs(uy)):Infinity);
  const from=boundary(a)+2+linewidth/2,to=boundary(b)+3+linewidth/2;
  if(distance<=from+to)throw new Error(`连接节点间没有可见间隙：${source.id} → ${target.id}`);
  return {start:[ac[0]+ux*from,ac[1]+uy*from],end:[bc[0]-ux*to,bc[1]-uy*to]};
}

export function svgTextLines(text,width,fontSize) {
  const cap=Math.max(1,Math.trunc(width/(fontSize*.57))),lines=[];
  for(const paragraph of String(text).split('\n')) {
    let current='';
    for(const word of paragraph.match(/\S+\s*/gu)||['']) {
      if(current&&length(current+word)>cap){lines.push(current.trimEnd());current='';}
      if(length(word)>cap) {
        for(const ch of word){if(length(current)>=cap){lines.push(current);current='';}current+=ch;}
      } else current+=word;
    }
    lines.push(current.trimEnd());
  }
  return lines;
}

export function diagramLabelBox(text,fontSize,start,end,obstacles,pageWidth,pageHeight) {
  const padding=5,width=Math.min(220,Math.max(72,Math.max(...String(text).split('\n').map(length))*fontSize*.57));
  const height=svgTextLines(text,width,fontSize).length*fontSize*1.25,bw=width+padding*2,bh=height+padding*2;
  const dx=end[0]-start[0],dy=end[1]-start[1],distance=Math.hypot(dx,dy);
  let nx=-dy/distance,ny=dx/distance;
  if(ny>0||(ny===0&&nx>0)){nx=-nx;ny=-ny;}
  const normalOffset=Math.abs(nx)*bw/2+Math.abs(ny)*bh/2+7;
  const overlap=(box,obstacle)=>Math.max(0,Math.min(box[0]+box[2],obstacle[0]+obstacle[2]+4)-Math.max(box[0],obstacle[0]-4))*Math.max(0,Math.min(box[1]+box[3],obstacle[1]+obstacle[3]+4)-Math.max(box[1],obstacle[1]-4));
  let best=null;
  for(const fraction of [.5,.4,.6,.3,.7,.2,.8,.1,.9])for(const side of [1,-1])for(const extra of [0,fontSize*1.5,fontSize*3]) {
    const offset=side*(normalOffset+extra),box=[start[0]+dx*fraction+nx*offset-bw/2,start[1]+dy*fraction+ny*offset-bh/2,bw,bh];
    const outside=bw*bh-Math.max(0,Math.min(box[0]+bw,pageWidth)-Math.max(0,box[0]))*Math.max(0,Math.min(box[1]+bh,pageHeight)-Math.max(0,box[1]));
    const penalty=outside+obstacles.reduce((sum,item)=>sum+overlap(box,item),0);
    if(penalty<=1e-8)return {box,layout:'clear',padding};
    if(!best||penalty<best.penalty)best={penalty,box};
  }
  return {box:best.box,layout:'overlap_unresolved',padding};
}

export function diagramGeometry(data) {
  const width=number(data.width,1000),height=number(data.height,640);
  if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)throw new Error('画布尺寸必须为正数');
  const nodes=data.nodes||[],byId=new Map(nodes.map(node=>[node.id,node])),obstacles=nodes.map(nodeBox),edges=[],warnings=[];
  for(const edge of data.edges||[]) {
    const source=byId.get(edge.source??edge.src),target=byId.get(edge.target??edge.dst);
    try {
      if(!source||!target)throw new Error(`连接引用的节点不存在：${edge.id}`);
      const linewidth=number(edge.linewidth,2),fontSize=number(edge.font_size,14);
      if(!Number.isFinite(linewidth)||linewidth<=0||!Number.isFinite(fontSize)||fontSize<=0)throw new Error(`连接样式尺寸无效：${edge.id}`);
      const entry={...edge,...diagramEndpoints(source,target,linewidth),linewidth,fontSize,label:edge.label??edge.type??''};
      if(entry.label) {
        entry.labelBox=diagramLabelBox(entry.label,fontSize,entry.start,entry.end,obstacles,width,height);
        obstacles.push(entry.labelBox.box);
        if(entry.labelBox.layout!=='clear')warnings.push(`连接标签与节点、标签或页面边界仍有重叠：${edge.id}`);
      }
      edges.push(entry);
    } catch(error){warnings.push(error.message);}
  }
  return {width,height,nodes,edges,warnings};
}

function textMarkup(text,x,y,width,fontSize,color='#253a39',align='left',bold=false) {
  const anchor={left:'start',center:'middle',right:'end'}[align]||'start',tx=x+(anchor==='middle'?width/2:anchor==='end'?width:0);
  return `<text x="${tx}" y="${y+fontSize}" fill="${paint(color,'#253a39')}" font-size="${fontSize}" font-family="DejaVu Sans, sans-serif" text-anchor="${anchor}" font-weight="${bold?'bold':'normal'}">${svgTextLines(text,width,fontSize).map((line,i)=>`<tspan x="${tx}" dy="${i?fontSize*1.25:0}">${esc(line)}</tspan>`).join('')}</text>`;
}

export function diagramEdgeMarkup(geometry) {
  const defs=[],lines=[],labels=[];
  geometry.edges.forEach((edge,index)=>{
    const color=paint(edge.color,'#617974'),marker=`editor-diagram-arrow-${index}`,action=`data-action="diagram-edge-edit" data-id="${esc(edge.id)}" role="button" tabindex="0" aria-label="${esc(edge.label||edge.id)}"`;
    defs.push(`<marker id="${marker}" markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="${color}"/></marker>`);
    lines.push(`<g ${action} style="cursor:pointer"><line data-edge-line="${esc(edge.id)}" x1="${edge.start[0]}" y1="${edge.start[1]}" x2="${edge.end[0]}" y2="${edge.end[1]}" stroke="${color}" stroke-width="${edge.linewidth}" stroke-dasharray="${edge.status==='confirmed'?'none':'6 4'}" marker-end="url(#${marker})" style="pointer-events:stroke"/></g>`);
    if(edge.labelBox) {
      const [x,y,w,h]=edge.labelBox.box,p=edge.labelBox.padding;
      labels.push(`<g ${action} data-edge-label="${esc(edge.id)}" data-label-layout="${edge.labelBox.layout}" style="cursor:pointer;pointer-events:all"><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="white" rx="3"/>${textMarkup(edge.label,x+p,y+p,w-p*2,edge.fontSize,'#253a39','center')}</g>`);
    }
  });
  return {defs:defs.join(''),lines:lines.join(''),labels:labels.join('')};
}

export function diagramArtwork(data,selected=[]) {
  const geometry=diagramGeometry(data),edges=diagramEdgeMarkup(geometry);
  const nodes=geometry.nodes.map(node=>{
    const [x,y,w,h]=nodeBox(node),fontSize=number(node.font_size,16),chosen=selected.includes(node.id);
    const fill=paint(node.fill,'#eff6f3'),stroke=paint(node.stroke,'#617974'),lineWidth=number(node.linewidth,1);
    if(!Number.isFinite(fontSize)||fontSize<=0||!Number.isFinite(lineWidth)||lineWidth<0)throw new Error(`节点样式尺寸无效：${node.id}`);
    return `<g data-node="${esc(node.id)}" data-group="${esc(node.group||'')}" data-node-x="${x}" data-node-y="${y}" transform="translate(${x} ${y})" role="button" tabindex="0" aria-label="${esc(node.text??node.label??node.id)}" style="cursor:move;user-select:none;touch-action:none"><title>${esc(node.text??node.label??node.id)}</title><rect width="${w}" height="${h}" fill="${fill}" stroke="${stroke}" stroke-width="${lineWidth}"/>${textMarkup(node.text??node.label??'',0,0,w,fontSize,node.color,node.align,node.bold)}<rect data-node-outline="true" x="-2" y="-2" width="${w+4}" height="${h+4}" fill="none" stroke="#649b81" stroke-width="2" visibility="${chosen?'visible':'hidden'}" style="pointer-events:none"/></g>`;
  }).join('');
  const svg=`<svg xmlns="http://www.w3.org/2000/svg" data-diagram-svg="true" width="${geometry.width}" height="${geometry.height}" viewBox="0 0 ${geometry.width} ${geometry.height}" aria-label="可编辑概念图" style="display:block"><rect width="${geometry.width}" height="${geometry.height}" fill="white"/><defs data-diagram-defs="true">${edges.defs}</defs><g data-diagram-lines="true">${edges.lines}</g><g data-diagram-nodes="true">${nodes}</g><g data-diagram-labels="true">${edges.labels}</g></svg>`;
  return {svg,geometry};
}
