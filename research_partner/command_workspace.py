"""工作区与设置命令；调用前由公共分派层完成作用域检查。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from .contracts import JsonObject, Scope
from .store import require

if TYPE_CHECKING:
    from .app import App


def cycle_command(app: App, data: JsonObject, scope: Scope) -> Any:
    action = data["action"]
    from . import cycle

    if action == "cycle.submit":
        return cycle.create(app, data, scope)
    if action == "cycle.view":
        return cycle.view(app, data["id"], scope)
    return cycle.control(app, data["id"], data["operation"], scope)


def literature_command(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    from .literature import Literature

    app.get(data["project_id"], scope)
    return Literature(s, app.config.get("network", {})).dispatch(data)


def extension_command(app: App, data: JsonObject, scope: Scope) -> Any:
    require(scope is None, "仅空间所有者可管理扩展", "forbidden", 403)
    from .extensions import Extensions

    return Extensions(app).dispatch(data)


def layer_settings(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    from .conventions import layer_action

    return layer_action(s, data, scope)


def update_settings(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    require(scope is None, "仅空间所有者可管理设置", "forbidden", 403)
    require(
        data["key"] in {"domain", "preferences"},
        "此配置需通过本机授权文件修改",
        "forbidden",
        403,
    )
    from .conventions import validate

    s.set_setting(data["key"], validate(data["value"]))
    return {"saved": True}


def backup_workspace(app: App, data: JsonObject, scope: Scope) -> Any:
    require(scope is None, "受限客户端不能导出整个空间", "forbidden", 403)
    return app.backup()
