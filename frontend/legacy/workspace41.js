/* Workdesk chrome. Content and edits remain owned by the existing artifact editors. */
import {esc,kinds,button} from './ui.js';

const paths={
 desk:'M3 4h18v14H3z M3 8h18 M8 8v10 M8 13h13',
 tree:'M5 3v14h5 M5 7h5 M11 5h9v4h-9z M11 15h9v4h-9z',
 graph:'M5 4a2 2 0 1 0 0 .1 M19 4a2 2 0 1 0 0 .1 M12 19a2 2 0 1 0 0 .1 M7 5l10 0 M6 7l5 10 M18 7l-5 10',
 workshop:'m14 3 7 7-3 3-3-3-7 10-4-4 10-7-3-3z',
 book:'M3 4h7l2 2 2-2h7v15h-7l-2 2-2-2H3z M12 6v15',
 activity:'M3 12h4l3-7 4 14 3-7h4',
 settings:'M12 8a4 4 0 1 0 0 8 4 4 0 1 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',
 search:'M10 3a7 7 0 1 0 0 14 7 7 0 1 0 0-14 M15 15l6 6',
 split:'M3 4h18v16H3z M12 4v16',
 fit:'M3 9V3h6 M15 3h6v6 M21 15v6h-6 M9 21H3v-6',
 comment:'M3 4h18v13H9l-6 4z M7 8h10 M7 12h6',
 sliders:'M4 5h16 M4 12h16 M4 19h16 M8 3v4 M16 10v4 M10 17v4',
 note:'M4 3h12l4 4v14H4z M15 3v5h5 M8 12h8 M8 16h5',
 arrow:'M5 12h14 M13 6l6 6-6 6',
 pin:'m9 3 9 0-2 6 3 4-6 0-5 8 2-8H5l5-4z',
 folder:'M3 6h7l2 2h9v12H3z M3 6V3h7l2 3',
 plus:'M12 4v16 M4 12h16',
 back:'M19 12H5 M11 6l-6 6 6 6',
 close:'M6 6l12 12 M6 18 18 6'
};
export function icon41(name){return `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${paths[name]||paths.desk}"/></svg>`;}
function tool(label,name,extra='',active=false){return `<button type="button" class="desk41-tool ${active?'active':''}" data-desk41="${name}" title="${esc(label)}" aria-label="${esc(label)}" ${extra}>${icon41(name)}</button>`;}
export function readDesk41State(storage=localStorage,key='research-partner:desk41'){
 try{const data=JSON.parse(storage.getItem(key)||'null')||{};return {outliner:data.outliner!==false,properties:data.properties===true,ratio:Math.max(.3,Math.min(.7,Number(data.ratio)||.55)),outlinerWidth:Math.max(190,Math.min(420,Number(data.outlinerWidth)||252)),query:'',collapsedKeys:data.collapsedKeys,selectedKeys:[],focusKey:null,pinned:!!data.pinned,pinObject:data.pinObject||'',...{}};}catch{return {outliner:true,properties:false,ratio:.55,outlinerWidth:252,query:'',selectedKeys:[]};}
}
export function storeDesk41State(state,storage=localStorage,key='research-partner:desk41'){
 try{const {outliner,properties,ratio,outlinerWidth,collapsedKeys,pinned,pinObject}=state;storage.setItem(key,JSON.stringify({outliner,properties,ratio,outlinerWidth,collapsedKeys,pinned,pinObject}));}catch{}
}
export function shell41(c,{body,state,embedded=false,split=false,maximized=null,restoring=false}={}){
 const project=(c.objects||[]).find(o=>o.id===c.project),editing=c.view==='workspace'&&c.object;
 const title=project?.title||'研究空间';
 const rail=[['desk','工作台','projects'],['graph','研究图谱','graph'],['workshop','研究工坊','workshop'],['book','文献','literature'],['activity','任务与活动','activity']];
 const area=`<div class="desk41-areas ${split?'is-split':''} ${maximized?'maximized-'+maximized:''}" style="--desk41-ratio:${state.ratio||.55}"><section class="desk41-primary" data-region41-primary tabindex="-1">${body}</section>${!embedded&&split?`<div class="desk41-area-divider" data-desk41-resize="areas" role="separator" aria-label="调整两个编辑区宽度" aria-orientation="vertical" tabindex="0"></div><section class="desk41-secondary" data-region41-secondary aria-label="副编辑区">${restoring?'<p class="desk41-region-loading" role="status">正在恢复副编辑区…</p>':''}</section>`:''}</div>`;
 if(embedded)return `<div class="desk41 desk41-embedded ${state.properties?'show-properties':''}"><header class="desk41-embeddedbar"><span>副编辑区</span><span class="desk41-region-project" title="所属项目">${esc(project?.title||'研究空间')}</span><span class="desk41-spacer"></span>${tool('显示属性','sliders','',state.properties)}${tool('聚焦此区 / 恢复双区','fit')}${tool('收起副区（保留草稿）','close')}</header>${area}</div>`;
 return `<div class="desk41 ${state.outliner?'show-outliner':''} ${state.properties?'show-properties':''} ${editing?'is-editing':''}" style="--desk41-outliner:${state.outlinerWidth||252}px">
 <header class="desk41-top"><button class="desk41-brand" data-action="select-project" data-id="" aria-label="返回研究空间">r<span>.</span></button><button class="desk41-project" data-desk41="project-picker" title="切换项目">${esc(title)}<span>⌄</span></button><div class="desk41-top-divider"></div><span class="desk41-workspace-name">学术工作台</span><span class="desk41-spacer"></span>${tool('查找成果','search')}${tool('显示 / 隐藏对象树','tree','',state.outliner)}${tool('显示副编辑区（恢复保留的对象）','split','',split)}${tool('聚焦当前编辑区 / 恢复布局','fit')}${uiButton41('搭档','workbench-partner','comment')}<details class="desk41-menu"><summary aria-label="工作台菜单">⋯</summary><div>${button('界面操作指南','desk-help',{},'text-button')}${button('设置与连接','navigate',{view:'settings'},'text-button')}${c.auth?.session_active?button('退出研究空间','session-logout',{},'text-button'):''}<small>工作台 41 · 实际成果</small></div></details></header>
 <nav class="desk41-rail" aria-label="研究空间模块">${rail.map(([icon,label,view])=>`<button type="button" class="desk41-tool ${(view==='projects'?['projects','workspace'].includes(c.view):c.view===view)?'active':''}" data-action="navigate" data-view="${view}" title="${label}" aria-label="${label}">${icon41(icon)}</button>`).join('')}<span class="desk41-spacer"></span><button class="desk41-tool" data-action="navigate" data-view="settings" title="设置" aria-label="设置">${icon41('settings')}</button></nav>
 <aside class="desk41-outliner"><header><strong>项目内容</strong><span class="desk41-spacer"></span><button class="desk41-tool" data-action="new-artifact" title="新建成果" aria-label="新建成果">${icon41('plus')}</button></header><div data-desk41-tree class="desk41-tree"></div><footer class="desk41-tree-footer"><button data-desk41="open-selected" title="在当前区打开所选对象">打开</button><button data-desk41="open-secondary" title="在副编辑区打开所选对象">在副区打开 ${icon41('split')}</button></footer><div class="desk41-outliner-divider" data-desk41-resize="outliner" role="separator" aria-label="调整对象树宽度" aria-orientation="vertical" tabindex="0"></div></aside>
 <main class="desk41-main" id="main">${area}</main>
 <footer class="desk41-status"><span class="desk41-connection ${c.online?'':'offline'}" title="${c.online?'研究空间已连接':'连接中断，本机草稿保留'}"></span><span data-desk41-status>${editing?esc(kinds[c.object.kind]||c.object.kind):'工作空间'}</span><span class="desk41-spacer"></span><span class="desk41-key-help">中键 / 空格拖动 · Ctrl + 滚轮缩放</span><span>${split?'双编辑区':'单编辑区'}</span></footer></div>`;
}
function uiButton41(label,action,icon){return `<button class="desk41-label-tool" data-action="${action}">${icon41(icon)}<span>${label}</span></button>`;}
export function areaTools41(c){return `<div class="desk41-context-tools"><span>${esc(kinds[c.object?.kind]||'成果')}</span><span class="desk41-spacer"></span><button data-action="annotate" class="desk41-label-tool" title="给当前位置添加批注">${icon41('comment')}<span>批注</span></button>${['paper','report','note'].includes(c.object?.kind)?'<button data-action="workspace-panel" data-panel="notes" class="desk41-tool" title="阅读位置的章节工坊笔记" aria-label="章节工坊笔记">'+icon41('note')+'</button>':''}<button data-desk41="sliders" class="desk41-tool" title="属性 / 排版" aria-label="属性 / 排版">${icon41('sliders')}</button><button data-desk41="pin" class="desk41-tool" title="固定当前成果，树中选择只定位" aria-label="固定当前成果">${icon41('pin')}</button></div>`;}
export function home41(c){
 const projects=(c.objects||[]).filter(o=>o.kind==='project'&&!o.archived),project=projects.find(o=>o.id===c.project);
 const visible=(c.objects||[]).filter(o=>o.project_id===project?.id&&!o.archived),outputs=visible.filter(o=>['paper','report','slides','poster','note','figure','diagram'].includes(o.kind));
 const featured=new Set(project?.metadata?.featured_objects||[]);
 const ordered=[...outputs].sort((a,b)=>Number(featured.has(b.id))-Number(featured.has(a.id))||Number(['paper','report','slides'].includes(b.kind))-Number(['paper','report','slides'].includes(a.kind)));
 return `<section class="desk41-home"><div class="desk41-home-heading"><span class="desk41-eyebrow">RESEARCH PARTNER / WORKSPACE</span><h1>${project?'继续你的研究':'你的研究空间'}</h1><p>${project?'从稿件开始，沿对象树进入图、章节和支撑材料。':'选择项目，打开成果。在同一张工作桌中阅读、修订与整理。'}</p></div>${project?`<div class="desk41-home-project"><span>${icon41('folder')}</span><h2>${esc(project.title)}</h2>${button('项目概览','workbench-project-details',{},'text-button')}</div><div class="desk41-output-list">${ordered.slice(0,12).map(o=>`<button data-action="open-object" data-id="${esc(o.id)}"><span class="desk41-output-icon">${icon41(['paper','report','note'].includes(o.kind)?'book':o.kind==='figure'?'sliders':'desk')}</span><span><strong>${esc(o.title)}</strong><small>${esc(kinds[o.kind]||o.kind)}${featured.has(o.id)?' · 项目置顶':''}</small></span>${icon41('arrow')}</button>`).join('')||'<p class="quiet-empty">还没有成果。从空文章框架或已有材料开始。</p>'}</div><div class="desk41-home-actions">${button('新建成果','new-artifact',{},'button')}${button('导入材料','workbench-import',{},'button subtle')}</div>`:`<div class="desk41-project-list">${projects.map(p=>{const count=(c.objects||[]).filter(o=>o.project_id===p.id&&['paper','report','slides','poster','figure','diagram'].includes(o.kind)).length;return `<button data-action="select-project" data-id="${esc(p.id)}"><span>${icon41('folder')}</span><strong>${esc(p.title)}</strong><small>${count} 份稿件与图形</small>${icon41('arrow')}</button>`;}).join('')}</div><div class="desk41-home-actions">${button('新建项目','new-project',{},'button')}</div>`}<div class="desk41-home-guide"><div><strong>一张工作桌</strong><p>左侧找对象，中间读成果。属性、批注和准备笔记按需展开。</p></div><div><strong>并排看，两区独立</strong><p>从对象树在副区打开图或材料。拖动分隔线调整宽度。</p></div></div></section>`;
}
