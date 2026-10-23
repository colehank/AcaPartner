import type {Node as PMNode} from 'prosemirror-model';
import {continuousPosition,continuousProjection,continuousSelection,type ManuscriptMark} from './ContinuousManuscriptModel';
import {paperReviewMarks} from './PaperReviewProjection';
import {captionComponentIdentity} from './PaperFigureIdentity';
export {captionComponentIdentity} from './PaperFigureIdentity';

export type ReviewSegment={block_id:string,start:number,end:number,quote:string};
export type CaptionReviewTarget={key:string,componentId:string,componentIdentity:string,afterBlockId:string,caption:string,start:number,end:number,quote:string};
export type ReviewNavigationItem={key:string,id:string,kind:'opinion'|'change',label:string,segments:ReviewSegment[],caption?:CaptionReviewTarget,available:boolean,reason?:string};
export type ReviewFocus={requestId:string,scope:string,item:ReviewNavigationItem};
export type ReviewNavigationResult={requestId:string,scope:string,key:string,status:'located'|'unavailable',reason?:string};
export type ReviewNavigation={scope:string,activeKeys:string[],activationId?:string,onLocate:(item:ReviewNavigationItem)=>void};
export function reviewNavigationScope(value:{projectId:string,paperId:string,revision:number,taskId?:string,candidateSha?:string,proposalSha?:string}){
  return JSON.stringify([value.projectId,value.paperId,value.revision,value.taskId??null,value.candidateSha??null,value.proposalSha??null]);
}
export const reviewMarkKey=(mark:Pick<ManuscriptMark,'kind'|'id'>)=>(mark.kind==='opinion'?'opinion:':'change:')+mark.id;

// Check exact identities and codepoints; never search another block by quote.
function segmentError(blocks:any[],segments:ReviewSegment[]):string|undefined{
  if(!segments.length)return '没有可定位的保存选区，请明确重新定位。';
  const used=new Set<string>();let previous=-1;
  for(let i=0;i<segments.length;i++){
    const s=segments[i],matches=blocks.filter(b=>b.id===s.block_id),index=blocks.findIndex(b=>b.id===s.block_id);
    if(matches.length!==1||used.has(s.block_id))return '段落身份缺失或不唯一，请明确重新定位。';
    used.add(s.block_id);const points=Array.from(matches[0].text as string);
    if(!Number.isSafeInteger(s.start)||!Number.isSafeInteger(s.end)||s.start<0||s.end<s.start||s.end>points.length||typeof s.quote!=='string'||points.slice(s.start,s.end).join('')!==s.quote)return '原选区已变化，请在保存稿件中明确重新定位。';
    if(i>0&&(index!==previous+1||s.start!==0))return '跨段选区次序已变化，请明确重新定位。';
    if(i<segments.length-1&&s.end!==points.length)return '跨段选区边界不完整，请明确重新定位。';
    previous=index;
  }
}
// The service's anchored status validates the stored component_ref_sha256.
// Keep the actual component identity too: JSON number formatting in a browser
// must not pretend to reproduce the server's original digest encoding.
function captionTarget(blocks:any[],saved:{paperId:string,components:any[]}|undefined,id:string,range:any):{caption?:CaptionReviewTarget,reason?:string}{
  const matches=saved?.components.map((component,index)=>({component,index})).filter(({component})=>(component.id||component.object_id)===id)||[];
  if(!saved?.paperId||!id||matches.length!==1)return {reason:'稿内图位置缺失或不唯一，请明确重新定位。'};
  const {component,index}=matches[0],text=component.caption;
  if(typeof text!=='string'||!Number.isSafeInteger(component.revision)||component.revision<1||blocks.filter(b=>b.id===component.after_block_id).length!==1)return {reason:'稿内图的固定来源或正文位置无效，请明确重新定位。'};
  const points=Array.from(text),start=range.start??0,end=range.end??points.length;
  if(!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start<0||end<start||end>points.length||typeof range.quote!=='string'||points.slice(start,end).join('')!==range.quote)return {reason:'图注原选区已变化，请明确重新定位。'};
  return {caption:{key:saved.paperId+':'+index,componentId:id,componentIdentity:captionComponentIdentity(component),afterBlockId:component.after_block_id,caption:text,start,end,quote:range.quote}};
}
export function paperReviewNavigationItems(blocks:any[],review:any,edits:any,view:any,saved?:{paperId:string,components:any[]}):ReviewNavigationItem[]{
  const items:ReviewNavigationItem[]=[],marks=paperReviewMarks(blocks,review?{...review,opinions:(review.opinions||[]).filter((o:any)=>o.anchor)}:review,edits,view,true);
  for(const o of review?.opinions||[]){
    if(o.field==='caption'){
      const target=captionTarget(blocks,saved,o.component_id,o.anchor||{}),annotation=review?.annotations?.find((a:any)=>a.id===o.id);
      const reason=o.deleted?'本意见已删除；历史保留。':annotation?.status!=='anchored'||o.anchor?.field!=='caption'||o.anchor.component_id!==o.component_id||!/^[a-f0-9]{64}$/.test(o.anchor.component_ref_sha256||'')?'原图注未可靠定位，请明确重新定位。':target.reason;
      items.push({key:'opinion:'+o.id,id:o.id,kind:'opinion',label:o.text||'图注意见',segments:[],...target,available:!reason,...(reason?{reason}:{})});continue;
    }
    const segments=(o.anchor?.segments||[o.anchor]).filter(Boolean).map((s:any)=>({block_id:s.block_id,start:s.start??0,end:s.end??Array.from(blocks.find(b=>b.id===s.block_id)?.text||'').length,quote:s.quote}));
    const annotation=review?.annotations?.find((a:any)=>a.id===o.id),reason=o.deleted?'本意见已删除；历史保留。':annotation?.status!=='anchored'?'原选区未可靠定位，请明确重新定位。':segmentError(blocks,segments);
    items.push({key:'opinion:'+o.id,id:o.id,kind:'opinion',label:o.text||'批注',segments,available:!reason,...(reason?{reason}:{})});
  }
  const changes=[...(edits?.changes||[]),...(view?.proposal?.changes||[])];
  for(const c of changes){
    if(c.target?.field==='caption'){
      const target=captionTarget(blocks,saved,c.target.component_id,{quote:c.before}),reason=c.state!=='pending'?'本候选已有决定。':c.conflict?'候选与当前图注冲突；人工内容保留。':target.reason;
      items.push({key:'change:'+c.id,id:c.id,kind:'change',label:c.reason||'图注修订',segments:[],...target,available:!reason,...(reason?{reason}:{})});continue;
    }
    const segments=marks.filter(m=>reviewMarkKey(m)==='change:'+c.id).map(m=>({block_id:m.block_id,start:m.start,end:m.end,quote:m.quote??''}));
    const reason=c.state!=='pending'?'本候选已有决定。':c.conflict?'候选与当前稿件冲突；人工内容保留。':segmentError(blocks,segments);
    items.push({key:'change:'+c.id,id:c.id,kind:'change',label:c.reason||'候选修订',segments,available:!reason,...(reason?{reason}:{})});
  }
  for(const item of items)if(items.filter(other=>other.key===item.key).length!==1){item.available=false;item.reason='审阅项身份重复，未猜测定位目标。';}
  return items.sort((a,b)=>{
    const first=(v:ReviewNavigationItem)=>v.segments[0],ai=blocks.findIndex(block=>block.id===(a.caption?.afterBlockId||first(a)?.block_id)),bi=blocks.findIndex(block=>block.id===(b.caption?.afterBlockId||first(b)?.block_id));
    return ai-bi||Number(!!a.caption)-Number(!!b.caption)||(a.caption?.start??first(a)?.start??0)-(b.caption?.start??first(b)?.start??0);
  });
}
export function nextReviewItem(items:ReviewNavigationItem[],activeKey:string|undefined,direction:1|-1):ReviewNavigationItem|null{
  const available=items.filter(item=>item.available),index=available.findIndex(item=>item.key===activeKey);
  return available[index<0?(direction===1?0:available.length-1):index+direction]??null;
}
export function reviewFocusRange(doc:PMNode,item:ReviewNavigationItem):{from:number,to:number}|{reason:string}{
  if(!item.id||!['opinion','change'].includes(item.kind)||item.key!==item.kind+':'+item.id)return {reason:'审阅项身份不一致，未猜测定位目标。'};
  if(!item.available)return {reason:item.reason||'此选区未可靠定位，请明确重新定位。'};
  const error=segmentError(continuousProjection(doc).blocks,item.segments);if(error)return {reason:error};
  const first=item.segments[0],last=item.segments.at(-1)!;
  const from=continuousPosition(doc,first.block_id,first.start,-1),to=continuousPosition(doc,last.block_id,last.end,1);
  if(from===null||to===null)return {reason:'当前文稿没有准确的目标位置。'};
  if(from!==to){
    const actual=continuousSelection(doc,from,to)?.segments;
    if(JSON.stringify(actual)!==JSON.stringify(item.segments))return {reason:'选区位于科学节点内部或跨段边界已变化，请明确重新定位。'};
  }
  return {from,to};
}
