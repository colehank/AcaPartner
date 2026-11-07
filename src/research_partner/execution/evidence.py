"""Deterministic, lossless source files for new native capsules.

The original packet remains byte-identical. Source IDs are the product IDs;
revision collisions receive explicit suffixes. Existing capsules are not migrated.
"""
from __future__ import annotations
import json
import re
from research_partner.storage.store import digest, require


LAYOUT_VERSION = 2


def evidence_layout(packet_bytes, objective, disclosure):
    require(len(packet_bytes) <= 65536, '原生冻结材料超过 65536 字节上限', 'context_limit', 413)
    packet = json.loads(packet_bytes)
    require(isinstance(packet, dict) and isinstance(packet.get('objects'), list)
            and isinstance(packet.get('context'), dict), '冻结材料结构无效', 'integrity', 409)
    entries, files = [], {}

    def add(ident, relative, data, source, **metadata):
        require(ident not in {e['id'] for e in entries}, '原生材料 ID 冲突', 'integrity', 409)
        require(len(data) <= 65536, '单项原生材料超过读取上限', 'context_limit', 413)
        entries.append({'id': ident, 'path': relative, 'sha256': digest(data),
                        'disclosure': disclosure, 'source': source, **metadata})
        files[relative] = data

    def serialized(value):
        return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')

    add('materials', 'evidence/materials.json', packet_bytes,
        'Complete original frozen packet; use individual sources below to avoid duplicate reading', role='bundle')
    add('task-context', 'evidence/task-context.json', serialized({'objective': objective, 'context': packet['context']}),
        'Complete frozen objective and context, including role-specific instructions and source selection', role='context')
    objects = packet['objects']
    require(len(objects) <= 28, '原生材料目录超过 30 项；未静默丢弃', 'context_limit', 413)
    counts = {}
    for obj in objects:
        require(isinstance(obj, dict) and isinstance(obj.get('id'), str)
                and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', obj['id'])
                and type(obj.get('revision')) is int and obj['revision'] > 0,
                '原生材料缺少有效成果 ID 与修订', 'integrity', 409)
        counts[obj['id']] = counts.get(obj['id'], 0) + 1
    for index, obj in enumerate(objects):
        ident = obj['id'] if counts[obj['id']] == 1 else f"{obj['id']}_r{obj['revision']}"
        add(ident, f'evidence/source-{index:02d}.json', serialized(obj),
            f"Frozen research object {obj['id']} revision {obj['revision']}",
            role='source', object_id=obj['id'], revision=obj['revision'],
            source_sha256=obj.get('source_sha256', digest(obj)))
    return entries, files


def verify_evidence_layout(contract, packet_bytes, read_file):
    """Verify exact new layout or the historical one-bundle contract, fail closed."""
    evidence = contract.get('evidence')
    if 'evidence_layout_version' not in contract:
        require(isinstance(evidence, list) and len(evidence) == 1 and isinstance(evidence[0], dict)
                and evidence[0].get('id') == 'materials' and evidence[0].get('path') == 'evidence/materials.json'
                and evidence[0].get('sha256') == digest(packet_bytes)
                and read_file('evidence/materials.json') == packet_bytes,
                '旧原生会话材料与当前任务冻结材料不一致', 'provider_checkpoint_missing', 503)
        return
    require(type(contract['evidence_layout_version']) is int and contract['evidence_layout_version'] == LAYOUT_VERSION
            and isinstance(evidence, list) and evidence and isinstance(evidence[0], dict),
            '原生材料合同版本无法验证', 'provider_checkpoint_missing', 503)
    expected, files = evidence_layout(packet_bytes, contract['objective'], evidence[0].get('disclosure'))
    require(contract.get('packet_sha256') == digest(packet_bytes) and evidence == expected,
            '原生来源目录与冻结材料不一致', 'provider_checkpoint_missing', 503)
    for relative, data in files.items():
        require(read_file(relative) == data, '原生来源文件与冻结修订不一致', 'provider_checkpoint_missing', 503)
