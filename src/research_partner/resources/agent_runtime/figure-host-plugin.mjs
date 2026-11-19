// Host service only. It loads the fixed factory, reads one root-designated
// Task bearer file, and grants no Agent, API, model, file-write or resume path.
import fs from 'node:fs';
import path from 'node:path';
import { createFigureTaskHost } from './figure-host.mjs';
import { FigureToolError } from './figure-tools.mjs';

export const name = 'acaworker-figure-task-host';
export const inject = [];
export const MAX_TASK_BEARER_BYTES = 4098; // 4096 token bytes + one optional CRLF.
const keys = ['taskId', 'projectId', 'planSha256', 'egressSha256', 'authorityContract', 'origin', 'taskBearerFile'];
const fail = (message, code = 'credentials_unavailable', status = 503) => { throw new FigureToolError(message, code, status, false); };
const object = v => v !== null && typeof v === 'object' && !Array.isArray(v) && Object.getPrototypeOf(v) === Object.prototype;
const same = (a, b) => ['dev', 'ino', 'mode', 'uid', 'size', 'mtimeNs', 'ctimeNs'].every(k => a[k] === b[k]);
const privateFile = stat => stat.isFile() && !stat.isSymbolicLink() && (stat.mode & 0o777n) === 0o600n && stat.uid === BigInt(process.geteuid()) && stat.size > 0n && stat.size <= BigInt(MAX_TASK_BEARER_BYTES);

function parents(filename) {
  for (let dir = path.dirname(filename); ; dir = path.dirname(dir)) {
    const stat = fs.lstatSync(dir);
    if (!stat.isDirectory() || stat.isSymbolicLink()) throw new Error('Unsafe Task path');
    if (dir === path.dirname(dir)) return;
  }
}
function readTaskBearer(filename) {
  let fd; const bytes = Buffer.alloc(MAX_TASK_BEARER_BYTES + 1);
  try {
    parents(filename);
    const before = fs.lstatSync(filename, { bigint: true });
    if (!privateFile(before)) throw new Error('Invalid Task file');
    fd = fs.openSync(filename, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
    const opened = fs.fstatSync(fd, { bigint: true });
    if (!privateFile(opened) || !same(before, opened)) throw new Error('Changed Task file');
    let count = 0;
    while (count < bytes.length) {
      const read = fs.readSync(fd, bytes, count, bytes.length - count, null);
      if (read === 0) break;
      count += read;
    }
    if (count > MAX_TASK_BEARER_BYTES || count !== Number(opened.size)) throw new Error('Task bytes exceed bound or changed');
    const after = fs.fstatSync(fd, { bigint: true }), current = fs.lstatSync(filename, { bigint: true });
    parents(filename);
    if (!privateFile(after) || !privateFile(current) || !same(opened, after) || !same(opened, current)) throw new Error('Task file changed during read');
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(0, count));
    const token = text.endsWith('\r\n') ? text.slice(0, -2) : text.endsWith('\n') ? text.slice(0, -1) : text;
    if (/^[\x21-\x7E]{24,4096}$/.exec(token)?.[0] !== token) throw new Error('Invalid Task bearer bytes');
    return 'Bearer ' + token;
  } catch { fail('Current private Task bearer file is unavailable or invalid'); }
  finally {
    bytes.fill(0);
    if (fd !== undefined) try { fs.closeSync(fd); }
    catch { fail('Current private Task bearer descriptor could not be closed'); }
  }
}

export function apply(ctx, supplied) {
  if (!object(supplied) || Object.keys(supplied).length !== keys.length || keys.some(k => !Object.hasOwn(supplied, k)) || typeof supplied.taskBearerFile !== 'string' || supplied.taskBearerFile.length > 4096 || supplied.taskBearerFile.includes('\0') || !path.isAbsolute(supplied.taskBearerFile) || path.normalize(supplied.taskBearerFile) !== supplied.taskBearerFile) fail('Exact task host configuration and literal absolute Task file required', 'invalid_configuration', 400);
  if (typeof ctx?.provide !== 'function' || typeof ctx?.effect !== 'function') fail('Scoped host context is unavailable', 'provider_missing');
  if (ctx.get?.('figureTaskBridge') != null) fail('A Task bridge is already provided in this scope', 'provider_conflict', 409);
  const config = { ...supplied }, stop = new AbortController(); let closed = false;
  const live = () => { if (closed) fail('Task host scope has been disposed', 'route_closed', 409); };
  const host = createFigureTaskHost({ origin: config.origin,
    binding: Object.fromEntries(keys.slice(0, 5).map(k => [k, config[k]])),
    getAuthorization: () => { live(); return readTaskBearer(config.taskBearerFile); } });
  const signal = suppliedSignal => AbortSignal.any([stop.signal, ...(suppliedSignal ? [suppliedSignal] : [])]);
  const bridge = Object.freeze({ ...host,
    async checkAuthority(request) { live(); return host.checkAuthority({ ...request, signal: signal(request?.signal) }); },
    client: Object.freeze({ async call(tool, args, options = {}) { live(); return host.client.call(tool, args, { ...options, signal: signal(options.signal) }); } }),
  });
  // Cordis fiber.dispose executes registered effect disposers, not an event
  // named "dispose". Retained service references must also become unusable.
  ctx.effect(() => () => { closed = true; stop.abort(); });
  ctx.provide('figureTaskBridge', bridge);
}
