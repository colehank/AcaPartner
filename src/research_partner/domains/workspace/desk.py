"""Project workdesk commands. No task runner or model is constructed here.

Manuscripts keep the existing Store authority and renderer; Markdown is routed
through the native file service. Layout and unsaved drafts are server state,
never a replacement for the project files. This module attests no acceptance.
"""
import copy
import hashlib
import threading

from research_partner.storage.store import Problem, digest, encoded, now, require, uid

_lock = threading.RLock()


def _principal(app, principal):
    from research_partner.domains.workspace.management import authority_scope
    principal = principal or {'kind': 'local_operator'}
    return authority_scope(app, principal)


def _project(app, ident, scope, principal, write=False):
    obj = app.writable(ident, scope) if write else app.get(ident, scope)
    require(obj['kind'] == 'project' and not obj['archived'], '需要未归档项目')
    # Sharing one material is never permission to read the entire notebook.
    require(scope is None or ident in scope, '无项目文件库权限', 'forbidden', 403)
    app.writable(ident, _principal(app, principal))
    return obj


def _state(app, project, namespace, data):
    key = 'desk_w1a:' + namespace + ':' + project['id']
    # Native path operations and browser caches share one file lock. Old
    # revisions fail before a stale browser can reintroduce old-path buffers.
    with app.notebook._locked(project['id']), _lock, app.store.transaction() as c:
        row = c.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
        import json
        current = json.loads(row[0]) if row else {'revision': 0, 'value': {}}
        if data['action'].endswith('.read'):
            return current
        require(data.get('expected_revision') == current['revision'],
                '另一个窗口已更新状态；请先读取，当前草稿不会覆盖', 'conflict', 409,
                {'current': current})
        value = data.get('value')
        require(isinstance(value, dict) and len(encoded(value)) <= 4 * 1024 * 1024,
                '工作桌状态无效或超限')
        result = {'revision': current['revision'] + 1, 'value': value, 'updated_at': now()}
        c.execute('INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (key, encoded(result)))
        return result


def _render(app, obj, scope, principal, template=None):
    template = template or ('double' if obj.get('metadata', {}).get('manuscript_format', {}).get('columns') == 2 else 'single')
    require(template in {'single', 'double'}, '基础模板须为单栏或双栏')
    from research_partner.domains.manuscripts.layout import dispatch as render
    request = {'action': 'manuscript.format.render', 'object_id': obj['id'],
               'expected_revision': obj['revision']}
    result = render(app, request, scope, principal)
    app.store.set_setting('desk_pdf:' + obj['id'], {'revision': obj['revision'],
                          'template': template, **result})
    return result


def dispatch(app, data, scope=None, principal=None):
    action = data.get('action', '')
    if action.startswith('notes.'):
        project = _project(app, data.get('project_id'), scope, principal,
                           action not in {'notes.read', 'notes.list', 'notes.search'})
        from research_partner.domains.workspace.notebook_files import ACTIONS as FILE_ACTIONS,dispatch as file_dispatch
        if action in FILE_ACTIONS:
            require(action in {'notes.move.inspect','notes.trash.list','notes.resolve'} or not principal or principal.get('kind')!='agent','Agent不能移动或回收用户笔记','forbidden',403)
            return file_dispatch(app.notebook,data)
        if action=='notes.search' and data.get('payload',{}).get('scope')=='all_projects':
            # Expand only on the explicit request. Check live authority twice:
            # never trust caller project lists or cached search permissions.
            payload=data['payload'];app.notebook._validate({**data,'payload':{**payload,'scope':'current_project'}})
            def allowed():
                ids=[]
                for p in app.store.objects(kinds=['project'],include_archived=False):
                    if p['kind']!='project' or p['archived']:continue
                    try:_project(app,p['id'],scope,principal)
                    except Problem:continue
                    ids.append(p['id'])
                return ids
            results=[];counts={};limit=payload.get('limit',200)
            for ident in allowed():
                x=app.notebook.dispatch({**data,'project_id':ident,'payload':{**payload,'scope':'current_project'}})
                counts[ident]=x['total_matches'];results.extend(x['matches'])
            live=set(allowed());results=[r for r in results if r['project_id'] in live]
            total=sum(n for ident,n in counts.items() if ident in live)
            return {'scope':'all_projects','query':payload['query'],'matches':results[:limit],'total_matches':total,'truncated':total>limit,'offset_unit':'unicode_code_point'}
        return app.notebook.dispatch(data)
    if action == 'desk.bootstrap':
        projects = []
        for obj in app.store.objects(kinds=['project'], include_archived=False):
            try:
                _project(app, obj['id'], scope, principal)
            except Problem:
                continue
            primary = obj['metadata'].get('article', {}).get('primary_manuscript_id')
            projects.append({**obj, 'primary_manuscript_id': primary})
        return {'projects': projects, 'implementation': app.loaded_implementation,
                'workspace_id': app.store.setting('workspace_id'),
                'runtime_running': bool(app.runner and app.runner.status().get('running')),
                'local_render_ready': bool(app.config.get('rendering', {}).get('latex')),
                'acceptance': 'NOT_ESTABLISHED'}
    if action == 'desk.project.create':
        require(scope is None and _principal(app, principal) is None,
                '受限身份不能创建项目', 'forbidden', 403)
        title = data.get('title')
        request_id = data.get('request_id')
        require(isinstance(title, str) and 0 < len(title.strip()) <= 200, '需要项目名称')
        require(isinstance(request_id, str) and 0 < len(request_id) <= 200, '需要请求标识')
        template = data.get('template', 'single')
        require(template in {'single', 'double'}, '基础模板须为单栏或双栏')
        key = 'desk_create:' + request_id
        fingerprint = digest({'title': title, 'template': template})
        with _lock, app.store.transaction() as c:
            import json
            row = c.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
            if row:
                receipt = json.loads(row[0])
                require(receipt['fingerprint'] == fingerprint, '同一请求标识不能改变内容',
                        'idempotency_conflict', 409)
                project = app.store.get(receipt['project_id'], connection=c)
            else:
                from research_partner.domains.manuscripts.workspace import initialize_output
                p = app.store.create('project', title.strip(), connection=c)
                result = initialize_output(app.store, c, p)
                project = result['project']
                manuscript = result['manuscript']
                from research_partner.domains.manuscripts.formatting import DEFAULT_FORMAT
                fmt = {**DEFAULT_FORMAT, 'columns': 2 if template == 'double' else 1}
                content = copy.deepcopy(manuscript['content'])
                content['blocks'] = [{**block, 'level': 1} if block.get('kind') == 'heading' else block
                                     for block in content['blocks']]
                content['blocks'] = [item for block in content['blocks'] for item in
                                     (block, {'id': uid('BLOCK'), 'kind': 'paragraph', 'text': ''})]
                app.store.save(manuscript['id'], manuscript['revision'], content=content,
                               metadata={**manuscript['metadata'], 'manuscript_format': fmt},
                               connection=c, merge=False, reason='local base template')
                c.execute('INSERT INTO kv VALUES(?,?)', (key, encoded({
                    'fingerprint': fingerprint, 'project_id': project['id']})))
        primary = project['metadata']['article']['primary_manuscript_id']
        note = {'action': 'notes.create', 'project_id': project['id'],
                'request_id': 'inbox:' + request_id,
                'payload': {'relative_path': 'notes/inbox.md', 'markdown': '# 随手记\n\n', 'if_absent': True}}
        with _lock:
            if not app.store.setting("desk_initialized:" + project["id"]):
                try:
                    app.notebook.dispatch({"action": "notes.read", "project_id": project["id"], "request_id": request_id, "payload": {"relative_path": "notes/inbox.md"}})
                except Problem as e:
                    if e.status != 404: raise
                    app.notebook.dispatch(note)
                app.store.set_setting("desk_initialized:" + project["id"], True)
        obj = app.get(primary, scope)
        render = app.store.setting('desk_pdf:' + primary)
        error = None
        if not render or render['revision'] != obj['revision']:
            try:
                render = _render(app, obj, scope, principal, template)
            except Problem as e:
                error = {'code': e.code, 'message': str(e), 'details': e.details}
        return {'project': {**project, 'primary_manuscript_id': primary},
                'manuscript': obj, 'render': render, 'render_error': error,
                'scientific_content_generated': False}
    project = _project(app, data.get('project_id'), scope, principal, True)
    if action=='desk.task.brief':
        from research_partner.domains.collaboration.brief import append
        return append(app,project,app.store.task(data.get('task_id')),scope,principal,
                      expected_final_source=data.get('expected_final_source'))
    if action=='desk.datasets.list':
        from research_partner.domains.generation.generation import dispatch as generation
        return generation(app,data,scope,principal)
    if action=='desk.figures.list' or action.startswith('desk.figure.'):
        from research_partner.domains.figures.desk import dispatch as figure_desk
        return figure_desk(app,data,project,scope,principal)
    if action.startswith('desk.note.review.'):
        from research_partner.domains.workspace.note_review import dispatch as note_review
        return note_review(app,data,project,scope,principal)
    if action == 'desk.note.revision.read':
        from research_partner.domains.workspace.note_revision import read as note_revision
        return note_revision(app, data, project)
    if action.startswith('desk.review.'):
        from research_partner.domains.collaboration.review import dispatch as review
        return review(app,data,project,scope,principal)
    if action == 'desk.asset.import':
        require('path' not in data, '工作桌只接收客户端明确上传的文件', 'forbidden', 403)
        asset = app.import_asset(data, scope)
        return {'id': 'asset:' + asset['sha'], **asset}
    if action == 'desk.assets.list':
        import json
        items = []
        with app.store.connect() as c:
            for row in c.execute('SELECT sha,metadata FROM assets ORDER BY created_at'):
                meta = json.loads(row['metadata'])
                if not meta.get('immutable_input'):
                    continue
                projects = set(meta.get('projects', [])) | {meta.get('project_id')}
                if project['id'] in projects:
                    asset = app.asset(row['sha'], scope, project['id'])
                    items.append({'id': 'asset:' + asset['sha'], **asset})
        return {'items': items}
    if action in {'desk.layout.read', 'desk.layout.write'}:
        return _state(app, project, 'layout', data)
    if action in {'desk.drafts.read', 'desk.drafts.write'}:
        return _state(app, project, 'drafts', data)
    primary = project['metadata'].get('article', {}).get('primary_manuscript_id')
    if action == 'desk.paper.read':
        obj = app.artifact(primary, scope)
        return {'object': obj, 'render': app.store.setting('desk_pdf:' + primary)}
    if action == 'desk.paper.edits':
        return app.dispatch({'action':'manuscript.edit.view','object_id':primary},scope,principal=principal)
    if action=='desk.paper.edit.decide':
        from research_partner.domains.manuscripts.formatting import dispatch as edit_decide
        request={k:v for k,v in data.items() if k!='project_id'}
        request.update(action='manuscript.edit.decide',object_id=primary)
        return edit_decide(app,request,scope,principal)
    if action in {'desk.paper.direct','desk.paper.propose'}:
        from research_partner.domains.manuscripts.paper import save_direct
        return save_direct(app,data,primary,scope,principal)
    if action == 'desk.paper.save':
        obj = app.writable(primary, scope)
        blocks = data.get('blocks')
        require(isinstance(blocks, list) and len(blocks) <= 10000, '稿件块无效')
        old = {b['id']: b for b in obj['content'].get('blocks', [])}
        require({b.get('id') for b in blocks} == set(old) and len(blocks) == len(old),
                '本轮本地编辑只修改既有章节文字；结构修订另有入口')
        content = copy.deepcopy(obj['content'])
        for block in blocks:
            require(set(block) == {'id', 'text'} and isinstance(block['text'], str), '需要原块与文字')
        content['blocks'] = [{**b, 'text': next(x['text'] for x in blocks if x['id'] == b['id'])}
                             for b in obj['content']['blocks']]
        result = app.store.save(primary, data.get('expected_revision'), content=content,
                                merge=False, reason='local workdesk section text edit')
        return {'object': result, 'render': app.store.setting('desk_pdf:' + primary)}
    if action == 'desk.paper.render':
        obj = app.writable(primary, scope)
        require(obj['revision'] == data.get('expected_revision'), '稿件已经改变', 'conflict', 409)
        return _render(app, obj, scope, principal)
    raise Problem('工作桌命令不支持', 'not_supported', 422)
