"""Unified workbench research projection keeps project scope and CAS authority."""
import tempfile
import unittest
from research_partner.app import App
from research_partner.store import Problem

class WorkbenchResearch(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=App(self.tmp.name)
        self.project=self.app.store.create('project','Synthetic study')
        self.other=self.app.store.create('project','Other study')
    def tearDown(self):self.tmp.cleanup()
    def call(self,action,scope=None,**data):
        return self.app.dispatch({'action':'workbench.'+action,'project_id':self.project['id'],**data},scope)
    def create(self,title='Question',key='q',parent=None):
        return self.call('question.create',title=title,parent_id=parent,request_key=key)
    def test_parent_and_child_both_have_independent_qaec(self):
        parent=self.create();child=self.create('Child','child',parent['id'])
        self.assertEqual(child['metadata']['parent_question_id'],parent['id'])
        saved=self.call('question.save',id=child['id'],expected_revision=child['revision'],title='Child',qaec={'Q':'Child','A':'Method','E':'Observation','C':'Tentative'},status='review',request_key='child-save')
        self.assertEqual(saved['content']['qaec']['C'],'Tentative')
        self.assertEqual(self.app.store.get(parent['id'])['content']['qaec']['C'],'')
        self.assertTrue(any(r['src']==parent['id'] and r['dst']==child['id'] for r in self.app.store.relations()))
    def test_replay_is_exact_and_conflict_preserves_saved_content(self):
        q=self.create();self.assertEqual(self.create()['id'],q['id'])
        data=dict(id=q['id'],expected_revision=q['revision'],title=q['title'],qaec={'Q':'Question','A':'','E':'','C':'Saved'},status='answered',request_key='save')
        saved=self.call('question.save',**data)
        self.assertEqual(self.call('question.save',**data)['revision'],saved['revision'])
        with self.assertRaises(Problem):self.call('question.save',**{**data,'request_key':'stale'})
        with self.assertRaises(Problem):self.create('Changed same key')
        self.assertEqual(self.app.store.get(q['id'])['content']['qaec']['C'],'Saved')
    def test_scope_parent_and_blocking_questions_are_separate(self):
        self.app.store.create('question','Task decision',self.project['id'])
        self.assertEqual(self.call('research.read')['questions'],[])
        with self.assertRaises(Problem):self.call('research.read',scope={self.other['id']})
        alien=self.app.store.create('concept','Alien',self.other['id'],metadata={'research_role':'research_question_v1'})
        before=len(self.app.store.objects(self.project['id']))
        with self.assertRaises(Problem):self.create(parent=alien['id'])
        self.assertEqual(len(self.app.store.objects(self.project['id'])),before)
    def test_background_keeps_other_project_content_and_requires_current_revision(self):
        p=self.app.store.get(self.project['id']);saved=self.call('background.save',expected_revision=p['revision'],background='Known facts',request_key='background')
        self.assertEqual(self.call('research.read')['background'],'Known facts')
        with self.assertRaises(Problem):self.call('background.save',expected_revision=p['revision'],background='Stale',request_key='stale')
        self.assertEqual(saved['content']['background'],'Known facts')
    def test_question_save_cannot_target_project(self):
        p=self.app.store.get(self.project['id'])
        with self.assertRaises(Problem):self.call('question.save',id=p['id'],expected_revision=p['revision'],title='Illegal',qaec={'Q':'','A':'','E':'','C':''},status='open',request_key='illegal')

    def test_existing_workbench_file_commands_keep_their_original_route(self):
        from research_partner.article_workspace import initialize_output
        with self.app.store.transaction() as c:
            initialize_output(self.app.store,c,self.project)
        result=self.app.dispatch({'action':'workbench.files','project_id':self.project['id']})
        self.assertIsInstance(result,dict)
        self.assertNotIn('questions',result)

    def test_numbering_uses_sibling_order_and_survives_edits(self):
        first=self.create('Z first','first');child=self.create('Child','child',first['id'])
        grandchild=self.create('Nested','nested',child['id'])
        for i in range(2,12):self.create('Root '+str(i),'root-'+str(i))
        self.call('question.save',id=first['id'],expected_revision=first['revision'],title='Renamed',qaec={'Q':'Renamed','A':'','E':'','C':''},status='review',request_key='rename')
        questions=self.call('research.read')['questions']
        self.assertEqual([q['number'] for q in questions],['Q1','Q1.1','Q1.1.1']+['Q'+str(i) for i in range(2,12)])
        self.assertEqual(questions[0]['id'],first['id'])
        self.assertNotIn('number',self.app.store.get(first['id']))
        self.assertEqual(questions[2]['tree_parent_id'],child['id'])
        self.assertEqual(questions[2]['id'],grandchild['id'])

    def test_legacy_order_explicit_order_and_archived_parent(self):
        a=self.app.store.create('concept','Z legacy',self.project['id'],metadata={'research_role':'research_question_v1'})
        b=self.app.store.create('concept','A legacy',self.project['id'],metadata={'research_role':'research_question_v1'})
        c=self.create('New','new')
        self.assertEqual([q['id'] for q in self.call('research.read')['questions']],[a['id'],b['id'],c['id']])
        self.app.store.save(b['id'],b['revision'],metadata={**b['metadata'],'workbench':{'order':0}},merge=False)
        child=self.create('Orphan','orphan',a['id'])
        latest=self.app.store.get(a['id']);self.app.store.save(a['id'],latest['revision'],archived=True)
        questions=self.call('research.read')['questions']
        orphan=next(q for q in questions if q['id']==child['id'])
        self.assertIsNone(orphan['tree_parent_id'])
        self.assertNotIn('.',orphan['number'])
