"""HTTP 协议输入与响应编码；不拥有鉴权、会话或业务路由。"""

from collections.abc import Mapping
from dataclasses import dataclass
import json
import secrets
from typing import Protocol

from .contracts import JsonObject
from .store import Problem, require


MAX_JSON_BODY = 180 * 1024 * 1024
JSON_MEDIA = "application/json; charset=utf-8"
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; worker-src 'self' blob:; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
    "connect-src 'self'; frame-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'self'"
)


class HeaderSource(Protocol):
    def get(self, name: str, default: str | None = None) -> str | None: ...


class BodyStream(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


def read_json_body(
    headers: HeaderSource,
    stream: BodyStream,
    *,
    address: str,
    public_origin: str,
    csrf_token: str,
    csrf_required: bool = True,
    limit: int = MAX_JSON_BODY,
) -> JsonObject:
    origin = headers.get("Origin")
    require(
        not origin or origin == (public_origin or "http://" + address),
        "来源不匹配",
        "forbidden",
        403,
    )
    require(
        headers.get("Sec-Fetch-Site") in {None, "same-origin", "none"},
        "拒绝跨来源请求",
        "forbidden",
        403,
    )
    if csrf_required:
        supplied_csrf = headers.get("X-CSRF-Token") or ""
        require(
            supplied_csrf.isascii()
            and secrets.compare_digest(supplied_csrf, csrf_token),
            "写入令牌失效，请保留草稿并刷新",
            "csrf",
            403,
        )
    require(
        (headers.get("Content-Type") or "").split(";")[0] == "application/json",
        "需要JSON",
        status=415,
    )
    try:
        length = int(headers.get("Content-Length") or "0")
    except ValueError:
        raise Problem("请求大小无效") from None
    require(0 < length <= limit, "请求大小无效")
    raw = stream.read(length)
    require(len(raw) == length, "请求体不完整")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Problem("JSON格式无效") from None
    require(isinstance(data, dict), "需要JSON对象")
    return data


@dataclass(frozen=True)
class EncodedResponse:
    body: bytes
    headers: tuple[tuple[str, str], ...]


def encode_response(
    body: object,
    media: str = JSON_MEDIA,
    extra: Mapping[str, str] | None = None,
) -> EncodedResponse:
    raw = (
        body
        if isinstance(body, bytes)
        else json.dumps(body, ensure_ascii=False).encode()
    )
    headers = (
        ("Content-Type", media),
        ("Content-Length", str(len(raw))),
        ("X-Content-Type-Options", "nosniff"),
        ("Cache-Control", "no-store"),
        ("Referrer-Policy", "no-referrer"),
        ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
        *tuple((extra or {}).items()),
    )
    return EncodedResponse(raw, headers)
