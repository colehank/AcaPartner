"""Q → finite work → fixed AEC candidates → explicit revision-checked adoption."""
import copy
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from research_partner.app import App, restore_workspace
from research_partner.commission import validate_candidate
from research_partner.runtime import Runtime
from research_partner.store import Problem, digest


class ResearchWork(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.app = App(Path(self.tmp.name)/'workspace', {'control_root': str(Path(self.tmp.name)/'control'),
            'providers': {'local': {'route': 'codex', 'executable': sys.executable, 'authorized': True}}, 'default_provider': 'local'})
        self.project = self.app.dispatch({'action': 'project.create', 'title': '研究工作验收'})
        self.q = self.app.dispatch({'action': 'workbench.question.create', 'project_id': self.project['id'], 'title': '哪种方法兼顾蛋白凝固与蛋黄柔软？', 'request_key': 'q'})
        self.other = self.app.dispatch({'action': 'workbench.question.create', 'project_id': self.project['id'], 'title': '方法能否适用于不同大小？', 'request_key': 'other'})
        self.source = self.app.store.create('report', '已保存的比较结果', self.project['id'], {'blocks': [{'id': 'results', 'text': '本次比较中甲方法3/10枚、乙方法5/10枚同时达到预设质构目标。结果仅用于界面测试。'}]})
        self.input = {'project_id': self.project['id'], 'request': '比较已保存结果，给出阶段分析、证据及结论候选，不执行新实验。',
            'materials': [{'id': self.source['id'], 'revision': self.source['revision']}],
            'questions': [{'id': self.q['id'], 'revision': self.q['revision'], 'parts': ['A', 'E', 'C']}]}

    def call(self, name, fields=None, **kwargs):
        return self.app.dispatch({'action': 'research.work.'+name, **(self.input if fields is None else fields)}, **kwargs)

    def submit(self, key='work'):
        preview = self.call('preview')
        return self.call('submit', {**self.input, 'input_pin': preview['input_pin'], 'provider_id': 'local', 'budget': {'max_model_calls': 1, 'timeout_seconds': 60}, 'request_key': key})

    def candidate(self):
        return {'title': 'Q1 阶段工作候选', 'kind': 'note', 'research_update': {'version': 1, 'summary': '依据现有记录比较两种方法，没有执行新实验。', 'changes': [
            {'id': p.lower(), 'question_id': self.q['id'], 'part': p, 'mode': 'append' if p == 'A' else 'replace',
             'text': {'A': '逐枚比较联合达标情况，区分观察与方法优劣判断。', 'E': '甲3/10，乙5/10；同一枚蛋须同时达标。', 'C': '现有记录中乙方法比例较高，但样本有限，尚不能判断稳定优越。'}[p],
             'rationale': '来自当前选定保存版，比较的目标一致。', 'basis': 'supported',
             'source_refs': [{'id': self.source['id'], 'revision': 1}]} for p in ('A', 'E', 'C')], 'limitations': ['样本少，没有独立重复。']}}

    def complete(self, task=None, raw=None):
        task = task or self.submit(); runtime = Runtime(self.app); self.assertEqual(runtime.claim(), task['id'])
        reply = {'text': json.dumps(raw or self.candidate()), 'receipt': {'route': 'codex', 'session_id': 'work-test', 'returncode': 0, 'usage': []}}
        with patch('research_partner.providers.Providers.call', return_value=reply) as model: runtime.execute(task['id'])
        self.assertIn('甲方法3/10枚', model.call_args.args[1])
        return self.call('read', {'project_id': self.project['id'], 'task_id': task['id']})

    def adoption(self, view, ids=('a', 'c'), key='adopt'):
        candidate = {x['id']: x for x in view['proposal']['content']['research_update']['changes']}
        return {'project_id': self.project['id'], 'task_id': view['task']['id'],
            'proposal_ref': {k: view['proposal'][k] for k in ('id', 'revision', 'sha256')},
            'changes': [{'id': i, 'text': candidate[i]['text']} for i in ids],
            'expected_questions': [{k: q[k] for k in ('id', 'revision', 'sha256')} for q in view['questions']], 'request_key': key}

    def test_preview_freezes_full_qaec_and_only_explicit_saved_context(self):
        self.app.store.set_setting('preferences', {'machine_profiles': [{'host': 'private.example'}]})
        before = self.app.store.objects(); preview = self.call('preview')
        self.assertFalse(preview['executed']); self.assertEqual(before, self.app.store.objects()); self.assertFalse(self.app.store.tasks())
        q = preview['input']['research_questions'][0]; self.assertEqual(q['qaec'], self.q['content']['qaec'])
        self.assertNotIn('private.example', json.dumps(preview))
        self.assertEqual(preview['input']['targets'][0]['parts'], ['A', 'E', 'C'])

    def test_bad_scope_stale_q_and_generic_bypass_are_rejected(self):
        with self.assertRaises(Problem): self.call('preview', scope=[])
        bad = copy.deepcopy(self.input); bad['questions'][0]['parts'] = ['Q']
        with self.assertRaises(Problem): self.call('preview', bad)
        self.app.store.save(self.q['id'], self.q['revision'], title='人工调整后的问题')
        with self.assertRaises(Problem): self.call('preview')
        with self.assertRaises(Problem): self.app.dispatch({'action': 'task.submit', **self.input, 'kind': 'research_work'})
        self.assertFalse(self.app.store.tasks())

    def test_stale_preview_and_same_request_replay(self):
        p = self.call('preview'); fields = {**self.input, 'input_pin': p['input_pin'], 'request_key': 'stable'}
        first = self.call('submit', fields)
        self.app.store.save(self.q['id'], self.q['revision'], title='后来更改了表述')
        self.assertEqual(self.call('submit', fields)['id'], first['id'])
        with self.assertRaises(Problem): self.call('submit', {**fields, 'request_key': 'new'})
        self.assertEqual(len(self.app.store.tasks()), 1)

    def test_target_q_cannot_have_two_conflicting_context_revisions(self):
        old = self.q; newer = self.app.store.save(old['id'], old['revision'], title='研究者修订后的Q')
        self.input['questions'][0]['revision'] = newer['revision']
        self.input['materials'].append({'id': old['id'], 'revision': old['revision']})
        with self.assertRaises(Problem): self.call('preview')
        self.assertFalse(self.app.store.tasks())

    def test_contract_rejects_other_q_parts_unselected_sources_and_fake_supported_c(self):
        task = self.submit(); bad = []
        for field, value in [('question_id', self.other['id']), ('part', 'Q'), ('source_refs', []), ('basis', 'plan')]:
            raw = self.candidate(); raw['research_update']['changes'][-1][field] = value; bad.append(raw)
        raw = self.candidate(); raw['research_update']['changes'][-1]['source_refs'] = [{'id': self.q['id'], 'revision': self.q['revision']}]; bad.append(raw)
        raw = self.candidate(); raw['research_update']['changes'][-1]['source_refs'] = [{'id': self.source['id'], 'revision': 2}]; bad.append(raw)
        for raw in bad:
            with self.subTest(raw=raw), self.assertRaises(Problem): validate_candidate(raw, 'note', self.app, self.project['id'], task=task)
        with self.assertRaises(Problem): validate_candidate(self.candidate(), 'note', self.app, self.project['id'])

    def test_runtime_saves_candidate_without_changing_questions_or_decision_gates(self):
        view = self.complete(); self.assertEqual(view['task']['status'], 'generated')
        self.assertEqual(self.app.store.get(self.q['id']), self.q); self.assertEqual(self.app.store.get(self.other['id']), self.other)
        self.assertFalse(self.app.store.objects(self.project['id'], ['question']))
        obj = view['proposal']; self.app.store.save(obj['id'], obj['revision'], content={'blocks': [{'id': 'manual', 'text': '人工后续编辑'}]})
        fixed = self.call('read', {'project_id': self.project['id'], 'task_id': view['task']['id']})
        self.assertEqual(fixed['proposal']['sha256'], obj['sha256'])

    def test_no_materials_can_propose_a_plan_or_report_no_change_without_fabricated_ec(self):
        self.input['materials'] = []; self.input['questions'][0]['parts'] = ['A']
        task = self.submit(); raw = self.candidate(); raw['research_update']['changes'] = raw['research_update']['changes'][:1]
        raw['research_update']['changes'][0].update(basis='plan', source_refs=[])
        content = validate_candidate(raw, 'note', self.app, self.project['id'], task=task)
        self.assertEqual(content['research_update']['changes'][0]['basis'], 'plan')
        raw['research_update']['changes'] = []
        self.assertFalse(validate_candidate(raw, 'note', self.app, self.project['id'], task=task)['research_update']['changes'])
        self.assertEqual(self.app.store.get(self.q['id'])['content']['qaec']['E'], '')

    def test_multiple_target_questions_keep_independent_scopes_and_partial_adoption(self):
        self.input['questions'].append({'id': self.other['id'], 'revision': self.other['revision'], 'parts': ['A']})
        raw = self.candidate(); extra = copy.deepcopy(raw['research_update']['changes'][0])
        extra.update(id='other-a', question_id=self.other['id']); raw['research_update']['changes'].append(extra)
        view = self.complete(raw=raw); fields = self.adoption(view, ids=('c',))
        fields['expected_questions'] = [r for r in fields['expected_questions'] if r['id'] == self.q['id']]
        self.call('adopt', fields)
        self.assertEqual(self.app.store.get(self.other['id']), self.other)

    def test_multi_question_conflict_does_not_partially_adopt_the_uncontested_question(self):
        self.input['questions'].append({'id': self.other['id'], 'revision': self.other['revision'], 'parts': ['A']})
        raw = self.candidate(); extra = copy.deepcopy(raw['research_update']['changes'][0])
        extra.update(id='other-a', question_id=self.other['id']); raw['research_update']['changes'].append(extra)
        view = self.complete(raw=raw); fields = self.adoption(view, ids=('c', 'other-a'))
        self.app.store.save(self.other['id'], self.other['revision'], title='另一个Q已由研究者调整')
        with self.assertRaises(Problem): self.call('adopt', fields)
        self.assertEqual(self.app.store.get(self.q['id']), self.q)

    def test_partial_adoption_keeps_q_other_parts_status_and_other_questions(self):
        view = self.complete(); fields = self.adoption(view); fields['changes'][1]['text'] += '\n人工补充：下一步需独立重复。'
        result = self.call('adopt', fields); q = result['questions'][0]
        self.assertEqual(q['title'], self.q['title']); self.assertEqual(q['content']['qaec']['Q'], self.q['content']['qaec']['Q'])
        self.assertEqual(q['content']['qaec']['E'], self.q['content']['qaec']['E']); self.assertEqual(q['content']['research_status'], 'open')
        self.assertIn('人工补充', q['content']['qaec']['C']); self.assertEqual(self.app.store.get(self.other['id']), self.other)
        self.assertEqual(self.call('adopt', fields)['questions'][0]['revision'], q['revision'])
        with self.assertRaises(Problem): self.call('adopt', {**fields, 'request_key': 'repeat'})
        self.assertEqual(len(self.call('read', {'project_id': self.project['id'], 'task_id': view['task']['id']})['adoptions']), 2)

    def test_conflict_requires_current_exact_target_then_keeps_unselected_human_text(self):
        view = self.complete(); fields = self.adoption(view, ids=('c',))
        content = copy.deepcopy(self.q['content']); content['qaec']['A'] = '期间新增的人工分析'; content['qaec']['C'] = '人工阶段结论'
        newer = self.app.store.save(self.q['id'], self.q['revision'], content=content)
        with self.assertRaises(Problem) as error: self.call('adopt', fields)
        self.assertEqual(error.exception.code, 'conflict'); self.assertEqual(self.app.store.get(self.q['id']), newer)
        latest = self.call('read', {'project_id': self.project['id'], 'task_id': view['task']['id']})
        fields['expected_questions'] = [{k: q[k] for k in ('id', 'revision', 'sha256')} for q in latest['questions']]
        fields['changes'][0]['text'] = content['qaec']['C'] + '\n结合候选新增的有限判断。'
        q = self.call('adopt', fields)['questions'][0]; self.assertEqual(q['content']['qaec']['A'], content['qaec']['A']); self.assertIn('人工阶段结论', q['content']['qaec']['C'])
        self.assertEqual(q['metadata']['research_work_adoptions']['C']['proposal_ref'], fields['proposal_ref'])

    def test_write_failure_is_atomic_and_same_request_concurrency_does_not_repeat(self):
        view = self.complete(); fields = self.adoption(view)
        with patch.object(self.app.store, 'relate', side_effect=Problem('登记失败')):
            with self.assertRaises(Problem): self.call('adopt', fields)
        self.assertEqual(self.app.store.get(self.q['id']), self.q)
        with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(lambda _: self.call('adopt', fields), range(2)))
        self.assertEqual(results[0]['questions'], results[1]['questions'])

    def test_revoked_provider_or_source_stops_dispatch_and_restore_revokes_grant(self):
        task = self.submit(); self.app.config['providers']['local']['authorized'] = False
        runtime = Runtime(self.app); runtime.claim()
        with patch('research_partner.providers.Providers.call') as model:
            with self.assertRaises(Problem): runtime.execute(task['id'])
        model.assert_not_called()
        self.app.config['providers']['local']['authorized'] = True
        backup = self.app.backup(); destination = Path(self.tmp.name)/'restored'; restore_workspace(self.app.store.blobs/backup['sha'], destination)
        restored = App(destination, self.app.config); self.assertIsNone(restored.store.setting('research_work:grant:'+task['id']))
        self.assertEqual(restored.store.task(task['id'])['status'], 'waiting_authorization')


if __name__ == '__main__': unittest.main()
