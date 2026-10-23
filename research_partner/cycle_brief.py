"""Explicit native-note projection of a cycle's registered final source.

Reading or writing this brief never advances a cycle or grants execution.
Current permissions are checked even when the output is a historical revision.
"""
import copy
import re

from .store import digest, encoded, require


def _reference(value):
    require(isinstance(value, dict) and isinstance(value.get('id'), str)
            and value['id'] and type(value.get('revision')) is int
            and value['revision'] > 0 and isinstance(value.get('sha256'), str)
            and re.fullmatch('[a-f0-9]{64}', value['sha256']),
            '协作尚无完整的固定最终稿身份；未创建简报', 'not_ready', 409)
    return {key: value[key] for key in ('id', 'revision', 'sha256')}


def report(app, project, task, scope):
    s = app.store
    require(task['project_id'] == project['id']
            and task['payload'].get('kind') == 'research_cycle',
            '协作任务不属于本项目', 'forbidden', 403)
    state = task['result'].get('cycle', {})
    ref = _reference(state.get('final_source'))
    source = app.get(ref['id'], scope, ref['revision'])
    require(source['project_id'] == project['id'] and source['kind'] in {'report', 'note'},
            '协作最终稿的项目或类型不符', 'forbidden', 403)
    require(digest(source) == ref['sha256'], '协作最终稿摘要不符', 'integrity', 409)
    with s.connect() as c:
        s.assert_material_access(c, task['payload'])
        s.assert_source_access(c, project['id'], source['id'])
        s.assert_reference_access(c, project['id'], source['content'])
        s.assert_reference_access(c, project['id'], source['metadata'].get('source_refs', []))
        staged = state.get('final_revision')
        if staged:
            # This is the registered coordinator revision, not a new model
            # output. Later HEAD edits do not rewrite the fixed brief source.
            require({**staged.get('source_ref', {}), 'sha256': staged.get('source_sha256')} == ref,
                    '最终稿与协调者登记修订不符', 'integrity', 409)
            candidate = staged.get('candidate', {})
            require(candidate.get('id') == ref['id'] and candidate.get('revision') == ref['revision']
                    and candidate.get('source_sha256') == ref['sha256']
                    and candidate.get('candidate_sha256') == staged.get('candidate_sha256')
                    and digest({k: v for k, v in candidate.items() if k != 'candidate_sha256'}) == staged.get('candidate_sha256'),
                    '协调者最终稿登记内容不完整', 'integrity', 409)
            evidence = staged.get('materials', {}).get('adopted')
            require(isinstance(evidence, list), '协调者最终稿缺少固定材料记录', 'integrity', 409)
            producer = {'origin': 'coordinator_final_revision',
                        'generation': staged['generation'], 'candidate_sha256': staged['candidate_sha256']}
        else:
            integrator = s.task(state.get('integrator'), c)
            require(integrator['project_id'] == project['id']
                    and integrator['payload'].get('cycle_parent') == task['id']
                    and integrator['payload'].get('cycle_role') == 'integrator'
                    and any(child.get('id') == integrator['id'] and child.get('role') == 'integrator'
                            for child in state.get('children', [])),
                    '最终稿与原协作整合任务不符', 'integrity', 409)
            from .research_brief import report as research_report
            original, _ = research_report(app, project, integrator, scope)
            require(original['fixed_output'] == ref, '整合任务登记的固定最终稿不同', 'integrity', 409)
            evidence = original['evidence_revisions']
            producer = {'origin': 'integrator', 'task_id': integrator['id'],
                        'provider_receipt': original['provider_receipt']}
        for item in evidence:
            fixed = _reference(item)
            s.assert_source_access(c, project['id'], fixed['id'])
            require(digest(app.get(fixed['id'], scope, fixed['revision'])) == fixed['sha256'],
                    '最终稿固定材料摘要不符', 'integrity', 409)

    content = source['content']
    blocks, claims = content.get('blocks', []), content.get('claims', [])
    require(isinstance(blocks, list) and all(isinstance(b, dict) and isinstance(b.get('text'), str) for b in blocks)
            and isinstance(claims, list) and all(isinstance(claim, dict) and isinstance(claim.get('text'), str)
                and isinstance(claim.get('limitation', ''), str) and isinstance(claim.get('evidence_ids', []), list) for claim in claims)
            and isinstance(content.get('rationale', ''), str)
            and ('markdown' not in content or isinstance(content['markdown'], str)),
            '协作最终稿文字结构无效；未省略字段生成简报', 'integrity', 409)
    review = state.get('final_review')
    # A newly staged source can retain the previous review as history. It is
    # never labelled as the review of this different source.
    bound_review = review if isinstance(review, dict) and (review.get('object_id'), review.get('revision'), review.get('source_sha256')) == (ref['id'], ref['revision'], ref['sha256']) else None
    if bound_review:
        require(bound_review in s.review_records(ref['id'], ref['revision']),
                '最终稿审查不在原版本记录中', 'integrity', 409)
    record = {'task_id': task['id'], 'status': task['status'], 'phase': state.get('phase'),
              'fixed_output': ref, 'producer': producer, 'evidence_revisions': copy.deepcopy(evidence),
              'bound_final_review': copy.deepcopy(bound_review),
              'limits': copy.deepcopy(task['payload'].get('cycle_config', {}).get('limits', {})),
              'allocated_calls': state.get('reserved_calls'), 'allocated_seconds': state.get('reserved_seconds')}
    from .collaboration_brief import _quote
    lines = ['### 科研协作固定成果回报', '父任务：' + task['id'],
             '实际状态：' + task['status'] + '；阶段：' + str(state.get('phase')),
             _quote(source['title']), f'固定成果：{ref["id"]} r{ref["revision"]}；SHA `{ref["sha256"]}`',
             f'[打开原协作与固定整合稿](/?project={project["id"]}&task={task["id"]})',
             '以下保留已登记最终稿原文与限制；整理为笔记不代表采用、科学批准或再次执行。',
             '#### 最终稿原文']
    lines += [_quote(block['text']) for block in blocks]
    if content.get('markdown'):
        lines += ['#### 原Markdown正文', _quote(content['markdown'])]
    if claims:
        lines += ['#### 原论点与限制']
        for claim in claims:
            lines += [_quote(claim['text']), '原限制：', _quote(claim.get('limitation', '')),
                      '登记证据：' + encoded(claim.get('evidence_ids', []))]
    if content.get('rationale'):
        lines += ['#### 原论证说明', _quote(content['rationale'])]
    lines += ['#### 此版本的审查记录']
    if bound_review:
        lines += [_quote(encoded(bound_review))]
    else:
        lines += ['此固定版本尚无已登记最终审查；旧版本的审查不转签。']
    lines += ['#### 固定来源']
    for item in evidence:
        lines += [f'- {item["id"]} r{item["revision"]}；SHA `{item["sha256"]}`']
    lines += ['#### 原协作资源合同', '上限：`' + encoded(record['limits']) + '`',
              '已分配调用额度：' + str(record['allocated_calls']) + '；已分配秒数：' + str(record['allocated_seconds']),
              '分配额度不代表实际模型耗时、内部API次数或账单；完整记录见原任务。']
    return record, lines
