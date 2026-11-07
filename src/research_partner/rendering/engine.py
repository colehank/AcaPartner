"""Real artifact import, rendering, and export using explicitly configured runtimes.

Core imports are stdlib. Scientific/Office libraries execute in a child process;
no packages are installed and inputs are copied exclusively from registered blobs.
"""

from __future__ import annotations

from research_partner.resources import module_file
import copy
import contextvars
import contextlib
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import zipfile
import xml.etree.ElementTree as ET

from research_partner.storage.store import Problem, digest, encoded, require, uid
from research_partner.domains.manuscripts.sequence import (
    document_markdown,
    markdown_segments,
    ordered_segments,
)
from research_partner.execution.process_output import (
    DEFAULT_OUTPUT_LIMIT_BYTES,
    capture_process,
)
from research_partner.rendering.contract import (
    ProcessRecord,
    RenderContractError,
    RenderSuccess,
    validate_render_request,
    validate_render_result,
)

MIME = {
    "md": "text/markdown",
    "txt": "text/plain",
    "tex": "application/x-tex",
    "bib": "application/x-bibtex",
    "json": "application/json",
    "svg": "image/svg+xml",
    "pdf": "application/pdf",
    "png": "image/png",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "zip": "application/zip",
}


def latex_caption(value):
    """LaTeX supplies its own figure number; retain the original source caption."""
    return re.sub(
        r"^\s*(?:Figure|Fig\.|图)\s*\d+[A-Za-z]?\s*[.：:]\s*",
        "",
        str(value),
        count=1,
        flags=re.I,
    )


def run_process(
    command, *, cwd, timeout=90, env=None, output_limit_bytes=DEFAULT_OUTPUT_LIMIT_BYTES
) -> ProcessRecord:
    """输出限额由 stdout/stderr 共享，不因尾部截断重置。"""
    try:
        captured = capture_process(
            command,
            cwd=cwd,
            timeout=timeout,
            env=env,
            output_limit_bytes=output_limit_bytes,
        )
    except OSError as exc:
        raise Problem(
            str(exc), "runtime_unavailable", 503, {"command": command}
        ) from exc
    record: ProcessRecord = {
        "command": command,
        "returncode": captured.returncode,
        "elapsed_seconds": captured.elapsed_seconds,
        "stdout": captured.stdout,
        "stderr": captured.stderr,
    }
    if captured.failure == "output_limit":
        raise Problem(
            "渲染输出达到字节限额",
            "render_output_limit",
            422,
            {**record, "output_limit_bytes": output_limit_bytes},
        )
    if captured.failure == "timeout":
        raise Problem(
            "渲染进程超时",
            "render_timeout",
            504,
            {
                **record,
                "timeout": timeout,
                "stdout": captured.stdout[-8000:],
                "stderr": captured.stderr[-8000:],
            },
        )
    if captured.failure == "incomplete_output":
        raise Problem(
            "渲染进程退出后仍有后代占用输出管道",
            "render_output_incomplete",
            422,
            record,
        )
    require(captured.returncode == 0, "渲染进程失败", "render_failed", 422, record)
    return record


def markdown_blocks(text):
    blocks = []
    for part in re.split(r"\n\s*\n", text.strip()):
        if not part:
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", part)
        blocks.append(
            {
                "id": uid("BLOCK"),
                "kind": "heading" if heading else "paragraph",
                "text": heading[2] if heading else part,
                **({"level": len(heading[1])} if heading else {}),
            }
        )
    return blocks


BUNDLE_REPLAY_SOURCE = r'''"""Verify or explicitly render a registered handoff job; no installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--verify', action='store_true')
parser.add_argument('--render')
parser.add_argument('--output')
parser.add_argument('--approve-code', action='store_true')
parser.add_argument('--timeout', type=float, default=90)
args = parser.parse_args()
root = Path(__file__).resolve().parent
manifest = json.loads((root / 'manifest.json').read_text())
def local(value):
    path = (root / value).resolve()
    if not path.is_relative_to(root): raise SystemExit('Bundle reference escapes package')
    return path
for name, expected in manifest['files'].items():
    path = local(name)
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('Missing or changed file: ' + name)
reader_path = 'runtime/asset_references.py'
if reader_path not in manifest['files']:
    raise SystemExit('Missing verified dependency reader')
if 'runtime/figure_interaction.py' not in manifest['files']:
    raise SystemExit('Missing verified figure interaction helper')
if 'runtime/render_contract.py' not in manifest['files']:
    raise SystemExit('Missing verified render contract helper')
import runpy
source_assets = runpy.run_path(str(local(reader_path)))['source_assets']
def canonical(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
nodes = {item['key']: item for item in manifest['objects']}
if len(nodes) != len(manifest['objects']) or manifest['root'] not in nodes:
    raise SystemExit('Missing or duplicate adopted object')
assets = {item['sha256']: item for item in manifest['assets']}
asset_paths = {item['path'] for item in assets.values()}
if len(assets) != len(manifest['assets']) or len(asset_paths) != len(assets):
    raise SystemExit('Duplicate registered asset identity or path')
for sha, item in assets.items():
    path = local(item['path'])
    if (manifest['files'].get(item['path']) != sha or not path.is_file()
            or path.stat().st_size != item['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != sha):
        raise SystemExit('Missing or changed registered asset: ' + sha)
    if any(usage['object'] not in nodes for usage in item['used_by']):
        raise SystemExit('Registered asset refers to a missing object: ' + sha)
review_count = 0
for key, node in nodes.items():
    if node['snapshot'] not in manifest['files'] or node['portable_source'] not in manifest['files']:
        raise SystemExit('Unverified source file: ' + key)
    source = json.loads(local(node['snapshot']).read_text())
    if key != source['id'] + '@' + str(source['revision']):
        raise SystemExit('Adopted object identity mismatch: ' + key)
    expected = node.get('source_snapshot_sha256', node['source_sha256'] if not node.get('redacted') else None)
    if expected and canonical(source) != expected:
        raise SystemExit('Adopted source hash mismatch: ' + key)
    if not node.get('redacted') and canonical(source) != node['source_sha256']:
        raise SystemExit('Original unredacted source identity mismatch: ' + key)
    try:
        declared_assets = source_assets(source)
    except (ValueError, TypeError, KeyError) as error:
        raise SystemExit('Invalid adopted asset declaration: ' + key + ': ' + str(error))
    if not declared_assets <= assets.keys():
        raise SystemExit('Missing adopted source assets: ' + key)
    for export in node.get('registered_exports', []):
        for ref in export.get('assets', []):
            if ref['sha256'] not in assets or assets[ref['sha256']]['path'] != ref['path']:
                raise SystemExit('Missing registered export asset: ' + key)
    for ref in source.get('metadata', {}).get('source_refs', []) + source.get('content', {}).get('source_refs', []):
        target = nodes.get(ref['id'] + '@' + str(ref['revision']))
        if target is None or (ref.get('sha256') and ref['sha256'] != target['source_sha256']):
            raise SystemExit('Missing or changed declared source: ' + ref['id'])
    for review in node.get('review_records', []):
        review_count += 1
        if (review.get('object_id') != source['id'] or review.get('revision') != source['revision']
                or review.get('source_sha256') != node['source_sha256']
                or review.get('identity') != canonical({k: v for k, v in review.items() if k not in {'identity', 'recorded_at'}})
                or review.get('scientific_approval') is not False or review.get('user_acceptance') is not False):
            raise SystemExit('Review source binding mismatch: ' + key)
        if review.get('review_object_id'):
            target = nodes.get(review['review_object_id'] + '@' + str(review.get('review_revision')))
            if target is None or target['source_sha256'] != review.get('review_source_sha256'):
                raise SystemExit('Review evidence binding mismatch: ' + key)
        elif not (review.get('role') == 'independent_cycle_final_review' and isinstance(review.get('findings'), dict)
                  and review.get('review_task_id') and review.get('review_candidate_sha256')):
            raise SystemExit('Review evidence contract missing: ' + key)
for key, node in nodes.items():
    if not node.get('markdown'): continue
    import posixpath
    markdown = node['markdown']
    if markdown['path'] not in manifest['files']:
        raise SystemExit('Unverified readable Markdown: ' + key)
    for binding in markdown['images']:
        asset = assets.get(binding['sha'])
        owner_key = binding['object_id'] + '@' + str(binding['revision'])
        owner = nodes.get(owner_key)
        if (asset is None or owner is None or binding['object_source_sha256'] != owner['source_sha256']
                or (owner_key != key and not any(e['source'] == key and e['target'] == owner_key for e in manifest['dependencies']))
                or binding['portable_target'] != posixpath.relpath(asset['path'], posixpath.dirname(markdown['path']))):
            raise SystemExit('Readable Markdown image binding mismatch: ' + key)
        if binding.get('source_object_id'):
            adopted = nodes.get(binding['source_object_id'] + '@' + str(binding['source_revision']))
            if adopted is None or adopted['source_sha256'] != binding['binding_source_sha256']:
                raise SystemExit('Readable Markdown adopted source mismatch: ' + key)
for edge in manifest['dependencies']:
    if edge['source'] not in nodes or edge['target'] not in nodes:
        raise SystemExit('Missing adopted dependency endpoint')
for key, job in manifest['jobs'].items():
    if key not in nodes:
        raise SystemExit('Rendering job refers to a missing source')
    inputs = job.get('inputs', {})
    if any(path not in asset_paths for path in inputs.values()):
        raise SystemExit('Rendering input lacks a verified registered asset: ' + key)
    if any(alias not in inputs for alias in job.get('images', {}).values()):
        raise SystemExit('Rendering image lacks a verified local input: ' + key)
    if job.get('script') and job['script'] not in asset_paths:
        raise SystemExit('Rendering script lacks a verified registered asset: ' + key)
    if job.get('renderer', 'runtime/render_worker.py') not in manifest['files']:
        raise SystemExit('Rendering worker lacks a verified file: ' + key)
print(json.dumps({'verified_files': len(manifest['files']), 'verified_objects': len(nodes),
                  'verified_review_records': review_count, 'verified_assets':len(assets),
                  'redacted_originals_not_byte_verifiable':sum(bool(n.get('redacted')) for n in nodes.values()),
                  'scientific_review': 'not_implied', 'authenticity_signature':False}))
if not args.render:
    if not args.verify: parser.print_help()
    raise SystemExit(0)
if args.render not in manifest['jobs']: raise SystemExit('No direct rendering job for this adopted source; inspect editable sources and requirements')
job = dict(manifest['jobs'][args.render])
if job.get('blocked_reason'): raise SystemExit(job['blocked_reason'])
if job.pop('requires_code_approval', False) and not args.approve_code:
    raise SystemExit('Imported script requires explicit --approve-code')
if not args.output: raise SystemExit('--output must name a new directory')
output = Path(args.output).resolve()
output.mkdir(parents=True, exist_ok=False)
job['inputs'] = {name: str(local(path)) for name, path in job.get('inputs', {}).items()}
if job.get('operation') == 'document':
    # The document worker only opens private copied inputs in its output dir.
    import shutil
    (output / 'inputs').mkdir()
    for index, (name, path) in enumerate(list(job['inputs'].items())):
        destination = output / 'inputs' / (str(index) + Path(path).suffix)
        shutil.copyfile(path, destination)
        job['inputs'][name] = str(destination)
if job.get('script'): job['script'] = str(local(job['script']))
job['output_dir'] = str(output)
job['response'] = str(output / 'result.json')
worker = job.pop('renderer', 'runtime/render_worker.py')
request = output / 'request.json'
request.write_text(json.dumps(job, ensure_ascii=False))
env = os.environ.copy()
env['MPLCONFIGDIR'] = str(output / 'mplconfig')
env['PYTHONDONTWRITEBYTECODE'] = '1'
# A recorded renderer can live in a hashed assets directory rather than runtime.
# Resolve its packaged helpers only from this already checksum-verified bundle.
env['PYTHONPATH'] = str(local('runtime'))
process = subprocess.Popen([sys.executable, str(local(worker)), str(request)], cwd=output, env=env, start_new_session=True)
try:
    code = process.wait(timeout=args.timeout)
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGKILL)
    process.wait()
    raise SystemExit('Rendering timed out')
if code: raise SystemExit(code)
result = json.loads((output / 'result.json').read_text())
print(json.dumps({'ok': result.get('ok'), 'output': str(output), 'error': result.get('error')}, ensure_ascii=False))
if not result.get('ok'): raise SystemExit(1)
'''


def bundle_reference_reader():
    """Package the exact shared parsers, without importing the application.

    This is source extraction, not a second maintained reference grammar.
    Only local exception/import adapters differ from the installed functions.
    """
    import ast
    import inspect
    import textwrap
    from research_partner.domains.manuscripts.sources import (
        image_references,
        asset_declarations,
    )

    declaration = textwrap.dedent(inspect.getsource(asset_declarations))
    lines = declaration.splitlines(keepends=True)
    removed = set()
    for node in ast.walk(ast.parse(declaration)):
        if isinstance(node, ast.ImportFrom) and (
            node.level or (node.module or "").startswith("research_partner.")
        ):
            removed.update(range(node.lineno - 1, node.end_lineno))
    declaration = "".join(line for i, line in enumerate(lines) if i not in removed)
    methods = "\n".join(
        textwrap.indent(textwrap.dedent(inspect.getsource(method)), "    ")
        for method in (
            ArtifactEngine._sha,
            ArtifactEngine._source_asset_refs,
            ArtifactEngine._asset_refs,
        )
    )
    adapter = "import re, copy\nclass Problem(ValueError): pass\ndef require(value, message, *args):\n    if not value: raise Problem(message)\n"
    reader = "\ndef source_assets(source):\n    source=copy.deepcopy(source)\n    metadata=source.get('metadata',{})\n    if metadata.get('last_export',{}).get('provenance',{}).get('bundle'):\n        metadata.pop('last_export')\n    return {sha for _,sha in ArtifactEngine._asset_refs(source)} | asset_declarations(source.get('content',{}))\n"
    return (
        adapter
        + "class ArtifactEngine:\n"
        + methods
        + "\n"
        + textwrap.dedent(inspect.getsource(image_references))
        + "\n"
        + declaration
        + reader
    ).encode()


class ArtifactEngine:
    def __init__(self, store, config=None):
        self.store = store
        self._recipient = contextvars.ContextVar("artifact_recipient", default=())
        supplied = config or {}
        # No environment-specific absolute paths are baked into the distribution.
        self.config = {
            "python": sys.executable,
            "scientific_python": os.environ.get(
                "RESEARCH_PARTNER_SCIENTIFIC_PYTHON", sys.executable
            ),
            "documents_python": os.environ.get(
                "RESEARCH_PARTNER_DOCUMENTS_PYTHON", sys.executable
            ),
            "svg_python": os.environ.get("RESEARCH_PARTNER_SVG_PYTHON", sys.executable),
            "office": os.environ.get(
                "RESEARCH_PARTNER_OFFICE",
                shutil.which("libreoffice") or shutil.which("soffice"),
            ),
            "office_library_dirs": [
                p
                for p in os.environ.get(
                    "RESEARCH_PARTNER_OFFICE_LIBRARY_DIRS", ""
                ).split(os.pathsep)
                if p
            ],
            "latex": os.environ.get(
                "RESEARCH_PARTNER_LATEX",
                shutil.which("pdflatex")
                or shutil.which("xelatex")
                or shutil.which("lualatex"),
            ),
            "pdftotext": shutil.which("pdftotext"),
            "timeout": 90,
            **supplied,
        }

    def capabilities(self):
        result = {
            "imports": ["md", "txt", "docx", "pdf"],
            "exports": {
                "report": ["md", "docx", "pdf"],
                "note": ["md", "docx", "pdf"],
                "figure": ["svg", "pdf", "png", "json"],
                "diagram": ["svg", "pdf", "png", "json"],
                "paper": ["md", "docx", "tex", "bib", "zip", "pdf"],
                "poster": ["svg", "pdf", "png", "json"],
                "slides": ["pptx", "pdf", "md", "json"],
            },
            "runtimes": {},
            "limitations": [
                "Imported Python executes only with explicit tool authorization; subprocess isolation is not a security sandbox.",
                "DOCX import preserves text/heading/table content, not arbitrary Word layout or tracked-change semantics.",
                "PDF is a reading source; extraction is not an editable-layout reconstruction.",
            ],
        }
        for key, modules in [
            ("scientific_python", ["matplotlib", "numpy"]),
            ("documents_python", ["docx", "pptx"]),
            ("svg_python", ["ctypes"]),
        ]:
            try:
                record = run_process(
                    [
                        self.config[key],
                        "-c",
                        "import importlib.util,json,sys; print(json.dumps({'executable':sys.executable,'version':sys.version,'modules':{x:bool(importlib.util.find_spec(x)) for x in "
                        + repr(modules)
                        + "}}))",
                    ],
                    cwd=str(self.store.workspace),
                    timeout=10,
                )
                result["runtimes"][key] = json.loads(record["stdout"])
                result["runtimes"][key]["available"] = all(
                    result["runtimes"][key]["modules"].values()
                )
                if key == "svg_python":
                    libraries = run_process(
                        [
                            self.config[key],
                            "-c",
                            "import ctypes.util,json; print(json.dumps({x:ctypes.util.find_library(x) for x in ['cairo','rsvg-2','gobject-2.0']}))",
                        ],
                        cwd=str(self.store.workspace),
                        timeout=10,
                    )
                    result["runtimes"][key]["libraries"] = json.loads(
                        libraries["stdout"]
                    )
                    result["runtimes"][key]["available"] = all(
                        result["runtimes"][key]["libraries"].values()
                    )
            except (Problem, ValueError) as exc:
                result["runtimes"][key] = {"available": False, "reason": str(exc)}
        for key in ["office", "latex", "pdftotext"]:
            result["runtimes"][key] = {
                "executable": self.config.get(key),
                "available": bool(
                    self.config.get(key)
                    and (
                        Path(self.config[key]).is_file()
                        or shutil.which(self.config[key])
                    )
                ),
            }
        for formats in result["exports"].values():
            if "zip" not in formats:
                formats.append("zip")
        result["bundle_formats"] = ["zip", "bundle"]
        return result

    def _object(self, ident, revision=None):
        if not isinstance(ident, dict):
            if revision is None:
                from research_partner.domains.figures.definition import (
                    FigureDefinitions,
                    is_definition,
                )

                if is_definition(self.store.get(ident)):
                    return copy.deepcopy(FigureDefinitions(self.store).sync(ident))
            return copy.deepcopy(self.store.get(ident, revision))
        require(
            ident.get("id") and isinstance(ident.get("revision"), int),
            "导出需要已登记的成果身份与修订",
            "object_identity_required",
            409,
        )
        recorded = self.store.get(ident["id"], revision or ident["revision"])
        current = self.store.get(ident["id"])
        require(
            ident.get("project_id")
            == recorded.get("project_id")
            == current.get("project_id")
            and ident.get("kind") == recorded.get("kind"),
            "不能通过候选对象变更项目归属或类型",
            "forbidden",
            403,
        )
        # Explicit historical export resolves the registered historical content.
        return copy.deepcopy(recorded if revision is not None else ident)

    @staticmethod
    def _sha(value):
        if isinstance(value, dict):
            value = (
                value.get("sha")
                or value.get("asset")
                or value.get("asset_sha")
                or value.get("asset_id")
            )
        if isinstance(value, str) and value.startswith("/api/assets/"):
            value = value.rsplit("/", 1)[-1]
        return value

    @classmethod
    def _source_asset_refs(cls, value, path, *, strict=True):
        """Typed source_assets: a list or alias map of blob IDs/descriptors.

        Descriptor identity/annotation fields are not additional dependencies.
        This exact parser is also shipped in the standalone bundle verifier.
        """
        pointers = {"asset", "asset_id", "asset_sha", "sha"}
        entries = (
            list(enumerate(value))
            if isinstance(value, list)
            else list(value.items())
            if isinstance(value, dict)
            else None
        )
        if entries is None:
            if strict:
                raise Problem(
                    "source_assets 须为资产列表或命名映射",
                    "unregistered_dependency",
                    422,
                    {"path": ".".join(path)},
                )
            return
        for name, entry in entries:
            location = path + (str(name),)
            refs = (
                [(key, item) for key, item in entry.items() if key in pointers]
                if isinstance(entry, dict)
                else [(None, entry)]
            )
            if not refs:
                if strict:
                    raise Problem(
                        "source_assets 条目缺少明确资产指针",
                        "unregistered_dependency",
                        422,
                        {"path": ".".join(location)},
                    )
                continue
            for key, item in refs:
                target = location + (key,) if key else location
                sha = cls._sha(item) if isinstance(item, str) else None
                if isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha):
                    yield target, sha
                elif strict:
                    raise Problem(
                        "source_assets 依赖不是已登记资产标识",
                        "unregistered_dependency",
                        422,
                        {"path": ".".join(target)},
                    )
            if isinstance(entry, dict):
                # Preserve pre-existing explicit nested declarations (e.g.
                # attachments or *_asset) without inheriting blob context into
                # ordinary descriptor identity/annotation digests.
                yield from cls._asset_refs(
                    {key: item for key, item in entry.items() if key not in pointers},
                    location,
                    strict=strict,
                )

    @classmethod
    def _asset_refs(cls, value, path=(), asset_context=False, *, strict=True):
        """Enumerate declared blob dependencies, never interpret digest-only fields."""
        direct = {
            "asset",
            "asset_id",
            "asset_sha",
            "sha",
            "script",
            "script_asset",
            "source_asset",
            "source_bundle",
            "bibtex_asset",
            "preview",
            "preview_asset",
            "png",
            "import_source",
            "script_sha256",
            "overlays_sha256",
            "renderer_asset_sha256",
        }
        containers = {
            "input_assets",
            "latex_assets",
            "assets",
            "inputs",
            "outputs",
            "attachments",
        }
        if isinstance(value, dict):
            if (
                strict
                and value.get("type") == "image"
                and "pages" in path
                and "objects" in path
            ):
                require(
                    any(value.get(k) for k in ("asset", "src", "asset_id")),
                    "画布图像缺少登记资产",
                    "missing_asset",
                    422,
                    {"path": ".".join(path)},
                )
            for key, item in value.items():
                if key == "source_assets":
                    yield from cls._source_asset_refs(
                        item, path + (key,), strict=strict
                    )
                    continue
                if key == "provenance" and isinstance(item, dict):
                    # Export provenance mixes blob references with object IDs,
                    # revisions and numeric/source digests. Only declared blob
                    # fields are dependency references, never identity metadata.
                    for field in [
                        "script_sha256",
                        "overlays_sha256",
                        "renderer_asset_sha256",
                    ]:
                        if item.get(field):
                            yield from cls._asset_refs(
                                item[field], path + (key, field), True, strict=strict
                            )
                    for index, source_input in enumerate(item.get("inputs", [])):
                        if isinstance(source_input, dict) and source_input.get("sha"):
                            yield from cls._asset_refs(
                                source_input["sha"],
                                path + (key, "inputs", str(index), "sha"),
                                True,
                                strict=strict,
                            )
                    continue
                yield from cls._asset_refs(
                    item,
                    path + (str(key),),
                    key in direct
                    or key.endswith(("_asset", "_asset_sha", "_asset_id"))
                    or key in containers
                    or (key == "src" and value.get("type") == "image")
                    or (
                        asset_context
                        and key
                        not in {
                            "filename",
                            "name",
                            "alias",
                            "path",
                            "role",
                            "media_type",
                            "mime",
                            "url",
                            "metadata",
                            "size",
                            "created_at",
                            "source",
                            "provenance",
                            "synthetic",
                            "project_id",
                            "source_object_id",
                            "source_revision",
                        }
                    ),
                    strict=strict,
                )
        elif isinstance(value, list):
            for index, item in enumerate(value):
                yield from cls._asset_refs(
                    item, path + (str(index),), asset_context, strict=strict
                )
        elif isinstance(value, str) and value:
            sha = cls._sha(value)
            if value.startswith("/api/assets/") or (
                asset_context and re.fullmatch(r"[a-f0-9]{64}", value)
            ):
                yield path, sha
            elif (
                strict
                and asset_context
                and path[-1]
                not in {
                    "preview",
                    "png",
                    "script_sha256",
                    "overlays_sha256",
                    "renderer_asset_sha256",
                }
            ):
                # Named input mappings and explicit source assets must resolve.
                if (
                    path[-1] in direct
                    or path[-1].endswith(("_asset", "_asset_sha", "_asset_id"))
                    or any(k in containers for k in path)
                ):
                    raise Problem(
                        "依赖不是已登记资产标识",
                        "unregistered_dependency",
                        422,
                        {"path": ".".join(path)},
                    )

    def _declared_references(self, obj):
        content = obj["content"]
        refs = list(content.get("components", [])) + list(content.get("citations", []))
        from research_partner.domains.figures.definition import is_definition

        if is_definition(obj):
            refs.extend(
                {**slot["source"], "relation_type": "fixed_main_figure_panel"}
                for slot in content["slots"]
                if slot["source"]
            )
        for container in (content, obj.get("metadata", {})):
            adopted = container.get("source_refs", [])
            require(
                isinstance(adopted, list),
                "登记来源须为明确版本引用列表",
                "component_revision_required",
                409,
            )
            for ref in adopted:
                require(
                    isinstance(ref, dict)
                    and isinstance(ref.get("id"), str)
                    and ref["id"]
                    and type(ref.get("revision")) is int
                    and ref["revision"] > 0,
                    "登记来源缺少明确对象与采用版本",
                    "component_revision_required",
                    409,
                )
                refs.append({**ref, "relation_type": "registered_source"})
        exported = obj.get("metadata", {}).get("last_export", {}).get("provenance", {})
        if not exported.get("bundle"):
            for item in exported.get("components", []) + exported.get("citations", []):
                if (
                    isinstance(item, dict)
                    and item.get("object_id")
                    and isinstance(item.get("revision"), int)
                ):
                    refs.append(
                        {
                            "id": item["object_id"],
                            "revision": item["revision"],
                            "relation_type": "recorded_export_source",
                        }
                    )
        # Bibliographic `pages` is a page-range string, not a canvas. Only
        # visual-layout objects interpret it as pages of component placements.
        pages = (
            content.get("pages", [])
            if obj.get("kind") in {"figure", "diagram", "poster", "slides"}
            else []
        )
        require(
            isinstance(pages, list) and all(isinstance(page, dict) for page in pages),
            "画布页面必须是对象列表",
            "invalid_canvas",
            422,
        )
        for page in pages:
            items = page.get("objects", [])
            require(
                isinstance(items, list)
                and all(isinstance(item, dict) for item in items),
                "画布页面元素必须是对象列表",
                "invalid_canvas",
                422,
            )
            for item in items:
                if item.get("component_id"):
                    refs.append(
                        {
                            "id": item["component_id"],
                            "revision": item.get(
                                "component_revision", item.get("revision")
                            ),
                        }
                    )

        def asset_sources(value):
            if isinstance(value, dict):
                if value.get("source_object_id"):
                    refs.append(
                        {
                            "id": value["source_object_id"],
                            "revision": value.get("source_revision"),
                        }
                    )
                for child in value.values():
                    asset_sources(child)
            elif isinstance(value, list):
                for child in value:
                    asset_sources(child)

        asset_sources(content)
        return refs

    def _shared_asset_owner(self, owner, sha, explicit=None):
        refs = []
        if isinstance(explicit, dict) and explicit.get("source_object_id"):
            refs.append(
                {
                    "id": explicit["source_object_id"],
                    "revision": explicit.get("source_revision"),
                }
            )
        refs.extend(self._declared_references(owner))
        for relation in self.store.relations(owner["id"]):
            if relation["src"] == owner["id"] and relation["type"] in {
                "contains",
                "uses",
                "cites",
                "depends_on",
            }:
                refs.append(
                    {"id": relation["dst"], "revision": relation["target_revision"]}
                )
        for ref in refs:
            try:
                source, _ = self._reference(owner, ref)
                from research_partner.domains.manuscripts.sources import (
                    asset_declarations,
                )

                declared = asset_declarations(source["content"], strict=False)
                declared.update(
                    value
                    for _, value in self._asset_refs(
                        {"metadata": source["metadata"]}, strict=False
                    )
                )
                if sha in declared:
                    return source
            except Problem as exc:
                if exc.code in {
                    "forbidden",
                    "component_revision_required",
                    "not_found",
                }:
                    continue
                raise
        return None

    def _asset_bytes(self, sha, owner=None, *, project_id=None):
        explicit, sha = sha, self._sha(sha)
        info = self.store.asset(sha)
        requested = owner.get("project_id") if owner else project_id
        owners = set(info["metadata"].get("projects", []))
        if info["metadata"].get("project_id"):
            owners.add(info["metadata"]["project_id"])
        allowed = requested in owners if requested is not None else not owners
        if not allowed and owner is not None:
            source = self._shared_asset_owner(owner, sha, explicit)
            allowed = bool(source and source.get("project_id") in owners)
        require(
            allowed,
            "成果无权读取此资产；需要本项目归属或采用版本的明确共享组件",
            "forbidden",
            403,
            {"asset_sha": sha},
        )
        reader = getattr(self.store, "staged_asset_bytes", None)
        return info, reader(info["sha"]) if reader else (
            self.store.blobs / info["sha"]
        ).read_bytes()

    def _write_asset(self, sha, work, alias=None, owner=None, *, project_id=None):
        info, data = self._asset_bytes(sha, owner, project_id=project_id)
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", alias or info["filename"])
        require(name not in {"", ".", ".."}, "输入名称不合法")
        path = work / "inputs" / (info["sha"][:12] + "_" + name)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        return str(path), {
            "sha": info["sha"],
            "filename": info["filename"],
            "alias": alias or info["filename"],
            "media_type": info["media_type"],
        }

    def _worker(self, job, work, runtime) -> RenderSuccess:
        request = work / ("request-" + str(time.time_ns()) + ".json")
        response = request.with_suffix(".result.json")
        try:
            payload = validate_render_request(
                {**job, "output_dir": str(work), "response": str(response)}
            )
        except RenderContractError as exc:
            raise Problem(str(exc), "invalid", 422) from exc
        request.write_text(encoded(payload), encoding="utf-8")
        env = os.environ.copy()
        env["MPLCONFIGDIR"] = str(work / "mplconfig")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        record = run_process(
            [
                str(self.config[runtime]),
                str(module_file("research_partner.rendering.worker")),
                str(request),
            ],
            cwd=work,
            timeout=float(self.config["timeout"]),
            env=env,
        )
        require(response.exists(), "渲染器未返回结果", "render_failed", 422, record)
        try:
            value = validate_render_result(json.loads(response.read_text()))
        except ValueError as exc:
            raise Problem("渲染器返回了无效结果", "render_failed", 422, record) from exc
        if not value["ok"]:
            raise Problem(
                value["error"],
                value.get("code", "render_failed"),
                422,
                {"worker": value, "process": record},
            )
        value["process"] = record
        return value

    def _publish(self, obj, work, value, primary, provenance=None):
        from research_partner.domains.generation.validity import ensure_deliverable

        ensure_deliverable(self.store, obj)
        provenance = {
            "object_id": obj.get("id"),
            "revision": obj.get("revision"),
            "kind": obj["kind"],
            "source_sha256": digest(obj),
            **(provenance or {}),
            "runtime": value.get("runtime", {}),
            "renderer_sha256": hashlib.sha256(
                module_file("research_partner.rendering.worker").read_bytes()
            ).hexdigest(),
            "process": value.get("process", {}),
            "script_stdout": value.get("script_stdout", ""),
            "script_stderr": value.get("script_stderr", ""),
            "verification": "generated; requires visual/scientific review",
        }
        assets = {}
        renderer = self.store.add_asset(
            module_file("research_partner.rendering.worker").read_bytes(),
            "render_worker.py",
            "text/x-python",
            {
                "project_id": obj.get("project_id"),
                "object_id": obj.get("id"),
                "revision": obj.get("revision"),
                "role": "renderer_source",
            },
        )
        assets["render_worker.py"] = renderer
        provenance["renderer_asset_sha256"] = renderer["sha"]
        for path in value.get("files", []):
            file = Path(path)
            require(
                file.resolve().is_relative_to(work.resolve()) and file.is_file(),
                "渲染器返回了工作目录外路径",
                "unsafe_output",
                422,
            )
            suffix = file.suffix.lstrip(".")
            assets[file.name] = self.store.add_asset(
                file.read_bytes(),
                file.name,
                MIME.get(
                    suffix,
                    mimetypes.guess_type(file.name)[0] or "application/octet-stream",
                ),
                {
                    "project_id": obj.get("project_id"),
                    "object_id": obj.get("id"),
                    "revision": obj.get("revision"),
                    "role": "export",
                    "source_sha256": provenance["source_sha256"],
                },
            )
        source = self.store.add_asset(
            (
                json.dumps(
                    {"object": obj, "provenance": provenance},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            ).encode(),
            "source.json",
            MIME["json"],
            {
                "project_id": obj.get("project_id"),
                "role": "editable_source",
                "object_id": obj.get("id"),
                "revision": obj.get("revision"),
            },
        )
        assets["source.json"] = source
        manifest = value.get("manifest", [])
        if manifest:
            assets["manifest.json"] = self.store.add_asset(
                (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode(),
                "manifest.json",
                MIME["json"],
                {
                    "project_id": obj.get("project_id"),
                    "role": "object_manifest",
                    "object_id": obj.get("id"),
                    "revision": obj.get("revision"),
                },
            )
        result = {
            "status": "generated",
            "asset": assets.get(primary),
            "assets": assets,
            "manifest": manifest,
            "provenance": provenance,
            "warnings": value.get("warnings", []),
            "replay": value.get("replay", {"applied": [], "failures": []}),
        }
        require(
            result["asset"],
            "请求格式没有产生文件",
            "missing_export",
            422,
            {"format": primary, "files": list(assets)},
        )
        return result

    def import_document(self, asset_sha, kind="report", title=None, project_id=None):
        require(kind in {"report", "note", "paper", "literature"}, "不支持的文稿类型")
        info, data = self._asset_bytes(asset_sha, project_id=project_id)
        suffix = Path(info["filename"]).suffix.lower()
        warnings = []
        if suffix in {".md", ".txt"}:
            text = data.decode("utf-8-sig")
            blocks = markdown_blocks(text)
        elif suffix == ".docx":
            import io

            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                require(
                    sum(x.file_size for x in archive.infolist()) < 100_000_000,
                    "DOCX 展开内容过大",
                )
                root = ET.fromstring(archive.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            blocks = []
            for p in root.findall(".//w:p", ns):
                text = "".join(n.text or "" for n in p.findall(".//w:t", ns))
                if not text:
                    continue
                style = p.find("w:pPr/w:pStyle", ns)
                style = (
                    style.get("{" + ns["w"] + "}val", "") if style is not None else ""
                )
                blocks.append(
                    {
                        "id": uid("BLOCK"),
                        "kind": "heading"
                        if style.startswith("Heading")
                        else "paragraph",
                        "text": text,
                    }
                )
            warnings.append(
                "仅导入正文、标题和表格中的文本；源 DOCX 保留，任意版式/批注/修订未无损重建。"
            )
        elif suffix == ".pdf":
            require(
                self.config.get("pdftotext"),
                "缺少 pdftotext，无法读取 PDF 文本",
                "runtime_unavailable",
                503,
            )
            with tempfile.TemporaryDirectory(
                prefix="rp-pdf-", dir=self.store.workspace
            ) as folder:
                work = Path(folder)
                path, _ = self._write_asset(
                    asset_sha, work, "reading.pdf", project_id=project_id
                )
                # Read the full extraction rather than the bounded process log.
                run_process(
                    [
                        self.config["pdftotext"],
                        "-layout",
                        path,
                        str(work / "reading.txt"),
                    ],
                    cwd=work,
                    timeout=self.config["timeout"],
                )
                pages = (work / "reading.txt").read_text().split("\f")
            blocks = [
                {
                    "id": uid("BLOCK"),
                    "kind": "paragraph",
                    "text": page.strip(),
                    "source_page": i + 1,
                }
                for i, page in enumerate(pages)
                if page.strip()
            ]
            warnings.append("已读取可提取 PDF 文本；不代表 OCR、图表理解或版式可编辑。")
            require(blocks, "PDF 没有可提取文本；需要另行授权 OCR", "pdf_no_text", 422)
        else:
            raise Problem(
                "仅支持 Markdown、TXT、DOCX 和 PDF 文本读取", "unsupported_format", 422
            )
        return self.store.create(
            kind,
            title or Path(info["filename"]).stem,
            project_id,
            {"blocks": blocks},
            {
                "import_source": info["sha"],
                "import_format": suffix[1:],
                "read_scope": "extracted_text" if suffix == ".pdf" else "text_content",
                "import_warnings": warnings,
            },
        )

    @contextlib.contextmanager
    def _request_scope(self, obj):
        prior = self._recipient.get()
        token = self._recipient.set(prior or (obj.get("project_id"),))
        try:
            recipient = self._recipient.get()[0]
            current = self.store.get(obj["id"])
            require(
                obj.get("project_id") == recipient
                or recipient in current["metadata"].get("shared_with", []),
                "嵌套导出来源未向接收项目共享",
                "forbidden",
                403,
            )
            yield
        finally:
            self._recipient.reset(token)

    def render_figure(
        self,
        ident,
        input_assets=None,
        overlays=None,
        authorized_code=False,
        revision=None,
        *,
        preview=False,
    ):
        obj = self._object(ident, revision)
        with self._request_scope(obj):
            return self._render_figure(
                obj, input_assets, overlays, authorized_code, preview=preview
            )

    def _render_figure(
        self,
        obj,
        input_assets=None,
        overlays=None,
        authorized_code=False,
        *,
        preview=False,
    ):
        require(obj["kind"] == "figure", "只可重绘科研图")
        c = obj["content"]
        sources = c.get("input_assets", []) if input_assets is None else input_assets
        layers = c.get("overlays", []) if overlays is None else overlays
        # A replay export is an explicit candidate based on this revision, not a
        # silent mutation of the stored object. Its source must match the run.
        base_source_sha = digest(obj)
        if input_assets is not None:
            c["input_assets"] = copy.deepcopy(sources)
        if overlays is not None:
            c["overlays"] = copy.deepcopy(layers)
        if isinstance(layers, dict):
            layers = [
                {"target": key, "properties": value} for key, value in layers.items()
            ]
        with tempfile.TemporaryDirectory(
            prefix="rp-figure-", dir=self.store.workspace
        ) as folder:
            work = Path(folder)
            paths, source_info = {}, []
            iterable = (
                sources.items()
                if isinstance(sources, dict)
                else [(str(i), item) for i, item in enumerate(sources)]
            )
            for alias, sha in iterable:
                if isinstance(sha, dict):
                    alias = sha.get("name", sha.get("alias", alias))
                path, info = self._write_asset(sha, work, owner=obj)
                paths[str(alias)] = path
                paths.setdefault(info["filename"], path)
                source_info.append({**info, "alias": str(alias)})
            script = c.get("script_asset") or c.get("script")
            if script:
                require(
                    authorized_code,
                    "运行导入 Python 脚本需要明确工具授权",
                    "authorization_required",
                    403,
                )
                path, info = self._write_asset(script, work, "source.py", owner=obj)
                script_sha = info["sha"]
            else:
                require(
                    c.get("spec"),
                    "请关联已授权脚本及输入，或提供结构化绘图 spec",
                    "missing_source",
                    422,
                )
                path, script_sha = None, None
            value = self._worker(
                {
                    "operation": "figure",
                    "script": path,
                    "inputs": paths,
                    "spec": c.get("spec"),
                    "parameters": c.get("parameters", {}),
                    "overlays": layers,
                    "preview": bool(preview),
                },
                work,
                "scientific_python",
            )
            if not script_sha:
                source_script = self.store.add_asset(
                    (work / "plot_source.py").read_bytes(),
                    "plot_source.py",
                    "text/x-python",
                    {
                        "project_id": obj.get("project_id"),
                        "role": "generated_source",
                        "object_id": obj.get("id"),
                        "revision": obj.get("revision"),
                    },
                )
                script_sha = source_script["sha"]
            overlays_asset = self.store.add_asset(
                (encoded(layers) + "\n").encode(),
                "visual_overlays.json",
                MIME["json"],
                {
                    "project_id": obj.get("project_id"),
                    "role": "visual_overlay",
                    "object_id": obj.get("id"),
                    "revision": obj.get("revision"),
                },
            )
            provenance = {
                "base_source_sha256": base_source_sha,
                "candidate_overrides": input_assets is not None or overlays is not None,
                "script_sha256": script_sha,
                "inputs": source_info,
                "overlays_sha256": overlays_asset["sha"],
                "numeric_before": value["numeric_before"],
                "numeric_after": value["numeric_after"],
                "numeric_preserved": value["numeric_before"] == value["numeric_after"],
                "script_authorized": bool(script and authorized_code),
            }
            return self._publish(obj, work, value, "figure.svg", provenance)

    def _canvas_inputs(self, obj, work):
        from research_partner.domains.figures.definition import (
            require_complete,
            is_definition,
        )

        require_complete(obj)
        c = obj["content"]
        inputs, provenance = {}, []
        for page in c.get("pages", []):
            for item in page.get("objects", []):
                if item.get("type") != "image":
                    continue
                sha = item.get("asset") or item.get("src") or item.get("asset_id")
                if is_definition(obj):
                    slot = next((s for s in c["slots"] if s["id"] == item["id"]), None)
                    ref = item.get("source_ref")
                    require(
                        slot and slot["source"] == ref and ref["svg_sha256"] == sha,
                        "主图投影与固定子图来源不符",
                        "integrity",
                        409,
                    )
                    source, _ = self._reference(
                        obj, {k: ref[k] for k in ("id", "revision", "sha256")}
                    )
                    require(
                        any(
                            r["result"].get("provenance", {}).get("source_sha256")
                            == digest(source)
                            and r["result"]
                            .get("assets", {})
                            .get("figure.svg", {})
                            .get("sha")
                            == sha
                            for r in self.store.export_records(
                                source["id"], source["revision"]
                            )
                        ),
                        "子图输出不是实际登记的来源",
                        "integrity",
                        409,
                    )
                require(
                    sha,
                    "图像对象缺少注册资产",
                    "missing_asset",
                    422,
                    {"object_id": item.get("id")},
                )
                path, info = self._write_asset(sha, work, owner=obj)
                inputs[item["id"]] = path
                provenance.append({**info, "object_id": item["id"]})
        return inputs, provenance

    def _document_images(self, obj, markdown, work):
        """Resolve only explicit aliases or asset URLs through the owner's ACL.

        A relative Markdown destination is an identifier in content.resources;
        it is never interpreted relative to the repository, an import path or
        the process cwd. The worker receives copied bytes only.
        """
        from urllib.parse import unquote, urlsplit
        from research_partner.rendering.worker import markdown_image_references

        resources = obj["content"].get("resources", {})
        require(
            isinstance(resources, dict),
            "文稿 resources 必须是相对引用到资产的映射",
            "invalid_document_resources",
            422,
        )
        inputs, images, provenance, warnings = {}, {}, [], []
        for occurrence in markdown_image_references(markdown):
            target = occurrence["target"]
            warning = {
                "code": "markdown_image_unresolved",
                "object_id": obj["id"],
                "revision": obj["revision"],
                "line": occurrence["line"],
                "target": target,
                "alt": occurrence["text"],
            }
            direct = re.fullmatch(r"/api/assets/[a-f0-9]{64}", target)
            decoded = unquote(target)
            relative = bool(
                decoded
                and not decoded.startswith(("/", "\\"))
                and "\\" not in decoded
                and not any(ord(c) < 32 for c in decoded)
                and not urlsplit(decoded).scheme
                and not urlsplit(decoded).netloc
                and not urlsplit(decoded).query
                and not urlsplit(decoded).fragment
                and ".." not in decoded.split("/")
            )
            if occurrence.get("unsupported_reference") or not (direct or relative):
                warnings.append(
                    {
                        **warning,
                        "code": "markdown_image_reference_blocked",
                        "reason": "Only inline registered asset URLs or explicit safe relative resource aliases are supported",
                    }
                )
                continue
            reference = (
                resources[target]
                if target in resources
                else (target if direct else None)
            )
            if not reference:
                warnings.append(
                    {
                        **warning,
                        "reason": "Relative image has no explicit content.resources asset binding; no filesystem or network lookup attempted",
                    }
                )
                continue
            if (not direct or target in resources) and (
                not isinstance(reference, dict)
                or not self._sha(reference)
                or not re.fullmatch(r"[a-f0-9]{64}", str(self._sha(reference)))
            ):
                warnings.append(
                    {
                        **warning,
                        "code": "markdown_image_binding_invalid",
                        "reason": "Resource binding must contain an explicit registered asset SHA",
                    }
                )
                continue
            if direct:
                require(
                    self._sha(reference) == target.rsplit("/", 1)[-1],
                    "图片直接地址与资源绑定资产不符",
                    "integrity",
                    409,
                )
            binding_source = None
            if isinstance(reference, dict) and (
                "source_object_id" in reference or "source_revision" in reference
            ):
                require(
                    reference.get("source_object_id")
                    and type(reference.get("source_revision")) is int,
                    "图片来源需要明确对象与采用修订",
                    "component_revision_required",
                    409,
                )
                binding_source, _ = self._reference(
                    obj,
                    {
                        "id": reference["source_object_id"],
                        "revision": reference["source_revision"],
                        **(
                            {"sha256": reference["source_sha256"]}
                            if "source_sha256" in reference
                            else {}
                        ),
                    },
                )
                from research_partner.domains.manuscripts.sources import (
                    asset_declarations,
                )

                require(
                    self._sha(reference)
                    in asset_declarations(binding_source["content"], strict=False),
                    "指定采用来源未声明此图片资产",
                    "forbidden",
                    403,
                )
            try:
                if binding_source is None:
                    asset_info = self.store.asset(self._sha(reference))
                    owners = set(asset_info["metadata"].get("projects", []))
                    if asset_info["metadata"].get("project_id"):
                        owners.add(asset_info["metadata"]["project_id"])
                    if (
                        obj.get("project_id") not in owners
                        if obj.get("project_id") is not None
                        else bool(owners)
                    ):
                        binding_source = self._shared_asset_owner(
                            obj, self._sha(reference), reference
                        )
                info, data = self._asset_bytes(reference, owner=binding_source or obj)
            except Problem as exc:
                # Access and integrity violations abort the export; reporting
                # an unavailable image must never turn permission into success.
                if exc.code != "not_found":
                    raise
                warnings.append(
                    {**warning, "reason": "Registered image asset is missing"}
                )
                continue
            require(
                hashlib.sha256(data).hexdigest() == info["sha"],
                "图像资产内容校验失败",
                "integrity",
                409,
            )
            signatures = [
                (b"\x89PNG\r\n\x1a\n", "png"),
                (b"\xff\xd8\xff", "jpg"),
                (b"GIF8", "gif"),
                (b"BM", "bmp"),
                (b"II*\x00", "tiff"),
                (b"MM\x00*", "tiff"),
            ]
            extension = next(
                (ext for prefix, ext in signatures if data.startswith(prefix)), None
            )
            if extension is None:
                warnings.append(
                    {
                        **warning,
                        "code": "markdown_image_format_unsupported",
                        "reason": "Bound bytes are not a supported raster image; vector/network content was not opened",
                    }
                )
                continue
            if target in images:
                continue
            alias = "markdown-image-" + str(len(images) + 1)
            path = work / "inputs" / (info["sha"] + "." + extension)
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
            inputs[alias] = str(path)
            images[target] = alias
            binding = (
                {
                    "source_object_id": binding_source["id"],
                    "source_revision": binding_source["revision"],
                }
                if binding_source
                else {}
            )
            provenance.append(
                {
                    "sha": info["sha"],
                    "filename": info["filename"],
                    "target": target,
                    "alias": alias,
                    "object_id": obj["id"],
                    "revision": obj["revision"],
                    "object_source_sha256": digest(obj),
                    **binding,
                    **(
                        {"binding_source_sha256": digest(binding_source)}
                        if binding_source
                        else {}
                    ),
                }
            )
        return inputs, images, provenance, warnings

    def _document_math(self, texts, work):
        """Render bounded mathematical glyphs, never source code or scientific fits."""
        from research_partner.rendering.worker import markdown_math_references

        values = list(
            dict.fromkeys(
                raw for text in texts for raw in markdown_math_references(text)
            )
        )
        if not values:
            return {"math_images": {}, "math_runtime": {}, "inputs": {}}
        require(
            len(values) <= 128 and all(len(raw) <= 4096 for raw in values),
            "文稿公式超出单次渲染上限",
            "render_limit",
            413,
        )
        output = work / ("docx-math-" + digest(values)[:12])
        output.mkdir(exist_ok=True)
        request = output / "input.json"
        request.write_text(json.dumps(values, ensure_ascii=False))
        helper = module_file("research_partner.rendering.docx_semantics")
        env = os.environ.copy()
        env["MPLCONFIGDIR"] = str(output / "mplconfig")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            process = run_process(
                [
                    self.config["scientific_python"],
                    str(helper),
                    str(request),
                    str(output),
                ],
                cwd=output,
                timeout=float(self.config["timeout"]),
                env=env,
            )
            payload = json.loads((output / "equations-result.json").read_text())
            runtime = {**payload["runtime"], "process": process}
        except Problem as exc:
            payload = {
                "equations": [
                    {
                        "source": raw,
                        "source_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                        "status": "unsupported",
                        "error": "Existing mathematical glyph runtime unavailable: "
                        + str(exc),
                    }
                    for raw in values
                ]
            }
            runtime = {
                "kind": "unavailable",
                "code": exc.code,
                "process": exc.details,
                "latex_compiled": False,
            }
        images = {}
        inputs = {}
        for entry in payload["equations"]:
            item = dict(entry)
            if entry.get("status") == "rendered":
                filename = entry["filename"]
                path = output / filename
                require(
                    path.resolve().is_relative_to(output.resolve())
                    and path.is_file()
                    and hashlib.sha256(path.read_bytes()).hexdigest()
                    == entry["sha256"],
                    "公式渲染资产身份不符",
                    "integrity",
                    409,
                )
                item["input_alias"] = "docx-math-" + entry["source_sha256"]
                inputs[item["input_alias"]] = str(path)
            images[entry["source"]] = item
        return {"math_images": images, "math_runtime": runtime, "inputs": inputs}

    def _office_pdf(self, source, work):
        office = self.config.get("office")
        require(
            office and (Path(office).is_file() or shutil.which(office)),
            "缺少可用 LibreOffice，不能从 Office 原件生成阅读 PDF",
            "runtime_unavailable",
            503,
            {"needed": "office", "source_format": source.suffix},
        )
        outdir = work / "office-pdf"
        outdir.mkdir(exist_ok=True)
        env = os.environ.copy()
        env.update(
            {
                "SAL_USE_VCLPLUGIN": "svp",
                "SAL_DISABLEGL": "1",
                "SAL_DISABLE_OPENCL": "1",
            }
        )
        if self.config.get("office_library_dirs"):
            env["LD_LIBRARY_PATH"] = os.pathsep.join(self.config["office_library_dirs"])
        for key, value in self.config.get("office_env", {}).items():
            env[key] = value
        profile = work / "office-profile"
        record = run_process(
            [
                office,
                "-env:UserInstallation=" + profile.as_uri(),
                "--headless",
                "--norestore",
                "--nofirststartwizard",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                str(source),
            ],
            cwd=work,
            timeout=self.config["timeout"],
            env=env,
        )
        pdf = outdir / (source.stem + ".pdf")
        require(
            pdf.exists() and pdf.read_bytes().startswith(b"%PDF"),
            "LibreOffice 未产生有效 PDF",
            "render_failed",
            422,
            record,
        )
        target = work / pdf.name
        shutil.copyfile(pdf, target)
        return str(target), record

    def export(self, ident, format, revision=None, authorized_code=False):
        obj = self._object(ident, revision)
        with self._request_scope(obj):
            return self._export(obj, format, authorized_code)

    def _export(self, obj, format, authorized_code=False):
        from research_partner.domains.generation.validity import ensure_deliverable

        ensure_deliverable(self.store, obj)
        from research_partner.domains.figures.definition import require_complete

        require_complete(obj)
        fmt = format.lower().lstrip(".")
        if fmt == "bundle":
            fmt = "zip"
        if fmt == "zip":
            return self._bundle(obj)
        require(fmt in MIME, "不支持的导出格式", "unsupported_format", 422)
        if (
            obj["kind"] == "figure"
            and fmt in {"svg", "pdf", "png"}
            and not obj["content"].get("composition")
        ):
            result = self.render_figure(obj, authorized_code=authorized_code)
            result["asset"] = result["assets"]["figure." + fmt]
            return result
        with tempfile.TemporaryDirectory(
            prefix="rp-export-", dir=self.store.workspace
        ) as folder:
            work = Path(folder)
            c, kind = obj["content"], obj["kind"]
            value = {
                "files": [],
                "warnings": [],
                "runtime": {
                    "executable": sys.executable,
                    "python_version": sys.version,
                },
            }
            provenance = {}
            if kind == "paper":
                from research_partner.domains.manuscripts.paper_sources import (
                    export_origin,
                )

                provenance["paper_source"] = export_origin(
                    obj, "all_sources" if fmt == "json" else "structured"
                )
            if fmt == "json":
                name = kind + ".json"
                (work / name).write_text(
                    json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
                )
                value["files"].append(str(work / name))
            elif kind in {
                "report",
                "note",
                "paper",
                "literature",
                "question",
                "concept",
                "growth",
                "commission",
            }:
                if (
                    kind in {"report", "note", "paper"}
                    and "manuscript_format" in obj.get("metadata", {})
                    and fmt in {"tex", "pdf"}
                ):
                    from research_partner.domains.manuscripts.paper_sources import (
                        source_state,
                    )

                    if source_state(obj)["mode"] == "structured":
                        from research_partner.domains.manuscripts.layout import export

                        return export(self, obj, fmt, work)
                if kind == "paper" and fmt in {"tex", "bib", "zip", "pdf"}:
                    return self._paper(obj, fmt, work, authorized_code)
                require(
                    fmt in {"md", "txt", "docx", "pdf"},
                    "文稿格式不支持",
                    "unsupported_format",
                    422,
                )
                md = document_markdown(obj)
                ordered_segments(c, c.get("components", []))
                materials = self._component_materials(obj, "png", work, authorized_code)
                citations = self._citation_materials(obj)
                tail = ""
                if citations:
                    tail = "\n\n## References\n\n" + "\n\n".join(
                        "; ".join(
                            str(value)
                            for value in [
                                ", ".join(item["content"].get("authors", [])),
                                item["content"].get("title", item["title"]),
                                item["content"].get("year"),
                                item["content"].get("doi")
                                or item["content"].get("url"),
                            ]
                            if value
                        )
                        for item in citations
                    )
                # Native DOCX owns numeric citations/bibliography; Markdown
                # retains its existing portable source representation.
                segments, sequence_warnings = markdown_segments(
                    obj, materials, tail if fmt in {"md", "txt"} else ""
                )
                if fmt in {"md", "txt"}:
                    md += tail
                provenance["citations"] = [
                    {
                        "object_id": item["id"],
                        "revision": item["revision"],
                        "source_sha256": digest(item),
                    }
                    for item in citations
                ]
                provenance["components"] = [
                    {
                        k: v
                        for k, v in item.items()
                        if k not in {"path", "blocks", "markdown"}
                    }
                    for item in materials
                ]
                if fmt in {"md", "txt"}:
                    from research_partner.rendering.markdown import document_export

                    value, name, image_provenance = document_export(
                        self, obj, md, materials, work, fmt, segments=segments
                    )
                    provenance.update(image_provenance)
                else:
                    inputs, images, image_info, image_warnings = self._document_images(
                        obj, md, work
                    )
                    for material in materials:
                        if material["type"] == "text":
                            source = self.store.get(
                                material["object_id"], material["revision"]
                            )
                            child_inputs, child_images, child_info, child_warnings = (
                                self._document_images(
                                    source, material["markdown"], work
                                )
                            )
                            material.update(
                                {
                                    "inputs": child_inputs,
                                    "images": child_images,
                                    "image_warnings": child_warnings,
                                    "citations": self._citation_materials(source),
                                }
                            )
                            image_info.extend(child_info)
                    provenance["inputs"] = image_info
                    math_job = self._document_math(
                        [md]
                        + [
                            item.get("caption", "")
                            if item["type"] == "image"
                            else item.get("markdown", "")
                            for item in materials
                        ],
                        work,
                    )
                    inputs.update(math_job.pop("inputs"))
                    provenance["mathematical_display"] = {
                        "kind": "mathtext_png_with_source",
                        "latex_compiled": False,
                        "runtime": math_job["math_runtime"],
                        "formula_count": len(math_job["math_images"]),
                    }
                    value = self._worker(
                        {
                            "operation": "document",
                            "object": obj,
                            "markdown": md,
                            "segments": segments,
                            "components": materials,
                            "inputs": inputs,
                            "images": images,
                            "image_warnings": image_warnings,
                            "citations": citations,
                            **math_job,
                        },
                        work,
                        "documents_python",
                    )
                    # Retain the exact helper bytes alongside the worker source,
                    # including citation-only exports and unavailable-math cases.
                    helper = work / "docx_semantics41.py"
                    helper.write_bytes(
                        module_file(
                            "research_partner.rendering.docx_semantics"
                        ).read_bytes()
                    )
                    value["files"].append(str(helper))
                    name = "document.docx"
                    if fmt == "pdf":
                        path, record = self._office_pdf(work / name, work)
                        value["files"].append(path)
                        value["office_process"] = record
                        name = "document.pdf"
                        provenance["office_process"] = record
                value.setdefault("warnings", []).extend(sequence_warnings)
            elif kind in {"diagram", "poster", "slides"} or c.get("composition"):
                if kind == "slides" and fmt in {"md", "txt"}:
                    name = "speaker_notes." + fmt
                    notes = "\n\n".join(
                        "## "
                        + str(i + 1)
                        + ". "
                        + p.get("title", p["id"])
                        + "\n\n"
                        + p.get("notes", "")
                        + "\n\n<!-- page_id: "
                        + p["id"]
                        + " -->"
                        for i, p in enumerate(c.get("pages", []))
                    )
                    (work / name).write_text(notes, encoding="utf-8")
                    value["files"] = [str(work / name)]
                elif kind == "slides":
                    require(
                        fmt in {"pptx", "pdf"},
                        "幻灯片格式不支持",
                        "unsupported_format",
                        422,
                    )
                    inputs, info = self._canvas_inputs(obj, work)
                    value = self._worker(
                        {"operation": "slides", "object": obj, "inputs": inputs},
                        work,
                        "documents_python",
                    )
                    name = "slides.pptx"
                    provenance["inputs"] = info
                    if fmt == "pdf":
                        path, record = self._office_pdf(work / name, work)
                        value["files"].append(path)
                        provenance["office_process"] = record
                        name = "slides.pdf"
                else:
                    require(
                        fmt in {"svg", "pdf", "png"},
                        "画布格式不支持",
                        "unsupported_format",
                        422,
                    )
                    inputs, info = self._canvas_inputs(obj, work)
                    value = self._worker(
                        {"operation": "canvas", "object": obj, "inputs": inputs},
                        work,
                        "svg_python",
                    )
                    provenance["inputs"] = info
                    name = "canvas." + fmt
                    if fmt == "svg" and len(c.get("pages", [])) > 1:
                        value["warnings"].append(
                            "主 SVG 是第一页；每页 SVG 分别保存在 exports 中。PDF 包含所有页。"
                        )
            else:
                raise Problem("该成果类型暂不支持此格式", "unsupported_format", 422)
            return self._publish(obj, work, value, name, provenance)

    def _reference(self, obj, ref):
        obj = self._object(obj)
        ref = {"id": ref} if isinstance(ref, str) else ref
        ident = ref.get("object_id") or ref.get("id")
        require(
            ident and ident != obj.get("id"),
            "组件引用无效或自引用",
            "invalid_component",
            422,
        )
        revision = ref.get("revision")
        if revision is None and obj.get("id"):
            pinned = [
                r
                for r in self.store.relations(obj["id"])
                if r["src"] == obj["id"]
                and r["dst"] == ident
                and r["type"] in {"contains", "uses", "cites", "depends_on"}
                and r["source_revision"] <= obj["revision"]
            ]
            if pinned:
                choices = {item["target_revision"] for item in pinned}
                require(
                    len(choices) == 1,
                    "同一依赖有不同采用版本，请明确指定修订",
                    "component_revision_required",
                    409,
                    {"object_id": ident},
                )
                revision = pinned[0]["target_revision"]
        require(
            isinstance(revision, int),
            "导出组件或引用需要明确采用修订",
            "component_revision_required",
            409,
            {"object_id": ident},
        )
        source = self.store.get(ident, revision)
        recipient = self._recipient.get()
        if recipient and source.get("project_id") != recipient[0]:
            current = self.store.get(ident)
            require(
                recipient[0] in current["metadata"].get("shared_with", []),
                "依赖未向最终接收项目共享",
                "forbidden",
                403,
            )
        if obj.get("project_id") != source.get("project_id"):
            current = self.store.get(ident)
            require(
                obj["project_id"] in current["metadata"].get("shared_with", []),
                "组件未授权跨项目使用",
                "forbidden",
                403,
            )
        if ref.get("sha256") is not None:
            require(
                ref["sha256"] == digest(source),
                "采用来源哈希与登记版本不符",
                "integrity",
                409,
            )
        return source, ref

    def _bundle_reviews(self, source):
        """Keep existing object-review and inline cycle-review contracts exact."""
        records = self.store.review_records(source["id"], source["revision"])
        require(
            isinstance(records, list), "审查记录格式无效", "bundle_review_binding", 409
        )
        refs = []
        for record in records:
            require(
                isinstance(record, dict)
                and record.get("object_id") == source["id"]
                and record.get("revision") == source["revision"]
                and record.get("source_sha256") == digest(source)
                and record.get("identity")
                == digest(
                    {
                        k: v
                        for k, v in record.items()
                        if k not in {"identity", "recorded_at"}
                    }
                )
                and record.get("scientific_approval") is False
                and record.get("user_acceptance") is False,
                "审查记录不再绑定此精确成果版本",
                "bundle_review_binding",
                409,
            )
            require(
                self._portable_value(record, []) == record,
                "审查记录含不能原样移交的私有字段",
                "sensitive_review",
                403,
            )
            if record.get("review_object_id"):
                require(
                    type(record.get("review_revision")) is int
                    and record["review_revision"] > 0
                    and isinstance(record.get("review_source_sha256"), str),
                    "审查依据缺少明确版本与哈希",
                    "bundle_review_binding",
                    409,
                )
                refs.append(
                    {
                        "id": record["review_object_id"],
                        "revision": record["review_revision"],
                        "sha256": record["review_source_sha256"],
                        "relation_type": "recorded_review",
                    }
                )
            else:
                require(
                    record.get("role") == "independent_cycle_final_review"
                    and isinstance(record.get("findings"), dict)
                    and isinstance(record.get("review_task_id"), str)
                    and isinstance(record.get("review_candidate_sha256"), str)
                    and re.fullmatch(
                        r"[a-f0-9]{64}", record["review_candidate_sha256"]
                    ),
                    "审查缺少冻结报告或已保存的协作审查合同",
                    "bundle_review_binding",
                    409,
                )
        return copy.deepcopy(records), refs

    def _matching_export_records(self, source):
        """Exact source-version records from the registry and legacy history."""
        expected_hash = digest(source)
        candidates, failures, matches = [], [], []
        if hasattr(self.store, "export_records"):
            for record in reversed(
                self.store.export_records(source["id"], source["revision"])
            ):
                candidates.append(
                    {
                        "record_revision": record["revision"],
                        "result": record["result"],
                        "storage": "export_registry",
                        "created_at": record.get("created_at"),
                    }
                )
        # An export of revision N is normally recorded by the API in revision
        # N+1. Later exports must not make the earlier exact snapshot disappear.
        with self.store.connect() as connection:
            records = connection.execute(
                "SELECT revision,snapshot FROM revisions WHERE object_id=? AND json_extract(snapshot,'$.metadata.exported_revision')=? ORDER BY revision DESC",
                (source["id"], source["revision"]),
            ).fetchall()
        for record in records:
            saved = json.loads(record["snapshot"])
            candidates.append(
                {
                    "record_revision": record["revision"],
                    "result": saved.get("metadata", {}).get("last_export", {}),
                    "storage": "legacy_revision_metadata",
                }
            )
        for record in candidates:
            exported = record["result"]
            proof = exported.get("provenance", {})
            if (
                proof.get("object_id") != source["id"]
                or proof.get("revision") != source["revision"]
                or proof.get("source_sha256") != expected_hash
            ):
                failures.append(
                    {
                        "record_revision": record["record_revision"],
                        "reason": "export_source_mismatch",
                    }
                )
                continue
            matches.append(record)
        return matches, failures

    def _registered_component_export(self, source, extension):
        """Find a verifiable export of this exact adopted source, never latest."""
        expected_hash = digest(source)
        records, failures = self._matching_export_records(source)
        for record in records:
            exported = record["result"]
            proof = exported["provenance"]
            prefix = (
                "figure"
                if source["kind"] == "figure"
                and not source["content"].get("composition")
                else "canvas"
            )
            asset = exported.get("assets", {}).get(prefix + "." + extension)
            snapshot = exported.get("assets", {}).get("source.json")
            if exported.get("status") not in {None, "generated"} or exported.get(
                "replay", {}
            ).get("failures"):
                failures.append(
                    {
                        "record_revision": record["record_revision"],
                        "reason": "component_export_failed",
                    }
                )
                continue
            if not asset:
                continue
            if not snapshot:
                failures.append(
                    {
                        "record_revision": record["record_revision"],
                        "reason": "component_export_invalid",
                        "message": "Export asset has no source snapshot",
                    }
                )
                continue
            try:
                snapshot_info, snapshot_bytes = self._asset_bytes(
                    snapshot["sha"], source
                )
                require(
                    hashlib.sha256(snapshot_bytes).hexdigest() == snapshot_info["sha"],
                    "源快照资产校验失败",
                    "integrity",
                    409,
                )
                snapshot_value = json.loads(snapshot_bytes)
                require(
                    digest(snapshot_value.get("object")) == expected_hash
                    and snapshot_value.get("provenance") == proof,
                    "导出源快照不匹配采用版本",
                    "component_export_invalid",
                    409,
                )
                info, data = self._asset_bytes(asset["sha"], source)
                require(
                    hashlib.sha256(data).hexdigest() == info["sha"],
                    "组件导出资产校验失败",
                    "integrity",
                    409,
                )
                require(
                    info["media_type"] == MIME[extension],
                    "组件导出格式不匹配",
                    "component_export_invalid",
                    409,
                )
                if extension == "pdf":
                    require(
                        data.startswith(b"%PDF"),
                        "组件不是PDF",
                        "component_export_invalid",
                        409,
                    )
                elif extension == "png":
                    require(
                        data.startswith(b"\x89PNG\r\n\x1a\n"),
                        "组件不是PNG",
                        "component_export_invalid",
                        409,
                    )
                elif extension == "svg":
                    require(
                        ET.fromstring(data).tag.rsplit("}", 1)[-1] == "svg",
                        "组件不是SVG",
                        "component_export_invalid",
                        409,
                    )
                return {
                    "info": info,
                    "data": data,
                    "source_snapshot_asset_sha256": snapshot_info["sha"],
                    "export_record_revision": record["record_revision"],
                    "export_storage": record["storage"],
                    "materialization": "registered_exact_revision_snapshot",
                }, failures
            except (Problem, ValueError, ET.ParseError, KeyError) as exc:
                failures.append(
                    {
                        "record_revision": record["record_revision"],
                        "reason": getattr(exc, "code", "component_export_invalid"),
                        "message": str(exc),
                    }
                )
        return None, failures

    @staticmethod
    def _is_registered_static_figure(source):
        """An explicit static import, never a fallback for unrendered edits."""
        content = source["content"]
        return (
            source["kind"] == "figure"
            and content.get("editable_source_available") is False
            and not any(
                content.get(key)
                for key in (
                    "script_asset",
                    "script",
                    "spec",
                    "composition",
                    "pages",
                    "nodes",
                    "edges",
                    "overlays",
                )
            )
        )

    def _registered_static_component(self, source, extension):
        """Copy the adopted revision's declared PNG/PDF bytes; do not render.

        Call only after exact export lookup has yielded no usable snapshot and
        no rejected proofs. A filesystem source_path is never an asset binding.
        """
        if not self._is_registered_static_figure(source):
            return None
        require(
            not source.get("metadata", {}).get("last_export")
            and not source.get("metadata", {}).get("exported_revision"),
            "静态来源含未匹配的旧导出证明；请核对采用版本后重试",
            "component_export_required",
            409,
            {
                "object_id": source["id"],
                "revision": source["revision"],
                "format": extension,
                "failures": [{"reason": "unmatched_legacy_export"}],
            },
        )
        content = source["content"]
        if extension == "png":
            field, value = "content.preview", content.get("preview")
        elif extension == "pdf":
            inputs = content.get("input_assets", {})
            field, value = (
                "content.input_assets.original_pdf",
                inputs.get("original_pdf") if isinstance(inputs, dict) else None,
            )
        else:
            raise Problem(
                "静态图只有已登记的 PNG 预览或原始 PDF；不转换或伪造请求格式",
                "static_source_format_unavailable",
                422,
                {"format": extension},
            )
        sha = self._sha(value)
        require(
            isinstance(sha, str) and re.fullmatch(r"[a-f0-9]{64}", sha),
            "采用的静态图版本缺少此格式的明确登记资产",
            "static_source_asset_required",
            422,
            {
                "object_id": source["id"],
                "revision": source["revision"],
                "format": extension,
                "required_field": field,
            },
        )
        info, data = self._asset_bytes(sha, source)
        require(
            hashlib.sha256(data).hexdigest() == info["sha"],
            "静态图资产内容校验失败",
            "integrity",
            409,
        )
        require(
            info["media_type"] == MIME[extension],
            "静态图登记 MIME 与请求格式不符",
            "component_export_invalid",
            409,
        )
        signature = b"\x89PNG\r\n\x1a\n" if extension == "png" else b"%PDF-"
        require(
            data.startswith(signature),
            "静态图资产字节不是声明的格式",
            "component_export_invalid",
            409,
        )
        if extension == "pdf" and source.get("metadata", {}).get("original_sha256"):
            require(
                source["metadata"]["original_sha256"] == info["sha"],
                "原始 PDF 与登记来源身份不符",
                "integrity",
                409,
            )
        return {
            "info": info,
            "data": data,
            "materialization": "registered_static_source_asset",
            "source_asset_field": field,
            "source_asset_sha256": info["sha"],
            "media_type": info["media_type"],
            "rendered": False,
        }

    def _registered_paper_image(self, source):
        """Select native PDF or PNG bytes for LaTeX, without format conversion.

        A rejected PDF proof still blocks selection. Only an explicitly static
        source lacking an original PDF may use its registered PNG as a PNG.
        """
        snapshot, failures = self._registered_component_export(source, "pdf")
        extension = "pdf"
        if snapshot or failures:
            return snapshot, failures, extension
        if self._is_registered_static_figure(source):
            inputs = source["content"].get("input_assets", {})
            has_original = isinstance(inputs, dict) and "original_pdf" in inputs
            if not has_original:
                extension = "png"
                snapshot, failures = self._registered_component_export(
                    source, extension
                )
            if not snapshot and not failures:
                snapshot = self._registered_static_component(source, extension)
        return snapshot, failures, extension

    def _component_materials(
        self, obj, extension, work, authorized_code=False, *, paper_images=False
    ):
        materials = []
        for index, ref in enumerate(obj["content"].get("components", [])):
            if isinstance(ref, dict) and ref.get("content_role") == "preparation":
                continue
            source, ref = self._reference(obj, ref)
            item = {
                "object_id": source["id"],
                "revision": source["revision"],
                "source_sha256": digest(source),
                "title": source["title"],
                "caption": ref.get("caption", source["content"].get("caption", "")),
                "after_block_id": ref.get("after_block_id"),
            }
            if source["kind"] in {"figure", "diagram", "poster"}:
                selected_extension = extension
                if paper_images:
                    snapshot, failures, selected_extension = (
                        self._registered_paper_image(source)
                    )
                else:
                    snapshot, failures = self._registered_component_export(
                        source, extension
                    )
                if snapshot:
                    info, data = snapshot["info"], snapshot["data"]
                    item.update(
                        {
                            key: value
                            for key, value in snapshot.items()
                            if key not in {"info", "data"}
                        }
                    )
                else:
                    imported_script = (
                        source["kind"] == "figure"
                        and not source["content"].get("composition")
                        and bool(
                            source["content"].get("script_asset")
                            or source["content"].get("script")
                        )
                    )
                    require(
                        not imported_script and not failures,
                        "采用版本缺少可核验的组件导出；请明确导出该源版本后重试，父文稿授权不能代替源脚本授权",
                        "component_export_required",
                        409,
                        {
                            "object_id": source["id"],
                            "revision": source["revision"],
                            "format": extension,
                            "action": "export_source_revision_then_retry",
                            "failures": failures,
                        },
                    )
                    static = self._registered_static_component(source, extension)
                    if static:
                        info, data = static["info"], static["data"]
                        item.update(
                            {
                                key: value
                                for key, value in static.items()
                                if key not in {"info", "data"}
                            }
                        )
                    else:
                        # Declarative plots/canvases may render without executing
                        # an imported script. Never pass the parent's grant.
                        result = self.export(source, extension, authorized_code=False)
                        info, data = self._asset_bytes(result["asset"]["sha"], source)
                        item["materialization"] = "rendered_declarative_component"
                name = "component-" + str(index + 1) + "." + selected_extension
                path = work / name
                path.write_bytes(data)
                item.update(
                    {
                        "path": str(path),
                        "filename": name,
                        "asset_sha256": info["sha"],
                        "type": "image",
                    }
                )
            elif source["kind"] in {"report", "note", "paper"}:
                item.update(
                    {
                        "type": "text",
                        "markdown": document_markdown(source),
                        "blocks": source["content"].get("blocks", []),
                    }
                )
            else:
                raise Problem(
                    "该组件类型不能嵌入文稿",
                    "unsupported_component",
                    422,
                    {"object_id": source["id"], "kind": source["kind"]},
                )
            materials.append(item)
        return materials

    def _bundle_reading_materials(self, obj, package, asset_records):
        """Use only saved images for a bundle's ordered reading page; never render."""
        ordered_segments(obj["content"], obj["content"].get("components", []))
        materials, warnings = [], []
        for index, ref in enumerate(obj["content"].get("components", [])):
            if isinstance(ref, dict) and ref.get("content_role") == "preparation":
                continue
            source, selected = self._reference(obj, ref)
            clean = self._portable_value(source, [])
            caption = selected.get("caption", clean["content"].get("caption", ""))
            item = {
                "object_id": source["id"],
                "revision": source["revision"],
                "title": clean["title"],
                "caption": caption,
                "after_block_id": selected.get("after_block_id"),
            }
            if source["kind"] in {"report", "note", "paper"}:
                item.update(type="text", markdown=document_markdown(clean))
            else:
                require(
                    source["kind"] in {"figure", "diagram", "poster"},
                    "该组件类型不能嵌入文稿",
                    "unsupported_component",
                    422,
                )
                cached, failures = self._registered_component_export(source, "png")
                if not cached and not failures:
                    cached = self._registered_static_component(source, "png")
                if cached and cached["info"]["sha"] in asset_records:
                    sha = cached["info"]["sha"]
                    item.update(
                        type="image",
                        asset_sha256=sha,
                        filename="component-" + str(index + 1) + ".png",
                        path=str(package / asset_records[sha]["path"]),
                    )
                else:
                    item.update(type="text", markdown=caption or clean["title"])
                    warnings.append(
                        "Reading component "
                        + source["id"]
                        + "@"
                        + str(source["revision"])
                        + " has no verified exact-revision PNG; its caption is retained at the saved position, and its registered source is included without executing it."
                        + (
                            " Rejected export records: " + json.dumps(failures)
                            if failures
                            else ""
                        )
                    )
            materials.append(item)
        return materials, warnings

    def _citation_materials(self, obj):
        refs = []
        for ref in obj["content"].get("citations", []):
            source, selection = self._reference(obj, ref)
            require(
                source["kind"] == "literature",
                "引用必须指向文献对象",
                "invalid_citation",
                422,
            )
            refs.append(source)
        return refs

    @staticmethod
    def _portable_value(value, omissions, path=()):
        """Strip credential/config fields, never serialize process environment."""
        sensitive = {
            "api_key",
            "apikey",
            "access_token",
            "refresh_token",
            "auth_token",
            "password",
            "passwd",
            "secret",
            "client_secret",
            "private_key",
            "credentials",
            "credential",
            "provider_config",
            "remote_hosts",
            "office_env",
            "environment_variables",
            "headers",
            "env",
        }
        if isinstance(value, dict):
            result = {}
            for key, item in value.items():
                lower = str(key).lower().replace("-", "_")
                if lower in sensitive or (
                    lower == "authorization" and isinstance(item, str)
                ):
                    omissions.append(
                        {
                            "path": ".".join(path + (str(key),)),
                            "reason": "credential_or_private_configuration",
                        }
                    )
                    result[key] = "[excluded from handoff]"
                elif lower in {"stdout", "stderr", "script_stdout", "script_stderr"}:
                    omissions.append(
                        {
                            "path": ".".join(path + (str(key),)),
                            "reason": "raw_execution_log_not_exported",
                        }
                    )
                else:
                    result[key] = ArtifactEngine._portable_value(
                        item, omissions, path + (str(key),)
                    )
            return result
        if isinstance(value, list):
            return [
                ArtifactEngine._portable_value(item, omissions, path + (str(i),))
                for i, item in enumerate(value)
            ]
        if isinstance(value, str):
            pattern = r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}|\bBearer\s+[A-Za-z0-9._-]{20,}"
            cleaned = re.sub(pattern, "[excluded credential]", value)
            if cleaned != value:
                omissions.append(
                    {
                        "path": ".".join(path),
                        "reason": "credential_or_private_configuration",
                    }
                )
            return cleaned
        return value

    @staticmethod
    def _check_bundle_asset(info, data, depth=0):
        """Immutable inputs are either copied exactly or rejected, never redacted."""
        name = info["filename"].lower()
        require(depth <= 3, "嵌套归档层数超过检查限制", "bundle_archive_limit", 413)
        if data.startswith(b"PK\x03\x04"):
            import io

            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                entries = archive.infolist()
                require(
                    len(entries) <= 5000
                    and sum(entry.file_size for entry in entries) <= 256 * 1024 * 1024,
                    "嵌套归档展开内容超过检查限制",
                    "bundle_archive_limit",
                    413,
                )
                for entry in entries:
                    require(
                        not Path(entry.filename).is_absolute()
                        and ".." not in Path(entry.filename).parts,
                        "嵌套归档包含越界路径",
                        "unsafe_bundle_path",
                        422,
                    )
                    if entry.is_dir():
                        continue
                    inner = archive.read(entry)
                    ArtifactEngine._check_bundle_asset(
                        {
                            "filename": entry.filename,
                            "sha": info["sha"],
                            "media_type": mimetypes.guess_type(entry.filename)[0]
                            or "application/octet-stream",
                        },
                        inner,
                        depth + 1,
                    )
        require(
            Path(name).name
            not in {
                ".env",
                "credentials.json",
                "credentials.yaml",
                "id_rsa",
                "id_ed25519",
            }
            and not name.endswith((".pem", ".key")),
            "依赖看起来包含凭据或私钥，不能加入移交包",
            "sensitive_asset",
            403,
            {"asset_sha": info["sha"], "filename": info["filename"]},
        )
        if info["media_type"].startswith("text/") or Path(name).suffix in {
            ".json",
            ".py",
            ".yaml",
            ".yml",
            ".toml",
            ".txt",
            ".md",
            ".tex",
            ".bib",
            ".csv",
            ".xml",
            ".rels",
        }:
            text = data.decode("utf-8", errors="replace")
            require(
                not re.search(
                    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bsk-[A-Za-z0-9_-]{20,}|\bBearer\s+[A-Za-z0-9._-]{20,}",
                    text,
                ),
                "依赖含凭据特征，不能加入移交包",
                "sensitive_asset",
                403,
                {"asset_sha": info["sha"]},
            )
            assignment = re.compile(
                r"(?im)(?:[\"']?(?:api[_-]?key|access_token|refresh_token|client_secret|password)[\"']?)\s*[:=]\s*[\"']([^\"'\r\n]{4,})[\"']"
            )
            require(
                not assignment.search(text),
                "文本依赖包含显式凭据赋值；原资产未被修改",
                "sensitive_asset",
                403,
                {"asset_sha": info["sha"]},
            )
            if Path(name).suffix == ".json":
                try:
                    obj = json.loads(text)
                except ValueError:
                    return
                omitted = []
                ArtifactEngine._portable_value(obj, omitted)
                secret = [
                    item
                    for item in omitted
                    if item["reason"] == "credential_or_private_configuration"
                ]
                require(
                    not secret,
                    "JSON 依赖包含凭据或私有配置；原资产未被修改",
                    "sensitive_asset",
                    403,
                    {"asset_sha": info["sha"], "fields": [x["path"] for x in secret]},
                )

    def _bundle(self, obj):
        """Complete registered dependency closure; no source execution or host reads."""
        import posixpath

        (
            nodes,
            asset_records,
            failures,
            edges,
            omissions,
            registered_exports,
            review_records,
        ) = {}, {}, [], [], [], {}, {}
        queue = [obj]

        def key(source):
            return source["id"] + "@" + str(source["revision"])

        def fail(source, exc, location):
            failures.append(
                {
                    "object_id": source["id"],
                    "revision": source["revision"],
                    "location": location,
                    "code": exc.code,
                    "message": str(exc),
                    "details": exc.details,
                }
            )

        while queue:
            source = queue.pop(0)
            node_key = key(source)
            if node_key in nodes:
                continue
            require(
                len(nodes) < 1000, "移交依赖超过1000个采用版本", "bundle_limit", 413
            )
            nodes[node_key] = source
            registered_exports[node_key], _ = self._matching_export_records(source)
            try:
                refs = self._declared_references(source)
                review_records[node_key], review_refs = self._bundle_reviews(source)
                refs.extend(review_refs)
            except Problem as exc:
                fail(source, exc, "declared_sources_or_reviews")
                refs = []
                review_records[node_key] = []
            explicit_ids = {
                ref if isinstance(ref, str) else ref.get("id", ref.get("object_id"))
                for ref in refs
            }
            # The stored content is authoritative for historical revisions. A
            # newer relation is not silently retrofitted onto an older source.
            for relation in self.store.relations(source["id"]):
                if (
                    relation["src"] == source["id"]
                    and relation["type"] in {"contains", "uses", "cites", "depends_on"}
                    and relation["dst"] not in explicit_ids
                    and relation["source_revision"] <= source["revision"]
                ):
                    refs.append(
                        {
                            "id": relation["dst"],
                            "revision": relation["target_revision"],
                            "relation_type": relation["type"],
                        }
                    )
            for index, ref in enumerate(refs):
                try:
                    target, selection = self._reference(source, ref)
                    edges.append(
                        {
                            "source": node_key,
                            "target": key(target),
                            "type": selection.get("relation_type", "adopted_reference"),
                        }
                    )
                    queue.append(target)
                except Problem as exc:
                    fail(source, exc, "references." + str(index))
            try:
                dependency_source = copy.deepcopy(source)
                if (
                    dependency_source.get("metadata", {})
                    .get("last_export", {})
                    .get("provenance", {})
                    .get("bundle")
                ):
                    dependency_source["metadata"].pop("last_export")
                references = list(self._asset_refs(dependency_source))
                from research_partner.domains.manuscripts.sources import (
                    asset_declarations,
                )

                references.extend(
                    (("content", "registered_document_assets"), sha)
                    for sha in sorted(asset_declarations(source["content"]))
                )
                for export_index, export_record in enumerate(
                    registered_exports[node_key]
                ):
                    references.extend(
                        self._asset_refs(
                            export_record["result"],
                            ("registered_exports", str(export_index)),
                        )
                    )
            except Problem as exc:
                fail(source, exc, "assets")
                references = []
            for location, sha in references:
                try:
                    info, data = self._asset_bytes(sha, source)
                    # Repeated handoff exports should not recursively package old
                    # handoff ZIPs. Their adopted source/assets are collected here.
                    if (
                        location[0] == "registered_exports"
                        or location[:2] == ("metadata", "last_export")
                    ) and (
                        info["metadata"].get("role") == "handoff_bundle"
                        or info["filename"]
                        in {"handoff.zip", "markdown-package.zip", "text-package.zip"}
                    ):
                        continue
                    self._check_bundle_asset(info, data)
                    filename = re.sub(r"[^A-Za-z0-9_.-]", "_", info["filename"])
                    require(
                        filename not in {"", ".", ".."},
                        "依赖文件名不合法",
                        "invalid_filename",
                        422,
                    )
                    entry = asset_records.setdefault(
                        sha,
                        {
                            "sha256": sha,
                            "path": "assets/" + sha + "/" + filename,
                            "filename": info["filename"],
                            "media_type": info["media_type"],
                            "size": len(data),
                            "used_by": [],
                        },
                    )
                    usage = {"object": node_key, "field": ".".join(location)}
                    if usage not in entry["used_by"]:
                        entry["used_by"].append(usage)
                except Problem as exc:
                    fail(source, exc, ".".join(location))
                except OSError:
                    fail(
                        source,
                        Problem(
                            "登记资产字节不可读取；未创建成功包",
                            "missing_asset",
                            409,
                            {"asset_sha": sha},
                        ),
                        ".".join(location),
                    )
        require(
            not failures,
            "移交包依赖不完整或未授权；未创建成功包",
            "bundle_dependencies",
            409,
            {"status": "blocked", "failures": failures},
        )
        require(
            sum(item["size"] for item in asset_records.values()) <= 1024**3,
            "移交资产超过1GB限制",
            "bundle_limit",
            413,
        )
        with tempfile.TemporaryDirectory(
            prefix="rp-handoff-", dir=self.store.workspace
        ) as folder:
            work = Path(folder)
            package = work / "package"
            package.mkdir()
            object_paths = {
                node_key: "objects/"
                + re.sub(r"[^A-Za-z0-9_.-]", "_", source["id"])
                + "_"
                + digest(source["id"])[:8]
                + "-r"
                + str(source["revision"])
                for node_key, source in nodes.items()
            }
            for sha, item in asset_records.items():
                path = package / item["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                # Permission and identity were checked against each source above.
                data = (self.store.blobs / sha).read_bytes()
                require(
                    hashlib.sha256(data).hexdigest() == sha,
                    "打包期间资产身份变化",
                    "integrity",
                    409,
                )
                path.write_bytes(data)
            node_records, jobs, reading_notes = [], {}, []
            for node_key, source in nodes.items():
                directory = package / object_paths[node_key]
                directory.mkdir(parents=True, exist_ok=True)
                local_omissions = []
                clean = self._portable_value(source, local_omissions)
                omissions.extend(
                    {"object": node_key, **item} for item in local_omissions
                )
                original_name = object_paths[node_key] + "/object.json"
                (directory / "object.json").write_text(
                    json.dumps(clean, ensure_ascii=False, indent=2) + "\n"
                )

                def rewrite(value):
                    if isinstance(value, dict):
                        return {k: rewrite(v) for k, v in value.items()}
                    if isinstance(value, list):
                        return [rewrite(v) for v in value]
                    if isinstance(value, str):
                        sha = self._sha(value)
                        if sha in asset_records:
                            return posixpath.relpath(
                                asset_records[sha]["path"], object_paths[node_key]
                            )
                    return value

                portable = rewrite(clean)
                portable["bundle_references"] = [
                    {
                        "object": edge["target"],
                        "path": posixpath.relpath(
                            object_paths[edge["target"]] + "/portable.json",
                            object_paths[node_key],
                        ),
                    }
                    for edge in edges
                    if edge["source"] == node_key
                ]
                (directory / "portable.json").write_text(
                    json.dumps(portable, ensure_ascii=False, indent=2) + "\n"
                )
                record = {
                    "key": node_key,
                    "id": source["id"],
                    "revision": source["revision"],
                    "project_id": source.get("project_id"),
                    "kind": source["kind"],
                    "title": source["title"],
                    "source_sha256": digest(source),
                    "source_snapshot_sha256": digest(clean),
                    "snapshot": original_name,
                    "portable_source": object_paths[node_key] + "/portable.json",
                    "redacted": bool(local_omissions),
                    "review_records": review_records[node_key],
                }
                record["registered_exports"] = []
                from research_partner.domains.figures.definition import (
                    FigureDefinitions,
                    is_definition,
                )

                if is_definition(source):
                    fixed = FigureDefinitions(self.store).read(
                        source["id"], source["revision"]
                    )
                    raw = fixed["definition_text"].encode("utf-8")
                    require(
                        digest(raw) == source["content"]["definition_sha256"],
                        "原定义编码字节不能保真打包",
                        "integrity",
                        409,
                    )
                    self._check_bundle_asset(
                        {
                            "filename": "figure.yaml",
                            "sha": digest(raw),
                            "media_type": "application/json",
                        },
                        raw,
                    )
                    destination = directory / "main/figure.yaml"
                    destination.parent.mkdir()
                    destination.write_bytes(raw)
                    record["figure_definition"] = {
                        "path": object_paths[node_key] + "/main/figure.yaml",
                        "sha256": digest(raw),
                        "authority_kind": "file",
                        "format": "json_yaml_subset",
                    }
                for export_record in registered_exports[node_key]:
                    export_omissions = []
                    provenance = self._portable_value(
                        export_record["result"].get("provenance", {}), export_omissions
                    )
                    omissions.extend(
                        {
                            "object": node_key,
                            "export_record_revision": export_record["record_revision"],
                            **entry,
                        }
                        for entry in export_omissions
                    )
                    record["registered_exports"].append(
                        {
                            "storage": export_record["storage"],
                            "record_revision": export_record["record_revision"],
                            "created_at": export_record.get("created_at"),
                            "provenance": provenance,
                            "assets": [
                                {"sha256": sha, "path": asset_records[sha]["path"]}
                                for sha in dict.fromkeys(
                                    sha
                                    for _, sha in self._asset_refs(
                                        export_record["result"]
                                    )
                                )
                                if sha in asset_records
                            ],
                        }
                    )
                node_records.append(record)
                c = clean["content"]
                if source["kind"] in {
                    "report",
                    "note",
                    "paper",
                    "question",
                    "concept",
                    "literature",
                    "commission",
                    "growth",
                    "feedback",
                }:
                    from research_partner.rendering.markdown import reading_markdown

                    def markdown_destination(image, path):
                        require(
                            image["sha"] in asset_records,
                            "文稿图像未包含在采用资产闭包",
                            "bundle_dependencies",
                            409,
                        )
                        return posixpath.relpath(
                            asset_records[image["sha"]]["path"], object_paths[node_key]
                        )

                    materials, material_warnings = self._bundle_reading_materials(
                        clean, package, asset_records
                    )
                    segments, sequence_warnings = markdown_segments(clean, materials)
                    content_md, markdown_images = reading_markdown(
                        self, source, materials, segments, work, markdown_destination
                    )
                    reading_notes.extend(
                        node_key + ": " + warning
                        for warning in material_warnings + sequence_warnings
                    )
                    (directory / "content.md").write_text(content_md, encoding="utf-8")
                    record["markdown"] = {
                        "path": object_paths[node_key] + "/content.md",
                        "images": markdown_images,
                    }
                if source["kind"] == "figure" and not c.get("composition"):
                    inputs = {}
                    values = c.get("input_assets", {})
                    values = (
                        values.items()
                        if isinstance(values, dict)
                        else [(str(i), v) for i, v in enumerate(values)]
                    )
                    for alias, value in values:
                        sha = self._sha(value)
                        require(
                            isinstance(sha, str) and sha in asset_records,
                            "图形输入缺少有效登记资产",
                            "unregistered_dependency",
                            422,
                            {
                                "object_id": source["id"],
                                "revision": source["revision"],
                                "input": str(alias),
                            },
                        )
                        if isinstance(value, dict):
                            alias = value.get("name", value.get("alias", alias))
                        inputs[str(alias)] = asset_records[sha]["path"]
                        inputs.setdefault(
                            asset_records[sha]["filename"], asset_records[sha]["path"]
                        )
                    script = self._sha(c.get("script_asset") or c.get("script"))
                    layers = c.get("overlays", [])
                    if isinstance(layers, dict):
                        layers = [
                            {"target": k, "properties": v} for k, v in layers.items()
                        ]
                    jobs[node_key] = {
                        "operation": "figure",
                        "script": asset_records[script]["path"] if script else None,
                        "inputs": inputs,
                        "spec": c.get("spec"),
                        "parameters": self._portable_value(c.get("parameters", {}), []),
                        "overlays": layers,
                        "requires_code_approval": bool(script),
                        "runtime_requirements": ["matplotlib", "numpy"],
                    }
                    if self._is_registered_static_figure(source):
                        jobs[node_key].update(
                            runtime_requirements=[],
                            blocked_reason="Registered static figure: preserved PNG/PDF assets are available; no editable renderer source is registered.",
                        )
                elif source["kind"] in {"diagram", "poster", "slides"} or c.get(
                    "composition"
                ):
                    inputs = {}
                    for page in c.get("pages", []):
                        for item in page.get("objects", []):
                            if item.get("type") == "image":
                                sha = self._sha(
                                    item.get("asset")
                                    or item.get("src")
                                    or item.get("asset_id")
                                )
                                inputs[item["id"]] = asset_records[sha]["path"]
                    jobs[node_key] = {
                        "operation": "slides"
                        if source["kind"] == "slides"
                        else "canvas",
                        "object": clean,
                        "inputs": inputs,
                        "runtime_requirements": ["python-pptx", "Pillow"]
                        if source["kind"] == "slides"
                        else ["libcairo", "librsvg"],
                    }
                elif source["kind"] in {"report", "note"} and not c.get("components"):
                    md = document_markdown(clean)
                    _, images, image_info, image_warnings = self._document_images(
                        source, md, work
                    )
                    inputs = {
                        entry["alias"]: asset_records[entry["sha"]]["path"]
                        for entry in image_info
                    }
                    math_job = self._document_math([md], work)
                    for alias, path in math_job.pop("inputs").items():
                        data = Path(path).read_bytes()
                        info = self.store.add_asset(
                            data,
                            Path(path).name,
                            "image/png",
                            {
                                "project_id": source.get("project_id"),
                                "object_id": source["id"],
                                "revision": source["revision"],
                                "source_sha256": digest(source),
                                "role": "document_math_display",
                                "latex_compiled": False,
                            },
                        )
                        sha = info["sha"]
                        filename = re.sub(r"[^A-Za-z0-9_.-]", "_", info["filename"])
                        entry = asset_records.setdefault(
                            sha,
                            {
                                "sha256": sha,
                                "path": "assets/" + sha + "/" + filename,
                                "filename": info["filename"],
                                "media_type": "image/png",
                                "size": len(data),
                                "used_by": [],
                            },
                        )
                        usage = {
                            "object": node_key,
                            "field": "derived_document_math." + alias,
                        }
                        if usage not in entry["used_by"]:
                            entry["used_by"].append(usage)
                        destination = package / entry["path"]
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.write_bytes(data)
                        inputs[alias] = entry["path"]
                    jobs[node_key] = {
                        "operation": "document",
                        "object": clean,
                        "markdown": md,
                        "inputs": inputs,
                        "images": images,
                        "image_warnings": image_warnings,
                        "citations": [
                            self._portable_value(item, [])
                            for item in self._citation_materials(source)
                        ],
                        "runtime_requirements": ["python-docx"],
                        **math_job,
                    }
                if node_key in jobs:
                    prior_renderer = (
                        source.get("metadata", {})
                        .get("last_export", {})
                        .get("provenance", {})
                        .get("renderer_asset_sha256")
                    )
                    jobs[node_key]["renderer"] = (
                        asset_records[prior_renderer]["path"]
                        if prior_renderer in asset_records
                        else "runtime/render_worker.py"
                    )
                    jobs[node_key]["renderer_selection"] = (
                        "recorded_source"
                        if prior_renderer in asset_records
                        else "current_packaged_implementation"
                    )
                if node_key in jobs and any(
                    item["reason"] == "credential_or_private_configuration"
                    and item["path"].startswith("content.")
                    for item in local_omissions
                ):
                    jobs[node_key]["blocked_reason"] = (
                        "Required source fields were redacted; restore authorized local values before rendering."
                    )
            (package / "runtime").mkdir()
            worker_bytes = module_file("research_partner.rendering.worker").read_bytes()
            (package / "runtime/render_worker.py").write_bytes(worker_bytes)
            (package / "runtime/figure_interaction.py").write_bytes(
                module_file("research_partner.rendering.interaction").read_bytes()
            )
            (package / "runtime/process_output.py").write_bytes(
                module_file("research_partner.execution.process_output").read_bytes()
            )
            (package / "runtime/render_contract.py").write_bytes(
                module_file("research_partner.rendering.contract").read_bytes()
            )
            (package / "runtime/docx_semantics41.py").write_bytes(
                module_file("research_partner.rendering.docx_semantics").read_bytes()
            )
            (package / "runtime/asset_references.py").write_bytes(
                bundle_reference_reader()
            )
            (package / "replay.py").write_text(BUNDLE_REPLAY_SOURCE)
            root_record = next(
                record for record in node_records if record["key"] == key(obj)
            )
            root_markdown = root_record.get("markdown", {}).get("path")
            if root_markdown:
                reading_entry = (
                    f"After fully extracting this archive, read the root document here: [{root_markdown}]({root_markdown}). "
                    "This is the root object's `markdown.path` in `manifest.json`; its registered image paths are relocated for this package. "
                    "For supporting documents, use each adopted object's `markdown.path` when present.\n\n"
                )
            else:
                reading_entry = (
                    "The root object has no Markdown reading page. Find its exact identity in `manifest.json` under `root` and `objects`. "
                    f"Inspect [{root_record['portable_source']}]({root_record['portable_source']}) for the relocated structured source, "
                    f"or [{root_record['snapshot']}]({root_record['snapshot']}) for the preserved source identity. "
                    "The root object's `registered_exports` lists any saved rendered outputs; retain their original directory context when needed. "
                    "Supporting documents may have their own `markdown.path` reading pages.\n\n"
                )
            (package / "README.md").write_text(
                "# Research artifact handoff\n\n"
                + reading_entry
                + "`portable_source` points to machine-readable relocation structure, not the recommended human reading page. "
                "`object.json` preserves source identity fields; `portable.json` replaces registered asset references with local relative paths. "
                "Manifest file paths are relative to the extracted archive; relocatable source references are relative to their containing source file. "
                "Any redactions are listed in `manifest.omissions`.\n\n"
                "Registered export assets under `assets/` preserve their original bytes and SHA. Their internal links may depend on the original export directory layout; "
                "opening a raw `document.md` in a hashed asset directory is not guaranteed to show its images. "
                "Use the root object's `markdown.path` reading page when available instead of treating every Markdown asset as a portable reading entry.\n\n"
                "Verify after extraction: `python replay.py --verify`. Optional rendering: `python replay.py --render 'OBJECT_ID@REVISION' --output new-output-directory`; "
                "select an environment satisfying that job's runtime_requirements. Imported scripts additionally require `--approve-code`. "
                "No environment, service configuration, credentials or dependency installation is bundled. Existing output folders are rejected. "
                "The verifier checks bytes and paths, not scientific validity or visual quality.\n\n"
                "Source transfer is complete only for the registered dependency closure. External runtime dependencies are stated, not shipped or claimed available on the receiving computer. "
                "PDFs and Office exports are recorded snapshots; editable JSON/Markdown/LaTeX/Python sources remain alongside them.\n",
                encoding="utf-8",
            )
            if obj["kind"] == "figure" and obj.get("content", {}).get("caption"):
                (package / "CAPTION.md").write_text(
                    "# " + obj["title"] + "\n\n" + obj["content"]["caption"] + "\n",
                    encoding="utf-8",
                )
            paper_notes = reading_notes
            if obj["kind"] in {
                "paper",
                "report",
                "note",
            } and "manuscript_format" in obj.get("metadata", {}):
                from research_partner.domains.manuscripts.paper_sources import (
                    source_state,
                )

                state = source_state(obj)
                if state["mode"] == "structured":
                    from research_partner.domains.manuscripts.layout import prepare

                    prepared = prepare(self, self._portable_value(obj, []), package)
                    (package / "paper-structured.tex").write_text(
                        prepared["tex"], encoding="utf-8"
                    )
                    (package / "paper-source.json").write_text(
                        json.dumps(
                            {
                                **state,
                                "format_config": prepared["format"],
                                "compiled": False,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                        + "\n"
                    )
                    if obj["content"].get("latex"):
                        (package / "paper-manual.tex").write_text(
                            self._portable_value(obj["content"]["latex"], []),
                            encoding="utf-8",
                        )
                    paper_notes += [
                        "Styled LaTeX source and native adopted images are included; package generation does not compile or approve the paper. XeLaTeX/fontspec/xeCJK and the configured fonts are required on the receiver."
                    ]
                elif obj["kind"] == "paper":
                    paper_notes += self._bundle_paper_sources(
                        self._portable_value(obj, []), package, nodes, asset_records
                    )
            elif obj["kind"] == "paper":
                paper_notes += self._bundle_paper_sources(
                    self._portable_value(obj, []), package, nodes, asset_records
                )
            checksums = {
                str(path.relative_to(package)): hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
                for path in sorted(package.rglob("*"))
                if path.is_file()
            }
            manifest = {
                "schema": "research-partner-handoff/1",
                "root": key(obj),
                "objects": node_records,
                "dependencies": edges,
                "assets": list(asset_records.values()),
                "files": checksums,
                "jobs": jobs,
                "omissions": omissions,
                "warnings": paper_notes,
                "status": {
                    "registered_dependencies": "complete",
                    "receiving_environment": "unverified",
                    "scientific_review": "not_implied",
                    "source_execution_during_packaging": False,
                    "editable_sources": "redacted"
                    if any(
                        x["reason"] == "credential_or_private_configuration"
                        for x in omissions
                    )
                    else "complete",
                },
                "producer": {
                    "python_version": sys.version,
                    "renderer_sha256": hashlib.sha256(worker_bytes).hexdigest(),
                },
                "recorded_environments": [
                    {
                        "object": key(source),
                        "runtime": self._portable_value(
                            source.get("metadata", {})
                            .get("last_export", {})
                            .get("provenance", {})
                            .get("runtime", {}),
                            [],
                        ),
                    }
                    for source in nodes.values()
                ],
            }
            manifest_data = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
            (package / "manifest.json").write_text(manifest_data)
            (work / "bundle_manifest.json").write_text(manifest_data)
            verified = run_process(
                [sys.executable, "-I", str(package / "replay.py"), "--verify"],
                cwd=package,
                timeout=30,
            )
            require(
                verified["returncode"] == 0,
                "移交包自身依赖验证失败；未发布成功包",
                "bundle_integrity",
                409,
                {"stderr": verified.get("stderr", "")[-4000:]},
            )
            with zipfile.ZipFile(
                work / "handoff.zip", "w", zipfile.ZIP_DEFLATED
            ) as archive:
                for path in sorted(package.rglob("*")):
                    if path.is_file():
                        archive.write(path, path.relative_to(package))
            clean_root = self._portable_value(obj, [])
            result = self._publish(
                clean_root,
                work,
                {
                    "files": [
                        str(work / "handoff.zip"),
                        str(work / "bundle_manifest.json"),
                    ],
                    "warnings": (
                        [
                            "Source fields or raw logs were excluded; inspect manifest.omissions."
                        ]
                        if omissions
                        else []
                    )
                    + paper_notes,
                    "runtime": {"python_version": sys.version},
                },
                "handoff.zip",
                {
                    "source_sha256": digest(obj),
                    "source_snapshot_redacted": clean_root != obj,
                    "compiled": False,
                    "components": [
                        {
                            "object_id": nodes[e["target"]]["id"],
                            "revision": nodes[e["target"]]["revision"],
                        }
                        for e in edges
                        if e["source"] == key(obj)
                    ],
                    "bundle": {
                        "schema": manifest["schema"],
                        "root": key(obj),
                        "object_count": len(nodes),
                        "asset_count": len(asset_records),
                        "registered_dependencies": "complete",
                        "receiving_environment": "unverified",
                        "source_execution_during_packaging": False,
                    },
                },
            )
            # Preserve the output project and distinguish this package from source ZIPs.
            with self.store.transaction() as connection:
                metadata = dict(result["asset"]["metadata"])
                metadata["role"] = "handoff_bundle"
                connection.execute(
                    "UPDATE assets SET metadata=? WHERE sha=?",
                    (encoded(metadata), result["asset"]["sha"]),
                )
            result["asset"] = self.store.asset(result["asset"]["sha"])
            result["assets"]["handoff.zip"] = result["asset"]
            return result

    def _bundle_paper_sources(self, obj, package, nodes, asset_records):
        """Create portable paper sources without executing component Python."""
        c = obj["content"]
        notes = []
        component_materials = []
        from research_partner.domains.manuscripts.paper_sources import source_state

        paper_state = source_state(obj)
        from research_partner.domains.manuscripts.formatting import (
            tex_inline,
            tex_markdown,
            legacy_tex_font_preamble,
        )

        if "xelatex" in Path(self.config.get("latex") or "").name.lower():
            from research_partner.domains.manuscripts.fonts import stage_fonts

            stage_fonts(package)
        body = []
        sequence, sequence_warnings = ordered_segments(c, c.get("components", []))
        notes.extend(sequence_warnings)
        for segment in sequence:
            if segment["kind"] == "block":
                block = segment["block"]
                body.append(
                    r"\section{" + tex_inline(block.get("text", "")) + "}"
                    if block.get("kind") == "heading"
                    else tex_markdown(block.get("text", ""))
                )
                for citation in block.get("citation_keys", []):
                    require(
                        re.fullmatch(r"[A-Za-z0-9_.:-]+", citation), "引用 key 不合法"
                    )
                    body.append(r"\cite{" + citation + "}")
                continue
            if segment["kind"] == "markdown":
                body.append(tex_markdown(segment["markdown"]))
                continue
            if segment["kind"] == "unplaced_heading":
                body.append(r"\section{" + tex_inline(segment["text"]) + "}")
                continue
            index = segment["index"]
            ref = c["components"][index]
            source, selected = self._reference(obj, ref)
            if source["kind"] in {"report", "note", "paper"}:
                source = self._portable_value(source, [])
                body.append(r"\section{" + tex_inline(source["title"]) + "}")
                body.extend(
                    tex_markdown(b.get("text", ""))
                    for b in source["content"].get("blocks", [])
                    if b.get("content_role") != "preparation"
                )
            else:
                cached, failures, extension = self._registered_paper_image(source)
                saved = (
                    cached["info"]
                    if cached and cached["info"]["sha"] in asset_records
                    else None
                )
                if saved:
                    sha = self._sha(saved)
                    name = "component-" + str(index + 1) + "." + extension
                    (package / name).write_bytes(
                        (package / asset_records[sha]["path"]).read_bytes()
                    )
                    component_materials.append(
                        {
                            "object_id": source["id"],
                            "revision": source["revision"],
                            "source_sha256": digest(source),
                            "filename": name,
                            "asset_sha256": sha,
                            **{
                                key: value
                                for key, value in cached.items()
                                if key not in {"info", "data"}
                            },
                        }
                    )
                    body.append(
                        r"\begin{figure}[htbp]\centering\includegraphics[width=\linewidth]{"
                        + name
                        + r"}\caption{"
                        + tex_inline(
                            latex_caption(
                                selected.get(
                                    "caption",
                                    source["content"].get("caption", source["title"]),
                                )
                            )
                        )
                        + r"}\end{figure}"
                    )
                else:
                    # Retain the scientific caption at its saved position; a
                    # missing image is reported in metadata, never invented.
                    body.append(
                        tex_inline(
                            latex_caption(
                                selected.get(
                                    "caption",
                                    source["content"].get("caption", source["title"]),
                                )
                            )
                        )
                    )
                    notes.append(
                        "Paper component "
                        + source["id"]
                        + "@"
                        + str(source["revision"])
                        + " has no verified exact-revision image snapshot; its source and data are included and must be explicitly rendered before final paper compilation."
                        + (
                            " Rejected export records: " + json.dumps(failures)
                            if failures
                            else ""
                        )
                    )
        citations = self._citation_materials(obj)
        bib = c.get("bibtex", "")
        if c.get("bibtex_asset"):
            bib = self._asset_bytes(c["bibtex_asset"], obj)[1].decode("utf-8")
        if citations:
            from research_partner.domains.literature.literature import Literature

            bib += "\n" + Literature(self.store).bibtex(citations)
            body.append(
                r"\nocite{"
                + ",".join(
                    item["metadata"].get("citation_key", item["id"])
                    for item in citations
                )
                + "}"
            )
        structured_tex = (
            "\\documentclass{article}\n"
            + legacy_tex_font_preamble(self.config.get("latex"), portable_fonts=True)
            + "\\usepackage{graphicx}\n\\usepackage{amsmath,amssymb}\n\\title{"
            + tex_inline(obj["title"])
            + "}\n\\begin{document}\n\\maketitle\n"
            + "\n\n".join(body)
            + "\n\\bibliographystyle{plain}\n\\bibliography{references}\n\\end{document}\n"
        )
        manual = c.get("latex") or ""
        (package / "paper-structured.tex").write_text(structured_tex, encoding="utf-8")
        if manual:
            (package / "paper-manual.tex").write_text(manual, encoding="utf-8")
        if paper_state["mode"] != "unselected":
            from research_partner.domains.manuscripts.paper_sources import (
                selected_latex,
            )

            selected, _ = selected_latex(obj)
            (package / "paper.tex").write_text(
                selected if selected is not None else structured_tex, encoding="utf-8"
            )
        else:
            notes.append(
                "Paper source is unselected: paper-structured.tex and paper-manual.tex are independent sources. No authoritative paper.tex was selected; select/save a source before compilation."
            )
        (package / "paper-source.json").write_text(
            json.dumps(paper_state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (package / "paper-component-materials.json").write_text(
            json.dumps(component_materials, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        (package / "references.bib").write_text(bib, encoding="utf-8")
        for name, value in c.get("latex_assets", {}).items():
            require(
                Path(name).name == name
                and name
                not in {
                    "paper.tex",
                    "paper-structured.tex",
                    "paper-manual.tex",
                    "paper-source.json",
                    "paper-component-materials.json",
                    "references.bib",
                    "manifest.json",
                    "replay.py",
                    "README.md",
                },
                "LaTeX 附件名称不安全",
                "unsafe_bundle_path",
                422,
            )
            sha = self._sha(value)
            destination = package / name
            require(
                not destination.exists(),
                "LaTeX 附件文件名冲突",
                "bundle_collision",
                422,
            )
            destination.write_bytes((package / asset_records[sha]["path"]).read_bytes())
        if not self.config.get("latex"):
            notes.append(
                "LaTeX compiler is unavailable in the packaging environment; paper sources were not compiled."
            )
        return notes

    def _paper(self, obj, fmt, work, authorized_code=False):
        c = obj["content"]
        from research_partner.domains.manuscripts.paper_sources import (
            selected_latex,
            export_origin,
        )

        if fmt == "bib":
            citations = self._citation_materials(obj)
            bib = c.get("bibtex", "")
            if c.get("bibtex_asset"):
                bib = self._asset_bytes(c["bibtex_asset"], obj)[1].decode("utf-8")
            if citations:
                from research_partner.domains.literature.literature import Literature

                bib += "\n" + Literature(self.store).bibtex(citations)
            path = work / "references.bib"
            path.write_text(bib, encoding="utf-8")
            return self._publish(
                obj,
                work,
                {"files": [str(path)], "warnings": [], "runtime": {}},
                "references.bib",
                {
                    "paper_source": export_origin(obj, "references"),
                    "bibtex_sha256": hashlib.sha256(bib.encode()).hexdigest(),
                    "compiled": False,
                    "citations": [
                        {
                            "object_id": item["id"],
                            "revision": item["revision"],
                            "source_sha256": digest(item),
                        }
                        for item in citations
                    ],
                },
            )
        tex, paper_state = selected_latex(obj)
        if tex is None:
            ordered_segments(c, c.get("components", []))
        if fmt == "pdf":
            compiler = self.config.get("latex")
            require(
                compiler and (Path(compiler).is_file() or shutil.which(compiler)),
                "缺少 LaTeX 编译器；可导出 .tex/.bib 源稿，不能生成已编译论文 PDF",
                "latex_unavailable",
                503,
                {
                    "needed": "pdflatex, xelatex, or lualatex",
                    "available_exports": ["tex", "bib", "zip", "docx"],
                },
            )
        materials = (
            self._component_materials(
                obj, "pdf", work, authorized_code, paper_images=True
            )
            if fmt != "bib"
            else []
        )
        citations = self._citation_materials(obj)
        warnings = []
        font_files = []
        if tex is None:
            from research_partner.domains.manuscripts.formatting import (
                tex_inline,
                tex_markdown,
                legacy_tex_font_preamble,
                tex_figure_labels,
            )

            if "xelatex" in Path(self.config.get("latex") or "").name.lower():
                from research_partner.domains.manuscripts.fonts import stage_fonts

                font_files = stage_fonts(work)
            body = []
            figure_aliases = set()
            sequence, warnings = ordered_segments(c, materials)
            for segment in sequence:
                if segment["kind"] == "block":
                    b = segment["block"]
                    if b.get("kind") == "heading":
                        body.append(r"\section{" + tex_inline(b.get("text", "")) + "}")
                    else:
                        body.append(tex_markdown(b.get("text", "")))
                    for key in b.get("citation_keys", []):
                        require(
                            re.fullmatch(r"[A-Za-z0-9_.:-]+", key), "BibTeX key 不合法"
                        )
                        body.append(r"\cite{" + key + "}")
                    continue
                if segment["kind"] == "markdown":
                    body.append(tex_markdown(segment["markdown"]))
                    continue
                if segment["kind"] == "unplaced_heading":
                    body.append(r"\section{" + tex_inline(segment["text"]) + "}")
                    continue
                item = materials[segment["index"]]
                if item["type"] == "image":
                    labels = tex_figure_labels(
                        segment["index"], item["object_id"], figure_aliases
                    )
                    body.append(
                        r"\begin{figure}[htbp]\centering\includegraphics[width=\linewidth]{"
                        + item["filename"]
                        + r"}\caption{"
                        + tex_inline(latex_caption(item["caption"] or item["title"]))
                        + r"}"
                        + labels
                        + r"\end{figure}"
                    )
                else:
                    body.append(r"\section{" + tex_inline(item["title"]) + "}")
                    body.extend(
                        tex_markdown(block.get("text", ""))
                        for block in item["blocks"]
                        if block.get("content_role") != "preparation"
                    )
            if citations:
                keys = [
                    item["metadata"].get("citation_key", item["id"])
                    for item in citations
                ]
                require(
                    all(re.fullmatch(r"[A-Za-z0-9_.:-]+", key) for key in keys),
                    "引用 key 不合法",
                )
                body.append(r"\nocite{" + ",".join(keys) + "}")
            tex = (
                "\\documentclass{article}\n"
                + legacy_tex_font_preamble(
                    self.config.get("latex"), portable_fonts=True
                )
                + "\\usepackage{graphicx}\n\\usepackage{amsmath,amssymb}\n\\title{"
                + tex_inline(obj["title"])
                + "}\n\\begin{document}\n\\maketitle\n"
                + "\n\n".join(body)
                + "\n\\bibliographystyle{plain}\n\\bibliography{references}\n\\end{document}\n"
            )
        bib = c.get("bibtex", "")
        if c.get("bibtex_asset"):
            _, data = self._asset_bytes(c["bibtex_asset"], obj)
            bib = data.decode("utf-8")
        if citations:
            from research_partner.domains.literature.literature import Literature

            bib += "\n" + Literature(self.store).bibtex(citations)
        (work / "paper.tex").write_text(tex, encoding="utf-8")
        (work / "references.bib").write_text(bib, encoding="utf-8")
        input_info = [
            {
                "name": item["filename"],
                "sha": item["asset_sha256"],
                "object_id": item["object_id"],
                "revision": item["revision"],
            }
            for item in materials
            if item["type"] == "image"
        ]
        for name, sha in c.get("latex_assets", {}).items():
            require(
                Path(name).name == name
                and name
                not in {"paper.tex", "references.bib"}
                | {item["name"] for item in input_info}
                | {item["filename"] for item in font_files},
                "LaTeX 附件必须为安全且不重复的单层文件名",
            )
            info, data = self._asset_bytes(sha, obj)
            (work / name).write_bytes(data)
            input_info.append({"name": name, "sha": info["sha"]})
        files = [str(work / "paper.tex"), str(work / "references.bib")] + [
            item["path"] for item in materials if item["type"] == "image"
        ]
        files += [str(work / item["filename"]) for item in font_files]
        compiler = self.config.get("latex")
        compile_record = []
        if fmt == "pdf":
            require(
                compiler and (Path(compiler).is_file() or shutil.which(compiler)),
                "缺少 LaTeX 编译器；可导出 .tex/.bib 源稿，不能生成已编译论文 PDF",
                "latex_unavailable",
                503,
                {
                    "needed": "pdflatex, xelatex, or lualatex",
                    "available_exports": ["tex", "bib", "zip", "docx"],
                },
            )
            env = os.environ.copy()
            env.update(
                {"openin_any": "p", "openout_any": "p", "TEXMFOUTPUT": str(work)}
            )
            command = [
                compiler,
                "-no-shell-escape",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "paper.tex",
            ]
            compile_record.append(
                run_process(command, cwd=work, timeout=self.config["timeout"], env=env)
            )
            if bib.strip():
                bibtool = self.config.get("bibtex") or shutil.which(
                    "bibtex",
                    path=str(Path(compiler).parent)
                    + os.pathsep
                    + os.environ.get("PATH", ""),
                )
                require(
                    bibtool,
                    "论文有 BibTeX 引用但缺少 bibtex 编译器",
                    "bibtex_unavailable",
                    503,
                )
                compile_record.append(
                    run_process(
                        [bibtool, "paper"],
                        cwd=work,
                        timeout=self.config["timeout"],
                        env=env,
                    )
                )
            for _ in range(2):
                compile_record.append(
                    run_process(
                        command, cwd=work, timeout=self.config["timeout"], env=env
                    )
                )
            require(
                (work / "paper.pdf").exists(), "LaTeX 未生成 PDF", "latex_failed", 422
            )
            log = (work / "paper.log").read_text(errors="replace")
            from research_partner.domains.manuscripts.fonts import (
                missing_glyph_warnings,
            )

            missing = missing_glyph_warnings(log)
            require(
                not missing,
                "LaTeX字体缺少保存字符；源稿和既有PDF保留，请修正字体或内容后重试。",
                "latex_missing_glyphs",
                422,
                {"log": "\n".join(missing)[-8000:], "processes": compile_record},
            )
            require(
                "undefined references" not in log
                and "Citation"
                not in "\n".join(
                    line for line in log.splitlines() if "undefined" in line
                ),
                "LaTeX 含未解决引用",
                "latex_references",
                422,
                {"log": log[-10000:]},
            )
            files += [str(work / "paper.pdf"), str(work / "paper.log")]
        elif not compiler:
            warnings.append("当前缺少 LaTeX 编译器；此源稿尚未编译验证。")
        if fmt == "zip":
            (work / "source.json").write_text(
                json.dumps(obj, ensure_ascii=False, indent=2)
            )
            with zipfile.ZipFile(
                work / "paper_source.zip", "w", zipfile.ZIP_DEFLATED
            ) as z:
                for name in ["paper.tex", "references.bib", "source.json"] + [
                    item["name"] for item in input_info
                ]:
                    z.write(work / name, name)
            files.append(str(work / "paper_source.zip"))
        name = {
            "tex": "paper.tex",
            "bib": "references.bib",
            "pdf": "paper.pdf",
            "zip": "paper_source.zip",
        }[fmt]
        return self._publish(
            obj,
            work,
            {
                "files": files,
                "warnings": warnings,
                "runtime": {"compiler": compiler, "compile_records": compile_record},
            },
            name,
            {
                "inputs": input_info,
                "components": [
                    {
                        k: v
                        for k, v in item.items()
                        if k not in {"path", "blocks", "markdown"}
                    }
                    for item in materials
                ],
                "citations": [
                    {
                        "object_id": item["id"],
                        "revision": item["revision"],
                        "source_sha256": digest(item),
                    }
                    for item in citations
                ],
                "paper_source": export_origin(obj, paper_state["mode"]),
                "tex_sha256": hashlib.sha256(tex.encode()).hexdigest(),
                "bibtex_sha256": hashlib.sha256(bib.encode()).hexdigest(),
                "compiled": fmt == "pdf",
            },
        )
