/** Read-only presentation of already registered asset bytes supplied by the host. */
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const PAGE_ROWS = 50;
const PAGE_COLUMNS = 40;
const CELL_CHARACTERS = 400;
const validSha = value => typeof value === 'string' && /^[a-f0-9]{64}$/i.test(value);
const assetURL = sha => validSha(sha) ? `/api/assets/${sha.toLowerCase()}` : '';
const button = (action, label, extra = '') => `<button type="button" class="asset41-button" data-asset41-action="${action}"${extra}>${label}</button>`;

/** Strict CSV/TSV records, with no numeric conversion or inferred column names.
 * A truncated buffer's final unfinished record is excluded, never presented as
 * a complete observation. On malformed quoting, only earlier complete records
 * are returned; the original source text remains available to the viewer.
 */
export function parseDelimitedAsset(text, delimiter = ',', {truncated = false} = {}) {
  if (typeof text !== 'string' || ![',','\t'].includes(delimiter)) throw new TypeError('Expected UTF-8 text and a CSV or TSV delimiter.');
  const source = text.replace(/^\uFEFF/, '');
  const rows = []; let row = [], field = '', quoted = false, closed = false;
  const addField = () => { row.push(field); field = ''; closed = false; };
  const addRow = () => { addField(); rows.push(row); row = []; };
  const failed = reason => ({rows, error: `第 ${rows.length + 1} 条记录、第 ${row.length + 1} 列${reason}；该记录及后续内容未作为表格记录显示。`, incomplete: true, delimiter});
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (quoted) {
      if (char === '"') { if (source[i + 1] === '"') { field += '"'; i++; } else { quoted = false; closed = true; } }
      else field += char;
      continue;
    }
    if (char === delimiter) { addField(); continue; }
    if (char === '\n' || char === '\r') { addRow(); if (char === '\r' && source[i + 1] === '\n') i++; continue; }
    if (closed) return failed('的闭引号后有非分隔字符');
    if (char === '"') { if (field) return failed('在未加引号字段中出现引号'); quoted = true; }
    else field += char;
  }
  const pending = quoted || closed || field.length > 0 || row.length > 0;
  if (truncated) return {rows, error: '', incomplete: pending, delimiter};
  if (quoted) return failed('的引号未闭合');
  if (pending) addRow();
  return {rows, error: '', incomplete: false, delimiter};
}

export function assetViewerModel(asset = {}) {
  const mime = String(asset.mime || '').split(';')[0].trim().toLowerCase();
  const title = String(asset.title || '未命名资产');
  const extension = title.toLowerCase().match(/\.([^.\s/\\]+)$/)?.[1] || '';
  const url = assetURL(asset.sha), text = typeof asset.text === 'string' ? asset.text : null;
  let kind = 'binary';
  if (mime === 'application/pdf' || extension === 'pdf') kind = 'pdf';
  else if (['image/png','image/svg+xml','image/jpeg','image/webp','image/gif'].includes(mime) || ['png','svg','jpg','jpeg','webp','gif'].includes(extension)) kind = 'image';
  else if (['text/csv','application/csv','text/tab-separated-values'].includes(mime) || ['csv','tsv'].includes(extension)) kind = 'table';
  else if (text !== null || mime.startsWith('text/') || ['application/json','application/javascript','application/xml','application/x-yaml'].includes(mime) || ['txt','md','markdown','py','js','ts','jsx','tsx','json','jsonl','yaml','yml','toml','ini','cfg','r','sh','tex','bib','ipynb','html','css','xml'].includes(extension)) kind = 'code';
  const delimiter = mime === 'text/tab-separated-values' || extension === 'tsv' ? '\t' : ',';
  const parsed = kind === 'table' && text !== null ? parseDelimitedAsset(text, delimiter, {truncated: asset.truncated === true}) : null;
  return {kind, mime, title, url, text, parsed, asset, error: asset.error ? String(asset.error.message || asset.error) : !url ? '缺少有效的已登记资产 SHA，无法提供原文件。' : ''};
}

/** Paging is display-only. Original values, row ordering and source bytes survive. */
export function assetTablePage(model, {query = '', page = 0, header = false, columnPage = 0} = {}) {
  const rows = model.parsed?.rows || [], first = header && rows.length ? 1 : 0;
  const needle = String(query).toLowerCase();
  const filtered = [];
  let columnCount = 0;
  for (let index = 0; index < rows.length; index++) {
    columnCount = Math.max(columnCount, rows[index].length);
    if (index >= first && (!needle || rows[index].some(value => value.toLowerCase().includes(needle)))) filtered.push({index, values: rows[index]});
  }
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_ROWS)), columnPageCount = Math.max(1, Math.ceil(columnCount / PAGE_COLUMNS));
  const safePage = Math.min(pageCount - 1, Math.max(0, Math.floor(Number(page) || 0))), safeColumnPage = Math.min(columnPageCount - 1, Math.max(0, Math.floor(Number(columnPage) || 0)));
  const columnStart = safeColumnPage * PAGE_COLUMNS, columnEnd = Math.min(columnCount, columnStart + PAGE_COLUMNS);
  return {rows: filtered.slice(safePage * PAGE_ROWS, (safePage + 1) * PAGE_ROWS), totalRows: Math.max(0, rows.length - first), filteredRows: filtered.length, page: safePage, pageCount, columnPage: safeColumnPage, columnPageCount, columnStart, columnEnd, columnCount, headers: header ? rows[0] || [] : null, header: first === 1};
}

function shortCell(value) {
  if (value.length <= CELL_CHARACTERS) return esc(value);
  let preview = value.slice(0, CELL_CHARACTERS);
  if (/[\uD800-\uDBFF]$/.test(preview)) preview = preview.slice(0, -1);
  return `<span class="asset41-short-cell" title="长字段仅缩短表格显示；完整已读取字段可在源文本中查看">${esc(preview)}…</span>`;
}

function tableHTML(table) {
  if (!table.columnCount) return '<p class="asset41-empty">没有可读取的完整记录。</p>';
  const columns = Array.from({length: table.columnEnd - table.columnStart}, (_, index) => index + table.columnStart);
  return `<table class="asset41-table"><caption class="asset41-sr-only">只读文件记录；不转换数值、不更改顺序。记录号对应源文件中的完整记录。</caption><thead><tr><th scope="col" class="asset41-row-number">记录</th>${columns.map(index => `<th scope="col">${table.headers ? index < table.headers.length ? shortCell(table.headers[index]) : `<span title="首条记录没有此列字段">列 ${index + 1}</span>` : `列 ${index + 1}`}</th>`).join('')}</tr></thead><tbody>${table.rows.length ? table.rows.map(row => `<tr><th scope="row" class="asset41-row-number">${row.index + 1}</th>${columns.map(index => index < row.values.length ? `<td>${shortCell(row.values[index])}</td>` : '<td class="asset41-missing" title="此记录没有该列字段">—</td>').join('')}</tr>`).join('') : `<tr><td colspan="${columns.length + 1}" class="asset41-empty">当前筛选没有匹配记录。</td></tr>`}</tbody></table>`;
}

function tableStatus(table, asset) {
  const start = table.filteredRows ? table.page * PAGE_ROWS + 1 : 0;
  const end = Math.min(table.filteredRows, (table.page + 1) * PAGE_ROWS);
  return `显示 ${table.rows.length} 行（${start}–${end}） · 匹配 ${table.filteredRows} 行 / 可读取完整${table.header ? '数据' : ''}记录 ${table.totalRows} 行${asset.truncated ? ' · 文件未读全，总行数未知' : ''}`;
}

function pagerHTML(table) {
  return `<div class="asset41-pager-group">${button('prev','上一页', table.page === 0 ? ' disabled' : '')}<span>${table.page + 1} / ${table.pageCount} 页</span>${button('next','下一页', table.page + 1 >= table.pageCount ? ' disabled' : '')}<span>每页最多 ${PAGE_ROWS} 行</span></div>${table.columnPageCount > 1 ? `<div class="asset41-pager-group">${button('columns-prev','前列', table.columnPage === 0 ? ' disabled' : '')}<span>列 ${table.columnStart + 1}–${table.columnEnd} / ${table.columnCount}</span>${button('columns-next','后列', table.columnPage + 1 >= table.columnPageCount ? ' disabled' : '')}</div>` : ''}`;
}

function textHTML(model) {
  if (model.text === null) return '<p class="asset41-empty">尚无可显示的 UTF-8 文本。可下载原文件核对。</p>';
  return `<pre class="asset41-source" tabindex="0" aria-label="只读源文本；可选择复制"><code data-asset41-code>${esc(model.text)}</code></pre>`;
}

function contentHTML(model, view, table) {
  if (model.error) return `<p class="asset41-error" role="alert">${esc(model.error)}</p>`;
  if (view === 'code') return textHTML(model);
  if (view === 'table') return tableHTML(table);
  if (view === 'image') return `<img class="asset41-image" data-asset41-image src="${esc(model.url)}" alt="${esc(model.title)}" draggable="false"><p class="asset41-media-error" data-asset41-media-error hidden>浏览器未能显示此图像。可下载原文件核对。</p>`;
  if (view === 'pdf') return `<iframe class="asset41-pdf" src="${esc(model.url)}" title="${esc(model.title)} · 原始 PDF" loading="lazy"></iframe><p class="asset41-pdf-help">PDF 使用浏览器自带查看器。若未显示，可<a href="${esc(model.url)}" target="_blank" rel="noopener">打开原始 PDF</a>。</p>`;
  return '<div class="asset41-empty"><p>此文件没有可用的只读预览。</p><p>请下载已登记原文件，使用适用的软件查看。</p></div>';
}

function sizeLabel(size) {
  if (!Number.isFinite(size) || size < 0) return '大小未提供';
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MiB`;
}

export function renderAssetViewer(asset = {}) {
  const model = assetViewerModel(asset), table = assetTablePage(model), initialView = model.kind;
  const textAvailable = model.text !== null, hasTable = model.kind === 'table';
  const owner = asset.ownerTitle || asset.ownerId || '未提供所属成果';
  const warnings = [asset.truncated ? '当前仅包含文件已读取的前缀，不能据此判断文件总行数或完整内容。下载链接仍指向登记的原文件。' : '', model.parsed?.incomplete ? '末尾未完成的记录未计入表格；已读取原文仍可在“源文本”中查看。' : '', model.parsed?.error || ''].filter(Boolean);
  return `<section class="asset41-viewer" data-asset41-viewer data-asset41-kind="${model.kind}" aria-label="只读来源查看器"><header class="asset41-header"><div class="asset41-heading"><span class="asset41-readonly">只读来源</span><h2>${esc(model.title)}</h2><p>所属成果：${esc(owner)}</p></div><div class="asset41-actions">${button('return','返回成果')}${button('trace','来源检查')}${model.url ? `<a class="asset41-button" href="${esc(model.url)}" download="${esc(model.title)}">原文件下载</a>` : ''}</div></header><div class="asset41-metadata"><span>${esc(asset.mime || 'MIME 未提供')} · ${sizeLabel(asset.size)}</span>${validSha(asset.sha) ? `<details class="asset41-identity"><summary>文件身份</summary><code>SHA-256 ${esc(asset.sha.toLowerCase())}</code></details>` : ''}</div>${warnings.map(warning => `<p class="asset41-warning">${esc(warning)}</p>`).join('')}<div class="asset41-toolbar">${hasTable ? `<div class="asset41-mode" role="group" aria-label="表示方式">${button('table','表格',' aria-pressed="true"')}${button('source','源文本',' aria-pressed="false"')}</div><label class="asset41-filter-label" data-asset41-table-tools>筛选已读取记录<input class="asset41-filter" type="search" data-asset41-filter aria-label="筛选已读取记录" placeholder="字段中包含…"></label><label class="asset41-header-option" data-asset41-table-tools><input type="checkbox" data-asset41-header>首条记录为列名</label>` : ''}${textAvailable && (hasTable || model.kind === 'code') ? `<span class="asset41-copy-tools" data-asset41-copy-tools${hasTable ? ' hidden' : ''}>${button('select','选择全部文本')}${button('copy','复制文本')}</span>` : ''}<span class="asset41-status" data-asset41-status role="status" aria-live="polite"></span></div>${hasTable ? `<p class="asset41-count" data-asset41-count>${tableStatus(table, asset)}</p><p class="asset41-table-note" data-asset41-table-tools>筛选只作用于可读取的完整记录；默认所有记录均为数据。长字段仅缩短表格显示，源文本保留已读取字符。</p>` : ''}<div class="asset41-viewport-frame" data-asset41-frame data-asset41-view-kind="${initialView}"><div class="asset41-viewport-surface" data-asset41-surface><div class="asset41-content" data-asset41-content>${contentHTML(model, initialView, table)}</div></div></div>${hasTable ? `<footer class="asset41-pager" data-asset41-pager>${pagerHTML(table)}</footer>` : ''}</section>`;
}

/** Does not fetch, execute, save or mutate the supplied asset. Returns a disposer.
 * Frame/surface identity is stable. On a table/source switch, synchronous
 * asset41:beforeviewchange lets the host save/detach its outgoing viewport BEFORE
 * DOM/scroll geometry changes. asset41:viewchange then lets it attach the new
 * representation. Page/filter changes emit only the latter and start at the top.
 * An optional caller-owned stateKey stores display preferences only. Bind before
 * attaching a viewport so restored table/source geometry precedes scroll restore.
 */
export function bindAssetViewer(root, {asset = {}, onReturn = () => {}, onTrace = () => {}, stateKey, storage} = {}) {
  const viewer = root?.matches?.('[data-asset41-viewer]') ? root : root?.querySelector('[data-asset41-viewer]');
  if (!viewer) return () => {};
  const model = assetViewerModel(asset), doc = viewer.ownerDocument, view = doc.defaultView;
  const frame = viewer.querySelector('[data-asset41-frame]'), content = viewer.querySelector('[data-asset41-content]');
  const status = viewer.querySelector('[data-asset41-status]'), count = viewer.querySelector('[data-asset41-count]'), pager = viewer.querySelector('[data-asset41-pager]');
  const filter = viewer.querySelector('[data-asset41-filter]'), header = viewer.querySelector('[data-asset41-header]');
  const state = {query: '', page: 0, columnPage: 0, header: false, view: model.kind};
  const identity = {sha: asset.sha, title: model.title, mime: asset.mime, size: asset.size, truncated: asset.truncated === true, ownerId: asset.ownerId, ownerTitle: asset.ownerTitle};
  const persistent = model.kind === 'table' && model.parsed && !model.error && typeof stateKey === 'string' && stateKey.length > 0;
  const disposers = []; let disposed = false, store, restored = false, storageNotice = '';
  if (persistent) {
    try {
      store = storage === undefined ? view?.localStorage : storage;
      if (!store?.getItem || !store?.setItem) throw new Error('Display storage unavailable');
      const raw = store.getItem(stateKey);
      if (raw != null) {
        try {
          const saved = JSON.parse(raw);
          if (!saved || saved.version !== 1 || typeof saved.query !== 'string' || typeof saved.header !== 'boolean' || !['table','code'].includes(saved.view) || !Number.isSafeInteger(saved.page) || saved.page < 0 || !Number.isSafeInteger(saved.columnPage) || saved.columnPage < 0) throw new Error('Invalid display state');
          for (const field of ['query','header','page','columnPage','view']) state[field] = saved[field];
          restored = true;
        } catch { storageNotice = '已保存的显示状态无效，当前使用默认视图。'; }
      }
    } catch { storageNotice = '显示状态未能读取；当前文件仍可查看。'; }
  }
  const listen = (node, type, fn, options) => { if (!node) return; node.addEventListener(type, fn, options); disposers.push(() => node.removeEventListener(type, fn, options)); };
  const message = text => { if (!disposed && status) status.textContent = [storageNotice, text].filter(Boolean).join(' '); };
  const persist = () => {
    if (!persistent) return;
    try { store.setItem(stateKey, JSON.stringify({version: 1, ...state})); storageNotice = ''; }
    catch { storageNotice = '显示状态未能保存；当前文件仍可查看。'; }
  };
  const update = ({restore = false} = {}) => {
    if (disposed) return;
    const previousView = frame.dataset.asset41ViewKind;
    if (previousView !== state.view && view?.CustomEvent) viewer.dispatchEvent(new view.CustomEvent('asset41:beforeviewchange', {bubbles: true, detail: {previousViewKind: previousView, viewKind: state.view, restore}}));
    const table = assetTablePage(model, state); state.page = table.page; state.columnPage = table.columnPage;
    if (filter && filter.value !== state.query) filter.value = state.query;
    if (header && header.checked !== state.header) header.checked = state.header;
    content.innerHTML = contentHTML(model, state.view, table); frame.dataset.asset41ViewKind = state.view;
    if (count) { count.hidden = state.view !== 'table'; count.textContent = tableStatus(table, asset); }
    if (pager) { pager.hidden = state.view !== 'table'; pager.innerHTML = pagerHTML(table); }
    for (const node of viewer.querySelectorAll('[data-asset41-table-tools]')) node.hidden = state.view !== 'table';
    const copyTools = viewer.querySelector('[data-asset41-copy-tools]'); if (copyTools) copyTools.hidden = state.view !== 'code';
    for (const node of viewer.querySelectorAll('[data-asset41-action="table"], [data-asset41-action="source"]')) node.setAttribute('aria-pressed', String(node.dataset.asset41Action === (state.view === 'table' ? 'table' : 'source')));
    if (!restore) { frame.scrollTop = 0; frame.scrollLeft = 0; }
    persist(); message('');
    if (view?.CustomEvent) viewer.dispatchEvent(new view.CustomEvent('asset41:viewchange', {bubbles: true, detail: {viewKind: state.view, page: table.page, totalRows: table.totalRows, filteredRows: table.filteredRows}}));
  };
  const selectText = () => {
    const code = viewer.querySelector('[data-asset41-code]');
    if (!code || !doc.createRange || !doc.getSelection) return false;
    const range = doc.createRange(); range.selectNodeContents(code); const selection = doc.getSelection(); selection?.removeAllRanges(); selection?.addRange(range); return Boolean(selection);
  };
  const copy = async () => {
    if (model.text === null) return;
    const selection = doc.getSelection?.(), code = viewer.querySelector('[data-asset41-code]');
    const selected = code && selection && !selection.isCollapsed && selection.rangeCount && code.contains(selection.getRangeAt(0).commonAncestorContainer) ? selection.toString() : '';
    const value = selected || model.text;
    try {
      if (!view?.navigator?.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await view.navigator.clipboard.writeText(value);
      message(selected ? '已复制所选源文本。' : asset.truncated ? '已复制已读取的源文本前缀，文件未读全。' : '已复制已读取的源文本。');
    } catch { if (!disposed) selectText(); message('浏览器未允许直接复制；可选择文本后使用系统复制。'); }
  };
  listen(viewer, 'click', async event => {
    const target = event.target?.closest?.('[data-asset41-action]');
    if (!target || !viewer.contains(target) || target.disabled) return;
    event.preventDefault(); event.stopPropagation();
    const action = target.dataset.asset41Action;
    try {
      if (action === 'return') await onReturn({...identity});
      else if (action === 'trace') await onTrace({...identity});
      else if (action === 'select') selectText();
      else if (action === 'copy') await copy();
      else if (model.kind === 'table') {
        if (action === 'table' || action === 'source') {
          const nextView = action === 'table' ? 'table' : 'code';
          if (state.view === nextView) return;
          state.view = nextView;
        }
        else if (action === 'prev') state.page--;
        else if (action === 'next') state.page++;
        else if (action === 'columns-prev') state.columnPage--;
        else if (action === 'columns-next') state.columnPage++;
        else return;
        update();
      }
    } catch (error) { message(String(error?.message || error)); }
  });
  listen(filter, 'input', event => { event.stopPropagation(); state.query = filter.value; state.page = 0; update(); });
  listen(header, 'change', event => { event.stopPropagation(); state.header = header.checked; state.page = 0; update(); });
  const image = viewer.querySelector('[data-asset41-image]');
  listen(image, 'error', () => { const notice = viewer.querySelector('[data-asset41-media-error]'); if (notice) notice.hidden = false; message('图像预览未能加载，原文件仍可下载。'); });
  if (restored) update({restore: true}); else message('');
  return () => { if (disposed) return; disposed = true; for (const dispose of disposers) dispose(); };
}
