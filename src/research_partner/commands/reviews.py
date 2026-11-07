"""批注、审阅与依赖决策；调用前由公共分派层完成作用域检查。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from research_partner.contracts import JsonObject, Scope
from research_partner.storage.store import require, digest

if TYPE_CHECKING:
    from research_partner.app import App


def add_annotation(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    app.writable(data["object_id"], scope)
    return s.annotate(
        data["object_id"],
        data["revision"],
        data.get("anchor", {}),
        data["text"],
    )


def record_review(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    target = app.writable(data["object_id"], scope)
    reviewed = s.get(target["id"], data["revision"])
    report = app.get(data["review_object_id"], scope, data["review_revision"])
    require(report["kind"] in {"report", "note"}, "审阅依据需要可读报告或笔记")
    require(
        report["project_id"] == target["project_id"]
        or target["project_id"] in report["metadata"].get("shared_with", []),
        "审阅依据尚未授权给目标项目",
        "forbidden",
        403,
    )
    require(
        data.get("verdict")
        in {"needs_revision", "usable_for_discussion", "reviewed_with_limits"},
        "审阅判断不支持；此操作不授予科学批准或用户验收",
    )
    require(
        data.get("scope", "").strip()
        and data.get("summary", "").strip()
        and data.get("reviewer_reference", "").strip(),
        "需要审阅范围、具体判断与审阅者来源",
    )
    return s.record_review(
        target["id"],
        reviewed["revision"],
        {
            **{
                k: data[k]
                for k in (
                    "review_object_id",
                    "review_revision",
                    "verdict",
                    "scope",
                    "summary",
                    "reviewer_reference",
                )
            },
            "review_source_sha256": digest(report),
        },
    )


def update_annotation(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    app.writable(data["object_id"], scope)
    changes = {key: data[key] for key in ("text", "status") if key in data}
    return s.update_annotation(data["id"], data["object_id"], **changes)


def change_dependency(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    action = data["action"]
    rel = next((r for r in s.relations() if r["id"] == data["id"]), None)
    require(rel, "引用不存在", "not_found", 404)
    app.writable(rel["src"], scope)
    app.get(rel["dst"], scope)
    updated = s.accept_dependency(
        data["id"],
        data["target_revision"],
        action.endswith("accept"),
        expected_relation_revision=data.get("relation_revision"),
        expected_source_revision=data.get("expected_revision"),
    )
    return [relation for relation in updated if app.relation_allowed(relation, scope)]
