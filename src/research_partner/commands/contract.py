"""GUI、CLI 与代理共用的命令信封；业务字段由各领域验证。"""

from collections.abc import Callable
import json
from typing import TypedDict, cast

from research_partner.contracts import JsonObject, Scope
from research_partner.storage.store import Problem, require


class ActionRequest(TypedDict):
    action: str


def validate_action_request(data: object) -> ActionRequest:
    """只验证公共字段，不裁剪或改写调用方的业务参数。"""
    require(isinstance(data, dict), "需要 JSON 对象")
    fields = cast(JsonObject, data)
    action = fields.get("action")
    require(isinstance(action, str) and bool(action.strip()), "action 必须是非空字符串")
    return cast(ActionRequest, data)


def parse_action_json(raw: str) -> ActionRequest:
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise Problem("命令 JSON 格式无效", details={"field": "body"}) from None
    return validate_action_request(data)


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _revision(value: object) -> bool:
    return type(value) is int and value >= 1


FieldCheck = Callable[[object], bool]

# 只纳管已迁移的核心命令，其他领域仍由其自有入口验证。
COMMAND_FIELDS: dict[str, dict[str, FieldCheck]] = {
    "project.create": {"title": _text},
    "project.feature": {
        "project_id": _text,
        "object_id": _text,
        "expected_revision": _revision,
        "featured": lambda value: type(value) is bool,
    },
    "workshop.accept": {"id": _text, "expected_revision": _revision},
    "object.create": {"project_id": _text, "kind": _text, "title": _text},
    "object.restore": {
        "id": _text,
        "revision": _revision,
        "expected_revision": _revision,
    },
    "annotation.add": {
        "object_id": _text,
        "revision": _revision,
        "text": lambda value: isinstance(value, str),
    },
    "annotation.update": {"id": _text, "object_id": _text},
    "review.record": {
        "object_id": _text,
        "revision": _revision,
        "review_object_id": _text,
        "review_revision": _revision,
        "verdict": _text,
        "scope": _text,
        "summary": _text,
        "reviewer_reference": _text,
    },
    "dependency.accept": {"id": _text, "target_revision": _revision},
    "dependency.retain": {"id": _text, "target_revision": _revision},
    "asset.inspect": {"project_id": _text, "sha": _text},
    "asset.import": {"project_id": _text},
    "object.import": {"project_id": _text, "asset_sha": _text},
    "object.authorize_code": {"id": _text, "expected_revision": _revision},
    "object.export": {"id": _text, "format": _text},
    "figure.render": {"id": _text},
    "task.control": {"id": _text, "operation": _text},
    "task.guide": {"id": _text, "text": _text},
    "task.extend_budget": {"id": _text},
    "task.revise_candidate": {"id": _text},
    "settings.update": {"key": _text, "value": lambda value: True},
    "cycle.view": {"id": _text},
    "cycle.control": {"id": _text, "operation": _text},
}
for _action in (
    "project.update",
    "project.archive",
    "project.restore",
    "object.save",
    "object.rename",
    "object.archive",
):
    COMMAND_FIELDS[_action] = {"id": _text, "expected_revision": _revision}
for _action in ("task.submit", "workshop.submit", "commission.submit"):
    COMMAND_FIELDS[_action] = {"project_id": _text}

OWNER_ONLY = frozenset(
    {"project.create", "object.authorize_code", "settings.update", "workspace.backup"}
)


def validate_command_parameters(data: JsonObject, scope: Scope) -> None:
    action = data["action"]
    require(
        scope is None
        or action not in OWNER_ONLY
        and not action.startswith("extension."),
        "此业务命令仅限空间所有者",
        "forbidden",
        403,
    )
    for field, check in COMMAND_FIELDS.get(action, {}).items():
        valid = field in data and check(data[field])
        if field == "expected_revision":
            require(
                valid, "写入需要已读版本", "version_required", 409, {"field": field}
            )
        else:
            require(valid, "请求字段缺失或格式错误", details={"field": field})
    if action in {
        "object.create",
        "project.create",
        "object.save",
        "object.rename",
        "project.update",
    }:
        for field in ("content", "metadata"):
            if field in data:
                require(
                    data[field] is None or isinstance(data[field], dict),
                    "对象字段需要 JSON 对象",
                    details={"field": field},
                )
        if "title" in data:
            require(
                data["title"] is None or _text(data["title"]),
                "标题不能为空",
                details={"field": "title"},
            )
    if action.startswith("annotation."):
        if "text" in data:
            require(
                isinstance(data["text"], str),
                "批注文字需要字符串",
                details={"field": "text"},
            )
        if "anchor" in data:
            require(
                isinstance(data["anchor"], dict),
                "批注锚点需要 JSON 对象",
                details={"field": "anchor"},
            )
        if "status" in data:
            require(
                isinstance(data["status"], str),
                "批注状态需要字符串",
                details={"field": "status"},
            )
    if action.startswith("literature."):
        require(
            _text(data.get("project_id")),
            "请选择文献所属项目",
            details={"field": "project_id"},
        )
