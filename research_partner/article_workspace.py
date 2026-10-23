"""Article scaffolds and separate, section-bound preparation notes.

These actions never infer scientific prose, submit tasks, or transform old reports.
All creation is explicit or part of a new-project transaction.
"""
from __future__ import annotations

import copy
import json

from .store import digest, encoded, require, uid

FEATURE = 'article_workspace_v1'
KEY = 'article39:'
DEFAULT_SECTIONS = ('引言', '方法', '结果', '讨论', '引用')


def _revision(value):
    require(type(value) is int and value > 0, '需要已读的准确修订', 'version_required', 409)
    return value


def sections(manuscript):
    """Read authoritative section identities; a deleted heading is not retargeted."""
    values = manuscript.get('metadata', {}).get('article', {}).get('sections', [])
    require(isinstance(values, list), '文章章节登记无效', 'article_sections', 409)
    source_blocks = manuscript.get('content', {}).get('blocks', [])
    require(isinstance(source_blocks, list) and all(isinstance(b, dict) for b in source_blocks), '文章段落结构无效', 'article_sections', 409)
    identities = [b.get('id') for b in source_blocks if b.get('id')]
    require(all(isinstance(i, str) for i in identities) and len(set(identities)) == len(identities), '文章段落身份重复', 'article_sections', 409)
    blocks = {b.get('id'): b for b in source_blocks}
    seen = set(); headings = set(); result = []
    for item in values:
        require(isinstance(item, dict) and isinstance(item.get('id'), str) and item['id']
                and isinstance(item.get('heading_block_id'), str) and item['heading_block_id']
                and isinstance(item.get('title'), str) and item['id'] not in seen and item['heading_block_id'] not in headings,
                '文章章节身份重复或缺失', 'article_sections', 409)
        seen.add(item['id']); headings.add(item['heading_block_id'])
        block = blocks.get(item['heading_block_id'])
        result.append({**item, 'title': block.get('text', item['title']) if block else item['title'],
                       'anchor_valid': bool(block and block.get('kind') in {'heading', 'title'})})
    return result


def initialize_output(store, connection, project, kind='paper'):
    """Called inside the caller's creation/explicit initialization transaction.

    Returns the updated project plus its existing or newly created manuscript.
    Never chooses, converts or adopts an old report implicitly.
    """
    require(connection.in_transaction, '文章框架须与项目写入同一事务', 'article_transaction', 409)
    require(kind in {'paper', 'report'}, '框架类型须为文章或报告')
    current = store.get(project['id'], connection=connection)
    require(current['kind'] == 'project' and not current['archived'], '需要未归档项目')
    require(current['revision'] == project['revision'], '项目已经改变', 'conflict', 409)
    primary = current['metadata'].get('article', {}).get('primary_manuscript_id')
    if primary:
        manuscript = store.get(primary, connection=connection)
        require(manuscript['project_id'] == current['id'] and manuscript['kind'] in {'paper', 'report'}
                and not manuscript['archived'], '主稿登记无效；请明确修复，不会另建替代稿', 'article_primary', 409)
        return {'project': current, 'manuscript': manuscript, 'sections': sections(manuscript), 'created': False}
    from .compatibility import require_features
    require_features(connection, [FEATURE])
    structure = [{'id': uid('SECTION'), 'title': title, 'heading_block_id': uid('BLOCK')} for title in DEFAULT_SECTIONS]
    content = {'blocks': [{'id': item['heading_block_id'], 'kind': 'heading', 'level': 2, 'text': item['title']} for item in structure],
               'components': [], 'citations': []}
    if kind == 'paper': content['paper_source_mode'] = 'structured'
    manuscript = store.create(kind, current['title'] + (' · 文章工作稿' if kind == 'paper' else ' · 报告工作稿'), current['id'],
                              content, {'article': {'version': 1, 'sections': structure},
                                        'workbench': {'section': 'manuscript', 'order': 0}}, connection=connection)
    metadata = copy.deepcopy(current['metadata'])
    metadata['article'] = {**metadata.get('article', {}), 'primary_manuscript_id': manuscript['id']}
    updated = store.save(current['id'], current['revision'], metadata=metadata, merge=False,
                         reason='initialize explicit article framework', connection=connection)
    store.event(connection, 'article.initialized', current['id'], {'manuscript_id': manuscript['id'], 'kind': kind,
                'sections': structure, 'scientific_content_generated': False})
    return {'project': updated, 'manuscript': manuscript, 'sections': sections(manuscript), 'created': True}


def _project(app, ident, scope, connection, principal=None, *, write=False):
    project = app.access(app.store.get(ident, connection=connection), scope)
    require(project['kind'] == 'project', '需要所属项目')
    # A shared project/leaf is not permission to enumerate its private notes/files.
    require(scope is None or project['id'] in scope, '当前身份无此项目工作区权限', 'forbidden', 403)
    if principal is not None:
        from .project_management import authority_scope
        current = authority_scope(app, principal)
        require(current is None or project['id'] in current, '项目访问权限已改变', 'forbidden', 403)
    require(not write or not project['archived'], '归档项目只读', 'archived', 409)
    return project


def _request(connection, data, scope, principal):
    key = data.get('request_key')
    require(isinstance(key, str) and key.strip() and len(key) <= 180, '需要稳定请求标识')
    fingerprint = digest({'request': data, 'scope': sorted(scope) if scope is not None else None, 'principal': principal})
    row = connection.execute('SELECT value FROM kv WHERE key=?', (KEY + key,)).fetchone()
    previous = json.loads(row[0]) if row else None
    require(not previous or previous['fingerprint'] == fingerprint, '同一请求标识内容不同', 'idempotency_conflict', 409)
    return key, fingerprint, previous


def _commit(connection, key, fingerprint, identity):
    from .compatibility import require_features
    require_features(connection, [FEATURE])
    connection.execute('INSERT INTO kv VALUES(?,?)', (KEY + key, encoded({'fingerprint': fingerprint, **identity})))


def _view(app, project, connection):
    primary = project['metadata'].get('article', {}).get('primary_manuscript_id')
    manuscript = app.store.get(primary, connection=connection) if primary else None
    require(not manuscript or (manuscript['project_id'] == project['id'] and manuscript['kind'] in {'paper', 'report'}),
            '主稿登记不属于本项目', 'article_primary', 409)
    notes = [app.store.unpack(row) for row in connection.execute(
        "SELECT * FROM objects WHERE project_id=? AND kind='workshop_note' AND archived=0 ORDER BY id", (project['id'],))]
    return {'project': project, 'manuscript': manuscript, 'sections': sections(manuscript) if manuscript else [],
            'notes': notes, 'initialization_required': not bool(manuscript), 'legacy_outputs_preserved': True}


def dispatch(app, data, scope, principal=None):
    allowed = {
        'article.initialize': {'action', 'project_id', 'expected_revision', 'kind', 'request_key'},
        'article.organize': {'action', 'object_id', 'expected_revision', 'sections', 'request_key'},
        'article.section_note': {'action', 'manuscript_id', 'section_id', 'expected_revision', 'request_key'},
        'article.view': {'action', 'project_id'},
        'article.files': {'action', 'project_id'},
        'article.file_read': {'action', 'project_id', 'path'},
    }
    action = data.get('action')
    require(action in allowed and set(data) <= allowed[action], '文章操作或字段不支持')
    write = action in {'article.initialize', 'article.section_note', 'article.organize'}
    context = app.store.transaction if write else app.store.read_snapshot
    with context() as connection:
        manuscript = None
        if action in {'article.section_note', 'article.organize'}:
            manuscript = app.access(app.store.get(data.get('manuscript_id') if action == 'article.section_note' else data.get('object_id'), connection=connection), scope)
            require(manuscript['kind'] in {'paper', 'report'} and not manuscript['archived'], '需要未归档文章或报告')
            project_id = manuscript['project_id']
        else: project_id = data.get('project_id')
        project = _project(app, project_id, scope, connection, principal, write=write)
        if action == 'article.view': return _view(app, project, connection)
        if write:
            key, fingerprint, previous = _request(connection, data, scope, principal)
            if action == 'article.organize':
                if previous: return {'manuscript': manuscript, 'object': manuscript, 'sections': sections(manuscript), 'replayed': True}
                require(manuscript['revision'] == _revision(data.get('expected_revision')), '稿件已改变，请重新读取', 'conflict', 409)
                if manuscript['kind'] == 'paper':
                    from .paper_sources import source_state
                    require(source_state(manuscript)['mode'] == 'structured', '请先明确选择结构稿，不能给未采用正文登记章节', 'paper_source_required', 409)
                blocks = manuscript['content'].get('blocks', [])
                require(isinstance(blocks, list), '此成果没有结构化章节', 'article_sections', 409)
                headings = {b['id']: b for b in blocks if isinstance(b, dict) and isinstance(b.get('id'), str)
                            and b.get('kind') in {'heading', 'title'} and isinstance(b.get('text'), str) and b['text'].strip()}
                chosen = data.get('sections', [{'heading_block_id': ident} for ident in headings])
                require(isinstance(chosen, list) and 0 < len(chosen) <= 100 and
                        all(isinstance(s, dict) and set(s) == {'heading_block_id'} and s['heading_block_id'] in headings for s in chosen)
                        and len({s['heading_block_id'] for s in chosen}) == len(chosen), '请选择1–100个现有非空章节标题')
                existing = {s['heading_block_id']: s for s in sections(manuscript)}
                structure = [{'id': existing.get(s['heading_block_id'], {}).get('id') or uid('SECTION'),
                              'title': headings[s['heading_block_id']]['text'], 'heading_block_id': s['heading_block_id']} for s in chosen]
                metadata = copy.deepcopy(manuscript['metadata'])
                metadata['article'] = {**metadata.get('article', {}), 'version': 1, 'sections': structure}
                updated = app.store.save(manuscript['id'], manuscript['revision'], metadata=metadata, merge=False,
                                         reason='explicit existing chapter organization; prose and kind retained', connection=connection)
                _commit(connection, key, fingerprint, {'object_id': updated['id'], 'project_id': project['id']})
                return {'manuscript': updated, 'object': updated, 'sections': sections(updated)}
            if action == 'article.initialize':
                if previous: return {**_view(app, project, connection), 'created': False, 'replayed': True}
                require(project['revision'] == _revision(data.get('expected_revision')), '项目已改变，请重新读取', 'conflict', 409)
                result = initialize_output(app.store, connection, project, data.get('kind', 'paper'))
                _commit(connection, key, fingerprint, {'project_id': project['id'], 'manuscript_id': result['manuscript']['id']})
                return result
            matches = [s for s in sections(manuscript) if s['id'] == data.get('section_id')]
            require(len(matches) == 1 and matches[0]['anchor_valid'], '章节已删除或身份不符；不会重定向笔记', 'section_missing', 409)
            section = matches[0]
            rows = connection.execute("SELECT * FROM objects WHERE project_id=? AND kind='workshop_note' AND json_extract(content,'$.manuscript_id')=? AND json_extract(content,'$.section_id')=?", (project['id'], manuscript['id'], section['id'])).fetchall()
            require(len(rows) <= 1, '章节有重复笔记登记，请明确修复', 'article_note_conflict', 409)
            if previous:
                note = app.store.get(previous['note_id'], connection=connection)
                require(note['kind'] == 'workshop_note' and not note['archived'] and note['project_id'] == project['id'] and note['content'].get('manuscript_id') == manuscript['id']
                        and note['content'].get('section_id') == section['id'] and note['content'].get('section_block_id') == section['heading_block_id'],
                        '笔记关联已改变', 'article_note_conflict', 409)
                return {'note': note, 'created': False, 'replayed': True}
            require(manuscript['revision'] == _revision(data.get('expected_revision')), '稿件已改变，请重新读取章节', 'conflict', 409)
            if rows:
                note = app.store.unpack(rows[0])
                require(not note['archived'] and note['content'].get('section_block_id') == section['heading_block_id'], '章节笔记已归档或锚点改变，请明确修复', 'article_note_conflict', 409)
                created = False
            else:
                note = app.store.create('workshop_note', section['title'] + ' · 工坊笔记', project['id'],
                    {'blocks': [], 'manuscript_id': manuscript['id'], 'section_id': section['id'],
                     'section_block_id': section['heading_block_id']}, connection=connection)
                created = True
            _commit(connection, key, fingerprint, {'note_id': note['id'], 'project_id': project['id']})
            return {'note': note, 'created': created}
    # File repair writes only the managed mirror, outside any Store transaction.
    from .project_files import ProjectFiles
    files = ProjectFiles(app.store)
    if action == 'article.file_read': return files.read(project['id'], data.get('path'))
    return files.sync_project(project['id'])
