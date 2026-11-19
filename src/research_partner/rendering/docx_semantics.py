"""Bounded math source, visible Mathtext glyphs and pinned citation display.

OMML structure follows Microsoft's OfficeMath schema (m:f, m:sSubSup, m:nary).
Unsupported syntax raises; callers must preserve the complete original text and
report the occurrence. OMML is preserved as a source representation; displayed
equations use PNG because the authorized Office runtime lacks its Math module.
The CLI renders glyphs only and never executes TeX or scientific source code.
"""
from __future__ import annotations
import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET

M = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
ET.register_namespace('m', M)
MATH_PATTERN = (r'(?<!\\)\$\$[\s\S]+?\$\$|(?<![\\$])\$(?!\$)[^\n$]+\$(?!\$)'
                r'|(?<!\\)\\\[[\s\S]+?\\\]|(?<!\\)\\\([^\n]+?\\\)')
CITE_PATTERN = r'\[@[A-Za-z0-9_.:-]+(?:\s*;\s*@[A-Za-z0-9_.:-]+)*\]'


def node(tag, children=(), **attrs):
    element = ET.Element('{' + M + '}' + tag, {'{' + M + '}' + k: str(v) for k, v in attrs.items()})
    element.extend(children)
    return element


def run(text, normal=False):
    value = node('t'); value.text = text
    if ' ' in text: value.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
    return node('r', ([node('rPr', [node('nor', val='1')])] if normal else []) + [value])


GREEK = dict(zip(('alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi '
                 'omicron pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega '
                 'Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega').split(),
                'α β γ δ ϵ ε ζ η θ ϑ ι κ λ μ ν ξ ο π ϖ ρ ϱ σ ς τ υ ϕ φ χ ψ ω Γ Δ Θ Λ Ξ Π Σ Υ Φ Ψ Ω'.split()))
SYMBOLS = {**GREEK, 'cdot':'⋅', 'times':'×', 'div':'÷', 'pm':'±', 'mp':'∓', 'le':'≤', 'leq':'≤',
           'ge':'≥', 'geq':'≥', 'ne':'≠', 'neq':'≠', 'approx':'≈', 'sim':'∼', 'equiv':'≡',
           'propto':'∝', 'in':'∈', 'notin':'∉', 'infty':'∞', 'partial':'∂', 'nabla':'∇',
           'to':'→', 'rightarrow':'→', 'leftarrow':'←', 'leftrightarrow':'↔', 'cdots':'⋯',
           'ldots':'…', 'ell':'ℓ', 'forall':'∀', 'exists':'∃', 'emptyset':'∅', 'cup':'∪', 'cap':'∩'}
FUNCTIONS = {'sin','cos','tan','log','ln','exp','min','max','lim','det','arg'}


class MathSyntaxError(ValueError): pass


class MathParser:
    def __init__(self, text):
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise MathSyntaxError('Equation must contain 1–4096 characters')
        if any(ord(ch) < 32 and ch not in '\n\t' for ch in text):
            raise MathSyntaxError('Control character in equation')
        self.text = text; self.i = 0; self.depth = 0

    def skip(self):
        while self.i < len(self.text) and self.text[self.i].isspace(): self.i += 1

    def argument(self):
        self.skip()
        if self.i >= len(self.text): raise MathSyntaxError('Missing mathematical argument')
        if self.text[self.i] == '{':
            self.i += 1
            return self.sequence('}')
        return [self.atom()]

    def sequence(self, end=None):
        self.depth += 1
        if self.depth > 64: raise MathSyntaxError('Equation nesting exceeds 64')
        values = []
        while True:
            self.skip()
            if self.i >= len(self.text):
                if end: raise MathSyntaxError('Unclosed mathematical group')
                break
            if end and self.text.startswith(end, self.i):
                self.i += len(end); break
            if self.text[self.i] == '}': raise MathSyntaxError('Unexpected closing brace')
            base = self.atom(); scripts = {}
            while True:
                self.skip()
                if self.i >= len(self.text) or self.text[self.i] not in '_^': break
                kind = self.text[self.i]; self.i += 1
                if kind in scripts: raise MathSyntaxError('Repeated subscript or superscript')
                scripts[kind] = self.argument()
            if base.tag == '{'+M+'}nary':
                props = base.find('{'+M+'}naryPr')
                props.extend([node('subHide', val='0' if '_' in scripts else '1'), node('supHide', val='0' if '^' in scripts else '1')])
                base.extend([node('sub', scripts.get('_', [])), node('sup', scripts.get('^', [])), node('e')])
            elif scripts:
                tag = 'sSubSup' if len(scripts) == 2 else 'sSub' if '_' in scripts else 'sSup'
                base = node(tag, [node('e', [base])] + ([node('sub', scripts['_'])] if '_' in scripts else []) + ([node('sup', scripts['^'])] if '^' in scripts else []))
            values.append(base)
        self.depth -= 1
        return values

    def atom(self):
        self.skip()
        if self.i >= len(self.text): raise MathSyntaxError('Missing mathematical atom')
        ch = self.text[self.i]; self.i += 1
        if ch == '{': return node('box', [node('e', self.sequence('}'))])
        if ch in '_^}#$&%': raise MathSyntaxError('Unsupported/unattached mathematical token: ' + ch)
        if ch != '\\': return run('−' if ch == '-' else ch)
        match = re.match(r'[A-Za-z]+|.', self.text[self.i:])
        if not match: raise MathSyntaxError('Incomplete command')
        command = match[0]; self.i += len(command)
        if command in SYMBOLS: return run(SYMBOLS[command])
        if command in FUNCTIONS: return run(command, normal=True)
        if command in {'sum','prod','int','iint','oint'}:
            return node('nary', [node('naryPr', [node('chr', val={'sum':'∑','prod':'∏','int':'∫','iint':'∬','oint':'∮'}[command]), node('limLoc', val='subSup' if 'int' in command else 'undOvr')])])
        if command in {'frac','dfrac','tfrac'}:
            return node('f', [node('num', self.argument()), node('den', self.argument())])
        if command == 'sqrt':
            self.skip(); degree = []
            if self.i < len(self.text) and self.text[self.i] == '[':
                self.i += 1; degree = self.sequence(']')
            return node('rad', [node('radPr', [node('degHide', val='0' if degree else '1')]), node('deg', degree), node('e', self.argument())])
        if command == 'text':
            self.skip()
            if self.i >= len(self.text) or self.text[self.i] != '{': raise MathSyntaxError('Text requires braces')
            self.i += 1; text = []
            while self.i < len(self.text) and self.text[self.i] != '}':
                ch = self.text[self.i]; self.i += 1
                if ch == '{': raise MathSyntaxError('Nested text groups are unsupported')
                if ch == '\\':
                    if self.i >= len(self.text) or self.text[self.i] not in '{}_%#&': raise MathSyntaxError('Unsupported command in text')
                    ch = self.text[self.i]; self.i += 1
                text.append(ch)
            if self.i >= len(self.text): raise MathSyntaxError('Unclosed text')
            self.i += 1
            return run(''.join(text), normal=True)
        if command in {'mathrm','mathbf','mathit','mathsf','mathtt','operatorname'}:
            children = self.argument()
            for element in children:
                for r in element.iter('{'+M+'}r'):
                    props = r.find('{'+M+'}rPr')
                    if props is None: props = node('rPr'); r.insert(0, props)
                    if command in {'text','mathrm','operatorname'}: props.append(node('nor', val='1'))
                    elif command in {'mathbf','mathit'}: props.append(node('sty', val='b' if command == 'mathbf' else 'i'))
                    else: props.append(node('scr', val='sans-serif' if command=='mathsf' else 'monospace'))
            return node('box', [node('e', children)])
        if command in {'hat','bar','overline','vec','tilde','dot','ddot'}:
            return node('acc', [node('accPr', [node('chr', val={'hat':'̂','bar':'̅','overline':'̅','vec':'⃗','tilde':'̃','dot':'̇','ddot':'̈'}[command])]), node('e', self.argument())])
        if command == 'left':
            opening = self.delimiter(); children = self.sequence(r'\right'); closing = self.delimiter()
            return node('d', [node('dPr', [node('begChr', val=opening), node('endChr', val=closing)]), node('e', children)])
        if command in {',',';',':','!',' ','quad','qquad'}: return run({'!':'', 'quad':'\u2003','qquad':'\u2003\u2003'}.get(command,'\u2009'), normal=True)
        if command in '{}_%#|': return run(command)
        raise MathSyntaxError('Unsupported command: \\' + command)

    def delimiter(self):
        self.skip()
        if self.i >= len(self.text): raise MathSyntaxError('Missing delimiter')
        if self.text[self.i] == '\\':
            match = re.match(r'\\(?:[A-Za-z]+|.)', self.text[self.i:])
            token = match[0]; self.i += len(token)
            choices = {r'\{':'{',r'\}':'}',r'\langle':'⟨',r'\rangle':'⟩',r'\lvert':'|',r'\rvert':'|',r'\Vert':'‖'}
            if token not in choices: raise MathSyntaxError('Unsupported delimiter ' + token)
            return choices[token]
        value = self.text[self.i]; self.i += 1
        if value not in '()[]|.': raise MathSyntaxError('Unsupported delimiter ' + value)
        return '' if value == '.' else value


def equation_xml(raw):
    if not isinstance(raw, str) or not re.fullmatch(MATH_PATTERN, raw):
        raise MathSyntaxError('Unclosed or mixed mathematical delimiters')
    display = raw.startswith(('$$', r'\['))
    if raw.startswith('$$'): text = raw[2:-2]
    elif raw.startswith('$'): text = raw[1:-1]
    elif raw.startswith((r'\(', r'\[')): text = raw[2:-2]
    else: raise MathSyntaxError('Explicit math delimiters required')
    math = node('oMath', MathParser(text).sequence())
    if display: math = node('oMathPara', [node('oMathParaPr', [node('jc', val='center')]), math])
    return ET.tostring(math, encoding='unicode'), display


def display_chunks(text):
    """Separate standalone display equations, preserving full unsupported input."""
    lines = text.splitlines(keepends=True); plain = []; i = 0; fence = None
    while i < len(lines):
        line = lines[i]; marker = re.match(r'^\s*(`{3,}|~{3,})', line)
        if marker:
            if fence is None: fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence): fence = None
        stripped = line.strip()
        opening = next((v for v in (r'\[', '$$') if stripped.startswith(v)), None) if fence is None else None
        if opening:
            closing = r'\]' if opening == r'\[' else '$$'
            body = line; i += 1
            while closing not in body[body.index(opening)+len(opening):] and i < len(lines): body += lines[i]; i += 1
            if plain: yield 'markdown', ''.join(plain); plain = []
            yield 'math', body.strip()
        else: plain.append(line); i += 1
    if plain: yield 'markdown', ''.join(plain)


def citation_keys(item):
    content = item.get('content', {}); metadata = item.get('metadata', {})
    values = [metadata.get('citation_key')] + [content.get(k) for k in ('citation_key','cite_key','key','bibtex_key')]
    return {value for value in values if isinstance(value, str) and value}


def citation_map(citations):
    result = {}
    for i, item in enumerate(citations, 1):
        for key in citation_keys(item): result.setdefault(key, []).append(i)
    return result


def resolve_citation(raw, citations, offset=0):
    mapping = citation_map(citations); keys = re.findall(r'@([A-Za-z0-9_.:-]+)', raw)
    missing = [key for key in keys if len(mapping.get(key, [])) != 1]
    if missing: return None, missing
    return '[' + ', '.join(str(offset+mapping[key][0]) for key in keys) + ']', []


_BIB_ACCENTS = {"'":'\u0301', '`':'\u0300', '^':'\u0302', '"':'\u0308',
                '~':'\u0303', '=':'\u0304', '.':'\u0307', 'u':'\u0306',
                'v':'\u030c', 'H':'\u030b', 'c':'\u0327', 'k':'\u0328',
                'r':'\u030a', 'd':'\u0323', 'b':'\u0331'}
_BIB_ACCENT = re.compile(
    r'''\\(?P<mark>['`^"~=.]|[uvHckrdb](?![A-Za-z]))\s*'''
    r'''(?:\{(?P<braced>\\[ij]|[^\W\d_])\}|(?P<bare>\\[ij](?![A-Za-z])|[^\W\d_]))''')


def bibliography_plain(value):
    """Decode finite TeX accents for display; preserve unknown macros verbatim."""
    def group_end(text, start):
        pairs={'{':'}','[':']'};stack=[pairs[text[start]]];i=start+1
        while i<len(text):
            if text[i]=='\\':i+=2;continue
            if text[i] in pairs:stack.append(pairs[text[i]])
            elif text[i]==stack[-1]:
                stack.pop()
                if not stack:return i+1
            i+=1
        return None

    def decode(text, depth=0):
        if depth>32:return text
        result=[];i=0
        while i<len(text):
            if text[i]=='\\':
                accent=_BIB_ACCENT.match(text,i)
                if accent:
                    base=accent['braced'] or accent['bare']
                    base={r'\i':'i',r'\j':'j'}.get(base,base)
                    result.append(unicodedata.normalize('NFC',base+_BIB_ACCENTS[accent['mark']]))
                    i=accent.end();continue
                if i+1<len(text) and text[i+1] in '&%_#{}\\':
                    result.append(text[i+1]);i+=2;continue
                command=re.match(r'\\(?:[A-Za-z]+|.)',text[i:])
                end=i+len(command[0]) if command else i+1
                # Unknown commands and their balanced arguments stay exact;
                # capitalization-brace cleanup must not corrupt their source.
                while end<len(text):
                    start=end
                    while start<len(text) and text[start].isspace():start+=1
                    if start>=len(text) or text[start] not in '{[':break
                    closing=group_end(text,start)
                    if closing is None:end=len(text);break
                    end=closing
                result.append(text[i:end]);i=end;continue
            if text[i]=='{':
                closing=group_end(text,i)
                if closing is not None:
                    result.append(decode(text[i+1:closing-1],depth+1));i=closing;continue
            result.append(text[i]);i+=1
        return ''.join(result)
    return decode(str(value))


def bibliography_text(item):
    c = item.get('content', {})
    authors = c.get('authors') or c.get('author') or []
    if isinstance(authors, list): authors = ', '.join(str(a) for a in authors)
    # Display decoding never infers authors, dates, title, DOI or read scope.
    values = [authors, c.get('year'), c.get('title') or item.get('title'), c.get('journal'),
              c.get('doi') or c.get('url')]
    return '. '.join(bibliography_plain(v).strip().rstrip('.') for v in values if v)


def text_identity(text):
    return hashlib.sha256(text.encode()).hexdigest()


def render_images(request, output):
    """Trusted glyph-only Mathtext process using an already configured runtime."""
    import json
    from pathlib import Path
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.mathtext import math_to_image
    from matplotlib.font_manager import FontProperties
    from PIL import Image
    matplotlib.rcParams['text.usetex'] = False
    out = Path(output); results = []
    for raw in request:
        item = {'source':raw,'source_sha256':text_identity(raw),'renderer':'matplotlib.mathtext','latex_compiled':False}
        try:
            xml, display = equation_xml(raw)
            formula = raw[2:-2] if raw.startswith(('$$',r'\[',r'\(')) else raw[1:-1]
            filename = 'equation-'+item['source_sha256']+'.png'; dpi = 240
            math_to_image('$'+formula.strip().replace('\n',' ')+'$',out/filename,
                          prop=FontProperties(size=12 if display else 11),format='png',dpi=dpi)
            with Image.open(out/filename) as image: width,height=image.size
            item.update(status='rendered',filename=filename,sha256=hashlib.sha256((out/filename).read_bytes()).hexdigest(),
                        width_px=width,height_px=height,dpi=dpi,display=display,omml_source=xml)
        except (MathSyntaxError,ValueError,RuntimeError) as exc:
            item.update(status='unsupported',error=type(exc).__name__+': '+str(exc))
        results.append(item)
    return {'equations':results,'runtime':{'kind':'matplotlib.mathtext','matplotlib_version':matplotlib.__version__,
            'helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'latex_compiled':False}}


if __name__ == '__main__':
    import json
    from pathlib import Path
    import sys
    request=Path(sys.argv[1]); output=Path(sys.argv[2])
    result=render_images(json.loads(request.read_text()),output)
    (output/'equations-result.json').write_text(json.dumps(result,ensure_ascii=False))
