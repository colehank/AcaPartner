"""Saved block/component order shared by reading and structured exports."""
from collections import Counter

from research_partner.storage.store import require


UNPLACED_HEADING = '附图与材料'


def block_markdown(block):
    text = str(block.get('text', ''))
    if block.get('kind') in {'heading', 'title'} and not text.startswith('#'):
        text = '#' * min(6, max(2, int(block.get('level', 2)))) + ' ' + text
    return text


def document_markdown(obj):
    content = obj['content']
    if 'markdown' in content:
        return content['markdown']
    lines = ['# ' + obj['title'], '']
    for block in content.get('blocks', []):
        if block.get('content_role') != 'preparation':
            lines.extend([block_markdown(block), ''])
    return '\n'.join(lines)


def ordered_segments(content, components):
    """Resolve exact block IDs, retaining all visible component occurrences.

    Multiple components may follow one unique block, in saved list order.
    Missing/ambiguous/excluded targets are errors, never guessed positions.
    """
    blocks = content.get('blocks', [])
    counts = Counter(block.get('id') for block in blocks)
    visible = {b.get('id') for b in blocks if b.get('content_role') != 'preparation'}
    placed, unplaced = {}, []
    boundaries = {'start': [], 'end': []}
    for index, component in enumerate(components):
        if isinstance(component, str): component = {}
        if component.get('content_role') == 'preparation':
            continue
        anchor = component.get('after_block_id')
        if anchor is None or anchor == '':
            unplaced.append(index)
            continue
        if anchor in ('start', 'end'):
            boundaries[anchor].append(index)
            continue
        require(isinstance(anchor, str) and 'markdown' not in content and counts[anchor] == 1 and anchor in visible,
                '图件正文位置不存在、重复或属于准备内容；未猜测位置或生成缺图成果',
                'component_anchor_invalid', 409,
                {'component_index': index, 'after_block_id': anchor,
                 'matching_blocks': counts.get(anchor, 0) if isinstance(anchor, str) else 0,
                 'excluded': isinstance(anchor, str) and anchor not in visible,
                 'opaque_markdown': 'markdown' in content})
        placed.setdefault(anchor, []).append(index)
    segments = [{'kind': 'component', 'index': index} for index in boundaries['start']]
    if 'markdown' in content:
        segments.append({'kind': 'markdown', 'markdown': content['markdown']})
    else:
        for block in blocks:
            if block.get('content_role') == 'preparation':
                continue
            segments.append({'kind': 'block', 'block': block})
            segments.extend({'kind': 'component', 'index': index} for index in placed.get(block.get('id'), []))
    segments.extend({'kind': 'component', 'index': index} for index in boundaries['end'])
    warnings = []
    if unplaced:
        segments.append({'kind': 'unplaced_heading', 'text': UNPLACED_HEADING})
        segments.extend({'kind': 'component', 'index': index} for index in unplaced)
        warnings.append('Components without after_block_id were retained after the body under an explicit unplaced-components heading.')
    return segments, warnings


def markdown_segments(obj, components, tail=''):
    sequence, warnings = ordered_segments(obj['content'], components)
    if not any(s['kind'] == 'component' for s in sequence):
        return [{'kind': 'markdown', 'markdown': document_markdown(obj) + tail}], warnings
    segments, text = [], ([] if 'markdown' in obj['content'] else ['# ' + obj['title']])
    def flush():
        if text:
            segments.append({'kind': 'markdown', 'markdown': '\n\n'.join(text)})
            text.clear()
    for segment in sequence:
        if segment['kind'] == 'component':
            flush(); segments.append(segment)
        elif segment['kind'] == 'block':
            text.append(block_markdown(segment['block']))
        elif segment['kind'] == 'markdown':
            text.append(segment['markdown'])
        else:
            text.append('## ' + segment['text'])
    if tail: text.append(tail)
    flush()
    return segments, warnings
