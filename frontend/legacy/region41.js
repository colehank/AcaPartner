/** Stable secondary editor session. Drafts and object changes remain owned by app.js. */
const SCOPE = 'research-partner:region41';
// v2 prepares then confirms component links; v1 activation messages cannot
// safely interoperate. Desk and draft storage identities are unchanged.
const VERSION = 2;
const idOK = id => typeof id === 'string' && id.trim().length > 0 && id.length <= 512 && !/[\u0000-\u001f\u007f]/.test(id);
const identity = value => idOK(value) ? value : '';
const title = value => typeof value === 'string' ? value.slice(0, 512) : '';
const summary = state => ({
  objectId: identity(state?.objectId),
  title: title(state?.title),
  projectId: identity(state?.projectId),
  projectTitle: title(state?.projectTitle),
  selectedItem: identity(state?.selectedItem),
  selectedBlock: identity(state?.selectedBlock),
  dirty: state?.dirty === true,
  saving: state?.saving === true,
});
const sameSummary = (left, right) => Object.keys(left).every(key => left[key] === right[key]);
const errorText = error => String(error?.message || error || '区域操作未完成。').slice(0, 1000);
const randomID = view => view.crypto?.randomUUID?.() || Array.from(view.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');

/** Identity-only selection contract; unknown actions/body fields are rejected. */
export function cleanRegionSelection(value) {
  const stringFields = ['id','artistId','blockId','componentId','itemId','parentObjectId'];
  const numberFields = ['componentIndex','revision','pageIndex'];
  const types = ['object','block','component','artist','page','canvas'];
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).some(key => !['objectId','anchor','open'].includes(key)) || !idOK(value.objectId) || (value.open !== undefined && typeof value.open !== 'boolean')) return null;
  const input = value.anchor;
  if (!input || typeof input !== 'object' || Array.isArray(input) || !types.includes(input.type) || Object.keys(input).some(key => !['type', ...stringFields, ...numberFields].includes(key))) return null;
  const anchor = {type: input.type};
  for (const key of stringFields) { if (input[key] === undefined) continue; if (!idOK(input[key])) return null; anchor[key] = input[key]; }
  for (const key of numberFields) { if (input[key] === undefined) continue; if (!Number.isSafeInteger(input[key]) || input[key] < 0) return null; anchor[key] = input[key]; }
  if (anchor.type === 'block' && !anchor.blockId && !anchor.id) return null;
  if (anchor.type === 'component' && !anchor.componentId && !anchor.id) return null;
  if (anchor.type === 'artist' && !anchor.artistId && !anchor.id) return null;
  if (anchor.type === 'page' && anchor.pageIndex === undefined && !anchor.id) return null;
  if (anchor.type === 'canvas' && !anchor.itemId && !anchor.id) return null;
  return {objectId: value.objectId, anchor, open: value.open === true};
}

/** A component link is a reference to a caller-owned frozen trail, never its
 * contents. A random linkId is supplied by the host, not generated from data. */
export function cleanRegionComponentLink(value, {commit = false} = {}) {
  const fields = ['objectId','parentObjectId','componentIndex','linkId', ...(commit ? ['requestKey'] : [])];
  if (!value || typeof value !== 'object' || Array.isArray(value) || Reflect.ownKeys(value).some(key => !fields.includes(key)) || fields.some(key => !Object.hasOwn(value, key))) return null;
  if (!idOK(value.objectId) || !idOK(value.parentObjectId) || value.objectId === value.parentObjectId || !Number.isSafeInteger(value.componentIndex) || value.componentIndex < 0 || typeof value.linkId !== 'string' || !/^[A-Za-z0-9_-]{16,128}$/.test(value.linkId) || (commit && !idOK(value.requestKey))) return null;
  return Object.fromEntries(fields.map(key => [key, value[key]]));
}
const sameComponentLink = (left, right) => Boolean(left && right && ['objectId','parentObjectId','componentIndex','linkId'].every(key => left[key] === right[key]));
const componentDeclined = (error = '组件链接已过期、身份不符，或区域正在处理其他操作。') => ({ok: false, error});
// Keep replies for this desk session: retransmission cannot invoke an app
// callback twice. Reusing a requestId with different fields is always rejected.
function componentInbox() {
  const records = new Map();
  return {
    run(data, descriptor, callback) {
      const signature = JSON.stringify([data.kind, descriptor, data.linkEpoch]);
      const previous = records.get(data.requestId);
      if (previous) return previous.signature === signature ? previous.result : Promise.resolve(componentDeclined('重复消息的组件身份不符。'));
      const result = Promise.resolve().then(callback).catch(error => componentDeclined(errorText(error)));
      records.set(data.requestId, {signature, result});
      return result;
    },
    clear() { records.clear(); },
  };
}

export function regionMessage(desk, kind, payload = {}, extra = {}) {
  return {scope: SCOPE, version: VERSION, desk, kind, payload, ...extra};
}

/** Both window identity and origin are necessary; desk isolates stale same-origin sessions. */
export function validRegionMessage(event, {origin, source, desk, kinds}) {
  const data = event?.data;
  return event?.origin === origin && event.source === source && data?.scope === SCOPE && data.version === VERSION && data.desk === desk && typeof data.kind === 'string' && (!kinds || kinds.includes(data.kind)) && data.payload && typeof data.payload === 'object' && !Array.isArray(data.payload);
}

function requests(view, send, timeoutMs) {
  const pending = new Map();
  let sequence = 0;
  return {
    ask(kind, payload, expected, extra = {}) {
      const requestId = `${Date.now().toString(36)}-${++sequence}`;
      const result = new Promise((resolve, reject) => {
        const timer = view.setTimeout(() => { pending.delete(requestId); reject(new Error('区域未及时确认；当前编辑会话已保留。')); }, timeoutMs);
        pending.set(requestId, {resolve, reject, timer, expected, extra});
        send(kind, payload, {...extra, requestId});
      });
      result.requestId = requestId;
      return result;
    },
    accept(data) {
      const item = pending.get(data.replyTo);
      if (!item || item.expected !== data.kind || Object.keys(item.extra).some(key => data[key] !== item.extra[key])) return false;
      pending.delete(data.replyTo); view.clearTimeout(item.timer); item.resolve(data.payload); return true;
    },
    cancel() {
      for (const item of pending.values()) { view.clearTimeout(item.timer); item.reject(new Error('区域连接已结束；未确认操作未执行。')); }
      pending.clear();
    },
  };
}

/**
 * attach() follows a replaceable [data-region41-secondary] slot. The iframe itself
 * is appended to document.body, outside #app, and survives every host draw/close.
 * guardOpen()/finishPrimaryOpen() bracket the app's primary open operation.
 * prepareClose() saves and holds the child; call resume() on an aborted exit, or
 * logout() after host logout succeeds. close() only hides the secondary session.
 */
export function createRegions({getPrimaryId = () => '', onFocusPrimary = () => {}, onOpenPrimary, onRequestLogout, onComponentCommit, onComponentReturn, onStateChange = () => {}, url, view = globalThis.window, requestTimeoutMs = 15000} = {}) {
  if (new URL(view.location.href).searchParams.get('embedded') === '1') throw new Error('副编辑区不能再创建嵌套分屏。');
  const doc = view.document, origin = view.location.origin;
  let desk = randomID(view);
  const host = doc.createElement('section');
  host.className = 'region41-host'; host.hidden = true; host.setAttribute('aria-label', '副编辑区域');
  doc.body.appendChild(host);
  let frame = null, slot = null, observer = null, animation = null;
  let opened = false, ready = false, disposed = false, focused = 'primary', maximized = null, splitRatio = 0.5;
  let secondary = summary(null), primaryReservation = null, initialId = '', hostOpeningId = '', lastError = '', held = false, loggedOut = false, hostSelecting = false;
  const childReservations = new Map(), disposers = [];
  let componentLink = null, componentBusy = false, componentEpoch = 0, activeComponentEpoch = 0;
  const retiredComponentLinks = new Set(), knownComponentLinks = new Map(), componentCommits = new Set(), componentMessages = componentInbox();
  const retireComponentLink = () => { if (componentLink) retiredComponentLinks.add(componentLink.linkId); componentLink = null; activeComponentEpoch = 0; };
  const updateSecondary = state => { secondary = summary(state); if (componentLink && secondary.objectId !== componentLink.objectId) retireComponentLink(); };
  const listen = (node, type, fn, options) => { node.addEventListener(type, fn, options); disposers.push(() => node.removeEventListener(type, fn, options)); };
  const primaryID = () => String(getPrimaryId() || '');
  const secondaryIDs = () => new Set([secondary.objectId, initialId, hostOpeningId, ...childReservations.values()].filter(Boolean));
  const getState = () => ({open: opened, ready, desk, focused, maximized, splitRatio, secondaryObjectId: secondary.objectId || initialId || hostOpeningId, secondary: {...secondary}, primaryObjectId: primaryID(), pendingPrimaryObjectId: primaryReservation, pendingSecondaryObjectId: hostOpeningId || initialId || [...childReservations.values()][0] || '', held, loggedOut, componentLink: componentLink ? {...componentLink} : null, componentBusy, error: lastError});
  const emit = reason => { if (!disposed) onStateChange(getState(), reason); };
  const post = (kind, payload, extra) => frame?.contentWindow?.postMessage(regionMessage(desk, kind, payload, extra), origin);
  const channel = requests(view, post, requestTimeoutMs);
  const position = () => {
    animation = null;
    if (disposed) return;
    const rect = slot?.isConnected !== false ? slot?.getBoundingClientRect() : null;
    const visible = opened && maximized !== 'primary' && rect && rect.width > 0 && rect.height > 0;
    host.hidden = !visible;
    if (!visible) return;
    Object.assign(host.style, {left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`, height: `${rect.height}px`});
  };
  const schedulePosition = () => {
    if (animation !== null || disposed) return;
    animation = view.requestAnimationFrame ? view.requestAnimationFrame(position) : view.setTimeout(position, 0);
  };
  const attach = root => {
    if (disposed) return;
    const next = root?.querySelector?.('[data-region41-secondary]') || null;
    if (next !== slot) { observer?.disconnect(); slot = next; if (slot && view.ResizeObserver) { observer = new view.ResizeObserver(schedulePosition); observer.observe(slot); } }
    position();
  };
  const focus = (region = 'secondary') => {
    if (disposed) return false;
    if (region === 'primary') {
      // Returning to the manuscript must reveal it, including when its child
      // editor was maximized. Render the restored layout before focusing its
      // DOM; neither editor nor its drafts are reopened or discarded.
      const changed = focused !== 'primary' || maximized === 'secondary';
      focused = 'primary'; if (maximized === 'secondary') maximized = null;
      if (changed) emit('focus'); position(); onFocusPrimary(); return true;
    }
    if (!frame) return false;
    const changed = !opened || focused !== 'secondary' || maximized === 'primary';
    opened = true; focused = 'secondary'; if (maximized === 'primary') maximized = null;
    if (changed) emit('focus'); position();
    frame.focus?.({preventScroll: true}); frame.contentWindow?.focus?.(); post('focus', {}); return true;
  };
  const guardOpen = id => {
    if (disposed || !idOK(id)) return false;
    if (loggedOut && !reset()) return false;
    if (secondaryIDs().has(id)) { focus('secondary'); return false; }
    if (componentBusy) { lastError = '正在核对组件链接，请等待当前操作完成。'; emit('busy'); return false; }
    if (primaryReservation) { lastError = '主区正在打开对象，请等待当前操作完成。'; emit('busy'); return false; }
    primaryReservation = id; return true;
  };
  const finishPrimaryOpen = () => { primaryReservation = null; if (componentLink && primaryID() !== componentLink.parentObjectId) retireComponentLink(); emit('primary-state'); };
  const openPrimary = async id => {
    if (!onOpenPrimary || !idOK(id) || componentBusy) return false;
    if (secondaryIDs().has(id)) { focus('secondary'); return false; }
    // onOpenPrimary is the app's normal, guarded open entry point.
    await onOpenPrimary(id); return primaryID() === id;
  };
  const createFrame = id => {
    const target = new URL(url || view.location.href, view.location.href);
    if (target.origin !== origin) throw new Error('副编辑区必须使用同源地址。');
    target.searchParams.set('embedded', '1'); target.searchParams.set('object', id);
    target.searchParams.set('region', 'secondary'); target.searchParams.set('desk', desk);
    frame = doc.createElement('iframe'); frame.className = 'region41-frame'; frame.title = '副编辑区';
    frame.setAttribute('data-region41-frame', ''); frame.referrerPolicy = 'same-origin';
    initialId = id; frame.src = target.href; host.appendChild(frame);
  };
  const openSecondary = async id => {
    if (disposed || !idOK(id)) return false;
    if (loggedOut && !reset()) return false;
    if (id === primaryID() || id === primaryReservation) { focus('primary'); return false; }
    if (secondaryIDs().has(id)) { focus('secondary'); return true; }
    if (held) { lastError = '副区正在协调退出，尚不能切换对象。'; emit('busy'); return false; }
    if (frame && (!ready || initialId || hostOpeningId || hostSelecting || componentBusy || childReservations.size)) { lastError = '副区正在打开对象，请等待当前操作完成。'; focus('secondary'); emit('busy'); return false; }
    lastError = ''; opened = true; focused = 'secondary';
    if (!frame) { createFrame(id); emit('open'); position(); return true; }
    hostOpeningId = id; emit('opening'); position();
    try {
      const reply = await channel.ask('navigate', {id}, 'navigate-result');
      if (reply.state) updateSecondary(reply.state);
      if (!reply.ok) { lastError = errorText(reply.error || '副区保留当前对象，未完成切换。'); return false; }
      return secondary.objectId === id;
    } catch (error) { lastError = errorText(error); return false; }
    finally { hostOpeningId = ''; emit('secondary-state'); }
  };
  const selectSecondary = async value => {
    const selection = cleanRegionSelection(value);
    if (!selection) throw new TypeError('副区选区只能包含已支持的对象身份与定位字段。');
    if (disposed || !frame || !ready || held || loggedOut || initialId || hostOpeningId || hostSelecting || componentBusy || childReservations.size) return false;
    if (selection.objectId === primaryID() || selection.objectId === primaryReservation) { focus('primary'); return false; }
    if (!selection.open && selection.objectId !== secondary.objectId) return false;
    hostSelecting = true;
    if (selection.objectId !== secondary.objectId) hostOpeningId = selection.objectId;
    const wasOpen = opened, wasFocused = focused, wasMaximized = maximized;
    opened = true; focused = 'secondary'; if (maximized === 'primary') maximized = null;
    if (!wasOpen) emit('open'); else if (wasMaximized !== maximized) emit('maximize'); else if (wasFocused !== focused) emit('focus');
    position();
    try {
      const reply = await channel.ask('select', selection, 'select-result');
      if (reply.state) { const next = summary(reply.state); if (!sameSummary(secondary, next)) { updateSecondary(next); emit('secondary-state'); } }
      if (!reply.ok) { lastError = errorText(reply.error || '副区未采用该选区。'); return false; }
      return true;
    } catch (error) { lastError = errorText(error); return false; }
    finally { hostSelecting = false; hostOpeningId = ''; }
  };
  const componentContext = (descriptor, allowSaving = false) => !disposed && frame && ready && !held && !loggedOut && !initialId && !hostOpeningId && !hostSelecting && !childReservations.size && !primaryReservation && (allowSaving || !secondary.saving) && primaryID() === descriptor.parentObjectId && secondary.objectId === descriptor.objectId;
  const linkedComponent = descriptor => {
    if (componentLink && (primaryID() !== componentLink.parentObjectId || secondary.objectId !== componentLink.objectId)) retireComponentLink();
    return !retiredComponentLinks.has(descriptor.linkId) && sameComponentLink(componentLink, descriptor);
  };
  const attachComponent = async (value, restore = false, {isCurrent = () => true} = {}) => {
    const descriptor = cleanRegionComponentLink(value);
    if (!descriptor) throw new TypeError('组件链接只能包含成果、原稿、组件位置和随机链接身份。');
    const known = knownComponentLinks.get(descriptor.linkId);
    if (componentBusy || !componentContext(descriptor) || isCurrent() !== true || (known && !sameComponentLink(known, descriptor)) || (!restore && retiredComponentLinks.has(descriptor.linkId)) || (componentLink?.linkId === descriptor.linkId && !sameComponentLink(componentLink, descriptor)) || (restore && componentLink && !sameComponentLink(componentLink, descriptor))) return false;
    if (!restore && sameComponentLink(componentLink, descriptor)) return true;
    componentBusy = true;
    knownComponentLinks.set(descriptor.linkId, descriptor);
    const linkEpoch = ++componentEpoch;
    let accepted = false;
    try {
      const reply = await channel.ask(restore ? 'component-link-restore' : 'component-link', descriptor, 'component-link-result', {linkEpoch});
      if (!reply.ok || !componentContext(descriptor) || isCurrent() !== true) { lastError = errorText(reply.error || '组件链接身份已变化。'); return false; }
      // Sending confirmation is the activation boundary. Preparation has not
      // invoked the child app. Edits after this point are concurrent edits of
      // an established link; a failed final check revokes this exact epoch.
      const confirmed = await channel.ask('component-link-confirm', descriptor, 'component-link-confirm-result', {linkEpoch});
      if (!confirmed.ok || !componentContext(descriptor) || isCurrent() !== true) { lastError = errorText(confirmed.error || '组件链接身份已变化。'); return false; }
      if (componentLink && !sameComponentLink(componentLink, descriptor)) retireComponentLink();
      componentLink = descriptor; activeComponentEpoch = linkEpoch; retiredComponentLinks.delete(descriptor.linkId); lastError = ''; accepted = true; return true;
    } finally {
      if (!accepted) post('component-link-cancel', descriptor, {linkEpoch});
      componentBusy = false;
    }
  };
  const attachComponentLink = (value, options) => attachComponent(value, false, options);
  // Only the host may request explicit recovery after checking its frozen intent.
  // The scientific link/request identities stay unchanged; transport gets a new
  // epoch so pre-recovery messages and acknowledgements remain obsolete.
  const restoreComponentLink = (value, options) => attachComponent(value, true, options);
  const close = () => { if (disposed) return; opened = false; maximized = null; focused = 'primary'; position(); emit('close'); onFocusPrimary(); };
  const setSplitRatio = ratio => {
    if (!Number.isFinite(ratio)) return false;
    const next = Math.max(0.25, Math.min(0.75, ratio));
    if (next === splitRatio) return true;
    splitRatio = next; emit('resize'); schedulePosition(); return true;
  };
  const toggleMaximize = (region = 'secondary') => {
    if (!['primary','secondary'].includes(region) || (region === 'secondary' && !frame)) return false;
    maximized = maximized === region ? null : region;
    if (region === 'secondary') opened = true;
    emit('maximize'); schedulePosition(); return maximized;
  };
  const prepareClose = async () => {
    if (!frame) return {...secondary};
    if (!ready || initialId || hostOpeningId || hostSelecting || componentBusy || childReservations.size) throw new Error('副区仍在加载或切换对象；会话已保留。');
    let reply;
    try { reply = await channel.ask('prepare-close', {}, 'prepared'); }
    catch (error) { held = false; post('resume', {}); throw error; }
    if (reply.state) updateSecondary(reply.state);
    held = reply.ok === true;
    if (!reply.ok || secondary.dirty || secondary.saving) { held = false; post('resume', {}); throw new Error(errorText(reply.error || '副区仍有未保存编辑；退出已暂停。')); }
    emit('prepared'); return {...secondary};
  };
  const resume = () => { if (loggedOut) return false; held = false; post('resume', {}); emit('resume'); return true; };
  const logout = async () => {
    if (loggedOut) return true;
    if (frame && (!held || secondary.dirty || secondary.saving)) return false;
    if (frame) {
      const reply = await channel.ask('logout', {}, 'logged-out');
      if (!reply.ok) throw new Error(errorText(reply.error || '副区尚未完成退出，会话已保留。'));
      if (reply.state) updateSecondary(reply.state);
    }
    loggedOut = true; close(); return true;
  };
  const reset = () => {
    // Reuse the region controller after login, but only discard a frame after
    // the held, clean editor has acknowledged its app-level logout callback.
    if (disposed || !loggedOut || (frame && (!held || secondary.dirty || secondary.saving))) return false;
    channel.cancel(); frame?.remove(); frame = null;
    ready = false; opened = false; held = false; loggedOut = false; maximized = null; focused = 'primary';
    secondary = summary(null); initialId = ''; hostOpeningId = ''; primaryReservation = null; hostSelecting = false; lastError = ''; childReservations.clear();
    componentLink = null; componentBusy = false; componentEpoch = 0; activeComponentEpoch = 0; retiredComponentLinks.clear(); knownComponentLinks.clear(); componentCommits.clear(); componentMessages.clear();
    desk = randomID(view); position(); emit('reset'); return true;
  };
  const onMessage = event => {
    if (!frame || !validRegionMessage(event, {origin, source: frame.contentWindow, desk, kinds: ['ready','state','focus','request-open','open-complete','navigate-result','select-result','prepared','logged-out','request-logout','request-maximize','request-close','component-link-result','component-link-confirm-result','component-commit','component-return']})) return;
    const data = event.data, payload = data.payload;
    if (channel.accept(data)) return;
    if (data.kind === 'component-commit' || data.kind === 'component-return') {
      if (!idOK(data.requestId)) return;
      const commit = data.kind === 'component-commit', descriptor = cleanRegionComponentLink(payload, {commit});
      const extra = {replyTo: data.requestId, linkEpoch: data.linkEpoch};
      if (!descriptor) { post(data.kind + '-result', componentDeclined('组件通知只能包含已支持的身份字段。'), extra); return; }
      if (!Number.isSafeInteger(data.linkEpoch) || data.linkEpoch <= 0 || data.linkEpoch !== activeComponentEpoch) {
        // A visible manuscript may still be finishing its reference reads. A
        // return gesture may wait for the app-validated fresh handshake; it
        // never restores a link or authorizes a write by itself.
        const retryAfterLink = !commit && !held && !loggedOut && primaryID() === descriptor.parentObjectId && secondary.objectId === descriptor.objectId;
        post(data.kind + '-result', {...componentDeclined('组件消息属于旧的链接会话。'), retryAfterLink}, extra); return;
      }
      componentMessages.run(data, descriptor, async () => {
        const callback = commit ? onComponentCommit : onComponentReturn;
        if (componentBusy || !componentContext(descriptor, !commit) || !linkedComponent(descriptor) || typeof callback !== 'function') return componentDeclined();
        const commitKey = JSON.stringify([descriptor.linkId, descriptor.requestKey]);
        if (commit && componentCommits.has(commitKey)) return {ok: true};
        componentBusy = true;
        try {
          const result = await callback({...descriptor});
          if (result === false || data.linkEpoch !== activeComponentEpoch || !componentContext(descriptor, !commit) || !linkedComponent(descriptor)) return componentDeclined();
          if (commit) componentCommits.add(commitKey);
          return {ok: true};
        } finally { componentBusy = false; }
      }).then(reply => { if (!disposed) post(data.kind + '-result', reply, extra); });
      return;
    }
    switch (data.kind) {
      case 'ready': { const next = summary(payload.state), changed = !ready || !sameSummary(secondary, next); ready = true; updateSecondary(next); if (changed) emit('ready'); break; }
      case 'state': { const next = summary(payload.state); if (!sameSummary(secondary, next)) { updateSecondary(next); emit('secondary-state'); } break; }
      case 'focus': if (focused !== 'secondary') { focused = 'secondary'; emit('focus'); } break;
      case 'request-open': {
        if (!idOK(payload.id) || typeof data.requestId !== 'string') return;
        const conflict = payload.id === primaryID() || payload.id === primaryReservation;
        const allowed = !held && !componentBusy && !conflict && !childReservations.size;
        if (allowed) childReservations.set(data.requestId, payload.id);
        post('open-result', {allowed, reason: conflict ? '对象已在主区打开；已聚焦主区。' : held ? '区域正在协调退出。' : allowed ? '' : '副区仍有打开操作未完成。'}, {replyTo: data.requestId});
        if (conflict) focus('primary');
        break;
      }
      case 'open-complete': {
        if (typeof payload.requestId !== 'string' || !childReservations.has(payload.requestId)) return;
        const attempted = childReservations.get(payload.requestId); childReservations.delete(payload.requestId);
        if (initialId === attempted) initialId = '';
        updateSecondary(payload.state); emit('secondary-state'); break;
      }
      case 'request-logout': {
        if (typeof data.requestId !== 'string') return;
        Promise.resolve().then(() => {
          if (!onRequestLogout) throw new Error('请从主工作区退出；当前副区会话已保留。');
          return onRequestLogout();
        }).then(result => post('logout-result', {ok: result !== false}, {replyTo: data.requestId}), error => post('logout-result', {ok: false, error: errorText(error)}, {replyTo: data.requestId}));
        break;
      }
      case 'request-maximize':
      case 'request-close': {
        if (typeof data.requestId !== 'string') return;
        if (data.kind === 'request-maximize') toggleMaximize('secondary'); else close();
        post('layout-result', {ok: true}, {replyTo: data.requestId}); break;
      }
    }
  };
  listen(view, 'message', onMessage);
  listen(view, 'resize', schedulePosition);
  listen(view, 'scroll', schedulePosition, true);
  listen(doc, 'click', event => { if (event.target?.closest?.('[data-region41-primary]') && !host.contains(event.target) && focused !== 'primary') { focused = 'primary'; Promise.resolve().then(() => emit('focus')); } });
  const destroy = () => {
    // Unknown/loading sessions are also retained: absence of a dirty flag is not
    // evidence that destroying an editor is safe.
    if (frame && (!held || secondary.dirty || secondary.saving)) return false;
    if (disposed) return true;
    disposed = true; channel.cancel(); observer?.disconnect();
    if (animation !== null) { if (view.cancelAnimationFrame) view.cancelAnimationFrame(animation); else view.clearTimeout(animation); }
    disposers.forEach(dispose => dispose()); host.remove(); return true;
  };
  return {attach, openSecondary, openPrimary, selectSecondary, attachComponentLink, restoreComponentLink, isOpen: () => opened, getState, setSplitRatio, toggleMaximize, close, focus, guardOpen, finishPrimaryOpen, prepareClose, resume, logout, reset, destroy};
}

/** Install once in the embedded app. requestOpen and finishOpen bracket every open. */
export function embeddedRegionBridge({getState = () => ({}), persist = async () => {}, onOpen, onSelect, onComponentLink, onComponentLinkCancelled, onError = () => {}, onLogout = () => {}, view = globalThis.window, requestTimeoutMs = 15000} = {}) {
  const doc = view.document, params = new URL(view.location.href).searchParams;
  const desk = params.get('desk') || '', region = params.get('region') || '';
  const isEmbedded = params.get('embedded') === '1' && region === 'secondary' && Boolean(desk) && view.parent !== view;
  const origin = view.location.origin, disposers = [];
  let destroyed = false, activeOpen = null, requesting = false, hostOpening = false, selecting = false, held = false, preparing = false, resumeRequested = false, shield = null;
  let inertRoot = null, previousInert = false;
  let componentLink = null, componentBusy = false, highestComponentEpoch = 0, activeComponentEpoch = 0, pendingComponent = null, activeComponentAttempt = null;
  const cancelledComponentEpochs = new Set();
  const componentAttemptKey = (descriptor, epoch) => JSON.stringify([descriptor, epoch]);
  const retiredComponentLinks = new Set(), knownComponentLinks = new Map(), componentMessages = componentInbox();
  const retireComponentLink = () => { if (componentLink) retiredComponentLinks.add(componentLink.linkId); componentLink = null; activeComponentEpoch = 0; };
  const post = (kind, payload, extra) => { if (isEmbedded && !destroyed) view.parent.postMessage(regionMessage(desk, kind, payload, extra), origin); };
  const channel = requests(view, post, requestTimeoutMs);
  const listen = (node, type, fn, options) => { node.addEventListener(type, fn, options); disposers.push(() => node.removeEventListener(type, fn, options)); };
  const publish = () => { const state = summary(getState()); if (componentLink && state.objectId !== componentLink.objectId) retireComponentLink(); notifyLinkWaiters(); post('state', {state}); return state; };
  const hold = value => {
    held = value;
    if(value)notifyLinkWaiters();
    if (value && !shield) {
      inertRoot = doc.getElementById('app'); previousInert = Boolean(inertRoot?.inert); if (inertRoot) inertRoot.inert = true;
      shield = doc.createElement('div'); shield.className = 'region41-close-shield'; shield.setAttribute('role', 'status');
      shield.textContent = '正在保存并协调退出，请稍候。'; doc.body.appendChild(shield);
    } else if (!value && shield) {
      if (inertRoot) inertRoot.inert = previousInert;
      shield.remove(); shield = null; inertRoot = null;
    }
  };
  const requestOpen = async id => {
    if (!idOK(id)) return false;
    if (!isEmbedded) return true;
    if (destroyed || held || preparing || requesting || activeOpen || componentBusy || pendingComponent) return false;
    requesting = true;
    const request = channel.ask('request-open', {id}, 'open-result');
    try {
      // Each request has its own transaction token, carried back in the result.
      const reply = await request;
      if (reply.allowed && typeof reply.requestId === 'string') activeOpen = {id, requestId: reply.requestId};
      return Boolean(activeOpen);
    } catch (error) {
      // A late reply is ignored by the channel. Release only this attempt's
      // reservation, allowing a later retry without unloading the editor.
      post('open-complete', {requestId: request.requestId, state: summary(getState())});
      throw error;
    } finally { requesting = false; }
  };
  const finishOpen = () => {
    const attempt = activeOpen; activeOpen = null;
    const state = summary(getState());
    if (componentLink && state.objectId !== componentLink.objectId) retireComponentLink();
    notifyLinkWaiters();
    if (attempt) post('open-complete', {requestId: attempt.requestId, state});
    else publish();
    return state;
  };
  const prepareClose = async () => {
    if (activeOpen || requesting || hostOpening || selecting || componentBusy || pendingComponent || preparing) throw new Error('副区仍在切换或保存，请等待当前操作完成。');
    preparing = true; resumeRequested = false; hold(true);
    try {
      await persist(); const state = summary(getState());
      if (state.dirty || state.saving) throw new Error('副区仍有未保存编辑；当前会话已保留。');
      if (shield) shield.textContent = '此区域已保存，等待退出完成。';
      return state;
    } catch (error) { hold(false); throw error; }
    finally { preparing = false; if (resumeRequested) hold(false); }
  };
  const requestLogout = async () => {
    if (!isEmbedded || destroyed) return false;
    const reply = await channel.ask('request-logout', {}, 'logout-result');
    if (!reply.ok && reply.error) throw new Error(reply.error);
    return reply.ok === true;
  };
  const requestLayout = async kind => {
    if (!isEmbedded || destroyed) return false;
    const reply = await channel.ask(kind, {}, 'layout-result'); return reply.ok === true;
  };
  const componentContext = (descriptor, allowSaving = false) => isEmbedded && !destroyed && !held && !preparing && !requesting && !activeOpen && !hostOpening && !selecting && (allowSaving || !summary(getState()).saving) && summary(getState()).objectId === descriptor.objectId;
  const linkedComponent = descriptor => {
    if (componentLink && summary(getState()).objectId !== componentLink.objectId) retireComponentLink();
    return !retiredComponentLinks.has(descriptor.linkId) && sameComponentLink(componentLink, descriptor);
  };
  const linkWaiters = new Set();
  const notifyLinkWaiters = () => { for (const check of [...linkWaiters]) check(); };
  const waitForRestoredLink = (descriptor, oldEpoch) => new Promise(resolve => {
    const timer = view.setTimeout(() => finish(false), requestTimeoutMs);
    const check = () => {
      if (destroyed || held || summary(getState()).objectId !== descriptor.objectId) finish(false);
      else if (!componentBusy && activeComponentEpoch > oldEpoch && linkedComponent(descriptor)) finish(true);
    };
    function finish(value) { view.clearTimeout(timer); linkWaiters.delete(check); resolve(value); }
    linkWaiters.add(check); check();
  });
  const requestComponent = async (kind, value, mayWait = true) => {
    const descriptor = cleanRegionComponentLink(value, {commit: kind === 'component-commit'});
    if (!descriptor) throw new TypeError('组件通知只能包含成果、原稿、组件位置、随机链接及提交请求身份。');
    if (componentBusy || !componentContext(descriptor, kind === 'component-return') || !linkedComponent(descriptor)) return false;
    componentBusy = true;
    const linkEpoch = activeComponentEpoch;
    let reply;
    try { reply = await channel.ask(kind, descriptor, kind + '-result', {linkEpoch}); }
    finally { componentBusy = false; }
    // Waiting owns no request lock. Its timeout must never release the lock
    // of a newer handshake callback that is still validating its source.
    if (kind === 'component-return' && mayWait && reply.retryAfterLink === true) {
      if (await waitForRestoredLink(descriptor, linkEpoch)) return requestComponent(kind, descriptor, false);
      return false;
    }
    return reply.ok === true && linkEpoch === activeComponentEpoch && componentContext(descriptor, kind === 'component-return') && linkedComponent(descriptor);
  };
  const cancelComponentAttempt = async attempt => {
    attempt.cancelled = true;
    cancelledComponentEpochs.add(componentAttemptKey(attempt.descriptor, attempt.linkEpoch));
    view.clearTimeout(attempt.timer);
    if (attempt.activating) return {ok: true}; // The callback retains its lock until settled.
    if (pendingComponent === attempt) pendingComponent = null;
    if (activeComponentEpoch === attempt.linkEpoch && sameComponentLink(componentLink, attempt.descriptor)) { componentLink = null; activeComponentEpoch = 0; activeComponentAttempt = null; }
    if (attempt.callbackInvoked && !attempt.cleanupInvoked) {
      attempt.cleanupInvoked = true;
      try { await onComponentLinkCancelled?.({...attempt.descriptor}, {linkEpoch: attempt.linkEpoch}); }
      catch (error) { try { onError(error); } catch {} return componentDeclined(errorText(error)); }
    }
    return {ok: true};
  };
  const onMessage = async event => {
    if (!validRegionMessage(event, {origin, source: view.parent, desk, kinds: ['open-result','navigate','select','focus','prepare-close','resume','logout','logout-result','layout-result','component-link','component-link-restore','component-link-confirm','component-link-cancel','component-commit-result','component-return-result']})) return;
    const data = event.data, payload = data.payload;
    if (data.kind === 'open-result') {
      // Keep the request token out of caller-visible state, but retain it until
      // finishOpen explicitly reports success/failure and the actual object.
      channel.accept({...data, payload: {...payload, requestId: data.replyTo}}); return;
    }
    if (channel.accept(data)) return;
    if (data.kind === 'component-link-cancel') {
      const descriptor = cleanRegionComponentLink(payload), linkEpoch = data.linkEpoch;
      if (!descriptor || !Number.isSafeInteger(linkEpoch) || linkEpoch <= 0) return;
      cancelledComponentEpochs.add(componentAttemptKey(descriptor, linkEpoch));
      const attempt = pendingComponent?.linkEpoch === linkEpoch && sameComponentLink(pendingComponent.descriptor, descriptor) ? pendingComponent : activeComponentAttempt?.linkEpoch === linkEpoch && sameComponentLink(activeComponentAttempt.descriptor, descriptor) ? activeComponentAttempt : null;
      if (attempt) await cancelComponentAttempt(attempt);
      notifyLinkWaiters(); return;
    }
    if (['component-link', 'component-link-restore', 'component-link-confirm'].includes(data.kind)) {
      if (!idOK(data.requestId)) return;
      const descriptor = cleanRegionComponentLink(payload), restore = data.kind === 'component-link-restore', linkEpoch = data.linkEpoch, confirming = data.kind === 'component-link-confirm';
      const extra = {replyTo: data.requestId, linkEpoch}, resultKind = confirming ? 'component-link-confirm-result' : 'component-link-result';
      if (!descriptor) { post(resultKind, componentDeclined('组件链接只能包含已支持的身份字段。'), extra); return; }
      if (!Number.isSafeInteger(linkEpoch) || linkEpoch <= 0 || linkEpoch < highestComponentEpoch || cancelledComponentEpochs.has(componentAttemptKey(descriptor, linkEpoch))) { post(resultKind, componentDeclined('组件链接消息已过期。'), extra); return; }
      const reply = await componentMessages.run(data, descriptor, async () => {
        if (cancelledComponentEpochs.has(componentAttemptKey(descriptor, linkEpoch))) return componentDeclined('组件链接消息已取消。');
        if (confirming) {
          const attempt = pendingComponent;
          if (componentBusy || !attempt || attempt.linkEpoch !== linkEpoch || !sameComponentLink(attempt.descriptor, descriptor) || !componentContext(descriptor)) return componentDeclined();
          componentBusy = true; attempt.activating = true; attempt.callbackInvoked = true;
          let accepted = false;
          try {
            const result = await onComponentLink({...descriptor}, {restore: attempt.restore, linkEpoch});
            if (result === false || attempt.cancelled || linkEpoch !== highestComponentEpoch || !componentContext(descriptor)) return componentDeclined();
            if (componentLink && !sameComponentLink(componentLink, descriptor)) retireComponentLink();
            componentLink = descriptor; activeComponentEpoch = linkEpoch; activeComponentAttempt = attempt; retiredComponentLinks.delete(descriptor.linkId);
            view.clearTimeout(attempt.timer); pendingComponent = null; accepted = true;
            return {ok: true};
          } finally {
            attempt.activating = false;
            try { if (!accepted) { const cancelled = await cancelComponentAttempt(attempt); if (!cancelled.ok) throw new Error(cancelled.error); } }
            finally { componentBusy = false; }
          }
        }
        const known = knownComponentLinks.get(descriptor.linkId);
        if (componentBusy || pendingComponent || linkEpoch <= highestComponentEpoch || !componentContext(descriptor) || typeof onComponentLink !== 'function' || (known && !sameComponentLink(known, descriptor)) || (!restore && retiredComponentLinks.has(descriptor.linkId)) || (componentLink?.linkId === descriptor.linkId && !sameComponentLink(componentLink, descriptor)) || (restore && componentLink && !sameComponentLink(componentLink, descriptor))) return componentDeclined();
        highestComponentEpoch = linkEpoch; knownComponentLinks.set(descriptor.linkId, descriptor);
        const attempt = {descriptor, linkEpoch, restore, cancelled: false, activating: false, callbackInvoked: false, cleanupInvoked: false};
        attempt.timer = view.setTimeout(() => { cancelComponentAttempt(attempt); notifyLinkWaiters(); }, requestTimeoutMs);
        pendingComponent = attempt;
        return {ok: true};
      });
      post(resultKind, reply, extra); notifyLinkWaiters(); return;
    }
    if (data.kind === 'focus') { view.focus?.(); return; }
    if (data.kind === 'resume') { resumeRequested = true; if (!preparing) hold(false); return; }
    if (data.kind === 'logout') {
      if (typeof data.requestId !== 'string') return;
      if (!held || preparing) { post('logged-out', {ok: false, state: summary(getState()), error: '副区尚未完成退出前保存。'}, {replyTo: data.requestId}); return; }
      try { await onLogout(); const state = publish(); post('logged-out', {ok: true, state}, {replyTo: data.requestId}); }
      catch (error) { post('logged-out', {ok: false, state: summary(getState()), error: errorText(error)}, {replyTo: data.requestId}); }
      return;
    }
    if (typeof data.requestId !== 'string') return;
    if (data.kind === 'select') {
      const selection = cleanRegionSelection(payload);
      if (!selection || !onSelect || held || hostOpening || selecting || componentBusy || pendingComponent || activeOpen || requesting || (!selection.open && summary(getState()).objectId !== selection.objectId)) { post('select-result', {ok: false, state: summary(getState()), error: '选区身份无效，或当前副区尚不能定位此对象。'}, {replyTo: data.requestId}); return; }
      selecting = true;
      try { const result = await onSelect(selection); post('select-result', {ok: result !== false, state: summary(getState())}, {replyTo: data.requestId}); }
      catch (error) { post('select-result', {ok: false, state: summary(getState()), error: errorText(error)}, {replyTo: data.requestId}); }
      finally { selecting = false; }
    } else if (data.kind === 'navigate') {
      if (!idOK(payload.id) || !onOpen || held || hostOpening || selecting || componentBusy || pendingComponent || activeOpen || requesting) { post('navigate-result', {ok: false, state: summary(getState()), error: '副区尚未准备好切换对象。'}, {replyTo: data.requestId}); return; }
      hostOpening = true;
      try { await onOpen(payload.id); const state = summary(getState()); post('navigate-result', {ok: state.objectId === payload.id, state}, {replyTo: data.requestId}); }
      catch (error) { post('navigate-result', {ok: false, state: summary(getState()), error: errorText(error)}, {replyTo: data.requestId}); }
      finally { hostOpening = false; }
    } else if (data.kind === 'prepare-close') {
      try { const state = await prepareClose(); post('prepared', {ok: true, state}, {replyTo: data.requestId}); }
      catch (error) { post('prepared', {ok: false, state: summary(getState()), error: errorText(error)}, {replyTo: data.requestId}); }
    }
  };
  if (isEmbedded) {
    listen(view, 'message', onMessage);
    listen(doc, 'pointerdown', event => { if (held) { event.preventDefault(); event.stopImmediatePropagation(); } else post('focus', {}); }, true);
    for (const type of ['keydown','beforeinput']) listen(doc, type, event => { if (held) { event.preventDefault(); event.stopImmediatePropagation(); } }, true);
    post('ready', {state: summary(getState())});
  }
  const destroy = () => { destroyed = true; if (pendingComponent) { view.clearTimeout(pendingComponent.timer); pendingComponent.cancelled = true; } notifyLinkWaiters(); channel.cancel(); componentMessages.clear(); retiredComponentLinks.clear(); componentLink = null; disposers.forEach(dispose => dispose()); hold(false); };
  return {requestOpen, finishOpen, publish, prepareClose, requestLogout, notifyComponentCommit: value => requestComponent('component-commit', value), requestComponentReturn: value => requestComponent('component-return', value), requestMaximize: () => requestLayout('request-maximize'), requestClose: () => requestLayout('request-close'), resume: () => hold(false), destroy, isEmbedded, desk, region};
}
