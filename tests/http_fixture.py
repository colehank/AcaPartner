"""仅提供临时 loopback HTTP 环境，不包含 unittest 测试用例。"""

import http.client
import json
from pathlib import Path
import secrets
import tempfile
import threading

from research_partner.app import App
from research_partner.server import serve


class HTTPFixture:
    def setUp(self):
        super().setUp()
        self.tmp = tempfile.TemporaryDirectory(prefix="rp-http-auth-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.owner_token = secrets.token_urlsafe(32)
        self.client_token = secrets.token_urlsafe(32)
        self.owner_file = self.root / "owner-token"
        self.client_file = self.root / "client-token"
        for path, value in [
            (self.owner_file, self.owner_token),
            (self.client_file, self.client_token),
        ]:
            path.write_text(value)
            path.chmod(0o600)
        self.app = App(
            self.root / "workspace",
            {
                "access_token_file": str(self.owner_file),
                "clients": [{"token_file": str(self.client_file), "projects": []}],
            },
        )
        self.a = self.app.dispatch(
            {"action": "project.create", "title": "First fixture project"}
        )
        self.b = self.app.dispatch(
            {"action": "project.create", "title": "Second fixture project"}
        )
        self.app.config["clients"][0]["projects"] = [self.a["id"]]
        self.notes = {}
        self.assets = {}
        for project in [self.a, self.b]:
            self.notes[project["id"]] = self.app.dispatch(
                {
                    "action": "object.create",
                    "project_id": project["id"],
                    "kind": "note",
                    "title": "Fixture note",
                    "content": {
                        "blocks": [
                            {
                                "id": "b1",
                                "kind": "paragraph",
                                "text": project["title"],
                            }
                        ]
                    },
                }
            )
            self.assets[project["id"]] = self.app.store.add_asset(
                project["title"].encode(),
                "fixture.txt",
                "text/plain",
                {"project_id": project["id"]},
            )
        self.start_server()

    def start_server(self):
        self.server = serve(self.app, "127.0.0.1", 0)
        self.port = self.server.server_port
        self.base = "http://127.0.0.1:" + str(self.port)
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.01}
        )
        self.thread.start()
        self.addCleanup(self.stop_server, self.server, self.thread)

    def stop_server(self, server, thread):
        if thread.is_alive():
            server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())

    def restart(self):
        self.stop_server(self.server, self.thread)
        self.start_server()

    def request(
        self, path, method="GET", data=None, cookie=None, bearer=None, headers=None
    ):
        values = dict(headers or {})
        if cookie:
            values["Cookie"] = cookie
        if bearer:
            values["Authorization"] = "Bearer " + bearer
        body = None
        if data is not None:
            body = json.dumps(data).encode()
            values.setdefault("Content-Type", "application/json")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=values)
            response = conn.getresponse()
            raw = response.read()
            result = (
                json.loads(raw)
                if response.getheader("Content-Type", "").startswith("application/json")
                else raw
            )
            return response.status, dict(response.getheaders()), result
        finally:
            conn.close()
