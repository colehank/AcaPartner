"""User-authorized partner turns → atomic changes to the existing research graph.

Store, graph validation, relation history and the shared Runtime remain owners.
Generated structure is provisional; this module never confirms scientific work.
"""
from __future__ import annotations
import copy
import json
import re
from graphlib import TopologicalSorter, CycleError
from .store import Problem, digest, encoded, now, require
from . import research_graph as graph

FEATURE = 'partner_graph_changes_v1'
KEY = 'partner_graph_change:'
LOCAL = re.compile(r'[a-z][A-Za-z0-9_.-]{0,79}')


def state_pin(view):
    return digest({'project': view['project'],
                   'nodes': [{k: n.get(k) for k in ('id', 'revision', 'signature')} for n in view['nodes']],
                   'edges': [{k: e[k] for k in ('id', 'src', 'dst', 'kind', 'revision', 'active')} for e in view['edges']]})


def input_graph(app, project, data, connection):
    view = graph.read(app, project, connection)
    require(len(view['nodes']) <= 80 and len(view['edges']) <= 160,
            '研究图超过本轮上下文范围，请先缩小项目范围', 'context_limit', 413)
    focus = data.get('graph_focus')
    require(focus is None or isinstance(focus, str), '当前研究节点需要准确身份')
    focus = focus or None
    selected = data.get('questions', [])
    require(isinstance(selected, list) and len(selected) <= 4, '单次最多选择4个研究问题')
    ids = {focus} if focus else set()
    by_id = {n['id']: n for n in view['nodes']}
    require(not focus or focus in by_id, '选中节点不属于当前研究图', 'forbidden', 403)
    ids.update(r['id'] for r in data.get('materials', []) if r['id'] in by_id)
    for ref in selected:
        require(isinstance(ref, dict) and set(ref) == {'id', 'revision', 'parts'}
                and isinstance(ref.get('id'), str) and ref['id'] in by_id
                and type(ref['revision']) is int and isinstance(ref['parts'], list)
                and all(isinstance(part, str) and part in {'Q', 'A', 'E', 'C'} for part in ref['parts']),
                '选中的研究问题不可用', 'forbidden', 403)
        node = by_id[ref['id']]
        require(node['kind'] == 'Q' and node['revision'] == ref['revision'], '研究问题已有新版本，请重新发送', 'conflict', 409)
        ids.add(node['id'])
    nodes = [{k: copy.deepcopy(n[k]) for k in ('id', 'kind', 'label', 'title', 'revision', 'status')}
             | ({'body': n['body']} if n['id'] in ids else {}) for n in view['nodes']]
    edges = [{k: e[k] for k in ('id', 'src', 'dst', 'kind', 'revision', 'active')} for e in view['edges']]
    return {'version': 1, 'project_id': project['id'], 'project_revision': project['revision'],
            'pin': state_pin(view), 'focus_id': focus, 'nodes': nodes, 'edges': edges,
            'editable': bool(view['migrated'] or not view['legacy_available'])}


def freeze_request(app, snapshot, connection):
    """Keep the exact user's message as a citation, using the existing Store."""
    from .research_context import freeze
    result = freeze(app, snapshot, connection)
    if not result.get('graph'): return result
    from .compatibility import require_features
    require_features(connection, [FEATURE])
    pid, text = result['project']['id'], result['request']
    ident = 'CTX-' + digest([pid, 'user_input', text])[:24]
    content = {'markdown': text}
    metadata = {'research_role': 'material_snapshot', 'research_context_snapshot': {
        'authority_kind': 'user_input', 'sha256': digest(text), 'bytes': len(text.encode())}}
    row = connection.execute('SELECT id FROM objects WHERE id=?', (ident,)).fetchone()
    obj = app.store.get(ident, connection=connection) if row else app.store.create(
        'concept', '研究输入', pid, content, metadata, ident=ident, actor='user', connection=connection)
    require(obj['project_id'] == pid and not obj['archived'] and obj['content'] == content and obj['metadata'] == metadata,
            '研究输入来源身份不同', 'integrity', 409)
    ref = {'id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj)}
    result['graph']['request_source'] = ref
    if ref not in result['materials']: result['materials'].append(ref)
    from .research_tasks import check_input_size
    return check_input_size(app, result, connection)


def schema():
    return '''Return exactly {title:string,kind:"note",partner_reply:{version:1,text:string,next_steps:[{id:ASCII_ID,label:string,prompt:string}]},graph_change:null|{
version:1,summary:string,background:null|string,
creates:[{id:local_lowercase_ASCII_key,kind:"Q"|"A"|"E"|"C",title:string,body:string,quote:string,source_refs:[{id,revision}]}],
updates:[{id:exact_existing_node_id,title:null|string,body:null|string,quote:string,source_refs:null|[{id,revision}]}],
edges:[{src:local_key_or_existing_id_or_"project",dst:local_key_or_existing_id,kind:"contains"|"analyzes"|"produces"|"supports"|"limits"|"refutes"|"answers"|"prerequisite",rationale:string}]}}.
The graph is the current research record. Use its exact IDs; do not duplicate an existing question or analysis.
Structure an idea immediately into useful provisional Qs and, where justified, planned As. Do not require an approval screen before drawing. Ordinary discussion may return graph_change:null.
Parent Qs only contain child Qs; only leaf Qs own AEC. Put synthesis in an explicit final leaf Q. Each A has at most one E; multiple E may support one C.
Edge directions are exact: project/root → Q contains; parent Q → child Q contains; leaf Q → A analyzes (NEVER A → Q); A → E produces; E → C supports/limits/refutes; C → leaf Q answers; prerequisite Q → dependent Q prerequisite. src is the left endpoint, dst the right endpoint. For a planned analysis use {src:"new_question",dst:"new_analysis",kind:"analyzes",rationale:"..."}.
No status, confirmations, scripts, file changes, deletions, layout coordinates or arbitrary actions. Up to24 creates,24 updates,48 edges.
Q/A may be proposed without evidence. E/C require a nonempty VERBATIM quote from the user request or selected saved evidence, with exact source_refs (use {id:"request",revision:1} for this user's input). They are reported content awaiting review, never completed work. Never invent results or claim you ran a script.
Existing bodies may be replaced only when that exact body appears in context.partner.graph.nodes. Use body:null for title-only edits. Preserve untargeted content. background:null keeps existing background; a string must preserve existing relevant background.
New Qs without contains are attached to project. contains may attach new Qs, not silently reparent existing ones. Repeated existing edges are no-ops. Keep dependency edges distinct from decomposition. A/E/C must be connected to a Q by their typed relationships.
The service applies a valid change atomically against this frozen graph; concurrent changes keep the candidate unapplied. Reply briefly about what you organized; do not claim scientific approval or guaranteed application.'''


def _text(value, label, maximum=12000, nullable=False):
    require(nullable and value is None or isinstance(value, str) and bool(value.strip()) and len(value.encode()) <= maximum,
            label + '无效或过长', 'invalid_model_output', 422)
    return value


def _references(app, task, refs, quote, kind):
    snapshot = task['payload']['context']['partner']
    allowed = {(r['id'], r['revision']): r for r in snapshot['materials']}
    request_ref = snapshot['graph']['request_source']
    require(isinstance(refs, list) and len(refs) <= 16 and isinstance(quote, str), '节点来源无效', 'invalid_model_output', 422)
    normalized, quoted = [], False
    for ref in refs:
        require(isinstance(ref, dict) and set(ref) == {'id', 'revision'} and isinstance(ref['id'], str) and type(ref['revision']) is int,
                '来源需要准确身份与版本', 'invalid_model_output', 422)
        ref = request_ref if ref == {'id': 'request', 'revision': 1} else ref
        require((ref['id'], ref['revision']) in allowed, '节点来源不在本次输入中', 'invalid_model_output', 422)
        source = app.store.get(ref['id'], ref['revision'])
        text = source['content'].get('markdown', source['content'].get('text', ''))
        eligible = source['metadata'].get('research_role') != 'research_question_v1' and (
            source['metadata'].get('research_role') != graph.ROLE_NODE or source['metadata'].get('graph_node', {}).get('kind') == 'E')
        # Blocks are actual selected saved text too; do not compare metadata/IDs.
        texts = [text, *[b.get('text', '') for b in source['content'].get('blocks', []) if isinstance(b, dict)]]
        quoted |= bool(eligible and quote.strip() and any(isinstance(t, str) and quote in t for t in texts))
        fixed = {'id': source['id'], 'revision': source['revision'], 'sha256': digest(source)}
        if fixed not in normalized: normalized.append(fixed)
    require(kind not in {'E', 'C'} or quoted, '证据与结论需要选定来源中的逐字依据，不能从计划生成结果', 'invalid_model_output', 422)
    if request_ref not in normalized: normalized.append(copy.deepcopy(request_ref))
    return normalized


def validate(app, task, value):
    if value is None: return None
    require(isinstance(value, dict) and set(value) == {'version', 'summary', 'background', 'creates', 'updates', 'edges'}
            and type(value['version']) is int and value['version'] == 1 and len(encoded(value).encode()) <= 96000,
            '图变更结构或大小无效', 'invalid_model_output', 422)
    _text(value['summary'], '图变更说明', 4000); _text(value['background'], '背景', 32000, True)
    for name, limit in (('creates', 24), ('updates', 24), ('edges', 48)):
        require(isinstance(value[name], list) and len(value[name]) <= limit, '图变更超出本轮范围', 'invalid_model_output', 422)
    snapshot = task['payload']['context']['partner']['graph']
    existing = {n['id']: n for n in snapshot['nodes'] if n['kind'] != 'root'}
    created, updated, result = {}, set(), copy.deepcopy(value)
    for item in result['creates']:
        require(isinstance(item, dict) and set(item) == {'id', 'kind', 'title', 'body', 'quote', 'source_refs'}
                and isinstance(item['id'], str) and LOCAL.fullmatch(item['id']) and item['id'] not in created
                and item['id'] not in existing and item['id'] != 'project' and isinstance(item['kind'], str) and item['kind'] in {'Q', 'A', 'E', 'C'},
                '新研究节点身份或类型无效', 'invalid_model_output', 422)
        _text(item['title'], '节点标题', 2000); require(len(item['title']) <= 500, '节点标题过长', 'invalid_model_output', 422)
        _text(item['body'], '节点正文')
        item['source_refs'] = _references(app, task, item['source_refs'], item['quote'], item['kind'])
        created[item['id']] = item
    for item in result['updates']:
        require(isinstance(item, dict) and set(item) == {'id', 'title', 'body', 'quote', 'source_refs'}
                and isinstance(item.get('id'), str) and item['id'] in existing and item['id'] not in updated, '修改节点不在本次研究图中', 'invalid_model_output', 422)
        old = existing[item['id']]; updated.add(item['id'])
        _text(item['title'], '节点标题', 2000, True); _text(item['body'], '节点正文', nullable=True)
        require(item['title'] is None or len(item['title']) <= 500, '节点标题过长', 'invalid_model_output', 422)
        require(item['body'] is None or 'body' in old, '修改正文前需要选中该节点的保存版', 'invalid_model_output', 422)
        refs = [] if item['source_refs'] is None else item['source_refs']
        item['source_refs'] = _references(app, task, refs, item['quote'], old['kind'] if item['body'] is not None else 'Q')
    kinds = {snapshot['project_id']: 'root', 'project': 'root', **{i: n['kind'] for i, n in existing.items()}, **{i: n['kind'] for i, n in created.items()}}
    parents = {}
    for e in result['edges']:
        require(isinstance(e, dict) and set(e) == {'src', 'dst', 'kind', 'rationale'} and isinstance(e['src'], str)
                and isinstance(e['dst'], str) and e['src'] in kinds and e['dst'] in kinds and e['src'] != e['dst']
                and isinstance(e['kind'], str) and e['kind'] in graph.EDGE_TYPES, '图关系身份或类型无效', 'invalid_model_output', 422)
        _text(e['rationale'], '关系依据', 4000)
        if e['kind'] == 'contains':
            if e['dst'] in created:
                require(created[e['dst']]['kind'] == 'Q' and e['dst'] not in parents, '新问题只能有一个拆解父问题', 'invalid_model_output', 422)
                parents[e['dst']] = e['src']
            else:
                require(any(old['active'] and old['src'] == e['src'] and old['dst'] == e['dst'] and old['kind'] == e['kind'] for old in snapshot['edges']),
                        '不能在本轮中隐式移动已有问题，请使用问题整理操作', 'invalid_model_output', 422)
    require(result['creates'] or result['updates'] or result['edges'] or result['background'] is not None,
            '没有研究变更时应返回 graph_change:null', 'invalid_model_output', 422)
    return result


def application(app, task_id, connection):
    row = connection.execute('SELECT value FROM kv WHERE key=?', (KEY + task_id,)).fetchone()
    return json.loads(row[0]) if row else None


def _public(record):
    return {k: record[k] for k in ('status', 'summary', 'created_ids', 'updated_ids', 'edge_ids', 'project_revision')}


def apply(app, task, content, proposal_ref, connection):
    """Called only within guarded publication, under the same write transaction."""
    value = content.get('graph_change')
    if value is None: return None
    prior = application(app, task['id'], connection)
    if prior: return _public(prior)
    c, s, pid = connection, app.store, task['project_id']
    proposal_ref = {'id': proposal_ref['object_id'], 'revision': proposal_ref['revision'], 'sha256': proposal_ref['sha256']}
    frozen = task['payload']['context']['partner']['graph']
    project = s.get(pid, connection=c); current = graph.read(app, project, c)
    if state_pin(current) != frozen['pin']:
        return {'status': 'conflict', 'summary': '研究图已有新版本，本轮结果已保留，未覆盖当前内容。'}
    if not frozen['editable']:
        return {'status': 'unapplied', 'summary': '原有 QAEC 尚未导入独立研究图，请先在画布导入，原内容已保留。'}
    # A failed graph change never leaves partial nodes, edges or compatibility
    # markers. The actual model reply can still be published with its conflict.
    c.execute('SAVEPOINT partner_graph')
    try:
        from .compatibility import require_features
        require_features(c, [FEATURE, graph.FEATURE, graph.LEAF_FEATURE])
        objects = [o for o in graph._objects(app, pid, c) if o['id'] != project['metadata'].get('research_root_question_id')]
        before = {o['id']: copy.deepcopy(o) for o in objects}; before_edges = {e['id']: copy.deepcopy(e) for e in graph._edges(app, pid, graph._objects(app, pid, c), c)}
        by_id = dict(before); aliases = {'project': pid, pid: pid, **{i: i for i in before}}
        created = {n['id']: n for n in value['creates']}
        parents = {e['dst']: e['src'] for e in value['edges'] if e['kind'] == 'contains' and e['dst'] in created}
        dependencies = {i: ([parents[i]] if parents.get(i) in created else []) for i in created}
        try: order = list(TopologicalSorter(dependencies).static_order())
        except CycleError: raise Problem('问题拆解形成循环', 'dependency_cycle', 409)
        origin = {'kind': 'partner_graph', 'task_id': task['id'], 'proposal_ref': proposal_ref,
                  'input_graph_pin': frozen['pin'], 'request_source': frozen['request_source']}
        for ident in order:
            item = created[ident]; kind = item['kind']
            metadata = {'research_role': graph.ROLE_NODE, 'graph_node': {'kind': kind, 'status': 'review' if kind in {'E', 'C'} else 'not_started'},
                        'graph_origin': {**origin, 'change_id': ident, 'quote': item['quote']}}
            if kind == 'Q':
                parent = aliases.get(parents.get(ident, 'project'))
                require(parent in {pid, *by_id}, '父问题尚不可用', 'invalid_model_output', 422)
                q = graph.create_question(s, c, pid, item['title'], parent=None if parent == pid else parent, actor='agent',
                                          origin=metadata['graph_origin'], qaec={'Q': item['body'], 'A': '', 'E': '', 'C': ''})
                obj = s.save(q['id'], q['revision'], content={**q['content'], 'source_refs': item['source_refs']},
                             metadata={**q['metadata'], 'graph_node': metadata['graph_node'], 'graph_origin': metadata['graph_origin']}, actor='agent', merge=False, connection=c)
            else:
                obj = s.create('concept', item['title'], pid, {'text': item['body'], 'source_refs': item['source_refs']}, metadata, actor='agent', connection=c)
            aliases[ident] = obj['id']; by_id[obj['id']] = obj
        updated = []
        for item in value['updates']:
            old = by_id[item['id']]; body = copy.deepcopy(old['content']); metadata = copy.deepcopy(old['metadata'])
            if item['body'] is not None:
                if graph._kind(old) == 'Q': body.setdefault('qaec', {})['Q'] = item['body']
                else: body['text'] = item['body']
            refs = body.setdefault('source_refs', [])
            for ref in item['source_refs']:
                if ref not in refs: refs.append(copy.deepcopy(ref))
            metadata['graph_origin'] = {**origin, 'change_id': item['id'], 'quote': item['quote']}
            obj = s.save(old['id'], old['revision'], title=item['title'] or old['title'], content=body, metadata=metadata,
                         actor='agent', reason='partner.graph.update', merge=False, connection=c)
            by_id[obj['id']] = obj; updated.append(obj['id'])
        for e in value['edges']:
            a, b = aliases[e['src']], aliases[e['dst']]
            existing = next((r for r in graph._edges(app, pid, list(by_id.values()), c) if r['active'] and r['src'] == a and r['dst'] == b and r['kind'] == e['kind']), None)
            if not existing: graph._link(app, c, a, b, e['kind'], e['rationale'], 'agent')
        objects = list(by_id.values()); edges = graph._edges(app, pid, objects, c)
        graph._validate(objects, edges, pid, graph._parent_conflicts(list(before.values()), list(before_edges.values())))
        projected_edges = graph.read(app, project, c)['edges']
        reachable, pending = set(), [pid]
        while pending:
            ident = pending.pop()
            if ident in reachable: continue
            reachable.add(ident)
            pending.extend(e['dst'] for e in projected_edges if e['active'] and e['src'] == ident and e['kind'] not in {'answers', 'prerequisite'})
        new_ids = [aliases[i] for i in created]
        require(all(i in reachable for i in new_ids), '新节点需要通过明确关系连接到研究问题', 'invalid_model_output', 422)
        body = copy.deepcopy(project['content'])
        if value['background'] is not None: body['background'] = value['background']
        saved = s.save(pid, project['revision'], content=body, metadata={**project['metadata'], 'research_graph_version': 2, 'research_graph_question_model': 'leaf_v1'},
                       actor='agent', reason='partner.graph.apply', merge=False, connection=c)
        changed_edges = [e['id'] for e in graph._edges(app, pid, graph._objects(app, pid, c), c) if e['id'] not in before_edges]
        record = {'status': 'applied', 'summary': value['summary'], 'created_ids': new_ids, 'updated_ids': updated,
                  'edge_ids': changed_edges, 'project_revision': saved['revision'], 'proposal_ref': proposal_ref,
                  'before_project': project, 'before_nodes': {i: before[i] for i in updated},
                  'after_pin': state_pin(graph.read(app, saved, c))}
        c.execute('INSERT INTO kv VALUES(?,?)', (KEY + task['id'], encoded(record)))
        s.event(c, 'research.graph.applied', pid, {**_public(record), 'task_id': task['id'], 'proposal_ref': proposal_ref}, 'agent')
        c.execute('RELEASE partner_graph')
        return _public(record)
    except Problem as error:
        c.execute('ROLLBACK TO partner_graph'); c.execute('RELEASE partner_graph')
        return {'status': 'conflict' if error.status == 409 else 'unapplied', 'summary': str(error), 'code': error.code}


def undo(app, data, scope, principal):
    require(set(data) == {'action', 'project_id', 'task_id', 'request_key'}, '撤销字段不支持')
    require((principal or {}).get('actor_kind') != 'agent' and (principal or {}).get('kind') != 'agent', '请由研究者撤销本轮图变更', 'forbidden', 403)
    from .research_tasks import project_access, text
    project_access(app, data['project_id'], scope, principal, True); text(data['request_key'], '撤销请求标识', 180)
    s, pid = app.store, data['project_id']
    with s.transaction() as c:
        task = s.task(data['task_id'], c)
        require(task['project_id'] == pid and task['payload'].get('kind') == 'research_partner', '工作记录不属于当前项目', 'forbidden', 403)
        record = application(app, task['id'], c); require(record, '本轮没有已应用的图变更', 'not_ready', 409)
        if record['status'] == 'undone': return {'graph_change': _public(record), 'replayed': True}
        project = s.get(pid, connection=c)
        require(state_pin(graph.read(app, project, c)) == record['after_pin'], '图已有后续修改，未覆盖；请在当前图中调整', 'conflict', 409)
        objects = graph._objects(app, pid, c); edges = graph._edges(app, pid, objects, c)
        for edge in edges:
            if edge['id'] in record['edge_ids']:
                graph._withdraw(app, c, edge, '撤销搭档本轮图变更，保留历史', 'user')
        for ident, old in record['before_nodes'].items():
            current = s.get(ident, connection=c)
            s.save(ident, current['revision'], title=old['title'], content=old['content'], metadata=old['metadata'], actor='user', reason='partner.graph.undo', merge=False, connection=c)
        for ident in record['created_ids']:
            current = s.get(ident, connection=c)
            s.save(ident, current['revision'], archived=True, actor='user', reason='partner.graph.undo', merge=False, connection=c)
        old = record['before_project']
        saved = s.save(pid, project['revision'], content=old['content'], metadata={**project['metadata'], 'research_graph_version': 2},
                       actor='user', reason='partner.graph.undo', merge=False, connection=c)
        record.update(status='undone', project_revision=saved['revision'])
        c.execute('UPDATE kv SET value=? WHERE key=?', (encoded(record), KEY + task['id']))
        result = {**task['result'], 'graph_change': _public(record)}
        c.execute('UPDATE tasks SET result=?,updated_at=? WHERE id=?', (encoded(result), now(), task['id']))
        s.event(c, 'research.graph.undone', pid, {'task_id': task['id'], 'project_revision': saved['revision']}, 'user')
        return {'graph_change': _public(record), 'replayed': False}
