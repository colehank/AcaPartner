"""Project-scoped research projection for the unified workbench.

Research Qs are concepts with an explicit role, separate from blocking task
questions. Store remains authoritative; this does not reinterpret old gates.
"""
from __future__ import annotations
import copy
import json
from .store import require, encoded, digest

ROLE = 'research_question_v1'
FIELDS = {
    'workbench.research.read': {'action', 'project_id'},
    'workbench.question.create': {'action', 'project_id', 'title', 'parent_id', 'request_key'},
    'workbench.question.save': {'action', 'project_id', 'id', 'expected_revision', 'title', 'qaec', 'status', 'request_key'},
    'workbench.background.save': {'action', 'project_id', 'expected_revision', 'background', 'request_key'},
}


def sibling_order(questions):
    """Reuse workbench order; legacy questions keep creation order, never title order."""
    created = sorted(questions, key=lambda q: (q['created_at'], q['id']))
    def rank(pair):
        index, question = pair
        order = question['metadata'].get('workbench', {}).get('order')
        return (order if type(order) is int and order >= 0 else index, index)
    return [question for _, question in sorted(enumerate(created), key=rank)]


def numbered_questions(questions, root_id=None):
    """Number the current visible hierarchy without changing titles, IDs or revisions."""
    by_id = {q['id']: q for q in questions}
    groups = {}
    for q in questions:
        parent = q['metadata'].get('parent_question_id')
        groups.setdefault(parent if parent in by_id and parent != q['id'] else None, []).append(q)
    result, seen = [], set()
    def walk(roots, start=1):
        pending = [(q, str(i), None) for i, q in reversed(list(enumerate(sibling_order(roots), start)))]
        while pending:
            q, number, parent = pending.pop()
            if q['id'] in seen: continue
            seen.add(q['id']); result.append({**q, 'number': 'Q' + number, 'tree_parent_id': parent})
            children = sibling_order(groups.get(q['id'], []))
            pending.extend((child, number + '.' + str(i), q['id']) for i, child in reversed(list(enumerate(children, 1))))
    walk(groups.get(None, []))
    # A malformed imported cycle must not hide all of its contents or recurse forever.
    for q in sibling_order(questions):
        if q['id'] not in seen: walk([q], sum('.' not in x['number'] for x in result) + 1)
    root = next((q for q in result if q['id'] == root_id and not q['tree_parent_id']), None)
    if root:
        prefix = root['number']
        for q in result:
            if q['id'] == root_id: q['number'] = 'Q'
            elif q['number'].startswith(prefix + '.'): q['number'] = 'Q' + q['number'][len(prefix)+1:]
        result.sort(key=lambda q: 0 if q['id'] == root_id else 1)
    return result


def create_question(store, connection, project_id, title, parent=None, actor='user', *, origin=None, qaec=None):
    """One transactional creation path for manual questions and adopted proposals."""
    require(isinstance(title, str) and 0 < len(title.strip()) <= 500, '请输入研究问题（最多500字）')
    if not parent:
        root_id = store.get(project_id, connection=connection)['metadata'].get('research_root_question_id')
        if root_id:
            row = connection.execute('SELECT * FROM objects WHERE id=? AND project_id=? AND archived=0', (root_id, project_id)).fetchone()
            if row and store.unpack(row)['metadata'].get('research_role') == ROLE: parent = root_id
    if parent:
        p = store.get(parent, connection=connection)
        require(p['project_id'] == project_id and not p['archived']
                and p['metadata'].get('research_role') == ROLE, '父问题不属于当前项目', 'forbidden', 403)
        project=store.get(project_id,connection=connection)
        if project['metadata'].get('research_graph_version')==2 and parent!=project['metadata'].get('research_root_question_id'):
            rows=connection.execute('SELECT type,metadata,status FROM relations WHERE src=? OR dst=?',(parent,parent)).fetchall()
            owned=any(r['status'] not in {'withdrawn','rejected','superseded'} and
                      json.loads(r['metadata']).get('research_graph',{}).get('kind') in {'analyzes','answers'}
                      for r in rows)
            require(not owned,'问题已有 AEC，请从研究图拆分并迁移已有工作，再添加子问题','decomposition_required',409)
    siblings = [store.unpack(row) for row in connection.execute('SELECT * FROM objects WHERE project_id=?', (project_id,))]
    siblings = [q for q in siblings if q['metadata'].get('research_role') == ROLE
                and (q['metadata'].get('parent_question_id') or None) == (parent or None)]
    ranks = [q['metadata'].get('workbench', {}).get('order') for q in siblings]
    order = max([len(siblings) - 1] + [r for r in ranks if type(r) is int and r >= 0]) + 1
    metadata = {'research_role': ROLE, 'parent_question_id': parent, 'workbench': {'order': order}}
    if origin is not None: metadata['origin'] = copy.deepcopy(origin)
    result = store.create('concept', title.strip(), project_id,
                          {'qaec': qaec or {'Q': title.strip(), 'A': '', 'E': '', 'C': ''}, 'research_status': 'open'},
                          metadata, connection=connection, actor=actor)
    store.relate(parent or project_id, result['id'], 'contains', 'confirmed', connection=connection)
    return result


def dispatch(app, data, scope=None, principal=None):
    action = data.get('action')
    require(action in FIELDS and set(data) <= FIELDS[action], '研究操作或字段不支持')
    from .desk_w1a import _project
    writable = action != 'workbench.research.read'
    project = _project(app, data.get('project_id'), scope, principal, writable)
    if not writable:
        with app.store.read_snapshot() as c:
            project = app.store.get(project['id'], connection=c)
            questions = [app.store.unpack(row) for row in c.execute('SELECT * FROM objects WHERE project_id=?', (project['id'],))]
            questions = [o for o in questions if o['project_id'] == project['id']
                         and not o['archived'] and o['metadata'].get('research_role') == ROLE]
            from .research_nodes import project_states, identity
            states = project_states(questions, app.store, c)
            visible = numbered_questions(questions, project['metadata'].get('research_root_question_id'))
            graph_states = {}
            if project['metadata'].get('research_graph_version') == 2:
                from .research_graph import read
                graph_states = {n['id']:n for n in read(app,project,c)['nodes'] if n['kind']=='Q'}
            for q in visible:
                q['node_states'] = {p:states[identity(q['id'],p)] for p in ('Q','A','E','C')}
                if q['id'] in graph_states: q['graph_state'] = graph_states[q['id']]
            return {'project': project, 'background': project['content'].get('background', ''), 'questions': visible}
    key = data.get('request_key')
    require(isinstance(key, str) and 0 < len(key) <= 180, '需要稳定请求标识')
    fingerprint = digest({'request': data, 'scope': sorted(scope) if scope is not None else None, 'principal': principal})
    with app.store.transaction() as c:
        project = _project(app, data['project_id'], scope, principal, True)
        project = app.store.get(project['id'], connection=c)
        name = 'workbench_research_request:' + key
        row = c.execute('SELECT value FROM kv WHERE key=?', (name,)).fetchone()
        prior = json.loads(row[0]) if row else None
        require(not prior or prior['fingerprint'] == fingerprint, '同一请求标识内容已改变', 'idempotency_conflict', 409)
        if prior:
            return {**app.store.get(prior['id'], prior['revision'], c), 'replayed': True}
        from .project_management import actor
        who = actor(principal or {'kind': 'local_operator'})
        if action == 'workbench.question.create':
            result = create_question(app.store, c, project['id'], data.get('title'), data.get('parent_id'), who)
        else:
            obj = project if action == 'workbench.background.save' else app.store.get(data.get('id'), connection=c)
            require((action == 'workbench.background.save' and obj['id'] == project['id']) or
                    (action == 'workbench.question.save' and obj['kind'] == 'concept' and obj['project_id'] == project['id']
                    and not obj['archived'] and obj['metadata'].get('research_role') == ROLE), '研究对象不属于当前项目', 'forbidden', 403)
            require(type(data.get('expected_revision')) is int and data['expected_revision'] == obj['revision'],
                    '内容已有新版本；当前草稿保留，请比较后重新保存', 'conflict', 409)
            content = copy.deepcopy(obj['content'])
            if action == 'workbench.background.save':
                background = data.get('background')
                require(isinstance(background, str) and len(background.encode()) <= 2 * 1024 * 1024, '背景内容过大')
                content['background'] = background
                title = obj['title']
            else:
                qaec = data.get('qaec')
                require(isinstance(qaec, dict) and set(qaec) == {'Q', 'A', 'E', 'C'}
                        and all(isinstance(v, str) for v in qaec.values()) and len(encoded(qaec).encode()) <= 2 * 1024 * 1024,
                        'QAEC 内容无效或过大')
                status = data.get('status', 'open')
                require(status in {'open', 'active', 'review', 'answered'}, '研究状态无效')
                title = data.get('title', obj['title'])
                require(isinstance(title, str) and 0 < len(title.strip()) <= 500, '研究问题标题无效')
                content.update(qaec=qaec, research_status=status)
            result = app.store.save(obj['id'], obj['revision'], title=title, content=content,
                                    merge=False, actor=who, connection=c, reason=action)
        from .compatibility import require_features
        require_features(c, ['unified_research_workspace_v1'])
        c.execute('INSERT INTO kv VALUES(?,?)', (name, encoded({'fingerprint': fingerprint, 'id': result['id'], 'revision': result['revision']})))
        return result
