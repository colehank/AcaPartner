import {test,expect,type Page,type Route} from '@playwright/test';
import {rolldown} from 'rolldown';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

// Whole App + actual Session and native Chromium controls. All network is
// intercepted on a reserved .invalid origin; no workspace, server or model.
// This is a directed UI contract, not real HTTP/Store acceptance.
const front=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const origin='https://local-account275.invalid';
const USER='local.owner',PASSWORD='independent-ui-password';
const project={id:'PRJ-local-account275-synthetic',title:'独立登录测试项目'};
const paper={id:'PAPER-local-account275-synthetic',revision:1,title:'独立稿件',content:{blocks:[{id:'B',kind:'paragraph',text:'原始独立稿件'}],components:[]}};
let bundle='',styles='';
test.use({launchOptions:process.env.LOCAL_ACCOUNT_BROWSER?{executablePath:process.env.LOCAL_ACCOUNT_BROWSER}:undefined});
test.setTimeout(30000);
test.beforeAll(async()=>{
  const main=resolve(front,'src/main.tsx'),entry=resolve(front,'.local-account275-fixture.ts');
  const require=createRequire(resolve(front,'package.json'));
  for(const match of readFileSync(main,'utf8').matchAll(/import '([^']+\.css)';/g))styles+=readFileSync(match[1].startsWith('.')?resolve(front,'src',match[1]):require.resolve(match[1]),'utf8');
  const code=`import {Session} from ${JSON.stringify(resolve(front,'src/session.ts'))};import ${JSON.stringify(main)};
    const load=Session.prototype.load;window.accountTest={sessions:[],lateEdit:()=>window.accountTest.sessions.at(-1).editPaper('B','迟到的手改仍需保留')};
    Session.prototype.load=async function(){window.accountTest.sessions.push(this);return load.call(this);};`;
  const build=await rolldown({cwd:front,input:entry,platform:'browser',transform:{jsx:'react-jsx',define:{'process.env.NODE_ENV':JSON.stringify('production')}},plugins:[{
    name:'local-account275-isolated-main',resolveId(id){if(id===entry)return id;if(id.endsWith('.css'))return '\0css:'+id+'.js';if(id==='pdfjs-dist/build/pdf.worker.min.mjs?url')return '\0unused-pdf';},
    load(id){if(id===entry)return {code,moduleType:'ts'};if(id.startsWith('\0css:'))return 'export default {};';if(id==='\0unused-pdf')return 'export default "/unused-pdf.mjs";';}
  }]});
  try{bundle=(await build.generate({format:'iife',codeSplitting:false})).output.filter(x=>x.type==='chunk').map(x=>x.code).join('\n');}finally{await build.close();}
});
function gate(){let release!:()=>void;return {promise:new Promise<void>(done=>{release=done;}),release:()=>release()};}
async function mount(page:Page,options:{registered?:boolean,enabled?:boolean,authenticated?:boolean}={}){
  await page.addInitScript(()=>localStorage.setItem('research-partner.workspace-guide.v1',JSON.stringify({version:1,status:'deferred',step:0})));
  let registered=options.registered??true,enabled=options.enabled??true,authenticated=options.authenticated??false;
  let failDrafts=false,failLogout=false,closeRegistration=false,failMetadata=false;
  let authGate:ReturnType<typeof gate>|null=null,logoutGate:ReturnType<typeof gate>|null=null,bootstrapGate:ReturnType<typeof gate>|null=null;
  let draft:any={revision:1,value:{buffers:{},manuscript:{base:1,blocks:structuredClone(paper.content.blocks),dirty:false}}};
  let layout:any={revision:1,value:{layout:null}},metadataReads=0,logoutCount=0,authCount=0,draftReads=0;
  const requests:any[]=[],unexpected:string[]=[],errors:string[]=[];
  page.on('pageerror',e=>errors.push(e.message));
  const json=(route:Route,status:number,body:any)=>route.fulfill({status,json:body});
  await page.route('**/*',async route=>{
    try{
      const request=route.request(),url=new URL(request.url());
      if(url.origin!==origin)throw new Error('External request denied: '+url.origin);
      if(url.pathname==='/')return await route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><style>'+styles+'</style><div id="root"></div><script src="/fixture.js"></script>'});
      if(url.pathname==='/fixture.js')return await route.fulfill({contentType:'application/javascript',body:bundle});
      const input=request.method()==='POST'?request.postDataJSON():{};
      requests.push({path:url.pathname,input,csrf:request.headers()['x-csrf-token'],authenticated});
      if(url.pathname==='/api/auth/registration'){
        metadataReads++;if(failMetadata)return await json(route,503,{ok:false,error:'设置暂不可读'});
        return await json(route,200,{ok:true,result:{enabled,registration_open:enabled&&!registered}});
      }
      if(url.pathname==='/api/state')return await json(route,authenticated?200:401,authenticated?{csrf:'synthetic-csrf275'}:{ok:false,code:'unauthorized',error:'请登录'});
      if(url.pathname==='/api/auth/login'||url.pathname==='/api/auth/register'){
        authCount++;if(authGate)await authGate.promise;
        expect(Object.keys(input).sort()).toEqual(['password','username']);
        if(url.pathname.endsWith('/register')&&(registered||closeRegistration)){registered=true;return await json(route,409,{ok:false,code:'registration_closed',error:'注册已关闭'});}
        if(input.username!==USER||input.password!==PASSWORD)return await json(route,401,{ok:false,code:'unauthorized',error:'用户名或密码不正确'});
        registered=true;authenticated=true;return await json(route,200,{ok:true,result:{required:true,authenticated:true,session_active:true}});
      }
      if(url.pathname==='/api/auth/logout'){
        logoutCount++;expect(request.headers()['x-csrf-token']).toBe('synthetic-csrf275');
        if(logoutGate)await logoutGate.promise;
        if(failLogout)return await json(route,503,{ok:false,code:'unavailable',error:'暂时无法退出'});
        authenticated=false;return await json(route,200,{ok:true,result:{required:true,authenticated:false,session_active:false}});
      }
      if(url.pathname!=='/api/action')throw new Error('Unexpected URL: '+url.pathname);
      if(!authenticated)return await json(route,401,{ok:false,code:'unauthorized',error:'请登录'});
      let result:any;
      if(input.action==='desk.bootstrap'){if(bootstrapGate)await bootstrapGate.promise;result={projects:[project]};}
      else if(input.action==='desk.drafts.read'){draftReads++;result=structuredClone(draft);}
      else if(input.action==='desk.layout.read')result=structuredClone(layout);
      else if(input.action==='desk.paper.read')result={object:paper,render:null};
      else if(input.action==='notes.list')result={entries:[]};
      else if(input.action==='notes.navigation')result={favorites:[],recent:[],history:[],history_index:-1};
      else if(input.action==='desk.assets.list')result={items:[]};
      else if(input.action==='desk.paper.edits')result={changes:[],marked_blocks:paper.content.blocks.map(block=>({block})),decision_version:0};
      else if(input.action==='desk.review.read')result={revision:1,opinions:[],annotations:[],rounds:[],providers:[],runtime_running:false};
      else if(input.action==='desk.layout.write'){expect(input.expected_revision).toBe(layout.revision);layout={revision:layout.revision+1,value:structuredClone(input.value)};result=layout;}
      else if(input.action==='desk.drafts.write'){
        if(failDrafts)return await json(route,409,{ok:false,code:'conflict',error:'隔离草稿版本冲突'});
        expect(input.expected_revision).toBe(draft.revision);draft={revision:draft.revision+1,value:structuredClone(input.value)};result=draft;
      }else throw new Error('Unexpected action: '+input.action);
      await json(route,200,{ok:true,result});
    }catch(e){unexpected.push(String(e));await route.abort().catch(()=>{});}
  });
  await page.goto(origin+'/');
  return {requests,errors,unexpected,
    get authCount(){return authCount;},get logoutCount(){return logoutCount;},get draftReads(){return draftReads;},get metadataReads(){return metadataReads;},get draft(){return structuredClone(draft);},
    failDrafts(value:boolean){failDrafts=value;},failLogout(value:boolean){failLogout=value;},closeRegistration(){closeRegistration=true;},failMetadata(value:boolean){failMetadata=value;},
    holdAuth(){authGate=gate();return authGate;},holdLogout(){logoutGate=gate();return logoutGate;},holdBootstrap(){bootstrapGate=gate();return bootstrapGate;}
  };
}
const account=(page:Page)=>page.getByRole('dialog',{name:'本地账号',exact:true});
const manuscript=(page:Page)=>page.getByRole('textbox',{name:'连续稿件',exact:true});
async function fill(page:Page,password=PASSWORD){await account(page).getByLabel('用户名',{exact:true}).fill(USER);await account(page).getByLabel('密码',{exact:true}).fill(password);}
async function login(page:Page){await fill(page);await account(page).getByRole('button',{name:'登录并进入工作桌',exact:true}).click();await expect(manuscript(page)).toBeVisible();}
function clean(f:Awaited<ReturnType<typeof mount>>){expect(f.unexpected).toEqual([]);expect(f.errors).toEqual([]);}

test('first local registration confirms password, prevents duplicate submit, and waits for authenticated bootstrap',async({page})=>{
  const f=await mount(page,{registered:false});
  await expect(account(page)).toContainText('本机工作空间');await expect(page.getByLabel('引导令牌')).toHaveCount(0);
  await account(page).getByRole('button',{name:'注册本地账号',exact:true}).click();await fill(page);
  await expect(account(page).getByLabel('密码',{exact:true})).toHaveAttribute('autocomplete','new-password');
  await account(page).getByLabel('确认密码',{exact:true}).fill('different-password');
  await account(page).getByRole('button',{name:'注册并进入工作桌',exact:true}).click();
  await expect(account(page).getByRole('alert')).toHaveText('两次输入的密码不一致。');expect(f.authCount).toBe(0);
  await account(page).getByLabel('确认密码',{exact:true}).fill(PASSWORD);
  const held=f.holdAuth(),bootstrap=f.holdBootstrap();
  try{
    await account(page).getByRole('button',{name:'注册并进入工作桌',exact:true}).click();await expect.poll(()=>f.authCount).toBe(1);
    await expect(account(page).getByRole('button',{name:'正在打开工作桌…'})).toBeDisabled();
    await expect(account(page).getByRole('button',{name:'返回登录'})).toBeDisabled();
    await account(page).evaluate(form=>form.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true})));expect(f.authCount).toBe(1);
    held.release();await expect.poll(()=>f.requests.some(r=>r.input.action==='desk.bootstrap')).toBe(true);
    await expect(account(page)).toBeVisible();await expect(page.getByRole('button',{name:'新建项目',exact:true})).toBeDisabled();
    bootstrap.release();await expect(manuscript(page)).toBeVisible();await expect(account(page)).toHaveCount(0);
    expect(f.requests.filter(r=>r.path==='/api/auth/register')).toHaveLength(1);clean(f);
  }finally{held.release();bootstrap.release();}
});

test('wrong password stays on login; successful login uses username autocomplete and no token input',async({page})=>{
  const f=await mount(page);
  await expect(account(page).getByLabel('用户名',{exact:true})).toHaveAttribute('autocomplete','username');
  await expect(account(page).getByLabel('密码',{exact:true})).toHaveAttribute('autocomplete','current-password');
  await expect(account(page).getByRole('button',{name:'注册本地账号'})).toHaveCount(0);
  await fill(page,'incorrect-password');await account(page).getByRole('button',{name:'登录并进入工作桌'}).click();
  await expect(account(page).getByRole('alert')).toHaveText('用户名或密码不正确');await expect(manuscript(page)).toHaveCount(0);
  await login(page);expect(f.authCount).toBe(2);clean(f);
});

test('a simultaneous first registration closes registration and returns to password login',async({page})=>{
  const f=await mount(page,{registered:false});
  await account(page).getByRole('button',{name:'注册本地账号'}).click();await fill(page);await account(page).getByLabel('确认密码').fill(PASSWORD);f.closeRegistration();
  await account(page).getByRole('button',{name:'注册并进入工作桌'}).click();
  await expect(account(page).getByRole('alert')).toContainText('已建立账号');await expect(account(page).getByLabel('确认密码')).toHaveCount(0);
  await expect(account(page).getByLabel('密码',{exact:true})).toHaveValue('');await expect(account(page).getByRole('button',{name:'注册本地账号'})).toHaveCount(0);
  await login(page);clean(f);
});

test('an instance without local account support explains the boundary and disables credentials',async({page})=>{
  const f=await mount(page,{enabled:false});
  await expect(account(page)).toContainText('此实例尚未启用账号密码登录');await expect(account(page).getByLabel('密码',{exact:true})).toBeDisabled();
  await expect(account(page).getByRole('button',{name:'登录并进入工作桌'})).toBeDisabled();expect(f.authCount).toBe(0);clean(f);
});

test('pending logout retains the workdesk, saves drafts before CSRF logout, then discards cached sessions',async({page})=>{
  const f=await mount(page,{authenticated:true});await expect(manuscript(page)).toBeVisible();
  await manuscript(page).locator('[data-block-id="B"]').click();await page.keyboard.press('End');await page.keyboard.insertText('，本地新输入');
  const draftText=(await manuscript(page).textContent())!,held=f.holdLogout();
  try{
    await page.getByRole('button',{name:'退出登录',exact:true}).click();await expect.poll(()=>f.logoutCount).toBe(1);
    await expect(manuscript(page)).toBeVisible();await expect(manuscript(page)).toHaveText(draftText);await expect(page.getByLabel('当前项目')).toHaveValue(project.id);
    await expect(page.getByLabel('当前项目')).toBeDisabled();expect(await manuscript(page).evaluate(el=>!!el.closest('[inert]'))).toBe(true);
    const logoutIndex=f.requests.findIndex(r=>r.path==='/api/auth/logout');expect(f.requests.slice(0,logoutIndex).some(r=>r.input.action==='desk.drafts.write'&&r.input.value.manuscript.dirty)).toBe(true);
    held.release();await expect(account(page)).toBeVisible();await expect(manuscript(page)).toHaveCount(0);await expect(page.getByLabel('当前项目').locator('option')).toHaveCount(1);
    expect(new URL(page.url()).searchParams.has('project')).toBe(false);
    await page.waitForTimeout(300);expect(f.requests.slice(logoutIndex+1).filter(r=>r.path==='/api/action')).toEqual([]);
    await login(page);await expect(manuscript(page)).toHaveText(draftText);expect(f.draftReads).toBe(2);clean(f);
  }finally{held.release();}
});

test('draft persistence failure blocks logout, keeps native edits, and permits explicit retry',async({page})=>{
  const f=await mount(page,{authenticated:true});await expect(manuscript(page)).toBeVisible();f.failDrafts(true);
  await manuscript(page).locator('[data-block-id="B"]').click();await page.keyboard.press('End');await page.keyboard.insertText('，未同步的修改');const text=(await manuscript(page).textContent())!;
  await page.getByRole('button',{name:'退出登录',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'未能退出登录'})).toBeVisible();
  expect(f.logoutCount).toBe(0);await expect(manuscript(page)).toHaveText(text);expect(await manuscript(page).evaluate(el=>!!el.closest('[inert]'))).toBe(false);
  f.failDrafts(false);await page.getByRole('button',{name:'退出登录',exact:true}).click();await expect(account(page)).toBeVisible();await login(page);await expect(manuscript(page)).toHaveText(text);clean(f);
});

test('logout HTTP failure preserves the same workdesk and draft rather than clearing it early',async({page})=>{
  const f=await mount(page,{authenticated:true});await expect(manuscript(page)).toBeVisible();f.failLogout(true);
  await page.getByRole('button',{name:'退出登录',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'暂时无法退出'})).toBeVisible();
  await expect(manuscript(page)).toHaveText('独立稿件原始独立稿件');expect(f.draftReads).toBe(1);await expect(account(page)).toHaveCount(0);
  f.failLogout(false);await page.getByRole('button',{name:'退出登录',exact:true}).click();await expect(account(page)).toBeVisible();clean(f);
});

test('a late local mutation during logout is retained for re-login and is never cleared as saved',async({page})=>{
  const f=await mount(page,{authenticated:true});await expect(manuscript(page)).toBeVisible();const held=f.holdLogout();
  try{
    await page.getByRole('button',{name:'退出登录',exact:true}).click();await expect.poll(()=>f.logoutCount).toBe(1);
    await page.evaluate(()=>(window as any).accountTest.lateEdit());held.release();await expect(account(page)).toBeVisible();
    await expect(page.getByRole('alert').filter({hasText:'较新草稿仍保留'})).toBeVisible();await login(page);await expect(manuscript(page)).toContainText('迟到的手改仍需保留');expect(f.draftReads).toBe(1);clean(f);
  }finally{held.release();}
});
