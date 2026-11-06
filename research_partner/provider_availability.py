"""公共分发中实验性 provider 的只读可用性声明。"""

from typing import TypedDict

from .store import Problem


class ProviderAvailability(TypedDict):
    available: bool
    reason: str


def codex_dynamic_availability() -> ProviderAvailability:
    return {
        "available": False,
        "reason": (
            "公共版本未包含 Codex AppServer 动态协议所需的私有连接适配器；"
            "此实验路线不可用，未启动模型，也不会回退到 CLI。"
        ),
    }


def require_codex_dynamic_available() -> None:
    availability = codex_dynamic_availability()
    if not availability["available"]:
        raise Problem(availability["reason"], "provider_missing", 503)
