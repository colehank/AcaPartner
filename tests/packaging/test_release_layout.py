"""src 发行的输入冻结、资源装配及离线预检边界。"""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from research_partner.packaging.compatibility import verify_release
from research_partner.storage.store import Problem
from tools.build import WEB_RESOURCES, build, distribution_inputs
from tools.install import install


class ReleaseLayout(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        self.output = Path(self.temporary.name) / "output"
        self.target = Path(self.temporary.name) / "installed"
        files = {
            "src/research_partner/__init__.py": "",
            "src/research_partner/__main__.py": "",
            "src/research_partner/app.py": "",
            "src/research_partner/storage/store.py": "",
            "src/research_partner/execution/runtime.py": "",
            "src/research_partner/packaging/compatibility.py": "",
            "src/research_partner/resources/runtime-features.json": json.dumps(
                {"schema_version": 1, "runtime_features": []}
            ),
            "src/research_partner/resources/fonts/DejaVuSans.ttf": "fixture-font",
            "src/research_partner/resources/agent_runtime/acaworker-plugin.mjs": "// fixture",
            "src/research_partner/resources/agent_runtime/research-strategy.md": "fixture strategy",
            "frontend/legacy/index.html": "legacy",
            "build/frontend/workdesk/index.html": '<script src="/workdesk/app.js"></script>',
            "build/frontend/workdesk/app.js": "console.log('fixture');",
        }
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def freeze(self):
        path = Path(self.temporary.name) / "frozen.json"
        path.write_text(
            json.dumps(
                {
                    "files": {
                        name: hashlib.sha256(
                            (self.root / name).read_bytes()
                        ).hexdigest()
                        for name in set(distribution_inputs(self.root).values())
                    }
                }
            )
        )
        return path

    def release(self):
        result = build(self.root, self.output)
        install(result["path"], self.target)
        return verify_release(self.target)

    def test_source_map_binds_generated_resources_without_polluting_source(self):
        inputs = distribution_inputs(self.root)
        self.assertEqual(
            inputs[f"{WEB_RESOURCES}/workdesk/app.js"], "build/frontend/workdesk/app.js"
        )
        self.assertEqual(
            inputs[f"{WEB_RESOURCES}/legacy/index.html"], "frontend/legacy/index.html"
        )
        self.assertFalse((self.root / WEB_RESOURCES).exists())
        verified = self.release()
        self.assertEqual(verified["verified_files"], len(inputs))
        self.assertEqual(
            (self.target / WEB_RESOURCES / "legacy/index.html").read_text(), "legacy"
        )
        self.assertFalse((self.target / "build").exists())

    def test_compiled_javascript_changes_are_rejected_by_freeze(self):
        frozen = self.freeze()
        (self.root / "build/frontend/workdesk/app.js").write_text("different bytes")
        with self.assertRaisesRegex(ValueError, "not bound to frozen source"):
            build(self.root, self.output, frozen)
        self.assertFalse(self.output.exists())

    def test_private_materials_are_not_product_inputs(self):
        for name in (
            ".private/secret.py",
            "src/research_partner/resources/account.json",
            "frontend/workdesk/node_modules/secret.js",
        ):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("private fixture")
            self.assertNotIn(name, distribution_inputs(self.root).values())
        self.release()

    def test_resource_tampering_is_rejected_without_loading_target_code(self):
        self.release()
        (self.target / "src/research_partner/app.py").write_text(
            "raise AssertionError('must never be imported')"
        )
        with self.assertRaises(Problem) as caught:
            verify_release(self.target)
        self.assertEqual(caught.exception.code, "release_integrity")

    def test_unregistered_executable_module_is_rejected(self):
        self.release()
        (self.target / "src/research_partner/unregistered.py").write_text(
            "raise AssertionError('must never be imported')"
        )
        with self.assertRaises(Problem) as caught:
            verify_release(self.target)
        self.assertEqual(caught.exception.code, "release_integrity")

    def test_missing_compiled_frontend_fails_before_archive(self):
        (self.root / "build/frontend/workdesk/app.js").unlink()
        with self.assertRaises((ValueError, SystemExit)):
            build(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_source_parent_directory_symlink_is_rejected(self):
        source = self.root / "src"
        source.rename(self.root / "real-source")
        source.symlink_to(self.root / "real-source", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            build(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_explicit_document_parent_symlink_cannot_import_external_material(self):
        external = Path(self.temporary.name) / "external"
        (external / "user").mkdir(parents=True)
        (external / "user/quickstart.md").write_text("private fixture")
        (self.root / "docs").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            build(self.root, self.output)
        self.assertFalse(self.output.exists())

    def test_legacy_flat_release_preflight_does_not_import_target_code(self):
        legacy = Path(self.temporary.name) / "legacy-release"
        records = {}
        for name in (
            "__init__.py",
            "__main__.py",
            "app.py",
            "store.py",
            "runtime.py",
            "compatibility.py",
            "runtime-features.json",
        ):
            path = legacy / "research_partner" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = (
                json.dumps({"schema_version": 1, "runtime_features": []})
                if name.endswith(".json")
                else "raise AssertionError('target code must not be loaded')"
            )
            path.write_text(data)
            records[path.relative_to(legacy).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        (legacy / "distribution-manifest.json").write_text(
            json.dumps(
                {
                    "format": "research-partner-source",
                    "files": records,
                    "runtime_features": [],
                }
            )
        )
        self.assertEqual(verify_release(legacy)["verified_files"], len(records))

    def test_assembled_offline_source_can_be_repacked(self):
        self.release()
        rebuilt = build(self.target, Path(self.temporary.name) / "rebuilt")
        target = Path(self.temporary.name) / "reinstalled"
        install(rebuilt["path"], target)
        self.assertEqual(verify_release(target)["runtime_features"], [])


if __name__ == "__main__":
    unittest.main()
