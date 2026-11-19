"""资产、导入与成果导出；调用前由公共分派层完成作用域检查。"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from research_partner.contracts import JsonObject, Scope
import copy
from research_partner.storage.store import require, now

if TYPE_CHECKING:
    from research_partner.app import App


def inspect_asset(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    project = app.writable(data.get("project_id"), scope)
    require(project["kind"] == "project", "请选择资产所属项目")
    asset = app.asset(data.get("sha"), scope, project["id"])
    with (s.blobs / asset["sha"]).open("rb") as source:
        header = source.read(24)
    detected = (
        "png"
        if header.startswith(b"\x89PNG\r\n\x1a\n")
        else "jpeg"
        if header.startswith(b"\xff\xd8\xff")
        else None
    )
    supported = bool(
        detected
        and asset["media_type"] == {"png": "image/png", "jpeg": "image/jpeg"}[detected]
    )
    return {k: asset[k] for k in ["sha", "url", "filename", "media_type"]} | {
        "byte_size": asset["size"],
        "project_id": project["id"],
        "supported_image": supported,
        "detected_format": detected,
        "validation": "Stored SHA and PNG/JPEG signature plus registered MIME checked; full image decoding is not implied.",
    }


def import_asset(app: App, data: JsonObject, scope: Scope) -> Any:
    return app.import_asset(data, scope)


def import_object(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    app.writable(data["project_id"], scope)
    app.asset(data["asset_sha"], scope, data["project_id"])
    from research_partner.rendering.engine import ArtifactEngine

    return ArtifactEngine(s, app.config.get("rendering", {})).import_document(
        data["asset_sha"],
        kind=data.get("kind", "report"),
        title=data.get("title"),
        project_id=data["project_id"],
    )


def authorize_code(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    require(scope is None, "仅所有者可授权运行导入脚本", "forbidden", 403)
    obj = app.get(data["id"])
    require(
        data.get("approved") is True and data.get("reason"),
        "需要明确授权及其范围",
    )
    require(
        obj["revision"] == data["expected_revision"],
        "脚本对象已更新，需重新审查",
        "conflict",
        409,
    )
    script = obj["content"].get("script_asset")
    require(script, "此对象没有待执行脚本")
    s.asset(script)
    s.set_setting(
        "code_grant:" + obj["id"],
        {"script_sha": script, "reason": data["reason"], "at": now()},
    )
    return {"authorized_script_sha": script}


def export_object(app: App, data: JsonObject, scope: Scope) -> Any:
    s = app.store
    action = data["action"]
    obj = app.writable(data["id"], scope)
    from research_partner.domains.figures.definition import is_definition

    require(
        action != "figure.render" or not is_definition(obj),
        "主图使用组成渲染，不通过单脚本图的修改入口",
        "file_authority",
        409,
    )
    from research_partner.rendering.engine import ArtifactEngine

    engine = ArtifactEngine(s, app.config.get("rendering", {}))
    require(
        obj["revision"] == data.get("expected_revision", obj["revision"]),
        "成果已更新",
        "conflict",
        409,
    )
    grant = s.setting("code_grant:" + obj["id"], {})
    allowed_code = bool(
        grant and grant.get("script_sha") == obj["content"].get("script_asset")
    )
    if action == "figure.render":
        content = copy.deepcopy(obj["content"])
        if data.get("overlays") is not None:
            content["overlays"] = data["overlays"]
        if data.get("input_assets") is not None:
            content["input_assets"] = data["input_assets"]
        if content != obj["content"]:
            obj = s.save(
                obj["id"],
                obj["revision"],
                content=content,
                reason="explicit figure source update",
                merge=False,
            )
        result = engine.render_figure(obj, authorized_code=allowed_code)
    else:
        obj = app.get(obj["id"], scope, data.get("revision", obj["revision"]))
        result = engine.export(obj, data["format"], authorized_code=allowed_code)
    s.record_export(obj["id"], obj["revision"], result)
    return {**result, "object": app.render_view(obj, scope)}
