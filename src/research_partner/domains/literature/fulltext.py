"""Bounded, offline JATS text extraction, not retrieval or scientific approval.

The caller owns source selection, current ACL, network/Task budgets, and assets.
Raw XML remains authoritative. Text below is an explicitly derived view: XML
line endings/entities are decoded by Expat, and unsupported content is omitted
with limits. No URL (including a declared external DTD) is opened here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from xml.parsers import expat


MAX_BYTES = 4 * 1024 * 1024
MAX_TEXT_BYTES = 256 * 1024
MAX_DEPTH = 64
MAX_NODES = 50000
MAX_RESULT_BYTES = 768 * 1024
_XML_ID = 'http://www.w3.org/XML/1998/namespace}id'
_XLINK_HREF = 'http://www.w3.org/1999/xlink}href'
_UNPARSED = {'inline-formula', 'disp-formula', 'tex-math', 'math', 'chem-struct',
             'table', 'array', 'graphic', 'inline-graphic', 'media', 'inline-media',
             'supplementary-material', 'sub-article', 'response'}
_BLOCKS = {'p', 'fig', 'fig-group', 'table-wrap', 'table-wrap-group', 'boxed-text',
           'sec', 'list', 'def-list', 'disp-quote'}


class JATSParseError(ValueError):
    """Pure parser failure; a public host may map code to its own error schema."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require(condition, code, message):
    if not condition:
        raise JATSParseError(code, message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _local(name: str) -> str:
    return name.rsplit('}', 1)[-1]


@dataclass
class _Node:
    name: str
    attrs: dict
    path: str
    parts: list = field(default_factory=list)
    children: list = field(default_factory=list)
    counts: dict = field(default_factory=dict)
    ancestors: tuple = ()


def _direct(node, name):
    # Core JATS elements are unqualified. Namespace-qualified MathML is handled
    # as unsupported content; arbitrary foreign "article" elements are not JATS.
    return [child for child in node.children if child.name == name]


def _one(node, name, *, required=False):
    found = _direct(node, name)
    _require(len(found) <= 1 and (not required or len(found) == 1),
             'invalid_jats', 'Expected one direct JATS ' + name + ' element')
    return found[0] if found else None


def _walk(node):
    yield node
    if _local(node.name) not in _UNPARSED:
        for child in node.children:
            yield from _walk(child)


def _text(node, *, paragraph=False):
    """Mixed inline text, never double-count descendant paragraph/block text."""
    pieces = []
    for part in node.parts:
        if isinstance(part, str):
            pieces.append(part)
        elif _local(part.name) not in _UNPARSED and (not paragraph or _local(part.name) not in _BLOCKS):
            pieces.append(_text(part, paragraph=paragraph))
    return ''.join(pieces)


def _normal_pmcid(value):
    value = value.strip()
    if re.fullmatch(r'[1-9][0-9]*', value):
        return 'PMC' + value
    return value if re.fullmatch(r'PMC[1-9][0-9]*', value) else None


def parse_jats(raw: bytes, *, expected_pmcid: str,
               expected_raw_sha256: str | None = None,
               max_bytes: int = MAX_BYTES, max_text_bytes: int = MAX_TEXT_BYTES,
               max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> dict:
    """Parse supplied article bytes with one explicit PMC identity.

    Limits may only be reduced. No full-text string duplicates ``paragraphs``.
    A body containing readable p elements gives read_scope=fulltext, meaning a
    body-text view exists, not that equations/tables/images or science were read.
    Missing/empty body remains abstract or metadata. License observations never
    grant redistribution permission or prove public network accessibility.
    """
    _require(type(raw) is bytes, 'invalid_input', 'raw must be immutable bytes')
    _require(isinstance(expected_pmcid, str) and re.fullmatch(r'PMC[1-9][0-9]*', expected_pmcid),
             'invalid_input', 'expected_pmcid must be an explicit canonical PMC identifier')
    for value, ceiling in [(max_bytes, MAX_BYTES), (max_text_bytes, MAX_TEXT_BYTES),
                           (max_depth, MAX_DEPTH), (max_nodes, MAX_NODES)]:
        _require(type(value) is int and 1 <= value <= ceiling,
                 'invalid_input', 'Parser limits must be positive integers within hard bounds')
    _require(0 < len(raw) <= max_bytes, 'resource_limit', 'Raw XML size exceeds the bounded input')
    raw_sha = _sha(raw)
    if expected_raw_sha256 is not None:
        _require(isinstance(expected_raw_sha256, str) and re.fullmatch(r'[0-9a-f]{64}', expected_raw_sha256),
                 'invalid_input', 'Expected raw SHA256 is invalid')
        _require(raw_sha == expected_raw_sha256, 'integrity', 'Raw XML SHA256 does not match')

    parser = expat.ParserCreate(namespace_separator='}')
    parser.buffer_text = True
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    if hasattr(parser, 'SetReparseDeferralEnabled'):
        parser.SetReparseDeferralEnabled(True)
    roots, stack, xml_ids = [], [], set()
    nodes = 0
    doctype = None

    def start(name, attrs):
        nonlocal nodes
        nodes += 1
        _require(nodes <= max_nodes and len(stack) < max_depth,
                 'resource_limit', 'XML node/depth limit reached; no partial article returned')
        _require(len(name.encode()) <= 256, 'resource_limit', 'XML element name exceeds parser bound')
        parent = stack[-1] if stack else None
        if parent:
            parent.counts[name] = parent.counts.get(name, 0) + 1
            path = parent.path + '/' + name + '[' + str(parent.counts[name]) + ']'
        else:
            path = '/' + name + '[1]'
        _require(len(path.encode()) <= 4096, 'resource_limit', 'XML structural path exceeds parser bound')
        ids = [attrs[key] for key in ('id', _XML_ID) if key in attrs]
        _require(len(ids) <= 1, 'duplicate_xml_id', 'Multiple XML ID attributes on one element are ambiguous')
        for ident in ids:
            _require(ident and len(ident.encode()) <= 256 and ident not in xml_ids,
                     'duplicate_xml_id', 'XML IDs must be nonempty, bounded and unique across the article')
            xml_ids.add(ident)
        node = _Node(name, attrs, path, ancestors=parent.ancestors + (_local(parent.name),) if parent else ())
        if parent:
            parent.children.append(node)
            parent.parts.append(node)
        else:
            roots.append(node)
        stack.append(node)

    def characters(value):
        if stack:
            stack[-1].parts.append(value)

    def declaration(name, system_id, public_id, has_internal_subset):
        nonlocal doctype
        _require(name == 'article' and not has_internal_subset,
                 'unsafe_xml', 'Only an external JATS article DOCTYPE without an internal subset is accepted')
        doctype = {'name': name, 'system_id': system_id, 'public_id': public_id, 'resolved': False}

    def reject_entity(*_args):
        raise JATSParseError('unsafe_xml', 'Entity declarations or external entity resolution are forbidden')

    parser.StartElementHandler = start
    parser.EndElementHandler = lambda _name: stack.pop()
    parser.CharacterDataHandler = characters
    parser.StartDoctypeDeclHandler = declaration
    parser.EntityDeclHandler = reject_entity
    parser.ExternalEntityRefHandler = reject_entity
    parser.SkippedEntityHandler = reject_entity
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as error:
        raise JATSParseError('invalid_xml', 'Malformed or unsupported XML at line ' + str(error.lineno)) from error
    _require(len(roots) == 1 and roots[0].name == 'article', 'invalid_jats', 'Expected an unqualified JATS article root')
    article = roots[0]
    front = _one(article, 'front', required=True)
    meta = _one(front, 'article-meta', required=True)
    identifiers = [{'type': node.attrs.get('pub-id-type'), 'value': _text(node)} for node in _direct(meta, 'article-id')]
    pmc_ids = [_normal_pmcid(item['value']) for item in identifiers if item['type'] in {'pmc', 'pmcid'}]
    _require(bool(pmc_ids) and all(value == expected_pmcid for value in pmc_ids),
             'identity_mismatch', 'Article PMC identity is missing, conflicting, or different from expected_pmcid')
    title_group = _one(meta, 'title-group')
    title_node = _one(title_group, 'article-title') if title_group else None
    title = _text(title_node) if title_node else ''
    body = _one(article, 'body')

    text_bytes = 0

    def charge(text):
        nonlocal text_bytes
        text_bytes += len(text.encode('utf-8'))
        _require(text_bytes <= max_text_bytes, 'resource_limit', 'Derived text exceeds its byte limit; no truncation')
        return text

    charge(title)
    abstracts = []
    for node in meta.children:
        if node.name in {'abstract', 'trans-abstract'}:
            # Paragraph boundaries remain explicit; parent abstracts never
            # concatenate and duplicate all nested p records.
            parts = [child for child in _walk(node) if child.name == 'p']
            if parts:
                for child in parts:
                    abstracts.append({'structure_path': child.path, 'text': charge(_text(child, paragraph=True))})
            else:
                abstracts.append({'structure_path': node.path, 'text': charge(_text(node))})
    paragraphs = []
    if body:
        for node in _walk(body):
            if node.name != 'p':
                continue
            text = charge(_text(node, paragraph=True))
            record = {'id': 'jats-p-' + _sha(node.path.encode()), 'kind': 'paragraph', 'text': text,
                      'structure_path': node.path, 'role': 'caption' if 'caption' in node.ancestors else 'paragraph',
                      'content_sha256': _sha(text.encode()), 'utf8_bytes': len(text.encode()), 'codepoints': len(text)}
            ident = node.attrs.get('id', node.attrs.get(_XML_ID))
            if ident is not None:
                record['xml_id'] = ident
            paragraphs.append(record)
    license_observations = []
    permissions = _one(meta, 'permissions')
    if permissions:
        for node in _direct(permissions, 'license'):
            license_observations.append({'type': node.attrs.get('license-type'),
                                         'href': node.attrs.get(_XLINK_HREF), 'text': charge(_text(node))})
    unparsed = []
    # Every unsupported subtree is recorded once; no child MathML/table cells
    # become invented prose, and caption p outside those subtrees still appears.
    for node in _walk(article):
        if _local(node.name) in _UNPARSED:
            unparsed.append({'tag': _local(node.name), 'structure_path': node.path})
    readable_body = any(record['text'].strip() for record in paragraphs)
    scope = 'fulltext' if body and readable_body else 'abstract' if any(x['text'].strip() for x in abstracts) else 'metadata'
    result = {'raw_sha256': raw_sha, 'raw_bytes': len(raw), 'pmcid': expected_pmcid,
              'article_ids': identifiers, 'title': title, 'abstracts': abstracts, 'paragraphs': paragraphs,
              'body_present': body is not None, 'read_scope': scope, 'derived_text_bytes': text_bytes,
              'license_status': 'observed' if license_observations else 'unknown',
              'license_observations': license_observations, 'redistribution_permission': 'unknown',
              'public_access': 'not_assessed_by_parser', 'scientific_content_complete': False,
              'unparsed_elements': unparsed, 'external_doctype': doctype,
              'parser': {'name': 'stdlib.pyexpat', 'expat_version': expat.EXPAT_VERSION,
                         'parameter_entities': 'never', 'external_entities': 'forbidden',
                         'dtd_validation': False, 'reparse_deferral': hasattr(parser, 'SetReparseDeferralEnabled')},
              'limitations': [
                  'A derived XML text view only; raw bytes and raw SHA256 remain separate and authoritative.',
                  'XML line-ending and character-reference decoding apply; no further Unicode/whitespace normalization.',
                  'Paragraph records follow source element order; parent p excludes nested block/p text to avoid duplicate captions.',
                  'Only title, abstract and body p text is extracted; section headings/back matter are not a complete article rendering.',
                  'Unsupported mathematics, tables, images/media and supplementary content are not interpreted or fetched.',
                  'No DTD/schema validation, public-access verification, license grant, or scientific understanding is asserted.',
              ]}
    _require(len(json.dumps(result, ensure_ascii=False).encode()) <= MAX_RESULT_BYTES,
             'resource_limit', 'Derived structure exceeds its bounded result size; no partial result')
    return result


def locate_paragraph(document: dict, paragraph_id: str, *, start_offset: int = 0,
                     end_offset: int | None = None, expected_content_sha256: str | None = None) -> dict:
    """Locate a nonempty Unicode-codepoint range in one exact derived paragraph.

    Hash validation detects mutated derived text; this is not project/asset ACL
    validation. The caller still binds document.raw_sha256 to its saved source.
    """
    _require(isinstance(document, dict) and isinstance(document.get('paragraphs'), list),
             'invalid_locator', 'Expected a parsed document')
    matches = [item for item in document['paragraphs'] if isinstance(item, dict) and item.get('id') == paragraph_id]
    _require(len(matches) == 1, 'paragraph_not_found', 'Paragraph identity must match exactly one saved structure position')
    paragraph = matches[0]
    text = paragraph.get('text')
    _require(isinstance(text, str) and paragraph.get('content_sha256') == _sha(text.encode())
             and paragraph.get('codepoints') == len(text) and paragraph.get('utf8_bytes') == len(text.encode()),
             'integrity', 'Derived paragraph text/identity was modified')
    end = len(text) if end_offset is None else end_offset
    _require(type(start_offset) is int and type(end) is int and 0 <= start_offset < end <= len(text),
             'invalid_locator', 'Expected a nonempty half-open Unicode codepoint range')
    selected = text[start_offset:end]
    selected_sha = _sha(selected.encode())
    if expected_content_sha256 is not None:
        _require(expected_content_sha256 == selected_sha, 'integrity', 'Selected derived text SHA256 does not match')
    return {'paragraph_id': paragraph_id, 'structure_path': paragraph['structure_path'],
            'pmcid': document['pmcid'], 'raw_sha256': document['raw_sha256'],
            'paragraph_sha256': paragraph['content_sha256'], 'start_offset': start_offset, 'end_offset': end,
            'text': selected, 'content_sha256': selected_sha, 'utf8_bytes': len(selected.encode()), 'codepoints': len(selected)}
