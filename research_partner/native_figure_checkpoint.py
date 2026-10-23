"""Bounded, read-only snapshots of the fresh figure Harness's durable files.

This reader neither creates/resumes an Agent nor proves provider execution,
current permission, process termination, candidate validity or scientific merit.
It returns exact saved evidence for the owning provider's independent checks.
"""
from __future__ import annotations

import contextlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import stat
import subprocess
import time

from .store import Problem, digest, require

FEATURE = "deepseek_task_figure_tools_v1"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_DECODED_BYTES = 32 * 1024 * 1024
DECODE_SECONDS = 5
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_FILE = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,200}\Z")
_SESSION = re.compile(r"session-[A-Za-z0-9_-]{1,160}\Z")


def _check(condition, message):
    require(condition, message, "candidate_checkpoint_invalid", 409)


def _json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            _check(key not in value, "检查点 JSON 含重复字段")
            value[key] = item
        return value

    def finite(value, depth=0):
        _check(depth <= 64, "检查点 JSON 嵌套超限")
        if isinstance(value, str):
            value.encode("utf-8", errors="strict")
        elif isinstance(value, float):
            _check(math.isfinite(value), "检查点 JSON 数值无效")
        elif isinstance(value, (list, dict)):
            if isinstance(value, dict):
                for key in value:
                    key.encode("utf-8", errors="strict")
            for item in value.values() if isinstance(value, dict) else value:
                finite(item, depth + 1)

    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
        finite(value)
        return value
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Problem("检查点不是完整有限 UTF-8 JSON", "candidate_checkpoint_invalid", 409) from error


@contextlib.contextmanager
def _root(path):
    """Open every absolute ancestor without following a directory symlink."""
    fd = os.open("/", _DIRECTORY)
    try:
        with _directory(fd, path.parts[1:]) as instance:
            yield instance
    finally:
        os.close(fd)


@contextlib.contextmanager
def _directory(root_fd, parts):
    descriptors = [os.dup(root_fd)]
    identities = []
    try:
        for part in parts:
            parent = descriptors[-1]
            child = os.open(part, _DIRECTORY, dir_fd=parent)
            descriptors.append(child)
            original = os.fstat(child)
            identities.append((parent, part, original.st_dev, original.st_ino))
        yield descriptors[-1]
        for parent, part, device, inode in identities:
            current = os.stat(part, dir_fd=parent, follow_symlinks=False)
            _check(stat.S_ISDIR(current.st_mode) and (device, inode) == (current.st_dev, current.st_ino),
                   "原生保存目录在核对期间被替换")
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def _stamp(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


@contextlib.contextmanager
def _file(root_fd, parts):
    with _directory(root_fd, parts[:-1]) as parent:
        fd = os.open(parts[-1], _FILE, dir_fd=parent)
        try:
            before = os.fstat(fd)
            _check(stat.S_ISREG(before.st_mode) and before.st_size <= MAX_FILE_BYTES,
                   "检查点缺失、非普通文件或超过 8MiB")
            raw = bytearray()
            while True:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                raw.extend(chunk)
                _check(len(raw) <= MAX_FILE_BYTES, "检查点超过完整文件界限")
            _check(len(raw) == before.st_size and _stamp(before) == _stamp(os.fstat(fd)),
                   "检查点在读取期间改变")
            yield fd, bytes(raw)
            current = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
            _check(_stamp(before) == _stamp(os.fstat(fd)) == _stamp(current)
                   and stat.S_ISREG(current.st_mode), "检查点在核对期间被替换或改变")
        finally:
            os.close(fd)


def _decode(fd):
    executable = shutil.which("zstd")
    require(executable, "缺少本地 zstd；未调用模型", "candidate_checkpoint_unavailable", 503)
    os.lseek(fd, 0, os.SEEK_SET)
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "LANG", "LC_ALL", "TZ"}}
    process = subprocess.Popen([executable, "-dc", "--memory=32MB"], stdin=fd,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    data = bytearray()
    deadline = time.monotonic() + DECODE_SECONDS
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                _check(time.monotonic() < deadline, "原生完整事件解码超时")
                for key, _ in selector.select(min(.1, max(0, deadline - time.monotonic()))):
                    chunk = os.read(key.fileobj.fileno(), 65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        data.extend(chunk)
                        _check(len(data) <= MAX_DECODED_BYTES, "原生完整事件超过 32MiB")
        _check(process.wait(timeout=max(.01, deadline - time.monotonic())) == 0,
               "原生 Zstd 文件损坏或未完整解码")
    except subprocess.TimeoutExpired as error:
        raise Problem("原生完整事件解码超时", "candidate_checkpoint_invalid", 409) from error
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        process.stdout.close()
    return bytes(data)


def _event_path(root_fd, session):
    matches = []
    with _directory(root_fd, ("home", "sessions")) as home:
        for project in os.listdir(home):
            with _directory(home, (project,)) as folder:
                if session not in os.listdir(folder):
                    continue
                with _directory(folder, (session,)) as saved:
                    names = os.listdir(saved)
                    # The native POSIX writer leaves its regular session.lock
                    # after releasing flock. Its existence says nothing about
                    # a live writer and is not a physical log generation.
                    logs = [n for n in names if n.startswith("session.") and n != "session.lock"]
                    _check(logs == ["session.v3.jsonl.zstd"],
                           "原生格式代次未知、混合或不唯一；不能选择旧 v3")
                matches.append(("home", "sessions", project, session, "session.v3.jsonl.zstd"))
    _check(len(matches) == 1, "原生完整事件文件不能唯一确定")
    return matches[0]


def _binding(value):
    keys = ("task_id", "project_id", "plan_sha256", "egress_sha256",
            "definition_sha256", "contract_sha256", "provider", "model")
    _check(isinstance(value, dict) and all(k in value for k in keys), "缺少明确固定的 Task/profile 身份")
    _check(all(isinstance(value[k], str) and _ID.fullmatch(value[k]) for k in ("task_id", "project_id", "model"))
           and value["provider"] == "deepseek-official"
           and all(isinstance(value[k], str) and _SHA.fullmatch(value[k]) for k in keys if k.endswith("sha256")),
           "固定 Task/profile 身份无效")
    if "session_id" in value:
        _check(isinstance(value["session_id"], str) and _SESSION.fullmatch(value["session_id"]), "固定 session 身份无效")
    return value


@contextlib.contextmanager
def _usage_file(root_fd, incomplete):
    """An interrupted fresh attempt may have no stream reservation yet."""
    with contextlib.ExitStack() as stack:
        try:
            value = stack.enter_context(_file(root_fd, ("control", "usage.json")))
        except FileNotFoundError:
            if not incomplete:
                raise
            value = (None, None)
        yield value


def read_figure_checkpoint(instance, expected_binding, *, allow_missing_usage_for_accounting=False):
    """Return complete saved files and hashes; absent receipt returns ``None``.

    ``expected_binding`` pins task_id/project_id/plan_sha256/egress_sha256,
    definition_sha256/contract_sha256/provider/model; optional session_id must
    also match. Loaded/unknown receipts expose saved evidence only; absent
    usage is None and no attempt range is inferred. Missing/mismatched saved
    logs raise Problem. ``raw_jsonl_utf8`` is the original decoded bytes.
    Accounting inspection may explicitly read a closed turn whose usage file
    is absent. Absence remains None, never an empty invented ledger or proof of
    zero requests. The default candidate-read contract remains strict.
    The caller must independently establish Task authority, native provenance,
    stopped writer, terminal state and a successful candidate before adoption.
    """
    expected = dict(_binding(expected_binding))
    try:
        instance = Path(os.path.abspath(instance))
    except (TypeError, ValueError) as error:
        raise Problem("需要明确原生实例目录", "candidate_checkpoint_invalid", 409) from error
    _check("\x00" not in str(instance), "原生实例目录含非法字符")
    try:
        with _root(instance) as root:
            try:
                with _file(root, ("control", "native-receipt.json")) as (_, raw_receipt):
                    receipt = _json(raw_receipt)
                    _check(isinstance(receipt, dict), "原生回执格式无效")
                    session = receipt.get("session_id")
                    _check(isinstance(session, str) and _SESSION.fullmatch(session)
                           and ("session_id" not in expected or session == expected["session_id"]), "原生 session 身份不匹配")
                    _check(receipt.get("feature") == FEATURE and receipt.get("native_api") == "agents.create"
                           and "resumed_from" in receipt and receipt["resumed_from"] is None
                           and receipt.get("identity_source") == "authoritative_agents_create_return"
                           and receipt.get("phase") in ("loaded", "unknown", "flushed", "checkpoint_flushed")
                           and all(receipt.get(k) == expected[k] for k in ("provider", "model")),
                           "缺少 fresh 原生保存回执；不能推断运行完成")
                    binding = receipt.get("figure_task_binding")
                    _check(isinstance(binding, dict) and binding.get("feature") == FEATURE
                           and binding.get("transport") == "deepseek_harness_native"
                           and binding.get("session_id") == session
                           and all(binding.get(k) == expected[k] for k in
                                   ("task_id", "project_id", "plan_sha256", "egress_sha256", "definition_sha256")),
                           "原生回执不属于固定 Task/profile")
                    proof = binding.get("binding_proof")
                    _check(isinstance(proof, dict) and proof.get("native_api") == "agents.create"
                           and "resumed_from" in proof and proof["resumed_from"] is None
                           and proof.get("identity_source") == "authoritative_host_return_after_agent_created",
                           "缺少 fresh authoritative binding 回执")
                    incomplete = receipt["phase"] in ("loaded", "unknown")
                    with _usage_file(root, incomplete or allow_missing_usage_for_accounting) as (_, raw_usage):
                        usage = _json(raw_usage) if raw_usage is not None else None
                        _check(usage is None and (incomplete or allow_missing_usage_for_accounting) or isinstance(usage, dict)
                               and usage.get("contract_sha256") == expected["contract_sha256"]
                               and isinstance(usage.get("calls"), list)
                               and len(usage["calls"]) <= 4
                               and type(usage.get("reserved_usd")) in (int, float) and usage["reserved_usd"] >= 0
                               and all(isinstance(c, dict) and c.get("session_id") == session
                                       and c.get("model") == expected["model"] for c in usage["calls"]),
                               "原生用量不属于固定合同/session/model")
                        ids = [c.get("id") for c in usage["calls"]] if usage is not None else []
                        _check(all(isinstance(i, str) and i for i in ids) and len(ids) == len(set(ids)),
                               "原生预留 request 身份重复或缺失")
                        relative = _event_path(root, session)
                        with _file(root, relative) as (fd, physical):
                            decoded = _decode(fd)
                            _check(decoded.endswith(b"\n"), "原生 JSONL 缺完整尾行")
                            records = [_json(line) for line in decoded.splitlines()]
                            _check(bool(records), "原生 JSONL 缺头")
                            header, events = records[0], records[1:]
                            _check(isinstance(header, dict) and header.get("type") == "session"
                                   and type(header.get("version")) is int and header["version"] == 3
                                   and header.get("id") == session and header.get("cwd") == str(instance / "capsule"),
                                   "原生日志 version/session/cwd 不匹配")
                            _check(all(isinstance(e, dict) and type(e.get("seq")) is int and e["seq"] == i
                                       and isinstance(e.get("type"), str) and isinstance(e.get("data"), dict)
                                       for i, e in enumerate(events)), "原生事件序列不完整")
                            loaded, first, final = (receipt.get(k) for k in ("loaded_seq", "first_seq", "final_seq"))
                            _check(type(loaded) is int and 0 <= loaded <= len(events), "原生加载事件边界不一致")
                            if incomplete:
                                # Read the complete saved prefix without making
                                # up the unrecorded followup or terminal boundary.
                                attempt_events = None
                            else:
                                _check(all(type(v) is int for v in (first, final))
                                       and loaded <= first < final == len(events), "原生回执与完整事件边界不一致")
                                attempt_events = events[first:final]
                            return {"version": 1, "feature": FEATURE, "instance": str(instance),
                                    "expected_binding": dict(expected), "session_id": session,
                                    "receipt": receipt, "usage": usage, "header": header, "events": events,
                                    "attempt_events": attempt_events, "raw_jsonl_utf8": decoded,
                                    "raw_receipt_utf8": raw_receipt.decode("utf-8"),
                                    "raw_usage_utf8": raw_usage.decode("utf-8") if raw_usage is not None else None,
                                    "receipt_sha256": digest(raw_receipt),
                                    "usage_sha256": digest(raw_usage) if raw_usage is not None else None,
                                    "physical_sha256": digest(physical), "events_sha256": digest(decoded),
                                    "decoded_sha256": digest(decoded),
                                    "physical_bytes": len(physical), "decoded_bytes": len(decoded),
                                    "event_path": str(instance.joinpath(*relative)),
                                    "event_range_verified": not incomplete,
                                    "usage_missing": raw_usage is None,
                                    "read_status": "incomplete_saved_evidence" if incomplete else "saved_evidence",
                                    "native_execution_verified": False, "actual_bill_usd": None,
                                    "process_termination_verified": False}
            except FileNotFoundError:
                # Only absent authoritative receipt means no saved checkpoint;
                # a receipt whose usage/log is missing is incomplete evidence.
                with _directory(root, ("control",)) as control:
                    if "native-receipt.json" not in os.listdir(control):
                        return None
                raise
    except FileNotFoundError as error:
        if not instance.exists():
            return None
        raise Problem("原生保存证据缺失；未验证", "candidate_checkpoint_invalid", 409) from error
    except OSError as error:
        raise Problem("原生保存路径不安全或无法读取", "candidate_checkpoint_invalid", 409) from error
