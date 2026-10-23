/** Persist a visual adoption before submitting it. The caller supplies the
 * storage namespace and only the request/draft/selected trail; this module
 * never reads authentication, session state, or global browser storage.
 */
export function createVisualIntentStore({storage,prefix}={}){
 if(typeof prefix!=='string'||!prefix.trim())throw new TypeError('视觉采用意图需要独立的存储前缀。');
 if(!storage||['getItem','setItem','removeItem'].some(method=>typeof storage[method]!=='function'))throw new TypeError('视觉采用意图需要可读写的显式 storage。');
 const activeKey=objectId=>prefix+':visual-intent41:active:'+JSON.stringify(identity(objectId,'成果'));
 const recoveryKey=(objectId,requestKey,reason)=>prefix+':visual-intent41:archive:'+JSON.stringify([objectId,requestKey,reason]);
 const get=key=>access('读取',()=>{
  const raw=storage.getItem(key);
  if(raw!==null&&typeof raw!=='string')throw new TypeError('storage.getItem 必须返回字符串或 null。');
  return raw;
 });
 const put=(key,raw)=>{
  access('保存',()=>storage.setItem(key,raw));
  // Do not authorize a submit or removal if storage silently rejected the copy.
  if(get(key)!==raw)throw failure('VISUAL_INTENT_STORAGE','视觉采用意图未能确认保存；请保留草稿并核对存储状态。');
 };
 const load=objectId=>{
  const key=activeKey(objectId),raw=get(key);
  return {key,raw,record:raw===null?null:parseRecord(raw,objectId)};
 };
 const removeCurrent=({key,raw})=>{
  // Archive performs a storage write first. Recheck so a newer intent created
  // during that work cannot be deleted by the older completion.
  if(get(key)!==raw)return false;
  access('移除',()=>storage.removeItem(key));
  const remaining=get(key);
  if(remaining===raw)throw failure('VISUAL_INTENT_STORAGE','视觉采用意图未能移除；原记录保留，请核对存储状态。');
  return remaining===null;
 };
 return {
  /** Return a fresh snapshot, null for absent, and throw for unreadable bytes. */
  read(objectId){return load(objectId).record;},
  /** Must complete synchronously before any network submission. A retry keeps
   * the first key AND first snapshots. Only top-level request_key is ignored;
   * object key order is irrelevant, while array order remains meaningful.
   */
  begin({objectId,request,draft=null,trail=null}={}){
   identity(objectId,'成果');
   const frozenRequest=jsonSnapshot(request,'采用请求');
   requestIdentity(frozenRequest);
   const current=load(objectId);
   if(current.record){
    if(semanticRequest(current.record.request)===semanticRequest(frozenRequest))return current.record;
    throw failure('VISUAL_INTENT_PENDING','此成果有尚未核对的采用请求；请先核对上次采用，不能覆盖原请求。');
   }
   const record={version:1,objectId,request:frozenRequest,draft:jsonSnapshot(draft,'草稿'),trail:jsonSnapshot(trail,'来源快照'),createdAt:new Date().toISOString()};
   const raw=JSON.stringify(record);
   put(current.key,raw);
   return JSON.parse(raw);
  },
  /** Only a confirmed matching receipt may settle an unresolved intent. */
  settle(objectId,requestKey){
   identity(requestKey,'请求');
   const current=load(objectId);
   if(!current.record||current.record.request.request_key!==requestKey)return false;
   return removeCurrent(current);
  },
  /** Explicit user recovery only: retain the EXACT original bytes separately
   * before removing active. The reason lives in the archive key, so even the
   * archived JSON formatting stays intact. No archive is automatically pruned.
   */
  archive(objectId,requestKey,reason){
   identity(requestKey,'请求');identity(reason,'归档原因');
   const current=load(objectId);
   if(!current.record||current.record.request.request_key!==requestKey)return false;
   const key=recoveryKey(objectId,requestKey,reason),previous=get(key);
   if(previous!==null&&previous!==current.raw)throw failure('VISUAL_INTENT_ARCHIVE_CONFLICT','已有不同的采用恢复记录；当前请求保留，请先核对恢复记录。');
   if(previous===null)put(key,current.raw);
   return removeCurrent(current);
  }
 };
}

function failure(code,message,cause){
 const error=new Error(message);error.code=code;
 if(cause!==undefined)error.cause=cause;
 return error;
}
function access(operation,fn){
 try{return fn();}catch(cause){throw failure('VISUAL_INTENT_STORAGE',`视觉采用意图${operation}失败；请保留草稿并核对上次采用。`,cause);}
}
function identity(value,label){
 if(typeof value!=='string'||!value.trim())throw new TypeError(`${label}标识不能为空。`);
 return value;
}
function requestIdentity(request){
 if(request===null||typeof request!=='object'||Array.isArray(request))throw new TypeError('采用请求必须是 JSON 对象。');
 identity(request.request_key,'请求 request_key');
}
function parseRecord(raw,objectId){
 try{
  const record=JSON.parse(raw);
  if(!record||record.version!==1||record.objectId!==objectId||typeof record.createdAt!=='string'||!Number.isFinite(Date.parse(record.createdAt))||!Object.hasOwn(record,'draft')||!Object.hasOwn(record,'trail'))throw new TypeError('采用意图记录身份或格式不符。');
  requestIdentity(record.request);
  return record;
 }catch(cause){throw failure('VISUAL_INTENT_CORRUPT','已保存的采用意图无法解析；原记录保留，请核对上次采用后恢复。',cause);}
}

// JSON.stringify alone silently drops undefined, functions and symbols, turns
// non-finite numbers into null, and invokes toJSON/getters. Reject lossy JSON
// fields and serialize directly, without invoking hidden toJSON methods.
function jsonSnapshot(value,label){
 const path=new Set();
 function visit(item,depth=0){
  if(item===null||typeof item==='string'||typeof item==='boolean')return;
  if(typeof item==='number'&&Number.isFinite(item))return;
  if(typeof item!=='object'||depth>100)throw new TypeError('仅支持有限深度的 JSON 值。');
  if(path.has(item))throw new TypeError('JSON 值不能循环引用。');
  const array=Array.isArray(item),prototype=Object.getPrototypeOf(item);
  if(!array&&prototype!==Object.prototype&&prototype!==null)throw new TypeError('仅支持普通 JSON 对象。');
  if(Object.getOwnPropertySymbols(item).length)throw new TypeError('JSON 值不能包含 Symbol 字段。');
  const fields=Object.keys(item);
  if(array&&(fields.length!==item.length||fields.some((key,i)=>key!==String(i))))throw new TypeError('JSON 数组不能含空项或附加字段。');
  path.add(item);
  for(const key of fields){
   const descriptor=Object.getOwnPropertyDescriptor(item,key);
   if(!Object.hasOwn(descriptor,'value'))throw new TypeError('JSON 字段不能是访问器。');
   visit(descriptor.value,depth+1);
  }
  path.delete(item);
 }
 try{visit(value);return JSON.parse(canonical(value));}
 catch(cause){throw failure('VISUAL_INTENT_JSON',`${label}不能无损保存为 JSON；未提交采用请求。`,cause);}
}
function canonical(value){
 if(value===null||typeof value!=='object')return JSON.stringify(value);
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}';
}
function semanticRequest(request){
 return '{'+Object.keys(request).filter(key=>key!=='request_key').sort().map(key=>JSON.stringify(key)+':'+canonical(request[key])).join(',')+'}';
}
