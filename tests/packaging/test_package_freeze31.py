"""Real archive failures reproduce the unregistered patch-backup defect."""

import hashlib
import importlib.util
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    "build31", Path(__file__).resolve().parents[2] / "tools/build.py"
)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PackageFreeze31(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "source"
        files = {
            "src/research_partner/__init__.py": "",
            "src/research_partner/resources/runtime-features.json": json.dumps(
                {"schema_version": 1, "runtime_features": []}
            ),
            "frontend/legacy/index.html": "<html>legacy</html>",
            "frontend/legacy/app.js": "export const revision=1;\n",
            "build/frontend/workdesk/index.html": '<script type="module" src="/workdesk/assets/app.js"></script>',
            "build/frontend/workdesk/assets/app.js": "export const app=1;",
        }
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.manifest = Path(self.temporary.name) / "FROZEN.json"
        self.manifest.write_text(
            json.dumps(
                {
                    "files": {
                        str(p.relative_to(self.root)): hashlib.sha256(
                            p.read_bytes()
                        ).hexdigest()
                        for p in self.root.rglob("*")
                        if p.is_file()
                    }
                }
            )
        )
        self.output = Path(self.temporary.name) / "dist"

    def test_actual_patch_backup_rejected_before_output(self):
        for suffix in [".orig", ".rej", ".bak", ".swp", ".swo", "~"]:
            with self.subTest(suffix=suffix):
                backup = self.root / ("frontend/legacy/app.js" + suffix)
                backup.write_text("old source")
                with self.assertRaisesRegex(ValueError, "backup"):
                    builder.build(self.root, self.output)
                self.assertFalse(self.output.exists())
                backup.unlink()

    def test_extra_nonbackup_member_is_not_silently_accepted(self):
        (self.root / "frontend/legacy/unreviewed.js").write_text(
            "console.log('extra');"
        )
        with self.assertRaisesRegex(ValueError, "member set differs"):
            builder.build(self.root, self.output, self.manifest)
        self.assertFalse(self.output.exists())

    def test_changed_member_is_not_silently_accepted(self):
        (self.root / "frontend/legacy/app.js").write_text("export const revision=2;")
        with self.assertRaisesRegex(ValueError, "not bound to frozen source"):
            builder.build(self.root, self.output, self.manifest)
        self.assertFalse(self.output.exists())

    def test_missing_distributed_entry_rejected_before_archive(self):
        (self.root / "frontend/legacy/app.js").unlink()
        with self.assertRaisesRegex(ValueError, "member set differs.*app.js"):
            builder.build(self.root, self.output, self.manifest)
        self.assertFalse(self.output.exists())

    def test_nondistributed_frozen_tests_need_not_be_shipped(self):
        frozen = json.loads(self.manifest.read_text())
        frozen["files"]["tests/unshipped.py"] = hashlib.sha256(
            b"test input"
        ).hexdigest()
        self.manifest.write_text(json.dumps(frozen))
        result = builder.build(self.root, self.output, self.manifest)
        with tarfile.open(result["path"]) as archive:
            self.assertNotIn("tests/unshipped.py", archive.getnames())
            self.assertIn("frontend/legacy/app.js", archive.getnames())

    def test_clean_frozen_archive_contains_exact_source_and_is_repeatable(self):
        first = builder.build(self.root, self.output, self.manifest)
        second = builder.build(self.root, self.output, self.manifest)
        self.assertEqual(first["sha256"], second["sha256"])
        source = json.loads(self.manifest.read_text())["files"]
        inputs = builder.distribution_inputs(self.root)
        with tarfile.open(first["path"]) as archive:
            self.assertEqual(
                set(archive.getnames()), set(inputs) | {"distribution-manifest.json"}
            )
            manifest = json.load(archive.extractfile("distribution-manifest.json"))
            self.assertEqual(manifest["source_files"], inputs)
            for name, original in inputs.items():
                self.assertEqual(manifest["files"][name], source[original])
                self.assertEqual(
                    hashlib.sha256(archive.extractfile(name).read()).hexdigest(),
                    source[original],
                )


if __name__ == "__main__":
    unittest.main()
