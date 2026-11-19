"""Explicit same-round leaf results adopted by selected main-figure slots.

No model-supplied revision or asset is accepted. Future sources are private to
the declared batch until the existing file/SQL journal commits the whole group.
"""
import copy

from research_partner.storage.store import digest, encoded, require


def freeze(app, raw, targets, groups, project, connection):
    from research_partner.domains.manuscripts.main_round import is_main
    require(isinstance(raw, list) and len(raw) <= 48, '本轮图位采用需有界明确列表')
    result, seen = [], set()
    for edge in raw:
        require(isinstance(edge, dict) and set(edge) == {'main_target_index', 'slot_id', 'leaf_target_index'},
                '图位采用只接受本轮主图目标、图位和叶图目标')
        mi, li, slot_id = edge['main_target_index'], edge['leaf_target_index'], edge['slot_id']
        require(type(mi) is int and type(li) is int and 0 <= mi < len(targets) and 0 <= li < len(targets)
                and mi != li and isinstance(slot_id, str) and (mi, slot_id) not in seen,
                '图位采用目标无效或重复')
        main, leaf = targets[mi], targets[li]
        require(is_main(main['target']) and leaf['target'].get('kind') == 'figure'
                and leaf['target'].get('field') == 'visual_overlays'
                and slot_id in main['target']['slot_ids'], '图位采用只连接本轮已选主图图位与独立叶图')
        require(any({mi, li} <= set(g['target_indices']) for g in groups),
                '图位与叶图必须明确列入同一依赖组', 'atomic_group_required', 409)
        ref = next(s['source'] for s in main['base']['content']['slots'] if s['id'] == slot_id)
        require(ref is not None and ref['id'] == leaf['target']['object_id'],
                '本轮只推进原已引用叶图，不猜测或替换其他来源', 'figure_source_changed', 409)
        old = app.store.get(ref['id'], ref['revision'], connection)
        require(old['project_id'] == leaf['base']['project_id'] == main['base']['project_id'] == project
                and digest(old) == ref['sha256'], '原图位来源身份不符', 'integrity', 409)
        scientific = lambda obj: {k: v for k, v in obj['content'].items() if k not in {'overlays', 'caption'}}
        require(digest(scientific(old)) == digest(scientific(leaf['base'])),
                '叶图科学来源已改变，不能作为本轮视觉更新偷偷采用', 'figure_source_changed', 409)
        frozen = {**copy.deepcopy(edge), 'source_ref': copy.deepcopy(ref),
                  'leaf_source_sha256': digest(leaf['base'])}
        result.append(frozen); seen.add((mi, slot_id))
        main['binding'].setdefault('slot_adoptions', []).append(copy.deepcopy(frozen))
    return result


def check_changes(contract, changes, decisions=None):
    by_target = {encoded(row['target']): row['id'] for row in changes}
    chosen = {d['change_id']: d['decision'] for d in decisions} if decisions is not None else None
    for edge in contract.get('slot_adoptions', []):
        main = by_target.get(encoded(contract['targets'][edge['main_target_index']]['target']))
        leaf = by_target.get(encoded(contract['targets'][edge['leaf_target_index']]['target']))
        if main is None: continue  # Honest no-change response remains allowed.
        require(leaf is not None, '推进图位引用必须有同轮真实叶图变更', 'atomic_group_required', 409)
        if chosen and chosen.get(main) == 'accept':
            require(chosen.get(leaf) == 'accept', '图位与叶图必须在同一次决定中共同采用',
                    'atomic_group_required', 409)


class BoundSources:
    """Read facade containing only explicitly bound, already rendered leaves."""
    def __init__(self, store, stages):
        self.store = store
        self.stages = dict(stages)
        for ident, stage in self.stages.items():
            obj, result = stage['candidate'], stage['result']
            require(obj['id'] == ident and result.get('status') == 'generated'
                    and result.get('provenance', {}).get('source_sha256') == digest(obj),
                    '暂存叶图没有本次真实渲染身份', 'integrity', 409)

    def __getattr__(self, name):
        return getattr(self.store, name)

    def get(self, ident, revision=None, connection=None):
        stage = self.stages.get(ident)
        if stage and revision == stage['candidate']['revision']:
            return copy.deepcopy(stage['candidate'])
        return self.store.get(ident, revision, connection)

    def export_records(self, ident, revision=None):
        stage = self.stages.get(ident)
        if stage and revision == stage['candidate']['revision']:
            return [{'result': copy.deepcopy(stage['result'])}]
        return self.store.export_records(ident, revision)

    def _pending(self, sha):
        for stage in self.stages.values():
            for data, item in stage['assets'].pending:
                if item['sha'] == sha:
                    require(digest(data) == sha, '暂存叶图资产字节已改变', 'integrity', 409)
                    return data, item
        return None

    def asset(self, sha, connection=None):
        found = self._pending(sha)
        return copy.deepcopy(found[1]) if found else self.store.asset(sha, connection=connection)

    def staged_asset_bytes(self, sha):
        found = self._pending(sha)
        if found: return found[0]
        self.store.asset(sha)
        return (self.store.blobs / sha).read_bytes()


def apply_staged(contract, accepted, contents, staged):
    chosen = {encoded(r['target']) for r in accepted}
    for edge in contract.get('slot_adoptions', []):
        target = contract['targets'][edge['main_target_index']]['target']
        if encoded(target) not in chosen: continue
        ident = target['object_id']
        slot = next(s for s in contents[ident]['slots'] if s['id'] == edge['slot_id'])
        require(slot['source'] == edge['source_ref'], '原图位引用已改变', 'conflict', 409)
        fresh = next(s['source'] for s in staged[ident]['candidate']['content']['slots'] if s['id'] == edge['slot_id'])
        leaf_id = contract['targets'][edge['leaf_target_index']]['target']['object_id']
        require(fresh['id'] == leaf_id and fresh['revision'] == staged[leaf_id]['candidate']['revision']
                and fresh['sha256'] == digest(staged[leaf_id]['candidate']), '图位不是本轮实际叶图', 'integrity', 409)
        slot['source'] = copy.deepcopy(fresh)


from research_partner.domains.figures.commit import _CandidateAssets


class MainCandidateAssets(_CandidateAssets):
    def staged_asset_bytes(self, sha):
        for data, item in self.pending:
            if item['sha'] == sha:
                require(digest(data) == sha, '主图暂存资产字节不符', 'integrity', 409)
                return data
        return self.store.staged_asset_bytes(sha)
