"""Complete one queued task in an isolated, workbench-only browser fixture.

No HTTP test endpoint is added to the product. The real Runtime and publication
path run here, with only the model response replaced for deterministic tests.
"""
import argparse
import json
from pathlib import Path
from unittest.mock import patch

from research_partner.app import App
from research_partner.runtime import Runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('workspace', type=Path)
    parser.add_argument('config', type=Path)
    parser.add_argument('task')
    args = parser.parse_args()
    app = App(args.workspace, json.loads(args.config.read_text()))
    task = app.store.task(args.task)
    assert task['payload']['kind'] == 'research_exploration'
    refined = bool(task['payload']['context']['exploration'].get('previous_proposal'))
    title = '哪种煮蛋方法能够使蛋白凝固、蛋黄柔软？' if refined else '不同加热程序如何影响蛋白和蛋黄的质构？'
    proposal = {'title': '煮蛋研究的问题提案', 'kind': 'note', 'research_proposal': {
        'version': 1, 'interpretation': '研究如何同时达到蛋白凝固、蛋黄柔软的目标。' if refined else '“更好”尚需明确评价目标，可以先讨论口感方向。',
        'candidates': [{'id': 'texture', 'question': title,
            'unknown': '不同加热程序能否在同一枚蛋上同时满足两项目标。',
            'rationale': '蛋白与蛋黄的热响应不同，需要比较同一枚蛋的两种表现。',
            'assumptions': ['蛋白凝固、蛋黄柔软的测量标准还需预先约定。'],
            'analysis_plan': '先规定质构评价方法，再比较逐枚联合达标情况，并报告不确定性。',
            'evidence_needed': ['各组逐枚的蛋白与蛋黄质构记录。', '蛋重、下锅温度与温度过程记录。'],
            'source_refs': task['payload']['context']['materials'] and [
                {k: r[k] for k in ('id', 'revision')} for r in task['payload']['context']['materials']] or []}],
        'clarifications': [] if refined else [{'id': 'goal', 'question': '主要关注口感、营养还是效率？',
            'why_it_matters': '研究目标会决定评价指标与比较方法。'}],
        'limitations': ['尚无实验数据，不能据此判断哪种方法更优。']}}
    runtime = Runtime(app)
    assert runtime.claim() == args.task, 'Fixture must contain exactly the intended pending task'
    receipt = {'route': 'codex', 'session_id': 'browser-test-session', 'returncode': 0, 'usage': []}
    with patch('research_partner.providers.Providers.call', return_value={'text': json.dumps(proposal), 'receipt': receipt}):
        runtime.execute(args.task)
    assert app.store.task(args.task)['status'] == 'generated'
    print(json.dumps({'task_id': args.task, 'status': 'generated'}))


if __name__ == '__main__':
    main()
