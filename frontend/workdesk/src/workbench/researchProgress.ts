import {markdownParser} from '../editors/markdown';
export type Part='Q'|'A'|'E'|'C';
export const parts:Part[]=['Q','A','E','C'];
export const partNames:Record<Part,string>={Q:'问题',A:'分析',E:'证据',C:'结论'};
export type NodeStatus='unmarked'|'not_started'|'active'|'review'|'completed'|'paused'|'stale'|'blocked';
export type NodeDependency={id:string;question_id:string;part:Part;kind:'requires'|'supports'|'limits'|'refutes';builtin:boolean;available:boolean;title:string;status:NodeStatus;signature:string;question_revision:number|null};
export type ResearchNode={id:string;question_id:string;part:Part;title:string;status:NodeStatus;stored_status:NodeStatus;flags:string[];configured:boolean;content_sha256:string;signature:string;dependencies:NodeDependency[];blockers:string[];can_complete:boolean;confirmation:null|{id:string;actor:string;at:string;question_revision:number;note:string;dependencies:{id:string;signature:string}[]}};
export const nodeStatusNames:Record<NodeStatus,string>={unmarked:'未标记',not_started:'待开展',active:'进行中',review:'待确认',completed:'已完成',paused:'暂缓',stale:'待复核',blocked:'受阻'};
export const dependencyNames={requires:'完成依赖',supports:'支持',limits:'限制',refutes:'反驳'};
export type Revision={id:string;part:Part;revision:number;sha256:string;title:string;excerpt:string;empty:boolean;actor:string;created_at:string;change_kind:'created'|'edited'|'restored'|'adopted';origin:null|{available:boolean;task_id?:string;proposal_ref?:any;source_refs?:{id:string;revision:number;title:string}[]}};
export type ProgressQuestion={id:string;title:string;number:string;parent_id:string|null;is_root:boolean;revision:number;sha256:string;status:string;updated_at:string;review_hint:boolean;history_complete:boolean;parts:Record<Part,{node:ResearchNode;empty:boolean;excerpt:string;versions:Revision[];last_changed_revision:number|null;older_versions_available:boolean}>};
export type Progress={version:1;project:{id:string;title:string;revision:number};root_question_id:string|null;description:string;background_excerpt:string;questions:ProgressQuestion[];recent_changes:(Revision&{question_id:string;number:string})[]};
export function nodeLabel(q:ProgressQuestion,p:Part){return p==='Q'?q.number:p+q.number.slice(1);}
export const statusNames:Record<string,string>={open:'待分析',active:'进行中',review:'待核对',answered:'已有回答'};
export function plain(text:string){return markdownParser().parse(text||'',{}).filter(t=>t.type==='inline').flatMap(t=>(t.children||[]).filter(c=>['text','code_inline','image'].includes(c.type)).map(c=>c.content)).join(' ').replace(/\s+/g,' ').trim();}
export function excerpt(text:string,max=100){const value=plain(text);return Array.from(value).slice(0,max).join('')+(Array.from(value).length>max?'…':'');}
export function currentVersion(q:ProgressQuestion,part:Part):Revision{
 const value=q.parts[part],v=value.versions[0];
 return v||{id:q.id+':'+part+':current',part,revision:q.revision,sha256:q.sha256,title:q.title,excerpt:value.excerpt,empty:value.empty,actor:'',created_at:q.updated_at,change_kind:'created',origin:null};
}
