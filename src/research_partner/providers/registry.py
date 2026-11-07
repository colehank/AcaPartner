"""Real provider adapters. A missing provider never becomes a template answer."""

from __future__ import annotations
import json
import copy
import contextlib
import os
import re
import selectors
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from research_partner.providers.availability import require_codex_dynamic_available
from research_partner.storage.store import Problem, require, now, digest


def restricted_environment(extra=None):
    allowed = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "TZ",
        "TMPDIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
    }
    env = {k: v for k, v in os.environ.items() if k in allowed}
    env.update(extra or {})
    return env


def _native_write(path, value):
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def _native_json(path, root=None):
    try:
        value = (
            _controlled_file(root, path).decode()
            if root is not None
            else path.read_text()
        )
        return json.loads(value), None
    except (OSError, ValueError, Problem) as error:
        return None, {"path": str(path), "error": type(error).__name__}


def _native_session(value):
    return isinstance(value, str) and bool(
        re.fullmatch(r"session-[A-Za-z0-9_-]{1,160}", value)
    )


def _native_checkpoint(instance, resume=None, run_dirs_before=None):
    """Read durable identity/accounting; never infer a session from launch intent."""
    runs = instance / "control/runs"
    directories = sorted(p for p in runs.glob("*") if p.is_dir())
    selected = (
        directories
        if run_dirs_before is None
        else [p for p in directories if p.name not in run_dirs_before]
    )
    errors = []
    receipts = []
    if run_dirs_before is not None and len(selected) > 1:
        errors.append({"error": "multiple_native_runs_in_one_attempt"})
    for directory in selected:
        path = directory / "native-receipt.json"
        if path.exists():
            value, error = _native_json(path, instance)
            if error:
                errors.append(error)
            elif (
                isinstance(value, dict)
                and _native_session(value.get("session_id"))
                and value.get("native_api") in ("agents.create", "agents.resume")
                and value.get("phase") in ("loaded", "flushed", "checkpoint_flushed")
                and type(value.get("loaded_seq")) is int
                and value["loaded_seq"] >= 0
                and isinstance(value.get("provider"), str)
                and value["provider"]
                and isinstance(value.get("model"), str)
                and value["model"]
                and (
                    (
                        value["native_api"] == "agents.create"
                        and value.get("resumed_from") is None
                    )
                    or (
                        value["native_api"] == "agents.resume"
                        and value.get("resumed_from") == value["session_id"]
                    )
                )
            ):
                receipts.append((path, value))
            else:
                errors.append({"path": str(path), "error": "invalid_receipt"})
    usagepath = instance / "control/usage.json"
    usage, error = (
        _native_json(usagepath, instance)
        if usagepath.exists() or usagepath.is_symlink()
        else (None, None)
    )
    if error:
        errors.append(error)
    sessions = {r.get("session_id") for _, r in receipts if r.get("session_id")}
    calls = usage.get("calls", []) if isinstance(usage, dict) else []
    if usage is not None and (
        not isinstance(usage, dict)
        or not isinstance(calls, list)
        or any(
            not isinstance(call, dict) or not _native_session(call.get("session_id"))
            for call in calls
        )
    ):
        errors.append({"path": str(usagepath), "error": "invalid_usage_ledger"})
        calls = []
    sessions.update(call["session_id"] for call in calls)
    if resume:
        if _native_session(resume):
            sessions.add(resume)
        else:
            errors.append({"error": "invalid_resume_session"})
    # Multiple native sessions in one task or malformed identity evidence must
    # be inspected rather than silently picking a lexicographically last run.
    known = len(sessions) == 1 and bool(receipts or resume) and not errors
    session = next(iter(sessions)) if known else None
    if resume and any(
        r.get("session_id") != resume or r.get("resumed_from") != resume
        for _, r in receipts
    ):
        known = False
        session = None
        errors.append({"error": "resume_receipt_identity_mismatch"})
    latest = (
        max(receipts, key=lambda item: item[1]["loaded_seq"])[1] if receipts else {}
    )
    if (
        receipts
        and sum(value["loaded_seq"] == latest["loaded_seq"] for _, value in receipts)
        > 1
    ):
        errors.append({"error": "ambiguous_native_sequence"})
        known = False
        session = None
    return {
        **latest,
        "route": "deepseek_harness",
        "session_id": session,
        "resumed_from": resume if resume is not None else latest.get("resumed_from"),
        "usage": usage,
        "actual_bill_usd": None,
        "session_identity_confirmed": known,
        "session_identity_sources": [str(path) for path, _ in receipts]
        + ([str(usagepath)] if calls else []),
        "native_run_directories": [str(p) for p in selected],
        "recovery_errors": errors,
        "cumulative_dispatch_reservations": len(calls),
        "dispatch_scope": "Cumulative task ledger; not proof that this attempt reached the provider.",
        "dispatch_meaning": "Durable native reservation precedes provider stream; interrupted billing or network delivery remains unknown.",
        "resume_requires_explicit_task_control": True,
    }


def _controlled_file(root, path, limit=8 * 1024 * 1024):
    """Read a bounded regular file without following a capsule-owned symlink."""
    root = Path(root)
    path = Path(path)
    require(
        not root.is_symlink() and path.is_relative_to(root),
        "候选文件不在受控目录",
        "candidate_checkpoint_invalid",
        409,
    )
    walk = root
    for part in path.relative_to(root).parts:
        walk = walk / part
        require(
            not walk.is_symlink(),
            "候选检查点含符号链接",
            "candidate_checkpoint_invalid",
            409,
        )
    require(
        path.is_file() and path.stat().st_size <= limit,
        "候选检查点缺失或超出大小界限",
        "candidate_checkpoint_invalid",
        409,
    )
    return path.read_bytes()


def verify_native_sources(task, directory, expected_contract_hash=None):
    """Used on dispatch AND zero-call recovery/new publication, never object reads."""
    from research_partner.execution.evidence import verify_evidence_layout

    directory = Path(directory)
    raw = _controlled_file(directory, directory / "capsule/task.json", 131072)
    try:
        contract = json.loads(raw)
    except ValueError as error:
        raise Problem(
            "原生来源合同无效", "candidate_checkpoint_invalid", 409
        ) from error
    require(
        isinstance(contract, dict)
        and contract.get("task_id") == task["id"].lower()
        and contract.get("objective") == task["payload"].get("request")
        and contract.get("context", {}) == task["payload"].get("context", {}),
        "原生来源合同不属于当前任务与冻结上下文",
        "candidate_checkpoint_invalid",
        409,
    )
    if expected_contract_hash:
        require(
            digest(raw) == expected_contract_hash,
            "原生来源合同身份变化",
            "candidate_checkpoint_invalid",
            409,
        )
    packet = _controlled_file(directory, directory / "evidence.json", 131072)
    verify_evidence_layout(
        contract,
        packet,
        lambda relative: _controlled_file(
            directory, directory / "capsule" / relative, 131072
        ),
    )
    return contract


def _usage_extends(current, baseline):
    """Reservations are immutable; only their finish/usage fields may settle."""
    mutable = {"usage", "finish", "status", "conservative_usage_estimate_usd"}

    def identity(call):
        return {k: v for k, v in call.items() if k not in mutable}

    return (
        isinstance(current, dict)
        and isinstance(baseline, dict)
        and current.get("contract_sha256") == baseline.get("contract_sha256")
        and isinstance(current.get("calls"), list)
        and isinstance(baseline.get("calls"), list)
        and len(current["calls"]) >= len(baseline["calls"])
        and all(
            isinstance(a, dict) and isinstance(b, dict) and identity(a) == identity(b)
            for a, b in zip(current["calls"], baseline["calls"])
        )
        and isinstance(current.get("reserved_usd", 0), (int, float))
        and isinstance(baseline.get("reserved_usd", 0), (int, float))
        and current.get("reserved_usd", 0) >= baseline.get("reserved_usd", 0)
    )


def _merge_native_usage(left, right, code="native_accounting_integrity", status=409):
    """Keep the longest reservation history and every compatible settled leaf."""
    if _usage_extends(right, left):
        result = copy.deepcopy(right)
    else:
        require(_usage_extends(left, right), "原生用量记录不符合单调历史", code, status)
        result = copy.deepcopy(left)

    def known(a, b):
        if a is None:
            return copy.deepcopy(b)
        if b is None:
            return copy.deepcopy(a)
        if isinstance(a, dict) and isinstance(b, dict):
            return {key: known(a.get(key), b.get(key)) for key in a.keys() | b.keys()}
        require(
            a == b
            and (
                type(a) is type(b)
                or type(a) in {int, float}
                and type(b) in {int, float}
            ),
            "同一请求的已结算用量互相矛盾",
            code,
            status,
        )
        return copy.deepcopy(a)

    for i, (old, new) in enumerate(zip(left["calls"], right["calls"])):
        for field in ("usage", "finish"):
            if field in old or field in new:
                result["calls"][i][field] = known(old.get(field), new.get(field))
    return result


def _remember_native_usage(store, task_id, usage, session_id=None, connection=None):
    """Monotonic accounting evidence, independent of mutable task/error rows.

    A late owned receipt may record spending after pause, but grants no new
    dispatch or publication. The caller fences actual receipts by launch intent.
    """
    require(
        isinstance(usage, dict)
        and isinstance(usage.get("contract_sha256"), str)
        and isinstance(usage.get("calls"), list)
        and all(isinstance(c, dict) for c in usage["calls"]),
        "原生已见预算记录无效",
        "provider_checkpoint_missing",
        503,
    )

    def remember(c):
        key = "native_usage_anchor:" + task_id
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        old = json.loads(row[0]) if row else None
        require(
            not old
            or not old.get("session_id")
            or not session_id
            or old["session_id"] == session_id,
            "原生预算锚点不属于同一会话",
            "provider_checkpoint_missing",
            503,
        )
        if old:
            chosen = _merge_native_usage(
                old["usage"], usage, "provider_checkpoint_missing", 503
            )
        else:
            chosen = usage
        value = {
            "version": 1,
            "task_id": task_id,
            "session_id": session_id or (old or {}).get("session_id"),
            "usage": chosen,
            "observed_at": now(),
        }
        from research_partner.packaging.compatibility import require_features

        require_features(c, ["native_accounting_anchor_v1"])
        c.execute(
            "INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        return value

    if connection is not None:
        return remember(connection)
    with store.transaction() as c:
        return remember(c)


def _native_events(directory, receipt):
    """Read the native durable event stream, never an assistant's final prose."""
    session = receipt["session_id"]
    home = directory / "instance/home/sessions"
    matches = list(home.glob("*/" + session + "/session.v3.jsonl.zstd"))
    require(
        len(matches) == 1,
        "原生会话事件文件不能唯一确定",
        "candidate_checkpoint_invalid",
        409,
    )
    path = matches[0]
    _controlled_file(directory, path)
    executable = shutil.which("zstd")
    require(
        executable,
        "验证原生候选需要本地 zstd 解码工具；未重新调用模型",
        "candidate_checkpoint_unavailable",
        503,
    )
    # Read incrementally with a deadline and output cap; malformed compression
    # cannot make recovery unbounded or trigger any network/model operation.
    process = subprocess.Popen(
        [executable, "-dc", "--memory=32MB", str(path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=restricted_environment(),
    )
    data = bytearray()
    deadline = time.monotonic() + 5
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                require(
                    time.monotonic() < deadline,
                    "原生事件读取超时",
                    "candidate_checkpoint_invalid",
                    409,
                )
                for key, _ in selector.select(0.1):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    data.extend(chunk)
                    require(
                        len(data) <= 32 * 1024 * 1024,
                        "原生事件超出读取界限",
                        "candidate_checkpoint_invalid",
                        409,
                    )
        require(
            process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0,
            "原生会话事件解码失败",
            "candidate_checkpoint_invalid",
            409,
        )
    except subprocess.TimeoutExpired:
        raise Problem("原生事件读取超时", "candidate_checkpoint_invalid", 409)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
    try:
        records = [json.loads(line) for line in data.decode().splitlines()]
    except (ValueError, UnicodeError):
        raise Problem("原生事件不是有效记录", "candidate_checkpoint_invalid", 409)
    require(
        records
        and isinstance(records[0], dict)
        and records[0].get("type") == "session"
        and records[0].get("id") == session
        and records[0].get("cwd") == str((directory / "capsule").resolve()),
        "原生会话身份或任务目录不匹配",
        "candidate_checkpoint_invalid",
        409,
    )
    events = records[1:]
    require(
        all(
            isinstance(event, dict)
            and type(event.get("seq")) is int
            and event["seq"] == index
            for index, event in enumerate(events)
        ),
        "原生事件序列不完整",
        "candidate_checkpoint_invalid",
        409,
    )
    require(
        type(receipt.get("first_seq")) is int
        and type(receipt.get("final_seq")) is int
        and 0
        <= receipt["loaded_seq"]
        <= receipt["first_seq"]
        < receipt["final_seq"]
        <= len(events),
        "原生回执的事件范围无效",
        "candidate_checkpoint_invalid",
        409,
    )
    return events[receipt["first_seq"] : receipt["final_seq"]]


def _native_candidate(
    task, directory, receipt, *, allow_budget_tail=False, allow_bookkeeping_tail=False
):
    """Select the last successful registered JSON write in this exact native run.

    Session event sequence, task contract, successful tool result, audit record
    and exact file bytes must agree. File name and modification time confer no
    authority. Returns None when this run has no successful candidate write.
    """
    directory = Path(directory)
    reason = receipt.get("reason", {})
    budget_tail = (
        allow_budget_tail
        and isinstance(reason, dict)
        and reason.get("kind") == "error"
        and isinstance(reason.get("error"), dict)
        and isinstance(reason["error"].get("message"), str)
        and reason["error"]["message"].startswith("BUDGET_EXHAUSTED: No dispatch;")
    )
    require(
        receipt.get("session_identity_confirmed")
        and receipt.get("phase") == "flushed"
        and isinstance(reason, dict)
        and (reason.get("kind") == "completed" or budget_tail),
        "原生会话尚无完整成功回执",
        "candidate_checkpoint_invalid",
        409,
    )
    contract_bytes = _controlled_file(
        directory, directory / "capsule/task.json", 131072
    )
    try:
        contract = json.loads(contract_bytes)
    except ValueError:
        raise Problem("任务合同检查点无效", "candidate_checkpoint_invalid", 409)
    contract_hash = digest(contract_bytes)
    verify_native_sources(task, directory, contract_hash)
    require(
        isinstance(contract, dict)
        and contract.get("task_id") == task["id"].lower()
        and contract.get("objective") == task["payload"].get("request")
        and isinstance(receipt.get("usage"), dict)
        and receipt["usage"].get("contract_sha256") == contract_hash,
        "候选任务合同与账本不匹配",
        "candidate_checkpoint_invalid",
        409,
    )
    evidence = contract.get("evidence", [])
    require(
        isinstance(evidence, list) and all(isinstance(item, dict) for item in evidence),
        "材料合同无效",
        "candidate_checkpoint_invalid",
        409,
    )
    evidence_ids = {
        item.get("id") for item in evidence if isinstance(item.get("id"), str)
    }
    calls = {}
    selected = None
    prompt_evidence = None
    events = _native_events(directory, receipt)
    require(
        events
        and events[-1].get("type") == "turn/end"
        and isinstance(events[-1].get("data"), dict)
        and events[-1]["data"].get("reason") == reason,
        "原生回执与终止事件不一致",
        "candidate_checkpoint_invalid",
        409,
    )
    if budget_tail:
        require(
            len(receipt["usage"].get("calls", []))
            == task["payload"]["budget"]["max_model_calls"],
            "预算终止未匹配任务原生请求上限",
            "candidate_checkpoint_invalid",
            409,
        )
    for event in events:
        data = event.get("data", {})
        if event.get("type") == "user/message" and isinstance(data, dict):
            prompt = "".join(
                part["text"]
                for part in data.get("content", [])
                if isinstance(part, dict)
                and part.get("type") == "text"
                and isinstance(part.get("text"), str)
            )
            coordinator = None
            if "\nCOORDINATOR GUIDANCE" in prompt:
                tail = prompt.rsplit("\nCOORDINATOR GUIDANCE", 1)[1]
                require(
                    "\n" in tail,
                    "原生指导输入缺少正文",
                    "candidate_checkpoint_invalid",
                    409,
                )
                try:
                    coordinator, _ = json.JSONDecoder().raw_decode(
                        tail.split("\n", 1)[1].lstrip()
                    )
                except ValueError:
                    raise Problem(
                        "原生指导输入无法验证", "candidate_checkpoint_invalid", 409
                    )
                require(
                    isinstance(coordinator, (dict, list)),
                    "原生指导输入不是对象或列表",
                    "candidate_checkpoint_invalid",
                    409,
                )
            prompt_evidence = {
                "prompt_seq": event["seq"],
                "prompt_sha256": digest(prompt.encode()),
                "coordinator_input": coordinator,
            }
            continue
        if (
            event.get("type") == "tool/call"
            and isinstance(data, dict)
            and data.get("name") == "write_candidate"
        ):
            require(
                isinstance(data.get("callId"), str),
                "候选工具调用身份无效",
                "candidate_checkpoint_invalid",
                409,
            )
            calls[data["callId"]] = (data, prompt_evidence)
            continue
        if event.get("type") != "tool/result" or not isinstance(data, dict):
            continue
        message = data.get("message", {})
        for block in message.get("content", []) if isinstance(message, dict) else []:
            if (
                not isinstance(block, dict)
                or block.get("type") != "tool-result"
                or block.get("isError") is not False
            ):
                continue
            entry = (
                calls.get(block.get("toolCallId"))
                if isinstance(block.get("toolCallId"), str)
                else None
            )
            if not entry:
                continue
            call, call_input = entry
            try:
                args = (
                    json.loads(call["arguments"])
                    if isinstance(call.get("arguments"), str)
                    else call.get("arguments")
                )
                text = "".join(
                    part["text"]
                    for part in block.get("content", [])
                    if isinstance(part, dict) and part.get("type") == "text"
                )
                registration = json.loads(text)
            except (ValueError, KeyError, TypeError):
                raise Problem(
                    "候选工具登记回执损坏", "candidate_checkpoint_invalid", 409
                )
            require(
                isinstance(args, dict) and isinstance(registration, dict),
                "候选登记不是对象",
                "candidate_checkpoint_invalid",
                409,
            )
            name = registration.get("name")
            require(
                isinstance(name, str)
                and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}\.json", name),
                "候选名称不是受控 JSON 文件",
                "candidate_checkpoint_invalid",
                409,
            )
            require(
                registration.get("status") == "candidate"
                and registration.get("contract_sha256") == contract_hash
                and args.get("name") == name
                and isinstance(args.get("content"), str)
                and isinstance(registration.get("evidence_ids"), list)
                and all(
                    isinstance(value, str) and value in evidence_ids
                    for value in registration["evidence_ids"]
                )
                and args.get("evidence_ids") == registration["evidence_ids"],
                "候选工具回执与合同不一致",
                "candidate_checkpoint_invalid",
                409,
            )
            content = _controlled_file(
                directory, directory / "capsule/outputs" / name, 131072
            )
            require(
                content == args["content"].encode()
                and digest(content) == registration.get("sha256"),
                "候选内容或哈希与原生回执不符",
                "candidate_checkpoint_invalid",
                409,
            )
            audits = []
            for path in (directory / "capsule/audit").glob("artifact-*.json"):
                try:
                    audit = json.loads(_controlled_file(directory, path, 8192))
                except ValueError:
                    raise Problem(
                        "候选审计回执损坏", "candidate_checkpoint_invalid", 409
                    )
                if audit == registration:
                    audits.append(path)
            require(
                len(audits) == 1,
                "候选缺少唯一匹配的登记审计",
                "candidate_checkpoint_invalid",
                409,
            )
            selected = {
                "text": content.decode(),
                "receipt": {
                    **receipt,
                    "input_provenance": call_input,
                    "candidate": {
                        **registration,
                        "session_id": receipt["session_id"],
                        "task_id": task["id"],
                        "tool_call_id": block["toolCallId"],
                        "result_seq": event["seq"],
                        "native_first_seq": receipt["first_seq"],
                        "native_final_seq": receipt["final_seq"],
                        "audit_record": audits[0].name,
                        "selection": "successful_native_tool_result_sequence",
                    },
                },
            }
    if selected and budget_tail:
        tail = [
            e
            for e in events
            if e["seq"] > selected["receipt"]["candidate"]["result_seq"]
        ]
        quiet = all(
            e.get("type") in {"step/end", "step/start", "assistant/attempt", "turn/end"}
            and (
                e.get("type") != "assistant/attempt"
                or e.get("data", {}).get("stream") == []
            )
            for e in tail
        )
        if not quiet:
            require(
                allow_bookkeeping_tail,
                "候选写入后仍有其他原生动作；不适用预算尾部回收",
                "candidate_checkpoint_invalid",
                409,
            )
            from research_partner.execution.recovery_tail import verify

            selected["receipt"]["bookkeeping_tail"] = verify(
                directory, tail, selected, contract, evidence_ids
            )

        selected["receipt"]["recovered_before_budget_tail"] = True
    return selected


def _release_dead_native_lock(instance):
    """Remove only this instance's demonstrably dead launcher lock."""
    lock = instance / "launch.lock"
    if not lock.exists():
        return None
    require(
        not lock.is_symlink() and lock.is_dir(),
        "原生执行锁无法安全确认",
        "provider_session_unknown",
        409,
    )
    ownerpath = lock / "owner.json"
    require(
        not ownerpath.is_symlink(),
        "原生执行锁身份无法确认",
        "provider_session_unknown",
        409,
    )
    owner, error = _native_json(ownerpath)
    require(
        not error
        and isinstance(owner, dict)
        and type(owner.get("pid")) is int
        and owner["pid"] > 1,
        "原生执行锁缺少有效进程身份；保留现场",
        "provider_session_unknown",
        409,
    )
    try:
        os.kill(owner["pid"], 0)
    except ProcessLookupError:
        pass
    except PermissionError:
        raise Problem(
            "原生执行锁进程身份不可确认；未清除", "provider_session_unknown", 409
        )
    else:
        raise Problem(
            "原生执行锁进程仍存活；未重复执行", "provider_session_unknown", 409
        )
    require(
        {p.name for p in lock.iterdir()} == {"owner.json"},
        "原生执行锁含未知文件；保留现场",
        "provider_session_unknown",
        409,
    )
    # The launcher can die before its DSH child. Refuse to clear its lock while
    # any live member of that process group remains; never terminate by PID here.
    require(
        Path("/proc").is_dir(),
        "无法核验原生进程组已停止",
        "provider_session_unknown",
        409,
    )
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            stat = (path / "stat").read_text().rsplit(")", 1)[1].split()
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError:
            raise Problem("无法核验原生进程组身份", "provider_session_unknown", 409)
        require(
            int(stat[2]) != owner["pid"] or stat[0] == "Z",
            "原生执行进程组仍有活动成员；未清除锁",
            "provider_session_unknown",
            409,
        )
    ownerpath.unlink()
    lock.rmdir()
    return {
        "pid": owner["pid"],
        "started_at": owner.get("started_at"),
        "removed_only_after_process_absent": True,
    }


class Providers:
    def __init__(self, app):
        self.app = app

    def recover_candidate(self, task, directory):
        """Recover a completed registered native output without model dispatch."""
        directory = Path(directory)
        saved = directory / "provider-receipt.json"
        if not saved.exists():
            return None
        previous, error = _native_json(saved, directory)
        require(
            not error and isinstance(previous, dict),
            "提供者回执无法读取",
            "candidate_checkpoint_invalid",
            409,
        )
        if (
            previous.get("transport") == "deepseek_harness_native"
            or task["payload"]
            .get("context", {})
            .get("figure_composition", {})
            .get("native_transport")
            == "deepseek_harness_native"
        ):
            from research_partner.providers.native_figure import recover_candidate

            return recover_candidate(self, task, directory, previous)
        if previous.get("transport") == "app_server_dynamic":
            from research_partner.providers.codex_dynamic import (
                continuity,
                read_snapshot,
            )
            from research_partner.providers.codex_evidence import (
                verified_figure,
                verify_wire,
            )

            continuity(self, task, directory)
            snapshot = read_snapshot(directory, previous)
            proof = verified_figure(self.app, task, snapshot, previous)
            provenance = verify_wire(snapshot, previous)["input_provenance"]
            text = snapshot["final_reply"]
            rejected = directory / "candidate.rejected.json"
            if rejected.exists():
                try:
                    same = digest(
                        json.loads(_controlled_file(directory, rejected, 131072))
                    ) == digest(json.loads(text))
                except ValueError:
                    return None
                if same:
                    return None
            recovered = {
                "transport": "app_server_dynamic",
                "task_id": task["id"],
                "session_id": previous["session_id"],
                "native_turn_id": previous["native_turn_id"],
                "reply_sha256": previous["reply_sha256"],
                "composition_candidate": proof,
                "selection": "verified_native_completed_turn",
            }
            return {
                "text": text,
                "receipt": {
                    **previous,
                    "candidate": recovered,
                    "input_provenance": provenance,
                    "recovered_registered_candidate": True,
                    "new_model_requests": 0,
                },
            }
        if previous.get("route") == "codex":
            from research_partner.execution.cli_recovery import recover

            return recover(self, task, directory, previous)
        if previous.get("route") != "deepseek_harness":
            return None
        if getattr(self.app, "store", None):
            self.assert_dispatch_continuity(task, directory)
        receipt = _native_checkpoint(directory / "instance")
        require(
            receipt.get("session_identity_confirmed")
            and receipt.get("session_id") == previous.get("session_id"),
            "候选恢复会话身份不一致",
            "candidate_checkpoint_invalid",
            409,
        )
        if (
            receipt.get("phase") != "flushed"
            or not isinstance(receipt.get("reason"), dict)
            or receipt["reason"].get("kind") != "completed"
        ):
            return None
        result = _native_candidate(task, directory, receipt)
        if result:
            rejected = directory / "candidate.rejected.json"
            if rejected.exists():
                try:
                    same = digest(
                        json.loads(_controlled_file(directory, rejected, 131072))
                    ) == digest(json.loads(result["text"]))
                except ValueError:
                    raise Problem(
                        "被拒候选检查点损坏", "candidate_checkpoint_invalid", 409
                    )
                if same:
                    return None
            result["receipt"]["recovered_registered_candidate"] = True
            result["receipt"]["new_model_requests"] = 0
        return result

    def assert_dispatch_continuity(self, task, directory):
        """A migrated database still proves prior dispatch when files are gone.

        Run before reserving a further invocation. Credentials are not recovery
        evidence; rebinding them cannot authorize a fresh native session for an
        old task or replace its original request ledger.
        """
        config = self.app.config.get("providers", {}).get(
            task["payload"].get("provider_id"), {}
        )
        if (
            config.get("transport") == "app_server_dynamic"
            or task["payload"]
            .get("context", {})
            .get("figure_composition", {})
            .get("native_transport")
            == "app_server_dynamic"
        ):
            require_codex_dynamic_available()
        if (
            config.get("transport") == "deepseek_harness_native"
            or task["payload"]
            .get("context", {})
            .get("figure_composition", {})
            .get("native_transport")
            == "deepseek_harness_native"
        ):
            from research_partner.providers.native_figure import dispatch_continuity

            return dispatch_continuity(self, task, directory, config)
        if (
            config.get("transport") == "app_server_dynamic"
            or task["payload"]
            .get("context", {})
            .get("figure_composition", {})
            .get("native_transport")
            == "app_server_dynamic"
        ):
            from research_partner.providers.codex_configuration import guard

            guard(task, config)
            prior = self.app.store.setting("codex_launch_intent:" + task["id"])
            if prior:
                from research_partner.providers.codex_dynamic import continuity

                continuity(self, task, directory)
                raise Problem(
                    "已有原生turn仅可读回；本协议尚不支持显式接续，未新增调用",
                    "provider_checkpoint_missing",
                    503,
                )
        if task["payload"].get("cycle_parent"):
            require(
                config.get("route") == task["payload"].get("cycle_provider_route"),
                "协作执行路线与冻结分配不一致；未变更预算口径或分派",
                "authorization_required",
                403,
            )
        if config.get("route") == "codex":
            return self.assert_codex_continuity(task, directory)
        if config.get("route") != "deepseek_harness":
            return None
        store = self.app.store
        previous = store.task(task["id"])
        model = next(
            (step for step in previous["steps"] if step["step_key"] == "model"), None
        )
        calls = store.setting("provider_invocations:" + task["id"], 0)
        continuity = (model["data"].get("dispatch_continuity") or {}) if model else {}
        # Migrate trusted Store evidence BEFORE any private-file check can fail
        # and Runtime replaces error details or the next model step.
        records = [
            previous.get("result", {}).get("provider"),
            previous.get("result", {}).get("details", {}).get("provider_checkpoint"),
            model["data"].get("provider") if model else None,
        ]
        if isinstance(continuity.get("native_usage_snapshot"), dict):
            records.append(
                {
                    "usage": continuity["native_usage_snapshot"],
                    "session_id": continuity.get("session_id"),
                }
            )
        for record in records:
            if isinstance(record, dict) and isinstance(record.get("usage"), dict):
                _remember_native_usage(
                    store, task["id"], record["usage"], record.get("session_id")
                )
        anchor = store.setting("native_usage_anchor:" + task["id"])
        if not calls and not model and not anchor:
            return {"requires_checkpoint": False, "reason": "no prior dispatch"}
        directory = Path(directory)
        instance = directory / "instance"
        prior = _native_checkpoint(instance)
        # A guarded attempt that failed before any launch intent is a proven
        # preparation failure, not an unknown native request. Legacy records
        # lack that proof and therefore require their private checkpoint.
        guarded = (
            model
            and model["data"].get("dispatch_guard_version") == 1
            and model["data"].get("provider_route") == "deepseek_harness"
            and (model["data"].get("dispatch_continuity") or {}).get(
                "requires_checkpoint"
            )
            is False
        )
        intent = store.setting("native_launch_intent:" + task["id"])
        if (
            guarded
            and not anchor
            and not intent
            and not prior["native_run_directories"]
            and not prior.get("recovery_errors")
        ):
            usage = prior.get("usage")
            if usage is None or not usage.get("calls"):
                return {
                    "requires_checkpoint": False,
                    "reason": "guarded preparation did not launch",
                }
        require(
            prior.get("session_identity_confirmed")
            and isinstance(prior.get("usage"), dict),
            "旧任务缺少原生会话或用量检查点；请恢复私有执行材料。重绑凭据不会新建会话或重置预算。",
            "provider_checkpoint_missing",
            503,
            {
                "task_id": task["id"],
                "checkpoint_required": True,
                "new_model_requests": 0,
            },
        )
        saved = directory / "provider-receipt.json"
        if saved.exists():
            receipt, error = _native_json(saved, directory)
            require(
                not error
                and isinstance(receipt, dict)
                and receipt.get("session_id") == prior["session_id"],
                "旧任务回执与原生会话身份不一致；未分派",
                "provider_checkpoint_missing",
                503,
            )
        require(
            (instance / "control/authorization.json").is_file()
            and (directory / "capsule/task.json").is_file(),
            "旧任务私有授权或任务合同检查点缺失；未分派",
            "provider_checkpoint_missing",
            503,
        )
        try:
            contract_bytes = _controlled_file(
                directory, directory / "capsule/task.json", 131072
            )
            contract = json.loads(contract_bytes)
            contract_hash = digest(contract_bytes)
            authorization_bytes = _controlled_file(
                directory, instance / "control/authorization.json", 131072
            )
            authorization = json.loads(authorization_bytes)
            evidence_bytes = _controlled_file(
                directory, directory / "evidence.json", 131072
            )
            usage_bytes = _controlled_file(directory, instance / "control/usage.json")
            require(
                json.loads(usage_bytes) == prior["usage"],
                "原生账本在检查期间改变；未分派",
                "provider_checkpoint_missing",
                503,
            )
            require(
                isinstance(contract, dict)
                and contract.get("task_id") == task["id"].lower()
                and contract.get("objective") == task["payload"]["request"]
                and contract.get("context") == task["payload"]["context"],
                "旧合同不属于当前任务或冻结研究目标",
                "provider_checkpoint_missing",
                503,
            )
            require(
                prior["usage"].get("contract_sha256") == contract_hash
                and isinstance(authorization, dict)
                and authorization.get("contract_sha256") == contract_hash,
                "旧合同、原生用量和授权检查点不一致",
                "provider_checkpoint_missing",
                503,
            )
            require(
                type(authorization.get("max_requests")) is int
                and 0
                <= authorization["max_requests"]
                <= task["payload"]["budget"]["max_model_calls"],
                "旧授权的原生请求额度与当前任务上限不一致",
                "provider_checkpoint_missing",
                503,
            )
            from research_partner.execution.evidence import verify_evidence_layout

            verify_evidence_layout(
                contract,
                evidence_bytes,
                lambda relative: _controlled_file(
                    directory, directory / "capsule" / relative, 131072
                ),
            )
            bound_hash = (intent or {}).get("contract_sha256")
            if bound_hash:
                require(
                    bound_hash == contract_hash,
                    "旧分派合同登记与当前文件不一致",
                    "provider_checkpoint_missing",
                    503,
                )
            checkpoint_hash = (
                (model["data"].get("dispatch_continuity") or {}).get("contract_sha256")
                if model
                else None
            )
            if checkpoint_hash:
                require(
                    checkpoint_hash == contract_hash,
                    "旧执行合同身份已变化",
                    "provider_checkpoint_missing",
                    503,
                )
            snapshots = [anchor["usage"]] if anchor else []
            require(
                not anchor
                or not anchor.get("session_id")
                or anchor["session_id"] == prior["session_id"],
                "原生预算锚点会话身份改变；未分派",
                "provider_checkpoint_missing",
                503,
            )
            for snapshot in snapshots:
                require(
                    _usage_extends(prior["usage"], snapshot),
                    "原生预算账本短于或不同于数据库已见预留；未重置或分派",
                    "provider_checkpoint_missing",
                    503,
                )
            old_usage_hash = continuity.get("usage_sha256")
            require(
                not old_usage_hash
                or old_usage_hash == digest(usage_bytes)
                or bool(snapshots),
                "历史预算哈希变化且缺少可核对的单调预留快照；请恢复原检查点",
                "provider_checkpoint_missing",
                503,
            )
        except (ValueError, OSError, Problem) as error:
            if (
                isinstance(error, Problem)
                and error.code == "provider_checkpoint_missing"
            ):
                raise
            raise Problem(
                "旧任务合同或材料检查点无法验证；未新增预算或分派",
                "provider_checkpoint_missing",
                503,
            ) from error
        _remember_native_usage(store, task["id"], prior["usage"], prior["session_id"])
        return {
            "requires_checkpoint": True,
            "session_id": prior["session_id"],
            "contract_sha256": contract_hash,
            "evidence_sha256": digest(evidence_bytes),
            "usage_sha256": digest(usage_bytes),
            "native_usage_snapshot": prior["usage"],
            "authorization_sha256": digest(authorization_bytes),
        }

    def _codex_contract(self, task, directory):
        evidence = _controlled_file(directory, Path(directory) / "evidence.json")
        return {
            "version": 1,
            "route": "codex",
            "task_id": task["id"],
            "provider_id": task["payload"].get("provider_id"),
            "project_id": task["payload"]["project_id"],
            "objective": task["payload"]["request"],
            "context": task["payload"]["context"],
            "budget": task["payload"]["budget"],
            "evidence_sha256": digest(evidence),
        }

    def assert_codex_continuity(self, task, directory):
        """Bind a CLI thread.started event to this task before spending again.

        A receipt or CLI session ID alone cannot establish task ownership. The
        durable database binding survives ordinary workspace backup even though
        private execution files do not. Missing legacy bindings fail closed.
        """
        store = self.app.store
        directory = Path(directory)
        ident = task["id"]
        previous = store.task(ident)
        model = next(
            (step for step in previous["steps"] if step["step_key"] == "model"), None
        )
        calls = store.setting("provider_invocations:" + ident, 0)
        intent = store.setting("codex_launch_intent:" + ident)
        checkpoint = store.setting("codex_checkpoint:" + ident)
        if (
            isinstance(intent, dict) and intent.get("transport") == "app_server_dynamic"
        ) or (
            isinstance(checkpoint, dict)
            and checkpoint.get("transport") == "app_server_dynamic"
        ):
            from research_partner.providers.codex_dynamic import continuity

            return continuity(self, task, directory)
        artifacts = any(
            (directory / name).exists()
            for name in ["provider-receipt.json", "codex-attempt.json"]
        ) or any(directory.glob("codex-events-*.json"))
        guarded = (
            model
            and model["data"].get("dispatch_guard_version") == 1
            and model["data"].get("provider_route") == "codex"
            and (model["data"].get("dispatch_continuity") or {}).get(
                "requires_checkpoint"
            )
            is False
        )
        if not intent and not checkpoint and not artifacts:
            if not calls and not model:
                return {"requires_checkpoint": False, "reason": "no prior dispatch"}
            if guarded:
                return {
                    "requires_checkpoint": False,
                    "reason": "guarded preparation did not launch",
                }
        message = "旧 Codex 任务缺少可验证的同任务会话检查点；请恢复私有执行材料。重绑凭据不会新建会话或重置预算。"
        try:
            require(
                isinstance(checkpoint, dict) and isinstance(intent, dict),
                message,
                "provider_checkpoint_missing",
                503,
            )
            expected = self._codex_contract(task, directory)
            raw = _controlled_file(directory, directory / "codex-contract.json", 131072)
            contract = json.loads(raw)
            contract_hash = digest(raw)
            require(
                contract == expected
                and checkpoint.get("contract_sha256") == contract_hash
                and intent.get("contract_sha256") == contract_hash,
                "Codex 合同与当前任务或数据库分派绑定不一致",
                "provider_checkpoint_missing",
                503,
            )
            for record in [checkpoint, intent]:
                require(
                    record.get("version") == 1
                    and record.get("task_id") == ident
                    and record.get("route") == "codex"
                    and record.get("provider_id") == task["payload"].get("provider_id")
                    and record.get("evidence_sha256") == expected["evidence_sha256"],
                    "Codex 检查点属于其他任务或材料",
                    "provider_checkpoint_missing",
                    503,
                )
            session = checkpoint.get("session_id")
            require(
                isinstance(session, str)
                and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", session)
                and not intent.get("identity_error"),
                "Codex 会话身份缺失或矛盾",
                "provider_checkpoint_missing",
                503,
            )
            attempt_id = checkpoint.get("attempt_id")
            require(
                isinstance(attempt_id, str)
                and re.fullmatch(r"[a-f0-9]{24}", attempt_id),
                message,
                "provider_checkpoint_missing",
                503,
            )
            receipt_bytes = _controlled_file(
                directory, directory / ("codex-receipt-" + attempt_id + ".json"), 131072
            )
            require(
                digest(receipt_bytes) == checkpoint.get("receipt_sha256")
                and _controlled_file(
                    directory, directory / "provider-receipt.json", 131072
                )
                == receipt_bytes,
                "Codex 回执被替换或缺失",
                "provider_checkpoint_missing",
                503,
            )
            receipt = json.loads(receipt_bytes)
            event_bytes = _controlled_file(
                directory, directory / ("codex-events-" + attempt_id + ".json")
            )
            events = json.loads(event_bytes)
            starts = (
                [
                    e.get("thread_id")
                    for e in events
                    if isinstance(e, dict) and e.get("type") == "thread.started"
                ]
                if isinstance(events, list)
                else []
            )
            require(
                starts == [session]
                and digest(event_bytes) == checkpoint.get("events_sha256")
                and receipt.get("events_sha256") == checkpoint["events_sha256"]
                and receipt.get("session_id") == session
                and receipt.get("session_identity_confirmed") is True
                and receipt.get("contract_sha256") == contract_hash
                and receipt.get("task_id") == ident
                and receipt.get("attempt_id") == attempt_id
                and receipt.get("invocation") == checkpoint.get("invocation")
                and type(checkpoint.get("invocation")) is int
                and 0 < checkpoint["invocation"] <= calls,
                "Codex thread.started 事件、回执和任务登记不一致",
                "provider_checkpoint_missing",
                503,
            )
            require(
                intent.get("attempt_id") == attempt_id
                or intent.get("resume_session") == session,
                "后续 Codex 分派未绑定原会话",
                "provider_checkpoint_missing",
                503,
            )
            return {
                "requires_checkpoint": True,
                "session_id": session,
                "contract_sha256": contract_hash,
                "evidence_sha256": expected["evidence_sha256"],
                "receipt_sha256": checkpoint["receipt_sha256"],
                "events_sha256": checkpoint["events_sha256"],
                "attempt_id": attempt_id,
            }
        except (OSError, ValueError, TypeError, KeyError, Problem) as error:
            if (
                isinstance(error, Problem)
                and error.code == "provider_checkpoint_missing"
            ):
                raise
            raise Problem(
                message,
                "provider_checkpoint_missing",
                503,
                {
                    "task_id": ident,
                    "checkpoint_required": True,
                    "new_model_requests": 0,
                },
            ) from error

    def interrupted_cli_receipt(self, task, directory):
        """Read ended CLI timing even when no native session was identified.

        This settles an invocation, never creates a continuity checkpoint or
        proves an API request count. An absent/uncertain process exit keeps the
        reservation. Native transports retain their own terminal proof rules.
        """
        from datetime import datetime

        directory = Path(directory)
        ident = task["id"]
        store = self.app.store
        intent = store.setting("codex_launch_intent:" + ident)
        if not isinstance(intent, dict) or intent.get("transport") is not None:
            return None
        try:
            attempt = intent.get("attempt_id")
            require(
                isinstance(attempt, str) and re.fullmatch(r"[a-f0-9]{24}", attempt),
                "无效调用身份",
            )
            receipt = json.loads(
                _controlled_file(
                    directory,
                    directory / ("codex-receipt-" + attempt + ".json"),
                    131072,
                )
            )
            require(
                isinstance(receipt, dict)
                and type(receipt.get("invocation")) is int
                and isinstance(task.get("execution_token"), str)
                and bool(task["execution_token"]),
                "缺少原执行归属",
            )
            contract = _controlled_file(
                directory, directory / "codex-contract.json", 131072
            )
            events = _controlled_file(
                directory, directory / ("codex-events-" + attempt + ".json")
            )
            require(
                json.loads(contract) == self._codex_contract(task, directory),
                "调用合同不一致",
            )
            require(
                all(
                    receipt.get(key) == intent.get(key)
                    for key in (
                        "task_id",
                        "attempt_id",
                        "invocation",
                        "route",
                        "contract_sha256",
                    )
                )
                and receipt.get("task_id") == ident
                and receipt.get("route") == "codex"
                and receipt.get("transport") is None
                and receipt.get("invocation")
                == store.setting("provider_invocations:" + ident)
                and intent.get("execution_token") == task.get("execution_token")
                and receipt.get("contract_sha256") == digest(contract)
                and receipt.get("events_sha256") == digest(events),
                "调用回执不一致",
            )
            parsed = json.loads(events)
            require(
                isinstance(parsed, list) and len(parsed) == receipt.get("event_count"),
                "事件回执不一致",
            )
            start = datetime.fromisoformat(receipt["started_at"])
            end = datetime.fromisoformat(receipt["finished_at"])
            require(
                start.tzinfo is not None and end.tzinfo is not None and end >= start,
                "执行时间未知",
            )
            matches = []
            for path in directory.glob("process-*.finished.json"):
                finished = json.loads(_controlled_file(directory, path, 131072))
                require(isinstance(finished, dict), "无效进程结束记录")
                if (
                    finished.get("task_id") != ident
                    or finished.get("execution_token") != intent.get("execution_token")
                    or str(directory / ("reply-" + attempt + ".txt"))
                    not in finished.get("argv", [])
                ):
                    continue
                original = json.loads(
                    _controlled_file(
                        directory,
                        path.with_name(path.name.replace(".finished.", ".started.")),
                        131072,
                    )
                )
                require(isinstance(original, dict), "无效进程启动记录")
                require(
                    all(
                        finished.get(key) == value
                        for key, value in original.items()
                        if key != "state"
                    ),
                    "结束进程与启动身份不一致",
                )
                require(
                    finished.get("state") == "finished"
                    and type(finished.get("returncode")) is int
                    and finished.get("cwd") == str(directory)
                    and not finished.get("deadline_stop_errors")
                    and start
                    <= datetime.fromisoformat(finished["started_at"])
                    <= datetime.fromisoformat(finished["finished_at"])
                    <= end,
                    "进程未确认结束",
                )
                matches.append(finished)
            require(len(matches) == 1, "没有唯一已结束的本次CLI进程")
            return receipt
        except (OSError, ValueError, TypeError, KeyError, Problem):
            return None

    def call(self, task, prompt, directory, run_process, resume=None):
        config = self.app.config.get("providers", {}).get(
            task["payload"].get("provider_id")
        )
        require(config, "没有配置所选模型路线", "provider_missing", 503)
        if (
            config.get("transport") == "app_server_dynamic"
            or task["payload"]
            .get("context", {})
            .get("figure_composition", {})
            .get("native_transport")
            == "app_server_dynamic"
        ):
            require_codex_dynamic_available()
        require(
            config.get("authorized"),
            "该模型路线尚未获准执行",
            "authorization_required",
            403,
        )
        route = config.get("route")
        if (
            config.get("transport") == "deepseek_harness_native"
            or task["payload"]
            .get("context", {})
            .get("figure_composition", {})
            .get("native_transport")
            == "deepseek_harness_native"
        ):
            from research_partner.providers.native_figure import call

            return call(self, config, task, prompt, directory, run_process, resume)
        if config.get("transport") == "app_server_dynamic":
            from research_partner.providers.codex_dynamic import call

            return call(self, config, task, prompt, directory, resume)
        if route == "codex":
            return self.codex(config, task, prompt, directory, run_process, resume)
        if route == "deepseek_harness":
            return self.deepseek(config, task, prompt, directory, run_process, resume)
        raise Problem("模型适配路线尚未安装", "provider_missing", 503)

    def codex(self, config, task, prompt, directory, run_process, resume):
        executable = shutil.which(config.get("executable", "codex"))
        require(executable, "Codex执行器不存在", "provider_missing", 503)
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        continuity = self.assert_codex_continuity(task, directory)
        verified_resume = continuity.get("session_id")
        require(
            resume == verified_resume,
            "Codex 接续参数未匹配当前任务检查点",
            "provider_checkpoint_missing",
            503,
        )
        if not (directory / ".git").exists():
            subprocess.run(["git", "init", "-q", str(directory)], check=True)
        domain = task["payload"]["kind"] == "figure_composition"
        policy = "This is a bounded research capsule. Read only supplied evidence. No direct network, installation, new neural fitting, direct external mutation, private credential access or direct work outside this capsule. Candidate output is not scientific approval. Follow the task contract and preserve uncertainty.\n"
        if domain:
            policy += "Only the two explicitly configured project/task-scoped MCP figure tools may read the frozen source revisions and save the exact unadopted main-figure candidate. No shell, source execution, adoption, annotation edits or additional tasks.\n"
        (directory / "AGENTS.md").write_text(policy)
        attempt_id = os.urandom(12).hex()
        reply = directory / ("reply-" + attempt_id + ".txt")
        command = [
            executable,
            "exec",
            "--sandbox",
            "workspace-write",
            "-c",
            'web_search="disabled"',
            "-c",
            "model_reasoning_effort="
            + json.dumps(config.get("reasoning_effort", "medium")),
        ]
        disabled = [
            "shell_tool",
            "apps",
            "multi_agent",
            "browser_use",
            "browser_use_external",
            "in_app_browser",
            "computer_use",
            "hooks",
            "image_generation",
            "workspace_dependencies",
            "skill_search",
        ]
        for feature in disabled:
            command += ["--disable", feature]
        # Per-process overrides only; the user's global configuration is read,
        # never rewritten. Research replies need supplied text, not host tools.
        config_path = (
            Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
            / "config.toml"
        )
        if config_path.exists():
            local = tomllib.loads(config_path.read_text())
            for name in local.get("mcp_servers", {}):
                require(
                    re.fullmatch(r"[A-Za-z0-9_-]+", name),
                    "MCP配置名无法安全转换为此版本CLI参数",
                    "provider_missing",
                    503,
                )
                command += ["-c", "mcp_servers." + name + ".enabled=false"]
            if domain:
                for name in local.get("plugins", {}):
                    command += ["-c", "plugins." + json.dumps(name) + ".enabled=false"]
        if config.get("model"):
            command += ["--model", config["model"]]
        if resume:
            command += ["resume", "--json", "-o", str(reply), resume, "-"]
        else:
            command += ["--json", "-C", str(directory), "-o", str(reply), "-"]
        if resume and not domain:
            # A thread.started receipt proves session identity, not that the
            # interrupted turn consumed its input. Keep Runtime's complete,
            # already-frozen prompt, including the original request, targets,
            # materials and scoped guidance, on every explicit continuation.
            prompt = (
                "Continue the same unfinished task in this session. "
                "The previous call may have stopped before you received its materials. "
                "The complete authorized request and frozen materials are supplied below again; "
                "use them to finish the required JSON candidate. "
                "Do not fetch newer sources, repeat completed external work, expand permissions "
                "or perform new computations. Preserve stable IDs and untargeted user content.\n\n"
                + prompt
            )
        if not domain:
            # The CLI captures its final response using -o. Native Harness tool
            # registration belongs to that adapter, not the shared content schema.
            prompt += (
                "\nOUTPUT DELIVERY FOR THIS CLI CALL:\n"
                "Return the required JSON object as your final response, without a Markdown fence. "
                "The CLI captures that final response and the product validates it before registering a candidate. "
                "Do not call write_candidate: that tool is not available in this CLI route. "
                "Do not create or edit a local candidate copy or other files. "
                "Registration does not adopt the candidate or grant scientific approval.\n"
            )
        store = self.app.store
        ident = task["id"]
        contract_path = directory / "codex-contract.json"
        if not continuity["requires_checkpoint"]:
            _native_write(contract_path, self._codex_contract(task, directory))
        contract_hash = digest(_controlled_file(directory, contract_path, 131072))
        invocation = store.setting("provider_invocations:" + ident, 0)
        intent = {
            "version": 1,
            "route": "codex",
            "task_id": ident,
            "provider_id": task["payload"].get("provider_id"),
            "contract_sha256": contract_hash,
            "evidence_sha256": self._codex_contract(task, directory)["evidence_sha256"],
            "attempt_id": attempt_id,
            "invocation": invocation,
            "resume_session": resume,
            "execution_token": task.get("execution_token"),
            "started_at": now(),
        }
        # This write precedes the process boundary, survives database backup,
        # and does not claim that a request or a native session was created.
        store.set_setting(
            "codex_launch_intent:" + ident,
            intent,
            task_id=ident,
            execution_token=task.get("execution_token"),
        )
        _native_write(directory / "codex-attempt.json", intent)
        before_logs = {p.name for p in directory.glob("process-*.stdout")}
        interrupted = None
        try:
            from research_partner.domains.figures.composition import transport

            with (
                transport(self.app, task, directory)
                if domain
                else contextlib.nullcontext(None)
            ) as mcp:
                if mcp:
                    options = []
                    for key, value in mcp.items():
                        options += [
                            "-c",
                            "mcp_servers.rp_figure_candidate."
                            + key
                            + "="
                            + json.dumps(value),
                        ]
                    index = command.index("--json")
                    command[index:index] = options
                result = run_process(
                    command, directory, prompt, restricted_environment()
                )
        except Problem as exc:
            interrupted = exc
            logs = [
                p
                for p in directory.glob("process-*.stdout")
                if p.name not in before_logs
            ]
            # A previous attempt's newest log cannot prove the current session.
            result = {
                "stdout": logs[0].read_text(errors="replace") if len(logs) == 1 else "",
                "returncode": None,
                "started_at": intent["started_at"],
            }
        usage = []
        events = []
        for line in result["stdout"].splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            events.append(event)
            if event.get("usage"):
                usage.append(event["usage"])
        starts = [
            e.get("thread_id") for e in events if e.get("type") == "thread.started"
        ]
        session = (
            starts[0]
            if len(starts) == 1
            and isinstance(starts[0], str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,160}", starts[0])
            else None
        )
        confirmed = bool(session and (resume is None or session == resume))
        events_path = directory / ("codex-events-" + attempt_id + ".json")
        _native_write(events_path, events)
        receipt = {
            "route": "codex",
            "session_id": session,
            "resumed_from": resume,
            "returncode": result["returncode"],
            "usage": usage,
            "model": config.get("model", "local CLI configured default"),
            "started_at": result["started_at"],
            "finished_at": now(),
            "actual_bill_usd": None,
            "event_count": len(events),
            "host_tools_disabled": disabled,
            "mcp_servers_disabled_for_this_call": not domain,
            "scoped_domain_tools": ["read_figure_context", "create_main_figure"]
            if domain
            else [],
            "budget_unit": "CLI invocations; internal API request count unavailable",
            "version": 1,
            "task_id": ident,
            "contract_sha256": contract_hash,
            "attempt_id": attempt_id,
            "invocation": invocation,
            "events_sha256": digest(events_path.read_bytes()),
            "session_identity_confirmed": confirmed,
        }
        receipt_path = directory / ("codex-receipt-" + attempt_id + ".json")
        _native_write(receipt_path, receipt)
        if confirmed or starts:
            # Recording the result of an already owned process remains valid
            # after pause revokes its lease. This is evidence, not publication
            # or permission to run again. A later attempt's intent fences it.
            with store.transaction() as connection:
                row = connection.execute(
                    "SELECT value FROM kv WHERE key=?",
                    ("codex_launch_intent:" + ident,),
                ).fetchone()
                require(
                    row and json.loads(row[0]) == intent,
                    "较新 Codex 分派已取代本轮；旧回执保留为独立文件",
                    "provider_checkpoint_missing",
                    503,
                )
                if confirmed:
                    _native_write(directory / "provider-receipt.json", receipt)
                    checkpoint = {
                        **intent,
                        "session_id": session,
                        "events_sha256": receipt["events_sha256"],
                        "receipt_sha256": digest(receipt_path.read_bytes()),
                    }
                    connection.execute(
                        "INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        ("codex_checkpoint:" + ident, json.dumps(checkpoint)),
                    )
                    store.event(
                        connection,
                        "provider.checkpoint",
                        ident,
                        {
                            "route": "codex",
                            "attempt_id": attempt_id,
                            "session_id": session,
                            "lease_may_be_revoked": True,
                            "new_dispatch_authorized": False,
                        },
                        "runtime",
                    )
                else:
                    connection.execute(
                        "UPDATE kv SET value=? WHERE key=?",
                        (
                            json.dumps({**intent, "identity_error": True}),
                            "codex_launch_intent:" + ident,
                        ),
                    )
        if interrupted:
            interrupted.details.update(
                {
                    "provider_checkpoint": receipt,
                    "resume_requires_explicit_task_control": True,
                }
            )
            raise interrupted
        require(
            confirmed,
            "Codex 未返回与原会话一致的 thread.started 回执；保留检查点，禁止冷启动",
            "provider_checkpoint_missing",
            503,
            {"provider_checkpoint": receipt},
        )
        require(
            result["returncode"] == 0 and reply.is_file() and reply.stat().st_size > 0,
            "Codex未产生成功候选；查看任务证据",
            "provider_failed",
            503,
            receipt,
        )
        return {"text": reply.read_text(), "receipt": receipt}

    def deepseek(self, config, task, prompt, directory, run_process, resume):
        pin = config.get("expected_lock_sha256")
        if pin is not None:
            require(
                isinstance(pin, str) and re.fullmatch(r"[a-f0-9]{64}", pin),
                "Harness 固定版本配置无效",
                "provider_missing",
                503,
            )
            lock = Path(config["runtime"]) / "app/package-lock.json"
            require(
                lock.is_file()
                and not lock.is_symlink()
                and lock.stat().st_size <= 8 * 1024 * 1024
                and digest(lock.read_bytes()) == pin,
                "Harness 依赖锁与已验证版本不符；保留任务检查点，禁止自动替换或重装",
                "provider_missing",
                503,
            )
        from research_partner.execution.prepare import prepare

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        capsule = directory / "capsule"
        instance = directory / "instance"
        require(
            not resume or instance.exists(),
            "接续所需的原生实例缺失；未新建会话",
            "provider_session_unknown",
            409,
        )
        attemptfile = directory / "native-attempt.json"
        previous_attempt, error = (
            _native_json(attemptfile) if attemptfile.exists() else (None, None)
        )
        require(
            not error
            and (
                not attemptfile.exists()
                or (
                    isinstance(previous_attempt, dict)
                    and type(previous_attempt.get("attempt")) is int
                    and previous_attempt["attempt"] > 0
                )
            ),
            "原生分派检查点无法读取；未新建会话",
            "provider_session_unknown",
            409,
        )
        prior = _native_checkpoint(instance)
        require(
            not resume
            or (prior["session_identity_confirmed"] and resume == prior["session_id"]),
            "接续会话缺少匹配的原生回执；未新建或推断会话",
            "provider_session_unknown",
            409,
            {"provider_checkpoint": prior},
        )
        attempted = bool(
            attemptfile.exists()
            or prior["native_run_directories"]
            or (instance / "control/usage.json").exists()
            or prior["recovery_errors"]
        )
        if attempted:
            _native_write(directory / "provider-receipt.json", prior)
            require(
                prior["session_identity_confirmed"],
                "原生执行已尝试分派但会话身份未确认；保留用量，禁止冷启动",
                "provider_session_unknown",
                409,
                {"provider_checkpoint": prior},
            )
            require(
                not resume or resume == prior["session_id"],
                "待接续会话与原生检查点不一致",
                "provider_session_unknown",
                409,
            )
            resume = prior["session_id"]
        cleared_lock = (
            _release_dead_native_lock(instance) if instance.exists() else None
        )
        if not instance.exists():
            from research_partner.execution.evidence import (
                LAYOUT_VERSION,
                evidence_layout,
            )
            from research_partner.packaging.compatibility import require_features

            packet_bytes = _controlled_file(
                directory, directory / "evidence.json", 65536
            )
            entries, files = evidence_layout(
                packet_bytes,
                task["payload"]["request"],
                config.get("disclosure", "authorized_private"),
            )
            if getattr(self.app, "store", None):
                with self.app.store.transaction() as connection:
                    self.app.store.assert_execution(
                        connection, task["id"], task.get("execution_token")
                    )
                    require_features(connection, ["native_source_pages_v1"])
            capsule.mkdir(parents=True, exist_ok=True)
            (capsule / "evidence").mkdir(exist_ok=True)
            for relative, data in files.items():
                (capsule / relative).write_bytes(data)
            contract = {
                "task_id": task["id"].lower(),
                "objective": task["payload"]["request"],
                "context": task["payload"]["context"],
                "acceptance": "Read actual evidence and write candidate.json using write_candidate. Candidate content is the required JSON; no template completion.",
                "evidence_layout_version": LAYOUT_VERSION,
                "packet_sha256": digest(packet_bytes),
                "evidence": entries,
            }
            (capsule / "task.json").write_text(
                json.dumps(contract, ensure_ascii=False, indent=2) + "\n"
            )
            prepare(instance, capsule, Path(config["runtime"]))
            key = Path(config.get("credential_file", ""))
            require(
                key.is_file()
                and not key.is_symlink()
                and not key.stat().st_mode & 0o077,
                "DeepSeek凭据引用不可用或非私有",
                "credentials_unavailable",
                503,
            )
            # Private runtime instance only; backup/distribution explicitly excludes it.
            destination = instance / "control/api-key.txt"
            destination.write_bytes(key.read_bytes())
            destination.chmod(0o600)
            auth = json.loads((instance / "control/authorization.json").read_text())
            auth.update(
                approved=True,
                authorization_reference=config.get(
                    "authorization_reference",
                    "User authorized provider in local config",
                ),
                expires_at=(
                    datetime.now(timezone.utc) + timedelta(hours=2)
                ).isoformat(),
                budget_mode="uncapped",
                budget_usd=None,
                uncapped_spending_authorized=bool(
                    config.get("uncapped_spending_authorized")
                ),
                max_requests=int(task["payload"]["budget"].get("max_model_calls", 4)),
                max_output_tokens=8192,
                disclosure_classes=[config.get("disclosure", "authorized_private")],
                model=config.get("model", "deepseek-flash"),
            )
            if not auth["uncapped_spending_authorized"]:
                require(
                    config.get("budget_usd", 0) > 0,
                    "需要明确付费上限或已有无总额限制授权",
                    "authorization_required",
                    403,
                )
                auth.update(budget_mode="capped", budget_usd=config["budget_usd"])
            (instance / "control/authorization.json").write_text(
                json.dumps(auth, indent=2) + "\n"
            )
            # Fixed explicit route; no silent fallback or unreviewed retry plugin.
            if config.get("model") and config["model"] != "deepseek-flash":
                for p in [
                    instance / "control/profile-base.yml",
                    instance / "home/profiles/acaworker/cordis.patch.yml",
                    instance / "home/profiles/acaworker-headless/cordis.patch.yml",
                ]:
                    p.write_text(
                        p.read_text().replace("deepseek-flash", config["model"])
                    )
        # Native tools expose the same frozen materials once; avoid doubling them
        # inside the prompt and the subsequent evidence read.
        head, _, tail = prompt.partition("\nMATERIALS:\n")
        if "\nCOORDINATOR GUIDANCE" in tail:
            head += (
                "\nCOORDINATOR GUIDANCE" + tail.split("\nCOORDINATOR GUIDANCE", 1)[1]
            )
        if resume:
            guidance = head.partition("\nCOORDINATOR GUIDANCE")[2]
            from research_partner.domains.collaboration.commission import (
                candidate_schema,
            )

            schema = candidate_schema(
                task["payload"].get("context", {}).get("output", "report"), task
            )
            head = (
                "Continue this same interrupted task in its existing native session and remaining budget. Reuse the frozen evidence already read; do not restart the task or duplicate completed work. Finish the requested JSON candidate using write_candidate. Keep the same artifact type, stable IDs and untargeted user content. No new analysis, computation, permissions or source claims.\nREQUIRED OUTPUT SCHEMA:\n"
                + schema
            )
            if guidance:
                head += "\nCOORDINATOR GUIDANCE" + guidance
        contract = json.loads((capsule / "task.json").read_text())
        reading = (
            "Read research_task for the catalog. Read relevant individual source IDs (the actual object IDs), and task-context for any missing frozen instructions. read_evidence returns explicit pages: keep the same ID and use next_offset until complete=true. Cite the actual source IDs/revisions in claims and pass read source IDs to write_candidate. Do not read the duplicate materials bundle if those sources are already complete."
            if contract.get("evidence_layout_version") == 2
            else "Use research_task and read_evidence only as needed for the frozen context/materials and source identity. Save via write_candidate with evidence_ids=['materials']."
        )
        if resume and contract.get("evidence_layout_version") == 2:
            reading = "Reuse sources already read completely in this native session and their evidence IDs. If a required source is not yet complete, read only its remaining pages; do not restart the catalog or duplicate completed reads. Save the requested JSON with write_candidate; task-context/materials are task provenance, not database object identities."
        promptfile = directory / "prompt.txt"
        promptfile.write_text(
            head
            + "\n"
            + reading
            + " Save the scientific candidate with write_candidate before optional observations or handoff preparation. Use candidate.json initially; on revision choose an unused candidate-rN.json name because original outputs cannot be overwritten. The file content must be the requested JSON. Keep the candidate concise enough for one write_candidate call; prioritize the requested question and necessary denominators/limits.\n"
        )
        command = [
            sys.executable,
            str(instance / "launch.py"),
            "--prompt-file",
            str(promptfile),
        ]
        if resume:
            command += ["--resume-session", resume]
        before = [
            path.name for path in (instance / "control/runs").glob("*") if path.is_dir()
        ]
        attempt = {
            "started_at": now(),
            "resume_session": resume,
            "run_dirs_before": before,
            "attempt": int((previous_attempt or {}).get("attempt", 0)) + 1,
        }
        _native_write(attemptfile, attempt)
        launch_intent = {
            "at": now(),
            "resume_session": resume,
            "execution_token": task.get("execution_token"),
            "attempt": attempt["attempt"],
            "contract_sha256": digest(
                _controlled_file(directory, capsule / "task.json", 131072)
            ),
        }
        if getattr(self.app, "store", None):
            self.app.store.set_setting(
                "native_launch_intent:" + task["id"],
                launch_intent,
                task_id=task["id"],
                execution_token=task.get("execution_token"),
            )
        interrupted = None
        try:
            result = run_process(command, directory, None, restricted_environment())
        except Problem as exc:
            interrupted = exc
            result = {"returncode": None, "started_at": attempt["started_at"]}
        receipt = _native_checkpoint(instance, resume, before)
        receipt.update(
            returncode=result["returncode"],
            adapter_started_at=attempt["started_at"],
            adapter_finished_at=now(),
            interrupted=bool(interrupted),
            cleared_dead_launcher_lock=cleared_lock,
        )
        if getattr(self.app, "store", None) and isinstance(receipt.get("usage"), dict):
            store = self.app.store
            with store.transaction() as connection:
                row = connection.execute(
                    "SELECT value FROM kv WHERE key=?",
                    ("native_launch_intent:" + task["id"],),
                ).fetchone()
                require(
                    row and json.loads(row[0]) == launch_intent,
                    "较新原生分派已取代本轮；旧回执不能覆盖预算锚点",
                    "provider_checkpoint_missing",
                    503,
                )
                require(
                    receipt["usage"].get("contract_sha256")
                    == launch_intent["contract_sha256"],
                    "原生返回用量不属于本轮合同",
                    "provider_checkpoint_missing",
                    503,
                )
                _remember_native_usage(
                    store,
                    task["id"],
                    receipt["usage"],
                    receipt.get("session_id"),
                    connection,
                )
        _native_write(directory / "provider-receipt.json", receipt)
        if interrupted:
            interrupted.details.update(
                {
                    "provider_checkpoint": receipt,
                    "resume_requires_explicit_task_control": True,
                }
            )
            raise interrupted
        require(
            receipt["session_identity_confirmed"],
            "原生分派后会话身份未确认；禁止冷启动重试",
            "provider_session_unknown",
            409,
            {"provider_checkpoint": receipt},
        )
        require(
            result["returncode"] == 0,
            "DeepSeek原生执行未完成约定候选",
            "provider_failed",
            503,
            {"provider_checkpoint": receipt},
        )
        candidate = _native_candidate(task, directory, receipt)
        require(
            candidate is not None,
            "本轮原生会话没有成功登记新的 JSON 候选；未采用旧文件",
            "provider_failed",
            503,
            {"provider_checkpoint": receipt},
        )
        _native_write(directory / "provider-receipt.json", candidate["receipt"])
        return candidate
