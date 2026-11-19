"""可选 provider 的离线可用性边界，不连接模型、账户或私有协议。"""

import copy
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from research_partner.app import App
from research_partner.providers import codex_configuration as configuration
from research_partner.providers import codex_dynamic as dynamic_provider
from research_partner.execution.budget import Budget
from research_partner.domains.figures.composition import provider_definition
from research_partner.providers.availability import codex_dynamic_availability
from research_partner.providers.registry import Providers
from research_partner.execution.runtime import Runtime
from research_partner.storage.store import Problem, digest


class ProviderAvailability(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="rp-provider-availability-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = {
            "route": "codex",
            "transport": "app_server_dynamic",
            "authorized": True,
            "model": "offline-fixture-model",
        }
        self.app = App(
            self.root / "workspace",
            {
                "providers": {"dynamic": self.config},
                "default_provider": "dynamic",
                "control_root": str(self.root / "control"),
            },
        )
        self.providers = Providers(self.app)
        self.directory = self.root / "provider-run"
        self.task = {
            "id": "TASK-offline-availability",
            "payload": {
                "provider_id": "dynamic",
                "kind": "research",
                "context": {},
            },
        }

    def assert_missing(self, callback):
        with self.assertRaises(Problem) as caught:
            callback()
        self.assertEqual(caught.exception.code, "provider_missing")
        self.assertEqual(caught.exception.status, 503)
        self.assertIn("公共版本", str(caught.exception))

    def test_availability_is_read_only_and_does_not_probe_personal_installation(self):
        with (
            mock.patch.object(Path, "home", side_effect=AssertionError("读取个人配置")),
            mock.patch("shutil.which", side_effect=AssertionError("探测个人执行器")),
            mock.patch.dict(sys.modules, {"tools.codex_thread_dispatch": None}),
        ):
            availability = codex_dynamic_availability()
        self.assertIs(availability["available"], False)
        self.assertIn("私有连接适配器", availability["reason"])

    def test_app_status_keeps_dynamic_unavailable_even_when_cli_is_installed(self):
        self.app.config["providers"] = {
            "dynamic": {**self.config, "executable": "offline-codex"},
            "cli": {
                "route": "codex",
                "authorized": True,
                "executable": "offline-codex",
            },
        }
        with (
            mock.patch(
                "research_partner.app.shutil.which",
                return_value="/offline/bin/codex",
            ) as which,
            mock.patch.dict(sys.modules, {"tools.codex_thread_dispatch": None}),
            mock.patch("socket.socket", side_effect=AssertionError("连接 socket")),
            mock.patch("subprocess.Popen", side_effect=AssertionError("启动模型")),
        ):
            status = {provider["id"]: provider for provider in self.app.providers()}
        which.assert_called_with("offline-codex")
        dynamic = status["dynamic"]
        self.assertIs(dynamic["available"], False)
        self.assertIs(dynamic["supports_resume"], False)
        self.assertIs(dynamic["supports_figure_composition"], False)
        self.assertIsNone(dynamic["figure_composition_budget"])
        self.assertEqual(dynamic["note"], codex_dynamic_availability()["reason"])
        self.assertIs(dynamic["connected"], False)
        cli = status["cli"]
        self.assertIs(cli["available"], True)
        self.assertIs(cli["supports_resume"], True)
        self.assertIs(cli["supports_figure_composition"], True)
        self.assertEqual(cli["figure_composition_budget"]["max_model_calls"], 1)
        self.assertIs(cli["connected"], False)

    def test_configuration_preflight_reports_missing_before_transport_import(self):
        with mock.patch.dict(
            sys.modules, {"research_partner.providers.codex_transport": None}
        ):
            for callback in (
                lambda: configuration.definition(self.config),
                lambda: configuration.guard({}, self.config),
                configuration.session_limits,
                lambda: provider_definition(self.config),
            ):
                with self.subTest(callback=callback):
                    self.assert_missing(callback)
        self.assertFalse(self.directory.exists())
        self.assertEqual(self.app.store.tasks(), [])

    def test_public_transport_import_and_pure_limits_do_not_need_private_adapter(self):
        with (
            mock.patch.dict(sys.modules, {"tools.codex_thread_dispatch": None}),
            mock.patch("socket.socket", side_effect=AssertionError("连接 socket")),
            mock.patch("subprocess.Popen", side_effect=AssertionError("启动模型")),
        ):
            transport = importlib.import_module(
                "research_partner.providers.codex_transport"
            )
            transport = importlib.reload(transport)
            self.assertEqual(transport.validate_limits()["max_messages"], 256)
            self.assert_missing(transport.ManagedAppServerClient)

    def test_dynamic_call_rejects_before_imports_directory_and_launch_intent(self):
        with mock.patch.dict(
            sys.modules,
            {
                "research_partner.providers.codex_transport": None,
                "research_partner.providers.codex_tools": None,
            },
        ):
            self.assert_missing(
                lambda: dynamic_provider.call(
                    self.providers, self.config, {}, "offline", self.directory, None
                )
            )
        self.assertFalse(self.directory.exists())
        self.assertIsNone(
            self.app.store.setting("codex_launch_intent:" + self.task["id"])
        )

    def test_provider_call_rejects_dynamic_without_cli_fallback(self):
        run_process = mock.Mock(side_effect=AssertionError("启动 CLI"))
        with mock.patch.object(self.providers, "codex") as cli:
            self.assert_missing(
                lambda: self.providers.call(
                    self.task, "offline", self.directory, run_process
                )
            )
        cli.assert_not_called()
        run_process.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_frozen_dynamic_task_cannot_switch_to_default_cli(self):
        self.app.config["providers"]["dynamic"] = {
            "route": "codex",
            "authorized": True,
        }
        task = copy.deepcopy(self.task)
        task["payload"]["context"] = {
            "figure_composition": {"native_transport": "app_server_dynamic"}
        }
        with mock.patch.object(self.providers, "codex") as cli:
            self.assert_missing(
                lambda: self.providers.call(
                    task, "offline", self.directory, mock.Mock()
                )
            )
            self.assert_missing(
                lambda: self.providers.assert_dispatch_continuity(task, self.directory)
            )
        cli.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_dispatch_preflight_rejects_before_reading_or_writing_launch_state(self):
        with mock.patch.object(self.app.store, "setting") as setting:
            self.assert_missing(
                lambda: self.providers.assert_dispatch_continuity(
                    self.task, self.directory
                )
            )
        setting.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_runtime_rejects_before_parent_budget_and_provider_reservations(self):
        project = self.app.dispatch(
            {"action": "project.create", "title": "离线可用性测试"}
        )
        task = self.app.submit(
            {
                "action": "task.submit",
                "project_id": project["id"],
                "request": "离线检查 provider，不执行模型",
                "provider_id": "dynamic",
                "output_kind": "note",
                "budget": {"max_model_calls": 1, "timeout_seconds": 30},
            }
        )
        budget_file = self.root / "parent-budget.json"
        Budget(budget_file).initialize(started_at=time.time())
        before = budget_file.read_bytes()
        self.app.config["development_budget"] = str(budget_file)
        runtime = Runtime(self.app)
        self.assertEqual(runtime.claim(), task["id"])
        with (
            mock.patch.object(Budget, "reserve") as reserve,
            mock.patch.object(runtime, "run_process") as run_process,
            mock.patch.object(runtime, "run_native_turn") as native,
        ):
            self.assert_missing(lambda: runtime.execute(task["id"]))
        reserve.assert_not_called()
        run_process.assert_not_called()
        native.assert_not_called()
        self.assertEqual(budget_file.read_bytes(), before)
        self.assertEqual(
            self.app.store.setting("provider_invocations:" + task["id"], 0), 0
        )
        self.assertIsNone(self.app.store.setting("codex_launch_intent:" + task["id"]))
        run = runtime.runs / task["id"]
        self.assertFalse((run / "codex-contract.json").exists())
        self.assertFalse((run / "codex-attempt.json").exists())
        with self.app.store.connect() as connection:
            reserved = connection.execute(
                "SELECT COUNT(*) FROM events WHERE object_id=? AND kind='provider.reserved'",
                (task["id"],),
            ).fetchone()[0]
        self.assertEqual(reserved, 0)

    def test_default_cli_route_remains_separate_without_executing_model(self):
        cli_config = {"route": "codex", "authorized": True}
        self.app.config["providers"]["dynamic"] = cli_config
        self.assertIsNone(provider_definition(cli_config))
        run_process = mock.Mock(side_effect=AssertionError("启动模型"))
        with mock.patch.object(
            self.providers, "codex", return_value={"adapter": "existing-cli"}
        ) as cli:
            result = self.providers.call(
                self.task, "offline", self.directory, run_process
            )
        self.assertEqual(result, {"adapter": "existing-cli"})
        cli.assert_called_once_with(
            cli_config, self.task, "offline", self.directory, run_process, None
        )
        run_process.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_saved_snapshot_remains_readable_and_integrity_checked(self):
        self.directory.mkdir()
        attempt = "a" * 24
        path = self.directory / ("codex-appserver-" + attempt + ".json")
        snapshot = {"state": "completed", "wire_messages": []}
        path.write_text(json.dumps(snapshot))
        receipt = {"attempt_id": attempt, "events_sha256": digest(path.read_bytes())}
        self.assertEqual(
            dynamic_provider.read_snapshot(self.directory, receipt), snapshot
        )
        path.write_text('{"state":"changed"}')
        with self.assertRaises(Problem) as caught:
            dynamic_provider.read_snapshot(self.directory, receipt)
        self.assertEqual(caught.exception.code, "integrity")
        with self.assertRaises(Problem) as caught:
            dynamic_provider.continuity(self.providers, self.task, self.directory)
        self.assertEqual(caught.exception.code, "provider_checkpoint_missing")


if __name__ == "__main__":
    unittest.main()
