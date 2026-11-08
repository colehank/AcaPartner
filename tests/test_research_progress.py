"""Read-only progress must describe actual field changes, never invented progress."""
import copy
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from research_partner.app import App
from research_partner.runtime import Runtime
from research_partner.store import Problem, digest


class ResearchProgress(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=App(self.tmp.name, {'providers':{'local':{'route':'codex','executable':sys.executable,'authorized':True}},'default_provider':'local'})
        self.p=self.app.store.create('project','煮蛋研究');self.other=self.app.store.create('project','Other')
        self.counter=0
    def call(self, action='read', **data):
        return self.app.dispatch({'action':'workbench.progress.'+action,'project_id':self.p['id'],**data})
    def q(self,title='哪种煮法兼顾蛋白凝固与蛋黄柔软？',parent=None):
        self.counter+=1
        return self.app.dispatch({'action':'workbench.question.create','project_id':self.p['id'],'title':title,'parent_id':parent,'request_key':'q'+str(self.counter)})
    def save(self,q,**patch):
        return self.app.store.save(q['id'],q['revision'],content={**q['content'],'qaec':{**q['content']['qaec'],**patch}},merge=False)
    def test_empty_read_has_no_side_effects_or_fake_nodes(self):
        with self.app.store.connect() as c:before={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('objects','revisions','events','kv','tasks')}
        value=self.call();self.assertEqual(value['questions'],[]);self.assertEqual(value['recent_changes'],[])
        self.assertFalse(value['semantics']['scientific_approval'])
        with self.app.store.connect() as c:self.assertEqual(before,{t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in before})
    def test_status_only_save_is_not_a_new_aec_version(self):
        q=self.save(self.q(),A='比较不同方法。',E='逐枚记录。',C='当前结果有限。')
        for status in ('active','review','answered'):
            q=self.app.store.save(q['id'],q['revision'],content={**q['content'],'research_status':status},merge=False)
        value=self.call()['questions'][0]
        self.assertEqual(value['revision'],5)
        for part in ('A','E','C'):
            self.assertEqual([x['revision'] for x in value['parts'][part]['versions']],[2])
            self.assertEqual(value['parts'][part]['last_changed_revision'],2)
        self.assertNotIn(5,[r['revision'] for r in self.call()['recent_changes']])
    def test_real_changes_clear_and_restore_keep_actual_order_and_identity(self):
        q=self.save(self.q(),A='原思路');q=self.save(q,A='新思路');q=self.save(q,A='')
        q=self.app.store.restore(q['id'],2,q['revision']);value=self.call()['questions'][0]['parts']['A']
        self.assertEqual([v['revision'] for v in value['versions']],[5,4,3]);self.assertFalse(value['empty'])
        self.assertEqual(value['versions'][0]['change_kind'],'restored');self.assertTrue(value['versions'][1]['empty'])
        history=self.call('history',question_id=q['id'])['versions']['A']
        for v in history:self.assertEqual(v['sha256'],digest(self.app.store.get(q['id'],v['revision'])))
    def test_evidence_newer_than_c_hints_review_without_changing_conclusion(self):
        q=self.save(self.q(),A='计划',E='第一批记录',C='已有有限结论')
        q=self.save(q,E='第二批记录有差异');self.assertTrue(self.call()['questions'][0]['review_hint'])
        self.assertEqual(self.app.store.get(q['id'])['content']['qaec']['C'],'已有有限结论')
        q=self.save(q,C='复核后的结论');self.assertFalse(self.call()['questions'][0]['review_hint'])
    def test_recursive_qs_have_independent_histories_and_stable_numbering(self):
        parent=self.q();child=self.q('蛋白凝固的条件？',parent['id']);sibling=self.q('初温的泛化性？')
        self.save(child,E='子问题的记录',C='子问题的回答')
        value=self.call()['questions'];self.assertEqual([q['number'] for q in value],['Q1','Q1.1','Q2'])
        self.assertTrue(value[0]['parts']['C']['empty']);self.assertFalse(value[1]['parts']['C']['empty'])
        self.assertEqual(value[1]['parent_id'],parent['id'])
    def test_history_pages_do_not_invent_changes_at_window_boundaries(self):
        q=self.save(self.q(),A='只在r2修改过')
        for i in range(105):q=self.app.store.save(q['id'],q['revision'],content={**q['content'],'research_status':'open' if i%2 else 'active'},merge=False)
        item=self.call()['questions'][0]
        self.assertFalse(item['history_complete']);self.assertEqual(item['parts']['A']['versions'],[])
        self.assertIsNone(item['parts']['A']['last_changed_revision']);self.assertFalse(item['parts']['A']['empty'])
        versions=[];cursor=None
        while True:
            page=self.call('history',question_id=q['id'],**({'before_revision':cursor} if cursor else {}));versions+=page['versions']['A'];cursor=page['next_before_revision']
            if cursor is None:break
        self.assertEqual([v['revision'] for v in versions],[2])
    def test_foreign_archived_or_unsupported_requests_are_rejected(self):
        q=self.q();self.app.store.save(q['id'],q['revision'],archived=True)
        self.assertEqual(self.call()['questions'],[])
        with self.assertRaises(Problem):self.call('history',question_id=q['id'])
        other=self.app.store.create('concept','foreign',self.other['id'],{'qaec':{'Q':'foreign','A':'','E':'','C':''}},{'research_role':'research_question_v1'})
        with self.assertRaises(Problem):self.call('history',question_id=other['id'])
        with self.assertRaises(Problem):self.call('read',surprise=True)
        with self.assertRaises(Problem):self.app.dispatch({'action':'workbench.progress.read','project_id':self.p['id']},scope=[])
    def test_metadata_without_adoption_ledger_is_not_adoption(self):
        q=self.q();metadata={**q['metadata'],'research_work_adoptions':{'C':{'task_id':'TASK-fake','change_id':'c'}}}
        self.app.store.save(q['id'],q['revision'],content={**q['content'],'qaec':{**q['content']['qaec'],'C':'人工内容'}},metadata=metadata,merge=False)
        v=self.call()['questions'][0]['parts']['C']['versions'][0]
        self.assertEqual(v['change_kind'],'edited');self.assertIsNone(v['origin'])
    def test_real_adoption_is_traceable_but_later_manual_edit_is_separate(self):
        q=self.q();source=self.app.store.create('report','保存的结果',self.p['id'],{'markdown':'本批7/10同时达标。'})
        fields={'project_id':self.p['id'],'request':'核对已有结果，提出有限的C。','materials':[{'id':source['id'],'revision':1}], 'questions':[{'id':q['id'],'revision':q['revision'],'parts':['C']}]}
        preview=self.app.dispatch({'action':'research.work.preview',**fields});task=self.app.dispatch({'action':'research.work.submit',**fields,'input_pin':preview['input_pin'],'request_key':'work'})
        candidate={'title':'阶段候选','kind':'note','research_update':{'version':1,'summary':'核对已有记录。','changes':[{'id':'c','question_id':q['id'],'part':'C','mode':'replace','text':'当前批次7/10，不外推。','rationale':'已有记录。','basis':'supported','source_refs':[{'id':source['id'],'revision':1}]}],'limitations':['只有一个批次。']}}
        runtime=Runtime(self.app);self.assertEqual(runtime.claim(),task['id'])
        with patch('research_partner.providers.Providers.call',return_value={'text':json.dumps(candidate),'receipt':{'route':'codex','session_id':'progress-test','returncode':0,'usage':[]}}):runtime.execute(task['id'])
        view=self.app.dispatch({'action':'research.work.read','project_id':self.p['id'],'task_id':task['id']})
        adopted=self.app.dispatch({'action':'research.work.adopt','project_id':self.p['id'],'task_id':task['id'],'proposal_ref':{k:view['proposal'][k] for k in ('id','revision','sha256')},'changes':[{'id':'c','text':'人工采用的有限结论。'}],'expected_questions':[{k:view['questions'][0][k] for k in ('id','revision','sha256')}],'request_key':'adopt'})['questions'][0]
        origin=self.call()['questions'][0]['parts']['C']['versions'][0]['origin']
        self.assertTrue(origin['available']);self.assertEqual(origin['task_id'],task['id']);self.assertEqual(origin['source_refs'][0]['id'],source['id'])
        self.save(adopted,C='后续人工修订。');items=self.call()['questions'][0]['parts']['C']['versions']
        self.assertEqual(items[0]['change_kind'],'edited');self.assertIsNone(items[0]['origin']);self.assertEqual(items[1]['change_kind'],'adopted')


if __name__=='__main__':unittest.main()
