"""渲染进程共享的标准库信封契约，不依赖应用或科学运行时。"""

from __future__ import annotations

from typing import Literal, NotRequired, Sequence, TypedDict, cast

RenderOperation = Literal["figure", "canvas", "document", "slides"]
RENDER_OPERATIONS = frozenset({"figure", "canvas", "document", "slides"})
MAX_PATH_LENGTH = 32768


class ProcessRecord(TypedDict):
    command: Sequence[str]
    returncode: int
    elapsed_seconds: float
    stdout: str
    stderr: str


class RenderRequest(TypedDict):
    operation: RenderOperation
    output_dir: str
    response: str
    output_limit_bytes: NotRequired[int]
    object: NotRequired[dict[str, object]]
    inputs: NotRequired[dict[str, str]]
    script: NotRequired[str]
    spec: NotRequired[dict[str, object]]
    parameters: NotRequired[dict[str, object]]
    overlays: NotRequired[list[dict[str, object]]]
    preview: NotRequired[bool]
    markdown: NotRequired[str]
    segments: NotRequired[list[dict[str, object]]]
    components: NotRequired[list[dict[str, object]]]
    images: NotRequired[dict[str, str]]
    image_warnings: NotRequired[list[str]]
    citations: NotRequired[list[dict[str, object]]]
    math_images: NotRequired[dict[str, dict[str, object]]]
    math_runtime: NotRequired[dict[str, object]]


class RenderSuccess(TypedDict):
    ok: Literal[True]
    files: NotRequired[list[str]]
    manifest: NotRequired[list[dict[str, object]]]
    warnings: NotRequired[list[str]]
    runtime: NotRequired[dict[str, object]]
    script_stdout: NotRequired[str]
    script_stderr: NotRequired[str]
    process: NotRequired[ProcessRecord]


class RenderFailure(TypedDict):
    ok: Literal[False]
    error: str
    type: str
    code: NotRequired[str]
    traceback: NotRequired[str]
    script_stdout: NotRequired[str]
    script_stderr: NotRequired[str]


RenderResult = RenderSuccess | RenderFailure


class RenderContractError(ValueError):
    """公共信封无效；错误消息只包含固定字段名，不回显输入。"""


def _path_field(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > MAX_PATH_LENGTH
        or "\x00" in value
    ):
        raise RenderContractError(f"Invalid render path field: {field}")
    return value


def render_response_path(value: object) -> str:
    """即使其他字段无效，也允许调用方确定失败结果的目标路径。"""
    if not isinstance(value, dict):
        raise RenderContractError("Render request must be an object")
    return _path_field(value.get("response"), "response")


def validate_render_request(value: object) -> RenderRequest:
    """只校验有界公共信封；保留未知领域字段，由各渲染器解释。"""
    render_response_path(value)
    request = cast(dict[str, object], value)
    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in RENDER_OPERATIONS:
        raise RenderContractError("Invalid render operation")
    _path_field(request.get("output_dir"), "output_dir")
    if "output_limit_bytes" in request:
        limit = request["output_limit_bytes"]
        if type(limit) is not int or limit <= 0:
            raise RenderContractError("Invalid render output_limit_bytes")
    return cast(RenderRequest, request)


def validate_render_result(value: object) -> RenderResult:
    """校验共享结果字段，不限制渲染器额外的领域结果。"""
    if not isinstance(value, dict) or type(value.get("ok")) is not bool:
        raise RenderContractError("Invalid render result status")
    if value["ok"] is False:
        for field in ("error", "type"):
            if not isinstance(value.get(field), str):
                raise RenderContractError(f"Invalid render result field: {field}")
    for field in ("code", "traceback", "script_stdout", "script_stderr"):
        if field in value and not isinstance(value[field], str):
            raise RenderContractError(f"Invalid render result field: {field}")
    if "files" in value and (
        not isinstance(value["files"], list)
        or any(not isinstance(path, str) for path in value["files"])
    ):
        raise RenderContractError("Invalid render result field: files")
    return cast(RenderResult, value)
