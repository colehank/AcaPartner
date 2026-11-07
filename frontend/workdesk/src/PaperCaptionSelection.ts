import {captionComponentIdentity} from './PaperFigureIdentity';

export type CaptionTextSelection={key:string,componentIdentity:string,componentId:string,caption:string,start:number,end:number,quote:string};
export type CaptionComposerAnchor=CaptionTextSelection&{field:'caption',component_id:string,projectId:string,paperId:string,block_id?:never};
export const isCaptionComposerAnchor=(value:any):value is CaptionComposerAnchor=>value?.field==='caption';

// Selection is measured from native text inside this one saved occurrence.
// The resulting codepoints refer to its source caption, never widget HTML.
export function captionTextRange(element:HTMLElement,caption:string):{start:number,end:number,quote:string}|null{
  const selection=element.ownerDocument.getSelection();
  if(!selection||selection.rangeCount!==1||selection.isCollapsed||!element.contains(selection.anchorNode)||!element.contains(selection.focusNode)||element.textContent!==caption)return null;
  const range=selection.getRangeAt(0),prefix=element.ownerDocument.createRange();
  prefix.selectNodeContents(element);prefix.setEnd(range.startContainer,range.startOffset);
  const before=prefix.toString(),quote=range.toString(),start=Array.from(before).length,end=start+Array.from(quote).length,points=Array.from(caption);
  if(!quote||points.slice(0,start).join('')!==before||points.slice(start,end).join('')!==quote)return null;
  return {start,end,quote};
}

export function captionComposerError(anchor:CaptionComposerAnchor,projectId:string,paper:any):string|undefined{
  if(typeof anchor.caption!=='string'||typeof anchor.quote!=='string'||typeof anchor.componentIdentity!=='string'||typeof anchor.component_id!=='string'||!anchor.component_id)return '图注选区身份不完整；意见草稿保留，请重新选择。';
  if(anchor.projectId!==projectId||anchor.paperId!==paper?.id)return '选区来自另一份稿件；意见草稿保留，请重新选择。';
  const components=paper?.content?.components||[],matches=components.map((component:any,index:number)=>({component,index})).filter(({component}:any)=>(component.id||component.object_id)===anchor.component_id);
  if(matches.length!==1)return '稿内图位置缺失或不唯一；意见草稿保留，请明确重新选择。';
  const {component,index}=matches[0];
  if(anchor.componentId!==anchor.component_id||anchor.key!==paper.id+':'+index||captionComponentIdentity(component)!==anchor.componentIdentity||component.caption!==anchor.caption)return '图注或固定来源已改变；意见草稿保留，请重新选择保存版。';
  const points=Array.from(anchor.caption);
  if(!Number.isSafeInteger(anchor.start)||!Number.isSafeInteger(anchor.end)||anchor.start<0||anchor.end<=anchor.start||anchor.end>points.length||points.slice(anchor.start,anchor.end).join('')!==anchor.quote)return '图注选区不完整；意见草稿保留，请重新选择。';
}

export function captionWireAnchor(anchor:CaptionComposerAnchor){
  return {field:'caption',component_id:anchor.component_id,start:anchor.start,end:anchor.end,quote:anchor.quote};
}
