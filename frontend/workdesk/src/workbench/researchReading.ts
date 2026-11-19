import type {ViewSpec} from './context';
export function questionLabel(q:{title:string;number?:string}){return q.number?q.number+' '+q.title:q.title;}
/** Same Unicode-safe first-paragraph rule as the approved prototype. */
export function researchExcerpt(value:string){const full=String(value||'').trim(),paragraph=full.split(/\n\s*\n/)[0]||'',chars=Array.from(paragraph),excerpt=chars.slice(0,120).join('').trim();return {text:excerpt+(chars.length>120?'…':''),more:excerpt!==full};}
export function sourceView(ref:{id:string;revision:number;consumer_id?:string},consumer:string,title='来源内容'):ViewSpec{const effective=ref.consumer_id||consumer;return {id:'source:'+encodeURIComponent(ref.id)+':r'+ref.revision+':'+encodeURIComponent(effective),kind:'object',title:title+' · r'+ref.revision,value:ref.id,data:{...ref,consumer_id:effective}};}
