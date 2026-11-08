import {test,expect} from '@playwright/test';
import {execFileSync} from 'node:child_process';
import {mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
const origin=process.env.EXPLORATION_TEST_URL||'';
const workspace=process.env.EXPLORATION_TEST_WORKSPACE||'';
const config=process.env.EXPLORATION_TEST_CONFIG||'';
const python=resolve('../.venv/bin/python');
const evidence=resolve('../.private/research-exploration/evidence');
test.use({reducedMotion:'reduce',launchOptions:{executablePath:process.env.PW_BROWSER_EXECUTABLE}});
test.skip(!origin||!workspace||!config,'Requires an isolated workbench-only fixture; never run against user data.');


async function restoreExplorationDraft(page:any,project:any){
 await page.evaluate((id:string)=>{const view={id:'exploration:draft',kind:'exploration',title:'探索研究问题'};sessionStorage.setItem('acapartner.unified.tabs:'+id,JSON.stringify({views:[view],active:view.id}));},project.id);await page.reload();
}

test('vague intent, lost responses, revision, adoption and refresh form one project-scoped workflow',async({page,request})=>{
 test.setTimeout(90000);mkdirSync(evidence,{recursive:true});const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const state=await(await request.get(origin+'/api/state')).json();
 async function api(action:string,fields:any={}){const response=await request.post(origin+'/api/action',{headers:{'X-CSRF-Token':state.csrf,Origin:origin},data:{action,...fields}});const body=await response.json();expect(response.ok(),JSON.stringify(body)).toBeTruthy();return body.result;}
 const project=await api('project.create',{title:'探索闭环 '+Date.now()});
 let submitted:any=null,lostSubmit=true,lostAdopt=true;
 const submits:any[]=[],adopts:any[]=[];
 await page.route('**/api/action',async route=>{
  const fields=route.request().postDataJSON();
  if(fields.action==='desk.review.read'){const response=await route.fetch(),body=await response.json();body.result.runtime_running=true;return route.fulfill({response,json:body});}
  if(fields.action==='research.exploration.submit'){submits.push(fields);const response=await route.fetch(),body=await response.json();submitted=body.result;if(lostSubmit){lostSubmit=false;return route.abort('failed');}return route.fulfill({response,json:body});}
  if(fields.action==='research.exploration.adopt'){adopts.push(fields);const response=await route.fetch();if(lostAdopt){lostAdopt=false;return route.abort('failed');}return route.fulfill({response});}
  return route.continue();
 });
 await page.goto(origin+'/?project='+project.id);await restoreExplorationDraft(page,project);
 const intent=page.getByRole('textbox',{name:'研究想法',exact:true});await intent.fill('我想研究怎么把鸡蛋煮得更好。');await page.reload();await expect(intent).toHaveValue('我想研究怎么把鸡蛋煮得更好。');
 await page.getByRole('button',{name:'核对探索输入',exact:true}).click();await expect(page.getByRole('region',{name:'探索输入预览'})).toContainText('0 份固定材料');await page.screenshot({path:evidence+'/input-light.png'});
 await page.getByRole('button',{name:'开始探索',exact:true}).click();await expect(page.getByRole('button',{name:'核对同一探索请求',exact:true})).toBeVisible();await expect(intent).toBeDisabled();await page.reload();await page.getByRole('button',{name:'核对同一探索请求',exact:true}).click();await expect(page.getByRole('heading',{name:'从一个想法开始',exact:true})).toBeVisible();await expect(page.getByText('等待执行。可以切换内容，任务和结果会保留。',{exact:true})).toBeVisible();expect(submits).toHaveLength(2);expect(submits[0]).toEqual(submits[1]);
 function complete(){execFileSync(python,[resolve('../tests/helpers/complete_exploration.py'),workspace,config,submitted.id],{cwd:resolve('..'),env:process.env});}
 complete();await page.getByRole('button',{name:'刷新探索状态',exact:true}).click();await expect(page.getByRole('heading',{name:'研究问题提案',exact:true})).toBeVisible();await expect(page.getByRole('heading',{name:'主要关注口感、营养还是效率？',exact:true})).toBeVisible();expect((await api('workbench.research.read',{project_id:project.id})).questions).toHaveLength(0);await page.screenshot({path:evidence+'/proposal-light.png'});
 const firstTask=submitted.id;await page.getByRole('textbox',{name:'补充研究目标',exact:true}).fill('关注口感，目标是蛋白凝固、蛋黄柔软。');await page.getByRole('button',{name:'核对下一轮输入',exact:true}).click();await expect(intent).toHaveValue('关注口感，目标是蛋白凝固、蛋黄柔软。');await page.getByRole('button',{name:'核对探索输入',exact:true}).click();await page.getByRole('button',{name:'开始探索',exact:true}).click();await expect(page.getByText('等待执行。可以切换内容，任务和结果会保留。',{exact:true})).toBeVisible();expect(submitted.payload.context.exploration.previous_proposal.task_id).toBe(firstTask);complete();await page.getByRole('button',{name:'刷新探索状态',exact:true}).click();
 await expect(page.getByRole('heading',{name:'哪种煮蛋方法能够使蛋白凝固、蛋黄柔软？',exact:true})).toBeVisible();await page.getByRole('checkbox',{name:'选择候选 哪种煮蛋方法能够使蛋白凝固、蛋黄柔软？',exact:true}).check();await page.getByRole('textbox',{name:'研究标题 texture',exact:true}).fill('哪种方法可以让同一枚蛋的蛋白凝固、蛋黄柔软？');await page.reload();await expect(page.getByRole('textbox',{name:'研究标题 texture',exact:true})).toHaveValue('哪种方法可以让同一枚蛋的蛋白凝固、蛋黄柔软？');await page.getByRole('button',{name:'将所选方向加入研究 · 1',exact:true}).click();await expect(page.getByRole('button',{name:'核对同一采用请求',exact:true})).toBeVisible();await page.reload();await page.getByRole('button',{name:'核对同一采用请求',exact:true}).click();await expect(page.getByRole('button',{name:/已加入研究 · 哪种方法/})).toBeVisible();expect(adopts).toHaveLength(2);expect(adopts[0]).toEqual(adopts[1]);
 const research=await api('workbench.research.read',{project_id:project.id});expect(research.questions).toHaveLength(1);const q=research.questions[0];expect(q.content.qaec.E).toBe('');expect(q.content.qaec.C).toBe('');expect(q.content.research_status).toBe('open');expect(q.metadata.origin.root_task_id).toBe(firstTask);await expect(page.locator('.wb-q-number')).toHaveText(['Q1']);await page.screenshot({path:evidence+'/adopted-light.png'});await page.getByRole('button',{name:'新的研究想法',exact:true}).click();await expect(page.getByRole('textbox',{name:'研究想法',exact:true})).toHaveValue('');await page.getByRole('tab',{name:'完善问题提案',exact:true}).click();
 await page.getByRole('button',{name:/已加入研究 · 哪种方法/}).click();await expect(page.getByRole('heading',{name:q.title,exact:true})).toBeVisible();await page.getByRole('button',{name:'研究探索提案 · r1',exact:true}).click();await expect(page.getByRole('heading',{name:'研究问题提案',exact:true})).toBeVisible();await page.getByRole('button',{name:'切换明暗主题',exact:true}).click();await page.screenshot({path:evidence+'/proposal-dark.png'});await page.setViewportSize({width:390,height:844});await page.screenshot({path:evidence+'/proposal-mobile.png'});expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();expect(await page.locator('.exploration-document:visible').evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBeTruthy();expect(errors).toEqual([]);
});

test('saved sources survive a changed goal; stale preview and late reads preserve project scope',async({page,request})=>{
 const state=await(await request.get(origin+'/api/state')).json();
 async function api(action:string,fields:any={}){const response=await request.post(origin+'/api/action',{headers:{'X-CSRF-Token':state.csrf,Origin:origin},data:{action,...fields}});const body=await response.json();expect(response.ok(),JSON.stringify(body)).toBeTruthy();return body.result;}
 const project=await api('project.create',{title:'已有材料与新目标 '+Date.now()}),other=await api('project.create',{title:'另一个项目 '+Date.now()});
 const source=await api('object.create',{kind:'note',title:'首次操作记录',project_id:project.id,content:{text:'记录鸡蛋质量与下锅温度。尚无不同初温的对照结果。'}});
 let submitted:any=null;
 await page.route('**/api/action',async route=>{const fields=route.request().postDataJSON();if(fields.action==='desk.review.read'){const response=await route.fetch(),body=await response.json();body.result.runtime_running=true;return route.fulfill({response,json:body});}if(fields.action==='research.exploration.submit'){const response=await route.fetch(),body=await response.json();if(body.ok)submitted=body.result;return route.fulfill({response,json:body});}return route.continue();});
 await page.goto(origin+'/?project='+project.id);await restoreExplorationDraft(page,project);await page.getByRole('textbox',{name:'研究想法',exact:true}).fill('关注口感，看看已有操作记录能帮助提出什么问题。');await page.getByText('采用的保存材料 · 0 项',{exact:true}).click();await page.locator('.wb-exploration').getByLabel(/首次操作记录/).check();await page.getByRole('button',{name:'核对探索输入',exact:true}).click();
 const research=await api('workbench.research.read',{project_id:project.id});await api('workbench.background.save',{project_id:project.id,expected_revision:research.project.revision,background:'补充：先明确蛋白与蛋黄的目标质构。',request_key:crypto.randomUUID()});await page.getByRole('button',{name:'开始探索',exact:true}).click();await expect(page.locator('.wb-exploration').getByRole('alert')).toContainText('探索输入已变化');await expect(page.getByRole('textbox',{name:'研究想法',exact:true})).toHaveValue('关注口感，看看已有操作记录能帮助提出什么问题。');expect(submitted).toBeNull();
 await page.getByRole('button',{name:'核对探索输入',exact:true}).click();await page.getByRole('button',{name:'开始探索',exact:true}).click();await expect(page.getByText('等待执行。可以切换内容，任务和结果会保留。',{exact:true})).toBeVisible();execFileSync(python,[resolve('../tests/helpers/complete_exploration.py'),workspace,config,submitted.id],{cwd:resolve('..'),env:process.env});await page.getByRole('button',{name:'刷新探索状态',exact:true}).click();await page.getByRole('textbox',{name:'补充研究目标',exact:true}).fill('现在更关心方法对鸡蛋大小与下锅温度的适用范围。');await page.getByRole('button',{name:'核对下一轮输入',exact:true}).click();await page.getByRole('button',{name:'核对探索输入',exact:true}).click();await expect(page.getByRole('region',{name:'探索输入预览'})).toContainText('1 份固定材料');
 const preview=await page.evaluate(()=>Object.entries(localStorage).filter(([k])=>k.startsWith('acapartner.exploration.v1:')).map(([,v])=>{try{return JSON.parse(v);}catch{return {};}}).find(d=>d.previousTaskId&&d.request.includes('适用范围')));expect(preview.materials).toEqual([{id:source.id,revision:source.revision}]);expect(preview.preview.input.previous_proposal.original_request).toContain('关注口感');
 // Hold an old project's read across a project switch; it cannot adopt into the new project.
 await page.getByRole('button',{name:'前一份提案',exact:true}).click();let release:()=>void=()=>{};const gate=new Promise<void>(r=>{release=r;});let arrived:()=>void=()=>{};const waiting=new Promise<void>(r=>{arrived=r;});await page.route('**/api/action',async route=>{if(route.request().postDataJSON().action!=='research.exploration.read')return route.fallback();const response=await route.fetch();arrived();await gate;return route.fulfill({response});});await page.getByRole('button',{name:'刷新探索状态',exact:true}).click();await waiting;
 await page.getByRole('button',{name:/切换项目|选择项目/}).first().click();await page.getByRole('menuitem',{name:other.title,exact:true}).click();release();await expect(page.getByRole('heading',{name:other.title,exact:true})).toBeVisible();expect((await api('workbench.research.read',{project_id:other.id})).questions).toHaveLength(0);
});
