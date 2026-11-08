"""Independent research nodes and versioned semantic edges on Store.

Graph relations reuse graph_growth history; no second graph database. Scientific
completion is explicit, authenticated, and pinned to content and prerequisites.
"""
from __future__ import annotations
import copy
import json
from graphlib import TopologicalSorter, CycleError
from .store import require, digest, encoded, now
from .desk_w1a import _project
from .workbench_research import ROLE, create_question, numbered_questions
from .research_nodes import STATUSES, project_states, identity
from .graph_growth import _relation, _history, _insert_relation

ROLE_NODE = 'research_node_v2'
KEY = 'research_graph:'
FEATURE = 'free_research_graph_v2'
LEAF_FEATURE = 'leaf_research_questions_v1'
EDGE_TYPES = {'contains':'contains', 'analyzes':'studies', 'produces':'produces',
              'supports':'supports', 'limits':'limits', 'refutes':'cites',
              'answers':'related', 'prerequisite':'depends_on'}
LABELS = {'contains':'拆解', 'analyzes':'开展分析', 'produces':'产生证据', 'supports':'支持',
          'limits':'限制', 'refutes':'反驳', 'answers':'回答', 'prerequisite':'前置条件'}


def _objects(app, pid, c):
    return [app.store.unpack(r) for r in c.execute("SELECT * FROM objects WHERE project_id=? AND archived=0", (pid,))
            if json.loads(r['metadata']).get('research_role') in {ROLE, ROLE_NODE}]


def _kind(o):
    return 'Q' if o['metadata'].get('research_role') == ROLE else o['metadata'].get('graph_node', {}).get('kind')


def _body(o):
    return o['content'].get('qaec', {}).get('Q', '') if _kind(o) == 'Q' else o['content'].get('text', '')


def _sha(o):
    return digest({'kind':_kind(o), 'title':o['title'], 'body':_body(o), 'sources':o['content'].get('source_refs',[])})


def _edges(app, pid, objects, c):
    ids = {pid, *[o['id'] for o in objects]}; result = []
    for row in c.execute('SELECT * FROM relations ORDER BY id'):
        if row['src'] not in ids or row['dst'] not in ids: continue
        value = app.store.unpack(row); cfg = value['metadata'].get('research_graph', {})
        kind = cfg.get('kind')
        if not kind and value['type'] == 'contains': kind = 'contains'
        if kind not in EDGE_TYPES: continue
        result.append({**value, 'kind':kind, 'revision':value['metadata'].get('graph_revision', 1),
                       'rationale':cfg.get('rationale', ''), 'active':value['status'] not in {'withdrawn','rejected','superseded'}})
    return result


def _dependencies(objects, edges):
    kinds = {o['id']:_kind(o) for o in objects}; result = {o['id']:[] for o in objects}
    for e in edges:
        if e['active'] and e['kind']=='contains' and kinds.get(e['src'])=='Q' and kinds.get(e['dst'])=='Q':
            result[e['src']].append({**e, 'src':e['dst'], 'dst':e['src']})
            continue
        if not e['active'] or e['dst'] not in result: continue
        if e['kind'] in {'produces','supports','limits','refutes','answers','prerequisite'}:
            result[e['dst']].append(e)
    return result


def _question_structure(objects, edges):
    qs = {o['id'] for o in objects if _kind(o)=='Q'}
    children = {q:[] for q in qs}; own = {q:[] for q in qs}
    for e in edges:
        if not e['active']: continue
        if e['kind']=='contains' and e['src'] in qs and e['dst'] in qs: children[e['src']].append(e)
        if e['kind']=='analyzes' and e['src'] in qs: own[e['src']].append(e)
        if e['kind']=='answers' and e['dst'] in qs: own[e['dst']].append(e)
    return children, own


def _parent_conflicts(objects, edges):
    children, own = _question_structure(objects, edges)
    return {qid:{e['id'] for e in children[qid]+own[qid]} for qid in children if children[qid] and own[qid]}


def _order(deps):
    try: return list(TopologicalSorter({i:[e['src'] for e in es] for i,es in deps.items()}).static_order())
    except CycleError: require(False, '完成依赖形成循环；问题拆解不需要设为前置条件', 'dependency_cycle', 409)


def _states(app, objects, edges, c):
    by_id = {o['id']:o for o in objects}; deps = _dependencies(objects, edges); result = {}
    children, own = _question_structure(objects, edges)
    for ident in _order(deps):
        if ident not in by_id: continue
        o = by_id[ident]; cfg = o['metadata'].get('graph_node', {}); state = cfg.get('status', 'not_started')
        pins = [{'id':e['src'], 'edge_id':e['id'], 'edge_revision':e['revision'],
                 'signature':result.get(e['src'], {}).get('signature', 'unavailable')} for e in deps[ident]]
        # Analysis scope changes require rechecking even though a Q need not be
        # answered before an analysis can start (no Q→A→E→C→Q circular wait).
        scope = [{'id':e['src'], 'edge_id':e['id'], 'edge_revision':e['revision'], 'sha256':_sha(by_id[e['src']])} for e in edges
                 if e['active'] and e['kind']=='analyzes' and e['dst']==ident and e['src'] in by_id]
        blockers = [p['id'] for p in pins if result.get(p['id'], {}).get('status') != 'completed']
        confirmation = cfg.get('confirmation'); authentic = False; changed = False
        if isinstance(confirmation, dict):
            row = c.execute('SELECT value FROM kv WHERE key=?', (KEY+'confirmation:'+str(confirmation.get('id')),)).fetchone()
            authentic = bool(row and json.loads(row[0]) == {'node_id':ident, 'confirmation':confirmation})
            for r in c.execute('SELECT snapshot FROM revisions WHERE object_id=? AND revision>?', (ident, confirmation.get('revision', 0))):
                if _sha(json.loads(r[0])) != confirmation.get('content_sha256'): changed = True; break
        parent = bool(children.get(ident))
        structural = (_kind(o)=='Q' and (bool(own[ident]) if parent else not any(e['kind']=='answers' for e in deps[ident])) or
                      _kind(o)=='C' and not any(e['kind'] in {'supports','limits','refutes'} for e in deps[ident]) or
                      _kind(o)=='E' and sum(e['kind']=='produces' for e in deps[ident]) != 1)
        stale = state == 'completed' and (not authentic or changed or confirmation.get('content_sha256') != _sha(o)
                    or confirmation.get('dependencies') != pins or confirmation.get('scope') != scope or structural)
        effective = 'stale' if stale else 'blocked' if state=='completed' and blockers else state
        signature = digest({'content':_sha(o), 'status':effective, 'confirmation':confirmation.get('id') if confirmation else None,
                            'dependencies':pins, 'scope':scope})
        result[ident] = {'status':effective, 'stored_status':state, 'signature':signature, 'dependencies':pins,
                         'blockers':blockers, 'scope':scope, 'confirmation':confirmation,
                         'can_complete':not blockers and not structural and bool(_body(o).strip())}
    return result


def _confirm(app, o, objects, edges, c, key, who, note, pins, answers=False):
    states = _states(app, objects, edges, c); value = states[o['id']]
    require(bool(note and isinstance(note, str) and len(note.strip())<=4000), '完成前请记录核对依据')
    require(_kind(o)!='Q' or answers is True, '请确认当前结论足以回答这个问题')
    require(pins == value['dependencies'], '依赖版本已改变，请重新核对', 'dependency_conflict', 409)
    require(value['can_complete'], '尚未满足完成条件：请核对正文、证据、结论与前置条件', 'dependencies_unmet', 409)
    confirmation = {'id':key, 'actor':who, 'at':now(), 'revision':o['revision'], 'content_sha256':_sha(o),
                    'dependencies':pins, 'scope':value['scope'], 'note':note.strip()}
    metadata = copy.deepcopy(o['metadata']); metadata.setdefault('graph_node', {}).update(status='completed', confirmation=confirmation)
    saved = app.store.save(o['id'], o['revision'], metadata=metadata, actor=who, reason='research.graph.confirm', merge=False, connection=c)
    c.execute('INSERT INTO kv VALUES(?,?)', (KEY+'confirmation:'+key, encoded({'node_id':o['id'], 'confirmation':confirmation})))
    return saved


def _link(app, c, src, dst, kind, rationale, who):
    s = app.store; existing = c.execute('SELECT id FROM relations WHERE src=? AND dst=? AND type=?', (src, dst, EDGE_TYPES[kind])).fetchone()
    cfg = {'kind':kind, 'rationale':rationale}
    if not existing:
        return _insert_relation(s,c,src,dst,EDGE_TYPES[kind],'candidate',{'research_graph':cfg},actor=who)
    old = _relation(s,c,existing[0]); require(old['type']=='contains' and not old['metadata'].get('research_graph'), '已有关系请读取后修改', 'conflict', 409)
    metadata = {**old['metadata'], 'graph_revision':old['revision']+1, 'research_graph':cfg}
    c.execute('UPDATE relations SET metadata=? WHERE id=?', (encoded(metadata), old['id']))
    return _history(s,c,_relation(s,c,old['id']),old,'attach research semantics',who)


def _validate(objects, edges, pid, previous_conflicts=None):
    kinds = {pid:'root', **{o['id']:_kind(o) for o in objects}}
    seen_results = set()
    pairs = {'contains':({'root','Q'},{'Q'}), 'analyzes':({'Q'},{'A'}), 'produces':({'A'},{'E'}),
             'supports':({'E'},{'C'}), 'limits':({'E'},{'C'}), 'refutes':({'E'},{'C'}),
             'answers':({'C'},{'Q'}), 'prerequisite':({'Q'},{'Q'})}
    for e in edges:
        if not e['active']: continue
        require(e['src'] in kinds and e['dst'] in kinds and e['src']!=e['dst'], '关系端点不可用或不属于当前项目', 'forbidden',403)
        a,b=pairs[e['kind']];require(kinds[e['src']] in a and kinds[e['dst']] in b, '关系类型与节点类型不匹配')
        if e['kind']=='produces':
            require(e['src'] not in seen_results, '每项分析只对应一项可版本化证据；请更新原证据或建立另一项分析')
            require(e['dst'] not in seen_results, '一项证据结果只能由一项分析产生')
            seen_results.update((e['src'],e['dst']))
    conflicts = _parent_conflicts(objects, edges)
    require(all(ids <= (previous_conflicts or {}).get(qid,set()) for qid,ids in conflicts.items()),
            '父问题只组织子问题，不能直接挂分析或回答结论；请先拆分并迁移已有工作', 'decomposition_required',409)
    _order(_dependencies(objects,edges))
    # Organizational hierarchy is separately acyclic. Semantic answer feedback
    # loops are allowed and never mistaken for a circular completion wait.
    _order({i:[e for e in edges if e['active'] and e['kind']=='contains' and e['dst']==i] for i in kinds})


def _withdraw(app, c, edge, reason, who):
    before = _relation(app.store,c,edge['id'])
    metadata = {**before['metadata'], 'graph_revision':before['revision']+1,
                'research_graph':{'kind':edge['kind'], 'rationale':reason}}
    c.execute('UPDATE relations SET status=?,metadata=? WHERE id=?', ('withdrawn',encoded(metadata),edge['id']))
    return _history(app.store,c,_relation(app.store,c,edge['id']),before,reason,who)


def _organize(app, project, parent, title, body, c, who, status='active'):
    """Atomic split: retain A/E/C identities, content and past scientific decisions.

    The new question's scope and changed links require fresh confirmation. This
    operation never infers a scientific answer from moving existing text.
    """
    require(_kind(parent)=='Q', '只能拆分研究问题')
    require(isinstance(title,str) and 0<len(title.strip())<=500 and isinstance(body,str) and len(body.encode())<=128*1024,
            '子问题需要具体标题，正文最多128 KiB')
    require(isinstance(status,str) and status in STATUSES-{'completed'},'拆分后需要重新核对完成，不能直接标为完成')
    pid=project['id'];root=project['metadata'].get('research_root_question_id')
    objects=[o for o in _objects(app,pid,c) if o['id']!=root];edges=_edges(app,pid,objects,c)
    children,own=_question_structure(objects,edges);previous=_parent_conflicts(objects,edges)
    require(own[parent['id']], '没有需要迁移的分析或结论，可直接新建子问题', 'not_ready',409)
    routes=own[parent['id']]; reason='拆分研究问题：原有 AEC 移入子问题，保留对象与关系历史'
    for e in routes:_withdraw(app,c,e,reason,who)
    child=create_question(app.store,c,pid,title,parent=parent['id'],actor=who,
                          origin={'kind':'question_organization','question_id':parent['id'],'revision':parent['revision']})
    origin={'kind':'question_organization','question_id':parent['id'],'revision':parent['revision'],'part':'Q'}
    child=app.store.save(child['id'],child['revision'],content={**child['content'],'qaec':{**child['content']['qaec'],'Q':body}},
                         metadata={**child['metadata'],'graph_node':{'kind':'Q','status':status,'origin':origin}},
                         actor=who,reason='research.graph.organize',merge=False,connection=c)
    for e in routes:
        src,dst=(child['id'],e['dst']) if e['kind']=='analyzes' else (e['src'],child['id'])
        _link(app,c,src,dst,e['kind'],reason+'；'+e.get('rationale',''),who)
        if e['kind']=='answers':
            conclusion=app.store.get(e['src'],connection=c);cfg=copy.deepcopy(conclusion['metadata'])
            value=cfg.setdefault('graph_node',{})
            if value.get('status')=='completed':
                value['status']='review'
                app.store.save(conclusion['id'],conclusion['revision'],metadata=cfg,actor=who,reason=reason,merge=False,connection=c)
    for e in children[parent['id']]:
        _link(app,c,e['dst'],child['id'],'prerequisite','综合子问题依据前面的子问题回答',who)
    for e in edges:
        if e['active'] and e['kind']=='prerequisite' and e['dst']==parent['id'] and e['src'] in {x['dst'] for x in children[parent['id']]}:
            _withdraw(app,c,e,'父问题的子问题完成条件由 contains 统一记录；综合前置关系移入新子问题',who)
    current=app.store.get(parent['id'],connection=c);metadata=copy.deepcopy(current['metadata'])
    cfg=metadata.setdefault('graph_node',{});cfg.setdefault('kind','Q')
    if cfg.get('status')=='completed':cfg['status']='active'
    app.store.save(current['id'],current['revision'],metadata=metadata,actor=who,reason=reason,merge=False,connection=c)
    objects=[o for o in _objects(app,pid,c) if o['id']!=root]
    _validate(objects,_edges(app,pid,objects,c),pid,previous)
    return child


def _display_labels(objects, edges, questions):
    """Question-scoped display names; scientific identities and versions stay intact.

    Dots belong to Q decomposition; a hyphen disambiguates parallel analyses
    (A1-1 versus A1.1). Evidence inherits its producing analysis's suffix.
    """
    ordered = sorted(objects, key=lambda o:(o['created_at'], o['id']))
    active = [e for e in edges if e['active']]
    rank = {ident:i for i,ident in enumerate(questions)}
    owners = {}; labels = dict(questions)
    def choose(o, candidates):
        candidates = sorted(set(candidates) & questions.keys(), key=lambda ident:rank[ident])
        origin = (o['metadata'].get('graph_node',{}).get('origin') or {}).get('question_id')
        return origin if origin in candidates else candidates[0] if candidates else None
    def name_group(kind):
        groups = {}
        for o in ordered:
            if _kind(o)==kind: groups.setdefault(owners.get(o['id']), []).append(o['id'])
        for owner, ids in groups.items():
            for i, ident in enumerate(ids, 1):
                labels[ident] = kind + questions[owner][1:] + ('-'+str(i) if len(ids)>1 else '') if owner else kind+'?'
    for o in ordered:
        if _kind(o)=='A': owners[o['id']] = choose(o, [e['src'] for e in active if e['kind']=='analyzes' and e['dst']==o['id']])
    name_group('A')
    for o in ordered:
        if _kind(o)!='E': continue
        source = next((e['src'] for e in active if e['kind']=='produces' and e['dst']==o['id']), None)
        owners[o['id']] = owners.get(source)
        labels[o['id']] = 'E'+labels[source][1:] if source in labels else 'E?'
    for o in ordered:
        if _kind(o)!='C': continue
        targets = [e['dst'] for e in active if e['kind']=='answers' and e['src']==o['id']]
        if not targets:
            evidence_owners = {owners.get(e['src']) for e in active if e['kind'] in {'supports','limits','refutes'} and e['dst']==o['id']}
            if len(evidence_owners)==1: targets = list(evidence_owners)
        owners[o['id']] = choose(o, targets)
    name_group('C')
    return labels, owners


def read(app, project, c):
    pid=project['id']; legacy_root=project['metadata'].get('research_root_question_id')
    objects=[o for o in _objects(app,pid,c) if o['id']!=legacy_root]
    edges=_edges(app,pid,objects,c)
    # Existing question creation/adoption still uses the shared question path;
    # project containment is projected from the same persisted hierarchy.
    for o in objects:
        if _kind(o)!='Q' or any(e['kind']=='contains' and e['active'] and e['dst']==o['id'] for e in edges): continue
        parent=o['metadata'].get('parent_question_id') if not any(e['kind']=='contains' and e['dst']==o['id'] for e in edges) else None
        parent=pid if not parent or parent==legacy_root else parent
        if parent not in {pid,*[x['id'] for x in objects]}:parent=pid
        edges.append({'id':'hierarchy:'+o['id'],'src':parent,'dst':o['id'],'kind':'contains','type':'contains','revision':1,'status':'confirmed','active':True,'rationale':'问题层级','virtual':True})
    states=_states(app,objects,edges,c)
    children, own = _question_structure(objects, edges)
    numbered=[]
    for o in objects:
        if _kind(o)!='Q':continue
        parents=[e['src'] for e in edges if e['active'] and e['kind']=='contains' and e['dst']==o['id'] and e['src']!=pid]
        primary=o['metadata'].get('parent_question_id')
        numbered.append({**o,'metadata':{**o['metadata'],'parent_question_id':primary if primary in parents else parents[0] if parents else None}})
    numbers={q['id']:q['number'] for q in numbered_questions(numbered)}
    labels, owners = _display_labels(objects, edges, numbers)
    question_order = {ident:i for i,ident in enumerate(numbers)}
    nodes=[]
    for o in sorted(objects,key=lambda o:(o['created_at'],o['id'])):
        kind=_kind(o)
        nodes.append({'id':o['id'],'kind':kind,'label':labels[o['id']], 'owner_question_id':o['id'] if kind=='Q' else owners.get(o['id']),
                      'question_role':('parent' if children[o['id']] else 'leaf') if kind=='Q' else None,
                      'child_question_ids':sorted([e['dst'] for e in children.get(o['id'],[])],key=lambda ident:question_order[ident]),
                      'needs_organization':bool(children.get(o['id']) and own.get(o['id'])),
                      'title':o['title'],'body':_body(o),'revision':o['revision'],'sha256':digest(o),
                      'origin':o['metadata'].get('graph_node',{}).get('origin'),'source_refs':o['content'].get('source_refs',[]),**states[o['id']]})
    by_id={n['id']:n for n in nodes}
    for e in edges:
        a,b=by_id.get(e['src']),by_id.get(e['dst']);kind=e['kind']
        done=bool(a and b and (a['status']=='completed' if kind in {'prerequisite','answers'} else b['status']=='completed'))
        if kind in {'supports','limits','refutes','produces'}:done=done and a['status']=='completed'
        e.update(label=LABELS[kind],fulfilled=done and e['active'])
    root={'id':pid,'kind':'root','label':'Q','title':project['title'],'body':project['content'].get('background','') or project['content'].get('description',''),
          'revision':project['revision'],'status':'active' if nodes else 'not_started','stored_status':'active',
          'legacy_question_id':legacy_root,'dependencies':[],'blockers':[],'confirmation':None,'can_complete':False}
    return {'version':2,'project':{'id':pid,'title':project['title'],'revision':project['revision']},
            'nodes':[root,*nodes],'edges':edges,'migrated':project['metadata'].get('research_graph_version')==2,
            'source_refs':[{'id':o['id'],'revision':o['revision']} for o in _objects(app,pid,c)],
            'legacy_available':any(any(o['content'].get('qaec',{}).get(p,'').strip() for p in ('A','E','C')) for o in objects if _kind(o)=='Q')}


def _migrate(app, project, c, who, key):
    require(project['metadata'].get('research_graph_version')!=2,'已有独立研究图，不会重复导入', 'conflict',409)
    pid=project['id'];old=_objects(app,pid,c);source_states=project_states([o for o in old if _kind(o)=='Q'],app.store,c)
    root=project['metadata'].get('research_root_question_id'); old=[o for o in old if o['id']!=root]
    mapping={};desired={};origins={}
    for q in old:
        if _kind(q)!='Q':continue
        for part in ('Q','A','E','C'):
            text=q['content'].get('qaec',{}).get(part,'');source=source_states[identity(q['id'],part)]
            if part!='Q' and not text.strip():continue
            origin={'question_id':q['id'],'revision':q['revision'],'part':part,'confirmation':source.get('confirmation')}
            status=source['status']; cfg={'kind':part,'status':'review' if status in {'completed','stale','blocked','unmarked'} else status,'origin':origin}
            if part=='Q':
                node=app.store.save(q['id'],q['revision'],metadata={**q['metadata'],'graph_node':cfg},actor=who,reason='research.graph.migrate',merge=False,connection=c)
            else:
                node=app.store.create('concept',source['title'] or q['title']+' · '+part,pid,{'text':text},
                                      {'research_role':ROLE_NODE,'graph_node':cfg},actor=who,connection=c)
            mapping[identity(q['id'],part)]=node['id'];desired[node['id']]=status;origins[node['id']]=origin
    def link(a,b,kind,reason='从原有研究记录迁移'):
        if a and b and a!=b:_link(app,c,a,b,kind,reason,who)
    for q in old:
        if _kind(q)!='Q':continue
        ids={p:mapping.get(identity(q['id'],p)) for p in ('Q','A','E','C')}
        if ids['A']:link(ids['Q'],ids['A'],'analyzes')
        if ids['A'] and ids['E']:link(ids['A'],ids['E'],'produces')
        if ids['E'] and ids['C']:link(ids['E'],ids['C'],'supports','原记录的证据与结论关联；支持范围见正文和核对记录')
        if ids['C']:link(ids['C'],ids['Q'],'answers')
        for part in ('Q','C'):
            for dep in source_states[identity(q['id'],part)]['dependencies']:
                src=mapping.get(dep['id']);dst=ids[part]
                if not src or not dst or dep.get('builtin'):continue
                if part=='Q' and dep['part']=='Q':link(src,dst,'prerequisite')
                elif part=='C' and dep['part']=='E':
                    existing=c.execute('SELECT 1 FROM relations WHERE src=? AND dst=?',(src,dst)).fetchone()
                    if not existing:link(src,dst,dep['kind'] if dep['kind'] in {'supports','limits','refutes'} else 'supports')
    objects=[o for o in _objects(app,pid,c) if o['id']!=root];edges=_edges(app,pid,objects,c)
    organization_questions={}
    for parent_id in list(_parent_conflicts(objects,edges)):
        parent=app.store.get(parent_id,connection=c)
        child=_organize(app,project,parent,parent['title'],_body(parent),c,who)
        organization_questions[parent_id]=child['id']
        desired[child['id']]=desired.get(parent_id,'active');origins[child['id']]=origins[parent_id]
    objects=[o for o in _objects(app,pid,c) if o['id']!=root];edges=_edges(app,pid,objects,c)
    _validate(objects,edges,pid)
    for ident in _order(_dependencies(objects,edges)):
        if desired.get(ident)!='completed':continue
        objects=[o for o in _objects(app,pid,c) if o['id']!=root];o=next(o for o in objects if o['id']==ident)
        states=_states(app,objects,edges,c);previous=origins[ident].get('confirmation')
        if states[ident]['can_complete'] and previous:
            _confirm(app,o,objects,edges,c,key+':'+ident,who,'迁移已核对记录：'+previous['note'],states[ident]['dependencies'],True)
    return {'mapping':mapping, 'organization_questions':organization_questions}


def dispatch(app,data,scope=None,principal=None):
    action=data.get('action');allowed={'workbench.graph.read','workbench.graph.history','workbench.graph.migrate','workbench.graph.question.organize','workbench.graph.node.create','workbench.graph.node.save','workbench.graph.edge.create','workbench.graph.edge.save'}
    require(action in allowed,'未知研究图操作')
    read_only=action in {'workbench.graph.read','workbench.graph.history'}
    project=_project(app,data.get('project_id'),scope,principal,not read_only)
    if read_only:
        with app.store.read_snapshot() as c:
            project=app.store.get(project['id'],connection=c);view=read(app,project,c)
            if action.endswith('.history'):
                ident=data.get('id');require(ident in {n['id'] for n in view['nodes']},'节点不属于当前项目','forbidden',403)
                before=data.get('before_revision',2**63-1);require(type(before) is int and before>0,'历史游标无效')
                rows=c.execute('SELECT * FROM revisions WHERE object_id=? AND revision<? ORDER BY revision DESC LIMIT 31',(ident,before)).fetchall()
                return {'versions':[{'revision':r['revision'],'actor':r['actor'],'created_at':r['created_at'],'snapshot':json.loads(r['snapshot'])} for r in rows[:30]],'has_more':len(rows)>30}
            return view
    fields={'action','project_id','request_key','expected_project_revision','id','kind','title','body','status','expected_revision','confirmation_note','expected_dependencies','answers_question','src','dst','rationale','active','expected_sources','parent_id','relation_kind','source_refs'}
    require(set(data)<=fields,'研究图操作含未知字段')
    key=data.get('request_key');require(isinstance(key,str) and 0<len(key)<=160,'需要稳定请求标识')
    fingerprint=digest({'data':data,'scope':sorted(scope) if scope is not None else None,'principal':principal})
    from .project_management import actor
    who=actor(principal or {'kind':'local_operator'})
    with app.store.transaction() as c:
        _project(app,project['id'],scope,principal,True)
        row=c.execute('SELECT value FROM kv WHERE key=?',(KEY+'request:'+key,)).fetchone()
        if row:
            previous=json.loads(row[0]);require(previous['fingerprint']==fingerprint,'同一请求内容已改变','idempotency_conflict',409)
            return {**previous['result'],'replayed':True}
        project=app.store.get(project['id'],connection=c);pid=project['id']
        require(type(data.get('expected_project_revision')) is int and data['expected_project_revision']==project['revision'],'研究图已有更新；草稿已保留，请刷新后核对','conflict',409)
        root=project['metadata'].get('research_root_question_id');objects=[o for o in _objects(app,pid,c) if o['id']!=root]
        edges=_edges(app,pid,objects,c);by_id={o['id']:o for o in objects};result={}
        previous_conflicts=_parent_conflicts(objects,edges)
        if action=='workbench.graph.migrate':
            expected=[{'id':o['id'],'revision':o['revision']} for o in _objects(app,pid,c)]
            require(data.get('expected_sources')==expected,'原有研究内容已更新，请重新核对迁移','conflict',409)
            result=_migrate(app,project,c,who,key)
        elif action=='workbench.graph.question.organize':
            parent=by_id.get(data.get('id'))
            require(parent is not None and _kind(parent)=='Q','问题不属于当前项目','forbidden',403)
            require(type(data.get('expected_revision')) is int and data['expected_revision']==parent['revision'],
                    '研究问题已有更新，未迁移任何内容','conflict',409)
            child=_organize(app,project,parent,data.get('title'),data.get('body',_body(parent)),c,who,data.get('status','active'))
            result={'node_id':child['id'],'organized_parent_id':parent['id']}
        elif '.node.' in action:
            title=data.get('title');body=data.get('body');status=data.get('status','not_started')
            require(isinstance(title,str) and 0<len(title.strip())<=500 and isinstance(body,str) and len(body.encode())<=128*1024 and isinstance(status,str) and status in STATUSES,'节点需要标题、正文与有效状态')
            refs=data.get('source_refs')
            if refs is not None:
                require(isinstance(refs,list) and len(refs)<=16,'最多登记16项固定来源')
                refs=copy.deepcopy(refs)
                for ref in refs:
                    require(isinstance(ref,dict) and set(ref)=={'id','revision'} and isinstance(ref['id'],str) and type(ref['revision']) is int,'来源需要稳定身份和准确版本')
                    app.store.assert_source_access(c,pid,ref['id'])
                    source=app.store.get(ref['id'],ref['revision'],c);ref['sha256']=digest(source)
            if action.endswith('.create'):
                kind=data.get('kind');require(isinstance(kind,str) and kind in {'Q','A','E','C'} and status!='completed','新节点需先保存，再核对完成')
                if kind=='Q':
                    parent=data.get('parent_id') if data.get('relation_kind')=='contains' and data.get('parent_id') in by_id else None
                    o=create_question(app.store,c,pid,title,parent=parent,actor=who);content={**o['content'],'qaec':{**o['content']['qaec'],'Q':body},**({'source_refs':refs} if refs is not None else {})}
                    o=app.store.save(o['id'],o['revision'],content=content,metadata={**o['metadata'],'graph_node':{'kind':'Q','status':status}},actor=who,merge=False,connection=c)
                else:o=app.store.create('concept',title,pid,{'text':body,**({'source_refs':refs} if refs is not None else {})},{'research_role':ROLE_NODE,'graph_node':{'kind':kind,'status':status}},actor=who,connection=c)
                if data.get('parent_id'):
                    parent=data['parent_id'];relation=data.get('relation_kind')
                    require(parent in {pid,*by_id} and isinstance(relation,str) and relation in EDGE_TYPES,'父节点或关系无效','forbidden',403)
                    _link(app,c,parent,o['id'],relation,data.get('rationale') or '新建关联研究节点',who)
                    _validate([*objects,o],_edges(app,pid,[*objects,o],c),pid,previous_conflicts)
            else:
                o=by_id.get(data.get('id'));require(o is not None,'节点不属于当前项目','forbidden',403)
                require(type(data.get('expected_revision')) is int and o['revision']==data['expected_revision'],'节点已有更新；请重新核对','conflict',409)
                content=copy.deepcopy(o['content']);metadata=copy.deepcopy(o['metadata'])
                if refs is not None:content['source_refs']=refs
                if _kind(o)=='Q':content.setdefault('qaec',{})['Q']=body
                else:content['text']=body
                metadata.setdefault('graph_node',{}).update(kind=_kind(o),status='review' if status=='completed' else status)
                o=app.store.save(o['id'],o['revision'],title=title,content=content,metadata=metadata,actor=who,merge=False,reason=action,connection=c)
                if status=='completed':
                    require((principal or {}).get('actor_kind')!='agent' and (principal or {}).get('kind')!='agent','Agent可提出判断，不能自行确认科学完成','forbidden',403)
                    objects=[o if x['id']==o['id'] else x for x in objects]
                    o=_confirm(app,o,objects,edges,c,key,who,data.get('confirmation_note'),data.get('expected_dependencies'),data.get('answers_question'))
            result={'node_id':o['id']}
        else:
            if action.endswith('.create'):
                src,dst,kind=data.get('src'),data.get('dst'),data.get('kind')
                require(src in {pid,*by_id} and dst in by_id and isinstance(kind,str) and kind in EDGE_TYPES,'关系端点或类型不可用','forbidden',403)
                rationale=data.get('rationale','');require(isinstance(rationale,str) and 0<len(rationale.strip())<=4000,'请说明这条关系的含义或依据')
                e=_link(app,c,src,dst,kind,rationale,who)
            else:
                old=next((e for e in edges if e['id']==data.get('id')),None);require(old is not None,'关系不属于当前项目','forbidden',403)
                require(type(data.get('expected_revision')) is int and data['expected_revision']==old['revision'],'关系已有更新','conflict',409)
                active=data.get('active');rationale=data.get('rationale')
                require(type(active) is bool and isinstance(rationale,str) and 0<len(rationale.strip())<=4000,'需要关系状态与依据')
                before=_relation(app.store,c,old['id']);metadata={**before['metadata'],'graph_revision':before['revision']+1,'research_graph':{'kind':old['kind'],'rationale':rationale}}
                c.execute('UPDATE relations SET status=?,metadata=?,source_revision=?,target_revision=? WHERE id=?',('candidate' if active else 'withdrawn',encoded(metadata),app.store.get(old['src'],connection=c)['revision'],by_id[old['dst']]['revision'],old['id']))
                e=_history(app.store,c,_relation(app.store,c,old['id']),before,action,who)
            objects=[o for o in _objects(app,pid,c) if o['id']!=root];_validate(objects,_edges(app,pid,objects,c),pid,previous_conflicts);result={'edge_id':e['id']}
        from .compatibility import require_features
        require_features(c,[FEATURE,LEAF_FEATURE])
        project=app.store.get(pid,connection=c)
        project=app.store.save(pid,project['revision'],metadata={**project['metadata'],'research_graph_version':2,'research_graph_question_model':'leaf_v1'},actor=who,reason=action,merge=False,connection=c)
        result={**result,'graph':read(app,project,c)}
        c.execute('INSERT INTO kv VALUES(?,?)',(KEY+'request:'+key,encoded({'fingerprint':fingerprint,'result':result})))
        return result
