"""Versioned manuscript sources behind mature editor/renderer adapters.

Source storage reuses Store revisions. No Office parser or TeX engine lives here.
DOCX assets, historical Univer snapshots and LaTeX remain independent sources.
"""
from __future__ import annotations

import copy
import base64
import binascii
import io
import json
import os
import shutil
import stat
import uuid
import zipfile
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET

from .store import digest, encoded, require

FIELDS = {
    'document.read': {'action', 'project_id'},
    'document.save': {'action', 'project_id', 'object_id', 'expected_revision', 'request_key', 'format', 'source'},
    'document.render': {'action', 'project_id', 'object_id', 'expected_revision', 'request_key'},
    'document.checkout': {'action', 'project_id', 'object_id', 'expected_revision', 'request_key'},
    'document.commit': {'action', 'project_id', 'object_id', 'expected_revision', 'request_key', 'checkout_id'},
    'document.select': {'action', 'project_id', 'object_id', 'expected_revision', 'request_key', 'format'},
}
DOCX_MIME = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
DOCX_LIMIT = 32 * 1024 * 1024


def validate_docx(raw):
    """Bound the OPC container, without converting or rewriting its contents."""
    require(isinstance(raw, bytes) and 0 < len(raw) <= DOCX_LIMIT, 'DOCX 文件为空或超过32MiB', 'source_limit', 413)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as package:
            entries = package.infolist()
            names = [entry.filename for entry in entries]
            require(len(entries) <= 5000 and len(names) == len(set(names))
                    and sum(entry.file_size for entry in entries) <= 100 * 1024 * 1024,
                    'DOCX 压缩包过大或包含重复部件', 'invalid_docx', 422)
            for entry in entries:
                path = PurePosixPath(entry.filename)
                require(not path.is_absolute() and '..' not in path.parts and '\\' not in entry.filename
                        and not entry.flag_bits & 1 and not stat.S_ISLNK(entry.external_attr >> 16),
                        'DOCX 包含不支持的部件路径、链接或加密内容', 'invalid_docx', 422)
            require({'[Content_Types].xml', '_rels/.rels', 'word/document.xml'} <= set(names),
                    '请选择有效的 DOCX 文件', 'invalid_docx', 422)
            # Read all entries to check CRC and actual decompression bounds.
            for entry in entries:
                with package.open(entry) as stream:
                    while stream.read(1024 * 1024):
                        pass
            types = ET.fromstring(package.read('[Content_Types].xml'))
            require(any(item.get('PartName') == '/word/document.xml' and item.get('ContentType') ==
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
                        for item in types), '不支持宏文档或此 Office 格式', 'invalid_docx', 422)
    except (zipfile.BadZipFile, ET.ParseError, RuntimeError, OSError, NotImplementedError) as error:
        require(False, 'DOCX 文件已损坏或格式不受支持', 'invalid_docx', 422)
    return raw


def _docx_bytes(source):
    require(isinstance(source, dict) and set(source) <= {'base64', 'filename'}
            and isinstance(source.get('base64'), str), '需要 DOCX 文件字节')
    require(len(source['base64']) <= (DOCX_LIMIT + 2) // 3 * 4, 'DOCX 文件超过32MiB', 'source_limit', 413)
    try:
        raw = base64.b64decode(source['base64'], validate=True)
    except (ValueError, binascii.Error):
        require(False, 'DOCX 文件编码无效', 'invalid_docx', 422)
    return validate_docx(raw)


def _work_directory(app):
    path = app.store.workspace / 'document-work'
    path.mkdir(mode=0o700, exist_ok=True)
    require(stat.S_ISDIR(path.lstat().st_mode), '文稿工作目录不能是链接', 'source_unreadable', 409)
    return path, os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _working_bytes(app, checkout):
    _, directory = _work_directory(app)
    try:
        fd = os.open(checkout['id'] + '.docx', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(fd)
            require(stat.S_ISREG(before.st_mode) and before.st_size <= DOCX_LIMIT,
                    '工作副本必须是32MiB以内的普通文件', 'source_unreadable', 422)
            with os.fdopen(fd, 'rb', closefd=False) as source:
                raw = source.read(DOCX_LIMIT + 1)
            require(app.store._file_identity(before) == app.store._file_identity(os.fstat(fd)),
                    '工作副本仍在写入，请写完后重新提交', 'input_integrity', 409)
        finally:
            os.close(fd)
    except OSError:
        require(False, '工作副本不可读；不能提交链接或已删除的文件', 'source_unreadable', 422)
    finally:
        os.close(directory)
    return validate_docx(raw)


def _source(app, data, scope, principal, connection):
    project = app.access(app.store.get(data.get('project_id'), connection=connection), scope)
    require(project['kind'] == 'project' and not project['archived'], '需要未归档项目')
    require(scope is None or project['id'] in scope, '没有此项目的文稿权限', 'forbidden', 403)
    if principal is not None:
        from .project_management import authority_scope
        current_scope = authority_scope(app, principal)
        require(current_scope is None or project['id'] in current_scope, '当前身份无此项目权限', 'forbidden', 403)
    ident = project['metadata'].get('article', {}).get('primary_manuscript_id')
    require(ident, '项目尚未建立论文，请先初始化论文框架', 'manuscript_missing', 409)
    require(not data.get('object_id') or data['object_id'] == ident, '论文不属于当前项目', 'forbidden', 403)
    obj = app.access(app.store.get(ident, connection=connection), scope)
    require(obj['project_id'] == project['id'] and obj['kind'] == 'paper' and not obj['archived'],
            '当前项目的论文源无效', 'manuscript_missing', 409)
    return project, obj


def _view(app, obj, connection=None):
    from .paper_sources import source_state
    rendering = app.config.get('rendering', {})
    compiler = rendering.get('latex') or shutil.which('xelatex') or shutil.which('pdflatex')
    return {
        'id': obj['id'], 'project_id': obj['project_id'], 'revision': obj['revision'], 'title': obj['title'],
        'source_state': source_state(obj),
        'sources': {'latex': obj['content'].get('latex', ''), 'univer': obj['content'].get('univer_snapshot'),
                    'docx': app.store.asset(obj['content']['docx_asset'], connection) if obj['content'].get('docx_asset') else None},
        'structured_blocks': obj['content'].get('blocks', []),
        'render': app.store.setting('document_render:' + obj['id']),
        'adapters': {
            'docx': {'editor': 'superdoc', 'version': '2.28.0', 'file_editing': True, 'max_bytes': DOCX_LIMIT,
                     'comments': True, 'tracked_changes': True},
            'univer': {'editor': 'univer', 'snapshot_editing': True, 'docx_exchange_ready': False,
                       'reason': 'DOCX 导入导出需要配置 Univer Pro 转换后端与授权。'},
            'latex': {'editor': 'codemirror', 'preview': 'pdfjs', 'compiler_available': bool(compiler)},
        },
    }


def _request(app, data, scope, principal, connection):
    key = data.get('request_key')
    require(isinstance(key, str) and 0 < len(key) <= 180, '需要稳定请求标识')
    fingerprint = digest({'request': data, 'scope': sorted(scope) if scope is not None else None, 'principal': principal})
    name = 'document_request:' + key
    row = connection.execute('SELECT value FROM kv WHERE key=?', (name,)).fetchone()
    prior = json.loads(row[0]) if row else None
    require(not prior or prior['fingerprint'] == fingerprint, '同一请求标识的内容已改变', 'idempotency_conflict', 409)
    return name, fingerprint, prior


def dispatch(app, data, scope=None, principal=None):
    action = data.get('action')
    require(action in FIELDS and set(data) <= FIELDS[action], '文稿操作或字段不支持')
    if action == 'document.read':
        with app.store.read_snapshot() as connection:
            _, obj = _source(app, data, scope, principal, connection)
            return _view(app, obj, connection)
    if action == 'document.select':
        fmt = data.get('format')
        require(fmt in {'docx', 'latex', 'univer'}, '论文源稿格式不支持')
        with app.store.transaction() as connection:
            _, obj = _source(app, data, scope, principal, connection)
            name, fingerprint, prior = _request(app, data, scope, principal, connection)
            if prior:
                return {**_view(app, app.store.get(obj['id'], prior['revision'], connection), connection), 'replayed': True}
            require(type(data.get('expected_revision')) is int and data['expected_revision'] == obj['revision'],
                    '论文已改变，请先载入最新版本再选择源稿', 'conflict', 409)
            content = copy.deepcopy(obj['content'])
            available = {'docx': bool(content.get('docx_asset')), 'latex': bool(content.get('latex', '').strip()),
                         'univer': bool(content.get('univer_snapshot'))}
            require(available[fmt], '请先保存这份源文件，再设为论文源稿', 'source_required', 409)
            content['paper_source_mode'] = fmt
            from .compatibility import require_features
            require_features(connection, ['native_primary_source_v1'])
            from .project_management import actor
            saved = app.store.save(obj['id'], obj['revision'], content=content, connection=connection,
                                   actor=actor(principal or {'kind': 'local_operator'}), merge=False,
                                   reason='select primary manuscript file: ' + fmt)
            connection.execute('INSERT INTO kv VALUES(?,?)', (name, encoded({'fingerprint': fingerprint, 'revision': saved['revision']})))
            return _view(app, saved, connection)
    if action == 'document.checkout':
        with app.store.transaction() as connection:
            _, obj = _source(app, data, scope, principal, connection)
            name, fingerprint, prior = _request(app, data, scope, principal, connection)
            if prior:
                return prior['result']
            require(type(data.get('expected_revision')) is int and data['expected_revision'] == obj['revision'],
                    '论文已改变，请先载入最新版本', 'conflict', 409)
            sha = obj['content'].get('docx_asset')
            require(sha, '请先保存一份 DOCX 稿件', 'source_required', 409)
            app.store.asset(sha, connection)
            raw = (app.store.blobs / sha).read_bytes()
            path, directory = _work_directory(app)
            ident = uuid.uuid4().hex
            try:
                fd = os.open(ident + '.docx', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                with os.fdopen(fd, 'wb') as output:
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
            finally:
                os.close(directory)
            result = {'id': ident, 'path': str(path / (ident + '.docx')), 'object_id': obj['id'],
                      'project_id': obj['project_id'], 'base_revision': obj['revision'], 'source_sha256': sha}
            connection.execute('INSERT INTO kv VALUES(?,?)', ('document_checkout:' + ident, encoded(result)))
            connection.execute('INSERT INTO kv VALUES(?,?)', (name, encoded({'fingerprint': fingerprint, 'result': result})))
            return result
    if action in {'document.save', 'document.commit'}:
        fmt = data.get('format')
        if action == 'document.commit':
            fmt = 'docx'
        require(fmt in {'latex', 'univer', 'docx'}, '请选择 DOCX 或 LaTeX 原生源')
        source = data.get('source')
        if action == 'document.commit':
            require(isinstance(data.get('checkout_id'), str) and len(data['checkout_id']) == 32
                    and all(c in '0123456789abcdef' for c in data['checkout_id']), '工作副本标识无效')
        elif fmt == 'docx':
            source = _docx_bytes(source)
        elif fmt == 'latex':
            require(isinstance(source, str) and len(source.encode('utf-8')) <= 2 * 1024 * 1024,
                    'LaTeX 源文件无效或超过2MiB', 'source_limit', 413)
        else:
            require(isinstance(source, dict) and isinstance(source.get('body'), dict)
                    and isinstance(source['body'].get('dataStream'), str), 'Univer 文稿快照无效')
            require(len(encoded(source).encode()) <= 8 * 1024 * 1024, 'Univer 文稿超过8MiB', 'source_limit', 413)
        with app.store.transaction() as connection:
            _, obj = _source(app, data, scope, principal, connection)
            name, fingerprint, prior = _request(app, data, scope, principal, connection)
            if prior:
                return {**_view(app, app.store.get(obj['id'], prior['revision'], connection), connection), 'replayed': True}
            require(type(data.get('expected_revision')) is int and data['expected_revision'] == obj['revision'],
                    '论文已被其他窗口或工具修改；草稿保留，请先比较版本', 'conflict', 409,
                    {'current_revision': obj['revision']})
            if action == 'document.commit':
                row = connection.execute('SELECT value FROM kv WHERE key=?', ('document_checkout:' + data['checkout_id'],)).fetchone()
                checkout = json.loads(row[0]) if row else None
                require(checkout and checkout['object_id'] == obj['id'] and checkout['project_id'] == obj['project_id'],
                        '工作副本不属于当前论文', 'forbidden', 403)
                require(checkout['base_revision'] == obj['revision'],
                        '工作副本基于旧版本，文件保留；请比较后重新准备副本', 'conflict', 409)
                source = _working_bytes(app, checkout)
            if fmt == 'univer':
                require(source.get('id') == obj['id'], '文稿快照身份与当前论文不一致', 'source_identity', 409)
                require(isinstance(source.get('documentStyle'), dict), 'Univer 文稿缺少文档样式')
            content = copy.deepcopy(obj['content'])
            # Editing an independent file must not change the manuscript's binding.
            # The first native file initializes it; later changes use document.select.
            if content.get('paper_source_mode') not in {'docx', 'latex', 'univer'}:
                content['paper_source_mode'] = fmt
            if fmt == 'docx':
                asset = app.store.add_asset(source, 'manuscript.docx', DOCX_MIME,
                                           {'project_id': obj['project_id'], 'object_id': obj['id']}, connection=connection)
                content['docx_asset'] = asset['sha']
            else:
                content['latex' if fmt == 'latex' else 'univer_snapshot'] = copy.deepcopy(source)
            from .compatibility import require_features
            require_features(connection, ['native_manuscript_sources_v1', 'native_primary_source_v1']
                             + (['native_docx_files_v1'] if fmt == 'docx' else []))
            from .project_management import actor
            saved = app.store.save(obj['id'], obj['revision'], content=content, connection=connection,
                                   actor=actor(principal or {'kind': 'local_operator'}),
                                   merge=False, reason='save native manuscript source: ' + fmt)
            connection.execute('INSERT INTO kv VALUES(?,?)', (name, encoded({'fingerprint': fingerprint, 'revision': saved['revision']})))
            return _view(app, saved, connection)
    with app.store.read_snapshot() as connection:
        _, obj = _source(app, data, scope, principal, connection)
        name, fingerprint, prior = _request(app, data, scope, principal, connection)
        if prior:
            return prior['result']
        require(type(data.get('expected_revision')) is int and obj['revision'] == data['expected_revision'],
                '论文已改变，请先保存或重新读取', 'conflict', 409)
        require(bool(obj['content'].get('latex', '').strip()), '请先保存 LaTeX 源文件', 'source_required', 409)
    # Reuse the actual existing compiler, asset store and bounded process runner.
    from .artifacts import ArtifactEngine
    # Render this explicitly requested saved .tex file, even when the primary is DOCX.
    # This projection does not write or change the manuscript binding. It is not an
    # alternate PDF export of the primary: the receipt is explicitly tagged LaTeX.
    render_source = copy.deepcopy(obj)
    render_source['content']['paper_source_mode'] = 'latex'
    result = ArtifactEngine(app.store, app.config.get('rendering', {})).export(render_source, 'pdf')
    if obj['content'].get('paper_source_mode') == 'latex':
        app.store.record_export(obj['id'], obj['revision'], result)
    render = {'object_id': obj['id'], 'revision': obj['revision'], 'source_sha256': digest(obj), 'format': 'latex',
              'asset': result['asset'], 'provenance': result.get('provenance', {})}
    with app.store.transaction() as connection:
        _source(app, data, scope, principal, connection)
        row = connection.execute('SELECT value FROM kv WHERE key=?', ('document_render:' + obj['id'],)).fetchone()
        if not row or json.loads(row[0]).get('revision', 0) <= obj['revision']:
            connection.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                               ('document_render:' + obj['id'], encoded(render)))
        connection.execute('INSERT OR IGNORE INTO kv VALUES(?,?)', (name, encoded({'fingerprint': fingerprint, 'result': render})))
    return render
