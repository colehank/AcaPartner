"""渲染信封与离线启动只依赖标准库，不加载科学或 Office 运行时。"""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from research_partner.rendering import worker as render_worker
from research_partner.rendering.engine import ArtifactEngine
from research_partner.execution.process_output import DEFAULT_OUTPUT_LIMIT_BYTES
from research_partner.rendering.contract import (
    MAX_PATH_LENGTH,
    RENDER_OPERATIONS,
    RenderContractError,
    render_response_path,
    validate_render_request,
    validate_render_result,
)
from research_partner.storage.store import Problem, Store
from research_partner.resources import module_file


class RenderEnvelopeTests(unittest.TestCase):
    def request(self, **fields):
        return {
            "operation": "figure",
            "output_dir": "/tmp/render-output",
            "response": "/tmp/render-response.json",
            **fields,
        }

    def test_all_operations_accept_extra_domain_fields_unchanged(self):
        for operation in RENDER_OPERATIONS:
            with self.subTest(operation=operation):
                request = self.request(operation=operation, domain_extension={"x": 1})
                self.assertIs(validate_render_request(request), request)

    def test_invalid_operations_and_missing_fields(self):
        for operation in (None, "unknown", 1, True, [], {}, "x" * 100000):
            with self.subTest(operation=type(operation).__name__):
                with self.assertRaises(RenderContractError):
                    validate_render_request(self.request(operation=operation))
        for field in ("operation", "output_dir", "response"):
            request = self.request()
            request.pop(field)
            with self.subTest(missing=field), self.assertRaises(RenderContractError):
                validate_render_request(request)
        for value in (None, [], "private-request", 1):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(RenderContractError):
                    validate_render_request(value)

    def test_path_fields_are_nonempty_bounded_strings_without_nul(self):
        for field in ("output_dir", "response"):
            for value in (
                None,
                False,
                1,
                [],
                {},
                "",
                "  ",
                "secret\x00path",
                "x" * (MAX_PATH_LENGTH + 1),
            ):
                with self.subTest(field=field, value=type(value).__name__):
                    with self.assertRaises(RenderContractError) as caught:
                        validate_render_request(self.request(**{field: value}))
                    self.assertNotIn("secret", str(caught.exception))
        self.assertEqual(
            render_response_path({"operation": [], "response": "response.json"}),
            "response.json",
        )

    def test_output_limit_is_positive_integer_without_changing_default(self):
        for value in (None, True, 0, -1, 1.5, "1"):
            with self.subTest(value=value), self.assertRaises(RenderContractError):
                validate_render_request(self.request(output_limit_bytes=value))
        request = self.request(output_limit_bytes=12)
        self.assertEqual(validate_render_request(request)["output_limit_bytes"], 12)
        self.assertEqual(DEFAULT_OUTPUT_LIMIT_BYTES, 4 * 1024 * 1024)

    def test_success_and_failure_result_shapes_allow_domain_extensions(self):
        for result in (
            {"ok": True, "files": [], "extension": {}},
            {"ok": False, "error": "bad", "type": "ValueError", "code": "invalid"},
        ):
            self.assertIs(validate_render_result(result), result)
        for result in (
            None,
            [],
            {},
            {"ok": 1},
            {"ok": False, "error": "bad"},
            {"ok": False, "error": [], "type": "ValueError"},
            {"ok": True, "files": [1]},
            {"ok": True, "script_stderr": []},
        ):
            with self.subTest(result=result), self.assertRaises(RenderContractError):
                validate_render_result(result)

    def test_contract_import_does_not_load_application_or_scientific_modules(self):
        source = (
            "import sys; "
            f"sys.path.insert(0, {str(module_file('research_partner.rendering.contract').parents[2])!r}); "
            "import research_partner.rendering.contract; "
            "assert not any(name in sys.modules for name in "
            "('research_partner.storage.store', 'matplotlib', 'numpy', 'pptx', 'docx'))"
        )
        subprocess.run(
            [sys.executable, "-I", "-c", source], check=True, capture_output=True
        )


class RenderBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.response = self.root / "response.json"
        self.request = self.root / "request.json"

    def invoke(self, value, operation=None):
        self.request.write_text(json.dumps(value), encoding="utf-8")
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.object(sys, "argv", ["render_worker.py", str(self.request)]),
            patch.object(render_worker, "figure", operation),
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            status = render_worker.main()
        result = (
            json.loads(self.response.read_text()) if self.response.exists() else None
        )
        return status, result, stdout.getvalue(), stderr.getvalue()

    def envelope(self, **fields):
        return {
            "operation": "figure",
            "output_dir": str(self.root),
            "response": str(self.response),
            **fields,
        }

    def test_worker_dispatches_every_operation_without_optional_imports(self):
        for operation in RENDER_OPERATIONS:
            with self.subTest(operation=operation):

                def handler(job, work):
                    return {"files": [], "extension": job["extra"]}

                with patch.object(render_worker, operation, handler):
                    self.request.write_text(
                        json.dumps(self.envelope(operation=operation, extra="kept"))
                    )
                    output = io.StringIO()
                    with (
                        patch.object(sys, "argv", ["worker", str(self.request)]),
                        contextlib.redirect_stdout(output),
                    ):
                        self.assertEqual(render_worker.main(), 0)
                result = json.loads(self.response.read_text())
                self.assertTrue(result["ok"])
                self.assertEqual(result["extension"], "kept")
                self.assertEqual(result["script_stderr"], "")

    def test_invalid_job_writes_stable_failure_before_dispatch(self):
        for fields in (
            {"operation": "private-unknown"},
            {"operation": []},
            {"output_dir": None},
            {"output_dir": "private\x00path"},
            {"output_limit_bytes": True},
        ):
            with self.subTest(fields=fields):
                handler = unittest.mock.Mock()
                status, result, summary, errors = self.invoke(
                    self.envelope(**fields), handler
                )
                self.assertEqual(status, 0)
                self.assertFalse(result["ok"])
                self.assertEqual(result["code"], "invalid")
                self.assertEqual(result["type"], "RenderContractError")
                self.assertNotIn("private", result["error"])
                self.assertFalse(json.loads(summary)["ok"])
                self.assertEqual(errors, "")
                handler.assert_not_called()
        for missing in ("operation", "output_dir"):
            job = self.envelope()
            job.pop(missing)
            status, result, _, _ = self.invoke(job)
            self.assertEqual(status, 0)
            self.assertEqual(result["code"], "invalid")

    def test_unavailable_response_has_only_fixed_diagnostic(self):
        for value in (None, [], {"response": "private\x00path"}, {"secret": "private"}):
            with self.subTest(value=value):
                status, result, stdout, stderr = self.invoke(value)
                self.assertEqual(status, 2)
                self.assertIsNone(result)
                self.assertEqual(stdout, "")
                self.assertEqual(
                    stderr, "Invalid render request; response path unavailable\n"
                )
        self.request.write_text('{"secret": "private",')
        stderr = io.StringIO()
        with (
            patch.object(sys, "argv", ["worker", str(self.request)]),
            contextlib.redirect_stderr(stderr),
        ):
            self.assertEqual(render_worker.main(), 2)
        self.assertNotIn("private", stderr.getvalue())

    def test_unwritable_response_does_not_print_request(self):
        status, result, stdout, stderr = self.invoke(
            self.envelope(response=str(self.root))
        )
        self.assertEqual(status, 2)
        self.assertIsNone(result)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "Unable to write render response\n")

    def test_engine_rejects_invalid_request_before_starting_process(self):
        engine = ArtifactEngine(None)
        for job in ({}, {"operation": []}, {"operation": "unknown"}):
            with (
                self.subTest(job=job),
                patch("research_partner.rendering.engine.run_process") as run,
            ):
                with self.assertRaises(Problem) as caught:
                    engine._worker(job, self.root, "python")
                self.assertEqual(caught.exception.code, "invalid")
                run.assert_not_called()
        self.assertEqual(list(self.root.glob("request-*.json")), [])

    def test_engine_checks_worker_results_and_attaches_process_record(self):
        engine = ArtifactEngine(None)
        record = {
            "command": ["python"],
            "returncode": 0,
            "elapsed_seconds": 0.1,
            "stdout": "",
            "stderr": "",
        }

        def run(command, **kwargs):
            payload = json.loads(Path(command[-1]).read_text())
            self.assertEqual(payload["operation"], "figure")
            Path(payload["response"]).write_text(json.dumps(result))
            return record

        with patch("research_partner.rendering.engine.run_process", side_effect=run):
            result = {"ok": True, "files": []}
            self.assertEqual(
                engine._worker({"operation": "figure"}, self.root, "python")["process"],
                record,
            )
            result = {
                "ok": False,
                "error": "operation failed",
                "type": "ValueError",
                "code": "invalid",
            }
            with self.assertRaises(Problem) as caught:
                engine._worker({"operation": "figure"}, self.root, "python")
            self.assertEqual(caught.exception.code, "invalid")
            self.assertEqual(caught.exception.details["worker"], result)
            for result in ([], {"ok": "true"}):
                with self.assertRaises(Problem) as caught:
                    engine._worker({"operation": "figure"}, self.root, "python")
                self.assertEqual(caught.exception.code, "render_failed")

    def test_direct_script_startup_and_missing_contract_helper(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        for name in (
            "render_worker.py",
            "figure_interaction.py",
            "process_output.py",
            "render_contract.py",
        ):
            shutil.copyfile(
                module_file(
                    {
                        "render_worker.py": "research_partner.rendering.worker",
                        "figure_interaction.py": "research_partner.rendering.interaction",
                        "process_output.py": "research_partner.execution.process_output",
                        "render_contract.py": "research_partner.rendering.contract",
                    }[name]
                ),
                runtime / name,
            )
        self.request.write_text(json.dumps(self.envelope(operation="private-unknown")))
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        command = [
            sys.executable,
            "-S",
            str(runtime / "render_worker.py"),
            str(self.request),
        ]
        completed = subprocess.run(
            command, cwd=self.root, env=env, capture_output=True, text=True, timeout=5
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(self.response.read_text())
        self.assertEqual(result["code"], "invalid")
        self.assertEqual(result["type"], "RenderContractError")
        (runtime / "render_contract.py").unlink()
        completed = subprocess.run(
            command, cwd=self.root, env=env, capture_output=True, text=True, timeout=5
        )
        self.assertNotEqual(completed.returncode, 0)
        self.assertEqual(completed.stdout, "")
        self.assertEqual(
            completed.stderr, "Missing render contract helper: render_contract.py\n"
        )

    def test_bundle_contains_checksum_verified_contract_helper(self):
        store = Store(self.root / "workspace")
        obj = store.create(
            "note", "Render contract", content={"markdown": "plain text"}
        )
        bundle = ArtifactEngine(store)._bundle(obj)
        with zipfile.ZipFile(store.blobs / bundle["asset"]["sha"]) as archive:
            name = "runtime/render_contract.py"
            data = archive.read(name)
            manifest = json.loads(archive.read("manifest.json"))
            self.assertEqual(
                data,
                module_file("research_partner.rendering.contract").read_bytes(),
            )
            self.assertEqual(manifest["files"][name], hashlib.sha256(data).hexdigest())
            replay = archive.read("replay.py").decode()
            self.assertIn("Missing verified render contract helper", replay)


if __name__ == "__main__":
    unittest.main()
