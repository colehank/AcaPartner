import {test,expect} from '@playwright/test';
import {researchCardPreview,researchCardCaption} from '../src/workbench/researchCardContent';

test('evidence excerpts retain method labels, denominators and column context',()=>{
 const body='| 煮法 | 蛋白 | 蛋黄 | 同时达标 |\n|---|---|---|---|\n| 沸水6分钟 |117/120|0/120|0/120|\n| 沸水12分钟 |120/120|8/120|8/120|\n| 恒温 |0/120|114/120|0/120|\n| 冷热交替 |120/120|45/120|45/120|';
 const p=researchCardPreview(body,'E');
 expect(p.table?.headers).toEqual(['煮法','同时达标']);
 expect(p.table?.rows).toEqual([['沸水6分钟','0/120'],['沸水12分钟','8/120'],['恒温','0/120'],['冷热交替','45/120']]);
 expect(p.table?.partial).toBe(true);
 expect(researchCardCaption({id:'e',kind:'E',status:'review'},[],[],p)).toBe('4 行结果 · 节选');
});

test('empty content and saved non-paragraph content are not confused',()=>{
 expect(researchCardPreview('','A').text).toBe('');
 expect(researchCardPreview('```python\nprint(45 / 120)\n```','A').text).toContain('点击查看');
 expect(researchCardPreview('**37.5%** 同时达标；不能外推新批次。\n\n[来源](/?object=x)','C').text).toBe('37.5% 同时达标；不能外推新批次。');
});

test('parent progress uses effective completed questions and leaf work stays separate',()=>{
 const q={id:'q',kind:'Q',status:'active',child_question_ids:['q1','q2']},nodes=[q,{id:'q1',kind:'Q',status:'completed'},{id:'q2',kind:'Q',status:'stale'}];
 expect(researchCardCaption(q,nodes,[],{text:''})).toBe('2 个子问题 · 1 个已回答');
 expect(researchCardCaption({id:'leaf',kind:'Q',status:'review'},[],[{src:'leaf',dst:'a',kind:'analyzes',active:true},{src:'c',dst:'leaf',kind:'answers',active:true},{src:'leaf',dst:'old',kind:'analyzes',active:false}],{text:''})).toBe('1 项分析 · 1 项结论');
});
