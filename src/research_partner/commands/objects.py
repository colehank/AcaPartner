"""项目与研究对象生命周期；调用前由公共分派层完成作用域检查。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from research_partner.contracts import JsonObject, Scope
from research_partner.storage.store import require

if TYPE_CHECKING:
    from research_partner.app import App


from research_partner.storage.store import uid

KINDS = {
    "report",
    "note",
    "paper",
    "figure",
    "diagram",
    "poster",
    "slides",
    "workshop",
    "workshop_note",
    "concept",
    "question",
    "literature",
    "commission",
    "growth",
    "dataset",
    "recipe",
}


def default_content(kind):
    if kind in {"report", "note", "paper", "commission"}:
        return {
            "blocks": [{"id": uid("BLOCK"), "kind": "paragraph", "text": ""}],
            "citations": [],
        }
    if kind == "diagram":
        return {"nodes": [], "edges": []}
    if kind in {"poster", "slides"}:
        return {
            "units": "cm",
            "pages": [
                {
                    "id": uid("PAGE"),
                    "width": 80 if kind == "poster" else 33.867,
                    "height": 120 if kind == "poster" else 19.05,
                    "objects": [],
                    "notes": "",
                }
            ],
        }
    if kind == "figure":
        return {
            "input_assets": {},
            "overlays": [],
            "spec": {"kind": "line", "x": [], "series": []},
        }
    return {}


def create_project(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    require(scope is None, "受限客户端不能创建项目", "forbidden", 403)
    from research_partner.domains.manuscripts.workspace import initialize_output

    with s.transaction() as connection:
        project = s.create(
            "project",
            data["title"],
            content=data.get("content", {}),
            metadata=data.get("metadata", {}),
            connection=connection,
        )
        result = initialize_output(s, connection, project)
    return {
        **result["project"],
        "primary_manuscript_id": result["manuscript"]["id"],
    }


def feature_project(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    project = app.writable(data["project_id"], scope)
    require(project["kind"] == "project", "需要所属项目")
    obj = app.get(data["object_id"], scope)
    require(
        obj["project_id"] == project["id"]
        and obj["kind"]
        in {
            "report",
            "note",
            "paper",
            "figure",
            "diagram",
            "poster",
            "slides",
            "workshop",
            "commission",
        }
        and not obj["archived"],
        "请选择本项目未归档成果",
    )
    require(type(data.get("featured")) is bool, "需要明确置顶或取消置顶")
    ids = list(dict.fromkeys(project["metadata"].get("featured_objects", [])))
    if data["featured"] and obj["id"] not in ids:
        ids.append(obj["id"])
    if not data["featured"]:
        ids = [x for x in ids if x != obj["id"]]
    require(len(ids) <= 12, "重点成果最多12项；其他成果仍可在工作台打开")
    return s.save(
        project["id"],
        data["expected_revision"],
        metadata={**project["metadata"], "featured_objects": ids},
        reason="explicit project highlight selection",
        merge=False,
    )


def accept_workshop(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    obj = app.writable(data["id"], scope)
    require(obj["kind"] == "workshop", "需要工坊产物")
    records = obj["content"].get("acceptance", [])
    records = records if isinstance(records, list) else [records]
    content = {
        **obj["content"],
        "acceptance": [
            *records,
            {k: data.get(k, "") for k in ("status", "evidence", "limitations")},
        ],
    }
    return s.save(
        obj["id"],
        data["expected_revision"],
        content=content,
        reason="explicit technical acceptance; no scientific approval",
        merge=False,
    )


def save_object(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    action = data["action"]
    obj = app.writable(data["id"], scope)
    from research_partner.domains.figures.definition import is_definition

    require(
        not is_definition(obj) or action == "object.archive",
        "文件优先的主图必须通过组成文件服务修改",
        "file_authority",
        409,
    )
    require(
        not isinstance(data.get("content"), dict)
        or not data["content"].get("definition_schema"),
        "主图文件身份只能由定义服务登记",
        "file_authority",
        409,
    )
    archived = (
        action.endswith("archive")
        if action in {"project.archive", "project.restore", "object.archive"}
        else data.get("archived")
    )
    result = s.save(
        obj["id"],
        data["expected_revision"],
        content=data.get("content"),
        title=data.get("title"),
        metadata=data.get("metadata"),
        archived=archived,
    )
    if app.runner:
        app.runner.stop_revoked()
    return result


def create_object(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    kind = data["kind"]
    require(kind in KINDS, "不支持的成果类型")
    require(
        not isinstance(data.get("content"), dict)
        or not data["content"].get("definition_schema"),
        "主图定义须经文件服务创建",
        "file_authority",
        409,
    )
    app.writable(data["project_id"], scope)
    obj = s.create(
        kind,
        data["title"],
        data["project_id"],
        data.get("content", default_content(kind)),
        data.get("metadata", {}),
    )
    s.relate(data["project_id"], obj["id"], "contains", "confirmed")
    return obj


def restore_object(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    obj = app.writable(data["id"], scope)
    from research_partner.domains.figures.definition import is_definition

    require(
        not is_definition(obj),
        "主图历史仍保留；恢复须通过定义文件的明确新修订",
        "file_authority",
        409,
    )
    result = s.restore(data["id"], data["revision"], data["expected_revision"])
    if app.runner:
        app.runner.stop_revoked()
    return result
