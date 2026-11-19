/** Saved figure annotation navigation. This module never edits an object or image. */
const active = new WeakMap();
const shaPattern = /^[a-f0-9]{64}$/i;
const shaOf = asset => typeof asset === 'string' ? asset : asset?.sha256 || asset?.sha;
const own = (object, key) => Object.prototype.hasOwnProperty.call(object || {}, key);
const invalid = message => { throw new Error(message); };

function bounds(value) {
  if (!Array.isArray(value) || value.length !== 4 || Array.from(value).some(n => typeof n !== 'number' || !Number.isFinite(n) || n < 0) || value[2] <= 0 || value[3] <= 0 || value[0] + value[2] > 1 + 1e-9 || value[1] + value[3] > 1 + 1e-9) {
    invalid('批注区域坐标无效；请重新定位，原批注保留。');
  }
  return [...value];
}

/** No DOM access: verify the annotation against the saved object and displayed bytes. */
export function resolveFigureAnnotation41({object, annotation, displayedAssetSha, dirty = false, preview = false} = {}) {
  if (object?.kind !== 'figure' || !object.id || !Number.isInteger(object.revision) || object.revision < 1 || !shaPattern.test(object.canonical_source_sha256 || '')) {
    invalid('缺少当前已保存图形的完整身份；请重新读取后定位。');
  }
  if (dirty || preview) invalid('当前有未采用图形预览或编辑；先采用或取消，再定位已保存批注。');
  if (!annotation || annotation.object_id !== object.id || annotation.revision !== object.revision) {
    invalid('批注绑定另一幅图或旧修订；请打开对应保存版本，原批注保留。');
  }
  if (annotation.status === 'orphaned' || annotation.status === 'text_changed') invalid('批注锚点已变化，不能自动定位到当前图像；请核对原版本。');
  if (!shaPattern.test(displayedAssetSha || '')) invalid('当前显示图像没有可验证的资产身份，未绘制定位框。');

  const output = object.metadata?.last_export;
  const provenance = output?.provenance;
  if (own(output, 'preview_identity') || own(provenance, 'preview_identity')) invalid('当前显示的是候选预览，不能定位已保存批注。');
  const formal = output?.status === 'generated' && provenance?.object_id === object.id && provenance?.revision === object.revision && provenance?.source_sha256 === object.canonical_source_sha256 && !output?.replay?.failures?.length;
  const formalImages = formal ? ['figure.png', 'figure.svg'].map(name => shaOf(output.assets?.[name])).filter(Boolean) : [];
  const staticImage = object.content?.editable_source_available === false ? shaOf(object.content.preview) : null;
  if (!formalImages.includes(displayedAssetSha) && displayedAssetSha !== staticImage) {
    invalid('当前图像与已保存来源或渲染版本不一致；请打开对应图像后再定位。');
  }

  const anchor = annotation.anchor || {};
  const source = anchor.render_source;
  const requireSource = () => {
    if (source?.object_id !== object.id || source?.revision !== object.revision || source?.source_sha256 !== object.canonical_source_sha256) {
      invalid('批注的渲染来源已变化；不能把旧锚点贴到当前图像。');
    }
  };
  let kind, bbox;
  if (anchor.figure_region) {
    requireSource();
    if (anchor.figure_region.coordinates !== 'whole_figure_normalized_top_left') invalid('批注区域使用了不支持的坐标系统；请核对原图。');
    if (source.preview_sha256 !== displayedAssetSha) invalid('批注绑定的图像资产与当前显示不同；请打开批注对应的原图。');
    bbox = bounds(anchor.figure_region.bbox);
    kind = bbox.every((n, i) => n === [0, 0, 1, 1][i]) ? 'whole' : 'region';
  } else if (anchor.artist_id) {
    requireSource();
    if (!formal || object.content?.editable_source_available === false) invalid('当前图没有可验证的真实元素；只能定位整图或已保存区域。');
    const items = Array.isArray(output.manifest) ? output.manifest.filter(item => item.id === anchor.artist_id) : [];
    if (items.length !== 1) invalid('批注中的图元素身份已不存在或不唯一；请重新定位。');
    bbox = bounds(items[0].bbox);
    kind = 'artist';
  } else if (anchor.object_id === object.id && !anchor.block_id && !anchor.node_id && !anchor.component_id) {
    // Legacy whole-image comments bind object + revision, not an invented region.
    if (source) requireSource();
    if (source?.preview_sha256 && source.preview_sha256 !== displayedAssetSha) invalid('整图批注的图像资产与当前显示不同；请核对原图。');
    kind = 'whole';
    bbox = [0, 0, 1, 1];
  } else invalid('此批注没有可用的整图、区域或真实元素锚点。');
  return {kind, bbox, objectId: object.id, revision: object.revision, sourceSha: object.canonical_source_sha256, previewSha: displayedAssetSha, annotationId: annotation.id || null};
}

function displayedSha(image) {
  const base = image.ownerDocument?.location?.href || 'http://localhost/';
  const url = new URL(image.currentSrc || image.getAttribute('src') || '', base);
  if (url.origin !== new URL(base).origin) invalid('当前图像不是此服务的已登记资产，未绘制定位框。');
  return url.pathname.match(/^\/api\/assets\/([a-f0-9]{64})$/i)?.[1];
}

/** Frame-local scrolling only: never scroll the window or another editor area. */
export function figureAnnotationScroll41({frameRect, imageRect, bbox, scrollLeft = 0, scrollTop = 0, clientWidth, clientHeight, scrollWidth, scrollHeight}) {
  const target = bounds(bbox);
  const numbers = [frameRect?.left, frameRect?.top, imageRect?.left, imageRect?.top, imageRect?.width, imageRect?.height, scrollLeft, scrollTop, clientWidth, clientHeight, scrollWidth, scrollHeight];
  if (numbers.some(n => !Number.isFinite(n)) || imageRect.width <= 0 || imageRect.height <= 0 || clientWidth <= 0 || clientHeight <= 0) invalid('图像尚未显示，无法定位；请等待图像载入后重试。');
  return {
    left: Math.max(0, Math.min(Math.max(0, scrollWidth - clientWidth), scrollLeft + imageRect.left - frameRect.left + (target[0] + target[2] / 2) * imageRect.width - clientWidth / 2)),
    top: Math.max(0, Math.min(Math.max(0, scrollHeight - clientHeight), scrollTop + imageRect.top - frameRect.top + (target[1] + target[3] / 2) * imageRect.height - clientHeight / 2)),
  };
}

/** Call before the host redraws/navigates. Idempotent, with no document listeners. */
export function clearFigureAnnotation41(root) {
  const state = active.get(root);
  if (!state) return false;
  active.delete(root);
  state.dispose();
  return true;
}

/** Add an independently removable outline, preserving image pixels and object content. */
export function locateFigureAnnotation41({root, object, annotation, dirty = false, preview = false} = {}) {
  // Failed requests also remove an earlier outline, so it cannot label a new target.
  clearFigureAnnotation41(root);
  const holder = root?.querySelector('[data-figure-image]');
  const image = holder?.querySelector('img');
  const frame = holder?.closest('[data-figure-stage]');
  if (!image || !frame || !image.complete || !image.naturalWidth) invalid('当前编辑区没有载入的图像，无法定位批注。');
  const target = resolveFigureAnnotation41({object, annotation, displayedAssetSha: displayedSha(image), dirty, preview});
  const doc = image.ownerDocument;
  const outline = doc.createElement('div');
  outline.className = 'figure-annotation41-outline';
  outline.dataset.figureAnnotation41Outline = '';
  outline.setAttribute('role', 'img');
  outline.setAttribute('aria-label', target.kind === 'whole' ? '整图批注定位' : target.kind === 'artist' ? '真实图元素批注定位' : '区域批注定位');
  Object.assign(outline.style, {position: 'absolute', left: `${target.bbox[0] * 100}%`, top: `${target.bbox[1] * 100}%`, width: `${target.bbox[2] * 100}%`, height: `${target.bbox[3] * 100}%`, boxSizing: 'border-box', border: '2px dashed #1765d1', boxShadow: '0 0 0 1px #fff, inset 0 0 0 1px #fff', pointerEvents: 'none', zIndex: '6'});
  const controls = doc.createElement('div');
  controls.className = 'figure-annotation41-controls';
  controls.dataset.figureAnnotation41Controls = '';
  controls.setAttribute('role', 'status');
  Object.assign(controls.style, {display: 'flex', alignItems: 'center', gap: '8px', padding: '3px 9px', minHeight: '24px', flexShrink: '0', background: '#e8edf3', color: '#30425f', fontSize: '11px'});
  const label = doc.createElement('span');
  label.textContent = `${target.kind === 'whole' ? '已定位整图' : target.kind === 'artist' ? '已定位真实图元素' : '已定位批注区域'} · r${target.revision} · 仅显示定位框`;
  const close = doc.createElement('button');
  close.type = 'button';
  close.dataset.figureAnnotation41Clear = '';
  close.textContent = '清除定位';
  close.setAttribute('aria-label', '清除批注定位框');
  Object.assign(close.style, {border: '1px solid #9aaec9', borderRadius: '3px', background: '#f8faff', color: '#30425f', padding: '2px 6px', fontSize: '11px', cursor: 'pointer'});
  controls.appendChild(label);
  controls.appendChild(close);
  holder.appendChild(outline);
  const center = frame.parentElement;
  center.appendChild(controls);
  const clear = () => clearFigureAnnotation41(root);
  const onKey = event => { if (event.key === 'Escape') { event.stopPropagation(); clear(); } };
  const checkImage = () => { try { if (displayedSha(image) !== target.previewSha) clear(); } catch { clear(); } };
  close.addEventListener('click', clear);
  frame.addEventListener('keydown', onKey);
  image.addEventListener('load', checkImage);
  const Observer = doc.defaultView?.MutationObserver;
  const observer = Observer ? new Observer(checkImage) : null;
  observer?.observe(image, {attributes: true, attributeFilter: ['src', 'srcset']});
  active.set(root, {dispose() { observer?.disconnect(); close.removeEventListener('click', clear); frame.removeEventListener('keydown', onKey); image.removeEventListener('load', checkImage); outline.remove(); controls.remove(); }});
  try {
    const frameRect = frame.getBoundingClientRect();
    const focus = figureAnnotationScroll41({frameRect: {left: frameRect.left + (frame.clientLeft || 0), top: frameRect.top + (frame.clientTop || 0)}, imageRect: image.getBoundingClientRect(), bbox: target.bbox, scrollLeft: frame.scrollLeft || 0, scrollTop: frame.scrollTop || 0, clientWidth: frame.clientWidth, clientHeight: frame.clientHeight, scrollWidth: frame.scrollWidth, scrollHeight: frame.scrollHeight});
    frame.scrollLeft = focus.left;
    frame.scrollTop = focus.top;
    frame.focus({preventScroll: true});
  } catch (error) { clear(); throw error; }
  return {...target, clear};
}
