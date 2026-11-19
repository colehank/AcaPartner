import {esc,pretty,diff} from './ui.js';

export const reconciliationSlot=()=>'<div data-graph-reconcile></div>';
export function showGraphComparison(form,before,current,draft){
 const panel=form.querySelector('[data-graph-reconcile]');
 panel.innerHTML=`<div class="notice">当前记录已重读；表单中的草稿保持原样。请比较旧基础、当前记录与准备提交的草稿，明确选择后再提交。</div><details open><summary>原基础与服务器当前记录</summary>${diff(pretty(before),pretty(current))}</details><details open><summary>仍保留的表单草稿</summary><pre>${esc(pretty(draft))}</pre></details><label><input type="checkbox" name="reconcile" value="yes"> 已核对差异，明确按当前版本提交我的表单内容</label>`;
 form.querySelector('button[type=submit]').textContent='确认协调后提交';
}
export function graphSubmission({base,read,request,onSaved,compare=showGraphComparison,conflicted=false}){
 let current=null,needsReview=conflicted;
 return async(v,form)=>{
  if(needsReview&&!current){
   const fresh=await read();if(!form?.isConnected)return false;
   current=fresh;compare(form,base,current,v);return false;
  }
  if(needsReview&&v.reconcile!=='yes')throw new Error('请先比较当前记录与保留草稿，并明确确认协调后提交。');
  const attempt=needsReview?current:base;
  try{const result=await request(attempt,v);await onSaved?.(result,v);return result;}
  catch(error){
   if(error.status===409){needsReview=true;current=null;
    if(form?.isConnected){form.querySelector('[data-graph-reconcile]').innerHTML='<p class="notice">服务器已有新修改。草稿未丢失，请先重读比较；再次点击不会重复发送旧版本。</p>';form.querySelector('button[type=submit]').textContent='保留草稿并重读比较';}
   }
   throw error;
  }
 };
}
export function fillGraphDraft(form,draft){
 for(const [key,value] of Object.entries(draft||{})){
  const input=form.elements.namedItem?.(key)||form.elements[key];if(!input||key==='reconcile')continue;
  if(input.tagName==='SELECT'&&![...input.options].some(option=>option.value===String(value)))input.add(new Option(String(value)+'（冲突草稿值，尚待核对）',String(value)));
  input.value=String(value??'');
 }
}
