"""Recoverable, readable project files backed by saved research objects.

The Store remains the revision authority. This module opens no Store write
transaction and never runs a renderer, model, scientific code or input archive.
The manifest is committed last; partial writes retain an ownership journal.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import fcntl
import json
import mimetypes
import os
import re
import tempfile
from pathlib import Path, PurePosixPath

from .artifacts import ArtifactEngine, document_markdown
from .document_sources import asset_declarations, image_references
from .evidence_neutral import project as scientific_content
from .portable_markdown import rewrite_images
from .store import Problem, digest, encoded, require

KINDS = frozenset({'paper', 'report', 'note', 'figure', 'diagram', 'poster', 'slides', 'literature', 'workshop_note'})
FOLDERS = ('manuscript', 'figures', 'code', 'configs', 'data', 'workshop', 'exports')
MAX_FILES = 2048
MAX_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MANIFEST = '.project-files.json'
JOURNAL = '.project-files-pending.json'


def _name(value, fallback='untitled'):
    result = re.sub(r'[^\w.\-]+', '-', str(value), flags=re.UNICODE).strip('.-')[:80]
    return result or fallback


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def _relative(value):
    require(isinstance(value, str) and value and '\\' not in value and '\x00' not in value,
            '项目文件路径无效', 'invalid_path', 400)
    path = PurePosixPath(value)
    require(not path.is_absolute() and all(p not in {'', '.', '..'} for p in value.split('/'))
            and not any(p.startswith('.') for p in path.parts), '项目文件路径越界或为内部登记文件', 'invalid_path', 400)
    return path


class ProjectFiles:
    def __init__(self, store):
        self.store = store
        self.base = store.workspace / 'projects'

    @staticmethod
    def sync_after_commit(store, project_ids):
        return sync_after_commit(store, project_ids)

    def _safe(self, path):
        require(path == self.base or path.is_relative_to(self.base), '项目路径越界', 'invalid_path', 409)
        for parent in [path, *path.parents]:
            if parent == self.store.workspace: break
            require(not parent.is_symlink(), '项目文件目录不得含符号链接', 'project_file_conflict', 409)
        return path

    @contextlib.contextmanager
    def _locked(self):
        self._safe(self.base).mkdir(exist_ok=True, mode=0o700)
        lock = self._safe(self.base / '.project-files.lock')
        fd = os.open(lock, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _load(self, path, default):
        self._safe(path)
        if not path.exists(): return copy.deepcopy(default)
        require(path.is_file() and path.stat().st_size <= 4 * 1024 * 1024, '项目目录登记损坏', 'project_file_conflict', 409)
        try: return json.loads(path.read_text())
        except (ValueError, UnicodeError) as error:
            raise Problem('项目目录登记不可读取；原文件保留', 'project_file_conflict', 409) from error

    def _atomic_write(self, path, data):
        self._safe(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._safe(path.parent)
        fd, temporary = tempfile.mkstemp(prefix='.rp-write-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as file:
                file.write(data); file.flush(); os.fsync(file.fileno())
            os.chmod(temporary, 0o600)
            self._safe(path)
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)

    def _root(self, project):
        index = self._load(self.base / '.project-index.json', {'version': 1, 'projects': {}})
        require(index.get('version') == 1 and isinstance(index.get('projects'), dict), '项目目录索引无效', 'project_file_conflict', 409)
        folder = index['projects'].get(project['id'])
        if folder is None:
            folder = _name(project['title']) + '--' + project['id'].split('-')[-1][:10]
            require(folder not in index['projects'].values(), '项目目录名称冲突', 'project_file_conflict', 409)
            index['projects'][project['id']] = folder
            self._atomic_write(self.base / '.project-index.json', _json(index))
        require(isinstance(folder, str) and len(PurePosixPath(folder).parts) == 1 and not folder.startswith('.')
                and '/' not in folder and '\\' not in folder, '项目目录索引越界', 'project_file_conflict', 409)
        path = self._safe(self.base / folder)
        path.mkdir(exist_ok=True, mode=0o700)
        return path

    def _project(self, project_id, connection):
        project = self.store.get(project_id, connection=connection)
        require(project['kind'] == 'project', '需要项目目录')
        return project

    def _build(self, project, previous, connection):
        rows = connection.execute('SELECT * FROM objects WHERE project_id=? AND archived=0 ORDER BY id', (project['id'],)).fetchall()
        objects = [self.store.unpack(r) for r in rows if r['kind'] in KINDS]
        require(len(objects) <= 256, '项目文件超过256份成果，请分项目整理', 'project_files_limit', 413)
        names = copy.deepcopy(previous.get('names', {})); files = {}; entries = []; size = 0; asset_paths = {}; omissions = []
        source_names = {}
        engine = ArtifactEngine(self.store)

        def stable(key, title, suffix=''):
            if key not in names:
                base = _name(title); candidate = base; index = 2
                while candidate in names.values():
                    candidate = base + '-' + str(index); index += 1
                names[key] = candidate
            value = names[key]
            require(isinstance(value, str) and len(PurePosixPath(value).parts) == 1 and not value.startswith('.')
                    and '\\' not in value, '文件名称登记无效', 'project_file_conflict', 409)
            return value + suffix

        def add(path, data, role, **origin):
            nonlocal size
            _relative(path)
            require(path not in files and len(files) < MAX_FILES and len(data) <= MAX_FILE_BYTES and size + len(data) <= MAX_BYTES,
                    '项目文件数量、大小或名称超出边界', 'project_files_limit', 413)
            files[path] = data; size += len(data)
            entries.append({'path': path, 'role': role, 'size': len(data), 'sha256': digest(data), **origin})

        def asset_path(sha, source, *, exported=False, pinned_revision=False, export_role=None, source_assets=()):
            if sha in asset_paths:
                # Rights are checked again for each declaring source.
                check_asset(sha, source)
                entry = next(e for e in entries if e['path'] == asset_paths[sha])
                reference = {'object_id': source['id'], 'revision': source['revision']}
                if reference not in entry['used_by']: entry['used_by'].append(reference)
                if exported and reference not in entry.setdefault('exported_by', []): entry['exported_by'].append(reference)
                return asset_paths[sha]
            info = check_asset(sha, source)
            filename = info['filename']; ext = Path(filename).suffix.lower()
            # Same source/file role keeps its ordinary filename on a new revision;
            # identical registered bytes are reused across all declaring objects.
            logical = ('export:' if exported else 'source:') + source['id'] + ':' + filename
            # A bundle can expose distinct files whose CAS registrations share
            # an original filename (e.g. two canvas.pdf components). Its named
            # output role is their identity; ordinary same-name exports retain
            # their existing stable key. Identical bytes are still shared above.
            if exported and export_role is not None and export_role != filename:
                logical += ':role:' + encoded(export_role)
            if pinned_revision: logical += ':r' + str(source['revision'])
            if not exported:
                # Distinct current inputs can share a CAS filename (e.g. both
                # generation nodes output filtered.csv). Keep the ordinary key
                # for its existing asset, and name only additional identities
                # separately. Do not weaken add()'s duplicate-path protection.
                separate = logical + ':asset:' + sha
                old_name = names.get(logical)
                old_asset = next((e.get('asset_sha256') for e in previous.get('entries', [])
                                  if old_name and PurePosixPath(e['path']).name in
                                  {old_name + ext, old_name + '.reference.json'}), None)
                occupied = logical in source_names and source_names[logical] != sha
                retained = old_asset in source_assets and old_asset != sha
                if separate in names or occupied or retained:
                    logical = separate
                source_names[logical] = sha
            title = Path(filename).stem
            if title in {'figure', 'diagram', 'source', 'manifest', 'numeric_values', 'plot_source'}:
                title = source['title'] + '-' + title
            ordinary_data = ext in {'.csv', '.tsv', '.parquet', '.npy', '.npz', '.h5', '.hdf5', '.mat', '.pkl', '.pickle'}
            archive = ext in {'.zip', '.tar', '.gz', '.tgz', '.bz2', '.xz', '.7z', '.rar', '.docx', '.pptx', '.xlsx'}
            # Data and opaque containers remain explicit references, never copied,
            # unpacked or claimed to be executable reproducibility packages.
            if ordinary_data or archive or info['size'] > MAX_FILE_BYTES:
                path = 'data/' + stable(logical, title, '.reference.json')
                add(path, _json({'filename': filename, 'asset': sha, 'bytes': info['size'], 'download_url': '/api/assets/' + sha,
                    'source_object_id': source['id'], 'source_revision': source['revision'],
                    'content_copied': False, 'reason': 'registered_data_or_container_reference',
                    'reproduction': 'requires authorized original data and environment; not executed'}), 'data_reference', asset_sha256=sha)
            else:
                info, raw = engine._asset_bytes(sha, source)
                require(len(raw) <= MAX_FILE_BYTES, '登记文件超过64MiB', 'project_files_limit', 413)
                # A disguised container is also reference-only, not recursively inspected.
                if raw.startswith((b'PK', b'\x1f\x8b', b'BZh', b'\xfd7zXZ', b'7z\xbc\xaf\x27\x1c', b'Rar!')) or raw[257:262] == b'ustar':
                    path = 'data/' + stable(logical, title, '.reference.json')
                    add(path, _json({'filename': filename, 'asset': sha, 'bytes': info['size'], 'content_copied': False,
                                    'reason': 'opaque_container', 'download_url': '/api/assets/' + sha}), 'data_reference', asset_sha256=sha)
                else:
                    engine._check_bundle_asset(info, raw)
                    folder = ('code' if ext in {'.py', '.r', '.jl', '.m', '.sh', '.js'} else
                              'configs' if ext in {'.json', '.toml', '.yaml', '.yml', '.mplstyle', '.ini', '.cfg', '.lock'}
                              or filename.lower() in {'requirements.txt', 'environment.yml', 'environment.yaml'} else
                              'exports' if exported else 'figures' if ext in {'.png', '.svg', '.jpg', '.jpeg', '.webp', '.pdf'} else 'manuscript')
                    path = folder + '/' + stable(logical, title, ext or '.txt')
                    add(path, raw, 'registered_export' if exported else 'registered_source', asset_sha256=sha,
                        download_url='/api/assets/' + sha, media_type=info['media_type'])
            asset_paths[sha] = path
            entry = next(e for e in entries if e['path'] == path)
            entry['used_by'] = [{'object_id': source['id'], 'revision': source['revision']}]
            if exported: entry['exported_by'] = list(entry['used_by'])
            return path

        def check_asset(sha, source):
            require(isinstance(sha, str) and re.fullmatch(r'[a-f0-9]{64}', sha), '登记文件身份无效')
            row = connection.execute('SELECT * FROM assets WHERE sha=?', (sha,)).fetchone()
            require(row is not None, '来源文件未登记', 'missing_asset', 409)
            info = self.store.unpack(row)
            owners = set(info['metadata'].get('projects', [])) | {info['metadata'].get('project_id')}
            if project['id'] not in owners:
                owner = engine._shared_asset_owner(source, sha)
                require(owner is not None and owner.get('project_id') in owners,
                        '项目无权读取此登记文件', 'forbidden', 403)
                self.store.assert_source_access(connection, project['id'], owner['id'])
            path = self.store.blobs / sha
            require(not path.is_symlink() and path.is_file() and path.stat().st_size == info['size'],
                    '登记文件缺失或大小不符', 'missing_asset', 409)
            return info

        prepared = []
        for obj in objects:
            content, excluded = scientific_content(obj['content'], obj['kind'])
            redactions = []
            content = engine._portable_value(content, redactions)
            clean = {k: obj[k] for k in ('id', 'kind', 'project_id', 'title', 'revision')}
            clean['title'] = engine._portable_value(clean['title'], redactions)
            clean['content'] = content
            prepared.append((obj, clean))
            omissions.append({'object_id': obj['id'], 'excluded': excluded, 'redactions': redactions})
            declared = set(asset_declarations(content))
            declared.update(sha for _, sha in engine._asset_refs({'source_assets': obj['metadata'].get('source_assets', [])}))
            from .figure_definition import is_definition
            if is_definition(obj):
                # Panel exporters use ordinary repeated names such as
                # figure.svg. Their declaring authority is the fixed panel,
                # not the main figure: otherwise distinct panels collide on
                # the same source:<main>:figure.svg stable-name key.
                for slot in obj['content']['slots']:
                    ref = slot.get('source')
                    if ref is None: continue
                    panel = self.store.get(ref['id'], ref['revision'], connection)
                    require(panel['kind'] == 'figure' and panel['project_id'] == project['id'] and digest(panel) == ref['sha256'],
                            '主图引用的固定子图身份不符', 'project_files_integrity', 409)
                    for key in ('svg_sha256', 'numeric_sha256'):
                        sha = ref.get(key)
                        if not sha: continue
                        path = asset_path(sha, panel, pinned_revision=True)
                        entry = next(e for e in entries if e['path'] == path)
                        reference = {'object_id': obj['id'], 'revision': obj['revision']}
                        if reference not in entry['used_by']: entry['used_by'].append(reference)
                        declared.discard(sha)
            for sha in sorted(declared): asset_path(sha, obj, source_assets=declared)
            matches, _ = engine._matching_export_records(obj)
            # Latest exact-source output for each named role. CAS filenames
            # describe the original registration, not the output's identity in
            # a compound export. Legacy unnamed refs retain filename semantics.
            exports = {}
            for record in matches:
                refs = list(engine._asset_refs(record['result']))
                named = {sha for path, sha in refs if len(path) >= 2 and path[0] == 'assets'}
                for path, sha in refs:
                    role = path[1] if len(path) >= 2 and path[0] == 'assets' else None
                    if role is None and sha in named:
                        continue  # primary asset/provenance aliases of a named output
                    row = connection.execute('SELECT filename FROM assets WHERE sha=?', (sha,)).fetchone()
                    if row and (row[0] in {'source.json', 'manifest.json', 'render_worker.py'}
                                or role in {'source.json', 'manifest.json', 'render_worker.py'}):
                        # The object/source projection above is deliberate: an
                        # export's whole object metadata is not a public source file.
                        continue
                    key = role if role is not None else (row[0] if row else None)
                    if row and key not in exports: exports[key] = (sha, role)
            for sha, role in exports.values(): asset_path(sha, obj, exported=True, export_role=role)

        def markdown(clean):
            text = document_markdown(clean); destinations = {}
            for target in image_references(text):
                descriptor = clean['content'].get('resources', {}).get(target, target)
                sha = engine._sha(descriptor)
                require(sha in asset_paths and not asset_paths[sha].endswith('.reference.json'),
                        '正文图片没有可读取的登记图像', 'missing_asset', 409)
                destinations[target] = '../' + asset_paths[sha]
            return rewrite_images(text, destinations).encode()

        for obj, clean in prepared:
            origin = {'object_id': obj['id'], 'revision': obj['revision']}
            prefix = 'workshop' if obj['kind'] == 'workshop_note' else 'figures' if obj['kind'] in {'figure', 'diagram', 'poster', 'slides'} else 'manuscript'
            stem = stable('object:' + obj['id'], clean['title'])
            add(prefix + '/' + stem + '.json', _json(clean), 'preparation_source' if obj['kind'] == 'workshop_note' else 'editable_source', **origin)
            source_mode = obj['content'].get('paper_source_mode') if obj['kind'] == 'paper' else None
            if obj['kind'] == 'paper' and obj['content'].get('docx_asset'):
                sha = obj['content']['docx_asset']
                check_asset(sha, obj)
                self.store.asset(sha, connection)
                add(prefix + '/' + stem + '.docx', (self.store.blobs / sha).read_bytes(),
                    'native_manuscript' if source_mode == 'docx' else 'retained_manuscript',
                    source_format='docx', asset_sha256=sha, download_url='/api/assets/' + sha, **origin)
            if obj['kind'] == 'paper' and obj['content'].get('univer_snapshot'):
                add(prefix + '/' + stem + '.univer.json', _json(obj['content']['univer_snapshot']),
                    'native_manuscript' if source_mode == 'univer' else 'retained_manuscript', source_format='univer', **origin)
            if obj['kind'] == 'paper' and obj['content'].get('latex', '').strip():
                add(prefix + '/' + stem + '.tex', obj['content']['latex'].encode(),
                    'native_manuscript' if source_mode == 'latex' else 'retained_manuscript', source_format='latex', **origin)
            if source_mode in {'docx', 'latex', 'univer'}:
                continue
            if 'manuscript_format' in obj.get('metadata', {}):
                from .manuscript_format40 import format_for
                add('configs/' + stem + '.layout.json', _json({'format': format_for(obj), 'object_id': obj['id'],
                    'revision': obj['revision'], 'renderer': 'xelatex', 'source_of_truth': 'saved object metadata',
                    'external_changes': 'preserved as conflicts; explicitly save/import through manuscript.format.save'}),
                    'manuscript_layout', **origin)
            if obj['kind'] in {'paper', 'report', 'note', 'literature', 'workshop_note'}:
                add(prefix + '/' + stem + '.md', markdown(clean), 'preparation_note' if obj['kind'] == 'workshop_note' else 'manuscript', **origin)
            if obj['kind'] in {'paper', 'report'}:
                from .article_workspace import sections
                declared_sections = sections(obj)
                blocks = clean['content'].get('blocks', [])
                for section in declared_sections:
                    if not section['anchor_valid']: continue
                    start = next(i for i, b in enumerate(blocks) if b.get('id') == section['heading_block_id'])
                    following = {s['heading_block_id'] for s in declared_sections}
                    end = next((i for i in range(start + 1, len(blocks)) if blocks[i].get('id') in following), len(blocks))
                    chapter = {**clean, 'title': section['title'], 'content': {**clean['content'], 'blocks': blocks[start + 1:end]}}
                    path = 'manuscript/' + stable('section:' + obj['id'] + ':' + section['id'], section['title'], '.md')
                    add(path, markdown(chapter), 'chapter', section_id=section['id'], **origin)
                add('manuscript/' + stem + '.references.json', _json({'citations': clean['content'].get('citations', []),
                    'source_refs': clean['content'].get('source_refs', [])}), 'references', **origin)
        add('README.md', ('# ' + project['title'] + '\n\nThis directory contains saved scholarly sources and explicitly separate preparation notes.\n'
            'manuscript/: prose, chapters, references; figures/: registered figures and figure source; code/: shared registered scripts; '
            'configs/: registered configuration; data/: authorized source references (raw data are not copied); workshop/: internal section notes; exports/: actual registered exports.\n\n'
            'The application keeps object revisions in SQLite. These files use stable names across revisions. External file edits are preserved as conflicts and must be explicitly imported; they are never silently overwritten. '
            'Workshop notes are not manuscript content. Missing scientific inputs or environment prevent a claim of full reproducibility. No code or model is run when synchronizing this directory.\n').encode(), 'readme')
        # Record an actionable mapping from the saved contract, not an inferred
        # analysis pipeline. An opaque data reference is never a local input file.
        by_id = {obj['id']: obj for obj, _ in prepared}
        source_paths = {e['object_id']: e['path'] for e in entries if e['role'] == 'editable_source'}
        by_asset = {e['asset_sha256']: e for e in entries if e.get('asset_sha256')}

        def asset_binding(value):
            sha = engine._sha(value)
            entry = by_asset.get(sha)
            if not entry: return {'asset': sha, 'status': 'not_registered_in_project_files'}
            return {'asset': sha, 'path': entry['path'],
                    'status': 'authorized_service_reference' if entry['role'] == 'data_reference' else 'local_file',
                    'download_url': '/api/assets/' + sha,
                    'local_bytes_available': entry['role'] != 'data_reference'}

        def adopted_binding(ref):
            ident = ref.get('id') or ref.get('object_id')
            revision = ref.get('revision'); current = by_id.get(ident)
            exact = type(revision) is int and current is not None and revision == current['revision']
            return {'object_id': ident, 'adopted_revision': revision, 'sha256': ref.get('sha256'),
                    'mirrored_current_revision': current['revision'] if current else None,
                    'status': 'exact_current_source' if exact else 'adopted_revision_not_in_current_mirror',
                    'source_file': source_paths.get(ident) if exact else None}

        reproduction = []
        prose = ['# Saved source and reproduction map', '',
                 'These entries describe saved source bindings. They do not certify a scientific result or a successful rerun. '
                 'Only files marked local_file contain input bytes. Data/container references require authorized retrieval from the originating service; '
                 'relative /api/assets URLs are not offline or public download links. Retain the input alias when making a local input map. '
                 'No source script is run, adapted or granted execution permission by this directory.', '',
                 'The machine-readable mapping is configs/reproduction.json. Current source files do not substitute for an older adopted revision. '
                 'Object history and exact-version portable exports remain separate. No environment is inferred from Python imports.', '']
        for obj, clean in prepared:
            content = clean['content']
            if obj['kind'] == 'workshop_note': continue
            if obj['kind'] not in {'figure', 'diagram', 'paper', 'report', 'poster', 'slides'} and not content.get('script_asset'): continue
            inputs = content.get('input_assets', {})
            inputs = {key: asset_binding(value) for key, value in inputs.items()} if isinstance(inputs, dict) else {}
            script = asset_binding(content['script_asset']) if content.get('script_asset') else None
            adopted = [adopted_binding(ref) for key in ['components', 'source_refs', 'citations']
                       for ref in (content.get(key, []) if isinstance(content.get(key, []), list) else [])
                       if isinstance(ref, dict) and (ref.get('id') or ref.get('object_id'))]
            gaps = []
            if obj['kind'] == 'figure' and not script: gaps.append('no_registered_executable_figure_source')
            if any(not value.get('local_bytes_available') for value in inputs.values()): gaps.append('inputs_require_authorized_retrieval')
            if not content.get('environment'): gaps.append('execution_environment_not_registered')
            if not content.get('computation_path'): gaps.append('computation_path_not_registered')
            if any(r['status'] != 'exact_current_source' for r in adopted): gaps.append('adopted_versions_not_fully_mirrored')
            outputs = [{'path': e['path'], 'asset': e.get('asset_sha256'), 'role': e['role']} for e in entries
                       if {'object_id': obj['id'], 'revision': obj['revision']} in e.get('exported_by', [])]
            record = {'object_id': obj['id'], 'revision': obj['revision'], 'title': clean['title'], 'kind': obj['kind'],
                      'source_file': source_paths.get(obj['id']), 'script': script, 'input_aliases': inputs,
                      'parameters': content.get('parameters', {}), 'visual_overlays': content.get('overlays', []),
                      'environment_declaration': content.get('environment'), 'computation_path': content.get('computation_path'),
                      'declared_scientific_relations': content.get('scientific_provenance', []),
                      'adopted_sources': adopted, 'registered_current_exports': outputs, 'missing_or_external': gaps,
                      'execution_verified_by_sync': False, 'scientific_support_verified_by_sync': False}
            reproduction.append(record)
            prose.extend(['## ' + clean['title'] + ' · ' + obj['id'] + ' @' + str(obj['revision']), '',
                          '- Saved source: ' + str(record['source_file']),
                          '- Registered script: ' + (script.get('path', 'unavailable') if script else 'not registered; do not infer editability from a preview')])
            prose.extend('- Input alias `' + key + '` → `' + value.get('path', 'unavailable') + '` (' + value['status'] + ')' for key, value in inputs.items())
            prose.append('- Exact current exports: ' + (', '.join(e['path'] for e in outputs) or 'none registered for this source revision'))
            prose.append('- Recorded computation path: ' + (str(record['computation_path']) if record['computation_path'] else 'not registered'))
            prose.append('- Scientific support: ' + ('saved declarations are in configs/reproduction.json; no independent scientific validation by file sync' if record['declared_scientific_relations'] else 'not registered'))
            prose.append('- Environment: ' + ('saved declaration only; execution not verified' if record['environment_declaration'] else 'not registered; obtain and verify the applicable environment before running'))
            prose.extend('- Adopted source ' + str(r['object_id']) + ' @' + str(r['adopted_revision']) + ': ' + r['status'] for r in adopted)
            prose.extend(['- Remaining dependencies: ' + (', '.join(gaps) or 'no structural gap detected; execution and scientific support still unverified'), ''])
        add('configs/reproduction.json', _json({'format': 'research-partner-reproduction-map-v1', 'objects': reproduction,
            'execution_performed': False, 'automatic_permission': False}), 'reproduction_map')
        add('REPRODUCE.md', ('\n'.join(prose) + '\n').encode(), 'reproduction')
        add('configs/environment.json', _json({'status': 'not_verified_by_file_sync', 'dependency_installation': False,
            'source': 'Only explicitly registered environment/configuration files are copied. This file is not a lockfile or executed environment receipt.'}), 'environment_boundary')
        revisions = {obj['id']: obj['revision'] for obj in objects}
        manifest = {'format': 'research-partner-project-files-v1', 'project_id': project['id'], 'project_revision': project['revision'],
                    'object_revisions': revisions, 'names': names, 'entries': entries, 'omissions': omissions,
                    'scope': 'Saved scientific content and separately labeled preparation notes; no runtime, credentials, tasks or automatic scientific execution.'}
        return files, manifest

    def _verify_owned(self, root, old, pending, files):
        known = {}
        for record in [old, pending]:
            for entry in record.get('entries', []): known.setdefault(entry['path'], set()).add(entry['sha256'])
        conflicts = []
        for name in set(known) | set(files):
            _relative(name); path = self._safe(root / name)
            if not path.exists(): continue
            require(path.is_file() and path.stat().st_size <= MAX_FILE_BYTES, '文件被外部目录或过大内容替换', 'project_file_conflict', 409)
            actual = digest(path.read_bytes())
            accepted = known.get(name, set()) | ({digest(files[name])} if name in files else set())
            if actual not in accepted: conflicts.append(name)
        require(not conflicts, '磁盘文件已有外部编辑；数据库和文件均保留，请明确处理差异',
                'project_file_conflict', 409, {'paths': sorted(conflicts)})

    def _sync(self, project_id):
        with self._locked():
            with self.store.read_snapshot() as connection:
                project = self._project(project_id, connection)
                root = self._root(project)
                old = self._load(root / MANIFEST, {})
                pending = self._load(root / JOURNAL, {})
                require(not old or old.get('project_id') == project_id, '文件目录不属于当前项目', 'project_file_conflict', 409)
                require(not pending or pending.get('project_id') == project_id, '待恢复目录不属于当前项目', 'project_file_conflict', 409)
                files, manifest = self._build(project, old or pending, connection)
            self._verify_owned(root, old, pending, files)
            for folder in FOLDERS: self._safe(root / folder).mkdir(exist_ok=True, mode=0o700)
            self._atomic_write(root / JOURNAL, _json(manifest))
            for name, data in files.items():
                path = self._safe(root / name)
                if not path.exists() or digest(path.read_bytes()) != digest(data): self._atomic_write(path, data)
            # Remove only previously managed bytes after checking their exact ownership.
            for name in {e['path'] for e in old.get('entries', []) + pending.get('entries', [])} - set(files):
                path = self._safe(root / name)
                if path.exists(): path.unlink()
            # No new source revision can be falsely described as represented here.
            with self.store.read_snapshot() as connection:
                current = self._project(project_id, connection)
                rows = connection.execute('SELECT id,kind,revision FROM objects WHERE project_id=? AND archived=0', (project_id,)).fetchall()
                require(current['revision'] == manifest['project_revision'] and
                        {r['id']: r['revision'] for r in rows if r['kind'] in KINDS} == manifest['object_revisions'],
                        '同步期间研究对象已改变；文件等待重新核对', 'project_files_stale', 409)
            for entry in manifest['entries']:
                require(digest(self._safe(root / entry['path']).read_bytes()) == entry['sha256'], '项目文件回读校验失败', 'project_files_integrity', 409)
            self._atomic_write(root / MANIFEST, _json(manifest))
            self._safe(root / JOURNAL).unlink()
            return {'status': 'ready', 'project_id': project_id, 'root': str(root.relative_to(self.store.workspace)),
                    'entries': manifest['entries'], 'files': manifest['entries'], 'object_revisions': manifest['object_revisions'],
                    'project_revision': manifest['project_revision'], 'omissions': manifest['omissions'],
                    'directory_verified': True, 'scientific_reproduction_verified': False}

    def sync_project(self, project_id):
        """After-commit hook. Failure never claims that the saved object was undone."""
        try: return self._sync(project_id)
        except Exception as error:
            return {'status': 'repair_required', 'project_id': project_id, 'directory_verified': False,
                    'database_content_preserved': True, 'code': error.code if isinstance(error, Problem) else 'project_files_io',
                    'message': str(error) if isinstance(error, Problem) else '已保存的研究对象保留；项目文件未完整同步，请重开修复。',
                    'details': error.details if isinstance(error, Problem) else {}}

    def ensure_object(self, object_id):
        with self.store.read_snapshot() as connection:
            obj = self.store.get(object_id, connection=connection)
            project_id = obj['id'] if obj['kind'] == 'project' else obj.get('project_id')
        if not project_id or (obj['kind'] != 'project' and obj['kind'] not in KINDS): return {'status': 'not_applicable'}
        return self.sync_project(project_id)

    def read(self, project_id, path):
        """Caller must check current project ACL; only manifested files are served."""
        _relative(path)
        result = self.sync_project(project_id)
        require(result['status'] == 'ready', result.get('message', '项目文件尚未同步'), result.get('code', 'project_files_unavailable'), 409, result.get('details'))
        entry = next((e for e in result['entries'] if e['path'] == path), None)
        require(entry is not None, '项目文件未登记', 'not_found', 404)
        target = self._safe(self.store.workspace / result['root'] / path)
        require(target.is_file() and target.stat().st_size <= MAX_FILE_BYTES, '项目文件不可读取', 'project_files_integrity', 409)
        data = target.read_bytes()
        require(digest(data) == entry['sha256'], '项目文件在读取时改变；原内容保留', 'project_file_conflict', 409)
        media = entry.get('media_type') or mimetypes.guess_type(path)[0] or 'application/octet-stream'
        text = media.startswith('text/') or Path(path).suffix.lower() in {
            '.json', '.md', '.py', '.r', '.jl', '.m', '.toml', '.yaml', '.yml', '.bib', '.tex',
            '.js', '.jsx', '.mjs', '.cjs', '.ts', '.tsx', '.css', '.html', '.xml', '.sh', '.sql',
            '.ini', '.cfg', '.lock', '.txt', '.c', '.cpp', '.h', '.rs', '.go', '.ipynb'}
        try: content = data.decode('utf-8') if text else None
        except UnicodeError: content = None
        return {'project_id': project_id, 'path': path, 'revision': entry.get('revision'), 'object_id': entry.get('object_id'),
                'sha256': entry['sha256'], 'size': len(data), 'media_type': media, 'encoding': 'utf-8' if content is not None else 'base64',
                'content': content if content is not None else base64.b64encode(data).decode(), 'role': entry['role'], 'verified': True}


def sync_after_commit(store, project_ids):
    """Optional Store hook; call after its outer transaction has committed.

    Existing projects without article registration or a mirror are left alone.
    Returns explicit repair states without recursively writing Store settings.
    """
    files = ProjectFiles(store); result = {}
    for project_id in sorted(set(project_ids)):
        if not project_id: continue
        try:
            with store.read_snapshot() as connection:
                project = files._project(project_id, connection)
                registered = bool(project['metadata'].get('article')) or connection.execute(
                    "SELECT 1 FROM objects WHERE project_id=? AND kind IN ('paper','report','note') AND (json_type(metadata,'$.article')='object' OR json_type(metadata,'$.manuscript_format')='object') LIMIT 1",
                    (project_id,)).fetchone() is not None
            if not registered and files.base.exists():
                index = files._load(files.base / '.project-index.json', {'projects': {}})
                registered = project_id in index.get('projects', {})
            if registered: result[project_id] = files.sync_project(project_id)
        except Exception as error:
            result[project_id] = {'status': 'repair_required', 'project_id': project_id, 'database_content_preserved': True,
                'directory_verified': False, 'code': error.code if isinstance(error, Problem) else 'project_files_io',
                'message': str(error) if isinstance(error, Problem) else '项目文件登记未能同步；已保存内容保留。'}
    return result
