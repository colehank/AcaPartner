import {test,expect} from '@playwright/test';
const origin=process.env.NATIVE_DOCUMENTS_TEST_URL||'';
test.use({reducedMotion:'reduce',launchOptions:{executablePath:process.env.PW_BROWSER_EXECUTABLE}});
test.skip(!origin,'Requires an isolated local workbench.');
test('research Markdown opens an exact saved source and guards project identity and revision',async({page,request})=>{
 const state=await(await request.get(origin+'/api/state')).json();
 async function api(action:string,fields:any={}){const response=await request.post(origin+'/api/action',{headers:{'X-CSRF-Token':state.csrf,Origin:origin},data:{action,...fields}});const body=await response.json();expect(response.ok(),JSON.stringify(body)).toBeTruthy();return body.result;}
 const p=await api('project.create',{title:'研究来源链接 · 合成验收'}),other=await api('project.create',{title:'链接范围对照 · 合成验收'});
 const first=await api('object.create',{kind:'report',project_id:p.id,title:'有版本的依据',content:{markdown:'第一保存版：配对计数。'},metadata:{research_role:'analysis'}});
 await api('object.save',{id:first.id,expected_revision:first.revision,content:{markdown:'第二保存版：更新后的计数。'}});
 const guide=await api('object.create',{kind:'report',project_id:p.id,title:'来源导览',content:{markdown:`[固定依据](/?project=${p.id}&object=${first.id}&revision=1)\n\n[错误项目](/?project=${other.id}&object=${first.id})\n\n[无效修订](/?project=${p.id}&object=${first.id}&revision=-1)`}});
 const project=(await api('workbench.research.read',{project_id:p.id})).project;await api('project.feature',{project_id:p.id,object_id:guide.id,featured:true,expected_revision:project.revision});
 await page.goto(origin+'/?project='+p.id);await page.getByRole('button',{name:'来源导览',exact:true}).click();await page.getByRole('link',{name:'固定依据',exact:true}).click();await expect(page.locator('.document:visible')).toContainText('固定来源 · r1');await expect(page.locator('.document:visible')).toContainText('第一保存版：配对计数。');await expect(page.locator('.document:visible')).not.toContainText('第二保存版');
 await page.locator('[data-view-id="'+guide.id+'"]').click();await page.getByRole('link',{name:'错误项目',exact:true}).click();await expect(page.locator('.wb-error')).toContainText('不属于当前项目');await expect(page).toHaveURL(new RegExp(p.id));await expect(page.getByRole('heading',{name:'来源导览',exact:true})).toBeVisible();await page.getByRole('button',{name:'关闭错误提示'}).click();await page.getByRole('link',{name:'无效修订',exact:true}).click();await expect(page.locator('.wb-error')).toContainText('来源修订无效');await expect(page.getByRole('heading',{name:'来源导览',exact:true})).toBeVisible();
});

test('published Chinese manuscript paints with local PDF.js CMaps',async({page})=>{
 const project=process.env.SCIENTIFIC_EGG_TEST_PROJECT;
 test.skip(!project,'Run after publishing the scientific egg example.');
 const fontWarnings:string[]=[],maps:string[]=[];
 page.on('console',m=>{if(/translateFont failed|Error during font loading|cMapUrl/.test(m.text()))fontWarnings.push(m.text());});
 page.on('response',r=>{if(r.url().includes('/pdfjs/cmaps/')){expect(r.status()).toBe(200);maps.push(r.url());}});
 await page.goto(origin+'/?project='+project);await page.getByRole('heading',{name:'科学煮蛋 · 可复现研究示例',exact:true}).waitFor();
 await page.keyboard.press('Meta+k');await page.getByRole('combobox',{name:'搜索内容',exact:true}).fill('.tex');await page.getByRole('option').filter({hasText:/\.tex/}).first().click();
 await expect(page.locator('.native-pdf-pages canvas[data-rendered=true]')).toHaveCount(6,{timeout:30000});
 expect(maps.some(url=>/UniGB|Adobe-GB1/.test(url))).toBeTruthy();expect(fontWarnings).toEqual([]);
});
