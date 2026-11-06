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
            root = Path(tmp) / "source"
            files = {
                "research_partner/runtime-features.json": json.dumps(
                    {"schema_version": 1, "runtime_features": []}
                ),
                "research_partner/web/workdesk/index.html": "<html>current app</html>",
                "frontend/src/main.tsx": "export const app = 1;",
                "frontend/package-lock.json": "{}",
                "tools/start_local.py": "# local start",
                "docs/quickstart.md": "Start here",
                "tests/test_start_local.py": "# isolated",
                "tests/http_fixture.py": "# shared HTTP fixture",
                "tests/test_action_contract.py": "# action contract",
                "tests/test_store_results.py": "# transaction boundaries",
                "tests/test_render_output.py": "# bounded rendering",
                "tests/test_provider_availability.py": "# optional transport",
                "research_partner/process_output.py": "# standalone capture helper",
                "docs/backend-development.md": "# backend development",
                ".github/workflows/backend.yml": "# read-only backend CI",
                "development/core-generation-runtime.lock": "# public dependency pins",
                "development/continuation.md": "private task history",
                "development/RESUMED41.json": "old authorization",
                "docs/product/current-20261010/spec/sources/private.md": "source context",
                "tools/codex_thread_dispatch.py": "author-specific dispatcher",
                "frontend/tests/developer-budget.ts": "author ledger path",
                "research_partner/web/tests/old-fixture.mjs": "old integration fixture",
                ".private/access.token": "never distribute",
                "research_partner/accounts.json": "private account record in wrong folder",
                "research_partner/.env.production": "private environment in wrong folder",
                "research_partner/research.sqlite3": "private workspace in wrong folder",
            }
            for name, value in files.items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(value)
            package = build(root, Path(tmp) / "output")
            with tarfile.open(package["path"]) as archive:
                names = set(archive.getnames())
                for name in files:
                    self.assertEqual(name in names, distributed_source(name), name)
                self.assertIn("frontend/src/main.tsx", names)
                self.assertIn("frontend/package-lock.json", names)
                self.assertIn("docs/quickstart.md", names)
                for name in (
                    "tests/http_fixture.py",
                    "tests/test_action_contract.py",
                    "tests/test_store_results.py",
                    "tests/test_render_output.py",
                    "tests/test_provider_availability.py",
                    "research_partner/process_output.py",
                    "docs/backend-development.md",
                    ".github/workflows/backend.yml",
                ):
                    self.assertIn(name, names)
                self.assertNotIn("development/RESUMED41.json", names)
            target = Path(tmp) / "installed"
            result = install(package["path"], target)
            self.assertTrue(result["installed"])
            self.assertEqual(
                (target / "frontend/src/main.tsx").read_text(),
                files["frontend/src/main.tsx"],
            )
            self.assertFalse((target / ".private").exists())


if __name__ == "__main__":
    unittest.main()
