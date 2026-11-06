"""Experimental managed Codex message pump; no server/model is started here.

Only the owner constructs the connected client and supplies fresh thread/turn
parameters and task/lease/budget authority. ``deadline`` is absolute monotonic
time. Cleanup uses only this fresh thread and authoritative native turn IDs.
Local finish/connection close is never a native terminal or settlement receipt.
"""

from __future__ import annotations

import copy
import base64
import hashlib
import json
import math
import time
import uuid

from .provider_availability import require_codex_dynamic_available
from .mcp_workbench import MAX_RESPONSE

DEFAULT_MAX_MESSAGES = 256
# Raw streaming notifications only. Byte, tool, time and identity limits remain
# independent; this does not authorize additional callbacks or native turns.
MAX_MESSAGES = 2048


def validate_limits(
    *,
    check_interval=1.0,
    max_messages=DEFAULT_MAX_MESSAGES,
    max_total_bytes=64 * 1024 * 1024,
    max_message_bytes=MAX_RESPONSE,
    max_buffered_requests=8,
    cleanup_seconds=2.0,
):
    """Pure transport preflight; call before reservation/connection/dispatch.

    Returns the exact constructor keyword values without reading a clock,
    checker, router, socket or budget, and without performing any side effect.
    """
    for value, minimum, maximum, strict_minimum in (
        (check_interval, 0, 1, True),
        (cleanup_seconds, 0, 2, False),
    ):
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value > maximum
            or value < minimum
            or strict_minimum
            and value == minimum
        ):
            raise ValueError("Finite short transport time bounds required")
    for value, minimum, maximum in (
        (max_messages, 8, MAX_MESSAGES),
        (max_total_bytes, 4096, 64 * 1024 * 1024),
        (max_message_bytes, 1024, MAX_RESPONSE),
        (max_buffered_requests, 1, 8),
    ):
        if type(value) is not int or not minimum <= value <= maximum:
            raise ValueError("Native transport bounds exceeded")
    if max_message_bytes > max_total_bytes:
        raise ValueError("One message cannot exceed total raw evidence capacity")
    return dict(
        check_interval=check_interval,
        max_messages=max_messages,
        max_total_bytes=max_total_bytes,
        max_message_bytes=max_message_bytes,
        max_buffered_requests=max_buffered_requests,
        cleanup_seconds=cleanup_seconds,
    )


class DynamicTransportError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def _encoded(value):
    # Matches the existing AppServer.send JSON encoding; no protocol renaming.
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _identity(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 200
        and all(c.isascii() and (c.isalnum() or c in "_.:-") for c in value)
    )


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _loads(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate native JSON member")
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError("Nonfinite native JSON")

    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    _encoded(value)  # Reject lone surrogates before identity or callbacks.
    return value


class ManagedAppServerClient:
    """公共版本不提供私有 AppServer 连接协议，构造时明确拒绝。"""

    def __init__(self, path=None, timeout=1.0, max_message_bytes=MAX_RESPONSE):
        require_codex_dynamic_available()


class NativeDynamicSession:
    """One fresh thread, one turn/start, bounded raw wire evidence and cleanup.

    A client supplies send(dict), receive()->dict, settimeout(seconds), and
    last_received_raw bytes (or None, explicitly recorded as reconstructed).
    Unknown outcomes never expose finished_at or auto-retry/start another turn.
    """

    def __init__(
        self,
        client,
        router,
        budget_check,
        deadline,
        *,
        check_interval=1.0,
        max_messages=DEFAULT_MAX_MESSAGES,
        max_total_bytes=64 * 1024 * 1024,
        max_message_bytes=MAX_RESPONSE,
        max_buffered_requests=8,
        cleanup_seconds=2.0,
    ):
        validate_limits(
            check_interval=check_interval,
            max_messages=max_messages,
            max_total_bytes=max_total_bytes,
            max_message_bytes=max_message_bytes,
            max_buffered_requests=max_buffered_requests,
            cleanup_seconds=cleanup_seconds,
        )
        if (
            not callable(budget_check)
            or type(deadline) not in (int, float)
            or not math.isfinite(deadline)
        ):
            raise ValueError("Finite deadline and authority check required")
        if router.thread_id or router.turn_id:
            raise ValueError("A new router is required for a fresh native session")
        self.client, self.router, self.budget_check, self.deadline = (
            client,
            router,
            budget_check,
            deadline,
        )
        self.check_interval, self.cleanup_seconds = check_interval, cleanup_seconds
        self.max_messages, self.max_total_bytes, self.max_message_bytes = (
            max_messages,
            max_total_bytes,
            max_message_bytes,
        )
        self.max_buffered_requests = max_buffered_requests
        self._reserve_messages = min(8, max_messages // 4)
        self._reserve_bytes = min(65536, max_total_bytes // 4)
        self._wire, self._overflows, self._buffer, self._usage, self._reply_items = (
            [],
            [],
            [],
            [],
            {},
        )
        self._bytes = 0
        self.thread_id = self.turn_id = None
        self._thread_rpc = self._turn_rpc = self._read_rpc = self._interrupt_rpc = None
        self._turn_sent, self._started, self._limit_hit, self._terminal = (
            False,
            False,
            False,
            None,
        )
        self._thread_response = self._turn_response = self._read_response = None
        self._identity_source = None
        self._times = dict(
            thread_request_sent_at=None,
            turn_request_sent_at=None,
            terminal_received_at=None,
            local_finished_at=None,
        )
        self._failure = self._cleanup_error = None
        self._evidence_invalid = False

    def _check(self):
        self.budget_check()
        if time.monotonic() >= self.deadline:
            raise DynamicTransportError("timeout", "Native turn deadline reached")

    def _record(self, direction, value, raw=None, *, cleanup=False):
        origin = "client_raw_bytes" if isinstance(raw, bytes) else "reconstructed_json"
        raw = raw if isinstance(raw, bytes) else _encoded(value)
        timestamp = time.time()
        max_count = (
            self.max_messages if cleanup else self.max_messages - self._reserve_messages
        )
        max_bytes = (
            self.max_total_bytes
            if cleanup
            else self.max_total_bytes - self._reserve_bytes
        )
        if (
            len(raw) > self.max_message_bytes
            or len(self._wire) >= max_count
            or self._bytes + len(raw) > max_bytes
        ):
            self._limit_hit = True
            if len(self._overflows) < 4:
                self._overflows.append(
                    {
                        "direction": direction,
                        "sha256": _sha(raw),
                        "utf8_bytes": len(raw),
                        "received_at": timestamp,
                        "raw_preserved": False,
                    }
                )
            raise DynamicTransportError(
                "evidence_limit",
                "Raw message/count evidence limit reached; outcome remains unknown",
            )
        try:
            text, raw_base64 = raw.decode("utf-8"), None
        except UnicodeError:
            text, raw_base64 = None, base64.b64encode(raw).decode("ascii")
        try:
            decoded = _loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            decoded = None
        record = {
            "sequence": len(self._wire) + 1,
            "direction": direction,
            "wall_timestamp": timestamp,
            "raw_json": text,
            "utf8_bytes": len(raw),
            "sha256": _sha(raw),
            "origin": origin,
            "rpc_id": decoded.get("id") if isinstance(decoded, dict) else None,
            "method": decoded.get("method") if isinstance(decoded, dict) else None,
        }
        if raw_base64 is not None:
            record["raw_base64"] = raw_base64
        self._wire.append(record)
        self._bytes += len(raw)
        if not isinstance(decoded, dict) or decoded != value:
            self._evidence_invalid = True
            record["classification"] = "invalid_raw_native_json"
            raise DynamicTransportError(
                "invalid_wire_evidence",
                "Native raw message cannot authorize an identity or callback",
            )
        if direction == "in" and origin != "client_raw_bytes":
            self._evidence_invalid = True
            record["classification"] = "missing_raw_native_json"
            raise DynamicTransportError(
                "raw_evidence_missing",
                "Client must retain original received JSON bytes",
            )
        return record

    def _send(self, value, *, cleanup=False, stamp=None):
        record = self._record("out", value, _encoded(value), cleanup=cleanup)
        record["delivery"] = "not_sent"
        if not cleanup:
            self._check()
        if stamp:
            self._times[stamp] = (
                time.time()
            )  # Before first actual send, even if delivery fails.
            if stamp == "turn_request_sent_at":
                self._turn_sent = True
        record["delivery"] = "attempted"
        self.client.send(value)
        record["delivery"] = "sent"
        return record

    def _rpc(self, method, params, *, cleanup=False, stamp=None):
        ident = str(uuid.uuid4())
        attribute = {
            "thread/start": "_thread_rpc",
            "turn/start": "_turn_rpc",
            "thread/read": "_read_rpc",
            "turn/interrupt": "_interrupt_rpc",
        }[method]
        setattr(self, attribute, ident)  # Keep the request ID even when send is lost.
        self._send(
            {"id": ident, "method": method, "params": params},
            cleanup=cleanup,
            stamp=stamp,
        )
        return ident

    def _receive(self, until, *, cleanup=False):
        if not cleanup:
            self._check()
        remaining = until - time.monotonic()
        if remaining <= 0:
            raise DynamicTransportError("timeout", "Native receive bound reached")
        self.client.settimeout(min(self.check_interval, remaining))
        if hasattr(self.client, "set_receive_guard"):

            def guard():
                if not cleanup:
                    self._check()
                if time.monotonic() >= until:
                    raise DynamicTransportError(
                        "timeout", "Native frame receive bound reached"
                    )

            self.client.set_receive_guard(guard)
        previous_raw = getattr(self.client, "last_received_raw", None)
        try:
            value = self.client.receive()
        except Exception:
            raw = getattr(self.client, "last_received_raw", None)
            if isinstance(raw, bytes) and raw is not previous_raw:
                try:
                    self._record("in", {}, raw, cleanup=cleanup)
                except DynamicTransportError:
                    pass  # Keep invalid raw evidence and preserve original failure.
            raise
        if not isinstance(value, dict):
            raise DynamicTransportError(
                "invalid_message", "Native JSON object required"
            )
        raw = getattr(self.client, "last_received_raw", None)
        record = self._record("in", value, raw, cleanup=cleanup)
        return value, record

    def _server_request(self, value, record, *, cleanup=False):
        if value.get("method") == "item/tool/call" and not self.turn_id and not cleanup:
            count = sum(
                message.get("method") == "item/tool/call" for message, _ in self._buffer
            )
            if count >= self.max_buffered_requests:
                self._limit_hit = True
                raise DynamicTransportError(
                    "early_request_limit", "Too many unbound early tool requests"
                )
            record["classification"] = "buffered_until_authoritative_turn"
            self._buffer.append((value, record))
            return
        if not cleanup:
            self._check()
        raw = record["raw_json"].encode("utf-8")
        reply = self.router.handle(raw)
        record["classification"] = (
            "server_request_routed"
            if value.get("method") == "item/tool/call"
            else "server_request_denied"
        )
        self._send(reply, cleanup=cleanup)

    def _notification(self, value, record):
        params = value.get("params", {})
        if not isinstance(params, dict):
            raise DynamicTransportError(
                "invalid_message", "Native notification params must be an object"
            )
        if self.thread_id is None:
            record["classification"] = "buffered_until_authoritative_thread"
            self._buffer.append((value, record))
            return
        if params.get("threadId") != self.thread_id:
            record["classification"] = "foreign_or_unscoped_notification"
            return
        if not self.turn_id:
            record["classification"] = "buffered_until_authoritative_turn"
            self._buffer.append((value, record))
            return
        turn = params.get("turn", {})
        turn_id = (
            turn.get("id")
            if isinstance(turn, dict) and value.get("method") == "turn/completed"
            else params.get("turnId")
        )
        if turn_id != self.turn_id:
            record["classification"] = "foreign_turn_notification"
            return
        record["classification"] = "own_turn_notification"
        if value.get("method") == "thread/tokenUsage/updated":
            self._usage.append(
                {
                    "sequence": record["sequence"],
                    "wall_timestamp": record["wall_timestamp"],
                    "tokenUsage": copy.deepcopy(params.get("tokenUsage")),
                }
            )
        if value.get("method") == "item/completed":
            item = params.get("item", {})
            self._completed_reply(item, record)
        if value.get("method") == "turn/completed":
            if turn.get("status") not in (
                "completed",
                "failed",
                "interrupted",
            ) or not isinstance(turn.get("items"), list):
                self._evidence_invalid = True
                raise DynamicTransportError(
                    "invalid_terminal",
                    "Own terminal notification has no terminal status",
                )
            if self._terminal:
                if self._terminal["params"]["turn"]["status"] != turn["status"]:
                    self._evidence_invalid = True
                    raise DynamicTransportError(
                        "terminal_conflict", "Native terminal statuses conflict"
                    )
                record["classification"] = "duplicate_own_terminal"
                return
            self._terminal = copy.deepcopy(value)
            self._times["terminal_received_at"] = record["wall_timestamp"]
            for item in turn.get("items", []):
                self._completed_reply(item, record)

    def _completed_reply(self, item, record):
        if (
            isinstance(item, dict)
            and item.get("type") == "agentMessage"
            and isinstance(item.get("text"), str)
        ):
            key = item.get("id", str(record["sequence"]))
            self._reply_items.pop(key, None)
            self._reply_items[key] = {"text": item["text"], "phase": item.get("phase")}

    def _final_reply(self):
        # Installed 0.161 MessagePhase is commentary/final_answer. Prefer the
        # last completed final_answer; legacy fallback requires the last own
        # completed message itself to have an absent/null phase. Never compose.
        replies = list(self._reply_items.values())
        finals = [item for item in replies if item["phase"] == "final_answer"]
        if finals:
            return finals[-1]["text"]
        return replies[-1]["text"] if replies and replies[-1]["phase"] is None else ""

    def _consume(self, value, record, *, cleanup=False):
        if "method" in value and "id" in value:
            self._server_request(value, record, cleanup=cleanup)
        elif "method" in value:
            self._notification(value, record)
        else:
            record["classification"] = "unmatched_rpc_response"

    def _wait_rpc(self, ident):
        while True:
            try:
                value, record = self._receive(self.deadline)
            except TimeoutError:
                continue  # Short socket timeout is a check point, never a resend.
            if value.get("id") == ident and "method" not in value:
                record["classification"] = "authoritative_rpc_response"
                if "error" in value or not isinstance(value.get("result"), dict):
                    raise DynamicTransportError(
                        "native_rpc_error",
                        "Native RPC rejected or returned invalid data",
                    )
                return value
            self._consume(value, record)

    def _bind_turn(self, ident, source, *, cleanup=False):
        if not _identity(ident) or self.turn_id not in (None, ident):
            raise DynamicTransportError(
                "identity_mismatch", "Native turn authority is absent or conflicts"
            )
        if not cleanup:
            self.router.bind_turn(ident)
        self.turn_id, self._identity_source = ident, source
        buffered, self._buffer = self._buffer, []
        return buffered

    def _drain(self, buffered, *, cleanup=False):
        # A terminal already received before the start response cancels queued
        # callbacks; it is never permission to perform late writes.
        for value, record in buffered:
            params = value.get("params", {})
            if (
                value.get("method") == "turn/completed"
                and params.get("threadId") == self.thread_id
                and params.get("turn", {}).get("id") == self.turn_id
            ):
                self._notification(value, record)
                self.router.close()
                break
        for value, record in buffered:
            if "id" in value:
                if self._terminal:
                    self.router.close()
                self._server_request(value, record, cleanup=cleanup)
            else:
                self._notification(value, record)

    def _cleanup(self):
        self.router.close()
        until = time.monotonic() + self.cleanup_seconds
        if (
            not self.thread_id
            or not self._turn_sent
            or self._terminal
            or not self.cleanup_seconds
        ):
            return
        try:
            if not self.turn_id:
                # Explicit narrow recovery: one authoritative read of this fresh
                # thread, never infer a turn from a model's tool arguments.
                self._read_rpc = self._rpc(
                    "thread/read",
                    {"threadId": self.thread_id, "includeTurns": True},
                    cleanup=True,
                )
            if self.turn_id:
                self._interrupt_rpc = self._rpc(
                    "turn/interrupt",
                    {"threadId": self.thread_id, "turnId": self.turn_id},
                    cleanup=True,
                )
            while not self._terminal and time.monotonic() < until:
                try:
                    value, record = self._receive(until, cleanup=True)
                except TimeoutError:
                    continue
                if "method" not in value and value.get("id") in (
                    self._turn_rpc,
                    self._read_rpc,
                ):
                    record["classification"] = "cleanup_authority_response"
                    result = value.get("result", {})
                    if not isinstance(result, dict) or "error" in value:
                        continue
                    if value["id"] == self._turn_rpc:
                        self._turn_response = copy.deepcopy(value)
                        turn = result.get("turn", {})
                        ident = turn.get("id") if isinstance(turn, dict) else None
                        source = "turn/start"
                    else:
                        self._read_response = copy.deepcopy(value)
                        thread = result.get("thread", {})
                        turns = (
                            thread.get("turns", []) if isinstance(thread, dict) else []
                        )
                        if (
                            not isinstance(thread, dict)
                            or thread.get("id") != self.thread_id
                            or not isinstance(turns, list)
                            or len(turns) != 1
                            or not isinstance(turns[0], dict)
                            or turns[0].get("status") != "inProgress"
                        ):
                            continue
                        ident, source = (
                            turns[0].get("id"),
                            "thread/read_unique_fresh_turn",
                        )
                    if not self.turn_id:
                        buffered = self._bind_turn(ident, source, cleanup=True)
                        self._drain(buffered, cleanup=True)
                    if self.turn_id and not self._terminal and not self._interrupt_rpc:
                        self._interrupt_rpc = self._rpc(
                            "turn/interrupt",
                            {"threadId": self.thread_id, "turnId": self.turn_id},
                            cleanup=True,
                        )
                else:
                    self._consume(value, record, cleanup=True)
        except Exception as error:
            self._cleanup_error = {
                "code": getattr(error, "code", "cleanup_transport_error"),
                "type": type(error).__name__,
            }

    def run(self, thread_params, turn_params):
        if self._started:
            raise ValueError("A native session cannot start another thread or turn")
        self._started = True
        try:
            if (
                not isinstance(thread_params, dict)
                or not isinstance(turn_params, dict)
                or "threadId" in thread_params
            ):
                raise DynamicTransportError(
                    "invalid_params", "Fresh thread/turn parameter objects required"
                )
            for entry in getattr(self.client, "initialization_trace", []):
                raw = entry["raw_json"].encode("utf-8")
                record = self._record(entry["direction"], _loads(raw), raw)
                record["wall_timestamp"] = entry["wall_timestamp"]
                record["classification"] = "initialization_wire_message"
            params = copy.deepcopy(thread_params)
            declared = self.router.dynamic_tools()
            if "dynamicTools" in params and params["dynamicTools"] != declared:
                raise DynamicTransportError(
                    "tool_not_allowed", "Thread tools differ from the task allowlist"
                )
            params["dynamicTools"] = declared
            self._check()
            self._thread_rpc = self._rpc(
                "thread/start", params, stamp="thread_request_sent_at"
            )
            self._thread_response = self._wait_rpc(self._thread_rpc)
            thread = self._thread_response["result"].get("thread", {})
            ident = thread.get("id") if isinstance(thread, dict) else None
            if not _identity(ident) or thread.get("turns", []) != []:
                raise DynamicTransportError(
                    "identity_mismatch", "Fresh authoritative native thread required"
                )
            self.router.bind_thread(ident)
            self.thread_id = ident
            turn = copy.deepcopy(turn_params)
            if turn.get("threadId", ident) != ident:
                raise DynamicTransportError(
                    "identity_mismatch", "Turn parameters name a foreign thread"
                )
            turn["threadId"] = ident
            self._check()
            # Mark intent before send: lost/partial delivery cannot be retried.
            self._turn_rpc = self._rpc("turn/start", turn, stamp="turn_request_sent_at")
            self._turn_response = self._wait_rpc(self._turn_rpc)
            native_turn = self._turn_response["result"].get("turn", {})
            buffered = self._bind_turn(
                native_turn.get("id") if isinstance(native_turn, dict) else None,
                "turn/start",
            )
            self._drain(buffered)
            while not self._terminal:
                try:
                    value, record = self._receive(self.deadline)
                except TimeoutError:
                    continue
                self._consume(value, record)
        except Exception as error:
            self._failure = {
                "code": getattr(error, "code", "budget_or_transport_error"),
                "type": type(error).__name__,
            }
            self._cleanup()
        self.router.close()
        self._times["local_finished_at"] = time.time()
        state = (
            self._terminal["params"]["turn"]["status"]
            if self._terminal and not (self._limit_hit or self._evidence_invalid)
            else "unknown"
        )
        result = {
            "version": 1,
            "experimental": True,
            "state": state,
            "native_terminal_observed": self._terminal is not None,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "turn_identity_source": self._identity_source,
            "request_ids": {
                "thread/start": self._thread_rpc,
                "turn/start": self._turn_rpc,
                "thread/read": self._read_rpc,
                "turn/interrupt": self._interrupt_rpc,
            },
            "thread_start_response": self._thread_response,
            "turn_start_response": self._turn_response,
            "cleanup_thread_read_response": self._read_response,
            "terminal": self._terminal,
            **self._times,
            "wire_messages": self._wire,
            "total_raw_utf8_bytes": self._bytes,
            "raw_evidence_complete": not (self._limit_hit or self._evidence_invalid),
            "overflow_digests": self._overflows,
            "limits": {
                "messages": self.max_messages,
                "total_raw_bytes": self.max_total_bytes,
                "message_bytes": self.max_message_bytes,
                "early_tool_requests": self.max_buffered_requests,
            },
            "usage_events": self._usage,
            "latest_token_usage": self._usage[-1]["tokenUsage"]
            if self._usage
            else None,
            "final_reply": self._final_reply(),
            "failure": self._failure,
            "cleanup_error": self._cleanup_error,
            "router": self.router.snapshot(),
        }
        result["sha256"] = _sha(_encoded(result))
        return copy.deepcopy(result)
