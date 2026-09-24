"""AstrBot 插件：从呜哇小站获取随机鸣潮表情包并发送到 QQ。

指令：``龟龟鸣潮`` / ``龟龟表情`` / ``鸣潮表情包`` / ``呜哇小站``，
四者行为一致，均可选带角色名。
带不带 ``/`` 唤醒前缀都能响应——为此这里使用 ``@filter.regex`` 而非
``@filter.command``：命令过滤器要求事件先被唤醒前缀 / @ 唤醒，在群聊里
直接发「龟龟鸣潮」时根本不会被求值；而正则过滤器不受唤醒前缀约束。
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from importlib import import_module

import aiohttp

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, StarTools

# 与同级插件 astrbot_plugin_wuwa 相同的加载方式：AstrBot 以包的形式加载插件目录。
_wuwa_api = import_module(".wuwa_api", __package__)

PLUGIN_NAME = "astrbot_plugin_wuwaemoji"

COMMAND_MINGCHAO = "龟龟鸣潮"
COMMAND_BIAOQING = "龟龟表情"
COMMAND_MINGCHAO_PACK = "鸣潮表情包"
COMMAND_WUWA_SITE = "呜哇小站"

#: 全部指令，四者行为完全一致，仅作别名区分。
COMMANDS = (
    COMMAND_MINGCHAO,
    COMMAND_BIAOQING,
    COMMAND_MINGCHAO_PACK,
    COMMAND_WUWA_SITE,
)

#: 单张图片大小上限，超过则放弃发送。
MAX_IMAGE_BYTES = 10 * 1024 * 1024
#: 临时文件保留时长（秒）。发送发生在 handler 返回之后，因此不能立即删除。
TMP_FILE_TTL_SECONDS = 600
#: 角色名长度上限，避免构造出离谱的请求。
MAX_CHARACTER_LENGTH = 64


def command_pattern(command: str) -> str:
    """构造指令正则。

    使用 :func:`re.escape` 以免指令名里的正则元字符影响匹配。末尾只允许跟一个
    可选的角色名，因此「龟龟鸣潮今天天气不错」这类闲聊不会被误触发。
    """
    return rf"^{re.escape(command)}(?:\s+(?P<character>.+?))?\s*$"


class WuwaEmojiPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        # Star.__init__ 会丢弃 config，必须自己保存。
        self.config = config
        self.data_dir = StarTools.get_data_dir(PLUGIN_NAME)
        self.tmp_dir = self.data_dir / "tmp"

    async def initialize(self) -> None:
        """插件加载后创建临时目录，并在缺少 Token 时提醒用户。"""
        try:
            self.tmp_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.error(f"[{PLUGIN_NAME}] 无法创建临时目录 {self.tmp_dir}：{exc}")
        if not self._token():
            logger.warning(
                f"[{PLUGIN_NAME}] 尚未配置呜哇小站 API Token，"
                "当前只能匿名访问，可能会被小站拒绝（503）。"
                "请在插件配置中填写 Token。",
            )

    # ------------------------------------------------------------------ 指令
    # 四个指令行为完全一致，仅作别名区分；带不带 "/" 都能触发。

    @filter.regex(command_pattern(COMMAND_MINGCHAO))
    async def wuwa_mingchao(self, event: AstrMessageEvent):
        """随机获取一张鸣潮表情包（可加角色名，如：龟龟鸣潮 爱弥斯）"""
        async for result in self._handle(event, COMMAND_MINGCHAO):
            yield result

    @filter.regex(command_pattern(COMMAND_BIAOQING))
    async def wuwa_biaoqing(self, event: AstrMessageEvent):
        """随机获取一张鸣潮表情包（可加角色名，如：龟龟表情 爱弥斯）"""
        async for result in self._handle(event, COMMAND_BIAOQING):
            yield result

    @filter.regex(command_pattern(COMMAND_MINGCHAO_PACK))
    async def wuwa_mingchao_pack(self, event: AstrMessageEvent):
        """随机获取一张鸣潮表情包（可加角色名，如：鸣潮表情包 爱弥斯）"""
        async for result in self._handle(event, COMMAND_MINGCHAO_PACK):
            yield result

    @filter.regex(command_pattern(COMMAND_WUWA_SITE))
    async def wuwa_site(self, event: AstrMessageEvent):
        """随机获取一张鸣潮表情包（可加角色名，如：呜哇小站 爱弥斯）"""
        async for result in self._handle(event, COMMAND_WUWA_SITE):
            yield result

    # ------------------------------------------------------------------ 主流程

    async def _handle(self, event: AstrMessageEvent, command: str):
        character = self._extract_character(event, command)

        try:
            local_path, emoji = await self._fetch_emoji(character)
        except _wuwa_api.WuwaApiError as exc:
            logger.warning(f"[{PLUGIN_NAME}] 获取表情失败：{exc}（code={exc.code!r}）")
            yield event.plain_result(_wuwa_api.friendly_message(exc, character))
            event.stop_event()
            return
        except asyncio.TimeoutError:
            logger.warning(f"[{PLUGIN_NAME}] 请求呜哇小站超时。")
            yield event.plain_result("请求呜哇小站超时了，请稍后再试喵~")
            event.stop_event()
            return
        except aiohttp.ClientError as exc:
            logger.warning(f"[{PLUGIN_NAME}] 连接呜哇小站失败：{exc}")
            yield event.plain_result("连接呜哇小站失败，请检查服务器的网络喵~")
            event.stop_event()
            return
        except Exception:
            logger.exception(f"[{PLUGIN_NAME}] 获取表情时发生未预期的错误。")
            yield event.plain_result("获取表情包时出错了，请查看 AstrBot 日志喵~")
            event.stop_event()
            return

        chain: list[Comp.BaseMessageComponent] = []
        if self._show_character_name() and emoji.character_name:
            chain.append(Comp.Plain(emoji.character_name))
        # 用本地文件而不是 URL：官 bot 的「频道」消息只认本地文件，
        # 纯 URL 图片会被静默丢弃；本地文件在 OneBot / 官 bot 群聊 / C2C / 频道都可用。
        chain.append(Comp.Image.fromFileSystem(str(local_path)))

        yield event.chain_result(chain)
        # 必须放在 yield 之后：管道在 yield 处才递归执行后续阶段（含发送阶段），
        # 提前 stop 会导致图片发不出去；放在这里则只用来阻止 LLM 再回复一条。
        event.stop_event()

    # ------------------------------------------------------------------ 取图

    async def _fetch_emoji(self, character: str | None) -> tuple[object, object]:
        """请求随机表情并把图片下载到本地临时文件。

        Returns:
            ``(本地文件路径, EmojiResult)``
        """
        api_base = self._api_base()
        url = _wuwa_api.build_url(
            api_base,
            character,
            self.config.get("image_format"),
        )
        timeout = aiohttp.ClientTimeout(total=self._timeout())

        async with aiohttp.ClientSession(timeout=timeout, trust_env=True) as session:
            async with session.get(
                url,
                headers=_wuwa_api.build_headers(self._token()),
            ) as response:
                body = await response.read()
                if response.status != 200:
                    raise _wuwa_api.parse_error_response(response.status, body)
                try:
                    payload = json.loads(body)
                except ValueError as exc:
                    raise _wuwa_api.WuwaApiError(
                        "呜哇小站返回了无法解析的数据。",
                    ) from exc

            emoji = _wuwa_api.parse_random_response(payload)
            media_url = _wuwa_api.validate_media_url(emoji.media_url, api_base)

            # 下载媒体时不能带 Authorization，否则小站会返回 401。
            async with session.get(
                media_url,
                headers=_wuwa_api.media_headers(),
            ) as media_response:
                if media_response.status != 200:
                    raise _wuwa_api.WuwaApiError(
                        f"下载表情图片失败（HTTP {media_response.status}）。",
                        http_status=media_response.status,
                    )
                content_type = media_response.headers.get("Content-Type", "")
                data = await self._read_limited(media_response)

        suffix = _wuwa_api.guess_suffix(content_type, media_url)
        return self._write_temp_file(data, suffix), emoji

    @staticmethod
    async def _read_limited(response: aiohttp.ClientResponse) -> bytes:
        """流式读取响应体，超过上限立即放弃。"""
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.content.iter_chunked(64 * 1024):
            total += len(chunk)
            if total > MAX_IMAGE_BYTES:
                raise _wuwa_api.WuwaApiError(
                    f"表情图片超过 {MAX_IMAGE_BYTES // (1024 * 1024)} MiB，已放弃发送。",
                )
            chunks.append(chunk)

        data = b"".join(chunks)
        if not data:
            raise _wuwa_api.WuwaApiError("呜哇小站返回了空的图片数据。")
        return data

    def _write_temp_file(self, data: bytes, suffix: str):
        """写入临时文件，并顺手清理过期文件。"""
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        # 先清理再写入，确保不会误删本次刚生成的文件。
        self._prune_tmp_dir()
        path = self.tmp_dir / f"{uuid.uuid4().hex}{suffix}"
        path.write_bytes(data)
        return path

    def _prune_tmp_dir(self) -> None:
        deadline = time.time() - TMP_FILE_TTL_SECONDS
        try:
            entries = list(self.tmp_dir.iterdir())
        except OSError:
            return
        for entry in entries:
            try:
                if entry.is_file() and entry.stat().st_mtime < deadline:
                    entry.unlink()
            except OSError:
                continue

    # ------------------------------------------------------------------ 工具

    @staticmethod
    def _extract_character(event: AstrMessageEvent, command: str) -> str | None:
        """从消息中取出角色名（正则过滤器不向 handler 暴露捕获组）。"""
        text = (event.get_message_str() or "").strip()
        if not text.startswith(command):
            return None
        character = text[len(command) :].strip()
        if not character:
            return None
        return character[:MAX_CHARACTER_LENGTH]

    def _token(self) -> str:
        return str(self.config.get("api_token") or "").strip()

    def _api_base(self) -> str:
        return (
            str(self.config.get("api_base") or "").strip()
            or _wuwa_api.DEFAULT_API_BASE
        )

    def _timeout(self) -> int:
        try:
            value = int(self.config.get("timeout") or 20)
        except (TypeError, ValueError):
            value = 20
        return min(max(value, 5), 120)

    def _show_character_name(self) -> bool:
        return bool(self.config.get("show_character_name", False))

    async def terminate(self) -> None:
        """插件卸载 / 停用时调用。"""
        logger.info(f"[{PLUGIN_NAME}] 插件已停止")
