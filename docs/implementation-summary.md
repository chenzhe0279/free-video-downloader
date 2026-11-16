# 万能视频下载站 · 功能实现总结

> 版本：v0.8（2026-11-14）
> 关联文档：[需求分析](./requirements.md) · [v0.8 总结流设计](./v0.8-streaming-summary-design.md) · [v0.7 同屏工作台设计](./v0.7-single-screen-design.md) · [v0.6 内容体验设计](./v0.6-content-experience-design.md) · [AI 总结设计](./ai-summary-design.md) · [AI 问答设计](./ai-qa-design.md) · [项目 README](../README.md)

---

## 最新交付（2026-11-17）

**账号与权益。** 新增邮箱注册、验证、登录、退出和重置密码。MySQL 8 通过 Alembic 迁移保存用户、会话、订单、事件与会员每日用量。月卡 ¥19 / 30 天，年卡 ¥149 / 365 天，均为一次性付款。会员按账号每天可新建 20 次 AI 总结，北京时间零点重置。缓存命中免扣额度，免费用户继续按 IP 使用现有额度。

**支付。** 使用 Stripe 托管收银台处理银行卡付款。每个账号同一时间最多一笔待付款订单。点击重试复用订单和幂等键，取消后以 Stripe 的实际状态为准。Webhook 验签并持久化事件，再核对套餐、金额、币种和环境后更新权益。全额退款撤销权益，部分退款保留权益。拒付暂停权益，胜诉后恢复原到期日，败诉撤销。支付环境和运营对账见 [Stripe 会员验收指南](./stripe-membership.md)。

**前端。** 首屏改为深墨色解析区配暖金色主按钮，桌面显示双栏，手机显示单列。示例封面使用内置 ImageGen 生成的日出群山照片，压缩为 [WebP](../frontend/public/clipnest-preview.webp) 后本地交付。导航、免费/月卡/年卡卡片、登录及订单弹窗采用同一套视觉。套餐仍展示有效期、支付方式和实际权益，FAQ、结构化数据和公开定价同步更新。

**设计工具。** Windows 已通过 `npm install -g uipro-cli` 安装 CLI，`ui-ux-pro-max` 位于用户级 `~/.codex/skills/ui-ux-pro-max`。本次使用 CLI 的 `uipro init --ai codex --offline` 在临时目录生成技能，再将生成的技能目录安装到用户目录，供其他项目复用。项目运行无需安装此技能或 CLI。

**验收。** 本地 MySQL 集成回归通过 118 项测试。前端构建、TypeScript 检查和 SEO 构建检查通过。Chromium 已核对 375、768、1024 和 1440 像素布局，验证解析表单的空输入反馈、会员入口和 Escape 关闭弹窗，并走完注册、SMTP 验证、模拟付款拒绝后继续付款、签名回调开通和全额退款流程。已验证 Stripe CLI 可取得沙盒签名密钥，`/api/payment/webhook` 本地验签通过。真实 Stripe 沙盒购买还需配置两档 CNY Price ID，正式收款默认关闭。

---

## 0. 本期新增（v0.8）

2026-11-14 本轮把「等待总结」的进度条改成大模型式思考态，总结完成后用 SSE 打字机输出，并把双栏工作台改为等高固定布局，同时更新顶栏会员入口：

| 新增能力 | 说明 | 详见 |
|---|---|---|
| 无进度条思考态 | 生成期间只显示跳动圆点、「正在总结中…」、阶段文案、已用时与取消；不再出现百分比/进度条 | 第 16 节 · [设计文档](./v0.8-streaming-summary-design.md) |
| SSE 总结流 + 打字机 | 新增 `GET /api/summary/{task_id}/stream`；`state → meta → delta* → done`；完成后打开结果界面并逐块打出 Markdown；断流回退轮询 | 第 16 节 |
| 等高固定双栏 | ≥1024px 两栏固定为 `100dvh - 5.5rem`、彼此等高、各自内部滚动；页面滚动时整体移动（取消吸顶）；移动端/降级单列 | 第 16 节 |
| 顶栏「升级 Pro」 | 「开通会员」改为品牌蓝胶囊「升级 Pro」，链接 `#pricing` | 第 16 节 |
| 测试与验收 | 后端 110 测试；`tsc` + `vite build`；workspace/content/degraded 三个浏览器脚本全绿 | 第 16 节 |

> 上一轮（v0.7）交付的同屏双栏、解析即总结见第 15 节。本轮后端新增的是**呈现层 SSE 端点**，总结生成 / 缓存 / 额度 / 任务模型均未改；`SummaryTaskStatus.progress` 保留用于轮询兼容，UI 不再展示。

---

## 1. 背景与目标

本项目最初只支持 yt-dlp 能直接处理的链接：解析出格式后，用浏览器直链或服务端转存的方式下载。实际使用中遇到三类问题：

1. **高清格式无法直接下载**：B 站等平台的 1080P 是音视频分离的 DASH，必须由服务端合并后才能交付；用户希望合并完成后直接落到本机，而不是先转存到服务器再手动取回。
2. **抖音链接完全不可用**：yt-dlp 不识别 `douyin.com/jingxuan?modal_id=...` 这类 URL，且其抖音 extractor 在没有 Cookie 时会报 `Fresh cookies ... are needed`。用户要求**不提供 Cookie、不登录**也能下载无水印抖音视频。
3. **解析后无法先确认内容**：用户希望解析完就能在网页里直接播放，确认是不是目标视频、画面是否正常，再决定下载哪种清晰度；而不是下载完再打开文件核对。

本阶段完成了：

- 「下载到本地」交付通道；
- 抖音专用解析与无水印下载；
- B 站按视频配置的去水印；
- 网页内「在线预览」播放器与预览接口；
- 后端依赖从 pip 迁移到 uv；
- 相关前端交互与验证。

## 2. 功能总览

| 能力 | 说明 |
|------|------|
| 链接解析 | `POST /api/probe` 返回标题、封面、时长、作者、平台、清晰度列表 |
| 在线预览 | `POST /api/preview`；单文件格式走代理流边下边播，分离格式服务端合并后在线播放，支持 Range |
| 下载到本地 | 服务端完成合并/转码后，把文件流式传给浏览器；浏览器下载完成后服务器副本按 TTL 清理 |
| 服务端转存 | 文件保存在服务器，保留 1 小时，可换设备或稍后取回 |
| 直链 | 浏览器直接访问平台 CDN，速度最快；防盗链平台可能 403 |
| 代理下载 | 服务端转发直链，补全 Referer/UA，支持 Range |
| 抖音无水印 | 专用解析，服务端自动获取匿名 ttwid，无需用户 Cookie；`playwm` → `play` |
| B 站去水印 | 按视频配置固定区域，ffmpeg `delogo` 有损去除烧录水印 |
| 进度反馈 | 下载进度、速度、已下载/总大小、剩余时间；合并、去水印阶段单独展示 |
| 清理 | 本地任务 15 分钟、服务端任务 1 小时后自动清理；传输中的文件不会被清理线程删除 |
| AI 视频总结 | 平台字幕/DeepSeek ASR → 结构化 TL;DR、章节、要点、概念、文稿、Markdown；缓存与额度控制 |
| AI 视频问答 | 仅基于总结；相关性 gate + 无关拒答；SSE 流式；最近 3 轮多轮对话 |
| Markmap 思维导图 | 彩色分支、根节点胶囊、曲线连接、缩放/拖拽/折叠 |
| 同屏工作台 | 解析结果与 AI 总结左右同屏：左栏播放器/信息/清晰度/下载，右栏总结；≥1024px 两栏等高固定、内部滚动，移动端单列 |
| 解析即总结 | 解析成功自动生成总结（默认开、可关并记忆），缓存复用不占额度，不支持的视频降级为中性提示 |
| 总结思考态 | 生成期间不展示进度条，显示跳动圆点、「正在总结中…」、阶段文案、已用时与取消 |
| SSE 总结流 | `GET /api/summary/{id}/stream`；完成后打开结果界面，Markdown 按块下发，前端打字机渲染；断流回退轮询 |
| 升级 Pro | 顶栏品牌蓝胶囊 CTA，链接会员权益区；套餐按钮保持不变 |

## 3. 目录与架构

```
backend/
  app/
    api/
      probe.py           # 解析
      preview.py         # 在线预览：代理 / 合并任务 / 内联播放地址
      download.py        # 创建任务 / 直链 / 代理 / 本地
      stream.py          # 文件 Range 下载、代理流、预览代理
      summary.py         # AI 总结任务 / 配置 / 文稿
      qa.py              # AI 问答 SSE 路由
    services/
      media.py           # 平台调度：抖音专用 / 其他平台 yt-dlp
      douyin.py          # 抖音 ttwid、分享页 SSR、无水印地址、WAF 兜底
      ytdlp_service.py   # yt-dlp 解析、格式归一化、直链
      task_manager.py    # 任务、下载、合并、去水印、TTL、传输保护
      watermark.py       # 按视频配置的 delogo 去水印
      cleanup.py         # 过期任务/孤儿目录清理
      summary/           # 逐字稿、DeepSeek ASR/总结、任务与缓存
      qa/                # 总结材料、相关性 gate、SSE 流式问答
    data/
      watermark_profiles.json
    schemas.py
    config.py
    security.py
    utils.py             # 安全文件名、下载文件名
  tests/                 # 单元测试 / Mock DeepSeek / 浏览器验收脚本
  pyproject.toml
  uv.lock
  .python-version
frontend/
  src/
    api/client.ts
    views/Home.vue
    components/ResultPanel.vue
    components/PreviewPlayer.vue
    components/TaskProgress.vue
    components/AiSummaryPanel.vue   # AI 总结 / 问答容器
    components/QaChatPanel.vue      # 流式问答面板
    components/MindmapTree.vue      # Markmap 思维导图
    utils/format.ts
docs/
  requirements.md
  implementation-summary.md
  ai-summary-design.md
  ai-qa-design.md
runtime/                 # 运行时下载、验证产物（gitignore，不放代码）
```

调度关系：

```
前端
  └─ POST /api/probe ──► services/media.probe
                         ├─ douyin.probe（抖音）
                         └─ ytdlp_service.probe（其他平台）

  └─ POST /api/preview
       ├─ 单文件直链 ──► token_store → /api/preview/proxy/{token}（边下边播）
       └─ 音视频分离 ──► task_manager(mode=preview) → /api/files/{id}?inline=1

  └─ POST /api/download
       ├─ mode=local   ──► 单文件：代理流直接下载
       │                  音视频分离：task_manager 合并/去水印 → /api/files/{id}
       ├─ mode=server  ──► task_manager → /api/files/{id}
       ├─ mode=direct  ──► resolve_direct 返回平台直链
       └─ mode=proxy   ──► token_store → /api/proxy/{token}

  └─ POST /api/summary ──► summary_manager
       ├─ 字幕优先 / DeepSeek ASR 分片
       ├─ deepseek-flash JSON 结构化总结
       └─ 缓存 + TTL；GET /api/summary/{id} 轮询

  └─ POST /api/summary/{id}/ask ──► qa (SSE)
       ├─ 相关性 gate（无关 → refusal）
       └─ stream_chat（逐 token → token 事件）→ done
```

## 4. 关键实现

### 4.1 下载到本地

- 新增 `DownloadMode = "local"`，与 `server`/`direct`/`proxy` 并列。
- DASH 等需要合并的格式：先创建任务，状态依次为 `downloading → processing → finished`；前端轮询到 `finished` 后自动触发浏览器下载。
- 单文件格式：后端只生成一个带 TTL 的代理流地址，浏览器直接从 CDN 取文件，服务器不落盘。
- 本地任务使用更短的 `VDS_LOCAL_FILE_TTL_SECONDS`（默认 900 秒），服务端转存仍为 3600 秒。
- `/api/files/{id}` 支持 `Range`，下载文件名由 `build_filename(title, label, ext)` 生成；传输期间用 `begin_serve/end_serve` 计数，避免清理线程删除正在读取的文件。
- 前端结果页主按钮为「下载到本地」，「服务端转存」和「直链」作为次级操作；任务卡完成后提供「再次保存到本机」。

### 4.2 在线预览

目标：解析完成后，用户不离开页面就能播放当前选中的清晰度。

- 新增 `POST /api/preview`，入参 `{url, option_id}`，返回三种模式：
  - `proxy`：单文件格式（抖音、YouTube progressive 等），服务端用 `token_store` 生成短期 token，`/api/preview/proxy/{token}` 补全 Referer/UA 并透传 Range，浏览器边下边播，服务器不落盘；
  - `file`：同一 IP 的相同清晰度已有完成的预览副本，直接返回 `/api/files/{id}?inline=1`；
  - `task`：音视频分离（B 站高清）或容器不可直接播放，创建 `mode=preview` 任务，前端轮询到 `finished` 后播放 `/api/files/{id}?inline=1`。
- `DownloadTask.mode` 增加 `preview`，TTL 复用 `VDS_LOCAL_FILE_TTL_SECONDS`（默认 900 秒）；`TaskStatus.mode` 同步扩展。
- `manager.find_preview()` 按「IP + URL + 清晰度」复用进行中或已完成的预览任务，重复点击播放不会重复合并。
- `/api/files/{id}` 增加 `inline` 查询参数：`inline=1` 时 `Content-Disposition: inline`，下载场景仍为 `attachment`。
- 浏览器不能直接播放的容器（如 B 站低清 flv）在任务完成前用 ffmpeg `-c copy` 无损重新封装为 MP4，再交给 `<video>`。
- 预览相关请求单独使用 `VDS_PREVIEW_RATE_LIMIT_PER_MINUTE`（默认 120 次/分钟），避免拖动进度条产生的多次 Range 请求触发下载限流。
- 前端 `PreviewPlayer.vue`：`idle` 显示封面 + 播放按钮；`preparing` 显示进度；`ready` 切换为原生 `<video controls>`；`error` 提供重试。解析完成后对可直链的清晰度静默预取代理地址（不自动播放），用户点播放即可秒开。
- `Home.vue` 独立维护预览状态与轮询，不复用下载任务卡；切换清晰度、重新解析、组件卸载时停止轮询并删除旧预览任务。

### 4.3 抖音无水印解析（无需用户 Cookie）

核心流程（`backend/app/services/douyin.py`）：

1. 识别 `douyin.com` / `iesdouyin.com` / `v.douyin.com` 链接，提取 aweme_id：
   - `?modal_id=`、`?aweme_id=` 等 query；
   - `/video/{id}`、`/note/{id}`、`/share/video/{id}`；
   - 短链跟随 302 后提取。
2. 服务端 `POST https://ttwid.bytedance.com/ttwid/union/register/` 获取匿名 `ttwid`（12 小时内存缓存），这是设备级匿名 token，**不是用户 Cookie**。
3. 用 iPhone Safari UA + Referer + ttwid 请求 `https://www.iesdouyin.com/share/video/{aweme_id}/`。
4. 解析 `window._ROUTER_DATA`，在 `loaderData` 中找 `videoInfoRes.item_list[0]`。
5. 取 `video.play_addr.url_list[0]`，把 `playwm` 替换为 `play`，得到无水印地址。
6. 用 HEAD 比较 `ratio=1080p` 和 `ratio=720p` 的 `content-length`，优先选择 1080P；不可用时回退 720P。
7. 分享页触发 WAF 时，刷新 ttwid 重试一次；仍为挑战页则尝试 SHA-256 proof-of-work（参考 MIT 项目 `rathodpratham-dev/douyin_video_downloader`，代码中保留归属注释）。

平台调度在 `services/media.py`：抖音走专用模块，其他平台继续交给 yt-dlp；`probe.py` / `download.py` / `task_manager.py` 统一使用 `media.probe`、`media.resolve_direct` 和 `MediaError`。

服务端下载：`task_manager` 新增 `direct_url` 分支，用 `httpx` 流式下载并更新进度/速度/ETA；因此「服务端转存」对抖音同样可用，不再依赖 yt-dlp。

抖音只支持视频：图文/图集会返回 422 并提示暂不支持。

### 4.4 B 站去水印

- 配置在 `backend/app/data/watermark_profiles.json`，按视频 ID 登记：
  ```json
  {
    "BV1s18cziEtw": {
      "label": "B站左上角 UP 主水印与右上角签名",
      "reference": [1280, 720],
      "regions": [[18, 16, 168, 58], [1146, 14, 108, 56]]
    }
  }
  ```
- `watermark.py` 按实际分辨率缩放区域，用 ffmpeg `delogo` 生成 `clean.mp4`；去水印在合并之后执行，任务状态为 `cleaning`。
- 去水印是固定区域、有损重编码（H.264 CRF 18）；平坦背景可能留下轻微填补痕迹，不承诺对所有视频通用。
- 前端仅在 `probe.watermark.available=true` 时显示「去水印 · 有损重编码」开关，默认勾选。
- 曾评估 `removelogo`：质量更好，但 1080P 下比 `delogo` 慢约 50 倍（5 秒片段约 32 秒 vs 0.7 秒），因此选择 `delogo`。

### 4.5 后端依赖迁移到 uv

- 删除旧 `.venv`、23 个 `pip-*` 临时目录和 `requirements.txt`。
- 新增 `backend/pyproject.toml`（FastAPI、uvicorn、yt-dlp、httpx、pydantic、pydantic-settings、imageio-ffmpeg），`[tool.uv] package = false`。
- 新增 `backend/uv.lock` 和 `.python-version`（3.12）。
- 启动方式：
  ```powershell
  cd backend
  uv sync
  uv run uvicorn app.main:app --reload
  ```
- `uv.lock` 是按当前网络用清华镜像生成的；换网络后可执行 `uv lock --default-index https://pypi.org/simple` 重新生成。

### 4.6 前端

- `Home.vue`：解析、下载、轮询、自动接收文件；「下载到本地」与「服务端转存」共用任务进度组件；在线预览状态独立维护。
- `ResultPanel.vue`：顶部为在线播放器，下方为视频信息与清晰度列表；主按钮「下载到本地」；直链/服务端转存次级操作；去水印开关。
- `PreviewPlayer.vue`：播放器状态机与原生 `<video>` 切换，封面、准备进度、错误重试。
- `TaskProgress.vue`：`cleaning` 状态显示「去水印中」；本地任务完成后提示 15 分钟清理。
- 平台标签沿用 `utils/format.ts`，抖音显示为「抖音」。
- `frontend/vite.config.ts` 保留用户添加的 `watch.ignored` 配置。

## 5. API 与数据结构

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/probe` | 解析链接；返回 `watermark: {available, label}` |
| POST | `/api/preview` | 准备在线播放地址；返回 `mode=proxy/file/task` |
| GET | `/api/preview/proxy/{token}` | 预览代理：内联播放，透传 Range 与 Referer/UA |
| POST | `/api/download` | 创建下载；`mode=server/direct/proxy/local`，`remove_watermark` 可选 |
| GET | `/api/tasks/{id}` | 任务状态、进度、速度、ETA、`expires_in`、下载地址 |
| DELETE | `/api/tasks/{id}` | 主动删除任务与文件 |
| GET | `/api/files/{id}` | 服务端文件下载，支持 Range；`inline=1` 时用于在线播放 |
| GET | `/api/proxy/{token}` | 代理直链，透传 Range 与 Referer/UA |
| GET | `/api/health` | 健康检查（ffmpeg、大小上限、TTL） |
| GET | `/api/summary/{task_id}/stream` | AI 总结 SSE：`state/meta/delta/done/error/cancelled/gone`；思考态与打字机；任务不存在返回 404 |

任务状态：`queued`、`downloading`、`processing`、`cleaning`、`finished`、`error`；`mode` 为 `server`、`local` 或 `preview`。

抖音 probe 的选项示例（内部字段 `direct_url`/`headers` 不会返回前端）：

```json
{
  "id": "douyin",
  "label": "1080P 无水印",
  "note": "无水印直链，无需 Cookie",
  "height": 1080,
  "ext": "mp4",
  "filesize": 81956645,
  "progressive": true,
  "direct_format_id": "douyin",
  "audio_only": false
}
```

## 6. 配置

前缀 `VDS_`，可写在 `backend/.env`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VDS_DOWNLOAD_DIR` | `runtime/downloads` | 服务端临时下载目录 |
| `VDS_FILE_TTL_SECONDS` | `3600` | 服务端转存保留时长 |
| `VDS_LOCAL_FILE_TTL_SECONDS` | `900` | 下载到本地临时副本保留时长 |
| `VDS_MAX_FILE_SIZE_BYTES` | `2147483648` | 单文件上限（2GB） |
| `VDS_MAX_CONCURRENT_PER_IP` | `3` | 单 IP 并发 |
| `VDS_MAX_CONCURRENT_TOTAL` | `8` | 全局并发 |
| `VDS_PROBE_RATE_LIMIT_PER_MINUTE` | `20` | 解析限流 |
| `VDS_DOWNLOAD_RATE_LIMIT_PER_MINUTE` | `30` | 下载限流 |
| `VDS_PREVIEW_RATE_LIMIT_PER_MINUTE` | `120` | 在线预览限流（含 Range 请求） |
| `VDS_PROBE_CACHE_TTL_SECONDS` | `1200` | 解析缓存 |
| `VDS_DIRECT_LINK_TTL_SECONDS` | `1800` | 直链/代理 token 有效期 |
| `VDS_SUMMARY_STREAM_POLL_SECONDS` | `0.8` | 总结未完成时的状态轮询间隔 |
| `VDS_SUMMARY_STREAM_CHUNK_CHARS` | `48` | SSE `delta` 分块字符数（16–400） |
| `VDS_SUMMARY_STREAM_INTERVAL_MS` | `35` | SSE `delta` 间隔毫秒（0–200，0 为瞬时） |

## 7. 安全与清理

- `validate_public_url` 拒绝内网/环回/保留地址，防 SSRF。
- 单 IP 与全局并发、滑动窗口限流、单文件 2GB 上限。
- 代理链接使用短期随机 token，不暴露内部请求头。
- 服务端文件按任务 TTL 清理；`serving` 计数防止传输中被删。
- 抖音 ttwid 只存在内存中，不落盘、不要求用户 Cookie、不登录。
- 去水印仅对配置了 profile 的视频生效，属于有损处理。

## 8. 验证记录

### 在线预览

- 抖音 `POST /api/preview` 返回 `mode=proxy`；`/api/preview/proxy/{token}` 的 Range 请求 206、`video/mp4`、`Content-Disposition: inline`，文件总大小 81,956,645 字节。
- 无头 Chrome 实测：解析后播放器直接出现，`<video>` 的 `readyState=4`、`videoWidth=1920`、`videoHeight=1080`、`duration=204.33`，点击播放后 `currentTime` 正常推进、`paused=false`。
- B 站 360P：`POST /api/preview` 返回 `mode=task`，任务完成 5,265,275 字节；`/api/files/{id}?inline=1` Range 206、inline 播放，`<video>` 640×360、68.54 秒。
- B 站 480P 预览任务：8,706,371 字节，inline Range 正常。
- 预览复用：同一 URL + 清晰度再次请求返回 `mode=file`，`expires_in≈894`。
- 下载回归：不带 `inline` 的 `/api/files/{id}` 仍返回 `attachment`。

### 抖音

- 测试链接：`https://www.douyin.com/jingxuan?modal_id=7690944936060980520`
- 解析结果：`[诸神进化-究极速射樱桃加木桩] 极致的输出组合！...`，作者 `pvz东方`，204.3 秒。
- 1080P 无水印：1920×1080、3:24、含 AAC 音轨，81,956,645 字节。
- 抽帧检查：1 秒、60 秒画面均无抖音水印。
- 本地下载：代理流 200 `video/mp4`，完整大小一致，Range 206。
- 浏览器实测：点击「下载到本地」自动落盘，文件名含 `[1080P 无水印]`，大小 81,956,645 字节。
- 服务端转存：任务进度 0→100%，速度约 9–10 MB/s，完成后 Range 正常。
- 直链：HEAD 200。
- B 站回归：`BV1s18cziEtw` 解析与 360P 本地任务正常（5,265,275 字节）。

### B 站去水印

- 1080P 成片：89,268,000 字节、68.54 秒、1920×1080、AAC。
- 浏览器自动下载与 Range 均通过；6 秒帧平坦暗角有轻微 delogo 痕迹，30/60 秒帧无可见水印。

### 依赖与构建

- `uv run python -c "import app.main"` 通过（本次用 `backend/.venv` 直接执行导入校验）。
- 前端 `npm run build` 通过，产物已更新到 `frontend/dist` 并由后端挂载。
- 验证时的临时视频、浏览器 profile、uv 缓存均已从 `runtime/` 清理；`runtime/proof` 保留三张预览验证截图。

## 9. 已知限制

- 抖音公开分享接口和 ttwid 机制可能随时调整；接口变化时会返回明确错误，需要更新解析逻辑。
- 抖音清晰度以分享页 `play` 端点为准，不保证所有视频都有 1080P。
- 抖音图文/图集暂不支持。
- WAF proof-of-work 兜底不保证在所有网络环境成功；失败时会提示重试。
- 去水印是**按视频配置**的固定区域处理，不是通用 AI 去水印；对未登记视频不显示开关。
- 去水印是有损重编码，会改变视频码率和体积；B 站 1080P 去水印后约 89MB。
- 无数据库：任务在内存中，进程重启后任务丢失；多进程部署需要共享存储/队列。
- 不保存用户 Cookie/账号；需要登录才能拿到的最高画质不在支持范围。
- 抖音单文件直链会过期；长时间未下载时需重新解析。
- 在线预览对音视频分离格式需要先由服务端完成合并，首次播放需等待；抖音、YouTube 等单文件格式可秒开。
- 预览副本按 15 分钟 TTL 清理；切换清晰度、重新解析或关闭页面会主动删除旧预览任务。
- 在线预览播放的是原始画面，去水印只对「下载到本地」「服务端转存」生效。
- HLS/DASH 清单不引入 hls.js，统一由服务端合并后再交给 `<video>`；预览代理在平台直链过期后返回 502，需要重新解析。

## 10. 后续可做

- 为更多平台增加专用解析（快手、小红书、视频号等），复用 `media` 调度层。
- 抖音图文/图集下载。
- 任务持久化与多进程/队列支持。
- 可选登录态（用户自愿提供 Cookie）以获取更高清晰度。
- 去水印区域的可视化框选，而不是手工维护 JSON。
- AI 追问增强：逐字稿检索（RAG）、答案时间戳点击跳转、对话历史持久化。
- AI 总结增强：字幕翻译、画面视觉理解、Markmap 导出 PNG/SVG。
- 自动化测试扩展：真实平台的 Range/直链回归、更多长视频样本。

## 11. 相关文件

- [需求文档](./requirements.md)
- [AI 总结设计](./ai-summary-design.md)
- [AI 问答设计](./ai-qa-design.md)
- [README](../README.md)
- [预览接口](../backend/app/api/preview.py)
- [流与代理](../backend/app/api/stream.py)
- [总结接口](../backend/app/api/summary.py)
- [问答 SSE 接口](../backend/app/api/qa.py)
- [总结任务管理](../backend/app/services/summary/tasks.py)
- [问答服务](../backend/app/services/qa/service.py)
- [抖音解析](../backend/app/services/douyin.py)
- [平台调度](../backend/app/services/media.py)
- [任务管理](../backend/app/services/task_manager.py)
- [去水印](../backend/app/services/watermark.py)
- [水印配置](../backend/app/data/watermark_profiles.json)
- [在线播放器](../frontend/src/components/PreviewPlayer.vue)
- [AI 总结 / 问答面板](../frontend/src/components/AiSummaryPanel.vue)
- [流式问答组件](../frontend/src/components/QaChatPanel.vue)
- [Markmap 思维导图](../frontend/src/components/MindmapTree.vue)
- [前端结果面板](../frontend/src/components/ResultPanel.vue)
- [前端进度卡](../frontend/src/components/TaskProgress.vue)

---

## 12. AI 视频总结（v0.4）

> 详细方案与竞品调研见 [AI 视频总结设计文档](./ai-summary-design.md)。

- 新增 `POST /api/summary` 异步任务；`GET /api/summary/{id}` 轮询；`GET /api/summary/{id}/transcript` 按需取文稿；`DELETE /api/summary/{id}` 取消/删除。
- 逐字稿：平台字幕（VTT/SRT/ASS/Bilibili JSON/YouTube json3）优先；无字幕时 yt-dlp 下载音频 → ffmpeg 按 60 秒分片 → DeepSeek ASR（Ogg Opus，失败回退 16k WAV）。
- 总结：`deepseek-flash` + JSON Output + `thinking=disabled`；服务端归一化时间戳/章节/要点/思维导图并生成 Markdown。
- 前端：`AiSummaryPanel.vue` 提供总结/章节/文稿/思维导图/问答五个标签页、进度/取消、复制/下载 Markdown；章节与文稿时间戳可跳转在线预览；思维导图使用 `markmap-view` 渲染，支持彩色分支、根节点胶囊、缩放/拖拽/折叠。
- 默认限制：单视频 2 小时、每 IP 每天 3 次、并发 2、缓存 6 小时；未配置 `VDS_DEEPSEEK_API_KEY` 时功能禁用，下载/预览不受影响。
- 现有 `probe/preview/download/stream/task_manager` 等业务逻辑未改，仅增加路由注册、组件挂载和 seek 出口。

### 验证记录

- 后端 `unittest`：AI 总结相关 38 个测试通过（字幕解析、ASR 合并、JSON 归一化、时间戳吸附、Markdown、任务缓存/额度/取消、API 错误映射）；加入问答后总计 62 个。
- Mock 全链路：真实解析 B站 `BV1s18cziEtw`（68.5 秒）→ 下载音频 → ffmpeg 分片 → Mock ASR/LLM → finished；缓存第二次命中 `cached=true`；`force=true` 重新生成；DELETE 后 404。
- 真实 DeepSeek 全链路（68.5 秒 B站视频，无平台字幕）：ASR 68.52 秒 / 2 分片（60+8 秒），总结耗时 16.25 秒，3 章节、10 要点、2 概念、4 分支思维导图；时间戳吸附为 0/0/60 秒；ASR 费用估算 ¥0.0148，模型 tokens 2391；缓存复用不重复计费。
- 真实 DeepSeek 全链路（204 秒抖音视频）：抖音专用解析下载，ASR 204.27 秒 / 4 分片，总结耗时 28.33 秒，4 章节、6 要点、6 概念，时间戳 0/60/120/180 秒；ASR 费用估算 ¥0.0443。
- 无头 Chrome（B站真实缓存结果）：解析 → 生成总结 → 章节时间戳跳转（点击 1:00 后 `currentTime=60`）→ 文稿 → 思维导图；思维导图已升级为 Markmap 渲染（15 个节点、彩色分支、根节点胶囊），控制台无异常；桌面与 375px 截图见 `runtime/proof/ai-summary-*.png`。
- 真实输出与状态快照：`runtime/proof/real-summary-v2.md`、`runtime/proof/real-summary-v2-status.json`、`runtime/proof/real-summary-douyin-v2.md`、`runtime/proof/real-summary-douyin-v2-status.json`。
- 现有 `probe`、`preview`、`health` 回归正常；`npm run build` 通过。
- 已知限制：ASR 对带背景音乐的独白有少量漏字；平台字幕路径已有解析单测，但本次未找到可用的免登录 B站 CC 字幕样本做真实联调。

---

## 13. 视频内 AI 问答（v0.5）

> 详细方案见 [AI 问答设计文档](./ai-qa-design.md)。

- 新增 `POST /api/summary/{task_id}/ask`，返回 SSE（`status` / `token` / `refusal` / `done` / `error`）。
- 回答只基于当前 AI 总结（不含逐字稿）；多轮保留最近 3 轮；与视频无关的问题固定拒答；总结未覆盖的细节回复“材料中没有提到”。
- 先生成相关性 gate（`deepseek-flash` JSON），无关不调用回答模型；相关再用 `stream_chat` 逐 token 输出。
- 前端新增 `QaChatPanel.vue` 与「问答」标签页；支持逐字渲染、停止、推荐问题、过期重新生成、切换标签保持会话。
- 新增 `VDS_QA_*` 配置；默认每 IP 每天 30 问、每分钟 10 次；提问会滑动延长总结任务 TTL。
- 现有总结、预览、下载代码未改，仅增加 QA 路由、流式方法、`touch` 与前端组件。

### 验证记录

- 后端 `unittest`：总计 **62 个测试通过**（含 24 个问答相关：材料构建、历史裁剪、gate、流式客户端、SSE、错误映射）。
- 真实 DeepSeek 问答（B站 68.5 秒视频总结，任务 `94d0a03ac6304450`）：
  - 相关：“这个视频的核心内容是什么？”首 token 1.52 秒，总 2.24 秒，111 个 token 事件；
  - 无关：“今天天气怎么样？”1.61 秒返回 `refusal`，0 个答案 token；
  - 超纲：“视频里用的什么拍摄设备？”首 token 1.87 秒，回答“材料中没有提到……”；
  - 多轮：“再展开说说第一点”首 token 2.15 秒，正确引用上文；
  - 完整事件记录见 `runtime/proof/real-qa-events.json`。
- 无头 Chrome：问答标签页、逐字增长（innerText 从 416→509→587）、拒答样式、多轮、停止、标签切换保持会话均通过；控制台无异常；截图见 `runtime/proof/ai-qa-*.png`。
- 现有总结链路与前端构建回归通过。
- 已知限制：仅基于总结，总结没覆盖的细节无法回答；相关性 gate 可能误判；历史仅当前页面；拒答为固定 SSE 事件而非 token 流。

---

## 14. 内容体验增强（v0.6）

> 详细竞品调研与方案见 [v0.6 内容体验设计](./v0.6-content-experience-design.md)。

### 14.1 Markdown 笔记阅读

- 后端 `build_markdown()`：
  - 新增 `_inline()` 把 AI 文本折叠为单行并转义 `\`、`` ` ``、`*`、`_`、`[`、`]`、`<`、`>`、`|`，避免 AI 输出破坏结构或注入链接；
  - 时间戳改为 `[mm:ss](#t=秒)`，章节标题与要点均带可跳转链接；
  - 关键词改为行内代码；思维导图节点文本同样转义。
- 前端新增 `utils/markdown.ts`：markdown-it（`html:false`、`linkify:true`）+ DOMPurify（`USE_PROFILES: {html:true}`）；在 token 流上给标题注入 `md-h-{n}`、收集 h2/h3 目录、给时间戳加 `md-timestamp`/`data-seek`、给外链加 `target/rel`。
- 新增 `MarkdownNote.vue`：目录折叠面板、`v-html` 消毒内容、时间戳事件委托（preventDefault，不污染 URL hash）、空内容提示；移动端目录默认收起。
- `AiSummaryPanel.vue` 总结页新增「笔记 / 卡片」分段控件，默认笔记，偏好存 `localStorage('vds-summary-view')`；markdown 为空时自动回退卡片。
- `style.css` 新增 `.md-body` 排版：15/16px 字号、1.85 行高、h2 左侧品牌色竖线、引用块、列表 marker、表格横向滚动、代码块、图片、分割线、时间戳胶囊。

### 14.2 思维导图全屏与导出

- `MindmapTree.vue`：
  - 新增 `height` prop（默认 600px）；
  - 根节点胶囊、字体、行高迁移到 markmap `OPTIONS.style`，随 SVG `<style>` 同时作用于页面与导出；
  - 暴露 `fit / expandAll / exportPng / exportSvgString`；
  - 导出：等字体 → `getBBox()+32px padding` → 克隆 SVG（补 xmlns、移除根/内容 g 的 zoom transform、补 foreignObject XHTML 命名空间、移除折叠圆点与高亮）→ 设置 viewBox 与目标尺寸 → base64 data URL → Canvas 白底 → `toBlob`；单边 >16384 自动降倍率。
- 新增 `MindmapViewer.vue`：
  - 工具条「适应屏幕 / 展开全部 / 导出（PNG 2x、PNG 3x、SVG）/ 全屏」；
  - 导出菜单 `Teleport to body` + fixed 定位（根据按钮 rect 计算上下位置与右对齐），不会被工具栏 overflow 裁切，滚轮/缩放/点击外部自动关闭；
  - 内联工具栏桌面单行、窄屏自然换行，不再出现横向滚动条；
  - `Teleport to body` 全屏弹层，ESC/遮罩/退出按钮关闭，打开时锁 body 滚动、关闭恢复；
  - 内联与全屏各一个 `MindmapTree` 实例，导出使用当前激活实例；
  - 失败提示“PNG 导出失败，请改用 SVG”；移动端隐藏标题区、按钮横向滚动。
- 修复：根节点胶囊 `width: max-content; max-width: var(--markmap-max-width)`，避免 250px 宽背景遮挡分支。

### 14.3 字幕下载

- 新增 `exporters.py`：`prepare_cues()` 过滤空段并补结束时间（`end_seconds` → 下一段起点 → `start+3s`，按视频时长截断，至少 0.5 秒）；`to_srt / to_vtt / to_txt / to_markdown`；文件名 `{标题}-字幕-{平台字幕|AI语音识别}.{ext}`，总长 ≤120，`Content-Disposition` 带 ASCII fallback + `filename*`。
- 新增 `GET /api/summary/{task_id}/subtitles?format=srt|vtt|txt|md`：
  - 200：对应 MIME、`attachment`、`Cache-Control: no-store`；
  - 404：任务不存在/过期；
  - 409：字幕尚未生成；
  - 422：非法格式；
  - 不扣额度、不延长 TTL。
- 前端 `client.ts` 新增 `downloadSummarySubtitle()`，解析响应头文件名；文稿页新增格式下拉 + 下载按钮，ASR 来源提示约 1 分钟粒度。

### 14.4 验证记录

- 后端：**95 个测试通过**（62 原有 + 6 Markdown + 27 字幕）。
- 前端：`npx vite build` 通过（JS 405.80 KB / gzip 148.83 KB，CSS 49.78 KB / gzip 8.24 KB）。
- 真实链路（B站 `BV1s18cziEtw`，68.5 秒，ASR）：
  - 任务 `a8732f36b71147a8`；ASR 68.52 秒 / 2 分片；总结耗时 20.86 秒；
  - 3 章节、8 要点、2 概念；Markdown 1983 字符、11 个 `#t=` 时间戳链接；
  - SRT/VTT/TXT/MD 四种字幕均 200，大小 715/723/650/970 字节。
- 无头 Chrome E2E（`backend/tests/content_e2e.py`）：
  - 笔记 11 标题、12 列表、2 引用、11 时间戳；点击 `01:00` 后 `currentTime=60`；
  - 卡片切换往返正常；视图默认笔记；
  - 全屏弹层正常，ESC 关闭后 body overflow 恢复；
  - PNG 2x 1366×1128（190,143B）、PNG 3x 2049×1692（313,530B）、SVG 13,137B；
  - SRT 下载 715B、Markdown 970B；375px 移动端笔记与导图全屏正常；
  - 控制台 0 异常，E2E 总耗时约 20 秒。
- 导出菜单二次验收（修复工具栏裁切后）：菜单 Teleport 到 body、192×121、三项完整；工具栏 `scrollWidth = clientWidth = 642`；回归 E2E PNG 2x 1334×946、PNG 3x 2001×1419、SVG 与字幕均通过，0 异常；截图 `runtime/proof/v0.6-mindmap-toolbar-fixed.png` 与 `v0.6-mindmap-export-menu-fixed.png`。
- 产物：`runtime/proof/v0.6-*.png`、`v0.6-mindmap-2x-final.png`、`v0.6-mindmap-3x-final.png`、`v0.6-mindmap-final.svg`、`v0.6-subtitle-final.{srt,md}`、`v0.6-e2e.json`、`v0.6-real-summary.md`。

### 14.5 相关文件

- [Markdown 导出](../backend/app/services/summary/markdown.py)
- [字幕导出](../backend/app/services/summary/exporters.py)
- [总结 API](../backend/app/api/summary.py)
- [Markdown 渲染工具](../frontend/src/utils/markdown.ts)
- [Markdown 笔记组件](../frontend/src/components/MarkdownNote.vue)
- [思维导图渲染](../frontend/src/components/MindmapTree.vue)
- [思维导图外壳](../frontend/src/components/MindmapViewer.vue)
- [AI 总结面板](../frontend/src/components/AiSummaryPanel.vue)
- [下载工具](../frontend/src/utils/download.ts)
- [E2E 脚本](../backend/tests/content_e2e.py)

### 14.6 已知限制

- Safari/iOS 对 `foreignObject` → Canvas 支持不稳定，PNG 可能失败，失败时提供 SVG；SVG 为透明背景。
- ASR 字幕约 1 分钟粒度，平台字幕保留原始时间轴。
- 总结任务 30 分钟过期后笔记/字幕不可下载。
- 导图导出当前展开内容；折叠后需先“展开全部”。
- 导图单边超过 16384px 自动降低倍率。
- 问答回答仍未渲染 Markdown。

---

## 15. 同屏工作台与解析即总结（v0.7）

> 详细方案、决策确认与实施记录见 [v0.7 同屏工作台设计](./v0.7-single-screen-design.md)。本轮后端业务代码与接口契约**零改动**。

### 15.1 布局

- 结果区从一个 `max-w-3xl` 窄列改为 `#workspace`（`max-w-[1400px]`）+ CSS Grid：`lg:grid-cols-[minmax(340px,420px)_minmax(0,1fr)]`，≥1024px 双栏，<1024px 单列（视频信息在上、总结在下）。
- 左栏 v0.7 交付时使用 `lg:sticky lg:top-20` + `lg:max-h-[calc(100dvh-5.5rem)] lg:overflow-y-auto`；**v0.8 已改为两栏等高固定工作台**（`lg:h-[calc(100dvh-5.5rem)]`，取消吸顶，两栏各自内部滚动），详见第 16 节。
- `TaskProgress` 从结果区下方移入左栏，下载进度与视频信息同列。
- 解析成功后 `scrollIntoView` 工作台（`scroll-mt-20`，尊重 `prefers-reduced-motion`）；下载/预览的动作提示从 Hero 移到工作台顶部，避免滚动后被忽略。
- AI 未启用（`/api/summary/config` 返回 `enabled=false`）时自动降级为单列，右侧不再留空白。

### 15.2 左栏紧凑化（`ResultPanel.vue`）

- 清晰度由纵向列表（每行含主/次按钮，约 300px）改为换行 chips + 一行选中项详情 + 一组动作按钮；
- 详情行展示格式、大小、是否支持直链、音频是否可预览，`note` 单行截断；
- 主按钮「下载到本地」+ `.chip` 次级按钮「直链下载」「服务端转存」（直链在开启去水印时隐藏，沿用原逻辑）；
- 大段说明折叠进「预览与下载说明」；去水印改为工具条 chip 开关，开启后才显示说明行；
- 左栏高度从约 720px 降到约 550–620px，1440×900 可完整容纳；props/emits/`defineExpose({ seekTo })`/`id="result"` 全部保持不变。

### 15.3 解析即总结（`AiSummaryPanel.vue` + `Home.vue`）

- 新增 props `autoStart`，emits `update:autoSummary`、`task-change`；`Home` 持有 `autoSummary`（`localStorage['vds-auto-summary']`，默认开启）与 `summaryTaskId`。
- 触发链：`probe` 成功 → 面板挂载 → `loadConfig()` → `maybeAutoGenerate()`（`autoStarted` 守卫，只执行一次）。
- 前端前置拦截：合集/播放列表、时长超过 `max_duration_seconds` 时不发请求，直接展示原因。
- 结果分支：缓存命中（`cached=true`）直接渲染且不占额度；新建任务进入现有进度态；429/422/503/网络错误归类为“可预期软失败”，用琥珀色中性提示 + 「立即生成」，真实失败（ASR/LLM 报错）仍走红色错误卡。
- 关闭开关只影响下一次解析，不取消已在进行任务；用户取消后不自动重启。
- 竞态：`analyze()` 在 `probe` 之前 `await deleteSummary(上一任务 id)`，释放单 IP 并发槽位（默认 1），避免连续解析两个视频时新视频自动总结偶发 429。
- 生成过程中常驻额度说明；面板头部新增「解析后自动总结」开关；标签栏在桌面吸顶（需根节点去掉 `overflow-hidden`）；笔记/卡片内容限宽 `max-w-[52rem]`。

### 15.4 验证记录

- 后端：`unittest discover -s tests` → **95 个测试通过**（无后端改动，纯回归）。
- 前端：`npx tsc --noEmit` 通过；`npm run build` 通过，`index-oJDAjX2S.js 409.86 KB / gzip 150.47 KB`、`index-eHL4zoES.css 50.89 KB / gzip 8.50 KB`。
- 真实链路（`backend/tests/workspace_e2e.py`，B站 `BV1s18cziEtw`，缓存为空）：
  - 解析 4.8 秒；**未点击任何按钮**即出现「准备总结 3%」与额度说明，16.7 秒后渲染 Markdown 笔记；
  - 1440×900：左栏 `36→452`、右栏 `476→1388`，两栏 `top` 同为 80；左栏底 697px、右栏顶 80px，同屏可见；无横向溢出；
  - 滚动 700px 后左栏 `top` 仍为 80（吸顶生效），右栏继续滚动；
  - 1280×800：左 416px / 右 777px，仍双栏；
  - 点击笔记 `01:00` → 预览准备完成后 `video.currentTime=60`；
  - 关闭自动总结：`localStorage` 写入 `off`，重新解析 5 秒后仍只有「生成总结」，无进度、无笔记；
  - 重新手动生成命中缓存，立即出笔记、不占额度；
  - 375×812：单列（右栏 `top=707` > 左栏 `bottom=687`），`scrollWidth=375` 无横向溢出；
  - 控制台 `Runtime.exceptionThrown` 0 次，总耗时 48.1 秒，消耗 1 次当日额度。
- 降级链路：`VDS_SUMMARY_ENABLED=false` 重启后端后，工作台回落为单列（`max-w-3xl`、取消吸顶）、右栏显示“AI 总结未启用”、无自动总结开关、无溢出、无异常。
- 产物：`runtime/proof/v0.7-workspace-{1440,1280,375}.png`、`v0.7-workspace-sticky.png`、`v0.7-auto-summary-{generating,off}.png`、`v0.7-degraded-single-column.png`、`v0.7-e2e.json`。
- 回归脚本适配：`browser_e2e.py`、`content_e2e.py` 的清晰度选择由 `#result li` 改为 `#result [role=radio]`。

### 15.5 相关文件

- [首页布局](../frontend/src/views/Home.vue)
- [结果面板](../frontend/src/components/ResultPanel.vue)
- [AI 总结面板](../frontend/src/components/AiSummaryPanel.vue)
- [样式工具类](../frontend/src/style.css)
- [v0.7 E2E](../backend/tests/workspace_e2e.py)
- [降级布局核对](../backend/tests/degraded_e2e.py)
- [v0.7 设计文档](./v0.7-single-screen-design.md)
- [v0.8 总结流与等高工作台设计](./v0.8-streaming-summary-design.md)

### 15.6 已知限制

- 自动总结默认每次解析消耗 1 次额度（默认 3 次/天）；自测期建议调高 `VDS_SUMMARY_DAILY_LIMIT_PER_IP` 或复用已缓存视频。
- 自动总结与在线预览并行执行，首次播放高清格式仍需等待服务端合并。
- 关闭开关不取消进行中的任务；取消后不会自动重启。
- 笔记目录（TOC）内部滚动条仍为浏览器原生样式（v0.6 既有实现）。
- **v0.8 更新**：生成进度条已移除，改为思考态 + SSE 打字机；左栏吸顶改为两栏等高固定，详见第 16 节。

---

## 16. 无进度条总结流与等高工作台（v0.8）

> 详细方案、SSE 契约、决策与实施记录见 [v0.8 总结流设计](./v0.8-streaming-summary-design.md)。本轮总结生成/缓存/额度/任务模型未改，新增的是呈现层 SSE 端点。

### 16.1 后端 SSE

- 新增 `GET /api/summary/{task_id}/stream`（`text/event-stream`，任务不存在 404，响应头 `Cache-Control: no-cache, no-transform`、`X-Accel-Buffering: no`）。
- [stream.py](../backend/app/services/summary/stream.py)：未完成时只推 `state {status, stage, message}`（不含 progress）；完成后先推 `meta`（完整任务状态），再按块推 `delta {text}`，最后 `done`；`error/cancelled/gone` 为终态；空闲 12 秒发 `: keep-alive`。
- 分块：`iter_markdown_chunks()` 优先整行切分、超长行硬切，保证拼接结果与 `summary.markdown` 完全一致；Markdown 为空时只发 `meta → done`。
- [settings.py](../backend/app/services/summary/settings.py)：新增 `summary_stream_poll_seconds=0.8`、`summary_stream_chunk_chars=48`、`summary_stream_interval_ms=35`（带 clamp）；`backend/.env.example` 已同步。
- 测试：[test_summary_stream.py](../backend/tests/test_summary_stream.py) 13 → 15 个，覆盖事件顺序、分块、断连、错误/取消/过期、state 不含 progress、空 Markdown 与响应头。

### 16.2 前端思考态与打字机

- [AiSummaryPanel.vue](../frontend/src/components/AiSummaryPanel.vue)：
  - 移除进度条/百分比，生成期显示 `.thinking-dots` 跳动圆点、「正在总结中…」、阶段文案、已用时与取消；
  - 新增 `summaryPhase`（`idle/starting/thinking/streaming/done/error/cancelled`）并绑定根节点 `data-summary-phase`，滚动容器加 `data-summary-scroll`；
  - `meta` 到达即打开结果界面并 `stopElapsed()`；`delta` 追加到 `streamText` 交给 `MarkdownNote` 增量渲染；
  - 打字期间「笔记/卡片」可见但禁用、复制/下载/重新生成隐藏、时间戳不可 seek；结束后恢复；
  - 首块到达前显示「正在整理总结内容…」骨架，避免闪出空笔记提示；
  - 流请求失败或「无终态 EOF」时自动回退 `GET /api/summary/{id}` 轮询，避免永久停在思考态/「正在输出」；
  - 思考卡与「正在输出」徽章带 `role="status" aria-live="polite"`。
- [client.ts](../frontend/src/api/client.ts)：`streamSummaryTask()` 支持 fetch 流读取、`\r\n`、`: keep-alive` 忽略与 7 种事件分发；既有轮询接口保留。
- 实测：思考态 `hasProgressbar=false`、`hasPercent=false`；打字机采样 `[35, 86, 134]`（连续递增）；完成态正文 758 字符、复制/切视图恢复。

### 16.3 等高固定工作台与 Pro

- [Home.vue](../frontend/src/views/Home.vue)：`#workspace` 双栏 grid 使用 `lg:h-[calc(100dvh-5.5rem)]`（`100vh` 降级）与 `lg:grid-cols-[minmax(340px,420px)_minmax(0,1fr)]`；左栏 `lg:flex lg:h-full lg:flex-col lg:overflow-y-auto`；右栏 `AiSummaryPanel` 头部固定、正文内部滚动；取消 v0.7 的吸顶。
- [ResultPanel.vue](../frontend/src/components/ResultPanel.vue)：`lg:h-full lg:flex-1`，控件区内部滚动；「预览与下载说明」`lg:mt-auto` 贴底。
- 实测 1440×900：左 `416×812`、右 `912×812`、`top=80`、`gridHeight=812`；1280×800：左 `416×712`、右 `777×712`；页面下滚 300px 后两栏 `top=-220` 同步移动；375×812 单列（右栏 `top=711` > 左栏 `bottom=691`）、`docWidth=375`。
- [AppHeader.vue](../frontend/src/components/AppHeader.vue) + [style.css](../frontend/src/style.css)：`开通会员` → `升级 Pro`，`.pro-cta` 品牌蓝胶囊；实测 `rgb(59,107,250)`、白字、`9999px`、高 32px、`href=#pricing`。

### 16.4 验证记录

- 后端：`unittest discover -s tests` → **110 个测试通过**。
- 前端：`npx tsc --noEmit` 通过；`npm run build` 通过。流式验收时产物为 `index-BWSb4oyz.js 414.26 KB / gzip 151.96 KB`、`index-BqEhZONv.css 53.88 KB / gzip 8.93 KB`；UI 精修后最终产物为 `index-B-R94qI4.js 414.51 KB / gzip 152.06 KB`、`index-BhlyPCgw.css 53.96 KB / gzip 8.94 KB`。
- 浏览器 E2E（Mock DeepSeek + 真实 B 站样本 `BV1s18cziEtw`；放慢打字节奏用于断言）：
  - 解析 → 思考态（无进度条/百分比，阶段「正在解析视频信息…」）→ meta → 打字机 `[35,86,134]` → done；
  - 1440×900 两栏 `top` 同为 80、高度同为 812；右栏内滚 `scrollTop=160` 时左栏 `top` 仍为 80；
  - 1280×800 两栏高度 712；375×812 单列、无横向溢出；
  - Pro CTA 计算样式与链接断言通过；自动总结开关 `off/on` 持久化通过；
  - 控制台 `Runtime.exceptionThrown` 0 次；整轮 24.5 秒。命中缓存路径另一轮 23.3 秒：initial phase 直接 streaming，脚本自动点「重新生成」后验证思考态与打字机，同样 PASS。
- 回归：
  - `python -m tests.content_e2e`：笔记 11 标题、10 列表、2 引用、8 时间戳；时间戳跳转 `currentTime=60`；导图 2x/3x/SVG 与 SRT/MD 字幕正常；0 异常。
  - `VDS_SUMMARY_ENABLED=false` + `python -m tests.degraded_e2e`：单列（左底 807、右顶 827）、无自动开关、无固定高度、无溢出、0 异常。
- 补充修复：B 站 PCDN 偶发 `WinError 10061`（`mcdn.bilivideo.cn:8082` 节点拒绝连接）；`source.download_audio` 增加「重新解析 + `worstaudio/best` 降码率」二次尝试，用户反馈视频 `BV11XWR6ZEBu` 实测下载成功（4.39MB）。
- 后续 UI 微调（同日）：移除 AI 总结标题旁的 DeepSeek 徽章；压缩 Hero 间距（1440×900 下 623 → 463px）并把平台 chips 收敛为单行；为 5 个 tab 增加 emoji 图标（📝 / 📑 / 📄 / 🧠 / 💬，详见 [v0.8 设计文档 §11.4](./v0.8-streaming-summary-design.md#114-2026-11-14-后续-ui-微调)）。
- 产物：`runtime/proof/v0.8-thinking.png`、`v0.8-streaming.png`、`v0.8-workspace-{1440,1280,375}.png`、`v0.8-degraded-single-column.png`、`v0.8-e2e.json`；回归产物 `v0.6-*.png` / `v0.6-e2e.json`。

### 16.5 相关文件

- [总结 SSE 路由](../backend/app/api/summary.py)
- [总结流实现](../backend/app/services/summary/stream.py)
- [音频下载与 PCDN 重试](../backend/app/services/summary/source.py)
- [总结配置](../backend/app/services/summary/settings.py)
- [前端 API 客户端](../frontend/src/api/client.ts)
- [AI 总结面板](../frontend/src/components/AiSummaryPanel.vue)
- [Tab 图标](../frontend/src/components/SummaryTabIcon.vue)
- [首页布局](../frontend/src/views/Home.vue)
- [结果面板](../frontend/src/components/ResultPanel.vue)
- [顶栏](../frontend/src/components/AppHeader.vue)
- [样式](../frontend/src/style.css)
- [v0.8 浏览器验收](../backend/tests/workspace_e2e.py)
- [v0.6 内容回归](../backend/tests/content_e2e.py)
- [降级验收](../backend/tests/degraded_e2e.py)
- [v0.8 设计文档](./v0.8-streaming-summary-design.md)

### 16.6 已知限制

- 打字机是呈现层流式：模型仍一次返回完整 JSON，等待时间不变；打字时长随 Markdown 长度线性增长，可用 `VDS_SUMMARY_STREAM_INTERVAL_MS` 调整或设 0 关闭。
- SSE 需要反代关闭缓冲；流不可用时回退轮询，用户仍可看到完整结果。
- 浏览器验收在 Chrome 完成；Safari/Firefox 的 SSE、`dvh` 未单独验证。
- 本轮真实 DeepSeek 链路未重复消耗额度，UI/流验收使用 Mock；v0.7 已验证真实 ASR/总结链路。
