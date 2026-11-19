"""Portable document reading exports, without host-path or network resolution."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import zipfile


def rewrite_images(markdown, destinations):
    """Change only supported inline image destination spans, preserving all prose.

    Match the document renderer's bounded Markdown grammar, including nested
    emphasis; fenced/inline code and escaped image syntax remain literal.
    """
    from research_partner.rendering.worker import MD_INLINE

    def line(text):
        edits = []
        for match in MD_INLINE.finditer(text):
            if match['alt'] is not None:
                raw = match['target']
                target = re.sub(r'\\([() ])', r'\1', raw.removeprefix('<').removesuffix('>'))
                if target in destinations:
                    start, end = match.span('target')
                    edits.append((start, end, '<' + destinations[target] + '>' if raw.startswith('<') else destinations[target]))
            elif match['strong'] or match['emphasis']:
                group = 'strong_text' if match['strong'] else 'emphasis_text'
                start, end = match.span(group)
                edits.append((start, end, line(match[group])))
        for start, end, value in reversed(edits):
            text = text[:start] + value + text[end:]
        return text

    result, fence = [], None
    for text in markdown.splitlines(keepends=True):
        marker = re.match(r'^\s*(`{3,}|~{3,})', text)
        if marker:
            if fence is None: fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence): fence = None
            result.append(text)
        else:
            result.append(text if fence else line(text))
    return ''.join(result)


def resolved_markdown(engine, source, markdown, work, destination):
    from research_partner.storage.store import require
    inputs, images, records, warnings = engine._document_images(source, markdown, work)
    require(not warnings, '文稿图片不能完整移交；未生成缺图成功件', 'document_resources_incomplete', 409,
            {'object_id': source['id'], 'revision': source['revision'], 'warnings': warnings})
    targets = {}
    for record in records:
        record['portable_target'] = destination(record, Path(inputs[record['alias']]))
        targets[record['target']] = record['portable_target']
    return rewrite_images(markdown, targets), records


VERIFY_SOURCE = r'''"""Offline byte and document-resource verification; no network or installation."""
import hashlib
import json
from pathlib import Path
root = Path(__file__).resolve().parent
manifest = json.loads((root / 'document-resources.json').read_text())
def local(name):
    path = (root / name).resolve()
    if not path.is_relative_to(root): raise SystemExit('Package path escapes root')
    return path
def sha(data): return hashlib.sha256(data).hexdigest()
def canonical(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())
for name, expected in manifest['files'].items():
    path = local(name)
    if not path.is_file() or sha(path.read_bytes()) != expected:
        raise SystemExit('Missing or changed file: ' + name)
sources = {item['key']: item for item in manifest['sources']}
if len(sources) != len(manifest['sources']) or manifest['root'] not in sources:
    raise SystemExit('Missing or duplicate adopted source')
for key, item in sources.items():
    if item['snapshot'] not in manifest['files']: raise SystemExit('Unverified source snapshot')
    source = json.loads(local(item['snapshot']).read_text())
    if (key != source['id'] + '@' + str(source['revision'])
            or canonical(source) != item['snapshot_sha256']
            or (not item['redacted'] and canonical(source) != item['source_sha256'])):
        raise SystemExit('Changed adopted source identity')
assets = {item['path']: item for item in manifest['assets']}
if len(assets) != len(manifest['assets']): raise SystemExit('Duplicate image path')
for path, item in assets.items():
    if manifest['files'].get(path) != item['sha256'] or local(path).stat().st_size != item['size']:
        raise SystemExit('Missing or changed image asset')
for binding in manifest['images']:
    source = sources.get(binding['object_id'] + '@' + str(binding['revision']))
    if source is None or source['source_sha256'] != binding['object_source_sha256']:
        raise SystemExit('Missing or changed image owner')
    asset = assets.get(binding['portable_target'])
    if asset is None or asset['sha256'] != binding['sha']:
        raise SystemExit('Image target lacks its exact registered bytes')
    if binding.get('source_object_id'):
        adopted = sources.get(binding['source_object_id'] + '@' + str(binding['source_revision']))
        if adopted is None or adopted['source_sha256'] != binding['binding_source_sha256']:
            raise SystemExit('Missing or changed bound image source')
print(json.dumps({'verified_files':len(manifest['files']), 'verified_sources':len(sources),
                  'verified_images':len(assets), 'scientific_review':'not_implied',
                  'authenticity_signature':False}))
'''


def reading_markdown(engine, obj, materials, segments, work, destination, remember=lambda source: None):
    """Compose the saved reading sequence with each source's own image bindings."""
    from research_partner.storage.store import digest
    bindings, parts = [], []
    def section(source, text):
        remember(source)
        rewritten, records = resolved_markdown(engine, source, text, work, destination)
        for record in records:
            if record.get('source_object_id'):
                remember(engine.store.get(record['source_object_id'], record['source_revision']))
        bindings.extend(records)
        return rewritten
    for segment in segments:
        if segment['kind'] == 'markdown':
            parts.append(section(obj, segment['markdown']))
            continue
        material = materials[segment['index']]
        source = engine.store.get(material['object_id'], material['revision'])
        remember(source)
        if material['type'] == 'text':
            parts.append(section(source, material['markdown']))
        else:
            record = {'sha': material['asset_sha256'], 'object_id': source['id'], 'revision': source['revision'],
                      'object_source_sha256': digest(source), 'target': material['filename'], 'kind': 'image_component'}
            record['portable_target'] = destination(record, Path(material['path']))
            bindings.append(record)
            alt = str(material['title']).replace('\\', '\\\\').replace('[', r'\[').replace(']', r'\]')
            text = '![' + alt + '](' + record['portable_target'] + ')'
            if material.get('caption'): text += '\n\n' + section(source, material['caption'])
            parts.append(text)
    return '\n\n'.join(parts), bindings


def document_export(engine, obj, markdown, materials, work, fmt, *, segments=None):
    """Return plain text when image-free, otherwise an atomic reading package.

    This is a document + image delivery, not the full dependency/replay bundle.
    No previous exports, scripts, data, environment or services are collected.
    """
    from research_partner.storage.store import digest, require
    package = work / 'document-package'
    package.mkdir()
    assets, bindings, sources = {}, [], {}

    def remember(source):
        sources[source['id'] + '@' + str(source['revision'])] = source

    def destination(record, path):
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == record['sha'], '文稿图像字节发生变化', 'integrity', 409)
        name = 'assets/' + record['sha'] + path.suffix.lower()
        if name not in assets:
            engine._check_bundle_asset({'filename': path.name, 'sha': record['sha'], 'media_type': 'image/' + path.suffix[1:]}, data)
            target = package / name
            target.parent.mkdir(exist_ok=True); target.write_bytes(data)
            assets[name] = {'path': name, 'sha256': record['sha'], 'size': len(data)}
        return name

    if segments is None:
        from research_partner.domains.manuscripts.sequence import markdown_segments
        segments, _ = markdown_segments(obj, materials)
    body, bindings = reading_markdown(engine, obj, materials, segments, work, destination, remember)
    name = 'document.' + fmt
    (package / name).write_text(body, encoding='utf-8')
    provenance = {'inputs': bindings}
    if not assets:
        return {'files': [str(package / name)], 'warnings': []}, name, provenance

    source_records, omissions = [], []
    for key, source in sources.items():
        local_omissions = []
        clean = engine._portable_value(source, local_omissions)
        path = 'sources/' + digest(key) + '.json'
        target = package / path; target.parent.mkdir(exist_ok=True)
        target.write_text(json.dumps(clean, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        source_records.append({'key': key, 'source_sha256': digest(source), 'snapshot_sha256': digest(clean),
                               'snapshot': path, 'redacted': clean != source})
        omissions.extend({'object': key, **entry} for entry in local_omissions)
    (package / 'verify.py').write_text(VERIFY_SOURCE, encoding='utf-8')
    reading = 'Open document.md in a Markdown reader.' if fmt == 'md' else 'Open document.txt as plain text. Image references are literal text; associated images are in assets/.'
    (package / 'README.txt').write_text(
        'Extract the complete ZIP, preserving its folders. ' + reading + '\n'
        'document-resources.json binds each relative image to its adopted object/revision and original asset bytes.\n'
        'Optional offline integrity check: python verify.py\n'
        'The standalone document needs this assets/ directory. This reading package includes only document sources and images, '
        'not a full code/data replay environment; use the complete handoff ZIP for that purpose. '
        'Byte verification is not scientific approval or visual acceptance.\n', encoding='utf-8')
    checksums = {str(p.relative_to(package)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(package.rglob('*')) if p.is_file()}
    manifest = {'schema': 'research-partner-document/1', 'root': obj['id'] + '@' + str(obj['revision']),
                'document': name, 'format': 'markdown' if fmt == 'md' else 'plain_text',
                'sources': source_records, 'images': bindings, 'assets': list(assets.values()), 'files': checksums,
                'omissions': omissions, 'status': {'registered_images': 'complete', 'scientific_review': 'not_implied',
                                                 'source_execution_during_packaging': False}}
    (package / 'document-resources.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    archive = work / ('markdown-package.zip' if fmt == 'md' else 'text-package.zip')
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as out:
        for path in sorted(package.rglob('*')):
            if path.is_file(): out.write(path, path.relative_to(package))
    provenance['document_package'] = {'schema': manifest['schema'], 'document': name, 'format': manifest['format'],
                                      'asset_count': len(assets), 'registered_images': 'complete'}
    # Images remain obtainable separately with hash-named filenames. The ZIP is
    # the primary download; sidecar hierarchy is guaranteed only inside it.
    files = [str(archive), str(package / name), str(package / 'document-resources.json')]
    files.extend(str(package / path) for path in assets)
    return {'files': files, 'warnings': ['Source fields were excluded; inspect document-resources.json omissions.'] if omissions else []}, archive.name, provenance
