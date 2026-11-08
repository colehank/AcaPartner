"""Public packaging has a positive scope, independent of the author's checkout."""
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from tools.build import build, distributed_source
from tools.install import install


class PublicDistribution(unittest.TestCase):
    def test_only_product_files_and_self_contained_tests_are_distributed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'source'
            files = {
                'research_partner/runtime-features.json': json.dumps({'schema_version': 1, 'runtime_features': []}),
                'research_partner/web/workdesk/index.html': '<html>current app</html>',
                'frontend/src/workbench/main.tsx': 'export const app = 1;',
                'frontend/src/workbench/theme/tokens.css': ':root { --surface: white; }',
                'frontend/editors.html': '<html>native editor entry</html>',
                'frontend/public/licenses/superdoc/DOCX-ENGINE-LICENSE.md': 'upstream engine terms',
                'tests/fixtures/documents/input.docx': 'document fixture',
                'tests/helpers/inspect_docx.py': '# round-trip inspector',
                'frontend/package-lock.json': '{}', 'tools/start_local.py': '# local start',
                'docs/quickstart.md': 'Start here', 'tests/test_start_local.py': '# isolated',
                'docs/product/README.md': 'Canonical product context',
                'docs/product/glossary.md': 'Canonical domain terms',
                'docs/design-system.md': 'Canonical design rules',
                'docs/sources/private.docx': 'original user-supplied input',
                '.impeccable/design.json': '{}',
                '.impeccable/surfaces/frontend-index-html.md': 'design-tool page notes',
                'development/core-generation-runtime.lock': '# public dependency pins',
                'development/continuation.md': 'private task history',
                'development/RESUMED41.json': 'old authorization',
                'docs/product/current-20261010/spec/sources/private.md': 'source context',
                'tools/codex_thread_dispatch.py': 'author-specific dispatcher',
                'frontend/tests/developer-budget.ts': 'author ledger path',
                'research_partner/web/tests/old-fixture.mjs': 'old integration fixture',
                '.private/access.token': 'never distribute',
                'research_partner/accounts.json': 'private account record in wrong folder',
                'research_partner/.env.production': 'private environment in wrong folder',
                'research_partner/research.sqlite3': 'private workspace in wrong folder',
            }
            for name, value in files.items():
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_text(value)
            package = build(root, Path(tmp) / 'output')
            with tarfile.open(package['path']) as archive:
                names = set(archive.getnames())
                for name in files:
                    self.assertEqual(name in names, distributed_source(name), name)
                for name in (
                    'frontend/src/workbench/main.tsx',
                    'frontend/src/workbench/theme/tokens.css',
                    'frontend/editors.html',
                    'frontend/public/licenses/superdoc/DOCX-ENGINE-LICENSE.md',
                    'tests/fixtures/documents/input.docx',
                    'tests/helpers/inspect_docx.py',
                    'docs/product/README.md',
                    'docs/product/glossary.md',
                    'docs/design-system.md',
                ):
                    self.assertIn(name, names)
                self.assertIn('frontend/package-lock.json', names)
                self.assertIn('docs/quickstart.md', names)
                self.assertNotIn('development/RESUMED41.json', names)
                self.assertNotIn('docs/sources/private.docx', names)
                self.assertFalse(any(name.startswith('.impeccable/') for name in names))
            target = Path(tmp) / 'installed'
            result = install(package['path'], target)
            self.assertTrue(result['installed'])
            self.assertEqual((target / 'frontend/src/workbench/main.tsx').read_text(), files['frontend/src/workbench/main.tsx'])
            self.assertFalse((target / '.private').exists())


if __name__ == '__main__': unittest.main()
