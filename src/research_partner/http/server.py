"""Loopback-first HTTP interface. Task ownership belongs to the runtime."""

from research_partner.resources import web_directory
import hashlib
import mimetypes
import secrets
import threading
import time
import urllib.parse
from collections.abc import Mapping
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from research_partner.app import App
from research_partner.storage.store import Problem, require
from research_partner.security.credentials import token_fingerprint
from research_partner.http.accounts import LocalAccounts
from research_partner.commands.contract import validate_action_request
from research_partner.contracts import JsonObject, Principal, Scope
from research_partner.execution.diagnostics import record_internal_error
from research_partner.http.boundary import (
    JSON_MEDIA,
    MAX_JSON_BODY,
    encode_response,
    read_json_body,
)


def serve(app: App, host: str = "127.0.0.1", port: int = 8877) -> ThreadingHTTPServer:
    require(
        host in {"127.0.0.1", "localhost", "::1"}
        or app.config.get("access_token_file"),
        "非本地监听必须配置访问令牌",
        "authorization_required",
        403,
    )
    csrf = secrets.token_urlsafe(32)

    if app.config.get("access_token_file"):
        require(
            token_fingerprint(app.config["access_token_file"]),
            "访问令牌文件必须私有(0600)且不少于24字符",
        )
    accounts = None
    if app.config.get("local_accounts_file"):
        require(app.config.get("access_token_file"), "本地账号需要实例内部的所有者凭据")
        accounts = LocalAccounts(app.config["local_accounts_file"])
        accounts.registration_open()  # Invalid private files must never enable anonymous access.
    public_origin = app.config.get("public_origin", "").rstrip("/")
    if public_origin:
        origin_url = urllib.parse.urlsplit(public_origin)
        require(
            origin_url.scheme in {"http", "https"}
            and origin_url.netloc
            and not origin_url.path
            and not origin_url.query
            and not origin_url.fragment
            and not origin_url.username,
            "public_origin必须是完整且无路径的HTTP(S)来源",
        )
    session_seconds = float(app.config.get("browser_session_seconds", 8 * 3600))
    require(0 < session_seconds <= 86400, "浏览器会话有效期必须大于0且不超过24小时")
    secure_cookie = bool(
        app.config.get("browser_cookie_secure", False)
        or public_origin.startswith("https://")
    )
    if accounts:
        require(
            host in {"127.0.0.1", "localhost", "::1"}
            or public_origin.startswith("https://"),
            "账号密码登录需要本地监听或已配置的HTTPS来源",
            "authorization_required",
            403,
        )
    sessions = {}
    session_lock = threading.Lock()
    login_attempts = {}

    def auth_required() -> bool:
        return bool(
            accounts or app.config.get("access_token_file") or app.config.get("clients")
        )

    def credential_scope(fingerprint: str) -> tuple[bool, Scope]:
        owner = (
            token_fingerprint(app.config["access_token_file"])
            if app.config.get("access_token_file")
            else None
        )
        if owner and secrets.compare_digest(fingerprint, owner):
            return True, None
        for client in app.config.get("clients", []):
            current = token_fingerprint(client.get("token_file", ""))
            if current and secrets.compare_digest(fingerprint, current):
                if client.get("task_binding"):
                    binding = client["task_binding"]
                    try:
                        with app.store.connect() as c:
                            app.store.assert_execution(
                                c, binding["id"], binding["token"]
                            )
                        if app.config.get("development_budget"):
                            from research_partner.execution.budget import Budget

                            Budget(app.config["development_budget"]).check()
                    except (Problem, KeyError):
                        return False, None
                return True, client.get("projects", [])
        return False, None

    class Handler(BaseHTTPRequestHandler):
        server_version = "ResearchPartner/0.1"

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def log_message(self, fmt, *args):
            # Deliberately omit query strings and request bodies from access logs.
            pass

        def cookie_name(self):
            return "rp_session_" + str(self.server.server_port)

        def session_key(self):
            try:
                cookie = SimpleCookie()
                cookie.load(self.headers.get("Cookie", ""))
                value = cookie.get(self.cookie_name())
                return (
                    hashlib.sha256(value.value.encode()).hexdigest() if value else None
                )
            except CookieError:
                return None

        def cookie_header(self, value="", clear=False):
            cookie = SimpleCookie()
            cookie[self.cookie_name()] = value
            item = cookie[self.cookie_name()]
            item["path"] = "/"
            item["httponly"] = True
            item["samesite"] = "Strict"
            item["max-age"] = "0" if clear else str(max(1, int(session_seconds)))
            if clear:
                item["expires"] = "Thu, 01 Jan 1970 00:00:00 GMT"
            if secure_cookie:
                item["secure"] = True
            return item.OutputString()

        def authentication(self) -> tuple[bool, Scope, bool]:
            authorization = self.headers.get("Authorization")
            if authorization is not None:
                scheme, _, value = authorization.partition(" ")
                if scheme.lower() != "bearer" or not value:
                    return False, None, False
                allowed, scope = credential_scope(
                    hashlib.sha256(value.encode()).hexdigest()
                )
                return allowed, scope, False
            key = self.session_key()
            if key:
                with session_lock:
                    expired = [
                        ident
                        for ident, record in sessions.items()
                        if record["expires_at"] <= time.monotonic()
                    ]
                    for ident in expired:
                        sessions.pop(ident, None)
                    record = sessions.get(key)
                if record:
                    if record.get("account_identity") and not accounts.current(
                        record["account_identity"]
                    ):
                        with session_lock:
                            sessions.pop(key, None)
                        return False, None, False
                    allowed, scope = credential_scope(record["credential_fingerprint"])
                    if allowed:
                        return True, scope, True
                    with session_lock:
                        sessions.pop(key, None)
            return not auth_required(), None, False

        def auth_status(self):
            authenticated, _, active = self.authentication()
            return {
                "required": auth_required(),
                "authenticated": authenticated,
                "session_active": active,
            }

        def scope(self) -> Scope:
            authenticated, scope, _ = self.authentication()
            require(authenticated, "请登录后继续", "unauthorized", 401)
            return scope

        def management_principal(self) -> Principal:
            # Identity comes from the authenticated connection, never request JSON.
            authorization = self.headers.get("Authorization")
            if authorization is not None:
                fingerprint = hashlib.sha256(
                    authorization.partition(" ")[2].encode()
                ).hexdigest()
                return self.credential_principal(fingerprint)
            key = self.session_key()
            if key:
                with session_lock:
                    record = sessions.get(key)
                if record:
                    return self.credential_principal(record["credential_fingerprint"])
            return {"kind": "loopback"}

        def credential_principal(self, fingerprint: str) -> Principal:
            principal: Principal = {
                "kind": "credential",
                "credential_sha256": fingerprint,
            }
            for client in app.config.get("clients", []):
                if token_fingerprint(
                    client.get("token_file", "")
                ) == fingerprint and client.get("task_binding"):
                    principal.update(
                        actor_kind="agent",
                        domain_task_id=client["task_binding"]["id"],
                        _execution_token=client["task_binding"]["token"],
                        allowed_actions=client.get("allowed_actions", []),
                    )
            return principal

        def post_body(
            self, address: str, csrf_required: bool = True, limit: int = MAX_JSON_BODY
        ) -> JsonObject:
            return read_json_body(
                self.headers,
                self.rfile,
                address=address,
                public_origin=public_origin,
                csrf_token=csrf,
                csrf_required=csrf_required,
                limit=limit,
            )

        def send(
            self,
            status: int,
            body: object,
            media: str = JSON_MEDIA,
            extra: Mapping[str, str] | None = None,
        ) -> None:
            response = encode_response(body, media, extra)
            self.send_response(status)
            for key, value in response.headers:
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(response.body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def login_rate_guard(self):
            address = self.client_address[0]
            with session_lock:
                cutoff = time.monotonic() - 60
                for ip in list(login_attempts):
                    login_attempts[ip] = [t for t in login_attempts[ip] if t > cutoff]
                    if not login_attempts[ip]:
                        del login_attempts[ip]
                require(
                    len(login_attempts.get(address, [])) < 8
                    and len(login_attempts) < 1024,
                    "登录尝试过多，请稍后再试",
                    "rate_limited",
                    429,
                )
                login_attempts.setdefault(address, []).append(time.monotonic())

        def finish_login(self, fingerprint, account_identity=None):
            value = secrets.token_urlsafe(32)
            key = hashlib.sha256(value.encode()).hexdigest()
            with session_lock:
                for ident in [
                    i
                    for i, r in sessions.items()
                    if r["expires_at"] <= time.monotonic()
                ]:
                    sessions.pop(ident, None)
                require(
                    len(sessions) < 512,
                    "活动会话过多，请退出闲置会话后重试",
                    "session_limit",
                    429,
                )
                sessions.pop(self.session_key(), None)
                sessions[key] = {
                    "credential_fingerprint": fingerprint,
                    "expires_at": time.monotonic() + session_seconds,
                    **(
                        {"account_identity": account_identity}
                        if account_identity
                        else {}
                    ),
                }
                if account_identity:
                    login_attempts.pop(self.client_address[0], None)
            return self.send(
                200,
                {
                    "ok": True,
                    "result": {
                        "required": auth_required(),
                        "authenticated": True,
                        "session_active": True,
                    },
                },
                extra={"Set-Cookie": self.cookie_header(value)},
            )

        def request(self):
            try:
                address = self.headers.get("Host", "")
                try:
                    hostname = urllib.parse.urlsplit("//" + address).hostname
                except ValueError:
                    raise Problem("无效Host") from None
                allowed = {
                    "127.0.0.1",
                    "localhost",
                    "::1",
                    host,
                    *app.config.get("allowed_hosts", []),
                }
                require(hostname in allowed, "Host不在配置允许范围", "forbidden", 403)
                try:
                    url = urllib.parse.urlsplit(self.path)
                except ValueError:
                    raise Problem("无效请求路径") from None
                require(not url.scheme and not url.netloc, "无效请求路径")
                if self.command == "GET" and url.path == "/api/auth/status":
                    status = self.auth_status()
                    extra = (
                        {"Set-Cookie": self.cookie_header(clear=True)}
                        if self.session_key() and not status["session_active"]
                        else None
                    )
                    return self.send(200, {"ok": True, "result": status}, extra=extra)
                if self.command == "GET" and url.path == "/api/auth/registration":
                    return self.send(
                        200,
                        {
                            "ok": True,
                            "result": {
                                "enabled": bool(accounts),
                                "registration_open": bool(
                                    accounts and accounts.registration_open()
                                ),
                            },
                        },
                    )
                if self.command == "POST" and url.path == "/api/auth/register":
                    data = self.post_body(address, csrf_required=False, limit=8192)
                    require(
                        accounts is not None,
                        "此实例尚未启用本地账号注册",
                        "registration_closed",
                        403,
                    )
                    require(
                        host in {"127.0.0.1", "localhost", "::1"}
                        and self.client_address[0] in {"127.0.0.1", "::1"},
                        "首次注册仅允许本地连接",
                        "forbidden",
                        403,
                    )
                    fingerprint = token_fingerprint(app.config["access_token_file"])
                    require(fingerprint, "实例所有者凭据已撤回", "unauthorized", 401)
                    self.login_rate_guard()
                    identity = accounts.register(
                        data.get("username"), data.get("password")
                    )
                    return self.finish_login(fingerprint, identity)
                if self.command == "POST" and url.path == "/api/auth/login":
                    data = self.post_body(address, csrf_required=False, limit=8192)
                    if "username" in data or "password" in data:
                        require(
                            accounts is not None,
                            "此实例尚未启用账号密码登录",
                            "authorization_required",
                            403,
                        )
                        self.login_rate_guard()
                        identity = accounts.verify(
                            data.get("username"), data.get("password")
                        )
                        fingerprint = token_fingerprint(app.config["access_token_file"])
                        require(
                            fingerprint, "实例所有者凭据已撤回", "unauthorized", 401
                        )
                        return self.finish_login(fingerprint, identity)
                    token = data.get("token")
                    require(
                        isinstance(token, str) and 24 <= len(token) <= 4096,
                        "访问令牌无效",
                        "unauthorized",
                        401,
                    )
                    fingerprint = hashlib.sha256(token.strip().encode()).hexdigest()
                    allowed, _ = credential_scope(fingerprint)
                    require(allowed, "访问令牌无效", "unauthorized", 401)
                    require(
                        self.credential_principal(fingerprint).get("actor_kind")
                        != "agent",
                        "任务凭据不能换取通用浏览器会话",
                        "forbidden",
                        403,
                    )
                    return self.finish_login(fingerprint)
                if self.command == "POST" and url.path == "/api/auth/logout":
                    self.scope()
                    self.post_body(address, limit=8192)
                    with session_lock:
                        sessions.pop(self.session_key(), None)
                    return self.send(
                        200,
                        {
                            "ok": True,
                            "result": {
                                "required": auth_required(),
                                "authenticated": not auth_required(),
                                "session_active": False,
                            },
                        },
                        extra={"Set-Cookie": self.cookie_header(clear=True)},
                    )
                # Static UI bootstrap is public. No API data or registered asset
                # is reachable through this web-root-only branch.
                if self.command == "GET" and not url.path.startswith("/api/"):
                    rel = url.path.removeprefix("/") or (
                        "workdesk/index.html"
                        if app.config.get("workdesk_w1a")
                        else "index.html"
                    )
                    interface = "workdesk" if rel.startswith("workdesk/") else "legacy"
                    webroot = web_directory(interface)
                    if interface == "workdesk":
                        rel = rel.removeprefix("workdesk/") or "index.html"
                    path = (webroot / rel).resolve()
                    require(
                        path.is_relative_to(webroot.resolve()) and path.is_file(),
                        "页面不存在",
                        "not_found",
                        404,
                    )
                    return self.send(
                        200,
                        path.read_bytes(),
                        mimetypes.guess_type(path)[0] or "application/octet-stream",
                    )
                scope = self.scope()
                principal = self.management_principal()
                figure_authority = None
                if principal.get("actor_kind") == "agent" and principal.get(
                    "domain_task_id"
                ):
                    task = app.store.task(principal["domain_task_id"])
                    if task["payload"].get("kind") == "figure_composition":
                        from research_partner.domains.figures.composition import (
                            check_current_authority,
                        )

                        figure_authority = check_current_authority(
                            app, task, scope, principal["_execution_token"]
                        )
                if self.command == "GET":
                    if url.path == "/api/state":
                        authority_headers = (
                            {
                                "X-Research-Partner-Task": figure_authority["task_id"],
                                "X-Research-Partner-Project": figure_authority[
                                    "project_id"
                                ],
                                "X-Research-Partner-Plan": figure_authority[
                                    "plan_sha256"
                                ],
                                "X-Research-Partner-Egress": figure_authority[
                                    "egress_sha256"
                                ],
                            }
                            if figure_authority
                            else None
                        )
                        return self.send(
                            200,
                            {**app.state(scope), "csrf": csrf},
                            extra=authority_headers,
                        )
                    if url.path.startswith("/api/objects/"):
                        ident = urllib.parse.unquote(url.path.split("/")[-1])
                        query = urllib.parse.parse_qs(url.query)
                        try:
                            revision = (
                                int(query["revision"][0])
                                if "revision" in query
                                else None
                            )
                        except ValueError:
                            raise Problem("版本号格式无效") from None
                        consumer = query.get("consumer", [None])[0]
                        return self.send(
                            200,
                            {
                                "ok": True,
                                "result": app.artifact(
                                    ident, scope, revision, consumer=consumer
                                ),
                            },
                        )
                    if url.path.startswith("/api/tasks/"):
                        task = app.store.task(url.path.split("/")[-1])
                        if task["payload"].get("kind") == "manuscript_revision":
                            from research_partner.domains.manuscripts.revision import (
                                task_access,
                            )

                            with app.store.connect() as connection:
                                task_access(app, task, scope, connection)
                        elif task["payload"].get("kind") == "project_management":
                            from research_partner.domains.workspace.management import (
                                task_access,
                            )

                            with app.store.connect() as connection:
                                task_access(app, task, scope, connection)
                        else:
                            app.get(task["project_id"], scope)
                        return self.send(
                            200,
                            {
                                "ok": True,
                                "result": {
                                    **task,
                                    "events": app.store.events(task["id"]),
                                    **app.store.task_input_view(task["id"]),
                                },
                            },
                        )
                    if url.path.startswith("/api/assets/"):
                        sha = url.path.split("/")[-1]
                        asset = app.asset(sha, scope)
                        name = urllib.parse.quote(asset["filename"])
                        policy = "sandbox; default-src 'none'; img-src data:; style-src 'unsafe-inline'"
                        if asset["media_type"].split(";")[0] == "text/html":
                            policy = "sandbox allow-scripts allow-downloads; default-src 'none'; script-src 'unsafe-inline'; img-src data: blob:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
                        return self.send(
                            200,
                            (app.store.blobs / sha).read_bytes(),
                            asset["media_type"],
                            {
                                "Content-Disposition": "inline; filename*=UTF-8''"
                                + name,
                                "Content-Security-Policy": policy,
                            },
                        )
                    if url.path == "/api/health":
                        return self.send(
                            200,
                            {
                                "ok": True,
                                "implementation": app.loaded_implementation["digest"],
                                "runtime": app.runner.status() if app.runner else None,
                            },
                        )
                require(
                    self.command == "POST" and url.path == "/api/action",
                    "接口不存在",
                    "not_found",
                    404,
                )
                data = validate_action_request(self.post_body(address))
                principal = self.management_principal()
                require(
                    "allowed_actions" not in principal
                    or data.get("action") in principal["allowed_actions"],
                    "此任务凭据没有该业务命令权限",
                    "forbidden",
                    403,
                )
                result = app.dispatch(data, scope, principal=principal)
                return self.send(200, {"ok": True, "result": result})
            except Problem as e:
                return self.send(
                    e.status,
                    {
                        "ok": False,
                        "error": str(e),
                        "code": e.code,
                        "details": e.details,
                    },
                )
            except (KeyError, ValueError, TypeError):
                return self.send(
                    400,
                    {
                        "ok": False,
                        "error": "请求字段不完整或格式错误",
                        "code": "invalid",
                    },
                )
            except Exception as e:
                error_id = record_internal_error(e)
                return self.send(
                    500,
                    {
                        "ok": False,
                        "error": "操作失败，原内容仍保留",
                        "code": "internal_error",
                        "exception_type": type(e).__name__,
                        "error_id": error_id,
                    },
                )

        do_GET = request
        do_POST = request

    server = ThreadingHTTPServer((host, port), Handler)
    app.config["_local_mcp_origin"] = "http://127.0.0.1:" + str(
        server.server_address[1]
    )
    server.daemon_threads = False
    if app.runner:
        app.runner.start()
    return server
