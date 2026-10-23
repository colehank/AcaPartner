let csrf = '';
export class CommandError extends Error { constructor(public code:string, message:string, public details:any) { super(message); } }
export async function initialize() {
  const response = await fetch('/api/state');
  const data = await response.json();
  if (!response.ok) throw new CommandError(data.code,data.error,data.details);
  csrf = data.csrf;
}
/** Explicit connection refresh; never retries a command or adopts a late scope's token. */
export async function refreshConnection(isCurrent:()=>boolean):Promise<boolean> {
  const response=await fetch('/api/state',{method:'GET',credentials:'same-origin'});
  const data=await response.json();
  if(!isCurrent())return false;
  if(!response.ok)throw new CommandError(data?.code,data?.error||'无法刷新连接',data?.details);
  if(!data||typeof data.csrf!=='string'||!data.csrf)
    throw new CommandError('invalid_response','连接信息不完整；尚未恢复提交。',null);
  csrf=data.csrf;
  return true;
}
export async function command(action:string, fields:Record<string,any>={}) {
  const response = await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify({action,...fields})});
  const data=await response.json();
  if (!response.ok || !data.ok) throw new CommandError(data.code,data.error,data.details);
  return data.result;
}
export async function logout(isCurrent:()=>boolean=()=>true){
  const response=await fetch('/api/auth/logout',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:'{}'});
  const body=await response.json();
  if(!isCurrent())return false;
  if(!response.ok||body.ok!==true||body.result?.session_active!==false)throw new CommandError(body.code,body.error||'退出登录失败；当前草稿已保留。',body.details);
  csrf='';return true;
}
export const requestId = () => crypto.randomUUID();
export async function readTask(id:string){
  const response=await fetch('/api/tasks/'+encodeURIComponent(id)),body=await response.json();
  if(!response.ok||!body.ok)throw new CommandError(body.code,body.error||'任务状态不可读取',body.details);
  if(body.result?.id!==id||typeof body.result?.status!=='string')throw new CommandError('invalid_response','任务状态封装无效',null);
  return body.result;
}
export const noteCommand = (action:string,project_id:string,payload:any) => command(action,{project_id,request_id:requestId(),payload});
