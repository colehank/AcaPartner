"""Exact Unicode source ranges across stable manuscript blocks.

An ambiguous split, reorder or changed quote is never silently reattached.
The existing annotation and ReviewRound remain the authority; this is a source
adapter, not a second document or review store.
"""
import copy
from research_partner.storage.store import require


def validate_range(blocks, anchor):
    require(isinstance(anchor, dict) and set(anchor) == {
        'kind', 'offset_unit', 'block_id', 'segments', 'quote'
    } and anchor['kind'] == 'manuscript_range' and
        anchor['offset_unit'] == 'unicode_codepoint', '连续选区格式无效')
    segments = anchor['segments']
    require(isinstance(segments, list) and 2 <= len(segments) <= 1000,
            '跨段选区需要完整且有界的段落范围')
    ids = [block['id'] for block in blocks]
    positions = []
    for i, segment in enumerate(segments):
        require(isinstance(segment, dict) and set(segment) == {'block_id', 'start', 'end', 'quote'},
                '选区段落字段无效')
        require(segment['block_id'] in ids, '选区段落已移除，请重新定位', 'anchor_conflict', 409)
        position = ids.index(segment['block_id']); positions.append(position)
        text = blocks[position]['text']; start, end = segment['start'], segment['end']
        require(type(start) is int and type(end) is int and 0 <= start <= end <= len(text),
                '选区范围无效')
        require(text[start:end] == segment['quote'], '选中文字已改变，请重新定位', 'anchor_conflict', 409)
        require((i == 0 or start == 0) and (i == len(segments)-1 or end == len(text)),
                '跨段选区必须包括段落之间的完整正文')
    require(positions == list(range(positions[0], positions[0]+len(positions))),
            '选区段落顺序已改变，请重新定位', 'anchor_conflict', 409)
    require(anchor['block_id'] == segments[0]['block_id'] and
            anchor['quote'] == '\n\n'.join(segment['quote'] for segment in segments) and
            any(segment['quote'] for segment in segments), '选区原文或起点不一致')
    return copy.deepcopy(anchor)


def annotation_targets(anchor):
    if anchor.get('kind') == 'manuscript_range':
        return [segment['block_id'] for segment in anchor.get('segments', [])]
    return [anchor['block_id']] if anchor.get('block_id') else []
