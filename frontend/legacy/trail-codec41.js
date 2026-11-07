/** Lossless, synchronous JSON recovery storage. No history is dropped.
 *
 * Wire format: [tag, version, [ordinaryJSON, undo, redo, recovery]]. Ordinary
 * JSON keeps placeholders at compressed fields, preserving key order and
 * arbitrary field names. Each history is [firstDraftJSON|null, deltas], where
 * a delta is [prefix UTF-16 units, suffix UTF-16 units, inserted string] against
 * the preceding JSON string. Slices may cross surrogate pairs; joining them
 * before JSON.parse restores exactly the original units, including lone ones.
 *
 * Limits reject, never truncate. A caller must retain the original stored bytes
 * on any error. Bounds apply across both histories and nested recovery records.
 */
const TAG='rp.trail41.delta-json',VERSION=1;
const MAX_DEPTH=96,MAX_NODES=250000,MAX_ARRAY=100000;
const MAX_STRING=8*1024*1024,MAX_TOTAL_CHARS=64*1024*1024,MAX_HISTORY=4096;
const own=(value,key)=>Object.hasOwn(value,key);
const object=value=>value!==null&&typeof value==='object'&&!Array.isArray(value);
const context=()=>({nodes:0,chars:0,historyChars:0,historyEntries:0});
function fail(message,limit=false){
 const error=new TypeError(`返回路径恢复记录${message}；请保留原记录。`);
 error.code=limit?'TRAIL_CODEC41_LIMIT':'TRAIL_CODEC41_INVALID';throw error;
}
function requireShape(condition,message){if(!condition)fail(message);}
function bounded(condition,message){if(!condition)fail(message,true);}
function field(target,key,value){Object.defineProperty(target,key,{value,enumerable:true,writable:true,configurable:true});}
function chars(budget,length){
 bounded(length<=MAX_STRING,'单项文本过长');budget.chars+=length;
 bounded(budget.chars<=MAX_TOTAL_CHARS,'文本总量超限');
}

// Validate before JSON serialization. JSON.stringify alone invokes getters /
// toJSON and silently loses sparse entries, unsupported values and extra keys.
function copyJSON(value,budget,depth=0,path=new Set()){
 bounded(depth<=MAX_DEPTH,'嵌套过深');bounded(++budget.nodes<=MAX_NODES,'节点总量超限');
 if(value===null||typeof value==='boolean')return value;
 if(typeof value==='string'){chars(budget,value.length);return value;}
 if(typeof value==='number'){requireShape(Number.isFinite(value),'包含非有限数字');return value;}
 requireShape(typeof value==='object','包含非 JSON 值');
 requireShape(!path.has(value),'包含循环引用');
 const array=Array.isArray(value),prototype=Object.getPrototypeOf(value);
 requireShape(array||prototype===Object.prototype||prototype===null,'包含非普通 JSON 对象');
 const keys=Reflect.ownKeys(value);
 requireShape(keys.every(key=>typeof key==='string'),'包含 Symbol 字段');
 if(array){
  bounded(value.length<=MAX_ARRAY,'数组长度超限');
  requireShape(keys.length===value.length+1&&keys.at(-1)==='length'&&keys.slice(0,-1).every((key,index)=>key===String(index)),'数组包含空项或附加字段');
 }
 const result=array?[]:{};path.add(value);
 for(const key of keys){
  if(array&&key==='length')continue;
  chars(budget,key.length);
  const descriptor=Object.getOwnPropertyDescriptor(value,key);
  requireShape(descriptor?.enumerable&&own(descriptor,'value'),'包含访问器或不可枚举字段');
  field(result,key,copyJSON(descriptor.value,budget,depth+1,path));
 }
 path.delete(value);return result;
}

// An explicit serializer preserves -0 and never consults a toJSON property.
// Packed JSON stores all such numbers inside strings, so JSON.stringify /
// JSON.parse of the outer envelope also preserves them without special markers.
function stringify(value){
 const parts=[];let length=0;
 const add=text=>{length+=text.length;bounded(length<=MAX_STRING,'单项 JSON 过长');parts.push(text);};
 function emit(item){
  if(item===null||typeof item!=='object'){
   add(typeof item==='number'&&Object.is(item,-0)?'-0':JSON.stringify(item));return;
  }
  if(Array.isArray(item)){
   add('[');item.forEach((entry,index)=>{if(index)add(',');emit(entry);});add(']');return;
  }
  add('{');Object.keys(item).forEach((key,index)=>{if(index)add(',');add(JSON.stringify(key));add(':');emit(item[key]);});add('}');
 }
 emit(value);return parts.join('');
}
function parse(text,budget){
 requireShape(typeof text==='string','JSON 文本类型无效');bounded(text.length<=MAX_STRING,'单项 JSON 过长');
 let value;
 try{value=JSON.parse(text);}catch{fail('JSON 文本损坏');}
 const result=copyJSON(value,budget);
 // v1 emits this exact JSON form. Reject duplicate keys and alternative lossy
 // parses instead of silently changing a corrupted stored record.
 requireShape(stringify(result)===text,'JSON 文本不符合当前编码');return result;
}
function historyLength(budget,length){
 bounded(length<=MAX_STRING,'历史快照过长');budget.historyChars+=length;
 bounded(budget.historyChars<=MAX_TOTAL_CHARS,'历史展开总量超限');
}
function historyEntry(budget){bounded(++budget.historyEntries<=MAX_HISTORY,'历史条目总量超限');}
function snapshot(value){requireShape(object(value),'历史条目不是 draft 对象');}
function delta(previous,current){
 const limit=Math.min(previous.length,current.length);let prefix=0,suffix=0;
 while(prefix<limit&&previous.charCodeAt(prefix)===current.charCodeAt(prefix))prefix++;
 while(suffix<limit-prefix&&previous.charCodeAt(previous.length-1-suffix)===current.charCodeAt(current.length-1-suffix))suffix++;
 return [prefix,suffix,current.slice(prefix,current.length-suffix)];
}
function packHistory(history,budget){
 requireShape(Array.isArray(history),'undo/redo 不是数组');
 let first=null,previous=null;const deltas=[];
 for(const draft of history){
  historyEntry(budget);snapshot(draft);const current=stringify(draft);historyLength(budget,current.length);
  if(previous===null)first=current;else deltas.push(delta(previous,current));
  previous=current;
 }
 return [first,deltas];
}
function packRecord(record,budget,depth=0){
 bounded(depth<=MAX_DEPTH,'恢复记录嵌套过深');requireShape(object(record),'不是 trail/historyRecovery 对象');
 const plain={},histories=[null,null];let recovery=null;
 for(const key of Object.keys(record)){
  if(key==='undo'||key==='redo'){
   histories[key==='undo'?0:1]=packHistory(record[key],budget);field(plain,key,null);
  }else if(key==='historyRecovery'&&record[key]!==null){
   recovery=packRecord(record[key],budget,depth+1);field(plain,key,false);
  }else field(plain,key,record[key]);
 }
 return [stringify(plain),histories[0],histories[1],recovery];
}
function unpackHistory(packed,budget){
 requireShape(Array.isArray(packed)&&packed.length===2,'历史编码结构无效');
 const [first,deltas]=packed;requireShape(Array.isArray(deltas),'历史差分不是数组');
 if(first===null){requireShape(deltas.length===0,'空历史带有差分');return [];}
 requireShape(typeof first==='string','历史基准不是 JSON 文本');
 bounded(deltas.length<MAX_HISTORY,'历史条目总量超限');
 const result=[];
 function accept(text){historyEntry(budget);const draft=parse(text,budget);snapshot(draft);result.push(draft);}
 historyLength(budget,first.length);accept(first);let previous=first;
 for(const change of deltas){
  requireShape(Array.isArray(change)&&change.length===3,'历史差分结构无效');
  const [prefix,suffix,insert]=change;
  requireShape(Number.isSafeInteger(prefix)&&prefix>=0&&Number.isSafeInteger(suffix)&&suffix>=0&&typeof insert==='string','历史差分类型或范围无效');
  requireShape(prefix<=previous.length&&suffix<=previous.length-prefix,'历史差分越界或重叠');
  const length=prefix+suffix+insert.length;historyLength(budget,length);
  // All expansion limits are checked before any slice/concatenation allocation.
  const current=previous.slice(0,prefix)+insert+previous.slice(previous.length-suffix);
  accept(current);previous=current;
 }
 return result;
}
function unpackRecord(packed,budget,depth=0){
 bounded(depth<=MAX_DEPTH,'恢复记录嵌套过深');
 requireShape(Array.isArray(packed)&&packed.length===4,'恢复记录结构无效');
 const [plainJSON,undo,redo,recovery]=packed,record=parse(plainJSON,budget);
 requireShape(object(record),'普通字段不是对象');
 for(const [key,encoded] of [['undo',undo],['redo',redo]]){
  if(!own(record,key))requireShape(encoded===null,'历史没有对应字段');
  else {requireShape(record[key]===null&&encoded!==null,'历史占位或编码缺失');field(record,key,unpackHistory(encoded,budget));}
 }
 if(recovery!==null){
  requireShape(own(record,'historyRecovery')&&record.historyRecovery===false,'恢复字段占位缺失');
  field(record,'historyRecovery',unpackRecord(recovery,budget,depth+1));
 }else if(own(record,'historyRecovery'))requireShape(record.historyRecovery===null,'恢复字段编码缺失');
 return record;
}
function validateLegacy(record,budget,depth=0){
 bounded(depth<=MAX_DEPTH,'恢复记录嵌套过深');requireShape(object(record),'不是 trail/historyRecovery 对象');
 for(const key of ['undo','redo'])if(own(record,key)){
  requireShape(Array.isArray(record[key]),'undo/redo 不是数组');
  for(const draft of record[key]){historyEntry(budget);snapshot(draft);}
 }
 if(own(record,'historyRecovery')&&record.historyRecovery!==null)validateLegacy(record.historyRecovery,budget,depth+1);
}

export function packTrail41(trail){
 if(trail===null)return null;
 const budget=context(),record=copyJSON(trail,budget);return [TAG,VERSION,packRecord(record,budget)];
}
export function unpackTrail41(packed){
 if(packed===null)return null;
 const record=copyJSON(packed,context()),budget=context();
 if(!Array.isArray(record)){validateLegacy(record,budget);return record;}
 requireShape(record.length===3&&record[0]===TAG&&record[1]===VERSION,'编码标记或版本无效');
 return unpackRecord(record[2],budget);
}
