"""Unsaved visual previews using the registered, explicitly authorized renderer.

This is not a Python sandbox. An approved plot is rerun in the existing bounded
worker. No model/runner is involved, and no source code, input or spec replacement
is accepted here. Assets are staged until a final locked identity/ACL check; the
object, revisions and official export registry remain unchanged.
"""
from __future__ import annotations

from research_partner.resources import module_file
import copy
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import threading

from research_partner.rendering.engine import ArtifactEngine
from research_partner.storage.store import Problem, digest, now, require


MAX_OVERLAY_BYTES = 512_000
MAX_PREVIEW_BYTES = 128_000_000
_CACHE = OrderedDict()
_CACHE_LOCK = threading.Lock()
VISUAL_PROPERTIES = frozenset({
    'text', 'fontsize', 'color', 'fontweight', 'rotation', 'position', 'visible',
    'linewidth', 'linestyle', 'marker', 'markersize', 'alpha', 'label',
    'facecolor', 'edgecolor', 'cmap', 'interpolation', 'fill', 'hatch',
    'loc', 'title', 'frameon', 'bbox_to_anchor', 'tick_fontsize', 'figsize',
    'subplot_left', 'subplot_right', 'subplot_bottom', 'subplot_top',
    'subplot_wspace', 'subplot_hspace',
})


def _overlays(value):
    if isinstance(value, dict):
        value = [{'target': key, 'properties': properties} for key, properties in value.items()]
    require(isinstance(value, list) and len(value) <= 512, '视觉覆盖需要有界列表', 'invalid_preview', 422)
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError):
        raise Problem('视觉覆盖须为有限JSON值', 'invalid_preview', 422)
    require(len(raw) <= MAX_OVERLAY_BYTES, '视觉覆盖超出本次预览大小限制', 'preview_limit', 413)
    for layer in value:
        require(isinstance(layer, dict) and set(layer) <= {'target', 'properties'}, '预览只接受明确target/properties覆盖', 'invalid_preview', 422)
        require(isinstance(layer.get('target'), str) and 0 < len(layer['target']) <= 512, '视觉覆盖目标不合法', 'invalid_preview', 422)
        props = layer.get('properties')
        require(isinstance(props, dict) and len(props) <= 32 and set(props) <= VISUAL_PROPERTIES,
                '不支持数据、归一化或色阶范围修改；仅接受已声明视觉属性', 'unsupported_property', 422)
    return copy.deepcopy(value)


class _StagedAssets:
    """Delegate all reads; hold renderer-produced bytes out of the real store."""
    def __init__(self, store):
        self.store = store
        self.pending = []
        self.size = 0

    def __getattr__(self, name):
        return getattr(self.store, name)

    def asset(self, sha, connection=None):
        # Child declarative renders are consumed by the parent before the
        # final transaction. Read their staged bytes without publishing them.
        for data, item in reversed(self.pending):
            if item['sha'] == sha:
                require(hashlib.sha256(data).hexdigest() == sha, '暂存资产校验失败', 'integrity', 409)
                return copy.deepcopy(item)
        return self.store.asset(sha, connection=connection)

    def staged_asset_bytes(self, sha):
        for data, item in reversed(self.pending):
            if item['sha'] == sha:
                require(hashlib.sha256(data).hexdigest() == sha, '暂存资产校验失败', 'integrity', 409)
                return data
        self.store.asset(sha)
        return (self.store.blobs / sha).read_bytes()

    def add_asset(self, data, filename, media_type='application/octet-stream', metadata=None):
        self.size += len(data)
        require(self.size <= MAX_PREVIEW_BYTES, '预览输出超出本次大小限制', 'preview_limit', 413)
        sha = hashlib.sha256(data).hexdigest()
        meta = copy.deepcopy(metadata or {})
        meta['preview_only'] = True
        meta['projects'] = sorted(set(meta.get('projects', [])) | ({meta['project_id']} if meta.get('project_id') else set()))
        item = {'sha': sha, 'filename': Path(filename).name, 'media_type': media_type,
                'metadata': meta, 'size': len(data), 'created_at': now(), 'url': '/api/assets/' + sha}
        self.pending.append((data, item))
        return item


def _recheck(app, obj, source_sha, script, scope, engine, principal=None):
    if principal is not None:
        from research_partner.domains.workspace.management import authority_scope
        app.writable(obj['id'], authority_scope(app, principal))
    current = app.writable(obj['id'], scope)
    require(current['revision'] == obj['revision'] and digest(current) == source_sha,
            '渲染期间图已变化；旧预览不会覆盖新编辑', 'conflict', 409)
    if script:
        require(app.store.setting('code_grant:' + obj['id'], {}).get('script_sha') == script,
                '绘图脚本授权已撤回', 'authorization_required', 403)
    inputs = current['content'].get('input_assets', [])
    for asset in (inputs.values() if isinstance(inputs, dict) else inputs):
        engine._asset_bytes(asset, owner=current)
    if script: engine._asset_bytes(script, owner=current)


def _baseline(app, obj, source_sha, result):
    records = app.store.export_records(obj['id'], obj['revision'])
    known = [record['result'] for record in records
             if record['result'].get('provenance', {}).get('source_sha256') == source_sha
             and record['result']['provenance'].get('numeric_before')]
    if not known: return 'within_render_only_no_prior_official_numeric_baseline'
    baseline = known[-1]
    asset = baseline.get('assets', {}).get('numeric_values.json', {})
    if not isinstance(asset, dict) or not asset.get('sha'):
        return 'within_render_only_prior_numeric_schema_unverified'
    app.asset(asset['sha'], project_id=obj.get('project_id'))
    try:
        values = json.loads((app.store.blobs / asset['sha']).read_bytes())
    except (ValueError, UnicodeDecodeError):
        raise Problem('已登记数值基线不能解析', 'integrity', 409)
    if not (isinstance(values, list) and values and all(isinstance(item, dict) and item.get('schema_version') == 3 for item in values)):
        return 'within_render_only_prior_numeric_schema_unverified'
    verified = hashlib.sha256(json.dumps(values, sort_keys=True, allow_nan=True, separators=(',', ':')).encode()).hexdigest()
    require(verified == baseline['provenance']['numeric_before'], '已登记数值基线字节与哈希不一致', 'integrity', 409)
    require(result['provenance']['numeric_before'] == verified,
            '重绘数值与当前保存版已有渲染基线不同；未将其作为视觉预览', 'numeric_baseline_changed', 409)
    return 'matched_current_official_render'


def dispatch(app, data, scope, principal=None):
    require(isinstance(data, dict) and set(data) <= {'action', 'id', 'expected_revision', 'overlays', 'request_key'},
            '预览不能替换绘图脚本、输入、数据spec或参数', 'invalid_preview', 422)
    require(data.get('action') == 'figure.preview', '预览动作不支持')
    require(isinstance(data.get('id'), str) and type(data.get('expected_revision')) is int and data['expected_revision'] > 0,
            '预览需要已保存图的准确版本', 'invalid_preview', 422)
    key = data.get('request_key')
    require(key is None or isinstance(key, str) and 0 < len(key) <= 200, '预览请求标识过长或无效', 'invalid_preview', 422)
    obj = app.writable(data['id'], scope)
    if principal is not None:
        from research_partner.domains.workspace.management import authority_scope
        app.writable(obj['id'], authority_scope(app, principal))
    require(obj['revision'] == data['expected_revision'], '图已变化，草稿保留；请先核对保存版本', 'conflict', 409)
    require(obj['kind'] == 'figure' and not obj['content'].get('composition') and not obj.get('archived'), '需要未归档的科研图', 'invalid_preview', 422)
    require(obj['content'].get('editable_source_available') is not False, '静态图没有可编辑绘图来源', 'missing_source', 422)
    layers = _overlays(data.get('overlays', obj['content'].get('overlays', [])))
    source_sha = digest(obj)
    script = obj['content'].get('script_asset') or obj['content'].get('script')
    grant = app.store.setting('code_grant:' + obj['id'], {})
    authorized = bool(script and grant.get('script_sha') == obj['content'].get('script_asset'))
    require(not script or authorized, '预览执行已登记脚本仍需明确授权', 'authorization_required', 403)
    staged = _StagedAssets(app.store)
    engine = ArtifactEngine(staged, app.config.get('rendering', {}))
    code_identity = digest([module_file(name).read_bytes().hex()
                            for name in ('research_partner.rendering.worker', 'research_partner.rendering.interaction')])
    cache_key = (str(app.store.db), source_sha, digest(layers), code_identity, str(engine.config['scientific_python']))
    with _CACHE_LOCK:
        cached = copy.deepcopy(_CACHE.get(cache_key))
    if cached is not None:
        # Cache hits never bypass current access, asset integrity or grant checks.
        with app.store.transaction():
            _recheck(app, obj, source_sha, script, scope, engine, principal)
            for item in cached['assets'].values(): engine._asset_bytes(item['sha'], project_id=obj.get('project_id'))
            cached['preview_identity']['numeric_baseline'] = _baseline(app, obj, source_sha, cached)
        cached['preview_identity'].update(request_key=key, cache_hit=True)
        return cached
    result = engine.render_figure(obj, overlays=layers, authorized_code=authorized, preview=True)
    require(result.get('provenance', {}).get('numeric_preserved') is True,
            '视觉预览未通过数值身份校验', 'integrity', 409)
    require(not result.get('replay', {}).get('failures'), '部分视觉覆盖无法重放；未登记本次预览，草稿与旧图保留',
            'preview_replay_failed', 422, {'replay': result.get('replay', {})})
    # Short write lock spans revalidation and registration, never the renderer.
    with app.store.transaction() as connection:
        _recheck(app, obj, source_sha, script, scope, engine, principal)
        baseline_status = _baseline(app, obj, source_sha, result)
        registered = {}
        for payload, item in staged.pending:
            registered[item['sha']] = app.store.add_asset(payload, item['filename'], item['media_type'], item['metadata'], connection=connection)
    result['assets'] = {name: registered[item['sha']] for name, item in result['assets'].items()}
    result['asset'] = registered[result['asset']['sha']]
    result['status'] = 'preview'
    result['preview_identity'] = {
        'object_id': obj['id'], 'base_revision': obj['revision'], 'base_source_sha256': source_sha,
        'overlays_sha256': digest(layers), 'candidate_source_sha256': result['provenance']['source_sha256'],
        'request_key': key, 'saved': False, 'official_export_recorded': False,
        'numeric_baseline': baseline_status, 'cache_hit': False,
        'numeric_schema_version': 3,
    }
    with _CACHE_LOCK:
        _CACHE[cache_key] = copy.deepcopy(result)
        _CACHE.move_to_end(cache_key)
        while len(_CACHE) > 16: _CACHE.popitem(last=False)
    return result
