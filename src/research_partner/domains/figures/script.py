"""Explicit source edits of an existing leaf; saving never executes code."""
import copy
import json
import re

from research_partner.storage.store import digest, encoded, require


def save(app, data, project, scope, principal):
    require(set(data) == {'action', 'project_id', 'id', 'expected_revision',
                          'expected_script_sha256', 'code', 'request_key'},
            '源码保存只接受当前图身份、原脚本摘要和新代码')
    require(not principal or (principal.get('kind') != 'agent' and
                               principal.get('actor_kind') != 'agent'),
            '源码保存需要用户明确操作', 'forbidden', 403)
    revision = data['expected_revision']
    expected = data['expected_script_sha256']
    key = data['request_key']
    code = data['code']
    require(type(revision) is int and revision > 0, '需要准确的保存修订')
    require(isinstance(expected, str) and re.fullmatch(r'[a-f0-9]{64}', expected),
            '需要准确的原脚本摘要')
    require(isinstance(key, str) and 0 < len(key) <= 160, '需要稳定请求身份')
    require(isinstance(code, str) and code.strip() and '\x00' not in code,
            '代码须为非空 UTF-8 文本且不含空字符')
    try:
        raw = code.encode('utf-8')
    except UnicodeEncodeError:
        require(False, '代码包含无法保存的 Unicode 字符')
    require(len(raw) <= 1024 * 1024, '源码超过 1MB 保存边界', 'context_limit', 413)
    lookup = data['action'] == 'desk.figure.script.receipt'
    identity = digest({'data': {**data, 'action': 'desk.figure.script.save'}, 'principal': principal})
    store = app.store
    with store.transaction() as connection:
        # Recheck live ownership before even returning an earlier receipt. The
        # write lock then keeps this exact source and all other metadata stable.
        current_project = store.get(project['id'], connection=connection)
        current = store.get(data['id'], connection=connection)
        app.access(current_project, scope)
        app.access(current, scope)
        from research_partner.domains.workspace.desk import _principal
        live_scope = _principal(app, principal)
        app.access(current_project, live_scope)
        require(live_scope is None or project['id'] in live_scope,
                '当前凭据没有该项目写权限；共享来源只允许读取', 'forbidden', 403)
        require(not current_project['archived'] and current_project['kind'] == 'project'
                and current['project_id'] == project['id'] and not current['archived']
                and (scope is None or project['id'] in scope),
                '当前图不属于可修改项目', 'forbidden', 403)
        from research_partner.domains.figures.definition import is_definition
        require(current['kind'] == 'figure' and not is_definition(current)
                and not current['content'].get('composition'),
                '只可编辑已有叶图的绘图脚本', 'invalid_figure', 422)
        storage = 'figure_script_save:' + current['id'] + ':' + key
        previous = connection.execute('SELECT value FROM kv WHERE key=?', (storage,)).fetchone()
        if previous:
            receipt = json.loads(previous[0])
            require(receipt['input'] == identity, '同一源码保存请求不能改变内容',
                    'idempotency_conflict', 409)
            return {**receipt['result'], 'replayed': True, **({'found': True} if lookup else {})}
        if lookup:
            return {'found': False, 'executed': False}
        require(current['revision'] == revision and current['content'].get('script_asset') == expected,
                '图或脚本已有新修订；保留草稿，重新读取后比较', 'conflict', 409)
        old_script = app.asset(expected, scope, project['id'])
        require(old_script['size'] <= 1024 * 1024,
                '原脚本超过 1MB 编辑边界；原资产保留', 'context_limit', 413)
        store._verify_asset_blob(expected, old_script['size'])
        old_raw = (store.blobs / expected).read_bytes()
        try:
            unchanged = old_raw.decode('utf-8-sig') == code
        except UnicodeDecodeError:
            unchanged = False
        if unchanged:
            authorized = store.setting('code_grant:' + current['id'], {}).get('script_sha') == expected
            rendered = any(record['result'].get('status') == 'generated'
                and record['result'].get('provenance', {}).get('source_sha256') == digest(current)
                and 'figure.svg' in record['result'].get('assets', {})
                for record in store.export_records(current['id'], current['revision']))
            result = {'figure': current, 'script': old_script, 'saved': False,
                      'executed': False, 'render_required': not rendered,
                      'authorization_required': not authorized, 'manuscript_updated': False}
        else:
            script = store.add_asset(raw, old_script['filename'], 'text/x-python',
                {'project_id': project['id'], 'immutable_input': True}, connection=connection)
            content = copy.deepcopy(current['content'])
            content['script_asset'] = script['sha']
            figure = store.save(current['id'], revision, content=content, merge=False,
                reason='explicit leaf script revision; execution requires separate approval',
                connection=connection)
            connection.execute('DELETE FROM kv WHERE key=?', ('code_grant:' + current['id'],))
            result = {'figure': figure, 'script': script, 'saved': True,
                      'executed': False, 'render_required': True,
                      'authorization_required': True, 'manuscript_updated': False}
        connection.execute('INSERT INTO kv VALUES(?,?)', (storage, encoded({'input': identity, 'result': result})))
        return result
