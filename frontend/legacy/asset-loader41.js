/** Bounded, read-only access to registered, same-origin asset endpoints. */
const DEFAULT_TEXT_BYTES = 2 * 1024 * 1024;
const finiteSize = value => Number.isSafeInteger(value) && value >= 0 ? value : undefined;
const shaPattern = /^[a-f0-9]{64}$/i;
const abortError = signal => signal?.reason?.name === 'AbortError' ? signal.reason : new DOMException('资产读取已取消。', 'AbortError');
const checkAbort = signal => { if (signal?.aborted) throw abortError(signal); };

function basename(value) {
  if (typeof value !== 'string') return '';
  const clean = value.replace(/[\u0000-\u001f\u007f\u202a-\u202e\u2066-\u2069]/g, '').trim();
  const name = clean.replaceAll('\\', '/').split('/').filter(Boolean).at(-1) || '';
  return name === '.' || name === '..' ? '' : name;
}

/** RFC 5987 UTF-8 filename* takes precedence over a quoted/plain filename. */
export function registeredAssetFilename(disposition, fallback = '') {
  const values = new Map();
  const pattern = /(?:^|;)\s*([\w*-]+)\s*=\s*(?:"((?:\\.|[^"\\])*)"|([^;]*))/g;
  let match;
  while ((match = pattern.exec(String(disposition || '')))) values.set(match[1].toLowerCase(), match[2] !== undefined ? match[2].replace(/\\(["\\])/g, '$1') : match[3].trim());
  const extended = /^([^']*)'[^']*'(.*)$/.exec(values.get('filename*') || '');
  if (extended && /^utf-?8$/i.test(extended[1])) {
    try { const decoded = basename(decodeURIComponent(extended[2])); if (decoded) return decoded; } catch { /* Try the plain filename instead. */ }
  }
  return basename(values.get('filename')) || basename(fallback);
}

function contentLength(headers) {
  const raw = headers?.get?.('Content-Length');
  if (typeof raw !== 'string' || !/^\d+$/.test(raw.trim())) return undefined;
  return finiteSize(Number(raw));
}

function textCandidate({mime, title, originalTitle, role}) {
  const type = String(mime || '').split(';')[0].trim().toLowerCase();
  const extensions = [title, originalTitle].map(name => String(name || '').toLowerCase().match(/\.([^.\s/\\]+)$/)?.[1] || '');
  // Media use their real registered URL. Even SVG/XML media is not executed or
  // copied into the host DOM; the image viewer can display it directly.
  if (type.startsWith('image/') || type === 'application/pdf' || extensions.some(ext => ['pdf','png','svg','jpg','jpeg','gif','webp','avif','ico','tif','tiff'].includes(ext))) return false;
  if (type.startsWith('text/') || /(?:\+json|\+xml)$/.test(type) || ['application/json','application/x-ndjson','application/ndjson','application/javascript','application/ecmascript','application/xml','application/yaml','application/x-yaml','application/toml','application/csv','application/x-python','application/x-sh','application/x-latex','application/sql'].includes(type)) return true;
  if (extensions.some(ext => ['csv','tsv','txt','md','markdown','py','pyw','js','mjs','cjs','ts','jsx','tsx','json','jsonl','ndjson','yaml','yml','toml','ini','cfg','conf','r','rmd','sh','bash','zsh','tex','bib','ipynb','html','htm','css','xml','sql','jl','m','c','cc','cpp','h','hpp','rs','go'].includes(ext))) return true;
  return role === 'code';
}

async function cancelBody(response) {
  try { await response?.body?.cancel?.(); } catch { /* Cancelling unused bytes must not remove the download identity. */ }
}

/**
 * ref is catalog metadata already authorized/resolved by the host. It never
 * supplies a request URL. maxTextBytes bounds retained/decoded bytes; a fetch
 * stream can deliver a larger final network chunk, whose excess is discarded.
 * AbortError propagates; HTTP, format and stream errors return explicit error
 * results with the original asset identity and without fabricated source text.
 */
export async function loadRegisteredAsset(ref = {}, {fetcher = globalThis.fetch, signal, maxTextBytes = DEFAULT_TEXT_BYTES} = {}) {
  const inputSha = ref?.sha ?? ref?.sha256;
  const initialTitle = basename(ref?.title || ref?.filename || '');
  const base = {sha: typeof inputSha === 'string' ? inputSha.toLowerCase() : '', title: initialTitle || '已登记资产', mime: String(ref?.mime || ref?.media_type || ''), size: finiteSize(ref?.size), totalBytes: finiteSize(ref?.size), readBytes: 0, truncated: false, ownerId: ref?.ownerId, ownerTitle: ref?.ownerTitle};
  if (!shaPattern.test(base.sha)) return {...base, binary: true, error: '需要有效的 64 位登记资产 SHA；未请求任何地址。'};
  if (!Number.isSafeInteger(maxTextBytes) || maxTextBytes <= 0) return {...base, binary: true, error: '文本读取上限必须是正整数个字节；未请求资产。'};
  checkAbort(signal);
  let response;
  try {
    response = await fetcher(`/api/assets/${base.sha}`, {credentials: 'same-origin', signal});
    checkAbort(signal);
    if (!response?.ok) {
      await cancelBody(response); checkAbort(signal);
      return {...base, binary: true, error: `读取已登记资产失败（HTTP ${response?.status ?? '未知'}${response?.statusText ? ` ${response.statusText}` : ''}）。`};
    }
    const type = response.headers?.get?.('Content-Type');
    if (type) base.mime = type;
    base.title = registeredAssetFilename(response.headers?.get?.('Content-Disposition'), initialTitle) || base.title;
    const length = contentLength(response.headers), encoding = response.headers?.get?.('Content-Encoding');
    // Fetch transparently decompresses encoded bodies. Wire Content-Length is
    // therefore kept separately and is not mislabeled as decoded file size.
    if (length !== undefined) {
      base.contentLength = length;
      if (!encoding || encoding.toLowerCase() === 'identity') base.size = base.totalBytes = length;
    }
    if (!textCandidate({mime: base.mime, title: base.title, originalTitle: initialTitle, role: ref?.role})) {
      await cancelBody(response); checkAbort(signal); return {...base, binary: true};
    }
    if (!response.body) return {...base, size: 0, totalBytes: 0, text: '', binary: false};
    if (typeof response.body.getReader !== 'function') {
      await cancelBody(response);
      return {...base, binary: true, error: '当前运行时不能进行有上限的流式文本读取；保留原文件下载。'};
    }
    const reader = response.body.getReader(), decoder = new TextDecoder('utf-8', {fatal: true}), parts = [];
    let done = false, readBytes = 0, truncated = false, text = '', decodeFailure = false;
    const onAbort = () => { try { Promise.resolve(reader.cancel(signal.reason)).catch(() => {}); } catch { /* The read will check the aborted signal. */ } };
    signal?.addEventListener('abort', onAbort, {once: true});
    try {
      while (readBytes < maxTextBytes) {
        checkAbort(signal);
        const chunk = await reader.read(); checkAbort(signal);
        if (chunk.done) { done = true; break; }
        if (!(chunk.value instanceof Uint8Array)) throw new Error('资产流没有返回字节数据。');
        const remaining = maxTextBytes - readBytes, bytes = chunk.value.subarray(0, remaining);
        readBytes += bytes.byteLength;
        truncated = chunk.value.byteLength > remaining || (readBytes === maxTextBytes && base.totalBytes !== readBytes);
        try { parts.push(decoder.decode(bytes, {stream: true})); } catch { decodeFailure = true; throw new Error('文件不是有效的 UTF-8 文本；保留原文件下载。'); }
        if (chunk.value.byteLength > remaining) { truncated = true; break; }
        if (readBytes === maxTextBytes) {
          // A truthful unencoded length proves exact-boundary completeness. If
          // length is unknown, conservatively report only a loaded prefix.
          truncated = base.totalBytes !== readBytes;
          break;
        }
      }
      if (done) {
        if (base.totalBytes !== undefined && base.totalBytes > readBytes && (!encoding || encoding.toLowerCase() === 'identity')) throw new Error('资产流早于声明长度结束；未提供不完整的文本预览。');
        base.size = base.totalBytes = readBytes;
      }
      if (!truncated) {
        try { parts.push(decoder.decode()); } catch { decodeFailure = true; throw new Error('文件末尾不是完整有效的 UTF-8 文本；保留原文件下载。'); }
      }
      // A truncated final multibyte code point stays buffered in the decoder;
      // it is omitted rather than replaced by a fabricated replacement glyph.
      text = parts.join('');
      if (text.includes('\u0000')) { decodeFailure = true; throw new Error('文件包含 NUL 字节，未按文本预览；保留原文件下载。'); }
      return {...base, text, readBytes, truncated, binary: false};
    } catch (error) {
      if (signal?.aborted || error?.name === 'AbortError') throw abortError(signal);
      return {...base, readBytes, truncated, binary: true, error: decodeFailure ? error.message : `文本读取未完成：${error?.message || error}`};
    } finally {
      signal?.removeEventListener('abort', onAbort);
      if (!done) { try { await reader.cancel(); } catch { /* Keep the primary read/decode result. */ } }
      try { reader.releaseLock(); } catch { /* Reader may already be released by an abort. */ }
      checkAbort(signal);
    }
  } catch (error) {
    if (signal?.aborted || error?.name === 'AbortError') { await cancelBody(response); throw abortError(signal); }
    await cancelBody(response);
    return {...base, binary: true, error: `读取已登记资产失败：${error?.message || error}`};
  }
}
