"""Freeze explicitly selected saved native Markdown for a review context.

The canonical notes reader performs its existing file/revision/index bookkeeping.
This adapter dispatches only reads: it never writes note text, changes navigation,
reads desktop draft buffers, submits a task, or asserts that an Agent read it.
"""
from __future__ import annotations

import copy
import re

from .store import Problem, digest, require, uid

MAX_NOTES = 4
MAX_UTF8_BYTES = 128 * 1024
SOURCE = 'saved_native_notes_read'
REF_FIELDS = {'id', 'relative_path', 'revision', 'content_sha256'}
FRAGMENT_FIELDS = {'start_offset', 'end_offset', 'content_sha256'}
NOTE_FIELDS = ('id', 'project_id', 'relative_path', 'revision', 'content_sha256',
               'markdown', 'encoding', 'authority_kind', 'offset_unit', 'bytes')


def note_ref(note):
    """Keep the source identity distinct from an optional selected byte range."""
    ref = {key: note[key] for key in REF_FIELDS}
    if 'fragment' in note:
        ref['fragment'] = copy.deepcopy(note['fragment'])
    return ref


def freeze_notes(app, project_id, refs, scope, principal):
    """Read current whole files or explicit historical fragments with live ACL.

    Empty refs freeze no content and do not prove project/file authorization;
    the enclosing review entry retains its normal project authorization check.
    Caller order is preserved, with no implicit note discovery or truncation.
    """
    require(isinstance(project_id, str) and 1 <= len(project_id) <= 200,
            '原生笔记上下文需要准确项目身份')
    require(isinstance(refs, list), '原生笔记引用必须为明确列表')
    require(len(refs) <= MAX_NOTES, '原生笔记上下文最多选择4篇', 'context_limit', 413)
    ids, paths = set(), set()
    for ref in refs:
        require(isinstance(ref, dict) and set(ref) in
                (REF_FIELDS, REF_FIELDS | {'fragment'}),
                '原生笔记引用仅接受固定文件身份及可选fragment选区')
        require(isinstance(ref['id'], str) and 1 <= len(ref['id']) <= 200
                and isinstance(ref['relative_path'], str)
                and type(ref['revision']) is int and ref['revision'] > 0
                and isinstance(ref['content_sha256'], str)
                and re.fullmatch(r'[a-f0-9]{64}', ref['content_sha256']),
                '原生笔记引用身份、修订或字节摘要无效')
        if 'fragment' in ref:
            fragment = ref['fragment']
            require(isinstance(fragment, dict) and set(fragment) == FRAGMENT_FIELDS
                    and type(fragment['start_offset']) is int
                    and type(fragment['end_offset']) is int
                    and 0 <= fragment['start_offset'] < fragment['end_offset']
                    and isinstance(fragment['content_sha256'], str)
                    and re.fullmatch(r'[a-f0-9]{64}', fragment['content_sha256']),
                    '笔记片段需要非空Unicode码点选区及选中文本的UTF-8摘要')
        require(ref['id'] not in ids and ref['relative_path'] not in paths,
                '同一原生笔记身份或路径不能重复选择')
        ids.add(ref['id']); paths.add(ref['relative_path'])

    notes, total = [], 0
    for ref in refs:
        # Do not bypass live App scope/principal checks or substitute a Store
        # object, arbitrary filesystem path, or an unsaved browser buffer.
        fragment = ref.get('fragment')
        if fragment is None:
            document = app.dispatch({'action': 'notes.read', 'project_id': project_id,
                                     'request_id': uid('READ'),
                                     'payload': {'relative_path': ref['relative_path']}},
                                    scope, principal=principal)
        else:
            # This public reader checks the current project/path authority and
            # registered note/revision, not just a user-provided snapshot hash.
            document = app.dispatch({'action': 'desk.note.revision.read',
                                     'project_id': project_id,
                                     'note_id': ref['id'],
                                     **{key: ref[key] for key in
                                        ('relative_path', 'revision', 'content_sha256')}},
                                    scope, principal=principal)
        require(isinstance(document, dict) and set(NOTE_FIELDS) <= set(document)
                and document['authority_kind'] == ('file' if fragment is None else 'file_snapshot')
                and (fragment is None or document.get('read_only') is True)
                and document['encoding'] == 'utf-8'
                and document['offset_unit'] == 'unicode_code_point'
                and isinstance(document['markdown'], str),
                '笔记读取不是完整的原生文件合同', 'notes_integrity', 409)
        require(document['project_id'] == project_id
                and type(document['revision']) is int
                and all(document[key] == ref[key] for key in REF_FIELDS),
                '所选原生笔记身份、路径、修订或摘要已变化；未冻结新内容',
                'source_mismatch', 409)
        try:
            raw = document['markdown'].encode('utf-8')
        except UnicodeError as error:
            raise Problem('笔记读取正文不能按UTF-8还原', 'notes_encoding', 409) from error
        require(type(document['bytes']) is int and document['bytes'] == len(raw)
                and digest(raw) == document['content_sha256'],
                '笔记正文实际字节与固定摘要或长度不一致', 'notes_integrity', 409)
        selected = {key: document[key] for key in NOTE_FIELDS}
        if fragment is not None:
            require(fragment['end_offset'] <= len(document['markdown']),
                    '笔记片段选区超出固定原文', 'source_mismatch', 409)
            text = document['markdown'][fragment['start_offset']:fragment['end_offset']]
            selected_raw = text.encode('utf-8')
            require(digest(selected_raw) == fragment['content_sha256'],
                    '笔记片段与固定选区摘要不同；未扩大为整篇', 'source_mismatch', 409)
            selected.update(markdown=text, bytes=len(selected_raw), source_bytes=len(raw),
                            fragment=copy.deepcopy(fragment), authority_kind='file_snapshot_fragment')
        total += selected['bytes']
        require(total <= MAX_UTF8_BYTES,
                '所选原生笔记完整UTF-8内容超过128KiB；未截断或冻结', 'context_limit', 413)
        notes.append({**selected, 'source': SOURCE if fragment is None else
                      'saved_native_note_fragment', 'readonly': True})
    snapshot = {'version': 2 if any('fragment' in ref for ref in refs) else 1,
                'project_id': project_id, 'notes': notes,
                'total_utf8_bytes': total}
    return {**snapshot, 'sha256': digest(snapshot)}
