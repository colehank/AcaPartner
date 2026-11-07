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
                "build/frontend/workdesk/assets/app.js": "export const app=1;",
                "frontend/legacy/index.html": "<html>legacy</html>",
                "src/research_partner/resources/runtime-features.json": json.dumps(
                    {"schema_version": 1, "runtime_features": []}
                ),
                "build/frontend/workdesk/index.html": '<script type="module" src="/workdesk/assets/app.js"></script>',
                "frontend/workdesk/src/main.tsx": "export const app = 1;",
                "frontend/workdesk/package-lock.json": "{}",
                "tools/start_local.py": "# local start",
                "docs/user/quickstart.md": "Start here",
                "tests/integration/test_start_local.py": "# isolated",
                "tests/support/http_fixture.py": "# shared HTTP fixture",
                "tests/unit/test_action_contract.py": "# action contract",
                "tests/unit/test_store_results.py": "# transaction boundaries",
                "tests/unit/test_render_output.py": "# bounded rendering",
                "tests/unit/test_provider_availability.py": "# optional transport",
                "tests/integration/test_command_routing.py": "# ordered domain dispatch",
                "tests/integration/test_contracts.py": "# public contracts",
                "tests/unit/test_object_policies.py": "# transactional policies",
                "tests/integration/test_http_boundary.py": "# HTTP boundary",
                "tests/unit/test_render_contract.py": "# worker boundary",
                "tools/check_backend.py": "# shared quality entrypoint",
                "src/research_partner/execution/process_output.py": "# standalone capture helper",
                "src/research_partner/rendering/contract.py": "# standalone render contract",
                "docs/development/backend-development.md": "# backend development",
                ".github/workflows/backend.yml": "# read-only backend CI",
                "environments/core-generation-runtime.lock": "# public dependency pins",
                "environments/continuation.md": "private task history",
                "environments/RESUMED41.json": "old authorization",
                "docs/product/current-20261010/spec/sources/private.md": "source context",
                "tools/codex_thread_dispatch.py": "author-specific dispatcher",
                "frontend/workdesk/tests/developer-budget.ts": "author ledger path",
                "frontend/legacy/tests/old-fixture.mjs": "old integration fixture",
                ".private/access.token": "never distribute",
                "src/research_partner/accounts.json": "private account record in wrong folder",
                "src/research_partner/.env.production": "private environment in wrong folder",
                "src/research_partner/research.sqlite3": "private workspace in wrong folder",
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
                self.assertIn("frontend/workdesk/src/main.tsx", names)
                self.assertIn("frontend/workdesk/package-lock.json", names)
                self.assertIn("docs/user/quickstart.md", names)
                for name in (
                    "tests/support/http_fixture.py",
                    "tests/unit/test_action_contract.py",
                    "tests/unit/test_store_results.py",
                    "tests/unit/test_render_output.py",
                    "tests/unit/test_provider_availability.py",
                    "tests/integration/test_command_routing.py",
                    "tests/integration/test_contracts.py",
                    "tests/unit/test_object_policies.py",
                    "tests/integration/test_http_boundary.py",
                    "tests/unit/test_render_contract.py",
                    "tools/check_backend.py",
                    "src/research_partner/execution/process_output.py",
                    "src/research_partner/rendering/contract.py",
                    "docs/development/backend-development.md",
                    ".github/workflows/backend.yml",
                ):
                    self.assertIn(name, names)
                self.assertNotIn("environments/RESUMED41.json", names)
            target = Path(tmp) / "installed"
            result = install(package["path"], target)
            self.assertTrue(result["installed"])
            self.assertEqual(
                (target / "frontend/workdesk/src/main.tsx").read_text(),
                files["frontend/workdesk/src/main.tsx"],
            )
            self.assertFalse((target / ".private").exists())


if __name__ == "__main__":
    unittest.main()
