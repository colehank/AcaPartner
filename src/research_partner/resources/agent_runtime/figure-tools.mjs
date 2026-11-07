// New task-bound DSH native-tool feature; does not alter the five-tool research capsule.
// No model loop, file access, permission grant, source adoption or automatic retry.
import { createHash } from 'node:crypto';
import { strictCandidateJSON } from './acaworker-core.mjs';

export const FIGURE_TOOLS = Object.freeze(['read_figure_context', 'create_main_figure']);
const ACTIONS = { read_figure_context: 'desk.figure.read', create_main_figure: 'desk.figure.composition.create' };
const identity = v => typeof v === 'string' && /^[A-Za-z0-9_.:-]{1,200}$/.exec(v)?.[0] === v;
const digestIdentity = v => typeof v === 'string' && v.length === 64 && /^[a-f0-9]{64}$/.test(v);
const sha = v => createHash('sha256').update(v).digest('hex');
const object = v => v !== null && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype;

function canonical(value, depth = 0) {
  if (depth > 64) throw new Error('JSON depth limit');
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isFinite(value)) return JSON.stringify(value);
  if (typeof value === 'string' && !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)) return JSON.stringify(value);
  if (Array.isArray(value)) {
    if (Object.keys(value).length !== value.length) throw new Error('Dense JSON arrays required');
    return '[' + value.map(v => canonical(v, depth + 1)).join(',') + ']';
  }
  if (object(value)) return '{' + Object.keys(value).sort().map(k => canonical(k, depth + 1) + ':' + canonical(value[k], depth + 1)).join(',') + '}';
  throw new Error('Lossless finite Unicode JSON required');
}
const clone = value => JSON.parse(canonical(value));
const UNSUPPORTED_BOUNDS = new Set(['minLength', 'maxLength', 'pattern', 'minimum', 'maximum', 'minItems', 'maxItems']);
const FULL_SCHEMA_KEYS = new Set(['type', 'oneOf', 'properties', 'required', 'additionalProperties', 'items', 'enum', 'description', 'title', ...UNSUPPORTED_BOUNDS]);

/** Mechanical installed-rc.2 declaration projection only. Every removed bound
 * stays in the full catalog and in a per-field description, and execute below
 * enforces that original schema. Unknown schema keywords are NOT_LOADABLE.
 */
export function projectNativeCatalog(catalog) {
  function project(schema) {
    if (!object(schema) || Object.keys(schema).some(k => !FULL_SCHEMA_KEYS.has(k))) throw new Error('Unsupported full-schema keyword; no implicit weakening');
    const output = clone(schema), bounds = {};
    for (const key of UNSUPPORTED_BOUNDS) if (Object.hasOwn(output, key)) { bounds[key] = output[key]; delete output[key]; }
    if (Object.keys(bounds).length) output.description = (output.description ? output.description + '\n' : '') + 'Exact execution constraints (enforced by the complete original schema): ' + canonical(bounds);
    if (schema.properties) output.properties = Object.fromEntries(Object.entries(schema.properties).map(([k, v]) => [k, project(v)]));
    if (schema.items) output.items = project(schema.items);
    if (schema.oneOf) output.oneOf = schema.oneOf.map(project);
    return output;
  }
  return clone(catalog).map(d => ({ ...d, inputSchema: project(d.inputSchema) }));
}

export class FigureToolError extends Error {
  constructor(error, code = 'bridge_error', http_status = null, write_outcome_uncertain = false, details) {
    const value = { error, code, http_status, write_outcome_uncertain };
    if (details !== undefined) value.details = clone(details);
    // DSH's native failure projection retains Error.message, so keep the typed
    // HTTP failure as JSON text; never return it as a successful tool value.
    super(canonical(value)); this.name = 'FigureToolError'; this.value = value;
    this.code = code; this.http_status = http_status; this.write_outcome_uncertain = write_outcome_uncertain;
  }
  public() { return clone(this.value); }
}
const fail = (text, code = 'invalid_arguments', status = 400, uncertain = false) => { throw new FigureToolError(text, code, status, uncertain); };
function problem(error, uncertain = false) {
  if (error instanceof FigureToolError) return error;
  const p = typeof error?.public === 'function' ? error.public() : error;
  if (typeof p?.code === 'string') return new FigureToolError(typeof p.error === 'string' ? p.error : error.message || 'Service action failed', p.code, p.http_status ?? p.status ?? null, p.write_outcome_uncertain === true || p.uncertain === true || p.details?.write_outcome_uncertain === true, p.details);
  return new FigureToolError('Unexpected task callback failure; inspect state before repeating a write', 'internal_error', 500, uncertain);
}

function validate(value, schema, path = 'arguments') {
  if (schema.oneOf) {
    let matches = 0;
    for (const s of schema.oneOf) { try { validate(value, s, path); matches++; } catch (e) { if (!(e instanceof FigureToolError)) throw e; } }
    if (matches !== 1) fail(path + ' must match exactly one allowed type');
    return;
  }
  const type = schema.type;
  const good = type === 'object' ? object(value) : type === 'array' ? Array.isArray(value) : type === 'null' ? value === null :
    type === 'integer' ? Number.isSafeInteger(value) : type === 'number' ? typeof value === 'number' && Number.isFinite(value) : typeof value === type;
  if (!good) fail(path + ' has the wrong type');
  if (schema.enum && !schema.enum.includes(value)) fail(path + ' has an unsupported value');
  if (type === 'object') {
    if ((schema.required || []).some(k => !Object.hasOwn(value, k)) || schema.additionalProperties === false && Object.keys(value).some(k => !Object.hasOwn(schema.properties, k))) fail(path + ' has missing or unknown fields');
    for (const [k, v] of Object.entries(value)) validate(v, schema.properties[k], path + '.' + k);
  } else if (type === 'array') {
    if (value.length < (schema.minItems || 0) || value.length > (schema.maxItems ?? Infinity)) fail(path + ' has an invalid item count');
    value.forEach((v, i) => validate(v, schema.items, path + '[' + i + ']'));
  } else if (type === 'string') {
    if ([...value].length < (schema.minLength || 0) || [...value].length > (schema.maxLength ?? Infinity) || schema.pattern && new RegExp(schema.pattern, 'u').exec(value)?.[0] !== value) fail(path + ' has an invalid identity or length');
  } else if (type === 'number' || type === 'integer') {
    if (value < (schema.minimum ?? -Infinity) || value > (schema.maximum ?? Infinity)) fail(path + ' is outside its finite range');
  }
}

/** Existing WorkbenchClient HTTP contract; bearer is supplied by root's task_bridge.
 * No credential files are read. fetchImpl injection is for controlled offline tests.
 */
export function createWorkbenchBridge({ origin, getAuthorization, fetchImpl = globalThis.fetch, timeoutMs = 15000, maxResponseBytes = 32 * 1024 * 1024 }) {
  const url = new URL(origin);
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || !url.port || url.username || url.password || url.pathname !== '/' || url.search || url.hash || typeof getAuthorization !== 'function' || typeof fetchImpl !== 'function') throw new Error('Exact task-bridge loopback origin and authorization callback required');
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 15000 || !Number.isInteger(maxResponseBytes) || maxResponseBytes < 1024 || maxResponseBytes > 32 * 1024 * 1024) throw new Error('Bounded task bridge limits required');
  async function http(path, data, signal, csrf) {
    if (signal?.aborted) fail('Call cancelled before HTTP dispatch', 'cancelled', 409);
    let authorization;
    try { authorization = await getAuthorization(); } catch (e) { throw problem(e); }
    if (typeof authorization !== 'string' || !/^Bearer [\x21-\x7E]{24,4096}$/.test(authorization)) fail('Task bridge authorization unavailable', 'credentials_unavailable', 503);
    if (signal?.aborted) fail('Call cancelled before HTTP dispatch', 'cancelled', 409);
    const headers = { Accept: 'application/json', Authorization: authorization };
    if (data) Object.assign(headers, { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf });
    let attempted = false;
    try {
      const combined = signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs);
      attempted = true;
      const response = await fetchImpl(url.origin + path, { method: data ? 'POST' : 'GET', headers, body: data ? canonical(data) : undefined, redirect: 'manual', signal: combined });
      if (response.status >= 300 && response.status < 400) fail('Service redirect refused', 'redirect_refused', response.status, !!data);
      const reader = response.body?.getReader();
      if (!reader) fail('Service returned no response body', 'invalid_response', response.status, !!data);
      let count = 0; const chunks = [];
      try {
        while (true) {
          combined.throwIfAborted(); const { done, value } = await reader.read(); if (done) break;
          count += value.byteLength;
          if (count > maxResponseBytes) fail('Complete service response exceeds its byte limit', 'response_limit', response.status, !!data);
          chunks.push(Buffer.from(value));
        }
      } finally { await reader.cancel().catch(() => {}); }
      let result;
      try { result = strictCandidateJSON(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))); canonical(result); }
      catch { fail('Service returned invalid lossless JSON', 'invalid_response', response.status, !!data); }
      if (!object(result)) fail('Service response must be an object', 'invalid_response', response.status, !!data);
      if (!response.ok || result.ok === false) throw new FigureToolError(typeof result.error === 'string' ? result.error : 'Service rejected the request', typeof result.code === 'string' ? result.code : 'http_error', response.status, result.write_outcome_uncertain === true || result.details?.write_outcome_uncertain === true, result.details);
      return Object.hasOwn(result, 'result') ? result.result : result;
    } catch (e) {
      if (e instanceof FigureToolError) throw e;
      throw new FigureToolError('Service connection failed or was interrupted; inspect state before repeating a write', 'transport_error', null, !!data && attempted);
    }
  }
  return { async call(name, args, { signal } = {}) {
    if (!FIGURE_TOOLS.includes(name)) fail('Only the two task-bound figure tools are permitted', 'tool_not_allowed', 403);
    if (!object(args) || Object.hasOwn(args, 'action')) fail('Tool arguments cannot replace the domain action');
    const state = await http('/api/state', undefined, signal);
    if (typeof state.csrf !== 'string' || !state.csrf) fail('Service did not provide its write token', 'csrf_unavailable', 503);
    return http('/api/action', { ...args, action: ACTIONS[name] }, signal, state.csrf);
  } };
}

/** Supply the exact two catalog entries from mcp_workbench.TOOLS; no second schema.
 * checkAuthority must retain root's current Task lease, egress and parent budget.
 * Native session ID is bound only after the authoritative agents.create result.
 */
export function createFigureTools({ taskId, projectId, planSha256, fixedSources, request, toolDeclarations, catalogJson, client, checkAuthority, maxToolCalls = 8, maxRequests = 64, maxRequestBytes = 1024 * 1024, maxOutputBytes = 32 * 1024 * 1024, maxEvidenceBytes = 64 * 1024 * 1024 }) {
  if (!identity(taskId) || !identity(projectId) || !digestIdentity(planSha256) || typeof client?.call !== 'function' || typeof checkAuthority !== 'function') throw new Error('Explicit task/project/plan and authority-bearing client required');
  for (const [value, cap, minimum] of [[maxToolCalls, 8, 1], [maxRequests, 64, 1], [maxRequestBytes, 1024 * 1024, 1], [maxOutputBytes, 32 * 1024 * 1024, 1024], [maxEvidenceBytes, 64 * 1024 * 1024, 2048]]) if (!Number.isInteger(value) || value < minimum || value > cap) throw new Error('Existing finite tool/evidence limits required');
  const originalJson = catalogJson === undefined ? canonical(toolDeclarations) : catalogJson;
  if (typeof originalJson !== 'string' || Buffer.byteLength(originalJson) > 1024 * 1024) throw new Error('Complete bounded original catalog required');
  const declarations = strictCandidateJSON(originalJson), frozenRequest = clone(request), sources = clone(fixedSources);
  if (toolDeclarations !== undefined && canonical(declarations) !== canonical(toolDeclarations)) throw new Error('Original catalog bytes disagree with supplied declarations');
  if (!Array.isArray(declarations) || declarations.length !== 2 || new Set(declarations.map(d => d.name)).size !== 2 || declarations.some(d => !FIGURE_TOOLS.includes(d.name) || d.inputSchema?.type !== 'object' || d.inputSchema.additionalProperties !== false || typeof d.description !== 'string')) throw new Error('Exact complete two-tool catalog required');
  const schemas = Object.fromEntries(declarations.map(d => [d.name, d.inputSchema]));
  const projected = projectNativeCatalog(declarations);
  const catalogEvidence = { origin: catalogJson === undefined ? 'canonical_mapping' : 'supplied_json', raw_json: originalJson, sha256: sha(originalJson),
    native_schema_is_projection: true, native_declarations: projected, native_declarations_sha256: sha(canonical(projected)), removed_bound_keywords: [...UNSUPPORTED_BOUNDS] };
  if (!Array.isArray(sources) || !sources.length || sources.length > 24 || sources.some(s => !identity(s.id) || !Number.isSafeInteger(s.revision) || s.revision < 1 || !digestIdentity(s.sha256))) throw new Error('Explicit fixed source pins required');
  const refs = new Map();
  for (const s of sources) { const key = s.id + ':' + s.revision; if (refs.has(key) && refs.get(key) !== canonical(s)) throw new Error('Conflicting fixed source pins'); refs.set(key, canonical(s)); }
  const requestArgs = { ...frozenRequest, request_key: taskId + ':composition' };
  validate(requestArgs, schemas.create_main_figure);
  if (frozenRequest.project_id !== projectId || frozenRequest.slots.some(s => s.source && !refs.has(s.source.id + ':' + s.source.revision)) || new Set(frozenRequest.slots.filter(s => s.source).map(s => s.source.id + ':' + s.source.revision)).size !== refs.size) throw new Error('Composition must use exactly its fixed source set');
  const normalize = a => ({ project_id: a.project_id, title: a.title, width: a.width ?? 1200, height: a.height ?? 600, slots: a.slots });
  const expected = canonical(normalize(frozenRequest));
  const scope = { task_id: taskId, project_id: projectId, plan_sha256: planSha256, allowed_tools: [...FIGURE_TOOLS], fixed_sources: clone(sources),
    composition_request_sha256: sha(expected), request_key: taskId + ':composition', adopted_head_write: false };
  let sessionId = null, closed = false, executed = 0, uncertain = false, evidenceBytes = 0, pendingWrite = false;
  const routeAbort = new AbortController();
  const calls = new Map(), receipts = [];
  async function execute(name, args, exec) {
    if (closed) fail('Task tool route is closed', 'route_closed', 409);
    if (!sessionId || exec?.agent?.id !== sessionId || exec.name !== name || !identity(exec.callId) || !exec.signal || typeof exec.signal.throwIfAborted !== 'function') fail('Native task/session/call identity is unbound or foreign', 'foreign_identity', 403);
    const signal = AbortSignal.any([exec.signal, routeAbort.signal]);
    signal.throwIfAborted();
    try { if (await checkAuthority({ taskId, projectId, planSha256, scope: clone(scope), sessionId, tool: name, callId: exec.callId, signal }) === false) fail('Current task authority rejected the call', 'forbidden', 403); }
    catch (e) { throw problem(e); }
    if (closed) fail('Task tool route closed during authority check', 'route_closed', 409);
    signal.throwIfAborted();
    let encoded;
    try { encoded = canonical({ name, arguments: args }); } catch { fail('Tool arguments must be finite lossless JSON'); }
    if (Buffer.byteLength(encoded) > maxRequestBytes) fail('Tool request byte limit', 'request_limit', 413);
    const signature = sha(encoded), previous = calls.get(exec.callId);
    if (previous) {
      if (previous.signature !== signature) fail('callId is pinned to different arguments', 'call_id_conflict', 409);
      if (!previous.done) fail('Original call is still in progress; no retry', 'call_in_progress', 409, name === 'create_main_figure');
      if (previous.error) throw new FigureToolError(...previous.error);
      return clone(previous.value);
    }
    if (calls.size >= maxRequests || evidenceBytes + Buffer.byteLength(encoded) + 1024 > maxEvidenceBytes) fail('Complete tool evidence limit reached', 'evidence_limit', 409);
    const entry = { signature, done: false }; calls.set(exec.callId, entry);
    const record = { call_id: exec.callId, session_id: sessionId, name, arguments: clone(args), arguments_sha256: signature, at: new Date().toISOString(), callback_invoked: false };
    receipts.push(record); evidenceBytes += Buffer.byteLength(encoded);
    try {
      validate(args, schemas[name]);
      if (args.project_id !== projectId) fail('Tool request is outside the fixed project', 'forbidden', 403);
      if (name === 'read_figure_context' && (!Object.hasOwn(args, 'revision') || !refs.has(args.id + ':' + args.revision))) fail('Read only explicit fixed source revisions', 'forbidden', 403);
      if (name === 'create_main_figure' && (args.request_key !== taskId + ':composition' || canonical(normalize(args)) !== expected)) fail('Only the fixed unadopted task composition is permitted', 'forbidden', 403);
      if (executed >= maxToolCalls) fail('Task tool-call limit reached', 'budget_exhausted', 409);
      if (name === 'create_main_figure' && uncertain) fail('Previous write outcome is uncertain; inspect service state', 'write_outcome_uncertain', 409, true);
      if (name === 'create_main_figure' && pendingWrite) fail('Original candidate write is still in progress', 'call_in_progress', 409, true);
      executed++; record.callback_invoked = true;
      if (name === 'create_main_figure') pendingWrite = true;
      let value;
      try { value = await client.call(name, clone(args), { signal }); }
      finally { if (name === 'create_main_figure') pendingWrite = false; }
      if (!object(value)) fail('Service result must be an object', 'invalid_response', 502, name === 'create_main_figure');
      if (value.ok === false || value.isError === true || 'error' in value && 'code' in value) throw new FigureToolError(value.error || 'Service action failed', value.code || 'service_error', value.http_status ?? null, value.write_outcome_uncertain === true, value.details);
      let output;
      try { output = canonical(value); } catch { fail('Service returned invalid lossless JSON', 'invalid_response', 502, name === 'create_main_figure'); }
      if (Buffer.byteLength(output) > maxOutputBytes || evidenceBytes + Buffer.byteLength(output) + 1024 > maxEvidenceBytes) {
        record.callback_result_sha256 = sha(output); record.callback_result_bytes = Buffer.byteLength(output);
        fail('Complete tool result exceeds its byte limit; no truncation', 'response_limit', 502, name === 'create_main_figure');
      }
      evidenceBytes += Buffer.byteLength(output); entry.value = clone(value); record.result = clone(value); record.success = true;
      return clone(value);
    } catch (e) {
      let failure = problem(e, record.callback_invoked && name === 'create_main_figure');
      const originalFailure = canonical(failure.public());
      if (Buffer.byteLength(originalFailure) > 1024) {
        const p = failure.public();
        failure = new FigureToolError('Original failure detail exceeds its evidence envelope', p.code, p.http_status, p.write_outcome_uncertain,
          { original_failure_sha256: sha(originalFailure), original_failure_bytes: Buffer.byteLength(originalFailure), failure_evidence_complete: false });
      }
      const p = failure.public(); entry.error = [p.error, p.code, p.http_status, p.write_outcome_uncertain, p.details]; record.error = p; record.success = false; evidenceBytes += Buffer.byteLength(canonical(p));
      if (p.write_outcome_uncertain) uncertain = true;
      throw failure;
    } finally { entry.done = true; record.finished_at = new Date().toISOString(); }
  }
  return {
    bindSession(id) { if (closed || !identity(id) || sessionId && sessionId !== id) throw new Error('Bind only the authoritative immutable native agent ID'); sessionId = id; },
    close() { closed = true; routeAbort.abort(); },
    catalogSnapshot() { return clone(catalogEvidence); },
    nativeDefinitions() { return projected.map(d => ({ name: d.name, description: d.description, parameters: clone(d.inputSchema), timeoutMs: 15000,
      output: { schema: { type: 'object', additionalProperties: true }, render: (_args, value) => [{ type: 'text', text: canonical(value) }] },
      execute: (args, exec) => execute(d.name, args, exec),
      finalizeContent: (_exec, result) => result.isError && typeof result.error?.message === 'string' ? [{ type: 'text', text: result.error.message }] : undefined,
    })); },
    snapshot() { const value = { version: 1, feature: 'deepseek_task_figure_tools_v1', task_id: taskId, project_id: projectId, plan_sha256: planSha256, scope: clone(scope), catalog_sha256: catalogEvidence.sha256, native_declarations_sha256: catalogEvidence.native_declarations_sha256, native_schema_is_projection: true, fixed_sources: clone(sources), session_id: sessionId, closed, executed_tool_calls: executed, write_outcome_uncertain: uncertain, receipts: clone(receipts), native_execution_verified: false }; return { ...value, sha256: sha(canonical(value)) }; },
  };
}
