import {esc,pretty,button} from './ui.js';

export const workshopRecipes={
 stimulus:{name:'刺激准备',canonical:'stimuli',input:'登记 PNG/JPEG/TIFF/BMP/WebP/PPM 图像。alias 用于排序；不接受本机路径或外部 URL。',config:{width:256,height:256,resize:'pad',interpolation:'lanczos'},help:'width/height 为 1–4096 像素；resize 可选 contain（保比例）、pad（补边）、stretch（拉伸）；interpolation 可选 lanczos/nearest。可选 order 必须包含每个输入 alias 且只出现一次。生成新 PNG 和尺寸/哈希清单。'},
 annotations:{name:'图像与标注清洗',canonical:'annotation_cleaning',input:'登记图像及恰好一个标注 JSON：{"annotations":[{"id":"a1","image":"image.png","label":"object","bbox":[10,20,30,40]}]}。bbox 为像素 [x,y,width,height]。',config:{rename_map:{},clip_bboxes:false},help:'rename_map 将标注中的旧图名映射到登记文件名。clip_bboxes:true 明确允许裁剪越界框；默认不裁剪。缺失、重复、无效和不确定行会保留并标记。'},
 neural:{name:'神经数据预处理',canonical:'neural_preprocessing',input:'一个数值 NPY/CSV/JSON/HDF5。确认 samples_axis 与样本索引；HDF5 必须指定 dataset，CSV 用 skiprows:0 或 1。',config:{operation:'select_window',samples_axis:0,window_samples:[0,256],sampling_rate_hz:null,units:'source units unspecified',skiprows:1},help:'operation 只支持 select_window 或 baseline_subtract，分别提供 window_samples 或 baseline_samples:[start,stop]（左闭右开）。samples_axis 为 0/1。已知采样率才填写正值，不知道则 null；单位可明确未指定。示例区间只是配置格式，须按实际数据核对。只生成新输出，不拟合或改写输入。'},
 visualization:{name:'可视化工具',canonical:'visualization',input:'一个 CSV/JSON 数值表，至少两个数值列，1–100,000 行。',config:{x:'time',y:'response'},help:'x/y 必须改成输入表中真实列名。输出本地 HTML 浏览工具、精确数据 JSON、SVG 预览和 serve.py；生成不等于浏览器交互已验收。'},
 experiment:{name:'实验软件',canonical:'experiment',input:'登记刺激图像；本流程生成实验软件与清单，不控制物理设备。',config:{trials:2},help:'trials 为 1–200。可选 responses 必须逐 trial 提供一个短文本，只用于受控技术执行，不代表真实被试响应。浏览器、人类被试、设备和物理时序另行验证。'}
};
export const workshopKey=value=>Object.keys(workshopRecipes).find(k=>k===value||workshopRecipes[k].canonical===value)||'stimulus';
export function workshopHelp(value){const key=workshopKey(value),r=workshopRecipes[key];return `<details class="config-help" open><summary>${esc(r.name)} · 输入与参数</summary><p>${esc(r.input)}</p><p>${esc(r.help)}</p><pre>${esc(pretty(r.config))}</pre>${button('填入此类别示例（替换配置）','workshop-example',{category:key},'button small subtle')}<p class="hint">示例仅提供参数格式；提交前请核对输入、范围与授权。</p></details>`;}
export function registeredSHA(value){const v=typeof value==='object'?value?.sha||value?.asset||value?.url:value;const match=String(v||'').match(/^(?:\/api\/assets\/)?([a-f0-9]{64})$/);if(!match)throw new Error('请选择已登记资产的 SHA 或 /api/assets/SHA 地址。');return match[1];}
export function workshopRequest(v,project_id,request_key){
 const key=workshopKey(v.category),inputs=JSON.parse(v.inputs),config=JSON.parse(v.config);
 if(!Array.isArray(inputs)||!inputs.length)throw new Error('输入必须是包含已登记 SHA 的非空 JSON 数组。');
 inputs.forEach(x=>{if(typeof x!=='object'||!x||x.path||x.url)throw new Error('工坊输入只接受 {sha,alias?}，不能填写路径或 URL。');registeredSHA(x.sha);});
 if(!config||Array.isArray(config)||typeof config!=='object')throw new Error('处理配置必须是 JSON 对象。');
 if(v.execute_code!=='on')throw new Error('请明确授权本次配置的执行。');
 if(key==='neural'&&v.scientific_preprocessing!=='on')throw new Error('神经数据预处理需要另行明确授权。');
 const remote=(v.remote_host||config.remote_host||'').trim();if(remote)config.remote_host=remote;else delete config.remote_host;
 if(remote&&v.remote_execution!=='on')throw new Error('远端执行需要明确授权发送当前输入至配置的执行器。');
 const timeout=Number(v.timeout_seconds||60);if(!Number.isFinite(timeout)||timeout<1||timeout>600)throw new Error('工坊时限应为 1–600 秒。');
 return {project_id,request_key,title:v.title,request:v.title,category:key,inputs,config,expected_output:v.acceptance,acceptance:v.acceptance,budget:{max_model_calls:0,timeout_seconds:timeout},authorization:{execute_code:true,scientific_preprocessing:key==='neural'&&v.scientific_preprocessing==='on',remote_execution:!!remote&&v.remote_execution==='on'}};
}
export const canGuide=task=>!['cancelled','deliverable','completed','succeeded','canceled'].includes(task.status);
export function canExtendBudget(task,providers){return ['failed','waiting_resource','waiting_authorization','paused'].includes(task.status)&&providers.some(p=>p.id===task.payload?.provider_id&&p.route==='codex');}
export function budgetExtension(task,v,providers){
 if(!canExtendBudget(task,providers))throw new Error('仅停止后的 Codex 路线任务可从这里追加额度。');
 if(v.approved!=='on'&&v.approved!==true)throw new Error('请明确确认新增额度及其费用边界。');
 const calls=Number(v.additional_invocations),seconds=Number(v.additional_seconds),reason=String(v.reason||'').trim();
 if(!Number.isInteger(calls)||calls<0||calls>5||!Number.isFinite(seconds)||seconds<0||seconds>900||calls+seconds<=0)throw new Error('每次追加限 0–5 次 CLI 调用、0–900 秒，至少一项大于零。');
 if(!reason)throw new Error('请填写本次追加理由和边界。');
 return {id:task.id,approved:true,reason,additional_invocations:calls,additional_seconds:seconds};
}
export function exportFormats(kind){const formats={report:['md','docx','pdf'],note:['md','docx','pdf'],paper:['md','docx','tex','bib','pdf'],figure:['svg','pdf','png'],diagram:['svg','pdf','png'],poster:['pdf','svg','png'],slides:['pptx','pdf','md','txt'],literature:['bib']};return [...(formats[kind]||['md']),'json','zip'];}
export function growthStatus(g){return g.content?.status||g.status||'candidate';}
export async function packageExtension(raw,files){
 const manifest=typeof raw==='string'?JSON.parse(raw):structuredClone(raw);
 if(!manifest||typeof manifest!=='object'||Array.isArray(manifest))throw new Error('扩展清单必须是 JSON 对象。');
 if(!manifest.files||typeof manifest.files!=='object'||Array.isArray(manifest.files))throw new Error('清单需要 files 文件映射。');
 const names=Object.keys(manifest.files);if(names.length<1||names.length>32)throw new Error('扩展需要 1–32 个明确列出的源码文件。');
 const selected=Array.from(files||[]);let total=0;
 for(const name of names){
  if(!/^[A-Za-z0-9_./-]+$/.test(name)||name.startsWith('/')||name.split('/').some(p=>p.startsWith('.')||!p))throw new Error(`不允许的扩展相对路径：${name}`);
  const info=typeof manifest.files[name]==='string'?{sha256:manifest.files[name]}:{...manifest.files[name]};
  const matches=selected.filter(f=>{const p=f.webkitRelativePath||f.name;return p===name||p.split('/').slice(1).join('/')===name||(!name.includes('/')&&f.name===name);});
  if(matches.length>1)throw new Error(`文件 ${name} 对应多个选择，请保留一个精确来源。`);
  let bytes;
  if(matches.length){if(matches[0].size>1024*1024)throw new Error(`${name} 超过 1 MB，未读取或发送。`);bytes=new Uint8Array(await matches[0].arrayBuffer());}
  else if(info.base64){try{bytes=Uint8Array.from(atob(info.base64),c=>c.charCodeAt(0));}catch{throw new Error(`${name} 的 base64 无效。`);}}
  else throw new Error(`缺少文件 ${name}；请选择实际文件或在清单中提供 base64。`);
  total+=bytes.byteLength;if(total>1024*1024)throw new Error('扩展源码总量超过 1 MB。');
  const sha256=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes)),x=>x.toString(16).padStart(2,'0')).join('');
  if(info.sha256&&info.sha256!==sha256)throw new Error(`${name} 与清单 SHA256 不一致；请核对来源，不能静默替换身份。`);
  let binary='';for(let i=0;i<bytes.length;i+=32768)binary+=String.fromCharCode(...bytes.subarray(i,i+32768));
  manifest.files[name]={sha256,base64:btoa(binary)};
 }
 if(!names.includes(manifest.entrypoint))throw new Error('entrypoint 必须是 files 中已选择的 Python 文件。');
 return manifest;
}

export function canReviseCandidate(task){return ['waiting_input','paused','failed'].includes(task?.status)&&task.attempts<3&&task.result?.failure_code==='candidate_revision_required'&&!task.result?.object_id&&task.payload?.kind!=='workshop';}

export function diagramReference(values){
 const id=String(values.reference_id||'').trim(),revision=String(values.reference_revision||'').trim(),block=String(values.reference_block||'').trim();
 if(!id){if(revision||block)throw new Error('来源修订和段落需要对应的来源成果。');return null;}
 const number=Number(revision);if(!Number.isInteger(number)||number<1)throw new Error('请选择来源成果的准确修订（正整数）。');
 return {id,revision:number,...(block?{block_id:block}:{})};
}
