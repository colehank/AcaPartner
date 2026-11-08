"""Real Store, source identity, conflicts and existing TeX rendering adapter."""
import shutil
import base64
import io
import zipfile
import tempfile
import unittest
from pathlib import Path

from research_partner.app import App
from research_partner.article_workspace import initialize_output
from research_partner.artifacts import ArtifactEngine
from research_partner.project_files import ProjectFiles
from research_partner.store import Problem


class DocumentAdapters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='acapartner-documents-')
        self.app = App(self.tmp.name)
        with self.app.store.transaction() as c:
            project = self.app.store.create('project', 'Document fixture', connection=c)
            initialized = initialize_output(self.app.store, c, project)
        self.project = initialized['project']
        self.paper = initialized['manuscript']
        self.tex = '\\documentclass{article}\n\\begin{document}\nNative source $x^2+1$.\n\\end{document}\n'

    def tearDown(self):
        self.tmp.cleanup()

    def read(self, scope=None):
        return self.app.dispatch({'action': 'document.read', 'project_id': self.project['id']}, scope)

    def save(self, fmt, source, revision=None, key='save-1'):
        return self.app.dispatch({'action': 'document.save', 'project_id': self.project['id'],
                                 'object_id': self.paper['id'], 'expected_revision': revision or self.paper['revision'],
                                 'request_key': key, 'format': fmt, 'source': source})

    def select(self, fmt, revision, key='select-1'):
        return self.app.dispatch({'action': 'document.select', 'project_id': self.project['id'],
                                 'object_id': self.paper['id'], 'expected_revision': revision,
                                 'request_key': key, 'format': fmt})

    def test_read_is_not_a_source_conversion(self):
        before = self.app.store.get(self.paper['id'])
        view = self.read()
        self.assertEqual(view['source_state']['mode'], 'structured')
        self.assertFalse(view['adapters']['univer']['docx_exchange_ready'])
        self.assertIsNone(view['sources']['univer'])
        self.assertEqual(self.app.store.get(self.paper['id']), before)

    def test_native_sources_preserve_each_other_and_old_blocks(self):
        latex = self.save('latex', self.tex)
        snapshot = {'id': self.paper['id'], 'body': {'dataStream': 'Native Office text\r\n'},
                    'documentStyle': {'pageSize': {'width': 794, 'height': 1123}}}
        office = self.save('univer', snapshot, latex['revision'], 'save-2')
        self.assertEqual(office['sources']['latex'], self.tex)
        self.assertEqual(office['sources']['univer'], snapshot)
        self.assertEqual(office['structured_blocks'], self.paper['content']['blocks'])
        self.assertEqual(office['source_state']['mode'], 'latex')
        office = self.select('univer', office['revision'])
        restored = self.save('latex', self.tex + '% edited\n', office['revision'], 'save-3')
        self.assertEqual(restored['source_state']['mode'], 'univer')
        restored = self.select('latex', restored['revision'], 'select-2')
        self.assertEqual(restored['sources']['univer'], snapshot)
        self.assertEqual(self.app.store.get(self.paper['id'], latex['revision'])['content']['latex'], self.tex)
        mirror = ProjectFiles(self.app.store).sync_project(self.project['id'])
        self.assertEqual(mirror['status'], 'ready')
        self.assertTrue(any(e['path'].endswith('.tex') and e['role'] == 'native_manuscript' for e in mirror['entries']))

    def test_replay_and_conflict_do_not_overwrite(self):
        saved = self.save('latex', self.tex)
        replay = self.save('latex', self.tex)
        self.assertTrue(replay['replayed'])
        self.assertEqual(saved['revision'], replay['revision'])
        with self.assertRaises(Problem) as conflict:
            self.save('latex', 'stale replacement', key='other-request')
        self.assertEqual(conflict.exception.code, 'conflict')
        with self.assertRaises(Problem) as changed_request:
            self.save('latex', 'different request body', saved['revision'])
        self.assertEqual(changed_request.exception.code, 'idempotency_conflict')
        self.assertEqual(self.read()['sources']['latex'], self.tex)
        from research_partner.compatibility import check_workspace, SUPPORTED_FEATURES
        with self.assertRaises(Problem) as downgrade:
            check_workspace(self.tmp.name, supported=SUPPORTED_FEATURES - {'native_manuscript_sources_v1'})
        self.assertEqual(downgrade.exception.code, 'runtime_incompatible')

    def test_scope_and_document_identity(self):
        with self.assertRaises(Problem) as forbidden:
            self.read([])
        self.assertEqual(forbidden.exception.status, 403)
        with self.assertRaises(Problem) as wrong:
            self.save('univer', {'id': 'other-paper', 'body': {'dataStream': 'wrong\r\n'}})
        self.assertEqual(wrong.exception.code, 'source_identity')
        self.assertEqual(self.read()['revision'], self.paper['revision'])

    def test_univer_never_exports_old_structured_text_as_docx(self):
        snapshot = {'id': self.paper['id'], 'body': {'dataStream': 'Office source\r\n'}, 'documentStyle': {}}
        self.save('univer', snapshot)
        with self.assertRaises(Problem) as error:
            ArtifactEngine(self.app.store).export(self.paper['id'], 'docx')
        self.assertEqual(error.exception.code, 'document_adapter_required')
        with self.assertRaises(Problem) as legacy:
            self.app.dispatch({'action': 'manuscript.format.render', 'object_id': self.paper['id'],
                               'expected_revision': self.read()['revision']})
        self.assertEqual(legacy.exception.code, 'document_adapter_required')
        mirror = ProjectFiles(self.app.store).sync_project(self.project['id'])
        self.assertEqual(mirror['status'], 'ready')
        self.assertTrue(any(e['path'].endswith('.univer.json') for e in mirror['entries']))
        self.assertFalse(any(e['role'] in {'manuscript', 'chapter'} and e.get('object_id') == self.paper['id'] for e in mirror['entries']))

    def docx(self):
        return (Path(__file__).resolve().parents[1] / 'tests/fixtures/documents/input.docx').read_bytes()

    def save_docx(self, raw=None, revision=None, key='docx-1'):
        return self.save('docx', {'base64': base64.b64encode(raw or self.docx()).decode(), 'filename': 'paper.docx'}, revision, key)

    def checkout(self, revision, key='checkout-1'):
        return self.app.dispatch({'action': 'document.checkout', 'project_id': self.project['id'],
                                 'object_id': self.paper['id'], 'expected_revision': revision, 'request_key': key})

    def commit(self, checkout, key='commit-1', scope=None):
        return self.app.dispatch({'action': 'document.commit', 'project_id': self.project['id'],
                                 'object_id': self.paper['id'], 'expected_revision': checkout['base_revision'],
                                 'checkout_id': checkout['id'], 'request_key': key}, scope)

    def test_docx_exact_bytes_history_mirror_and_no_stale_conversion(self):
        latex = self.save('latex', self.tex)
        saved = self.save_docx(revision=latex['revision'])
        self.assertEqual(saved['source_state']['mode'], 'latex')
        saved = self.select('docx', saved['revision'])
        self.assertEqual(saved['source_state']['mode'], 'docx')
        self.assertEqual(saved['sources']['latex'], self.tex)
        self.assertEqual(saved['structured_blocks'], self.paper['content']['blocks'])
        asset = saved['sources']['docx']
        self.assertEqual((self.app.store.blobs / asset['sha']).read_bytes(), self.docx())
        self.assertEqual(self.app.store.get(self.paper['id'], latex['revision'])['content']['paper_source_mode'], 'latex')
        exported = ArtifactEngine(self.app.store).export(self.paper['id'], 'docx')
        self.assertEqual(exported['asset']['sha'], asset['sha'])
        with self.assertRaises(Problem) as blocked:
            ArtifactEngine(self.app.store).export(self.paper['id'], 'pdf')
        self.assertEqual(blocked.exception.code, 'document_adapter_required')
        mirror = ProjectFiles(self.app.store).sync_project(self.project['id'])
        self.assertEqual(mirror['status'], 'ready', str(mirror))
        entries = [e for e in mirror['entries'] if e.get('object_id') == self.paper['id'] and e['role'] == 'native_manuscript']
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0]['path'].endswith('.docx'))
        self.assertEqual(entries[0]['asset_sha256'], asset['sha'])
        self.assertTrue(self.save_docx(revision=latex['revision'])['replayed'])

    def test_primary_binding_changes_only_by_explicit_selection(self):
        first = self.save_docx()
        edited = self.save('latex', self.tex, first['revision'], 'independent-latex')
        self.assertEqual(edited['source_state']['mode'], 'docx')
        mirror = ProjectFiles(self.app.store).sync_project(self.project['id'])
        files = {e['source_format']: e['role'] for e in mirror['entries'] if e.get('object_id') == self.paper['id'] and e.get('source_format')}
        self.assertEqual(files, {'docx': 'native_manuscript', 'latex': 'retained_manuscript'})
        selected = self.select('latex', edited['revision'])
        self.assertEqual(selected['source_state']['mode'], 'latex')
        self.assertTrue(self.select('latex', edited['revision'])['replayed'])
        with self.assertRaises(Problem) as stale:
            self.select('docx', edited['revision'], 'stale-selection')
        self.assertEqual(stale.exception.code, 'conflict')
        checkout = self.checkout(selected['revision'])
        committed = self.commit(checkout)
        self.assertEqual(committed['source_state']['mode'], 'latex')
        self.assertEqual(committed['sources']['latex'], self.tex)
        with self.assertRaises(Problem) as export:
            ArtifactEngine(self.app.store).export(self.paper['id'], 'docx')
        self.assertEqual(export.exception.code, 'document_adapter_required')
        from research_partner.compatibility import check_workspace, SUPPORTED_FEATURES
        with self.assertRaises(Problem) as downgrade:
            check_workspace(self.tmp.name, supported=SUPPORTED_FEATURES - {'native_primary_source_v1'})
        self.assertEqual(downgrade.exception.code, 'runtime_incompatible')

    def test_primary_selection_requires_saved_source_and_scope(self):
        with self.assertRaises(Problem) as missing:
            self.select('docx', self.paper['revision'])
        self.assertEqual(missing.exception.code, 'source_required')
        saved = self.save_docx()
        with self.assertRaises(Problem) as denied:
            self.app.dispatch({'action': 'document.select', 'project_id': self.project['id'],
                               'object_id': self.paper['id'], 'expected_revision': saved['revision'],
                               'request_key': 'denied-select', 'format': 'docx'}, [])
        self.assertEqual(denied.exception.status, 403)

    def test_docx_working_copy_commit_and_conflict_retains_file(self):
        saved = self.save_docx()
        checkout = self.checkout(saved['revision'])
        path = Path(checkout['path'])
        self.assertEqual(path.read_bytes(), self.docx())
        self.assertEqual(self.checkout(saved['revision']), checkout)
        # Simulate an Agent using ordinary OOXML file tools, without an editor SDK.
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.docx())) as src, zipfile.ZipFile(output, 'w') as dst:
            for entry in src.infolist():
                raw = src.read(entry)
                if entry.filename == 'word/document.xml':
                    raw = raw.replace(b'Research', b'Agent research')
                dst.writestr(entry, raw)
        path.write_bytes(output.getvalue())
        committed = self.commit(checkout)
        self.assertEqual((self.app.store.blobs / committed['sources']['docx']['sha']).read_bytes(), output.getvalue())
        self.assertEqual(self.commit(checkout)['revision'], committed['revision'])
        with self.assertRaises(Problem) as stale:
            self.commit(checkout, 'stale-commit')
        self.assertEqual(stale.exception.code, 'conflict')
        self.assertEqual(path.read_bytes(), output.getvalue())
        self.assertEqual((self.app.store.blobs / saved['sources']['docx']['sha']).read_bytes(), self.docx())
        with self.assertRaises(Problem) as denied:
            self.commit(checkout, 'denied', [])
        self.assertEqual(denied.exception.status, 403)

    def test_docx_rejects_bad_packages_links_and_missing_file_without_revision(self):
        before = self.read()['revision']
        for raw in [b'not a zip', b'PK\x03\x04broken']:
            with self.assertRaises(Problem):
                self.save_docx(raw, key='invalid')
        bad = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(self.docx())) as src, zipfile.ZipFile(bad, 'w') as dst:
            for entry in src.infolist():dst.writestr(entry, src.read(entry))
            dst.writestr('../escape', b'x')
        with self.assertRaises(Problem):self.save_docx(bad.getvalue(), key='traversal')
        self.assertEqual(self.read()['revision'], before)
        saved = self.save_docx()
        checkout = self.checkout(saved['revision'])
        path = Path(checkout['path']);path.unlink();path.symlink_to(self.app.store.blobs / saved['sources']['docx']['sha'])
        with self.assertRaises(Problem) as linked:self.commit(checkout)
        self.assertEqual(linked.exception.code, 'source_unreadable')
        path.unlink()
        with self.assertRaises(Problem):self.commit(checkout)
        self.assertEqual(self.read()['revision'], saved['revision'])

    @unittest.skipUnless(shutil.which('xelatex') or shutil.which('pdflatex'), 'TeX runtime unavailable')
    def test_compile_independent_latex_file_keeps_docx_primary(self):
        first = self.save_docx()
        saved = self.save('latex', self.tex, first['revision'], 'independent-tex')
        rendered = self.app.dispatch({'action': 'document.render', 'project_id': self.project['id'],
                                     'object_id': self.paper['id'], 'expected_revision': saved['revision'],
                                     'request_key': 'render-retained-latex'})
        self.assertEqual(rendered['format'], 'latex')
        self.assertEqual(self.read()['source_state']['mode'], 'docx')
        sha = rendered['asset']['sha'] if isinstance(rendered['asset'], dict) else rendered['asset']
        self.assertTrue((self.app.store.blobs / sha).read_bytes().startswith(b'%PDF-'))
        self.assertEqual(self.app.store.export_records(self.paper['id']), [])

    @unittest.skipUnless(shutil.which('xelatex') or shutil.which('pdflatex'), 'TeX runtime unavailable')
    def test_actual_latex_pdf_and_source_binding(self):
        saved = self.save('latex', self.tex)
        data = {'action': 'document.render', 'project_id': self.project['id'], 'object_id': self.paper['id'],
                'expected_revision': saved['revision'], 'request_key': 'render-1'}
        rendered = self.app.dispatch(data)
        asset = rendered['asset']
        sha = asset['sha'] if isinstance(asset, dict) else asset
        self.assertTrue((self.app.store.blobs / sha).read_bytes().startswith(b'%PDF-'))
        self.assertEqual(rendered['revision'], saved['revision'])
        self.assertEqual(self.app.dispatch(data), rendered)
        self.save('latex', self.tex + '% changed\n', saved['revision'], 'save-2')
        self.assertNotEqual(self.read()['render']['revision'], self.read()['revision'])


if __name__ == '__main__':
    unittest.main()
