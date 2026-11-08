"""State transitions must be explicit, version-bound, scoped and reversible by revision."""
import copy
import tempfile
import unittest
from research_partner.app import App
from research_partner.store import Problem

class ResearchNodes(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.app=App(self.tmp.name)
        self.p=self.app.store.create('project','Egg');self.other=self.app.store.create('project','Other');self.n=0
    def action(self,name,**fields):
        self.n+=1
        return self.app.dispatch({'action':name,'project_id':self.p['id'],'request_key':str(self.n),**fields})
    def q(self,title='Which method?',parent=None):
        return self.action('workbench.question.create',title=title,parent_id=parent)
    def full(self,q):
        return self.app.store.save(q['id'],q['revision'],content={**q['content'],'qaec':{'Q':q['title'],'A':'Compare','E':'7 of 10','C':'Limited answer'}},merge=False)
    def read(self):return self.app.dispatch({'action':'workbench.progress.read','project_id':self.p['id']})
    def node(self,q,p):return next(x for x in self.read()['questions'] if x['id']==q['id'])['parts'][p]['node']
    def save(self,q,p,state='review',**extra):
        q=self.app.store.get(q['id']);node=self.node(q,p)
        return self.action('workbench.node.save',question_id=q['id'],part=p,expected_revision=q['revision'],title=q['title'] if p=='Q' else q['metadata'].get('research_nodes',{}).get(p,{}).get('title','Title '+p),status=state,
            expected_dependencies=[{'id':d['id'],'signature':d['signature']} for d in node['dependencies']],confirmation_note='Checked saved content and scope',answers_question=True,**extra)['question']
    def complete(self,q):
        for p in ('A','E','C','Q'):q=self.save(q,p,'completed')
        return q
    def test_reads_do_not_make_old_text_complete(self):
        q=self.full(self.q());v=self.read()['questions'][0]
        self.assertTrue(all(v['parts'][p]['node']['status']=='unmarked' for p in ('A','E','C')))
        self.assertEqual(self.app.store.get(q['id'])['revision'],q['revision'])
    def test_q_requires_c_and_c_requires_checked_evidence(self):
        q=self.full(self.q())
        for p in ('Q','C'):
            with self.assertRaises(Problem) as e:self.save(q,p,'completed')
            self.assertEqual(e.exception.code,'dependencies_unmet')
        q=self.save(q,'E','completed');q=self.save(q,'C','completed');q=self.save(q,'Q','completed')
        self.assertEqual(self.node(q,'Q')['status'],'completed')
        self.assertTrue(self.node(q,'Q')['confirmation']['note'])
    def test_q_answer_attestation_is_required_even_after_c(self):
        q=self.full(self.q());q=self.save(q,'E','completed');q=self.save(q,'C','completed');node=self.node(q,'Q')
        with self.assertRaises(Problem):self.action('workbench.node.save',question_id=q['id'],part='Q',expected_revision=q['revision'],title=q['title'],status='completed',confirmation_note='Done',expected_dependencies=[{'id':d['id'],'signature':d['signature']} for d in node['dependencies']])
        self.assertNotEqual(self.node(q,'Q')['status'],'completed')
    def test_changed_evidence_invalidates_only_actual_downstream(self):
        q=self.complete(self.full(self.q()));other=self.complete(self.full(self.q('Other Q')))
        q=self.app.store.save(q['id'],q['revision'],content={**q['content'],'qaec':{**q['content']['qaec'],'E':'New evidence contradicts'}},merge=False)
        for p in ('E','C','Q'):self.assertEqual(self.node(q,p)['status'],'stale')
        self.assertEqual(self.node(q,'A')['status'],'completed');self.assertEqual(self.node(other,'Q')['status'],'completed')
        self.assertEqual(q['content']['qaec']['C'],'Limited answer')
        for p in ('E','C','Q'):q=self.save(q,p,'completed')
        self.assertEqual(self.node(q,'Q')['status'],'completed')
    def test_dependency_changes_and_cycles_fail_atomically(self):
        q=self.full(self.q());deps=[{'question_id':q['id'],'part':'A','kind':'requires'}]
        q=self.save(q,'E','active',dependencies=deps)
        with self.assertRaises(Problem) as e:self.save(q,'A','review',dependencies=[{'question_id':q['id'],'part':'Q','kind':'requires'}])
        self.assertEqual(e.exception.code,'dependency_cycle')
        self.assertNotIn('A',self.app.store.get(q['id'])['metadata']['research_nodes'])
    def test_stale_dependency_pin_is_rejected(self):
        q=self.full(self.q());q=self.save(q,'E','completed');node=self.node(q,'C');old=[{'id':d['id'],'signature':d['signature']} for d in node['dependencies']]
        q=self.save(q,'E','completed')
        with self.assertRaises(Problem) as e:self.action('workbench.node.save',question_id=q['id'],part='C',expected_revision=q['revision'],title='Answer',status='completed',confirmation_note='Checked',expected_dependencies=old)
        self.assertEqual(e.exception.code,'dependency_conflict')
    def test_paused_or_archived_dependency_blocks_completed_target(self):
        source=self.complete(self.full(self.q('Source')));target=self.full(self.q('Target'))
        target=self.save(target,'A','active',dependencies=[{'question_id':source['id'],'part':'C','kind':'limits'}]);target=self.save(target,'A','completed',dependencies=[{'question_id':source['id'],'part':'C','kind':'limits'}])
        self.app.store.save(source['id'],source['revision'],archived=True)
        node=self.node(target,'A');self.assertEqual(node['status'],'stale');self.assertIn('blocked',node['flags']);self.assertFalse(node['dependencies'][0]['available'])
    def test_root_preserves_children_bodies_and_numbering(self):
        a=self.full(self.q());child=self.q('Sub',a['id']);b=self.q('Generalization')
        p=self.app.store.get(self.p['id']);result=self.action('workbench.root.set',expected_project_revision=p['revision'],title='Article question',attach_roots=True,expected_roots=[{'id':x['id'],'revision':x['revision']} for x in (a,b)])
        root=result['question'];v=self.read();self.assertEqual(v['root_question_id'],root['id']);self.assertEqual([x['number'] for x in v['questions']],['Q','Q1','Q1.1','Q2'])
        self.assertEqual(self.app.store.get(a['id'])['content'],a['content'])
        new=self.q('New top question');self.assertEqual(new['metadata']['parent_question_id'],root['id'])
    def test_root_conflict_rolls_back_new_root_and_attachments(self):
        q=self.q();before=len(self.app.store.objects());p=self.app.store.get(self.p['id'])
        with self.assertRaises(Problem):self.action('workbench.root.set',expected_project_revision=p['revision'],title='Root',attach_roots=True,expected_roots=[])
        self.assertEqual(len(self.app.store.objects()),before);self.assertIsNone(self.app.store.get(q['id'])['metadata']['parent_question_id'])
    def test_cross_project_and_scoped_mutations_are_forbidden(self):
        q=self.full(self.q());foreign=self.app.dispatch({'action':'workbench.question.create','project_id':self.other['id'],'title':'Foreign','request_key':'foreign'})
        with self.assertRaises(Problem):self.save(q,'A',dependencies=[{'question_id':foreign['id'],'part':'E','kind':'supports'}])
        with self.assertRaises(Problem):self.app.dispatch({'action':'workbench.node.save','project_id':self.p['id'],'question_id':q['id'],'part':'A','expected_revision':q['revision'],'title':'A','status':'active','request_key':'scoped'},scope=[])
    def test_request_replay_and_status_history(self):
        q=self.full(self.q());fields={'question_id':q['id'],'part':'A','expected_revision':q['revision'],'title':'Specific analysis','status':'review','request_key':'stable'}
        a=self.app.dispatch({'action':'workbench.node.save','project_id':self.p['id'],**fields});b=self.app.dispatch({'action':'workbench.node.save','project_id':self.p['id'],**fields});self.assertTrue(b['replayed']);self.assertEqual(a['question']['revision'],b['question']['revision'])
        q=self.save(a['question'],'A','active');history=self.app.dispatch({'action':'workbench.progress.history','project_id':self.p['id'],'question_id':q['id']})
        self.assertNotIn(q['revision'],[x['revision'] for x in history['versions']['A']])

    def test_restoring_old_content_does_not_resurrect_confirmation(self):
        q=self.complete(self.full(self.q()));original=q['content']['qaec']['E']
        q=self.app.store.save(q['id'],q['revision'],content={**q['content'],'qaec':{**q['content']['qaec'],'E':'Changed'}},merge=False)
        q=self.app.store.save(q['id'],q['revision'],content={**q['content'],'qaec':{**q['content']['qaec'],'E':original}},merge=False)
        for p in ('E','C','Q'):self.assertEqual(self.node(q,p)['status'],'stale')
    def test_forged_confirmation_metadata_is_not_accepted(self):
        from research_partner.research_nodes import content_sha
        q=self.full(self.q());metadata=copy.deepcopy(q['metadata']);metadata['research_nodes']={'A':{'title':'A','status':'completed','dependencies':[]}}
        candidate={**q,'metadata':metadata};metadata['research_nodes']['A']['confirmation']={'id':'forged','actor':'someone','question_revision':q['revision'],'content_sha256':content_sha(candidate,'A'),'dependencies':[],'note':'Forged'}
        q=self.app.store.save(q['id'],q['revision'],metadata=metadata,merge=False)
        self.assertEqual(self.node(q,'A')['status'],'stale')
    def test_question_scope_change_requires_rechecking_owned_aec(self):
        q=self.complete(self.full(self.q()));q=self.app.store.save(q['id'],q['revision'],title='Different scope',merge=False)
        for p in ('A','E','C','Q'):self.assertEqual(self.node(q,p)['status'],'stale')
