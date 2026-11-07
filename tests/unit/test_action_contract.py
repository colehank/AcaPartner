"""公共命令入口及脱敏诊断的离线回归测试。"""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from research_partner.__main__ import main
from research_partner.commands.contract import validate_action_request
from research_partner.app import App
from research_partner.storage.store import Problem
from tests.support.http_fixture import HTTPFixture


INVALID_REQUESTS = [
    None,
    [],
    "action",
    {},
    *({"action": v} for v in [None, 42, True, [], {}, "", " \t\n"]),
]


class ActionContract(unittest.TestCase):
    def test_invalid_envelopes_have_one_domain_error(self):
        for data in INVALID_REQUESTS:
            with self.subTest(data=data), self.assertRaises(Problem) as raised:
                validate_action_request(data)
            self.assertEqual(
                (raised.exception.status, raised.exception.code), (400, "invalid")
            )

    def test_valid_envelope_preserves_business_fields_and_action(self):
        data = {"action": "future.action", "payload": {"extra": [1, 2]}}
        self.assertIs(validate_action_request(data), data)

    def test_app_validates_before_domain_dispatch(self):
        with tempfile.TemporaryDirectory() as root:
            app = App(root)
            for data in INVALID_REQUESTS:
                with self.subTest(data=data), self.assertRaises(Problem) as raised:
                    app.dispatch(data)
                self.assertEqual(raised.exception.code, "invalid")
            with self.assertRaises(Problem) as raised:
                app.dispatch({"action": "future.action"})
            self.assertEqual(
                (raised.exception.status, raised.exception.code),
                (501, "not_implemented"),
            )

    def test_cli_reports_invalid_action_without_traceback(self):
        with tempfile.TemporaryDirectory() as root:
            for data in [{}, {"action": 42}, {"action": []}, {"action": ""}]:
                with (
                    self.subTest(data=data),
                    mock.patch("sys.stdin", io.StringIO(json.dumps(data))),
                    contextlib.redirect_stderr(io.StringIO()) as errors,
                ):
                    status = main(
                        ["--workspace", str(Path(root) / "workspace"), "action"]
                    )
                self.assertEqual(status, 2)
                self.assertEqual(json.loads(errors.getvalue())["code"], "invalid")
                self.assertNotIn("Traceback", errors.getvalue())


class ActionHTTP(HTTPFixture, unittest.TestCase):
    def action(self, data, **kwargs):
        status, _, state = self.request("/api/state", bearer=self.owner_token)
        self.assertEqual(status, 200)
        return self.request(
            "/api/action",
            "POST",
            data,
            bearer=kwargs.get("bearer", self.owner_token),
            headers={"X-CSRF-Token": state["csrf"]},
        )

    def test_bad_actions_are_400_and_unknown_action_remains_501(self):
        for data in [v for v in INVALID_REQUESTS if isinstance(v, dict)]:
            with self.subTest(data=data):
                status, _, body = self.action(data)
                self.assertEqual((status, body["code"]), (400, "invalid"))
        status, _, body = self.action({"action": "future.action"})
        self.assertEqual((status, body["code"]), (501, "not_implemented"))

    def test_authentication_and_csrf_still_precede_dispatch(self):
        with mock.patch.object(self.app, "dispatch") as dispatch:
            status, _, _ = self.request("/api/action", "POST", {})
            self.assertEqual(status, 401)
            status, _, body = self.request(
                "/api/action", "POST", {}, bearer=self.owner_token
            )
            self.assertEqual((status, body["code"]), (403, "csrf"))
            dispatch.assert_not_called()

    def test_valid_command_keeps_project_scope(self):
        status, _, body = self.action(
            {
                "action": "object.create",
                "project_id": self.b["id"],
                "kind": "note",
                "title": "denied",
            },
            bearer=self.client_token,
        )
        self.assertEqual(status, 403)
        self.assertFalse(body["ok"])
        status, _, body = self.action({"action": "project.create", "title": "accepted"})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["title"], "accepted")

    def test_internal_error_is_correlated_without_sensitive_text(self):
        secret = "private-credential-value-and-research-content"
        with (
            mock.patch.object(self.app, "dispatch", side_effect=RuntimeError(secret)),
            self.assertLogs(
                "research_partner.execution.diagnostics", level="ERROR"
            ) as captured,
        ):
            status, _, body = self.action({"action": "project.create", "title": secret})
        self.assertEqual((status, body["code"]), (500, "internal_error"))
        self.assertEqual(body["exception_type"], "RuntimeError")
        self.assertRegex(body["error_id"], r"^[a-f0-9]{16}$")
        logs = "\n".join(captured.output)
        self.assertIn(body["error_id"], logs)
        self.assertIn("research_partner.http.server:request:", logs)
        self.assertIn("RuntimeError", logs)
        for text in [json.dumps(body), logs]:
            self.assertNotIn(secret, text)
            self.assertNotIn(self.owner_token, text)
            self.assertNotIn(str(self.root), text)
        self.assertIsNone(captured.records[0].exc_info)


if __name__ == "__main__":
    unittest.main()
