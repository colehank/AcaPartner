"""目录迁移不改变工作桌与旧页面的公开 URL。"""

from unittest import mock
import unittest

from tests.support.http_fixture import HTTPFixture


class StaticLayoutHTTP(HTTPFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.interfaces = {}
        for interface in ("workdesk", "legacy"):
            folder = self.root / interface
            folder.mkdir()
            (folder / "index.html").write_text(interface + " home")
            (folder / "app.js").write_text(interface + " script")
            self.interfaces[interface] = folder
        patch = mock.patch(
            "research_partner.http.server.web_directory",
            side_effect=lambda interface: self.interfaces[interface],
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_workdesk_home_and_prefixed_assets_keep_their_urls(self):
        self.app.config["workdesk_w1a"] = True
        for path, expected in (
            ("/", b"workdesk home"),
            ("/workdesk/", b"workdesk home"),
            ("/workdesk/app.js", b"workdesk script"),
        ):
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(body, expected)
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(self.request("/api/state")[0], 401)

    def test_legacy_home_and_unprefixed_assets_remain_available(self):
        self.app.config["workdesk_w1a"] = False
        self.assertEqual(self.request("/")[2], b"legacy home")
        self.assertEqual(self.request("/app.js")[2], b"legacy script")
        self.assertEqual(self.request("/workdesk/app.js")[2], b"workdesk script")

    def test_static_mapping_never_escapes_interface_root(self):
        secret = "private-fixture-not-a-static-file"
        (self.root / "secret.txt").write_text(secret)
        for path in ("/workdesk/../secret.txt", "/../secret.txt", "/missing.js"):
            with self.subTest(path=path):
                status, _, body = self.request(path)
                self.assertEqual(status, 404)
                self.assertNotIn(secret, str(body))


if __name__ == "__main__":
    unittest.main()
