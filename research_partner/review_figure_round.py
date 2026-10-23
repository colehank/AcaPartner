"""Figure opinions join the existing project review list and round identity.

This adapter adds no execution authority. Only saved leaf Artists with a real
mapping are addressable; composition definitions keep their own journal.
"""
import copy
import json

from .store import require, digest, encoded, now
from .manuscript_revision import actor
from .manuscript_figure_round import freeze, writable as leaf_writable


def writable(app, ident, project, scope, c):
    from .figure_definition import is_definition
    if is_definition(app.store.get(ident, connection=c)):
        from .manuscript_main_round import writable as main_writable
        return main_writable(app, ident, project, scope, c)
    return leaf_writable(app, ident, project, scope, c)


def visual_item(item):
    return item.get('field') in {'visual_overlays', 'slot_layout'}


def selection(app, data, main, scope, c):
    if data.get('field') == 'slot_layout':
        from .manuscript_main_round import freeze as freeze_main
        raw = {'kind': 'figure', 'field': 'slot_layout', 'object_id': data.get('object_id'),
               'expected_revision': data.get('expected_object_revision'), 'slot_ids': data.get('slot_ids'),
               'expected_definition_sha256': data.get('expected_definition_sha256')}
        if 'component_index' in data: raw['component_index'] = data['component_index']
        frozen = freeze_main(app, raw, main, scope, c)
        return frozen, {'kind': 'main_figure_slots', 'slot_ids': copy.deepcopy(raw['slot_ids']), 'render_source': {
            'object_id': raw['object_id'], 'revision': frozen['base_revision'],
            'source_sha256': frozen['binding']['source_sha256'],
            'definition_sha256': frozen['binding']['definition_sha256']}}
    require(isinstance(data.get('artist_id'), str), '请在真实画布选中一个已登记元素')
    raw = {'kind': 'figure', 'field': 'visual_overlays', 'object_id': data.get('object_id'),
           'expected_revision': data.get('expected_object_revision'), 'artist_ids': [data['artist_id']]}
    if 'component_index' in data: raw['component_index'] = data['component_index']
    frozen = freeze(app, raw, main, scope, c)
    anchor = {'artist_id': data['artist_id'], 'render_source': {
        'object_id': frozen['target']['object_id'], 'revision': frozen['base_revision'],
        'source_sha256': frozen['binding']['source_sha256']}}
    return frozen, anchor


def change(app, data, project, state, main, scope, principal, c):
    from .review_w1b import save
    allowed = {'action', 'project_id', 'expected_review_revision', 'expected_manuscript_revision',
               'op', 'id', 'field', 'object_id', 'expected_object_revision', 'artist_id', 'component_index', 'text',
               'slot_ids', 'expected_definition_sha256'}
    require(set(data) <= allowed, '图意见只接受当前元素和原话，不能写数据或图形')
    op = data.get('op'); require(op in {'create', 'edit', 'delete', 'restore', 'reanchor'}, '意见操作不支持')
    item = None if op == 'create' else next((i for i in state['opinions'] if i['id'] == data.get('id')), None)
    if op != 'create':
        require(item and visual_item(item), '图意见不存在', 'not_found', 404)
        writable(app, item['base_ref']['id'], project['id'], scope, c)
    if op in {'create', 'reanchor'}:
        require(data.get('field') in {'visual_overlays', 'slot_layout'}, '请明确图意见类型')
        require(('artist_id' not in data if data['field'] == 'slot_layout' else
                 'slot_ids' not in data and 'expected_definition_sha256' not in data), '图意见类型不可混用')
        frozen, anchor = selection(app, data, main, scope, c)
        if data['field'] == 'slot_layout':
            from .compatibility import require_features
            require_features(c, ['reviewed_main_layout_round_v1'])
        target = frozen['target']
        ident, revision = target['object_id'], frozen['base_revision']
        if item:
            require(not item['deleted'] and ident == item['base_ref']['id'] and item['field'] == data['field'], '不能把原意见转移到另一幅图或类型')
    if op == 'create':
        text = data.get('text'); require(isinstance(text, str) and 0 < len(text.strip()) <= 4000, '意见需要1–4000字')
        annotation = app.store.annotate(ident, revision, anchor, text, connection=c)
        require(annotation['status'] == 'anchored', '当前元素没有有效映射', 'conflict', 409)
        selection_fields = ({'slot_ids': copy.deepcopy(data['slot_ids']), 'expected_definition_sha256': data['expected_definition_sha256']}
                            if data['field'] == 'slot_layout' else {'artist_id': data['artist_id']})
        item = {'id': annotation['id'], 'field': data['field'], **selection_fields,
                'anchor': anchor, 'text': text, 'revision': 1, 'base_ref': {'id': ident, 'revision': revision},
                'deleted': False, 'created_by': actor(principal), 'created_at': now()}
        if 'component_index' in target: item['component_index'] = target['component_index']
        state['opinions'].append(item)
    else:
        before = copy.deepcopy({k: v for k, v in item.items() if k != 'history'})
        if op == 'edit':
            require(not item['deleted'], '请先恢复已删除意见')
            text = data.get('text'); require(isinstance(text, str) and 0 < len(text.strip()) <= 4000, '意见需要1–4000字')
            row = c.execute('SELECT * FROM annotations WHERE id=? AND object_id=?', (item['id'], item['base_ref']['id'])).fetchone()
            require(row, '原图批注不存在', 'not_found', 404)
            c.execute('UPDATE annotations SET text=? WHERE id=?', (text, item['id']))
            app.store.event(c, 'annotation.updated', item['base_ref']['id'], {'id': item['id'], 'previous_text': row['text']}, actor(principal))
            item['text'] = text
        elif op == 'reanchor':
            c.execute("UPDATE annotations SET anchor=?,revision=?,status='anchored' WHERE id=? AND object_id=?", (encoded(anchor), revision, item['id'], ident))
            app.store.event(c, 'annotation.reanchored', ident, {'id': item['id'], 'previous_anchor': item['anchor'],
                'previous_revision': item['base_ref']['revision'], 'anchor': anchor, 'revision': revision}, actor(principal))
            item.update(anchor=anchor, base_ref={'id': ident, 'revision': revision})
            if item['field'] == 'slot_layout':
                item.update(slot_ids=copy.deepcopy(data['slot_ids']), expected_definition_sha256=data['expected_definition_sha256'])
            else: item['artist_id'] = data['artist_id']
            item.pop('component_index', None)
            if 'component_index' in target: item['component_index'] = target['component_index']
        else: item['deleted'] = op == 'delete'
        item['revision'] += 1; item.setdefault('history', []).append(before)
    return save(app, project, state, principal, {'op': op, 'opinion_id': item['id']}, c)


def targets(active, main, text_targets):
    """Coalesce selected Artists on the same saved figure without extra writes."""
    selected, indices = [], []
    for item, items in zip(active, text_targets):
        if visual_item(item):
            raw = {'object_id': item['base_ref']['id'], 'expected_revision': item['base_ref']['revision'],
                   'kind': 'figure', 'field': item['field']}
            if item['field'] == 'slot_layout':
                raw.update(slot_ids=copy.deepcopy(item['slot_ids']), expected_definition_sha256=item['expected_definition_sha256'])
            else: raw['artist_ids'] = [item['artist_id']]
            if 'component_index' in item: raw['component_index'] = item['component_index']
            matches = [t for t in selected if t['kind'] == 'figure' and t['object_id'] == raw['object_id']]
            if matches:
                previous = matches[0]
                require(previous['field'] == raw['field'] and previous['expected_revision'] == raw['expected_revision']
                        and previous.get('expected_definition_sha256') == raw.get('expected_definition_sha256')
                        and previous.get('component_index') == raw.get('component_index'),
                        '同一图的意见需同一保存版和同一采用位置，请先整理', 'conflict', 409)
                field = 'slot_ids' if raw['field'] == 'slot_layout' else 'artist_ids'
                for ident in raw[field]:
                    if ident not in previous[field]: previous[field].append(ident)
                indices.append([selected.index(previous)])
            else:
                selected.append(raw); indices.append([len(selected) - 1])
        else:
            own = []
            for target in items:
                raw = {'object_id': main['id'], 'expected_revision': main['revision'], 'kind': 'manuscript', **target}
                if raw not in selected: selected.append(raw)
                own.append(selected.index(raw))
            indices.append(own)
    return selected, indices


def groups(raw, active, opinion_targets):
    require(isinstance(raw, list) and len(raw) <= 48, '关联组需明确有限列表')
    index = {item['id']: targets for item, targets in zip(active, opinion_targets)}
    result = []
    for group in raw:
        require(isinstance(group, dict) and set(group) == {'id', 'opinion_ids'}, '关联组只接受组名和明确意见')
        ids = group['opinion_ids']
        require(isinstance(ids, list) and len(ids) >= 2 and all(isinstance(i, str) and i in index for i in ids)
                and len(ids) == len(set(ids)), '关联组意见需唯一且在当前保留集合中')
        result.append({'id': group['id'], 'target_indices': sorted({n for i in ids for n in index[i]})})
    return result


def decide(app, data, project, scope, principal):
    """No outer writer lock while rendering; recheck review CAS at publication."""
    from .review_w1b import load
    from .manuscript_figure_round import decide as decide_round
    def check(c):
        state = load(app, project, c)
        require(data.get('expected_review_revision') == state['revision'], '意见列表已改变', 'conflict', 409)
        found = next((r for r in state['rounds'] if r['task_id'] == data.get('task_id')), None)
        require(found and found['status'] == 'submitted', '本回合不存在或已经撤回', 'forbidden', 403)
    request = {k: v for k, v in data.items() if k not in {'project_id', 'expected_review_revision'}}
    request['action'] = 'manuscript.revision.decide'
    return decide_round(app, request, scope, principal, precommit=check)


def slot_adoptions(raw, active, opinion_targets, dependency_groups):
    """Translate explicit saved opinion identities; never infer a source edge."""
    require(isinstance(raw, list) and len(raw) <= 48, '本轮来源采用需明确有限列表')
    by_id = {item['id']: (item, indices) for item, indices in zip(active, opinion_targets)}
    result = []
    for edge in raw:
        require(isinstance(edge, dict) and set(edge) == {'main_opinion_id', 'slot_id', 'leaf_opinion_id'}
                and all(isinstance(v, str) for v in edge.values()), '图位采用需要准确的两条意见和图位')
        mi, li = edge['main_opinion_id'], edge['leaf_opinion_id']
        require(mi in by_id and li in by_id, '来源采用意见已删除或不在本轮', 'conflict', 409)
        main, mains = by_id[mi]; leaf, leaves = by_id[li]
        require(main.get('field') == 'slot_layout' and leaf.get('field') == 'visual_overlays'
                and edge['slot_id'] in main['slot_ids'] and len(mains) == len(leaves) == 1,
                '图位采用需明确所选主图图位与叶图意见')
        require(any({mi, li} <= set(group['opinion_ids']) for group in dependency_groups),
                '来源采用意见需在同一明确关联组', 'atomic_group_required', 409)
        result.append({'main_target_index': mains[0], 'slot_id': edge['slot_id'], 'leaf_target_index': leaves[0]})
    return result
