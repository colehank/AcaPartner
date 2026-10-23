/** Shared validation of explicit native Task brief replies. */
const identity=(value:any)=>typeof value==='string'&&value.length>0&&value.length<=200&&!/[\s/\\\u0000-\u001f]/u.test(value);
const sha=(value:any)=>typeof value==='string'&&/^[a-f0-9]{64}$/.test(value);
export type TaskBriefRef={id:string,project_id:string,relative_path:string,content_sha256:string};
export function actualTaskBrief(response:any,projectId:string):TaskBriefRef {
  const note=response?.note,path=note?.relative_path;
  if(response?.executed!==false||!note||note.project_id!==projectId||!identity(note.id)||!sha(note.content_sha256)||
    typeof path!=='string'||!path.startsWith('notes/')||!path.endsWith('.md')||path.split('/').some(p=>!p||p==='.'||p==='..'||p==='.trash'||p==='.notebook')||/[\\\u0000-\u001f]/u.test(path))
    throw new Error('简报返回缺少本项目真实笔记身份；未猜测打开路径。');
  return {id:note.id,project_id:note.project_id,relative_path:path,content_sha256:note.content_sha256};
}
