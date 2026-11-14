# 万能视频下载站

一个基于 **FastAPI + yt-dlp** 的网页端视频下载工具：粘贴链接解析清晰度，支持「在线预览」「下载到本地」「服务端转存」「直链」四种交付方式，并可为特定视频配置去水印；同时提供 **AI 视频总结**（TL;DR、章节、要点、文稿、思维导图）与 **视频内 AI 问答**（严格基于总结、流式回答、无关拒答）。

> 实现细节、接口说明与验证记录见 [docs/implementation-summary.md](docs/implementation-summary.md)。

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
- `uv.lock` 是按当前机器网络用清华镜像生成的；换网络后可执行 `uv lock --default-index https://pypi.org/simple` 重新生成。
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

完整配置见 `backend/.env.example` 与 [AI 问答设计文档](docs/ai-qa-design.md)。

ffmpeg 优先使用系统 `ffmpeg`，缺失时回退到 `imageio-ffmpeg` 自带二进制。

## 前端（npm）

```powershell
cd frontend
npm install
npm run dev      # 开发：http://127.0.0.1:5173 ，/api 代理到 8000
npm run build    # 产物在 frontend/dist，后端启动时自动挂载
```

## 在线预览

解析成功后，结果卡片顶部会显示播放器，当前选中的清晰度可以直接在网页里播放：

- **单文件格式**（抖音、YouTube progressive 等）：服务端只做代理并补全 Referer/UA，浏览器边下边播，不落盘、点开即可播放；
- **音视频分离格式**（B 站高清等）：服务端先下载并合并，播放器显示实时进度，合并完成后自动开始播放；预览副本保留 15 分钟，可拖动进度条（Range）；
- 预览地址由 `POST /api/preview` 生成，返回 `proxy` / `file` / `task` 三种模式；同一个 IP 的相同清晰度会复用同一份预览副本；
- 预览不应用去水印，去水印仍只影响「下载到本地」「服务端转存」。

## AI 视频总结（DeepSeek）

解析成功后，结果面板下方会出现「AI 视频总结」卡片。点击生成后，后端按以下流程处理：

1. **逐字稿**：优先下载平台字幕（VTT/SRT/ASS/Bilibili JSON/YouTube json3）；没有字幕时下载音频，按 60 秒分片调用 DeepSeek ASR；
2. **结构化总结**：`deepseek-flash` 输出 JSON，服务端校验时间戳、章节、要点，并生成 Markdown；
3. **前端展示**：总结 / 章节 / 文稿 / 思维导图 / 问答五个标签页；章节和文稿时间戳可跳转到在线预览播放器；思维导图使用 `markmap-view` 渲染，支持彩色分支、缩放、拖拽和节点折叠；
4. **导出**：复制 Markdown 或下载 `.md` 笔记。

限制与行为：

- 默认单视频 ≤2 小时、每 IP 每天 3 次新建总结；缓存命中不计额度，同一视频 6 小时内重复总结直接复用；
- 有平台字幕的视频不产生 ASR 费用；无字幕时按音频时长计费（DeepSeek ASR 刊例 0.78 元/小时，当前限时 0.39 元/小时）；
- 无字幕视频的时间戳粒度约 1 分钟；平台字幕时间戳更精确；
- 合集、直播、图文、纯音乐/无对白视频会返回明确提示；
- 任务与缓存都在内存中，重启后端后丢失；临时音频在任务结束后立即删除；
- 只向 DeepSeek 发送音频分片与逐字稿文本，不发送视频文件、不保存用户 Cookie。

接口：`GET /api/summary/config`、`POST /api/summary`、`GET /api/summary/{id}`、`GET /api/summary/{id}/transcript`、`DELETE /api/summary/{id}`。

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

AI 测试覆盖字幕解析、ASR 合并、JSON 归一化、Markdown 导出、任务缓存/额度/取消、API 错误映射，以及问答材料构建、相关性 gate、SSE 流式解析、无关拒答和额度限制。`backend/tests/mock_deepseek.py` 可用于无 Key 的 Mock 全链路验证（`uvicorn tests.mock_deepseek:app --port 8100`，并通过 `VDS_DEEPSEEK_BASE_URL` 指向它）；`tests/browser_e2e.py` 与 `tests/qa_browser_e2e.py` 是无头 Chrome 验收脚本（需要后端 8000 与 Chrome 9222）。

## 免责声明

仅用于学习与个人技术研究。请遵守各平台版权与服务条款，不要下载、传播未经授权的内容；去水印功能仅在你拥有相应权利时使用。
