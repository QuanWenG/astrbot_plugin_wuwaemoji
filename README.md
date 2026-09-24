# astrbot_plugin_wuwaemoji

AstrBot 插件：从[呜哇小站 · 表情包仓鼠库](https://emoji.wuwa.games)获取**随机鸣潮表情包**，并在 QQ 中发送。

适配 **OneBot（aiocqhttp）** 与 **QQ 官方机器人（qq_official / qq_official_webhook）**，包含官 bot 的「频道」消息。

## 功能

- `龟龟鸣潮` / `龟龟表情` / `鸣潮表情包` / `呜哇小站`：随机获取一张鸣潮表情包
- 可在指令后跟角色名，获取该角色的随机表情：`龟龟表情 爱弥斯`
- **带不带 `/` 都能响应**：`/龟龟鸣潮`、`龟龟鸣潮`、`@机器人 龟龟鸣潮` 均可

## 指令

四个指令**行为完全一致**，仅作别名区分。角色名按小站的中文名精确匹配。

| 指令 | 说明 |
| --- | --- |
| `龟龟鸣潮` | 随机一张鸣潮表情包 |
| `龟龟鸣潮 爱弥斯` | 随机一张「爱弥斯」的表情包 |
| `龟龟表情` / `鸣潮表情包` / `呜哇小站` | 同 `龟龟鸣潮` |
| `呜哇小站 爱弥斯` | 同 `龟龟鸣潮 爱弥斯` |

## 安装

1. 将本仓库放入 AstrBot 的 `data/plugins/` 目录（目录名需为 `astrbot_plugin_wuwaemoji`）。
2. 在 AstrBot 面板中重载插件。

本插件不需要额外的 `requirements.txt`：HTTP 请求使用 AstrBot 内置依赖 `aiohttp`。

## 配置

在 **AstrBot 面板 → 插件 → 龟龟鸣潮表情包** 中配置：

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `api_token` | string（密文） | 空 | **必填。** 呜哇小站 API Token |
| `api_base` | string | 官方 API 地址 | 一般无需修改 |
| `image_format` | string | `original` | `original`（GIF / PNG）或 `webp` |
| `show_character_name` | bool | `false` | 是否在图片前附带角色名 |
| `timeout` | int | `20` | 网络请求超时（秒） |

### 如何获取 Token

1. 打开 <https://emoji.wuwa.games/api>
2. 点击页面中的 **【点击获取Token】**
3. 复制弹出的 Token（**仅显示这一次**），粘贴到插件的 `api_token` 配置项中

> 小站目前**不接受匿名访问**（会返回 `503 访客身份暂不可用`），因此必须填写 Token。
> 每个 Token 默认限制 60 次/分钟。

## 常见提示对照

| 提示 | 原因与处理 |
| --- | --- |
| 呜哇小站当前不接受匿名访问… | 没有填写 `api_token`，去插件配置里填上 |
| 呜哇小站 API Token 无效、已停用或已过期… | Token 失效，重新获取并更新配置 |
| 没找到角色「XXX」的表情包… | 角色名写错了，或该角色没有公开表情 |
| 呜哇小站请求过于频繁… | 触发限流（60 次/分钟），稍后再试 |
| 连接呜哇小站失败… | AstrBot 所在服务器网络不通或被墙 |

## 实现说明

- 随机接口 `GET /apis/api.random-emoji.wuwa.games/v1alpha1/random`
  通过 `Authorization: Bearer <token>` 鉴权，返回 JSON：`{"id", "character": {...}, "url"}`。
- 返回的 `url` 是带 `ticket` 签名的媒体地址，**公开可下载**；但若请求时带上
  `Authorization` 头会被小站判为 `401`，因此插件下载图片时不带该头。
- 插件会先把图片下载到本地临时文件，再用 `Image.fromFileSystem` 发送。
  QQ 官方机器人的**频道**消息只接受本地文件，纯 URL 图片会被静默丢弃；
  本地文件在 OneBot、官 bot 群聊 / 单聊 / 频道下都能正常发送。
- 指令使用正则过滤器（`@filter.regex`）而不是命令过滤器（`@filter.command`），
  因为后者要求事件先被唤醒前缀或 @ 唤醒，群聊中直接发「龟龟鸣潮」不会被触发。

## 声明

表情包素材来自[呜哇小站 · 表情包仓鼠库](https://emoji.wuwa.games)，版权归原作者所有。
本插件仅调用其公开 API，请遵守小站的服务条款，勿用于商业用途。

## 许可

本项目基于 [MIT License](LICENSE) 开源，Copyright (c) 2026 QuanWenG。
