"""GUI、CLI 与代理共用的命令信封；业务字段由各领域验证。"""

from typing import TypedDict, cast

from .store import require


class ActionRequest(TypedDict):
    action: str


def validate_action_request(data: object) -> ActionRequest:
    """只验证公共字段，不裁剪或改写调用方的业务参数。"""
    require(isinstance(data, dict), "需要 JSON 对象")
    action = data.get("action")
    require(isinstance(action, str) and bool(action.strip()), "action 必须是非空字符串")
    return cast(ActionRequest, data)
