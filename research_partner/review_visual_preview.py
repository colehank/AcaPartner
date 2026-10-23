"""Explicit preview of immutable review candidates, without adopting them.

Reuse the adoption renderer and its source/numeric checks. Only the selected
image assets become preview cache entries after revalidation. No model, source,
native definition, official export, task or review decision is written.
"""
import copy

from . import manuscript_revision as mr
from . import manuscript_main_round as main_round
from .figure_definition import FigureDefinitions
from .store import digest, require


def preview(app, data, scope, principal, *, precheck=None):
    require(isinstance(data, dict) and set(data) <= {
        'action', 'project_id', 'task_id', 'candidate_sha256', 'proposal_sha256',
        'expected_review_revision', 'expected_decision_version',
        'expected_target_revisions', 'change_ids'},
        '预览只接受固定候选身份和完整组，不能修改候选内容', 'invalid_preview', 422)
    require(data.get('action') == 'desk.review.preview', '预览动作不支持')
    ids = data.get('change_ids')
    require(isinstance(ids, list) and 0 < len(ids) <= 256 and
            all(isinstance(i, str) for i in ids) and len(set(ids)) == len(ids),
            '请选择明确且唯一的候选项', 'invalid_preview', 422)
    task = app.store.task(data.get('task_id'))
    require(task['project_id'] == data.get('project_id'), '候选不属于当前项目', 'forbidden', 403)
    mr.task_access(app, task, scope, None)
    # Project/group selection is projected locally, not sent to a decide route.
    # This pure preparation cannot produce a receipt or change review state.
    selected = {**data, 'decisions': [{'change_id': i, 'decision': 'accept'} for i in ids]}

    def prepare(c):
        if precheck:
            precheck(c)
        current_task, contract, record, state = mr.proposal(app, data, scope, c)
        require(record and contract['version'] == 3, '此回合没有可预览的图候选', 'conflict', 409)
        prepared = mr.prepare_round_selection(app, selected, principal, scope, c,
                                               current_task, contract, record, state)
        require(any(row['target']['kind'] == 'figure' for row in prepared['accepted']),
                '所选候选没有图形改动', 'invalid_preview', 422)
        return current_task, contract, prepared

    # Never recover a pending adoption merely because the user asks to preview.
    with FigureDefinitions(app.store).locked(task['project_id'], recover=False) as context:
        with app.store.read_snapshot() as c:
            task, contract, prepared = prepare(c)
        _, entries, stages, _ = main_round.render_candidates(app, task, contract, prepared,
                                                            context, scope, principal)
        identity = {
            'project_id': task['project_id'], 'task_id': task['id'],
            'candidate_sha256': data['candidate_sha256'], 'proposal_sha256': data['proposal_sha256'],
            'decision_version': data['expected_decision_version'],
            'target_revisions': copy.deepcopy(data['expected_target_revisions']),
            'change_ids': copy.deepcopy(ids), 'saved': False, 'official_export_recorded': False,
        }
        images = []
        # Do not retain candidate outputs on a failed freshness/permission check.
        with app.store.transaction() as c:
            _, latest_contract, latest = prepare(c)
            require(digest(latest) == digest(prepared) and digest(latest_contract) == digest(contract),
                    '预览期间稿件、图或意见已变化；请重新读取', 'conflict', 409)
            for ident, entry in entries.items():
                require(FigureDefinitions(app.store)._raw(context, ident) == entry['before'],
                        '预览期间主图定义文件已变化；保留当前文件', 'conflict', 409)
            main_round.recheck_staged(app, stages, entries, scope, principal)
            for ident, stage in stages.items():
                result = stage['result']
                asset = result.get('assets', {}).get('figure.svg') or result.get('asset')
                require(isinstance(asset, dict) and asset.get('media_type') in {'image/svg+xml', 'image/png'},
                        '候选没有可查看的实际图像', 'integrity', 409)
                payload = stage['assets'].staged_asset_bytes(asset['sha'])
                metadata = {**asset.get('metadata', {}), 'preview_only': True,
                            'project_id': task['project_id'], 'review_preview': identity}
                registered = app.store.add_asset(payload, asset['filename'], asset['media_type'],
                                                 metadata, connection=c)
                images.append({
                    'object_id': ident, 'title': stage['source']['title'],
                    'base_revision': stage['source']['revision'],
                    'base_source_sha256': digest(stage['source']),
                    'candidate_source_sha256': digest(stage['candidate']),
                    'asset': registered, 'numeric_preserved': True,
                })
        return {'preview_identity': identity, 'figures': images}
