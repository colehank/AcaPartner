"""Commit one bounded visual edit and, optionally, one exact manuscript use.

Only the existing registered plotting source runs. Rendering happens outside the
writer lock; bytes stay staged until the figure, occurrence, permission, grant
and numerical baseline have been rechecked. The final object snapshots, assets,
official export and idempotent receipt share one short transaction.
"""
from __future__ import annotations

import copy
import json
import os

from research_partner.rendering.engine import ArtifactEngine
from research_partner.domains.figures.preview import _StagedAssets, _overlays, _recheck, _baseline
from research_partner.storage.store import Problem, digest, encoded, now, require, uid


KEY = 'figure.visual.commit41:'
ACTION = 'figure.visual.commit'
RECEIPT_ACTION = 'figure.visual.receipt'


class _CandidateAssets(_StagedAssets):
    """An internal future snapshot, visible only to its own staged renderer."""
    def __init__(self, store, candidate):
        super().__init__(store)
        self.candidate = copy.deepcopy(candidate)

    def get(self, ident, revision=None, connection=None):
        if ident == self.candidate['id'] and revision == self.candidate['revision']:
            return copy.deepcopy(self.candidate)
        return self.store.get(ident, revision, connection)

    def add_asset(self, *args, **kwargs):
        item = super().add_asset(*args, **kwargs)
        # These bytes are unpublished candidates for an official render, not a
        # registered draft preview. The final transaction determines publication.
        item['metadata'].pop('preview_only', None)
        return item


def _positive(value):
    return type(value) is int and value > 0


def _validate(data):
    require(isinstance(data, dict) and set(data) <= {'action','id','expected_revision','overlays','title','caption','request_key','manuscript'},
            '视觉采用仅接受覆盖、标题和图注，不能替换绘图来源', 'invalid_visual_commit', 422)
    require(data.get('action') == ACTION and isinstance(data.get('id'), str) and _positive(data.get('expected_revision')),
            '视觉采用需要图形准确版本', 'invalid_visual_commit', 422)
    key = data.get('request_key')
    require(isinstance(key, str) and key.strip() and len(key) <= 180, '视觉采用需要稳定请求标识', 'invalid_visual_commit', 422)
    require('overlays' in data, '请提供本次明确的视觉覆盖', 'invalid_visual_commit', 422)
    layers = _overlays(data['overlays'])
    if 'title' in data:
        require(isinstance(data['title'], str) and data['title'].strip() and len(data['title']) <= 500,
                '标题须为非空文本且不超过500字符', 'invalid_visual_commit', 422)
    if 'caption' in data:
        require(isinstance(data['caption'], str) and len(data['caption']) <= 30000,
                '图注须为文本且不超过30000字符', 'invalid_visual_commit', 422)
    target = data.get('manuscript')
    if target is not None:
        fields = {'id','expected_revision','component_index','component_id','component_revision','component_ref','component_ref_sha256'}
        require(isinstance(target, dict) and set(target) <= fields and isinstance(target.get('id'), str)
                and _positive(target.get('expected_revision')) and type(target.get('component_index')) is int
                and target['component_index'] >= 0 and target.get('component_id') == data['id']
                and _positive(target.get('component_revision')), '稿内采用位置不完整', 'invalid_occurrence', 422)
        require('component_ref' in target or 'component_ref_sha256' in target,
                '需要冻结的完整引用或其哈希', 'invalid_occurrence', 422)
        if 'component_ref' in target:
            require(isinstance(target['component_ref'], dict), '冻结引用须为对象', 'invalid_occurrence', 422)
        if 'component_ref_sha256' in target:
            sha = target['component_ref_sha256']
            require(isinstance(sha, str) and len(sha) == 64 and all(x in '0123456789abcdef' for x in sha),
                    '冻结引用哈希无效', 'invalid_occurrence', 422)
    return layers, target


def _writable(app, ident, scope, principal, connection=None):
    obj = app.store.get(ident, connection=connection)
    app.access(obj, scope)
    require(scope is None or obj['project_id'] in scope, '共享材料只读，不能采用到此对象', 'forbidden', 403)
    if principal is not None:
        from research_partner.domains.workspace.management import authority_scope
        current_scope = authority_scope(app, principal)
        require(current_scope is None or obj['project_id'] in current_scope, '对象写入权限已撤回', 'forbidden', 403)
    require(not obj['archived'], '归档成果只读', 'archived', 409)
    project = app.store.get(obj['project_id'], connection=connection)
    require(not project['archived'], '归档项目只读', 'archived', 409)
    return obj


def _occurrence(app, target, figure, scope, principal, connection=None):
    if target is None:
        return None, None
    manuscript = _writable(app, target['id'], scope, principal, connection)
    require(manuscript['kind'] in {'paper','report','note'}, '采用位置必须属于文稿', 'invalid_occurrence', 422)
    require(manuscript['revision'] == target['expected_revision'], '稿件已变化；图形与引用均未采用', 'conflict', 409)
    refs = manuscript['content'].get('components', [])
    index = target['component_index']
    require(isinstance(refs, list) and index < len(refs) and isinstance(refs[index], dict),
            '稿内引用位置已变化', 'conflict', 409)
    ref = refs[index]
    require((ref.get('id') or ref.get('object_id')) == figure['id']
            and all(ref[name] == figure['id'] for name in ['id','object_id'] if name in ref)
            and ref.get('revision') == target['component_revision'], '稿内引用或采用版本已变化', 'conflict', 409)
    if 'component_ref' in target:
        require(ref == target['component_ref'], '稿内引用字段已变化', 'conflict', 409)
    if 'component_ref_sha256' in target:
        require(digest(ref) == target['component_ref_sha256'], '稿内引用指纹已变化', 'conflict', 409)
    adopted = app.store.get(figure['id'], ref['revision'], connection)
    if ref.get('sha256') is not None:
        require(ref['sha256'] == digest(adopted), '原稿采用来源哈希不符', 'integrity', 409)
    # A manuscript may be pinned behind the figure head. Visual adoption must
    # never smuggle a different script/data/spec/parameter source into that pin.
    scientific_source = lambda obj: {key:value for key,value in obj['content'].items() if key not in {'overlays','caption'}}
    require(digest(scientific_source(adopted)) == digest(scientific_source(figure)),
            '图形生成来源与本稿采用版不同；需要另行核对科学来源，本次两端均未采用', 'figure_source_changed', 409,
            {'adopted_revision':ref['revision'],'current_revision':figure['revision']})
    if connection is None:
        with app.store.connect() as reader:
            app.store.assert_source_access(reader, manuscript['project_id'], figure['id'])
    else:
        app.store.assert_source_access(connection, manuscript['project_id'], figure['id'])
    return manuscript, copy.deepcopy(ref)


def _previous(connection, storage_key, fingerprint):
    row = connection.execute('SELECT value FROM kv WHERE key=?', (storage_key,)).fetchone()
    if row is None:
        return None
    saved = json.loads(row[0])
    require(saved['fingerprint'] == fingerprint, '同一采用请求标识内容不同', 'idempotency_conflict', 409)
    return saved['receipt']


def _readable(app, ident, scopes, connection):
    current = app.store.get(ident, connection=connection)
    for scope in scopes:
        app.access(current, scope)
    return current


def _receipt_access(app, receipt, scope, principal, connection):
    """An old receipt never retains a revoked right to its source or blobs."""
    scopes = [scope]
    if principal is not None:
        from research_partner.domains.workspace.management import authority_scope
        current_scope = authority_scope(app, principal)
        if current_scope != scope:
            scopes.append(current_scope)
    figure = receipt['figure']
    _readable(app, figure['id'], scopes, connection)
    saved_figure = app.store.get(figure['id'], figure['revision'], connection)
    proof = receipt['render'].get('provenance', {})
    require(figure.get('canonical_source_sha256') == digest(saved_figure)
            and proof.get('object_id') == saved_figure['id'] and proof.get('revision') == saved_figure['revision']
            and proof.get('source_sha256') == digest(saved_figure), '采用回执来源不符', 'integrity', 409)
    sources = [saved_figure]
    manuscript = receipt.get('manuscript')
    if manuscript is not None:
        _readable(app, manuscript['id'], scopes, connection)
        saved_manuscript = app.store.get(manuscript['id'], manuscript['revision'], connection)
        require(digest(manuscript) == digest(saved_manuscript), '采用回执稿件快照不符', 'integrity', 409)
        app.store.assert_source_access(connection, saved_manuscript['project_id'], saved_figure['id'])
        sources.append(saved_manuscript)
    engine = ArtifactEngine(app.store, app.config.get('rendering', {}))
    # Check the actual source relationships too, even for an owner who can read
    # both projects separately. Revoked sharing cannot be bypassed via proof.
    for reference in engine._declared_references(saved_figure):
        ident = reference.get('id') or reference.get('object_id')
        if ident:
            _readable(app, ident, scopes, connection)
            app.store.assert_source_access(connection, saved_figure['project_id'], ident)
            engine._reference(saved_figure, reference)
    checked = set()
    for source in sources:
        declared = {sha for _,sha in engine._asset_refs(source, strict=False)}
        if source['id'] == saved_figure['id']:
            declared.update(sha for _,sha in engine._asset_refs(receipt['render'], strict=False))
        for sha in sorted(declared):
            engine._asset_bytes(sha, owner=source)
            if sha not in checked:
                for current_scope in scopes:
                    app.asset(sha, current_scope)
                checked.add(sha)
    return receipt


def read_receipt(app, data, scope, principal=None):
    require(isinstance(data, dict) and set(data) == {'action','id','request_key'}
            and data.get('action') == RECEIPT_ACTION and isinstance(data.get('id'), str),
            '核对采用回执仅接受图形身份与请求标识', 'invalid_visual_receipt', 422)
    key = data.get('request_key')
    require(isinstance(key, str) and key.strip() and len(key) <= 180, '需要原采用请求标识', 'invalid_visual_receipt', 422)
    scopes = [scope]
    if principal is not None:
        from research_partner.domains.workspace.management import authority_scope
        scopes.append(authority_scope(app, principal))
    with app.store.read_snapshot() as connection:
        figure = _readable(app, data['id'], scopes, connection)
        require(figure['kind'] == 'figure', '需要图形成果', 'invalid_visual_receipt', 422)
        row = connection.execute('SELECT value FROM kv WHERE key=?', (KEY + data['id'] + ':' + key,)).fetchone()
        if row is None:
            return {'status':'not_committed','id':data['id'],'request_key':key}
        return _receipt_access(app, json.loads(row[0])['receipt'], scope, principal, connection)


def _retain_failure(store, data, source, staged, phase, error, committed=False):
    """Keep private, unregistered staged evidence; never create an export record."""
    ident = uid('VISUAL-FAIL')
    folder = store.workspace / 'figure-commit-failures' / ident
    record = {'id':ident,'at':now(),'object_id':source['id'],'base_revision':source['revision'],
              'request_key':data['request_key'],'phase':phase,'code':getattr(error,'code','visual_commit_failed'),
              'message':str(error),'candidate_source_sha256':digest(staged.candidate),'committed':committed,'assets':[]}
    try:
        folder.mkdir(parents=True, mode=0o700)
        for payload, asset in staged.pending:
            filename = asset['sha']
            if not (folder / filename).exists():
                with os.fdopen(os.open(folder / filename, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'wb') as stream:
                    stream.write(payload)
            record['assets'].append({key:asset[key] for key in ['sha','filename','media_type','size']})
        with os.fdopen(os.open(folder / 'failure.json', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), 'w') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        retained = {'failure_id':ident,'staged_evidence_retained':True,'registered':False}
    except OSError:
        retained = {'failure_id':ident,'staged_evidence_retained':False,'registered':False}
    try:
        with store.transaction() as connection:
            store.event(connection, 'figure.visual.commit.failed', source['id'], {**retained,'phase':phase,'code':record['code'],'request_key':data['request_key']})
    except Exception:
        pass  # Never mask the original conflict or renderer failure.
    if isinstance(error, Problem):
        error.details = {**error.details, **retained, 'phase':phase, 'committed':committed}


def dispatch(app, data, scope, principal=None):
    if isinstance(data, dict) and data.get('action') == RECEIPT_ACTION:
        return read_receipt(app, data, scope, principal)
    layers, target = _validate(data)
    store = app.store
    source = _writable(app, data['id'], scope, principal)
    require(source['kind'] == 'figure' and not source['content'].get('composition')
            and source['content'].get('editable_source_available') is not False,
            '需要真实可编辑来源的独立图形', 'missing_source', 422)
    if target is not None:
        _writable(app, target['id'], scope, principal)
    fingerprint = digest({'request':data,'scope':sorted(scope) if scope is not None else None,'principal':principal})
    storage_key = KEY + source['id'] + ':' + data['request_key']
    with store.read_snapshot() as reader:
        previous = _previous(reader, storage_key, fingerprint)
        if previous is not None:
            return _receipt_access(app, previous, scope, principal, reader)
    require(source['revision'] == data['expected_revision'], '图形已变化；本次尚未采用', 'conflict', 409)
    manuscript, original_ref = _occurrence(app, target, source, scope, principal)
    candidate = {**copy.deepcopy(source), 'revision':source['revision'] + 1, 'updated_at':now(),
                 'content':{**copy.deepcopy(source['content']), 'overlays':layers}}
    if 'caption' in data:
        candidate['content']['caption'] = data['caption']
    if 'title' in data:
        candidate['title'] = data['title'].strip()
        if candidate['title'] != source['title']:
            # Match Store.save's existing rename normalization before rendering.
            candidate['metadata']['aliases'] = list(dict.fromkeys(source['metadata'].get('aliases', []) + [source['title']]))
    source_sha = digest(source)
    candidate_sha = digest(candidate)
    script = source['content'].get('script_asset') or source['content'].get('script')
    grant = store.setting('code_grant:' + source['id'], {})
    authorized = bool(script and grant.get('script_sha') == source['content'].get('script_asset'))
    require(not script or authorized, '视觉采用运行已登记脚本仍需明确授权', 'authorization_required', 403)
    staged = _CandidateAssets(store, candidate)
    engine = ArtifactEngine(staged, app.config.get('rendering', {}))
    phase = 'render'
    try:
        result = engine.render_figure(candidate, authorized_code=authorized)
        require(result.get('provenance', {}).get('source_sha256') == candidate_sha
                and result['provenance'].get('numeric_preserved') is True,
                '视觉采用未通过候选来源与数值核验', 'integrity', 409)
        require(not result.get('replay', {}).get('failures'), '部分覆盖不能重放；两端均未采用', 'preview_replay_failed', 422,
                {'replay':result.get('replay', {})})
        phase = 'recheck'
        with store.transaction() as connection:
            # A concurrent duplicate may have committed while this renderer ran.
            _writable(app, source['id'], scope, principal, connection)
            if target is not None:
                _writable(app, target['id'], scope, principal, connection)
            previous = _previous(connection, storage_key, fingerprint)
            if previous is not None:
                return _receipt_access(app, previous, scope, principal, connection)
            _recheck(app, source, source_sha, script, scope, engine, principal)
            current = store.get(source['id'], connection=connection)
            require(digest(current) == source_sha, '图形在渲染期间已改变；未采用', 'conflict', 409)
            current_manuscript, current_ref = _occurrence(app, target, source, scope, principal, connection)
            require(current_ref == original_ref, '稿内引用已变化；未采用', 'conflict', 409)
            baseline = _baseline(app, source, source_sha, result)
            phase = 'commit'
            saved = store.save(source['id'], source['revision'], content=candidate['content'], title=candidate['title'], metadata=candidate['metadata'], merge=False,
                               reason='explicit visual adoption', connection=connection, prepared_updated_at=candidate['updated_at'])
            require(digest(saved) == candidate_sha, '保存快照与实际渲染候选不一致；采用已回滚', 'integrity', 409)
            registered = {}
            for payload, asset in staged.pending:
                registered[asset['sha']] = store.add_asset(payload, asset['filename'], asset['media_type'], asset['metadata'], connection=connection)
            result['assets'] = {name:registered[asset['sha']] for name,asset in result['assets'].items()}
            result['asset'] = registered[result['asset']['sha']]
            exported = store.record_export(saved['id'], saved['revision'], result, connection=connection)
            occurrence = None
            adopted_manuscript = None
            if target is not None:
                content = copy.deepcopy(current_manuscript['content'])
                ref = content['components'][target['component_index']]
                ref['revision'] = saved['revision']
                if 'sha256' in ref:
                    ref['sha256'] = candidate_sha
                adopted_manuscript = store.save(current_manuscript['id'], current_manuscript['revision'], content=content,
                                                merge=False, reason='adopt one visual figure occurrence', connection=connection)
                occurrence = {'manuscript_id':adopted_manuscript['id'],'index':target['component_index'],
                              'component_id':saved['id'],'before_revision':original_ref['revision'],'after_revision':saved['revision'],
                              'before':original_ref,'after':copy.deepcopy(ref),'ref_sha256':digest(ref)}
            figure = {**saved,'metadata':{**saved['metadata'],'last_export':result,'exported_revision':saved['revision']},
                      'exports':[exported],'review_records':[],'canonical_source_sha256':candidate_sha}
            receipt = {'status':'committed','request_key':data['request_key'],'figure':figure,'render':result,
                       'manuscript':adopted_manuscript,'occurrence':occurrence,'numeric_baseline':baseline,
                       'changed':{'figure':True,'manuscript':adopted_manuscript is not None}}
            connection.execute('INSERT INTO kv VALUES(?,?)', (storage_key, encoded({'fingerprint':fingerprint,'receipt':receipt})))
            store.event(connection, 'figure.visual.committed', saved['id'], {'request_key':data['request_key'],
                        'revision':saved['revision'],'source_sha256':candidate_sha,'manuscript_id':adopted_manuscript['id'] if adopted_manuscript else None,
                        'component_index':target['component_index'] if target else None})
        return receipt
    except Exception as error:
        # A failure in post-commit file mirroring must not misreport a durable
        # two-object commit as rolled back. The receipt is part of that commit.
        committed = False
        try:
            with store.connect() as reader:
                durable = _previous(reader, storage_key, fingerprint)
        except Exception:
            durable = None
            committed = None
        if durable is not None:
            try:
                _writable(app, source['id'], scope, principal)
                if target is not None:
                    _writable(app, target['id'], scope, principal)
                with store.read_snapshot() as reader:
                    _receipt_access(app, durable, scope, principal, reader)
            except Problem as access_error:
                access_error.details = {**access_error.details,'committed':True,'request_key':data['request_key']}
                raise access_error from error
            return {**durable,'post_commit_warning':{'code':'post_commit_processing_failed',
                    'message':str(error),'committed':True}}
        _retain_failure(store, data, source, staged, phase, error, committed)
        raise
