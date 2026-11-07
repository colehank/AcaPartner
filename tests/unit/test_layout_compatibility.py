"""目录迁移不放宽运行环境身份，也不搬动已有开发状态。"""

import copy
from pathlib import Path
import tempfile
import unittest

from research_partner.development.control import DevelopmentControl
from research_partner.domains.generation.checkpoint import environment_binding
from research_partner.storage.store import Problem


class LayoutCompatibility(unittest.TestCase):
    def environment(self, folder):
        return {
            "python": "/fixed/runtime/python",
            "receipt_sha256": "a" * 64,
            "worker_sha256": "b" * 64,
            "platform": "fixture-platform",
            "lock_refs": [
                {
                    "path": f"/source/{folder}/core-generation-runtime.lock",
                    "sha256": "c" * 64,
                },
                {
                    "path": f"/source/{folder}/core-existing-python-runtime.json",
                    "sha256": "d" * 64,
                },
            ],
        }

    def test_registered_lock_directory_can_move_without_changing_runtime(self):
        original = self.environment("development")
        current = self.environment("environments")
        binding = environment_binding(original, current)
        self.assertEqual(binding["kind"], "same_runtime_source_lock_relocation")
        self.assertFalse(binding["cross_machine_tested"])
        self.assertEqual(binding["original_lock_refs"], original["lock_refs"])
        self.assertEqual(binding["current_lock_refs"], current["lock_refs"])
        self.assertIsNone(environment_binding(current, copy.deepcopy(current)))

    def test_relocation_does_not_allow_different_runtime_or_unregistered_locks(self):
        original = self.environment("development")
        alternatives = []
        for field in ("python", "receipt_sha256", "worker_sha256", "platform"):
            changed = self.environment("environments")
            changed[field] = "different"
            alternatives.append(changed)
        alternatives.append(self.environment("unregistered"))
        changed = self.environment("environments")
        changed["lock_refs"][0]["sha256"] = "e" * 64
        alternatives.append(changed)
        for current in alternatives:
            with self.subTest(current=current), self.assertRaises(Problem) as caught:
                environment_binding(original, current)
            self.assertEqual(caught.exception.code, "environment_changed")

    def test_new_control_state_uses_private_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            control = DevelopmentControl(root)
            self.assertEqual(control.directory, root / ".private/development")
            with control.transaction():
                pass
            self.assertFalse((root / "development").exists())
            self.assertTrue((control.directory / ".state.lock").is_file())

    def test_existing_control_state_is_not_silently_moved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            legacy = root / "development"
            legacy.mkdir()
            marker = legacy / "state.json"
            marker.write_text('{"legacy": true}')
            control = DevelopmentControl(root)
            self.assertEqual(control.directory, legacy)
            self.assertEqual(control.path.read_bytes(), marker.read_bytes())
            self.assertFalse((root / ".private").exists())


if __name__ == "__main__":
    unittest.main()
