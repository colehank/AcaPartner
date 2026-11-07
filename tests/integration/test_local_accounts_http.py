"""Local credentials at the real HTTP boundary; no models or existing workspace."""

from concurrent.futures import ThreadPoolExecutor
import json
import unittest

from research_partner.http.server import serve
from tests.support.http_fixture import HTTPFixture


class LocalAccountHTTP(HTTPFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.accounts = self.root / "private-auth" / "account.json"
        self.app.config["local_accounts_file"] = str(self.accounts)
        self.restart()

    def register(self):
        status, headers, body = self.request(
            "/api/auth/register",
            "POST",
            {"username": "local-owner", "password": "local-test-password-123"},
        )
        self.assertEqual(status, 200, body)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        return headers["Set-Cookie"].split(";", 1)[0]

    def test_register_login_logout_reopen_and_live_authority(self):
        self.assertEqual(
            self.request("/api/auth/registration")[2]["result"],
            {"enabled": True, "registration_open": True},
        )
        self.assertEqual(self.request("/api/state")[0], 401)
        cookie = self.register()
        self.assertFalse(
            self.request("/api/auth/registration")[2]["result"]["registration_open"]
        )
        status, _, state = self.request("/api/state", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(len(state["projects"]), 2)
        action = {
            "action": "notes.create",
            "project_id": self.a["id"],
            "request_id": "account-note",
            "payload": {
                "relative_path": "notes/account.md",
                "markdown": "# 本地登录\n保留正文",
                "if_absent": True,
            },
        }
        self.assertEqual(
            self.request(
                "/api/action",
                "POST",
                action,
                cookie=cookie,
                headers={"X-CSRF-Token": state["csrf"]},
            )[0],
            200,
        )
        self.assertEqual(
            self.request("/api/auth/logout", "POST", {}, cookie=cookie)[0], 403
        )
        self.assertEqual(
            self.request(
                "/api/auth/logout",
                "POST",
                {},
                cookie=cookie,
                headers={"X-CSRF-Token": state["csrf"]},
            )[0],
            200,
        )
        self.assertEqual(self.request("/api/state", cookie=cookie)[0], 401)
        self.restart()
        status, headers, body = self.request(
            "/api/auth/login",
            "POST",
            {"username": "local-owner", "password": "local-test-password-123"},
        )
        self.assertEqual(status, 200, body)
        new_cookie = headers["Set-Cookie"].split(";", 1)[0]
        state = self.request("/api/state", cookie=new_cookie)[2]
        read = self.request(
            "/api/action",
            "POST",
            {
                "action": "notes.read",
                "project_id": self.a["id"],
                "request_id": "read-after-login",
                "payload": {"relative_path": "notes/account.md"},
            },
            cookie=new_cookie,
            headers={"X-CSRF-Token": state["csrf"]},
        )
        self.assertEqual(read[0], 200, read[2])
        self.assertIn("保留正文", json.dumps(read[2], ensure_ascii=False))
        self.owner_file.write_text("changed-owner-token-more-than-24-characters")
        self.assertEqual(self.request("/api/state", cookie=new_cookie)[0], 401)

    def test_password_hash_private_file_and_no_credentials_in_response(self):
        self.register()
        record = json.loads(self.accounts.read_text())
        self.assertNotIn("local-test-password-123", self.accounts.read_text())
        self.assertEqual(record["iterations"], 600000)
        self.assertEqual(self.accounts.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.accounts.parent.stat().st_mode & 0o777, 0o700)
        for password in ["wrong", "local-test-password-123"]:
            status, _, body = self.request(
                "/api/auth/login",
                "POST",
                {"username": "local-owner", "password": password},
            )
            self.assertEqual(status, 200 if password.startswith("local-test") else 401)
            self.assertNotIn(record["password_hash"], json.dumps(body))
            self.assertNotIn(record["salt"], json.dumps(body))

    def test_first_registration_is_atomic_and_does_not_accept_second_user(self):
        payload = {"username": "first-owner", "password": "first-password-long"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    lambda _: self.request("/api/auth/register", "POST", payload)[0],
                    range(2),
                )
            )
        self.assertEqual(sorted(results), [200, 409])
        self.assertEqual(
            self.request(
                "/api/auth/register",
                "POST",
                {"username": "other", "password": "second-password"},
            )[0],
            409,
        )

    def test_origin_content_type_invalid_input_and_closed_configuration(self):
        payload = {"username": "local-owner", "password": "local-test-password-123"}
        self.assertEqual(
            self.request(
                "/api/auth/register",
                "POST",
                payload,
                headers={"Origin": "https://foreign.example"},
            )[0],
            403,
        )
        self.assertEqual(
            self.request(
                "/api/auth/register",
                "POST",
                payload,
                headers={"Content-Type": "text/plain"},
            )[0],
            415,
        )
        for body in [
            {"username": "../outside", "password": "long-enough"},
            {"username": "a", "password": "long-enough"},
            {"username": "valid", "password": "short"},
            {"username": {}, "password": "long-enough"},
        ]:
            self.assertEqual(self.request("/api/auth/register", "POST", body)[0], 400)
        self.assertFalse(self.accounts.exists())
        self.app.config.pop("local_accounts_file")
        self.restart()
        self.assertEqual(
            self.request("/api/auth/registration")[2]["result"],
            {"enabled": False, "registration_open": False},
        )
        self.assertEqual(self.request("/api/auth/register", "POST", payload)[0], 403)

    def test_login_rate_limit_no_anonymous_fallback_or_bearer_fallback(self):
        cookie = self.register()
        for _ in range(8):
            self.assertEqual(
                self.request(
                    "/api/auth/login",
                    "POST",
                    {"username": "local-owner", "password": "wrong"},
                )[0],
                401,
            )
        self.assertEqual(
            self.request(
                "/api/auth/login",
                "POST",
                {"username": "local-owner", "password": "local-test-password-123"},
            )[0],
            429,
        )
        self.assertEqual(
            self.request("/api/state", cookie=cookie, bearer="invalid")[0], 401
        )
        self.accounts.unlink()
        self.assertEqual(self.request("/api/state", cookie=cookie)[0], 401)
        self.assertEqual(self.request("/api/state")[0], 401)

    def test_corrupt_or_public_account_file_is_fail_closed(self):
        cookie = self.register()
        self.accounts.chmod(0o644)
        self.assertEqual(self.request("/api/state", cookie=cookie)[0], 403)
        self.accounts.chmod(0o600)
        self.accounts.write_text("{corrupt")
        self.assertEqual(self.request("/api/auth/registration")[0], 403)
        self.assertEqual(self.request("/api/state")[0], 401)
        self.assertEqual(
            self.request(
                "/api/auth/register",
                "POST",
                {"username": "replace", "password": "replacement-pass"},
            )[0],
            403,
        )

    def test_password_login_rejects_nonlocal_plain_http_startup(self):
        from research_partner.storage.store import Problem

        with self.assertRaises(Problem) as caught:
            serve(self.app, "0.0.0.0", 0)
        self.assertEqual(caught.exception.status, 403)

    def test_owner_principal_and_old_scoped_clients_still_use_current_acl(self):
        cookie = self.register()
        state = self.request("/api/state", cookie=cookie)[2]
        response = self.request(
            "/api/action",
            "POST",
            {"action": "desk.bootstrap"},
            cookie=cookie,
            headers={"X-CSRF-Token": state["csrf"]},
        )
        self.assertEqual(response[0], 200, response[2])
        self.assertEqual(
            self.request("/api/objects/" + self.b["id"], bearer=self.client_token)[0],
            403,
        )
        self.app.config["clients"][0]["projects"] = []
        self.assertEqual(
            self.request("/api/objects/" + self.a["id"], bearer=self.client_token)[0],
            403,
        )


if __name__ == "__main__":
    unittest.main()
