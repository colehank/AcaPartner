"""Execute an isolated browser fixture's queued Q work with a model test double."""
import argparse
import json
from pathlib import Path
from unittest.mock import patch
from research_partner.app import App
from research_partner.runtime import Runtime


def main():
    p = argparse.ArgumentParser(); p.add_argument('workspace', type=Path); p.add_argument('config', type=Path); p.add_argument('task')
    args = p.parse_args(); app = App(args.workspace, json.loads(args.config.read_text())); task = app.store.task(args.task)
    assert task['payload']['kind'] == 'research_work'
    snapshot = task['payload']['context']['research_work']; targets = snapshot['targets']
    sources = [{k: r[k] for k in ('id', 'revision')} for r in snapshot['materials'] if r['id'] not in {q['id'] for q in targets}]
    changes = []
    for target in targets:
        for part in target['parts']:
            changes.append({'id': target['id'] + '.' + part, 'question_id': target['id'], 'part': part,
                'mode': 'append' if part == 'A' else 'replace', 'text': {
                    'A': '按同一枚鸡蛋的两项指标比较联合达标情况，保留原有操作与缺失记录。',
                    'E': '已保存记录中甲方法3/10枚、乙方法5/10枚同时达标；这些是原记录，未开展新实验。',
                    'C': '现有记录中乙方法比例较高；样本有限，尚不能认定其稳定优越。'}[part],
                'rationale': '比较采用了同一目标及固定来源，需要区分描述性差异与可推广的判断。',
                'basis': 'supported' if sources else 'plan' if part == 'A' else 'unresolved', 'source_refs': sources})
    reply = {'title': '研究工作的阶段候选', 'kind': 'note', 'research_update': {'version': 1,
        'summary': '比较已选保存记录，形成分析与阶段判断候选；没有执行新实验或脚本。', 'changes': changes, 'limitations': ['示例记录不足以建立稳定优越性。']}}
    runtime = Runtime(app); assert runtime.claim() == args.task
    with patch('research_partner.providers.Providers.call', return_value={'text': json.dumps(reply), 'receipt': {
            'route': 'codex', 'session_id': 'browser-work-test', 'returncode': 0, 'usage': []}}): runtime.execute(args.task)
    assert app.store.task(args.task)['status'] == 'generated'
    print(json.dumps({'task_id': args.task, 'status': 'generated'}))


if __name__ == '__main__': main()
