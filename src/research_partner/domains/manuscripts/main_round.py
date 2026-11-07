"""File-authoritative main-layout targets in an explicitly selected v3 round.

These targets change selected slot boxes, never panel bindings or scientific
values. The existing definition lock is acquired before any SQL writer.
"""
import contextlib
import contextvars
import copy
import json
import math

from research_partner.domains.figures.definition import FigureDefinitions, is_definition
from research_partner.storage.store import Problem, digest, encoded, now, require

_current = contextvars.ContextVar('manuscript_main_definition_session', default=None)


def is_main(target):
    return target.get('kind') == 'figure' and target.get('field') == 'slot_layout'


@contextlib.contextmanager
def locked(app, project):
    value = _current.get()
    if value is not None:
        require(value[0] is app and value[1]['project_id'] == project, '主图回合不能跨项目嵌套', 'integrity', 409)
        yield value[1]
        return
    with FigureDefinitions(app.store).locked(project) as session:
        token = _current.set((app, session))
        try: yield session
        finally: _current.reset(token)


def session(app, project):
    value = _current.get()
    require(value is not None and value[0] is app and value[1]['project_id'] == project,
            '主图冻结需先持有定义锁，再进入事务', 'context_preparation', 409)
    return value[1]


def has_session(app):
    value = _current.get()
    return value is not None and value[0] is app


def writable(app, ident, project, scope, c):
    from research_partner.domains.figures.commit import _writable
    obj = _writable(app, ident, scope, None, c)
    require(obj['project_id'] == project and is_definition(obj), '请选择当前项目的文件主图', 'forbidden', 403)
    return obj


def selected_slots(obj, ids):
    by_id = {s['id']: s for s in obj['content']['slots']}
    require(isinstance(ids, list) and 0 < len(ids) <= 24 and all(isinstance(i, str) and i in by_id for i in ids)
            and len(set(ids)) == len(ids), '请选择当前主图的唯一图位', 'invalid_visual_target', 422)
    return [{'id': i, 'box': copy.deepcopy(by_id[i]['box'])} for i in ids]


def freeze(app, raw, main, scope, c):
    require(set(raw) <= {'object_id', 'expected_revision', 'kind', 'field', 'slot_ids',
                        'expected_definition_sha256', 'component_index'} and is_main(raw)
            and isinstance(raw.get('object_id'), str) and type(raw.get('expected_revision')) is int,
            '主图意见只接受固定版本、定义摘要与所选图位')
    obj = writable(app, raw['object_id'], main['project_id'], scope, c)
    definitions = FigureDefinitions(app.store)
    content = definitions._raw(session(app, main['project_id']), obj['id'])
    require(obj['revision'] == raw['expected_revision'] and digest(content) ==
            raw.get('expected_definition_sha256') == obj['content']['definition_sha256'],
            '主图定义文件或保存版已变化，请重新读取', 'conflict', 409)
    value = definitions.parse(content, main['project_id'], obj['id'])
    require(definitions.content(value, digest(content)) == obj['content'] and value['title'] == obj['title'],
            '主图定义与登记投影不同', 'integrity', 409)
    before = selected_slots(obj, raw.get('slot_ids'))
    target = {'kind': 'figure', 'field': 'slot_layout', 'object_id': obj['id'], 'slot_ids': copy.deepcopy(raw['slot_ids'])}
    binding = {'kind': 'main_figure_layout', 'source_sha256': digest(obj),
               'definition_sha256': digest(content), 'definition_text': content.decode('utf-8')}
    if 'component_index' in raw:
        from research_partner.domains.figures.commit import _occurrence
        index = raw['component_index']; refs = main['content'].get('components', [])
        require(type(index) is int and 0 <= index < len(refs) and isinstance(refs[index], dict), '需准确稿内图位置')
        ref = copy.deepcopy(refs[index])
        _occurrence(app, {'id': main['id'], 'expected_revision': main['revision'], 'component_index': index,
                         'component_id': obj['id'], 'component_revision': ref.get('revision'), 'component_ref': ref}, obj, scope, None, c)
        target['component_index'] = index; binding['component_ref'] = ref
    return {'target': target, 'base_revision': obj['revision'], 'base': copy.deepcopy(obj),
            'before': encoded(before), 'binding': binding, 'title': obj['title']}


def validate_after(frozen, value):
    require(isinstance(value, str) and len(value) <= 30000, '主图布局需有限JSON文字', 'invalid_model_output', 422)
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result: raise ValueError('duplicate member')
            result[k] = v
        return result
    def nonfinite(_): raise ValueError('nonfinite number')
    try: slots = json.loads(value, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, TypeError) as error: raise Problem('主图候选不是有限JSON', 'invalid_model_output', 422) from error
    require(isinstance(slots, list) and len(slots) == len(frozen['target']['slot_ids']),
            '主图候选需保留完整所选图位集合', 'invalid_model_output', 422)
    for row, ident in zip(slots, frozen['target']['slot_ids']):
        require(isinstance(row, dict) and set(row) == {'id', 'box'} and row['id'] == ident,
                '主图候选只能按原顺序修改所选图位边界', 'invalid_model_output', 422)
        box = row['box']
        require(isinstance(box, list) and len(box) == 4 and all(type(x) in (int, float) and math.isfinite(x) for x in box),
                '主图候选需要四个有限布局值', 'invalid_model_output', 422)
        x, y, w, h = box
        require(x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= 1 and y+h <= 1,
                '主图布局超出边界', 'invalid_model_output', 422)
    require(slots != json.loads(frozen['before']) or frozen['binding'].get('slot_adoptions'),
            '主图布局未发生变化', 'invalid_model_output', 422)
    return slots


def current(frozen, objects, main):
    obj = objects[frozen['target']['object_id']]
    require(digest(obj) == frozen['binding']['source_sha256'], '主图有新保存或来源，旧候选不能覆盖', 'conflict', 409)
    if 'component_index' in frozen['target']:
        index = frozen['target']['component_index']; refs = main['content'].get('components', [])
        require(index < len(refs) and refs[index] == frozen['binding']['component_ref'], '稿内使用已有变化', 'conflict', 409)
    return encoded(selected_slots(obj, frozen['target']['slot_ids']))


def apply_content(content, frozen, after):
    # This intermediate value is never saved. The file journal prepares the
    # complete derived pages, raw definition SHA and future revision together.
    rows = {s['id']: s['box'] for s in validate_after(frozen, after)}
    for slot in content['slots']:
        if slot['id'] in rows: slot['box'] = copy.deepcopy(rows[slot['id']])


def anchor_status(anchor, obj):
    if anchor.get('kind') != 'main_figure_slots': return 'orphaned'
    identity = anchor.get('render_source', {})
    try: selected_slots(obj, anchor.get('slot_ids'))
    except (Problem, KeyError, TypeError): return 'orphaned'
    return 'anchored' if (is_definition(obj) and identity == {
        'object_id': obj['id'], 'revision': obj['revision'], 'source_sha256': digest(obj),
        'definition_sha256': obj['content']['definition_sha256']}) else 'text_changed'


def annotation_indices(annotation, targets):
    a = annotation['anchor']
    return [i for i, t in enumerate(targets) if is_main(t['target'])
            and t['target']['object_id'] == annotation['object_id']
            and set(a.get('slot_ids', [])) <= set(t['target']['slot_ids'])]


def check_annotation(annotation, targets, indices):
    matches = annotation_indices(annotation, targets)
    require(matches and set(indices) == set(matches), '主图意见需准确绑定全部所选图位', 'conflict', 409)
    for i in matches:
        require(anchor_status(annotation['anchor'], targets[i]['base']) == 'anchored',
                '主图意见来自另一保存定义，请明确重新定位', 'conflict', 409)


def check_sources(app, obj, scope, principal, engine):
    """Revalidate each pinned panel and exact registered numeric/SVG bytes."""
    from research_partner.domains.figures.commit import _writable
    refs = []
    for slot in obj['content']['slots']:
        ref = slot['source']
        if ref is None: continue
        _writable(app, ref['id'], scope, principal)
        source, _ = engine._reference(obj, {k: ref[k] for k in ('id', 'revision', 'sha256')})
        require(source['project_id'] == obj['project_id'], '主图固定子图不属于当前项目', 'forbidden', 403)
        for key in ('svg_sha256', 'numeric_sha256'):
            if ref.get(key): engine._asset_bytes(ref[key], owner=source)
        refs.append(copy.deepcopy(ref))
    return refs


def render_candidates(app, task, contract, prepared, context, scope, principal, *, staged=None):
    """Privately render the exact selected leaves then their main figures.

    No publication, source write, export registration or review decision occurs
    here. The caller must revalidate before exposing or adopting these bytes.
    """
    from research_partner.domains.manuscripts import revision as mr
    from research_partner.domains.figures import round_journal as journal
    from research_partner.rendering.engine import ArtifactEngine
    from research_partner.domains.figures.commit import _CandidateAssets
    staged = {} if staged is None else staged
    definitions = FigureDefinitions(app.store)
    changes = []
    for row in prepared['accepted']:
        if is_main(row['target']):
            frozen = prepared['frozen'][mr.target_key(row['target'])]
            changes.append({'object_id': row['target']['object_id'], 'expected_revision': frozen['base_revision'],
                            'expected_definition_sha256': frozen['binding']['definition_sha256'],
                            'slots': validate_after(frozen, row['after'])})
    batch, main_entries, source_store = None, {}, app.store
    # Leaves render privately first. Only declared same-batch results
    # become readable to the main renderer, never global HEADs.
    for row in sorted(prepared['accepted'], key=lambda r: is_main(r['target'])):
        if row['target']['kind'] != 'figure': continue
        ident = row['target']['object_id']; source = prepared['objects'][ident]
        if is_main(row['target']) and not main_entries:
            from research_partner.domains.manuscripts.slot_adoption import BoundSources
            edges = [edge for edge in contract.get('slot_adoptions', [])
                     if contract['targets'][edge['main_target_index']]['target']['object_id'] in prepared['contents']]
            leaf_ids = {contract['targets'][edge['leaf_target_index']]['target']['object_id'] for edge in edges}
            require(leaf_ids <= set(staged), '图位需要同批已真实渲染的叶图', 'integrity', 409)
            source_store = BoundSources(app.store, {i: staged[i] for i in leaf_ids}) if edges else app.store
            definitions = FigureDefinitions(source_store)
            by_id = {change['object_id']: change for change in changes}
            for edge in edges:
                main_id = contract['targets'][edge['main_target_index']]['target']['object_id']
                leaf_id = contract['targets'][edge['leaf_target_index']]['target']['object_id']
                leaf_stage = staged[leaf_id]
                require(digest(leaf_stage['source']) == edge['leaf_source_sha256'], '本轮叶图来源不符', 'integrity', 409)
                fresh = definitions.resolve_source(task['project_id'], {'id': leaf_id, 'revision': leaf_stage['candidate']['revision']}, main_id)
                require(fresh['numeric_sha256'] == edge['source_ref']['numeric_sha256'],
                        '本轮叶图数值与原图位固定资产不同', 'numeric_baseline_changed', 409)
                by_id[main_id].setdefault('sources', {})[edge['slot_id']] = fresh
            batch = journal.prepare(definitions, context, changes)
            main_entries = {e['base']['id']: e for e in batch['entries']}
        candidate = main_entries[ident]['candidate'] if ident in main_entries else {
            **copy.deepcopy(source), 'revision': source['revision'] + 1, 'updated_at': now(),
            'content': copy.deepcopy(prepared['contents'][ident])}
        if ident in main_entries and source_store is not app.store:
            from research_partner.domains.manuscripts.slot_adoption import MainCandidateAssets
            assets = MainCandidateAssets(source_store, candidate)
        else:
            assets = _CandidateAssets(app.store, candidate)
        engine = ArtifactEngine(assets, app.config.get('rendering', {}))
        stage = {'source': source, 'candidate': candidate, 'assets': assets, 'engine': engine}
        staged[ident] = stage
        if ident in main_entries:
            old_refs = check_sources(app, source, scope, principal, engine)
            stage['refs'] = check_sources(app, candidate, scope, principal, engine)
            chosen_sources = next(change.get('sources', {}) for change in changes if change['object_id'] == ident)
            expected_refs = [chosen_sources.get(slot['id'], slot['source']) for slot in source['content']['slots'] if slot['source'] is not None]
            require(stage['refs'] == expected_refs, '主图改变了未授权固定来源', 'integrity', 409)
            result = engine.export(candidate, 'svg')
            # Keep the renderer's provenance and its registered JSON
            # bytes identical. The independent exact-layout proof is
            # recorded on the decision receipt, not patched into them.
            stage['layout_proof'] = {'fixed_panels': copy.deepcopy(stage['refs']),
                                     'numeric_preserved': True, 'layout_only': not bool(chosen_sources)}
            if chosen_sources:
                stage['layout_proof']['explicit_slot_adoptions'] = copy.deepcopy(chosen_sources)
                stage['layout_proof']['previous_panels'] = old_refs
        else:
            script = source['content'].get('script_asset') or source['content'].get('script')
            stage['script'] = script
            grant = app.store.setting('code_grant:' + ident, {})
            authorized = bool(script and grant.get('script_sha') == source['content'].get('script_asset'))
            require(not script or authorized, '图重绘需当前明确代码授权', 'authorization_required', 403)
            result = engine.render_figure(candidate, authorized_code=authorized)
            require(result.get('provenance', {}).get('numeric_preserved') is True
                    and not result.get('replay', {}).get('failures'), '叶图重放或数值保护失败', 'integrity', 409)
        require(result.get('status') == 'generated' and result.get('provenance', {}).get('source_sha256') == digest(candidate),
                '真实渲染不属于本次候选', 'integrity', 409)
        stage['result'] = result
    return batch, main_entries, staged, definitions


def recheck_staged(app, staged, main_entries, scope, principal):
    from research_partner.domains.figures.preview import _recheck, _baseline
    for ident, stage in staged.items():
        if ident in main_entries:
            require(stage['refs'] == check_sources(app, stage['candidate'], scope, principal, stage['engine']),
                    '重绘后固定子图来源变化', 'conflict', 409)
        else:
            _recheck(app, stage['source'], digest(stage['source']), stage['script'], scope, stage['engine'], principal)
            _baseline(app, stage['source'], digest(stage['source']), stage['result'])


def decide(app, data, scope, principal, *, precommit=None):
    from research_partner.domains.manuscripts import revision as mr
    from research_partner.domains.figures import round_journal as journal
    from research_partner.rendering.engine import ArtifactEngine
    from research_partner.domains.figures.commit import _CandidateAssets, _retain_failure
    from research_partner.domains.figures.preview import _recheck, _baseline
    task = app.store.task(data.get('task_id'))
    mr.source(app, task['payload']['context'][mr.KIND]['object_id'], scope, None)
    definitions = FigureDefinitions(app.store); staged = {}; phase = 'prepare'
    with locked(app, task['project_id']) as context:
        try:
            with app.store.read_snapshot() as c:
                if precommit: precommit(c)
                task, contract, record, state = mr.proposal(app, data, scope, c)
                require(record and contract['version'] == 3, '主图回合候选未就绪', 'conflict', 409)
                prepared = mr.decide_round(app, data, principal, scope, c, task, contract, record, state, prepare_only=True)
            if not prepared.get('prepared'): return prepared
            phase = 'render'
            batch, main_entries, staged, definitions = render_candidates(app, task, contract, prepared, context, scope, principal, staged=staged)
            phase = 'recheck'
            def check(c):
                if precommit: precommit(c)
                current_task, current_contract, current_record, current_state = mr.proposal(app, data, scope, c)
                latest = mr.decide_round(app, data, principal, scope, c, current_task, current_contract,
                                         current_record, current_state, prepare_only=True)
                require(digest(latest) == digest(prepared), '重绘期间意见、稿件或图已改变；整组不采用', 'conflict', 409)
                recheck_staged(app, staged, main_entries, scope, principal)

            def commit(c, written):
                current_task, current_contract, current_record, current_state = mr.proposal(app, data, scope, c)
                return mr.decide_round(app, data, principal, scope, c, current_task, current_contract,
                                       current_record, current_state, staged=staged, prewritten={
                                           ident: {'base': main_entries[ident]['base'], 'written': obj}
                                           for ident, obj in written.items()})
            phase = 'commit'
            if batch:
                # Refuse already stale authority/opinions before any native file
                # changes. Repeat this check in the writer to close later races.
                with app.store.read_snapshot() as c:
                    check(c)
                return journal.publish(definitions, context, batch, data['request_key'],
                                       digest({'data': data, 'principal': principal}), commit, prewrite=check)
            with app.store.transaction() as c:
                check(c)
                return commit(c, {})
        except Exception as error:
            if phase == 'commit':
                # Ordinary rejected commands return with their own uncommitted
                # native bytes restored. A process crash still leaves the durable
                # batch for next-open recovery. Never overwrite external bytes.
                try:
                    definitions._recover(context)
                except Exception as recovery:
                    if isinstance(error, Problem):
                        error.details = {**error.details, 'definition_recovery': {
                            'status': 'blocked', 'code': getattr(recovery, 'code', type(recovery).__name__)}}
                    error.add_note('Definition recovery blocked: ' + str(recovery))
            with app.store.connect() as c:
                durable = mr.setting(c, 'receipt:' + task['id'] + ':' + str(data.get('request_key')))
            for ident, stage in staged.items():
                _retain_failure(app.store, {'id': ident, 'request_key': data['request_key']}, stage['source'],
                                stage['assets'], phase, error, committed=bool(durable))
            raise
