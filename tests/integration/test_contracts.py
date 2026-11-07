"""公共类型契约在实际对象、任务和入口上的接入检查。"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import tomllib
import typing
import unittest
from unittest import mock

from research_partner.__main__ import main
from research_partner.commands.contract import COMMAND_FIELDS, parse_action_json
from research_partner.app import App
from research_partner.contracts import (
    ObjectCreateRequest,
    ObjectSaveRequest,
    Principal,
    ResearchObject,
    Scope,
    TaskRecord,
    TaskStatus,
)
from research_partner.storage.store import Problem, Store
from tests.support.http_fixture import HTTPFixture
from tools.check_backend import MAINTAINED_MODULES, TYPED_BOUNDARIES, commands


class PublicContracts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.app = App(self.root / "workspace")
        self.project = self.app.dispatch(
            {"action": "project.create", "title": "contract"}
        )

    def test_research_object_required_fields_match_persisted_and_historical_objects(
        self,
    ):
        for obj in (
            self.project,
            self.app.get(self.project["id"]),
            self.app.get(self.project["id"], revision=1),
        ):
            self.assertTrue(ResearchObject.__required_keys__ <= obj.keys())
            self.assertIs(type(obj["archived"]), bool)
            self.assertIs(type(obj["revision"]), int)
            json.dumps(obj)
        self.assertIs(typing.get_type_hints(App.get)["return"], ResearchObject)
        self.assertIs(typing.get_type_hints(Store.get)["return"], ResearchObject)

    def test_task_payload_result_and_status_round_trip(self):
        task = self.app.dispatch(
            {
                "action": "task.submit",
                "project_id": self.project["id"],
                "request": "offline contract",
                "output_kind": "note",
                "budget": {"max_model_calls": 1, "timeout_seconds": 30},
            }
        )
        self.assertEqual(task["status"], "queued")
        detail = self.app.store.task(task["id"])
        self.assertEqual(detail["steps"], [])
        self.assertTrue(detail.keys() <= typing.get_type_hints(TaskRecord).keys())
        self.assertIn("acquisition", typing.get_type_hints(TaskRecord))
        self.assertIs(typing.get_type_hints(Store.task)["return"], TaskRecord)
        self.assertIs(typing.get_type_hints(App.submit)["return"], TaskRecord)
        for status in ("paused", "queued", "failed", "waiting_input"):
            self.assertIn(status, typing.get_args(TaskStatus))
            self.app.store.task_update(
                task["id"],
                status,
                result={"failure_code": "offline", "details": {"stage": "contract"}},
            )
            current = self.app.store.task(task["id"])
            self.assertEqual(current["status"], status)
            self.assertEqual(current["result"]["details"], {"stage": "contract"})
        self.assertEqual(
            self.app.store.task(task["id"])["payload"]["budget"],
            {"max_model_calls": 1, "timeout_seconds": 30},
        )

    def test_request_static_required_fields_have_runtime_checks(self):
        for request_type, action in (
            (ObjectCreateRequest, "object.create"),
            (ObjectSaveRequest, "object.save"),
        ):
            hints = typing.get_type_hints(request_type, include_extras=True)
            required = {
                name
                for name, hint in hints.items()
                if typing.get_origin(hint) is not typing.NotRequired
            }
            self.assertTrue(required - {"action"} <= COMMAND_FIELDS[action].keys())
        hints = typing.get_type_hints(App.dispatch)
        self.assertEqual(hints["scope"], Scope)
        self.assertEqual(hints["principal"], Principal | None)

    def test_cli_bad_json_is_a_domain_error_without_echo_or_traceback(self):
        secret = "untrusted-private-command-body"
        for raw in ("", '{"action": "' + secret, "[]", "null", '{"action": 3}'):
            with (
                self.subTest(raw=raw),
                mock.patch("sys.stdin", io.StringIO(raw)),
                contextlib.redirect_stderr(io.StringIO()) as errors,
            ):
                status = main(["--workspace", str(self.root / "cli"), "action"])
            self.assertEqual(status, 2)
            self.assertEqual(json.loads(errors.getvalue())["code"], "invalid")
            self.assertNotIn(secret, errors.getvalue())
            self.assertNotIn("Traceback", errors.getvalue())
        with self.assertRaises(Problem):
            parse_action_json("[" * 2000)

    def test_quality_entrypoint_is_one_shared_scope_without_optional_runtime(self):
        config = tomllib.loads(
            (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
        )
        self.assertEqual(config["project"]["dependencies"], [])
        self.assertIn(
            "ruff==0.14.14", config["project"]["optional-dependencies"]["dev"]
        )
        self.assertIn("mypy==1.18.2", config["project"]["optional-dependencies"]["dev"])
        for path in MAINTAINED_MODULES:
            self.assertTrue((Path(__file__).resolve().parents[2] / path).exists(), path)
        self.assertIn("src/research_partner/storage/policies.py", TYPED_BOUNDARIES)
        self.assertIn("src/research_partner/rendering/contract.py", TYPED_BOUNDARIES)
        all_commands = commands("all")
        self.assertEqual(
            all_commands,
            commands("lint")
            + commands("format")
            + commands("types")
            + commands("test"),
        )
        self.assertNotIn("--fix", str(all_commands))
        self.assertNotIn("frontend", str(all_commands))


class CommandContractHTTP(HTTPFixture, unittest.TestCase):
    def test_malformed_domain_fields_are_explicit_and_do_not_echo_values(self):
        status, _, state = self.request("/api/state", bearer=self.owner_token)
        self.assertEqual(status, 200)
        for fields in (
            {"title": ["private-input"]},
            {"title": "ok", "content": []},
            {"title": "ok", "metadata": []},
        ):
            with self.subTest(fields=fields):
                status, _, result = self.request(
                    "/api/action",
                    "POST",
                    {
                        "action": "object.create",
                        "project_id": self.a["id"],
                        "kind": "note",
                        **fields,
                    },
                    bearer=self.owner_token,
                    headers={"X-CSRF-Token": state["csrf"]},
                )
                self.assertEqual((status, result["code"]), (400, "invalid"))
                self.assertIn("field", result["details"])
                self.assertNotIn("private-input", json.dumps(result))

    def test_request_scope_and_principal_fields_cannot_grant_authority(self):
        _, _, state = self.request("/api/state", bearer=self.client_token)
        status, _, result = self.request(
            "/api/action",
            "POST",
            {
                "action": "object.save",
                "id": self.notes[self.b["id"]]["id"],
                "expected_revision": 1,
                "title": "denied",
                "scope": None,
                "principal": {"kind": "loopback"},
            },
            bearer=self.client_token,
            headers={"X-CSRF-Token": state["csrf"]},
        )
        self.assertEqual((status, result["code"]), (403, "forbidden"))
        self.assertNotEqual(
            self.app.get(self.notes[self.b["id"]]["id"])["title"], "denied"
        )


if __name__ == "__main__":
    unittest.main()
