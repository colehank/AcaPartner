"""Read a registered native-note snapshot without replacing its current file.

Project authority is checked by the workdesk dispatcher on every request. A
snapshot hash alone is never sufficient: the path, stable note identity and
revision must all belong to that project's registered history.
"""
import hashlib
import re

from research_partner.domains.workspace.notebook import _components, _decode, _outline, _read_at
from research_partner.storage.store import require


def read(app, data, project):
    required = {'action', 'project_id', 'relative_path', 'note_id',
                'revision', 'content_sha256'}
    require(set(data) == required, '读取笔记历史需要准确文件身份、修订和摘要')
    path = data['relative_path']
    _components(path)
    require(isinstance(data['note_id'], str) and data['note_id'], '笔记身份无效')
    require(type(data['revision']) is int and data['revision'] >= 1, '笔记修订无效')
    require(isinstance(data['content_sha256'], str)
            and re.fullmatch(r'[a-f0-9]{64}', data['content_sha256']), '笔记历史摘要无效')
    service = app.notebook
    with service._locked(project['id']) as session:
        # A removed/moved path cannot silently resolve to an unrelated file.
        # Reading the current file checks the same non-symlink boundary as
        # notes.read, but does not register an external edit or change caches.
        service._read_file(session, path)
        key = service._key('revision', project['id']) + ':' + hashlib.sha256(path.encode()).hexdigest()
        entry = app.store.setting(key)
        require(isinstance(entry, dict) and entry.get('note_id') == data['note_id']
                and entry.get('relative_path') == path,
                '笔记历史身份与当前路径不符，请重新读取目录', 'notes_revision_mismatch', 409)
        record = next((r for r in entry['history'] if r['revision'] == data['revision']), None)
        require(record is not None, '笔记历史修订不存在', 'not_found', 404)
        require(record['content_sha256'] == data['content_sha256'],
                '笔记历史修订与摘要不符', 'notes_revision_mismatch', 409)
        raw = _read_at(session['snapshots'], record['content_sha256'])
        require(hashlib.sha256(raw).hexdigest() == record['content_sha256'],
                '笔记历史快照摘要不符，未替换为当前正文', 'notes_integrity', 409)
        markdown = _decode(raw)
        return {'id': data['note_id'], 'project_id': project['id'], 'relative_path': path,
                'revision': record['revision'], 'content_sha256': record['content_sha256'],
                'markdown': markdown, 'encoding': 'utf-8', 'bytes': len(raw),
                'offset_unit': 'unicode_code_point', 'outline': _outline(markdown),
                'authority_kind': 'file_snapshot', 'read_only': True}
