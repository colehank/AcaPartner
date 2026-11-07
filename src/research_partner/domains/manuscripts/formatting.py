"""Direct operator text proposals and independent, bounded manuscript layout.

No task/model is created here. Proposals remain outside the source until an
explicit decision; layout generation does not compile or read local files.
"""
from __future__ import annotations
import copy
import contextlib
import difflib
import hashlib
import json
import math
import re
import unicodedata
from research_partner.storage.store import require, digest, encoded, now, uid, Problem
from research_partner.domains.manuscripts import revision as mr
from research_partner.domains.workspace.management import authority_scope
from research_partner.domains.manuscripts.sequence import ordered_segments
from research_partner.domains.manuscripts.citations import citation_at

KEY = 'manuscript_edit40:'
DEFAULT_FORMAT = {'font_family': 'Noto Serif CJK SC', 'font_size_pt': 11,
                  'line_spacing': 1.35, 'paragraph_spacing_pt': 6, 'page_size': 'a4',
                  'margin_top_mm': 25, 'margin_bottom_mm': 25,
                  'margin_left_mm': 25, 'margin_right_mm': 25, 'columns': 1}


def normalize_format(value=None):
    value = {} if value is None else value
    require(isinstance(value, dict) and set(value) <= set(DEFAULT_FORMAT), '格式字段不支持', 'invalid_format', 422)
    result = {**DEFAULT_FORMAT, **value}
    family = result['font_family']
    require(isinstance(family, str) and re.fullmatch(r'[\w][\w .-]{0,79}', family, re.UNICODE),
            '字体必须是安全的已安装 family 名称，不能包含 LaTeX 命令', 'invalid_format', 422)
    require(result['page_size'] in {'a4', 'letter'}, '仅支持 A4 或 Letter 纸张', 'invalid_format', 422)
    require(type(result['columns']) is int and result['columns'] in {1, 2}, '仅支持单栏或双栏', 'invalid_format', 422)
    limits = {'font_size_pt': (8, 24), 'line_spacing': (1, 2.5), 'paragraph_spacing_pt': (0, 36),
              **{k: (10, 60) for k in DEFAULT_FORMAT if k.startswith('margin_')}}
    for key, (low, high) in limits.items():
        v = result[key]
        require(type(v) in (int, float) and math.isfinite(v) and low <= v <= high,
                '格式参数超出支持范围：' + key, 'invalid_format', 422)
    return result


def format_for(obj, override=None):
    saved = normalize_format(obj.get('metadata', {}).get('manuscript_format'))
    require(override is None or isinstance(override, dict), '格式预览必须是对象', 'invalid_format', 422)
    return normalize_format({**saved, **(override or {})})


def _get(c, key, default=None):
    row = c.execute('SELECT value FROM kv WHERE key=?', (KEY + key,)).fetchone()
    return json.loads(row[0]) if row else default


def _put(c, key, value):
    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (KEY + key, encoded(value)))


def _source(app, ident, scope, c, principal=None):
    obj = mr.source(app, ident, scope, c)
    if principal is not None: mr.source(app, ident, authority_scope(app, principal), c)
    mr.blocks(obj)
    return obj


def _key(data):
    key = data.get('request_key')
    require(isinstance(key, str) and 0 < len(key) <= 180, '需要稳定的有限请求标识')
    return key


def _exact_revision(obj, expected):
    require(type(expected) is int and obj['revision'] == expected,
            '稿件已变化，请保留草稿并重新读取', 'conflict', 409)


def _proposal(c, obj, ident=None):
    ident = ident or _get(c, 'latest:' + obj['id'])
    if not ident: return None
    require(isinstance(ident, str), '修订标识无效')
    record = _get(c, 'proposal:' + ident)
    require(record and record['object_id'] == obj['id'], '此稿件没有该修订', 'not_found', 404)
    require(digest(record['immutable']) == record['proposal_sha256'], '修订记录完整性不符', 'integrity', 409)
    return record


def _blocked_delete(obj, ident):
    refs = obj['content'].get('components', [])
    sections = obj.get('metadata', {}).get('article', {}).get('sections', [])
    return any(r.get('after_block_id') == ident for r in refs if isinstance(r, dict)) or any(s.get('heading_block_id') == ident for s in sections)


def _conflict(obj, record, row):
    current = mr.blocks(obj)
    if row['op'] != 'insert':
        if current.get(row['block_id']) != row['base_block']: return '目标段落已改变或移除'
        if row['op'] == 'delete' and _blocked_delete(obj, row['block_id']): return '该段仍被图件位置或章节绑定引用，请先明确调整绑定'
        return None
    if row['block_id'] in current: return '新增段落标识已被使用'
    inserted = {r['block_id'] for r in record['immutable']['changes'] if r['op'] == 'insert' and record['decisions'].get(r['id'], {}).get('decision') == 'accepted'}
    deleted = {r['block_id'] for r in record['immutable']['changes'] if r['op'] == 'delete' and record['decisions'].get(r['id'], {}).get('decision') == 'accepted'}
    expected = [b['id'] for b in record['immutable']['base_blocks'] if b['id'] not in deleted]
    if [b['id'] for b in obj['content']['blocks'] if b['id'] not in inserted] != expected: return '正文结构同期变化，不能猜测插入位置'
    if row['after_block_id'] != 'start' and row['after_block_id'] not in current: return '插入锚点尚未采用或已移除'
    return None


def _apply(content, row, record):
    blocks = content['blocks']
    if row['op'] == 'replace': next(b for b in blocks if b['id'] == row['block_id'])['text'] = row['after']
    elif row['op'] == 'delete': content['blocks'] = [b for b in blocks if b['id'] != row['block_id']]
    else:
        # Same-anchor insertions keep proposal order, including when adopted in
        # separate decisions. Existing adopted new blocks are not duplicated.
        ordered = record['immutable']['changes']; at = ordered.index(row)
        prior = [r['block_id'] for r in ordered[:at] if r['op'] == 'insert' and r['after_block_id'] == row['after_block_id']]
        ids = [b['id'] for b in blocks]
        anchor = next((ident for ident in reversed(prior) if ident in ids), row['after_block_id'])
        index = 0 if anchor == 'start' else ids.index(anchor) + 1
        blocks.insert(index, copy.deepcopy(row['new_block']))


def text_diff(before, after):
    # Every character is retained, including multiple separated edits.
    result = []
    for op, a, b, x, y in difflib.SequenceMatcher(None, before, after, autojunk=False).get_opcodes():
        if op == 'equal': result.append({'kind': 'equal', 'text': before[a:b]})
        else:
            if a != b: result.append({'kind': 'delete', 'text': before[a:b]})
            if x != y: result.append({'kind': 'insert', 'text': after[x:y]})
    return result


def _view(obj, record):
    current = copy.deepcopy(obj['content']['blocks'])
    if not record:
        return {'object_id': obj['id'], 'current_revision': obj['revision'], 'proposal_id': None, 'base_revision': None,
                'decision_version': 0, 'settled': False, 'receipts': [], 'changes': [], 'original_blocks': current,
                'latest_blocks': current, 'marked_blocks': [{'block': b, 'state': 'clean'} for b in current], 'can_render_latest': True}
    projected = copy.deepcopy(obj); rows = []; shadow = copy.deepcopy(record)
    for raw in record['immutable']['changes']:
        decision = record['decisions'].get(raw['id']); state = decision['decision'] if decision else 'pending'
        conflict = _conflict(projected, shadow, raw) if state == 'pending' else None
        row = {k: copy.deepcopy(v) for k, v in raw.items() if k not in {'base_block', 'new_block'}}
        rows.append({**row, 'state': state, 'can_accept': state == 'pending' and not conflict,
                     'conflict': bool(conflict), 'conflict_reason': conflict, 'diff': text_diff(raw['before'], raw['after'])})
        if state == 'pending' and not conflict:
            _apply(projected['content'], raw, shadow)
            shadow['decisions'][raw['id']] = {'decision': 'accepted'}
    # Markup exists only in this projection, never in source block text.
    pending = {r['block_id']: r for r in rows if r['state'] == 'pending'}
    marked = []
    # Start from source order with inserted blocks, then retain deleted originals.
    for b in current:
        row = pending.get(b['id'])
        marked.append({'block': b, 'state': 'pending' if row else 'clean', **({'change_id': row['id'], 'op': row['op'], 'before': row['before'], 'after': row['after'], 'diff': row['diff']} if row else {})})
    for raw in record['immutable']['changes']:
        if raw['op'] != 'insert' or raw['block_id'] not in pending: continue
        row = pending[raw['block_id']]; ids = [m['block']['id'] for m in marked]
        same_before = [r['block_id'] for r in record['immutable']['changes'][:record['immutable']['changes'].index(raw)] if r['op'] == 'insert' and r['after_block_id'] == raw['after_block_id']]
        anchor = next((i for i in reversed(same_before) if i in ids), raw['after_block_id'])
        index = 0 if anchor == 'start' else ids.index(anchor)+1 if anchor in ids else len(ids)
        marked.insert(index, {'block': copy.deepcopy(raw['new_block']), 'state': 'pending', 'change_id': row['id'], 'op': 'insert', 'before': '', 'after': row['after'], 'diff': row['diff']})
    return {'object_id': obj['id'], 'proposal_id': record['id'], 'proposal_sha256': record['proposal_sha256'],
            'base_revision': record['immutable']['base_revision'], 'current_revision': obj['revision'],
            'decision_version': record['decision_version'], 'settled': len(record['decisions']) == len(rows),
            'proposer': record['immutable']['proposer'], 'changes': rows,
            'original_blocks': copy.deepcopy(record['immutable']['base_blocks']),
            'latest_blocks': projected['content']['blocks'], 'marked_blocks': marked,
            'can_render_latest': not any(r['conflict'] for r in rows), 'receipts': copy.deepcopy(record['receipts'])}


def _track(app, data, scope, principal, c, obj):
    require(set(data) <= {'action', 'object_id', 'expected_revision', 'changes', 'request_key'}, '文字修订字段不支持')
    key = _key(data); fingerprint = digest({'data': data, 'principal': principal})
    previous = _get(c, 'request:' + obj['id'] + ':' + key)
    if previous:
        require(previous['fingerprint'] == fingerprint, '重复请求内容不同', 'idempotency_conflict', 409)
        return _view(obj, _proposal(c, obj, previous['proposal_id']))
    _exact_revision(obj, data.get('expected_revision'))
    from research_partner.packaging.compatibility import require_features
    require_features(c, ['user_text_revision_v1'])
    changes = data.get('changes')
    require(isinstance(changes, list) and 0 < len(changes) <= 200 and len(encoded(changes).encode()) <= 256000,
            '请提交1–200项有限文字增删修订', 'edit_limit', 413)
    by_id = mr.blocks(obj); rows = []; seen = set(); known = set(by_id)
    for item in changes:
        require(isinstance(item, dict), '修订项必须是对象')
        op = item.get('op'); require(op in {'replace', 'insert', 'delete'}, '仅支持正文替换、新增和删除')
        if op == 'insert':
            require(set(item) == {'op', 'block', 'after_block_id'}, '新增修订字段不支持')
            b = item['block']; anchor = item['after_block_id']
            require(isinstance(b, dict) and {'id', 'kind', 'text'} <= set(b) <= {'id', 'kind', 'text', 'level'}, '新增段落字段不支持')
            ident = b.get('id')
            require(isinstance(ident, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,180}', ident) and ident not in known and ident != 'start', '新增段落标识须稳定且未使用')
            require(b.get('kind') in {'paragraph', 'heading'} and ('level' not in b or type(b['level']) is int and 1 <= b['level'] <= 6), '新增段落类型无效')
            require(isinstance(anchor, str) and (anchor == 'start' or anchor in known), '新增段落需要明确的既有或本轮先前新增锚点')
            before = ''; after = b['text']; base = None; extra = {'after_block_id': anchor, 'new_block': copy.deepcopy(b)}
        else:
            require(set(item) == ({'op', 'block_id', 'text'} if op == 'replace' else {'op', 'block_id'}), '文字修订字段不支持')
            ident = item['block_id']; require(isinstance(ident, str) and ident in by_id, '修订段落不在当前来源')
            base = by_id[ident]; require(base.get('content_role') != 'preparation', '准备内容请在工坊笔记修订')
            before = base['text']; after = item['text'] if op == 'replace' else ''; extra = {}
            if op == 'delete': require(not _blocked_delete(obj, ident), '该段仍被图件位置或章节绑定引用，请先明确调整绑定', 'anchor_dependency', 409)
        require(ident not in seen, '同一段落不能包含相互重叠的修订'); seen.add(ident); known.add(ident)
        require(isinstance(after, str) and len(after) <= 30000 and (op != 'replace' or after != before), '修订文字过长或没有变化')
        rows.append({'id': 'change-' + str(len(rows)+1), 'op': op, 'block_id': ident,
                     'before': before, 'after': after, 'base_block': copy.deepcopy(base), **extra})
    deleted = {r['block_id'] for r in rows if r['op'] == 'delete'}
    require(not any(r.get('after_block_id') in deleted for r in rows), '不能同时删除本轮新增段落的锚点')
    immutable = {'object_id': obj['id'], 'base_revision': obj['revision'], 'base_sha256': digest(obj),
                 'base_blocks': copy.deepcopy(obj['content']['blocks']), 'changes': rows,
                 'proposer': {'role': 'operator', 'actor': mr.actor(principal)}, 'created_at': now()}
    record = {'id': uid('EDIT'), 'object_id': obj['id'], 'immutable': immutable,
              'proposal_sha256': digest(immutable), 'decision_version': 0, 'decisions': {}, 'receipts': []}
    _put(c, 'proposal:' + record['id'], record); _put(c, 'latest:' + obj['id'], record['id'])
    _put(c, 'request:' + obj['id'] + ':' + key, {'fingerprint': fingerprint, 'proposal_id': record['id']})
    app.store.event(c, 'manuscript.edit.proposed', obj['id'], {'proposal_id': record['id'], 'proposal_sha256': record['proposal_sha256']}, mr.actor(principal))
    return _view(obj, record)


def _decide(app, data, principal, c, obj, record, *, direct_save=False, direct_caption_edits=(), direct_title=None):
    # Only the internal operator text-save path can supply its already checked
    # occurrence edits. Public suggestion decisions retain their original scope.
    require(direct_save or (not direct_caption_edits and direct_title is None), '修订决定不能附加直接文字修改')
    require(set(data) <= {'action', 'object_id', 'proposal_id', 'expected_revision', 'expected_decision_version', 'decisions', 'request_key'}, '文字决定字段不支持')
    require(record and data.get('proposal_id') == record['id'], '请明确选择已查看的修订', 'conflict', 409)
    key = _key(data); fingerprint = digest({'data': data, 'principal': principal})
    previous = _get(c, 'decision:' + record['id'] + ':' + key)
    if previous:
        require(previous['fingerprint'] == fingerprint, '重复决定内容不同', 'idempotency_conflict', 409)
        return previous['receipt']
    _exact_revision(obj, data.get('expected_revision'))
    require(type(data.get('expected_decision_version')) is int and data['expected_decision_version'] == record['decision_version'], '修订决定已变化', 'conflict', 409)
    choices = data.get('decisions'); require(isinstance(choices, list) and choices and len(choices) <= len(record['immutable']['changes']), '请逐项接受或拒绝')
    rows = {r['id']: r for r in record['immutable']['changes']}; selected = {}
    for choice in choices:
        require(isinstance(choice, dict) and set(choice) == {'change_id', 'decision'} and isinstance(choice['change_id'], str) and choice['change_id'] in rows and choice['change_id'] not in selected and choice['change_id'] not in record['decisions'] and choice['decision'] in {'accept', 'reject'}, '修订选择无效或已决定')
        selected[choice['change_id']] = choice['decision']
    if not direct_save and any(choice=='accept' for choice in selected.values()):
        row=c.execute('SELECT value FROM kv WHERE key=?',('desk_w1a:drafts:'+obj['project_id'],)).fetchone()
        draft=(json.loads(row[0]) if row else {}).get('value',{}).get('manuscript',{})
        require(not draft.get('dirty'),'当前稿件有未保存草稿，旧建议不能覆盖新手改','unsaved_manuscript',409)
    result = copy.deepcopy(obj); changed = False
    for row in record['immutable']['changes']:
        if selected.get(row['id']) != 'accept': continue
        reason = _conflict(result, record, row)
        require(not reason, reason or '', 'conflict', 409, {'change_id': row['id']})
        _apply(result['content'], row, record); changed = True
        # Make earlier same-transaction inserts/deletes visible to later checks.
        record['decisions'][row['id']] = {'decision': 'accepted'}
    if changed:
        for edit in direct_caption_edits:
            result['content']['components'][edit['index']]['caption'] = edit['text']
        ordered_segments(result['content'], result['content'].get('components', []))
        result = app.store.save(obj['id'], obj['revision'], content=result['content'], title=direct_title, actor=mr.actor(principal), reason='explicit operator tracked edit ' + record['id'], merge=False, connection=c)
    receipt = {'object_id': obj['id'], 'proposal_id': record['id'], 'base_revision': obj['revision'],
               'result_revision': result['revision'], 'result_sha256': digest(result), 'source_changed': changed,
               'decision_version': record['decision_version']+1, 'decisions': choices, 'operator': mr.actor(principal),
               'at': now(), 'scientific_execution': False, 'scientific_approval': False, 'model_called': False, 'object': result}
    for ident, decision in selected.items(): record['decisions'][ident] = {'decision': 'accepted' if decision == 'accept' else 'rejected', 'result_revision': result['revision'], 'operator': mr.actor(principal)}
    record['decision_version'] += 1; record['receipts'].append({k: v for k, v in receipt.items() if k != 'object'})
    _put(c, 'proposal:' + record['id'], record); _put(c, 'decision:' + record['id'] + ':' + key, {'fingerprint': fingerprint, 'receipt': receipt})
    app.store.event(c, 'manuscript.edit.decided', obj['id'], {k: v for k, v in receipt.items() if k != 'object'}, mr.actor(principal))
    return receipt


def dispatch(app, data, scope, principal=None):
    principal = principal or {'kind': 'local_operator'}
    require(scope is None or principal.get('kind') != 'local_operator', '受限操作需要当前身份', 'forbidden', 403)
    action = data.get('action')
    require(action in {'manuscript.edit.track', 'manuscript.edit.view', 'manuscript.edit.decide', 'manuscript.format.view', 'manuscript.format.save'}, '文稿格式或修订操作不支持')
    with app.store.transaction() as c:
        obj = _source(app, data.get('object_id'), scope, c, principal)
        if action == 'manuscript.edit.track': return _track(app, data, scope, principal, c, obj)
        if action == 'manuscript.edit.view':
            require(set(data) <= {'action', 'object_id', 'proposal_id'}, '文字查看字段不支持')
            return _view(obj, _proposal(c, obj, data.get('proposal_id')))
        if action == 'manuscript.edit.decide': return _decide(app, data, principal, c, obj, _proposal(c, obj, data.get('proposal_id')))
        require(set(data) <= ({'action', 'object_id', 'expected_revision', 'format'} if action.endswith('.save') else {'action', 'object_id'}), '格式字段不支持')
        changed = False
        if action.endswith('.save'):
            _exact_revision(obj, data.get('expected_revision')); value = normalize_format(data.get('format'))
            changed = value != obj['metadata'].get('manuscript_format')
            if changed: obj = app.store.save(obj['id'], obj['revision'], metadata={**obj['metadata'], 'manuscript_format': value}, actor=mr.actor(principal), reason='independent manuscript layout', merge=False, connection=c)
        value = format_for(obj)
        return {'object_id': obj['id'], 'revision': obj['revision'], 'format_revision': obj['revision'], 'format': value,
                'format_sha256': digest(value), 'format_changed': changed, 'source_changed': False, 'object': obj}


def render_source(app, data, scope, *, connection=None):
    """Exact saved or latest candidate projection; never writes source/history."""
    # Explicit pins are assertions, including falsy values. They must never be
    # discarded and silently resolve to whichever candidate is current.
    pins = {key: data[key] for key in ('candidate_sha256', 'proposal_sha256') if key in data}
    for key, value in pins.items():
        require(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{64}', value),
                '显式候选摘要必须是 64 位小写十六进制：' + key, 'invalid_candidate_pin', 422)
    require(not pins or data.get('proposal_id') or data.get('revision_task_id'),
            '显式候选摘要需要准确候选来源', 'invalid_candidate_pin', 422)
    require(not (data.get('proposal_id') and 'candidate_sha256' in pins),
            '操作者修订使用 proposal_sha256，不存在模型 candidate_sha256', 'invalid_candidate_pin', 422)
    with (contextlib.nullcontext(connection) if connection is not None else app.store.transaction()) as c:
        obj = _source(app, data.get('object_id'), scope, c); _exact_revision(obj, data.get('expected_revision'))
        origin = {'object_id': obj['id'], 'revision': obj['revision'], 'source_sha256': digest(obj), 'source_mode': 'saved', 'candidate_applied': False}
        require(not (data.get('proposal_id') and data.get('revision_task_id')), '请选择一种准确候选来源')
        if data.get('proposal_id'):
            record = _proposal(c, obj, data['proposal_id'])
            require('proposal_sha256' not in pins or pins['proposal_sha256'] == record['proposal_sha256'],
                    '操作者修订提案摘要不符', 'conflict', 409)
            view = _view(obj, record)
            require(view['can_render_latest'], '候选与当前正文冲突，不能渲染为最新稿', 'conflict', 409)
            obj = copy.deepcopy(obj); obj['content']['blocks'] = view['latest_blocks']
            origin.update(source_mode='latest_operator_candidate', proposal_id=record['id'], proposal_sha256=record['proposal_sha256'], decision_version=record['decision_version'])
        elif data.get('revision_task_id'):
            pin = {'task_id': data['revision_task_id'], **pins}
            task, contract, record, state = mr.proposal(app, pin, scope, c)
            require(contract['object_id'] == obj['id'] and record, '模型候选不属于当前稿件', 'conflict', 409)
            require(all(record.get(key) == value for key, value in pins.items()),
                    '模型候选摘要不符', 'conflict', 409)
            view = mr.view(app, task, contract, record, state, scope, c)
            obj = copy.deepcopy(obj)
            for row in view['proposal']['changes']:
                if row['state'] != 'pending': continue
                require(not row['conflict'], '模型候选与当前来源冲突', 'conflict', 409)
                if contract['version'] == 1:
                    next(b for b in obj['content']['blocks'] if b['id'] == row['id'])['text'] = row['after']
                elif row['target']['kind'] == 'manuscript':
                    target = row['target']
                    if target.get('field') == 'caption': next(r for r in obj['content']['components'] if (r.get('id') or r.get('object_id')) == target['component_id'])['caption'] = row['after']
                    else: next(b for b in obj['content']['blocks'] if b['id'] == target['block_id'])['text'] = row['after']
            origin.update(source_mode='latest_agent_candidate', revision_task_id=task['id'], candidate_sha256=record['candidate_sha256'], proposal_sha256=record['proposal_sha256'], decision_version=view['decision_version'])
        ordered_segments(obj['content'], obj['content'].get('components', []))
        origin['projected_content_sha256'] = digest(obj['content'])
        return {'object': obj, 'provenance': origin}


# Generated LaTeX accepts bounded mathematical notation, never arbitrary TeX.
# Manual-source mode remains the separate legacy paper_sources contract.
MATH_COMMANDS = set(('alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa lambda mu nu xi omicron pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega '
                     'frac dfrac tfrac sqrt sum prod int iint iiint oint lim min max arg log ln exp sin cos tan sinh cosh det mod bmod pmod '
                     'left right middle overline underline hat widehat bar vec dot ddot tilde widetilde text mathrm mathbf mathit mathsf mathtt mathbb mathcal boldsymbol operatorname '
                     'cdot times div pm mp le leq ge geq ne neq approx sim simeq equiv propto in notin subset subseteq supset supseteq cup cap emptyset forall exists '
                     'infty partial nabla ell hbar Re Im angle perp parallel to mapsto rightarrow leftarrow leftrightarrow Rightarrow Leftarrow Leftrightarrow '
                     'ldots cdots vdots ddots colon quad qquad limits nolimits underbrace overbrace binom substack').split())
_MATH_TOKEN = r'\$\$[\s\S]+?\$\$|(?<![\\$])\$(?!\$)[^\n$]+\$(?!\$)|\\\[[\s\S]+?\\\]|\\\([^\n]+?\\\)'
_INLINE = re.compile('(?P<math>' + _MATH_TOKEN + r')|(?P<code>`+)(?P<code_text>.+?)(?P=code)'
                     r'|(?P<cite>\[)'
                     r'|(?P<strong>\*\*|__)(?=\S)(?P<strong_text>.+?)(?<=\S)(?P=strong)'
                     r'|(?P<emphasis>(?<!\w)\*|(?<!\w)_)(?=\S)(?P<emphasis_text>.+?)(?<=\S)(?P=emphasis)(?!\w)')


def _unicode_punctuation(value):
    return bool(value) and ord(value) > 127 and unicodedata.category(value).startswith('P')


def tex_escape(value, *, previous='', following=''):
    # fontspec's TeX mapping turns each literal ASCII double quote into a
    # right quote. An explicit text glyph preserves the saved character in
    # titles, prose and captions without guessing pairs or changing source.
    mapping = {'\\': r'\textbackslash{}', '&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#',
               '_': r'\_', '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
               '"': r'\textquotedbl{}'}
    text = str(value)
    # Keep TeX's existing -- / --- dash ligatures and math-token handling.
    # A single literal hyphen gets its own unambiguous PDF font glyph.
    # xeCJK discards input spaces beside its full-width punctuation, even with
    # CJKspace enabled. Emit the authored U+0020 explicitly; do not reclassify
    # punctuation, replace its font, or alter math/TeX dash ligature policy.
    return ''.join(r'\char32{}' if ch == ' ' and
                   (_unicode_punctuation(text[i-1] if i else previous)
                    or _unicode_punctuation(text[i+1] if i+1 < len(text) else following))
                   else r'\RPLiteralHyphen -' if ch == '-' and text[i-1:i] != '-' and text[i+1:i+2] != '-'
                   else mapping.get(ch, ch) for i, ch in enumerate(text))


def legacy_tex_font_preamble(compiler, *, portable_fonts=False):
    """Match the configured compiler in older structured source entries.

    XeLaTeX uses the same declared CJK font as the workdesk instead of virtual
    T1 fonts, which may be absent in its isolated runtime. This installs nothing.
    """
    if compiler and 'xelatex' in str(compiler).rsplit('/',1)[-1].lower():
        from research_partner.domains.manuscripts.fonts import fallback_preamble
        return '\n'.join([r'\usepackage{fontspec}',r'\usepackage{xeCJK}',
                          r'\setmainfont{Noto Serif CJK SC}',r'\setCJKmainfont{Noto Serif CJK SC}',
                          fallback_preamble(portable=portable_fonts)])+'\n'
    return ('\\usepackage[T1]{fontenc}\n\\usepackage[utf8]{inputenc}\n'
            + r'\DeclareRobustCommand{\RPLiteralHyphen}[1]{#1}' + '\n')


def safe_math(value):
    require(isinstance(value, str) and len(value) <= 4096 and not any(ch in value for ch in ('%', '#', '$', '^'+'^', '\x00', '\r')),
            '公式包含不支持的 TeX 语法', 'unsafe_math', 422)
    depth = 0; cursor = 0
    for match in re.finditer(r'\\([A-Za-z]+|.)', value):
        command = match.group(1)
        require(command in MATH_COMMANDS or command in '{}_,;! :|%',
                '公式命令不在安全范围：\\' + command, 'unsafe_math', 422)
        cursor = match.end()
    require(not value.endswith('\\'), '公式命令未完成', 'unsafe_math', 422)
    for i, ch in enumerate(value):
        if i and value[i-1] == '\\': continue
        if ch == '{': depth += 1
        if ch == '}': depth -= 1
        require(depth >= 0, '公式括号未配对', 'invalid_math', 422)
    require(depth == 0, '公式括号未配对', 'invalid_math', 422)
    return value


def tex_inline(text, depth=0):
    require(depth <= 8, '内联格式嵌套过深', 'format_limit', 413)
    text = str(text); out = []; cursor = 0; previous = ''
    while (match := _INLINE.search(text, cursor)) is not None:
        styled = match['code_text'] or match['strong_text'] or match['emphasis_text']
        out.append(tex_escape(text[cursor:match.start()], previous=previous,
                              following=styled[:1] if styled else ''))
        cursor = match.end()
        if match['math']:
            raw = match['math']; display = raw.startswith(('$$', r'\['))
            value = raw[2:-2] if raw.startswith(('$$', r'\[', r'\(')) else raw[1:-1]
            out.append((r'\[' if display else r'\(') + safe_math(value) + (r'\]' if display else r'\)'))
        elif match['code']: out.append(r'\texttt{' + tex_escape(match['code_text']) + '}')
        elif match['cite']:
            citation = citation_at(text, match.start(),
                                   render_inline=lambda value: tex_inline(value, depth+1),
                                   escape=tex_escape)
            if citation is None: out.append(tex_escape(match['cite']))
            else:
                cursor, rendered = citation
                out.append(rendered)
        elif match['strong']: out.append(r'\textbf{' + tex_inline(match['strong_text'], depth+1) + '}')
        else: out.append(r'\emph{' + tex_inline(match['emphasis_text'], depth+1) + '}')
        # Delimiters are not printed: retain the adjacent content at an inline
        # style boundary so a following authored space is not lost by xeCJK.
        previous = styled[-1:] if styled else ''
    out.append(tex_escape(text[cursor:], previous=previous)); return ''.join(out)


def _image_name(name):
    require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,180}\.(?:png|jpe?g|pdf)', name, re.I),
            '图片需要经过登记解析的安全单层文件名', 'invalid_image_reference', 422)
    return name


def tex_markdown(text, image_assets=None):
    """A deliberately bounded semantic conversion, with no filesystem access."""
    images = image_assets or {}; out = []; lines = str(text).splitlines(); i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('```'):
            code = []; i += 1
            while i < len(lines) and not lines[i].startswith('```'): code.append(lines[i]); i += 1
            require(i < len(lines), '代码围栏未闭合', 'invalid_markdown', 422)
            out.append('\\begin{quote}\\ttfamily\n' + '\n\\par\n'.join(tex_escape(x) for x in code) + '\n\\end{quote}'); i += 1; continue
        # Display math may span physical lines; keep it intact for validation.
        if line.strip() in {r'\[', '$$'}:
            delim = r'\]' if line.strip() == r'\[' else '$$'; formula = []; i += 1
            while i < len(lines) and lines[i].strip() != delim: formula.append(lines[i]); i += 1
            require(i < len(lines), '显示公式未闭合', 'invalid_math', 422)
            out.append(r'\[' + safe_math('\n'.join(formula)) + r'\]'); i += 1; continue
        if i+1 < len(lines) and '|' in line and re.fullmatch(r'\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*', lines[i+1]):
            rows = [[c.strip() for c in line.strip().strip('|').split('|')]]; i += 2
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')]); i += 1
            n = len(rows[0]); require(1 <= n <= 12 and all(len(r) == n for r in rows), '表格列数不一致或过多', 'invalid_table', 422)
            columns = '|'.join(r'p{\dimexpr\linewidth/' + str(n) + r'-2\tabcolsep-2\arrayrulewidth\relax}' for _ in range(n))
            out.append(r'\begin{longtable}{' + columns + '}\n' + '\n'.join(' & '.join(tex_inline(cell) for cell in row) + r'\\\hline' for row in rows) + '\n' + r'\end{longtable}')
            continue
        heading = re.match(r'^(#{1,6})\s+(.+)', line)
        if heading:
            command = ['section', 'subsection', 'subsubsection', 'paragraph', 'subparagraph', 'subparagraph'][len(heading[1])-1]
            out.append('\\' + command + '{' + tex_inline(heading[2]) + '}'); i += 1; continue
        # Resolve Markdown images only from the caller's authorized asset map.
        parts = []; pos = 0
        for image in re.finditer(r'!\[([^\]]*)\]\(([^)]+)\)', line):
            parts.append(tex_inline(line[pos:image.start()])); target = image[2].strip().strip('<>')
            require(target in images, '文稿图片尚未绑定可解析资产：' + target, 'missing_image_resource', 422)
            filename = images[target].get('filename') if isinstance(images[target], dict) else images[target]
            parts.append(r'\includegraphics[width=\linewidth,height=.78\textheight,keepaspectratio]{' + _image_name(filename) + '}'); pos = image.end()
        parts.append(tex_inline(line[pos:])); out.append(''.join(parts)); i += 1
    return '\n'.join(out)


_CAPTION_PREFIX = re.compile(
    r'^(?:#{1,6}[ \t]+)?(?P<marker>\*{1,3}|_{1,3})?[ \t]*'
    r'(?P<label>(?P<kind>Figure[ \t]+|Fig\.?[ \t]*|图[ \t]*)'
    r'(?P<value>\d+|[A-Za-z]))(?=$|[\s|｜.。:：、)）*_–—-])'
    r'[ \t]*[|｜.。:：、)）–—-]?[ \t]*', re.IGNORECASE)


def caption_display(value):
    """Remove only leading caption furniture, retaining scientific prose.

    This is a display projection: source labels are recorded, and body/within-
    caption references are deliberately not rewritten. Markdown emphasis around
    the scientific title survives removal of an embedded source label.
    """
    source = str(value or ''); text = source; labels = []; headings = []
    while text.strip():
        candidate = text.lstrip()
        first, separator, rest = candidate.partition('\n')
        heading = re.sub(r'^#{1,6}[ \t]+', '', first.strip())
        for marker in ('***', '___', '**', '__', '*', '_'):
            if heading.startswith(marker) and heading.endswith(marker) and len(heading) >= 2*len(marker):
                heading = heading[len(marker):-len(marker)].strip(); break
        if heading.rstrip('：:').strip() == '中文图注':
            headings.append(first); text = rest if separator else ''; continue
        match = _CAPTION_PREFIX.match(candidate)
        if not match: break
        remaining = candidate[match.end():]; marker = match['marker']
        if marker:
            if remaining.startswith(marker):
                remaining = remaining[len(marker):].lstrip()
                remaining = re.sub(r'^[|｜.。:：、–—-][ \t]*', '', remaining)
            elif marker in remaining:
                remaining = marker + remaining
            else:
                # Unbalanced markup is not a reliably identified label wrapper.
                break
        labels.append({'raw': match['label'], 'value': match['value'],
                       'kind': match['kind'].strip()})
        text = remaining
    return {'text': text, 'source_labels': labels, 'removed_format_headings': headings,
            'source_caption_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'display_caption_sha256': hashlib.sha256(text.encode()).hexdigest()}


def caption_numbering(obj, materials):
    """Describe automatic figure numbering in the same order used by build_tex."""
    sequence, _ = ordered_segments(obj['content'], materials)
    figures = []; warnings = []; seen = {}
    for segment in sequence:
        if segment['kind'] != 'component': continue
        index = segment['index']; item = materials[index]
        if item.get('type') != 'image': continue
        display = caption_display(item.get('caption') or item.get('title') or '')
        number = len(figures) + 1
        identity = {'material_index': index, 'object_id': item.get('object_id'),
                    'revision': item.get('revision'), 'display_number': number}
        display['display_caption'] = display.pop('text')
        figures.append({**identity, **display})
        for label in display['source_labels']:
            value = label['value']; key = str(int(value)) if value.isdigit() else value.upper()
            if key != str(number):
                warnings.append({**identity, 'code': 'source_figure_label_differs',
                                 'source_label': label['raw'],
                                 'message': '原始图号与展示顺序不同；正文及图注内手写引用未自动改写。'})
            if key in seen:
                warnings.append({**identity, 'code': 'duplicate_source_figure_label',
                                 'source_label': label['raw'], 'first_display_number': seen[key],
                                 'message': '原始图号重复；展示图号按文稿顺序唯一生成。'})
            else: seen[key] = number
        if display['removed_format_headings']:
            warnings.append({**identity, 'code': 'caption_format_heading_removed',
                             'message': '展示图注移除纯“中文图注”格式标题；原始字段保持不变。'})
    return {'figures': figures, 'warnings': warnings, 'body_references_rewritten': False,
            'source_modified': False}


def tex_figure_labels(material_index, object_label, seen_aliases):
    """Label each rendered slot; keep the old object alias on its first use."""
    require(isinstance(object_label, str) and re.fullmatch(r'[A-Za-z0-9_.:-]+', object_label), '图件标签无效')
    labels = r'\label{rp:figure-occurrence:' + str(material_index+1) + '}'
    if object_label not in seen_aliases:
        labels += r'\label{fig:' + object_label + '}'
        seen_aliases.add(object_label)
    return labels


def build_tex(obj, materials, citations=(), format_config=None, *, image_assets=None, portable_fonts=False):
    """Generate latest structured content with separate safe XeLaTeX layout.

    Caller owns exact assets, ACLs, BibTeX bytes, source/PDF publication and actual
    compiler validation. This function never selects/overwrites manual LaTeX.
    """
    from research_partner.domains.manuscripts.paper_sources import source_state
    from research_partner.domains.manuscripts.fonts import fallback_preamble
    state = source_state(obj)
    require(state['mode'] == 'structured', '格式生成仅适用于明确结构稿；手写 LaTeX 保持独立', 'paper_source_required', 409)
    f = format_for(obj, format_config); body = []; figure_aliases = set()
    sequence, _ = ordered_segments(obj['content'], materials)
    for segment in sequence:
        if segment['kind'] == 'block':
            b = segment['block']; text = str(b.get('text', ''))
            if b.get('kind') in {'heading', 'title'} and not re.match(r'^#{1,6}\s', text):
                level = b.get('level', 2); require(type(level) is int and 1 <= level <= 6, '章节层级无效')
                text = '#' * level + ' ' + text
            body.append(tex_markdown(text, image_assets))
            for key in b.get('citation_keys', []):
                require(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9_.:-]+', key), '引用 key 无效')
                body.append(r'\cite{' + key + '}')
        elif segment['kind'] == 'markdown': body.append(tex_markdown(segment['markdown'], image_assets))
        elif segment['kind'] == 'unplaced_heading': body.append(r'\section{' + tex_escape(segment['text']) + '}')
        else:
            item = materials[segment['index']]
            if item.get('type') == 'image':
                name = _image_name(item['filename']); label = item.get('object_id', 'component-' + str(segment['index']+1))
                # A saved object may appear in several independent figure slots,
                # including different fixed revisions. Give each slot its own
                # label; retain the historical object alias only on its first
                # occurrence in document order. Neither rewrites body references.
                labels = tex_figure_labels(segment['index'], label, figure_aliases)
                caption = item.get('caption') or item.get('title') or ''
                caption = caption_display(caption)['text']
                # Measure the exact image and legend once, at the saved font
                # size and column width. A block that fits one page stays
                # together in source order. A longer legend is unboxed so its
                # full text can span pages without shrinking or clipping it.
                body.append(r'\setbox\RPFigureBlock=\vbox{\hsize=\linewidth' + '\n'
                            + r'\begin{center}\includegraphics[width=\linewidth,height=.78\textheight,keepaspectratio]{' + name + r'}\end{center}' + '\n'
                            + r'\refstepcounter{figure}' + labels + r'\noindent\textbf{Figure~\thefigure. }' + tex_inline(caption) + r'\par}' + '\n'
                            + r'\ifdim\dimexpr\ht\RPFigureBlock+\dp\RPFigureBlock\relax>\textheight' + '\n'
                            + r'\unvbox\RPFigureBlock' + '\n' + r'\else\noindent\box\RPFigureBlock\par\fi')
            else:
                body.append(r'\section{' + tex_inline(item.get('title', '')) + '}')
                body.extend(tex_markdown(b.get('text', ''), item.get('image_assets', image_assets)) for b in item.get('blocks', []) if b.get('content_role') != 'preparation')
    if citations:
        keys = [c.get('metadata', {}).get('citation_key', c['id']) for c in citations]
        require(all(isinstance(k, str) and re.fullmatch(r'[A-Za-z0-9_.:-]+', k) for k in keys), '引用 key 无效')
        body.append(r'\nocite{' + ','.join(keys) + '}')
    preamble = '\n'.join([
        r'\documentclass' + ('[twocolumn]' if f['columns'] == 2 else '') + '{article}', r'\usepackage{fontspec}', r'\usepackage{xeCJK}',
        r'\usepackage{graphicx,amsmath,amssymb,longtable,array}',
        r'\newsavebox{\RPFigureBlock}',
        r'\usepackage[' + f['page_size'] + 'paper,top=' + str(f['margin_top_mm']) + 'mm,bottom=' + str(f['margin_bottom_mm']) + 'mm,left=' + str(f['margin_left_mm']) + 'mm,right=' + str(f['margin_right_mm']) + r'mm]{geometry}',
        r'\setmainfont{' + f['font_family'] + '}', r'\setCJKmainfont{' + f['font_family'] + '}',
        fallback_preamble(portable=portable_fonts),
        # A dictionary-inserted line-end hyphen becomes copyable PDF text that
        # was never present in the structured manuscript. Wrap at word spaces
        # instead. Literal source hyphens and mathematical minus keep their
        # existing formatter paths; manual LaTeX remains outside this builder.
        r'\hyphenpenalty=10000',
        r'\setlength{\parskip}{' + str(f['paragraph_spacing_pt']) + 'pt}',
        # maketitle and sectioning restore normalsize; defining only a one-off
        # AtBeginDocument fontsize would silently lose the user's body size.
        r'\renewcommand{\normalsize}{\fontsize{' + str(f['font_size_pt']) + '}{' + str(round(f['font_size_pt']*f['line_spacing'], 4)) + r'}\selectfont}',
        r'\AtBeginDocument{\normalsize}',
        r'\title{' + tex_inline(obj['title']) + '}', r'\date{}', r'\begin{document}', r'\maketitle'])
    return preamble + '\n\n' + '\n\n'.join(body) + '\n\\bibliographystyle{plain}\n\\bibliography{references}\n\\end{document}\n'
