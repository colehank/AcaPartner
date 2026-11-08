"""Saved native text → immutable research input, using existing file adapters.

No model/queue, file write, notebook reindex or second editable source. The
Store snapshot is an exact citation for one send, not the native file's head.
"""
import copy
import os
from .store import digest, require
from .notebook import _components, _open_dir, _read_at, _decode
from .project_files import ProjectFiles


def native_text(app, project, path):
    require(isinstance(path, str), '上下文文件路径需要文字')
    if path.startswith('notes/'):
        parts = _components(path)
    else:
        from .generation import FILE
        parts = path.split('/')
        require(len(parts) == 2 and parts[0] == 'scripts' and FILE.fullmatch(parts[1])
                and parts[1].endswith('.py'), '本次原生上下文支持 notes 下的 Markdown 与 scripts 下的 Python', 'unsupported_format', 422)
    files = ProjectFiles(app.store)
    with files._locked():
        root = files._root(project)
    # Read-only descriptors avoid taking the notebook's recovery/write lock
    # while a submission owns SQLite. Reuse its symlink/hardlink protection.
    fd = os.open(app.store.workspace, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in [*root.relative_to(app.store.workspace).parts, *parts[:-1]]:
            child = _open_dir(fd, part)
            os.close(fd); fd = child
        raw = _read_at(fd, parts[-1], max_bytes=45000)
    finally:
        os.close(fd)
    return {'path': path, 'sha256': digest(raw), 'text': _decode(raw), 'bytes': len(raw)}


def freeze(app, snapshot, connection):
    """Publish immutable citations atomically with the task and its grant."""
    result = copy.deepcopy(snapshot)
    for item in result['native_files']:
        project = result['project']['id']
        ident = 'CTX-' + digest([project, item['path'], item['sha256']])[:24]
        content = {'markdown': item['text']}
        metadata = {'research_role': 'material_snapshot', 'research_context_snapshot': {
            'path': item['path'], 'sha256': item['sha256'], 'bytes': item['bytes'], 'authority_kind': 'file'}}
        row = connection.execute('SELECT 1 FROM objects WHERE id=?', (ident,)).fetchone()
        if row:
            obj = app.store.get(ident, 1, connection)
            require(not app.store.get(ident, connection=connection)['archived'], '上下文快照已归档', 'conflict', 409)
        else:
            # concept is an existing Store kind and does not create a redundant
            # Markdown mirror in the user's file tree.
            obj = app.store.create('concept', item['path'], project, content, metadata,
                                   ident=ident, actor='user', connection=connection)
        require(obj['content'] == content and obj['metadata'] == metadata and obj['project_id'] == project,
                '保存文件与上下文快照身份不同', 'integrity', 409)
        ref = {'id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj)}
        result['materials'].append(ref)
        item.pop('text')
        item['source_ref'] = ref
    from .research_tasks import check_input_size
    return check_input_size(app, result, connection)
