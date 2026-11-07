"""Core-independent Research Partner extension: index explicit source references.

Reads only the supplied exported object JSON files. Resolution is identity lookup,
never evidence assessment, citation discovery or scientific approval.
"""
import csv
import hashlib
import io
import json
from pathlib import Path
import sys

VERSION = '1.1.0'
FIELDS = ['referrer_id', 'referrer_revision', 'referrer_title', 'referrer_block',
          'referrer_context', 'reference_pointer', 'source_id', 'source_revision', 'source_block',
          'source_title', 'status', 'exact_text', 'raw_reference', 'referrer_input_sha256', 'source_input_sha256']


def pointer(value):
    return str(value).replace('~', '~0').replace('/', '~1')


def references(value, path='/content', block=''):
    if isinstance(value, dict):
        if isinstance(value.get('id'), str) and 'kind' in value:
            block = value['id']
        for key, item in value.items():
            here = path + '/' + pointer(key)
            if key == 'source_ref':
                yield here, block, item, True
            elif key == 'source_refs':
                if isinstance(item, list):
                    for index, ref in enumerate(item):
                        yield here + '/' + str(index), block, ref, True
                else:
                    yield here, block, item, False
            else:
                yield from references(item, here, block)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from references(item, path + '/' + str(index), block)


def referring_context(obj, location):
    value = obj
    for segment in location.strip('/').split('/'):
        key = segment.replace('~1', '/').replace('~0', '~')
        if key in ('source_ref', 'source_refs'):
            break
        value = value[int(key)] if isinstance(value, list) else value[key]
    if not isinstance(value, dict):
        return ''
    fields = {k: v for k, v in value.items() if k not in ('source_ref', 'source_refs') and isinstance(v, (str, int, float, bool))}
    return json.dumps(fields, ensure_ascii=False, sort_keys=True)


def index_rows(objects, documents):
    result = []
    for ident, revision in documents:
        obj, input_sha = objects[(ident, revision)]
        for location, block, ref, collection_valid in references(obj['content']):
            row = dict.fromkeys(FIELDS, '')
            row.update(referrer_id=ident, referrer_revision=revision,
                       referrer_title=obj.get('title', ''), referrer_block=block,
                       reference_pointer=location, referrer_input_sha256=input_sha,
                       referrer_context=referring_context(obj, location), raw_reference=json.dumps(ref, ensure_ascii=False, sort_keys=True))
            if not collection_valid or not isinstance(ref, dict) or not isinstance(ref.get('id'), str) or not ref['id'].strip() or type(ref.get('revision')) is not int or ref['revision'] < 1:
                row['status'] = 'invalid_reference'
            else:
                row.update(source_id=ref['id'], source_revision=ref['revision'], source_block=ref.get('block_id', ''))
                source = objects.get((ref['id'], ref['revision']))
                if 'block_id' in ref and (not isinstance(ref['block_id'], str) or not ref['block_id']):
                    row['status'] = 'invalid_block_reference'
                elif not source:
                    row['status'] = 'source_not_supplied'
                else:
                    target, row['source_input_sha256'] = source
                    row['source_title'] = target.get('title', '')
                    if 'block_id' not in ref:
                        row['status'] = 'object_resolved_no_block'
                    else:
                        collection = target['content'].get('blocks', [])
                        if not isinstance(collection, list):
                            row['status'] = 'invalid_source_blocks'
                            result.append(row)
                            continue
                        blocks = [b for b in collection if isinstance(b, dict) and b.get('id') == ref['block_id']]
                        if len(blocks) != 1:
                            row['status'] = 'block_missing' if not blocks else 'ambiguous_block'
                        elif not isinstance(blocks[0].get('text'), str):
                            row['status'] = 'block_resolved_without_text'
                        else:
                            row.update(status='block_text_resolved', exact_text=blocks[0]['text'])
            result.append(row)
    return result


def csv_text(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=FIELDS, lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue()


def markdown(rows):
    parts = ['# 来源引用定位清单',
             '本清单逐条展开输入文稿中的显式 source_ref/source_refs。解析表示指定对象修订和片段可在所给输入中找到，不表示论断获得科学支持、审阅通过或用户验收。未提供的来源保留为缺失状态，不补造内容。',
             'CSV 和 JSON 保留完整文字、逐条位置与输入 SHA256。文字字段为原样内容，电子表格导入时应按文本处理。',
             '精确定位：在所属 Research Partner 实例检索对象 ID，再在修订历史中选择所列修订；不要用当前文稿替代这里的指定版本。']
    groups = {}
    for row in rows:
        groups.setdefault((row['referrer_id'], row['referrer_revision'], row['referrer_title']), []).append(row)
    parts.append('## 引用文稿\n\n' + '\n'.join(f"- {title}（{ident} @{revision}）：{len(items)} 条引用" for (ident, revision, title), items in groups.items()))
    previous = None
    for number, row in enumerate(rows, 1):
        group = (row['referrer_id'], row['referrer_revision'])
        if group != previous:
            parts.append(f"## {row['referrer_title']}\n\n{row['referrer_id']} @{row['referrer_revision']}")
            previous = group
        parts += [f"### 引用 {number} · {row['referrer_block'] or row['reference_pointer']}",
                  '引用者上下文：\n\n' + '\n'.join('> ' + line for line in row['referrer_context'].split('\n')),
                  f"引用位置：`{row['reference_pointer']}`",
                  f"来源：{row['source_title']} · `{row['source_id']} @{row['source_revision']} / {row['source_block']}`；状态：`{row['status']}`",
                  f"引用者输入 SHA256：`{row['referrer_input_sha256']}`；来源输入 SHA256：`{row['source_input_sha256']}`"]
        if row['exact_text']:
            parts.append('\n'.join('> ' + line for line in row['exact_text'].split('\n')))
    return '\n\n'.join(parts) + '\n'


def load_inputs(assets, root):
    if not isinstance(assets, list) or not 1 <= len(assets) <= 100:
        raise ValueError('Supply 1..100 exported object assets')
    objects = {}; total = 0
    for asset in assets:
        path = (root / asset['path']).resolve()
        if not path.is_relative_to((root / 'inputs').resolve()) or not path.is_file():
            raise ValueError('Input must be a brokered file inside inputs')
        total += path.stat().st_size
        if total > 32 * 1024 * 1024:
            raise ValueError('Inputs exceed 32 MiB')
        data = path.read_bytes(); sha = hashlib.sha256(data).hexdigest()
        if sha != asset['sha']:
            raise ValueError('Input SHA256 mismatch')
        obj = json.loads(data)
        if not isinstance(obj, dict) or not isinstance(obj.get('id'), str) or type(obj.get('revision')) is not int or obj['revision'] < 1 or not isinstance(obj.get('content'), dict):
            raise ValueError('Input must be an exported object with exact identity')
        key = (obj['id'], obj['revision'])
        if key in objects:
            raise ValueError('Duplicate object/revision input')
        objects[key] = obj, sha
    return objects


def run(request, root):
    if request.get('protocol') != 1 or request.get('operation') != 'export_index':
        raise ValueError('Unsupported protocol or operation')
    inputs = request['input']; objects = load_inputs(inputs['assets'], root)
    requested = inputs.get('params', {}).get('documents')
    if requested is None:
        documents = sorted(objects)
    else:
        if not isinstance(requested, list) or not requested:
            raise ValueError('documents must identify at least one supplied revision')
        documents = []
        for ref in requested:
            if not isinstance(ref, dict) or set(ref) != {'id', 'revision'} or not isinstance(ref['id'], str) or type(ref['revision']) is not int:
                raise ValueError('Each document needs exact id and integer revision')
            key = (ref['id'], ref['revision'])
            if key not in objects or key in documents:
                raise ValueError('Document revision absent or duplicated')
            documents.append(key)
    rows = index_rows(objects, documents)
    out = root / 'outputs'; out.mkdir(exist_ok=True)
    (out / 'source-references.csv').write_text(csv_text(rows), encoding='utf-8')
    (out / 'source-references.md').write_text(markdown(rows), encoding='utf-8')
    (out / 'source-references.json').write_text(json.dumps({'schema_version': 1, 'extension_version': VERSION, 'references': rows, 'scientific_approval': False}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    counts = {status: sum(row['status'] == status for row in rows) for status in sorted({row['status'] for row in rows})}
    return {'protocol': 1, 'operation': 'export_index', 'ok': True,
            'result': {'version': VERSION, 'references': len(rows), 'statuses': counts,
                       'documents': [{'id': i, 'revision': r} for i, r in documents],
                       'scientific_approval': False, 'source_discovery_performed': False},
            'outputs': [{'path': 'outputs/source-references.csv', 'media_type': 'text/csv'},
                        {'path': 'outputs/source-references.md', 'media_type': 'text/markdown'},
                        {'path': 'outputs/source-references.json', 'media_type': 'application/json'}]}


if __name__ == '__main__':
    try:
        print(json.dumps(run(json.load(sys.stdin), Path.cwd()), ensure_ascii=False))
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({'protocol': 1, 'ok': False, 'error': str(error)}, ensure_ascii=False))
        raise SystemExit(1)
