"""Natural input → shared Runtime → real independent graph, not a UI mock."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from research_partner.app import App
from research_partner.runtime import Runtime
from research_partner.store import Problem


class PartnerGraphChanges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.app = App(root/'workspace', {'control_root': str(root/'control'), 'providers': {
            'local': {'route': 'codex', 'executable': sys.executable, 'authorized': True}}, 'default_provider': 'local'})
        self.p = self.app.dispatch({'action': 'project.create', 'title': '从研究输入形成图'})
        self.fields = {'project_id': self.p['id'], 'request': '比较煮蛋方法，使蛋白凝固、蛋黄柔软。',
                       'materials': [], 'questions': [], 'native_paths': [], 'graph_mode': 'edit'}

    def graph(self):
        return self.app.dispatch({'action': 'workbench.graph.read', 'project_id': self.p['id']})

    def submit(self, key='turn', **extra):
        fields = {**self.fields, **extra}
        preview = self.app.dispatch({'action': 'research.partner.preview', **fields})
        task = self.app.dispatch({'action': 'research.partner.submit', **fields, 'input_pin': preview['input_pin'], 'request_key': key})
        self.last_submission = {'action': 'research.partner.submit', **fields, 'input_pin': preview['input_pin'], 'request_key': key}
        return task

    def candidate(self, creates=None, edges=None, updates=None):
        return {'title': '煮蛋研究结构', 'kind': 'note', 'partner_reply': {'version': 1, 'text': '已整理问题与待开展的分析，结果需后续记录。', 'next_steps': []},
                'graph_change': {'version': 1, 'summary': '整理研究问题和分析路线', 'background': None,
                                 'creates': creates if creates is not None else [self.node('question', 'Q'), self.node('analysis', 'A')],
                                 'updates': updates or [], 'edges': edges if edges is not None else [self.edge('question', 'analysis', 'analyzes')]}}

    @staticmethod
    def node(ident, kind, text=None, quote='', refs=None):
        return {'id': ident, 'kind': kind, 'title': {'Q': '哪种方法兼顾蛋白凝固与蛋黄柔软？', 'A': '比较逐枚两项目标', 'E': '本批计数', 'C': '本批阶段判断'}[kind],
                'body': text or '待开展的研究：' + ident, 'quote': quote, 'source_refs': refs or []}

    @staticmethod
    def edge(src, dst, kind):
        return {'src': src, 'dst': dst, 'kind': kind, 'rationale': '按明确的研究范围连接'}

    def execute(self, task, candidate):
        runtime = Runtime(self.app); self.assertEqual(runtime.claim(), task['id'])
        with patch('research_partner.providers.Providers.call', return_value={'text': json.dumps(candidate), 'receipt': {
            'route': 'codex', 'session_id': 'graph-contract-test', 'returncode': 0, 'usage': []}}) as call:
            runtime.execute(task['id'])
        return self.app.store.task(task['id']), call

    def complete(self, key='turn', candidate=None, **fields):
        task = self.submit(key, **fields); result, model = self.execute(task, candidate or self.candidate())
        self.assertEqual(result['status'], 'generated', result['error'])
        self.assertEqual(result['result']['graph_change']['status'], 'applied', result['result'])
        return result, model

    def test_idea_creates_real_q_and_a_through_runtime_without_filling_e_c(self):
        before = self.graph(); task, call = self.complete(); view = self.graph()
        self.assertEqual([n['kind'] for n in view['nodes']].count('Q'), 1)
        self.assertEqual([n['kind'] for n in view['nodes']].count('A'), 1)
        self.assertFalse(any(n['kind'] in {'E', 'C'} for n in view['nodes']))
        self.assertTrue(all(n['status'] == 'not_started' for n in view['nodes'] if n['kind'] != 'root'))
        self.assertGreater(view['project']['revision'], before['project']['revision'])
        self.assertIn('graph_change', call.call_args.args[1])
        for n in view['nodes'][1:]:
            source = self.app.store.get(n['source_refs'][0]['id'], n['source_refs'][0]['revision'])
            self.assertEqual(source['content']['markdown'], self.fields['request'])
            self.assertEqual(source['metadata']['research_context_snapshot']['authority_kind'], 'user_input')
        record = task['result']['graph_change']; self.assertEqual(len(record['created_ids']), 2)
        self.assertTrue(any(e['kind'] == 'analyzes' for e in view['edges']))

    def test_incremental_second_route_retains_ids_and_freezes_focused_a_body(self):
        first, _ = self.complete(); old = self.graph(); q = next(n for n in old['nodes'] if n['kind'] == 'Q'); a = next(n for n in old['nodes'] if n['kind'] == 'A')
        task = self.submit('another', graph_focus=a['id'], request='保留现有分析，再加一条独立批次验证路线。')
        frozen = task['payload']['context']['partner']['graph']
        self.assertEqual(next(n for n in frozen['nodes'] if n['id'] == a['id'])['body'], a['body'])
        candidate = self.candidate([self.node('batch', 'A')], [self.edge(q['id'], 'batch', 'analyzes')])
        result, _ = self.execute(task, candidate); self.assertEqual(result['result']['graph_change']['status'], 'applied')
        current = self.graph(); self.assertEqual(len([n for n in current['nodes'] if n['kind'] == 'A']), 2)
        actual = next(n for n in current['nodes'] if n['id'] == a['id'])
        for field in ('id', 'body', 'revision', 'signature', 'status', 'source_refs'): self.assertEqual(actual[field], a[field])
        self.assertEqual(self.app.store.get(q['id'])['content']['qaec']['A'], '')

    def test_reported_evidence_requires_exact_input_quote_and_stays_unconfirmed(self):
        self.complete(); a = next(n for n in self.graph()['nodes'] if n['kind'] == 'A'); q = next(n for n in self.graph()['nodes'] if n['kind'] == 'Q')
        text = '本批10枚中7枚同时达标。'; ref = [{'id': 'request', 'revision': 1}]
        nodes = [self.node('observed', 'E', text, text, ref), self.node('finding', 'C', text + '仅描述本批。', text, ref)]
        edges = [self.edge(a['id'], 'observed', 'produces'), self.edge('observed', 'finding', 'supports'), self.edge('finding', q['id'], 'answers')]
        self.complete('reported', self.candidate(nodes, edges), request=text)
        self.assertTrue(all(n['status'] == 'review' for n in self.graph()['nodes'] if n['kind'] in {'E', 'C'}))

    def test_invented_result_or_completion_field_is_rejected_before_graph_write(self):
        for candidate in [self.candidate([self.node('result', 'E', '90%成功', '90%成功', [{'id': 'request', 'revision': 1}])], []),
                          self.candidate([{**self.node('question', 'Q'), 'status': 'completed'}], [])]:
            task = self.submit(str(len(self.app.store.tasks()))); before = self.graph()
            with self.assertRaises(Problem): self.execute(task, candidate)
            self.assertEqual(self.graph(), before)

    def test_concurrent_human_edit_keeps_candidate_without_overwriting_graph(self):
        self.complete(); old = self.graph(); q = next(n for n in old['nodes'] if n['kind'] == 'Q')
        task = self.submit('stale')
        self.app.dispatch({'action': 'workbench.graph.node.save', 'project_id': self.p['id'], 'id': q['id'],
                           'expected_project_revision': old['project']['revision'], 'expected_revision': q['revision'], 'request_key': 'human',
                           'title': q['title'], 'body': '后来保存的人工作业，需要保留。', 'status': 'active'})
        before = self.graph(); result, _ = self.execute(task, self.candidate())
        self.assertEqual(result['status'], 'generated'); self.assertEqual(result['result']['graph_change']['status'], 'conflict')
        self.assertEqual(self.graph(), before); self.assertIn('graph_change', self.app.store.get(result['result']['object_id'])['content'])

    def test_invalid_relationship_rolls_back_whole_batch_but_keeps_reply(self):
        before = self.graph(); task = self.submit(); bad = self.candidate(edges=[self.edge('analysis', 'question', 'produces')])
        result, _ = self.execute(task, bad)
        self.assertEqual(result['status'], 'generated'); self.assertEqual(result['result']['graph_change']['status'], 'unapplied')
        self.assertEqual(self.graph(), before)

    def test_undo_is_version_checked_idempotent_and_retains_node_history(self):
        task, _ = self.complete(); ids = task['result']['graph_change']['created_ids']
        fields = {'action': 'research.partner.graph.undo', 'project_id': self.p['id'], 'task_id': task['id'], 'request_key': 'undo'}
        with self.assertRaises(Problem): self.app.dispatch(fields, principal={'kind': 'agent'})
        result = self.app.dispatch(fields); self.assertEqual(result['graph_change']['status'], 'undone')
        self.assertEqual(len(self.graph()['nodes']), 1); self.assertTrue(self.app.dispatch(fields)['replayed'])
        for ident in ids:
            self.assertTrue(self.app.store.get(ident)['archived']); self.assertFalse(self.app.store.get(ident, 1)['archived'])
        self.assertEqual(self.app.store.task(task['id'])['result']['graph_change']['status'], 'undone')

    def test_undo_refuses_to_erase_later_work(self):
        task, _ = self.complete(); old = self.graph(); q = next(n for n in old['nodes'] if n['kind'] == 'Q')
        self.app.dispatch({'action': 'workbench.graph.node.save', 'project_id': self.p['id'], 'id': q['id'],
                           'expected_project_revision': old['project']['revision'], 'expected_revision': q['revision'], 'request_key': 'later',
                           'title': q['title'], 'body': '后来的人工作业。', 'status': 'active'})
        before = self.graph()
        with self.assertRaises(Problem): self.app.dispatch({'action': 'research.partner.graph.undo', 'project_id': self.p['id'], 'task_id': task['id'], 'request_key': 'undo'})
        self.assertEqual(self.graph(), before)

    def test_title_edit_preserves_body_and_body_edits_require_selected_saved_text(self):
        self.complete(); q = next(n for n in self.graph()['nodes'] if n['kind'] == 'Q')
        update = {'id': q['id'], 'title': '不同煮法的联合达标情况如何？', 'body': None, 'quote': '', 'source_refs': None}
        self.complete('title', self.candidate([], [], [update])); self.assertEqual(next(n for n in self.graph()['nodes'] if n['kind'] == 'Q')['body'], q['body'])
        task = self.submit('hidden-body'); before = self.graph()
        with self.assertRaises(Problem): self.execute(task, self.candidate([], [], [{**update, 'body': '未经读取的替换'}]))
        self.assertEqual(self.graph(), before)

    def test_malformed_focus_and_question_identity_are_rejected_before_submission(self):
        for fields in ({'graph_focus': []}, {'graph_focus': {}}, {'questions': [{'id': [], 'revision': 1, 'parts': []}]}):
            with self.assertRaises(Problem):
                self.app.dispatch({'action': 'research.partner.preview', **self.fields, **fields})
        self.assertEqual(self.app.store.tasks(), [])

    def test_ordinary_discussion_does_not_change_graph(self):
        task = self.submit(); candidate = self.candidate(); candidate['graph_change'] = None; before = self.graph()
        result, _ = self.execute(task, candidate)
        self.assertEqual(result['status'], 'generated'); self.assertNotIn('graph_change', result['result']); self.assertEqual(self.graph(), before)

    def test_exact_submission_replay_after_application_does_not_duplicate_nodes(self):
        task, _ = self.complete(); before = self.graph()
        self.assertEqual(self.app.dispatch(self.last_submission)['id'], task['id']); self.assertEqual(self.graph(), before)

    def test_legacy_qaec_is_not_silently_replaced_by_an_independent_graph(self):
        q = self.app.dispatch({'action': 'workbench.question.create', 'project_id': self.p['id'], 'title': '已有研究问题', 'request_key': 'legacy'})
        q = self.app.dispatch({'action': 'workbench.question.save', 'project_id': self.p['id'], 'id': q['id'], 'expected_revision': q['revision'],
                              'title': q['title'], 'qaec': {'Q': '已有问题', 'A': '原始分析要保留', 'E': '原始结果要保留', 'C': ''}, 'status': 'active', 'request_key': 'legacy-body'})
        before = self.graph(); task = self.submit(); result, _ = self.execute(task, self.candidate())
        self.assertEqual(result['result']['graph_change']['status'], 'unapplied'); self.assertEqual(self.graph(), before)
        self.assertEqual(self.app.store.get(q['id'])['content'], q['content'])

    def test_existing_legacy_root_remains_the_same_record_through_apply_and_undo(self):
        q = self.app.dispatch({'action': 'workbench.question.create', 'project_id': self.p['id'], 'title': '原总体问题', 'request_key': 'root'})
        p = self.app.store.get(self.p['id']); self.app.store.save(p['id'], p['revision'], metadata={**p['metadata'], 'research_root_question_id': q['id']})
        task, _ = self.complete(); self.assertEqual(len([n for n in self.graph()['nodes'] if n['kind'] == 'Q']), 1)
        self.app.dispatch({'action': 'research.partner.graph.undo', 'project_id': self.p['id'], 'task_id': task['id'], 'request_key': 'undo-root'})
        self.assertEqual(len(self.graph()['nodes']), 1); self.assertEqual(self.app.store.get(q['id']), q)

    def test_changing_confirmed_analysis_and_undo_both_require_fresh_scientific_review(self):
        self.complete(); view = self.graph(); a = next(n for n in view['nodes'] if n['kind'] == 'A')
        self.app.dispatch({'action': 'workbench.graph.node.save', 'project_id': self.p['id'], 'id': a['id'],
                           'expected_project_revision': view['project']['revision'], 'expected_revision': a['revision'], 'request_key': 'confirmed',
                           'title': a['title'], 'body': a['body'], 'status': 'completed', 'confirmation_note': '已核对原分析依据', 'expected_dependencies': []})
        candidate = self.candidate([], [], [{'id': a['id'], 'title': None, 'body': '按新范围重写分析说明。', 'quote': '', 'source_refs': None}])
        task, _ = self.complete('revise', candidate, graph_focus=a['id'])
        self.assertEqual(next(n for n in self.graph()['nodes'] if n['id'] == a['id'])['status'], 'stale')
        self.app.dispatch({'action': 'research.partner.graph.undo', 'project_id': self.p['id'], 'task_id': task['id'], 'request_key': 'undo-revise'})
        restored = next(n for n in self.graph()['nodes'] if n['id'] == a['id'])
        self.assertEqual(restored['body'], a['body']); self.assertEqual(restored['status'], 'stale')

    def test_wrong_source_and_cross_project_node_cannot_be_smuggled_into_a_graph_change(self):
        foreign = self.app.dispatch({'action': 'project.create', 'title': '另一个项目'})
        obj = self.app.store.create('concept', '私有记录', foreign['id'], {'text': '不能发送的结果'})
        invalid = self.candidate([self.node('q', 'Q', refs=[{'id': obj['id'], 'revision': obj['revision']}])], [])
        task = self.submit(); before = self.graph()
        with self.assertRaises(Problem): self.execute(task, invalid)
        self.assertEqual(self.graph(), before)


if __name__ == '__main__': unittest.main()
