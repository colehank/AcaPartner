"""Local setup checks: temporary files only; no sockets, models or installation."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from research_partner.local_accounts import LocalAccounts
from research_partner.store import Store


ROOT = Path(__file__).resolve().parents[1]


class StartLocal(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location('start_local', ROOT / 'tools/start_local.py')
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)
        self.temporary = tempfile.TemporaryDirectory(prefix='rp-local-setup-')
        self.root = Path(self.temporary.name)
        self.data = self.root / 'private data'
        self.bundle = self.root / 'bundle'
        self.frontend = self.bundle / 'research_partner/web/workdesk'
        self.frontend.mkdir(parents=True)
        (self.frontend / 'index.html').write_text('<html><script type="module" src="/workdesk/assets/app.js"></script><link rel="stylesheet" href="/workdesk/assets/app.css"></html>')
        (self.frontend / 'assets').mkdir()
        (self.frontend / 'assets/app.js').write_text('console.log("built");')
        (self.frontend / 'assets/app.css').write_text('body{margin:0}')
        original = self.tool.check_frontend
        self.frontend_patch = mock.patch.object(self.tool, 'check_frontend', side_effect=lambda root: original(self.bundle))
        self.frontend_patch.start()
        self.addCleanup(self.frontend_patch.stop)
        self.addCleanup(self.temporary.cleanup)

    def run_setup(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = self.tool.main(['--data-dir', str(self.data), *args])
        return code, output.getvalue(), errors.getvalue()

    def prepare(self):
        code, output, errors = self.run_setup('--prepare')
        self.assertEqual(code, 0, errors)
        return json.loads(output)

    def test_plan_is_read_only_and_uses_requested_port(self):
        with mock.patch.object(self.tool, 'invoke_cli', side_effect=AssertionError('plan executed code')):
            code, output, errors = self.run_setup('--plan', '--port', '9012')
        self.assertEqual(code, 0, errors)
        result = json.loads(output)
        self.assertEqual(result['url'], 'http://127.0.0.1:9012/')
        self.assertFalse(result['files_written'])
        self.assertFalse(self.data.exists())

    def test_prepare_creates_private_files_without_registration_or_runner(self):
        with mock.patch('research_partner.runtime.Runtime', side_effect=AssertionError('Runtime constructed')):
            result = self.prepare()
        self.assertTrue(result['ready'])
        self.assertFalse(result['runtime_started'])
        self.assertTrue((self.data / 'workspace/research.sqlite3').is_file())
        for path in [self.data, self.data / 'workspace', self.data / 'auth']:
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)
        for path in [self.data / 'auth/owner.token', self.data / 'config.json']:
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertGreaterEqual(len((self.data / 'auth/owner.token').read_text().strip()), 24)
        self.assertFalse((self.data / 'auth/accounts.json').exists())
        config = json.loads((self.data / 'config.json').read_text())
        self.assertTrue(config['workdesk_w1a'])
        self.assertEqual(config['providers'], {})
        self.assertFalse(Path(config['local_accounts_file']).is_relative_to(self.data / 'workspace'))
        self.assertNotIn((self.data / 'auth/owner.token').read_text().strip(), json.dumps(result))

    def test_repeated_prepare_keeps_account_token_config_and_budget(self):
        self.prepare()
        LocalAccounts(self.data / 'auth/accounts.json').register('local-owner', 'private-long-password')
        config_path = self.data / 'config.json'
        config = json.loads(config_path.read_text())
        config.update(providers={'existing': {'route': 'unconfigured'}}, default_provider='existing',
                      development_budget=str(self.data / 'budget.json'))
        config_path.write_text(json.dumps(config) + '\n')
        budget = self.data / 'budget.json'
        budget.write_text('{"paused":true,"model_calls":3}\n')
        files = [config_path, self.data / 'auth/owner.token', self.data / 'auth/accounts.json', budget]
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode) for path in files}
        self.prepare()
        self.assertEqual(before, {path: (path.read_bytes(), path.stat().st_mtime_ns, path.stat().st_mode) for path in files})

    def test_normal_launch_uses_real_cli_with_no_runtime_and_preserves_queue(self):
        self.prepare()
        store = Store(self.data / 'workspace')
        task = store.submit({'request': 'Retain old queued task', 'provider': 'unconfigured'}, 'old-task')
        store.set_setting('budget:' + task['id'], {'model_calls': 2, 'elapsed_seconds': 17})
        before = store.tasks()
        server = mock.Mock(server_port=9013)
        apps = []

        def fake_serve(app, host, port):
            self.assertIsNone(app.runner)
            self.assertEqual((host, port), ('127.0.0.1', 9013))
            self.assertTrue(app.config['local_accounts_file'])
            apps.append(app)
            return server

        with mock.patch('research_partner.runtime.Runtime', side_effect=AssertionError('Runtime constructed')) as runtime, \
                mock.patch('research_partner.server.serve', side_effect=fake_serve), mock.patch('signal.signal'):
            code, output, errors = self.run_setup('--port', '9013')
        self.assertEqual(code, 0, errors)
        runtime.assert_not_called()
        self.assertEqual(len(apps), 1)
        server.serve_forever.assert_called_once()
        server.server_close.assert_called_once()
        self.assertEqual(before, store.tasks())
        self.assertEqual(store.setting('budget:' + task['id']), {'model_calls': 2, 'elapsed_seconds': 17})
        self.assertFalse((self.data / 'workspace/runtime.lock').exists())
        self.assertTrue(json.loads(output.splitlines()[-1])['workbench_only'])

    def test_missing_or_incomplete_frontend_fails_before_writing_data(self):
        for missing in ['index.html', 'assets/app.js', 'assets/app.css']:
            with self.subTest(missing=missing):
                path = self.frontend / missing
                saved = path.read_bytes()
                path.unlink()
                code, _, errors = self.run_setup('--prepare')
                self.assertEqual(code, 2)
                self.assertIn('build the frontend first', errors)
                self.assertFalse(self.data.exists())
                path.write_bytes(saved)

    def test_nonprivate_existing_directory_and_file_are_preserved(self):
        self.data.mkdir(mode=0o755)
        self.data.chmod(0o755)
        code, _, errors = self.run_setup('--prepare')
        self.assertEqual(code, 2)
        self.assertIn('0700', errors)
        self.assertEqual(self.data.stat().st_mode & 0o777, 0o755)
        self.assertEqual(list(self.data.iterdir()), [])
        self.data.chmod(0o700)
        self.prepare()
        token = self.data / 'auth/owner.token'
        before = token.read_bytes()
        token.chmod(0o644)
        code, _, errors = self.run_setup('--prepare')
        self.assertEqual(code, 2)
        self.assertIn('0600', errors)
        self.assertEqual(token.read_bytes(), before)
        self.assertEqual(token.stat().st_mode & 0o777, 0o644)

    def test_symlink_credentials_are_rejected_without_replacing_target(self):
        self.prepare()
        token = self.data / 'auth/owner.token'
        target = self.root / 'keep-token'
        token.rename(target)
        token.symlink_to(target)
        before = target.read_bytes()
        code, _, errors = self.run_setup('--prepare')
        self.assertEqual(code, 2)
        self.assertIn('regular file', errors)
        self.assertTrue(token.is_symlink())
        self.assertEqual(target.read_bytes(), before)

    def test_existing_configuration_missing_auth_is_preserved(self):
        self.data.mkdir(mode=0o700)
        config = self.data / 'config.json'
        config.write_text('{"workdesk_w1a":true,"providers":{"keep":{}}}\n')
        config.chmod(0o600)
        before = config.read_bytes()
        code, _, errors = self.run_setup('--prepare')
        self.assertEqual(code, 2)
        self.assertIn('access_token_file', errors)
        self.assertEqual(config.read_bytes(), before)
        self.assertFalse((self.data / 'workspace').exists())

    def test_missing_existing_owner_token_is_not_rotated(self):
        self.prepare()
        token = self.data / 'auth/owner.token'
        token.unlink()
        code, _, errors = self.run_setup('--prepare')
        self.assertEqual(code, 2)
        self.assertIn('restore it from your private backup', errors)
        self.assertFalse(token.exists())

    def test_accounts_cannot_be_inside_exportable_workspace(self):
        self.prepare()
        config = self.data / 'config.json'
        value = json.loads(config.read_text())
        value['local_accounts_file'] = str(self.data / 'workspace/accounts.json')
        config.write_text(json.dumps(value))
        code, _, errors = self.run_setup('--prepare')
        self.assertEqual(code, 2)
        self.assertIn('outside the workspace', errors)
        self.assertFalse((self.data / 'workspace/accounts.json').exists())

    def test_help_invalid_parameters_and_python_floor_do_not_create_data(self):
        for args, expected in [(['--help'], 0), (['--port', '0'], 2), (['--port', '65536'], 2),
                               (['--host', '0.0.0.0'], 2), (['--prepare', '--plan'], 2)]:
            with self.subTest(args=args), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    self.tool.main(['--data-dir', str(self.data), *args])
                self.assertEqual(caught.exception.code, expected)
        with mock.patch.object(sys, 'version_info', (3, 11)):
            code, _, errors = self.run_setup('--prepare')
        self.assertEqual(code, 2)
        self.assertIn('Python 3.12', errors)
        self.assertFalse(self.data.exists())

    def test_default_uses_home_or_absolute_xdg_without_machine_paths(self):
        with mock.patch.object(Path, 'home', return_value=Path('/example/home')), \
                mock.patch.object(sys, 'platform', 'linux'), mock.patch.dict(os.environ, {'XDG_DATA_HOME': ''}):
            self.assertEqual(self.tool.default_data_dir(), Path('/example/home/.local/share/research-partner'))
        with mock.patch.dict(os.environ, {'XDG_DATA_HOME': str(self.root / 'xdg')}):
            self.assertEqual(self.tool.default_data_dir(), self.root / 'xdg/research-partner')
        with mock.patch.object(Path, 'home', return_value=Path('/example/home')), mock.patch.object(sys, 'platform', 'darwin'):
            self.assertEqual(self.tool.default_data_dir(), Path('/example/home/Library/Application Support/Research Partner'))


if __name__ == '__main__':
    unittest.main()
