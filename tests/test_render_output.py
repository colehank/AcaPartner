"""离线验证渲染输出预算，不加载科学依赖。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest.mock import patch

from research_partner.artifacts import ArtifactEngine, run_process
from research_partner import render_worker
from research_partner.process_output import (
    BoundedTextCapture,
    DEFAULT_TAIL_BYTES,
    OutputBudget,
    OutputLimitExceeded,
)
from research_partner.store import Problem


class OutputBudgetTests(unittest.TestCase):
    def test_shared_utf8_byte_limit_is_latched(self):
        budget = OutputBudget(12, 8)
        stdout = BoundedTextCapture(budget, "stdout")
        stderr = BoundedTextCapture(budget, "stderr")
        self.assertEqual(stdout.write("你好"), 2)
        with self.assertRaises(OutputLimitExceeded):
            stderr.write("世界")
        self.assertEqual(stdout.getvalue(), "你好")
        self.assertEqual(stderr.getvalue(), "世界")
        with self.assertRaises(OutputLimitExceeded):
            stdout.write("ignored")
        with self.assertRaises(OutputLimitExceeded):
            budget.check()

    def test_large_single_write_retains_only_bounded_tail(self):
        budget = OutputBudget(200_000, 32)
        capture = BoundedTextCapture(budget, "stdout")
        capture.write("x" * 100_000 + "TAIL")
        self.assertEqual(capture.getvalue(), "x" * 28 + "TAIL")

    def test_concurrent_streams_share_budget_without_losing_writes(self):
        budget = OutputBudget(100_000, 12000)
        streams = [BoundedTextCapture(budget, name) for name in ("stdout", "stderr")]

        def write(stream):
            for _ in range(1000):
                stream.write("abcd")

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(write, streams))
        self.assertEqual(budget.text("stdout"), "abcd" * 1000)
        self.assertEqual(budget.text("stderr"), "abcd" * 1000)

    def test_invalid_limits_rejected(self):
        for value in (0, -1, True, 1.5, "10"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                OutputBudget(value)


@unittest.skipUnless(os.name == "posix", "渲染执行器使用POSIX进程组")
class RenderProcessOutputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_script(self, source, **kwargs):
        command = [sys.executable, "-u", "-c", textwrap.dedent(source)]
        return run_process(command, cwd=self.root, **kwargs)

    def test_normal_output_and_record_shape(self):
        record = self.run_script(
            "import sys; print('你好'); print('warning', file=sys.stderr)"
        )
        self.assertEqual(record["stdout"], "你好\n")
        self.assertEqual(record["stderr"], "warning\n")
        self.assertEqual(record["returncode"], 0)
        self.assertEqual(
            set(record),
            {"command", "returncode", "elapsed_seconds", "stdout", "stderr"},
        )

    def test_nonzero_exit_retains_failure_diagnostics(self):
        with self.assertRaises(Problem) as caught:
            self.run_script(
                "import sys; print('details', file=sys.stderr); sys.exit(7)"
            )
        self.assertEqual(caught.exception.code, "render_failed")
        self.assertEqual(caught.exception.status, 422)
        self.assertEqual(caught.exception.details["returncode"], 7)
        self.assertEqual(caught.exception.details["stderr"], "details\n")

    def test_invalid_utf8_does_not_break_capture(self):
        record = self.run_script("import os; os.write(1, b'hello\\xfftail')")
        self.assertEqual(record["stdout"], "hello�tail")

    def test_process_capture_keeps_universal_newline_behavior(self):
        record = self.run_script("import os; os.write(1, b'a\\r\\nb\\rc')")
        self.assertEqual(record["stdout"], "a\nb\nc")

    def test_two_busy_pipes_are_drained_concurrently_and_tails_are_bounded(self):
        record = self.run_script(
            """
            import os
            from concurrent.futures import ThreadPoolExecutor
            def emit(fd):
                for _ in range(32):
                    os.write(fd, b'x' * 8192)
                os.write(fd, b'END')
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(emit, (1, 2)))
            """,
            timeout=5,
            output_limit_bytes=1_000_000,
        )
        for name in ("stdout", "stderr"):
            self.assertEqual(len(record[name]), DEFAULT_TAIL_BYTES)
            self.assertTrue(record[name].endswith("END"))

    def test_reaching_limit_is_a_failure_even_for_zero_exit(self):
        with self.assertRaises(Problem) as caught:
            self.run_script(
                "import os; os.write(1, b'x' * 8192)", output_limit_bytes=8192
            )
        self.assertEqual(caught.exception.code, "render_output_limit")
        self.assertEqual(caught.exception.details["output_limit_bytes"], 8192)

    def test_output_limit_is_shared_between_streams(self):
        with self.assertRaises(Problem) as caught:
            self.run_script(
                "import os; os.write(1, b'x' * 5000); os.write(2, b'y' * 5000)",
                output_limit_bytes=9000,
            )
        self.assertEqual(caught.exception.code, "render_output_limit")
        self.assertTrue(caught.exception.details["stdout"])
        self.assertTrue(caught.exception.details["stderr"])

    def test_limit_stops_execution_and_preserves_tail(self):
        with self.assertRaises(Problem) as caught:
            self.run_script(
                """
                import os
                from pathlib import Path
                import time
                os.write(2, b'prefix' * 10)
                for _ in range(128):
                    os.write(1, b'x' * 8192)
                time.sleep(1)
                Path('continued').write_text('bad')
                """,
                output_limit_bytes=16000,
                timeout=5,
            )
        self.assertEqual(caught.exception.code, "render_output_limit")
        self.assertEqual(len(caught.exception.details["stdout"]), DEFAULT_TAIL_BYTES)
        self.assertIn("prefix", caught.exception.details["stderr"])
        self.assertFalse((self.root / "continued").exists())

    def test_timeout_keeps_diagnostics(self):
        with self.assertRaises(Problem) as caught:
            self.run_script(
                "import sys,time; print('before'); print('warning', file=sys.stderr); time.sleep(5)",
                timeout=0.3,
            )
        self.assertEqual(caught.exception.code, "render_timeout")
        self.assertEqual(caught.exception.status, 504)
        self.assertEqual(caught.exception.details["stdout"], "before\n")
        self.assertEqual(caught.exception.details["stderr"], "warning\n")

    def test_timeout_applies_even_if_both_streams_close_early(self):
        with self.assertRaises(Problem) as caught:
            self.run_script(
                "import os,time; os.close(1); os.close(2); time.sleep(5)", timeout=0.2
            )
        self.assertEqual(caught.exception.code, "render_timeout")

    def _descendant_source(self, ending, *, escape=False):
        child = (
            "from pathlib import Path; import time; "
            "p=Path('heartbeat'); p.write_text('ready'); "
            'exec("while True:\\n p.write_text(str(time.time_ns()))\\n time.sleep(0.01)")'
        )
        return (
            "import subprocess, sys, time, os\n"
            "from pathlib import Path\n"
            f"child=subprocess.Popen([sys.executable, '-u', '-c', {child!r}], "
            f"start_new_session={escape!r})\n"
            "Path('descendant.pid').write_text(str(child.pid))\n"
            "while not Path('heartbeat').exists(): time.sleep(0.01)\n"
            "print('descendant-ready', flush=True)\n" + ending
        )

    def _cleanup_descendant(self):
        path = self.root / "descendant.pid"
        if path.exists():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(path.read_text()), signal.SIGKILL)

    def _assert_descendant_stopped(self):
        heartbeat = self.root / "heartbeat"
        self.assertTrue(heartbeat.exists())
        threading.Event().wait(0.1)
        before = heartbeat.stat().st_mtime_ns
        threading.Event().wait(0.15)
        self.assertEqual(heartbeat.stat().st_mtime_ns, before)

    def test_timeout_kills_descendant_process_group(self):
        self.addCleanup(self._cleanup_descendant)
        with self.assertRaises(Problem) as caught:
            self.run_script(self._descendant_source("time.sleep(5)"), timeout=0.4)
        self.assertEqual(caught.exception.code, "render_timeout")
        self._assert_descendant_stopped()

    def test_output_limit_kills_descendant_process_group(self):
        self.addCleanup(self._cleanup_descendant)
        with self.assertRaises(Problem) as caught:
            self.run_script(
                self._descendant_source("os.write(1, b'x' * 20000); time.sleep(5)"),
                output_limit_bytes=16000,
                timeout=5,
            )
        self.assertEqual(caught.exception.code, "render_output_limit")
        self._assert_descendant_stopped()

    def test_exited_parent_with_inherited_pipes_is_not_success_or_hang(self):
        self.addCleanup(self._cleanup_descendant)
        started = time.monotonic()
        with self.assertRaises(Problem) as caught:
            self.run_script(self._descendant_source("sys.exit(0)"), timeout=5)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(caught.exception.code, "render_output_incomplete")
        self.assertEqual(caught.exception.details["returncode"], 0)
        self._assert_descendant_stopped()

    def test_escaped_descendant_cannot_hold_timeout_cleanup_open(self):
        self.addCleanup(self._cleanup_descendant)
        started = time.monotonic()
        with self.assertRaises(Problem) as caught:
            self.run_script(
                self._descendant_source("time.sleep(5)", escape=True), timeout=0.4
            )
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(caught.exception.code, "render_timeout")

    def test_spawn_failure_keeps_existing_error_contract(self):
        with self.assertRaises(Problem) as caught:
            run_process([str(self.root / "missing-runtime")], cwd=self.root)
        self.assertEqual(caught.exception.code, "runtime_unavailable")
        self.assertEqual(caught.exception.status, 503)


class WorkerOutputCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.response = self.root / "response.json"
        self.request = self.root / "request.json"

    def invoke(self, operation, **job_fields):
        self.request.write_text(
            json.dumps(
                {
                    "operation": "figure",
                    "output_dir": str(self.root),
                    "response": str(self.response),
                    **job_fields,
                }
            )
        )
        summary = io.StringIO()
        with (
            patch.object(sys, "argv", ["render_worker.py", str(self.request)]),
            patch.object(render_worker, "figure", operation),
            contextlib.redirect_stdout(summary),
        ):
            render_worker.main()
        return json.loads(self.response.read_text()), json.loads(summary.getvalue())

    def test_worker_captures_both_streams_and_restores_them(self):
        stdout, stderr = sys.stdout, sys.stderr

        def operation(job, work):
            print("hello")
            print("warning", file=sys.stderr)
            return {"files": []}

        result, summary = self.invoke(operation)
        self.assertTrue(result["ok"])
        self.assertEqual(result["script_stdout"], "hello\n")
        self.assertEqual(result["script_stderr"], "warning\n")
        self.assertTrue(summary["ok"])
        self.assertIs(sys.stdout, stdout)
        self.assertIs(sys.stderr, stderr)

    def test_worker_output_tails_are_bounded(self):
        def operation(job, work):
            sys.stdout.write("x" * 50000 + "OUT")
            sys.stderr.write("y" * 50000 + "ERR")
            return {}

        result, _ = self.invoke(operation, output_limit_bytes=200000)
        self.assertTrue(result["ok"])
        for name, suffix in (("script_stdout", "OUT"), ("script_stderr", "ERR")):
            self.assertEqual(len(result[name]), DEFAULT_TAIL_BYTES)
            self.assertTrue(result[name].endswith(suffix))

    def test_worker_stops_on_shared_utf8_output_limit(self):
        def operation(job, work):
            sys.stdout.write("你好")
            sys.stderr.write("世界")
            (work / "continued").write_text("bad")
            return {}

        result, summary = self.invoke(operation, output_limit_bytes=12)
        self.assertFalse(result["ok"])
        self.assertFalse(summary["ok"])
        self.assertEqual(result["code"], "render_output_limit")
        self.assertEqual(result["type"], "OutputLimitExceeded")
        self.assertEqual(result["script_stdout"], "你好")
        self.assertEqual(result["script_stderr"], "世界")
        self.assertFalse((self.root / "continued").exists())

    def test_swallowed_limit_exception_cannot_turn_into_success(self):
        def operation(job, work):
            with contextlib.suppress(OutputLimitExceeded):
                sys.stdout.write("x" * 100)
            return {"files": []}

        result, _ = self.invoke(operation, output_limit_bytes=32)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "render_output_limit")

    def test_swallowed_limit_followed_by_another_error_keeps_limit_code(self):
        def operation(job, work):
            with contextlib.suppress(OutputLimitExceeded):
                sys.stdout.write("x" * 100)
            raise ValueError("secondary failure")

        result, _ = self.invoke(operation, output_limit_bytes=32)
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "render_output_limit")
        self.assertEqual(result["type"], "OutputLimitExceeded")

    def test_portable_provenance_excludes_both_script_logs(self):
        omissions = []
        value = ArtifactEngine._portable_value(
            {
                "provenance": {
                    "script_stdout": "private output",
                    "script_stderr": "private error",
                    "runtime": "python",
                }
            },
            omissions,
        )
        self.assertEqual(value, {"provenance": {"runtime": "python"}})
        self.assertEqual(
            {item["path"] for item in omissions},
            {"provenance.script_stdout", "provenance.script_stderr"},
        )

    def test_worker_preserves_regular_exception_contract(self):
        def operation(job, work):
            print("before")
            raise ValueError("operation failed")

        result, _ = self.invoke(operation)
        self.assertFalse(result["ok"])
        self.assertEqual(result["type"], "ValueError")
        self.assertEqual(result["error"], "operation failed")
        self.assertEqual(result["script_stdout"], "before\n")

    def test_packaged_worker_supports_direct_script_launch_without_scientific_libraries(
        self,
    ):
        runtime = self.root / "runtime"
        runtime.mkdir()
        for name in (
            "render_worker.py",
            "figure_interaction.py",
            "process_output.py",
            "render_contract.py",
        ):
            shutil.copyfile(
                Path(render_worker.__file__).with_name(name), runtime / name
            )
        self.request.write_text(
            json.dumps(
                {
                    "operation": "unknown",
                    "output_dir": str(self.root),
                    "response": str(self.response),
                }
            )
        )
        record = run_process(
            [sys.executable, str(runtime / "render_worker.py"), str(self.request)],
            cwd=self.root,
            timeout=5,
        )
        result = json.loads(self.response.read_text())
        self.assertEqual(result["type"], "RenderContractError")
        self.assertEqual(result["code"], "invalid")
        self.assertFalse(json.loads(record["stdout"])["ok"])


if __name__ == "__main__":
    unittest.main()
