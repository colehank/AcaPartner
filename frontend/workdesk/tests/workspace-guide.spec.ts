import {test,expect,type Page} from '@playwright/test';
import {rolldown} from 'rolldown';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

// Actual React guide/Chrome plus a separate whole-main/actual-Session fixture.
// Reserved domain, synthetic content and allowlisted transport only. No live
// service, user workspace, runner, model or paid operation is used.
const front=resolve(dirname(fileURLToPath(import.meta.url)),'..'),origin='https://workspace-guide276.invalid';
const KEY='research-partner.workspace-guide.v1';
const topics=['项目与工作桌','连续稿件','选区批注与整轮意见','科研图画布','固定来源与当前来源','数据、代码与计算链','原生笔记与检索','研究委托','有限科研协作','项目任务与回报','问题与证据关系','稿件 Claim 与证据','当前 PDF、保存与重开'];
const modules=['workspace','paper','review','figure','sources','generation','notes','commission','collaboration','tasks','graph','claims','pdf'];
let guideBundle='',mainBundle='',styles='';
test.use({launchOptions:process.env.WORKSPACE_GUIDE_BROWSER?{executablePath:process.env.WORKSPACE_GUIDE_BROWSER}:undefined});
test.setTimeout(30000);
async function compile(code:string,name:string){
  const entry=resolve(front,'.'+name+'.tsx');
  const build=await rolldown({cwd:front,input:entry,platform:'browser',transform:{jsx:'react-jsx',define:{'process.env.NODE_ENV':JSON.stringify('production')}},plugins:[{
    name,resolveId(id){if(id===entry)return id;if(id.endsWith('.css'))return '\0css:'+id+'.js';if(id==='pdfjs-dist/build/pdf.worker.min.mjs?url')return '\0unused-pdf';},
    load(id){if(id===entry)return {code,moduleType:'tsx'};if(id.startsWith('\0css:'))return 'export default {};';if(id==='\0unused-pdf')return 'export default "/unused-pdf.mjs";';}
  }]});
  try{return (await build.generate({format:'iife',codeSplitting:false})).output.filter(x=>x.type==='chunk').map(x=>x.code).join('\n');}finally{await build.close();}
}
test.beforeAll(async()=>{
  const require=createRequire(resolve(front,'package.json')),main=resolve(front,'src/main.tsx');
  for(const match of readFileSync(main,'utf8').matchAll(/import '([^']+\.css)';/g))styles+=readFileSync(match[1].startsWith('.')?resolve(front,'src',match[1]):require.resolve(match[1]),'utf8');
  styles+=readFileSync(resolve(front,'src/workspace-guide.css'),'utf8');
  guideBundle=await compile(`import React,{useState} from 'react';import {createRoot} from 'react-dom/client';
    import {WorkspaceGuide} from ${JSON.stringify(resolve(front,'src/WorkspaceGuide.tsx'))};import {WorkspaceChrome} from ${JSON.stringify(resolve(front,'src/WorkspaceChrome.tsx'))};
    window.guideFixture={modules:[],otherActions:[],fail:false};const action=name=>()=>window.guideFixture.otherActions.push(name);
    function Fixture(){const [request,setRequest]=useState(0),[epoch,setEpoch]=useState(0);window.guideFixture.remount=()=>setEpoch(x=>x+1);return <main><WorkspaceChrome draftState="syncing" actions={{guide:()=>setRequest(x=>x+1),quickOpen:action('quickOpen'),search:action('search'),notes:action('notes'),paper:action('paper'),partner:action('partner'),figure:action('figure'),generation:action('generation'),graph:action('graph'),claims:action('claims'),resetLayout:action('resetLayout')}}/><textarea aria-label="原有草稿" defaultValue="原有未保存内容😀"/><WorkspaceGuide key={epoch} openRequest={request} onOpenModule={module=>{if(window.guideFixture.fail)throw Error('独立测试：模块暂不可用');window.guideFixture.modules.push(module);}}/></main>;}createRoot(document.getElementById('root')).render(<Fixture/>);`,'workspace-guide276-component');
  mainBundle=await compile(`import {Session} from ${JSON.stringify(resolve(front,'src/session.ts'))};import ${JSON.stringify(main)};const load=Session.prototype.load;Session.prototype.load=async function(){window.guideTestSession=this;return load.call(this);};`,'workspace-guide276-main');
});
const dialog=(page:Page)=>page.getByRole('dialog',{name:/认识你的研究工作桌|引导目录|项目与工作桌|连续稿件|选区批注|科研图|固定来源|数据、代码|原生笔记|研究委托|有限科研协作|项目任务|问题与证据|稿件 Claim|当前 PDF/});
async function mount(page:Page,options:{wholeMain?:boolean,storage?:'denied'|'malformed'}={}){
  if(options.storage==='denied')await page.addInitScript(()=>{Object.defineProperty(Storage.prototype,'getItem',{value(){throw new DOMException('Denied','SecurityError');}});Object.defineProperty(Storage.prototype,'setItem',{value(){throw new DOMException('Denied','SecurityError');}});});
  if(options.storage==='malformed')await page.addInitScript(key=>localStorage.setItem(key,'not json'),KEY);
  const requests:any[]=[],unexpected:string[]=[],errors:string[]=[];
  const project={id:'PRJ-guide276-synthetic',title:'引导隔离项目'},paper={id:'PAPER-guide276-synthetic',revision:1,title:'原稿标题',content:{blocks:[{id:'B',kind:'paragraph',text:'保存版原文'}],components:[]}};
  let layout:any={revision:1,value:{layout:null}},draft:any={revision:1,value:{buffers:{},manuscript:{base:1,blocks:[{id:'B',kind:'paragraph',text:'保留原有未保存草稿😀'}],title:paper.title,dirty:true},figure_drafts:{},caption_drafts:{},composition_drafts:{}}};
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
    try{
      const url=new URL(route.request().url());if(url.origin!==origin)throw new Error('External request denied: '+url.origin);
      if(url.pathname==='/')return await route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><style>'+styles+'</style><div id="root"></div><script src="/fixture.js"></script>'});
      if(url.pathname==='/fixture.js')return await route.fulfill({contentType:'application/javascript',body:options.wholeMain?mainBundle:guideBundle});
      const input=route.request().method()==='POST'?route.request().postDataJSON():{url:url.pathname};requests.push(input);
      if(!options.wholeMain)throw new Error('Guide must not request '+url.pathname);
      if(url.pathname==='/api/state')return await route.fulfill({json:{csrf:'synthetic-guide276',projects:[project],providers:[],runtime:{running:false},project_management:{can_create:true,writable_project_ids:[project.id]}}});
      if(url.pathname!=='/api/action')throw new Error('Forbidden URL: '+url.pathname);
      let result:any;
      if(input.action==='desk.bootstrap')result={projects:[project]};
      else if(input.action==='desk.drafts.read')result=structuredClone(draft);
      else if(input.action==='desk.layout.read')result=structuredClone(layout);
      else if(input.action==='desk.paper.read')result={object:paper,render:null};
      else if(input.action==='notes.list')result={entries:[]};
      else if(input.action==='notes.navigation')result={favorites:[],recent:[],history:[],history_index:-1};
      else if(input.action==='desk.assets.list')result={items:[]};
      else if(input.action==='desk.paper.edits')result={changes:[],marked_blocks:paper.content.blocks.map(block=>({block})),decision_version:0};
      else if(input.action==='desk.review.read')result={revision:1,opinions:[],annotations:[],rounds:[],providers:[],runtime_running:false};
      else if(input.action==='desk.layout.write'){expect(input.expected_revision).toBe(layout.revision);layout={revision:layout.revision+1,value:structuredClone(input.value)};result=layout;}
      else if(input.action==='desk.drafts.write'){expect(input.expected_revision).toBe(draft.revision);draft={revision:draft.revision+1,value:structuredClone(input.value)};result=draft;}
      else throw new Error('Forbidden action: '+input.action);
      await route.fulfill({json:{ok:true,result}});
    }catch(e){unexpected.push(String(e));await route.abort().catch(()=>{});}
  });
  await page.goto(origin+'/');await expect(dialog(page)).toBeVisible();
  return {requests,errors,unexpected};
}
async function contents(page:Page,topic:string){await dialog(page).getByRole('button',{name:'目录',exact:true}).click();await dialog(page).getByRole('button',{name:topic,exact:true}).click();await expect(dialog(page).getByRole('heading',{name:topic,exact:true})).toBeVisible();}
async function reopen(page:Page){await page.getByRole('button',{name:'使用引导',exact:true}).click();await expect(dialog(page)).toBeVisible();}
function clean(f:Awaited<ReturnType<typeof mount>>){expect(f.unexpected).toEqual([]);expect(f.errors).toEqual([]);}

test('welcome is optional; skipping and reopening keep the original draft and call no navigation',async({page})=>{
  const f=await mount(page);await expect(dialog(page)).toContainText('NoRunner');
  await dialog(page).getByRole('button',{name:'稍后再看'}).click();await expect(dialog(page)).toHaveCount(0);
  expect(await page.evaluate(key=>JSON.parse(localStorage.getItem(key)!).status,KEY)).toBe('deferred');
  await expect(page.getByLabel('原有草稿')).toHaveValue('原有未保存内容😀');await reopen(page);
  await expect(dialog(page).getByRole('heading')).toHaveText(topics[0]);await expect(dialog(page).getByRole('button',{name:'上一步'})).toBeDisabled();
  await dialog(page).getByRole('button',{name:'下一步'}).click();await expect(dialog(page).getByRole('heading')).toHaveText(topics[1]);
  await dialog(page).getByRole('button',{name:'上一步'}).click();await contents(page,topics[8]);
  await dialog(page).getByRole('button',{name:'结束引导'}).click();await reopen(page);await expect(dialog(page).getByRole('heading')).toHaveText(topics[8]);
  expect(await page.evaluate(()=>(window as any).guideFixture)).toMatchObject({modules:[],otherActions:[]});expect(f.requests).toEqual([]);clean(f);
});

test('every topic opens only its requested module on an explicit click and resumes that step',async({page})=>{
  const f=await mount(page);await dialog(page).getByRole('button',{name:'开始引导'}).click();
  for(let i=0;i<topics.length;i++){
    await contents(page,topics[i]);expect(await page.evaluate(()=>(window as any).guideFixture.modules.length)).toBe(i);
    await expect(dialog(page)).toContainText('保存与执行边界');await dialog(page).getByRole('button',{name:'打开此模块',exact:true}).click();
    await expect(dialog(page)).toHaveCount(0);await reopen(page);await expect(dialog(page).getByRole('heading')).toHaveText(topics[i]);
  }
  expect(await page.evaluate(()=>(window as any).guideFixture.modules)).toEqual(modules);expect(f.requests).toEqual([]);clean(f);
});

test('completion survives reload, invalid records are safe, and restarting remains available',async({page})=>{
  const f=await mount(page,{storage:'malformed'});await dialog(page).getByRole('button',{name:'开始引导'}).click();await contents(page,topics.at(-1)!);
  await expect(dialog(page).getByRole('button',{name:'下一步'})).toBeDisabled();await dialog(page).getByRole('button',{name:'完成引导'}).click();
  expect(await page.evaluate(key=>JSON.parse(localStorage.getItem(key)!).status,KEY)).toBe('completed');
  // Clear the one-time malformed-record init script for this navigation by
  // using a fresh page in the same browser context (same persistent storage).
  const next=await page.context().newPage();await next.route('**/*',async route=>{const url=new URL(route.request().url());if(url.origin!==origin)return route.abort();if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><style>'+styles+'</style><div id="root"></div><script src="/fixture.js"></script>'});if(url.pathname==='/fixture.js')return route.fulfill({contentType:'application/javascript',body:guideBundle});return route.abort();});
  try{await next.goto(origin+'/');await expect(next.getByRole('button',{name:'使用引导'})).toBeVisible();await expect(dialog(next)).toHaveCount(0);await reopen(next);await expect(dialog(next).getByRole('heading')).toHaveText(topics.at(-1)!);}finally{await next.close();}clean(f);
});

test('blocked browser storage still permits skip, reopen and step navigation',async({page})=>{
  const f=await mount(page,{storage:'denied'});await dialog(page).getByRole('button',{name:'稍后再看'}).click();await reopen(page);await contents(page,topics[5]);
  await page.keyboard.press('Escape');await expect(dialog(page)).toHaveCount(0);await reopen(page);await expect(dialog(page).getByRole('heading')).toHaveText(topics[5]);expect(f.requests).toEqual([]);clean(f);
});

test('a later storage write failure keeps newer in-memory progress across a workdesk remount',async({page})=>{
  const f=await mount(page);await dialog(page).getByRole('button',{name:'稍后再看'}).click();
  await page.evaluate(()=>Object.defineProperty(Storage.prototype,'setItem',{value(){throw new DOMException('Full','QuotaExceededError');}}));
  await reopen(page);await contents(page,topics[6]);await page.keyboard.press('Escape');
  await page.evaluate(()=>(window as any).guideFixture.remount());await reopen(page);await expect(dialog(page).getByRole('heading')).toHaveText(topics[6]);expect(f.requests).toEqual([]);clean(f);
});

test('keyboard focus stays inside the guide and Escape returns to the fixed entry',async({page})=>{
  const f=await mount(page);await dialog(page).getByRole('button',{name:'稍后再看'}).click();await reopen(page);
  await expect(dialog(page).getByRole('heading')).toBeFocused();await page.keyboard.press('Shift+Tab');await expect(dialog(page).getByRole('button',{name:'下一步'})).toBeFocused();
  await page.keyboard.press('Tab');await expect(dialog(page).getByRole('button',{name:'关闭引导'})).toBeFocused();
  await page.keyboard.press('ArrowRight');await expect(dialog(page).getByRole('heading')).toHaveText(topics[1]);await page.keyboard.press('ArrowLeft');await expect(dialog(page).getByRole('heading')).toHaveText(topics[0]);
  await page.keyboard.press('Escape');await expect(page.getByRole('button',{name:'使用引导'})).toBeFocused();clean(f);
});

for(const viewport of [{width:390,height:560},{width:320,height:480}])test(`small ${viewport.width}px viewport keeps close and navigation visible`,async({page},info)=>{
  await page.setViewportSize(viewport);const f=await mount(page);await dialog(page).getByRole('button',{name:'开始引导'}).click();await contents(page,topics[3]);
  for(const name of ['关闭引导','目录','上一步','下一步']){
    const control=dialog(page).getByRole('button',{name,exact:true});await expect(control).toBeVisible();const box=await control.boundingBox();expect(box).not.toBeNull();expect(box!.x).toBeGreaterThanOrEqual(0);expect(box!.x+box!.width).toBeLessThanOrEqual(viewport.width);expect(box!.y+box!.height).toBeLessThanOrEqual(viewport.height);
  }
  const screenshot=info.outputPath('guide-small-viewport.png');await page.screenshot({path:screenshot});await info.attach('guide-small-viewport',{path:screenshot,contentType:'image/png'});await page.keyboard.press('Escape');await expect(dialog(page)).toHaveCount(0);clean(f);
});

test('whole main keeps dirty manuscript and only opens real modules on explicit request',async({page})=>{
  const f=await mount(page,{wholeMain:true});await dialog(page).getByRole('button',{name:'稍后再看'}).click();
  const manuscript=page.getByRole('textbox',{name:'连续稿件',exact:true});await expect(manuscript).toContainText('保留原有未保存草稿😀');
  await manuscript.locator('[data-block-id="B"]').click();await page.keyboard.press('End');await page.keyboard.insertText('，继续输入');await expect(page.locator('.workspace-draft-state')).toHaveText('草稿已同步');
  const snapshot=()=>page.evaluate(()=>{const s=(window as any).guideTestSession;return structuredClone({paper:s.paper,paperDraft:s.paperDraft,buffers:[...s.buffers],figureDrafts:s.figureDrafts,captionDrafts:s.captionDrafts,compositionDrafts:s.compositionDrafts});});
  await page.waitForTimeout(250);const before=await snapshot(),writes=f.requests.filter(q=>q.action?.endsWith('.write')).length;
  await reopen(page);await dialog(page).getByRole('button',{name:'打开此模块'}).click();await expect(page.getByLabel('当前项目')).toBeFocused();
  await reopen(page);await page.keyboard.press('Control+k');await expect(page.getByRole('dialog',{name:'快速打开笔记'})).toHaveCount(0);
  for(const topic of topics)await contents(page,topic);
  expect(await snapshot()).toEqual(before);expect(f.requests.filter(q=>q.action?.endsWith('.write'))).toHaveLength(writes);
  await contents(page,'研究委托');await dialog(page).getByRole('button',{name:'打开此模块'}).click();await expect(dialog(page)).toHaveCount(0);
  await expect(page.getByText('执行器尚未运行；可以解析来源，当前不能提交执行。',{exact:true})).toBeVisible();expect(await snapshot()).toEqual(before);
  await reopen(page);await contents(page,'连续稿件');await dialog(page).getByRole('button',{name:'打开此模块'}).click();await expect(manuscript).toContainText('，继续输入');
  await reopen(page);await contents(page,topics.at(-1)!);await dialog(page).getByRole('button',{name:'打开此模块'}).click();await expect(page.locator('section.pdf-panel')).toBeVisible();await expect(page.getByText('尚未生成本次 PDF',{exact:true})).toBeVisible();
  expect(await snapshot()).toEqual(before);expect(f.requests.some(q=>q.action==='desk.paper.render'||/authorize|\.start$|\.submit$|commission|cycle|claim\.propose/.test(q.action||''))).toBe(false);clean(f);
});

test('failed module navigation leaves guide open with a retryable error',async({page})=>{
  const f=await mount(page);await dialog(page).getByRole('button',{name:'开始引导'}).click();await page.evaluate(()=>(window as any).guideFixture.fail=true);
  await dialog(page).getByRole('button',{name:'打开此模块'}).click();await expect(dialog(page).getByRole('alert')).toHaveText('独立测试：模块暂不可用');
  await page.evaluate(()=>(window as any).guideFixture.fail=false);await dialog(page).getByRole('button',{name:'打开此模块'}).click();await expect(dialog(page)).toHaveCount(0);expect(f.requests).toEqual([]);clean(f);
});
