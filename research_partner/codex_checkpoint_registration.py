"""Explicit registration of an already ended CLI call, never a new dispatch.

A durable prepared record binds every proposed byte. A process interruption
can only complete that same proposal; existing differing files are refused.
Task control, candidate validation and publication remain separate operations.
"""
import json
import os
import re
import tempfile

from .store import require, digest, encoded, now
from .native_recovery import _directory, _setting
from .providers import Providers, _controlled_file
from .codex_cli_checkpoint_recovery import inspect

KEY = 'codex_checkpoint_reconstruction:'
ACTIONS = {'task.recover_cli_checkpoint_preview', 'task.recover_cli_checkpoint'}


def _access(app, task, scope, principal):
    from .desk_w1a import _project
    require(not principal or principal.get('actor_kind') != 'agent',
            '检查点补登记需要用户明确操作', 'forbidden', 403)
    _project(app, task['project_id'], scope, principal, write=True)
    with app.store.connect() as c:
        app.store.assert_material_access(c, task['payload'])


def _budget(app):
    path = app.config.get('development_budget')
    if path:
        from .development_budget import Budget
        budget = Budget(path)
        budget.check()
        return budget


def _summary(ident, proposal, state, replay=False):
    proof = proposal['proof']
    return {'task_id': ident, 'proof_sha256': digest(proof), 'state': state,
            'session_id': proof['session_id'], 'invocation': 1,
            'original_returncode': 0, 'original_elapsed_seconds': proof['native_elapsed_seconds'],
            'original_receipt_was_absent': True, 'new_model_requests': 0,
            'task_enqueued': False, 'candidate_validated': False, 'replayed': replay}


def _publish(directory, name, text):
    """Create only our named immutable observation, or verify an exact retry."""
    raw = text.encode('utf-8'); path = directory / name
    if path.exists() or path.is_symlink():
        require(_controlled_file(directory, path) == raw,
                '检查点补登记文件已有不同内容；未覆盖', 'integrity', 409)
        return
    fd, temporary = tempfile.mkstemp(prefix='.' + name + '.reconstruct-', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        try:
            os.link(temporary, path, follow_symlinks=False)
        except FileExistsError:
            require(_controlled_file(directory, path) == raw,
                    '检查点补登记文件已有不同内容；未覆盖', 'integrity', 409)
    finally:
        os.unlink(temporary)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def _registered(app, task, record, scope=None, principal=None):
    """Current authority and exact original/reconstructed bytes, no writes."""
    _access(app, task, scope, principal)
    proposal = record['proposal']; proof = proposal['proof']; directory = _directory(app, task['id'])
    require(record['state'] in {'registered', 'settled'} and digest(proof) == record['proof_sha256'],
            '补登记尚未完成或证明已变化', 'integrity', 409)
    require(str(directory.absolute()) == proof['directory'], '原调用目录已变化', 'integrity', 409)
    for name, info in proof['files'].items():
        raw = _controlled_file(directory, directory / name)
        require(len(raw) == info['bytes'] and digest(raw) == info['sha256'],
                '原调用证据已变化；未重新调用', 'integrity', 409)
    for name, text in proposal['proposed_file_text'].items():
        require(_controlled_file(directory, directory / name) == text.encode('utf-8'),
                '补登记文件不一致；未重新调用', 'integrity', 409)
    require(app.store.setting('codex_checkpoint:' + task['id']) == proposal['checkpoint'],
            '原检查点已被另一调用替代', 'integrity', 409)
    return proposal


def cached_only(app, task, connection):
    """Until model.done, a reconstructed checkpoint can only consume its reply."""
    record = _setting(connection, KEY + task['id'])
    if record is None:
        return
    model = next((s for s in task['steps'] if s['step_key'] == 'model'), None)
    # Once the exact original reply has passed normal candidate validation,
    # subsequent explicit revision follows its existing permissions and budget.
    if model and model['status'] == 'done':
        provider = model['data'].get('provider', {})
        reconstruction = provider.get('reconstruction', {})
        if reconstruction.get('proof_sha256') == record['proof_sha256']:
            require(record['state'] == 'settled', '原调用结算尚未完成', 'conflict', 409)
            return
        # A later explicit invocation is not this registration's recovery.
        if provider.get('invocation', 0) > 1:
            return
    proposal = _registered(app, task, record)
    require(record['state'] == 'settled', '原调用结算尚未完成；不派发', 'conflict', 409)
    proof = proposal['proof']; s = app.store
    require(s.execution_inputs(connection, task['id']) == proof['input_snapshot']
            and s.setting('candidate_revision_authorized:' + task['id']) is None,
            '原回复后的指导或授权已变化；未派发', 'candidate_revision_required', 409)
    require(digest(app.config.get('providers', {}).get(task['payload']['provider_id'], {}))
            == proof['provider_configuration_sha256'], '当前提供者配置已变化', 'authorization_required', 403)
    if proof['cycle']:
        from .cycle import assert_child
        assert_child(s, connection, task['payload'])
        parent = s.task(proof['cycle']['parent_id'], connection)
        require(digest(parent) == proof['cycle']['parent_sha256'],
                '父协作已变化；旧回复未接回', 'candidate_revision_required', 409)
    result = Providers(app).recover_candidate(task, _directory(app, task['id']))
    require(result is not None and result['receipt'].get('recovered_completed_cli_reply') is True,
            '已登记的完成回复不可回收；禁止退回新模型调用', 'candidate_checkpoint_invalid', 409)


def _settle(app, ident, record):
    """Complete only the already reserved original invocation; retry is a no-op."""
    budget = _budget(app)
    receipt = record['proposal']['receipt']
    if budget:
        budget.complete(ident + ':1', receipt, only_unsettled=True)
    with app.store.transaction() as c:
        current = _setting(c, KEY + ident)
        if current and current['state'] == 'settled':
            require(current['proposal'] == record['proposal'] and current['intent'] == record['intent'],
                    '补登记已被另一请求改变','conflict',409)
            return current
        require(current == record, '补登记已变化；保留已完成结算', 'conflict', 409)
        current = {**current, 'state': 'settled', 'settled_observed_at': now()}
        c.execute('UPDATE kv SET value=? WHERE key=?', (encoded(current), KEY + ident))
    return current


def dispatch(app, data, scope=None, principal=None):
    preview = data.get('action') == 'task.recover_cli_checkpoint_preview'
    required = {'action', 'id'} if preview else {'action', 'id', 'expected_proof_sha256', 'approved', 'reason', 'request_key'}
    require(set(data) == required and data['action'] in ACTIONS and isinstance(data['id'], str),
            '检查点补登记命令字段无效')
    s = app.store; ident = data['id']; _budget(app)
    task = s.task(ident); _access(app, task, scope, principal)
    directory = _directory(app, ident)
    if preview:
        existing = s.setting(KEY + ident)
        if existing:
            if existing['state'] == 'prepared':
                proposal = inspect(app, ident, directory, scope, principal,
                                   _published=existing['proposal']['proposed_file_text'])
                require(proposal == existing['proposal'], '原补登记证明已变化', 'conflict', 409)
            else:
                proposal = _registered(app, task, existing, scope, principal)
            return _summary(ident, proposal, existing['state'], True)
        return _summary(ident, inspect(app, ident, directory, scope, principal), 'preview')
    require(data['approved'] is True and isinstance(data['reason'], str) and 1 <= len(data['reason']) <= 1000
            and isinstance(data['request_key'], str) and 1 <= len(data['request_key']) <= 200
            and isinstance(data['expected_proof_sha256'], str) and re.fullmatch('[a-f0-9]{64}', data['expected_proof_sha256']),
            '需要明确理由、唯一请求及原预览证明')
    intent = {k: data[k] for k in ('expected_proof_sha256', 'reason', 'request_key')}
    # Prepare is durable before any generated observation is created. It never
    # changes Task state, attempts, leases, parent allocation or original files.
    with s.transaction() as c:
        _budget(app)
        record = _setting(c, KEY + ident)
        replay = record is not None
        if record:
            require(record['intent'] == intent, '补登记请求与已保存意图不同', 'conflict', 409)
        else:
            proposal = inspect(app, ident, directory, scope, principal)
            require(digest(proposal['proof']) == data['expected_proof_sha256'],
                    '原任务、权限或证据已变化；请重新检查', 'conflict', 409)
            record = {'state': 'prepared', 'intent': intent, 'proposal': proposal,
                      'proof_sha256': data['expected_proof_sha256'], 'observed_at': now(),
                      'original_receipt_was_absent': True}
            c.execute('INSERT INTO kv VALUES(?,?)', (KEY + ident, encoded(record)))
    if record['state'] == 'prepared':
        with s.transaction() as c:
            _budget(app)
            require(_setting(c, KEY + ident) == record, '补登记准备记录已变化', 'conflict', 409)
            proposal = inspect(app, ident, directory, scope, principal,
                               _published=record['proposal']['proposed_file_text'])
            require(proposal == record['proposal'], '原证明在发布前已变化', 'conflict', 409)
            for name, text in proposal['proposed_file_text'].items():
                _budget(app)
                _publish(directory, name, text)
            # Native files may not be rewritten while we prepare registration.
            for name, info in proposal['proof']['files'].items():
                require(digest(_controlled_file(directory, directory / name)) == info['sha256'],
                        '原证据在登记时改变', 'integrity', 409)
            c.execute('INSERT INTO kv VALUES(?,?)', ('codex_checkpoint:' + ident, encoded(proposal['checkpoint'])))
            record = {**record, 'state': 'registered', 'registered_at': now()}
            c.execute('UPDATE kv SET value=? WHERE key=?', (encoded(record), KEY + ident))
            s.event(c, 'provider.checkpoint_reconstructed', ident,
                    {'proof_sha256': record['proof_sha256'], 'original_receipt_was_absent': True,
                     'attempt_id': proposal['proof']['attempt_id'], 'invocation': 1,
                     'new_model_requests': 0}, 'user')
    _registered(app, s.task(ident), record, scope, principal)
    if record['state'] == 'registered':
        record = _settle(app, ident, record)
    return _summary(ident, record['proposal'], record['state'], replay)
