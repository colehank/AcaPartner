"""Preparation tasks over registered immutable assets; no arbitrary host paths."""
from __future__ import annotations
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile

from .store import Problem, digest, encoded, now, require
from .workshop_worker import CATEGORIES, VERSION


ALIASES = {"stimulus": "stimuli", "annotations": "annotation_cleaning", "neural": "neural_preprocessing"}


class Workshop:
    def __init__(self, app):
        self.app, self.store = app, app.store

    def _inputs(self, requested, project_id, directory):
        require(isinstance(requested, list) and 1 <= len(requested) <= 101, "工坊需要1..101个已登记输入资产")
        inputs, aliases, total = [], set(), 0
        folder = directory / "inputs"
        folder.mkdir(exist_ok=True)
        for value in requested:
            ref = {"sha": value} if isinstance(value, str) else value
            require(isinstance(ref, dict) and not any(k in ref for k in ("path", "url", "host_path")), "输入只接受资产标识，不能传任意主机路径", "forbidden", 403)
            info = self.store.asset(ref.get("sha", ref.get("asset_sha")))
            metadata = info["metadata"]
            require(metadata.get("project_id") == project_id or project_id in metadata.get("projects", [])
                    or project_id in metadata.get("shared_with", []), "工坊输入未授权给此项目", "forbidden", 403)
            total += info["size"]
            require(total <= 128 * 1024 * 1024, "轻量准备任务总输入超过128MB")
            alias = ref.get("alias", info["filename"])
            require(isinstance(alias, str) and alias not in aliases and alias not in {"", ".", ".."}
                    and Path(alias).name == alias and len(alias) <= 200, "输入别名不合法或重复")
            aliases.add(alias)
            filename = info["sha"] + "_" + re.sub(r"[^A-Za-z0-9_.-]", "_", alias)
            path = folder / filename
            if not path.exists():
                shutil.copyfile(self.store.blobs / info["sha"], path)
                path.chmod(0o444)
            require(hashlib.sha256(path.read_bytes()).hexdigest() == info["sha"], "输入副本身份不一致", "integrity", 409)
            # Provenance comes from the registered asset, never from task claims.
            inputs.append({"sha": info["sha"], "alias": alias, "path": str(path.relative_to(directory)),
                           "role": ref.get("role", "input"), "media_type": info["media_type"],
                           "provenance": metadata.get("provenance", "unverified_import"),
                           "synthetic": bool(metadata.get("synthetic", False)),
                           "source": metadata.get("source", "registered asset"), "size": info["size"]})
        return inputs

    def execute(self, task, run_process):
        payload, s = task["payload"], self.store
        token=task.get('execution_token')
        guard={'task_id':task['id'],'execution_token':token}
        with s.connect() as connection:s.assert_execution(connection,task['id'],token)
        settings = payload.get("workshop", {})
        category = ALIASES.get(settings.get("category"), settings.get("category"))
        require(category in CATEGORIES, "未支持的工坊类别")
        authorization = payload.get("authorization", {})
        require(authorization.get("execute_code") is True, "工坊可执行代码尚未明确授权", "authorization_required", 403)
        if category == "neural_preprocessing":
            require(authorization.get("scientific_preprocessing") is True,
                    "神经数据预处理需要单独的科学计算授权；不启动拟合", "authorization_required", 403)
        require(not settings.get("code"), "此入口执行受支持的固定准备方法；任意用户脚本须通过独立审查和扩展授权", "unsupported_custom_code", 422)
        config = settings.get("config", {})
        require(isinstance(config, dict), "工坊配置需要JSON对象")
        self.app.get(payload["project_id"])
        object_id = "WORKSHOP-" + task["id"].removeprefix("TASK-")
        try:
            existing = s.get(object_id)
            require(existing["metadata"].get("task_digest") == task["payload_digest"], "成果任务身份冲突", "integrity", 409)
            for output in existing["content"].get("outputs", []):
                s.asset(output["sha"])
            return {"object_id": existing["id"], "revision": existing["revision"], "recovered": True,
                    "category": category, "scientific_approval": False, "user_acceptance": "pending"}
        except Problem as exc:
            if exc.status != 404:
                raise
        directory = s.workspace / "runs" / task["id"] / "workshop"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        inputs = self._inputs(settings.get("inputs"), payload["project_id"], directory)
        job = {"version": VERSION, "category": category, "inputs": inputs,
               "config": {k: v for k, v in config.items() if k != "remote_host"}}
        job_path = directory / "job.json"
        serialized = json.dumps(job, sort_keys=True, ensure_ascii=False)
        if job_path.exists():
            require(json.loads(job_path.read_text()) == job, "已冻结工坊任务与当前内容不一致", "integrity", 409)
        else:
            job_path.write_text(serialized + "\n")
        worker = Path(__file__).with_name("workshop_worker.py")
        snapshot = directory / "workshop_worker.py"
        if snapshot.exists():
            require(snapshot.read_bytes() == worker.read_bytes(), "工坊代码变化，保留当前尝试并重新评估", "integrity", 409)
        else:
            shutil.copyfile(worker, snapshot)
        s.step(task["id"], "workshop_inputs", "done", {"job_sha256": digest(serialized.encode()), "inputs": inputs, "worker_sha256": digest(snapshot.read_bytes())},execution_token=token)
        result_path = directory / "result.json"
        record_path = directory / "execution.json"
        remote_host = config.get("remote_host")
        if result_path.exists():
            result = json.loads(result_path.read_text())
            process = json.loads(record_path.read_text()) if record_path.exists() else {"recovered_after_output_commit": True}
        elif remote_host:
            require(authorization.get("remote_execution") is True, "输入传往执行主机尚未授权", "authorization_required", 403)
            from .remote import RemoteClient
            host = self.app.config.get("remote_hosts", {}).get(remote_host)
            require(host and host.get("authorized") is True, "执行主机缺少授权配置", "runtime_unavailable", 503)
            client = RemoteClient(host)
            previous = next((x for x in s.task(task["id"])["steps"] if x["step_key"] == "remote_workshop"), None)
            def checkpoint(value):
                s.step(task["id"], "remote_workshop", value["status"], value,execution_token=token)
            def check():
                with s.connect() as connection:s.assert_execution(connection,task['id'],token)
                require(s.task(task["id"])["status"] not in {"paused", "cancelled", "waiting_input"}, "远程任务已停止", "cancelled", 409)
                require(not (self.app.runner and self.app.runner.shutdown.is_set()), "执行服务已停止", "cancelled", 409)
            result, process = client.execute(job, directory, task["id"],
                                             timeout=payload.get("budget", {}).get("timeout_seconds", 300),
                                             checkpoint=checkpoint, check=check, previous=previous["data"] if previous else None)
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            record_path.write_text(json.dumps(process, ensure_ascii=False, indent=2) + "\n")
        else:
            # A partial failed attempt is retained. It cannot be silently overwritten.
            require(not (directory / "outputs").exists() or not any((directory / "outputs").iterdir()),
                    "上次尝试留下部分输出，需检查并以新请求接续", "partial_outputs", 409)
            rendering = self.app.config.get("rendering", {})
            python = rendering.get("scientific_python") or os.environ.get("RESEARCH_PARTNER_SCIENTIFIC_PYTHON", sys.executable)
            env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "SYSTEMROOT", "LD_LIBRARY_PATH"}}
            env.update(MPLCONFIGDIR=str(directory / "mplconfig"), PYTHONDONTWRITEBYTECODE="1", HOME=str(directory))
            process = run_process([str(python), str(snapshot), str(job_path)], cwd=directory, env=env)
            record_path.write_text(json.dumps(process, ensure_ascii=False, indent=2) + "\n")
            require(process.get("returncode") == 0 and result_path.is_file(), "工坊实际运行失败；日志与输入已保留", "workshop_failed", 422,
                    {"returncode": process.get("returncode"), "stderr": process.get("stderr", "")[-3000:]})
            result = json.loads(result_path.read_text())
        require(result.get("ok") and result.get("job_sha256") == digest(serialized.encode()), "工坊返回与任务身份不一致", "integrity", 409)
        require(result.get("manifest", {}).get("environment", {}).get("worker_sha256") == digest(snapshot.read_bytes()),
                "执行主机和交付构建的工坊代码不一致", "integrity", 409)
        outputs = []
        for file in result.get("files", []):
            path = (directory / file["path"]).resolve()
            require(path.is_relative_to(directory / "outputs") and path.is_file() and not path.is_symlink(), "输出路径越界", "unsafe_output", 422)
            data = path.read_bytes()
            require(digest(data) == file["sha256"], "输出内容身份不一致", "integrity", 409)
            require(len(data) <= 128 * 1024 * 1024, "单项输出超过限制")
            info = s.add_asset(data, path.name, mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                               {"project_id": payload["project_id"], "object_id": object_id, "task_id": task["id"], "role": "workshop_output"},**guard)
            outputs.append({"name": path.name, "sha": info["sha"], "url": info["url"], "mime": info["media_type"], "size": info["size"]})
        require(outputs and result.get("manifest"), "工坊没有实际输出", "workshop_failed", 422)
        bundle_path = directory / "reproducible-source.zip"
        with zipfile.ZipFile(bundle_path, "w", zipfile.ZIP_DEFLATED) as bundle:
            for path in [job_path, snapshot, result_path, record_path, *(directory / "inputs").iterdir(), *(directory / "outputs").iterdir()]:
                if path.is_file():
                    bundle.write(path, path.relative_to(directory))
            bundle.writestr("README.txt", "Use an authorized scientific Python environment with the modules listed in outputs/environment.json.\nInputs are immutable content-addressed copies.\nTo reproduce: rename outputs/ and result.json to preserve the recorded run, then execute: python workshop_worker.py job.json\nFor the interactive tool open outputs/visualization.html. For trials open outputs/experiment.html or run python experiment.py from outputs/.\nNo scientific, human-use, timing or product acceptance is implied.\n")
        bundle_info = s.add_asset(bundle_path.read_bytes(), bundle_path.name, "application/zip", {"project_id": payload["project_id"], "object_id": object_id, "role": "workshop_source_bundle"},**guard)
        outputs.append({"name": bundle_info["filename"], "sha": bundle_info["sha"], "url": bundle_info["url"], "mime": bundle_info["media_type"], "size": bundle_info["size"]})
        manifest = result["manifest"]
        content = {"category": category, "inputs": inputs, "config": config, "outputs": outputs,
                   "preview": next((o for o in outputs if "outputs/" + o["name"] == manifest["preview"]), None),
                   "validation": manifest["quality"], "acceptance": [], "status": "generated",
                   "limitations": manifest["limitations"], "run": {"task_id": task["id"], "process": process,
                   "worker_sha256": digest(snapshot.read_bytes()), "job_sha256": result["job_sha256"], "recorded_at": now()},
                   "source_bundle": bundle_info["sha"], "acceptance_eligible_input": manifest["acceptance_eligible_input"]}
        obj = s.create("workshop", payload.get("request") or f"{category} preparation", payload["project_id"], content,
                       {"task_id": task["id"], "task_digest": task["payload_digest"], "technical_status": "generated",
                        "scientific_approval": False, "user_acceptance": "pending"}, ident=object_id, actor="runtime",**guard)
        s.relate(payload["project_id"], obj["id"], "produces", "confirmed",**guard)
        s.step(task["id"], "workshop_persist", "done", {"object_id": obj["id"], "result_sha256": digest(result_path.read_bytes()), "outputs": [o["sha"] for o in outputs]},execution_token=token)
        return {"object_id": obj["id"], "revision": obj["revision"], "category": category, "outputs": outputs,
                "scientific_approval": False, "user_acceptance": "pending", "acceptance_eligible_input": manifest["acceptance_eligible_input"]}
