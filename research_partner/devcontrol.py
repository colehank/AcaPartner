"""Finite development continuation and evidence gate. Linux/POSIX, stdlib only.

This controls development work; it is deliberately separate from the product's
research-agent runner. A successful unit never marks a capability accepted.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import sys
import time
import uuid
from .source_identity import IDENTITY_SCOPE, source_files


SCOPE_SHA256 = "abe9c9fa30f9312f338b926cd49f866cb543ae271971554179c93a561ec0833f"
SCOPE_AMENDMENT_SHA256 = "b90bdb328251484385dc7c358a350f9ad498a2115de8ba2ac57bcc6307ee29a3"
CAPABILITIES = [f"C{i:02d}" for i in range(1, 51)]
SCENARIOS = [f"S{i:02d}" for i in range(1, 25)]
SUBCASES = ["S06:论文", "S06:海报", "S06:PPT与逐页讲稿", "S07:刺激准备",
            "S07:图像与标注清洗", "S07:神经数据预处理", "S07:可视化工具", "S07:实验软件"]
AXES = ("implementation", "engineering", "human")
SCREENSHOTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


class ControlError(RuntimeError):
    pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def identity(pid, include_zombie=False):
    """PID alone is unsafe after reuse. Include boot and /proc start ticks."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z" and not include_zombie:
            return None
        return {"pid": int(pid), "start_ticks": stat[19],
                "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    except (OSError, IndexError, ValueError):
        return None


def alive(owner):
    return bool(owner and identity(owner.get("pid")) == owner)


def terminate_owned(owner):
    # A retained zombie still reserves its PID/session identity. This lets the
    # runner stop descendants before reaping the group leader on normal exit.
    if owner and identity(owner.get("pid"), include_zombie=True) == owner:
        try:
            # Every child is created with start_new_session=True.
            if os.getpgid(owner["pid"]) == owner["pid"]:
                os.killpg(owner["pid"], signal.SIGTERM)
                deadline = time.monotonic() + 0.8
                while alive(owner) and time.monotonic() < deadline:
                    time.sleep(0.02)
                if identity(owner["pid"], include_zombie=True) == owner:
                    os.killpg(owner["pid"], signal.SIGKILL)
        except ProcessLookupError:
            pass


def codex_argv(root, last_message, session_id=None, executable="codex"):
    """Arguments verified against installed `codex exec{, resume} --help`.

    Resume does not accept -C or -s: root is supplied as subprocess cwd;
    sandbox is set on the parent exec command, before resume. Never use --last.
    """
    base = [executable, "exec", "-s", "workspace-write"]
    if session_id:
        return base + ["resume", "--json", "-o", str(last_message), session_id, "-"]
    return base + ["-C", str(root), "--json", "-o", str(last_message), "-"]


class DevelopmentControl:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / "development"
        self.path = self.directory / "state.json"
        self.runtime = self.root / ".runtime" / "development"

    @contextlib.contextmanager
    def transaction(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        with (self.directory / ".state.lock").open("a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(self.path.read_text()) if self.path.exists() else None
            yield state
            if state is not None:
                self._write(state)

    def _write(self, state):
        state["updated_at"] = now()
        temporary = self.path.with_suffix(f".{os.getpid()}.tmp")
        with temporary.open("w") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)
        directory_fd = os.open(self.directory, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    def scope_errors(self):
        errors = []
        path = self.directory / "scope-lock.json"
        if not path.is_file() or sha(path) != SCOPE_SHA256:
            return ["immutable scope lock missing or changed"]
        lock = json.loads(path.read_text())
        expected = dict(lock["package_sha256"])
        amendment = self.directory / "scope-amendments.json"
        if not amendment.is_file() or sha(amendment) != SCOPE_AMENDMENT_SHA256:
            return ["authorized scope amendment missing or changed"]
        changes = json.loads(amendment.read_text())
        if (changes.get("baseline_sha256") != SCOPE_SHA256 or
            changes.get("capability_ids") != lock["capability_ids"] or
            changes.get("scenario_ids") != lock["scenario_ids"] or
            changes.get("required_subcases") != lock["required_subcases"]):
            return ["authorized amendment changed mandatory scope"]
        for name, record in changes["replacements"].items():
            if record.get("previous_sha256") != expected.get(name):
                return ["authorized amendment does not match original baseline"]
            expected[name] = record["sha256"]
        for name, digest in expected.items():
            source = self.root / "docs" / "product" / name
            if not source.is_file() or sha(source) != digest:
                errors.append(f"requirement package changed or missing: {name}")
        return errors

    def source_identity(self):
        # Include consumed strategy text; ordinary evidence/docs remain excluded.
        files = source_files(self.root, development=True)
        digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
        git = {}
        for key, command in (("branch", ["git", "branch", "--show-current"]),
                             ("head", ["git", "rev-parse", "HEAD"])):
            result = subprocess.run(command, cwd=self.root, capture_output=True, text=True)
            git[key] = result.stdout.strip() if result.returncode == 0 else None
        return {"code_digest": digest, "files": files, "identity_scope": IDENTITY_SCOPE, **git}

    def init(self):
        errors = self.scope_errors()
        if errors:
            raise ControlError("; ".join(errors))
        with self.transaction() as existing:
            if existing is not None:
                return copy.deepcopy(existing)
            package = json.loads((self.root / "docs/product/04_全量功能清单.json").read_text())
            def item(title, scenarios):
                return {"title": title, "scenarios": scenarios,
                        **{axis: {"status": "unverified", "evidence": []} for axis in AXES},
                        "blockers": [], "limitations": []}
            state = {"schema": 1, "scope_sha256": SCOPE_SHA256, "created_at": now(),
                     "capabilities": {c["id"]: {**item(c["title"], c["scenarios"]),
                                               "stage": c["stage"]} for c in package["capabilities"]},
                     "scenarios": {s: item(s, [s]) for s in SCENARIOS},
                     "subcases": {s: item(s, [s.split(":")[0]]) for s in SUBCASES},
                     "queue": [], "runs": [], "events": [], "blockers": {},
                     "runner": {"mode": "idle", "owner": None, "child": None,
                                "current_unit": None, "session_id": None,
                                "authorization": None, "stop_requested": False,
                                "budget": {"max_attempts": 0, "used_attempts": 0,
                                           "max_seconds": 0, "used_seconds": 0,
                                           "max_output_bytes": 10485760}},
                     "delivery": {"installation": {"status": "unverified", "evidence": []},
                                  "independent_review": {"status": "unverified", "evidence": []},
                                  "defects": [], "release": {"status": "not_authorized",
                                  "authorization": None, "license_privacy_review": None}},
                     "handoff": "Full scope unverified. Queue bounded, authorized engineering units.",
                     "implementation": self.source_identity()}
            self._write(state)
            return copy.deepcopy(state)

    def read(self):
        if not self.path.exists():
            raise ControlError("Run init before other commands")
        return json.loads(self.path.read_text())

    @staticmethod
    def items(state):
        return {**state.get("capabilities", {}), **state.get("scenarios", {}),
                **state.get("subcases", {})}

    def artifact(self, path, role="output"):
        path = self._path(path)
        return {"path": str(path.relative_to(self.root)), "sha256": sha(path), "role": role}

    def _path(self, value):
        path = (self.root / value).resolve()
        if not path.is_relative_to(self.root):
            raise ControlError("Evidence and output paths must stay within repository")
        return path

    def _artifact_errors(self, artifact):
        try:
            path = self._path(artifact["path"])
            if not path.is_file():
                return [f"missing artifact: {artifact['path']}"]
            if sha(path) != artifact["sha256"]:
                return [f"changed artifact: {artifact['path']}"]
            return []
        except (KeyError, OSError, TypeError, ControlError) as exc:
            return [f"invalid artifact: {exc}"]

    def evidence_errors(self, receipt, axis, source):
        errors = []
        if receipt.get("status") != "passed":
            errors.append("evidence not passed")
        if receipt.get("source", {}).get("code_digest") != source["code_digest"]:
            errors.append("stale implementation evidence")
        if (receipt.get("mock") or receipt.get("synthetic") or receipt.get("skipped")
                or receipt.get("evidence_class") == "fault_injection"):
            errors.append("mock, synthetic or skipped acceptance")
        expected = {"implementation": "code_review", "engineering": "real_execution",
                    "human": "human_confirmation", "review": "independent_review"}[axis]
        if receipt.get("kind") != expected:
            errors.append(f"expected {expected} evidence")
        artifacts = receipt.get("artifacts", [])
        if not artifacts:
            errors.append("no evidence artifacts")
        for artifact in artifacts:
            errors.extend(self._artifact_errors(artifact))
        if artifacts and all(Path(a.get("path", "")).suffix.lower() in SCREENSHOTS for a in artifacts):
            errors.append("screenshot-only evidence")
        if not receipt.get("observed_at") or not receipt.get("actor"):
            errors.append("missing observation identity")
        if axis == "engineering":
            if not receipt.get("entrypoint") or not receipt.get("command"):
                errors.append("missing actual entrypoint/command")
            if not receipt.get("inputs"):
                errors.append("missing actual input identities")
            for value in receipt.get("inputs", []):
                errors.extend(self._artifact_errors(value))
                if value.get("provenance") not in ("authorized_real", "public_real", "source_code"):
                    errors.append("input lacks real provenance")
            if not receipt.get("checks") or not all(c.get("passed") is True and c.get("method")
                                                       for c in receipt.get("checks", [])):
                errors.append("missing or failed postconditions/replay checks")
            if not receipt.get("reopened_or_replayed"):
                errors.append("result not reopened or replayed")
            if not any(a.get("role") == "execution_log" for a in artifacts):
                errors.append("no raw execution log")
            if not any(a.get("role") == "output" for a in artifacts):
                errors.append("no actual output")
            review = receipt.get("independent_review", {})
            if (review.get("status") != "passed" or not review.get("reviewer")
                    or review.get("reviewer") == receipt.get("actor")):
                errors.append("missing independent evidence review")
            errors.extend(self._artifact_errors(review.get("artifact", {})))
        if axis == "human" and receipt.get("actor_type") != "human":
            errors.append("developer/model cannot supply human confirmation")
        if axis == "review" and not receipt.get("independent"):
            errors.append("review is not independent")
        return errors

    def gate(self, state=None):
        # The public gate is observational: report current file drift without
        # mutating a caller's snapshot or the live controller state. The runner
        # persists the same invalidations at its dispatch/commit boundaries.
        state = copy.deepcopy(state or self.read())
        self._revalidate_units(state, record_events=False)
        source = self.source_identity()
        errors = self.scope_errors()
        if state.get("scope_sha256") != SCOPE_SHA256:
            errors.append("state scope identity changed")
        for group, required in (("capabilities", CAPABILITIES), ("scenarios", SCENARIOS),
                                ("subcases", SUBCASES)):
            if set(state.get(group, {})) != set(required):
                errors.append(f"missing/deleted/unrecognized {group}")
        engineering_debt, human_debt = [], []
        for item_id, item in self.items(state).items():
            for axis in AXES:
                value = item.get(axis, {})
                failures = []
                if value.get("status") != "passed":
                    failures.append(f"{axis}: {value.get('status', 'missing')}")
                if not value.get("evidence"):
                    failures.append(f"{axis}: missing evidence")
                for receipt in value.get("evidence", []):
                    failures.extend(f"{axis}: {e}" for e in self.evidence_errors(receipt, axis, source))
                if failures:
                    debt = {"id": item_id, "axis": axis, "reasons": failures,
                            "blockers": item.get("blockers", [])}
                    (human_debt if axis == "human" else engineering_debt).append(debt)
        for key, axis in (("installation", "engineering"), ("independent_review", "review")):
            value = state.get("delivery", {}).get(key, {})
            if value.get("status") != "passed" or not value.get("evidence"):
                engineering_debt.append({"id": key, "reasons": ["not verified"], "blockers": value.get("blockers", [])})
            else:
                for receipt in value["evidence"]:
                    failures = self.evidence_errors(receipt, axis, source)
                    if failures:
                        engineering_debt.append({"id": key, "reasons": failures, "blockers": []})
        for defect in state.get("delivery", {}).get("defects", []):
            if defect.get("status") != "resolved":
                engineering_debt.append({"id": defect.get("id", "defect"),
                                         "reasons": ["unresolved defect"], "blockers": []})
        resolved_units = []
        for unit in state.get("queue", []):
            resolution_errors = self._resolution_errors(state, unit) if unit.get("resolution") else []
            if unit.get("resolution") and not resolution_errors:
                resolved_units.append({"id": unit["id"], "by": unit["resolution"]["by"],
                                       "original_status": unit["status"], "formal_acceptance": False})
            elif unit["status"] != "verified":
                engineering_debt.append({"id": "development:" + unit["id"],
                                         "reasons": resolution_errors or [unit.get("failure") or "development unit " + unit["status"]],
                                         "blockers": unit.get("blockers", [])})
        engineering_ready = not errors and not engineering_debt
        product_accepted = engineering_ready and not human_debt
        runner = state["runner"]
        budget = runner["budget"]
        authorized = bool(runner.get("authorization"))
        exhausted = authorized and (budget["used_attempts"] >= budget["max_attempts"]
                                    or budget["used_seconds"] >= budget["max_seconds"])
        eligible = self._eligible(state)
        debt = engineering_debt if engineering_debt else human_debt
        blocks = state.get("blockers", {})
        unblocked = [d for d in debt if not any(blocks.get(b, {}).get("active")
                                               for b in d.get("blockers", []))]
        if runner.get("stop_requested") or runner["mode"] == "stopped" or exhausted:
            decision, reason = "STOP", "user_stop" if runner.get("stop_requested") else "budget_exhausted"
        elif runner["mode"] == "paused":
            decision, reason = "WAIT", "user_paused"
        elif errors:
            decision, reason = "CONTINUE", "repair_scope_integrity"
        elif engineering_ready and not product_accepted and not eligible:
            decision, reason = "WAIT", "engineering_ready_pending_human_confirmation"
        elif eligible or unblocked:
            decision, reason = "CONTINUE", "actionable_work" if eligible else "plan_or_repair_unfinished_work"
        elif product_accepted:
            decision, reason = "COMPLETE", "product_accepted_public_release_separate"
        else:
            decision, reason = "WAIT", "all_remaining_work_has_specific_blockers"
        release = state.get("delivery", {}).get("release", {})
        permitted = bool(authorized and not exhausted and not errors and eligible
                         and not runner.get("stop_requested")
                         and runner["mode"] not in {"paused", "stopped"}
                         and decision == "CONTINUE")
        return {"decision": decision, "reason": reason, "engineering_ready": engineering_ready,
                "product_accepted": product_accepted,
                "public_release": bool(product_accepted and release.get("status") == "published"
                                       and release.get("authorization") and release.get("license_privacy_review")),
                "scope_errors": errors, "engineering_debt": engineering_debt, "human_debt": human_debt,
                "resolved_units": resolved_units,
                "next_units": [u["id"] for u in eligible], "source": source,
                "runner_active": alive(runner.get("owner")),
                "authorization_recorded": authorized,
                "execution_permitted_now": permitted,
                "execution_authorized": permitted}

    def status(self, *, verify=True):
        from .development_status import project_status
        state = self.read()
        recorded_sha = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
        if verify:
            self._revalidate_units(state, record_events=False)
            result = self.gate(state)
        else:
            # Current recorded state is visible without pretending that source,
            # evidence, scope or dependency bindings were checked on this poll.
            result = {"status": "verification_pending", "decision": "PENDING",
                      "reason": "fresh_full_gate_required", "engineering_ready": None,
                      "product_accepted": None, "public_release": None,
                      "execution_permitted_now": False, "execution_authorized": False,
                      "scope_errors": [], "engineering_debt": [], "human_debt": [],
                      "source": {"code_digest": None}, "authorization": False}
        return {"runner": state["runner"], "queue": state["queue"], "handoff": state["handoff"],
                "recorded_state_sha256": recorded_sha,
                "verification_mode": "fresh" if verify else "pending",
                "gate": result, "state_path": str(self.path),
                **project_status(self, state, result, (("capabilities", CAPABILITIES),
                                 ("scenarios", SCENARIOS), ("subcases", SUBCASES)), verify=verify)}

    def queue(self, spec):
        spec = copy.deepcopy(spec)
        if "resolution" in spec or "resolution_history" in spec:
            raise ControlError("queue cannot supply resolution; use explicit resolve after verification")
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", spec.get("id", "")):
            raise ControlError("unit id must be a safe filename")
        if spec.get("kind") not in ("command", "codex"):
            raise ControlError("unit kind must be command or codex")
        if spec["kind"] == "command" and not self._valid_argv(spec.get("argv")):
            raise ControlError("command unit requires argv list")
        if spec["kind"] == "codex" and not spec.get("prompt"):
            raise ControlError("codex unit requires prompt")
        if not spec.get("postconditions"):
            raise ControlError("postconditions required; exit 0 or final text is insufficient")
        for condition in spec["postconditions"]:
            if condition.get("kind") not in ("file_sha256", "json_equals", "command"):
                raise ControlError("unsupported postcondition")
            if condition["kind"] == "command":
                if not self._valid_argv(condition.get("argv")):
                    raise ControlError("postcondition command requires argv")
            else:
                self._path(condition["path"])
                if condition["kind"] == "file_sha256" and not re.fullmatch(r"[0-9a-f]{64}", condition.get("sha256", "")):
                    raise ControlError("postcondition requires expected SHA256")
        spec.setdefault("timeout_seconds", 120)
        spec.setdefault("max_attempts", 2)
        spec.setdefault("backoff_seconds", 1)
        spec.setdefault("depends_on", [])
        spec.setdefault("covers", [])
        spec.setdefault("blockers", [])
        spec.setdefault("replay_safe", False)
        spec.setdefault("evidence_class", "engineering")
        if spec["evidence_class"] not in ("engineering", "fault_injection"):
            raise ControlError("invalid evidence class")
        if (not math.isfinite(spec["timeout_seconds"]) or not 0 < spec["timeout_seconds"] <= 3600
                or not isinstance(spec["max_attempts"], int) or not 1 <= spec["max_attempts"] <= 5):
            raise ControlError("timeout must be 0..3600 seconds; attempts 1..5")
        if not 0 <= spec["backoff_seconds"] <= 60:
            raise ControlError("backoff must be 0..60 seconds")
        with self.transaction() as state:
            self._require(state)
            if any(u["id"] == spec["id"] for u in state["queue"]):
                raise ControlError("duplicate unit id; retain original history")
            known = {u["id"] for u in state["queue"]}
            if not set(spec["depends_on"]) <= known:
                raise ControlError("dependencies must refer to already queued units")
            if not set(spec["covers"]) <= self.items(state).keys():
                raise ControlError("unknown coverage id")
            spec.update(status="queued", attempts=0, run_ids=[], next_attempt_at=0, created_at=now())
            state["queue"].append(spec)
            self._event(state, "queued", spec["id"])
        return spec

    @staticmethod
    def _valid_argv(argv):
        return isinstance(argv, list) and bool(argv) and all(isinstance(a, str) and a and "\x00" not in a for a in argv)

    @staticmethod
    def _require(state):
        if state is None:
            raise ControlError("Run init first")

    @staticmethod
    def _event(state, kind, detail):
        state["events"].append({"at": now(), "kind": kind, "detail": detail})

    def _eligible(self, state):
        completed = {u["id"] for u in state["queue"] if self._completion_binding(state, u)}
        blocks = state.get("blockers", {})
        return [u for u in state["queue"] if u["status"] in ("queued", "retry")
                and not u.get("resolution")
                and u["attempts"] < u["max_attempts"]
                and set(u["depends_on"]) <= completed
                and not any(blocks.get(b, {}).get("active") for b in u["blockers"])
                and u.get("next_attempt_at", 0) <= time.time()]

    def start(self, max_attempts, max_seconds, authority, allow_codex=False, max_output_bytes=10485760):
        if (not authority or not isinstance(max_attempts, int) or max_attempts <= 0
                or not math.isfinite(max_seconds) or max_seconds <= 0 or max_output_bytes <= 0):
            raise ControlError("explicit authority and finite positive budgets required")
        with self.transaction() as state:
            self._require(state)
            runner = state["runner"]
            if runner.get("authorization"):
                raise ControlError("already authorized: resume preserves budgets; start cannot reset them")
            if runner["stop_requested"] or runner["mode"] == "stopped":
                raise ControlError("user stop is latched; use resume with explicit renewed authority")
            runner["authorization"] = {"at": now(), "authority": authority, "allow_codex": allow_codex}
            runner["budget"].update(max_attempts=max_attempts, max_seconds=max_seconds,
                                    max_output_bytes=max_output_bytes)
            runner["mode"] = "ready"
            self._event(state, "authorized", runner["authorization"])
        return self.status()

    def resume(self, authority=None, extra_attempts=0, extra_seconds=0, clear_stop=False):
        with self.transaction() as state:
            self._require(state)
            runner = state["runner"]
            if not runner["authorization"]:
                raise ControlError("start must establish finite authorization first")
            if (runner["stop_requested"] and not (clear_stop and authority)):
                raise ControlError("user stop cannot be bypassed by a new process/session")
            if (not isinstance(extra_attempts, int) or extra_attempts < 0
                    or not math.isfinite(extra_seconds) or extra_seconds < 0):
                raise ControlError("budget increments cannot be negative")
            if (extra_attempts or extra_seconds or clear_stop) and not authority:
                raise ControlError("renewal/stop override requires explicit authority")
            budget = runner["budget"]
            budget["max_attempts"] += extra_attempts
            budget["max_seconds"] += extra_seconds
            if clear_stop:
                runner["stop_requested"] = False
            if budget["used_attempts"] >= budget["max_attempts"] or budget["used_seconds"] >= budget["max_seconds"]:
                raise ControlError("budget exhausted; resume cannot reset consumption")
            runner["mode"] = "ready"
            self._event(state, "resumed", {"authority": authority, "extra_attempts": extra_attempts,
                                           "extra_seconds": extra_seconds, "clear_stop": clear_stop})
        return self.status()

    def pause(self):
        return self._control("paused", False)

    def stop(self):
        return self._control("stopped", True)

    def _control(self, mode, stopped):
        with self.transaction() as state:
            self._require(state)
            state["runner"]["mode"] = mode
            state["runner"]["stop_requested"] |= stopped
            child = state["runner"].get("child")
            self._event(state, mode, "explicit operator control")
        terminate_owned(child)
        return self.status()

    def block(self, blocker_id, reason, items=(), units=(), active=True):
        with self.transaction() as state:
            self._require(state)
            if not reason:
                raise ControlError("specific blocker reason required")
            state["blockers"][blocker_id] = {"active": active, "reason": reason, "at": now()}
            for item_id in items:
                target = (state["delivery"][item_id] if item_id in ("installation", "independent_review")
                          else self.items(state)[item_id])
                target.setdefault("blockers", [])
                if blocker_id not in target["blockers"]:
                    target["blockers"].append(blocker_id)
            for unit_id in units:
                target = next(u for u in state["queue"] if u["id"] == unit_id)
                if blocker_id not in target["blockers"]:
                    target["blockers"].append(blocker_id)
            self._event(state, "blocker", {"id": blocker_id, "active": active, "reason": reason})

    def record(self, item_id, axis, receipt):
        if axis not in AXES:
            raise ControlError("unknown verification axis")
        errors = self.evidence_errors(receipt, axis, self.source_identity())
        if errors:
            raise ControlError("; ".join(errors))
        with self.transaction() as state:
            self._require(state)
            if item_id not in self.items(state):
                raise ControlError("unknown fixed scope item")
            self.items(state)[item_id][axis] = {"status": "passed", "evidence": [receipt]}
            self._event(state, "evidence_recorded", {"item": item_id, "axis": axis})

    def retry(self, unit_id, reason, authority=None):
        """Explicitly reconsider a repaired/externally unblocked unit, never reset usage."""
        if not reason:
            raise ControlError("retry requires the repair/unblock explanation")
        with self.transaction() as state:
            self._require(state)
            runner = state["runner"]
            unit = next((u for u in state["queue"] if u["id"] == unit_id), None)
            if unit and unit.get("resolution"):
                raise ControlError("resolved history cannot be retried; diagnose and queue a changed method")
            if not unit or unit["status"] not in ("failed", "blocked", "needs_review"):
                raise ControlError("retry requires a failed, blocked or needs_review unit")
            if unit["attempts"] >= unit["max_attempts"]:
                raise ControlError("unit retry limit reached; diagnose and queue a changed method")
            if runner.get("model_blocker") and unit["kind"] == "codex":
                if not authority:
                    raise ControlError("model authorization/quota block requires explicit renewed authority")
                runner["model_blocker"] = None
            unit.update(status="queued", next_attempt_at=0)
            self._event(state, "retry_authorized", {"unit": unit_id, "reason": reason,
                                                     "authority": authority})
        return self.status()

    @staticmethod
    def _unit_contract(unit):
        return {key: copy.deepcopy(unit.get(key)) for key in
                ("id", "kind", "argv", "prompt", "covers", "postconditions", "depends_on", "evidence_class")}

    @staticmethod
    def _historical_state(unit):
        return {key: copy.deepcopy(unit.get(key)) for key in
                ("status", "attempts", "run_ids", "failure", "receipt")}

    def _resolution_errors(self, state, target):
        """Reopen an explicit replacement without rewriting historical execution."""
        record = target.get("resolution", {})
        units = {unit["id"]: unit for unit in state["queue"]}
        replacement = units.get(record.get("by"))
        errors = []
        if (record.get("kind") != "verified_replacement" or not record.get("reason")
                or record.get("target_contract") != self._unit_contract(target)
                or record.get("target_state") != self._historical_state(target)):
            errors.append("resolution missing rationale or original contract/history changed")
        if not replacement or replacement is target or replacement["status"] != "verified" or replacement.get("resolution"):
            return errors + ["replacement must be a distinct currently verified unit"]
        # A replacement cannot obtain its success from the work it resolves.
        pending, visited = list(replacement.get("depends_on", [])), set()
        while pending:
            ident = pending.pop()
            if ident == target["id"]:
                errors.append("replacement depends on the work it would resolve")
                break
            if ident not in visited:
                visited.add(ident)
                pending.extend(units.get(ident, {}).get("depends_on", []))
        if not set(target.get("covers", [])) <= set(replacement.get("covers", [])):
            errors.append("replacement drops original scope coverage")
        if replacement.get("evidence_class") != target.get("evidence_class"):
            errors.append("replacement evidence class differs from original work")
        if record.get("replacement_receipt") != replacement.get("receipt"):
            errors.append("replacement receipt binding changed")
        if target.get("receipt"):
            errors.extend(self._artifact_errors(target["receipt"]))
        problems, receipt = self._unit_receipt_errors(replacement)
        errors.extend(problems)
        if receipt:
            passed = [check.get("method") for check in receipt.get("checks", []) if check.get("passed") is True]
            if (receipt.get("returncode") != 0 or receipt.get("failure") or not passed
                    or any(check.get("passed") is not True for check in receipt.get("checks", []))
                    or any(condition not in passed for condition in replacement.get("postconditions", []))
                    or any(condition not in passed for condition in target.get("postconditions", []))
                    or any(condition not in replacement.get("postconditions", []) for condition in target.get("postconditions", []))):
                errors.append("replacement did not pass all original postconditions")
            if receipt.get("evidence_class") != target.get("evidence_class"):
                errors.append("replacement receipt evidence class mismatch")
            sources = record.get("source_files", [])
            if not isinstance(sources, list) or not sources:
                errors.append("resolution requires scoped implementation source identities")
            else:
                for artifact in sources:
                    errors.extend(self._artifact_errors(artifact))
                    if (not isinstance(artifact, dict) or receipt.get("source", {}).get("files", {}).get(artifact.get("path")) != artifact.get("sha256")):
                        errors.append("resolution source was not the implementation verified by replacement")
        return errors

    def resolve(self, unit_id, replacement_id, reason, source_files):
        """Bind already verified work to a failed/redundant unit; no execution or budget grant."""
        if not reason or not source_files:
            raise ControlError("resolve requires a reason and scoped implementation source files")
        with self.transaction() as state:
            self._require(state)
            if self.scope_errors():
                raise ControlError("scope integrity failed")
            if alive(state["runner"].get("owner")):
                raise ControlError("cannot resolve while a controller owns the runner")
            self._revalidate_units(state)
            units = {unit["id"]: unit for unit in state["queue"]}
            target, replacement = units.get(unit_id), units.get(replacement_id)
            if not target or target["status"] not in ("failed", "needs_review", "blocked", "queued", "retry"):
                raise ControlError("resolve requires outstanding work with preserved history")
            if not replacement:
                raise ControlError("unknown replacement unit")
            record = {"kind": "verified_replacement", "by": replacement_id, "reason": reason,
                      "at": now(), "formal_acceptance": False,
                      "target_contract": self._unit_contract(target), "target_state": self._historical_state(target),
                      "replacement_receipt": copy.deepcopy(replacement.get("receipt")),
                      "source_files": [self.artifact(self._path(path), "implementation") for path in source_files]}
            previous = target.get("resolution")
            target["resolution"] = record
            errors = self._resolution_errors(state, target)
            if errors:
                raise ControlError("; ".join(errors))
            if previous:
                target.setdefault("resolution_history", []).append(previous)
            self._event(state, "unit_resolved_by_verified_replacement", {"unit": unit_id, **copy.deepcopy(record)})
        return self.status()

    def _completion_binding(self, state, unit):
        if unit["status"] == "verified":
            return {"unit": unit["id"], "receipt": copy.deepcopy(unit.get("receipt"))}
        if unit.get("resolution") and not self._resolution_errors(state, unit):
            return {"unit": unit["id"], "receipt": copy.deepcopy(unit["resolution"]["replacement_receipt"]),
                    "resolved_by": unit["resolution"]["by"],
                    "resolution_sha256": hashlib.sha256(json.dumps(unit["resolution"], sort_keys=True).encode()).hexdigest()}
        return None

    def _unit_receipt_errors(self, unit):
        """Reopen a verified unit's receipt and every recorded input/output."""
        problems = self._artifact_errors(unit.get("receipt", {}))
        if problems:
            return problems, None
        try:
            receipt = json.loads(self._path(unit["receipt"]["path"]).read_text())
            if (not isinstance(receipt, dict) or receipt.get("unit") != unit["id"]
                    or receipt.get("status") != "verified"):
                return ["receipt does not verify this unit"], None
            for key in ("inputs", "artifacts"):
                artifacts = receipt.get(key, [])
                if not isinstance(artifacts, list):
                    problems.append("invalid receipt " + key)
                    continue
                for artifact in artifacts:
                    problems.extend(self._artifact_errors(artifact))
            if not receipt.get("artifacts"):
                problems.append("receipt contains no checked artifacts")
            return problems, receipt
        except (OSError, KeyError, ValueError, TypeError, ControlError) as exc:
            return ["unreadable completed unit receipt: " + type(exc).__name__], None

    def _revalidate_units(self, state, record_events=True):
        """Invalidate drift before the next dispatch, including its dependents.

        Historical receipts remain immutable evidence of what ran. Only the
        current eligibility changes; invalidated work needs an explicit review
        or retry, and independent queued work may still proceed.
        """
        units = {unit["id"]: unit for unit in state.get("queue", [])}
        receipts = {}

        def invalidate(unit, problems):
            unit["status"] = "needs_review"
            unit["failure"] = "completed unit evidence changed: " + "; ".join(problems)
            if record_events:
                self._event(state, "unit_evidence_invalidated", {"unit": unit["id"], "problems": problems})

        for unit in units.values():
            if unit["status"] == "verified":
                problems, receipt = self._unit_receipt_errors(unit)
                if problems:
                    invalidate(unit, problems)
                else:
                    receipts[unit["id"]] = receipt
        changed = True
        while changed:
            changed = False
            for unit in units.values():
                if unit["status"] != "verified":
                    continue
                problems = []
                for ident in unit.get("depends_on", []):
                    dependency = units.get(ident)
                    if not dependency or not self._completion_binding(state, dependency):
                        problems.append("prerequisite no longer verified: " + ident)
                bindings = receipts[unit["id"]].get("prerequisites", [])
                if not isinstance(bindings, list):
                    problems.append("invalid prerequisite receipt bindings")
                    bindings = []
                for binding in bindings:
                    if not isinstance(binding, dict):
                        problems.append("invalid prerequisite receipt binding")
                        continue
                    dependency = units.get(binding.get("unit"))
                    if dependency and self._completion_binding(state, dependency) != binding:
                        problems.append("prerequisite receipt changed: " + dependency["id"])
                if problems:
                    invalidate(unit, problems)
                    changed = True

    def _recover(self, state):
        runner = state["runner"]
        if alive(runner.get("owner")):
            raise ControlError("another controller still owns the runner")
        terminate_owned(runner.get("child"))
        self._revalidate_units(state)
        for unit in state["queue"]:
            if unit["status"] == "running":
                # Reserve attempt/time at launch. A crash cannot reset consumption.
                unit["status"] = "retry" if unit["replay_safe"] and unit["attempts"] < unit["max_attempts"] else "needs_review"
                unit["failure"] = "controller interrupted; partial effects require verification"
                self._event(state, "interrupted", unit["id"])
        runner.update(owner=None, child=None, current_unit=None)

    def _check_conditions(self, unit, run_dir, deadline, owner):
        checks, artifacts = [], []
        for index, condition in enumerate(unit["postconditions"]):
            ok, detail = False, ""
            try:
                if condition["kind"] == "command":
                    result = self._spawn(condition["argv"], None, run_dir / f"check-{index}", deadline, owner)
                    ok = result["returncode"] == 0 and result["failure"] is None
                    artifacts.extend(result["logs"])
                    detail = result["failure"] or f"exit={result['returncode']}"
                else:
                    path = self._path(condition["path"])
                    if condition["kind"] == "file_sha256":
                        ok = path.is_file() and sha(path) == condition["sha256"]
                    else:
                        value = json.loads(path.read_text())
                        for key in condition.get("keys", []):
                            value = value[key]
                        ok = value == condition["equals"]
                    artifacts.append(self.artifact(path))
                    detail = "reopened and compared expected value"
            except (OSError, KeyError, ValueError, TypeError, ControlError) as exc:
                detail = str(exc)
            checks.append({"method": condition, "passed": ok, "detail": detail})
        return checks, artifacts

    def _spawn(self, argv, stdin, prefix, deadline, owner):
        stdout_path, stderr_path = Path(f"{prefix}.stdout"), Path(f"{prefix}.stderr")
        failure, process = None, None
        with stdout_path.open("wb") as out, stderr_path.open("wb") as err:
            with self.transaction() as state:
                runner = state["runner"]
                if runner["owner"] != owner or runner["stop_requested"] or runner["mode"] == "paused":
                    failure = "execution interrupted by operator"
                elif time.monotonic() >= deadline:
                    failure = "timeout"
                else:
                    try:
                        process = subprocess.Popen(argv, cwd=self.root, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                                   stdout=out, stderr=err, start_new_session=True)
                        runner["child"] = identity(process.pid)
                    except (OSError, ValueError) as exc:
                        failure = f"spawn failed: {exc}"
            if process:
                child_owner = identity(process.pid, include_zombie=True)
                try:
                    payload = memoryview(stdin.encode()) if stdin is not None else memoryview(b"")
                    sent = 0
                    with selectors.DefaultSelector() as ready:
                        if process.stdin:
                            os.set_blocking(process.stdin.fileno(), False)
                            ready.register(process.stdin, selectors.EVENT_WRITE)
                        while True:
                            runner = self.read()["runner"]
                            if runner["owner"] != owner or runner["stop_requested"] or runner["mode"] == "paused":
                                failure = "execution interrupted by operator"
                            elif time.monotonic() >= deadline:
                                failure = "timeout"
                            elif stdout_path.stat().st_size + stderr_path.stat().st_size > runner["budget"]["max_output_bytes"]:
                                failure = "output budget exhausted"
                            if failure:
                                break
                            # WNOWAIT retains the leader identity until group
                            # cleanup. Stdin delivery is part of this same
                            # deadline/operator/output-budget loop, never a
                            # preceding synchronous buffered write.
                            if os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None:
                                if sent < len(payload):
                                    failure = "child exited before full input delivery"
                                break
                            if process.stdin and not process.stdin.closed and sent == len(payload):
                                ready.unregister(process.stdin)
                                process.stdin.close()
                            wait = min(0.05, max(0, deadline - time.monotonic()))
                            if sent < len(payload):
                                if ready.select(wait):
                                    try:
                                        sent += os.write(process.stdin.fileno(), payload[sent:sent + 65536])
                                    except BlockingIOError:
                                        continue
                                    except BrokenPipeError:
                                        failure = "child closed stdin before full input delivery"
                                        break
                            else:
                                time.sleep(wait)
                except (OSError, ValueError, KeyError) as exc:
                    failure = failure or "process supervision failed: " + type(exc).__name__
                finally:
                    try:
                        if process.stdin and not process.stdin.closed:
                            process.stdin.close()
                    finally:
                        try:
                            terminate_owned(child_owner)
                            process.wait()
                        finally:
                            with self.transaction() as state:
                                if state["runner"]["owner"] == owner:
                                    state["runner"]["child"] = None
                final_runner = self.read()["runner"]
                # Pause/stop can close the pipe while select reports writable.
                # Record the operator decision rather than a resulting EPIPE.
                if (final_runner["owner"] != owner or final_runner["stop_requested"]
                        or final_runner["mode"] == "paused"):
                    failure = "execution interrupted by operator"
                if stdout_path.stat().st_size + stderr_path.stat().st_size > final_runner["budget"]["max_output_bytes"]:
                    failure = failure or "output budget exhausted"
        return {"returncode": process.returncode if process else None, "failure": failure,
                "logs": [self.artifact(stdout_path, "execution_log"), self.artifact(stderr_path, "execution_log")]}

    def run(self, max_units=None):
        if max_units is not None and max_units <= 0:
            raise ControlError("max_units must be positive")
        self.runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
        owner = identity(os.getpid())
        with self.transaction() as state:
            self._require(state)
            if self.scope_errors():
                raise ControlError("scope integrity failed")
            runner = state["runner"]
            if not runner["authorization"]:
                raise ControlError("execution has no finite authorization; use start")
            if runner["stop_requested"] or runner["mode"] in ("paused", "stopped"):
                raise ControlError("paused/stopped: explicit resume required")
            self._recover(state)
            runner.update(owner=owner, mode="running")
        count = 0
        try:
            while max_units is None or count < max_units:
                with self.transaction() as state:
                    runner = state["runner"]
                    self._revalidate_units(state)
                    gate = self.gate(state)
                    if gate["decision"] != "CONTINUE":
                        break
                    eligible = self._eligible(state)
                    if not eligible:
                        retries = [u for u in state["queue"] if u["status"] == "retry" and u["next_attempt_at"] > time.time()]
                        if retries:
                            wait = min(max(0, min(u["next_attempt_at"] for u in retries) - time.time()), 0.25)
                        else:
                            state["handoff"] = "Unfinished scope remains; no executable queued unit. Controller exited, not running in background."
                            break
                    else:
                        wait = None
                        unit = eligible[0]
                        if unit["kind"] == "codex" and (not runner["authorization"].get("allow_codex") or runner.get("model_blocker")):
                            unit["status"] = "blocked"
                            unit["failure"] = runner.get("model_blocker") or "model execution not authorized"
                            continue
                        budget = runner["budget"]
                        reserved = min(unit["timeout_seconds"], budget["max_seconds"] - budget["used_seconds"])
                        budget["used_attempts"] += 1
                        budget["used_seconds"] += reserved
                        unit["attempts"] += 1
                        unit["status"] = "running"
                        run_id = f"{unit['id']}-{unit['attempts']}-{uuid.uuid4().hex[:8]}"
                        unit["run_ids"].append(run_id)
                        runner["current_unit"] = unit["id"]
                        unit = copy.deepcopy(unit)
                        unit["prerequisite_receipts"] = [
                            self._completion_binding(state, dependency)
                            for dependency in state["queue"] if dependency["id"] in unit["depends_on"]]
                        source_before = self.source_identity()
                        session_id = runner.get("session_id")
                if wait is not None:
                    time.sleep(wait)
                    continue
                run_dir = self.runtime / run_id
                run_dir.mkdir()
                specification_path = run_dir / "unit.json"
                specification_path.write_text(json.dumps(unit, ensure_ascii=False, indent=2) + "\n")
                started = time.monotonic()
                deadline = started + reserved
                argv, stdin = unit.get("argv"), None
                auth_failure = None
                if unit["kind"] == "codex":
                    # Status exposes only login state, never credential file contents.
                    try:
                        auth = subprocess.run(["codex", "login", "status"], cwd=self.root, capture_output=True, text=True, timeout=min(10, reserved))
                        if auth.returncode != 0 or "Logged in" not in auth.stdout + auth.stderr:
                            auth_failure = "Codex authentication unavailable; existing session retained"
                    except (OSError, subprocess.TimeoutExpired):
                        auth_failure = "Codex authentication check failed or timed out; existing session retained"
                    argv = codex_argv(self.root, run_dir / "last-message.txt", session_id)
                    stdin = unit["prompt"]
                result = self._spawn(argv, stdin, run_dir / "execute", deadline, owner) if not auth_failure else {
                    "returncode": None, "failure": auth_failure, "logs": []}
                checks, artifacts = [], []
                if result["returncode"] == 0 and result["failure"] is None:
                    checks, artifacts = self._check_conditions(unit, run_dir, deadline, owner)
                session, model_usage, model_completed, model_failed = session_id, None, False, False
                if unit["kind"] == "codex" and (run_dir / "execute.stdout").exists():
                    for line in (run_dir / "execute.stdout").read_text(errors="replace").splitlines():
                        try:
                            event = json.loads(line)
                            if not isinstance(event, dict):
                                continue
                            if event.get("type") == "thread.started":
                                session = event.get("thread_id", session)
                            if event.get("type") == "turn.completed":
                                model_usage = event.get("usage")
                                model_completed = True
                            if event.get("type") in ("error", "turn.failed"):
                                model_failed = True
                                message = json.dumps(event, ensure_ascii=False).lower()
                                if any(word in message for word in ("auth", "quota", "usage limit", "rate_limit", "permission", "credit")):
                                    auth_failure = "Codex authentication/quota/permission blocked; inspect private execution log; no session bypass"
                        except ValueError:
                            pass
                elapsed = time.monotonic() - started
                if unit["kind"] == "codex" and (not model_completed or model_failed or not session):
                    result["failure"] = result["failure"] or "Codex did not produce a successful completed turn and session identity"
                verified = (result["returncode"] == 0 and result["failure"] is None and auth_failure is None
                            and bool(checks) and all(c["passed"] for c in checks))
                failure = auth_failure or result["failure"] or (None if verified else "nonzero exit or failed/missing postconditions")
                source_after = self.source_identity()
                receipt = {"id": run_id, "unit": unit["id"], "kind": "development_unit",
                           "evidence_class": unit["evidence_class"], "formal_acceptance": False,
                           "observed_at": now(), "argv": argv, "session_id": session,
                           "resumed_session": session_id, "model_usage": model_usage, "monetary_cost": None,
                           "source_before": source_before,
                           "source": source_after, "seconds": elapsed, "reserved_seconds": reserved,
                           "status": "verified" if verified else "failed", "failure": failure,
                           "returncode": result["returncode"], "checks": checks,
                           "inputs": [self.artifact(specification_path, "unit_specification")],
                           "prerequisites": unit["prerequisite_receipts"],
                           "artifacts": result["logs"] + artifacts}
                receipt_path = run_dir / "receipt.json"
                receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
                with self.transaction() as state:
                    runner = state["runner"]
                    runner["budget"]["used_seconds"] -= max(0, reserved - elapsed)
                    current = next(u for u in state["queue"] if u["id"] == unit["id"])
                    interrupted = runner["stop_requested"] or runner["mode"] == "paused"
                    if verified and not interrupted:
                        current["status"] = "verified"
                    elif auth_failure:
                        current["status"] = "blocked"
                        current["failure"] = auth_failure
                        runner["model_blocker"] = auth_failure
                    elif current["attempts"] < current["max_attempts"] and current["replay_safe"]:
                        current["status"] = "retry"
                        current["next_attempt_at"] = time.time() + min(60, unit["backoff_seconds"] * 2 ** (unit["attempts"] - 1))
                    else:
                        current["status"] = "failed" if not interrupted else "needs_review"
                    current["failure"] = failure
                    current["receipt"] = self.artifact(receipt_path, "development_receipt")
                    state["runs"].append(current["receipt"])
                    runner.update(current_unit=None, child=None, session_id=session)
                    state["implementation"] = source_after
                    self._revalidate_units(state)
                    state["handoff"] = f"{unit['id']}: {current['status']}. Verify receipt and select next unit; feature acceptance remains independent."
                    self._event(state, "unit_finished", {"unit": unit["id"], "status": current["status"], "failure": current["failure"]})
                count += 1
        finally:
            with self.transaction() as state:
                runner = state["runner"]
                if runner["owner"] == owner:
                    terminate_owned(runner.get("child"))
                    runner.update(owner=None, child=None, current_unit=None)
                    if runner["mode"] == "running":
                        runner["mode"] = "idle"
        return self.status()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "gate", "pause", "stop"):
        sub.add_parser(name)
    queue = sub.add_parser("queue")
    queue.add_argument("spec", type=Path)
    start = sub.add_parser("start")
    start.add_argument("--max-attempts", type=int, required=True)
    start.add_argument("--max-seconds", type=float, required=True)
    start.add_argument("--authority", required=True)
    start.add_argument("--allow-codex", action="store_true")
    start.add_argument("--max-output-bytes", type=int, default=10485760)
    resume = sub.add_parser("resume")
    resume.add_argument("--authority")
    resume.add_argument("--extra-attempts", type=int, default=0)
    resume.add_argument("--extra-seconds", type=float, default=0)
    resume.add_argument("--clear-stop", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--max-units", type=int)
    record = sub.add_parser("record")
    record.add_argument("item_id")
    record.add_argument("axis", choices=AXES)
    record.add_argument("receipt", type=Path)
    block = sub.add_parser("block")
    block.add_argument("blocker_id")
    block.add_argument("--reason", required=True)
    block.add_argument("--item", action="append", default=[])
    block.add_argument("--unit", action="append", default=[])
    block.add_argument("--clear", action="store_true")
    retry = sub.add_parser("retry")
    retry.add_argument("unit_id")
    retry.add_argument("--reason", required=True)
    retry.add_argument("--authority")
    resolve = sub.add_parser("resolve")
    resolve.add_argument("unit_id")
    resolve.add_argument("--by", required=True, dest="replacement_id")
    resolve.add_argument("--reason", required=True)
    resolve.add_argument("--source", required=True, action="append", dest="source_files")
    args = parser.parse_args(argv)
    control = DevelopmentControl(args.root)
    try:
        if args.command == "queue":
            result = control.queue(json.loads(args.spec.read_text()))
        elif args.command == "start":
            result = control.start(args.max_attempts, args.max_seconds, args.authority,
                                   args.allow_codex, args.max_output_bytes)
        elif args.command == "resume":
            result = control.resume(args.authority, args.extra_attempts, args.extra_seconds, args.clear_stop)
        elif args.command == "run":
            result = control.run(args.max_units)
        elif args.command == "record":
            result = control.record(args.item_id, args.axis, json.loads(args.receipt.read_text()))
        elif args.command == "block":
            result = control.block(args.blocker_id, args.reason, args.item, args.unit, not args.clear)
        elif args.command == "retry":
            result = control.retry(args.unit_id, args.reason, args.authority)
        elif args.command == "resolve":
            result = control.resolve(args.unit_id, args.replacement_id, args.reason, args.source_files)
        else:
            result = getattr(control, args.command)()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ControlError, OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
