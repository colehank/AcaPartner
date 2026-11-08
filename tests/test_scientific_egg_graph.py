"""The authored demo must tell a consistent story without changing user work."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

from research_partner.app import App

SCRIPTS = Path(__file__).resolve().parents[1] / 'examples/scientific-egg/scripts'
sys.path.insert(0, str(SCRIPTS))
from case_content import QUESTIONS, build_case
from free_graph import configure_free_graph
from research_graph import configure_graph
from revise_graph import audit_counts, revise_case_graph


class EggGraph(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = App(self.tmp.name)
        self.project = self.app.store.create('project', 'Egg', metadata={'demo': 'scientific_egg_v1'})
        self.pid = self.project['id']
        self.other = self.app.store.create('project', 'Other')
        self.case = build_case(lambda key, label: f'[{label}](/{key})')
        questions = {}
        for key, parent, order, title, _ in QUESTIONS:
            q = self.call('workbench.question.create', project_id=self.pid, title=title,
                          parent_id=questions[parent]['id'] if parent else None)
            q = self.call('workbench.question.save', project_id=self.pid, id=q['id'],
                          expected_revision=q['revision'], title=title,
                          qaec=self.case['questions'][key], status='review')
            q = self.app.store.save(q['id'], q['revision'], metadata={**q['metadata'],
                                   'demo_question_key': key, 'workbench': {'order': order}})
            questions[key] = q
        configure_graph(self.call, self.pid)

    def call(self, action, **fields):
        if action not in {'workbench.graph.read', 'workbench.graph.history', 'workbench.research.read'}:
            fields.setdefault('request_key', str(uuid.uuid4()))
        return self.app.dispatch(dict(action=action, **fields))

    def read(self):
        return self.call('workbench.graph.read', project_id=self.pid)

    def mutate(self, action, **fields):
        return self.call('workbench.graph.' + action, project_id=self.pid,
                         expected_project_revision=self.read()['project']['revision'], **fields)

    def legacy_graph(self, complete=False):
        with patch('free_graph.revise_case_graph', lambda call, pid: {'graph': self.read()}):
            configure_free_graph(self.call, self.pid)
        g = self.read()
        by = {n['label']: n for n in g['nodes']}
        for src in ('E1.1', 'E1.2'):
            self.mutate('edge.create', src=by[src]['id'], dst=by['C1.3']['id'],
                        kind='supports', rationale='从原有研究记录迁移')
        if complete:
            # Authored fixture: explicitly check Q1, plus the old six-cell
            # computation only. Never mark the unfinished Q2 question complete.
            wanted = {n['id'] for n in self.read()['nodes'] if n['label'].startswith(('Q1', 'A1', 'E1', 'C1'))
                      or n['label'] in {'A2.4-1', 'E2.4-1'}}
            while wanted:
                ready = [n for n in self.read()['nodes'] if n['id'] in wanted and n['can_complete']]
                self.assertTrue(ready)
                for n in ready:
                    self.mutate('node.save', id=n['id'], expected_revision=n['revision'],
                                title=n['title'], body=n['body'], status='completed',
                                expected_dependencies=n['dependencies'], answers_question=True,
                                confirmation_note='Fixture: checked fixed case arithmetic and stated scope')
                    wanted.remove(n['id'])

    def test_fresh_import_uses_revised_story_without_approving_findings(self):
        result = configure_free_graph(self.call, self.pid)
        g = result['graph']
        self.assertEqual(len(g['nodes']), 34)
        self.assertFalse(any(n['status'] == 'completed' for n in g['nodes']))
        self.assertEqual(next(n for n in g['nodes'] if n['label'] == 'A2.4-1')['status'], 'active')
        self.assertIn('缺失读数', next(n for n in g['nodes'] if n['label'] == 'A1.3-2')['title'])
        again = configure_free_graph(self.call, self.pid)
        self.assertEqual(again['changed'], [])
        self.assertEqual(g, again['graph'])

    def test_existing_completed_case_keeps_ids_history_and_partial_progress(self):
        self.legacy_graph(complete=True)
        before = self.read()
        old_qaec = {q['id']: q['content'] for q in self.call('workbench.research.read', project_id=self.pid)['questions']}
        protected = self.app.store.get(self.other['id'])
        result = revise_case_graph(self.call, self.pid)
        g = result['graph']; by = {n['label']: n for n in g['nodes']}
        self.assertEqual({n['id'] for n in before['nodes']}, {n['id'] for n in g['nodes']})
        self.assertEqual(len([e for e in g['edges'] if e['active']]), 47)
        incoming = {(next(n['label'] for n in g['nodes'] if n['id'] == e['src']), e['kind'])
                    for e in g['edges'] if e['active'] and e['dst'] == by['C1.3']['id']}
        self.assertEqual(incoming, {('E1.3-1', 'supports'), ('E1.3-2', 'limits')})
        for label in ('Q1', 'Q1.1', 'Q1.2', 'Q1.3', 'C1.3', 'A1.3-2', 'E1.3-2'):
            self.assertEqual(by[label]['status'], 'completed', label)
        for label in ('Q2', 'Q2.4', 'A2.4-1', 'E2.4-1', 'C2.4', 'A2.4-2'):
            self.assertNotEqual(by[label]['status'], 'completed', label)
        self.assertEqual(by['A2.4-2']['status'], 'not_started')
        self.assertFalse(any(e['active'] and e['src'] == by['A2.4-2']['id'] and e['kind'] == 'produces' for e in g['edges']))
        self.assertEqual(self.app.store.get(self.other['id']), protected)
        for ident, content in old_qaec.items():
            self.assertEqual(self.app.store.get(ident)['content'], content)
        for old in before['nodes']:
            if old['kind'] == 'root':
                continue
            history = self.call('workbench.graph.history', project_id=self.pid, id=old['id'])
            self.assertTrue(any(v['revision'] == old['revision'] for v in history['versions']))
        self.assertEqual(revise_case_graph(self.call, self.pid)['changed'], [])
        self.assertEqual(g, self.read())

    def test_user_edits_stop_revision_before_any_write(self):
        self.legacy_graph()
        n = next(n for n in self.read()['nodes'] if n['label'] == 'C2.4')
        self.mutate('node.save', id=n['id'], expected_revision=n['revision'],
                    title=n['title'], body='User revised interpretation', status='review')
        before = self.read()
        with self.assertRaisesRegex(AssertionError, 'user edits'):
            revise_case_graph(self.call, self.pid)
        self.assertEqual(self.read(), before)

    def test_missing_bounds_are_computed_from_same_sample_not_marginal_counts(self):
        counts, sha = audit_counts()
        self.assertEqual(counts['sous_vide'], {'n': 120, 'joint': 0, 'missing': 1, 'upper': 1})
        self.assertEqual(counts['soft_boiled']['upper'], 0)
        self.assertEqual(counts['periodic']['joint'], 45)
        self.assertEqual(len(sha), 64)


if __name__ == '__main__':
    unittest.main()
