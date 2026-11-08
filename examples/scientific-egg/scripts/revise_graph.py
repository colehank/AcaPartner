"""Editorial revision of this authored case, through the existing graph API.

Retains object IDs, old QAEC and relation history. Refuses to replace edited
case text. Only previously completed, still answerable case claims may be
rechecked; the new synthesis of unfinished Q2 work stays unfinished.
"""
import csv
import hashlib
import json
from pathlib import Path

from case_content import METHODS, ROOT
from research_graph import TITLES

SINGLE_ANALYSIS = '在480枚鸡蛋上分别统计两个目标。蛋白评分≥7.5；蛋黄评分5至8.5。单项计数使用各自有读数的样本，并单独登记缺失；联合达标必须是同一 sample_id 同时满足两项判据。\n\n此分析汇总 Q1.1 与 Q1.2 已有计算，不替代联合达标分析。'
SINGLE_EVIDENCE = '| 煮法（各120枚） | 蛋白达标 | 蛋黄达标 |\n|---|---:|---:|\n| 沸水6分钟 |117|0|\n| 沸水12分钟 |120|8|\n| 65°C恒温60分钟 |0|114|\n| 冷热交替32分钟 |120|45|\n\n蛋白目标为评分≥7.5；蛋黄目标为评分5至8.5。蛋黄114枚按蛋黄单项有效读数统计；原汇总中的113枚使用两项可评估样本作为分母。6分钟组缺3项蛋白读数，恒温组缺1项蛋白读数。\n\n这些计数只判断单项目标；整枚鸡蛋的联合达标来自另一项按 sample_id 的分析。'


def audit_counts():
    """Recompute from saved observations, independently of summary counters."""
    raw = ROOT / 'data/observations.csv'
    with raw.open() as stream:
        rows = list(csv.DictReader(stream))
    criteria = json.loads((ROOT / 'protocol.json').read_text())['criteria']
    assert {k: criteria[k] for k in ('white_min', 'yolk_min', 'yolk_max')} == {'white_min': 7.5, 'yolk_min': 5.0, 'yolk_max': 8.5}
    assert len(rows) == 480 and len({r['sample_id'] for r in rows}) == 480
    counts = {}
    for method in METHODS:
        group = [r for r in rows if r['method'] == method]
        joint = sum(bool(r['white_index']) and float(r['white_index']) >= 7.5 and
                    5 <= float(r['yolk_index']) <= 8.5 for r in group)
        missing = [r for r in group if not r['white_index']]
        # Even an unknown white reading cannot rescue a known failing yolk.
        possible = sum(5 <= float(r['yolk_index']) <= 8.5 for r in missing)
        counts[method] = {'n': len(group), 'joint': joint,
                          'missing': len(missing), 'upper': joint + possible}
    assert [counts[k]['joint'] for k in METHODS] == [0, 8, 0, 45]
    assert all(c['n'] == 120 for c in counts.values())
    assert [counts[k]['upper'] for k in METHODS] == [0, 8, 1, 45]
    assert [counts[k]['missing'] for k in METHODS] == [3, 0, 1, 0]
    return counts, hashlib.sha256(raw.read_bytes()).hexdigest()


def revise_case_graph(call, pid):
    research = call('workbench.research.read', project_id=pid)
    assert research['project']['metadata'].get('demo') == 'scientific_egg_v1', 'Not the authored egg case'
    original = {q['id']: q['content'] for q in research['questions']}
    legacy = {q['metadata'].get('demo_question_key'): q for q in research['questions']}
    graph = call('workbench.graph.read', project_id=pid)
    assert graph['migrated'], 'Import the authored graph first'
    by = {n['label']: n for n in graph['nodes']}
    completed = {n['id'] for n in graph['nodes'] if n['status'] == 'completed'}
    counts, data_sha = audit_counts()
    specs = {}

    def replace(label, old_title, old_body, title, body, status='review', sources=()):
        n = by[label]
        assert (n['title'], n['body']) in {(old_title, old_body), (title, body)}, \
            f'{label} has user edits; inspect without overwriting'
        specs[label] = dict(title=title, body=body, status=status, sources=sources)

    def source_text(label):
        n = by[label]
        return f"[{label}：{n['title']}](/?project={pid}&object={n['id']}&revision={n['revision']})"

    old = legacy['qy']['content']['qaec']
    replace('A1.2', TITLES['qy'][0], old['A'], TITLES['qy'][0],
            old['A'].replace('再由Q1判断', '在综合问题Q1.3中逐枚判断'))
    replace('C1.2', TITLES['qy'][2], old['C'], '恒温程序的蛋黄达标最多，整枚表现另行比较',
            '65°C恒温有114/120枚蛋黄在5–8.5目标区间，冷热交替为45/120枚，沸水12分钟为8/120枚，沸水6分钟为0/120枚。这里只回答蛋黄目标；不能由这些单项计数推出整枚鸡蛋同时达标，联合比较见Q1.3。')
    replace('A1.3-2', '分别核对蛋白凝固与蛋黄柔软', SINGLE_ANALYSIS,
            '核对缺失读数会不会改变煮法排序',
            '保留全部480枚，每种煮法以120枚为分母。先按原判据逐枚计算联合达标，再把缺少蛋白读数的鸡蛋逐一核对蛋黄。\n\n蛋黄已经不达标的样本，即使补齐蛋白也不能联合达标；只有蛋黄达标而蛋白缺失的样本，才进入可能成功的上界。上界用于检查排序是否可能改变，不把未知读数填成成功。',
            sources=('E1.1', 'E1.2', 'E1.3-1'))
    table = '| 煮法 | 已确认同时达标/全部 | 蛋白缺失 | 若缺失蛋白均达标，联合达标上界 |\n|:--|--:|--:|--:|\n'
    table += '\n'.join(f"| {title} | {counts[k]['joint']}/120 | {counts[k]['missing']} | {counts[k]['upper']}/120 |" for k, title in METHODS.items())
    replace('E1.3-2', '两项单独达标，不能推出整枚同时达标', SINGLE_EVIDENCE,
            '缺失读数的最有利上界仍不改变当前排序',
            table + '\n\n沸水6分钟的3枚缺失蛋白读数，其蛋黄均不达标；恒温程序的1枚缺失蛋白读数，蛋黄达标，因此恒温最多从0/120变为1/120。两项完整的冷热交替与沸水12分钟仍为45/120、8/120。\n\n这只检查当前4项缺失的数值边界，不假定缺失随机，不证明固定程序可跨批次稳定复现。',
            sources=('E1.3-1',))
    old = legacy['q1']['content']['qaec']
    replace('C1.3', TITLES['q1'][2], old['C'], '冷热交替联合达标最多，但多数仍未达标',
            '在本例480条记录中，冷热交替有45/120枚（37.5%）同时达标，沸水12分钟为8/120枚，另外两种煮法为0/120。缺失蛋白读数的最有利上界也不改变这一次比较的排序。\n\n因此，冷热交替是继续检查的候选方法，但多数鸡蛋仍未同时满足两项目标。结论只回答当前记录中的描述性比较；不代表已经获得稳定程序或证明对不同大小、初温的泛化性，后者留给Q2。')
    refs = '\n\n'.join(source_text(label) for label in ('E2.1', 'E2.2', 'E2.3'))
    old = legacy['q2']['content']['qaec']
    replace('A2.4-1', TITLES['q2'][0], old['A'], '综合分层、批次与判据，检查适用范围的证据缺口',
            '以Q2.1的大小与初温分层、Q2.2的批次过程核对和Q2.3的判据敏感性为输入，逐项区分已有观察、限制和未完成验证。\n\n不再复制六格分层统计，也不把尚未核对的子问题当成已完成依据。分层敏感性、固定程序下的独立验证完成前，综合分析保持进行中。\n\n当前保存来源：\n\n' + refs,
            status='active', sources=('E2.1', 'E2.2', 'E2.3'))
    replace('E2.4-1', TITLES['q2'][1], old['E'], '适用范围判断的现有依据与缺口',
            '| 检查 | 目前有什么 | 仍缺什么 |\n|:--|:--|:--|\n| 大小与初温 | 六格各20枚，联合达标5/20至11/20；Q2.1待核对 | 同一固定过程下的条件比较 |\n| 批次过程 | B04为30/30，但热端停留与温控偏移同时改变；Q2.2待核对 | 分离过程变化的对照 |\n| 判据敏感性 | 总体冷热交替为45/120、45/120、43/120 | 按六个大小与初温组合重算 |\n| 独立验证 | 只有A2.4-2的计划 | 固定程序后的独立新批次 |\n\n这是对当前报告内容的证据覆盖核对，仍待确认，不是新的实验结果。\n\n' + refs,
            sources=('E2.1', 'E2.2', 'E2.3'))
    replace('C2.4', TITLES['q2'][2], old['C'], '现有依据尚不足以确定大小与初温的适用范围',
            '现有六格分层给出了25%–55%的描述性达标率，但混合了过程条件不同的批次；总体敏感性也不能替代分层敏感性。当前既不能确认广泛适用，也不能把条件差异归因于大小或初温本身。\n\n先完成Q2.1—Q2.3的核对与分层重算，再固定程序开展A2.4-2的独立验证。该结论为待确认的阶段判断，Q2.4和父Q2保持未完成。')

    # All text guards above run before the first write. Use stable IDs below;
    # display numbering is only used to identify the authored, guarded case.
    changed = []
    def mutate(action, **fields):
        nonlocal graph
        result = call('workbench.graph.' + action, project_id=pid,
                      expected_project_revision=graph['project']['revision'], **fields)
        graph = result['graph']
        return result

    def current(ident):
        return next(n for n in graph['nodes'] if n['id'] == ident)

    def relation(src, dst, kind, reason, active=True):
        edge = next((e for e in graph['edges'] if e['src'] == by[src]['id'] and
                     e['dst'] == by[dst]['id'] and e['kind'] == kind), None)
        if edge and (edge['active'] != active or active and edge['rationale'] != reason):
            mutate('edge.save', id=edge['id'], expected_revision=edge['revision'], active=active, rationale=reason)
            changed.append(f'{src} {kind} {dst}')
        elif not edge and active:
            mutate('edge.create', src=by[src]['id'], dst=by[dst]['id'], kind=kind, rationale=reason)
            changed.append(f'{src} {kind} {dst}')

    for label, spec in specs.items():
        n = current(by[label]['id'])
        refs = [{'id': by[s]['id'], 'revision': current(by[s]['id'])['revision']} for s in spec['sources']]
        text_changed = (n['title'], n['body']) != (spec['title'], spec['body'])
        # A later completion record adds a revision without changing the cited
        # result. Preserve the exact source snapshot already used by this edit.
        refs_changed = bool(refs) and [r['id'] for r in n['source_refs']] != [r['id'] for r in refs]
        if text_changed or refs_changed:
            mutate('node.save', id=n['id'], expected_revision=n['revision'],
                   title=spec['title'], body=spec['body'], status=spec['status'],
                   **({'source_refs': refs} if refs else {}))
            changed.append(label)
    for source in ('E1.1', 'E1.2'):
        relation(source, 'C1.3', 'supports', '撤回迁移残留：单项计数不能直接证明同一枚蛋的联合达标；来源在综合分析中保留。', False)
    relation('E1.3-2', 'C1.3', 'supports', '撤回重复汇总的支持关系，改为明确的缺失处理限制。', False)
    relation('E1.3-2', 'C1.3', 'limits', '限定缺失处理的解释：最有利上界不改变当前排序，但不能据此确认稳定性或泛化。')
    relation('E1.3-1', 'C1.3', 'supports', '同一sample_id的联合计数直接支持当前四种程序的描述性排序，不把单项均值当作联合达标。')
    relation('E1.2', 'C1.2', 'supports', '蛋黄单项计数支持目标区间内的数量比较，不包含对蛋白或整枚达标的判断。')
    relation('E2.4-1', 'C2.4', 'supports', '现有依据与缺口支持暂不能确定适用范围的阶段判断，不证明方法无效或已经泛化。')
    for source in ('Q1.1', 'Q1.2'):
        relation(source, 'Q1.3', 'prerequisite', '先明确单项目标及其核对结果，再开展综合比较；联合计数必须另读逐枚记录，不能相加单项计数。')
    for source in ('Q2.1', 'Q2.2', 'Q2.3'):
        relation(source, 'Q2.4', 'prerequisite', '完成对应子问题的核对后，综合判断大小与初温的适用范围；未完成项保持为缺口。')

    # New Q2 synthesis is broader than its old, verified six-cell calculation.
    # It must not inherit completion from that calculation.
    excluded = {by[label]['id'] for label in ('A2.4-1', 'E2.4-1')}
    desired = completed - excluded
    reconfirmed = []
    while True:
        ready = [n for n in graph['nodes'] if n['id'] in desired and
                 n['status'] != 'completed' and n['can_complete']]
        if not ready:
            break
        for prior in ready:
            n = current(prior['id'])
            mutate('node.save', id=n['id'], expected_revision=n['revision'],
                   title=n['title'], body=n['body'], status='completed',
                   expected_dependencies=n['dependencies'], answers_question=True,
                   confirmation_note='仅复核此前已完成的案例判断：重新逐枚核对480行、4项缺失及0/8/0/45联合计数；最有利上界0/8/1/45不改变描述性排序。按本节点当前正文、来源与依赖版本保存；不确认Q2或真实总体泛化。原始CSV SHA-256：' + data_sha)
            reconfirmed.append(n['label'])
    final = call('workbench.research.read', project_id=pid)
    assert all(q['content'] == original[q['id']] for q in final['questions']
               if q['id'] not in {by[label]['id'] for label in specs if label.startswith('Q')})
    return {'graph': graph, 'changed': changed, 'reconfirmed': reconfirmed,
            'counts': counts, 'data_sha256': data_sha, 'legacy_qaec_unchanged': True}


if __name__ == '__main__':
    import argparse
    import urllib.error
    import urllib.parse
    import urllib.request
    import uuid

    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://127.0.0.1:8924')
    parser.add_argument('--project', required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    base = args.base_url.rstrip('/')
    assert urllib.parse.urlparse(base).hostname in {'localhost', '127.0.0.1'}, 'Use an explicitly local workbench'
    assert not args.receipt.exists(), 'Use a fresh receipt path'
    state = json.load(urllib.request.urlopen(base + '/api/state'))
    assert not any(t['project_id'] == args.project and t['status'] in {'queued', 'running'} for t in state['tasks']), 'Wait for project tasks'

    def call(action, **fields):
        if action not in {'workbench.graph.read', 'workbench.research.read'}:
            fields['request_key'] = 'egg-case-revision:' + str(uuid.uuid4())
        req = urllib.request.Request(base + '/api/action', json.dumps(dict(action=action, **fields)).encode(),
                                     {'Content-Type': 'application/json', 'Origin': base, 'X-CSRF-Token': state['csrf']})
        try:
            response = json.load(urllib.request.urlopen(req, timeout=60))
        except urllib.error.HTTPError as error:
            raise RuntimeError(error.read().decode()) from error
        assert response['ok'], response
        return response['result']

    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    before = args.receipt.with_name(args.receipt.stem + '-before.json')
    with before.open('x') as stream:
        json.dump({'state': state, 'graph': call('workbench.graph.read', project_id=args.project)}, stream, ensure_ascii=False, indent=2)
    result = revise_case_graph(call, args.project)
    args.receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'graph'}, ensure_ascii=False))
