import {useState} from 'react';
import './figure-opinion-control.css';
import type {Session} from './session';

// Local composer identity only. The server builds the annotation anchor from
// its registered manifest; none of these display fields become a wire anchor.
export type FigureOpinionAnchor={kind:'figure_artist',project_id:string,paper_id:string,manuscript_revision:number,
  object_id:string,expected_object_revision:number,source_sha256:string,artist_id:string,figure_title:string,artist_label:string,component_index?:number};
export const isFigureOpinionAnchor=(value:any):value is FigureOpinionAnchor=>value?.kind==='figure_artist';
const hex=(value:unknown)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
export function figureOpinionError(anchor:FigureOpinionAnchor,s:Session){
  if(anchor.project_id!==s.project.id||anchor.paper_id!==s.paper.id||anchor.manuscript_revision!==s.paper.revision)return '稿件或项目已变化，请重新选择当前保存图中的元素；原意见保留。';
  if(!anchor.object_id||!anchor.artist_id||!hex(anchor.source_sha256)||!Number.isSafeInteger(anchor.expected_object_revision)||anchor.expected_object_revision<1||anchor.component_index!==undefined&&(!Number.isSafeInteger(anchor.component_index)||anchor.component_index<0))return '图元素的保存身份不完整，请重新读取并选择。';
  if(s.paperDraft?.dirty)return '请先保存文字草稿；当前意见和选区保留。';
  if(s.figureDrafts[anchor.object_id]||s.compositionDrafts[anchor.object_id])return '图有未采用草稿；请先明确保存或撤销，再选择保存版元素。';
}
export function figureOpinionViewError(anchor:FigureOpinionAnchor,view:any){
  const ref=view?.source_ref,render=view?.render,p=render?.provenance;
  if(view?.figure?.project_id!==anchor.project_id||ref?.id!==anchor.object_id||ref.revision!==anchor.expected_object_revision||ref.sha256!==anchor.source_sha256||view.figure.id!==ref.id||view.figure.revision!==ref.revision)return '图保存版已变化或无法读取；原意见保留，请重新选择。';
  if(view.definition||render?.status!=='generated'||render.preview_identity||p?.preview_identity||p?.object_id!==ref.id||p.revision!==ref.revision||p.source_sha256!==ref.sha256||render.replay?.failures?.length)return '此图没有对应当前保存版的已登记元素输出。';
  const members=render.manifest?.filter((m:any)=>m.id===anchor.artist_id);
  if(members?.length!==1||members[0].type==='figure')return '所选真实元素不在此保存版中；未替换为整图或其他元素。';
}
export function figureOpinionWire(anchor:FigureOpinionAnchor){return {field:'visual_overlays',object_id:anchor.object_id,expected_object_revision:anchor.expected_object_revision,artist_id:anchor.artist_id,...(anchor.component_index===undefined?{}:{component_index:anchor.component_index})};}

export function FigureOpinionControl({session:s,view,selected,busy,readOnly,dirty,preview,onReview}:{session:Session,view:any,selected:string[],busy:boolean,readOnly:boolean,dirty:boolean,preview:boolean,onReview?:(anchor:FigureOpinionAnchor)=>void}){
  const scope=JSON.stringify([s.project.id,s.paper.id,s.paper.revision,view?.figure?.id]);
  const [occurrence,setOccurrence]=useState<{session:Session,scope:string,index:number,ref:string}|null>(null);
  const uses=(Array.isArray(s.paper.content.components)?s.paper.content.components:[])
    .map((ref:any,index:number)=>({ref,index}))
    .filter(({ref}:any)=>ref&&(ref.id||ref.object_id)===view?.figure?.id
      &&['id','object_id'].every(key=>!(key in ref)||ref[key]===view?.figure?.id)
      &&Number.isSafeInteger(ref.revision)&&ref.revision>0);
  const bound=occurrence&&occurrence.session===s&&occurrence.scope===scope
    ?uses.find(({ref,index}:any)=>index===occurrence.index&&JSON.stringify(ref)===occurrence.ref):undefined;
  const member=selected.length===1?view?.render?.manifest?.find((m:any)=>m.id===selected[0]):null;
  const anchor:FigureOpinionAnchor={kind:'figure_artist',project_id:s.project.id,paper_id:s.paper.id,manuscript_revision:s.paper.revision,object_id:view?.figure?.id,expected_object_revision:view?.figure?.revision,source_sha256:view?.source_ref?.sha256,artist_id:member?.id,figure_title:view?.figure?.title||'',artist_label:member?.label||member?.id||'',...(bound?{component_index:bound.index}:{})};
  const reason=readOnly?'固定历史只读；明确切到当前保存版后可新建元素意见。':preview||dirty?'当前有未采用图形调整；请先保存或撤销，原调整保留。':occurrence&&!bound?'稿内图使用位置已变化；请重新明确选择，原意见保留。':selected.length!==1||!member||member.type==='figure'?'请选择一个真实图元素；不会把多选默认为首项。':figureOpinionError(anchor,s)||figureOpinionViewError(anchor,view);
  return <div className="figure-opinion-control" role="group" aria-label="图元素意见">
    {(uses.length>0||occurrence)&&<label>采用时更新稿内图<select aria-label="采用时更新稿内图" disabled={busy||readOnly||dirty||preview} value={bound?String(bound.index):''} onChange={e=>{const row=uses.find(({index}:any)=>String(index)===e.target.value);setOccurrence(row?{session:s,scope,index:row.index,ref:JSON.stringify(row.ref)}:null);}}><option value="">不更新稿内引用</option>{uses.map(({ref,index}:any)=><option key={index} value={index}>第 {index+1} 处 · r{ref.revision} · {ref.caption||'无图注'}</option>)}</select></label>}
    <button type="button" disabled={busy||!onReview||!!reason} onClick={()=>{if(!busy&&onReview&&!reason)onReview(structuredClone(anchor));}}>为所选元素添加意见</button>{reason&&<small role="status">{reason}</small>}
  </div>;
}
