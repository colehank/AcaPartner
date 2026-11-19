"""Render-time, explicit Artist drag coordinates. No code execution or data edits.

The matrix converts screen deltas normalized by the complete rendered figure
width/height to setter deltas. It is never inferred from a hit rectangle.
"""
from __future__ import annotations

import math
from numbers import Real
import sys


def figure_axes(fig):
    """Unique root/SubFigure axes plus inset child axes, in stable tree order."""
    seen = set()
    def visit(ax):
        if id(ax) in seen:
            return
        seen.add(id(ax))
        yield ax
        for child in getattr(ax, "child_axes", []):
            yield from visit(child)
    for ax in fig.axes:
        yield from visit(ax)


def figure_containers(fig):
    yield fig
    for child in getattr(fig, "subfigs", []):
        yield from figure_containers(child)


def artist_parent_figure(artist, root):
    try:
        return artist.get_figure(root=False) or root
    except TypeError:  # Matplotlib before the root keyword.
        return artist.get_figure() or root


def axes_position_reason(ax):
    if getattr(ax, "name", "rectilinear") != "rectilinear":
        return "投影/三维轴暂不支持位置覆盖。"
    if ax.get_axes_locator() is not None:
        return "子轴或色条由 locator 定位；重绘会重新计算位置，暂不支持拖动。"
    if ax.get_aspect() != "auto":
        return "此轴保持固定数据纵横比；为避免重绘改回位置，暂不支持拖动。"
    return None


def artist_interaction(artist, description, fig, width, height):
    def disabled(reason):
        return {"version": 1, "drag": {"enabled": False, "reason": reason}}

    typ = description.get("type")
    if typ not in {"axes", "text", "title", "xlabel", "ylabel", "legend"}:
        return disabled("此 Artist 仅支持样式编辑；移动数据点不属于视觉覆盖。")
    matplotlib = sys.modules.get("matplotlib")
    if matplotlib is not None and matplotlib.rcParams.get("savefig.bbox"):
        return disabled("导出启用了裁边，屏幕与完整 Figure 坐标未绑定；请用属性值编辑。")
    layout = getattr(fig, "get_layout_engine", lambda: None)()
    placeholder = layout is not None and type(layout).__module__ == "matplotlib.layout_engine" and type(layout).__name__ == "PlaceHolderLayoutEngine"
    if layout is not None and not placeholder:
        return disabled("自动布局会在导出时重排坐标；请固定布局后重绘，或使用属性值编辑。")
    if not all(math.isfinite(x) and x > 0 for x in (width, height)):
        return disabled("渲染尺寸不完整，请重新渲染。")
    prop = "bbox_to_anchor" if typ == "legend" else "position"
    value = description.get(prop)
    if not isinstance(value, (list, tuple)) or len(value) not in (2, 4) or any(isinstance(x, bool) or not isinstance(x, Real) or not math.isfinite(x) for x in value):
        return disabled("缺少可重放的位置值。")
    try:
        if typ == "axes":
            reason = axes_position_reason(artist)
            if reason:
                return disabled(reason)
            # set_position is local to its immediate Figure or SubFigure.
            parent = artist_parent_figure(artist, fig).bbox
            matrix = [[width / parent.width, 0.0], [0.0, -height / parent.height]]
        elif typ == "legend":
            if description.get("loc") in (0, "best"):
                return disabled("自动 best 图例会重新选择位置；先设定固定 loc 并重绘，再拖动。")
            parent = artist.axes.bbox if artist.axes is not None else artist_parent_figure(artist, fig).bbox
            if parent.width <= 0 or parent.height <= 0:
                return disabled("图例父坐标尺寸无效。")
            matrix = [[width / parent.width, 0.0], [0.0, -height / parent.height]]
        else:
            transform = artist.get_transform()
            if not transform.is_affine:
                return disabled("此 Artist 使用非线性坐标；请用确切属性值编辑并重绘。")
            inverse = transform.inverted().get_matrix()
            matrix = [[float(inverse[0, 0]) * width, -float(inverse[0, 1]) * height],
                      [float(inverse[1, 0]) * width, -float(inverse[1, 1]) * height]]
        if any(not math.isfinite(x) for row in matrix for x in row):
            return disabled("Artist 坐标无法有限求逆。")
        determinant = matrix[0][0] * matrix[1][1] - matrix[0][1] * matrix[1][0]
        if determinant == 0:
            return disabled("Artist 坐标变换不可逆。")
    except Exception:
        return disabled("无法验证 Artist 坐标变换；请用属性值编辑并重绘。")
    return {"version": 1, "drag": {"enabled": True, "property": prop,
            "value": [float(x) for x in value], "delta_matrix": matrix,
            "screen_coordinates": "whole_figure_normalized_top_left",
            "source_canvas": [width, height]}}


def figure_region_anchor_status(anchor, obj, source_object=None, source_sha256=None, *,
                                export_records=(), current_source_sha256=None,
                                source_preview_sha256=None, current_preview_sha256=None):
    """Validate an image-region anchor against a server-resolved saved revision.

    Source objects/digests and export records MUST come from persisted history,
    never request/object metadata. The Store caller verifies registered asset
    bytes, MIME and ownership before passing records or static preview identities. Regions bind immutable
    displayed image bytes, not recovered individual scientific Artists.
    """
    if "figure_region" not in anchor:
        return None
    region, identity = anchor.get("figure_region") or {}, anchor.get("render_source") or {}
    if not isinstance(region, dict) or not isinstance(identity, dict):
        return "orphaned"
    box = region.get("bbox")
    if (region.get("coordinates") != "whole_figure_normalized_top_left"
            or not isinstance(box, (list, tuple)) or len(box) != 4
            or any(isinstance(x, bool) or not isinstance(x, Real) or not math.isfinite(x) for x in box)
            or min(box) < 0 or box[2] <= 0 or box[3] <= 0
            or box[0] + box[2] > 1 + 1e-9 or box[1] + box[3] > 1 + 1e-9
            or obj.get("kind") != "figure" or identity.get("object_id") != obj.get("id")
            or type(identity.get("revision")) is not int or identity["revision"] < 1):
        return "orphaned"
    if source_object is None or source_sha256 is None:
        return "unverified"
    if (source_object.get("kind") != "figure" or source_object.get("id") != obj.get("id") or source_object.get("revision") != identity.get("revision")
            or not identity.get("source_sha256") or source_sha256 != identity["source_sha256"]):
        return "orphaned"
    def registered_pngs(o, canonical_sha):
        images = []
        if canonical_sha is None:
            return images
        for record in export_records:
            if not isinstance(record, dict):
                continue
            result = record.get("result", {})
            if not isinstance(result, dict):
                continue
            proof = result.get("provenance", {})
            assets = result.get("assets", {})
            replay = result.get("replay", {})
            if not all(isinstance(value, dict) for value in (proof, assets, replay)):
                continue
            image = assets.get("figure.png", {})
            if ("preview_identity" in result or result.get("status") != "generated"
                    or replay.get("failures")
                    or type(record.get("revision")) is not int
                    or type(proof.get("revision")) is not int
                    or record.get("revision") != o.get("revision")
                    or proof.get("object_id") != o.get("id")
                    or proof.get("revision") != o.get("revision")
                    or proof.get("source_sha256") != canonical_sha
                    or not isinstance(image, dict) or image.get("media_type") != "image/png"
                    or not isinstance(image.get("sha"), str)):
                continue
            images.append(image["sha"])
        return images

    original_images = registered_pngs(source_object, source_sha256)
    image_sha = identity.get("preview_sha256")
    if not image_sha or (source_preview_sha256 != image_sha and image_sha not in original_images):
        return "orphaned"
    current_images = registered_pngs(obj, current_source_sha256)
    # The current formal PNG takes precedence over a retained old preview.
    # An old valid image anchor remains historical/unverified when it is no
    # longer the displayed image, rather than being silently reanchored.
    current_image = current_images[-1] if current_images else current_preview_sha256
    return "anchored" if current_image == image_sha else "unverified"


def figure_artist_anchor_status(anchor, obj, export_records):
    """Return a status for an explicitly registered-Artist anchor, else None.

    Call with persistent export records for this object (not user content).
    An absent current render is unverified, not proof that the Artist vanished.
    No arbitrary object_id is promoted to an Artist anchor.
    """
    if not anchor.get("artist_id"):
        return None
    identity = anchor.get("render_source") or {}
    if obj.get("kind") != "figure" or identity.get("object_id") != obj.get("id"):
        return "orphaned"
    def matches(record, revision, source_sha=None):
        result = record.get("result", {})
        provenance = result.get("provenance", {})
        return (record.get("revision") == revision and provenance.get("object_id") == obj["id"]
                and provenance.get("revision") == revision
                and (source_sha is None or provenance.get("source_sha256") == source_sha))
    original = [r for r in export_records if matches(r, identity.get("revision"), identity.get("source_sha256"))]
    if not identity.get("source_sha256") or not any(any(m.get("id") == anchor["artist_id"] for m in r["result"].get("manifest", [])) for r in original):
        return "orphaned"
    current = [r for r in export_records if matches(r, obj.get("revision"))]
    if not current:
        return "unverified"
    return "anchored" if any(m.get("id") == anchor["artist_id"] for m in current[-1]["result"].get("manifest", [])) else "orphaned"
