export type ReviewAuthorContext={kind?:'agent',route?:unknown};
export type ReviewAuthorDisplay={label:string,kind:'operator'|'agent'|'unknown',identity:string|null,route:string|null};

// Display-only identifier, never a principal, permission, or login proof.
// Keep the full 16 hexadecimal digits so equal short prefixes stay distinct.
function displayIdentifier(identity:string):string{
  let value=0xcbf29ce484222325n;
  for(const byte of new TextEncoder().encode(identity))value=BigInt.asUintN(64,(value^BigInt(byte))*0x100000001b3n);
  return value.toString(16).padStart(16,'0');
}
function routeLabel(route:string|null):string{
  return route==='codex'?'Codex':route==='deepseek_harness'?'DeepSeek Harness':route||'路线未记录';
}
export function reviewAuthorDisplay(value:unknown,context:ReviewAuthorContext={}):ReviewAuthorDisplay{
  const identity=typeof value==='string'&&value.trim()?value:null;
  const route=typeof context.route==='string'&&context.route.trim()?context.route:null;
  // Agent classification is supplied only by the saved proposal's proposer
  // context; a credential fingerprint alone does not prove a human identity.
  if(context.kind==='agent')return {kind:'agent',identity,route,label:`Agent · ${routeLabel(route)}${identity?' · '+displayIdentifier(identity):' · 身份未记录'}`};
  if(!identity)return {kind:'unknown',identity:null,route:null,label:'作者未记录'};
  const credential=/^(?:operator|user):credential:([a-f0-9]{16,64})$/.exec(identity);
  if(credential)return {kind:'operator',identity,route:null,label:'操作者 · '+credential[1]};
  if(identity==='operator:local_operator'||identity==='user:local_operator')return {kind:'operator',identity,route:null,label:'本地操作者'};
  if(identity==='operator:loopback'||identity==='user:loopback')return {kind:'operator',identity,route:null,label:'操作者 · 本机连接'};
  return {kind:'unknown',identity,route:null,label:'未核对作者 · '+displayIdentifier(identity)};
}
export function reviewAuthorLabel(value:unknown,context:ReviewAuthorContext={}):string{
  return reviewAuthorDisplay(value,context).label;
}
