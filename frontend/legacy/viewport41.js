/** Local view navigation only. The caller continues to own the surface and its content.
 * Use a key containing object identity, representation and region; never share a region
 * key between two visible viewports. Display zoom is not a scientific/print dimension.
 */
const MIN_ZOOM = 0.1;
const MAX_ZOOM = 8;
const memory = new Map();
const owners = new WeakMap();
const escapeHTML = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const finite = value => typeof value === 'number' && Number.isFinite(value);

export function viewportStateKey(key) {
  const parts = typeof key === 'string' ? [key] : [key?.objectId, key?.representation, key?.region];
  if (parts.some(part => typeof part !== 'string' || !part.trim())) throw new TypeError('Viewport key needs objectId, representation and region, or a nonempty composite string.');
  return `research-partner:viewport41:${JSON.stringify(parts)}`;
}

export function normalizeViewportState(value) {
  if (!value || !finite(value.zoom) || !finite(value.x) || !finite(value.y) || value.zoom <= 0 || value.x < 0 || value.y < 0) return null;
  return {zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value.zoom)), x: value.x, y: value.y, hand: value.hand === true};
}

/** x/y are frame-local focal coordinates. Exported for deterministic geometry tests. */
export function zoomViewportAt(state, zoom, point) {
  const old = normalizeViewportState(state);
  if (!old || !finite(zoom) || zoom <= 0 || !finite(point?.x) || !finite(point?.y)) throw new TypeError('Invalid viewport geometry.');
  const next = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));
  return {...old, zoom: next, x: Math.max(0, (old.x + point.x) * next / old.zoom - point.x), y: Math.max(0, (old.y + point.y) * next / old.zoom - point.y)};
}

export function viewportControls(id = '') {
  const target = id ? ` aria-controls="${escapeHTML(id)}"` : '';
  const button = (action, text, label, extra = '') => `<button type="button" class="vp41-button" data-vp41-action="${action}" aria-label="${label}" title="${label}"${target}${extra}>${text}</button>`;
  return `<nav class="vp41-controls" data-vp41-controls="${escapeHTML(id)}" aria-label="视图导航">${button('hand','✋','手形平移；也可在非文本输入时按住空格',' aria-pressed="false"')}${button('out','−','缩小视图')}<label class="vp41-percent-label"><input class="vp41-percent" data-vp41-percent type="text" inputmode="decimal" value="100%" aria-label="视图缩放百分比" title="输入 10–800%，仅改变显示比例"${target}></label>${button('in','＋','放大视图')}${button('fit','适配','适配全部内容')}${button('selection','选区','适配选区')}${button('width','宽度','适合宽度')}${button('reset','100%','重置到 100% 和起始位置')}<span class="vp41-status" data-vp41-status role="status" aria-live="polite"></span></nav>`;
}

function editable(target) {
  return Boolean(target?.isContentEditable || target?.closest?.('input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="textbox"], [role="combobox"]'));
}

function defaultStorage(view) {
  try { return view?.localStorage; } catch { return null; }
}

/**
 * frame: finite-size scrolling element; surface: existing editor/preview descendant.
 * controls: the element returned by viewportControls (pass explicitly for split views).
 * mode: canvas (fit both dimensions), paper (fixed intrinsic page width,
 * fit width and scroll long documents), text/table (fit width and reflow).
 * getSelection: optional Element, Element[] or surface-coordinate {x,y,width,height}.
 * onChange(state, reason): view state only. Never send it to an object's content save.
 * setZoom's optional {x,y} and toContentPoint use browser client coordinates.
 * refresh() remeasures after content/image load; ResizeObserver does this when present.
 * destroy() restores the same surface node and removes all module event listeners.
 */
export function createViewport({frame, surface, key, mode = 'canvas', controls, onChange, storage, getSelection} = {}) {
  if (!frame || !surface || frame === surface || !frame.contains(surface)) throw new TypeError('Viewport needs a frame containing a distinct surface.');
  if (owners.has(frame) || owners.has(surface)) throw new Error('Destroy the existing viewport before binding this frame or surface again.');
  const stateKey = viewportStateKey(key);
  const doc = frame.ownerDocument;
  const view = doc.defaultView;
  const store = storage === undefined ? defaultStorage(view) : storage;
  controls ??= frame.parentElement?.querySelector('[data-vp41-controls]');
  const disposers = [];
  const oldTabindex = frame.getAttribute('tabindex');
  const hadFrameClass = frame.classList.contains('vp41-frame');
  const shell = doc.createElement('div');
  const stage = doc.createElement('div');
  shell.className = 'vp41-surface-shell';
  stage.className = 'vp41-stage';
  const initialWidth = Math.max(1, surface.offsetWidth || surface.getBoundingClientRect().width || frame.clientWidth);
  shell.style.width = `${initialWidth}px`;
  surface.parentNode.insertBefore(stage, surface);
  stage.appendChild(shell);
  shell.appendChild(surface);
  frame.classList.add('vp41-frame');
  if (oldTabindex === null) frame.setAttribute('tabindex', '0');
  let zoom = 1, hand = false, space = false, destroyed = false, drag = null;
  const nativePointers = new Set();
  let dimensions = {width: initialWidth, height: 1, readingWidth: initialWidth};
  let pendingRestore = null, lastVisibleState = null, clickUntil = 0, resizeObserver = null;
  const frameSize = () => ({width: frame.clientWidth, height: frame.clientHeight});
  let lastFrameSize = frameSize(), pendingApplied = false;
  const listen = (node, type, fn, options) => {
    if (!node?.addEventListener) return;
    node.addEventListener(type, fn, options);
    disposers.push(() => node.removeEventListener(type, fn, options));
  };
  const percent = controls?.querySelector('[data-vp41-percent]');
  const status = controls?.querySelector('[data-vp41-status]');
  const handButton = controls?.querySelector('[data-vp41-action="hand"]');
  const getState = () => ({zoom, x: Math.max(0, frame.scrollLeft || 0), y: Math.max(0, frame.scrollTop || 0), hand});
  const message = text => { if (status) status.textContent = text; };
  const preserveLayoutPosition = () => {
    const size = frameSize(), resized = size.width !== lastFrameSize.width || size.height !== lastFrameSize.height;
    // A visible wider/taller region can clamp scrolling just like a hidden one.
    // Scroll events may precede ResizeObserver, so check before persisting or measuring.
    if (resized || size.width <= 0 || size.height <= 0) {
      if (!pendingRestore && lastVisibleState) pendingRestore = {...lastVisibleState};
      if (resized) pendingApplied = false;
    }
    lastFrameSize = size;
    return resized;
  };
  const beginNavigation = () => { pendingRestore = null; pendingApplied = false; lastFrameSize = frameSize(); };
  const remember = () => {
    const resized = preserveLayoutPosition();
    if (pendingRestore && pendingApplied && !resized && frame.clientWidth > 0 && frame.clientHeight > 0) {
      const actual = getState(), x = Math.min(pendingRestore.x, Math.max(0, frame.scrollWidth - frame.clientWidth)), y = Math.min(pendingRestore.y, Math.max(0, frame.scrollHeight - frame.clientHeight));
      // A focus/selection scroll to somewhere other than the layout clamp is
      // also a new location, even when it did not originate in this module.
      if (Math.abs(actual.x - x) > 1 || Math.abs(actual.y - y) > 1) beginNavigation();
    }
    if (pendingRestore) pendingRestore = {...pendingRestore, zoom, hand};
    const state = pendingRestore || getState();
    if (frame.clientWidth > 0 && frame.clientHeight > 0 && !pendingRestore) lastVisibleState = {...state};
    memory.set(stateKey, {...state});
    try { store?.setItem(stateKey, JSON.stringify({version: 1, ...state})); } catch { /* A full/blocked store must not break navigation. */ }
    return {...state};
  };
  const syncControls = () => {
    if (percent && doc.activeElement !== percent) percent.value = `${Math.round(zoom * 100)}%`;
    handButton?.setAttribute('aria-pressed', String(hand));
    frame.classList.toggle('vp41-hand', hand || space);
    frame.classList.toggle('vp41-panning', Boolean(drag));
  };
  const changed = reason => {
    if (destroyed) return;
    if (['zoom', 'fit', 'fit-width', 'reset', 'pan'].includes(reason)) beginNavigation();
    syncControls();
    remember();
    onChange?.(getState(), reason);
  };
  const applyGeometry = () => {
    shell.style.transform = `scale(${zoom})`;
    stage.style.width = `${dimensions.width * zoom}px`;
    stage.style.height = `${dimensions.height * zoom}px`;
  };
  const measure = () => {
    preserveLayoutPosition();
    // Hiding a retained split iframe may report zero layout dimensions and
    // clamp its scroll position. Keep the visible state until it is shown again.
    if (frame.clientWidth <= 0 || frame.clientHeight <= 0) {
      if (!pendingRestore) pendingRestore = lastVisibleState ? {...lastVisibleState} : getState();
      return;
    }
    // Text reflows with available editing width, not with zoom. Canvas intrinsic
    // geometry remains fixed; no surface style, data-scale or content is changed.
    if ((mode === 'text' || mode === 'table') && frame.clientWidth > 0) shell.style.width = `${frame.clientWidth}px`;
    dimensions = {
      width: Math.max(1, surface.offsetWidth || 0, surface.scrollWidth || 0, shell.scrollWidth || 0),
      height: Math.max(1, surface.offsetHeight || 0, surface.scrollHeight || 0, shell.scrollHeight || 0),
      readingWidth: Math.max(1, surface.offsetWidth || initialWidth),
    };
    applyGeometry();
  };
  const toContentPoint = (clientX, clientY) => {
    const rect = surface.getBoundingClientRect();
    return {x: (clientX - rect.left) / zoom, y: (clientY - rect.top) / zoom};
  };
  const setZoom = (value, point) => {
    if (destroyed || !finite(value) || value <= 0) return false;
    const rect = frame.getBoundingClientRect();
    const focus = point && finite(point.x) && finite(point.y) ? point : {x: rect.left + frame.clientLeft + frame.clientWidth / 2, y: rect.top + frame.clientTop + frame.clientHeight / 2};
    const contentPoint = toContentPoint(focus.x, focus.y);
    zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
    pendingRestore = null;
    applyGeometry();
    const after = surface.getBoundingClientRect();
    frame.scrollLeft += after.left + contentPoint.x * zoom - focus.x;
    frame.scrollTop += after.top + contentPoint.y * zoom - focus.y;
    message('');
    changed('zoom');
    return true;
  };
  const boundsOf = selection => {
    if (!selection) return null;
    if (Array.isArray(selection)) {
      const items = selection.map(boundsOf).filter(Boolean);
      if (!items.length) return null;
      const x = Math.min(...items.map(item => item.x)), y = Math.min(...items.map(item => item.y));
      return {x, y, width: Math.max(...items.map(item => item.x + item.width)) - x, height: Math.max(...items.map(item => item.y + item.height)) - y};
    }
    if (typeof selection.getBoundingClientRect === 'function') {
      if (!surface.contains(selection) && selection !== surface) return null;
      const rect = selection.getBoundingClientRect(), point = toContentPoint(rect.left, rect.top);
      return rect.width > 0 && rect.height > 0 ? {...point, width: rect.width / zoom, height: rect.height / zoom} : null;
    }
    return ['x','y','width','height'].every(name => finite(selection[name])) && selection.width > 0 && selection.height > 0 ? {...selection} : null;
  };
  const fitBounds = (bounds, widthOnly = false) => {
    if (destroyed || !bounds || frame.clientWidth <= 0 || frame.clientHeight <= 0) return false;
    const horizontal = Math.max(1, frame.clientWidth - 24) / bounds.width;
    const vertical = Math.max(1, frame.clientHeight - 24) / bounds.height;
    zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, widthOnly ? horizontal : Math.min(horizontal, vertical)));
    pendingRestore = null;
    applyGeometry();
    const surfaceRect = surface.getBoundingClientRect(), frameRect = frame.getBoundingClientRect();
    frame.scrollLeft += surfaceRect.left - frameRect.left - frame.clientLeft + (bounds.x + bounds.width / 2) * zoom - frame.clientWidth / 2;
    frame.scrollTop += surfaceRect.top - frameRect.top - frame.clientTop + (widthOnly ? bounds.y * zoom - 12 : (bounds.y + bounds.height / 2) * zoom - frame.clientHeight / 2);
    message('');
    changed(widthOnly ? 'fit-width' : 'fit');
    return true;
  };
  const fitWidth = () => {
    // Width fitting keeps the current reading line, rather than jumping to page one.
    const rect = frame.getBoundingClientRect();
    const y = Math.max(0, toContentPoint(rect.left + frame.clientLeft, rect.top + frame.clientTop + 12).y);
    measure(); return fitBounds({x: 0, y, width: dimensions.readingWidth, height: dimensions.height}, true);
  };
  const fit = selection => {
    measure();
    if (selection !== undefined) {
      const bounds = boundsOf(selection);
      if (!bounds) { message('没有可适配的选区；请先选择对象或文字。'); return false; }
      return fitBounds(bounds);
    }
    if (mode === 'paper' || mode === 'text' || mode === 'table') return fitWidth();
    return fitBounds({x: 0, y: 0, ...dimensions});
  };
  const selection = () => {
    if (getSelection) return getSelection();
    const selected = doc.getSelection?.();
    if (!selected || selected.isCollapsed || !selected.rangeCount) return null;
    const range = selected.getRangeAt(0);
    if (!surface.contains(range.commonAncestorContainer)) return null;
    const rect = range.getBoundingClientRect(), point = toContentPoint(rect.left, rect.top);
    return {...point, width: rect.width / zoom, height: rect.height / zoom};
  };
  const setHand = value => { if (destroyed) return; hand = Boolean(value); changed('hand'); };
  const reset = () => {
    if (destroyed) return;
    zoom = 1; hand = false; space = false; pendingRestore = null;
    applyGeometry(); frame.scrollLeft = 0; frame.scrollTop = 0;
    message(''); changed('reset');
  };
  const restore = saved => {
    if (destroyed) return false;
    let value = saved;
    if (value === undefined) {
      try { const raw = store?.getItem(stateKey); if (raw) value = JSON.parse(raw); } catch { /* Fall back to same-session memory. */ }
      value ??= memory.get(stateKey);
    }
    const state = normalizeViewportState(value);
    if (!state) return false;
    zoom = state.zoom; hand = state.hand; pendingRestore = state; pendingApplied = false; applyGeometry();
    if (frame.clientWidth > 0 && frame.clientHeight > 0) {
      frame.scrollLeft = state.x; frame.scrollTop = state.y; pendingApplied = true;
      if (Math.abs(frame.scrollLeft - state.x) <= 1 && Math.abs(frame.scrollTop - state.y) <= 1) pendingRestore = null;
    }
    lastFrameSize = frameSize();
    changed('restore');
    return true;
  };
  const refresh = () => {
    if (destroyed) return;
    measure();
    if (pendingRestore && frame.clientWidth > 0 && frame.clientHeight > 0) restore(pendingRestore);
  };
  const stop = event => { event.preventDefault(); event.stopImmediatePropagation(); };
  const finishPan = event => {
    if (event?.type === 'pointerup' || event?.type === 'pointercancel') nativePointers.delete(event.pointerId);
    if (!drag || (event?.pointerId !== undefined && event.pointerId !== drag.id)) return;
    const id = drag.id;
    drag = null; clickUntil = Date.now() + 500;
    try { frame.releasePointerCapture?.(id); } catch { /* Pointer may already be released. */ }
    if (event) stop(event);
    changed('pan');
  };
  listen(frame, 'pointerdown', event => {
    if (event.target?.closest?.('[data-vp41-controls]')) return;
    if (drag) return;
    // Editors cache their screen-to-content mapping at pointerdown. Observe
    // native drags/selections without intercepting them and keep that scale
    // stable until release (also when capture delivers release outside frame).
    if (event.button === 0 && !hand && !space) {
      nativePointers.add(event.pointerId);
      const rect = frame.getBoundingClientRect();
      if (event.target === frame && (event.clientX >= rect.left + frame.clientLeft + frame.clientWidth || event.clientY >= rect.top + frame.clientTop + frame.clientHeight)) beginNavigation();
      return;
    }
    if (!(event.button === 1 || (event.button === 0 && (hand || space)))) return;
    stop(event);
    beginNavigation();
    drag = {id: event.pointerId, clientX: event.clientX, clientY: event.clientY, x: frame.scrollLeft, y: frame.scrollTop};
    try { frame.setPointerCapture?.(event.pointerId); } catch { /* Global move/up listeners remain available. */ }
    syncControls();
  }, true);
  listen(view, 'pointermove', event => {
    if (!drag || event.pointerId !== drag.id) return;
    stop(event);
    frame.scrollLeft = drag.x - (event.clientX - drag.clientX);
    frame.scrollTop = drag.y - (event.clientY - drag.clientY);
    changed('pan');
  }, {capture: true, passive: false});
  listen(view, 'pointerup', finishPan, true);
  listen(view, 'pointercancel', finishPan, true);
  listen(frame, 'lostpointercapture', finishPan);
  listen(frame, 'click', event => { if (Date.now() < clickUntil && !event.target?.closest?.('[data-vp41-controls]')) stop(event); }, true);
  listen(frame, 'auxclick', event => { if (event.button === 1) stop(event); }, true);
  listen(frame, 'wheel', event => {
    if (!event.ctrlKey && !event.metaKey) { if (event.deltaX || event.deltaY) beginNavigation(); return; }
    if (nativePointers.size) { event.preventDefault(); event.stopPropagation(); return; }
    const delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? frame.clientHeight : 1);
    if (!finite(delta) || !delta) return;
    event.preventDefault(); event.stopPropagation();
    setZoom(zoom * Math.exp(-Math.max(-1000, Math.min(1000, delta)) * 0.002), {x: event.clientX, y: event.clientY});
  }, {passive: false});
  listen(frame, 'keydown', event => {
    if (editable(event.target) || editable(doc.activeElement) || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.code === 'Space' || event.key === ' ') { space = true; stop(event); syncControls(); }
    // Arrows, text selection and editor shortcuts belong to the editor. These
    // single-key alternatives operate only when the empty frame itself has focus.
    else if (event.target === frame) {
      if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End'].includes(event.key)) beginNavigation();
      if (event.key === '+' || event.key === '=') { stop(event); setZoom(zoom * 1.2); }
      else if (event.key === '-') { stop(event); setZoom(zoom / 1.2); }
      else if (event.key === '0') { stop(event); reset(); }
    }
  }, true);
  listen(view, 'keyup', event => { if (event.code === 'Space' || event.key === ' ') { space = false; syncControls(); } }, true);
  listen(view, 'blur', () => { nativePointers.clear(); space = false; finishPan(); syncControls(); });
  listen(frame, 'scroll', () => changed('scroll'), {passive: true});
  listen(surface, 'load', refresh, true);
  listen(controls, 'click', event => {
    const button = event.target?.closest?.('[data-vp41-action]');
    if (!button || !controls.contains(button)) return;
    event.preventDefault(); event.stopPropagation();
    switch (button.dataset.vp41Action) {
      case 'in': setZoom(zoom * 1.2); break;
      case 'out': setZoom(zoom / 1.2); break;
      case 'fit': fit(); break;
      case 'selection': fit(selection()); break;
      case 'width': fitWidth(); break;
      case 'reset': reset(); break;
      case 'hand': setHand(!hand); break;
    }
  });
  const commitPercent = () => {
    const raw = percent?.value.trim().replace(/%$/, '').trim();
    const value = raw ? Number(raw) : NaN;
    if (finite(value) && value >= MIN_ZOOM * 100 && value <= MAX_ZOOM * 100) setZoom(value / 100);
    else message('请输入 10–800 之间的缩放百分比。');
    if (percent) percent.value = `${Math.round(zoom * 100)}%`;
  };
  listen(percent, 'change', event => { event.stopPropagation(); commitPercent(); });
  listen(percent, 'keydown', event => { if (event.key === 'Enter') { event.preventDefault(); event.stopPropagation(); commitPercent(); } });
  const destroy = () => {
    if (destroyed) return;
    remember(); destroyed = true; nativePointers.clear(); finishPan();
    for (const dispose of disposers) dispose();
    resizeObserver?.disconnect();
    owners.delete(frame); owners.delete(surface);
    frame.classList.remove('vp41-hand', 'vp41-panning');
    if (!hadFrameClass) frame.classList.remove('vp41-frame');
    if (oldTabindex === null) frame.removeAttribute('tabindex'); else frame.setAttribute('tabindex', oldTabindex);
    if (stage.parentNode && surface.parentNode === shell) stage.replaceWith(surface);
    else if (!shell.childNodes.length) stage.remove();
  };
  const api = {destroy, getState, setZoom, fit, fitWidth, reset, setHand, remember, restore, refresh, toContentPoint};
  owners.set(frame, api); owners.set(surface, api);
  measure(); restore(); syncControls();
  if (view?.ResizeObserver) { resizeObserver = new view.ResizeObserver(refresh); resizeObserver.observe(frame); resizeObserver.observe(surface); }
  else listen(view, 'resize', refresh);
  return api;
}
