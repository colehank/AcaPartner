"""Bounded bracket citations for the managed manuscript's numeric TeX output.

This is a projection, not a bibliography lookup or a complete Pandoc/CSL
implementation. The caller consumes outer math and literal code first and
supplies its safe inline renderer and text escaper. Every accepted key is
emitted, including keys absent from the bibliography; compilation must reject
undefined keys. No native file or TeX command is executed here.

Keys preserve the managed editor's entire existing [A-Za-z0-9_.:-]+ subset,
including repeated and terminal punctuation. That compatibility takes priority
over Pandoc's narrower unbraced punctuation rules; no existing key is renamed.
URL keys and other Pandoc key punctuation are explicitly unsupported. Post-key
comma text is preserved as the numeric citation's postnote, without guessing
CSL locator categories. Explicit {locator} / {} separates a suffix reliably.
"""
from __future__ import annotations

from collections.abc import Callable
import re
from typing import NoReturn

from .store import Problem


MAX_CITATION_CHARS = 4096
_KEY = re.compile(r'[A-Za-z0-9_.:-]+')
_BRACED_KEY = re.compile(_KEY.pattern + r'\Z')
_LEGACY_SIMPLE = re.compile(r'@[A-Za-z0-9_.:-]+(?:\s*;\s*@[A-Za-z0-9_.:-]+)*\Z')
_LINE_BREAKS = '\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029\x00'


def _invalid(message: str) -> NoReturn:
    raise Problem(message, 'invalid_citation', 422)


def _escaped(text: str, index: int) -> bool:
    previous = index - 1
    while previous >= 0 and text[previous] == '\\':
        previous -= 1
    return (index - previous - 1) % 2 == 1


def _code_end(text: str, start: int, limit: int) -> int | None:
    """Skip a matched Markdown code span, including literal ] ; and @."""
    cursor = start
    while cursor < limit and text[cursor] == '`':
        cursor += 1
    delimiter = text[start:cursor]
    search = cursor
    while search < limit:
        found = text.find(delimiter, search, limit)
        if found < 0:
            return None
        end = found + len(delimiter)
        if (found == 0 or text[found-1] != '`') and (end == limit or text[end] != '`'):
            return end
        search = end
    return None


def _positions(text: str):
    """Yield non-code, unescaped characters with square/curly depth."""
    square = curly = 0
    cursor = 0
    while cursor < len(text):
        char = text[cursor]
        if char == '`' and not _escaped(text, cursor):
            end = _code_end(text, cursor, len(text))
            if end is not None:
                cursor = end
                continue
        if _escaped(text, cursor):
            cursor += 1
            continue
        yield cursor, char, square, curly
        if char == '[': square += 1
        elif char == ']': square -= 1
        elif char == '{': curly += 1
        elif char == '}': curly -= 1
        cursor += 1


def _marks(text: str):
    """Email text is not a citation; a boundary @ (including -@) is."""
    result = []
    for index, char, square, curly in _positions(text):
        if char != '@':
            continue
        suppress = index and text[index-1] == '-' and not _escaped(text, index-1)
        begin = index - 1 if suppress else index
        if begin and (text[begin-1].isalnum() or text[begin-1] == '_'):
            continue
        result.append((begin, index, square, curly))
    return result


def _block(text: str, start: int) -> tuple[int, str] | None:
    limit = min(len(text), start + MAX_CITATION_CHARS)
    cursor = start + 1
    depth = 1
    single_line = True
    while cursor < limit:
        char = text[cursor]
        if char in _LINE_BREAKS:
            single_line = False
        if char == '`' and not _escaped(text, cursor):
            # Code may contain brackets, but never cross the single-line bound.
            line_end = cursor
            while line_end < limit and text[line_end] not in _LINE_BREAKS:
                line_end += 1
            end = _code_end(text, cursor, line_end)
            if end is not None:
                cursor = end
                continue
        if not _escaped(text, cursor):
            if char == '[': depth += 1
            elif char == ']':
                depth -= 1
                if depth == 0:
                    inner = text[start+1:cursor]
                    if not single_line:
                        if _marks(inner):
                            _invalid('引用必须是单行且不含空字符的方括号块')
                        return None
                    return cursor + 1, inner
        cursor += 1
    # Only citation intent is an error. Ordinary prose remains the caller's
    # responsibility, even when its square brackets are unmatched.
    if _marks(text[start+1:cursor]):
        _invalid('引用必须是完整、单行且不超过 4096 字符的方括号块')
    return None


def _parts(text: str) -> list[str]:
    cursor = 0
    parts = []
    square = curly = 0
    for index, char, _, _ in _positions(text):
        if square < 0 or curly < 0:
            _invalid('引用括号未配对')
        if char == ';' and square == 0 and curly == 0:
            parts.append(text[cursor:index])
            cursor = index + 1
        if char == '[': square += 1
        elif char == ']': square -= 1
        elif char == '{': curly += 1
        elif char == '}': curly -= 1
        if square < 0 or curly < 0:
            _invalid('引用括号未配对')
    if square or curly:
        _invalid('引用括号未配对')
    parts.append(text[cursor:])
    return parts


def _curly(text: str, start: int) -> tuple[int, str]:
    depth = 0
    for index, char, _, _ in _positions(text[start:]):
        if char == '{': depth += 1
        elif char == '}':
            depth -= 1
            if depth == 0:
                return start + index + 1, text[start+1:start+index]
    _invalid('引用键或定位信息的花括号未配对')


def _item(text: str) -> tuple[str, str, str, str]:
    marks = _marks(text)
    if len(marks) != 1 or marks[0][2:] != (0, 0):
        _invalid('每个分号分隔的引用项必须有且只有一个有效引用键')
    begin, marker, _, _ = marks[0]
    cursor = marker + 1
    if cursor < len(text) and text[cursor] == '{':
        cursor, key = _curly(text, cursor)
        if not _BRACED_KEY.fullmatch(key):
            _invalid('引用键不在安全 ASCII 范围内；不支持 URL 或 TeX 键')
    else:
        match = _KEY.match(text, cursor)
        if match is None:
            _invalid('引用键为空或不在安全 ASCII 范围内')
        key = match.group()
        cursor = match.end()
    # Consume the entire old safe key: repeated/terminal . : - are part of its
    # identity. An unsupported adjacent character cannot hide in prose after
    # a shorter, different key.
    if cursor < len(text) and not (text[cursor].isspace() or text[cursor] in ',{.!?'):
        _invalid('引用键含有不支持的字符；请使用受支持的准确引用键')
    prefix = text[:begin]
    rest = text[cursor:]
    note = ''
    suffix = ''
    if rest.startswith('{'):
        end, note = _curly(rest, 0)
        suffix = rest[end:]
    elif rest.lstrip().startswith(','):
        after_comma = rest.lstrip()[1:].lstrip()
        if not after_comma:
            _invalid('引用定位信息未完成')
        if after_comma.startswith('{'):
            end, note = _curly(after_comma, 0)
            suffix = after_comma[end:]
        else:
            note = after_comma.rstrip()
            suffix = after_comma[len(note):]
    else:
        suffix = rest
    return key, prefix, note, suffix


def citation_at(text: str, start: int, *, render_inline: Callable[[str], str],
                escape: Callable[[str], str]) -> tuple[int, str] | None:
    """Return exclusive source end and safe numeric TeX, or ordinary prose None.

    Source positions are Python Unicode code points. This function only reads
    source; it never normalizes the original text or changes annotation anchors.
    Caller callbacks must escape ordinary text and only render supported inline
    syntax. They may raise their normal validation errors; these are not hidden.
    """
    if not isinstance(text, str) or not isinstance(start, int) or isinstance(start, bool):
        _invalid('引用读取位置或文本类型无效')
    if start < 0 or start >= len(text) or text[start] != '[' or _escaped(text, start):
        return None
    block = _block(text, start)
    if block is None:
        return None
    end, inner = block
    if _LEGACY_SIMPLE.fullmatch(inner):
        # Keep the original simple-source contract byte-for-byte even when a
        # key is broader than standard Pandoc's unbraced punctuation rules.
        keys = [match.group()[1:] for match in re.finditer('@' + _KEY.pattern, inner)]
        return end, r'\cite{' + ','.join(keys) + '}'
    if not _marks(inner):
        return None
    items = [_item(part) for part in _parts(inner)]
    if all(not prefix.strip() and not note and not suffix.strip()
           for _, prefix, note, suffix in items):
        return end, r'\cite{' + ','.join(key for key, _, _, _ in items) + '}'

    def project(value: str) -> str:
        # Avoid recursive inline parsing for plain prose, especially literal
        # TeX commands. Formatted affixes use the caller's bounded safe renderer.
        formatted = any(token in value for token in ('`', '*', '_', '$', r'\(', r'\['))
        result = render_inline(value) if formatted else escape(value)
        if not isinstance(result, str):
            _invalid('引用文字投影未返回文本')
        return result

    output = []
    for key, prefix, note, suffix in items:
        rendered_note = project(note) if note else ''
        if '[' in rendered_note or ']' in rendered_note:
            # LaTeX's optional-argument scanner respects balanced braces. The
            # source is escaped first, so literal braces cannot end this group.
            rendered_note = '{' + rendered_note + '}'
        command = r'\cite' + ('[' + rendered_note + ']' if note else '') + '{' + key + '}'
        output.append(project(prefix) + command + project(suffix))
    return end, ';'.join(output)
