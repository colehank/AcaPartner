"""Actual LaTeX source/preview; no model, installation, or source mutation."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import tempfile

from .artifacts import ArtifactEngine, MIME, run_process
from .figure_preview40 import _StagedAssets
from .store import Problem, digest, require
from .document_sequence import document_markdown


def prepare(engine, obj, work, format_config=None):
    from .manuscript_format40 import build_tex, format_for, caption_numbering
    from .manuscript_fonts40 import stage_fonts
    from .paper_sources import selected_latex
    # A selected hand-written paper remains its independently chosen source.
    if obj['kind'] == 'paper':
        manual, _ = selected_latex(obj)
        require(manual is None, '手写LaTeX是独立来源；请明确选择结构稿后使用内容修订与排版联动。',
                'manual_latex_source', 409)
    font_files = stage_fonts(work)
    materials = engine._component_materials(obj, 'png', work, paper_images=True)
    citations = engine._citation_materials(obj)
    style = format_for(obj, format_config)
    inline_assets, inline_files = {}, []
    inline_owners = [(obj, document_markdown(obj), inline_assets)]
    for item in materials:
        if item['type'] == 'text':
            source = engine.store.get(item['object_id'], item['revision'])
            item['image_assets'] = {}
            inline_owners.append((source, item.get('markdown', document_markdown(source)), item['image_assets']))
    for owner_index, (owner, markdown, mapping) in enumerate(inline_owners):
        inputs, images, infos, warnings = engine._document_images(owner, markdown, work)
        require(not warnings, 'LaTeX图片资源未完整绑定，源稿保留；不以缺图签收排版。', 'missing_image_resource', 422, {'warnings': warnings})
        for target, alias in images.items():
            source_path = Path(inputs[alias])
            require(source_path.suffix.lower() in {'.png', '.jpg', '.jpeg'}, 'LaTeX暂不支持此内嵌图片格式', 'latex_image_format', 422)
            name = f'inline-{owner_index+1}-{len(mapping)+1}{source_path.suffix}'
            (work / name).write_bytes(source_path.read_bytes())
            mapping[target] = name
            info = next(info for info in infos if info['target'] == target)
            inline_files.append({'filename': name, 'asset_sha256': info['sha'], 'owner_id': owner['id'], 'owner_revision': owner['revision'], 'target': target})
    tex = build_tex(obj, materials, citations, style, image_assets=inline_assets, portable_fonts=True)
    bib = obj['content'].get('bibtex', '')
    if obj['content'].get('bibtex_asset'):
        bib = engine._asset_bytes(obj['content']['bibtex_asset'], obj)[1].decode('utf-8')
    if citations:
        from .literature import Literature
        bib += '\n' + Literature(engine.store).bibtex(citations)
    (work / 'paper.tex').write_text(tex, encoding='utf-8')
    (work / 'references.bib').write_text(bib, encoding='utf-8')
    return {'tex': tex, 'bib': bib, 'format': style, 'materials': materials, 'inline_files': inline_files, 'font_files': font_files,
            'caption_numbering': caption_numbering(obj, materials),
            'citations': [{'object_id': item['id'], 'revision': item['revision'], 'source_sha256': digest(item)} for item in citations]}


def unresolved_reference_warnings(log):
    """Keep original wrapped warning text, including the actual citation key."""
    blocks=[];current=[]
    for line in log.splitlines():
        if re.match(r'^(?:LaTeX|Package \S+) Warning:',line):
            if current:blocks.append('\n'.join(current))
            current=[line]
        elif current:
            if not line.strip():blocks.append('\n'.join(current));current=[]
            else:current.append(line)
    if current:blocks.append('\n'.join(current))
    def unresolved(block):
        compact=re.sub(r'\s+','',block).lower()
        return 'undefined' in compact and ('reference' in compact or 'citation' in compact)
    return [block for block in blocks if unresolved(block)]


def compile_pdf(engine, work, bib):
    from .manuscript_fonts40 import missing_glyph_warnings, verify_staged_font, FONT_FILENAME
    compiler = engine.config.get('latex')
    require(compiler and (Path(compiler).is_file() or shutil.which(compiler)),
            '缺少LaTeX编译器：源稿与修订已保留，不能把HTML或Word PDF当作LaTeX结果。',
            'latex_unavailable', 503, {'needed': 'XeLaTeX with fontspec and xeCJK; project-isolated runtime requires authorization',
                                       'source_action': 'manuscript.format.source'})
    name = Path(compiler).name.lower()
    require('xelatex' in name, '此稿件包含中文字体排版，需要明确配置XeLaTeX；不自动更换或安装编译器。',
            'latex_runtime_incompatible', 503)
    if FONT_FILENAME in (work / 'paper.tex').read_text():
        verify_staged_font(work)
    env = os.environ.copy()
    env.update({'openin_any': 'p', 'openout_any': 'p', 'TEXMFOUTPUT': str(work)})
    command = [str(compiler), '-no-shell-escape', '-interaction=nonstopmode', '-halt-on-error', 'paper.tex']
    def run(argv):
        try:
            return run_process(argv, cwd=work, timeout=engine.config['timeout'], env=env)
        except Problem as error:
            log = (work / 'paper.log').read_text(errors='replace') if (work / 'paper.log').is_file() else ''
            missing = missing_glyph_warnings(log)
            if missing:
                raise Problem('LaTeX字体缺少保存字符；源稿和既有PDF保留，请修正字体或内容后重试。',
                              'latex_missing_glyphs', 422, {'log': '\n'.join(missing)[-8000:], 'process': error.details}) from error
            raise
    records = [run(command)]
    if bib.strip() and '\\bibliography{' in (work / 'paper.tex').read_text():
        bibtool = engine.config.get('bibtex') or shutil.which('bibtex', path=str(Path(compiler).parent) + os.pathsep + os.environ.get('PATH', ''))
        require(bibtool, '此稿件有BibTeX引用，但未配置bibtex；源稿保留。', 'bibtex_unavailable', 503)
        records.append(run([str(bibtool), 'paper']))
    for _ in range(2):
        records.append(run(command))
    require((work / 'paper.pdf').is_file(), 'LaTeX未生成PDF', 'latex_failed', 422)
    log = (work / 'paper.log').read_text(errors='replace')
    missing = missing_glyph_warnings(log)
    require(not missing, 'LaTeX字体缺少保存字符；源稿和既有PDF保留，请修正字体或内容后重试。',
            'latex_missing_glyphs', 422, {'log': '\n'.join(missing)[-8000:], 'processes': records})
    unresolved = unresolved_reference_warnings(log)
    require(not unresolved, 'LaTeX仍有未解决引用；保留源稿和失败记录，不签收排版。', 'latex_references', 422, {'log': '\n'.join(unresolved)[-8000:]})
    return records


def export(engine, obj, fmt, work):
    """Official export from saved styled prose, called within engine scope."""
    prepared = prepare(engine, obj, work)
    records = compile_pdf(engine, work, prepared['bib']) if fmt == 'pdf' else []
    files = [str(work / 'paper.tex'), str(work / 'references.bib')]
    files += [str(work / item['filename']) for item in prepared['materials'] if item['type'] == 'image']
    files += [str(work / item['filename']) for item in prepared['inline_files']]
    files += [str(work / item['filename']) for item in prepared['font_files']]
    if records:
        files += [str(work / 'paper.pdf'), str(work / 'paper.log')]
    return engine._publish(obj, work, {'files': files, 'warnings': [] if records else ['LaTeX源稿尚未编译；请使用真实渲染核验。'],
                                      'runtime': {'renderer': 'xelatex', 'compiler': engine.config.get('latex')}},
                           'paper.' + fmt, {'compiled': bool(records), 'renderer_kind': 'xelatex',
                                           'format_config': prepared['format'], 'latex_processes': records,
                                           'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                                           'inline_images': prepared['inline_files'],
                                           'font_files': prepared['font_files'],
                                           'caption_numbering': prepared['caption_numbering'],
                                           'components': [{k: v for k, v in item.items() if k not in {'path', 'blocks', 'markdown'}} for item in prepared['materials']],
                                           'citations': prepared['citations']})


def dispatch(app, data, scope, principal=None):
    from .manuscript_format40 import render_source, normalize_format
    from .project_management import authority_scope
    principal = principal or {'kind': 'local_operator'}
    require(scope is None or principal.get('kind') != 'local_operator', '受限排版操作需要当前身份', 'forbidden', 403)
    allowed = {'action', 'object_id', 'expected_revision', 'proposal_id', 'revision_task_id', 'candidate_sha256',
               'proposal_sha256', 'format_config'}
    require(isinstance(data, dict) and set(data) <= allowed, '排版预览字段不支持', 'invalid_format', 422)
    require(data.get('action') in {'manuscript.format.render', 'manuscript.format.source'}, '排版动作不支持')
    base = app.writable(data.get('object_id'), scope)
    app.writable(base['id'], authority_scope(app, principal))
    require(base['content'].get('paper_source_mode') not in {'latex', 'univer', 'docx'},
            '当前论文采用原生源稿，请在原生论文编辑器中渲染；保留结构稿未用于替代当前源。',
            'document_adapter_required', 409)
    projected = render_source(app, data, scope)
    obj = projected['object']
    require(obj['kind'] in {'report', 'note', 'paper', 'workshop_note'}, '需要文稿')
    if data.get('format_config') is not None:
        normalize_format(data['format_config'])
    from .generation_validity import ensure_deliverable
    ensure_deliverable(app.store,obj)
    base_sha, candidate_sha = digest(base), digest(obj)
    staged = _StagedAssets(app.store)
    engine = ArtifactEngine(staged, app.config.get('rendering', {}))
    with tempfile.TemporaryDirectory(prefix='manuscript-layout-', dir=app.store.workspace) as directory:
        work = Path(directory)
        with engine._request_scope(obj):
            prepared = prepare(engine, obj, work, data.get('format_config'))
            records = compile_pdf(engine, work, prepared['bib']) if data['action'].endswith('.render') else []
            names = ['paper.tex', 'references.bib'] + (['paper.pdf', 'paper.log'] if records else [])
            # Include native, exact adopted image bytes for offline source use.
            names += [item['filename'] for item in prepared['materials'] if item['type'] == 'image']
            names += [item['filename'] for item in prepared['inline_files']]
            names += [item['filename'] for item in prepared['font_files']]
            assets = {}
            for name in names:
                file = work / name
                assets[name] = staged.add_asset(file.read_bytes(), name, 'font/ttf' if file.suffix == '.ttf' else MIME.get(file.suffix.lstrip('.'), 'text/plain'),
                                              {'project_id': obj['project_id'], 'object_id': obj['id'], 'revision': obj['revision'], 'role': 'latex_preview'})
            # Compiler/output completion cannot override a new saved draft or proposal decision.
            with app.store.transaction() as connection:
                app.writable(base['id'], authority_scope(app, principal))
                current = app.writable(base['id'], scope)
                require(digest(current) == base_sha, '排版期间稿件已更新；旧PDF不会覆盖新编辑。', 'conflict', 409)
                latest = render_source(app, data, scope, connection=connection)
                require(digest(latest['object']) == candidate_sha, '排版期间修订候选已变化；请重新预览。', 'conflict', 409)
                for ref in obj['content'].get('components', []):
                    if isinstance(ref, dict) and ref.get('content_role') == 'preparation':
                        continue
                    engine._reference(obj, ref)
                for item in prepared['materials']:
                    if item['type'] == 'image':
                        source = app.store.get(item['object_id'], item['revision'])
                        engine._asset_bytes(item['asset_sha256'], owner=source)
                for item in prepared['inline_files']:
                    source = app.store.get(item['owner_id'], item['owner_revision'])
                    engine._asset_bytes(item['asset_sha256'], owner=source)
                ensure_deliverable(app.store,obj,connection=connection)
                registered = {}
                for payload, item in staged.pending:
                    registered[item['sha']] = app.store.add_asset(payload, item['filename'], item['media_type'], item['metadata'], connection=connection)
    assets = {name: registered[item['sha']] for name, item in assets.items()}
    provenance = {**projected['provenance'], 'object_id': obj['id'], 'base_revision': base['revision'],
                  'base_source_sha256': base_sha, 'candidate_source_sha256': candidate_sha,
                  'tex_sha256': assets['paper.tex']['sha'], 'format_config': prepared['format'], 'compiled': bool(records),
                  'renderer_kind': 'xelatex', 'latex_processes': records, 'official_export_recorded': False,
                  'saved_source_changed': False, 'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  'components': [{k: v for k, v in item.items() if k not in {'path', 'blocks', 'markdown'}} for item in prepared['materials']],
                  'citations': prepared['citations']}
    provenance['inline_images'] = prepared['inline_files']
    provenance['font_files'] = prepared['font_files']
    provenance['caption_numbering'] = prepared['caption_numbering']
    return {'status': 'generated' if records else 'source_only', 'source': prepared['tex'], 'source_asset': assets['paper.tex'],
            'asset': assets['paper.pdf'] if records else assets['paper.tex'], 'assets': assets, 'provenance': provenance,
            'warnings': prepared['caption_numbering']['warnings'] + ([] if records else ['这是实际LaTeX源稿，尚未编译；不代表渲染或排版通过。'])}
