"""Record an already-saved external revision without impersonating execution.

The owner/client supplies provenance claims; the application verifies only local
revision identities, their exact delta, and an optional existing review record.
No provider, task, scientific approval, or user acceptance is created here.
"""
from __future__ import annotations
import copy
import json
import re
from research_partner.storage.store import Problem, require, digest, encoded, now

PREFIX = 'feedback_external_action:'
KIND = 'external_revision_receipt'
FIELDS = {'action', 'id', 'expected_revision', 'request_key', 'object_id',
          'base_revision', 'result_revision', 'base_sha256', 'result_sha256',
          'external_executor', 'review_identity'}


def object_references(value):
    """Collect explicit local object identities, never infer access from prose.

    This covers nested source_reference/source_refs/report and receipt fields.
    Paths/URLs without a registered local object identity remain declared text;
    the application neither fetches them nor authenticates external authors.
    """
    if isinstance(value, dict):
        return set().union(*(object_references(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(object_references(v) for v in value)) if value else set()
    if isinstance(value, str):
        match = re.fullmatch(r'((?:ART|PRJ|QUESTION)-[A-Za-z0-9_-]+)(?:@[1-9][0-9]*)?', value)
        if match:
            return {match[1]}
    return set()


def require_read_access(app, feedback, scope, *, seen=None):
    """Deny the whole outward object if receipt-derived sources are unreadable.

    Returning just a filtered feedback_view is insufficient: raw content and
    historical records embed the same before/after text. Keep storage untouched;
    current/history/inspect/get and state all use this one outward gate.
    """
    if scope is None:
        return
    seen = set(seen or ())
    if feedback['id'] in seen:
        return
    seen.add(feedback['id'])
    try:
        current = app.store.get(feedback['id'])
        references = object_references(feedback['content'].get('source_reference'))
        references.update(object_references(current['content'].get('source_reference')))
        with app.store.connect() as connection:
            for candidate in [*current['content'].get('actions', []), *feedback['content'].get('actions', [])]:
                receipt = _receipt(connection, candidate.get('id', ''))
                if not receipt or receipt.get('feedback_id') != feedback['id']:
                    continue
                action = receipt['action']
                references.update(object_references(action))
                # r1 receipts predate explicit source_objects. Their immutable
                # feedback pin still binds the exact original review locator.
                original = app.store.get(feedback['id'], action['feedback_revision'], connection=connection)
                references.update(object_references(original['content'].get('source_reference')))
        for ident in sorted(references):
            if ident != feedback['id']:
                source = app.store.get(ident)
                app.access(source, scope, _receipt_seen=seen)
    except Problem as error:
        # No copied delta, review summary, object title or denied source ID is
        # included in the error response. State omits the denied feedback.
        raise Problem('关联成果或审阅来源当前不可读；此意见的完整记录暂不可读取', 'forbidden', 403) from error


def visible_review_records(app, records, scope):
    """A shared result does not independently share copied review-report text."""
    if scope is None:
        return records
    visible = []
    for record in records:
        try:
            for ident in object_references(record):
                app.access(app.store.get(ident), scope)
        except Problem:
            continue
        visible.append(record)
    return visible


def delta(before, after, path=''):
    """JSON-pointer changes; missing and JSON null remain distinguishable."""
    if encoded(before) == encoded(after):
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            child = path + '/' + key.replace('~', '~0').replace('/', '~1')
            if key not in before or key not in after:
                result.append({'path': child,
                               'before': {'present': key in before, **({'value': before[key]} if key in before else {})},
                               'after': {'present': key in after, **({'value': after[key]} if key in after else {})}})
            else:
                result.extend(delta(before[key], after[key], child))
        return result
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        return [change for i, (a, b) in enumerate(zip(before, after))
                for change in delta(a, b, path + '/' + str(i))]
    return [{'path': path, 'before': {'present': True, 'value': before},
             'after': {'present': True, 'value': after}}]


def _receipt(connection, action_id):
    row = connection.execute('SELECT value FROM kv WHERE key=?', (PREFIX + action_id,)).fetchone()
    return json.loads(row[0]) if row else None


def protect_saved_actions(connection, feedback, proposed_content):
    """Enforced after merge under the same Store writer lock as every save."""
    proposed = proposed_content.get('actions', [])
    require(isinstance(proposed, list), '反馈行动应为列表')
    for action in feedback['content'].get('actions', []):
        record = _receipt(connection, action.get('id', ''))
        if record and record['feedback_id'] == feedback['id']:
            require(sum(encoded(item) == encoded(record['action']) for item in proposed) == 1,
                    '外部行动登记为追加记录，不能改写或删除', 'immutable_receipt', 409)


def project_action(app, feedback, action, scope=None):
    """Only a matching server receipt gives the dedicated verification label."""
    with app.store.connect() as c:
        record = _receipt(c, action.get('id', ''))
    if not record or record['feedback_id'] != feedback['id'] or encoded(record['action']) != encoded(action):
        return None
    # Current read access is required even for the old immutable result.
    app.get(record['action']['output']['id'], scope)
    result = copy.deepcopy(record['action'])
    result.update(task=None, live_status='external_recorded', registration_verified=True)
    return result


def install_guards(connection):
    # Keep the receipt append-only even through the generic settings API, and
    # fence an already-open older runtime from dropping its feedback action.
    for operation in ('UPDATE', 'DELETE'):
        connection.execute(f"""CREATE TRIGGER IF NOT EXISTS rp_external_receipt_{operation.lower()}
            BEFORE {operation} ON kv WHEN substr(OLD.key,1,{len(PREFIX)})='{PREFIX}'
            BEGIN SELECT RAISE(ABORT,'External feedback receipts are append-only'); END""")
    connection.execute("DROP TRIGGER IF EXISTS rp_external_receipt_feedback_update")
    connection.execute(f"""CREATE TRIGGER rp_external_receipt_feedback_update
        BEFORE UPDATE ON objects WHEN OLD.kind='feedback'
        AND EXISTS(SELECT 1 FROM kv WHERE substr(key,1,{len(PREFIX)})='{PREFIX}'
            AND json_extract(value,'$.feedback_id')=OLD.id)
        BEGIN SELECT CASE WHEN rp_runtime_supports('["external_feedback_receipt_v1","external_feedback_source_acl_v2"]')!=1
        THEN RAISE(ABORT,'External feedback receipts require a compatible runtime') END; END""")


def record(app, data, scope=None, principal=None):
    require(set(data) <= FIELDS, '外部行动登记含未支持字段')
    principal = copy.deepcopy(principal or {'kind': 'local_operator'})
    require(scope is None or principal.get('kind') != 'local_operator',
            '受限登记必须提供连接的认证身份', 'forbidden', 403)
    # This checks the *current* locally authenticated principal. The executor
    # reference remains a user-supplied claim and is never authenticated here.
    from research_partner.domains.workspace.management import authority_scope
    current_scope = authority_scope(app, principal)
    require(principal.get('kind') in {'local_operator', 'loopback', 'credential'}, '未知登记者身份')
    registered_by = {k: principal[k] for k in ('kind', 'credential_sha256') if k in principal}
    actor = 'external_registration:' + registered_by['kind']
    if principal.get('kind') == 'credential':
        actor += ':' + principal['credential_sha256'][:16]
    for field in ('expected_revision', 'base_revision', 'result_revision'):
        require(type(data.get(field)) is int and data[field] > 0, '登记需要准确正整数修订', 'version_required', 409)
    require(data['result_revision'] > data['base_revision'], '结果必须是同一对象较晚的修订')
    for field in ('base_sha256', 'result_sha256'):
        require(isinstance(data.get(field), str) and re.fullmatch(r'[0-9a-f]{64}', data[field]), '登记需要完整修订哈希')
    key = data.get('request_key')
    require(isinstance(key, str) and 0 < len(key.strip()) <= 200, '登记需要稳定请求标识（最多200字）')
    executor = data.get('external_executor')
    require(isinstance(executor, dict) and set(executor) == {'name', 'reference'} and
            all(isinstance(executor.get(k), str) and 0 < len(executor[k].strip()) <= 2000 for k in executor),
            '需分别填写声称的外部执行者与可追溯来源；不代表身份认证')
    review_identity = data.get('review_identity')
    require(review_identity is None or (isinstance(review_identity, str) and re.fullmatch(r'[0-9a-f]{64}', review_identity)),
            '审阅关联需要准确记录身份')
    action_id = 'ACTION-' + digest({'feedback_id': data.get('id'), 'request_key': key})[:32]
    fingerprint = digest({'request': data, 'registered_by': registered_by})
    s = app.store
    with s.transaction() as c:
        fb = app.access(s.get(data['id'], connection=c), scope)
        require(fb['kind'] == 'feedback', '对象不是反馈')
        project = fb['project_id']
        require(all(grant is None or project in grant for grant in (scope, current_scope)), '共享反馈为只读', 'forbidden', 403)
        require(not fb['archived'], '归档反馈不能新增登记', 'conflict', 409)
        require(fb['content'].get('lifecycle') != 'withdrawn', '已撤回反馈不能新增外部登记', 'cancelled', 409)
        require(app.feedback_disposition(fb) != 'defer', '已暂缓反馈不能新增外部登记', 'feedback_deferred', 409)
        require(data.get('object_id') == fb['content'].get('object_id') and data['base_revision'] == fb['content'].get('object_revision'),
                '登记基础必须绑定留言所见的同一对象修订', 'conflict', 409)
        current = app.access(s.get(data['object_id'], connection=c), scope)
        require(current.get('project_id') == project and current['kind'] not in {'feedback', 'project', 'question'}, '登记对象必须是本项目成果')
        require(not current['archived'], '归档成果不能新增登记', 'conflict', 409)
        prior = _receipt(c, action_id)
        if prior:
            require(prior['fingerprint'] == fingerprint, '同一外部登记标识的内容或登记者不同', 'idempotency_conflict', 409)
            return {'feedback': fb, 'registration': prior, 'replayed': True}
        require(data['expected_revision'] == fb['revision'], '反馈已变化，请重读后登记', 'conflict', 409, {'current': fb})
        require(data['result_revision'] == current['revision'], '成果已有较新修订，请重读后登记', 'conflict', 409, {'current': current})
        base = s.get(current['id'], data['base_revision'], connection=c)
        result = s.get(current['id'], data['result_revision'], connection=c)
        require(all(obj['id'] == current['id'] and obj['kind'] == current['kind'] and obj.get('project_id') == project for obj in (base, result)),
                '登记前后对象归属或类型不一致', 'conflict', 409)
        require(digest(base) == data['base_sha256'] and digest(result) == data['result_sha256'], '已存修订与提供的完整哈希不符', 'conflict', 409)
        changes = delta({k: base[k] for k in ('title', 'content', 'metadata', 'archived')},
                        {k: result[k] for k in ('title', 'content', 'metadata', 'archived')})
        require(changes, '这两个修订没有可登记的内容、标题或属性改动')
        review = None
        if review_identity:
            row = c.execute('SELECT value FROM kv WHERE key=?', ('reviews:' + current['id'] + ':' + str(result['revision']),)).fetchone()
            review = next((r for r in (json.loads(row[0]) if row else []) if r.get('identity') == review_identity), None)
            require(review and review.get('object_id') == current['id'] and review.get('revision') == result['revision'] and review.get('source_sha256') == digest(result),
                    '未找到绑定准确结果修订的审阅记录', 'review_mismatch', 409)
        source_objects = sorted(object_references({'feedback_source_reference': fb['content'].get('source_reference'),
                                                   'executor': executor, 'review': review}) | {current['id']})
        for ident in source_objects:
            source = s.get(ident, connection=c)
            app.access(source, scope)
            app.access(source, current_scope)
        stamp = now()
        ref = lambda obj: {'id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj)}
        action = {'id': action_id, 'registration_kind': KIND, 'status': 'external_recorded',
                  'scope': 'method' if fb['metadata'].get('scope') in {'method', 'work_method'} else 'result',
                  'timing': 'external_already_saved', 'feedback_revision': fb['revision'],
                  'external_executor': copy.deepcopy(executor), 'registered_by': registered_by,
                  'source_objects': source_objects,
                  'recorded_at': stamp, 'owner': executor['name'],
                  'output': {**ref(result), 'title': result['title'], 'kind': result['kind']},
                  'changes': {'base': ref(base), 'result': ref(result), 'kind': 'revision',
                              'changed_paths': [x['path'] for x in changes], 'delta': changes},
                  'validation': {'revision_delta': 'server_verified', 'independent_review': 'record_linked' if review else 'not_recorded',
                                 'user_acceptance': False, 'scientific_approval': False, 'records': [review] if review else [],
                                 'boundary': '仅核验本地修订差异及所选审阅记录；外部执行者与来源由登记者声明，不认证外部执行，也不代表科学批准或用户验收。'}}
        require(not any(x.get('id') == action_id for x in fb['content'].get('actions', [])), '行动标识已用于未核验记录', 'idempotency_conflict', 409)
        from research_partner.packaging.compatibility import require_features
        require_features(c, ['external_feedback_receipt_v1', 'external_feedback_source_acl_v2'])
        install_guards(c)
        tasks_before = [tuple(row) for row in c.execute('SELECT * FROM tasks ORDER BY id')]
        updated = s.save(fb['id'], fb['revision'], content={**fb['content'], 'actions': [*fb['content'].get('actions', []), action]},
                         merge=False, actor=actor, reason='register already-saved external revision; no execution or approval', connection=c)
        require(tasks_before == [tuple(row) for row in c.execute('SELECT * FROM tasks ORDER BY id')],
                '登记会使关联必要裁决失效；请先单独处理裁决，本次登记未保存', 'control_change_required', 409)
        receipt = {'schema': 1, 'feedback_id': fb['id'], 'feedback_revision': updated['revision'],
                   'fingerprint': fingerprint, 'action': action}
        c.execute('INSERT INTO kv VALUES(?,?)', (PREFIX + action_id, encoded(receipt)))
        s.event(c, 'feedback.external_action_recorded', fb['id'], {'action_id': action_id, 'base': ref(base), 'result': ref(result), 'registered_by': registered_by, 'external_executor_claim': executor}, actor)
        return {'feedback': updated, 'registration': receipt, 'replayed': False}
