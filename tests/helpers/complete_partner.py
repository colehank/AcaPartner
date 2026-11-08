"""Deterministic UI fixture through the real shared Runtime/publication path."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
from research_partner.app import App
from research_partner.runtime import Runtime


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('workspace', type=Path); parser.add_argument('config', type=Path)
    parser.add_argument('task'); parser.add_argument('mode', choices=['discussion','question','work'])
    args = parser.parse_args(); app = App(args.workspace, json.loads(args.config.read_text())); task = app.store.task(args.task)
    assert task['payload']['kind'] == 'research_partner'
    snapshot = task['payload']['context']['partner']
    reply = {'title': '煮蛋研究的下一步', 'kind': 'note', 'partner_reply': {'version': 1,
        'text': '先把同一枚鸡蛋的两项目标说清楚：蛋白凝固、蛋黄柔软。现有记录与判断需要分开核对。',
        'next_steps': [{'id': 'next', 'label': '继续明确评价标准', 'prompt': '一起明确蛋白与蛋黄的评价标准。'}]}, 'research_proposal': None, 'research_update': None}
    if snapshot.get('graph'):
        reply.pop('research_proposal'); reply.pop('research_update'); reply['graph_change'] = None
        def node(ident, kind, title, body, quote='', refs=None):
            return {'id': ident, 'kind': kind, 'title': title, 'body': body, 'quote': quote, 'source_refs': refs or []}
        def edge(src, dst, kind): return {'src': src, 'dst': dst, 'kind': kind, 'rationale': '由本轮研究内容确定范围与关系'}
        if args.mode == 'question':
            reply['partner_reply']['text'] = '先比较同一枚鸡蛋的两项目标，再检验所选程序在不同大小与初温下的表现。画布中的分析仍待开展。'
            reply['graph_change'] = {'version': 1, 'summary': '建立煮法比较与适用范围两个问题', 'background': None, 'updates': [],
                'creates': [node('methods', 'Q', '哪种煮法使蛋白凝固、蛋黄柔软？', '在同一枚鸡蛋上判断两项目标，比较不同煮法。'),
                            node('conditions', 'Q', '所选程序适用于不同大小与初温吗？', '在选定程序后，检验不同鸡蛋大小与下锅初温。'),
                            node('comparison', 'A', '比较逐枚联合达标率', '待开展：固定判据，逐枚核对蛋白和蛋黄的两项目标。'),
                            node('validation', 'A', '检验大小与初温条件', '待开展：保持煮蛋程序一致，在不同大小与初温下重复比较。')],
                'edges': [edge('methods', 'comparison', 'analyzes'), edge('conditions', 'validation', 'analyzes'), edge('methods', 'conditions', 'prerequisite')]}
        elif args.mode == 'work':
            focus = next(n for n in snapshot['graph']['nodes'] if n['id'] == snapshot['graph']['focus_id'])
            assert focus['kind'] == 'A'
            q = next(e['src'] for e in snapshot['graph']['edges'] if e['kind'] == 'analyzes' and e['dst'] == focus['id'])
            refs = [{k: f['source_ref'][k] for k in ('id', 'revision')} for f in snapshot['native_files']]
            quote = '本批10枚中7枚同时达标。'
            reply['partner_reply']['text'] = '从保存的记录中整理出本批计数和有限的阶段判断；本轮没有运行脚本，结论仍待核对。'
            reply['graph_change'] = {'version': 1, 'summary': '将保存记录整理为证据与阶段结论', 'background': None, 'updates': [],
                'creates': [node('reported', 'E', '本批联合达标计数', quote, quote, refs),
                            node('finding', 'C', '当前批次的描述性结果', '本批10枚中7枚同时达标，仅描述该批次，不能判断跨批次稳定性。', quote, refs)],
                'edges': [edge(focus['id'], 'reported', 'produces'), edge('reported', 'finding', 'supports'), edge('finding', q, 'answers')]}
    elif args.mode == 'question':
        reply['research_proposal'] = {'version': 1, 'interpretation': '研究兼顾两种质构的煮蛋方法。', 'candidates': [{
            'id': 'texture', 'question': '哪种煮蛋方法使蛋白凝固且蛋黄柔软？', 'unknown': '两项目标如何在同一枚蛋上同时实现？',
            'rationale': '蛋白与蛋黄热响应不同，不能用单一平均温度代表两种质构。', 'assumptions': ['先固定可重复的质构评价方法。'],
            'analysis_plan': '比较各方法逐枚联合达标率并报告不确定性。', 'evidence_needed': ['逐枚质构与温度记录'], 'source_refs': []}],
            'clarifications': [], 'limitations': ['提案不代表已有实验结果。']}
    elif args.mode == 'work':
        target = snapshot['targets'][0]
        refs = [{k: r[k] for k in ('id','revision')} for r in snapshot['materials'] if r['id'] not in {t['id'] for t in snapshot['targets']}]
        reply['partner_reply']['text'] = '读到了保存版实验记录和分析脚本。记录中本批10枚有7枚同时达到两项目标；脚本没有在本次执行。可以先保留这个有限的批次判断，再规划独立重复。'
        reply['research_update'] = {'version': 1, 'summary': '核对已保存记录与代码，提出有限的阶段判断。', 'changes': [{
            'id': 'conclusion', 'question_id': target['id'], 'part': 'C', 'mode': 'replace',
            'text': '本批10枚有7枚同时达到两项目标；这只描述当前批次，尚不能判断跨批次稳定性。', 'rationale': '来自冻结的逐枚记录，脚本未执行。',
            'basis': 'supported', 'source_refs': refs}], 'limitations': ['仅有一个批次，不能外推。']}
    runtime = Runtime(app); assert runtime.claim() == args.task
    with patch('research_partner.providers.Providers.call', return_value={'text': json.dumps(reply), 'receipt': {
        'route': 'codex', 'session_id': 'partner-browser-fixture', 'returncode': 0, 'usage': []}}): runtime.execute(args.task)
    result = app.store.task(args.task); assert result['status'] == 'generated', result['error']
    print(json.dumps({'task_id': args.task, 'status': result['status']}))


if __name__ == '__main__': main()
