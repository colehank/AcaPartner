"""Authenticated independent preparation executor and integrity-checking client.

No arbitrary command endpoint. Deployment/start is an explicit operator action.
Independent-environment evidence is measured, never inferred from a host label.
"""
from __future__ import annotations
import argparse
import base64
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import platform
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .devcontrol import identity, terminate_owned
from .store import Problem, require
from .workshop_worker import VERSION, CATEGORIES


MAX_REQUEST = 32 * 1024 * 1024
MAX_TRANSFER = 16 * 1024 * 1024


def hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def host_identity():
    def read(path):
        try:
            return Path(path).read_text().strip()
        except OSError:
            return None
    try:
        namespace = os.readlink("/proc/self/ns/pid")
    except OSError:
        namespace = None
    return {"hostname": socket.gethostname(), "platform": platform.platform(),
            "pid_namespace": namespace, "boot_id": read("/proc/sys/kernel/random/boot_id")}


def atomic_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(temporary, path)


class RemoteClient:
    def __init__(self, config):
        self.endpoint = str(config.get("endpoint", config.get("url", ""))).rstrip("/")
        parsed = urllib.parse.urlparse(self.endpoint)
        require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password and not parsed.query,
                "远程端点格式无效", "runtime_unavailable", 503)
        require(parsed.scheme == "https" or parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                or config.get("allow_http") is True, "非回环主机需要HTTPS或明确的受控网络HTTP授权", "authorization_required", 403)
        token_path = config.get("token_file")
        require(token_path and Path(token_path).is_file(), "远程执行凭据不可用", "credentials_unavailable", 503)
        self._token = Path(token_path).read_text().strip()
        require(len(self._token) >= 24, "远程执行凭据长度不足", "credentials_unavailable", 503)
        self.request_timeout = min(30, max(1, float(config.get("request_timeout", 10))))

    def request(self, method, path, body=None):
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
        require(data is None or len(data) <= MAX_REQUEST, "远程传输请求超过32MB限制")
        request = urllib.request.Request(self.endpoint + path, data=data, method=method,
                                         headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json"})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        try:
            with urllib.request.build_opener(NoRedirect).open(request, timeout=self.request_timeout) as response:
                raw = response.read(MAX_REQUEST + 1)
                require(len(raw) <= MAX_REQUEST, "远程回复过大", "remote_protocol", 502)
                value = json.loads(raw)
        except urllib.error.HTTPError as exc:
            code = "credentials_unavailable" if exc.code in {401, 403} else "remote_protocol"
            exc.close()
            raise Problem(f"远程执行HTTP状态 {exc.code}", code, 503) from exc
        except (OSError, ValueError) as exc:
            raise Problem("远程连接中断或返回无效；保存同一请求身份，未盲目重发", "runtime_unavailable", 503) from exc
        require(isinstance(value, dict) and value.get("ok") is True, "远程协议返回失败", "remote_protocol", 502)
        return value

    def submit(self, job, directory, request_key, timeout):
        data, total = {}, 0
        for ref in job["inputs"]:
            content = (directory / ref["path"]).read_bytes()
            require(hash_bytes(content) == ref["sha"], "上传前输入校验失败", "integrity", 409)
            total += len(content)
            require(total <= MAX_TRANSFER, "远程轻量准备总输入超过16MB")
            data[ref["sha"]] = base64.b64encode(content).decode()
        return self.request("POST", "/v1/jobs", {"request_key": request_key, "job": job, "inputs": data,
                                                  "timeout_seconds": min(600, max(1, int(timeout)))})

    def status(self, job_id):
        require(re.fullmatch(r"[a-f0-9]{32}", job_id), "无效远程任务标识")
        return self.request("GET", "/v1/jobs/" + job_id)

    def result(self, job_id):
        return self.request("GET", "/v1/jobs/" + job_id + "/result")

    def cancel(self, job_id):
        return self.request("POST", "/v1/jobs/" + job_id + "/cancel", {})

    def execute(self, job, directory, request_key, timeout=300, checkpoint=lambda v: None, check=lambda: None, previous=None):
        started = time.monotonic()
        remote_id = previous.get("job_id") if previous else None
        if not remote_id:
            submitted = self.submit(job, directory, request_key, timeout)
            remote_id = submitted["job_id"]
        checkpoint({"status": "running", "job_id": remote_id, "request_key": request_key,
                    "endpoint": self.endpoint, "dispatch_reused": bool(previous)})
        try:
            while True:
                check()
                status = self.status(remote_id)
                if status["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                    break
                if time.monotonic() - started > min(620, max(1, int(timeout)) + 20):
                    try:
                        self.cancel(remote_id)
                    finally:
                        raise Problem("远程执行超时，已请求取消", "budget_exhausted", 409)
                time.sleep(.1)
        except Problem as exc:
            if exc.code == "cancelled":
                try:
                    self.cancel(remote_id)
                except Problem:
                    pass
            checkpoint({"status": "disconnected" if exc.code == "runtime_unavailable" else "stopped",
                        "job_id": remote_id, "request_key": request_key, "endpoint": self.endpoint,
                        "reason": exc.code, "server_timeout_remains_enforced": True})
            raise
        require(status["status"] == "succeeded", "远程实际任务没有完成；保留远程身份和失败记录", "remote_failed", 422, status)
        received = self.result(remote_id)
        total = 0
        for file in received.get("files", []):
            path = (directory / file["path"]).resolve()
            require(path.is_relative_to(directory / "outputs") and path.name not in {"", ".", ".."}, "远程输出越界", "unsafe_output", 422)
            content = base64.b64decode(file["base64"], validate=True)
            total += len(content)
            require(total <= MAX_TRANSFER and hash_bytes(content) == file["sha256"], "远程输出传输校验失败", "integrity", 409)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        local, remote = host_identity(), received["host"]
        independent = bool((local.get("boot_id") and remote.get("boot_id") and local["boot_id"] != remote["boot_id"])
                           or (local.get("pid_namespace") and remote.get("pid_namespace") and local["pid_namespace"] != remote["pid_namespace"]))
        record = {"execution_location": "configured_remote_executor", "endpoint": self.endpoint,
                  "job_id": remote_id, "process": received["process"], "host": remote,
                  "independent_environment_observed": independent, "client_host": local,
                  "workdir": received["workdir"], "elapsed_seconds": time.monotonic() - started,
                  "transfer_integrity": "SHA256 verified", "s21_acceptance": "pending independent/user review"}
        checkpoint({"status": "done", "job_id": remote_id, "request_key": request_key, "receipt": record})
        return received["result"], record


class Executor:
    def __init__(self, workspace, scientific_python=sys.executable, max_jobs=100):
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.ownership = (self.root / ".executor.lock").open("a+")
        try:
            fcntl.flock(self.ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.ownership.close()
            raise Problem("execution workspace already has an owner", "runtime_owned", 409)
        self.python = scientific_python
        self.max_jobs = max_jobs
        self.lock = threading.RLock()
        self.children = {}
        self.threads = []
        self.stopping = False
        self.host = host_identity()
        instance = self.root / "instance-id"
        if not instance.exists():
            instance.write_text(uuid.uuid4().hex)
        self.host["executor_instance_id"] = instance.read_text().strip()
        for path in self.root.glob("*/state.json"):
            value = json.loads(path.read_text())
            if value["status"] in {"queued", "running"}:
                terminate_owned(value.get("process_identity"))
                value.update(status="interrupted", error="executor restart; no automatic duplicate execution")
                atomic_json(path, value)

    def _directory(self, ident):
        require(re.fullmatch(r"[a-f0-9]{32}", ident), "invalid executor job id")
        path = self.root / ident
        require((path / "state.json").is_file(), "executor job not found", "not_found", 404)
        return path

    def state(self, ident):
        with self.lock:
            return json.loads((self._directory(ident) / "state.json").read_text())

    def submit(self, payload):
        job = payload.get("job", {})
        require(job.get("version") == VERSION and job.get("category") in CATEGORIES, "unsupported worker job")
        key = payload.get("request_key")
        require(isinstance(key, str) and 1 <= len(key) <= 200, "stable request key required")
        fingerprint = hash_bytes(json.dumps(job, sort_keys=True, ensure_ascii=False).encode())
        ident = hashlib.sha256(key.encode()).hexdigest()[:32]
        with self.lock:
            require(not self.stopping, "executor is stopping", "runtime_unavailable", 503)
            directory = self.root / ident
            if directory.exists():
                previous = self.state(ident)
                require(previous["job_sha256"] == fingerprint, "idempotency key payload conflict", "idempotency_conflict", 409)
                return previous
            require(len(list(self.root.glob("*/state.json"))) < self.max_jobs, "executor retained-job limit reached", "budget_exhausted", 409)
            refs = job.get("inputs")
            require(isinstance(refs, list) and 1 <= len(refs) <= 101, "bounded copied inputs required")
            prepared, total = [], 0
            for ref in refs:
                relative = Path(ref["path"])
                require(not relative.is_absolute() and len(relative.parts) == 2 and relative.parts[0] == "inputs"
                        and re.fullmatch(r"[a-f0-9]{64}_[A-Za-z0-9_.-]+", relative.name), "invalid copied input path")
                content = base64.b64decode(payload["inputs"][ref["sha"]], validate=True)
                total += len(content)
                require(total <= MAX_TRANSFER and hash_bytes(content) == ref["sha"], "input integrity/size mismatch", "integrity", 409)
                prepared.append((relative, content))
            timeout = payload.get("timeout_seconds", 60)
            require(isinstance(timeout, int) and 1 <= timeout <= 600, "bounded executor timeout required")
            directory.mkdir(mode=0o700)
            (directory / "inputs").mkdir()
            for relative, content in prepared:
                path = directory / relative
                path.write_bytes(content); path.chmod(0o444)
            (directory / "job.json").write_text(json.dumps(job, ensure_ascii=False, sort_keys=True) + "\n")
            state = {"ok": True, "job_id": ident, "job_sha256": fingerprint, "status": "queued",
                     "timeout_seconds": timeout, "host": self.host, "workdir": str(directory),
                     "submitted_at": time.time(), "process_identity": None, "cancel_requested": False}
            atomic_json(directory / "state.json", state)
            thread = threading.Thread(target=self._run, args=(ident,), daemon=True)
            self.threads.append(thread); thread.start()
            return state

    def _run(self, ident):
        directory = self.root / ident
        worker = Path(__file__).with_name("workshop_worker.py")
        argv = [self.python, str(worker), str(directory / "job.json")]
        started = time.monotonic()
        process = None
        try:
            with (directory / "stdout").open("wb") as out, (directory / "stderr").open("wb") as err:
                with self.lock:
                    state = self.state(ident)
                    if state["cancel_requested"]:
                        state["status"] = "cancelled"; atomic_json(directory / "state.json", state); return
                    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH"}}
                    env.update(HOME=str(directory), MPLCONFIGDIR=str(directory / "mplconfig"), PYTHONDONTWRITEBYTECODE="1")
                    process = subprocess.Popen(argv, cwd=directory, env=env, stdout=out, stderr=err, start_new_session=True)
                    owner = identity(process.pid, include_zombie=True)
                    self.children[ident] = owner
                    state.update(status="running", process_identity=owner, started_at=time.time())
                    atomic_json(directory / "state.json", state)
                failure = None
                while os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                    state = self.state(ident)
                    if state["cancel_requested"]:
                        failure = "cancelled"; break
                    if time.monotonic() - started > state["timeout_seconds"]:
                        failure = "timeout"; break
                    if sum((directory / n).stat().st_size for n in ("stdout", "stderr")) > 2 * 1024 * 1024:
                        failure = "output log limit"; break
                    time.sleep(.05)
                terminate_owned(owner)
                process.wait(timeout=3)
                with self.lock:
                    state = self.state(ident)
                    result_path = directory / "result.json"
                    completed = process.returncode == 0 and result_path.is_file() and not failure and not state["cancel_requested"]
                    if completed:
                        result = json.loads(result_path.read_text())
                        completed = result.get("ok") is True and result.get("job_sha256") == state["job_sha256"]
                    state.update(status="succeeded" if completed else "cancelled" if state["cancel_requested"] else "failed",
                                 error=failure, finished_at=time.time(),
                                 process={"argv": argv, "returncode": process.returncode, "identity": owner,
                                          "elapsed_seconds": time.monotonic() - started,
                                          "stdout": (directory / "stdout").read_text(errors="replace")[-8000:],
                                          "stderr": (directory / "stderr").read_text(errors="replace")[-8000:]})
                    atomic_json(directory / "state.json", state)
        except Exception as exc:
            if process:
                terminate_owned(identity(process.pid, include_zombie=True))
                try: process.wait(timeout=3)
                except subprocess.TimeoutExpired: pass
            with self.lock:
                state = self.state(ident)
                state.update(status="failed", error=type(exc).__name__ + ": " + str(exc)[:500])
                atomic_json(directory / "state.json", state)
        finally:
            with self.lock:
                self.children.pop(ident, None)

    def cancel(self, ident):
        with self.lock:
            state = self.state(ident)
            if state["status"] not in {"succeeded", "failed", "cancelled", "interrupted"}:
                state["cancel_requested"] = True
                atomic_json(self._directory(ident) / "state.json", state)
                owner = self.children.get(ident)
                terminate_owned(owner)
            return state

    def result(self, ident):
        state = self.state(ident)
        require(state["status"] == "succeeded", "job has no successful result", "not_ready", 409)
        directory = self._directory(ident)
        result = json.loads((directory / "result.json").read_text())
        files, total = [], 0
        for item in result["files"]:
            path = (directory / item["path"]).resolve()
            require(path.is_relative_to(directory / "outputs") and path.is_file(), "unsafe executor output", "integrity", 409)
            content = path.read_bytes(); total += len(content)
            require(total <= MAX_TRANSFER and hash_bytes(content) == item["sha256"], "result transfer integrity/size mismatch", "integrity", 409)
            files.append({**item, "base64": base64.b64encode(content).decode()})
        return {"ok": True, "job_id": ident, "result": result, "files": files, "host": self.host,
                "process": state["process"], "workdir": state["workdir"]}

    def shutdown(self):
        with self.lock:
            self.stopping = True
            active = [path.parent.name for path in self.root.glob("*/state.json")
                      if json.loads(path.read_text())["status"] in {"queued", "running"}]
        for ident in active:
            self.cancel(ident)
        for thread in self.threads:
            thread.join(timeout=3)
        if not self.ownership.closed:
            fcntl.flock(self.ownership, fcntl.LOCK_UN)
            self.ownership.close()


def make_server(executor, token, host="127.0.0.1", port=0):
    require(len(token) >= 24, "executor token must contain at least 24 characters")
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                self.send_error(401); return
            try:
                path = self.path.split("?", 1)[0]
                body = None
                if self.command == "POST":
                    length = int(self.headers.get("Content-Length", "0"))
                    require(0 <= length <= MAX_REQUEST, "request too large")
                    body = json.loads(self.rfile.read(length) or b"{}")
                if self.command == "GET" and path == "/v1/health":
                    result = {"ok": True, "host": executor.host, "worker_version": VERSION}
                elif self.command == "POST" and path == "/v1/jobs":
                    result = executor.submit(body)
                else:
                    match = re.fullmatch(r"/v1/jobs/([a-f0-9]{32})(?:/(result|cancel))?", path)
                    require(match, "unknown endpoint", "not_found", 404)
                    ident, action = match.groups()
                    if self.command == "GET" and action is None:
                        result = executor.state(ident)
                    elif self.command == "GET" and action == "result":
                        result = executor.result(ident)
                    elif self.command == "POST" and action == "cancel":
                        result = executor.cancel(ident)
                    else:
                        raise Problem("method not allowed", "method", 405)
                data = json.dumps(result, ensure_ascii=False).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
            except (Problem, ValueError, KeyError, TypeError) as exc:
                code = exc.status if isinstance(exc, Problem) else 400
                data = json.dumps({"ok": False, "error": str(exc)}).encode()
                self.send_response(code); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        do_GET = handle_request
        do_POST = handle_request
    return ThreadingHTTPServer((host, port), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["serve"])
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--scientific-python", default=sys.executable)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8877)
    args = parser.parse_args(argv)
    executor = Executor(args.workspace, args.scientific_python)
    server = make_server(executor, args.token_file.read_text().strip(), args.host, args.port)
    print(json.dumps({"listening": server.server_address, "host": executor.host, "token_exposed": False}), flush=True)
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close(); executor.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
