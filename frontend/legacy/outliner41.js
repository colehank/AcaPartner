// A local view of supplied objects. This module does not fetch, persist or mutate them.
const array = value => Array.isArray(value) ? value : [];
const string = value => value == null ? '' : String(value);
const key = (...parts) => JSON.stringify(parts);
const escapeHTML = value => string(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fold = value => string(value).normalize('NFKC').toLocaleLowerCase();
const own = (value, name) => Object.prototype.hasOwnProperty.call(value || {}, name);
const objectKinds = new Set(['paper','report','figure','diagram','poster','slides','workshop','question','concept']);
const noteKinds = new Set(['note','workshop_note']);
const names = {paper:'稿件',report:'报告',figure:'主图',diagram:'图解',poster:'海报',slides:'幻灯片',note:'笔记',workshop_note:'章节笔记',literature:'文献',data:'数据',code:'代码',section:'章节',page:'页面',axes:'坐标区',line:'曲线',collection:'散点／集合',image:'图像',legend:'图例',colorbar:'色条',title:'标题',xlabel:'横轴标签',ylabel:'纵轴标签',text:'文字',patch:'形状',group:'分组'};
const icons = {paper:'▤',report:'▤',figure:'▧',diagram:'◇',poster:'▥',slides:'▱',note:'≡',workshop_note:'≡',literature:'▣',data:'▦',code:'⌘',section:'§',page:'▯',axes:'⌞',line:'∿',collection:'⠿',image:'▧',group:'▸'};
const titleOf = object => string(object?.title || names[object?.kind] || '未命名对象');
const sameRevision = (a, b) => a != null && b != null && string(a) === string(b);
const assetSha = value => {
  const candidate = typeof value === 'object' && value ? value.sha || value.sha256 || value.asset || value.asset_sha : value;
  const match = string(candidate).match(/^(?:\/api\/assets\/)?([a-f\d]{64})$/i);
  return match ? match[1].toLowerCase() : '';
};

/**
 * Build occurrence nodes while keeping source identity in objectId and anchor.
 * figureManifest is the existing (object, content) resolver, or an array for
 * activeObject only. It is never used to invent elements in a static image.
 */
export function buildObjectTree({objects = [], projectId = '', activeObject = null, draft = null, figureManifest = null} = {}) {
  const warnings = [], defaults = new Set(), byKey = new Map();
  const catalog = new Map(array(objects).filter(o => o && o.id).map(o => [string(o.id), o]));
  const active = activeObject?.id ? {...activeObject, ...(draft && own(draft, 'title') ? {title:draft.title} : {}), ...(draft && own(draft, 'content') ? {content:draft.content} : {})} : null;
  if (active) catalog.set(string(active.id), active);
  const project = string(projectId || active?.project_id);
  const seenReferences = new Set();
  const make = (data, collapsed = false) => {
    const node = {title:'未命名对象',kind:'group',objectId:null,revision:null,relation:'structure',anchor:{type:'group'},children:[],flags:{},...data};
    if (byKey.has(node.key)) throw new Error('Duplicate outliner occurrence key');
    byKey.set(node.key, node);
    if (collapsed) defaults.add(node.key);
    return node;
  };
  const warn = (code, node, extra = {}) => warnings.push({code,key:node.key,objectId:node.objectId,...extra});
  const group = (scope, id, title, children, collapsed = false) => make({key:key(scope,'group',id),title,kind:'group',relation:'group',anchor:{type:'group',groupId:id},children}, collapsed);

  function resolveManifest(object) {
    const content = object.content || {};
    if (content.editable_source_available === false) return [];
    let result;
    try {
      result = typeof figureManifest === 'function' ? figureManifest(object, content)
        : Array.isArray(figureManifest) && object.id === active?.id ? figureManifest
        : object.metadata?.last_export?.manifest || content.manifest || content.object_manifest;
      // Legacy content.objects is accepted only when it carries renderer metadata.
      if (!result && array(content.objects).every(item => item && (Array.isArray(item.supported_properties) || item.property_schema || item.interaction))) result = content.objects;
    } catch (_error) {
      warnings.push({code:'manifest_unavailable',objectId:object.id});
      return [];
    }
    return array(result).filter(item => item && typeof item.id === 'string' && item.id && typeof item.type === 'string' && item.type);
  }

  function appendArtists(parent, object) {
    if (!['figure','diagram'].includes(object.kind)) return;
    if (object.content?.editable_source_available === false) {parent.flags.staticImage = true; return;}
    const provenance = object.metadata?.last_export?.provenance;
    if (provenance?.object_id && provenance.object_id !== object.id) {
      parent.flags.manifestUnavailable = true; warn('manifest_identity_mismatch',parent); return;
    }
    const manifest = resolveManifest(object);
    if (!manifest.length) {parent.flags.manifestUnavailable = true; return;}
    const items = new Map(), duplicates = new Set();
    for (const item of manifest) {
      if (items.has(item.id)) duplicates.add(item.id);
      else items.set(item.id, item);
    }
    // Duplicate renderer IDs cannot identify one exact Artist, so never make them selectable.
    for (const id of duplicates) {items.delete(id); warn('duplicate_artist_id', parent, {artistId:id});}
    const renderedRevision = provenance?.object_id === object.id ? provenance.revision : null;
    if (renderedRevision != null && !sameRevision(renderedRevision, object.revision)) parent.flags.staleRender = true;
    const artistNodes = new Map(), parents = new Map();
    const axes = [...items.values()].filter(item => item.type === 'axes').map(item => item.id).sort((a,b) => b.length-a.length);
    const figureRoot = [...items.values()].find(item => item.type === 'figure' && item.id === 'figure:root') || [...items.values()].find(item => item.type === 'figure');
    for (const item of items.values()) {
      let parentId = string(item.parent_id || item.parentId || item.axes_id || item.axesId || (typeof item.parent === 'string' ? item.parent : ''));
      const explicitParent = !!parentId;
      if (!parentId && item.type !== 'axes' && item.type !== 'figure') parentId = axes.find(id => item.id.startsWith(id + ':')) || '';
      if (!parentId && figureRoot && item.id !== figureRoot.id && (item.type === 'axes' || item.id.startsWith('figure:'))) parentId = figureRoot.id;
      if (parentId && (!items.has(parentId) || parentId === item.id)) {
        warn('artist_parent_unavailable', parent, {artistId:item.id,parentArtistId:parentId}); parentId = '';
      }
      parents.set(item.id, parentId);
      artistNodes.set(item.id, make({key:key(parent.key,'artist',item.id),title:string(item.label || names[item.type] || item.id),kind:item.type,objectId:object.id,revision:object.revision,relation:'structure',anchor:{type:'artist',artistId:item.id,axesId:item.type === 'axes' ? item.id : null,renderedRevision},flags:{explicitParent}}, item.type === 'figure' || item.type === 'axes'));
    }
    // Resolve only recorded relationships. Bboxes and panel letters are not ownership.
    for (const id of parents.keys()) {
      const visited = new Set([id]); let cursor = parents.get(id);
      while (cursor) {
        if (visited.has(cursor)) {parents.set(id, ''); warn('artist_parent_cycle', parent, {artistId:id}); break;}
        visited.add(cursor); cursor = parents.get(cursor);
      }
    }
    const unassigned = [];
    for (const [id, node] of artistNodes) {
      let cursor = id, axesId = null;
      while (cursor) {if (items.get(cursor)?.type === 'axes') {axesId = cursor; break;} cursor = parents.get(cursor);}
      node.anchor.axesId = axesId;
      const parentId = parents.get(id);
      if (parentId) artistNodes.get(parentId).children.push(node);
      else if (node.kind === 'figure' || node.kind === 'axes') parent.children.push(node);
      else {node.flags.parentUnknown = true; unassigned.push(node);}
    }
    if (unassigned.length) parent.children.push(group(parent.key,'unassigned-artists','其他已登记元素',unassigned,true));
  }

  function reference(ref, parentObject, occurrenceKey, anchor, path) {
    const id = string(ref.component_id || ref.object_id || ref.id), target = catalog.get(id);
    const adoptedRevision = ref.revision ?? ref.component_revision ?? null;
    const node = make({key:occurrenceKey,title:titleOf(target || ref),kind:target?.kind || 'component',objectId:id || null,revision:adoptedRevision,relation:'reference',anchor:{...anchor,componentId:id,revision:adoptedRevision},flags:{currentRevision:target?.revision ?? null}}, ['figure','diagram'].includes(target?.kind));
    if (!id || !target) {node.flags.missing = true; warn('reference_unavailable',node); return node;}
    if (target.archived) node.flags.archived = true;
    if (adoptedRevision == null || !sameRevision(adoptedRevision,target.revision)) {
      node.flags.revisionUnavailable = true; warn('reference_revision_unavailable',node); return node;
    }
    const expectedSha = ref.source_sha256 || ref.sha256;
    const actualSha = target.canonical_source_sha256 || target.metadata?.canonical_source_sha256;
    if (expectedSha && actualSha && expectedSha !== actualSha) {node.flags.sourceMismatch = true; warn('reference_source_mismatch',node); return node;}
    if (path.has(id)) {node.flags.cycle = true; warn('reference_cycle',node); return node;}
    const identity = key(id,adoptedRevision);
    if (seenReferences.has(identity)) {node.flags.shared = true; return node;}
    seenReferences.add(identity);
    if (path.size >= 32) {node.flags.depthLimited = true; warn('reference_depth_limit',node); return node;}
    appendObject(node,target,new Set([...path,id]));
    return node;
  }

  function appendObject(parent, object, path) {
    const content = object.content || {}, blocks = array(content.blocks);
    const sections = new Map([...array(object.metadata?.article?.sections),...array(object.metadata?.workbench?.assembly?.modules)].filter(row => row?.heading_block_id).map(row => [string(row.heading_block_id),row]));
    const moduleIds = new Set(array(object.metadata?.workbench?.assembly?.modules).map(row => string(row.heading_block_id)));
    const stack = [], blockParents = new Map(), blockIds = new Set(), duplicates = new Set();
    for (const block of blocks) if (block?.id) {if (blockIds.has(string(block.id))) duplicates.add(string(block.id)); blockIds.add(string(block.id));}
    for (const block of blocks) {
      if (!block || !block.id) continue;
      const id = string(block.id), section = sections.get(id);
      if (duplicates.has(id)) {warn('duplicate_block_id',parent,{blockId:id}); continue;}
      if (block.kind === 'heading' || section) {
        const raw = string(block.text || section?.title || section?.heading || '未命名章节');
        const match = raw.match(/^\s*(#{1,6})\s+/), number = raw.match(/^\s*(\d+(?:\.\d+)*)[.、\s]/);
        const level = moduleIds.has(id) ? 0 : Math.min(6,Number.isInteger(block.level) && block.level > 0 ? block.level : match ? match[1].length : number ? number[1].split('.').length : 1);
        while (stack.length && stack.at(-1).level >= level) stack.pop();
        // Open top-level chapters only. An unlevelled source heading remains a
        // peer; compact display must not invent hierarchy or remove relations.
        const node = make({key:key(parent.key,'block',id),title:raw.replace(/^\s*#{1,6}\s+/,''),kind:'section',objectId:object.id,revision:object.revision,relation:'structure',anchor:{type:'block',blockId:id,sectionId:section?.id || null,level}}, stack.length > 0);
        (stack.at(-1)?.node || parent).children.push(node); stack.push({node,level});
      }
      blockParents.set(id,stack.at(-1)?.node || parent);
    }
    const occurrences = new Map();
    array(content.components).forEach((ref,index) => {
      if (!ref || typeof ref !== 'object') return;
      const id = string(ref.id || ref.object_id), afterBlockId = string(ref.after_block_id) || null;
      const identity = string(ref.slot_id || ref.instance_id || ref.ref_id || ref.key) || key(id,afterBlockId);
      const ordinal = occurrences.get(identity) || 0; occurrences.set(identity,ordinal+1);
      const node = reference(ref,object,key(parent.key,'component',identity,ordinal),{type:'component',parentObjectId:object.id,componentIndex:index,componentSlotId:ref.slot_id || ref.instance_id || ref.ref_id || ref.key || null,afterBlockId},path);
      if (ordinal) node.flags.repeatedOccurrence = true;
      const owner = afterBlockId ? blockParents.get(afterBlockId) : parent;
      if (!owner) {node.flags.anchorMissing = true; warn('component_anchor_unavailable',node,{blockId:afterBlockId});}
      (owner || parent).children.push(node);
    });
    const pageCounts = new Map();
    for (const page of array(content.pages)) if (page?.id) pageCounts.set(string(page.id),(pageCounts.get(string(page.id)) || 0)+1);
    array(content.pages).forEach((page,pageIndex) => {
      if (!page?.id || pageCounts.get(string(page.id)) !== 1) {warn('page_identity_unavailable',parent,{pageIndex}); return;}
      const pageId = string(page.id);
      const pageNode = make({key:key(parent.key,'page',pageId),title:string(page.title || page.name || `页面 ${pageIndex+1}`),kind:'page',objectId:object.id,revision:object.revision,relation:'structure',anchor:{type:'page',pageId,pageIndex}});
      const itemCounts = new Map();
      for (const item of array(page.objects)) if (item?.id) itemCounts.set(string(item.id),(itemCounts.get(string(item.id)) || 0)+1);
      array(page.objects).forEach(item => {
        if (!item?.id || itemCounts.get(string(item.id)) !== 1) {warn('canvas_identity_unavailable',pageNode); return;}
        const itemId = string(item.id);
        const anchor = {type:'canvas',pageId,pageIndex,itemId,parentObjectId:object.id};
        const node = item.component_id ? reference(item,object,key(pageNode.key,'canvas',itemId),{...anchor,type:'component'},path)
          : make({key:key(pageNode.key,'canvas',itemId),title:string(item.title || item.label || (item.type === 'text' ? item.text : '') || names[item.type] || '画布对象'),kind:item.type || 'canvas',objectId:object.id,revision:object.revision,relation:'structure',anchor:{...anchor,assetSha:assetSha(item.asset) || null}});
        pageNode.children.push(node);
      });
      parent.children.push(pageNode);
    });
    appendArtists(parent,object);
  }

  const roots = [];
  if (active) {
    const node = make({key:key('current',active.id),title:titleOf(active),kind:active.kind,objectId:active.id,revision:active.revision,relation:'current',anchor:{type:'object'}});
    appendObject(node,active,new Set([string(active.id)])); roots.push(node);
  }
  const support = {notes:[],data:[],code:[],literature:[],outputs:[]}, assets = new Map();
  const visibleObjects = [...catalog.values()].filter(o => !o.archived && (!project || string(o.project_id) === project) && (noteKinds.has(o.kind) || objectKinds.has(o.kind) || ['literature','data','code'].includes(o.kind)));
  function nameAsset(node) {
    const owners = node.anchor.ownerObjectIds.map(id => titleOf(catalog.get(string(id))));
    const label = node.assetFilename || node.assetLabel;
    // Keep the actual owner visible before a generic role such as caption or
    // plotting code. The tooltip/accessibility label retains full titles.
    node.title = owners.join(' / ') + ' · ' + label;
    node.displayTitle = owners.map(name => name.split(' · ')[0]).join(' / ') + ' · ' + label;
  }
  function addAsset(owner, value, role, fallbackName) {
    const sha = assetSha(value); if (!sha) return;
    const identity = key(role,sha), existing = assets.get(identity);
    const name = typeof value === 'object' ? value.name || value.filename || value.path : null;
    const filename = typeof name === 'string' ? name.replace(/\\/g,'/').split('/').at(-1) : '';
    if (existing) {
      if (!existing.anchor.ownerObjectIds.includes(owner.id)) existing.anchor.ownerObjectIds.push(owner.id);
      if (!existing.assetFilename && filename) existing.assetFilename = filename;
      existing.flags.shared = existing.anchor.ownerObjectIds.length > 1; nameAsset(existing); return;
    }
    const node = make({key:key('support',project,'asset',role,sha),assetFilename:filename,assetLabel:string(fallbackName || (role === 'code' ? '绘图代码' : '来源数据')),kind:role,objectId:owner.id,revision:owner.revision,relation:'asset',anchor:{type:'asset',assetSha:sha,ownerObjectId:owner.id,ownerObjectIds:[owner.id],role},flags:{}});
    nameAsset(node);
    assets.set(identity,node); support[role].push(node);
  }
  for (const object of visibleObjects) {
    if (object.id !== active?.id) {
      const category = noteKinds.has(object.kind) ? 'notes' : object.kind === 'literature' ? 'literature' : ['data','code'].includes(object.kind) ? object.kind : 'outputs';
      support[category].push(make({key:key('support',project,'object',object.id),title:titleOf(object),kind:object.kind,objectId:object.id,revision:object.revision,relation:'owned',anchor:{type:'object'}}));
    }
    const content = object.content || {};
    if (content.script_asset || content.script) addAsset(object,content.script_asset || content.script,'code','绘图代码');
    for (const field of ['input_assets','inputs','source_assets']) {
      const values = content[field];
      if (Array.isArray(values)) values.forEach((value,index) => addAsset(object,value,'data',`来源数据 ${index+1}`));
      else if (values && typeof values === 'object') {
        if (assetSha(values)) addAsset(object,values,'data','来源数据');
        else Object.entries(values).forEach(([name,value]) => addAsset(object,value,'data',name));
      }
    }
  }
  const categories = [['notes','笔记'],['data','数据'],['code','代码'],['literature','文献'],['outputs','其他成果']].filter(([id]) => support[id].length).map(([id,title]) => group(key('support',project),id,title,support[id],true));
  if (categories.length) roots.push(group(project,'project-support','项目支撑',categories));
  return {roots,byKey,warnings,defaultCollapsedKeys:[...defaults]};
}

function normalizeState(tree, state = {}) {
  const valid = keys => [...new Set(array(keys).filter(id => tree.byKey.has(id)))];
  return {query:string(state.query),collapsedKeys:valid(Array.isArray(state.collapsedKeys) ? state.collapsedKeys : tree.defaultCollapsedKeys),selectedKeys:valid(state.selectedKeys),focusKey:tree.byKey.has(state.focusKey) ? state.focusKey : null,rangeAnchorKey:tree.byKey.has(state.rangeAnchorKey) ? state.rangeAnchorKey : null};
}

function treeView(tree, state) {
  const query = fold(state.query).trim(), terms = query.split(/\s+/u).filter(Boolean), collapsed = new Set(state.collapsedKeys), keep = new Set(), parents = new Map(), visible = [];
  // A short display term such as "3" must not accidentally match a UUID/SHA.
  // Full identities remain searchable at any length; partial identity searches
  // must be a single ID-shaped token with at least eight characters.
  const partialIdentityQuery = /^[a-z0-9][a-z0-9_:./-]{7,}$/u.test(query);
  function match(node, parent = null) {
    if (parent) parents.set(node.key,parent.key);
    let descendant = false;
    for (const child of node.children) descendant = match(child,node) || descendant;
    const haystack = fold([node.title,names[node.kind],node.anchor.artistId].filter(Boolean).join(' '));
    // objectId on an Artist/asset/block is its owner, not the node's identity.
    // Matching a source must not also match every detail belonging to it.
    const ownIdentity = ['object','component'].includes(node.anchor.type) ? node.objectId
      : node.anchor.type === 'block' ? node.anchor.blockId
      : node.anchor.type === 'artist' ? node.anchor.artistId
      : node.anchor.type === 'asset' ? node.anchor.assetSha : null;
    const identity = fold(ownIdentity);
    const identityMatch = !!query && !!identity && (identity === query || (partialIdentityQuery && identity.includes(query)));
    if (!terms.length || terms.every(term => haystack.includes(term)) || identityMatch || descendant) {keep.add(node.key); return true;}
    return false;
  }
  tree.roots.forEach(root => match(root));
  function visit(node, level) {
    if (!keep.has(node.key)) return;
    // Search opens retained paths only; a matching parent does not retain its
    // entire subtree unless those children independently match the query.
    const children = node.children.filter(child => keep.has(child.key));
    const expanded = children.length > 0 && (terms.length > 0 || !collapsed.has(node.key));
    visible.push({node,level,children,expanded});
    if (expanded) children.forEach(child => visit(child,level+1));
  }
  tree.roots.forEach(root => visit(root,1));
  return {visible,keep,parents,searching:terms.length > 0};
}

function status(node) {
  const flags = node.flags;
  if (flags.missing) return '来源缺失';
  if (flags.sourceMismatch) return '来源不匹配';
  if (flags.revisionUnavailable) return node.revision == null ? '采用版本未记录' : `采用 r${node.revision}`;
  if (flags.anchorMissing) return '图位待定位';
  if (flags.cycle) return '循环引用';
  if (flags.staleRender) return '旧预览';
  if (flags.staticImage) return '整图';
  if (flags.shared) return '共享';
  if (node.relation === 'reference') return node.revision == null ? '引用' : `引用 r${node.revision}`;
  if (node.relation === 'current') return '当前成果';
  return '';
}

/** Render into a dedicated container; all labels, keys and attributes are escaped. */
export function renderOutliner(tree, state = {}) {
  const current = normalizeState(tree,state), view = treeView(tree,current), selected = new Set(current.selectedKeys);
  const focusKey = view.visible.some(row => row.node.key === current.focusKey) ? current.focusKey : view.visible.find(row => selected.has(row.node.key))?.node.key || view.visible[0]?.node.key;
  const rows = new Map(view.visible.map(row => [row.node.key,row]));
  function render(node) {
    const row = rows.get(node.key); if (!row) return '';
    const label = status(node), hasChildren = row.children.length > 0;
    return `<li class="outliner41-item" role="treeitem" data-outliner41-key="${escapeHTML(node.key)}" tabindex="${node.key === focusKey ? 0 : -1}" aria-label="${escapeHTML(node.title)}" aria-level="${row.level}" aria-selected="${selected.has(node.key)}"${hasChildren ? ` aria-expanded="${row.expanded}"` : ''}><div class="outliner41-row${selected.has(node.key) ? ' outliner41-selected' : ''}" title="${escapeHTML(node.title)}"><button type="button" class="outliner41-toggle${hasChildren ? '' : ' outliner41-leaf'}" data-outliner41-action="toggle" tabindex="-1" aria-label="${row.expanded ? '收起' : '展开'}${escapeHTML(node.title)}"${hasChildren ? '' : ' disabled aria-hidden="true"'}>${row.expanded ? '▾' : '▸'}</button><span class="outliner41-icon" aria-hidden="true">${icons[node.kind] || '·'}</span><span class="outliner41-title">${escapeHTML(node.displayTitle || node.title)}</span>${label ? `<span class="outliner41-status">${escapeHTML(label)}</span>` : ''}</div>${row.expanded ? `<ul class="outliner41-children" role="group">${row.children.map(render).join('')}</ul>` : ''}</li>`;
  }
  const detail = current.selectedKeys.map(id => tree.byKey.get(id)).filter(Boolean);
  return `<section class="outliner41" aria-label="素材目录"><div class="outliner41-search"><input class="outliner41-query" type="search" data-outliner41-action="search" value="${escapeHTML(current.query)}" placeholder="查找对象" aria-label="搜索素材目录" autocomplete="off" spellcheck="false"><button class="outliner41-clear" type="button" data-outliner41-action="clear" aria-label="清除搜索"${current.query ? '' : ' hidden'}>×</button></div><ul class="outliner41-tree" role="tree" aria-label="研究对象" aria-multiselectable="true">${tree.roots.map(render).join('')}</ul>${view.visible.length ? '' : `<p class="outliner41-empty" role="status">${current.query ? '没有匹配对象。清除搜索可返回原展开位置。' : '暂无可显示的研究对象。'}</p>`}<div class="outliner41-detail" aria-live="polite">${detail.length > 1 ? `已选择 ${detail.length} 个对象` : detail[0] ? escapeHTML(detail[0].title) : '选择对象以定位与查看属性'}</div></section>`;
}

/**
 * Bind only this mount. Callbacks receive actual nodes; callers decide whether
 * selection means locate, load a revision, open source or update properties.
 * setSelection does not emit onSelect, so canvas synchronization cannot loop.
 */
export function bindOutliner(mount, {tree, state = {}, onSelect = () => {}, onOpen = () => {}, onStateChange = () => {}} = {}) {
  if (!mount || !tree?.byKey) throw new TypeError('bindOutliner requires a dedicated mount and object tree');
  let currentTree = tree, current = normalizeState(tree,state), destroyed = false;
  const snapshot = () => ({...current,collapsedKeys:[...current.collapsedKeys],selectedKeys:[...current.selectedKeys]});
  const elements = () => [...mount.querySelectorAll('[data-outliner41-key]')];
  const elementFor = id => elements().find(element => element.dataset.outliner41Key === id);
  const emit = () => onStateChange(snapshot());
  function paint(focus = null) {
    if (destroyed) return;
    const active = mount.ownerDocument?.activeElement, searchActive = active?.dataset?.outliner41Action === 'search' && mount.contains(active);
    const caret = searchActive ? [active.selectionStart,active.selectionEnd] : null;
    const scrollTop = mount.querySelector('.outliner41-tree')?.scrollTop || 0;
    mount.innerHTML = renderOutliner(currentTree,current);
    const scrollContainer = mount.querySelector('.outliner41-tree');
    if (scrollContainer) scrollContainer.scrollTop = scrollTop;
    if (focus === 'search' || searchActive) {
      const input = mount.querySelector('[data-outliner41-action="search"]'); input?.focus();
      if (caret && typeof input?.setSelectionRange === 'function') {try {input.setSelectionRange(...caret);} catch (_error) { /* Search inputs may not expose a selection range. */ }}
    } else if (focus) elementFor(focus)?.focus();
  }
  function paintSelection(focus) {
    // Keep the clicked node alive for the browser's native double-click event.
    // Selection changes must not rebuild the tree or reset its scroll position.
    const selected = new Set(current.selectedKeys);
    for (const element of elements()) {
      const id = element.dataset.outliner41Key;
      element.setAttribute('aria-selected',String(selected.has(id)));
      element.setAttribute('tabindex',id === current.focusKey ? '0' : '-1');
      element.querySelector('.outliner41-row')?.classList.toggle('outliner41-selected',selected.has(id));
    }
    const detail = mount.querySelector('.outliner41-detail');
    if (detail) detail.textContent = selected.size > 1 ? `已选择 ${selected.size} 个对象` : selected.size ? currentTree.byKey.get(current.selectedKeys[0]).title : '选择对象以定位与查看属性';
    if (focus) elementFor(focus)?.focus();
  }
  function select(id, event = {}, source = 'pointer') {
    const node = currentTree.byKey.get(id); if (!node) return;
    const additive = !!(event.ctrlKey || event.metaKey), range = !!event.shiftKey;
    const view = treeView(currentTree,current), visible = view.visible.map(row => row.node.key);
    let keys;
    if (range && visible.includes(current.rangeAnchorKey) && visible.includes(id)) {
      const a = visible.indexOf(current.rangeAnchorKey), b = visible.indexOf(id), span = visible.slice(Math.min(a,b),Math.max(a,b)+1);
      keys = additive ? [...new Set([...current.selectedKeys,...span])] : span;
    } else if (additive) keys = current.selectedKeys.includes(id) ? current.selectedKeys.filter(value => value !== id) : [...current.selectedKeys,id];
    else keys = [id];
    current = {...current,selectedKeys:keys,focusKey:id,rangeAnchorKey:range ? current.rangeAnchorKey || id : id};
    paintSelection(id); emit(); onSelect(node,{nodes:keys.map(value => currentTree.byKey.get(value)),keys:[...keys],source,additive,range});
  }
  function toggle(id, expanded = null) {
    const node = currentTree.byKey.get(id); if (!node?.children.length) return;
    // A filtered path stays visible, and does not overwrite the user's saved folding.
    if (fold(current.query).trim()) return;
    const collapsed = new Set(current.collapsedKeys), isExpanded = !collapsed.has(id), nextExpanded = expanded ?? !isExpanded;
    if (nextExpanded) collapsed.delete(id); else collapsed.add(id);
    current = {...current,collapsedKeys:[...collapsed],focusKey:id}; paint(id); emit();
  }
  function targetOf(event) {
    const target = event.target?.closest?.('[data-outliner41-key]');
    return target && mount.contains(target) ? target.dataset.outliner41Key : null;
  }
  function actionOf(event) {
    const target = event.target?.closest?.('[data-outliner41-action]');
    return target && mount.contains(target) ? target.dataset.outliner41Action : null;
  }
  function open(id, source) {
    const node = currentTree.byKey.get(id); if (!node) return;
    if (node.anchor.type === 'group') toggle(id);
    else onOpen(node,{source});
  }
  function click(event) {
    const action = actionOf(event), id = targetOf(event);
    if (action === 'clear') {event.preventDefault(); event.stopPropagation(); current = {...current,query:''}; paint('search'); emit();}
    else if (action === 'toggle' && id) {event.preventDefault(); event.stopPropagation(); toggle(id);}
    else if (id) {event.preventDefault(); event.stopPropagation(); select(id,event);}
  }
  function doubleClick(event) {
    const id = targetOf(event); if (!id || actionOf(event) === 'toggle') return;
    event.preventDefault(); event.stopPropagation(); open(id,'pointer');
  }
  function input(event) {
    if (actionOf(event) !== 'search') return;
    event.stopPropagation(); current = {...current,query:string(event.target.value)}; paint('search'); emit();
  }
  function keyboard(event) {
    if (actionOf(event) === 'search') {
      if (event.key === 'Escape') {event.preventDefault(); event.stopPropagation(); current = {...current,query:''}; paint('search'); emit();}
      else if (event.key === 'ArrowDown') {const first = treeView(currentTree,current).visible[0]; if (first) {event.preventDefault(); event.stopPropagation(); select(first.node.key,{},'keyboard');}}
      return;
    }
    const id = targetOf(event); if (!id) return;
    const view = treeView(currentTree,current), index = view.visible.findIndex(row => row.node.key === id), row = view.visible[index];
    if (!row) return;
    if (!['ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Home','End','Enter',' '].includes(event.key)) return;
    event.preventDefault(); event.stopPropagation();
    if (event.key === 'Enter') {open(id,'keyboard'); return;}
    if (event.key === ' ') {select(id,event,'keyboard'); return;}
    if (event.key === 'ArrowLeft') {
      if (row.expanded && !view.searching) toggle(id,false);
      else if (view.parents.has(id)) select(view.parents.get(id),event,'keyboard');
      return;
    }
    if (event.key === 'ArrowRight') {
      if (row.children.length && !row.expanded) toggle(id,true);
      else if (row.expanded) select(row.children[0].key,event,'keyboard');
      return;
    }
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? view.visible.length-1 : Math.max(0,Math.min(view.visible.length-1,index+(event.key === 'ArrowUp' ? -1 : 1)));
    select(view.visible[next].node.key,event,'keyboard');
  }
  const listeners = {click,dblclick:doubleClick,input,keydown:keyboard};
  for (const [type,handler] of Object.entries(listeners)) mount.addEventListener(type,handler);
  paint();
  return {
    update({tree:nextTree = currentTree,state:nextState = current} = {}) {
      if (destroyed) return;
      const oldTree = currentTree;
      currentTree = nextTree;
      if (nextState === current && nextTree !== oldTree) nextState = {...current,collapsedKeys:[...current.collapsedKeys,...array(nextTree.defaultCollapsedKeys).filter(id => !oldTree.byKey.has(id))]};
      current = normalizeState(currentTree,nextState); paint();
    },
    setSelection(keys, {reveal = true} = {}) {
      if (destroyed) return;
      const selectedKeys = [...new Set(array(keys).filter(id => currentTree.byKey.has(id)))];
      const collapsed = new Set(current.collapsedKeys), view = treeView(currentTree,current);
      if (reveal) for (const id of selectedKeys) {let parent = view.parents.get(id); while (parent) {collapsed.delete(parent); parent = view.parents.get(parent);}}
      current = {...current,selectedKeys,focusKey:selectedKeys[0] || null,rangeAnchorKey:selectedKeys[0] || null,collapsedKeys:[...collapsed],query:reveal && selectedKeys.some(id => !view.keep.has(id)) ? '' : current.query};
      paint();
      if (reveal && selectedKeys[0]) elementFor(selectedKeys[0])?.scrollIntoView?.({block:'nearest',inline:'nearest'});
      emit();
    },
    getState:snapshot,
    destroy() {if (destroyed) return; destroyed = true; for (const [type,handler] of Object.entries(listeners)) mount.removeEventListener(type,handler);}
  };
}
