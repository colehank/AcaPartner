"""Typed visual targets in the existing manuscript round, version 3.

Only explicitly selected, already rendered leaf Artists are writable here.
File-authoritative main definitions retain their own journal and are refused,
not silently projected through Store.save. No model output executes or adopts.
"""
from __future__ import annotations

import copy
import json
import re

from research_partner.storage.store import Problem, digest, encoded, now, require
from research_partner.domains.figures.preview import _overlays

FEATURE = 'reviewed_figure_round_v3'


def is_visual(target):
    return target.get('kind') == 'figure'


def writable(app, ident, project, scope, c):
    from research_partner.domains.figures.commit import _writable
    obj = _writable(app, ident, scope, None, c)
    require(obj['project_id'] == project and obj['kind'] == 'figure',
            '图意见只修改同项目明确选中的图', 'forbidden', 403)
    require(not obj['content'].get('composition') and not obj['content'].get('definition_schema')
            and obj['content'].get('editable_source_available') is not False,
            '该图需走原主图定义或静态图路径，不能作为独立Artist视觉目标', 'unsupported_visual_target', 422)
    return obj


def manifest_for(app, obj, c):
    rows = c.execute('SELECT value FROM kv WHERE key LIKE ? ORDER BY key', ('exports:' + obj['id'] + ':%',)).fetchall()
    records = sorted([r for row in rows for r in json.loads(row[0]) if r['revision'] == obj['revision']], key=lambda r: r['created_at'])
    results = [r['result'] for r in records if r['result'].get('status') == 'generated'
               and 'preview_identity' not in r['result']
               and not r['result'].get('replay', {}).get('failures')
               and r['result'].get('provenance', {}).get('source_sha256') == digest(obj)]
    require(results, '图意见需当前保存版的真实渲染及元素映射；不会自动执行', 'figure_render_required', 409)
    result = results[-1]
    manifest = result.get('manifest')
    require(isinstance(manifest, list) and all(isinstance(m, dict) and isinstance(m.get('id'), str) for m in manifest)
            and len({m['id'] for m in manifest}) == len(manifest), '登记元素映射不完整或重复', 'integrity', 409)
    # Verify the registered mapping against its actual artifact bytes, not just
    # a client supplied descriptor. Source and asset access remain current.
    from research_partner.rendering.engine import ArtifactEngine
    engine = ArtifactEngine(app.store, app.config.get('rendering', {}))
    for ref in engine._declared_references(obj):
        engine._reference(obj, ref)
    for _, sha in engine._asset_refs(result, strict=False):
        engine._asset_bytes(sha, owner=obj)
    manifest_asset = result.get('assets', {}).get('manifest.json', {})
    require(isinstance(manifest_asset, dict) and isinstance(manifest_asset.get('sha'), str),
            '登记元素缺少实际映射资产', 'integrity', 409)
    try:
        _, raw_manifest = engine._asset_bytes(manifest_asset['sha'], owner=obj)
        actual_manifest = json.loads(raw_manifest)
    except (ValueError, UnicodeDecodeError) as error:
        raise Problem('实际元素映射不能读取', 'integrity', 409) from error
    require(digest(actual_manifest) == digest(manifest), '登记元素映射与实际资产不符', 'integrity', 409)
    return manifest, result


def selected_overlays(obj, artist_ids):
    layers = _overlays(obj['content'].get('overlays', []))
    require(len({r['target'] for r in layers}) == len(layers), '已有视觉覆盖目标重复，需先明确整理', 'conflict', 409)
    return [r for r in layers if r['target'] in artist_ids]


def freeze(app, raw, main, scope, c):
    require(set(raw) <= {'object_id', 'expected_revision', 'kind', 'field', 'artist_ids', 'component_index'}
            and raw.get('kind') == 'figure' and raw.get('field') == 'visual_overlays'
            and isinstance(raw.get('object_id'), str) and type(raw.get('expected_revision')) is int,
            '图目标只接受准确保存版与所选Artist视觉覆盖')
    obj = writable(app, raw['object_id'], main['project_id'], scope, c)
    require(obj['revision'] == raw['expected_revision'], '图已改变，请重新读取', 'conflict', 409)
    ids = raw.get('artist_ids')
    require(isinstance(ids, list) and 0 < len(ids) <= 128 and all(isinstance(x, str) for x in ids)
            and len(set(ids)) == len(ids), '图意见需1–128个唯一已登记元素')
    manifest, render = manifest_for(app, obj, c)
    by_id = {m['id']: m for m in manifest}
    require(set(ids) <= set(by_id), '所选元素未登记在当前真实渲染中', 'invalid_visual_target', 422)
    target = {'object_id': obj['id'], 'kind': 'figure', 'field': 'visual_overlays', 'artist_ids': copy.deepcopy(ids)}
    binding = {'kind': 'figure_visual', 'source_sha256': digest(obj),
               'manifest': [copy.deepcopy(by_id[i]) for i in ids], 'render_sha256': digest(render)}
    if 'component_index' in raw:
        index = raw['component_index']
        refs = main['content'].get('components', [])
        require(type(index) is int and isinstance(refs, list) and 0 <= index < len(refs)
                and isinstance(refs[index], dict), '需准确的稿内图使用位置', 'invalid_occurrence', 422)
        ref = copy.deepcopy(refs[index])
        from research_partner.domains.figures.commit import _occurrence
        occurrence = {'id': main['id'], 'expected_revision': main['revision'], 'component_index': index,
                      'component_id': obj['id'], 'component_revision': ref.get('revision'), 'component_ref': ref}
        _occurrence(app, occurrence, obj, scope, None, c)
        target['component_index'] = index
        binding['component_ref'] = ref
    return {'target': target, 'base_revision': obj['revision'], 'base': copy.deepcopy(obj),
            'before': encoded(selected_overlays(obj, ids)), 'binding': binding, 'title': obj['title']}


def validate_after(frozen, value):
    if frozen['target'].get('field') == 'slot_layout':
        from research_partner.domains.manuscripts.main_round import validate_after as validate_layout
        return validate_layout(frozen, value)
    require(isinstance(value, str) and len(value) <= 30000, '视觉候选须为有界JSON覆盖文字', 'invalid_model_output', 422)
    try:
        def pairs(items):
            result = {}
            for key, item in items:
                if key in result: raise ValueError('duplicate JSON member')
                result[key] = item
            return result
        def invalid_constant(_): raise ValueError('nonfinite JSON number')
        layers = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
        require(isinstance(layers, list), '视觉候选须为覆盖列表', 'invalid_model_output', 422)
        layers = _overlays(layers)
    except (ValueError, TypeError) as error:
        raise Problem('视觉候选不是有限JSON覆盖', 'invalid_model_output', 422) from error
    target = frozen['target']; members = {m['id']: m for m in frozen['binding']['manifest']}
    require(len({x['target'] for x in layers}) == len(layers), '视觉候选不能重复写一个元素', 'invalid_model_output', 422)
    for layer in layers:
        require(layer['target'] in target['artist_ids'] and layer['target'] in members,
                '视觉候选不能修改未选元素', 'invalid_model_output', 422)
        require(set(layer['properties']) <= set(members[layer['target']].get('supported_properties', [])),
                '元素未声明支持所提视觉属性', 'invalid_model_output', 422)
    require(digest(layers) != digest(json.loads(frozen['before'])), '视觉覆盖没有实际变化', 'invalid_model_output', 422)
    return layers


def annotation_indices(annotation, targets):
    anchor = annotation['anchor']
    artist = anchor.get('artist_id')
    if not isinstance(artist, str): return []
    return [i for i, frozen in enumerate(targets)
            if is_visual(frozen['target']) and frozen['target']['object_id'] == annotation['object_id']
            and artist in frozen['target']['artist_ids']]


def check_annotation(annotation, targets, indices):
    matches = annotation_indices(annotation, targets)
    require(matches and set(indices) == set(matches), '图批注必须准确绑定其所选元素目标', 'conflict', 409)
    identity = annotation['anchor'].get('render_source', {})
    for i in matches:
        frozen = targets[i]
        require(identity.get('object_id') == frozen['target']['object_id']
                and identity.get('revision') == frozen['base_revision']
                and identity.get('source_sha256') == frozen['binding']['source_sha256'],
                '图批注来自另一保存版，需先明确重新定位', 'conflict', 409)


def current(frozen, objects, main):
    if frozen['target'].get('field') == 'slot_layout':
        from research_partner.domains.manuscripts.main_round import current as current_layout
        return current_layout(frozen, objects, main)
    obj = objects[frozen['target']['object_id']]
    require(digest(obj) == frozen['binding']['source_sha256'],
            '图来源或已保存视觉已有新修改；保留当前图', 'conflict', 409)
    if 'component_index' in frozen['target']:
        index = frozen['target']['component_index']; refs = main['content'].get('components', [])
        require(isinstance(refs, list) and index < len(refs) and refs[index] == frozen['binding']['component_ref'],
                '稿内所选图使用已变化；不会替换其它使用', 'conflict', 409)
    return encoded(selected_overlays(obj, frozen['target']['artist_ids']))


def apply_content(content, frozen, after):
    if frozen['target'].get('field') == 'slot_layout':
        from research_partner.domains.manuscripts.main_round import apply_content as apply_layout
        return apply_layout(content, frozen, after)
    layers = validate_after(frozen, after)
    chosen = set(frozen['target']['artist_ids'])
    # Unselected original layers retain their exact values and order. The
    # explicit selected replacement may also remove an old selected override.
    content['overlays'] = [copy.deepcopy(x) for x in _overlays(content.get('overlays', [])) if x['target'] not in chosen] + layers


def freeze_groups(raw, targets):
    require(isinstance(raw, list) and len(raw) <= 48, '依赖组需有界列表')
    result, names, used = [], set(), set()
    for group in raw:
        require(isinstance(group, dict) and set(group) == {'id', 'target_indices'}, '依赖组只接受标识与明确目标')
        ident, indices = group['id'], group['target_indices']
        require(isinstance(ident, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,180}', ident) and ident not in names,
                '依赖组标识无效或重复')
        require(isinstance(indices, list) and 2 <= len(indices) <= len(targets)
                and all(type(i) is int and 0 <= i < len(targets) for i in indices)
                and len(set(indices)) == len(indices) and not used.intersection(indices),
                '依赖组需2个以上唯一目标；重叠组应先合并')
        names.add(ident); used.update(indices); result.append(copy.deepcopy(group))
    return result


def group_decisions(contract, record, decisions):
    by_target = {encoded(t['target']): i for i, t in enumerate(contract['targets'])}
    chosen = {d['change_id']: d['decision'] for d in decisions}
    for group in contract.get('dependency_groups', []):
        ids = {r['id'] for r in record['changes'] if by_target[encoded(r['target'])] in group['target_indices']}
        if not ids.intersection(chosen):
            continue
        require(ids <= set(chosen) and len({chosen[i] for i in ids}) == 1,
                '关联图文依赖组必须一起接受或一起拒绝；本次未部分写入', 'atomic_group_required', 409,
                {'group_id': group['id'], 'change_ids': sorted(ids)})


def protect_dirty(app, task, accepted, c):
    row = c.execute('SELECT value FROM kv WHERE key=?', ('desk_w1a:drafts:' + task['project_id'],)).fetchone()
    value = json.loads(row[0]).get('value', {}) if row else {}
    for change in accepted:
        if is_visual(change['target']):
            ident = change['target']['object_id']
            require(ident not in value.get('figure_drafts', {}) and ident not in value.get('composition_drafts', {}),
                    '该图存在未保存手改，旧候选不会覆盖', 'unsaved_figure', 409)


def schema(task):
    # V2's exact prompt and immutable records remain unchanged. Only the new
    # explicitly submitted version can carry these typed visual targets.
    from research_partner.domains.manuscripts import revision as mr
    legacy = copy.deepcopy(task)
    legacy['payload']['context'][mr.KIND]['version'] = 2
    return mr.round_schema(legacy) + '''
VERSION 3 VISUAL EXTENSION: A target with kind:"figure", field:"visual_overlays"
is an explicit selection of existing registered artist_ids, not manuscript
text. Its before and after fields remain JSON STRINGS encoding overlay lists
[{"target":"selected exact Artist id","properties":{"supported visual property":value}}].
Copy before exactly. after replaces ONLY the selected Artists' saved overrides;
unselected Artists retain original overlays. Use only the supplied manifest's
supported_properties and the visual whitelist. No data, numeric coordinates of
data points, script, input, source, normalization, scientific settings, or new
Artist may be changed. A component_index binds one exact manuscript occurrence;
only explicit acceptance may advance that occurrence to the actual rendered
figure revision. dependency_groups are frozen operator requirements, not model
instructions to perform writes. Each changed member of a group is accepted or
rejected together. Rendering is NOT performed by the model; verification must
state this honestly. All text and workshop-note constraints still apply. A
candidate is not adoption, scientific quality approval or completed rendering.
In VERSION 3 a single change may additionally have opinion_ids:["id", ...],
including its primary opinion_id, to address several frozen opinions together.
Every listed opinion must authorize this exact target. All their individual
responses must list the same change id; none may be omitted or claimed resolved.
Omitting opinion_ids keeps the original one-opinion shape. Each target still
changes at most once. Deleted or changed linked opinions block acceptance.
For field:"slot_layout", before and after are JSON STRINGS encoding the full
selected slot_ids in their original order: [{"id":"selected slot","box":[x,y,w,h]}].
Coordinates are normalized layout values, not data. Preserve every selected ID;
only finite boxes inside [0,1] may change. Do not change labels, panel references,
scripts, dimensions, numeric assets or unselected slots. No renderer runs in the
model; explicit adoption publishes the actual file, manuscript occurrence and
review decision together. This is distinct from leaf Artist visual_overlays.
An explicit frozen slot_adoptions edge is a user instruction to advance that
selected main slot to the same-round leaf result only upon a common acceptance.
The model must not provide a revision, source or asset. If proposing this main
change, also propose its authorized leaf change; if unable, explain why and
omit the main change. For an explicit edge only, unchanged main box JSON is
valid when no layout change is needed. All unselected pins remain fixed.
'''


def adopt_occurrences(contract, accepted, frozen, objects, contents, staged):
    main = objects[contract['object_id']]
    for row in accepted:
        target = row['target']
        if not is_visual(target) or 'component_index' not in target:
            continue
        original = frozen[encoded(target)]['binding']['component_ref']
        current_ref = main['content']['components'][target['component_index']]
        require(current_ref == original, '稿内图使用已变化；不部分采用', 'conflict', 409)
        content = contents.setdefault(main['id'], copy.deepcopy(main['content']))
        ref = content['components'][target['component_index']]
        candidate = staged[target['object_id']]['candidate']
        # A caption accepted in this same batch stays intact; only this
        # explicitly bound occurrence gets the newly rendered revision/SHA.
        ref['revision'] = candidate['revision']
        if 'sha256' in ref:
            ref['sha256'] = digest(candidate)


def register_renders(app, written, staged, c):
    for ident, stage in staged.items():
        require(digest(written[ident]) == digest(stage['candidate']),
                '保存图与本次真实渲染候选不同；整组回滚', 'integrity', 409)
        registered = {}
        for payload, asset in stage['assets'].pending:
            registered[asset['sha']] = app.store.add_asset(payload, asset['filename'], asset['media_type'], asset['metadata'], connection=c)
        result = copy.deepcopy(stage['result'])
        result['assets'] = {name: registered[asset['sha']] for name, asset in result['assets'].items()}
        result['asset'] = registered[result['asset']['sha']]
        app.store.record_export(ident, written[ident]['revision'], result, connection=c)


def decide(app, data, scope, principal, *, precommit=None):
    """Run authorized renderers outside the writer lock, then recheck all CAS.

    All source writes, output registrations and operator receipts share the
    existing round transaction. A failed/stale stage cannot partly apply prose.
    """
    from research_partner.domains.manuscripts import revision as mr
    from research_partner.rendering.engine import ArtifactEngine
    from research_partner.domains.figures.commit import _CandidateAssets, _retain_failure
    from research_partner.domains.figures.preview import _recheck, _baseline

    task_probe = app.store.task(data.get('task_id'))
    if any(t['target'].get('field') == 'slot_layout' for t in task_probe['payload']['context'][mr.KIND]['targets']):
        from research_partner.domains.manuscripts.main_round import decide as decide_main
        return decide_main(app, data, scope, principal, precommit=precommit)

    with app.store.read_snapshot() as reader:
        if precommit: precommit(reader)
        task, contract, record, state = mr.proposal(app, data, scope, reader)
        require(record and contract['version'] == 3, '图文候选尚未就绪', 'conflict', 409)
        prepared = mr.decide_round(app, data, principal, scope, reader, task, contract, record, state, prepare_only=True)
    if not prepared.get('prepared'):
        return prepared  # Idempotent actual committed receipt; no re-render.
    staged = {}
    phase = 'render'
    try:
        for row in prepared['accepted']:
            if not is_visual(row['target']):
                continue
            ident = row['target']['object_id']; source = prepared['objects'][ident]
            candidate = {**copy.deepcopy(source), 'revision': source['revision'] + 1, 'updated_at': now(),
                         'content': copy.deepcopy(prepared['contents'][ident])}
            script = source['content'].get('script_asset') or source['content'].get('script')
            grant = app.store.setting('code_grant:' + ident, {})
            authorized = bool(script and grant.get('script_sha') == source['content'].get('script_asset'))
            require(not script or authorized, '本图的真实重绘仍需原明确代码授权', 'authorization_required', 403)
            assets = _CandidateAssets(app.store, candidate)
            engine = ArtifactEngine(assets, app.config.get('rendering', {}))
            stage = {'source': source, 'candidate': candidate, 'assets': assets, 'script': script, 'engine': engine}
            staged[ident] = stage
            result = engine.render_figure(candidate, authorized_code=authorized)
            require(result.get('provenance', {}).get('source_sha256') == digest(candidate)
                    and result['provenance'].get('numeric_preserved') is True,
                    '图文采用未通过真实渲染来源与数值保护', 'integrity', 409)
            require(not result.get('replay', {}).get('failures'), '视觉覆盖不能全部重放；整组未采用', 'preview_replay_failed', 422)
            stage['result'] = result
        phase = 'recheck'
        with app.store.transaction() as c:
            if precommit: precommit(c)
            current_task, current_contract, current_record, current_state = mr.proposal(app, data, scope, c)
            current_prepared = mr.decide_round(app, data, principal, scope, c, current_task, current_contract,
                                             current_record, current_state, prepare_only=True)
            if not current_prepared.get('prepared'):
                return current_prepared
            require(digest(current_prepared) == digest(prepared),
                    '重绘期间图文、意见或目标已有新修改；整组未采用', 'conflict', 409)
            for stage in staged.values():
                source = stage['source']
                _recheck(app, source, digest(source), stage['script'], scope, stage['engine'], principal)
                _baseline(app, source, digest(source), stage['result'])
            phase = 'commit'
            return mr.decide_round(app, data, principal, scope, c, current_task, current_contract,
                                   current_record, current_state, staged=staged)
    except Exception as error:
        # Preserve staged evidence without registering a failed candidate as an
        # official export. A post-commit mirroring error is not a rollback.
        with app.store.connect() as reader:
            durable = mr.setting(reader, 'receipt:' + task['id'] + ':' + data['request_key'])
        for ident, stage in staged.items():
            _retain_failure(app.store, {'id': ident, 'request_key': data['request_key']}, stage['source'],
                            stage['assets'], phase, error, committed=bool(durable))
        raise

