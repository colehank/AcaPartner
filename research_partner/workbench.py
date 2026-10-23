"""Explicit organization, version-pinned assembly and finite source handoff.

No inference, task submission, renderer, archive extraction or external IO.
Scientific modules keep their identities; assembly creates an editable draft.
"""
from __future__ import annotations

import copy
import io
import json
import posixpath
import re
import zipfile
from pathlib import PurePosixPath

from .artifacts import ArtifactEngine, document_markdown
from .document_sources import asset_declarations, image_references
from .evidence_neutral import project as scientific_content
from .portable_markdown import rewrite_images
from .store import Problem, digest, encoded, now, require, uid

SECTIONS = ('manuscript', 'literature', 'methods', 'results', 'figures', 'drafts')
OUTPUT_KINDS = frozenset({'paper', 'report', 'note', 'figure', 'diagram', 'poster', 'slides', 'literature'})
MAX_MODULES = 64
MAX_PROJECT_ROOTS = 128
MAX_NODES = 128
MAX_FILES = 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
KEY = 'workbench38:'


def section(obj):
    saved = obj.get('metadata', {}).get('workbench', {}).get('section')
    if saved in SECTIONS:
        return saved
    if obj['kind'] in {'paper', 'poster', 'slides'}:
        return 'manuscript'
    if obj['kind'] in {'figure', 'diagram'}:
        return 'figures'
    return 'literature' if obj['kind'] == 'literature' else 'drafts'


def _text(value, label, limit=300):
    require(isinstance(value, str) and value.strip() and len(value) <= limit, label)
    return value.strip()


def _revision(value):
    require(type(value) is int and value > 0, '请选择明确的成果修订', 'version_required', 409)
    return value


def _read(app, ident, scope, c, revision=None, recipient=None):
    current = app.access(app.store.get(ident, connection=c), scope)
    if recipient is not None:
        app.store.assert_source_access(c, recipient, ident)
    source = app.store.get(ident, _revision(revision), c) if revision is not None else current
    require(source['kind'] == current['kind'] and source.get('project_id') == current.get('project_id'),
            '历史来源的身份或项目归属不一致', 'integrity', 409)
    return source


def _project(app, ident, scope, c, *, write=False):
    obj = _read(app, ident, scope, c)
    require(obj['kind'] == 'project', '需要所属项目')
    require(not write or scope is None or ident in scope, '共享项目不授予写入权限', 'forbidden', 403)
    require(not write or not obj['archived'], '请先恢复已归档项目', 'archived', 409)
    return obj


def _ref(obj):
    return {'id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj)}


def _references(engine, obj):
    """Reuse registered component/source grammar; include explicit text origins."""
    refs = list(engine._declared_references(obj))
    def visit(value):
        if isinstance(value, dict):
            if isinstance(value.get('source_ref'), dict):
                refs.append(value['source_ref'])
            for field in ('method_references', 'source_references'):
                values = value.get(field, [])
                require(isinstance(values, list), '来源列表格式无效')
                refs.extend(values)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(obj['content'])
    result = []
    seen = set()
    for ref in refs:
        require(isinstance(ref, dict) and isinstance(ref.get('id', ref.get('object_id')), str),
                '来源必须登记对象与准确修订', 'component_revision_required', 409)
        ident = ref.get('id', ref.get('object_id'))
        revision = _revision(ref.get('revision'))
        key = (ident, revision, ref.get('sha256'))
        if key not in seen:
            seen.add(key)
            result.append({**ref, 'id': ident, 'revision': revision})
    return result


def _closure(app, roots, scope, c, recipient):
    engine = ArtifactEngine(app.store, app.config)
    nodes, edges, pending = {}, [], list(roots)
    while pending:
        source = pending.pop(0)
        key = source['id'] + '@' + str(source['revision'])
        if key in nodes:
            continue
        require(len(nodes) < MAX_NODES, '采用来源超过128个版本，请缩小选择', 'workbench_limit', 413)
        source = _read(app, source['id'], scope, c, source['revision'], recipient)
        require(source['kind'] in OUTPUT_KINDS, '源目录仅移交科研文图和文献；不包含任务或管理记录', 'unsupported_source', 422)
        nodes[key] = source
        for ref in _references(engine, source):
            target = _read(app, ref['id'], scope, c, ref['revision'], recipient)
            # The final recipient AND each immediate source must have access.
            app.store.assert_source_access(c, source['project_id'], target['id'])
            require(not ref.get('sha256') or ref['sha256'] == digest(target), '采用来源哈希不一致', 'integrity', 409)
            edges.append({'source': key, 'target': target['id'] + '@' + str(target['revision'])})
            pending.append(target)
    return nodes, edges


def _receipt(c, data, scope, principal):
    key = _text(data.get('request_key'), '需要稳定请求标识', 180)
    fingerprint = digest({'request': data, 'scope': None if scope is None else sorted(scope), 'principal': principal})
    row = c.execute('SELECT value FROM kv WHERE key=?', (KEY + key,)).fetchone()
    if row:
        saved = json.loads(row[0])
        require(saved['fingerprint'] == fingerprint, '同一请求标识的内容或授权不同', 'idempotency_conflict', 409)
        return key, fingerprint, saved['result']
    return key, fingerprint, None


def _commit(c, key, fingerprint, result):
    from .compatibility import require_features
    require_features(c, ['workbench_assembly_v1'])
    c.execute('INSERT INTO kv VALUES(?,?)', (KEY + key, encoded({'fingerprint': fingerprint, 'result': result})))
    return result


def _organize(app, data, scope, principal):
    assignments = data.get('assignments')
    require(isinstance(assignments, list) and 0 < len(assignments) <= MAX_MODULES, '请选择1–64份成果')
    ids = []
    for item in assignments:
        require(isinstance(item, dict) and set(item) <= {'id', 'expected_revision', 'section', 'order', 'title'}, '分类字段无效')
        ids.append(_text(item.get('id'), '成果标识无效'))
        _revision(item.get('expected_revision'))
        require(item.get('section') in SECTIONS and type(item.get('order')) is int and 0 <= item['order'] <= 100000,
                '请选择有效分类和顺序')
        if 'title' in item:
            _text(item['title'], '标题不能为空')
    require(len(ids) == len(set(ids)), '同一成果不能重复分类')
    with app.store.transaction() as c:
        project = _project(app, data.get('project_id'), scope, c, write=True)
        objects = [_read(app, ident, scope, c) for ident in ids]
        require(all(o['project_id'] == project['id'] and o['kind'] in OUTPUT_KINDS for o in objects),
                '只能组织本项目的科研成果', 'forbidden', 403)
        key, fingerprint, previous = _receipt(c, data, scope, principal)
        if previous is not None:
            return previous
        for obj, item in zip(objects, assignments):
            require(obj['revision'] == item['expected_revision'], '成果已更新，请重新读取后分类', 'conflict', 409)
        result = []
        for obj, item in zip(objects, assignments):
            metadata = copy.deepcopy(obj['metadata'])
            metadata['workbench'] = {**metadata.get('workbench', {}), 'section': item['section'], 'order': item['order']}
            result.append(app.store.save(obj['id'], obj['revision'], title=item.get('title'), metadata=metadata,
                                         merge=False, reason='explicit workbench organization', connection=c))
        return _commit(c, key, fingerprint, {'project_id': project['id'], 'objects': result})


def _module_blocks(source):
    if source['kind'] == 'paper':
        from .paper_sources import source_state
        require(source_state(source)['mode'] == 'structured',
                '此稿件没有选定结构化正文；请先明确来源后再整合', 'paper_source_required', 409)
    content, excluded = scientific_content(source['content'], source['kind'])
    blocks = content.get('blocks', [])
    require(isinstance(blocks, list), '来源段落格式无效')
    if not blocks and isinstance(content.get('markdown'), str) and content['markdown']:
        # One editable Markdown block avoids inventing an original paragraph ID.
        blocks = [{'id': None, 'kind': 'paragraph', 'text': content['markdown']}]
    require(all(isinstance(b, dict) and isinstance(b.get('text', ''), str) for b in blocks), '来源段落格式无效')
    identities = [b['id'] for b in blocks if b.get('id')]
    require(len(identities) == len(set(identities)), '来源段落身份重复', 'invalid_source', 409)
    require(blocks or source['kind'] in {'figure', 'diagram'}, '此模块没有可整合正文；不会生成只有标题的成功稿件', 'empty_module', 409)
    return content, blocks, excluded


def _validate_sources(app, sources, scope, c, recipient):
    nodes, _ = _closure(app, sources, scope, c, recipient)
    engine = ArtifactEngine(app.store, app.config)
    for source in nodes.values():
        for sha in asset_declarations(source['content']):
            _bounded_asset(app, sha, c)
            engine._asset_bytes(sha, source)


def _contribution(app, source, selection, scope, c, recipient, order):
    content, original, excluded = _module_blocks(source)
    source_ref = _ref(source)
    mapping, components, citations = {}, [], []
    heading = selection.get('heading', source['title'])
    heading_id = 'module-' + digest(source_ref)[:16] + '-heading'
    blocks = [{'id': heading_id, 'kind': 'heading', 'level': 2, 'text': heading, 'source_ref': source_ref,
               'source_block_id': None, 'assembly_role': 'module_heading'}]
    asset_declarations(content)
    destinations = {}
    for alias, asset in content.get('resources', {}).items():
        sha = ArtifactEngine._sha(asset)
        if isinstance(asset, dict) and not sha:
            sha = ArtifactEngine._sha(asset.get('url'))
        destinations[alias] = '/api/assets/' + sha
    for number, block in enumerate(original):
        new_id = 'module-' + digest([source_ref, number, block.get('id')])[:24]
        if block.get('id'):
            mapping[block['id']] = new_id
        copied = copy.deepcopy(block)
        if copied.get('source_ref'):
            copied['upstream_source_ref'] = copied['source_ref']
        copied.update(id=new_id, source_ref=source_ref, source_block_id=block.get('id'),
                      source_block_index=number, text=rewrite_images(block.get('text', ''), destinations))
        blocks.append(copied)
    after = blocks[-1]['id']
    if source['kind'] in {'figure', 'diagram'}:
        components.append({**source_ref, 'after_block_id': after, 'caption': content.get('caption', '')})
    for ref in ([] if source['kind'] in {'figure', 'diagram'} else content.get('components', [])):
        target = _read(app, ref['id'], scope, c, ref['revision'], recipient)
        anchor = ref.get('after_block_id')
        require(anchor in (None, 'start', 'end') or anchor in mapping,
                '来源图位置没有对应正文段落', 'invalid_anchor', 409)
        # Sentinels belong to the source module, never the whole new manuscript.
        mapped_anchor = heading_id if anchor == 'start' else mapping.get(anchor, after)
        components.append({**copy.deepcopy(ref), **_ref(target), 'after_block_id': mapped_anchor})
    for ref in content.get('citations', []):
        target = _read(app, ref['id'], scope, c, ref['revision'], recipient)
        require(target['kind'] == 'literature', '文献引用必须指向文献对象')
        adopted = {**copy.deepcopy(ref), **_ref(target)}
        if adopted not in citations:
            citations.append(adopted)
    assets = [{'sha': sha, 'source_object_id': source['id'], 'source_revision': source['revision']}
              for sha in sorted(asset_declarations(content))]
    for component in components:
        component['assembly_module_id'] = source['id']
    module = {**source_ref, 'heading': heading, 'heading_block_id': heading_id, 'last_block_id': after,
              'block_ids': [b['id'] for b in blocks], 'block_sha256': digest(blocks), 'order': order,
              'components': components, 'citations': citations, 'source_assets': assets}
    return blocks, module, {'source_ref': source_ref, **excluded}


def _assemble(app, data, scope, principal):
    title = _text(data.get('title'), '请输入稿件标题')
    kind = data.get('kind', 'paper')
    require(kind in {'paper', 'report'}, '整合目标须为稿件或报告')
    selections = data.get('modules')
    require(isinstance(selections, list) and 0 < len(selections) <= MAX_MODULES, '请选择1–64个独立模块')
    for item in selections:
        require(isinstance(item, dict) and set(item) <= {'id', 'revision', 'heading'}, '模块选择字段无效')
        _text(item.get('id'), '模块标识无效'); _revision(item.get('revision'))
        if 'heading' in item:
            _text(item['heading'], '小节标题不能为空')
    require(len({item['id'] for item in selections}) == len(selections), '一个独立模块只能选择一次；不能混用其多个版本')
    with app.store.transaction() as c:
        project = _project(app, data.get('project_id'), scope, c, write=True)
        sources = [_read(app, item['id'], scope, c, item['revision'], project['id']) for item in selections]
        require(all(s['kind'] in OUTPUT_KINDS - {'poster', 'slides', 'literature'} for s in sources),
                '请选择独立文稿、图或示意图；文献通过明确引用保留')
        _validate_sources(app, sources, scope, c, project['id'])
        key, fingerprint, previous = _receipt(c, data, scope, principal)
        if previous is not None:
            _read(app, previous['object']['id'], scope, c)
            return previous
        blocks, components, citations, modules, exclusions = [], [], [], [], []
        assets = []
        for index, (selection, source) in enumerate(zip(selections, sources)):
            added, module, excluded = _contribution(app, source, selection, scope, c, project['id'], index)
            blocks.extend(added); components.extend(module['components']); assets.extend(module['source_assets'])
            citations.extend(ref for ref in module['citations'] if ref not in citations)
            modules.append(module); exclusions.append(excluded)
        content = {'blocks': blocks, 'components': components, 'citations': citations,
                   'source_refs': [_ref(s) for s in sources], 'source_assets': assets,
                   'scientific_status': 'explicit_assembly_draft_not_scientific_acceptance'}
        if kind == 'paper':
            content['paper_source_mode'] = 'structured'
        require(len(encoded(content).encode()) <= 4 * 1024 * 1024, '整合正文超过4MiB，请缩小模块选择', 'workbench_limit', 413)
        obj = app.store.create(kind, title, project['id'], content,
                               {'workbench': {'section': 'manuscript', 'order': 0,
                                              'assembly': {'version': 1, 'modules': modules, 'excluded': exclusions,
                                                           'selection': 'explicit_user_selection', 'created_at': now()}},
                                'scientific_approval': False, 'user_acceptance': False}, connection=c)
        app.store.event(c, 'workbench.assembled', obj['id'], {'modules': [_ref(s) for s in sources]}, 'user')
        return _commit(c, key, fingerprint, {'object': obj, 'modules': modules, 'excluded': exclusions})


def _module_decision(app, data, scope, principal):
    """Refresh only an unedited contribution; retain is a recorded version choice."""
    _revision(data.get('expected_revision')); _revision(data.get('revision'))
    with app.store.transaction() as c:
        obj = _read(app, data.get('object_id'), scope, c)
        project = _project(app, obj['project_id'], scope, c, write=True)
        require(obj['kind'] in {'paper', 'report'}, '请选择明确整合的稿件')
        assembly = copy.deepcopy(obj['metadata'].get('workbench', {}).get('assembly', {}))
        modules = assembly.get('modules', [])
        matches = [m for m in modules if m['id'] == data.get('module_id')]
        require(assembly.get('version') == 1 and len(matches) == 1, '所选模块不属于此稿件的明确整合记录', 'not_found', 404)
        old = matches[0]
        original = _read(app, old['id'], scope, c, old['revision'], project['id'])
        target = _read(app, old['id'], scope, c, data['revision'], project['id'])
        require(digest(original) == old['sha256'], '原采用来源身份不一致', 'integrity', 409)
        _validate_sources(app, [original, target], scope, c, project['id'])
        key, fingerprint, previous = _receipt(c, data, scope, principal)
        if previous is not None:
            return previous
        require(obj['revision'] == data['expected_revision'], '稿件已更新，请重新读取；所有编辑保持不变', 'conflict', 409)
        content = copy.deepcopy(obj['content'])
        if data['action'] == 'workbench.retain_module':
            current = app.store.get(old['id'], connection=c)
            require(current['revision'] == target['revision'], '来源已再次更新，请核读后保留旧版', 'conflict', 409)
            old['decision'] = {'action': 'retain', 'observed_revision': target['revision'], 'observed_sha256': digest(target), 'at': now()}
        else:
            require(target['revision'] != original['revision'], '请选择不同的来源修订')
            baseline, baseline_module, _ = _contribution(app, original, {'heading': old['heading']}, scope, c, project['id'], old['order'])
            require(old.get('block_sha256') == digest(baseline), '整合基线记录缺失或变化', 'conflict', 409)
            ids = old['block_ids']; positions = [i for i, b in enumerate(content['blocks']) if b.get('id') in ids]
            require(positions and positions == list(range(positions[0], positions[0] + len(ids)))
                    and digest(content['blocks'][positions[0]:positions[-1] + 1]) == digest(baseline),
                    '此模块的整合段落已被编辑、移动或插入内容；保留现稿，请人工合并', 'module_edited', 409)
            require(not any(ref.get('after_block_id') in ids and ref.get('assembly_module_id') != old['id']
                            for ref in content.get('components', [])), '其他图已锚定此模块；保留现稿，请人工调整', 'module_edited', 409)
            added, replacement, excluded = _contribution(app, target, {'heading': old['heading']}, scope, c, project['id'], old['order'])
            others = [m for m in modules if m['id'] != old['id']]
            for field in ('components', 'citations', 'source_assets'):
                before = baseline_module[field]
                current = content.get(field, [])
                require(all(entry in current for entry in before), '此模块的图、引用或资产已被编辑；保留现稿', 'module_edited', 409)
                if field == 'components':
                    require([entry for entry in current if entry.get('assembly_module_id') == old['id']] == before,
                            '此模块的图位置或顺序已编辑；保留现稿', 'module_edited', 409)
                retained = [entry for entry in current if entry not in before or any(entry in m.get(field, []) for m in others)]
                insertion = next((i for i, entry in enumerate(current) if entry in before), len(retained))
                fresh = [entry for entry in replacement[field] if entry not in retained]
                content[field] = retained[:insertion] + fresh + retained[insertion:]
            content['blocks'][positions[0]:positions[-1] + 1] = added
            previous_ref = _ref(original)
            require(content.get('source_refs', []).count(previous_ref) == 1, '原来源总表已编辑；保留现稿', 'module_edited', 409)
            content['source_refs'] = [_ref(target) if ref == previous_ref else ref for ref in content['source_refs']]
            replacement['decision'] = {'action': 'refresh', 'previous_revision': old['revision'], 'at': now()}
            modules[modules.index(old)] = replacement
            assembly['excluded'] = [item for item in assembly.get('excluded', []) if item['source_ref']['id'] != old['id']] + [excluded]
        metadata = copy.deepcopy(obj['metadata'])
        metadata['workbench']['assembly'] = assembly
        require(len(encoded(content).encode()) <= 4 * 1024 * 1024, '整合正文超过4MiB', 'workbench_limit', 413)
        updated = app.store.save(obj['id'], obj['revision'], content=content, metadata=metadata, merge=False,
                                 reason='explicit ' + data['action'], connection=c)
        return _commit(c, key, fingerprint, {'object': updated, 'modules': modules,
                       'annotation_policy': 'Old revision and annotations retained; replaced block anchors are checked by Store.'})


def _roots(app, data, scope, c, *, export=False):
    require(bool(data.get('object_id')) != bool(data.get('project_id')), '请选择单份成果或一个项目')
    if data.get('object_id'):
        revision = data.get('revision')
        if export:
            _revision(revision)
        obj = _read(app, data['object_id'], scope, c, revision)
        require(obj['kind'] in OUTPUT_KINDS, '请选择科研文稿或图形')
        # A shared leaf never conveys its owner's whole project rights.
        recipient = obj['project_id'] if scope is None or obj['project_id'] in scope else None
        if recipient is None:
            recipients = sorted(set(scope) & set(app.store.get(obj['id'], connection=c)['metadata'].get('shared_with', [])))
            require(len(recipients) == 1, '共享文件需要唯一接收项目范围', 'forbidden', 403)
            recipient = recipients[0]
        return [obj], recipient
    project = _project(app, data['project_id'], scope, c)
    require(scope is None or project['id'] in scope, '单份共享成果不授予项目目录读取权', 'forbidden', 403)
    if export:
        require(project['revision'] == _revision(data.get('expected_revision')), '项目已更新，请重新读取', 'conflict', 409)
    rows = c.execute('SELECT * FROM objects WHERE project_id=? AND archived=0 ORDER BY id', (project['id'],)).fetchall()
    roots = [app.store.unpack(row) for row in rows if row['kind'] in OUTPUT_KINDS]
    require(len(roots) <= MAX_PROJECT_ROOTS, '项目超过128份文图与文献，请按稿件分别移交', 'workbench_limit', 413)
    return roots, project['id']


def _filename(value):
    name = re.sub(r'[^\w.\-]+', '_', PurePosixPath(str(value).replace('\\', '/')).name, flags=re.UNICODE)[:140]
    return name if name not in {'', '.', '..'} else 'source.bin'


def _container(info, data):
    """Do not parse or nest input archives, including renamed/embedded ZIPs."""
    suffixes = ('.zip', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.rar', '.npz', '.docx', '.pptx', '.xlsx', '.odt')
    return (info['filename'].lower().endswith(suffixes)
            or data.startswith((b'PK', b'\x1f\x8b', b'BZh', b'\xfd7zXZ', b'7z\xbc\xaf\x27\x1c', b'Rar!'))
            or data[257:262] == b'ustar' or zipfile.is_zipfile(io.BytesIO(data)))


def _bounded_asset(app, sha, c):
    require(isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{64}', sha), '资产标识不合法')
    row = c.execute('SELECT size FROM assets WHERE sha=?', (sha,)).fetchone()
    require(row is not None, '资产不存在', 'not_found', 404)
    require(0 <= row['size'] <= MAX_FILE_BYTES, '单个登记文件超过64MiB', 'workbench_limit', 413)
    try:
        size = (app.store.blobs / sha).stat().st_size
    except OSError:
        raise Problem('登记资产文件缺失', 'missing_asset', 409)
    require(size <= MAX_FILE_BYTES, '实际资产超过64MiB', 'workbench_limit', 413)
    require(size == row['size'], '登记文件大小与实际字节不一致', 'integrity', 409)
    return app.store.asset(sha, c)


def _packet(app, roots, recipient, scope, c):
    """Create concrete file bytes with registered lineage; never discover host paths."""
    nodes, edges = _closure(app, roots, scope, c, recipient)
    engine = ArtifactEngine(app.store, app.config)
    files, entries, origins, omitted, asset_paths = {}, [], [], [], {}
    total = 0
    def add(path, data, role, **extra):
        nonlocal total
        require(path not in files and not PurePosixPath(path).is_absolute() and '..' not in PurePosixPath(path).parts,
                '移交文件路径重复或越界', 'invalid_path', 409)
        require(len(data) <= MAX_FILE_BYTES and total + len(data) <= MAX_TOTAL_BYTES and len(files) < MAX_FILES,
                '源目录超出有限文件大小或数量，请缩小选择', 'workbench_limit', 413)
        total += len(data); files[path] = data
        entries.append({'path': path, 'role': role, 'size': len(data), 'sha256': digest(data), **extra})
    for node_key, source in nodes.items():
        declared = set(asset_declarations(source['content']))
        # Explicit scientific asset provenance only; never copy execution/config metadata.
        declared.update(sha for _, sha in engine._asset_refs({'source_assets': source['metadata'].get('source_assets', [])}))
        exported = set()
        records, _ = engine._matching_export_records(source)
        for record in records:
            exported.update(sha for _, sha in engine._asset_refs(record['result']))
        for sha in sorted(declared | exported):
            info = _bounded_asset(app, sha, c)
            info, payload = engine._asset_bytes(sha, source)
            if _container(info, payload):
                require(sha not in declared, '科学来源含归档容器；本源目录不递归移交，请先明确登记所需叶文件',
                        'workbench_container', 409, {'object_id': source['id'], 'sha256': sha, 'filename': info['filename']})
                omitted.append({'object': node_key, 'sha256': sha, 'reason': 'prior_export_container_not_nested'})
                continue
            engine._check_bundle_asset(info, payload)
            if sha not in asset_paths:
                path = 'assets/' + sha + '/' + _filename(info['filename'])
                asset_paths[sha] = path
                add(path, payload, 'registered_source' if sha in declared else 'registered_export',
                    download_url=info['url'], filename=info['filename'], media_type=info['media_type'], used_by=[node_key])
            else:
                next(e for e in entries if e['path'] == asset_paths[sha])['used_by'].append(node_key)
    root_keys = {r['id'] + '@' + str(r['revision']) for r in roots}
    for node_key, source in nodes.items():
        folder = ('outputs/' + section(source) if node_key in root_keys else 'evidence') + '/' + _filename(node_key)
        exclusions = []
        snapshot = {k: copy.deepcopy(source[k]) for k in ('id', 'kind', 'project_id', 'title', 'revision', 'content')}
        snapshot = engine._portable_value(snapshot, exclusions)
        add(folder + '/source.json', (json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n').encode(), 'editable_source', object_id=source['id'], revision=source['revision'])
        if source['kind'] in {'paper', 'report', 'note', 'literature'}:
            markdown = document_markdown(snapshot)
            destinations = {}
            resources = source['content'].get('resources', {})
            for target in image_references(markdown):
                descriptor = resources.get(target, target)
                if isinstance(descriptor, dict) and descriptor.get('url'):
                    descriptor = descriptor.get('sha') or descriptor.get('asset') or descriptor['url']
                sha = engine._sha(descriptor)
                require(sha in asset_paths, '文稿图像未包含在源目录', 'missing_asset', 409)
                destinations[target] = posixpath.relpath(asset_paths[sha], folder)
            markdown = rewrite_images(markdown, destinations)
            add(folder + '/manuscript.md', markdown.encode(), 'readable_source')
            if source['content'].get('latex'):
                add(folder + '/manual.tex', str(snapshot['content']['latex']).encode(), 'manual_source_not_assumed_current')
            if source['content'].get('bibtex'):
                add(folder + '/references.bib', str(snapshot['content']['bibtex']).encode(), 'references')
        history = [dict(row) for row in c.execute('SELECT revision,created_at FROM revisions WHERE object_id=? ORDER BY revision', (source['id'],))]
        add(folder + '/history.json', (encoded({'object_id': source['id'], 'adopted_revision': source['revision'],
                                              'current_revision': app.store.get(source['id'], connection=c)['revision'],
                                              'revisions': history, 'scope': 'revision index only; historical bodies not included'}) + '\n').encode(), 'history_index')
        origins.append({'key': node_key, 'source_sha256': digest(source), 'snapshot_sha256': digest(snapshot),
                        'path': folder + '/source.json', 'projection': 'scientific_content_without_object_metadata',
                        'redactions': exclusions})
    add('README.md', ('# Research source directory\n\nOpen outputs/ for selected editable sources, evidence/ for adopted exact versions, and assets/ for registered bytes. manifest.json binds the files and original object identities.\n\nThis is a bounded source handoff, not a full workspace migration. History files list revisions, not their complete contents. Source JSON omits object metadata and redacts known credential fields; original source hash and projected snapshot hash differ deliberately. No code, renderer or model ran to produce this directory. No automatic code execution or package authenticity is promised. Input archives are never nested. Previous archive exports are listed as omissions. Scientific source containers block publication.\n').encode(), 'readme')
    manifest = {'format': 'research-partner-source-directory-v1', 'roots': [_ref(r) for r in roots],
                'recipient_project': recipient, 'sources': origins, 'references': edges, 'files': copy.deepcopy(entries),
                'omissions': omitted, 'scope': 'Selected scientific sources and registered flat files. No tasks, credentials, review acceptance, full history, migration or executable replay.',
                'limits': {'max_nodes': MAX_NODES, 'max_files': MAX_FILES, 'max_file_bytes': MAX_FILE_BYTES, 'max_total_bytes': MAX_TOTAL_BYTES}}
    add('manifest.json', (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode(), 'manifest')
    return {'entries': entries, 'manifest': manifest, 'total_bytes': total, 'files': files}


def dispatch(app, data, scope, principal=None):
    """App routes workbench.* here before its generic writable-object guard."""
    require(isinstance(data, dict), '需要JSON对象')
    action = data.get('action')
    allowed = {
        'workbench.organize': {'action', 'project_id', 'assignments', 'request_key'},
        'workbench.assemble': {'action', 'project_id', 'title', 'kind', 'modules', 'request_key'},
        'workbench.refresh_module': {'action', 'object_id', 'expected_revision', 'module_id', 'revision', 'request_key'},
        'workbench.retain_module': {'action', 'object_id', 'expected_revision', 'module_id', 'revision', 'request_key'},
        'workbench.files': {'action', 'project_id', 'object_id', 'revision'},
        'workbench.export_files': {'action', 'project_id', 'object_id', 'revision', 'expected_revision', 'request_key'},
    }
    require(action in allowed and set(data) <= allowed[action], '工作台操作或字段不支持')
    if action == 'workbench.organize':
        return _organize(app, data, scope, principal)
    if action == 'workbench.assemble':
        return _assemble(app, data, scope, principal)
    if action in {'workbench.refresh_module', 'workbench.retain_module'}:
        return _module_decision(app, data, scope, principal)
    context = app.store.transaction if action == 'workbench.export_files' else app.store.read_snapshot
    with context() as c:
        roots, recipient = _roots(app, data, scope, c, export=action == 'workbench.export_files')
        packet = _packet(app, roots, recipient, scope, c)
        public = {k: v for k, v in packet.items() if k != 'files'}
        if action == 'workbench.files':
            return public
        # Revalidate all current rights and bytes even for a replayed export.
        key, fingerprint, previous = _receipt(c, data, scope, principal)
        if previous is not None:
            app.store.asset(previous['asset']['sha'], c)
            return previous
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for path, payload in packet['files'].items():
                info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100600 << 16
                archive.writestr(info, payload)
        payload = output.getvalue()
        require(len(payload) <= MAX_TOTAL_BYTES, '压缩包超过256MiB', 'workbench_limit', 413)
        # Verify the real artifact before publishing it, without executing bytes.
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            require(set(archive.namelist()) == set(packet['files']) and
                    all(digest(archive.read(entry['path'])) == entry['sha256'] for entry in packet['entries']),
                    '源目录字节校验失败', 'integrity', 409)
        asset = app.store.add_asset(payload, 'research-sources.zip', 'application/zip',
                                    {'project_id': recipient, 'role': 'workbench_source_directory'}, connection=c)
        result = {**public, 'asset': asset}
        app.store.event(c, 'workbench.files_exported', data.get('object_id') or recipient,
                        {'asset_sha256': asset['sha'], 'roots': packet['manifest']['roots']}, 'user')
        return _commit(c, key, fingerprint, result)
