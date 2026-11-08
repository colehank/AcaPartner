import {test,expect} from '@playwright/test';
import {mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
const origin=process.env.NATIVE_DOCUMENTS_TEST_URL||'',project=process.env.SCIENTIFIC_EGG_TEST_PROJECT||'';
test.skip(!origin||!project,'Requires the revised scientific egg case.');
test.use({reducedMotion:'reduce',launchOptions:{executablePath:process.env.PW_BROWSER_EXECUTABLE}});
test('egg case explains the goal, sorts numbered questions, and keeps each question understandable',async({page,request})=>{
 const captures=resolve('../.private/egg-case-refinement/review');mkdirSync(captures,{recursive:true});
 const state=await(await request.get(origin+'/api/state')).json();
 const response=await request.post(origin+'/api/action',{headers:{Origin:origin,'X-CSRF-Token':state.csrf},data:{action:'workbench.research.read',project_id:project}});
 const research=(await response.json()).result;
 expect(research.questions.map((q:any)=>q.number)).toEqual(['Q1','Q1.1','Q1.2','Q2','Q2.1','Q2.2','Q2.3']);
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin+'/?project='+project);await expect(page.getByRole('heading',{name:'科学煮蛋 · 可复现研究示例',exact:true})).toBeVisible();
 await expect(page.locator('.wb-q-number')).toHaveText(['Q1','Q1.1','Q1.2','Q2','Q2.1','Q2.2','Q2.3']);
 await expect(page.locator('.document:visible')).toContainText('蛋白凝固指数');await expect(page.locator('.document:visible')).toContainText('越高表示越软');
 await page.screenshot({path:captures+'/background.png',fullPage:true});
 for(const index of [0,3]){
  const q=research.questions[index];await page.locator('.wb-tree-name[aria-label="'+q.title+'"]').click();
  await expect(page.getByRole('heading',{name:q.title,exact:true})).toBeVisible();await expect(page.locator('.breadcrumbs:visible')).toHaveText('研究 / '+q.number);
  const question=page.locator('.qaec-section:visible').first();await expect(question).toContainText('7.5');await expect(question).toContainText('同一枚蛋');
  await expect(question).not.toContainText('这是合成数据研究问题');await expect(page.locator('.wb-research-view:visible')).not.toContainText('配对达标');
  await page.screenshot({path:captures+'/'+(index===0?'desktop':'question2')+'.png',fullPage:true});
 }
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'显示项目导航',exact:true}).click();
 await expect(page.locator('.wb-q-number')).toHaveText(['Q1','Q1.1','Q1.2','Q2','Q2.1','Q2.2','Q2.3']);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();await page.screenshot({path:captures+'/mobile.png',fullPage:true});
 expect(errors).toEqual([]);
});
