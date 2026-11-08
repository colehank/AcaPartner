"""Actual loopback HTTP/SQLite auth tests with ephemeral local fixture tokens."""
import base64
import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading
import time
import unittest

from research_partner.app import App
from research_partner.server import serve


class BrowserSessionHTTP(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rp-http-auth-')
        self.root = Path(self.tmp.name)
        self.owner_token = secrets.token_urlsafe(32)
        self.client_token = secrets.token_urlsafe(32)
        self.owner_file = self.root / 'owner-token'
        self.client_file = self.root / 'client-token'
        for path, value in [(self.owner_file, self.owner_token), (self.client_file, self.client_token)]:
            path.write_text(value); path.chmod(0o600)
        self.app = App(self.root / 'workspace', {'access_token_file': str(self.owner_file),
            'clients': [{'token_file': str(self.client_file), 'projects': []}]})
        self.a = self.app.dispatch({'action': 'project.create', 'title': 'First fixture project'})
        self.b = self.app.dispatch({'action': 'project.create', 'title': 'Second fixture project'})
        self.app.config['clients'][0]['projects'] = [self.a['id']]
        self.notes = {}
        self.assets = {}
        for project in [self.a, self.b]:
            self.notes[project['id']] = self.app.dispatch({'action': 'object.create', 'project_id': project['id'],
                'kind': 'note', 'title': 'Fixture note', 'content': {'blocks': [{'id': 'b1', 'kind': 'paragraph', 'text': project['title']}]}})
            self.assets[project['id']] = self.app.store.add_asset(project['title'].encode(), 'fixture.txt', 'text/plain', {'project_id': project['id']})
        self.server = serve(self.app, '127.0.0.1', 0)
        self.port = self.server.server_port
        self.base = 'http://127.0.0.1:' + str(self.port)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01})
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
        self.assertFalse(self.thread.is_alive())
        self.tmp.cleanup()

    def request(self, path, method='GET', data=None, cookie=None, bearer=None, headers=None):
        values = dict(headers or {})
        if cookie: values['Cookie'] = cookie
        if bearer: values['Authorization'] = 'Bearer ' + bearer
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            values.setdefault('Content-Type', 'application/json')
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=values)
            response = conn.getresponse(); raw = response.read()
            result = json.loads(raw) if response.getheader('Content-Type', '').startswith('application/json') else raw
            return response.status, dict(response.getheaders()), result
        finally: conn.close()

    def login(self, token):
        status, headers, value = self.request('/api/auth/login', 'POST', {'token': token},
            headers={'Origin': self.base, 'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(status, 200, value)
        self.assertEqual(value['result'], {'required': True, 'authenticated': True, 'session_active': True})
        cookie = headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie); self.assertIn('SameSite=Strict', cookie)
        self.assertIn('Path=/', cookie); self.assertNotIn(token, cookie + json.dumps(value))
        return cookie.split(';', 1)[0]

    def test_local_graph_worker_allows_wasm_without_javascript_eval(self):
        status, headers, _ = self.request('/')
        self.assertEqual(status, 200)
        policy = headers['Content-Security-Policy']
        script = next(p.strip() for p in policy.split(';') if p.strip().startswith('script-src '))
        self.assertEqual(script, "script-src 'self' 'wasm-unsafe-eval'")
        self.assertNotIn("'unsafe-eval'", policy)
        self.assertIn("worker-src 'self' blob:", policy)

    def test_real_cookie_scope_rotation_revocation_and_logout(self):
        self.assertEqual(self.request('/')[0], 200)
        self.assertEqual(self.request('/app.js')[0], 200)
        self.assertEqual(self.request('/api/auth/status')[2]['result'],
            {'required': True, 'authenticated': False, 'session_active': False})
        for path in ['/api/state', '/api/health', '/api/objects/' + self.a['id'], '/api/assets/' + self.assets[self.a['id']]['sha']]:
            self.assertEqual(self.request(path)[0], 401)
        denied = self.request('/api/auth/login', 'POST', {'token': 'invalid-local-fixture-token-long-enough'})
        self.assertEqual(denied[0], 401); self.assertNotIn('Set-Cookie', denied[1])
        cookie = self.login(self.client_token)
        status, _, state = self.request('/api/state', cookie=cookie)
        self.assertEqual(status, 200)
        identities = {obj['id'] for obj in state['objects'] + state['projects']}
        self.assertIn(self.a['id'], identities); self.assertNotIn(self.b['id'], identities)
        self.assertEqual(self.request('/api/objects/' + self.a['id'], cookie=cookie)[0], 200)
        self.assertEqual(self.request('/api/objects/' + self.b['id'], cookie=cookie)[0], 403)
        self.assertEqual(self.request('/api/assets/' + self.assets[self.a['id']]['sha'], cookie=cookie)[0], 200)
        self.assertEqual(self.request('/api/assets/' + self.assets[self.b['id']]['sha'], cookie=cookie)[0], 403)
        note = self.notes[self.a['id']]
        updated = self.request('/api/action', 'POST', {'action': 'object.save', 'id': note['id'],
            'expected_revision': note['revision'], 'content': {'blocks': [{'id': 'b1', 'kind': 'paragraph', 'text': 'Actual scoped HTTP edit'}]}},
            cookie=cookie, headers={'X-CSRF-Token': state['csrf'], 'Origin': self.base})
        self.assertEqual(updated[0], 200, updated[2])
        other = self.notes[self.b['id']]
        denied = self.request('/api/action', 'POST', {'action': 'object.save', 'id': other['id'], 'expected_revision': 1,
            'content': {'blocks': []}}, cookie=cookie, headers={'X-CSRF-Token': state['csrf']})
        self.assertEqual(denied[0], 403)
        self.assertEqual(self.app.store.get(other['id'])['revision'], 1)
        denied = self.request('/api/action', 'POST', {'action': 'asset.import', 'project_id': self.b['id'],
            'filename': 'denied.txt', 'base64': base64.b64encode(b'fixture').decode()}, cookie=cookie,
            headers={'X-CSRF-Token': state['csrf']})
        self.assertEqual(denied[0], 403)
        rotated = secrets.token_urlsafe(32); self.client_file.write_text(rotated)
        self.assertEqual(self.request('/api/state', cookie=cookie)[0], 401)
        self.assertEqual(self.request('/api/state', bearer=self.client_token)[0], 401)
        self.assertEqual(self.request('/api/state', bearer=rotated)[0], 200)
        self.assertFalse(self.request('/api/auth/status', cookie=cookie)[2]['result']['authenticated'])
        cookie = self.login(rotated)
        self.assertEqual(self.request('/api/auth/logout', 'POST', {}, cookie=cookie)[0], 403)
        self.assertEqual(self.request('/api/state', cookie=cookie)[0], 200)
        logout = self.request('/api/auth/logout', 'POST', {}, cookie=cookie,
            headers={'X-CSRF-Token': state['csrf'], 'Origin': self.base})
        self.assertEqual(logout[0], 200); self.assertIn('Max-Age=0', logout[1]['Set-Cookie'])
        self.assertEqual(self.request('/api/state', cookie=cookie)[0], 401)
        cookie = self.login(rotated); self.client_file.unlink()
        self.assertEqual(self.request('/api/state', cookie=cookie)[0], 401)
        owner_cookie = self.login(self.owner_token)
        self.assertEqual(self.request('/api/objects/' + self.b['id'], cookie=owner_cookie)[0], 200)
        self.owner_file.write_text(secrets.token_urlsafe(32))
        self.assertEqual(self.request('/api/state', cookie=owner_cookie)[0], 401)
        self.assertEqual(self.request('/api/state', bearer=self.owner_token)[0], 401)

    def test_origin_content_type_and_host_guards(self):
        for headers in [{'Origin': 'https://unrelated.example'}, {'Origin': 'null'},
                        {'Sec-Fetch-Site': 'cross-site'}, {'Sec-Fetch-Site': 'same-site'}, {'Host': 'unrelated.example'}]:
            self.assertEqual(self.request('/api/auth/login', 'POST', {'token': self.owner_token}, headers=headers)[0], 403)
        self.assertEqual(self.request('/api/auth/login', 'POST', {'token': self.owner_token},
            headers={'Content-Type': 'text/plain'})[0], 415)
        self.assertEqual(self.request('/api/auth/login', 'POST', {'token': {}})[0], 401)
        self.assertEqual(self.request('/../research.sqlite3')[0], 404)
        self.assertEqual(self.request('/api/../research.sqlite3')[0], 401)

    def test_current_scope_and_file_permissions_are_rechecked(self):
        cookie = self.login(self.client_token)
        self.app.config['clients'][0]['projects'] = []
        self.assertEqual(self.request('/api/objects/' + self.a['id'], cookie=cookie)[0], 403)
        self.client_file.chmod(0o644)
        self.assertEqual(self.request('/api/state', cookie=cookie)[0], 401)

    def test_client_only_configuration_stays_required_and_fail_closed(self):
        self.app.config.pop('access_token_file')
        self.assertTrue(self.request('/api/auth/status')[2]['result']['required'])
        self.assertEqual(self.request('/api/state')[0], 401)
        cookie = self.login(self.client_token)
        self.client_file.unlink()
        self.assertEqual(self.request('/api/state', cookie=cookie)[0], 401)
        self.assertEqual(self.request('/api/state')[0], 401)

    def test_anonymous_loopback_requires_no_configured_credentials(self):
        self.app.config.pop('access_token_file'); self.app.config['clients'] = []
        self.assertEqual(self.request('/api/auth/status')[2]['result'],
            {'required': False, 'authenticated': True, 'session_active': False})
        self.assertEqual(self.request('/api/state')[0], 200)
        self.assertEqual(self.request('/api/state', bearer='invalid-even-on-anonymous-loopback')[0], 401)

    def test_memory_session_expires(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(timeout=5)
        self.app.config['browser_session_seconds'] = .05
        self.server = serve(self.app, '127.0.0.1', 0); self.port = self.server.server_port
        self.base = 'http://127.0.0.1:' + str(self.port)
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01})
        self.thread.start()
        cookie = self.login(self.owner_token)
        time.sleep(.08)
        self.assertEqual(self.request('/api/state', cookie=cookie)[0], 401)
        self.assertFalse(self.request('/api/auth/status', cookie=cookie)[2]['result']['session_active'])

    def test_native_history_http_requires_exact_note_identity_and_live_project_permission(self):
        notes = {}
        for project in (self.a, self.b):
            notes[project['id']] = self.app.dispatch({'action':'notes.create',
                'project_id':project['id'],'request_id':'history-'+project['id'],
                'payload':{'relative_path':'notes/history.md','markdown':'# 历史\r\n'+project['title'],
                           'if_absent':True}})
        cookie = self.login(self.client_token)
        csrf = self.request('/api/state', cookie=cookie)[2]['csrf']
        def read(project, **extra):
            note = notes[project['id']]
            return self.request('/api/action','POST',{'action':'desk.note.revision.read',
                'project_id':project['id'],'relative_path':'notes/history.md','note_id':note['id'],
                'revision':note['revision'],'content_sha256':note['content_sha256'],**extra},
                cookie=cookie,headers={'X-CSRF-Token':csrf})
        good = read(self.a)
        self.assertEqual(good[0],200,good[2])
        self.assertEqual(good[2]['result']['markdown'],notes[self.a['id']]['markdown'])
        self.assertEqual(read(self.b)[0],403)
        self.assertEqual(read(self.a,note_id=notes[self.b['id']]['id'])[0],409)
        self.app.config['clients'][0]['projects'] = []
        self.assertEqual(read(self.a)[0],403)
        self.app.config['clients'][0]['projects'] = [self.a['id']]
        self.client_file.unlink()
        self.assertEqual(read(self.a)[0],401)

    def test_bearer_invalidity_does_not_fall_back_to_cookie(self):
        cookie = self.login(self.owner_token)
        self.assertEqual(self.request('/api/state', cookie=cookie, bearer='invalid-bearer')[0], 401)


if __name__ == '__main__': unittest.main(verbosity=2)
