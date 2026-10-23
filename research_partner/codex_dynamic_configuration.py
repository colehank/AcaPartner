"""Explicit local AppServer configuration; never changes account/global config."""
from pathlib import Path
import os
import tomllib

from .store import require, digest

TRANSPORT = 'app_server_dynamic'
FEATURE = 'native_codex_dynamic_tools_v1'
DISABLED = ('shell_tool', 'apps', 'multi_agent', 'browser_use', 'browser_use_external',
            'in_app_browser', 'computer_use', 'hooks', 'image_generation',
            'workspace_dependencies', 'skill_search')


def definition(config):
    require(config.get('route')=='codex' and config.get('transport')==TRANSPORT
            and isinstance(config.get('model'), str) and config['model'],
            '原生动态工具需要明确的既有Codex模型与协议', 'provider_missing', 503)
    effort=config.get('reasoning_effort', 'medium')
    require(effort in {'none','minimal','low','medium','high','xhigh','max','ultra'},
            '原生推理设置不支持', 'provider_missing', 503)
    result={'transport':TRANSPORT, 'route':'codex', 'model':config['model'], 'reasoning_effort':effort}
    return {**result, 'sha256':digest(result)}


def guard(task, config):
    # The same pure constructor limits run before provider/parent reservations.
    # A simulated session must not hide an invalid real constructor setting.
    session_limits()
    require(config.get('authorized') is True, '原生模型路线授权已撤回；未新增调用', 'authorization_required', 403)
    plan=task['payload'].get('context',{}).get('figure_composition',{})
    require(task['payload']['kind']=='figure_composition' and plan.get('native_transport')==TRANSPORT,
            '不能将旧任务隐式切换到新原生协议', 'provider_checkpoint_missing', 503)
    require(plan.get('native_definition')==definition(config),
            '原生任务模型或协议已变化；未新增分派', 'provider_checkpoint_missing', 503)
    return plan


def session_limits():
    from .codex_dynamic_transport import validate_limits
    return validate_limits(max_messages=2048)


def overrides(config_path=None):
    """Disable inherited host tools/plugins only for this product thread."""
    result={'web_search':'disabled', **{'features.'+name:False for name in DISABLED}}
    path=Path(config_path) if config_path else Path(os.environ.get('CODEX_HOME',str(Path.home()/'.codex')))/'config.toml'
    if path.exists():
        local=tomllib.loads(path.read_text())
        for name in local.get('mcp_servers',{}): result['mcp_servers.'+name+'.enabled']=False
        for name in local.get('plugins',{}): result['plugins.'+name+'.enabled']=False
    return result
