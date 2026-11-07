export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const attr = esc;
export const clone = value => JSON.parse(JSON.stringify(value));
export const uid = prefix => `${prefix}-${crypto.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2, 8)}`;
export const kinds = {project:'研究项目',concept:'核心概念',question:'研究问题',report:'研究报告',note:'研讨笔记',figure:'科研图',diagram:'概念 / 流程图',paper:'论文',poster:'海报',slides:'幻灯片与讲稿',workshop:'工坊产物',workshop_note:'章节工坊笔记',literature:'文献',growth:'成长候选',feedback:'意见与反馈'};
export const statusNames = {queued:'排队中',running:'执行中',waiting:'等待条件',answered:'已回答',denied:'已拒绝',deferred:'已暂缓',blocked:'受阻',paused:'已暂停',cancelled:'已取消',canceled:'已取消',completed:'已完成',succeeded:'已完成',failed:'失败',pending:'待处理',accepted:'已接纳',resolved:'已处理',rejected:'未采用',proposed:'待比较',adopted:'已采用',reverted:'已回退',unverified:'未验证',unavailable:'不可用',available:'可用',withdrawn:'已撤回',generated:'候选已生成 · 待审查',review:'审查中',deliverable:'已形成交付',waiting_input:'等待输入',waiting_resource:'等待资源',waiting_authorization:'等待授权',anchored:'定位有效',orphaned:'锚点已移除',text_changed:'原文已变化',candidate:'候选待比较',adopt:'已采用',revert:'已回退',reject:'未采用',installed:'已安装',uninstalled:'已卸载',authorized:'已授权当前版本',unauthorized:'当前版本未授权'};
export const status = value => `<span class="status status-${esc(value || 'unknown')}">${esc(statusNames[value] || value || '未记录')}</span>`;
export const date = value => value ? new Date(value).toLocaleString('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '未记录时间';
export const button = (label, action, data={}, cls='button') => `<button class="${cls}" type="button" data-action="${esc(action)}" ${Object.entries(data).map(([k,v])=>`data-${k}="${esc(v)}"`).join(' ')}>${esc(label)}</button>`;
export const empty = (title, body, action='') => `<div class="empty"><div class="empty-mark">◇</div><h2>${esc(title)}</h2><p>${esc(body)}</p>${action}</div>`;
export const list = value => Array.isArray(value) ? value : value && typeof value === 'object' ? Object.values(value) : [];
export const pretty = value => JSON.stringify(value ?? {}, null, 2);
export const objectSearchText = o => [o.title,o.id,o.metadata?.category,...(Array.isArray(o.metadata?.aliases)?o.metadata.aliases:[])].filter(Boolean).join(' ').toLowerCase();
export const errorMessage = error => `${error.message || error}${error.details ? '\n' + (typeof error.details === 'string' ? error.details : pretty(error.details)) : ''}`;
export function safeURL(value) { if (!value) return ''; try { const u = new URL(value, location.origin); return ['http:','https:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } }
export function assetURL(value) { if (!value) return ''; if (typeof value === 'object') return assetURL(value.url || value.sha || value.sha256 || value.asset_id || value.path); if (/^[a-f0-9]{64}$/.test(value)) return `/api/assets/${value}`; if (String(value).startsWith('/api/assets/')) return value; return safeURL(value); }
export function markdown(text) {
  return esc(text).split('\n').map(line => line.replace(/^(#{1,4})\s+(.*)$/, (_,h,t)=>`<h${h.length+1}>${t}</h${h.length+1}>`).replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>').replace(/`([^`]+)`/g,'<code>$1</code>')).join('<br>');
}
export function toast(message, type='info') { const el=document.createElement('div');el.className=`toast ${type}`;el.textContent=message;document.querySelector('#toast-root').append(el);setTimeout(()=>el.remove(),type==='error'?11000:5000); }
const modalInstances=new WeakMap();
export function modal(title, body, {submit, label='保存', wide=false}={}) {
  const root=document.querySelector('#modal-root');modalInstances.get(root)?.dispose();const token=Symbol('modal');root.innerHTML=`<div class="modal-shade"><section class="modal ${wide?'wide':''}" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><header><h2 id="dialog-title">${esc(title)}</h2><button type="button" class="icon-button" data-close aria-label="关闭">×</button></header><form><div class="modal-body">${body}</div><p class="form-error" role="alert"></p><footer><button type="button" class="button" data-close>关闭</button>${submit?`<button type="submit" class="button primary">${esc(label)}</button>`:''}</footer></form></section></div>`;
  const form=root.querySelector('form'),errorNode=root.querySelector('.form-error');
  const active=()=>modalInstances.get(root)?.token===token&&root.querySelector('form')===form;
  const dispose=()=>document.removeEventListener('keydown',escape);
  const close=()=>{dispose();if(!active())return;modalInstances.delete(root);root.innerHTML='';};
  const escape=e=>{if(e.key==='Escape')close();};
  modalInstances.set(root,{token,dispose});document.addEventListener('keydown',escape);
  root.querySelectorAll('[data-close]').forEach(el=>el.addEventListener('click',close));
  form.addEventListener('submit',async e=>{e.preventDefault();if(!submit||!active())return;const btn=e.submitter;if(btn)btn.disabled=true;try { const result=await submit(Object.fromEntries(new FormData(e.target)),e.target);if(result!==false&&active())close(); } catch(error) {if(active())errorNode.textContent=errorMessage(error);} finally {if(btn)btn.disabled=false;}});
  setTimeout(()=>{if(active())root.querySelector('input,textarea,select,button')?.focus();},0);return {root,close,active,form};
}
export function field(label,name,value='',type='text',extra='') { return `<label class="field"><span>${esc(label)}</span>${type==='textarea'?`<textarea name="${esc(name)}" ${extra}>${esc(value)}</textarea>`:`<input name="${esc(name)}" type="${esc(type)}" value="${esc(value)}" ${extra}>`}</label>`; }
export const select = (label,name,options,value='',extra='') => `<label class="field"><span>${esc(label)}</span><select name="${esc(name)}" ${extra}>${options.map(o=>{const [v,l]=Array.isArray(o)?o:[o,o];return `<option value="${esc(v)}" ${v===value?'selected':''}>${esc(l)}</option>`;}).join('')}</select></label>`;
export function diff(before,after) {
  const oldLines=String(before).split('\n'),newLines=String(after).split('\n');
  const rows=[];const length=Math.max(oldLines.length,newLines.length);
  for(let i=0;i<length;i++) { const a=oldLines[i],b=newLines[i];rows.push(`<div class="diff-row ${a!==b?'changed':''}"><span>${i+1}</span><pre>${esc(a??'')}</pre><pre>${esc(b??'')}</pre></div>`); }
  return `<div class="diff"><div class="diff-head"><span></span><b>历史 / 服务器版本</b><b>当前版本 / 本地草稿</b></div>${rows.join('')}</div>`;
}
