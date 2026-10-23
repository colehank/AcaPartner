import type {ContinuousSelection,ManuscriptMark} from './ContinuousManuscriptModel';
import {reviewAuthorLabel} from './ReviewAuthorIdentity';

type Segment={block_id:string,start:number,end:number,quote:string};
export type PaperReviewAnchor=Segment|{kind:'manuscript_range',offset_unit:'unicode_codepoint',block_id:string,segments:Segment[],quote:string};
export function reviewAnchor(selection:ContinuousSelection|null):PaperReviewAnchor|undefined{
  if(!selection||!selection.segments.length)return undefined;
  const segments=selection.segments.map(({block_id,start,end,quote})=>({block_id,start,end,quote}));
  if(segments.length===1)return segments[0];
  return {kind:'manuscript_range',offset_unit:'unicode_codepoint',block_id:segments[0].block_id,segments,quote:segments.map(s=>s.quote).join('\n\n')};
}

// All projections are read-only decorations over current saved source. Never
// use a candidate's base blocks as current source or silently apply conflicts.
export function paperReviewMarks(blocks:any[],review:any,edits:any,view:any,showChanges:boolean):ManuscriptMark[]{
  const marks:ManuscriptMark[]=[];
  for(const opinion of review?.opinions||[]){
    const annotation=review.annotations?.find((a:any)=>a.id===opinion.id);
    if(opinion.deleted||annotation?.status!=='anchored'||opinion.field==='caption')continue;
    const segments=opinion.anchor.segments||[opinion.anchor];
    for(const segment of segments){
      const block=blocks.find(b=>b.id===segment.block_id);if(!block)continue;
      const start=segment.start??0,end=segment.end??Array.from(block.text).length;
      marks.push({id:opinion.id,block_id:block.id,start,end,quote:segment.quote,kind:'opinion',label:reviewAuthorLabel(opinion.created_by)});
    }
  }
  if(!showChanges)return marks;
  const own=(edits?.changes||[]).map((row:any)=>({...row,author:reviewAuthorLabel(edits?.proposer?.actor)}));
  const agent=(view?.proposal?.changes||[]).filter((row:any)=>row.target?.field!=='caption').map((row:any)=>({...row,block_id:row.target.block_id,author:reviewAuthorLabel(view.proposal.proposer?.session_id,{kind:'agent',route:view.proposal.proposer?.route})}));
  for(const change of [...own,...agent]){
    if(change.state!=='pending'||change.conflict)continue;
    const block=blocks.find(b=>b.id===change.block_id);
    if(!block)continue;
    if(change.op==='insert'&&block.text===change.after){marks.push({id:change.id,block_id:block.id,start:0,end:Array.from(block.text).length,quote:block.text,kind:'insert',label:change.author,text:'新增段落'});continue;}
    if(block.text!==change.before)continue;
    // Exact common prefix/suffix avoids striking an entire paragraph for a
    // small replacement while preserving Unicode source offsets.
    const before=Array.from(change.before as string),after=Array.from(change.after as string);let left=0,right=0;
    while(left<before.length&&left<after.length&&before[left]===after[left])left++;
    while(right<before.length-left&&right<after.length-left&&before[before.length-1-right]===after[after.length-1-right])right++;
    const end=before.length-right,insert=after.slice(left,after.length-right).join('');
    marks.push({id:change.id,block_id:block.id,start:left,end,quote:before.slice(left,end).join(''),kind:end===left?'insert':insert?'replace':'delete',label:change.author,text:insert||'删除此选区'});
  }
  return marks;
}
