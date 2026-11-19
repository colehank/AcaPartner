"""Pinned outline glyph fallback; no system-family lookup or installation.

Only actual supplementary pictograph and mathematical-alphanumeric glyphs in
the bundled fonts are added to xeCJK's text fallback. Math tokens and saved
manuscript/BibTeX bytes stay intact.
This is neither a color emoji renderer nor complete Unicode/emoji support.
"""
from research_partner.resources import resource_path
from pathlib import Path
import hashlib
import struct

from research_partner.storage.store import require

FONT = resource_path('fonts') / 'DejaVuSans.ttf'
LICENSE = FONT.with_name('DejaVuSans.LICENSE')
FONT_SHA256 = 'ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280'
LICENSE_SHA256 = '63d3ba759d12804c5b31a9d5940d855c1820d1f5999e6b0872eb1c7ff045fbc9'
FONT_FILENAME = 'rp-font-DejaVuSans.ttf'
LICENSE_FILENAME = 'rp-font-DejaVuSans.LICENSE'
MATH_FONT = FONT.with_name('NotoSansMath-Regular.ttf')
MATH_LICENSE = FONT.with_name('NotoSansMath.LICENSE')
MATH_FONT_SHA256 = '8242bd1e55368b27e32455260754cf9aa58f3ad7ea80664b66c21f1b09910d6c'
MATH_LICENSE_SHA256 = '075f91382875da1c4b491f1facf2586f55448705133264d98ce15cab6211b125'
MATH_FONT_FILENAME = 'rp-font-NotoSansMath-Regular.ttf'
MATH_LICENSE_FILENAME = 'rp-font-NotoSansMath.LICENSE'
# Google Fonts notoemoji, pinned upstream 8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5.
# Monochrome TrueType outlines under SIL OFL 1.1; no color bitmap dependency.
EMOJI_FONT = FONT.with_name('NotoEmoji-Variable.ttf')
EMOJI_LICENSE = FONT.with_name('NotoEmoji.LICENSE')
EMOJI_FONT_SHA256 = 'de6c18832938afc99caf132b39d6a30a19bac7f2e812e28db2535b4608d27551'
EMOJI_LICENSE_SHA256 = '500bb1ccf43df7bbb522112f9133a52b16e1c35e809632f5d8609b179152de5b'
EMOJI_FONT_FILENAME = 'rp-font-NotoEmoji-Variable.ttf'
EMOJI_LICENSE_FILENAME = 'rp-font-NotoEmoji.LICENSE'


def _fixed_bytes(path, sha):
    require(path.is_file() and not path.is_symlink(), '固定稿件字体资源缺失', 'latex_font_unavailable', 503)
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == sha, '固定稿件字体资源校验失败', 'latex_font_integrity', 503)
    return raw


def _glyph_ranges(path, sha, lower, upper):
    """Read a bounded format-12 cmap from a verified TTF, excluding glyph zero."""
    raw = _fixed_bytes(path, sha)
    tables = {raw[12+16*i:16+16*i]: struct.unpack_from('>II', raw, 20+16*i)
              for i in range(struct.unpack_from('>H', raw, 4)[0])}
    offset, _ = tables[b'cmap']
    for i in range(struct.unpack_from('>H', raw, offset+2)[0]):
        platform, encoding, relative = struct.unpack_from('>HHI', raw, offset+4+8*i)
        position = offset + relative
        if (platform, encoding) == (3, 10) and struct.unpack_from('>H', raw, position)[0] == 12:
            ranges = []
            for j in range(struct.unpack_from('>I', raw, position+12)[0]):
                start, end, glyph = struct.unpack_from('>III', raw, position+16+12*j)
                start = max(start + (glyph == 0), lower)
                end = min(end, upper)
                if start <= end:
                    if ranges and start == ranges[-1][1] + 1:
                        ranges[-1] = (ranges[-1][0], end)
                    else:
                        ranges.append((start, end))
            return tuple(ranges)
    raise RuntimeError('Pinned font is missing its Unicode format-12 cmap')


def pictograph_ranges():
    return _glyph_ranges(FONT, FONT_SHA256, 0x1F000, 0x1FAFF)


def mathematical_alphanumeric_ranges():
    return _glyph_ranges(MATH_FONT, MATH_FONT_SHA256, 0x1D400, 0x1D7FF)


def emoji_ranges():
    return _glyph_ranges(EMOJI_FONT, EMOJI_FONT_SHA256, 0x1F000, 0x1FAFF)


def fallback_preamble(*, portable=False):
    # Declare only actual covered scalar ranges, not the entire emoji block.
    # Preserve the previous font precedence for already-supported characters.
    covered = []
    for start, end in sorted(pictograph_ranges() + mathematical_alphanumeric_ranges() + emoji_ranges()):
        if covered and start <= covered[-1][1] + 1:
            covered[-1] = (covered[-1][0], max(covered[-1][1], end))
        else:
            covered.append((start, end))
    ranges = ','.join('"%X -> "%X' % pair if pair[0] != pair[1] else '"%X' % pair[0]
                      for pair in covered)
    directory = FONT.parent.resolve().as_posix() + '/'
    require(portable or not any(ch in directory for ch in '\\%#{}$^~\n\r'),
            '固定字体路径不能安全用于TeX', 'latex_font_path', 503)
    # Official prepared exports use a verified attached file. Older structured
    # entries resolve this module's own pinned file, never a same-name user file.
    def font(path, filename):
        options = 'Path={' + path + '},BoldFont={' + filename + '},ItalicFont={' + filename + '},BoldItalicFont={' + filename + '}'
        return '{[' + options + ']' + filename + '}'
    names = ((FONT_FILENAME, MATH_FONT_FILENAME, EMOJI_FONT_FILENAME) if portable
             else (FONT.name, MATH_FONT.name, EMOJI_FONT.name))
    chain = ','.join(font('./' if portable else directory, name) for name in names)
    families = '\n'.join(r'\setCJKfallbackfamilyfont{\CJK' + family + 'default}{' + chain + '}'
                         for family in ('rm', 'sf', 'tt'))
    literal_options = 'Path={' + ('./' if portable else directory) + '},BoldFont={' + names[0] + '},ItalicFont={' + names[0] + '},BoldItalicFont={' + names[0] + '}'
    return '\n'.join([r'\tracinglostchars=3',
        # Authored spaces are text, including between CJK and fallback glyphs.
        # xeCJK otherwise discards them as optional CJK source formatting.
        r'\xeCJKsetup{CJKspace=true}',
        # Noto CJK aliases U+002D and U+2011 to one glyph. A distinct pinned
        # glyph keeps ordinary text hyphens exact in PDF ToUnicode maps.
        r'\newfontfamily\RPLiteralHyphenFont[' + literal_options + ']{' + names[0] + '}',
        r'\DeclareRobustCommand{\RPLiteralHyphen}[1]{{\RPLiteralHyphenFont #1}}',
        families,
        r'\xeCJKenablefallback', r'\xeCJKDeclareCharClass{CJK}{' + ranges + '}'])


def stage_fonts(work):
    files = []
    for source, sha, name in ((FONT, FONT_SHA256, FONT_FILENAME), (LICENSE, LICENSE_SHA256, LICENSE_FILENAME),
                             (MATH_FONT, MATH_FONT_SHA256, MATH_FONT_FILENAME),
                             (MATH_LICENSE, MATH_LICENSE_SHA256, MATH_LICENSE_FILENAME),
                             (EMOJI_FONT, EMOJI_FONT_SHA256, EMOJI_FONT_FILENAME),
                             (EMOJI_LICENSE, EMOJI_LICENSE_SHA256, EMOJI_LICENSE_FILENAME)):
        (work / name).write_bytes(_fixed_bytes(source, sha))
        files.append({'filename': name, 'sha256': sha,
                      'media_type': 'font/ttf' if source in (FONT, MATH_FONT, EMOJI_FONT) else 'text/plain'})
    return files


def verify_staged_font(work):
    _fixed_bytes(work / FONT_FILENAME, FONT_SHA256)
    # Historical exports reference only DejaVu and do not acquire a new font
    # requirement. A current export must verify every support font it references.
    tex = (work / 'paper.tex').read_text(encoding='utf-8')
    for name, sha in ((MATH_FONT_FILENAME, MATH_FONT_SHA256), (EMOJI_FONT_FILENAME, EMOJI_FONT_SHA256)):
        if name in tex:
            _fixed_bytes(work / name, sha)


def missing_glyph_warnings(log):
    """Keep exact diagnostics, including wrapped XeTeX/xeCJK codepoints."""
    lines = log.splitlines()
    found = []
    for index, line in enumerate(lines):
        if 'Missing character:' in line or 'does not contain glyph' in line:
            found.append('\n'.join(lines[index:index+4]))
    return found
