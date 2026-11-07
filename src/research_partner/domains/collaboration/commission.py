"""Finite, source-preserving schemas for research commissions.

Validation does not render, execute code, or grant scientific acceptance. Target
edits are stable-ID patches: omission never silently deletes a user's object.
"""
from __future__ import annotations

import copy
import math
import re
from research_partner.storage.store import Problem, require

OUTPUT_KINDS = frozenset({'report', 'note', 'paper', 'diagram', 'poster', 'slides'})
COMMON = {'title', 'kind', 'blocks', 'rationale', 'claims', 'interpretation', 'questions',
          'source_ref', 'source_refs', 'citations', 'components', 'graph_proposal'}
PROSE = {'markdown', 'latex', 'bibtex', 'bibtex_asset', 'latex_assets', 'citation_keys'}
LAYOUT = {'diagram': {'width', 'height', 'nodes', 'edges'},
          'poster': {'units', 'pages'}, 'slides': {'units', 'pages'}}
KEYED = {'blocks', 'nodes', 'edges', 'pages', 'objects'}


def candidate_input_snapshot(store, task, provenance):
    """Resolve inputs from a verified native prompt, never from consumed flags.

    Old native prompts contained complete guidance records without event IDs.
    Each must match one immutable task event exactly. Decisions also bind their
    historical answer text, so a later answer cannot be attributed retroactively.
    Missing legacy provenance represents an empty snapshot only; the runtime
    compares this with current inputs before allowing any publication.
    """
    empty={'decisions':[], 'guidance':[]}
    if provenance is None:return empty
    require(isinstance(provenance,dict),'候选输入来源无效','candidate_checkpoint_invalid',409)
    value=provenance.get('coordinator_input')
    if value is None:return empty
    if isinstance(value,list):messages=value;decisions=[];declared=None
    else:
        require(isinstance(value,dict),'候选指导来源无效','candidate_checkpoint_invalid',409)
        messages=value.get('messages',[]);decisions=value.get('answered_decisions',[]);declared=value.get('input_snapshot')
    require(isinstance(messages,list) and isinstance(decisions,list),'候选输入集合无效','candidate_checkpoint_invalid',409)
    with store.connect() as connection:
        events=[store.unpack(row) for row in connection.execute("SELECT * FROM events WHERE object_id=? AND kind='task.guidance' ORDER BY seq",(task['id'],))]
        seqs=[];refs=[]
        for message in messages:
            require(isinstance(message,dict),'候选指导记录无效','candidate_checkpoint_invalid',409)
            matches=[event for event in events if (message==event['data'] if 'seq' not in message else message=={'seq':event['seq'],**event['data']})]
            require(len(matches)==1,'候选指导不能唯一绑定原始事件','candidate_checkpoint_invalid',409)
            seqs.append(matches[0]['seq'])
        for decision in decisions:
            require(isinstance(decision,dict) and isinstance(decision.get('id'),str) and type(decision.get('revision')) is int,'候选裁决身份无效','candidate_checkpoint_invalid',409)
            obj=store.get(decision['id'],decision['revision'],connection);content=obj['content']
            from research_partner.domains.collaboration.questions import decision_projection
            expected=decision_projection(obj)
            require(obj['kind']=='question' and obj['project_id']==task['project_id'] and (not content.get('task_id') or content['task_id']==task['id'])
                    and expected==decision,'候选裁决与实际历史答复不符','candidate_checkpoint_invalid',409)
            refs.append({'id':obj['id'],'revision':obj['revision']})
    require(len(set(seqs))==len(seqs) and len({ref['id'] for ref in refs})==len(refs),'候选输入重复','candidate_checkpoint_invalid',409)
    snapshot={'decisions':sorted(refs,key=lambda ref:ref['id']),'guidance':sorted(seqs)}
    require(declared is None or declared==snapshot,'候选声明的输入与真实提示内容不符','candidate_checkpoint_invalid',409)
    return snapshot


def invalid(message, path='candidate'):
    raise Problem('委托成果结构无效：' + message, 'invalid_model_output', 422, {'path': path})


def infer_output(request: str) -> str:
    """Small purpose heuristic; an explicit output or target always wins upstream."""
    text = str(request).strip().lower()
    verbs = list(re.finditer(r'生成|制作|画出|绘制|输出|撰写|写一|做一|\b(?:create|make|draw|produce|write|prepare|generate)\b', text[:400]))
    if verbs:
        text = text[verbs[-1].start():]
    patterns = {
        'slides': r'幻灯片|演示文稿|\bpptx?\b|\bslides?\b|\bslide deck\b',
        'poster': r'海报|\bposter\b',
        'diagram': r'概念图|流程图|机制图|关系图|结构图|示意图|\bdiagram\b|\bflowchart\b|\bconcept map\b',
        'paper': r'论文(?:草稿|初稿|正文|稿件)?|\bmanuscript\b|\bpaper draft\b',
        'note': r'笔记|\bresearch note\b',
        'report': r'报告|综述|\breport\b|\breview\b',
    }
    matches = []
    for kind, pattern in patterns.items():
        for match in re.finditer(pattern, text[:400]):
            prefix = text[max(0, match.start() - 20):match.start()]
            if re.search(r'(?:不要|不做|无需|不是|并非|非|not|no)\s*(?:生成|制作|写|a|an)?\s*$', prefix): continue
            matches.append((match.start(), kind))
    if not matches: return 'report'
    # Format nouns are more specific than source words such as “综述” in
    # “制作综述概念图”. A plain mention of a paper is not a manuscript commission.
    if not verbs: matches = [item for item in matches if item[1] != 'paper']
    visual = [item for item in matches if item[1] in {'diagram', 'poster', 'slides'}]
    return min(visual or matches)[1] if matches else 'report'


def candidate_schema(kind: str, task=None) -> str:
    if kind=='manuscript_revision':
        from research_partner.domains.manuscripts.revision import schema
        return schema(task)
    if kind=='project_management':
        from research_partner.domains.workspace.management import schema
        return schema(task)
    if kind not in OUTPUT_KINDS: invalid('不支持请求的成果类型', 'kind')
    common = (
        'Return one JSON object, with title (nonempty string), kind="' + kind + '", '
        'blocks:[{id,kind,text}] for readable prose/rationale, rationale (string), '
        'claims:[{text,evidence_ids:[source IDs],limitation}], interpretation (string), '
        'questions:[{id,question,scope,blocking,background,options:[{id,label,consequence}],recommendation,source_refs?}]. '
        'Every new question requires a stable ASCII id, explicit scope="current_task"|"followup"|"optional", evidence background, 2–8 concrete options with consequences, and a recommendation with limits. '
        'Use scope="current_task",blocking=true ONLY for an answer required before completing this already authorized artifact. '
        'Future scientific designs/permissions are scope="followup",blocking=false; optional feedback is scope="optional",blocking=false. Never make an unrun future experiment block the current bounded report. Questions and answers grant no tool, scientific or spending permission. '
        'Tool evidence IDs task-context and materials are task provenance, never database object IDs. '
        'Use only catalog object_id and its real revision in source_ref/source_refs/citations/questions.source_refs; '
        'omit object pointers for context-only questions: the coordinator binds their task/candidate provenance. '
        'Optional source_ref:{id,revision,block_id?}, source_refs:[{id,revision}], '
        'citations:[{id,revision}] (literature only), components:[{id,revision}]. '
        'Use actual readable source identities and exact revisions, never invented references. '
        'Do not emit code, script assets, URLs for images, approval flags, or arbitrary schema fields. '
        'Every stable id (blocks, nodes, edges, pages and page objects) must match '
        '[A-Za-z0-9_:.\\-]{1,180}: ASCII letters/digits, underscore, colon, dot or hyphen only. '
        'Put Chinese and other natural-language text in text/title/label fields, never in IDs. '
        'For an existing artifact, patch only requested stable IDs; omitted blocks/nodes/edges/pages/objects '
        'are preserved. Retain untargeted user material; do not imply deletion by omission. '
    )
    if task and task['payload'].get('cycle_role'):
        from research_partner.domains.collaboration.cycle import contract_schema
        common += contract_schema(task['payload']['cycle_role'])
        from research_partner.domains.evidence.graph import schema
        common += schema(task)
    if kind == 'diagram':
        return common + (
            'REQUIRED diagram content at top level: width,height in pixels; '
            'nodes:[{id,text,x,y,width,height,source_ref?,group?}]; '
            'edges:[{id,source,target,label,status,source_ref?}]. '
            'Provide actual substantive editable nodes, not a prose-only diagram description. '
            'All coordinates must be finite; positive boxes must fit inside the canvas. '
            'Edges reference existing node IDs; linked nodes cannot overlap or link to themselves. '
            'Use status="candidate" for hypotheses/proposals, status="confirmed" only for a '
            'source-supported observation/relation (not scientific approval or proof of causality). '
            'Keep node and edge IDs unique. Explain meaning and evidence limits in blocks/rationale.'
        )
    if kind in {'poster', 'slides'}:
        return common + (
            'REQUIRED layout content at top level: units="px"|"pt"|"cm"|"mm"|"in", '
            'pages:[{id,title?,width,height,notes,objects:[{id,type,x,y,width,height,text?,asset?,font_size?,group?,source_ref?}]}]. '
            'Types are text,shape,image. Provide actual substantive editable page objects. '
            'All coordinates must be finite and positive boxes must fit the page; each page has its own notes. '
            'Use only existing project-authorized registered image SHA values in asset. Never create placeholder images. '
            'Slides require equal page dimensions and PNG/JPEG images; posters may also use SVG. '
            'Stable object IDs must be unique across all pages. Preserve references, groups and notes.'
        )
    return common + 'Provide nonempty scholarly prose blocks. Paper may additionally include latex, bibtex, citation_keys, bibtex_asset and latex_assets; these are saved source only, never automatically compiled.'


def _string(value, path, nonempty=False):
    if not isinstance(value, str) or (nonempty and not value.strip()): invalid('需要' + ('非空' if nonempty else '') + '文本', path)


def _ids(values, path, maximum=1000):
    if not isinstance(values, list) or len(values) > maximum: invalid('需要有限对象列表', path)
    seen = set()
    for index, item in enumerate(values):
        current = path + '.' + str(index)
        if not isinstance(item, dict): invalid('列表项必须是对象', current)
        ident = item.get('id')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_:.\-]{1,180}', ident): invalid('缺少有效稳定ID', current + '.id')
        if ident in seen: invalid('稳定ID重复', current + '.id')
        seen.add(ident)
    return seen


def _number(value, path, positive=False):
    if type(value) not in {int, float} or not math.isfinite(value) or abs(value) > 1_000_000:
        invalid('几何必须是有界有限数值', path)
    if positive and value <= 0: invalid('尺寸必须为正', path)
    return value


def _box(item, path, width, height):
    values = {key: _number(item.get(key), path + '.' + key, key in {'width', 'height'})
              for key in ['x', 'y', 'width', 'height']}
    if values['x'] < 0 or values['y'] < 0 or values['x'] + values['width'] > width + 1e-6 or values['y'] + values['height'] > height + 1e-6:
        invalid('对象超出画布边界', path)
    for key in ['font_size', 'linewidth']:
        if key in item:
            number = _number(item[key], path + '.' + key, key == 'font_size')
            if number < 0: invalid('线宽不能为负', path + '.' + key)
    if 'group' in item: _string(item['group'], path + '.group')
    if 'z' in item: _number(item['z'], path + '.z')


def _patch(base, proposed, key=None):
    if isinstance(base, dict) and isinstance(proposed, dict):
        result = copy.deepcopy(base)
        for field, value in proposed.items(): result[field] = _patch(base.get(field), value, field)
        return result
    if key in KEYED and isinstance(base, list) and isinstance(proposed, list):
        _ids(base, 'base.' + key); _ids(proposed, 'candidate.' + key)
        updates = {item['id']: item for item in proposed}
        result = [_patch(item, updates.pop(item['id'])) if item['id'] in updates else copy.deepcopy(item) for item in base]
        result.extend(copy.deepcopy(list(updates.values())))
        return result
    return copy.deepcopy(proposed)


def validate_candidate(candidate, kind, app, project_id, *, base_content=None, task=None):
    """Return validated content; optional base content makes omissions non-destructive."""
    if kind=='manuscript_revision':
        from research_partner.domains.manuscripts.revision import validate
        return validate(candidate,task)
    if kind=='project_management':
        from research_partner.domains.workspace.management import validate
        return validate(candidate,task)
    if kind not in OUTPUT_KINDS: invalid('不支持请求的成果类型', 'kind')
    if not isinstance(candidate, dict): invalid('需要JSON对象')
    _string(candidate.get('title'), 'title', True)
    if candidate.get('kind', kind) != kind: invalid('返回类型与请求类型不一致', 'kind')
    if 'interpretation' in candidate: _string(candidate['interpretation'], 'interpretation')
    if 'questions' in candidate:
        from research_partner.domains.collaboration.questions import model_questions
        model_questions(candidate['questions'])
    allowed = COMMON | (LAYOUT[kind] if kind in LAYOUT else PROSE)
    if task and task['payload'].get('cycle_role'):
        from research_partner.domains.collaboration.cycle import validate_contract
        validate_contract(candidate,task)
        from research_partner.domains.evidence.graph import validate_candidate as validate_graph
        validate_graph(candidate,task)
        if task['payload']['cycle_role'] in {'reviewer','final_reviewer'}:allowed=allowed|{'graph_review'}
        if task['payload']['cycle_role'] in {'planner','reviewer','final_reviewer'}:allowed=allowed|{'cycle_contract'}
    if not (task and task['payload'].get('cycle_role')) and ('graph_proposal' in candidate or 'graph_review' in candidate):invalid('图谱提案仅限冻结版本协作任务')
    extra = set(candidate) - allowed
    if extra: invalid('未支持的输出字段：' + ', '.join(sorted(extra)), 'candidate')
    content = {key: copy.deepcopy(value) for key, value in candidate.items()
               if key not in {'title', 'kind', 'interpretation', 'questions'}}
    if task and task['payload'].get('cycle_role') in {'delegate','integrator'}:
        from research_partner.domains.evidence.graph import enabled,EMPTY
        if enabled(task):content.setdefault('graph_proposal',copy.deepcopy(EMPTY))
    if base_content is not None:
        content = _patch(base_content, content)
    # Legacy report checkpoints can omit kind, rationale, and claims; their
    # source remains compatible. A prose-only visual checkpoint fails explicitly.
    blocks = content.get('blocks', [])
    _ids(blocks, 'blocks')
    for index, block in enumerate(blocks):
        _string(block.get('text'), f'blocks.{index}.text')
        if 'kind' in block: _string(block['kind'], f'blocks.{index}.kind', True)
    if 'rationale' in content: _string(content['rationale'], 'rationale')
    claims = content.get('claims', [])
    if not isinstance(claims, list): invalid('claims必须是列表', 'claims')
    for index, claim in enumerate(claims):
        if not isinstance(claim, dict): invalid('claim必须是对象', f'claims.{index}')
        _string(claim.get('text'), f'claims.{index}.text', True)
        _string(claim.get('limitation'), f'claims.{index}.limitation')
        if not isinstance(claim.get('evidence_ids'), list) or not all(isinstance(value, str) and value for value in claim['evidence_ids']):
            invalid('claim需要明确证据标识列表', f'claims.{index}.evidence_ids')
    content.setdefault('claims', [])

    def reference(ref, path, literature=False):
        if not isinstance(ref, dict): invalid('来源必须绑定对象及明确修订', path)
        ident = ref.get('id', ref.get('object_id'))
        if not isinstance(ident, str) or type(ref.get('revision')) is not int or ref['revision'] < 1:
            invalid('来源必须绑定对象及明确修订', path)
        source = app.get(ident, [project_id], ref['revision'])
        if literature and source['kind'] != 'literature': invalid('引用记录不是文献对象', path)
        if 'block_id' in ref and ref['block_id'] not in {block.get('id') for block in source['content'].get('blocks', [])}:
            invalid('来源段落不存在于采用修订', path + '.block_id')

    def references(value, path='content'):
        if isinstance(value, dict):
            if 'source_ref' in value: reference(value['source_ref'], path + '.source_ref')
            if 'component_id' in value: reference({'id': value['component_id'], 'revision': value.get('component_revision', value.get('revision'))}, path + '.component_id')
            if 'source_object_id' in value: reference({'id': value['source_object_id'], 'revision': value.get('source_revision')}, path + '.source_object_id')
            for field in ['source_refs', 'citations', 'components']:
                if field in value:
                    if not isinstance(value[field], list): invalid('来源字段必须是列表', path + '.' + field)
                    for index, ref in enumerate(value[field]): reference(ref, f'{path}.{field}.{index}', field == 'citations')
            for key, child in value.items():
                if key not in {'source_ref', 'source_refs', 'citations', 'components', 'context'}: references(child, path + '.' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value): references(child, path + '.' + str(index))
    references(content)
    for index,question in enumerate(candidate.get('questions',[])):
        if question.get('scope'):references({'source_refs':question.get('source_refs',[])},f'questions.{index}')

    def registered_asset(sha, path):
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha): invalid('资产必须引用登记SHA', path)
        return app.asset(sha, [project_id])

    if kind not in LAYOUT:
        if not any(block['text'].strip() for block in blocks): invalid('正文成果需要实质段落', 'blocks')
        for field in ['markdown', 'latex', 'bibtex']:
            if field in content: _string(content[field], field)
        for field in ['bibtex_asset']:
            if content.get(field): registered_asset(content[field], field)
        if 'latex_assets' in content:
            if not isinstance(content['latex_assets'], dict): invalid('latex_assets必须是映射', 'latex_assets')
            for name, sha in content['latex_assets'].items():
                if not re.fullmatch(r'[A-Za-z0-9_.-]+', name) or name in {'.', '..'}: invalid('附件名称不安全', 'latex_assets')
                registered_asset(sha, 'latex_assets.' + name)
        return content

    if kind == 'diagram':
        width = _number(content.get('width'), 'width', True); height = _number(content.get('height'), 'height', True)
        nodes = content.get('nodes'); edges = content.get('edges')
        node_ids = _ids(nodes, 'nodes', 500); edge_ids = _ids(edges, 'edges', 1000)
        if not nodes: invalid('图对象需要实质节点，正文描述不能替代图结构', 'nodes')
        if node_ids & edge_ids: invalid('节点和连接ID必须不同', 'edges')
        indexed = {node['id']: node for node in nodes}
        for index, node in enumerate(nodes):
            path = f'nodes.{index}'; _string(node.get('text'), path + '.text', True); _box(node, path, width, height)
        for index, edge in enumerate(edges):
            path = f'edges.{index}'
            if not isinstance(edge.get('source'), str) or not isinstance(edge.get('target'), str): invalid('连接端点必须是节点ID', path)
            if edge.get('source') not in node_ids or edge.get('target') not in node_ids: invalid('连接引用缺失节点', path)
            if edge['source'] == edge['target']: invalid('当前直线图不支持自连接', path)
            _string(edge.get('label'), path + '.label', True)
            if edge.get('status') not in ('confirmed', 'candidate'): invalid('关系必须区分有来源的观察和候选解释', path + '.status')
            a, b = indexed[edge['source']], indexed[edge['target']]
            linewidth = _number(edge.get('linewidth', 2), path + '.linewidth')
            if linewidth < 0: invalid('线宽不能为负', path + '.linewidth')
            if 'font_size' in edge: _number(edge['font_size'], path + '.font_size', True)
            # This is pure trusted geometry, not a renderer subprocess or any
            # imported user code. Use the actual renderer's clipping contract.
            from research_partner.rendering.worker import diagram_endpoints
            try: diagram_endpoints(a, b, linewidth)
            except ValueError: invalid('相连节点重叠或无可见连线间隙', path)
        return content

    if content.get('units') not in ('px', 'pt', 'cm', 'mm', 'in'): invalid('需要明确画布单位', 'units')
    pages = content.get('pages'); _ids(pages, 'pages', 100)
    if not pages: invalid('版式成果需要页面及实质对象', 'pages')
    dimensions = set(); object_ids = set()
    for index, page in enumerate(pages):
        path = f'pages.{index}'
        width = _number(page.get('width'), path + '.width', True); height = _number(page.get('height'), path + '.height', True)
        dimensions.add((width, height)); _string(page.get('notes'), path + '.notes')
        objects = page.get('objects'); ids = _ids(objects, path + '.objects', 500)
        if not objects: invalid('页面没有实质对象', path + '.objects')
        if ids & object_ids: invalid('页面之间对象ID重复', path + '.objects')
        object_ids |= ids
        for j, item in enumerate(objects):
            current = f'{path}.objects.{j}'; _box(item, current, width, height)
            if item.get('type') not in ('text', 'shape', 'image'): invalid('不支持的画布对象类型', current + '.type')
            if item['type'] == 'text': _string(item.get('text'), current + '.text', True)
            elif 'text' in item: _string(item['text'], current + '.text')
            if item['type'] == 'image':
                sha = item.get('asset', item.get('asset_id', item.get('src')))
                asset = registered_asset(sha, current + '.asset')
                formats = {'image/png', 'image/jpeg'} | ({'image/svg+xml'} if kind == 'poster' else set())
                if asset['media_type'] not in formats: invalid('此版式不支持该图像格式', current + '.asset')
    if kind == 'slides' and len(dimensions) != 1: invalid('幻灯片页面尺寸必须一致', 'pages')
    return content
