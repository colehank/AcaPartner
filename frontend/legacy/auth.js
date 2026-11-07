import {esc} from './ui.js';

async function request(path,body,csrf){
  const response=await fetch(path,{credentials:'same-origin',...(body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json',...(csrf?{'X-CSRF-Token':csrf}:{})},body:JSON.stringify(body)})});
  const value=await response.json();
  if(!response.ok||value.ok===false){const error=new Error(value.error||'无法验证访问身份');error.status=response.status;throw error;}
  return value.result||value;
}
export const accessStatus=()=>request('/api/auth/status');
export const login=token=>request('/api/auth/login',{token});
export const logout=csrf=>request('/api/auth/logout',{},csrf);
export function accessForm(message=''){
  return `<div class="startup"><div class="brand-symbol">r.</div><h1>连接你的研究空间</h1><p>请输入实例所有者提供的访问令牌。令牌不写入浏览器存储。</p><form id="access-form" class="panel"><label class="field"><span>访问令牌</span><input name="token" type="password" required autocomplete="off" spellcheck="false" autofocus aria-label="访问令牌"></label><p id="access-error" role="alert">${esc(message)}</p><button class="button primary" type="submit">连接研究空间</button></form></div>`;
}
