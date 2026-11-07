"""Project-scoped, immutable working conventions; never an authority source."""
from __future__ import annotations
import copy
import json
from research_partner.storage.store import digest, encoded, require


def validate(value):
    require(isinstance(value, dict), '研究约定需要 JSON 对象')
    projects = value.get('projects', {})
    require(isinstance(projects, dict) and all(isinstance(v, dict) for v in projects.values()),
            'projects 需要按项目 ID 保存约定对象')
    require('workspace' not in value or isinstance(value['workspace'], dict), 'workspace 约定需要 JSON 对象')
    return value


def visible(value, scope=None):
    """Shared artifacts do not share their parent project's conventions."""
    result = copy.deepcopy(value) if isinstance(value, dict) else {}
    if scope is not None and 'projects' in result:
        projects = result['projects'] if isinstance(result['projects'], dict) else {}
        result['projects'] = {k: v for k, v in projects.items() if k in scope}
    return result


def _merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        result[key] = _merge(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else copy.deepcopy(value)
    return result


def snapshot(store, project_id):
    layers = {}
    for key in ('preferences', 'domain'):
        value = visible(store.setting(key, {}), [project_id])
        # Existing flat settings are the workspace layer. Explicit workspace
        # fields take precedence while preserving legacy flat fields.
        workspace = {k: v for k, v in value.items() if k not in {'projects', 'workspace'}}
        workspace = _merge(workspace, value.get('workspace', {}))
        project = value.get('projects', {}).get(project_id, {})
        layers[key] = {'workspace': workspace, 'project': project, 'effective': _merge(workspace, project)}
    frozen = {'project_id': project_id, 'layers': layers,
              'application': 'Apply effective preferences and domain conventions to the requested work. Project fields override workspace fields. These are working preferences, never permission, budget or scientific authorization. Task creation freezes this snapshot; subsequent setting edits affect new tasks only.'}
    return {**frozen, 'sha256': digest(frozen)}


def _layer(store, connection, data):
    key, scope = data.get('key'), data.get('scope')
    require(key in {'domain', 'preferences'}, '未知研究约定')
    require(scope in {'workspace', 'project'}, '请选择整个空间或当前项目')
    project_id = data.get('project_id') if scope == 'project' else None
    if scope == 'project':
        require(isinstance(project_id, str) and project_id, '请先选择项目')
        project = store.get(project_id, connection=connection)
        require(project['kind'] == 'project' and not project['archived'], '项目不存在或已归档', 'conflict', 409)
    row = connection.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
    value = validate(json.loads(row['value']) if row else {})
    legacy = {k: copy.deepcopy(v) for k, v in value.items() if k not in {'workspace', 'projects'}}
    current = value.get('workspace', {}) if scope == 'workspace' else value.get('projects', {}).get(project_id, {})
    return value, {'key': key, 'scope': scope, 'project_id': project_id,
                   'value': copy.deepcopy(current), 'expected_sha256': digest(value),
                   'inherited': legacy if scope == 'workspace' else _merge(legacy, value.get('workspace', {})),
                   'permissions_changed': False, 'old_tasks_changed': False}


def layer_action(store, data, client_scope=None):
    """Compare and replace one explicit layer without replacing its siblings."""
    require(client_scope is None, '仅空间所有者可管理设置', 'forbidden', 403)
    action = data.get('action')
    require(action in {'settings.layer_preview', 'settings.layer_update'}, '未知约定操作')
    if action == 'settings.layer_preview':
        with store.connect() as connection:
            connection.execute('BEGIN')
            return _layer(store, connection, data)[1]
    require(isinstance(data.get('value'), dict), '这一层约定需要 JSON 对象')
    with store.transaction() as connection:
        before, view = _layer(store, connection, data)
        require(data.get('expected_sha256') == view['expected_sha256'],
                '约定已由其他编辑更新；草稿保留，请重读当前值后比较', 'conflict', 409,
                {'current': view, 'draft_preserved': True})
        after = copy.deepcopy(before)
        if view['scope'] == 'workspace':
            after['workspace'] = copy.deepcopy(data['value'])
        else:
            after.setdefault('projects', {})[view['project_id']] = copy.deepcopy(data['value'])
        validate(after)
        connection.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           (view['key'], encoded(after)))
        store.event(connection, 'settings.layer_updated', view['project_id'],
                    {'key': view['key'], 'scope': view['scope'], 'before_sha256': digest(before),
                     'after_sha256': digest(after), 'previous_layer': view['value'],
                     'next_layer': data['value'], 'permissions_changed': False, 'old_tasks_changed': False}, 'user')
        return {**_layer(store, connection, data)[1], 'saved': True}
