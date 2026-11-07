"""Keep legacy node keys across a verified source-lock relocation.

The actual execution environment remains in every new node and plan. Only the
hash input uses the earliest frozen, same-project equivalent environment. This
retains existing content-addressed cache keys without rewriting old plans or
granting trust to a path basename alone. Cache validation remains mandatory.
"""
import copy

from research_partner.domains.generation.checkpoint import environment_binding
from research_partner.storage.store import Problem, digest, require


def key_environment(store, project_id, current):
    for task in sorted(store.tasks(), key=lambda t: (t['created_at'], t['id'])):
        if task['project_id'] != project_id or task['payload'].get('kind') != 'generation':
            continue
        plan = task['payload'].get('generation_plan')
        if not isinstance(plan, dict) or plan.get('project_id') != project_id:
            continue
        plan_hash = plan.get('plan_hash')
        if (plan_hash != digest({k: v for k, v in plan.items() if k != 'plan_hash'})
                or store.setting('generation_plan:' + plan_hash) != plan):
            continue
        # Relocation records are audit information, not a new trust root. The
        # original immutable producer remains available in this same project.
        if 'node_key_environment' in plan or 'node_key_environment_binding' in plan:
            continue
        original = plan.get('environment')
        if not isinstance(original, dict) or not isinstance(plan.get('environment'), dict):
            continue
        try:
            equivalent = environment_binding(original, current)
        except Problem:
            continue
        if equivalent is None:
            return copy.deepcopy(current), None
        return copy.deepcopy(original), {
            'source_run_id': task['id'], 'source_plan_hash': plan_hash,
            'equivalence': equivalent,
        }
    return copy.deepcopy(current), None


def verify_relocated_cache(node, cached, by_id):
    """An environment match never substitutes for the actual producer inputs."""
    expected = {
        alias: ref['asset_sha256'] if ref['kind'] == 'dataset' else
        by_id[ref['node_id']]['reuse']['outputs'][ref['output']]['asset_sha256']
        for alias, ref in node['bound_inputs'].items()
    }
    require(cached.get('node_key') == node['node_key']
            and cached.get('actual_inputs') == expected
            and cached.get('source_script_sha256') == node['script_snapshot']['sha256']
            and cached.get('parameters') == node['parameters']
            and cached.get('io') == node['io']
            and set(cached.get('outputs', {})) == set(node['io']['outputs']),
            '迁移缓存与实际代码、输入、参数或合同不同', 'output_integrity', 409)
