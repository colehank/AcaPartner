"""Read-only QAEC/iteration projection over existing Store revisions.

Organizing paths are explicitly distinct from revision and adoption records.
No graph authority, synthetic history, model call, or scientific completion score.
"""
from __future__ import annotations
import json
from .store import Problem, digest, require
from .workbench_research import ROLE, numbered_questions
from .desk_w1a import _project

PARTS = ('Q', 'A', 'E', 'C')


def excerpt(text, limit=220):
    text = text.strip() if isinstance(text, str) else ''
    first = text.split('\n\n')[0]
    return first[:limit] + ('…' if len(first) > limit else '')


def _question(app, project_id, ident, c):
    q = app.store.get(ident, connection=c)
    require(q['project_id'] == project_id and not q['archived'] and q['metadata'].get('research_role') == ROLE,
            '研究问题不属于当前项目或已归档', 'forbidden', 403)
    return q


def _origin(app, project_id, q, part, revision, text, c):
    """Only an immutable adoption decision can label a field as adopted."""
    origin = q['metadata'].get('research_work_adoptions', {}).get(part)
    if not isinstance(origin, dict): return None
    task_id, change_id = origin.get('task_id'), origin.get('change_id')
    if not isinstance(task_id, str) or not isinstance(change_id, str): return None
    for prefix in ('research_work:', 'research_partner:work:'):
        row = c.execute('SELECT value FROM kv WHERE key=?', (prefix+'adopted:'+task_id+':'+change_id,)).fetchone()
        if not row: continue
        decision = json.loads(row[0])
        if (decision.get('question_id') != q['id'] or decision.get('question_revision') != revision
                or decision.get('part') != part or decision.get('adopted_text') != text): continue
        ref = decision.get('proposal_ref')
        try:
            task = app.store.task(task_id, c)
            require(task['project_id'] == project_id, '来源任务不属于当前项目', 'forbidden', 403)
            app.store.assert_material_readiness(c, task['payload'])
            proposal = app.store.get(ref['id'], ref['revision'], c)
            require(digest(proposal) == ref['sha256'] and task['result'].get('object_id') == ref['id']
                    and task['result'].get('revision') == ref['revision'], '采用来源版本不匹配', 'integrity', 409)
            app.store.assert_source_access(c, project_id, ref['id'])
            # Continuing conversations can carry earlier, subsequently withdrawn sources.
            snapshot = task['payload'].get('context', {}).get('partner', {})
            app.store.assert_material_readiness(c, {**task['payload'], 'context': {'materials': snapshot.get('conversation_sources', [])}})
            refs = []
            for source in decision.get('source_refs', []):
                app.store.assert_source_access(c, project_id, source['id'])
                obj = app.store.get(source['id'], source['revision'], c)
                refs.append({'id': obj['id'], 'revision': obj['revision'], 'title': obj['title']})
            return {'task_id': task_id, 'proposal_ref': ref, 'source_refs': refs, 'available': True}
        except (Problem, KeyError, TypeError):
            return {'available': False}
    return None


def _history(app, project_id, q, c, before=None, limit=100):
    # The extra older row is the comparison base, not an extra visible version.
    rows = c.execute('SELECT revision,snapshot,actor,reason,created_at FROM revisions WHERE object_id=? AND revision<? ORDER BY revision DESC LIMIT ?',
                     (q['id'], before or q['revision']+1, limit+1)).fetchall()
    versions = {p: [] for p in PARTS}
    for index, row in enumerate(rows[:limit]):
        obj = json.loads(row['snapshot'])
        old = json.loads(rows[index+1]['snapshot']) if index+1 < len(rows) else None
        require(obj.get('id') == q['id'] and obj.get('project_id') == project_id, '历史问题的项目身份不同', 'integrity', 409)
        if obj.get('metadata', {}).get('research_role') != ROLE: continue
        # A bounded page must not invent an initial change at its oldest boundary.
        if old is None and row['revision'] != 1: continue
        if old and old.get('metadata', {}).get('research_role') != ROLE: old = None
        object_sha = None
        current, previous = obj['content'].get('qaec', {}), old['content'].get('qaec', {}) if old else {}
        for part in PARTS:
            value, prior = current.get(part, ''), previous.get(part, '')
            require(isinstance(value, str) and isinstance(prior, str), '历史QAEC不是文字', 'integrity', 409)
            from .research_nodes import config
            changed = (value != prior or part == 'Q' and obj['title'] != (old['title'] if old else '')
                       or part != 'Q' and config(obj,part).get('title','') != (config(old,part).get('title','') if old else ''))
            if not changed: continue
            origin = _origin(app, project_id, obj, part, row['revision'], value, c)
            if object_sha is None: object_sha = digest(obj)
            versions[part].append({'id': q['id']+':'+part+':r'+str(row['revision']), 'part': part,
                'revision': row['revision'], 'sha256': object_sha, 'title': obj['title'] if part=='Q' else config(obj,part).get('title',''), 'excerpt': excerpt(value),
                'empty': not bool(value.strip()), 'actor': row['actor'], 'created_at': row['created_at'],
                'change_kind': 'adopted' if origin else 'restored' if row['reason'].startswith('restore:') else 'created' if row['revision']==1 else 'edited',
                'origin': origin})
    oldest = rows[min(len(rows),limit)-1]['revision'] if rows else None
    more = bool(oldest and oldest > 1)
    return {'versions': versions, 'next_before_revision': oldest if more else None,
            'history_complete': not more, 'scanned_revisions': min(len(rows),limit)}


def dispatch(app, data, scope=None, principal=None):
    action = data.get('action')
    allowed = {'action', 'project_id'} | ({'question_id', 'before_revision'} if action=='workbench.progress.history' else set())
    require(action in {'workbench.progress.read','workbench.progress.history'} and set(data) <= allowed,
            '研究进展读取字段不支持')
    project = _project(app, data.get('project_id'), scope, principal)
    with app.store.read_snapshot() as c:
        project = app.store.get(project['id'], connection=c)
        if action.endswith('.history'):
            q = _question(app, project['id'], data.get('question_id'), c)
            before = data.get('before_revision')
            require(before is None or type(before) is int and before > 0, '历史游标无效')
            return {'project_id': project['id'], 'question_id': q['id'], **_history(app, project['id'], q, c, before, 40)}
        rows = c.execute("SELECT * FROM objects WHERE project_id=? AND archived=0 AND json_extract(metadata,'$.research_role')=?", (project['id'],ROLE)).fetchall()
        require(len(rows)<=250, '研究进展图目前支持250个可见问题，请缩小项目范围', 'context_limit', 413)
        from .research_nodes import project_states, identity
        objects = [app.store.unpack(row) for row in rows]
        states = project_states(objects, app.store, c)
        root_id = project['metadata'].get('research_root_question_id')
        result = []
        for q in numbered_questions(objects, root_id):
            history = _history(app, project['id'], q, c)
            parts = {}
            for part in PARTS:
                changes = history['versions'][part]
                parts[part] = {'empty': not bool(q['content']['qaec'].get(part, '').strip()),
                    'node':states[identity(q['id'],part)],
                    'excerpt': excerpt(q['content']['qaec'].get(part, '')), 'versions': changes[:3],
                    'last_changed_revision': changes[0]['revision'] if changes else None,
                    'older_versions_available': len(changes)>3 or not history['history_complete']}
            evidence, conclusion = parts['E']['last_changed_revision'], parts['C']['last_changed_revision']
            result.append({'id':q['id'], 'title':q['title'], 'number':q['number'], 'parent_id':q['tree_parent_id'],
                'revision':q['revision'], 'sha256':digest(q), 'status':q['content'].get('research_status','open'), 'is_root':q['id']==root_id,
                'updated_at':q['updated_at'], 'parts':parts,
                'review_hint': bool(evidence and conclusion and evidence>conclusion and not parts['C']['empty']),
                'history_complete':history['history_complete']})
        latest = sorted([{'question_id':q['id'],'number':q['number'], **v} for q in result for part in PARTS
                         for v in q['parts'][part]['versions']], key=lambda v:(v['created_at'],v['revision']), reverse=True)
        return {'version':1, 'project':{'id':project['id'],'title':project['title'],'revision':project['revision']},
            'description':project['content'].get('description',''), 'background_excerpt':excerpt(project['content'].get('background','')),
            'root_question_id':root_id if any(q['id']==root_id for q in result) else None,
            'questions':result, 'recent_changes':latest[:8],
            'semantics':{'qaec':'organization','revision':'saved_field_change','scientific_approval':False}}
