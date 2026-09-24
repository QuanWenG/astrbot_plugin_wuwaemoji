"""呜哇小站随机表情 API 客户端。

本模块只包含**纯逻辑**（URL 构造、响应解析、错误映射），不依赖 AstrBot，
因此可以在没有安装 AstrBot 的环境下直接做单元测试。

API 契约（实测于 2026-09）：

* ``GET {api_base}``，请求头必须带 ``Authorization: Bearer <token>``。
  - 不带该头 -> ``503 IDENTITY_UNAVAILABLE``（匿名访客身份不可用）
  - Token 无效 -> ``401 UNAUTHORIZED``
  - 注意 ``Bearer `` 前缀是必需的：直接把裸 Token 放进该头会被判为无效。
* 查询参数**只**接受 ``character``（中文角色名）与 ``format``
  （``original`` / ``webp``）；出现未知或重复参数会返回 ``400 INVALID_QUERY``。
* 成功返回 ``{"id", "character": {"slug", "name"}, "url"}``，
  其中 ``url`` 是带 ``ticket`` 签名的媒体地址。
* 媒体地址**无需鉴权**即可下载；但一旦附带 ``Authorization`` 头会返回 401，
  因此下载时绝不能带该头。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit

#: 官方 API 地址。
DEFAULT_API_BASE = (
    "https://emoji.wuwa.games/apis/api.random-emoji.wuwa.games/v1alpha1/random"
)

#: API 支持的 format 取值。
SUPPORTED_FORMATS = ("original", "webp")

#: 允许的媒体地址主机后缀，防止响应被篡改后指向任意外站。
_ALLOWED_HOST_SUFFIXES = (".wuwa.games",)

_CONTENT_TYPE_SUFFIX = {
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/bmp": ".bmp",
}

_KNOWN_SUFFIXES = (".png", ".gif", ".webp", ".jpg", ".jpeg", ".bmp")

#: 服务端错误码 -> 面向用户的中文提示。
ERROR_TEXT = {
    "UNAUTHORIZED": "呜哇小站 API Token 无效、已停用或已过期，请在插件配置中更新 Token。",
    "IDENTITY_UNAVAILABLE": (
        "呜哇小站当前不接受匿名访问，请在插件配置中填写 API Token"
        "（在 https://emoji.wuwa.games/api 点击【点击获取Token】获取）。"
    ),
    "CHARACTER_EMPTY": "呜哇小站没有找到符合条件的表情包。",
    "INVALID_FORMAT": "图片格式参数不受支持，请把「图片格式」改回默认值。",
    "INVALID_QUERY": "请求参数不被呜哇小站接受，可能是插件版本过旧，请更新插件。",
}


class WuwaApiError(Exception):
    """调用呜哇小站 API 失败。"""

    def __init__(
        self,
        message: str,
        *,
        code: str = "",
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


@dataclass(frozen=True)
class EmojiResult:
    """一次随机表情的结果。"""

    emoji_id: str
    character_slug: str
    character_name: str
    media_url: str


def _as_text(value: object) -> str:
    """把任意配置值安全地转成字符串（配置可能被写成数字或 null）。"""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return str(value)


def normalize_format(image_format: object) -> str:
    """把配置值规整为合法的 format 取值，非法时回退 ``original``。"""
    value = _as_text(image_format).strip().lower()
    return value if value in SUPPORTED_FORMATS else "original"


def build_url(
    api_base: str | None,
    character: str | None = None,
    image_format: str | None = None,
) -> str:
    """构造随机表情请求 URL。

    ``original`` 是服务端默认值，因此这种情况下**不会**附带 ``format`` 参数，
    避免任何触发 ``INVALID_QUERY`` 的可能；``character`` 为空时同样省略。
    """
    base = _as_text(api_base).strip() or DEFAULT_API_BASE

    params: list[tuple[str, str]] = []
    character = _as_text(character).strip()
    if character:
        params.append(("character", character))
    if normalize_format(image_format) == "webp":
        params.append(("format", "webp"))

    if not params:
        return base
    separator = "&" if urlsplit(base).query else "?"
    return f"{base}{separator}{urlencode(params)}"


def build_headers(token: str | None) -> dict[str, str]:
    """构造请求头；Token 为空时退回匿名访问（当前服务端会拒绝）。"""
    headers = {"Accept": "application/json"}
    token = _as_text(token).strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def media_headers() -> dict[str, str]:
    """下载媒体时使用的请求头。

    **绝不能**包含 ``Authorization``：带着它请求媒体地址会被小站判为 401。
    """
    return {"Accept": "image/*,*/*"}


def validate_media_url(url: str | None, api_base: str | None) -> str:
    """校验媒体地址合法且域名可信，返回原地址。"""
    url = _as_text(url).strip()
    if not url:
        raise WuwaApiError("呜哇小站返回的图片地址为空。")

    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise WuwaApiError("呜哇小站返回了非法的图片地址。")

    host = (parts.hostname or "").lower()
    api_host = (
        urlsplit(_as_text(api_base).strip() or DEFAULT_API_BASE).hostname or ""
    ).lower()
    if host and (host == api_host or host.endswith(_ALLOWED_HOST_SUFFIXES)):
        return url

    raise WuwaApiError(f"呜哇小站返回的图片地址不在允许的域名内：{host or '未知'}")


def parse_random_response(payload: object) -> EmojiResult:
    """解析成功响应。"""
    if not isinstance(payload, dict):
        raise WuwaApiError("呜哇小站返回了非预期的数据格式。")

    character = payload.get("character")
    if not isinstance(character, dict):
        character = {}

    return EmojiResult(
        emoji_id=str(payload.get("id") or ""),
        character_slug=str(character.get("slug") or ""),
        character_name=str(character.get("name") or ""),
        media_url=str(payload.get("url") or ""),
    )


def parse_error_response(status: int, body: bytes | str | None) -> WuwaApiError:
    """把非 200 响应转成 :class:`WuwaApiError`。"""
    code = ""
    message = ""

    if body:
        try:
            data = json.loads(body)
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            code = str(data.get("code") or "")
            message = str(data.get("message") or "")

    if not message:
        message = f"呜哇小站返回了 HTTP {status}。"

    return WuwaApiError(message, code=code, http_status=status)


def friendly_message(error: object, character: str | None = None) -> str:
    """把异常转成适合直接发给用户的中文提示。"""
    if not isinstance(error, WuwaApiError):
        return str(error) or "调用呜哇小站 API 失败。"

    if error.code == "CHARACTER_EMPTY":
        name = (character or "").strip()
        if name:
            return f"没找到角色「{name}」的表情包，请检查角色名是否正确喵~"
        return "呜哇小站暂时没有可用的表情包，请稍后再试喵~"

    if error.code in ERROR_TEXT:
        return ERROR_TEXT[error.code]

    if error.http_status == 429:
        return "呜哇小站请求过于频繁，请稍后再试喵~"

    if error.http_status:
        return f"呜哇小站返回错误（HTTP {error.http_status}）：{error.message}"

    return error.message or "调用呜哇小站 API 失败。"


def guess_suffix(content_type: str | None, url: str | None = "") -> str:
    """根据 Content-Type（其次 URL 后缀）推断图片扩展名。"""
    media_type = (content_type or "").split(";")[0].strip().lower()
    if media_type in _CONTENT_TYPE_SUFFIX:
        return _CONTENT_TYPE_SUFFIX[media_type]

    path = urlsplit(url or "").path.lower()
    for suffix in _KNOWN_SUFFIXES:
        if path.endswith(suffix):
            return ".jpg" if suffix == ".jpeg" else suffix

    return ".png"
