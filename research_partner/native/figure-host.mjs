// Host-only current authority probe. No Agent, model, credential-file access,
// external API, authorization grant, resume or permission expansion.
import { AUTHORITY_CONTRACT, createTaskBridge } from './figure-plugin.mjs';
import { FigureToolError } from './figure-tools.mjs';
import { strictCandidateJSON } from './acaworker-core.mjs';

export const MAX_AUTHORITY_ERROR_BYTES = 65536;
export const MAX_AUTHORITY_TIMEOUT_MS = 1000;
const HEADERS = Object.freeze({ taskId: 'X-Research-Partner-Task', projectId: 'X-Research-Partner-Project', planSha256: 'X-Research-Partner-Plan', egressSha256: 'X-Research-Partner-Egress' });
const object = v => v !== null && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype;
const fail = (message, code, status = 403) => { throw new FigureToolError(message, code, status, false); };
function stopped(signal) {
  if (signal.reason?.name === 'TimeoutError') fail('Current authority probe timed out; no model/tool dispatch', 'authority_timeout', 504);
  fail('Current authority probe cancelled; no model/tool dispatch', 'cancelled', 409);
}
async function bounded(promise, signal) {
  if (signal.aborted) { Promise.resolve(promise).catch(() => {}); stopped(signal); }
  let listener;
  const interrupted = new Promise((_, reject) => {
    listener = () => { try { stopped(signal); } catch (error) { reject(error); } };
    signal.addEventListener('abort', listener, { once: true });
  });
  try { return await Promise.race([promise, interrupted]); }
  finally { signal.removeEventListener('abort', listener); }
}

/** Root may provide this result as figureTaskBridge. A Bearer string is only
 * transport input: true requires a real current gate response whose four
 * server-checked identities equal the immutable task binding. The existing
 * bridge performs before/after checks; all three GET probes are fenced.
 * Its client retains the existing private CSRF read/action contract.
 */
export function createFigureTaskHost({ origin, binding, getAuthorization, fetchImpl = globalThis.fetch, timeoutMs = 1000, maxErrorBytes = 65536 }) {
  let url;
  try { url = new URL(origin); } catch { fail('Exact loopback origin required', 'invalid_configuration', 400); }
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname) || !url.port || url.username || url.password || url.pathname !== '/' || url.search || url.hash || typeof getAuthorization !== 'function' || typeof fetchImpl !== 'function') fail('Exact loopback origin and host callbacks required', 'invalid_configuration', 400);
  if (!object(binding) || Object.keys(binding).length !== 5 || binding.authorityContract !== AUTHORITY_CONTRACT || !['taskId', 'projectId'].every(k => typeof binding[k] === 'string' && /^[A-Za-z0-9_.:-]{1,200}$/.test(binding[k])) || !['planSha256', 'egressSha256'].every(k => typeof binding[k] === 'string' && /^[a-f0-9]{64}$/.test(binding[k]))) fail('Exact fixed Task/project/plan/egress binding required', 'invalid_configuration', 400);
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > MAX_AUTHORITY_TIMEOUT_MS || !Number.isSafeInteger(maxErrorBytes) || maxErrorBytes < 1 || maxErrorBytes > MAX_AUTHORITY_ERROR_BYTES) fail('Bounded authority time/error bytes required', 'invalid_configuration', 400);
  const fixed = Object.freeze({ ...binding });
  const authorization = async () => {
    const value = await bounded(Promise.resolve().then(getAuthorization), AbortSignal.timeout(timeoutMs));
    if (typeof value !== 'string' || !/^Bearer [\x21-\x7E]{24,4096}$/.test(value)) fail('Task bearer unavailable', 'credentials_unavailable', 503);
    return value;
  };
  async function cancel(body, signal, bestEffort = false) {
    try { if (body) await bounded(Promise.resolve().then(() => body.cancel()), signal); }
    catch (error) {
      if (bestEffort) return;
      if (error instanceof FigureToolError) throw error;
      fail('Successful authority body could not be cancelled', 'transport_error', null);
    }
  }
  async function errorResponse(response, signal) {
    const reader = response.body?.getReader();
    if (!reader) fail('Authority error has no complete JSON body', 'invalid_response', response.status);
    const chunks = []; let count = 0;
    try {
      while (true) {
        const { done, value } = await bounded(reader.read(), signal);
        if (done) break;
        count += value.byteLength;
        if (count > maxErrorBytes) fail('Complete authority error exceeds byte limit; no truncation', 'response_limit', response.status);
        chunks.push(Buffer.from(value));
      }
    } finally { try { await bounded(reader.cancel(), signal); } catch {} }
    let error;
    try { error = strictCandidateJSON(new TextDecoder('utf-8', { fatal: true }).decode(Buffer.concat(chunks))); }
    catch { fail('Authority error is not complete lossless JSON', 'invalid_response', response.status); }
    if (!object(error)) fail('Authority error must be a JSON object', 'invalid_response', response.status);
    throw new FigureToolError(typeof error.error === 'string' ? error.error : 'Current HTTP authority refused', typeof error.code === 'string' ? error.code : 'http_error', response.status,
      error.write_outcome_uncertain === true || error.details?.write_outcome_uncertain === true, error.details);
  }
  async function checkedFetch(input, options = {}) {
    const target = new URL(input);
    if (target.origin !== url.origin) fail('Foreign HTTP origin refused', 'forbidden');
    // Domain writes retain the existing Workbench bridge's attempted-write
    // uncertainty/timeout handling, rather than a read-only probe error.
    if (target.pathname !== '/api/state') return fetchImpl(input, { ...options, redirect: 'manual' });
    const signal = AbortSignal.any([AbortSignal.timeout(timeoutMs), ...(options.signal ? [options.signal] : [])]);
    let response;
    try { response = await bounded(Promise.resolve().then(() => fetchImpl(input, { ...options, redirect: 'manual', signal })), signal); }
    catch (error) { if (error instanceof FigureToolError) throw error; throw new FigureToolError('Current authority HTTP transport failed', 'transport_error', null, false); }
    if (target.search || (options.method ?? 'GET') !== 'GET') { await cancel(response.body, signal, true); fail('Only the exact read-only authority endpoint is permitted', 'forbidden'); }
    if (!response.ok) return errorResponse(response, signal);
    for (const [key, header] of Object.entries(HEADERS)) {
      if (response.headers.get(header) !== fixed[key]) {
        await cancel(response.body, signal, true);
        fail('Current authority response has missing or foreign ' + key, 'foreign_identity');
      }
    }
    return response;
  }
  async function checkCurrentAuthority(request) {
    for (const key of Object.keys(HEADERS)) if (request[key] !== fixed[key]) fail('Foreign Task authority request', 'foreign_identity');
    const signal = AbortSignal.any([AbortSignal.timeout(timeoutMs), ...(request.signal ? [request.signal] : [])]);
    const bearer = await bounded(authorization(), signal);
    const response = await checkedFetch(url.origin + '/api/state', { headers: { Authorization: bearer, Accept: 'application/json' }, signal });
    await cancel(response.body, signal);
    if (signal.aborted) stopped(signal);
    return true;
  }
  const bridge = createTaskBridge({ origin: url.origin, binding: fixed, getAuthorization: authorization, checkCurrentAuthority, fetchImpl: checkedFetch });
  return Object.freeze({ ...bridge, async checkAuthority(request) {
    const signal = AbortSignal.any([AbortSignal.timeout(timeoutMs), ...(request?.signal ? [request.signal] : [])]);
    if (signal.aborted) stopped(signal);
    return bounded(Promise.resolve().then(() => bridge.checkAuthority({ ...request, signal })), signal);
  } });
}
