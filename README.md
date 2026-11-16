# 万能视频下载站

一个基于 **FastAPI + yt-dlp** 的网页端视频下载工具：粘贴链接解析清晰度，支持「在线预览」「下载到本地」「服务端转存」「直链」四种交付方式，并可为特定视频配置去水印；同时提供 **AI 视频总结**（TL;DR、章节、要点、文稿、思维导图）与 **视频内 AI 问答**（严格基于总结、流式回答、无关拒答）。

> 实现细节、接口说明与验证记录见 [docs/implementation-summary.md](docs/implementation-summary.md)。

## 功能总览

| 模块 | 能力 |
|------|------|
| 下载 | 链接解析、清晰度选择、下载到本地、服务端转存、直链、代理加速 |
| 预览 | 单文件边下边播；DASH/HLS 服务端合并后在线播放，支持 Range |
| 平台适配 | 抖音无水印解析、B站按视频配置去水印 |
| AI 总结 | 平台字幕优先 / DeepSeek ASR 兜底；TL;DR、章节、要点、概念、文稿、Markdown 笔记 |
| 笔记阅读 | Markdown 精排版：目录、标题层级、引用、列表、表格、可点击时间戳；可切回卡片视图 |
| AI 问答 | 严格基于总结、相关性 gate、无关拒答、SSE 流式、最近 3 轮多轮对话 |
| 思维导图 | Markmap 交互式导图：彩色分支、根节点胶囊、缩放/拖拽/折叠、全屏、导出 PNG/SVG |
| 字幕下载 | 总结完成后下载 SRT / VTT / TXT / Markdown 字幕，平台字幕与 ASR 逐字稿都支持 |
| 同屏工作台 | 解析结果与 AI 总结左右同屏：左栏播放器/信息/清晰度/下载，右栏总结；≥1024px 两栏等高固定、内部滚动，移动端单列 |
| 解析即总结 | 解析成功自动生成总结（默认开启、可关闭并记忆），缓存复用不占额度，不支持的视频降级为提示 |
| 总结思考态 | 生成期间不展示进度条：跳动圆点 +「正在总结中…」+ 阶段文案 + 已用时 + 取消 |
| SSE 打字机 | 总结完成后直接打开结果界面，Markdown 按块流出；流不可用时回退轮询 |
| 升级 Pro | 月卡和年卡通过 Stripe 一次性付款，会员账号每天可新建 20 次 AI 总结 |

> 2026-11-14 本轮新增：无进度条总结流（思考态 + SSE 打字机）、左右栏等高固定工作台、顶栏「升级 Pro」。

## 文档索引

- [会员购买、Stripe 设置和 Windows 离线验收](docs/stripe-membership.md)
- [本次交付记录：会员、Stripe 与首页改版](docs/implementation-summary.md#最新交付2026-11-17)

- [需求分析](docs/requirements.md)
- [实现总结](docs/implementation-summary.md)
- [SEO 优化与搜索引擎收录（审计 · 实施 · 验证 · 上线清单）](docs/seo-optimization.md)
- [GEO 优化与 AI 引用（llms.txt · 内容结构化 · 监控运营）](docs/geo-optimization.md)
- [v0.8 无进度条总结流与等高工作台设计](docs/v0.8-streaming-summary-design.md)
- [v0.7 同屏工作台与解析即总结设计](docs/v0.7-single-screen-design.md)
- [v0.6 内容体验增强设计（含竞品调研）](docs/v0.6-content-experience-design.md)
- [AI 视频总结设计（含竞品调研）](docs/ai-summary-design.md)
- [AI 视频问答设计](docs/ai-qa-design.md)

## 目录结构

```
backend/
  app/                 # 全部后端业务代码
    api/               # probe / preview / download / stream / summary / qa 路由
    services/          # yt-dlp、任务管理、清理、去水印、AI 总结、AI 问答
      summary/         # 逐字稿、DeepSeek ASR/总结、任务与缓存
      qa/              # 总结材料问答、相关性 gate、SSE 流式
    data/              # 去水印配置（按视频 ID）
    config.py          # VDS_* 环境变量
  tests/               # 单元测试 + Mock DeepSeek 服务 + 浏览器验收脚本
  pyproject.toml       # 依赖声明（uv）
  uv.lock              # 锁定依赖版本
  .python-version      # Python 3.12
  .env.example         # AI 总结/问答配置示例（复制为 .env）
frontend/
  src/                 # Vue 3 + Vite + Tailwind 前端
runtime/               # 运行时下载目录与验证产物（gitignore，不放代码）
```

> 约定：**所有后端业务代码都在 `backend/app`，前端代码都在 `frontend/src`**；`runtime/` 只放媒体文件、缓存和验证截图，不放任何代码。

## 后端（uv）

```powershell
cd backend
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- 首次运行会创建 `backend/.venv` 并安装依赖；不要再用 pip 安装。
- `uv.lock` 使用 PyPI。联网安装一次后，可用 `uv sync --offline --locked` 检查本地缓存。
- 开发时也可以直接 `uv run python -c "import app.main"` 检查导入。
- 依赖更新：修改 `pyproject.toml` 后执行 `uv lock` 和 `uv sync`。

### 环境变量（可选）

前缀 `VDS_`，可写在 `backend/.env`：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VDS_DOWNLOAD_DIR` | `runtime/downloads` | 服务端临时下载目录 |
| `VDS_FILE_TTL_SECONDS` | `3600` | 「服务端转存」文件保留时长 |
| `VDS_LOCAL_FILE_TTL_SECONDS` | `900` | 「下载到本地」临时副本保留时长 |
| `VDS_MAX_FILE_SIZE_BYTES` | `2147483648` | 单文件大小上限 |
| `VDS_MAX_CONCURRENT_PER_IP` | `3` | 单 IP 并发任务数 |
| `VDS_MAX_CONCURRENT_TOTAL` | `8` | 全局并发任务数 |

### AI 总结（可选）

复制 `backend/.env.example` 为 `backend/.env`，填入 `VDS_DEEPSEEK_API_KEY` 后重启后端。未配置 Key 时下载/预览不受影响，AI 总结接口返回 503。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `VDS_DEEPSEEK_API_KEY` | 空 | DeepSeek API Key；只存在服务端 |
| `VDS_DEEPSEEK_MODEL` | `deepseek-flash` | 总结模型（可换 `deepseek-v4-pro`） |
| `VDS_SUMMARY_MAX_DURATION_SECONDS` | `7200` | 单视频时长上限（2 小时） |
| `VDS_SUMMARY_DAILY_LIMIT_PER_IP` | `3` | 每 IP 每天新建总结数；0 为不限 |
| `VDS_SUMMARY_RATE_LIMIT_PER_MINUTE` | `5` | 创建总结请求限流 |
| `VDS_SUMMARY_MAX_CONCURRENT` | `2` | 全局同时总结数 |
| `VDS_SUMMARY_ASR_CHUNK_SECONDS` | `60` | ASR 分片时长（官方上限 120 秒；60 秒换取 1 分钟级时间戳） |
| `VDS_SUMMARY_CACHE_TTL_SECONDS` | `21600` | 总结缓存时长（6 小时） |
| `VDS_QA_ENABLED` | `true` | AI 问答总开关 |
| `VDS_QA_RATE_LIMIT_PER_MINUTE` | `10` | 每 IP 每分钟问答请求数 |
| `VDS_QA_DAILY_LIMIT_PER_IP` | `30` | 每 IP 每天问答数；0 为不限 |
| `VDS_QA_MAX_QUESTION_CHARS` | `500` | 单次提问最大字数 |
| `VDS_QA_MAX_HISTORY_MESSAGES` | `6` | 多轮对话保留消息数（3 轮） |
| `VDS_QA_MAX_ANSWER_TOKENS` | `1200` | 单次回答最大 token |
| `VDS_SUMMARY_STREAM_POLL_SECONDS` | `0.8` | 总结未完成时的状态轮询间隔 |
| `VDS_SUMMARY_STREAM_CHUNK_CHARS` | `48` | SSE 打字机每块字符数（16–400） |
| `VDS_SUMMARY_STREAM_INTERVAL_MS` | `35` | SSE 打字机块间隔毫秒（0–200，0 为瞬时） |

完整配置见 `backend/.env.example` 与 [AI 问答设计文档](docs/ai-qa-design.md)。

ffmpeg 优先使用系统 `ffmpeg`，缺失时回退到 `imageio-ffmpeg` 自带二进制。

## 前端（npm）

```powershell
cd frontend
npm install
npm run dev      # 开发：http://127.0.0.1:5173 ，/api 代理到 8000
npm run build    # 产物在 frontend/dist，后端启动时自动挂载
```

- 前端依赖 `vue` + `markmap-view`（思维导图）+ `markdown-it` + `dompurify`（Markdown 笔记渲染）；`npm install` 会一并安装。
- 开发模式下 SSE 通过 Vite 代理转发；生产环境由后端直接返回 `text/event-stream`。
- 如果 npm 全局缓存目录不可写，可加 `--cache ..\runtime\npm-cache` 安装。

## 在线预览

解析成功后，结果卡片顶部会显示播放器，当前选中的清晰度可以直接在网页里播放：

- **单文件格式**（抖音、YouTube progressive 等）：服务端只做代理并补全 Referer/UA，浏览器边下边播，不落盘、点开即可播放；
- **音视频分离格式**（B 站高清等）：服务端先下载并合并，播放器显示实时进度，合并完成后自动开始播放；预览副本保留 15 分钟，可拖动进度条（Range）；
- 预览地址由 `POST /api/preview` 生成，返回 `proxy` / `file` / `task` 三种模式；同一个 IP 的相同清晰度会复用同一份预览副本；
- 预览不应用去水印，去水印仍只影响「下载到本地」「服务端转存」。

## 同屏工作台与解析即总结

解析成功后页面自动滚动到工作台，视频信息与 AI 总结左右同屏：

- **左栏**：播放器、标题/平台/作者/时长、清晰度 chips、选中项详情、主次下载按钮、去水印开关；桌面端与右栏**等高固定**（`100dvh - 5.5rem`），内容超高时在栏内滚动，≥1024px 才启用双栏；
- **右栏**：AI 总结（思考态 / 笔记 / 章节 / 文稿 / 思维导图 / 问答），标签栏带 📝 / 📑 / 📄 / 🧠 / 💬 emoji 图标，在桌面吸顶，正文限宽以保证阅读行宽；
- **首屏**：Hero 间距已压缩、平台 chips 单行展示；解析成功后自动滚动到工作台，优先展示视频与总结核心内容；
- **自动总结**：解析完成即自动创建总结任务，无需再点一次；命中缓存不消耗额度；合集、超过时长上限会在发请求前拦截；额度用尽、并发限制、未启用等可预期失败只给中性提示和「立即生成」按钮；
- **开关**：右栏头部的「解析后自动总结」可关闭，偏好保存在 `localStorage('vds-auto-summary')`；关闭只影响下一次解析，不取消进行中的任务；
- **移动端**：<1024px 回退单列，顺序为视频信息 → AI 总结。

> 注意：自动总结会消耗每日额度（默认 3 次/天），自测时如需频繁解析，可临时调高 `VDS_SUMMARY_DAILY_LIMIT_PER_IP`。

## AI 视频总结（DeepSeek）

解析成功后，右栏会自动开始生成总结（也可关闭自动开关后手动点击）。后端按以下流程处理：

1. **逐字稿**：优先下载平台字幕（VTT/SRT/ASS/Bilibili JSON/YouTube json3）；没有字幕时下载音频，按 60 秒分片调用 DeepSeek ASR；
2. **结构化总结**：`deepseek-flash` 输出 JSON，服务端校验时间戳、章节、要点，并生成 Markdown；
3. **等待与呈现**：生成期间不显示进度条，只显示跳动圆点、「正在总结中…」、阶段文案与取消；完成后直接打开结果界面，已生成的 Markdown 通过 SSE 按块打出（打字机效果）；
4. **前端展示**：总结 / 章节 / 文稿 / 思维导图 / 问答五个标签页；总结页默认渲染 Markdown 笔记（目录、标题层级、引用、列表、表格、可点击时间戳），可一键切回卡片视图；章节和文稿时间戳可跳转到在线预览播放器；思维导图使用 `markmap-view` 渲染，支持彩色分支、缩放、拖拽、节点折叠、全屏和 PNG/SVG 导出；
5. **导出**：复制 Markdown、下载 `.md` 笔记；文稿页可下载 SRT / VTT / TXT / Markdown 字幕。

限制与行为：

- 默认单视频 ≤2 小时、每 IP 每天 3 次新建总结；缓存命中不计额度，同一视频 6 小时内重复总结直接复用；
- 有平台字幕的视频不产生 ASR 费用；无字幕时按音频时长计费（DeepSeek ASR 刊例 0.78 元/小时，当前限时 0.39 元/小时）；
- 无字幕视频的时间戳粒度约 1 分钟；平台字幕时间戳更精确；
- 合集、直播、图文、纯音乐/无对白视频会返回明确提示；
- 任务与缓存都在内存中，重启后端后丢失；临时音频在任务结束后立即删除；
- 只向 DeepSeek 发送音频分片与逐字稿文本，不发送视频文件、不保存用户 Cookie。

接口：`GET /api/summary/config`、`POST /api/summary`、`GET /api/summary/{id}`、`GET /api/summary/{id}/stream`、`GET /api/summary/{id}/transcript`、`GET /api/summary/{id}/subtitles`、`DELETE /api/summary/{id}`。其中 `/stream` 返回 SSE：`state` / `meta` / `delta` / `done` / `error` / `cancelled` / `gone`。

### Markdown 笔记与字幕下载

- 总结页默认显示 Markdown 笔记视图：由后端 `build_markdown()` 生成，前端用 `markdown-it` 渲染、`DOMPurify` 消毒；h2/h3 生成目录，`[00:00](#t=0)` 形式的时间戳可点击跳转；
- 可切换到卡片视图（TL;DR / 要点 / 概念），偏好保存在浏览器本地；
- 文稿页选择 SRT / VTT / TXT / Markdown 后下载字幕文件，文件名形如 `视频标题-字幕-平台字幕.srt`；
- 字幕由总结任务中的 `segments` 生成；ASR 字幕时间戳约为 1 分钟粒度，平台字幕使用原始时间；
- 字幕下载不产生 AI 费用，任务过期（默认 30 分钟）后返回 404。

### 思维导图导出

- 内联高度 600px，支持页面内全屏（ESC 退出、自动锁定页面滚动）；
- 工具栏提供“适应屏幕 / 展开全部 / PNG 2x / PNG 3x / SVG”；
- PNG 在浏览器端由 SVG + Canvas 生成，Chrome/Edge 可正常导出；Safari 对 `foreignObject` 支持不稳定，失败时会提示改用 SVG；
- 导出的是当前展开的分支；需要完整图时先点“展开全部”。

## 视频内 AI 问答

总结完成后，结果面板会出现「问答」标签页。问答遵守以下边界：

- **只基于当前 AI 总结回答**（标题、作者、平台、时长、TL;DR、章节、要点、概念、思维导图），不把逐字稿加入上下文；
- 相关问题的回答通过 SSE **逐 token 流式输出**；
- 与视频无关的问题（天气、写代码、闲聊、问模型自身）返回固定拒答和推荐问题；
- 与视频相关但总结没覆盖的细节，回复“根据当前 AI 总结，材料中没有提到这一点”，不补充外部知识；
- 支持最近 3 轮追问，前端只发送最近 6 条消息；切换标签不会丢失对话和进行中的流；
- 支持停止生成、推荐问题、过期提示重新生成。

接口：`POST /api/summary/{task_id}/ask`，返回 `text/event-stream`；事件类型为 `status` / `token` / `refusal` / `done` / `error`。默认每 IP 每天 30 问、每分钟 10 次。

## 下载方式

- **下载到本地**：服务端合并/转码后立即把文件流式传给浏览器，浏览器下载完成后服务器副本按 TTL 清理；单文件格式直接走代理流，不落盘。
- **服务端转存**：文件保存在服务端，保留 1 小时，可换设备取回。
- **直链**：浏览器直接访问平台 CDN，速度最快；部分平台有防盗链会返回 403。

## 抖音链接（无需用户 Cookie）

抖音不走 yt-dlp，由 `backend/app/services/douyin.py` 单独解析：

- 服务端自动获取匿名 `ttwid`（不是用户 Cookie，也不需要登录），请求 `iesdouyin.com` 分享页；
- 从 `_ROUTER_DATA` 取 `video.play_addr`，把 `playwm` 替换成 `play` 得到无水印地址；
- 优先尝试 `ratio=1080p`，不可用时回退 720P；封面、作者、时长一并返回；
- 支持 `douyin.com/jingxuan?modal_id=...`、`/video/{id}`、`/note/{id}`、`/share/video/{id}` 和 `v.douyin.com` 短链；
- 只支持视频；图文/图集暂不支持；
- 分享页触发风控时会刷新 ttwid 并使用 WAF proof-of-work 兜底；公开接口变化时返回明确错误。

抖音选项本身不带平台水印，因此不会显示去水印开关。

## 去水印（按视频配置）

烧录在画面里的水印无法无损去除。本项目采用 **固定区域 `delogo` 插值填补** 的方案，且只对 `backend/app/data/watermark_profiles.json` 中登记的视频生效：

```json
{
  "BV1s18cziEtw": {
    "label": "B站左上角 UP 主水印与右上角签名",
    "reference": [1280, 720],
    "regions": [[18, 16, 168, 58], [1146, 14, 108, 56]]
  }
}
```

`regions` 为参考分辨率下的 `[x, y, w, h]`，服务端会按实际分辨率缩放。去水印需要重新编码（H.264 CRF 18），属于有损处理，平坦背景上可能有轻微填补痕迹；音频直接 copy。

## 测试

```powershell
cd backend
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

AI 测试覆盖字幕解析、ASR 合并、JSON 归一化、Markdown 导出与转义、字幕文件导出（SRT/VTT/TXT/MD 与 404/409/422）、任务缓存/额度/取消、API 错误映射、总结 SSE 事件/分块/断连/空 Markdown，以及问答材料构建、相关性 gate、SSE 流式解析、无关拒答和额度限制。`backend/tests/mock_deepseek.py` 可用于无 Key 的 Mock 全链路验证（`uvicorn tests.mock_deepseek:app --port 8100`，并通过 `VDS_DEEPSEEK_BASE_URL` 指向它）；`tests/browser_e2e.py`、`tests/qa_browser_e2e.py`、`tests/content_e2e.py`、`tests/workspace_e2e.py` 与 `tests/degraded_e2e.py` 是无头 Chrome 验收脚本（需要后端 8000 与 Chrome 9222）。会员的 MySQL 集成测试与浏览器验收配置见 [会员验收指南](docs/stripe-membership.md)。总结流与等高工作台验收：

```powershell
cd backend
# 推荐 Mock：后端设置 VDS_DEEPSEEK_BASE_URL=http://127.0.0.1:8100、VDS_DEEPSEEK_API_KEY=mock
.venv\Scripts\python.exe -m tests.workspace_e2e   # 产物写入 runtime/proof/v0.8-*
```

详细契约、失败模式与实测记录见 [v0.8 总结流设计](docs/v0.8-streaming-summary-design.md)。

## 免责声明

仅用于学习与个人技术研究。请遵守各平台版权与服务条款，不要下载、传播未经授权的内容；去水印功能仅在你拥有相应权利时使用。
