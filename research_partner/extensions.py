"""Versioned, explicitly authorized external JSON-process extensions.

Permission checks govern activation and brokered data. execute_code is a trust
grant for local code, not an OS sandbox; secrets are not inherited in the env.
"""
from __future__ import annotations
import base64
import contextlib
import fcntl
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .devcontrol import identity, terminate_owned
from .store import Problem, digest, encoded, now, require, uid


PERMISSIONS = {"execute_code", "read_inputs", "write_outputs"}


class Extensions:
    def __init__(self, app):
        self.app, self.store = app, app.store
        self.root = self.store.workspace / "extensions"
        self.root.mkdir(exist_ok=True, mode=0o700)

    @contextlib.contextmanager
    def locked(self):
        with (self.root / ".registry.lock").open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def registry(self):
        return self.store.setting("extension_registry", {})

    def _version_directory(self, ident, fingerprint, version):
        """Portable source assets rebuild the cache; never follow an old host path."""
        directory = self.root / ident / fingerprint
        directory.mkdir(parents=True, exist_ok=True)
        for name, description in version["manifest"]["files"].items():
            path = directory / name
            if not path.exists():
                asset = self.store.asset(description["sha256"])
                content = (self.store.blobs / asset["sha"]).read_bytes()
                require(digest(content) == description["sha256"], "扩展源资产损坏", "integrity", 409)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content); path.chmod(0o444)
        return directory

    @staticmethod
    def public(entry):
        current = entry["versions"][entry["current"]]
        manifest = current["manifest"]
        return {"id": entry["id"], "name": manifest.get("name", entry["id"]),
                "description": manifest.get("description", ""), "version": manifest["version"],
                "api_version": manifest["api_version"], "manifest_sha256": entry["current"],
                "status": entry["status"], "operations": manifest["operations"],
                "required_permissions": manifest["permissions"], "permissions": entry.get("grants", []),
                "authorized": entry["status"] == "installed" and set(manifest["permissions"]) <= set(entry.get("grants", [])),
                "versions": [{"sha256": key, "version": item["manifest"]["version"]} for key, item in entry["versions"].items()],
                "execution_boundary": "Explicit execute_code grants trusted local code execution; not an OS security sandbox."}

    def _save(self, registry, event, ident, detail):
        with self.store.transaction() as conn:
            for key, value in (("extension_registry", registry), ("extensions", [self.public(e) for e in registry.values()])):
                conn.execute("INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, encoded(value)))
            self.store.event(conn, event, ident, detail, "extension_owner")

    def _validate_manifest(self, value, data):
        require(isinstance(value, dict), "扩展清单必须是JSON对象")
        manifest = {key: value[key] for key in ["id", "version", "api_version", "entrypoint", "permissions", "operations", "files"] if key in value}
        manifest.update({key: value[key] for key in ("name", "description", "license", "author") if key in value})
        require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", manifest.get("id", "")), "扩展ID不合法")
        require(re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", manifest.get("version", "")), "扩展需要明确语义版本")
        require(manifest.get("api_version") == 1, "扩展协议版本不兼容", "extension_incompatible", 409)
        require(isinstance(manifest.get("permissions"), list) and "execute_code" in manifest["permissions"]
                and set(manifest["permissions"]) <= PERMISSIONS, "扩展声明需要execute_code及受支持的数据权限")
        require(isinstance(manifest.get("operations"), list) and manifest["operations"] and
                all(isinstance(op, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{0,79}", op) for op in manifest["operations"]), "扩展操作声明无效")
        require(isinstance(manifest.get("files"), dict) and 1 <= len(manifest["files"]) <= 32, "扩展需要1..32个带哈希的源码文件")
        entrypoint = manifest.get("entrypoint")
        require(isinstance(entrypoint, str) and entrypoint.endswith(".py") and entrypoint in manifest["files"], "扩展需要清单中的Python入口")
        source_root = None
        if data.get("path"):
            source_root = Path(data["path"]).resolve()
            roots = [Path(p).resolve() for p in self.app.config.get("extension_roots", [])]
            require(source_root.is_dir() and any(source_root.is_relative_to(p) for p in roots), "扩展路径未列入授权导入范围", "forbidden", 403)
        files, total, normalized = {}, 0, {}
        for name, description in manifest["files"].items():
            relative = Path(name)
            require(isinstance(name, str) and not relative.is_absolute() and ".." not in relative.parts
                    and not any(part.startswith(".") for part in relative.parts)
                    and re.fullmatch(r"[A-Za-z0-9_./-]+", name), "扩展源码路径不合法")
            info = {"sha256": description} if isinstance(description, str) else description
            require(isinstance(info, dict) and re.fullmatch(r"[a-f0-9]{64}", info.get("sha256", "")), "扩展源码缺少SHA256")
            if "base64" in info:
                try: content = base64.b64decode(info["base64"], validate=True)
                except (ValueError, TypeError): raise Problem("扩展源码base64无效")
            else:
                require(source_root is not None, "扩展源码需要base64或授权的外部目录")
                path = source_root / relative
                require(path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(source_root), "扩展源码文件越界", "forbidden", 403)
                content = path.read_bytes()
            total += len(content)
            require(total <= 1024 * 1024 and digest(content) == info["sha256"], "扩展源码身份或1MB限制不符合", "integrity", 409)
            files[name] = content
            normalized[name] = {"sha256": digest(content), "size": len(content)}
        manifest["files"] = normalized
        return manifest, files

    def _install(self, data, upgrade=False):
        manifest, files = self._validate_manifest(data.get("manifest"), data)
        ident, fingerprint = manifest["id"], digest(manifest)
        with self.locked():
            registry = self.registry()
            previous = registry.get(ident)
            if upgrade:
                require(previous and previous["status"] == "installed", "不能升级未安装扩展", "not_found", 404)
                require(previous["current"] != fingerprint, "该扩展版本已安装", "conflict", 409)
                require(previous["versions"][previous["current"]]["manifest"]["version"] != manifest["version"], "变更源码必须使用新扩展版本", "conflict", 409)
            else:
                require(not previous or previous["status"] == "uninstalled", "扩展已存在，请使用upgrade", "conflict", 409)
            directory = self.root / ident / fingerprint
            directory.mkdir(parents=True, exist_ok=True)
            for name, content in files.items():
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    require(digest(path.read_bytes()) == digest(content), "已缓存扩展源码损坏", "integrity", 409)
                else:
                    path.write_bytes(content); path.chmod(0o444)
                self.store.add_asset(content, Path(name).name, "text/x-python" if name.endswith(".py") else "application/octet-stream",
                                     {"role": "extension_source", "extension": ident, "manifest_sha256": fingerprint})
            entry = previous or {"id": ident, "versions": {}, "history": []}
            entry["versions"][fingerprint] = {"manifest": manifest, "source_assets": {name: digest(content) for name, content in files.items()},
                                              "registered_at": now()}
            entry["history"].append({"action": "upgrade" if upgrade else "register", "from": entry.get("current"), "to": fingerprint, "at": now()})
            entry.update(current=fingerprint, status="installed", grants=[], grant_workspace=None)
            registry[ident] = entry
            self._save(registry, "extension.upgraded" if upgrade else "extension.registered", ident, {"manifest_sha256": fingerprint, "permissions_granted": []})
            return self.public(entry)

    def dispatch(self, data):
        action = data.get("action", "")
        if action == "extension.register":
            return self._install(data)
        if action == "extension.upgrade":
            return self._install(data, upgrade=True)
        if action in {"extension.discover", "extension.list"}:
            return [self.public(entry) for entry in self.registry().values()]
        if action == "extension.call":
            return self.call(data)
        with self.locked():
            registry = self.registry()
            entry = registry.get(data.get("id"))
            require(entry, "扩展不存在", "not_found", 404)
            if action == "extension.authorize":
                require(entry["status"] == "installed", "扩展已卸载", "extension_unavailable", 409)
                permissions = data.get("permissions")
                required = entry["versions"][entry["current"]]["manifest"]["permissions"]
                require(isinstance(permissions, list) and set(permissions) <= set(required), "不能授予清单未声明的权限", "forbidden", 403)
                entry["grants"] = sorted(set(permissions))
                entry["grant_workspace"] = str(self.store.workspace)
                detail = {"manifest_sha256": entry["current"], "permissions": entry["grants"]}
            elif action == "extension.uninstall":
                entry.update(status="uninstalled", grants=[], grant_workspace=None)
                detail = {"outputs_retained": True, "version_archive_retained": True}
            elif action == "extension.rollback":
                target = data.get("manifest_sha256")
                if not target and data.get("version"):
                    matches = [key for key, value in entry["versions"].items() if value["manifest"]["version"] == data["version"]]
                    require(len(matches) == 1, "回退版本不唯一或不存在")
                    target = matches[0]
                require(target in entry["versions"] and target != entry["current"], "回退目标无效")
                detail = {"from": entry["current"], "to": target, "permissions_reset": True}
                entry.update(current=target, status="installed", grants=[], grant_workspace=None)
            else:
                raise Problem("不支持的扩展操作", "not_implemented", 501)
            entry["history"].append({"action": action, "at": now(), **detail})
            self._save(registry, action, entry["id"], detail)
            return self.public(entry)

    def call(self, data):
        with self.locked():
            registry = self.registry()
            entry = registry.get(data.get("id"))
            require(entry and entry["status"] == "installed", "扩展未安装或已卸载", "extension_unavailable", 409)
            version = entry["versions"][entry["current"]]
            manifest = version["manifest"]
            require(entry.get("grant_workspace") == str(self.store.workspace) and set(manifest["permissions"]) <= set(entry["grants"]),
                    "扩展当前代码版本未获本实例所需权限", "authorization_required", 403)
            operation = data.get("operation")
            require(operation in manifest["operations"], "扩展未声明此操作")
            code_directory = self._version_directory(entry["id"], entry["current"], version)
            for name, file in manifest["files"].items():
                path = code_directory / name
                require(path.is_file() and not path.is_symlink() and digest(path.read_bytes()) == file["sha256"], "扩展源码在授权后发生变化", "integrity", 409)
            # Freeze the grant and implementation this invocation actually uses.
            current_sha, permissions = entry["current"], list(entry["grants"])
        supplied = data.get("input", {})
        require(isinstance(supplied, dict), "扩展输入必须是JSON对象")
        project_id = data.get("project_id", supplied.get("project_id"))
        require(project_id, "扩展调用需要成果所属项目")
        self.app.get(project_id)
        refs = supplied.get("assets", [])
        require(isinstance(refs, list) and len(refs) <= 100, "扩展输入资产数量无效")
        require(not refs or "read_inputs" in permissions, "扩展未获输入读取权限", "forbidden", 403)
        invocation = uid("EXTCALL")
        directory = self.root / "runs" / invocation
        directory.mkdir(parents=True, mode=0o700)
        (directory / "inputs").mkdir(); (directory / "outputs").mkdir()
        inputs, total = [], 0
        for value in refs:
            ref = {"sha": value} if isinstance(value, str) else value
            require(isinstance(ref, dict) and not any(k in ref for k in ("path", "url")), "扩展输入只接受已登记资产")
            info = self.store.asset(ref.get("sha"))
            require(info["metadata"].get("project_id") == project_id or project_id in info["metadata"].get("projects", [])
                    or project_id in info["metadata"].get("shared_with", []), "扩展输入没有跨项目权限", "forbidden", 403)
            total += info["size"]
            require(total <= 32 * 1024 * 1024, "扩展总输入超过32MB")
            path = directory / "inputs" / info["sha"]
            shutil.copyfile(self.store.blobs / info["sha"], path); path.chmod(0o444)
            inputs.append({"sha": info["sha"], "filename": info["filename"], "path": str(path.relative_to(directory)), "media_type": info["media_type"]})
        request = {"protocol": 1, "operation": operation, "input": {"assets": inputs, "params": supplied.get("params", {})},
                   "output_dir": "outputs", "permissions": permissions}
        request_bytes = encoded(request).encode()
        require(len(request_bytes) <= 1024 * 1024, "扩展JSON请求过大")
        request_path = directory / "request.json"
        request_path.write_bytes(request_bytes)
        python = self.app.config.get("extensions", {}).get("python", sys.executable)
        argv = [python, "-I", "-c", "import runpy,sys; sys.path.insert(0,sys.argv[1]); runpy.run_path(sys.argv[2],run_name='__main__')",
                str(code_directory), str(code_directory / manifest["entrypoint"])]
        timeout = min(120, max(1, int(self.app.config.get("extensions", {}).get("timeout_seconds", 30))))
        env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "LD_LIBRARY_PATH"}}
        env.update(HOME=str(directory), PYTHONDONTWRITEBYTECODE="1")
        started = time.monotonic()
        with request_path.open("rb") as stdin, (directory / "stdout").open("wb") as stdout, (directory / "stderr").open("wb") as stderr:
            try:
                process = subprocess.Popen(argv, cwd=directory, env=env, stdin=stdin, stdout=stdout, stderr=stderr, start_new_session=True)
            except OSError as exc:
                raise Problem("扩展执行环境不可用", "runtime_unavailable", 503) from exc
            owner = identity(process.pid, include_zombie=True)
            failure = None
            while os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                if time.monotonic() - started > timeout:
                    failure = "timeout"; break
                if sum((directory / name).stat().st_size for name in ("stdout", "stderr")) > 2 * 1024 * 1024:
                    failure = "output_limit"; break
                current = self.registry().get(entry["id"], {})
                if current.get("status") != "installed" or current.get("current") != current_sha or not set(permissions) <= set(current.get("grants", [])):
                    failure = "authorization_withdrawn"; break
                time.sleep(.05)
            terminate_owned(owner); process.wait(timeout=3)
        raw = (directory / "stdout").read_bytes()
        error = (directory / "stderr").read_bytes()
        current = self.registry().get(entry["id"], {})
        if current.get("status") != "installed" or current.get("current") != current_sha or not set(permissions) <= set(current.get("grants", [])):
            failure = "authorization_withdrawn"
        for name, file in manifest["files"].items():
            path = code_directory / name
            if not path.is_file() or path.is_symlink() or digest(path.read_bytes()) != file["sha256"]:
                failure = "authorized_source_changed"
        receipt = {"invocation_id": invocation, "extension": entry["id"], "version": manifest["version"],
                   "manifest_sha256": current_sha, "permissions": permissions, "operation": operation,
                   "argv": argv, "cwd": str(directory),
                   "request_sha256": digest(request_bytes), "process_identity": owner, "returncode": process.returncode,
                   "stdout_sha256": digest(raw), "stderr_sha256": digest(error),
                   "elapsed_seconds": time.monotonic() - started, "failure": failure, "observed_at": now()}
        if len(raw) <= 1024 * 1024 and len(error) <= 1024 * 1024:
            receipt["logs"] = [self.store.add_asset(content, "extension-" + name + ".txt", "text/plain",
                                                   {"project_id": project_id, "invocation": invocation, "role": "execution_log"})
                               for name, content in (("stdout", raw), ("stderr", error))]
        # Failures are recorded before parsing/publishing; raw diagnostic assets stay private to the project.
        self.store.set_setting("extension_last_invocation:" + entry["id"], receipt)
        require(not failure and process.returncode == 0 and len(raw) <= 1024 * 1024 and len(error) <= 1024 * 1024,
                "扩展实际执行失败；没有发布成功结果", "extension_failed", 422, receipt)
        try: result = json.loads(raw)
        except (ValueError, UnicodeDecodeError): raise Problem("扩展未返回JSON协议结果", "extension_protocol", 422)
        require(isinstance(result, dict) and result.get("protocol") == 1 and result.get("ok") is True
                and result.get("operation") == operation, "扩展返回协议或操作不匹配", "extension_protocol", 422)
        files = result.get("outputs", [])
        require(isinstance(files, list) and len(files) <= 100, "扩展返回输出数量无效")
        require(not files or "write_outputs" in permissions, "扩展未获输出写入权限", "forbidden", 403)
        outputs, total = [], 0
        for value in files:
            require(isinstance(value, dict) and isinstance(value.get("path"), str), "扩展输出路径无效")
            unresolved = directory / value["path"]
            path = unresolved.resolve()
            require(path.is_relative_to(directory / "outputs") and path.is_file() and not unresolved.is_symlink(), "扩展输出路径越界", "unsafe_output", 422)
            content = path.read_bytes(); total += len(content)
            require(total <= 32 * 1024 * 1024, "扩展输出总量超限")
            asset = self.store.add_asset(content, path.name, value.get("media_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                                        {"project_id": project_id, "extension": entry["id"], "manifest_sha256": current_sha, "invocation": invocation})
            outputs.append({"name": path.name, "sha": asset["sha"], "url": asset["url"], "mime": asset["media_type"]})
        for ref in inputs:
            require(digest((directory / ref["path"]).read_bytes()) == ref["sha"], "扩展修改了只读输入副本", "integrity", 409)
        provenance = {"manifest": manifest, "receipt": receipt, "inputs": [{k: v for k, v in r.items() if k != "path"} for r in inputs],
                      "result": result.get("result"), "scientific_approval": False, "user_acceptance": "pending"}
        record = self.store.add_asset((json.dumps(provenance, ensure_ascii=False, indent=2) + "\n").encode(),
                                      "extension-invocation.json", "application/json", {"project_id": project_id, "role": "extension_receipt"})
        outputs.append({"name": record["filename"], "sha": record["sha"], "url": record["url"], "mime": record["media_type"]})
        obj = self.store.create("workshop", manifest.get("name", entry["id"]) + ": " + operation, project_id,
                                {"category": "extension", "inputs": inputs, "outputs": outputs, "run": receipt,
                                 "validation": {"protocol": "verified", "scientific_approval": False}, "acceptance": []},
                                {"extension": entry["id"], "manifest_sha256": current_sha, "invocation": invocation, "scientific_approval": False})
        self.store.relate(project_id, obj["id"], "produces", "confirmed")
        return {"object_id": obj["id"], "revision": obj["revision"], "result": result.get("result"), "outputs": outputs,
                "receipt": receipt, "user_acceptance": "pending"}
