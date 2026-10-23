"""Experimental Codex 0.161 dynamic-function routing, without a model/transport.

The caller binds IDs returned by the native thread/turn APIs. Early requests must
be buffered by that caller, never used to infer a turn ID. The callback retains
the existing service's task lease, fixed-source and egress authority. This module
does not grant permissions, retry writes, verify native execution or persist data.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import threading

from .mcp_workbench import BridgeError, MAX_INPUT, MAX_RESPONSE, SCHEMAS, TOOLS, validate
from .store import Problem

DOMAIN_TOOLS = ('read_figure_context', 'create_main_figure')


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identity(value):
    return isinstance(value, str) and 0 < len(value) <= 200 and all(c.isascii() and (c.isalnum() or c in '_.:-') for c in value)


def _request_id(value):
    # IDs are opaque, unlike task/source identities; bound their size so even a
    # rejection can fit the complete reply limit. bool is not an integer ID.
    return ((type(value) is int and -(2**63) <= value < 2**63)
            or (isinstance(value, str) and 0 < len(value.encode('utf-8')) <= 200))


def _failure(message, code, status=400, uncertain=False):
    return {'error': message, 'code': code, 'http_status': status, 'write_outcome_uncertain': uncertain}


def _response(value, success):
    return {'success': success, 'contentItems': [{'type': 'inputText', 'text': _json(value)}]}


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON member')
        value[key] = item
    return value


class DynamicToolRouter:
    """One bounded task/thread/turn, using the two existing domain schemas.

    ``handle`` returns a native JSON-RPC reply. Supported tool failures are
    ``result.success=False``; other server requests receive a JSON-RPC error.
    A same-call replay never invokes the callback again, including failed or
    uncertain writes. Receipts are in-memory; the owning adapter must freeze them
    before shutdown. Supplied events alone do not prove a real model execution.
    """

    def __init__(self, *, task_id, project_id, callback, allowed_tools=DOMAIN_TOOLS,
                 max_tool_calls=8, max_request_bytes=MAX_INPUT,
                 max_output_bytes=MAX_RESPONSE, max_events=64, max_requests=64):
        if not _identity(task_id) or not _identity(project_id) or not callable(callback):
            raise ValueError('Explicit task/project identities and callback required')
        if not isinstance(allowed_tools, (tuple, list)) or not all(isinstance(t, str) for t in allowed_tools):
            raise ValueError('Declare a list/tuple of known function names')
        tools = tuple(allowed_tools)
        if not tools or len(set(tools)) != len(tools) or not set(tools) <= set(DOMAIN_TOOLS):
            raise ValueError('Only explicitly declared figure-domain tools are permitted')
        for value, maximum in ((max_tool_calls, 8), (max_request_bytes, MAX_INPUT),
                               (max_output_bytes, MAX_RESPONSE), (max_events, 64), (max_requests, 64)):
            if type(value) is not int or not 1 <= value <= maximum:
                raise ValueError('Limits must be positive integers within existing bounds')
        # Ensure every local failure envelope fits; no response is truncated.
        if max_output_bytes < 1024:
            raise ValueError('Output limit must allow a complete failure response')
        self.task_id, self.project_id, self.callback = task_id, project_id, callback
        self.allowed_tools = tools
        self.max_tool_calls, self.max_request_bytes = max_tool_calls, max_request_bytes
        self.max_output_bytes, self.max_events = max_output_bytes, max_events
        self.max_requests = max_requests
        self.thread_id = self.turn_id = None
        self._calls, self._receipts, self._events = {}, [], []
        self._executed, self._write_uncertain, self._closed = 0, False, False
        self._lock = threading.RLock()

    def dynamic_tools(self):
        """Project existing schemas into the installed experimental function API."""
        return [dict(type='function', name=t['name'], description=t['description'],
                     inputSchema=copy.deepcopy(t['inputSchema']))
                for t in TOOLS if t['name'] in self.allowed_tools]

    def bind_thread(self, thread_id):
        with self._lock:
            if self._closed or not _identity(thread_id) or self.thread_id not in (None, thread_id):
                raise ValueError('Thread identity cannot be inferred or rebound')
            self.thread_id = thread_id

    def bind_turn(self, turn_id):
        with self._lock:
            if self._closed or not self.thread_id or not _identity(turn_id) or self.turn_id not in (None, turn_id):
                raise ValueError('Bind an authoritative thread before its immutable turn')
            self.turn_id = turn_id

    def close(self):
        with self._lock:
            self._closed = True

    def _decode(self, raw, limit):
        origin = 'supplied_bytes' if isinstance(raw, bytes) else 'supplied_text' if isinstance(raw, str) else 'canonical_mapping'
        data = raw if isinstance(raw, bytes) else raw.encode('utf-8') if isinstance(raw, str) else _json(raw).encode('utf-8')
        evidence = {'origin': origin, 'sha256': _sha(data), 'utf8_bytes': len(data)}
        if len(data) > limit:
            return None, {**evidence, 'preserved': False}, 'request_limit'
        try:
            text = data.decode('utf-8')
            evidence.update(text=text, preserved=True)
            def nonfinite(_):
                raise ValueError('Nonfinite JSON')
            value = json.loads(text, object_pairs_hook=_pairs, parse_constant=nonfinite)
            # Escaped lone surrogates parse in Python but are not UTF-8 replies.
            # Reject them before any callback, including opaque RPC IDs.
            _json(value).encode('utf-8')
        except (ValueError, UnicodeError, RecursionError):
            if 'text' not in evidence:
                evidence.update(base64=base64.b64encode(data).decode('ascii'), preserved=True)
            return None, evidence, 'invalid_request'
        return value, evidence, None

    def handle(self, raw):
        with self._lock:
            try:
                request, evidence, problem = self._decode(raw, self.max_request_bytes)
            except (ValueError, TypeError, UnicodeError, RecursionError):
                request, evidence, problem = None, {'origin': 'unserializable_mapping', 'preserved': False}, 'invalid_request'
            ident = request.get('id') if isinstance(request, dict) else None
            if not _request_id(ident):
                ident = None
                problem = problem or 'invalid_request'
            if len(self._receipts) >= self.max_requests:
                # Evidence is bounded too, including rejected/replayed requests.
                return {'id': ident, 'result': _response(_failure('Request receipt limit reached; no callback or retry.', 'request_count_limit', 429), False)}
            record = {'request': evidence, 'outcome': 'rejected', 'callback_invoked': False}
            def finish(value, success=False, *, rpc_error=False):
                response = ({'id': ident, 'error': {'code': -32601, 'message': value['error'], 'data': value}}
                            if rpc_error else {'id': ident, 'result': _response(value, success)})
                record.update(result_json=_json(value), result_sha256=_sha(_json(value).encode('utf-8')),
                              response=copy.deepcopy(response), response_sha256=_sha(_json(response).encode('utf-8')))
                self._receipts.append(record)
                return copy.deepcopy(response)
            if problem:
                return finish(_failure('Invalid or oversized dynamic-tool request.', problem))
            if set(request) - {'id', 'method', 'params', 'jsonrpc'} or request.get('jsonrpc', '2.0') != '2.0':
                return finish(_failure('Invalid JSON-RPC envelope.', 'invalid_request'))
            if request.get('method') != 'item/tool/call':
                return finish(_failure('Server request is outside the declared dynamic-tool route.', 'tool_not_allowed', 403), rpc_error=True)
            params = request.get('params')
            required = {'threadId', 'turnId', 'callId', 'tool', 'arguments'}
            if not isinstance(params, dict) or not required <= set(params) or set(params) - required - {'namespace'}:
                return finish(_failure('Dynamic-tool identity/arguments fields required.', 'invalid_request'))
            if not all(_identity(params[key]) for key in ('threadId', 'turnId', 'callId', 'tool')) or params.get('namespace') is not None:
                return finish(_failure('Flat declared functions require exact bounded identities.', 'invalid_request'))
            if self._closed:
                return finish(_failure('Task-scoped route is closed.', 'route_closed', 409))
            if self.thread_id is None or self.turn_id is None:
                return finish(_failure('Await authoritative thread/turn binding; no tool was executed.', 'identity_unbound', 409))
            if params['threadId'] != self.thread_id or params['turnId'] != self.turn_id:
                return finish(_failure('Request belongs to a different thread or turn.', 'foreign_identity', 403))
            tool, args, call_id = params['tool'], params['arguments'], params['callId']
            signature = _sha(_json({'tool': tool, 'arguments': args}).encode('utf-8'))
            existing = self._calls.get(call_id)
            if existing:
                if existing['signature'] != signature:
                    return finish(_failure('callId is already bound to different arguments.', 'call_id_conflict', 409))
                if 'result' not in existing:
                    return finish(_failure('Original callback is still in progress; no retry.', 'call_in_progress', 409, tool == 'create_main_figure'))
                record['outcome'] = 'replayed'
                return finish(existing['result'], existing['success'])
            # Pin bound request identity even when schema/permission/limit rejects
            # it. Editing a failed call's arguments is a different native call.
            self._calls[call_id] = {'signature': signature}
            record.update(call_id=call_id, arguments_sha256=signature)
            def remember(value, success=False):
                self._calls[call_id].update(result=copy.deepcopy(value), success=success)
                return finish(value, success)
            if tool not in self.allowed_tools:
                return remember(_failure('Function was not declared for this task.', 'tool_not_allowed', 403))
            try:
                validate(args, SCHEMAS[tool])
                if args['project_id'] != self.project_id:
                    raise BridgeError('Tool arguments belong to another project.', 'forbidden', 403)
                if tool == 'read_figure_context' and 'revision' not in args:
                    raise BridgeError('Read the explicit saved source revision.', 'invalid_arguments', 400)
            except BridgeError as error:
                return remember(error.public())
            if self._executed >= self.max_tool_calls:
                return remember(_failure('Task tool-call limit reached; no automatic retry.', 'budget_exhausted', 409))
            if tool == 'create_main_figure' and self._write_uncertain:
                return remember(_failure('A previous write outcome is uncertain; inspect real state before any new write.', 'write_outcome_uncertain', 409, True))
            self._executed += 1
            record.update(outcome='executed', callback_invoked=True, call_id=call_id, arguments_sha256=signature)
            uncertain = tool == 'create_main_figure'
            try:
                value = self.callback(tool, copy.deepcopy(args))
                if not isinstance(value, dict):
                    raise BridgeError('Tool callback returned invalid data; inspect state before repeating a write.', 'invalid_response', 502, uncertain=uncertain)
                success = not (value.get('ok') is False or value.get('isError') is True or ('error' in value and 'code' in value))
                rendered = _json(value)
                if len(_json({'id': ident, 'result': _response(value, success)}).encode('utf-8')) > self.max_output_bytes:
                    record.update(callback_result_sha256=_sha(rendered.encode('utf-8')), callback_result_bytes=len(rendered.encode('utf-8')))
                    raise BridgeError('Complete tool response exceeds its byte limit; no truncation or retry.', 'response_limit', 502, uncertain=uncertain)
            except (Problem, BridgeError) as error:
                if isinstance(error, BridgeError):
                    value = error.public()
                else:
                    value = _failure(str(error), error.code, error.status,
                                     bool(getattr(error, 'write_outcome_uncertain', False) or error.details.get('write_outcome_uncertain', False)))
                success = False
            except Exception:
                value, success = _failure('Unexpected callback failure; inspect service state before repeating a write.', 'internal_error', 500, uncertain), False
            # Error messages can themselves be oversized or invalid JSON.
            try:
                if len(_json({'id': ident, 'result': _response(value, success)}).encode('utf-8')) > self.max_output_bytes:
                    raise ValueError('Oversized failure')
            except (ValueError, TypeError, UnicodeError, RecursionError):
                value, success = _failure('Callback response cannot be returned within the complete JSON byte limit.', 'invalid_response', 502, uncertain), False
            if not success and value.get('write_outcome_uncertain'):
                self._write_uncertain = True
            return remember(value, success)

    def record_event(self, raw):
        """Retain supplied native event bytes only; never execute or infer IDs."""
        with self._lock:
            if self._closed or len(self._events) >= self.max_events:
                raise ValueError('Event evidence limit reached or route closed')
            value, evidence, problem = self._decode(raw, self.max_output_bytes)
            if problem or not isinstance(value, dict):
                raise ValueError('Event evidence must be bounded, valid JSON')
            self._events.append(evidence)

    def snapshot(self):
        with self._lock:
            snapshot = {'version': 1, 'experimental': True, 'protocol': 'codex-0.161-dynamic-function',
                        'task_id': self.task_id, 'project_id': self.project_id,
                        'thread_id': self.thread_id, 'turn_id': self.turn_id,
                        'declared_tools': list(self.allowed_tools), 'executed_tool_calls': self._executed,
                        'write_outcome_uncertain': self._write_uncertain, 'closed': self._closed,
                        'requests': copy.deepcopy(self._receipts), 'events': copy.deepcopy(self._events),
                        'native_execution_verified': False}
            snapshot['sha256'] = _sha(_json(snapshot).encode('utf-8'))
            return snapshot
