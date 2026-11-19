"""Actual bounded child processes; no model, credentials or user workspace."""

import json
import importlib.util
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

from research_partner.app import App
from research_partner.execution.runtime import (
    Runtime,
    process_identity,
    terminate_owned,
)
from research_partner.storage.store import Problem


@unittest.skipUnless(sys.platform in {"darwin", "linux"}, "POSIX task runtime")
@unittest.skipIf(
    sys.platform == "darwin" and importlib.util.find_spec("psutil") is None,
    "Install .[runtime] for macOS process integration tests",
)
class RuntimeProcessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.app = App(root / "workspace", {"control_root": str(root / "control")})
        self.project = self.app.store.create("project", "Process regression")
        self.runtime = Runtime(self.app)

    def claim(self, timeout=5):
        task = self.app.store.submit(
            {
                "project_id": self.project["id"],
                "kind": "research",
                "context": {"materials": []},
                "budget": {"timeout_seconds": timeout, "max_model_calls": 0},
            },
            "process-test",
        )
        self.assertEqual(self.runtime.claim(), task["id"])
        return task["id"]

    def test_real_child_output_receipts_and_budget_settlement(self):
        ident = self.claim()
        result = self.runtime.run_process(
            ident,
            [
                sys.executable,
                "-c",
                'import time; time.sleep(.05); print("bounded-child-ok")',
            ],
            self.tmp.name,
        )
        self.assertEqual(result["returncode"], 0)
        self.assertEqual(result["stdout"].strip(), "bounded-child-ok")
        directory = self.runtime.runs / ident
        start = json.loads((directory / "process-1.started.json").read_text())
        finish = json.loads((directory / "process-1.finished.json").read_text())
        self.assertEqual(start["start_ticks"], finish["start_ticks"])
        self.assertEqual(finish["state"], "finished")
        self.assertFalse(finish["deadline_triggered"])
        reservation = self.app.store.setting(result["reservation_key"])
        self.assertEqual(reservation["state"], "settled")
        self.assertLess(reservation["actual_seconds"], 5)
        self.assertFalse(self.runtime.children)
        from research_partner.domains.collaboration.cycle_stop import _quiet_group

        self.assertTrue(_quiet_group(finish))

    def test_deadline_stops_the_registered_process_group(self):
        ident = self.claim(timeout=0.5)
        with self.assertRaises(Problem) as caught:
            self.runtime.run_process(
                ident,
                [sys.executable, "-c", "import time; time.sleep(30)"],
                self.tmp.name,
            )
        self.assertEqual(
            caught.exception.code, "budget_exhausted", str(caught.exception)
        )
        record = json.loads((self.runtime.runs / ident / "process.json").read_text())
        self.assertTrue(record["deadline_triggered"])
        self.assertFalse(record["deadline_stop_errors"])
        self.assertIsNone(process_identity(record["pid"]))
        self.assertFalse(self.runtime.children)

    def test_polling_deadline_is_recorded_if_timer_callback_is_delayed(self):
        ident = self.claim(timeout=0.4)
        timer = threading.Timer
        with (
            patch(
                "research_partner.execution.runtime.threading.Timer",
                side_effect=lambda delay, callback: timer(delay + 30, callback),
            ),
            self.assertRaises(Problem) as caught,
        ):
            self.runtime.run_process(ident, ["/bin/sleep", "10"], self.tmp.name)
        self.assertEqual(caught.exception.code, "budget_exhausted")
        record = json.loads(
            (self.runtime.runs / ident / "process-1.finished.json").read_text()
        )
        self.assertTrue(record["deadline_triggered"])
        self.assertIsNone(process_identity(record["pid"]))

    def test_registration_waits_for_the_interpreter_after_framework_launcher(self):
        from research_partner.execution.process_control import _python_launcher
        from research_partner.execution.runtime import confirm_process_identity

        # Model a CPython framework installation without relying on xcode-select,
        # a first-run developer tools dialog, or a hosted runner's launcher speed.
        prefix = Path(self.tmp.name) / "Python.framework/Versions/3.12"
        launcher = prefix / "bin/python3.12"
        interpreter = prefix / "Resources/Python.app/Contents/MacOS/Python"
        for binary in (launcher, interpreter):
            binary.parent.mkdir(parents=True)
            binary.touch()
        self.assertTrue(_python_launcher(str(launcher)))
        self.assertFalse(_python_launcher(str(interpreter)))

        child = subprocess.Popen(["/bin/sleep", "10"], start_new_session=True)
        self.addCleanup(lambda: self.reap(child))
        observed = process_identity(child.pid)
        launcher_sample = {
            **observed,
            "launch_in_progress": True,
            "command_sha256": "launcher",
        }
        tracking = {}
        with patch(
            "research_partner.execution.runtime.process_identity",
            side_effect=[launcher_sample, observed],
        ):
            record = confirm_process_identity(child, time.monotonic() + 5, tracking)
        self.assertEqual(record["command_sha256"], observed["command_sha256"])
        self.assertEqual(record["registration"]["samples"], 2)
        self.assertEqual(tracking["anchor"]["start_ticks"], observed["start_ticks"])

    def test_changed_start_identity_cannot_signal_a_live_child(self):
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(lambda: self.reap(child))
        record = process_identity(child.pid)
        self.assertIsNotNone(record)
        wrong = {**record, "start_ticks": str(int(record["start_ticks"]) + 1)}
        with self.assertRaises(Problem) as caught:
            terminate_owned(wrong, hard=True)
        self.assertEqual(caught.exception.code, "process_identity")
        self.assertIsNone(child.poll())

    def test_exited_leader_does_not_leave_descendants_or_kill_other_groups(self):
        outsider = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(lambda: self.reap(outsider))
        ident = self.claim()
        code = (
            "import subprocess,sys,time; "
            'p=subprocess.Popen([sys.executable,"-c",'
            '"import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)"]); '
            "time.sleep(.1); print(p.pid,flush=True)"
        )
        result = self.runtime.run_process(
            ident, [sys.executable, "-c", code], self.tmp.name
        )
        descendant = int(result["stdout"].strip())
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            current = process_identity(descendant)
            if current is None or current["state"] == "Z":
                break
            time.sleep(0.02)
        else:
            self.fail("Owned descendant survived its leader and cleanup")
        self.assertIsNone(outsider.poll())

    def test_unregistered_child_cleanup_keeps_its_platform_anchor(self):
        from research_partner.execution.runtime import (
            confirm_process_identity,
            cleanup_unregistered,
        )

        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
        self.addCleanup(lambda: self.reap(child))
        tracking = {}
        confirm_process_identity(child, time.monotonic() + 5, tracking)
        cleanup_unregistered(child, tracking)
        self.assertIsNotNone(child.poll())

    @staticmethod
    def reap(child):
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


@unittest.skipUnless(sys.platform == "darwin", "macOS optional dependency guard")
class RuntimeDependencyTests(unittest.TestCase):
    def test_missing_dependency_does_not_consume_or_recover_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = App(root / "workspace", {"control_root": str(root / "control")})
            task = app.store.submit({"kind": "research"}, "untouched-queue")
            task = app.store.task(task["id"])
            runtime = Runtime(app)
            with patch.dict(sys.modules, {"psutil": None}):
                with self.assertRaises(Problem) as caught:
                    runtime.start()
            self.assertEqual(caught.exception.code, "runtime_unavailable")
            self.assertEqual(app.store.task(task["id"]), task)
            self.assertIsNone(runtime.lock)
            self.assertFalse(runtime.threads)


if __name__ == "__main__":
    unittest.main()
