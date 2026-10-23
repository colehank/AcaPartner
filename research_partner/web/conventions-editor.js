import {esc,pretty,modal,field,select,diff} from './ui.js';

// Each scope keeps its own text and server version. A scope switch is never a
// conversion of a project body into a complete workspace settings document.
export async function editConventions({key,projectId='',action,refresh}){
 const scopes=projectId?[['project','当前项目'],['workspace','整个研究空间']]:[['workspace','整个研究空间']];
 const records=new Map();let scope=scopes[0][0],busy=false,sequence=0;
 const request=s=>({key,scope:s,...(s==='project'?{project_id:projectId}:{})});
 // Claim a modal before the first network wait. A closed/replaced loading
 // instance must never acquire a later editor's modal or erase its draft.
 const loading=modal(key==='domain'?'编辑领域约定':'编辑研究偏好','<p role="status">正在读取当前约定…</p>');
 let first;
 try{first=await action('settings.layer_preview',request(scope),{notifyError:false});}
 catch(error){if(loading.active())loading.form.querySelector('.form-error').textContent=error.message;return loading;}
 if(!loading.active())return loading;
 records.set(scope,{view:first,text:pretty(first.value),remote:null});
 const dialog=modal(key==='domain'?'编辑领域约定':'编辑研究偏好',
  `${select('应用范围','scope',scopes,scope)}${field('这一层的约定（JSON）','value',pretty(first.value),'textarea','required rows="12"')}<div data-setting-inherited></div><p class="hint">只更新当前这一层；其他项目保持原值。未设置项沿用默认值。已有任务保留创建时的约定，设置不能增加权限或额度。</p><button type="button" class="button small" data-setting-reload>重读服务器并比较</button><div data-setting-comparison></div>`,
  {wide:true,label:'保存这一层',submit:async(v)=>{
   if(busy)return false;
   const record=records.get(scope);record.text=v.value;
   let value;try{value=JSON.parse(record.text);}catch{throw Error('请输入有效的 JSON 对象；草稿仍保留。');}
   if(!value||Array.isArray(value)||typeof value!=='object')throw Error('这一层需要 JSON 对象；草稿仍保留。');
   lock(true);
   try{
    const saved=await action('settings.layer_update',{...request(scope),value,expected_sha256:record.view.expected_sha256},{notifyError:false});
    record.view=saved;record.remote=null;
    await refresh();
   }catch(error){
    if(dialog.active()&&error.status===409&&error.details?.current){record.remote=error.details.current;renderComparison();throw new Error(error.message);}
    throw error;
   }finally{lock(false);}
  }});
 const area=dialog.form.querySelector('[name=value]'),chooser=dialog.form.querySelector('[name=scope]');
 function lock(value){busy=value;if(dialog.active())for(const element of dialog.form.querySelectorAll('input,textarea,select,button:not([data-close])'))element.disabled=value;}
 function renderInherited(){
  const inherited=records.get(scope).view.inherited;
  dialog.root.querySelector('[data-setting-inherited]').innerHTML=`<details><summary>未设置项沿用的默认值（只读）</summary><pre>${esc(pretty(inherited))}</pre></details>`;
 }
 function renderComparison(){
  if(!dialog.active())return;
  const record=records.get(scope),remote=record.remote,box=dialog.root.querySelector('[data-setting-comparison]');
  box.innerHTML=remote?`<p class="notice">服务器当前值与本地草稿分开保留。下面选择只更新比较基准，仍需点击“保存这一层”才会提交。</p>${diff(pretty(remote.value),record.text)}<div class="button-group"><button type="button" class="button" data-setting-use-current>采用服务器这一层</button><button type="button" class="button" data-setting-keep-draft>保留草稿，按当前版本保存</button></div>`:record.backup!==undefined?'<button type="button" class="button small" data-setting-restore-draft>取回比较前的草稿</button>':'';
  box.querySelector('[data-setting-use-current]')?.addEventListener('click',()=>{record.backup=record.text;record.text=pretty(remote.value);record.view=remote;record.remote=null;area.value=record.text;renderInherited();renderComparison();});
  box.querySelector('[data-setting-keep-draft]')?.addEventListener('click',()=>{record.view=remote;record.remote=null;renderInherited();renderComparison();});
  box.querySelector('[data-setting-restore-draft]')?.addEventListener('click',()=>{record.text=record.backup;delete record.backup;area.value=record.text;renderComparison();});
 }
 area.addEventListener('input',()=>{records.get(scope).text=area.value;});
 chooser.addEventListener('change',async()=>{
  const prior=scope,next=chooser.value,token=++sequence;records.get(prior).text=area.value;lock(true);
  try{
   if(!records.has(next)){const view=await action('settings.layer_preview',request(next),{notifyError:false});if(!dialog.active()||token!==sequence)return;records.set(next,{view,text:pretty(view.value),remote:null});}
   if(!dialog.active()||token!==sequence)return;
   scope=next;area.value=records.get(scope).text;dialog.form.querySelector('.form-error')?.replaceChildren();renderInherited();renderComparison();
  }catch(error){if(dialog.active()){chooser.value=prior;dialog.form.querySelector('.form-error').textContent=error.message;}}
  finally{if(token===sequence)lock(false);}
 });
 dialog.root.querySelector('[data-setting-reload]').addEventListener('click',async()=>{
  if(busy)return;const record=records.get(scope);record.text=area.value;lock(true);
  try{const remote=await action('settings.layer_preview',request(scope),{notifyError:false});if(dialog.active()){record.remote=remote;renderComparison();}}
  catch(error){if(dialog.active())dialog.form.querySelector('.form-error').textContent=error.message;}
  finally{lock(false);}
 });
 renderInherited();return dialog;
}
