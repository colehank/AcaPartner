import {useState} from 'react';
import type {Session} from './session';
import './figure-opinion-control.css';

// Local saved-selection identity. The server independently builds the annotation
// anchor from the exact definition; no client layout or anchor is submitted.
export type MainFigureOpinionAnchor={kind:'main_figure_slots',project_id:string,paper_id:string,manuscript_revision:number,
  object_id:string,expected_object_revision:number,source_sha256:string,definition_sha256:string,slot_ids:string[],
  figure_title:string,slot_labels:{id:string,label:string}[],component_index?:number};
export type MainFigureOpinionControlProps={session:Session,view:any,layoutSelection:readonly string[],busy:boolean,readOnly:boolean,dirty:boolean,onReview?:(anchor:MainFigureOpinionAnchor)=>void};
const hex=(value:unknown)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
const positive=(value:unknown)=>Number.isSafeInteger(value)&&Number(value)>0;
const validSlots=(value:unknown):value is string[]=>Array.isArray(value)&&value.length>0&&value.length<=24&&value.every(id=>typeof id==='string'&&!!id)&&new Set(value).size===value.length;
const stable=(value:any):any=>Array.isArray(value)?value.map(stable):value&&typeof value==='object'?Object.fromEntries(Object.keys(value).sort().map(key=>[key,stable(value[key])])):value;
const same=(a:any,b:any)=>JSON.stringify(stable(a))===JSON.stringify(stable(b));
const matchesUse=(ref:any,id:string)=>ref&&(ref.id||ref.object_id)===id&&['id','object_id'].every(key=>!(key in ref)||ref[key]===id)&&positive(ref.revision)&&(ref.sha256==null||hex(ref.sha256));
export function mainFigureOpinionError(anchor:MainFigureOpinionAnchor,s:Session){
  if(anchor.kind!=='main_figure_slots'||anchor.project_id!==s.project.id||anchor.paper_id!==s.paper.id||anchor.manuscript_revision!==s.paper.revision)return '稿件或项目已变化，请重新选择当前保存主图的图位；原意见保留。';
  if(!anchor.object_id||!positive(anchor.expected_object_revision)||!hex(anchor.source_sha256)||!hex(anchor.definition_sha256)||!validSlots(anchor.slot_ids))return '主图保存身份或所选图位无效，请重新读取并选择。';
  if(s.paperDraft?.dirty)return '请先保存文字草稿；当前意见和图位选择保留。';
  if(s.compositionDrafts[anchor.object_id]||s.figureDrafts[anchor.object_id])return '主图有未保存调整；请先保存或撤销，原选择保留。';
  if(anchor.component_index!==undefined){const index=anchor.component_index,ref=s.paper.content.components?.[index];if(!Number.isSafeInteger(index)||index<0||!matchesUse(ref,anchor.object_id)||ref.revision>anchor.expected_object_revision)return '稿内使用位置不再匹配，请重新明确选择；原意见保留。';}
}
export function mainFigureOpinionViewError(anchor:MainFigureOpinionAnchor,view:any){
  const obj=view?.figure,ref=view?.source_ref,definition=view?.definition;
  if(!obj||obj.project_id!==anchor.project_id||obj.id!==anchor.object_id||obj.revision!==anchor.expected_object_revision||ref?.id!==obj.id||ref?.revision!==obj.revision||ref?.sha256!==anchor.source_sha256||view.definition_sha256!==anchor.definition_sha256||obj.content?.definition_sha256!==anchor.definition_sha256)return '主图保存版已变化或无法读取；原意见保留，请重新选择。';
  if(obj.archived||obj.kind!=='figure'||!obj.content?.composition||definition?.schema!=='research-partner-main-figure/1'||definition.object_id!==obj.id||definition.project_id!==obj.project_id||!Array.isArray(definition.slots)||!same(definition.slots,obj.content.slots)||typeof view.definition_text!=='string')return '主图完整定义或保存身份不可核对；未替换为子图元素。';
  try{if(!same(JSON.parse(view.definition_text.replace(/^\uFEFF/,'')),definition))return '主图定义原文与所读定义不同，请重新读取。';}catch{return '主图定义原文不可读取，请重新读取。';}
  if(!validSlots(anchor.slot_ids)||!validSlots(definition.slots.map((slot:any)=>slot?.id))||anchor.slot_ids.some(id=>!definition.slots.some((slot:any)=>slot.id===id)))return '所选图位不在此保存定义中；不会替换为其他图位。';
}
export function mainFigureOpinionWire(anchor:MainFigureOpinionAnchor){return {field:'slot_layout',object_id:anchor.object_id,expected_object_revision:anchor.expected_object_revision,expected_definition_sha256:anchor.definition_sha256,slot_ids:[...anchor.slot_ids],...(anchor.component_index===undefined?{}:{component_index:anchor.component_index})};}

export function MainFigureOpinionControl({session:s,view,layoutSelection,busy,readOnly,dirty,onReview}:MainFigureOpinionControlProps){
  const id=view?.figure?.id,scope=JSON.stringify([s.project.id,s.paper.id,s.paper.revision,id,view?.figure?.revision,view?.source_ref?.sha256,view?.definition_sha256]);
  const [occurrence,setOccurrence]=useState<{session:Session,scope:string,index:number,ref:any}|null>(null);
  const uses=(Array.isArray(s.paper.content.components)?s.paper.content.components:[]).map((ref:any,index:number)=>({ref,index})).filter(({ref}:any)=>matchesUse(ref,id));
  const bound=occurrence&&occurrence.session===s&&occurrence.scope===scope?uses.find(({ref,index}:any)=>index===occurrence.index&&same(ref,occurrence.ref)):undefined;
  const slots=Array.isArray(view?.definition?.slots)?view.definition.slots:[];
  const anchor:MainFigureOpinionAnchor={kind:'main_figure_slots',project_id:s.project.id,paper_id:s.paper.id,manuscript_revision:s.paper.revision,object_id:id,expected_object_revision:view?.figure?.revision,source_sha256:view?.source_ref?.sha256,definition_sha256:view?.definition_sha256,slot_ids:[...layoutSelection],figure_title:view?.figure?.title||'',slot_labels:layoutSelection.map(id=>({id,label:slots.find((slot:any)=>slot.id===id)?.label||id})),...(bound?{component_index:bound.index}:{})};
  const reason=readOnly?'固定历史只读；明确切到当前保存版后可新建图位意见。':dirty?'当前有未保存主图布局；请先保存或撤销，原选择保留。':occurrence&&!bound?'主图或稿内使用位置已变化；请重新明确选择，原意见保留。':mainFigureOpinionError(anchor,s)||mainFigureOpinionViewError(anchor,view);
  return <div className="figure-opinion-control" role="group" aria-label="主图图位意见">
    <span>所选图位：{anchor.slot_labels.length?anchor.slot_labels.map(slot=>slot.label===slot.id?slot.id:`${slot.label}（${slot.id}）`).join('、'):'未选择'}</span>
    {(uses.length>0||occurrence)&&<label>采用时更新稿内图<select aria-label="采用时更新稿内图" disabled={busy||readOnly||dirty||!view} value={bound?String(bound.index):''} onChange={event=>{const row=uses.find(({index}:any)=>String(index)===event.target.value);setOccurrence(row?{session:s,scope,index:row.index,ref:structuredClone(row.ref)}:null);}}><option value="">不更新稿内引用</option>{uses.map(({ref,index}:any)=><option key={index} value={index}>第 {index+1} 处 · r{ref.revision} · {ref.caption||'无图注'}</option>)}</select></label>}
    <button type="button" disabled={busy||!onReview||!!reason} onClick={()=>{if(!busy&&onReview&&!reason)onReview(structuredClone(anchor));}}>为所选图位添加意见</button>
    {reason&&<small role="status">{reason}</small>}
  </div>;
}
