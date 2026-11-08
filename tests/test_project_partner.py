"""One composer contract: real replies, exact saved context, explicit adoption."""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from research_partner.app import App
from research_partner.runtime import Runtime
from research_partner.store import Problem, digest
from research_partner.commission import validate_candidate


class ProjectPartner(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.app = App(root/'workspace', {'control_root': str(root/'control'), 'providers': {
            'local': {'route': 'codex', 'executable': sys.executable, 'authorized': True}}, 'default_provider': 'local'})
        self.project = self.app.dispatch({'action': 'project.create', 'title': '从想法或已有研究开始'})
        self.fields = {'project_id': self.project['id'], 'request': '我想把蛋白煮凝固，同时让蛋黄保持柔软。', 'materials': [], 'questions': [], 'native_paths': []}

    def call(self, action, fields=None, **kw):
        return self.app.dispatch({'action': 'research.partner.'+action, **(self.fields if fields is None else fields)}, **kw)

    def submit(self, key='turn', fields=None):
        fields = fields or self.fields
        preview = self.call('preview', fields)
        return self.call('submit', {**fields, 'input_pin': preview['input_pin'], 'request_key': key})

    def reply(self):
        return {'title': '先明确口感目标', 'kind': 'note', 'partner_reply': {'version': 1,
            'text': '可以先关注同一枚鸡蛋的两项目标。你希望蛋黄流动还是呈柔软凝胶？',
            'next_steps': [{'id': 'texture', 'label': '明确蛋黄目标', 'prompt': '我希望蛋黄呈柔软凝胶。'}]},
            'research_proposal': None, 'research_update': None}

    def complete(self, task=None, reply=None):
        task = task or self.submit(); runtime = Runtime(self.app)
        self.assertEqual(runtime.claim(), task['id'])
        with patch('research_partner.providers.Providers.call', return_value={'text': json.dumps(reply or self.reply()),
            'receipt': {'route': 'codex', 'session_id': 'partner-test', 'returncode': 0, 'usage': []}}) as model:
            runtime.execute(task['id'])
        view = self.call('read', {'project_id': self.project['id'], 'task_id': task['id']})
        self.assertEqual(view['task']['status'], 'generated', view['task']['error'])
        return view, model.call_args.args[1]

    def note(self, text='本批记录中10枚有7枚蛋白凝固且蛋黄柔软。'):
        return self.app.dispatch({'action': 'notes.create', 'project_id': self.project['id'], 'request_id': 'native',
            'payload': {'relative_path': 'notes/实验记录.md', 'markdown': text, 'if_absent': True}})

    def test_discussion_responds_without_creating_q_and_continues_same_thread(self):
        before = self.app.store.objects(); view, _ = self.complete()
        self.assertEqual(len(self.app.store.objects()), len(before)+1)
        self.assertFalse(self.app.dispatch({'action': 'workbench.research.read', 'project_id': self.project['id']})['questions'])
        followup = {**self.fields, 'request': '我希望是柔软凝胶。', 'previous_task_id': view['task']['id']}
        task = self.submit('next', followup)
        self.assertEqual(task['payload']['context']['partner']['conversation'][0]['reply'], self.reply()['partner_reply']['text'])
        self.assertEqual(task['payload']['context']['partner']['root_task_id'], view['task']['id'])

    def test_native_saved_note_is_pinned_and_read_by_runtime_without_overwriting_file(self):
        note = self.note(); self.fields['native_paths'] = [note['relative_path']]
        before = self.app.store.objects(); preview = self.call('preview')
        self.assertEqual(self.app.store.objects(), before)
        self.assertIn('10枚有7枚', preview['input']['native_files'][0]['text'])
        task = self.submit(); snapshot = task['payload']['context']['partner']; f = snapshot['native_files'][0]
        self.assertNotIn('text', f); self.assertEqual(snapshot['materials'][0], f['source_ref'])
        self.app.dispatch({'action': 'notes.write', 'project_id': self.project['id'], 'request_id': 'external', 'payload': {
            'relative_path': note['relative_path'], 'markdown': '后来保存的不同记录', 'expected_content_sha256': note['content_sha256'], 'encoding': 'utf-8'}})
        _, prompt = self.complete(task)
        self.assertIn('10枚有7枚', prompt); self.assertNotIn('后来保存的不同记录', prompt)
        native = self.app.dispatch({'action': 'notes.read', 'project_id': self.project['id'], 'request_id': 'check', 'payload': {'relative_path': note['relative_path']}})
        self.assertEqual(native['markdown'], '后来保存的不同记录')

    def test_stale_context_no_snapshot_or_task_and_exact_request_replay_after_file_deleted(self):
        note = self.note(); self.fields['native_paths'] = [note['relative_path']]
        preview = self.call('preview'); fields = {**self.fields, 'input_pin': preview['input_pin'], 'request_key': 'stable'}
        with self.app.notebook._locked(self.project['id']) as session:
            path = session['root']/note['relative_path']; path.write_text('另一份内容')
        before = self.app.store.objects()
        with self.assertRaises(Problem) as err: self.call('submit', fields)
        self.assertEqual(err.exception.code, 'conflict'); self.assertEqual(before, self.app.store.objects()); self.assertFalse(self.app.store.tasks())
        fields['input_pin'] = self.call('preview')['input_pin']; task = self.call('submit', fields); path.unlink()
        self.assertEqual(self.call('submit', fields)['id'], task['id'])
        with self.assertRaises(Problem): self.call('submit', {**fields, 'request': 'changed'})

    def test_native_paths_reject_traversal_symlink_hardlink_and_unsupported_binary(self):
        note = self.note()
        with self.app.notebook._locked(self.project['id']) as session:
            root = session['root']; (root/'notes/link.md').symlink_to(root/note['relative_path'])
            import os
            os.link(root/note['relative_path'], root/'notes/hard.md')
        for path in ['../secrets.md', 'notes/../private.md', 'notes/link.md', 'notes/hard.md', 'manuscript/source.docx', '/tmp/test.py']:
            with self.subTest(path=path), self.assertRaises(Problem): self.call('preview', {**self.fields, 'native_paths': [path]})
        self.assertFalse(self.app.store.tasks())

    def test_snapshot_failure_rolls_back_and_readonly_or_agent_cannot_dispatch(self):
        note = self.note(); self.fields['native_paths'] = [note['relative_path']]
        preview = self.call('preview'); fields = {**self.fields, 'input_pin': preview['input_pin'], 'request_key': 'rollback'}
        before = self.app.store.objects()
        with patch.object(self.app.store, 'submit', side_effect=Problem('queue failed')):
            with self.assertRaises(Problem): self.call('submit', fields)
        self.assertEqual(before, self.app.store.objects()); self.assertFalse(self.app.store.tasks())
        with self.assertRaises(Problem): self.call('preview', scope=[])
        with self.assertRaises(Problem): self.call('submit', fields, principal={'kind': 'agent'})
        with self.assertRaises(Problem): self.app.dispatch({'action': 'task.submit', 'project_id': self.project['id'], 'request': 'bypass', 'kind': 'research_partner'})

    def test_new_q_proposal_reuses_adoption_and_preserves_e_c_empty(self):
        raw = self.reply(); raw['research_proposal'] = {'version': 1, 'interpretation': '关注联合口感目标。', 'candidates': [{
            'id': 'texture', 'question': '哪种煮蛋方法使蛋白凝固且蛋黄柔软？', 'unknown': '加热程序如何兼顾两项目标？',
            'rationale': '两部分的热响应不同。', 'assumptions': ['质构评价标准需预先约定。'], 'analysis_plan': '比较各方法逐枚联合达标率。',
            'evidence_needed': ['质构和温度记录'], 'source_refs': []}], 'clarifications': [], 'limitations': ['尚无结果。']}
        view, _ = self.complete(reply=raw)
        fields = {'project_id': self.project['id'], 'task_id': view['task']['id'], 'proposal_ref': {k: view['proposal'][k] for k in ('id','revision','sha256')},
            'candidates': [{'id': 'texture', 'title': '哪种煮蛋方法使蛋白凝固且蛋黄柔软？'}], 'request_key': 'adopt-q'}
        result = self.call('questions.adopt', fields); q = result['questions'][0]
        self.assertEqual(q['content']['qaec']['E'], ''); self.assertEqual(q['content']['qaec']['C'], '')
        self.assertEqual(q['metadata']['origin']['kind'], 'research_partner')
        self.assertEqual(self.call('questions.adopt', fields)['questions'][0], q)
        self.assertEqual(len(self.call('questions.read', {'project_id': self.project['id'], 'task_id': view['task']['id']})['adoptions']), 1)

    def test_existing_q_work_reuses_partial_adoption_cas_and_native_citations(self):
        q = self.app.dispatch({'action': 'workbench.question.create', 'project_id': self.project['id'], 'title': '哪种煮法更接近目标？', 'request_key': 'q'})
        note = self.note(); self.fields.update(questions=[{'id': q['id'], 'revision': q['revision'], 'parts': ['A','E','C']}], native_paths=[note['relative_path']])
        task = self.submit(); source = task['payload']['context']['partner']['materials'][-1]
        raw = self.reply(); raw['research_update'] = {'version': 1, 'summary': '核对已有记录，提出阶段判断。', 'changes': [{
            'id': 'c', 'question_id': q['id'], 'part': 'C', 'mode': 'replace', 'text': '该批次7/10达到两项目标，仍需更多独立重复。',
            'rationale': '采用保存版实验记录。', 'basis': 'supported', 'source_refs': [{k: source[k] for k in ('id','revision')}]}], 'limitations': ['只有一个批次。']}
        view, prompt = self.complete(task, raw); self.assertIn('10枚有7枚', prompt)
        view = self.call('work.read', {'project_id': self.project['id'], 'task_id': task['id']})
        fields = {'project_id': self.project['id'], 'task_id': task['id'], 'proposal_ref': {k: view['proposal'][k] for k in ('id','revision','sha256')},
            'changes': [{'id': 'c', 'text': '人工修改后的有限结论。'}], 'expected_questions': [{k: view['questions'][0][k] for k in ('id','revision','sha256')}], 'request_key': 'adopt-c'}
        result = self.call('work.adopt', fields); adopted = result['questions'][0]
        self.assertEqual(adopted['content']['qaec']['C'], '人工修改后的有限结论。'); self.assertEqual(adopted['content']['qaec']['E'], q['content']['qaec']['E'])
        self.assertEqual(self.call('work.adopt', fields)['questions'][0], adopted)
        self.assertEqual(len(self.call('work.read', {'project_id': self.project['id'], 'task_id': task['id']})['adoptions']), 1)

    def test_shared_source_withdrawal_blocks_later_conversation_and_its_publication(self):
        other = self.app.dispatch({'action': 'project.create', 'title': '来源项目'})
        source = self.app.store.create('note', '共享记录', other['id'], {'markdown': '只在共享期间可读。'}, {'shared_with': [self.project['id']]})
        self.fields['materials'] = [{'id': source['id'], 'revision': source['revision']}]
        previous, _ = self.complete()
        follow = {**self.fields, 'materials': [], 'request': '接着讨论', 'previous_task_id': previous['task']['id']}
        task = self.submit('follow-source', follow)
        self.assertTrue(task['payload']['context']['partner']['conversation_sources'])
        self.app.store.save(source['id'], source['revision'], metadata={'shared_with': []}, merge=False)
        runtime = Runtime(self.app); self.assertEqual(runtime.claim(), task['id'])
        with patch('research_partner.providers.Providers.call') as model:
            with self.assertRaises(Problem): runtime.execute(task['id'])
        self.assertFalse(model.called)
        history = self.call('history', {'project_id': self.project['id']})
        self.assertTrue(all(x['proposal'] is None for x in history['items']))
        self.assertNotIn('只在共享期间可读', json.dumps(history, ensure_ascii=False))

    def test_native_python_full_text_is_not_executed_and_oversize_is_explicit(self):
        self.app.dispatch({'action': 'recipe.script.write', 'project_id': self.project['id'], 'request_id': 'code',
            'payload': {'filename': 'study.py', 'code': 'raise RuntimeError("must not execute")\n', 'expected_sha256': None}})
        self.fields['native_paths'] = ['scripts/study.py']
        preview = self.call('preview')
        self.assertIn('must not execute', preview['input']['native_files'][0]['text'])
        view, prompt = self.complete()
        self.assertIn('must not execute', prompt)
        self.assertEqual(view['task']['status'], 'generated')
        self.fields['native_paths'] = [self.note('大'*16000)['relative_path']]
        with self.assertRaises(Problem) as err: self.call('preview')
        self.assertEqual(err.exception.code, 'context_limit')

    def test_work_cannot_target_unselected_q_or_invent_evidence_and_provider_rechecked(self):
        q = self.app.dispatch({'action': 'workbench.question.create', 'project_id': self.project['id'], 'title': '未知问题', 'request_key': 'q'})
        task = self.submit(); raw = self.reply(); raw['research_update'] = {'version': 1, 'summary': '候选', 'changes': [{
            'id': 'c', 'question_id': q['id'], 'part': 'C', 'mode': 'replace', 'text': '凭空结论', 'rationale': '无来源', 'basis': 'supported', 'source_refs': []}], 'limitations': []}
        with self.assertRaises(Problem): validate_candidate(raw, 'note', self.app, self.project['id'], task=task)
        self.app.config['providers']['local']['authorized'] = False
        runtime = Runtime(self.app); self.assertEqual(runtime.claim(), task['id'])
        with patch('research_partner.providers.Providers.call') as model:
            with self.assertRaises(Problem): runtime.execute(task['id'])
        self.assertFalse(model.called); self.assertNotEqual(self.app.store.task(task['id'])['status'], 'generated')


if __name__ == '__main__': unittest.main()
