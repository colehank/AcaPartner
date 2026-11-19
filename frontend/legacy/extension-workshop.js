import {esc,button,pretty,assetURL,list,status} from './ui.js';

export function isExtensionWorkshop(object) {
  return object?.kind==='workshop' && (object.content?.category==='extension' || !!object.content?.run?.extension || !!object.metadata?.extension);
}

export function workshopIdentity(object) {
  if(!isExtensionWorkshop(object))return `修订 ${esc(object.revision)}`;
  const run=object.content?.run||{};
  return `扩展 ${esc(run.version||'版本未记录')} · ${esc(run.operation||'操作未记录')}<br>${esc(object.id)} · 修订 ${esc(object.revision)}`;
}

export function extensionExecutionLabel(object) {
  const run=object?.content?.run||{};
  if(run.failure)return '执行失败';
  if(Number.isInteger(run.returncode))return `进程退出码 ${run.returncode}`;
  return '执行返回未记录';
}

export function extensionWorkshopPanel(object,extensions=[]) {
  const content=object.content||{},run=content.run||{},metadata=object.metadata||{};
  const ident=run.extension||metadata.extension||'',manifest=run.manifest_sha256||metadata.manifest_sha256||'';
  const current=extensions.find(e=>e.id===ident);
  const permissions=Array.isArray(run.permissions)?run.permissions:null;
  const labels={execute_code:'执行本机代码',read_inputs:'读取登记输入',write_outputs:'写入登记输出'};
  const inputs=list(content.inputs);
  const detail=(label,value)=>`<p><strong>${label}</strong><br><span>${esc(value??'未记录')}</span></p>`;
  return `<div data-extension-workshop="${esc(object.id)}"><div class="section-heading"><h2>扩展产物与执行来源</h2></div>
    <p class="hint">此处记录生成当前产物时的扩展与输入。再次调用请进入工具设置，核对当前版本与授权，并重新指定输入。</p>
    ${detail('产物身份',`${object.id} · 修订 ${object.revision}`)}
    ${detail('扩展',ident||'未记录')}${detail('本次执行版本',run.version||'未记录')}${detail('本次操作',run.operation||'未记录')}
    ${detail('执行记录',run.invocation_id||metadata.invocation||'未记录')}${detail('执行返回',extensionExecutionLabel(object))}
    ${run.failure?detail('失败记录',typeof run.failure==='string'?run.failure:pretty(run.failure)):''}
    ${detail('当次清单 SHA256',manifest||'未记录')}
    <h3>当次执行权限</h3><p>${permissions===null?'未记录':permissions.length?permissions.map(x=>esc(labels[x]||x)).join(' · '):'记录为空'}</p>
    <p class="hint">来自这次执行回执的权限集合；不代表当前版本仍有授权。技术验收与科学批准另行确认。</p>
    <h3>登记输入</h3>${inputs.length?inputs.map(x=>{const ref=typeof x==='string'?{sha:x}:x;const hash=ref.sha||ref.sha256||'',url=/^[a-f0-9]{64}$/.test(hash)?assetURL(hash):'';return `<article class="output-item"><strong>${esc(ref.filename||ref.alias||'登记输入')}</strong><p class="hint">${esc(hash||'SHA256 未记录')}</p>${url?`<a class="button small" href="${esc(url)}" target="_blank" rel="noopener">查看登记输入</a>`:''}</article>`;}).join(''):'<p class="hint">没有登记输入。</p>'}
    <h3>当前工具状态</h3>${current?`<p>${esc(current.name||ident)} · ${esc(current.version)} ${status(current.status)} ${status(current.authorized?'authorized':'unauthorized')}</p>${current.manifest_sha256!==manifest?'<p class="notice warning">当前登记清单与生成此产物的清单不同。</p>':''}${button('查看此扩展与当前权限','extension-settings',{id:ident},'button small')}`:`<p class="hint">当前工作空间没有此扩展的登记记录；历史执行来源仍保留。</p>${button('查看扩展设置','navigate',{view:'settings'},'button small')}`}
  </div>`;
}
