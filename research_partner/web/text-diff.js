import {esc} from './ui.js';

const tokens=text=>String(text??'').match(/[\p{Script=Han}]|[\p{L}\p{N}_]+|\s+|[^\s]/gu)||[];
export function completeTextDiff(before,after){
 const a=tokens(before),b=tokens(after);let prefix=0,suffix=0;
 while(prefix<a.length&&prefix<b.length&&a[prefix]===b[prefix])prefix++;
 while(suffix<a.length-prefix&&suffix<b.length-prefix&&a.at(-1-suffix)===b.at(-1-suffix))suffix++;
 const x=a.slice(prefix,a.length-suffix),y=b.slice(prefix,b.length-suffix),chunks=[];
 const push=(kind,text)=>{if(!text)return;const last=chunks.at(-1);if(last?.kind===kind)last.text+=text;else chunks.push({kind,text});};
 push('equal',a.slice(0,prefix).join(''));
 // Linear memory LCS, with a bounded matrix for ordinary paragraph edits.
 // The large replacement fallback still retains every character of both sides.
 if(x.length*y.length<=1200000){
  const rows=Array.from({length:x.length+1},()=>new Uint32Array(y.length+1));
  for(let i=x.length-1;i>=0;i--)for(let j=y.length-1;j>=0;j--)rows[i][j]=x[i]===y[j]?rows[i+1][j+1]+1:Math.max(rows[i+1][j],rows[i][j+1]);
  let i=0,j=0;while(i<x.length||j<y.length){if(i<x.length&&j<y.length&&x[i]===y[j]){push('equal',x[i]);i++;j++;}else if(i<x.length&&(j===y.length||rows[i+1][j]>=rows[i][j+1]))push('delete',x[i++]);else push('insert',y[j++]);}
 }else{push('delete',x.join(''));push('insert',y.join(''));}
 push('equal',suffix?a.slice(-suffix).join(''):'');return chunks;
}
export function inlineTextDiff(before,after,segments=null){
 const chunks=segments||completeTextDiff(before,after);
 return chunks.map(x=>x.kind==='delete'?`<del>${esc(x.text)}</del>`:x.kind==='insert'?`<ins>${esc(x.text)}</ins>`:esc(x.text)).join('');
}
