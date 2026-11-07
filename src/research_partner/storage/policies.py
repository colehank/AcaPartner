"""在调用方的写事务内校验研究对象，不自行创建连接或事务。"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any, Protocol

from research_partner.storage.store import require


class ObjectPolicyStore(Protocol):
    def get(
        self,
        ident: str | None,
        revision: int | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> Mapping[str, Any]: ...

    def reference_ids(self, value: Any) -> set[str]: ...


def require_member_snapshot_runtime(
    connection: sqlite3.Connection, obj: Mapping[str, Any]
) -> None:
    if (
        obj.get("kind") == "dataset"
        and obj.get("content", {}).get("authority_kind") == "immutable_member_manifest"
    ):
        from research_partner.packaging.compatibility import require_features

        require_features(connection, ["chunked_member_snapshot_v1"])


def require_figure_layout_runtime(
    connection: sqlite3.Connection, obj: Mapping[str, Any]
) -> None:
    if obj.get("kind") != "figure":
        return
    layers = obj.get("content", {}).get("overlays", [])
    targets = (
        list(layers)
        if isinstance(layers, dict)
        else [
            layer.get("target") or layer.get("object_id") or layer.get("id")
            for layer in layers
            if isinstance(layer, dict)
        ]
        if isinstance(layers, list)
        else []
    )
    if any(
        target == "figure:root"
        or isinstance(target, str)
        and target.startswith("colorbar:")
        for target in targets
    ):
        from research_partner.packaging.compatibility import require_features

        require_features(connection, ["figure_visual_layout_v1"])


def require_manuscript_format_runtime(
    connection: sqlite3.Connection, obj: Mapping[str, Any]
) -> None:
    if "manuscript_format" not in obj.get("metadata", {}):
        return
    require(
        obj.get("kind") in {"report", "note", "paper", "workshop_note"},
        "格式配置只适用于文稿",
    )
    from research_partner.domains.manuscripts.formatting import normalize_format

    normalize_format(obj["metadata"]["manuscript_format"])
    from research_partner.packaging.compatibility import require_features

    require_features(connection, ["manuscript_format_v1"])


def require_paper_source_runtime(
    connection: sqlite3.Connection, obj: Mapping[str, Any]
) -> None:
    if obj["kind"] == "paper":
        from research_partner.domains.manuscripts.paper_sources import source_state

        state = source_state(obj)
        if state["selection_explicit"]:
            from research_partner.packaging.compatibility import require_features

            require_features(connection, ["paper_source_selection_v1"])


def validate_article_object(
    store: ObjectPolicyStore, connection: sqlite3.Connection, obj: Mapping[str, Any]
) -> None:
    if obj["kind"] == "workshop_note":
        from research_partner.domains.manuscripts.workspace import sections
        from research_partner.packaging.compatibility import require_features

        require_features(connection, ["article_workspace_v1"])
        content = obj["content"]
        manuscript = store.get(content.get("manuscript_id"), connection=connection)
        require(
            manuscript["kind"] in {"paper", "report"}
            and manuscript["project_id"] == obj["project_id"],
            "工坊笔记必须关联本项目稿件",
            "article_note_conflict",
            409,
        )
        matches = [
            s for s in sections(manuscript) if s["id"] == content.get("section_id")
        ]
        require(
            len(matches) == 1
            and matches[0]["anchor_valid"]
            and matches[0]["heading_block_id"] == content.get("section_block_id"),
            "工坊笔记章节身份不符",
            "article_note_conflict",
            409,
        )
    if obj["kind"] in {
        "paper",
        "report",
        "note",
        "figure",
        "diagram",
        "poster",
        "slides",
    }:
        for ident in store.reference_ids(obj["content"]):
            row = connection.execute(
                "SELECT kind FROM objects WHERE id=?", (ident,)
            ).fetchone()
            require(
                not row or row["kind"] != "workshop_note",
                "准备笔记不能成为成果正文/导出的依赖",
                "preparation_boundary",
                409,
            )


def validate_object_policies(
    store: ObjectPolicyStore,
    connection: sqlite3.Connection,
    obj: Mapping[str, Any],
    *,
    saving: bool = False,
) -> None:
    validate_article_object(store, connection, obj)
    require_figure_layout_runtime(connection, obj)
    require_manuscript_format_runtime(connection, obj)
    require_member_snapshot_runtime(connection, obj)
    if saving:
        require(isinstance(obj["title"], str) and obj["title"].strip(), "标题不能为空")
    require_paper_source_runtime(connection, obj)
