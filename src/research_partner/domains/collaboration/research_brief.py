"""Read a Task's immutable research output for an explicit native-note brief.

This projects existing prose, claims and limitations. It never generates a
summary, grants execution, adopts the report, or substitutes current HEAD.
"""
from research_partner.storage.store import digest, encoded, require


def report(app, project, task, scope):
    payload, result = task['payload'], task['result']
    kind = payload.get('context', {}).get('output')
    revision, ident = result.get('revision'), result.get('object_id')
    require(task['status'] == 'generated' and payload.get('kind') == 'research'
            and payload.get('target_id') is None and payload.get('base_revision') is None
            and kind in {'report', 'note'} and isinstance(ident, str) and ident
            and type(revision) is int and revision > 0,
            '研究任务尚无可引用的独立固定候选；未创建简报', 'not_ready', 409)
    source = app.get(ident, scope, revision)
    require(source['project_id'] == project['id'] and source['kind'] == kind
            and source['metadata'].get('task_id') == task['id'],
            '研究候选的项目、类型或产出任务不一致', 'forbidden', 403)
    receipt = result.get('provider')
    steps = {s['step_key']: s for s in task.get('steps', [])}
    persist, model = steps.get('persist', {}), steps.get('model', {})
    require(isinstance(receipt, dict) and receipt
            and source['metadata'].get('provider_receipt') == receipt
            and model.get('status') == 'done' and model.get('data', {}).get('provider') == receipt
            and persist.get('status') == 'done'
            and persist.get('data') == {'object_id': ident, 'revision': revision, 'sha256': digest(source)},
            '研究候选与原固定保存记录或生产者回执不一致', 'integrity', 409)
    evidence = source['metadata'].get('evidence_revisions')
    require(isinstance(evidence, list), '研究候选缺少固定证据记录', 'integrity', 409)
    # The caller's ownership does not reinstate a source grant to this project.
    # Verify actual fixed source bytes while using *current* sharing permission.
    with app.store.connect() as c:
        app.store.assert_source_access(c, project['id'], ident)
        app.store.assert_reference_access(c, project['id'], source['content'])
        app.store.assert_reference_access(c, project['id'], payload.get('context', {}).get('materials', []))
        for ref in evidence:
            require(isinstance(ref, dict) and isinstance(ref.get('id'), str)
                    and type(ref.get('revision')) is int and ref['revision'] > 0,
                    '研究证据的固定引用无效', 'integrity', 409)
            app.store.assert_source_access(c, project['id'], ref['id'])
            fixed = app.get(ref['id'], scope, ref['revision'])
            require(digest(fixed) == ref.get('sha256'), '研究证据摘要与固定保存版不符', 'integrity', 409)
    content = source['content']
    blocks, claims = content.get('blocks', []), content.get('claims', [])
    require(isinstance(blocks, list) and all(isinstance(b, dict) and isinstance(b.get('text'), str) for b in blocks)
            and isinstance(claims, list) and all(isinstance(c, dict) and isinstance(c.get('text'), str)
                and isinstance(c.get('limitation', ''), str) and isinstance(c.get('evidence_ids', []), list) for c in claims),
            '研究候选文字结构无效；未丢弃字段生成简报', 'integrity', 409)
    require(isinstance(content.get('rationale', ''), str), '研究候选论证字段无效', 'integrity', 409)
    record = {'task_id': task['id'], 'status': task['status'],
              'fixed_output': {'id': ident, 'revision': revision, 'sha256': digest(source)},
              'provider_receipt': receipt, 'evidence_revisions': evidence}
    from research_partner.domains.collaboration.brief import _quote
    lines = ['### 研究候选回报', '任务：' + task['id'], '实际状态：' + task['status'],
             _quote(source['title']), f'固定成果：{ident} r{revision}；SHA `{digest(source)}`',
             f'[打开原任务与固定研究候选](/?project={project["id"]}&task={task["id"]})',
             '以下保留候选原文与限制；整理为笔记不代表采用、科学批准或再次执行。',
             '#### 候选原文']
    for block in blocks:
        lines.append(_quote(block['text']))
    if claims:
        lines.append('#### 候选论点与原限制')
        for claim in claims:
            lines += [_quote(claim['text']), '原限制：', _quote(claim.get('limitation', '')),
                      '登记证据：' + encoded(claim.get('evidence_ids', []))]
    if content.get('rationale'):
        lines += ['#### 原论证说明', _quote(content['rationale'])]
    lines += ['#### 固定来源']
    for ref in evidence:
        lines.append(f'- {ref["id"]} r{ref["revision"]}；SHA `{ref["sha256"]}`')
    # Unprojected fields remain in the immutable source. Never turn the first
    # paragraph into an invented task summary or rewrite the saved report.
    return record, lines
