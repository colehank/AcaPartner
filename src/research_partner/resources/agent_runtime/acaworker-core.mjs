// Parse grammar first, then check duplicate decoded keys and finite numeric values.
// This accepts JSON syntax only; it makes no scientific-schema or quality claim.
export function strictCandidateJSON(text) {
  const value = JSON.parse(text);
  const tokens = text.match(/"(?:[^"\\]|\\.)*"|[{}\[\]:,]|true|false|null|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/gs) || [];
  let index = 0;
  const walk = () => {
    const token = tokens[index++];
    if (token === '{') {
      const keys = new Set();
      if (tokens[index] === '}') { index++; return; }
      while (true) {
        const key = JSON.parse(tokens[index++]);
        if (keys.has(key)) throw new Error('Duplicate object key: ' + key);
        keys.add(key); index++; walk();
        if (tokens[index++] === '}') break;
      }
    } else if (token === '[') {
      if (tokens[index] === ']') { index++; return; }
      while (true) { walk(); if (tokens[index++] === ']') break; }
    } else if (/^-?\d/.test(token) && !Number.isFinite(Number(token))) throw new Error('Non-finite JSON number');
  };
  walk(); return value;
}

// Local mechanics only. This module does not implement an LLM or a harness loop.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export const sha256 = value => crypto.createHash('sha256').update(value).digest('hex');
const fail = (code, detail) => { throw Object.assign(new Error(`${code}: ${detail}`), { code }); };
const boundedString = (value, bytes, label) => {
  if (typeof value !== 'string' || Buffer.byteLength(value) > bytes) fail('INVALID_TEXT', label);
  return value;
};
const readJSON = p => JSON.parse(fs.readFileSync(p, 'utf8'));
function regularFile(p) {
  const stat = fs.lstatSync(p);
  if (!stat.isFile() || stat.isSymbolicLink()) fail('NOT_REGULAR_FILE', p);
}
function inside(root, relative) {
  if (typeof relative !== 'string' || path.isAbsolute(relative) || relative.split(/[\\/]/).some(x => x === '..' || x === '.' || x === '')) fail('UNSAFE_PATH', String(relative));
  const p = path.resolve(root, relative);
  if (!p.startsWith(root + path.sep)) fail('UNSAFE_PATH', relative);
  let walk = root;
  for (const part of relative.split('/')) {
    walk = path.join(walk, part);
    if (fs.existsSync(walk) && fs.lstatSync(walk).isSymbolicLink()) fail('SYMLINK', relative);
  }
  return p;
}
function atomicJSON(p, value) {
  const tmp = `${p}.${crypto.randomUUID()}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2) + '\n', { flag: 'wx', mode: 0o600 });
  fs.renameSync(tmp, p);
}
function withLock(lock, fn) {
  try { fs.mkdirSync(lock, { mode: 0o700 }); }
  catch (e) { if (e.code === 'EEXIST') fail('BUSY_OR_INTERRUPTED', 'Existing lock must be inspected; no automatic stale-lock removal'); throw e; }
  try { return fn(); } finally { fs.rmdirSync(lock); }
}

export class Capsule {
  constructor(root) {
    this.root = fs.realpathSync(root);
    const cp = inside(this.root, 'task.json'); regularFile(cp);
    this.contract = readJSON(cp);
    this.contractHash = sha256(fs.readFileSync(cp));
    const c = this.contract;
    if (c.evidence_layout_version !== undefined && c.evidence_layout_version !== 2) fail('INVALID_CONTRACT', 'evidence_layout_version');
    this.paged = c.evidence_layout_version === 2;
    if (!/^[a-z0-9][a-z0-9_-]{0,79}$/.test(c.task_id) || !Array.isArray(c.evidence) || c.evidence.length > 30) fail('INVALID_CONTRACT', 'task_id/evidence');
    this.evidence = new Map();
    for (const e of c.evidence) {
      const idPattern = this.paged ? /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/ : /^[a-z0-9][a-z0-9_-]*$/;
      if (typeof e.id !== 'string' || !idPattern.test(e.id) || this.evidence.has(e.id) || !/^[a-f0-9]{64}$/.test(e.sha256) || !['public', 'synthetic', 'authorized_private'].includes(e.disclosure)) fail('INVALID_EVIDENCE', e.id);
      const p = inside(this.root, e.path); regularFile(p);
      if (!e.path.startsWith('evidence/') || sha256(fs.readFileSync(p)) !== e.sha256) fail('EVIDENCE_IDENTITY', e.id);
      this.evidence.set(e.id, { ...e });
    }
    for (const dir of ['outputs', 'audit', 'reviews']) {
      const p = inside(this.root, dir); fs.mkdirSync(p, { recursive: true, mode: 0o700 });
    }
  }
  check() {
    if (sha256(fs.readFileSync(inside(this.root, 'task.json'))) !== this.contractHash) fail('CONTRACT_CHANGED', 'Start a new capsule for revised scope');
  }
  task() {
    this.check();
    if (this.paged) {
      // Context can be larger than the native harness's formatted tool-result
      // allowance. It is preserved in a paged source, never silently shortened.
      const { context: _context, objective: _objective, ...catalog } = this.contract;
      const result = { ...catalog, contract_sha256: this.contractHash,
        objective_and_context_id: 'task-context',
        reading: 'Read task-context for the complete frozen objective/context and individual sources by their IDs. Continue each needed source with next_offset until complete=true. The materials bundle is an exact duplicate, not an extra source.',
        evidence: [...this.evidence.values()].map(({ path: _path, ...e }) => e), review_status: 'not_reviewed' };
      if (Buffer.byteLength(JSON.stringify(result)) > 24000) fail('CATALOG_TOO_LARGE', 'No truncated catalog returned');
      return result;
    }
    return { ...this.contract, contract_sha256: this.contractHash, evidence: [...this.evidence.values()].map(({ path: _path, ...e }) => e), review_status: 'not_reviewed' };
  }
  read(id, signal, options = {}) {
    signal?.throwIfAborted(); this.check();
    const e = this.evidence.get(id); if (!e) fail('UNKNOWN_EVIDENCE', id);
    const p = inside(this.root, e.path); regularFile(p);
    const bytes = fs.readFileSync(p);
    if (sha256(bytes) !== e.sha256) fail('EVIDENCE_CHANGED', id);
    if (bytes.length > 65536) fail('EVIDENCE_TOO_LARGE', 'Prepare an explicit smaller source excerpt');
    const text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
    if (!this.paged) {
      if (options.offset !== undefined || options.limit !== undefined) fail('LEGACY_CONTRACT', 'Original capsule returns its original whole-source result');
      return { id, sha256: e.sha256, source: e.source, text };
    }
    const chars = Array.from(text), offset = options.offset === undefined ? 0 : options.offset, limit = options.limit === undefined ? 12000 : options.limit;
    if (!Number.isSafeInteger(offset) || offset < 0 || offset > chars.length || !Number.isSafeInteger(limit) || limit < 1 || limit > 12000) fail('INVALID_PAGE', 'offset is a Unicode code-point position; limit is 1–12000 code points');
    const page = end => ({ id, sha256: e.sha256, source: e.source, offset,
      offset_unit: 'unicode_code_points', total_length: chars.length, source_bytes: bytes.length,
      next_offset: end < chars.length ? end : null, complete: end === chars.length,
      text: chars.slice(offset, end).join('') });
    let end = Math.min(chars.length, offset + limit);
    if (Buffer.byteLength(JSON.stringify(page(end))) > 24000) {
      let low = offset, high = end;
      while (low < high) {
        const mid = Math.ceil((low + high) / 2);
        if (Buffer.byteLength(JSON.stringify(page(mid))) <= 24000) low = mid; else high = mid - 1;
      }
      end = low;
    }
    if ((end === offset && offset < chars.length) || Buffer.byteLength(JSON.stringify(page(end))) > 24000) fail('PAGE_METADATA_TOO_LARGE', 'No source bytes were truncated');
    return page(end);
  }
  write(name, content, evidenceIds, signal) {
    signal?.throwIfAborted(); this.check();
    if (!/^[a-z0-9][a-z0-9_-]{0,79}\.(md|json|csv|svg)$/.test(name)) fail('ARTIFACT_NAME', 'Use a simple .md/.json/.csv/.svg basename');
    boundedString(content, 131072, 'artifact');
    if (name.endsWith('.json')) {
      try { strictCandidateJSON(content); }
      catch (error) { fail('INVALID_JSON', `Candidate JSON syntax rejected before writing or registration: ${error.message}`); }
    }
    if (!Array.isArray(evidenceIds) || evidenceIds.length > 30 || evidenceIds.some(id => !this.evidence.has(id))) fail('UNKNOWN_EVIDENCE', 'Artifact evidence references');
    for (const id of evidenceIds) this.read(id, signal);
    const p = inside(this.root, `outputs/${name}`);
    fs.writeFileSync(p, content, { flag: 'wx', mode: 0o600 });
    const result = { name, sha256: sha256(content), evidence_ids: [...new Set(evidenceIds)], status: 'candidate', contract_sha256: this.contractHash };
    const record = inside(this.root, `audit/artifact-${crypto.randomUUID()}.json`); atomicJSON(record, result);
    return result;
  }
  prepareReview(names, signal) {
    signal?.throwIfAborted(); this.check();
    if (!Array.isArray(names) || !names.length || names.length > 15 || new Set(names).size !== names.length) fail('INVALID_ARTIFACT_LIST', '1–15 distinct artifacts');
    const entries = names.map(name => {
      if (!/^[a-z0-9][a-z0-9_-]{0,79}\.(md|json|csv|svg)$/.test(name)) fail('ARTIFACT_NAME', name);
      const p = inside(this.root, `outputs/${name}`); regularFile(p);
      const bytes = fs.readFileSync(p);
      return { name, sha256: sha256(bytes), path: `artifacts/${name}`, bytes };
    });
    // Capture exact evidence bytes before writing the packet. Paths in the frozen
    // task resolve within the packet directory, independently of the live capsule.
    const evidence = [...this.evidence.values()].map(e => {
      signal?.throwIfAborted();
      const p = inside(this.root, e.path); regularFile(p);
      const bytes = fs.readFileSync(p);
      if (sha256(bytes) !== e.sha256) fail('EVIDENCE_CHANGED', e.id);
      if (bytes.length > 65536) fail('EVIDENCE_TOO_LARGE', e.id);
      return { ...e, bytes };
    });
    const contractBytes = fs.readFileSync(inside(this.root, 'task.json'));
    if (sha256(contractBytes) !== this.contractHash) fail('CONTRACT_CHANGED', 'Start a new capsule for revised scope');
    signal?.throwIfAborted();
    const reviewId = crypto.randomUUID(); const dir = inside(this.root, `reviews/${reviewId}`); fs.mkdirSync(dir, { mode: 0o700 });
    for (const e of [...entries, ...evidence]) {
      const target = inside(dir, e.path);
      fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
      fs.writeFileSync(target, e.bytes, { flag: 'wx', mode: 0o600 });
    }
    fs.writeFileSync(path.join(dir, 'task.json'), contractBytes, { flag: 'wx', mode: 0o600 });
    // The frozen review handoff contains science/candidates, never the author's audit diary.
    const packet = { schema_version: 2, review_id: reviewId, paths_relative_to: 'packet_directory', task: this.contract, task_path: 'task.json', contract_sha256: this.contractHash, artifacts: entries.map(({ bytes, ...e }) => e), status: 'pending_independent_review', excluded_live_directories: ['audit'], coordinator_preflight_required: ['embedded author self-evaluation', 'repair diary', 'previous verdicts'], scientific_selection_history_must_be_retained: true, isolation_certified: false, reviewed: false };
    atomicJSON(path.join(dir, 'packet.json'), packet);
    return { review_id: reviewId, packet: path.join(dir, 'packet.json'), status: packet.status, reviewed: false };
  }
  observe(observation, evidenceId, signal) {
    signal?.throwIfAborted(); this.check(); boundedString(observation, 8192, 'observation');
    if (!this.evidence.has(evidenceId)) fail('UNKNOWN_EVIDENCE', evidenceId);
    const record = { origin: 'agent_observation', observation, evidence_id: evidenceId, at: new Date().toISOString(), tested_across_tasks: false, user_approval: false };
    atomicJSON(inside(this.root, `audit/observation-${crypto.randomUUID()}.json`), record);
    return record;
  }
}

export class BudgetLedger {
  constructor(controlRoot, contractHash) {
    this.root = fs.realpathSync(controlRoot); this.contractHash = contractHash;
    if (fs.statSync(this.root).mode & 0o077) fail('CONTROL_NOT_PRIVATE', this.root);
    this.authorizationPath = inside(this.root, 'authorization.json');
    this.ledgerPath = inside(this.root, 'usage.json');
    this.lock = inside(this.root, 'budget.lock');
    this.lastLedger = null;
    if (fs.existsSync(this.ledgerPath)) { regularFile(this.ledgerPath); this.lastLedger = readJSON(this.ledgerPath); }
  }
  reserve(options, disclosureClasses) {
    return withLock(this.lock, () => {
      regularFile(this.authorizationPath); const a = readJSON(this.authorizationPath);
      const expiryValid = (a.expires_at === null && a.no_expiry_authorized === true) || Date.parse(a.expires_at) > Date.now();
      if (a.approved !== true || a.contract_sha256 !== this.contractHash || !a.authorization_reference || !expiryValid) fail('AUTHORIZATION_REQUIRED', 'Explicit current scope and applicable expiration');
      if (options.provider !== 'deepseek-official' || options.model !== a.model || options.purpose) fail('MODEL_SCOPE', 'Only the authorized main task route');
      if (disclosureClasses.some(c => !a.disclosure_classes?.includes(c))) fail('DISCLOSURE_SCOPE', 'Evidence class not authorized');
      const inspectBlocks = blocks => {
        for (const block of blocks || []) {
          if (['image', 'file'].includes(block.type)) fail('MODALITY_SCOPE', 'This initial capsule is text-only');
          if (block.type === 'tool-result') inspectBlocks(block.content);
        }
      };
      for (const message of options.messages || []) inspectBlocks(message.content);
      if (!Number.isSafeInteger(options.maxTokens) || options.maxTokens < 1 || options.maxTokens > a.max_output_tokens) fail('OUTPUT_CAP', 'Resolved maxTokens must fit the authorized cap');
      const bytes = Buffer.byteLength(JSON.stringify({ messages: options.messages, system: options.system, tools: options.tools }));
      if (bytes > a.max_request_bytes) fail('CONTEXT_CAP', 'Prepare a bounded continuation instead of silently dropping evidence');
      const rate = a.rates_usd_per_million;
      const uncapped = a.budget_mode === 'uncapped' && a.uncapped_spending_authorized === true && a.budget_usd === null;
      const finiteBudget = (a.budget_mode === undefined || a.budget_mode === 'capped') && Number.isFinite(a.budget_usd) && a.budget_usd > 0;
      if (!(uncapped || finiteBudget) || ![a.max_requests, a.max_output_tokens, a.max_request_bytes, rate?.input_miss, rate?.output].every(v => Number.isFinite(v) && v > 0)) fail('INVALID_BUDGET', 'Explicit capped or uncapped spending and finite per-task execution bounds required');
      // UTF-8 bytes plus explicit protocol allowance is a conservative planning proxy,
      // NOT a provider-enforced wallet cap or an authoritative tokenizer.
      const reserved = ((bytes + 8192) * rate.input_miss + options.maxTokens * rate.output) / 1e6;
      if (fs.existsSync(this.ledgerPath)) regularFile(this.ledgerPath);
      else if (this.lastLedger) fail('LEDGER_SCOPE', 'Previously observed accounting is missing; no fresh allowance');
      const ledger = fs.existsSync(this.ledgerPath) ? readJSON(this.ledgerPath) : { contract_sha256: this.contractHash, calls: [], reserved_usd: 0 };
      if (ledger.contract_sha256 !== this.contractHash) fail('LEDGER_SCOPE', 'New contract requires a separate control directory');
      if (!Array.isArray(ledger.calls) || !Number.isFinite(ledger.reserved_usd) || ledger.reserved_usd < 0) fail('LEDGER_SCOPE', 'Invalid reservation history');
      if (this.lastLedger) {
        const immutable = call => Object.fromEntries(Object.entries(call).filter(([key]) => !['usage', 'finish', 'status', 'conservative_usage_estimate_usd'].includes(key)).sort(([a], [b]) => a.localeCompare(b)));
        if (ledger.calls.length < this.lastLedger.calls.length || ledger.reserved_usd < this.lastLedger.reserved_usd || this.lastLedger.calls.some((call, i) => JSON.stringify(immutable(call)) !== JSON.stringify(immutable(ledger.calls[i])))) fail('LEDGER_SCOPE', 'Previously observed reservations cannot be replaced or removed');
      }
      if (ledger.calls.length >= a.max_requests || (!uncapped && ledger.reserved_usd + reserved > a.budget_usd)) fail('BUDGET_EXHAUSTED', 'No dispatch; inspect the per-task request envelope and any authorized spending cap');
      const call = { id: crypto.randomUUID(), at: new Date().toISOString(), model: options.model, session_id: options.sessionId ?? null, request_sha256: sha256(JSON.stringify(options.messages)), request_bytes: bytes, max_output_tokens: options.maxTokens, reserved_usd: reserved, budget_mode: uncapped ? 'uncapped' : 'capped', authorization_reference: a.authorization_reference, status: 'reserved_billing_unknown', rates: rate, actual_provider_bill_usd: null };
      ledger.calls.push(call); ledger.reserved_usd += reserved; atomicJSON(this.ledgerPath, ledger); this.lastLedger = structuredClone(ledger);
      return call.id;
    });
  }
  finish(id, usage, finishReason) {
    return withLock(this.lock, () => {
      regularFile(this.ledgerPath);
      const ledger = readJSON(this.ledgerPath); const call = ledger.calls.find(x => x.id === id);
      if (!call) fail('UNKNOWN_RESERVATION', id);
      const numeric = usage && ['inputTokens', 'outputTokens'].every(k => Number.isFinite(usage[k]) && usage[k] >= 0);
      call.usage = numeric ? usage : null;
      call.finish = finishReason ?? null;
      call.status = numeric && ['stop', 'tool-calls', 'max-tokens'].includes(finishReason?.kind) ? 'usage_received_bill_unverified' : 'finished_billing_unknown';
      if (numeric) {
        const input = usage.inputTokens + (usage.cacheReadTokens || 0) + (usage.cacheWriteTokens || 0);
        call.conservative_usage_estimate_usd = (input * call.rates.input_miss + usage.outputTokens * call.rates.output) / 1e6;
      }
      // Never release a reservation after a timeout, error, or incomplete usage.
      atomicJSON(this.ledgerPath, ledger); return call;
    });
  }
}
