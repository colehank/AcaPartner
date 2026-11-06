"""HTTP 协议边界的独立测试与真实 loopback 回归。"""

import http.client
import io
import json
import socket
import unittest
from unittest import mock

from research_partner.http_boundary import (
    CONTENT_SECURITY_POLICY,
    MAX_JSON_BODY,
    encode_response,
    read_json_body,
)
from research_partner.store import Problem
from tests.http_fixture import HTTPFixture


class HTTPBoundary(unittest.TestCase):
    def read(self, raw=b"{}", *, headers=None, **options):
        values = {
            "Content-Type": "application/json; charset=utf-8",
            "Content-Length": str(len(raw)),
            "X-CSRF-Token": "fixture-csrf",
            **(headers or {}),
        }
        return read_json_body(
            values,
            io.BytesIO(raw),
            address="localhost:8877",
            public_origin=options.pop("public_origin", ""),
            csrf_token="fixture-csrf",
            **options,
        )

    def test_valid_json_and_configured_public_origin(self):
        self.assertEqual(self.read('{"标题":"测试"}'.encode()), {"标题": "测试"})
        self.assertEqual(
            self.read(
                headers={"Origin": "https://example.test", "Sec-Fetch-Site": "none"},
                public_origin="https://example.test",
            ),
            {},
        )
        with self.assertRaises(Problem) as raised:
            self.read(
                headers={"Origin": "http://localhost:8877"},
                public_origin="https://example.test",
            )
        self.assertEqual(raised.exception.status, 403)

    def test_length_boundary_and_incomplete_stream_are_explicit_invalid(self):
        for length in ["", "0", "-1", "not-a-length", "1.5", str(MAX_JSON_BODY + 1)]:
            with self.subTest(length=length), self.assertRaises(Problem) as raised:
                self.read(headers={"Content-Length": length})
            self.assertEqual(
                (raised.exception.status, raised.exception.code), (400, "invalid")
            )
        self.assertEqual(self.read(limit=2), {})
        for options in [{"limit": 1}, {"headers": {"Content-Length": "3"}}]:
            with self.subTest(options=options), self.assertRaises(Problem) as raised:
                self.read(**options)
            self.assertEqual(raised.exception.code, "invalid")

    def test_invalid_json_utf8_and_non_objects_are_domain_errors(self):
        for raw in [
            b"{",
            b"[]",
            b"null",
            b"false",
            b"42",
            b'"text"',
            b'{"password":"\xffprivate"}',
            "{}".encode("utf-16"),
        ]:
            with self.subTest(raw=raw), self.assertRaises(Problem) as raised:
                self.read(raw)
            self.assertEqual(
                (raised.exception.status, raised.exception.code), (400, "invalid")
            )
            self.assertNotIn("private", str(raised.exception))
            self.assertTrue(
                raised.exception.__suppress_context__
                or raised.exception.__context__ is None
            )

    def test_header_failure_never_reads_stream(self):
        stream = mock.Mock()
        with self.assertRaises(Problem):
            read_json_body(
                {"Origin": "https://foreign.example"},
                stream,
                address="localhost:8877",
                public_origin="",
                csrf_token="fixture-csrf",
            )
        stream.read.assert_not_called()

    def test_encoding_preserves_json_and_bytes_and_extra_header_order(self):
        encoded = encode_response({"标题": "测试"})
        self.assertEqual(json.loads(encoded.body), {"标题": "测试"})
        self.assertIn("测试".encode(), encoded.body)
        self.assertEqual(
            dict(encoded.headers)["Content-Length"], str(len(encoded.body))
        )
        raw = b"\x00\xffbinary"
        policy = "sandbox; default-src 'none'"
        encoded = encode_response(
            raw, "application/octet-stream", {"Content-Security-Policy": policy}
        )
        self.assertIs(encoded.body, raw)
        self.assertEqual(
            [
                value
                for key, value in encoded.headers
                if key == "Content-Security-Policy"
            ],
            [CONTENT_SECURITY_POLICY, policy],
        )


class HTTPBoundaryIntegration(HTTPFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.csrf = self.request("/api/state", bearer=self.owner_token)[2]["csrf"]

    def raw_post(
        self,
        raw=b"{}",
        *,
        headers=None,
        authenticated=True,
        path="/api/action",
        end_write=False,
    ):
        values = {
            "Content-Type": "application/json",
            "Content-Length": str(len(raw)),
            "X-CSRF-Token": self.csrf,
            **(
                {"Authorization": "Bearer " + self.owner_token} if authenticated else {}
            ),
            **(headers or {}),
        }
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request("POST", path, body=raw, headers=values)
            if end_write:
                conn.sock.shutdown(socket.SHUT_WR)
            response = conn.getresponse()
            return (
                response.status,
                dict(response.getheaders()),
                json.loads(response.read()),
            )
        finally:
            conn.close()

    def test_guard_order_is_host_authentication_origin_fetch_csrf_type_length(self):
        cases = [
            (
                {
                    "Host": "foreign.example",
                    "Origin": "https://foreign.example",
                    "Content-Type": "text/plain",
                    "Content-Length": "bad",
                },
                False,
                403,
                "forbidden",
                "Host不在配置允许范围",
            ),
            (
                {
                    "Origin": "https://foreign.example",
                    "Content-Type": "text/plain",
                    "Content-Length": "bad",
                },
                False,
                401,
                "unauthorized",
                "请登录后继续",
            ),
            (
                {
                    "Origin": "https://foreign.example",
                    "Sec-Fetch-Site": "cross-site",
                    "X-CSRF-Token": "bad",
                    "Content-Type": "text/plain",
                    "Content-Length": "bad",
                },
                True,
                403,
                "forbidden",
                "来源不匹配",
            ),
            (
                {
                    "Sec-Fetch-Site": "cross-site",
                    "X-CSRF-Token": "bad",
                    "Content-Type": "text/plain",
                    "Content-Length": "bad",
                },
                True,
                403,
                "forbidden",
                "拒绝跨来源请求",
            ),
            (
                {
                    "X-CSRF-Token": "bad",
                    "Content-Type": "text/plain",
                    "Content-Length": "bad",
                },
                True,
                403,
                "csrf",
                "写入令牌失效，请保留草稿并刷新",
            ),
            (
                {"Content-Type": "text/plain", "Content-Length": "bad"},
                True,
                415,
                "invalid",
                "需要JSON",
            ),
            ({"Content-Length": "bad"}, True, 400, "invalid", "请求大小无效"),
        ]
        with mock.patch.object(self.app, "dispatch") as dispatch:
            for headers, authenticated, expected, code, error in cases:
                with self.subTest(error=error):
                    status, _, body = self.raw_post(
                        headers=headers, authenticated=authenticated
                    )
                    self.assertEqual(
                        (status, body["code"], body["error"]), (expected, code, error)
                    )
            dispatch.assert_not_called()

    def test_json_type_length_encoding_and_short_body_are_invalid_without_logging(self):
        cases = [
            (b"{}", {"Content-Length": "0"}, False),
            (b"{}", {"Content-Length": "-1"}, False),
            (b"{}", {"Content-Length": str(MAX_JSON_BODY + 1)}, False),
            (b"{}", {"Content-Length": "3"}, True),
            (b"[1]", {}, False),
            (b"null", {}, False),
            (b'"private-json-value"', {}, False),
            (b'{"password":"\xffprivate-json-value"}', {}, False),
            (b'{"password":"private-json-value",', {}, False),
            ("{}".encode("utf-16"), {}, False),
        ]
        with self.assertNoLogs("research_partner.diagnostics", level="ERROR"):
            for raw, headers, end_write in cases:
                with self.subTest(raw=raw, headers=headers):
                    status, _, body = self.raw_post(
                        raw, headers=headers, end_write=end_write
                    )
                    self.assertEqual((status, body["code"]), (400, "invalid"))
                    self.assertNotIn("private-json-value", json.dumps(body))

    def test_non_ascii_csrf_is_a_forbidden_request_not_an_internal_type_error(self):
        status, _, body = self.raw_post(headers={"X-CSRF-Token": "\xff"})
        self.assertEqual((status, body["code"]), (403, "csrf"))

    def test_login_skips_csrf_but_keeps_origin_media_and_small_body_limit(self):
        payload = json.dumps({"token": self.owner_token}).encode()
        status, headers, body = self.raw_post(
            payload,
            path="/api/auth/login",
            authenticated=False,
            headers={"X-CSRF-Token": "invalid"},
        )
        self.assertEqual(status, 200, body)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertTrue(body["result"]["session_active"])
        for values, expected, code in [
            (
                {"Origin": "https://foreign.example", "Content-Type": "text/plain"},
                403,
                "forbidden",
            ),
            ({"Sec-Fetch-Site": "cross-site"}, 403, "forbidden"),
            ({"Content-Type": "text/plain"}, 415, "invalid"),
            ({"Content-Length": "8193"}, 400, "invalid"),
        ]:
            with self.subTest(headers=values):
                status, _, body = self.raw_post(
                    payload, path="/api/auth/login", authenticated=False, headers=values
                )
                self.assertEqual((status, body["code"]), (expected, code))

    def test_json_and_asset_bytes_keep_security_headers_and_content_length(self):
        paths = ["/api/auth/status", "/api/assets/" + self.assets[self.a["id"]]["sha"]]
        for path in paths:
            with self.subTest(path=path):
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
                try:
                    conn.request(
                        "GET",
                        path,
                        headers={"Authorization": "Bearer " + self.owner_token},
                    )
                    response = conn.getresponse()
                    raw = response.read()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(
                        response.getheader("Content-Length"), str(len(raw))
                    )
                    self.assertEqual(
                        response.getheader("X-Content-Type-Options"), "nosniff"
                    )
                    self.assertEqual(response.getheader("Cache-Control"), "no-store")
                    self.assertEqual(
                        response.getheader("Referrer-Policy"), "no-referrer"
                    )
                    self.assertIn(
                        CONTENT_SECURITY_POLICY,
                        response.getheader("Content-Security-Policy"),
                    )
                    if path.startswith("/api/assets/"):
                        self.assertEqual(raw, self.a["title"].encode())
                        self.assertEqual(
                            response.getheader("Content-Type"), "text/plain"
                        )
                    else:
                        self.assertTrue(json.loads(raw)["ok"])
                finally:
                    conn.close()

    def test_legacy_domain_errors_keep_400_without_exception_text(self):
        secret = "private-internal-value"
        for error_type in [KeyError, TypeError, ValueError]:
            with (
                self.subTest(error_type=error_type),
                mock.patch.object(self.app, "dispatch", side_effect=error_type(secret)),
                self.assertNoLogs("research_partner.diagnostics", level="ERROR"),
            ):
                status, _, body = self.raw_post(b'{"action":"desk.bootstrap"}')
            self.assertEqual((status, body["code"]), (400, "invalid"))
            self.assertNotIn(secret, json.dumps(body))

    def test_invalid_revision_query_remains_a_redacted_client_error(self):
        status, _, body = self.request(
            "/api/objects/"
            + self.notes[self.a["id"]]["id"]
            + "?revision=private-invalid-value",
            bearer=self.owner_token,
        )
        self.assertEqual((status, body["code"]), (400, "invalid"))
        self.assertNotIn("private-invalid-value", json.dumps(body))


if __name__ == "__main__":
    unittest.main()
