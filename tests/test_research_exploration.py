"""Project-level question exploration through the existing task interface."""
import hashlib
import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from research_partner.app import App
from research_partner.commission import candidate_schema, validate_candidate
from research_partner.runtime import Runtime
from research_partner.store import Problem, digest


def candidate(refs=None):
    return {'title': '煮蛋研究的问题提案', 'kind': 'note', 'research_proposal': {
        'version': 1, 'interpretation': '需要先明确“更好”指什么。',
        'candidates': [{'id': 'texture', 'question': '哪些加热程序能兼顾蛋白凝固与蛋黄柔软？',
            'unknown': '不同程序能否在同一枚蛋上满足两项目标。',
            'rationale': '这是对用户口感目标的一种可讨论解释。',
            'assumptions': ['用户关注口感，尚待确认。'],
            'analysis_plan': '明确质构判据后比较各程序的逐枚联合表现。',
            'evidence_needed': ['各程序逐枚的蛋白与蛋黄测量记录。'],
            'source_refs': refs or []}],
        'clarifications': [{'id': 'goal', 'question': '主要关注口感、营养还是效率？',
                            'why_it_matters': '决定研究目标与评价指标。'}],
        'limitations': ['没有实验数据，不能判断哪种程序更好。']}}


class ResearchExploration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app = App(Path(self.tmp.name) / 'workspace', {
            'control_root': str(Path(self.tmp.name) / 'control'),
            'providers': {'local': {'route': 'codex', 'executable': sys.executable, 'authorized': True}},
            'default_provider': 'local'})
        self.project = self.app.store.create('project', '探索项目',
            content={'background': '用户观察：不同煮法产生不同口感。', 'description': '原始研究方向'})
        self.input = {'project_id': self.project['id'], 'request': '我想研究怎么把鸡蛋煮得更好。', 'materials': []}

    def call(self, action, fields=None, **kwargs):
        return self.app.dispatch({'action': 'research.exploration.' + action,
                                  **(self.input if fields is None else fields)}, **kwargs)

    def submit(self, key='explore-1'):
        preview = self.call('preview')
        return self.call('submit', {**self.input, 'input_pin': preview['input_pin'],
            'provider_id': 'local', 'budget': {'max_model_calls': 1, 'timeout_seconds': 60}, 'request_key': key})

    def complete(self, task, raw=None):
        runtime = Runtime(self.app); self.assertEqual(runtime.claim(), task['id'])
        receipt = {'route': 'codex', 'session_id': 'test-session', 'returncode': 0, 'usage': []}
        with patch('research_partner.providers.Providers.call', return_value={'text': json.dumps(raw or candidate()), 'receipt': receipt}):
            runtime.execute(task['id'])
        return self.call('read', {'project_id': self.project['id'], 'task_id': task['id']})

    def adoption(self, view, key='adopt-1', title='哪种方法兼顾蛋白凝固与蛋黄柔软？'):
        return {'project_id': self.project['id'], 'task_id': view['task']['id'],
                'proposal_ref': {k: view['proposal'][k] for k in ('id', 'revision', 'sha256')},
                'candidates': [{'id': 'texture', 'title': title}], 'request_key': key}

    def test_preview_without_q_or_materials_is_read_only_and_keeps_background(self):
        before = self.app.store.objects()
        preview = self.call('preview')
        self.assertEqual(preview['input']['background']['text'], self.project['content']['background'])
        self.assertEqual(preview['input']['materials'], [])
        self.assertEqual(self.app.store.objects(), before)
        self.assertFalse(self.app.store.tasks())

    def test_submit_uses_existing_queue_and_replays_after_project_changes(self):
        preview = self.call('preview')
        fields = {**self.input, 'input_pin': preview['input_pin'], 'provider_id': 'local',
                  'budget': {'max_model_calls': 1, 'timeout_seconds': 60}, 'request_key': 'stable'}
        first = self.call('submit', fields)
        self.assertEqual(first['payload']['kind'], 'research_exploration')
        self.assertEqual(first['payload']['context']['output'], 'note')
        self.app.store.save(self.project['id'], self.project['revision'], title='后来改名')
        replay = self.call('submit', fields)
        self.assertEqual(first['id'], replay['id'])
        self.assertEqual(len(self.app.store.tasks()), 1)
        with self.assertRaises(Problem) as error:
            self.call('submit', {**fields, 'request': '不同请求'})
        self.assertEqual(error.exception.code, 'idempotency_conflict')

    def test_stale_preview_cannot_enqueue_new_work(self):
        preview = self.call('preview')
        self.app.store.save(self.project['id'], self.project['revision'], content={'background': '新的认识'})
        with self.assertRaises(Problem) as error:
            self.call('submit', {**self.input, 'input_pin': preview['input_pin'], 'request_key': 'stale'})
        self.assertEqual(error.exception.code, 'conflict')
        self.assertFalse(self.app.store.tasks())

    def test_selected_research_q_includes_complete_qaec_but_no_private_settings(self):
        q = self.app.dispatch({'action': 'workbench.question.create', 'project_id': self.project['id'],
                              'title': '已有问题', 'request_key': 'q'})
        q = self.app.dispatch({'action': 'workbench.question.save', 'project_id': self.project['id'],
            'id': q['id'], 'expected_revision': q['revision'], 'title': q['title'], 'status': 'open',
            'qaec': {'Q': '未知', 'A': '计划', 'E': '已有观察', 'C': '有条件的判断'}, 'request_key': 'q-save'})
        self.input['materials'] = [{'id': q['id'], 'revision': q['revision']}]
        self.app.store.set_setting('preferences', {'machine_profiles': [{'address': 'private-host'}]})
        task = self.submit()
        selected = task['payload']['context']['exploration']['research_questions'][0]
        self.assertEqual(selected['qaec'], q['content']['qaec'])
        self.assertNotIn('private-host', json.dumps(task['payload']))

    def test_selected_registered_text_reaches_actual_prompt_without_private_metadata(self):
        source = self.app.store.create('note', '操作记录', self.project['id'],
            {'text': '逐枚记录鸡蛋大小和下锅温度。'}, {'private_host': 'not-research-context'})
        self.input['materials'] = [{'id': source['id'], 'revision': source['revision']}]
        task = self.submit(); runtime = Runtime(self.app); runtime.claim()
        receipt = {'route': 'codex', 'session_id': 'text-input-session', 'returncode': 0, 'usage': []}
        with patch('research_partner.providers.Providers.call', return_value={'text': json.dumps(candidate()), 'receipt': receipt}) as provider:
            runtime.execute(task['id'])
        sent = str(provider.call_args)
        self.assertIn('逐枚记录鸡蛋大小和下锅温度', sent)
        self.assertNotIn('not-research-context', sent)

    def test_project_scope_provider_and_reserved_kind_are_checked(self):
        with self.assertRaises(Problem): self.call('preview', scope=set())
        preview = self.call('preview')
        self.app.config['providers']['local']['authorized'] = False
        with self.assertRaises(Problem):
            self.call('submit', {**self.input, 'input_pin': preview['input_pin'], 'request_key': 'no-grant'})
        with self.assertRaises(Problem):
            self.app.dispatch({'action': 'task.submit', 'project_id': self.project['id'],
                'request': 'forge', 'materials': [], 'kind': 'research_exploration'})
        self.assertFalse(self.app.store.tasks())

    def test_proposal_contract_is_scoped_and_rendered_from_one_source(self):
        task = self.submit()
        raw = candidate()
        content = validate_candidate(raw, 'note', self.app, self.project['id'], task=task)
        self.assertEqual(content['research_proposal'], raw['research_proposal'])
        self.assertIn('哪些加热程序', '\n'.join(b['text'] for b in content['blocks']))
        self.assertIn('research_proposal', candidate_schema('note', task))
        with self.assertRaises(Problem): validate_candidate(raw, 'note', self.app, self.project['id'])
        ordinary = {'title': '普通报告', 'kind': 'report', 'blocks': [{'id': 'p', 'text': '实际正文'}]}
        self.assertEqual(validate_candidate(ordinary, 'report', self.app, self.project['id'])['blocks'], ordinary['blocks'])

    def test_invalid_proposals_and_unselected_sources_are_rejected(self):
        task = self.submit()
        other = self.app.store.create('report', '未选择的资料', self.project['id'], {'blocks': [{'id': 'x', 'text': '来源'}]})
        bad = []
        value = candidate(); value['research_proposal']['candidates'][0]['C'] = '虚构结论'; bad.append(value)
        value = candidate(); value['research_proposal']['candidates'] *= 2; bad.append(value)
        value = candidate([{'id': other['id'], 'revision': 1}]); bad.append(value)
        value = candidate(); value['blocks'] = [{'id': 'other', 'text': '第二份可覆盖的正文'}]; bad.append(value)
        for value in bad:
            with self.subTest(value=value), self.assertRaises(Problem):
                validate_candidate(value, 'note', self.app, self.project['id'], task=task)

    def test_clarification_only_is_valid_without_fabricated_questions(self):
        task = self.submit(); raw = candidate()
        raw['research_proposal']['candidates'] = []
        content = validate_candidate(raw, 'note', self.app, self.project['id'], task=task)
        self.assertEqual(content['research_proposal']['candidates'], [])
        self.assertEqual(content['claims'], [])

    def test_adoption_creates_q_with_origin_without_fabricating_evidence(self):
        view = self.complete(self.submit()); fields = self.adoption(view)
        result = self.call('adopt', fields); q = result['questions'][0]
        self.assertEqual(q['title'], fields['candidates'][0]['title'])
        self.assertEqual(q['metadata']['origin']['proposal_ref'], fields['proposal_ref'])
        self.assertEqual(q['metadata']['origin']['root_task_id'], view['task']['id'])
        self.assertEqual(q['content']['research_status'], 'open')
        self.assertEqual(q['content']['qaec']['E'], '')
        self.assertEqual(q['content']['qaec']['C'], '')
        self.assertIn('尚未执行', q['content']['qaec']['A'])
        self.assertEqual(self.call('adopt', fields)['questions'][0]['id'], q['id'])
        self.assertEqual(len(self.app.store.objects(self.project['id'], ['concept'])), 1)
        self.assertTrue(self.call('read', {'project_id': self.project['id'], 'task_id': view['task']['id']})['adopted'])
        with self.assertRaises(Problem): self.call('adopt', self.adoption(view, key='duplicate'))

    def test_adoption_version_and_batch_membership_are_atomic(self):
        view = self.complete(self.submit()); fields = self.adoption(view)
        fields['proposal_ref']['revision'] = 2
        with self.assertRaises(Problem): self.call('adopt', fields)
        fields = self.adoption(view)
        fields['candidates'].append({'id': 'unrecognized', 'title': '不属于原提案'})
        with self.assertRaises(Problem): self.call('adopt', fields)
        self.assertFalse(self.app.store.objects(self.project['id'], ['concept']))

    def test_adoption_write_failure_rolls_back_question_relations_and_ledger(self):
        view = self.complete(self.submit()); fields = self.adoption(view)
        with patch.object(self.app.store, 'relate', side_effect=Problem('模拟登记失败')):
            with self.assertRaises(Problem): self.call('adopt', fields)
        self.assertFalse(self.app.store.objects(self.project['id'], ['concept']))
        result = self.call('adopt', fields)
        self.assertEqual(len(result['questions']), 1)
        self.assertFalse(result['replayed'])

    def test_concurrent_same_adoption_returns_one_question(self):
        from concurrent.futures import ThreadPoolExecutor
        view = self.complete(self.submit()); fields = self.adoption(view)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.call('adopt', fields), range(2)))
        self.assertEqual(results[0]['questions'][0]['id'], results[1]['questions'][0]['id'])
        self.assertEqual(len(self.app.store.objects(self.project['id'], ['concept'])), 1)

    def test_user_can_change_goal_in_a_linked_exploration_without_rewriting_old_proposal(self):
        first = self.complete(self.submit())
        self.input.update(previous_task_id=first['task']['id'], request='改为关注不同初温下的适用范围。')
        task = self.submit('second-exploration')
        previous = task['payload']['context']['exploration']['previous_proposal']
        self.assertEqual(previous['sha256'], first['proposal']['sha256'])
        self.assertEqual(previous['original_request'], first['task']['payload']['request'])
        self.assertEqual(task['payload']['exploration_root_task_id'], first['task']['id'])
        revised = candidate(); revised['research_proposal']['candidates'][0].update(id='initial-temperature', question='不同初温如何影响方法的适用范围？')
        second = self.complete(task, revised)
        self.assertEqual(second['root_task_id'], first['task']['id'])
        self.assertEqual([h['task_id'] for h in second['history']], [task['id'], first['task']['id']])
        original = self.call('read', {'project_id': self.project['id'], 'task_id': first['task']['id']})
        self.assertEqual(original['proposal']['sha256'], first['proposal']['sha256'])
        self.assertNotEqual(original['proposal']['id'], second['proposal']['id'])
        self.assertFalse(self.app.store.objects(self.project['id'], ['concept']))

    def test_model_references_must_match_selected_version_and_permission(self):
        source = self.app.store.create('report', '已有结果', self.project['id'], {'blocks': [{'id': 'p', 'text': '观察'}]})
        self.input['materials'] = [{'id': source['id'], 'revision': 1}]
        task = self.submit()
        good = candidate(self.input['materials'])
        self.assertEqual(validate_candidate(good, 'note', self.app, self.project['id'], task=task)['source_refs'], self.input['materials'])
        newer = self.app.store.save(source['id'], source['revision'], content={'blocks': [{'id': 'p', 'text': '新观察'}]})
        with self.assertRaises(Problem):
            validate_candidate(candidate([{'id': newer['id'], 'revision': newer['revision']}]), 'note', self.app, self.project['id'], task=task)

    def test_source_revocation_is_observed_before_model_dispatch(self):
        other = self.app.store.create('project', '资料所有者')
        source = self.app.store.create('report', '共享记录', other['id'], {'blocks': [{'id': 'p', 'text': '观察'}]},
                                       {'shared_with': [self.project['id']]})
        self.input['materials'] = [{'id': source['id'], 'revision': 1}]
        task = self.submit()
        self.app.store.save(source['id'], source['revision'], metadata={})
        runtime = Runtime(self.app); runtime.claim()
        with patch('research_partner.providers.Providers.call') as model:
            with self.assertRaises(Problem): runtime.execute(task['id'])
        model.assert_not_called()

    def test_backup_restore_revokes_execution_grant(self):
        from research_partner.app import restore_workspace
        task = self.submit(); backup = self.app.backup()
        destination = Path(self.tmp.name) / 'restored'
        restore_workspace(self.app.store.blobs / backup['sha'], destination)
        restored = App(destination, self.app.config)
        self.assertIsNone(restored.store.setting('research_exploration:grant:' + task['id']))
        self.assertEqual(restored.store.task(task['id'])['status'], 'waiting_authorization')

    def test_authority_revocation_stops_execution_before_model_dispatch(self):
        token = Path(self.tmp.name) / 'client-token'; token.write_text('x' * 32); token.chmod(0o600)
        self.app.config['clients'] = [{'token_file': str(token), 'projects': [self.project['id']]}]
        principal = {'kind': 'credential', 'credential_sha256': hashlib.sha256(token.read_bytes()).hexdigest()}
        scope = [self.project['id']]
        preview = self.call('preview', scope=scope, principal=principal)
        task = self.call('submit', {**self.input, 'input_pin': preview['input_pin'], 'request_key': 'scoped'},
                         scope=scope, principal=principal)
        self.app.config['clients'][0]['projects'] = []
        runtime = Runtime(self.app); self.assertEqual(runtime.claim(), task['id'])
        with patch('research_partner.providers.Providers.call') as model:
            with self.assertRaises(Problem) as error: runtime.execute(task['id'])
        self.assertEqual(error.exception.code, 'forbidden')
        model.assert_not_called()

    def test_failure_during_publication_rolls_back_and_reuses_model_checkpoint(self):
        task = self.submit(); runtime = Runtime(self.app); runtime.claim()
        reply = {'text': json.dumps(candidate()), 'receipt': {'route': 'codex', 'session_id': 'session', 'returncode': 0, 'usage': []}}
        with patch('research_partner.providers.Providers.call', return_value=reply) as model:
            with patch.object(self.app.store, 'relate', side_effect=Problem('模拟登记失败')):
                with self.assertRaises(Problem): runtime.execute(task['id'])
            self.assertFalse(self.app.store.objects(self.project['id'], ['note']))
            self.assertFalse(self.app.store.task(task['id'])['result'])
            runtime.execute(task['id'])
            self.assertEqual(model.call_count, 1)
        self.assertEqual(len(self.app.store.objects(self.project['id'], ['note'])), 1)
        self.assertEqual(self.app.store.task(task['id'])['status'], 'generated')

    def test_runtime_returns_fixed_proposal_without_creating_q_or_decisions(self):
        task = self.submit(); runtime = Runtime(self.app)
        self.assertEqual(runtime.claim(), task['id'])
        receipt = {'route': 'codex', 'session_id': 'test-session', 'returncode': 0, 'usage': []}
        with patch('research_partner.providers.Providers.call', return_value={'text': json.dumps(candidate(), ensure_ascii=False), 'receipt': receipt}):
            runtime.execute(task['id'])
        result = self.call('read', {'project_id': self.project['id'], 'task_id': task['id']})
        self.assertEqual(result['task']['status'], 'generated')
        self.assertEqual(result['proposal']['content']['research_proposal'], candidate()['research_proposal'])
        self.assertFalse(self.app.store.objects(self.project['id'], ['concept', 'question']))
        self.assertEqual(self.app.store.get(self.project['id']), self.project)
        # Editing current HEAD cannot replace the task's exact saved proposal.
        obj = self.app.store.get(result['proposal']['id'])
        self.app.store.save(obj['id'], obj['revision'], content={'blocks': [{'id': 'manual', 'text': '人工后续修改'}]})
        fixed = self.call('read', {'project_id': self.project['id'], 'task_id': task['id']})
        self.assertEqual(fixed['proposal']['revision'], 1)
        self.assertEqual(fixed['proposal']['sha256'], digest(obj))

    def test_http_route_uses_existing_csrf_and_returns_task_identity(self):
        from research_partner.server import serve
        server = serve(self.app, '127.0.0.1', 0)
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
        worker.start()
        def request(path, data=None, csrf=None):
            conn = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            headers = {'Content-Type': 'application/json'}
            if csrf: headers['X-CSRF-Token'] = csrf
            try:
                conn.request('POST' if data else 'GET', path, json.dumps(data) if data else None, headers)
                response = conn.getresponse(); return response.status, json.loads(response.read())
            finally: conn.close()
        try:
            _, state = request('/api/state')
            body = {'action': 'research.exploration.preview', **self.input}
            self.assertEqual(request('/api/action', body)[0], 403)
            code, preview = request('/api/action', body, state['csrf'])
            self.assertEqual(code, 200)
            code, response = request('/api/action', {**body, 'action': 'research.exploration.submit',
                'input_pin': preview['result']['input_pin'], 'request_key': 'http-explore'}, state['csrf'])
            self.assertEqual(code, 200)
            self.assertEqual(response['result']['payload']['kind'], 'research_exploration')
        finally:
            server.shutdown(); server.server_close(); worker.join(timeout=5)


if __name__ == '__main__':
    unittest.main()
