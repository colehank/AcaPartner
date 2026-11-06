"""Process entry point for optional artifact dependencies; request/response JSON."""

from __future__ import annotations
import base64
import contextlib
import hashlib
import importlib.metadata
import json
import math
import mimetypes
from pathlib import Path
import re
import runpy
import sys
import traceback
import xml.etree.ElementTree as ET

# This worker may be launched directly by an existing scientific environment.
try:
    from .figure_interaction import (
        artist_interaction,
        figure_axes,
        figure_containers,
        artist_parent_figure,
        axes_position_reason,
    )
except ImportError:
    from figure_interaction import (
        artist_interaction,
        figure_axes,
        figure_containers,
        artist_parent_figure,
        axes_position_reason,
    )

try:
    from .process_output import (
        BoundedTextCapture,
        DEFAULT_OUTPUT_LIMIT_BYTES,
        OutputBudget,
        OutputLimitExceeded,
    )
except ImportError:
    from process_output import (
        BoundedTextCapture,
        DEFAULT_OUTPUT_LIMIT_BYTES,
        OutputBudget,
        OutputLimitExceeded,
    )


def figure_property_schema(artist, typ, fig, owner_axes=None):
    """Describe setter input coordinates, never the screen-normalized hit box."""
    schema = {}
    if typ == "figure":
        schema["figsize"] = {
            "type": "number_tuple",
            "lengths": [2],
            "minimum": 1,
            "maximum": 24,
            "coordinates": "Figure 宽、高（英寸）；1–24，输出160 DPI，最多16百万像素。",
        }
        for key in ("left", "right", "bottom", "top", "wspace", "hspace"):
            schema["subplot_" + key] = {
                "type": "number",
                "minimum": 0,
                "maximum": 2 if key.endswith("space") else 1,
                "coordinates": "子图平均宽/高的比例"
                if key.endswith("space")
                else "Figure 归一化边界；left < right，bottom < top。",
            }
    elif typ in {"axes", "colorbar"}:
        schema["position"] = {
            "type": "number_tuple",
            "lengths": [4],
            "coordinates": "所属 Figure/SubFigure 归一化坐标 [left, bottom, width, height]；原点左下，宽高须大于零。",
        }
    elif typ != "spine" and hasattr(artist, "get_position"):
        transform = artist.get_transform()
        ax = owner_axes if owner_axes is not None else getattr(artist, "axes", None)
        parent = artist_parent_figure(artist, fig)
        if transform == fig.transFigure or transform == getattr(
            parent, "transSubfigure", None
        ):
            coordinates = "所属 Figure/SubFigure 归一化 [x, y]；原点左下。"
        elif ax is not None and transform == ax.transData:
            coordinates = "原 Axes 数据坐标 [x, y]（保留脚本设置的比例/变换）。"
        elif ax is not None and transform == ax.transAxes:
            coordinates = "Axes 归一化 [x, y]；原点左下。"
        elif typ in {"xlabel", "ylabel"}:
            _, standard = label_position_transform(artist, typ, fig, ax)
            if standard:
                mixed = (
                    "x 为 Axes 比例、y 为基准显示像素"
                    if typ == "xlabel"
                    else "x 为基准显示像素、y 为 Axes 比例"
                )
                coordinates = f"[x, y]；{mixed}（脚本基准 DPI={fig.dpi:g}，原点左下），导出按 DPI 同比例换算。不是命中框比例。"
            else:
                coordinates = (
                    "保留脚本自定义轴标签变换的 [x, y]；需核对脚本，不是命中框比例。"
                )
        elif typ == "title":
            coordinates = "保留原标题变换 [x, y]；默认 Axes 比例加标题点数偏移。自定义脚本可改变此变换；不是命中框比例。"
        else:
            coordinates = "保留脚本原 Artist 变换的 [x, y]；自定义坐标，需核对脚本。不是命中框比例。"
        schema["position"] = {
            "type": "number_tuple",
            "lengths": [2],
            "coordinates": coordinates,
            "transform_type": type(transform).__name__,
        }
    if typ == "legend":
        parent = "Axes" if artist.axes is not None else "Figure"
        schema["bbox_to_anchor"] = {
            "type": "number_tuple",
            "lengths": [2, 4],
            "coordinates": parent
            + " 归一化锚点 [x, y] 或 [x, y, width, height]；原点左下。与 loc 配合；编辑后明确采用父坐标，替换脚本自定义 anchor 变换。",
        }
    if typ == "collection":
        schema["linewidth"] = {
            "type": "number_list",
            "minimum": 0,
            "coordinates": "线宽数组，单位 pt；按 Matplotlib 规则循环应用，不改变数据坐标。",
        }
        # Array-valued marker sizes may encode a scientific metric. Expose no
        # size setter: source code remains the authority for this encoding.
    if typ == "spine":
        schema["linewidth"] = {
            "type": "number",
            "minimum": 0,
            "coordinates": "轴线线宽，单位 pt；不改变数据坐标、范围或轴线几何。",
        }
    return schema


def label_position_transform(artist, typ, fig, ax):
    """Retain native label units while scaling their display component at export DPI."""
    from matplotlib.transforms import (
        Affine2D,
        IdentityTransform,
        blended_transform_factory,
    )

    transform = artist.get_transform()
    if ax is None:
        return transform, False
    default = (
        blended_transform_factory(ax.transAxes, IdentityTransform())
        if typ == "xlabel"
        else blended_transform_factory(IdentityTransform(), ax.transAxes)
    )
    if transform != default:
        return transform, False
    pixels_at_source_dpi = Affine2D().scale(1 / fig.dpi) + fig.dpi_scale_trans
    return (
        blended_transform_factory(ax.transAxes, pixels_at_source_dpi)
        if typ == "xlabel"
        else blended_transform_factory(pixels_at_source_dpi, ax.transAxes)
    ), True


def validate_figure_property(key, value, schema):
    if key in {"visible", "frameon", "fill"} and type(value) is not bool:
        raise ValueError("Boolean property requires true or false")
    if key in {"position", "bbox_to_anchor"}:
        rule = schema.get(key, {})
        if (
            not isinstance(value, (list, tuple))
            or len(value) not in rule.get("lengths", [])
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in value)
        ):
            raise ValueError(
                "Position requires a finite numeric tuple of the advertised length"
            )
        if (
            key == "position"
            and 4 in rule.get("lengths", [])
            and (value[2] <= 0 or value[3] <= 0)
        ):
            raise ValueError("Axes width and height must be positive")
    if key == "rotation" and (
        type(value) not in (int, float) or not math.isfinite(value)
    ):
        raise ValueError("Rotation requires a finite number")
    rule = schema.get(key, {})
    if rule.get("type") == "number":
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not rule.get("minimum", -math.inf)
            <= value
            <= rule.get("maximum", math.inf)
        ):
            raise ValueError(
                "Property requires a finite number within its advertised bounds"
            )
    if key == "figsize":
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 2
            or any(
                type(v) not in (int, float) or not math.isfinite(v) or not 1 <= v <= 24
                for v in value
            )
            or value[0] * value[1] * 160**2 > 16_000_000
        ):
            raise ValueError(
                "Figure size must be 1–24 inches per dimension and at most 16 million output pixels"
            )
    if rule.get("type") == "number_list":
        if (
            not isinstance(value, (list, tuple))
            or not value
            or any(
                type(v) not in (int, float)
                or not math.isfinite(v)
                or v < rule.get("minimum", -math.inf)
                for v in value
            )
        ):
            raise ValueError(
                "Property requires a nonempty finite numeric array within its advertised bounds"
            )


def subplot_layout_reason(fig):
    """Only expose subplots_adjust where its coordinate contract is unambiguous."""
    engine = getattr(fig, "get_layout_engine", lambda: None)()
    placeholder = (
        engine is not None
        and type(engine).__name__ == "PlaceHolderLayoutEngine"
        and type(engine).__module__ == "matplotlib.layout_engine"
    )
    if engine is not None and not placeholder:
        return "自动布局仍在控制子图；本轮不覆盖布局引擎。"
    if getattr(fig, "subfigs", []):
        return "SubFigure 层级独立定位；不以根子图间距覆盖。"
    axes = list(figure_axes(fig))
    if not axes:
        return "没有可调整的子图网格。"
    grids = set()
    for ax in axes:
        if getattr(ax, "_colorbar", None) is not None:
            return "色条和父图布局联动；请分别使用已支持的位置控制。"
        if axes_position_reason(ax):
            return "含 locator、固定纵横比或投影轴，不能用普通网格重排。"
        spec = getattr(ax, "get_subplotspec", lambda: None)()
        if spec is None:
            return "含独立 add_axes/inset 位置，不是统一子图网格。"
        grid = spec.get_gridspec()
        if (
            type(grid).__name__ != "GridSpec"
            or type(grid).__module__ != "matplotlib.gridspec"
        ):
            return "嵌套或自定义网格需要独立布局控制。"
        # Explicit GridSpec settings override Figure.subplotpars.
        if any(
            getattr(grid, key, None) is not None
            for key in ("left", "right", "bottom", "top", "wspace", "hspace")
        ):
            return "GridSpec 自有边距或间距，不能声明 Figure 调整已生效。"
        grids.add(id(grid))
    return None if len(grids) == 1 else "存在多个独立网格，不能用一个间距值重排。"


def scalar_encoding(artist):
    """Read-only scalar/color semantics; no norm/clim setters are offered."""
    import matplotlib.colors as colors

    norm = getattr(artist, "norm", None)
    known = [
        getattr(colors, name, None)
        for name in (
            "Normalize",
            "NoNorm",
            "BoundaryNorm",
            "LogNorm",
            "SymLogNorm",
            "PowerNorm",
            "TwoSlopeNorm",
            "CenteredNorm",
            "AsinhNorm",
        )
    ]
    if norm is None:
        return None

    def serial(value):
        return json.loads(json.dumps(value, default=lambda x: x.tolist()))

    params = {
        key: serial(getattr(norm, key))
        for key in (
            "vmin",
            "vmax",
            "clip",
            "gamma",
            "vcenter",
            "halfrange",
            "linthresh",
            "linscale",
            "boundaries",
            "Ncmap",
            "extend",
            "linear_width",
        )
        if hasattr(norm, key)
    }
    # Scale internals define Log/SymLog base and transition behavior.
    scale = getattr(norm, "_scale", None)
    if scale is not None:
        params["scale"] = {
            key: serial(getattr(scale, key))
            for key in ("base", "linthresh", "linscale", "linear_width")
            if hasattr(scale, key)
        }
    return {
        "norm_class": type(norm).__module__ + "." + type(norm).__name__,
        "known_norm": type(norm) in known,
        "clim": serial(artist.get_clim()),
        "parameters": params,
        "editable": False,
    }


def colorbar_position_reason(colorbar, fig):
    ax = colorbar.ax
    engine = getattr(fig, "get_layout_engine", lambda: None)()
    if engine is not None and type(engine).__name__ != "PlaceHolderLayoutEngine":
        return "自动布局控制色条位置；本轮不取消布局引擎。"
    locator = ax.get_axes_locator()
    known = locator is None or (
        type(locator).__module__ == "matplotlib.colorbar"
        and type(locator).__name__ == "_ColorbarAxesLocator"
        and getattr(locator, "_orig_locator", None) is None
    )
    if (
        not known
        or ax.get_aspect() != "auto"
        or ax.name != "rectilinear"
        or colorbar.extend != "neither"
    ):
        return "自定义定位、扩展三角或固定比例色条暂不支持位置覆盖。"
    return None


def colorbar_tick_state(colorbar):
    """Actual displayed values/text, including user-installed Axis formatters."""
    axis = (
        colorbar.ax.yaxis if colorbar.orientation == "vertical" else colorbar.ax.xaxis
    )
    return {
        "major_values": axis.get_majorticklocs().tolist(),
        "major_labels": [label.get_text() for label in axis.get_majorticklabels()],
        "minor_values": axis.get_minorticklocs().tolist(),
        "minor_labels": [label.get_text() for label in axis.get_minorticklabels()],
        "offset_text": axis.get_offset_text().get_text(),
    }


def colorbar_tick_contract(colorbar):
    axis = (
        colorbar.ax.yaxis if colorbar.orientation == "vertical" else colorbar.ax.xaxis
    )
    return {
        "axis": axis,
        "major_locator": axis.get_major_locator(),
        "minor_locator": axis.get_minor_locator(),
        "major_formatter": axis.get_major_formatter(),
        "minor_formatter": axis.get_minor_formatter(),
        "state": colorbar_tick_state(colorbar),
    }


def restore_colorbar_ticks(colorbar, contract):
    """set_cmap callbacks can reset direct Axis settings via Colorbar internals.

    Retain the exact source objects, not rounded labels inferred from new ticks.
    Data ranges, norms and user-specified tick semantics remain source-owned.
    """
    axis = contract["axis"]
    for name in (
        "major_locator",
        "minor_locator",
        "major_formatter",
        "minor_formatter",
    ):
        getattr(axis, "set_" + name)(contract[name])
    # Colorbar.update_normal/update_ticks consult these cached objects during
    # later draw/export callbacks. Source code may have configured only the Axis.
    colorbar._locator = contract["major_locator"]
    colorbar._minorlocator = contract["minor_locator"]
    colorbar._formatter = contract["major_formatter"]
    colorbar._minorformatter = contract["minor_formatter"]


def stable(value):
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def runtime(*packages):
    versions = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "unavailable"
    return {
        "executable": sys.executable,
        "executable_sha256": hashlib.sha256(
            Path(sys.executable).read_bytes()
        ).hexdigest(),
        "python_version": sys.version,
        "packages": versions,
    }


BUILTIN_SOURCE = """# Generated, reproducible renderer; no fitting or statistical recomputation.
# Inputs are registered copies. Spec maps input table columns to plotted values.
def build_figure(inputs, parameters):
    import csv, json
    from pathlib import Path
    import matplotlib.pyplot as plt
    spec = parameters["spec"]
    fig, ax = plt.subplots(figsize=spec.get("figsize", [7, 4.5]))
    ax.set_gid("axes:main")
    for i, series in enumerate(spec.get("series", [])):
        if "input" in series:
            source = Path(inputs[str(series["input"])])
            if source.suffix.lower() == ".json":
                rows = json.loads(source.read_text())
                if isinstance(rows, dict): rows = rows[series.get("rows_key", "rows")]
            else:
                with source.open(newline="") as stream:
                    rows = list(csv.DictReader(stream, delimiter="\\t" if source.suffix.lower() == ".tsv" else ","))
            x = [float(row[series["x"]]) for row in rows]
            y = [float(row[series["y"]]) for row in rows]
        else:
            # JavaScript JSON serializes 192.0 as 192. Use the same numeric
            # convention as registered tabular inputs before creating Artists.
            x = [float(value) for value in series["x"]]
            y = [float(value) for value in series["y"]]
        if len(x) != len(y): raise ValueError("Series x/y lengths differ")
        line, = ax.plot(x, y, label=series.get("label", series.get("id", str(i))), **series.get("style", {}))
        line.set_gid("line:" + str(series.get("id", i)))
    ax.set_title(spec.get("title", ""))
    ax.set_xlabel(spec.get("xlabel", ""))
    ax.set_ylabel(spec.get("ylabel", ""))
    if spec.get("legend", True) and spec.get("series"): ax.legend()
    fig.tight_layout()
    return fig
"""


def patch_geometry(artist):
    """Scientific geometry before display/axes transforms; no style or pixels."""
    from matplotlib.patches import (
        Rectangle,
        Ellipse,
        Arc,
        Polygon,
        Wedge,
        PathPatch,
        FancyBboxPatch,
    )

    if isinstance(artist, Rectangle):
        return {
            "xy": list(artist.get_xy()),
            "width": artist.get_width(),
            "height": artist.get_height(),
            "angle": artist.angle,
            "rotation_point": artist.rotation_point,
        }
    if isinstance(artist, Ellipse):
        value = {
            "center": list(artist.center),
            "width": artist.width,
            "height": artist.height,
            "angle": artist.angle,
        }
        if isinstance(artist, Arc):
            value.update(theta1=artist.theta1, theta2=artist.theta2)
        return value
    if isinstance(artist, Wedge):
        return {
            "center": list(artist.center),
            "r": artist.r,
            "width": artist.width,
            "theta1": artist.theta1,
            "theta2": artist.theta2,
        }
    if isinstance(artist, Polygon):
        return {"xy": artist.get_xy().tolist(), "closed": artist.get_closed()}
    if isinstance(artist, PathPatch):
        path = artist.get_path()
        return {
            "vertices": path.vertices.tolist(),
            "codes": None if path.codes is None else path.codes.tolist(),
        }
    if isinstance(artist, FancyBboxPatch):
        return {"bounds": list(artist.get_bbox().bounds)}
    return None


def numeric_snapshot(fig):
    """Schema 3: raw values, dtypes, masks and scientific geometry, not pixels.

    Includes inset axes, scatter offsets, mesh coordinates, image extents and
    supported patch geometry. Unknown projection/patch internals remain explicit
    coverage gaps rather than a promise to verify arbitrary custom Artists.
    """
    import numpy as np

    def array(value):
        if value is None:
            return None
        value = np.ma.asarray(value)
        return {
            "values": value.data.tolist(),
            "mask": np.ma.getmaskarray(value).tolist(),
            "dtype": str(value.dtype),
            "shape": list(value.shape),
        }

    values = []
    for axis_index, ax in enumerate(figure_axes(fig)):
        axis_id = ax.get_gid() or "axes:" + str(axis_index)
        lines = []
        for index, line in enumerate(ax.lines):
            x, y = np.asarray(line.get_xdata()), np.asarray(line.get_ydata())
            line_value = {
                "id": line.get_gid() or axis_id + ":line:" + str(index),
                "type": type(line).__name__,
                "x": x.tolist(),
                "y": y.tolist(),
                "x_dtype": str(x.dtype),
                "y_dtype": str(y.dtype),
                "x_shape": list(x.shape),
                "y_shape": list(y.shape),
            }
            if hasattr(line, "get_data_3d"):
                line_value["data_3d"] = [array(v) for v in line.get_data_3d()]
            lines.append(line_value)
        collections = []
        for index, item in enumerate(ax.collections):
            paths = [
                {
                    "index": index,
                    "vertices": path.vertices.tolist(),
                    "codes": None if path.codes is None else path.codes.tolist(),
                    "vertex_count": len(path.vertices),
                    "vertex_dtype": str(path.vertices.dtype),
                }
                for index, path in enumerate(item.get_paths())
            ]
            offsets, scalar = array(item.get_offsets()), array(item.get_array())
            value = {
                "id": item.get_gid() or axis_id + ":collection:" + str(index),
                "type": type(item).__name__,
                "offsets": offsets["values"],
                "offset_mask": offsets["mask"],
                "offset_dtype": offsets["dtype"],
                "offset_shape": offsets["shape"],
                "offset_count": len(offsets["values"]),
                "array": None if scalar is None else scalar["values"],
                "array_identity": scalar,
                "paths": paths,
                "path_count": len(paths),
                "path_vertex_count": sum(path["vertex_count"] for path in paths),
                "path_coordinate_space": "artist_path_before_transform",
            }
            if hasattr(item, "get_coordinates"):
                value["coordinates"] = array(item.get_coordinates())
            if hasattr(item, "get_sizes"):
                value["sizes"] = array(item.get_sizes())
            if hasattr(item, "_offsets3d"):
                value["offsets3d"] = [array(v) for v in item._offsets3d]
            collections.append(value)
        images = [
            {
                "id": item.get_gid() or axis_id + ":image:" + str(index),
                "array": array(item.get_array()),
                "extent": list(item.get_extent()),
                "origin": item.origin,
            }
            for index, item in enumerate(ax.images)
        ]
        patches = [
            {
                "id": item.get_gid() or axis_id + ":patch:" + str(index),
                "type": type(item).__name__,
                "geometry": patch_geometry(item),
                "geometry_verified": patch_geometry(item) is not None,
            }
            for index, item in enumerate(ax.patches)
        ]
        values.append(
            {
                "schema_version": 3,
                "axes_id": axis_id,
                "projection": ax.name,
                "lines": lines,
                "collections": collections,
                "images": images,
                "patches": patches,
            }
        )
    encoded = json.dumps(
        values,
        sort_keys=True,
        allow_nan=True,
        separators=(",", ":"),
        default=lambda value: value.tolist(),
    )
    return hashlib.sha256(encoded.encode()).hexdigest(), json.loads(encoded)


@contextlib.contextmanager
def capture_legend_sources():
    """Capture exact original handles while legends are built, never infer labels."""
    from matplotlib.legend import Legend

    original = Legend._init_legend_box
    captured = {}

    def initialize(legend, handles, labels, *args, **kwargs):
        handles, labels = list(handles), list(labels)
        handler_map = legend.get_legend_handler_map()
        handlers = [
            legend.get_legend_handler(handler_map, handle) for handle in handles
        ]
        result = original(legend, handles, labels, *args, **kwargs)
        proxies = list(
            getattr(legend, "legend_handles", getattr(legend, "legendHandles", []))
        )
        texts, text_index, records = list(legend.get_texts()), 0, []
        if len(proxies) != min(len(handles), len(labels)):
            captured[legend] = None
            return result
        for index, (source, proxy, handler) in enumerate(
            zip(handles, proxies, handlers)
        ):
            text = (
                texts[text_index]
                if handler is not None and text_index < len(texts)
                else None
            )
            if handler is not None:
                text_index += 1
            records.append(
                {
                    "source": source,
                    "proxy": proxy,
                    "handler": handler,
                    "text": text,
                    "index": index,
                }
            )
        captured[legend] = records
        return result

    Legend._init_legend_box = initialize
    try:
        yield captured
    finally:
        Legend._init_legend_box = original


def legend_update_plan(fig, sources, artist, property_name):
    """Return atomic style targets or explicit reasons for an unsafe match."""
    from matplotlib.legend import Legend
    from matplotlib.legend_handler import (
        HandlerLine2D,
        HandlerPathCollection,
        HandlerPatch,
        HandlerLineCollection,
    )
    from matplotlib.lines import Line2D
    from matplotlib.collections import PathCollection, LineCollection
    from matplotlib.patches import Patch

    plans, failures = [], []

    def contains(source):
        return (
            source is artist
            or isinstance(source, (tuple, list))
            and any(contains(child) for child in source)
        )

    for legend in fig.findobj(Legend):
        if legend.axes is not None and legend.axes is not artist.axes:
            continue
        records = sources.get(legend)
        legend_id = legend.get_gid() or "unregistered_legend"
        if records is None:
            failures.append(
                {"legend": legend_id, "reason": "legend_source_mapping_unavailable"}
            )
            continue
        matches = [record for record in records if contains(record["source"])]
        if not matches:
            # Private/default labels explicitly exclude reference lines from an
            # automatic legend. Labelled-but-absent sources have no safe mapping.
            if str(artist.get_label() or "").startswith("_") or not artist.get_label():
                continue
            failures.append({"legend": legend_id, "reason": "legend_source_not_found"})
            continue
        for record in matches:
            handler, proxy = record["handler"], record["proxy"]
            supported = (
                (type(handler) is HandlerLine2D and isinstance(proxy, Line2D))
                or (
                    type(handler) is HandlerPathCollection
                    and isinstance(proxy, PathCollection)
                )
                or (type(handler) is HandlerPatch and isinstance(proxy, Patch))
                or (
                    type(handler) is HandlerLineCollection and isinstance(proxy, Line2D)
                )
            )
            if (
                record["source"] is not artist
                or not supported
                or getattr(handler, "_update_prop_func", None) is not None
                or (
                    property_name != "label"
                    and not hasattr(proxy, "set_" + property_name)
                )
            ):
                failures.append(
                    {
                        "legend": legend_id,
                        "handle_index": record["index"],
                        "reason": "legend_handler_unsupported",
                        "handler": type(handler).__name__,
                    }
                )
                continue
            # A proxy shared between two different originals is ambiguous even
            # if a custom script happened to give them identical labels/styles.
            if any(
                other["proxy"] is proxy and other["source"] is not artist
                for other in records
            ):
                failures.append(
                    {
                        "legend": legend_id,
                        "handle_index": record["index"],
                        "reason": "legend_proxy_ambiguous",
                    }
                )
                continue
            target = record["text"] if property_name == "label" else proxy
            plans.append(
                {
                    "legend": legend,
                    "legend_id": legend_id,
                    "record": record,
                    "target": target,
                }
            )
    return plans, failures


def figure(job, work):
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.rcParams["svg.fonttype"] = "none"
    import matplotlib.pyplot as plt
    import numpy as np

    source = Path(job["script"]) if job.get("script") else work / "plot_source.py"
    if not job.get("script"):
        source.write_text(BUILTIN_SOURCE)
    parameters = dict(job.get("parameters", {}))
    if not job.get("script"):
        parameters["spec"] = job["spec"]
    # Contract accepts build_figure(inputs, parameters); alternatively a script
    # can consume supplied INPUTS/PARAMETERS globals and expose `fig`.
    with capture_legend_sources() as legend_sources:
        namespace = runpy.run_path(
            str(source),
            init_globals={"INPUTS": job["inputs"], "PARAMETERS": parameters},
        )
        if callable(namespace.get("build_figure")):
            import inspect

            function = namespace["build_figure"]
            fig = (
                function(job["inputs"], parameters)
                if len(inspect.signature(function).parameters) > 1
                else function(job["inputs"])
            )
        else:
            fig = namespace.get("fig")
    if fig is None or not hasattr(fig, "savefig"):
        raise ValueError(
            "Script must return a Matplotlib Figure from build_figure(inputs, parameters), or expose fig"
        )
    objects, descriptors, warnings, owner_axes = {}, {}, [], {}

    def register(ident, artist, typ, properties, label="", owner=None):
        if ident in objects:
            raise ValueError("Duplicate plot object id: " + ident)
        objects[ident] = artist
        owner_axes[ident] = (
            owner if owner is not None else getattr(artist, "axes", None)
        )
        if hasattr(artist, "set_gid"):
            artist.set_gid(ident)
        groups = {"layout": [], "appearance": [], "content": []}
        for key in properties:
            group = (
                "layout"
                if key in {"figsize", "position", "bbox_to_anchor", "loc"}
                or key.startswith("subplot_")
                else "content"
                if key in {"text", "label", "title"}
                else "appearance"
            )
            groups[group].append(key)
        descriptors[ident] = {
            "id": ident,
            "type": typ,
            "label": label or ident,
            "supported_properties": properties,
            "property_groups": groups,
        }

    layout_reason = subplot_layout_reason(fig)
    register(
        "figure:root",
        fig,
        "figure",
        ["figsize"]
        + (
            []
            if layout_reason
            else [
                "subplot_" + key
                for key in ("left", "right", "bottom", "top", "wspace", "hspace")
            ]
        ),
        "整幅图",
    )
    if layout_reason:
        descriptors["figure:root"]["subplot_unavailable_reason"] = layout_reason
    text_props = [
        "text",
        "fontsize",
        "color",
        "fontweight",
        "rotation",
        "position",
        "visible",
    ]
    for i, ax in enumerate(figure_axes(fig)):
        axis_id = ax.get_gid() or "axes:" + str(i)
        reason = axes_position_reason(ax)
        register(
            axis_id,
            ax,
            "axes",
            ([] if reason else ["position"])
            + ["visible", "tick_fontsize", "facecolor"],
            ax.get_label(),
        )
        if reason:
            descriptors[axis_id]["position_unavailable_reason"] = reason
        for side, spine in ax.spines.items():
            spine_id = spine.get_gid() or axis_id + ":spine:" + side
            register(
                spine_id,
                spine,
                "spine",
                ["linewidth", "edgecolor", "visible"],
                axis_id + " · " + side + " axis spine",
                owner=ax,
            )
            descriptors[spine_id].update(
                spine_side=side,
                axes_role="colorbar"
                if getattr(ax, "_colorbar", None) is not None
                else "plot",
            )
        for label, artist in [
            ("title", ax.title),
            ("title:left", ax._left_title),
            ("title:right", ax._right_title),
            ("xlabel", ax.xaxis.label),
            ("ylabel", ax.yaxis.label),
        ]:
            if ":" in label and not artist.get_text():
                continue
            register(
                artist.get_gid() or axis_id + ":" + label,
                artist,
                label.split(":")[0],
                text_props,
                artist.get_text(),
                owner=ax,
            )
        for j, artist in enumerate(ax.lines):
            label = artist.get_label()
            register(
                artist.get_gid()
                or axis_id
                + ":line:"
                + (label if label and not label.startswith("_") else str(j)),
                artist,
                "line",
                [
                    "color",
                    "linewidth",
                    "linestyle",
                    "marker",
                    "markersize",
                    "alpha",
                    "label",
                    "visible",
                ],
                label,
            )
        for j, artist in enumerate(ax.texts):
            register(
                artist.get_gid() or axis_id + ":text:" + str(j),
                artist,
                "text",
                text_props,
                artist.get_text(),
            )
        for j, artist in enumerate(ax.collections):
            properties = ["alpha", "visible", "linewidth", "edgecolor"]
            if artist.get_array() is not None:
                if scalar_encoding(artist)["known_norm"]:
                    properties.append("cmap")
            else:
                properties.append("facecolor")
            if getattr(ax, "_colorbar", None) is not None:
                properties = []
            register(
                artist.get_gid() or axis_id + ":collection:" + str(j),
                artist,
                "collection",
                properties,
                artist.get_label(),
            )
        for j, artist in enumerate(ax.images):
            properties = ["alpha", "visible", "interpolation"]
            scalar_mapped = artist.get_array().ndim == 2
            if scalar_mapped and scalar_encoding(artist)["known_norm"]:
                properties.append("cmap")
            register(
                artist.get_gid() or axis_id + ":image:" + str(j),
                artist,
                "image",
                properties,
                artist.get_label(),
            )
            descriptors[artist.get_gid()]["scalar_mapped"] = scalar_mapped
            if not scalar_mapped:
                descriptors[artist.get_gid()]["cmap_unavailable_reason"] = (
                    "RGB/RGBA 像素直接给定颜色，色图参数不会改变图像；本轮不改像素数据。"
                )
        for j, artist in enumerate(ax.patches):
            verified = patch_geometry(artist) is not None
            properties = (
                [
                    "facecolor",
                    "edgecolor",
                    "linewidth",
                    "linestyle",
                    "alpha",
                    "fill",
                    "hatch",
                    "visible",
                ]
                if verified
                else []
            )
            register(
                artist.get_gid() or axis_id + ":patch:" + str(j),
                artist,
                "patch",
                properties,
                artist.get_label(),
            )
            if not verified:
                descriptors[artist.get_gid()]["unsupported_reason"] = (
                    "此自定义 patch 的科学几何尚无数值校验；仅定位和批注，样式覆盖暂不支持。"
                )
        legend = ax.get_legend()
        if legend:
            register(
                legend.get_gid() or axis_id + ":legend",
                legend,
                "legend",
                ["loc", "fontsize", "title", "frameon", "visible", "bbox_to_anchor"],
                "Legend",
            )
    for container_index, container in enumerate(figure_containers(fig)):
        prefix = (
            "figure" if container_index == 0 else "subfigure:" + str(container_index)
        )
        for j, artist in enumerate(container.texts):
            register(
                artist.get_gid() or prefix + ":text:" + str(j),
                artist,
                "text",
                text_props,
                artist.get_text(),
            )
    from matplotlib.legend import Legend

    for index, legend in enumerate(fig.findobj(Legend)):
        if not any(existing is legend for existing in objects.values()):
            register(
                legend.get_gid() or "figure:legend:" + str(index),
                legend,
                "legend",
                ["loc", "fontsize", "title", "frameon", "visible", "bbox_to_anchor"],
                "Legend",
            )
        for record in legend_sources.get(legend) or []:
            if record["proxy"] is not None:
                record["proxy"].set_gid(
                    legend.get_gid() + ":handle:" + str(record["index"])
                )
    for ax in figure_axes(fig):
        colorbar = getattr(ax, "_colorbar", None)
        if colorbar is None:
            continue
        ident = "colorbar:" + ax.get_gid()
        mappable_id = next(
            (key for key, item in objects.items() if item is colorbar.mappable), None
        )
        reason = colorbar_position_reason(colorbar, fig)
        properties = ["label", "fontsize", "tick_fontsize", "visible"]
        if mappable_id and "cmap" in descriptors[mappable_id]["supported_properties"]:
            properties.append("cmap")
        if reason is None:
            properties.append("position")
        register(ident, colorbar, "colorbar", properties, "色条", owner=ax)
        descriptors[ident].update(
            mappable_id=mappable_id,
            axes_id=ax.get_gid(),
            orientation=colorbar.orientation,
            color_semantics_readonly=True,
            position_mode="explicit_bbox_replaces_standard_locator_for_this_render"
            if reason is None
            else "source_layout",
            position_unavailable_reason=reason,
        )
    mappables = {
        ident: item
        for ident, item in objects.items()
        if descriptors[ident]["type"] in {"image", "collection"}
        and hasattr(item, "get_clim")
    }
    # A standalone Colorbar can use a ScalarMappable that is not an Axes Artist.
    for ident, item in objects.items():
        if descriptors[ident]["type"] == "colorbar":
            mappables[ident] = item.mappable
    # Initial draw establishes automatic title/axis-label coordinates before overlays.
    fig.canvas.draw()
    colorbar_ticks = {
        ident: colorbar_tick_contract(item)
        for ident, item in objects.items()
        if descriptors[ident]["type"] == "colorbar"
    }
    for ident, artist in objects.items():
        descriptors[ident]["property_schema"] = figure_property_schema(
            artist, descriptors[ident]["type"], fig, owner_axes[ident]
        )

    def numeric():
        return numeric_snapshot(fig)

    before, values = numeric()
    encoding_before = {
        ident: scalar_encoding(item) for ident, item in mappables.items()
    }
    replay = {"applied": [], "failures": [], "legend_sync": []}
    for layer in job.get("overlays", []):
        ident = layer.get("target") or layer.get("object_id") or layer.get("id")
        props = (
            layer["properties"]
            if "properties" in layer
            else {
                k: v for k, v in layer.items() if k not in {"target", "id", "object_id"}
            }
        )
        if ident not in objects:
            replay["failures"].append(
                {"target": ident, "properties": props, "reason": "object_missing"}
            )
            continue
        artist = objects[ident]
        subplot_keys = (
            [key for key in props if key.startswith("subplot_")]
            if descriptors[ident]["type"] == "figure"
            else []
        )
        if subplot_keys:
            try:
                if any(
                    key not in descriptors[ident]["supported_properties"]
                    for key in subplot_keys
                ):
                    raise ValueError(layout_reason or "Unsupported subplot property")
                for key in subplot_keys:
                    validate_figure_property(
                        key, props[key], descriptors[ident]["property_schema"]
                    )
                merged = {
                    key: getattr(fig.subplotpars, key)
                    for key in ("left", "right", "bottom", "top", "wspace", "hspace")
                }
                merged.update(
                    {key.removeprefix("subplot_"): props[key] for key in subplot_keys}
                )
                if not (
                    merged["left"] < merged["right"]
                    and merged["bottom"] < merged["top"]
                ):
                    raise ValueError("Subplot bounds must be ordered")
                fig.subplots_adjust(**merged)
                replay["applied"].extend(
                    {"target": ident, "property": key, "value": props[key]}
                    for key in subplot_keys
                )
            except Exception as exc:
                replay["failures"].extend(
                    {
                        "target": ident,
                        "property": key,
                        "reason": "incompatible_value",
                        "message": str(exc),
                    }
                    for key in subplot_keys
                )
        for key, value in props.items():
            if key in subplot_keys:
                continue
            if key not in descriptors[ident]["supported_properties"]:
                replay["failures"].append(
                    {"target": ident, "property": key, "reason": "unsupported_property"}
                )
                continue
            try:
                typ = descriptors[ident]["type"]
                validate_figure_property(
                    key, value, descriptors[ident]["property_schema"]
                )
                plans = []
                if typ in {"line", "collection", "patch"}:
                    plans, problems = legend_update_plan(
                        fig, legend_sources, artist, key
                    )
                    if problems:
                        replay["failures"].extend(
                            {"target": ident, "property": key, **problem}
                            for problem in problems
                        )
                        continue
                if key == "figsize" and typ == "figure":
                    fig.set_size_inches(value, forward=False)
                elif typ == "colorbar":
                    if key == "cmap":
                        artist.mappable.set_cmap(value)
                    elif key == "label":
                        artist.set_label(str(value))
                    elif key == "fontsize":
                        label = (
                            artist.ax.yaxis.label
                            if artist.orientation == "vertical"
                            else artist.ax.xaxis.label
                        )
                        label.set_fontsize(float(value))
                    elif key == "tick_fontsize":
                        artist.ax.tick_params(labelsize=float(value))
                    elif key == "visible":
                        artist.ax.set_visible(value)
                    elif key == "position":
                        artist.ax.set_axes_locator(None)
                        artist.ax.set_box_aspect(None)
                        artist.ax.set_position(value)
                elif key == "fontsize" and typ == "legend":
                    for text in [*artist.get_texts(), artist.get_title()]:
                        text.set_fontsize(float(value))
                elif key == "title" and typ == "legend":
                    artist.set_title(str(value))
                elif key == "frameon" and typ == "legend":
                    artist.set_frame_on(value)
                elif key == "tick_fontsize":
                    artist.tick_params(labelsize=float(value))
                elif key == "loc":
                    artist.set_loc(value)
                elif key == "bbox_to_anchor":
                    from matplotlib.transforms import BboxTransformTo

                    parent = (
                        artist.axes.bbox
                        if artist.axes is not None
                        else artist_parent_figure(artist, fig).bbox
                    )
                    artist.set_bbox_to_anchor(value, transform=BboxTransformTo(parent))
                elif key == "position":
                    # Matplotlib draw otherwise silently restores automatic label/title placement.
                    if typ in {"xlabel", "ylabel"}:
                        axis = (
                            owner_axes[ident].xaxis
                            if typ == "xlabel"
                            else owner_axes[ident].yaxis
                        )
                        transform, _ = label_position_transform(
                            artist, typ, fig, owner_axes[ident]
                        )
                        axis.set_label_coords(*value, transform=transform)
                    else:
                        if typ == "title":
                            owner_axes[ident]._autotitlepos = False
                        artist.set_position(value)
                else:
                    getattr(artist, "set_" + key)(value)
                for plan in plans:
                    proxy = plan["target"]
                    mapped_key = "text" if key == "label" else key
                    mapped_value = (
                        artist.get_markersize() * plan["legend"].markerscale
                        if key == "markersize"
                        else value
                    )
                    # The built-in LineCollection handler represents the first
                    # segment with one Line2D, matching Matplotlib's own rule.
                    from matplotlib.legend_handler import HandlerLineCollection

                    if (
                        type(plan["record"]["handler"]) is HandlerLineCollection
                        and key == "linewidth"
                    ):
                        mapped_value = value[0]
                    getattr(proxy, "set_" + mapped_key)(mapped_value)
                    replay["legend_sync"].append(
                        {
                            "source": ident,
                            "legend": plan["legend_id"],
                            "handle_index": plan["record"]["index"],
                            "property": key,
                            "match": "original_artist_identity",
                        }
                    )
                replay["applied"].append(
                    {"target": ident, "property": key, "value": value}
                )
            except Exception as exc:
                replay["failures"].append(
                    {
                        "target": ident,
                        "property": key,
                        "reason": "incompatible_value",
                        "message": str(exc),
                    }
                )
    for ident, contract in colorbar_ticks.items():
        restore_colorbar_ticks(objects[ident], contract)
    fig.canvas.draw()
    for ident, contract in colorbar_ticks.items():
        if colorbar_tick_state(objects[ident]) != contract["state"]:
            raise ValueError(
                "Visual edits changed Colorbar tick values or labels: " + ident
            )
    after, _ = numeric()
    if before != after:
        raise ValueError("Visual edits changed numerical content")
    if encoding_before != {
        ident: scalar_encoding(item) for ident, item in mappables.items()
    }:
        raise ValueError("Visual edits changed scalar normalization or color limits")
    renderer = fig.canvas.get_renderer()
    width, height = fig.canvas.get_width_height()
    manifest = []
    for ident, artist in objects.items():
        description = dict(descriptors[ident])
        owner = owner_axes.get(ident)
        description["owner_axes_id"] = (
            owner.get_gid() if hasattr(owner, "get_gid") else None
        )
        try:
            box = (
                artist.ax.get_window_extent(renderer)
                if description["type"] == "colorbar"
                else artist.get_window_extent(renderer)
            )
            if description["type"] == "collection" and (
                not np.isfinite(box.bounds).all() or box.width == 0 and box.height == 0
            ):
                box = artist.get_datalim(artist.axes.transData).transformed(
                    artist.axes.transData
                )
                description["bbox_kind"] = "collection_data_extent"
                from matplotlib.transforms import Bbox

                sizes = getattr(artist, "get_sizes", lambda: [])()
                padding = (
                    max(2.0, float(np.sqrt(np.max(sizes))) * fig.dpi / 144)
                    if len(sizes)
                    else 2.0
                )
                box = Bbox.from_extents(
                    box.x0 - padding,
                    box.y0 - padding,
                    box.x1 + padding,
                    box.y1 + padding,
                )
                description["bbox_kind"] = "collection_data_extent_with_marker_padding"
            if not np.isfinite(box.bounds).all():
                raise ValueError("nonfinite hit rectangle")
            description["bbox"] = [
                float(box.x0 / width),
                float(1 - box.y1 / height),
                float(box.width / width),
                float(box.height / height),
            ]
        except Exception:
            pass
        for key in [
            "text",
            "fontsize",
            "color",
            "linewidth",
            "linestyle",
            "label",
            "rotation",
            "visible",
            "fontweight",
            "marker",
            "markersize",
            "alpha",
            "facecolor",
            "edgecolor",
            "fill",
            "hatch",
            "cmap",
            "interpolation",
        ]:
            getter = getattr(artist, "get_" + key, None)
            if getter:
                try:
                    val = getter()
                    if key == "label" and (not val or str(val).startswith("_")):
                        continue  # Preserve the registered text/role label.
                    if key == "cmap":
                        val = val.name
                    description[key] = json.loads(
                        json.dumps(val, default=lambda item: item.tolist())
                    )
                except Exception:
                    pass
        if description["type"] == "axes":
            description["position"] = list(artist.get_position().bounds)
        elif description["type"] == "figure":
            description["figsize"] = list(fig.get_size_inches())
            description.update(
                {
                    "subplot_" + key: getattr(fig.subplotpars, key)
                    for key in ("left", "right", "bottom", "top", "wspace", "hspace")
                }
            )
        elif description["type"] == "colorbar":
            axis = (
                artist.ax.yaxis if artist.orientation == "vertical" else artist.ax.xaxis
            )
            description.update(
                position=list(artist.ax.get_position().bounds),
                cmap=artist.mappable.get_cmap().name,
                label=axis.label.get_text(),
                fontsize=axis.label.get_fontsize(),
                visible=artist.ax.get_visible(),
                ticks=artist.get_ticks().tolist(),
                tick_labels=[label.get_text() for label in axis.get_ticklabels()],
                scalar_encoding=scalar_encoding(artist.mappable),
            )
            description["tick_semantics"] = colorbar_tick_state(artist)
            description["tick_semantics_preserved"] = (
                description["tick_semantics"] == colorbar_ticks[ident]["state"]
            )
            labels = axis.get_ticklabels()
            if labels:
                description["tick_fontsize"] = labels[0].get_fontsize()
        elif description["type"] != "spine" and hasattr(artist, "get_position"):
            description["position"] = list(artist.get_position())
        if ident in mappables:
            description["scalar_encoding"] = scalar_encoding(mappables[ident])
        if description["type"] == "legend":
            from matplotlib.transforms import BboxTransformTo

            parent_box = (
                artist.axes.bbox
                if artist.axes is not None
                else artist_parent_figure(artist, fig).bbox
            )
            description["bbox_to_anchor"] = list(
                artist.get_bbox_to_anchor()
                .transformed(BboxTransformTo(parent_box).inverted())
                .bounds
            )
            description["loc"] = artist._loc
            description["frameon"] = artist.get_frame_on()
            description["title"] = artist.get_title().get_text()
            if artist.get_texts():
                description["fontsize"] = artist.get_texts()[0].get_fontsize()
            description["handles"] = []
            for record in legend_sources.get(artist) or []:
                proxy = record["proxy"]
                source_id = next(
                    (
                        name
                        for name, value in objects.items()
                        if value is record["source"]
                    ),
                    None,
                )
                properties = {}
                if proxy is not None:
                    for property_name in [
                        "color",
                        "linestyle",
                        "linewidth",
                        "markersize",
                    ]:
                        getter = getattr(proxy, "get_" + property_name, None)
                        if getter:
                            value = getter()
                            # Collection proxies can return NumPy arrays/tuples.
                            properties[property_name] = json.loads(
                                json.dumps(value, default=lambda item: item.tolist())
                            )
                description["handles"].append(
                    {
                        "index": record["index"],
                        "source_id": source_id,
                        "match": "original_artist_identity"
                        if source_id
                        else "unsupported_or_unregistered_source",
                        "proxy_id": proxy.get_gid() if proxy is not None else None,
                        "properties": properties,
                    }
                )
        description["interaction"] = artist_interaction(
            artist, description, fig, width, height
        )
        manifest.append(description)
    files = []
    preview = job.get("preview") is True
    for extension in ["svg", "png"] if preview else ["svg", "png", "pdf"]:
        path = work / ("figure." + extension)
        fig.savefig(
            path,
            dpi=100 if preview else 160,
            metadata={"Creator": "Research Partner"}
            if extension in {"pdf", "svg"}
            else None,
        )
        files.append(str(path))
    if numeric()[0] != before:
        raise ValueError("Export-time drawing changed numerical content")
    if encoding_before != {
        ident: scalar_encoding(item) for ident, item in mappables.items()
    }:
        raise ValueError(
            "Export-time drawing changed scalar normalization or color limits"
        )
    for ident, contract in colorbar_ticks.items():
        if colorbar_tick_state(objects[ident]) != contract["state"]:
            raise ValueError(
                "Export-time drawing changed Colorbar tick values or labels: " + ident
            )
    (work / "numeric_values.json").write_text(
        json.dumps(values, ensure_ascii=False, allow_nan=True)
    )
    files.append(str(work / "numeric_values.json"))
    (work / "plot_source.py").write_bytes(source.read_bytes())
    if not preview:
        files.append(str(work / "plot_source.py"))
    plt.close(fig)
    if replay["failures"]:
        warnings.append(
            "Some visual edits could not be replayed; inspect replay.failures."
        )
    return {
        "files": files,
        "manifest": manifest,
        "replay": replay,
        "warnings": warnings,
        "numeric_before": before,
        "numeric_after": after,
        "runtime": runtime("matplotlib", "numpy"),
    }


SVG = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
ET.register_namespace("", SVG)
ET.register_namespace("xlink", XLINK)


def element(parent, name, **attrs):
    return ET.SubElement(
        parent,
        "{" + SVG + "}" + name,
        {key.replace("_", "-"): str(value) for key, value in attrs.items()},
    )


def svg_text_lines(text, width, font_size):
    # Explicit newlines are preserved. Soft wrap uses conservative glyph width.
    cap = max(1, int(width / (font_size * 0.57)))
    lines = []
    for paragraph in str(text).split("\n"):
        current = ""
        for word in re.findall(r"\S+\s*", paragraph) or [""]:
            if current and len(current + word) > cap:
                lines.append(current.rstrip())
                current = ""
            if len(word) > cap:
                for ch in word:
                    if len(current) >= cap:
                        lines.append(current)
                        current = ""
                    current += ch
            else:
                current += word
        lines.append(current.rstrip())
    return lines


def svg_text(
    parent, text, x, y, width, font_size, color="#253a39", align="left", bold=False
):
    lines = svg_text_lines(text, width, font_size)
    anchor = {"left": "start", "center": "middle", "right": "end"}.get(align, "start")
    tx = x + (width / 2 if anchor == "middle" else width if anchor == "end" else 0)
    node = element(
        parent,
        "text",
        x=tx,
        y=y + font_size,
        fill=color,
        font_size=font_size,
        font_family="DejaVu Sans, sans-serif",
        text_anchor=anchor,
        font_weight="bold" if bold else "normal",
    )
    for i, line in enumerate(lines):
        span = element(node, "tspan", x=tx, dy=0 if i == 0 else font_size * 1.25)
        span.text = line
    return len(lines) * font_size * 1.25


def node_box(node):
    box = [
        float(node.get(key, default))
        for key, default in [("x", 0), ("y", 0), ("width", 160), ("height", 70)]
    ]
    if box[2] <= 0 or box[3] <= 0:
        raise ValueError("Diagram node dimensions must be positive: " + node["id"])
    return box


def diagram_endpoints(source, target, linewidth):
    """Clip a straight connection to rectangular boundaries, in canvas units."""
    a, b = node_box(source), node_box(target)
    ac, bc = (a[0] + a[2] / 2, a[1] + a[3] / 2), (b[0] + b[2] / 2, b[1] + b[3] / 2)
    dx, dy = bc[0] - ac[0], bc[1] - ac[1]
    distance = math.hypot(dx, dy)
    if distance == 0:
        raise ValueError(
            "Diagram connection has coincident node centers: "
            + source["id"]
            + " -> "
            + target["id"]
        )
    ux, uy = dx / distance, dy / distance

    def boundary(box):
        return min(
            box[2] / (2 * abs(ux)) if ux else math.inf,
            box[3] / (2 * abs(uy)) if uy else math.inf,
        )

    # Marker refX is its tip, so this gap survives node fill/border painting.
    start_distance, end_distance = (
        boundary(a) + 2 + linewidth / 2,
        boundary(b) + 3 + linewidth / 2,
    )
    if distance <= start_distance + end_distance:
        raise ValueError(
            "Diagram connection has no visible gap between node boundaries: "
            + source["id"]
            + " -> "
            + target["id"]
        )
    return [ac[0] + ux * start_distance, ac[1] + uy * start_distance], [
        bc[0] - ux * end_distance,
        bc[1] - uy * end_distance,
    ]


def diagram_label_box(text, font_size, start, end, obstacles, page_width, page_height):
    """Place a padded text box beside an edge; report unresolved collisions."""
    padding = 5
    width = min(
        220,
        max(72, max(len(line) for line in str(text).split("\n")) * font_size * 0.57),
    )
    height = len(svg_text_lines(text, width, font_size)) * font_size * 1.25
    bw, bh = width + padding * 2, height + padding * 2
    dx, dy = end[0] - start[0], end[1] - start[1]
    distance = math.hypot(dx, dy)
    nx, ny = -dy / distance, dx / distance
    if ny > 0 or ny == 0 and nx > 0:
        nx, ny = -nx, -ny
    normal_offset = abs(nx) * bw / 2 + abs(ny) * bh / 2 + 7

    def overlap(box, obstacle):
        return max(
            0,
            min(box[0] + box[2], obstacle[0] + obstacle[2] + 4)
            - max(box[0], obstacle[0] - 4),
        ) * max(
            0,
            min(box[1] + box[3], obstacle[1] + obstacle[3] + 4)
            - max(box[1], obstacle[1] - 4),
        )

    candidates = []
    for fraction in [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.1, 0.9]:
        for side in [1, -1]:
            for extra in [0, font_size * 1.5, font_size * 3]:
                offset = side * (normal_offset + extra)
                box = [
                    start[0] + dx * fraction + nx * offset - bw / 2,
                    start[1] + dy * fraction + ny * offset - bh / 2,
                    bw,
                    bh,
                ]
                outside = bw * bh - max(
                    0, min(box[0] + bw, page_width) - max(0, box[0])
                ) * max(0, min(box[1] + bh, page_height) - max(0, box[1]))
                penalty = outside + sum(overlap(box, item) for item in obstacles)
                if penalty <= 1e-8:
                    return box, "clear", padding
                candidates.append((penalty, box))
    return min(candidates, key=lambda item: item[0])[1], "overlap_unresolved", padding


def dimensions(page, units):
    scale = {"px": 72 / 96, "pt": 1, "cm": 72 / 2.54, "mm": 72 / 25.4, "in": 72}.get(
        units
    )
    if scale is None:
        raise ValueError("Unknown physical unit: " + units)
    w, h = float(page["width"]), float(page["height"])
    if not 0 < w * scale <= 14400 or not 0 < h * scale <= 14400:
        raise ValueError("Canvas dimension outside supported range (0, 200 inches]")
    return w, h, scale


def svg_image(root, path, item):
    x, y, w, h = [float(item.get(k, 0)) for k in ["x", "y", "width", "height"]]
    if Path(path).suffix.lower() == ".svg":
        tree = ET.fromstring(Path(path).read_bytes())
        # Block external SVG dependencies; all component bytes must be registered.
        for node in tree.iter():
            for key, value in node.attrib.items():
                if key.rsplit("}", 1)[-1] == "href" and not value.startswith(
                    ("#", "data:")
                ):
                    raise ValueError(
                        "SVG contains external resource; register/embed it first"
                    )
        tree.set("x", str(x))
        tree.set("y", str(y))
        tree.set("width", str(w))
        tree.set("height", str(h))
        tree.set("preserveAspectRatio", "xMidYMid meet")
        # Prefix IDs and url references to prevent collisions across compositions.
        prefix = item["id"] + "-"
        ids = {
            node.get("id"): prefix + node.get("id")
            for node in tree.iter()
            if node.get("id")
        }
        for node in tree.iter():
            if node.get("id"):
                node.set("id", ids[node.get("id")])
            for key, value in list(node.attrib.items()):
                for old, new in ids.items():
                    value = value.replace("url(#" + old + ")", "url(#" + new + ")")
                    if value == "#" + old:
                        value = "#" + new
                node.set(key, value)
        root.append(tree)
    else:
        media = mimetypes.guess_type(path)[0] or "image/png"
        if media not in {"image/png", "image/jpeg", "image/gif", "image/webp"}:
            raise ValueError("Unsupported embedded image format: " + media)
        image = element(
            root,
            "image",
            x=x,
            y=y,
            width=w,
            height=h,
            preserveAspectRatio="xMidYMid meet",
        )
        image.set(
            "{" + XLINK + "}href",
            "data:"
            + media
            + ";base64,"
            + base64.b64encode(Path(path).read_bytes()).decode(),
        )


def canvas(job, work):
    import ctypes as ct
    import ctypes.util

    # Use system C libraries directly. This avoids requiring optional gi-cairo
    # Python bridge packages and keeps this worker stdlib-only for vector jobs.
    cairo = ct.CDLL(ctypes.util.find_library("cairo") or "libcairo.so.2")
    rsvg = ct.CDLL(ctypes.util.find_library("rsvg-2") or "librsvg-2.so.2")
    gobject = ct.CDLL(ctypes.util.find_library("gobject-2.0") or "libgobject-2.0.so.0")

    def bind(lib, name, result, args):
        function = getattr(lib, name)
        function.restype = result
        function.argtypes = args
        return function

    ptr, dbl, integer = ct.c_void_p, ct.c_double, ct.c_int
    pdf_create = bind(cairo, "cairo_pdf_surface_create", ptr, [ct.c_char_p, dbl, dbl])
    pdf_size = bind(cairo, "cairo_pdf_surface_set_size", None, [ptr, dbl, dbl])
    image_create = bind(
        cairo, "cairo_image_surface_create", ptr, [integer, integer, integer]
    )
    context_create = bind(cairo, "cairo_create", ptr, [ptr])
    context_destroy = bind(cairo, "cairo_destroy", None, [ptr])
    context_scale = bind(cairo, "cairo_scale", None, [ptr, dbl, dbl])
    show_page = bind(cairo, "cairo_show_page", None, [ptr])
    surface_finish = bind(cairo, "cairo_surface_finish", None, [ptr])
    surface_destroy = bind(cairo, "cairo_surface_destroy", None, [ptr])
    surface_status = bind(cairo, "cairo_surface_status", integer, [ptr])
    write_png = bind(cairo, "cairo_surface_write_to_png", integer, [ptr, ct.c_char_p])
    cairo_version = bind(cairo, "cairo_version_string", ct.c_char_p, [])
    handle_create = bind(
        rsvg,
        "rsvg_handle_new_from_data",
        ptr,
        [ct.c_char_p, ct.c_size_t, ct.POINTER(ptr)],
    )

    class Rectangle(ct.Structure):
        _fields_ = [("x", dbl), ("y", dbl), ("width", dbl), ("height", dbl)]

    render = bind(
        rsvg,
        "rsvg_handle_render_document",
        integer,
        [ptr, ptr, ct.POINTER(Rectangle), ct.POINTER(ptr)],
    )
    unref = bind(gobject, "g_object_unref", None, [ptr])

    def draw(handle, context, viewport):
        error = ptr()
        if not render(handle, context, ct.byref(viewport), ct.byref(error)):
            raise ValueError("librsvg failed to render registered SVG")

    obj, inputs = job["object"], job.get("inputs", {})
    c, kind = obj["content"], obj["kind"]
    if kind == "diagram":
        pages = [
            {
                "id": "diagram",
                "width": c.get("width", 1000),
                "height": c.get("height", 640),
                "objects": [],
            }
        ]
        units = "px"
    else:
        pages, units = (
            c.get("pages", []),
            c.get("units", "cm" if kind == "poster" else "px"),
        )
    if not pages:
        raise ValueError("Canvas needs at least one page")
    warnings, files, manifest = [], [], []
    pdf = None
    for index, page in enumerate(pages):
        w, h, scale = dimensions(page, units)
        root = ET.Element(
            "{" + SVG + "}svg",
            {
                "width": str(w * scale) + "pt",
                "height": str(h * scale) + "pt",
                "viewBox": f"0 0 {w} {h}",
                "version": "1.1",
            },
        )
        element(
            root,
            "rect",
            x=0,
            y=0,
            width=w,
            height=h,
            fill=page.get("background", "white"),
        )
        edge_labels = []
        if kind == "diagram":
            nodes = {node["id"]: node for node in c.get("nodes", [])}
            defs = element(root, "defs")
            obstacles = [node_box(node) for node in nodes.values()]
            for edge_index, edge in enumerate(c.get("edges", [])):
                source = edge.get("source", edge.get("src"))
                target = edge.get("target", edge.get("dst"))
                if source not in nodes or target not in nodes:
                    raise ValueError(
                        "Diagram edge references missing node: " + edge.get("id", "")
                    )
                linewidth = float(edge.get("linewidth", 2))
                start, end = diagram_endpoints(nodes[source], nodes[target], linewidth)
                marker_id = "diagram-arrow-" + str(edge_index)
                marker = element(
                    defs,
                    "marker",
                    id=marker_id,
                    markerWidth=8,
                    markerHeight=8,
                    refX=8,
                    refY=4,
                    orient="auto",
                )
                element(
                    marker,
                    "path",
                    d="M0,0 L8,4 L0,8 z",
                    fill=edge.get("color", "#617974"),
                )
                element(
                    root,
                    "line",
                    id=edge["id"],
                    x1=start[0],
                    y1=start[1],
                    x2=end[0],
                    y2=end[1],
                    stroke=edge.get("color", "#617974"),
                    stroke_width=linewidth,
                    stroke_dasharray="none"
                    if edge.get("status") == "confirmed"
                    else "6 4",
                    marker_end="url(#" + marker_id + ")",
                )
                label = edge.get("label", edge.get("type", ""))
                entry = {
                    "id": edge["id"],
                    "type": "edge",
                    "source": source,
                    "target": target,
                    "label": label,
                    "start": start,
                    "end": end,
                    "endpoint_geometry": "rectangle_boundary_with_gap",
                }
                if label:
                    fs = float(edge.get("font_size", 14))
                    box, layout, padding = diagram_label_box(
                        label, fs, start, end, obstacles, w, h
                    )
                    group = ET.Element("{" + SVG + "}g", {"id": edge["id"] + ":label"})
                    element(
                        group,
                        "rect",
                        x=box[0],
                        y=box[1],
                        width=box[2],
                        height=box[3],
                        fill=page.get("background", "white"),
                        rx=3,
                    )
                    svg_text(
                        group,
                        label,
                        box[0] + padding,
                        box[1] + padding,
                        box[2] - padding * 2,
                        fs,
                        align="center",
                    )
                    edge_labels.append(group)
                    obstacles.append(box)
                    entry.update(label_bbox=box, label_layout=layout)
                    if layout != "clear":
                        warnings.append(
                            "Diagram edge label overlaps a node, label or page boundary: "
                            + edge["id"]
                        )
                manifest.append(entry)
            items = [
                {
                    "type": "shape",
                    "fill": "#eff6f3",
                    "stroke": "#617974",
                    **node,
                    "text": node.get("text", node.get("label", "")),
                    "width": node.get("width", 160),
                    "height": node.get("height", 70),
                }
                for node in nodes.values()
            ]
        else:
            items = sorted(page.get("objects", []), key=lambda x: x.get("z", 0))
        for item in items:
            x, y = float(item.get("x", 0)), float(item.get("y", 0))
            iw, ih = float(item.get("width", 1)), float(item.get("height", 1))
            if iw <= 0 or ih <= 0:
                raise ValueError("Object dimensions must be positive: " + item["id"])
            if x < 0 or y < 0 or x + iw > w + 0.001 or y + ih > h + 0.001:
                warnings.append("Object outside page: " + item["id"])
            group = element(root, "g", id=item["id"])
            if (
                item.get("fill")
                and item["fill"] != "transparent"
                or item.get("type") == "shape"
            ):
                element(
                    group,
                    "rect",
                    x=x,
                    y=y,
                    width=iw,
                    height=ih,
                    fill=item.get("fill", "#eff6f3"),
                    stroke=item.get("stroke", "none"),
                    stroke_width=item.get("linewidth", 1),
                )
            if item.get("type") == "image":
                svg_image(group, inputs[item["id"]], item)
            elif item.get("text"):
                fs = float(item.get("font_size", 16 if units == "px" else 0.8))
                used = svg_text(
                    group,
                    item["text"],
                    x,
                    y,
                    iw,
                    fs,
                    item.get("color", "#253a39"),
                    item.get("align", "left"),
                    item.get("bold", False),
                )
                if used > ih:
                    warnings.append("Text may overflow object: " + item["id"])
            manifest.append(
                {
                    "id": item["id"],
                    "page_id": page["id"],
                    "type": item.get("type", "text"),
                    "bbox": [x, y, iw, ih],
                    "units": units,
                    "group": item.get("group"),
                    "text": item.get("text", ""),
                }
            )
        # Labels are painted last so every edge gets the same opaque text backing.
        for label_group in edge_labels:
            root.append(label_group)
        svg = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        name = "canvas.svg" if index == 0 else "canvas-" + str(index + 1) + ".svg"
        path = work / name
        path.write_bytes(svg)
        files.append(str(path))
        error = ptr()
        handle = handle_create(svg, len(svg), ct.byref(error))
        if not handle:
            raise ValueError("librsvg rejected registered SVG")
        if pdf is None:
            pdf = pdf_create(str(work / "canvas.pdf").encode(), w * scale, h * scale)
        else:
            pdf_size(pdf, w * scale, h * scale)
        cr = context_create(pdf)
        viewport = Rectangle(0, 0, w * scale, h * scale)
        draw(handle, cr, viewport)
        show_page(cr)
        context_destroy(cr)
        zoom = min(2, 1800 / (w * scale), 1800 / (h * scale))
        surface = image_create(
            0, math.ceil(w * scale * zoom), math.ceil(h * scale * zoom)
        )
        cr = context_create(surface)
        context_scale(cr, zoom, zoom)
        draw(handle, cr, viewport)
        context_destroy(cr)
        png = work / (
            "canvas.png" if index == 0 else "canvas-" + str(index + 1) + ".png"
        )
        if write_png(surface, str(png).encode()):
            raise ValueError("Cairo failed writing PNG")
        files.append(str(png))
        surface_finish(surface)
        surface_destroy(surface)
        unref(handle)
    surface_finish(pdf)
    if surface_status(pdf):
        raise ValueError("Cairo failed writing PDF")
    surface_destroy(pdf)
    files.append(str(work / "canvas.pdf"))
    return {
        "files": files,
        "manifest": manifest,
        "warnings": warnings,
        "runtime": {
            **runtime(),
            "rsvg_library": rsvg._name,
            "cairo_library": cairo._name,
            "cairo_version": cairo_version().decode(),
        },
    }


# Bounded Markdown syntax: every image is a declared asset reference, never a
# file/URL opened from prose. This parser is shared with the stdlib coordinator.
MD_INLINE = re.compile(
    r"(?P<math>(?<!\\)\$\$[\s\S]+?\$\$|(?<![\\$])\$(?!\$)[^\n$]+\$(?!\$)|(?<!\\)\\\[[\s\S]+?\\\]|(?<!\\)\\\([^\n]+?\\\))"
    r"|(?P<math_unclosed>(?<!\\)\\\([^\n]*$|(?<!\\)\\\[[^\n]*$|(?<![\\$])\$(?=[A-Za-z_\\{])[^$\n]*$)"
    r"|(?P<citation>\[@[A-Za-z0-9_.:-]+(?:\s*;\s*@[A-Za-z0-9_.:-]+)*\])"
    r"|(?P<escape>\\[\\`*{}_\[\]()!|])"
    r"|(?P<code>`+)(?P<code_text>.+?)(?P=code)"
    r'|!\[(?P<alt>(?:\\.|[^\]])*)\]\((?P<target><[^>]*>|(?:\\.|[^\s()])*)(?:\s+["\'][^"\']*["\'])?\)'
    r"|!\[(?P<reference_alt>[^\]]*)\](?:\[(?P<reference_id>[^\]]*)\])?"
    r"|(?P<strong>\*\*|__)(?=\S)(?P<strong_text>.+?)(?<=\S)(?P=strong)"
    r"|(?P<emphasis>(?<!\w)\*|(?<!\w)_)(?=\S)(?P<emphasis_text>.+?)(?<=\S)(?P=emphasis)(?!\w)"
)


def markdown_inline(text):
    end = 0
    for match in MD_INLINE.finditer(text):
        if match.start() > end:
            yield {"type": "text", "text": text[end : match.start()]}
        if match["math"] or match["math_unclosed"]:
            yield {"type": "math", "text": match["math"] or match["math_unclosed"]}
        elif match["citation"]:
            yield {"type": "citation", "text": match["citation"]}
        elif match["escape"]:
            yield {"type": "text", "text": match["escape"][1:]}
        elif match["code"]:
            yield {"type": "code", "text": match["code_text"]}
        elif match["alt"] is not None:
            target = match["target"].removeprefix("<").removesuffix(">")
            yield {
                "type": "image",
                "text": match["alt"],
                "target": re.sub(r"\\([() ])", r"\1", target),
            }
        elif match["reference_alt"] is not None:
            # Reference-style images are explicit unsupported occurrences, not
            # interpreted as local paths or silently discarded.
            yield {
                "type": "image",
                "text": match["reference_alt"],
                "target": match.group(0),
                "unsupported_reference": True,
            }
        elif match["strong"]:
            yield {"type": "strong", "text": match["strong_text"]}
        else:
            yield {"type": "emphasis", "text": match["emphasis_text"]}
        end = match.end()
    if end < len(text):
        yield {"type": "text", "text": text[end:]}


def markdown_image_references(markdown):
    result, fence = [], None

    def collect(text, line):
        for token in markdown_inline(text):
            if token["type"] == "image":
                result.append({**token, "line": line})
            elif token["type"] in {"strong", "emphasis"}:
                collect(token["text"], line)

    for number, line in enumerate(markdown.splitlines(), 1):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1]
            elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                fence = None
            continue
        if fence is None:
            collect(line, number)
    return result


def markdown_math_references(markdown):
    try:
        from .docx_semantics41 import display_chunks
    except ImportError:
        from docx_semantics41 import display_chunks
    result = []

    def collect(text):
        for token in markdown_inline(text):
            if token["type"] == "math":
                result.append(token["text"])
            elif token["type"] in {"strong", "emphasis"}:
                collect(token["text"])

    for kind, text in display_chunks(markdown):
        if kind == "math":
            result.append(text)
            continue
        fence = None
        for line in text.splitlines():
            marker = re.match(r"^\s*(`{3,}|~{3,})", line)
            if marker:
                if fence is None:
                    fence = marker[1]
                elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                    fence = None
            elif fence is None:
                collect(line)
    return result


def markdown_table_cells(line):
    # Escaped pipes and pipes inside inline code are cell text.
    cells, current, ticks = [], [], 0
    i = 0
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line):
            current.extend(line[i : i + 2])
            i += 2
            continue
        if line[i] == "`":
            end = i + 1
            while end < len(line) and line[end] == "`":
                end += 1
            count = end - i
            ticks = 0 if ticks == count else count if not ticks else ticks
            current.append(line[i:end])
            i = end
            continue
        if line[i] == "|" and not ticks:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(line[i])
        i += 1
    cells.append("".join(current).strip())
    return cells


def document(job, work):
    from docx import Document
    from docx.shared import Inches, Pt, RGBColor
    from docx.image.image import Image
    from docx.oxml import OxmlElement

    try:
        from .docx_semantics41 import (
            equation_xml,
            display_chunks,
            resolve_citation,
            bibliography_text,
            text_identity,
            MathSyntaxError,
        )
    except ImportError:
        from docx_semantics41 import (
            equation_xml,
            display_chunks,
            resolve_citation,
            bibliography_text,
            text_identity,
            MathSyntaxError,
        )
    doc = Document()
    section = doc.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = section.left_margin = (
        section.right_margin
    ) = Inches(1)
    for name, size in [
        ("Normal", 11),
        ("Title", 24),
        ("Heading 1", 18),
        ("Heading 2", 14),
        ("Heading 3", 12),
    ]:
        style = doc.styles[name]
        style.font.name = "Arial"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string("202E2C")
        style.paragraph_format.space_after = Pt(7)
    warnings = list(job.get("image_warnings", []))
    manifest = []
    parent_citations = job.get("citations", [])
    extra_citations = []

    def math(paragraph, raw, source):
        entry = job.get("math_images", {}).get(raw, {})
        try:
            if entry.get("status") != "rendered":
                raise MathSyntaxError(
                    entry.get(
                        "error",
                        "Compatible equation image was not supplied; full source retained",
                    )
                )
            path = Path(job.get("inputs", {}).get(entry["input_alias"], "")).resolve()
            if (
                not path.is_relative_to(work.resolve())
                or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
            ):
                raise ValueError("Equation image identity/path mismatch")
            natural_width = entry["width_px"] / entry["dpi"]
            width = min(6.5, natural_width)
            shape = paragraph.add_run().add_picture(str(path), width=Inches(width))
            shape._inline.docPr.set("descr", raw)
            shape._inline.docPr.set("title", "Formula source: " + raw)
            if entry.get("display"):
                paragraph.alignment = 1
            if width < natural_width:
                warnings.append(
                    {
                        "code": "document_math_scaled",
                        "object_id": source,
                        "source": raw,
                        "scale": width / natural_width,
                    }
                )
            manifest.append(
                {
                    "type": "document_math",
                    "object_id": source,
                    "source": raw,
                    "source_sha256": text_identity(raw),
                    "representation": "mathtext_png_with_source",
                    "display": entry.get("display"),
                    "image_sha256": entry["sha256"],
                    "omml_source_available": bool(entry.get("omml_source")),
                }
            )
        except MathSyntaxError as exc:
            paragraph.add_run("[Equation conversion unavailable] ").italic = True
            paragraph.add_run(raw).font.name = "Courier New"
            warnings.append(
                {
                    "code": "document_math_unsupported",
                    "object_id": source,
                    "source": raw,
                    "source_sha256": text_identity(raw),
                    "reason": str(exc),
                }
            )

    def inline(
        paragraph,
        text,
        images,
        inputs,
        source,
        *,
        bold=False,
        italic=False,
        width=6.5,
        citations=None,
        citation_offset=0,
    ):
        citations = parent_citations if citations is None else citations
        for token in markdown_inline(text):
            kind = token["type"]
            if kind in {"strong", "emphasis"}:
                inline(
                    paragraph,
                    token["text"],
                    images,
                    inputs,
                    source,
                    bold=bold or kind == "strong",
                    italic=italic or kind == "emphasis",
                    width=width,
                    citations=citations,
                    citation_offset=citation_offset,
                )
            elif kind == "math":
                math(paragraph, token["text"], source)
            elif kind == "citation":
                label, missing = resolve_citation(
                    token["text"], citations, citation_offset
                )
                paragraph.add_run(
                    label or "[Unresolved citation: " + ", ".join(missing) + "]"
                )
                if missing:
                    warnings.append(
                        {
                            "code": "document_citation_unresolved",
                            "object_id": source,
                            "source": token["text"],
                            "keys": missing,
                            "reason": "Key absent or ambiguous in adopted citation list",
                        }
                    )
                else:
                    manifest.append(
                        {
                            "type": "document_citation",
                            "object_id": source,
                            "source": token["text"],
                            "display": label,
                        }
                    )
            elif kind == "image":
                target = token["target"]
                alias = images.get(target)
                if alias is None or alias not in inputs:
                    run = paragraph.add_run(
                        "[Image unavailable: " + token["text"] + " — " + target + "]"
                    )
                    run.italic = True
                    # Engine supplies occurrence warnings; replay/standalone
                    # workers still emit a warning if they have no resolver.
                    if not any(
                        w.get("target") == target and w.get("object_id") == source
                        for w in warnings
                        if isinstance(w, dict)
                    ):
                        warnings.append(
                            {
                                "code": "markdown_image_unresolved",
                                "object_id": source,
                                "target": target,
                                "alt": token["text"],
                                "reason": "No authorized registered image supplied",
                            }
                        )
                    continue
                path = Path(inputs[alias]).resolve()
                if not path.is_relative_to(work.resolve()) or not path.is_file():
                    raise ValueError(
                        "Document image input must be an authorized copy in output directory"
                    )
                try:
                    image = Image.from_file(str(path))
                    aspect = image.px_width / image.px_height
                    shape = paragraph.add_run().add_picture(
                        str(path), width=Inches(min(width, 8.0 * aspect))
                    )
                    shape._inline.docPr.set("descr", token["text"])
                    manifest.append(
                        {
                            "type": "document_image",
                            "target": target,
                            "object_id": source,
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "alt": token["text"],
                        }
                    )
                except Exception as exc:
                    paragraph.add_run(
                        "[Image unavailable: " + token["text"] + " — " + target + "]"
                    ).italic = True
                    warnings.append(
                        {
                            "code": "markdown_image_decode_failed",
                            "object_id": source,
                            "target": target,
                            "reason": type(exc).__name__ + ": " + str(exc),
                        }
                    )
            else:
                run = paragraph.add_run(token["text"])
                run.bold = bold
                run.italic = italic
                if kind == "code":
                    run.font.name = "Courier New"
                    run.font.size = Pt(9)

    def write_markdown(
        markdown, images, inputs, source, citations=None, citation_offset=0
    ):
        for kind, value in display_chunks(markdown):
            if kind == "math":
                math(doc.add_paragraph(), value, source)
            else:
                write_prose(value, images, inputs, source, citations, citation_offset)

    def write_prose(
        markdown, images, inputs, source, citations=None, citation_offset=0
    ):
        lines, index, fence = markdown.splitlines(), 0, None
        follows_image = False
        while index < len(lines):
            line = lines[index]
            index += 1
            marker = re.match(r"^\s*(`{3,}|~{3,})", line)
            if marker:
                if fence is None:
                    fence = marker[1]
                elif marker[1][0] == fence[0] and len(marker[1]) >= len(fence):
                    fence = None
                continue
            if fence is not None:
                p = doc.add_paragraph()
                run = p.add_run(line)
                run.font.name = "Courier New"
                run.font.size = Pt(9)
                continue
            if not line.strip():
                continue
            # GFM-style pipe tables, native editable Word rows and cells.
            separators = (
                markdown_table_cells(lines[index]) if index < len(lines) else []
            )
            if (
                "|" in line
                and len(separators) > 1
                and all(re.fullmatch(r":?-{3,}:?", cell) for cell in separators)
            ):
                rows = [markdown_table_cells(line)]
                index += 1
                while (
                    index < len(lines) and lines[index].strip() and "|" in lines[index]
                ):
                    rows.append(markdown_table_cells(lines[index]))
                    index += 1
                columns = max(len(row) for row in rows)
                if any(len(row) != len(separators) for row in rows):
                    warnings.append(
                        {
                            "code": "markdown_table_ragged",
                            "object_id": source,
                            "line": index - len(rows),
                            "reason": "Rows padded to retain every cell; inconsistent column counts",
                        }
                    )
                table = doc.add_table(rows=0, cols=columns)
                table.style = "Table Grid"
                table.autofit = False
                for col in table.columns:
                    col.width = Inches(6.5 / columns)
                for ri, row in enumerate(rows):
                    row_element = table.add_row()
                    row_element._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
                    cells = row_element.cells
                    if ri == 0:
                        repeat = OxmlElement("w:tblHeader")
                        table.rows[-1]._tr.get_or_add_trPr().append(repeat)
                    for ci, text in enumerate(row):
                        p = cells[ci].paragraphs[0]
                        inline(
                            p,
                            text,
                            images,
                            inputs,
                            source,
                            bold=ri == 0,
                            width=max(0.1, 6.5 / columns - 0.15),
                            citations=citations,
                            citation_offset=citation_offset,
                        )
                        p.paragraph_format.space_after = Pt(5)
                        for run in p.runs:
                            run.font.size = Pt(10)
                manifest.append(
                    {
                        "type": "document_table",
                        "object_id": source,
                        "rows": len(rows),
                        "columns": columns,
                    }
                )
                doc.add_paragraph().paragraph_format.space_after = Pt(0)
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)$", line)
            bullet = re.match(r"^\s*[-*+]\s+(.+)$", line)
            numbered = re.match(r"^\s*\d+[.)]\s+(.+)$", line)
            if heading:
                p = doc.add_heading(level=min(3, len(heading[1])))
                text = heading[2]
            elif bullet:
                p = doc.add_paragraph(style="List Bullet")
                text = bullet[1]
            elif numbered:
                p = doc.add_paragraph(style="List Number")
                text = numbered[1]
            else:
                p = doc.add_paragraph()
                text = line
            inline(
                p,
                text,
                images,
                inputs,
                source,
                citations=citations,
                citation_offset=citation_offset,
            )
            # Keep a following caption paragraph together with its image when
            # the combined content fits a page; never alter source text/bytes.
            if follows_image:
                p.paragraph_format.keep_together = False
            follows_image = bool(re.fullmatch(r"\s*!\[.*\]\(.*\)\s*", line))
            if follows_image:
                p.paragraph_format.keep_with_next = True

    components = job.get("components", [])
    caption_style = doc.styles["Caption"]
    caption_style.font.name = "Arial"
    caption_style.font.size = Pt(10)
    caption_style.font.color.rgb = RGBColor.from_string("202E2C")
    caption_style.font.italic = False
    # New exports receive the shared saved-order sequence. Old standalone
    # replay jobs retain their original append order; no block anchor is guessed.
    segments = job.get("segments")
    if segments is None:
        segments = [{"kind": "markdown", "markdown": job["markdown"]}] + [
            {"kind": "component", "index": i} for i in range(len(components))
        ]
    for segment in segments:
        if segment["kind"] == "markdown":
            write_markdown(
                segment["markdown"],
                job.get("images", {}),
                job.get("inputs", {}),
                job["object"].get("id"),
            )
            continue
        if segment["kind"] != "component":
            raise ValueError("Unknown document segment")
        item = components[segment["index"]]
        if item["type"] == "image":
            image = Image.from_file(item["path"])
            aspect = image.px_width / image.px_height
            doc.add_picture(item["path"], width=Inches(min(6.5, 7.5 * aspect)))
            if item.get("caption"):
                doc.paragraphs[-1].paragraph_format.keep_with_next = True
                caption = doc.add_paragraph(style="Caption")
                inline(
                    caption,
                    item["caption"],
                    item.get("images", {}),
                    item.get("inputs", {}),
                    item["object_id"],
                )
                caption.paragraph_format.keep_together = False
                caption.paragraph_format.widow_control = True
        else:
            warnings.extend(item.get("image_warnings", []))
            # Preserve the component section path, now with the same bounded
            # Markdown semantics as the parent document.
            offset = len(parent_citations) + len(extra_citations)
            write_markdown(
                item.get(
                    "markdown",
                    "# "
                    + item["title"]
                    + "\n\n"
                    + "\n\n".join(b.get("text", "") for b in item.get("blocks", [])),
                ),
                item.get("images", {}),
                item.get("inputs", {}),
                item["object_id"],
                item.get("citations", []),
                offset,
            )
            extra_citations.extend(item.get("citations", []))
    if parent_citations or extra_citations:
        doc.add_heading("References", level=2)
        for number, citation in enumerate(parent_citations + extra_citations, 1):
            doc.add_paragraph("[" + str(number) + "] " + bibliography_text(citation))
    doc.core_properties.title = job["object"]["title"]
    path = work / "document.docx"
    doc.save(path)
    files = [str(path)]
    if job.get("math_images"):
        sources = work / "document-equations.json"
        sources.write_text(
            json.dumps(
                {
                    "representation": "visible equation PNG; original math and OMML retained as source, not native Word equation",
                    "equations": [
                        {k: v for k, v in item.items() if k != "input_alias"}
                        for item in job["math_images"].values()
                    ],
                    "runtime": job.get("math_runtime", {}),
                    "latex_compiled": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        files.append(str(sources))
        files.extend(
            job["inputs"][entry["input_alias"]]
            for entry in job["math_images"].values()
            if entry.get("status") == "rendered"
        )
    warnings.append(
        "Supported Markdown: headings, paragraphs, lists, code, emphasis, tables, bound raster images, adopted numeric citations and bounded visible Mathtext equation images with preserved formula/OMML source. Equations are image objects in Word, not native editable equations or LaTeX compilation. Unsupported equations retain full source with occurrence warnings; arbitrary TeX/Word layout and tracked changes are not lossless."
    )
    runtime_info = runtime("python-docx")
    runtime_info["docx_semantics_sha256"] = hashlib.sha256(
        Path(equation_xml.__code__.co_filename).read_bytes()
    ).hexdigest()
    runtime_info["math_renderer"] = job.get("math_runtime", {})
    return {
        "files": files,
        "manifest": manifest,
        "warnings": warnings,
        "runtime": runtime_info,
    }


def slides(job, work):
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN, MSO_AUTO_SIZE
    from PIL import Image

    c = job["object"]["content"]
    pages = c.get("pages", [])
    if not pages:
        raise ValueError("Presentation needs at least one page")
    units = c.get("units", "px")
    w, h, scale = dimensions(pages[0], units)
    prs = Presentation()
    prs.slide_width = Pt(w * scale)
    prs.slide_height = Pt(h * scale)
    warnings, manifest = [], []

    def color(value, default="253a39"):
        val = str(value or default).lstrip("#")
        if len(val) == 3:
            val = "".join(ch * 2 for ch in val)
        return RGBColor.from_string(val[:6])

    for page in pages:
        pw, ph, ps = dimensions(page, units)
        if abs(pw - w) > 1e-6 or abs(ph - h) > 1e-6:
            raise ValueError("PPTX requires all slide sizes to agree")
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.name = page.get("title", page["id"])
        slide.background.fill.solid()
        slide.background.fill.fore_color.rgb = color(page.get("background"), "ffffff")
        grouped = {}
        for item in sorted(page.get("objects", []), key=lambda x: x.get("z", 0)):
            x, y, iw, ih = [
                float(item.get(k, 0)) for k in ["x", "y", "width", "height"]
            ]
            if iw <= 0 or ih <= 0:
                raise ValueError("Object dimensions must be positive: " + item["id"])
            if x < 0 or y < 0 or x + iw > w + 0.001 or y + ih > h + 0.001:
                warnings.append("Object outside slide: " + item["id"])
            target = slide.shapes
            if item.get("group"):
                if item["group"] not in grouped:
                    grouped[item["group"]] = slide.shapes.add_group_shape()
                    grouped[item["group"]].name = item["group"]
                target = grouped[item["group"]].shapes
            geometry = [Pt(v * scale) for v in [x, y, iw, ih]]
            if item.get("type") == "image":
                path = job["inputs"][item["id"]]
                if Path(path).suffix.lower() == ".svg":
                    raise ValueError(
                        "PPTX image insertion currently requires PNG/JPEG; retain the editable SVG component separately and use its registered PNG export"
                    )
                with Image.open(path) as image:
                    ratio = image.width / image.height
                boxratio = iw / ih
                if ratio > boxratio:
                    newh = iw / ratio
                    geometry = [
                        Pt(x * scale),
                        Pt((y + (ih - newh) / 2) * scale),
                        Pt(iw * scale),
                        Pt(newh * scale),
                    ]
                else:
                    neww = ih * ratio
                    geometry = [
                        Pt((x + (iw - neww) / 2) * scale),
                        Pt(y * scale),
                        Pt(neww * scale),
                        Pt(ih * scale),
                    ]
                shape = target.add_picture(path, *geometry)
            else:
                shape = (
                    target.add_shape(MSO_SHAPE.RECTANGLE, *geometry)
                    if item.get("type") == "shape"
                    else target.add_textbox(*geometry)
                )
                if item.get("fill") and item["fill"] != "transparent":
                    shape.fill.solid()
                    shape.fill.fore_color.rgb = color(item["fill"])
                else:
                    shape.fill.background()
                shape.line.fill.background()
                tf = shape.text_frame
                tf.clear()
                tf.word_wrap = True
                tf.auto_size = MSO_AUTO_SIZE.NONE
                tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
                for index, line in enumerate(str(item.get("text", "")).split("\n")):
                    p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
                    p.text = line
                    p.alignment = {
                        "left": PP_ALIGN.LEFT,
                        "center": PP_ALIGN.CENTER,
                        "right": PP_ALIGN.RIGHT,
                    }.get(item.get("align"), PP_ALIGN.LEFT)
                    p.font.size = Pt(float(item.get("font_size", 24)) * scale)
                    p.font.name = "Arial"
                    p.font.bold = bool(item.get("bold"))
                    p.font.color.rgb = color(item.get("color"))
            shape.name = item["id"]
            manifest.append(
                {
                    "id": item["id"],
                    "page_id": page["id"],
                    "type": item.get("type", "text"),
                    "editable": item.get("type") != "image",
                    "bbox": [x, y, iw, ih],
                    "units": units,
                }
            )
        slide.notes_slide.notes_text_frame.text = page.get("notes", "")
    path = work / "slides.pptx"
    prs.save(path)
    notes = work / "speaker_notes.md"
    notes.write_text(
        "\n\n".join(
            "## "
            + str(i + 1)
            + ". "
            + p.get("title", p["id"])
            + "\n\n"
            + p.get("notes", "")
            + "\n\n<!-- page_id: "
            + p["id"]
            + " -->"
            for i, p in enumerate(pages)
        ),
        encoding="utf-8",
    )
    return {
        "files": [str(path), str(notes)],
        "manifest": manifest,
        "warnings": warnings,
        "runtime": runtime("python-pptx", "Pillow"),
    }


def main():
    request = Path(sys.argv[1])
    job = json.loads(request.read_text())
    work = Path(job["output_dir"])
    response = Path(job["response"])
    budget = None
    try:
        budget = OutputBudget(job.get("output_limit_bytes", DEFAULT_OUTPUT_LIMIT_BYTES))
        capture = BoundedTextCapture(budget, "stdout")
        errors = BoundedTextCapture(budget, "stderr")
        with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(errors):
            result = {
                "figure": figure,
                "canvas": canvas,
                "document": document,
                "slides": slides,
            }[job["operation"]](job, work)
        budget.check()
        result.update(
            {
                "ok": True,
                "script_stdout": capture.getvalue(),
                "script_stderr": errors.getvalue(),
            }
        )
    except Exception as exc:
        error = exc
        if budget is not None:
            try:
                budget.check()
            except OutputLimitExceeded as limit_exc:
                error = limit_exc
        result = {
            "ok": False,
            "error": str(error),
            "type": type(error).__name__,
            "traceback": traceback.format_exc()[-16000:],
        }
        if isinstance(error, OutputLimitExceeded):
            result["code"] = "render_output_limit"
        if budget is not None:
            result.update(
                {
                    "script_stdout": budget.text("stdout"),
                    "script_stderr": budget.text("stderr"),
                }
            )
    response.write_text(
        json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(json.dumps({"ok": result["ok"], "response": str(response)}))


if __name__ == "__main__":
    main()
