import copy
import tempfile
import unittest
from research_partner.app import App
from research_partner.store import Problem

class FreeGraph(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.app=App(self.tmp.name)
        self.p=self.app.store.create('project','Egg');self.n=0
    def read(self):return self.app.dispatch({'action':'workbench.graph.read','project_id':self.p['id']})
    def call(self,action,**kw):
        self.n+=1;g=self.read()
        return self.app.dispatch({'action':'workbench.graph.'+action,'project_id':self.p['id'],'expected_project_revision':g['project']['revision'],'request_key':str(self.n),**kw})
    def node(self,kind,title,parent=None,relation=None):
        result=self.call('node.create',kind=kind,title=title,body='Content '+title,**({'parent_id':parent,'relation_kind':relation} if parent else {}))
        return result['node_id']
    def edge(self,src,dst,kind):return self.call('edge.create',src=src,dst=dst,kind=kind,rationale='Scoped relation')['edge_id']
    def get(self,i):return next(n for n in self.read()['nodes'] if n['id']==i)
    def save(self,i,status='completed',**kwargs):
        n=self.get(i)
        return self.call('node.save',id=i,expected_revision=n['revision'],title=n['title'],body=n['body'],status=status,
                         expected_dependencies=n['dependencies'],confirmation_note='Checked exact result within stated scope',answers_question=True,**kwargs)
    def branch(self):
        q=self.node('Q','Which method?');a1=self.node('A','White and yolk',q,'analyzes');a2=self.node('A','Same sample',q,'analyzes')
        e1=self.node('E','Individual counts',a1,'produces');e2=self.node('E','Joint counts',a2,'produces');c=self.node('C','Limited answer',e1,'supports');self.edge(e2,c,'supports');self.edge(c,q,'answers')
        return q,a1,a2,e1,e2,c
    def test_actual_branch_merge_and_single_project_root(self):
        q,a1,a2,e1,e2,c=self.branch();current=self.get(q);child=self.call('question.organize',id=q,expected_revision=current['revision'],title='Synthesis',body=current['body'])['node_id'];self.node('Q','Another subquestion',q,'contains');g=self.read()
        self.assertEqual(len([n for n in g['nodes'] if n['kind']=='root']),1)
        self.assertEqual(len([e for e in g['edges'] if e['src']==child and e['kind']=='analyzes']),2)
        self.assertEqual(len([e for e in g['edges'] if e['dst']==c and e['kind']=='supports']),2)
        self.assertFalse(any(e['src']==self.p['id'] and e['kind']=='analyzes' for e in g['edges']))
        self.assertEqual(self.get(child)['label'],'Q1.1')
    def test_aec_numbering_follows_question_and_analysis_paths(self):
        q,a1,a2,e1,e2,c=self.branch()
        n=self.get(q);synthesis=self.call('question.organize',id=q,expected_revision=n['revision'],title='Synthesis',body=n['body'])['node_id']
        child=self.node('Q','Sub question',q,'contains');a_child=self.node('A','Child analysis',child,'analyzes')
        e_child=self.node('E','Child evidence',a_child,'produces');c_child=self.node('C','Child conclusion',e_child,'supports');self.edge(c_child,child,'answers')
        self.edge(e_child,c,'supports')
        q2=self.node('Q','Generalization');a_q2=self.node('A','Validate',q2,'analyzes');e_q2=self.node('E','Validation result',a_q2,'produces')
        expected={q:'Q1',synthesis:'Q1.1',a1:'A1.1-1',a2:'A1.1-2',e1:'E1.1-1',e2:'E1.1-2',c:'C1.1',child:'Q1.2',a_child:'A1.2',e_child:'E1.2',c_child:'C1.2',q2:'Q2',a_q2:'A2',e_q2:'E2'}
        self.assertEqual({i:self.get(i)['label'] for i in expected},expected)
        before=self.app.store.get(a1)
        self.edge(q2,a1,'analyzes')
        self.assertEqual(self.get(a1)['label'],'A1.1-1');self.assertEqual(self.get(e1)['label'],'E1.1-1')
        self.assertEqual(self.app.store.get(a1),before)
        orphan=self.node('A','Not assigned')
        self.assertEqual(self.get(orphan)['label'],'A?');self.assertIsNone(self.get(orphan)['owner_question_id'])

    def test_completion_and_transitive_staleness(self):
        q,a1,a2,e1,e2,c=self.branch()
        with self.assertRaises(Problem):self.save(q)
        for ident in (a1,a2,e1,e2,c,q):self.save(ident)
        self.assertEqual(self.get(q)['status'],'completed')
        n=self.get(a1);o=self.app.store.get(a1);self.app.store.save(a1,o['revision'],content={'text':'Revised method'},merge=False)
        for ident in (a1,e1,c,q):self.assertEqual(self.get(ident)['status'],'stale')
        self.assertEqual(self.get(e2)['status'],'completed')
    def test_edge_withdrawal_invalidates_downstream_confirmation_and_has_history(self):
        q,a1,a2,e1,e2,c=self.branch()
        for ident in (a1,a2,e1,e2,c,q):self.save(ident)
        edge=next(e for e in self.read()['edges'] if e['src']==e2 and e['dst']==c)
        self.call('edge.save',id=edge['id'],expected_revision=edge['revision'],active=False,rationale='Withdraw unsupported inference')
        self.assertEqual(self.get(c)['status'],'stale');self.assertEqual(self.get(q)['status'],'stale')
        with self.app.store.connect() as conn:self.assertTrue(conn.execute('SELECT 1 FROM kv WHERE key=?',('graph_relation_history:'+edge['id'],)).fetchone())
    def test_bad_edges_and_cycle_are_atomic(self):
        q,a1,a2,e1,e2,c=self.branch();before=len(self.app.store.objects())
        with self.assertRaises(Problem):self.node('E','Second output',a1,'produces')
        self.assertEqual(len(self.app.store.objects()),before)
        q2=self.node('Q','Next');self.edge(q,q2,'prerequisite')
        with self.assertRaises(Problem):self.edge(q2,q,'prerequisite')
        with self.assertRaises(Problem):self.edge(c,a1,'analyzes')
    def test_acl_cas_idempotency_and_agent_confirmation(self):
        q=self.node('Q','Which?');g=self.read();fields={'action':'workbench.graph.node.create','project_id':self.p['id'],'expected_project_revision':g['project']['revision'],'kind':'A','title':'A','body':'Analyze','request_key':'stable'}
        first=self.app.dispatch(fields);second=self.app.dispatch(fields);self.assertTrue(second['replayed']);self.assertEqual(first['node_id'],second['node_id'])
        with self.assertRaises(Problem):self.app.dispatch({**fields,'request_key':'different'})
        with self.assertRaises(Problem):self.app.dispatch({'action':'workbench.graph.read','project_id':self.p['id']},scope=[])
        other=self.app.store.create('project','Other');foreign=self.app.dispatch({'action':'workbench.question.create','project_id':other['id'],'title':'Foreign','request_key':'foreign'})
        with self.assertRaises(Problem):self.edge(q,foreign['id'],'contains')
        a=first['node_id'];n=self.get(a);g=self.read()
        with self.assertRaises(Problem):self.app.dispatch({'action':'workbench.graph.node.save','project_id':self.p['id'],'id':a,'expected_revision':n['revision'],'expected_project_revision':g['project']['revision'],'title':n['title'],'body':n['body'],'status':'completed','confirmation_note':'Agent self approval','expected_dependencies':[],'request_key':'agent'},principal={'kind':'agent'})
    def test_restoring_body_does_not_resurrect_confirmation(self):
        a=self.node('A','Analyze');self.save(a);o=self.app.store.get(a)
        self.app.store.save(a,o['revision'],content={'text':'Different'},merge=False);o2=self.app.store.get(a)
        self.app.store.save(a,o2['revision'],content=o['content'],merge=False)
        self.assertEqual(self.get(a)['status'],'stale')
    def test_scope_change_and_forged_metadata_do_not_approve(self):
        q=self.node('Q','Scope');a=self.node('A','Analyze',q,'analyzes');self.save(a)
        o=self.app.store.get(q);self.app.store.save(q,o['revision'],title='Changed scientific scope',merge=False)
        self.assertEqual(self.get(a)['status'],'stale')
        n=self.app.store.get(a);metadata=copy.deepcopy(n['metadata']);metadata['graph_node']['confirmation']['id']='forged'
        self.app.store.save(a,n['revision'],metadata=metadata,merge=False);self.assertEqual(self.get(a)['status'],'stale')
    def test_migration_preserves_all_original_bodies_and_real_completed_decisions(self):
        from test_research_nodes import ResearchNodes
        helper=ResearchNodes();helper.app=self.app;helper.p=self.p;helper.n=100
        q=helper.complete(helper.full(helper.q()));root=helper.action('workbench.root.set',expected_project_revision=self.p['revision'],title='Overall question',attach_roots=True,expected_roots=[{'id':q['id'],'revision':q['revision']}])['question']
        original=self.app.store.get(q['id']);g=self.read();m=self.call('migrate',expected_sources=g['source_refs'])
        self.assertEqual(self.app.store.get(q['id'])['content'],original['content'])
        self.assertNotIn(root['id'],[n['id'] for n in m['graph']['nodes']]);self.assertEqual(self.get(q['id'])['status'],'completed')
        a=m['mapping'][q['id']+':A'];self.assertEqual(self.get(a)['body'],original['content']['qaec']['A']);self.assertEqual(self.get(a)['status'],'completed')
        h=self.app.dispatch({'action':'workbench.graph.history','project_id':self.p['id'],'id':a});self.assertGreaterEqual(len(h['versions']),2)

    def test_parent_only_organizes_and_explicitly_answers_through_children(self):
        q,a1,a2,e1,e2,c=self.branch()
        for ident in (a1,a2,e1,e2,c,q):self.save(ident)
        original={i:self.app.store.get(i) for i in (q,a1,a2,e1,e2,c)}
        n=self.get(q);child=self.call('question.organize',id=q,expected_revision=n['revision'],title='Which joint target succeeds?',body=n['body'])['node_id']
        g=self.read();self.assertEqual(self.get(q)['question_role'],'parent');self.assertEqual(self.get(child)['question_role'],'leaf')
        self.assertFalse(any(e['active'] and ((e['src']==q and e['kind']=='analyzes') or (e['dst']==q and e['kind']=='answers')) for e in g['edges']))
        for ident,obj in original.items():
            self.assertEqual(self.app.store.get(ident)['content'],obj['content'])
            self.assertEqual(self.app.store.get(ident,obj['revision'])['content'],obj['content'])
        self.assertEqual(self.get(a1)['status'],'stale');self.assertEqual(self.get(c)['status'],'review')
        with self.assertRaises(Problem):self.save(q)
        for ident in (a1,a2,e1,e2,c,child,q):self.save(ident)
        self.assertEqual(self.get(q)['status'],'completed')
        self.assertEqual([d['id'] for d in self.get(q)['dependencies']],[child])
        obj=self.app.store.get(e1);self.app.store.save(e1,obj['revision'],content={'text':'Changed result'},merge=False)
        for ident in (e1,c,child,q):self.assertEqual(self.get(ident)['status'],'stale')

    def test_all_creation_paths_reject_mixing_parent_and_aec_atomically(self):
        parent=self.node('Q','Parent');leaf=self.node('Q','Leaf',parent,'contains');a=self.node('A','Analyze',leaf,'analyzes');e=self.node('E','Result',a,'produces');c=self.node('C','Conclusion',e,'supports')
        before=len(self.app.store.objects())
        with self.assertRaises(Problem):self.node('A','Not on parent',parent,'analyzes')
        self.assertEqual(len(self.app.store.objects()),before)
        with self.assertRaises(Problem):self.edge(c,parent,'answers')
        with self.assertRaises(Problem):self.node('Q','Bad split',leaf,'contains')
        with self.assertRaises(Problem):self.app.dispatch({'action':'workbench.question.create','project_id':self.p['id'],'parent_id':leaf,'title':'Legacy path','request_key':'legacy-bypass'})
        self.assertEqual(len(self.app.store.objects()),before)

    def test_organization_cas_and_retry_do_not_duplicate_questions(self):
        q,a1,a2,e1,e2,c=self.branch();g=self.read();n=self.get(q)
        fields={'action':'workbench.graph.question.organize','project_id':self.p['id'],'id':q,'expected_revision':n['revision'],'expected_project_revision':g['project']['revision'],'title':'Synthesis','body':n['body'],'request_key':'split-once'}
        first=self.app.dispatch(fields);second=self.app.dispatch(fields);self.assertEqual(first['node_id'],second['node_id']);self.assertTrue(second['replayed'])
        count=len(self.app.store.objects())
        with self.assertRaises(Problem):self.call('question.organize',id=q,expected_revision=n['revision'],title='Stale split',body=n['body'])
        self.assertEqual(len(self.app.store.objects()),count)

    def test_legacy_import_moves_parent_routes_to_final_child(self):
        from test_research_nodes import ResearchNodes
        helper=ResearchNodes();helper.app=self.app;helper.p=self.p;helper.n=100
        parent=helper.complete(helper.full(helper.q('Overall')));child=helper.complete(helper.full(helper.q('Specific',parent['id'])))
        original={o['id']:o['content'] for o in (self.app.store.get(parent['id']),self.app.store.get(child['id']))}
        g=self.read();result=self.call('migrate',expected_sources=g['source_refs']);synthesis=result['organization_questions'][parent['id']]
        self.assertEqual(self.get(synthesis)['label'],'Q1.2');self.assertEqual(self.get(parent['id'])['question_role'],'parent')
        self.assertEqual(self.get(parent['id'])['status'],'completed')
        self.assertEqual(self.app.store.get(parent['id'])['content'],original[parent['id']])
        self.assertFalse(self.get(parent['id'])['needs_organization'])
