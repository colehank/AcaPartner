// Explicit task-scoped Harness feature. No model loop, credentials file, agent
// creation, native resume, adoption, scientific approval or permission grants.
import fs from 'node:fs';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { assertSupportedJsonSchema } from '@deepseek-ai/dsh-tools';
import { BudgetLedger, strictCandidateJSON } from './acaworker-core.mjs';
import { FIGURE_TOOLS, FigureToolError, createFigureTools, createWorkbenchBridge } from './figure-tools.mjs';

export const name = 'acaworker-figure-task';
export const inject = ['tools', 'llm'];
export const AUTHORITY_CONTRACT = 'task_lease_parent_budget_egress_v1';
const FEATURE = 'deepseek_task_figure_tools_v1', TRANSPORT = 'deepseek_harness_native';
const LOCK = 'a85eca55df1d7f4659acfec7c563c00c01c649f3ca1c2b76785de131acc1cdb2';
const sha = value => createHash('sha256').update(value).digest('hex');
const json = value => JSON.stringify(value);
function canonical(value, depth = 0) {
  if (depth > 64) throw new Error('JSON depth bound');
  if (value === null || typeof value === 'boolean') return JSON.stringify(value);
  if (typeof value === 'number' && Number.isFinite(value)) return JSON.stringify(value);
  if (typeof value === 'string' && !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)) return JSON.stringify(value);
  if (Array.isArray(value) && Object.keys(value).length === value.length) return '[' + value.map(v => canonical(v, depth + 1)).join(',') + ']';
  if (value && Object.getPrototypeOf(value) === Object.prototype) return '{' + Object.keys(value).sort().map(k => JSON.stringify(k) + ':' + canonical(value[k], depth + 1)).join(',') + '}';
  throw new Error('Finite lossless JSON required');
}
const clone = value => strictCandidateJSON(canonical(value));
const reject = (message, code = 'authorization_required', status = 403) => { throw new FigureToolError(message, code, status, false); };
const finite = (value, cap) => typeof value === 'number' && Number.isFinite(value) && value > 0 && value <= cap;
const integer = (value, cap) => Number.isSafeInteger(value) && value > 0 && value <= cap;
const digest = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const reference = value => typeof value === 'string' && value.trim().length > 0 && value.length <= 4096 && value.trim() !== 'User authorized provider in local config';

/** Pure profile validation: may load for inspection while approved=false. */
export function validateFigureProfile(value) {
  let config; try { config = clone(value); } catch { reject('Profile must be finite lossless JSON', 'invalid_configuration', 400); }
  const d = config.definition;
  if (config.feature !== FEATURE || config.transport !== TRANSPORT || !d || d.feature !== FEATURE || d.figure_profile !== undefined || d.route !== 'deepseek_harness' || d.transport !== TRANSPORT || d.provider !== 'deepseek-official' || d.runtime_lock_sha256 !== LOCK || !digest(d.sha256) || d.authority_contract !== AUTHORITY_CONTRACT || d.fresh_only !== true || d.retry_max !== 0 || d.max_tool_calls !== 8 || d.native_context_window !== 262144 || config.resumeSessionId || config.resume_session_id || config.checkpoint || config.resumed_from) reject('Exact locked fresh-only figure profile required', 'invalid_configuration', 400);
  if (!reference(d.authorization_reference) || !reference(d.model) || !integer(d.max_requests, 4) || !integer(d.max_output_tokens, 8192) || !integer(d.max_request_bytes, 262144) || !finite(d.timeout_seconds, 600) || !finite(d.deadline, Infinity) || d.budget_mode !== 'capped' || !finite(d.budget_usd, Infinity) || !reference(d.pricing_reference) || !finite(d.rates_usd_per_million?.input_miss, Infinity) || !finite(d.rates_usd_per_million?.output, Infinity)) reject('Current reference and explicit bounded model/request/context/time/USD required', 'invalid_configuration', 400);
  if (sha(canonical(Object.fromEntries(Object.entries(d).filter(([k]) => k !== 'sha256')))) !== d.sha256) reject('Frozen provider definition changed', 'integrity', 409);
  if (!finite(config.deadlineMs, d.deadline * 1000) || config.deadlineMs > Date.now() + d.timeout_seconds * 1000 + 1000 || !digest(config.contractSha256) || !digest(config.egressSha256)) reject('Current finite Task deadline and exact contract/egress required', 'invalid_configuration', 400);
  for (const filename of ['figure-plugin.mjs', 'figure-tools.mjs', 'acaworker-core.mjs', 'native-session-driver.mjs']) {
    if (!digest(d.modules?.[filename]) || sha(fs.readFileSync(path.join(import.meta.dirname, filename))) !== d.modules[filename]) reject('Frozen module identity changed', 'integrity', 409);
  }
  return config;
}

/** A real local Workbench bridge. The mandatory host check must cover current
 * egress, owner/source access and Task/parent authority, not a constant true.
 * GET state independently checks the existing HTTP lease/parent gate. Its
 * body is discarded and is neither model context nor evidence of agent reading.
 */
export function createTaskBridge({ origin, getAuthorization, checkCurrentAuthority, binding, fetchImpl = globalThis.fetch }) {
  if (typeof checkCurrentAuthority !== 'function' || binding?.authorityContract !== AUTHORITY_CONTRACT) reject('Current full host authority probe is not provided', 'provider_missing', 503);
  const pinned = clone(binding);
  const client = createWorkbenchBridge({ origin, getAuthorization, fetchImpl, timeoutMs: 1000 });
  return { ...pinned, client, async checkAuthority(request) {
    for (const key of ['taskId', 'projectId', 'planSha256', 'egressSha256']) if (request[key] !== pinned[key]) reject('Foreign Task authority probe', 'forbidden', 403);
    request.signal?.throwIfAborted();
    if (await checkCurrentAuthority(request) !== true) reject('Current complete Task/egress/parent authority refused', 'forbidden', 403);
    request.signal?.throwIfAborted();
    const authorization = await getAuthorization();
    if (typeof authorization !== 'string' || !/^Bearer [\x21-\x7E]{24,4096}$/.test(authorization)) reject('Task bearer unavailable', 'credentials_unavailable', 503);
    let response;
    try {
      response = await fetchImpl(new URL('/api/state', origin).href, { headers: { Authorization: authorization, Accept: 'application/json' }, redirect: 'manual', signal: request.signal ? AbortSignal.any([request.signal, AbortSignal.timeout(1000)]) : AbortSignal.timeout(1000) });
      if (!response.ok) {
        let p = {}; const chunks = []; let bytes = 0;
        const reader = response.body?.getReader();
        if (reader) try { while (true) { const { done, value } = await reader.read(); if (done) break; bytes += value.byteLength; if (bytes > 65536) reject('Complete authority error exceeds limit', 'response_limit', 502); chunks.push(Buffer.from(value)); } p = strictCandidateJSON(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))); } finally { await reader.cancel().catch(() => {}); }
        throw new FigureToolError(typeof p.error === 'string' ? p.error : 'Current HTTP Task authority refused', typeof p.code === 'string' ? p.code : 'http_error', response.status, p.write_outcome_uncertain === true || p.details?.write_outcome_uncertain === true, p.details);
      }
      await response.body?.cancel();
    } catch (error) {
      if (error instanceof FigureToolError) throw error;
      throw new FigureToolError('Current authority HTTP probe failed; no tool/model dispatch', 'transport_error', null, false);
    }
    request.signal?.throwIfAborted();
    // Authorization may change while the pure HTTP read is in flight.
    if (await checkCurrentAuthority(request) !== true) reject('Task authority changed during HTTP probe', 'forbidden', 403);
    return true;
  } };
}

export function apply(ctx, supplied) {
  const config = validateFigureProfile(supplied), d = config.definition;
  const budget = new BudgetLedger(config.controlRoot, config.contractSha256);
  const stop = new AbortController(), created = new WeakSet(), ready = new Set(), streams = [];
  let agent = null, bindingProof = null, closed = false, streaming = false, streamUnknown = false;
  const live = () => { if (closed || stop.signal.aborted) reject('Task figure route is closed', 'route_closed', 409); if (Date.now() >= config.deadlineMs) reject('Original Task/parent time bound reached', 'budget_exhausted', 409); };
  function authorization() {
    live(); const p = path.join(budget.root, 'authorization.json'), stat = fs.lstatSync(p);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.mode & 0o077) reject('Authorization must remain private regular JSON');
    const a = strictCandidateJSON(fs.readFileSync(p, 'utf8'));
    const fields = { authorization_reference: d.authorization_reference, contract_sha256: config.contractSha256, model: d.model, budget_mode: 'capped', budget_usd: d.budget_usd, max_requests: d.max_requests, max_output_tokens: d.max_output_tokens, max_request_bytes: d.max_request_bytes, rates_usd_per_million: d.rates_usd_per_million, pricing_reference: d.pricing_reference, task_id: config.taskId, project_id: config.projectId, plan_sha256: config.planSha256, egress_sha256: config.egressSha256, disclosure_classes: ['fixed_figure_context'] };
    if (a.approved !== true || a.uncapped_spending_authorized !== false || a.no_expiry_authorized !== false || !Number.isFinite(Date.parse(a.expires_at)) || Date.parse(a.expires_at) <= Date.now() || Date.parse(a.expires_at) > config.deadlineMs || Object.entries(fields).some(([k, v]) => !Object.hasOwn(a, k) || canonical(a[k]) !== canonical(v))) reject('Current Task/account/egress/finite spending authorization missing or changed');
  }
  function host() {
    const h = ctx.get('figureTaskBridge');
    if (h?.authorityContract !== AUTHORITY_CONTRACT || h.taskId !== config.taskId || h.projectId !== config.projectId || h.planSha256 !== config.planSha256 || h.egressSha256 !== config.egressSha256 || typeof h.checkAuthority !== 'function' || typeof h.client?.call !== 'function') reject('Current task-bound bridge with full authority not available', 'provider_missing', 503);
    return h;
  }
  async function authority(request) {
    authorization();
    if (!agent || request.sessionId !== agent.id || !ready.has(agent.id)) reject('Native identity/catalog is not authoritatively bound', 'foreign_identity', 403);
    const h = host();
    if (await h.checkAuthority({ ...request, egressSha256: config.egressSha256 }) !== true) reject('Current host authority refused', 'forbidden', 403);
    authorization();
    if (h !== host()) reject('Task bridge changed during authority probe', 'forbidden', 403);
    return true;
  }
  const tools = createFigureTools({ taskId: config.taskId, projectId: config.projectId, planSha256: config.planSha256, fixedSources: config.fixedSources, request: config.request, catalogJson: config.catalogJson,
    client: { call: (...args) => host().client.call(...args) }, checkAuthority: authority, maxToolCalls: 8 });
  const catalog = tools.catalogSnapshot();
  if (catalog.sha256 !== d.catalog_sha256 || catalog.native_declarations_sha256 !== d.native_declarations_sha256 || d.native_schema_is_projection !== true) reject('Full catalog or mechanical projection changed', 'integrity', 409);
  const definitions = tools.nativeDefinitions(), expected = definitions.map(({ name, description, parameters }) => ({ name, description, parameters }));
  // SystemPrompt orders declarations by name. Compare the complete objects,
  // including every annotation and unknown field; retain the outgoing order
  // unchanged in the request and its evidence. Duplicate names never match.
  const sameDeclarations = actual => Array.isArray(actual) && actual.length === expected.length
    && actual.every(item => item && typeof item.name === 'string')
    && new Set(actual.map(item => item.name)).size === actual.length
    && canonical([...actual].sort((a, b) => a.name.localeCompare(b.name)))
      === canonical([...expected].sort((a, b) => a.name.localeCompare(b.name)));
  const verifyCatalog = a => {
    if (canonical(ctx.tools.schemas(a)) !== canonical(expected)) reject('Native visible catalog differs from the exact two frozen declarations', 'integrity', 409);
  };
  // Installed defineTool takes an implicit property-map, not a raw JSON
  // schema. The public registry accepts these already projected definitions;
  // their bodies still validate the complete original catalog, including bounds.
  for (const definition of definitions) { assertSupportedJsonSchema(definition.parameters); ctx.tools.register(definition); }
  ctx.tools.guard(exec => !FIGURE_TOOLS.includes(exec.name) || !agent || exec.agent !== agent || !ready.has(agent.id) ? 'Only the authoritatively bound Task agent and its two figure tools may execute.' : undefined);
  ctx.on('agent/created', ({ agent: a }) => { a.ctx.tools.restrict({ allow: [...FIGURE_TOOLS] }); verifyCatalog(a); created.add(a); ready.add(a.id); });
  ctx.on('agent/disposed', ({ agent: a }) => { ready.delete(a.id); if (a === agent) { closed = true; stop.abort(); tools.close(); } });
  const service = {
    bindAgent(a, proof) {
      live(); host();
      if (budget.lastLedger?.calls?.length) reject('Existing stream history requires zero-call inspection; no new agent or implicit resume', 'provider_checkpoint_missing', 409);
      if (!created.has(a) || !ready.has(a.id) || typeof a.cancel !== 'function' || agent && agent !== a || proof?.native_api !== 'agents.create' || proof.resumed_from !== null) reject('Bind only the authoritative fresh agents.create return with native cancellation; never implicit resume', 'foreign_identity', 403);
      verifyCatalog(a); tools.bindSession(a.id); agent = a; bindingProof = { native_api: 'agents.create', resumed_from: null, identity_source: 'authoritative_host_return_after_agent_created' };
    },
    close() { closed = true; stop.abort(); tools.close(); },
    snapshot() { return { feature: FEATURE, transport: TRANSPORT, definition_sha256: d.sha256, task_id: config.taskId, project_id: config.projectId, plan_sha256: config.planSha256, egress_sha256: config.egressSha256, session_id: agent?.id ?? null, binding_proof: bindingProof, streams: clone(streams), stream_outcome_unknown: streamUnknown, catalog: tools.catalogSnapshot(), tools: tools.snapshot(), native_execution_verified: false }; },
  };
  ctx.provide('figureTaskTools', service);
  ctx.effect(() => () => service.close());
  ctx.on('llm/stream', (options, next) => (async function* () {
    live();
    if (!agent || options.sessionId !== agent.id || !ready.has(agent.id) || options.provider !== 'deepseek-official' || options.model !== d.model || options.purpose || !integer(options.maxTokens, d.max_output_tokens)) reject('Unbound/foreign/auxiliary model request refused', 'model_scope', 403);
    if (streaming || streamUnknown) reject('Previous stream is busy or unknown; no retry/resume', 'provider_checkpoint_missing', 409);
    verifyCatalog(agent);
    if (!sameDeclarations(options.tools)) reject('Outgoing native tool catalog changed', 'integrity', 409);
    const originalSignal = options.signal;
    const signal = AbortSignal.any([stop.signal, AbortSignal.timeout(Math.max(1, Math.floor(config.deadlineMs - Date.now()))), ...(originalSignal ? [originalSignal] : [])]);
    const requestPayload = () => ({ messages: options.messages, ...(options.system === undefined ? {} : { system: options.system }), tools: options.tools });
    let request;
    try { canonical(requestPayload()); request = json(requestPayload()); } catch { reject('Model input must remain complete finite Unicode JSON', 'invalid_arguments', 400); }
    if (Buffer.byteLength(request) > d.max_request_bytes) reject('Complete request exceeds explicit context bound; no truncation', 'context_cap', 413);
    // The installed loop freezes options and Cordis next() captures them.
    // Cancel through the bound native Agent, which aborts that original signal;
    // replacing next's arguments or mutating options would not be valid here.
    const cancelNative = () => agent.cancel({ kind: 'hook', reason: 'Task figure request authority or time ended' });
    signal.addEventListener('abort', cancelNative, { once: true });
    streaming = true; let id = null, usage = null, finish = null, record = null;
    try {
      await authority({ taskId: config.taskId, projectId: config.projectId, planSha256: config.planSha256, sessionId: agent.id, tool: null, callId: null, signal });
      signal.throwIfAborted();
      if (request !== json(requestPayload()) || options.sessionId !== agent.id || options.provider !== 'deepseek-official' || options.model !== d.model || !integer(options.maxTokens, d.max_output_tokens) || options.purpose) reject('Model request changed during authority probe', 'integrity', 409);
      id = budget.reserve(options, ['fixed_figure_context']);
      record = { request_id: id, session_id: agent.id, request_json_utf8: request, request_sha256: sha(request), started_at: new Date().toISOString(), status: 'reserved_billing_unknown', usage: null, finish: null }; streams.push(record);
      for await (const chunk of next()) {
        signal.throwIfAborted(); live();
        if (chunk.type === 'usage') usage = clone(chunk.usage);
        if (chunk.type === 'finish') finish = clone(chunk.reason);
        yield chunk;
      }
      signal.throwIfAborted();
      if (!['stop', 'tool-calls', 'max-tokens'].includes(finish?.kind)) { streamUnknown = true; reject('Native stream ended without a known finish; inspect original evidence', 'provider_checkpoint_missing', 409); }
      record.status = 'stream_returned_bill_unverified';
    } catch (error) {
      if (id) { streamUnknown = true; record.status = 'stream_unknown_no_retry'; }
      throw error;
    } finally {
      signal.removeEventListener('abort', cancelNative); streaming = false;
      if (id) { record.usage = usage; record.finish = finish; record.local_finished_at = new Date().toISOString(); budget.finish(id, usage, finish); }
    }
  })());
}
