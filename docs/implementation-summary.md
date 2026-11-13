# 视频下载功能实现总结

> 版本：v0.2（2026-11-13）
> 关联文档：[需求分析](./requirements.md) · [项目 README](../README.md)

---

## 1. 背景与目标

本项目最初只支持 yt-dlp 能直接处理的链接：解析出格式后，用浏览器直链或服务端转存的方式下载。实际使用中遇到两类问题：

1. **高清格式无法直接下载**：B 站等平台的 1080P 是音视频分离的 DASH，必须由服务端合并后才能交付；用户希望合并完成后直接落到本机，而不是先转存到服务器再手动取回。
2. **抖音链接完全不可用**：yt-dlp 不识别 `douyin.com/jingxuan?modal_id=...` 这类 URL，且其抖音 extractor 在没有 Cookie 时会报 `Fresh cookies ... are needed`。用户要求**不提供 Cookie、不登录**也能下载无水印抖音视频。

本阶段完成了：

- 「下载到本地」交付通道；
- 抖音专用解析与无水印下载；
- B 站按视频配置的去水印；
- 后端依赖从 pip 迁移到 uv；
- 相关前端交互与验证。

## 2. 功能总览

| 能力 | 说明 |
|------|------|
| 链接解析 | `POST /api/probe` 返回标题、封面、时长、作者、平台、清晰度列表 |
| 下载到本地 | 服务端完成合并/转码后，把文件流式传给浏览器；浏览器下载完成后服务器副本按 TTL 清理 |
| 服务端转存 | 文件保存在服务器，保留 1 小时，可换设备或稍后取回 |
| 直链 | 浏览器直接访问平台 CDN，速度最快；防盗链平台可能 403 |
| 代理下载 | 服务端转发直链，补全 Referer/UA，支持 Range |
| 抖音无水印 | 专用解析，服务端自动获取匿名 ttwid，无需用户 Cookie；`playwm` → `play` |
| B 站去水印 | 按视频配置固定区域，ffmpeg `delogo` 有损去除烧录水印 |
| 进度反馈 | 下载进度、速度、已下载/总大小、剩余时间；合并、去水印阶段单独展示 |
| 清理 | 本地任务 15 分钟、服务端任务 1 小时后自动清理；传输中的文件不会被清理线程删除 |

## 3. 目录与架构

```
backend/
  app/
    api/
      probe.py           # 解析
      download.py        # 创建任务 / 直链 / 代理 / 本地
      stream.py          # 文件 Range 下载、代理流
    services/
      media.py           # 平台调度：抖音专用 / 其他平台 yt-dlp
      douyin.py          # 抖音 ttwid、分享页 SSR、无水印地址、WAF 兜底
      ytdlp_service.py   # yt-dlp 解析、格式归一化、直链
      task_manager.py    # 任务、下载、合并、去水印、TTL、传输保护
      watermark.py       # 按视频配置的 delogo 去水印
      cleanup.py         # 过期任务/孤儿目录清理
    data/
      watermark_profiles.json
    schemas.py
    config.py
    security.py
    utils.py             # 安全文件名、下载文件名
  pyproject.toml
  uv.lock
  .python-version
frontend/
  src/
    api/client.ts
    views/Home.vue
    components/ResultPanel.vue
    components/TaskProgress.vue
    utils/format.ts
docs/
  requirements.md
  implementation-summary.md
runtime/                 # 运行时下载、验证产物（gitignore，不放代码）
```

调度关系：

```
前端
  └─ POST /api/probe ──► services/media.probe
                         ├─ douyin.probe（抖音）
                         └─ ytdlp_service.probe（其他平台）

  └─ POST /api/download
       ├─ mode=local   ──► 单文件：代理流直接下载
       │                  音视频分离：task_manager 合并/去水印 → /api/files/{id}
       ├─ mode=server  ──► task_manager → /api/files/{id}
       ├─ mode=direct  ──► resolve_direct 返回平台直链
       └─ mode=proxy   ──► token_store → /api/proxy/{token}
```

## 4. 关键实现

### 4.1 下载到本地

- 新增 `DownloadMode = "local"`，与 `server`/`direct`/`proxy` 并列。
- DASH 等需要合并的格式：先创建任务，状态依次为 `downloading → processing → finished`；前端轮询到 `finished` 后自动触发浏览器下载。
- 单文件格式：后端只生成一个带 TTL 的代理流地址，浏览器直接从 CDN 取文件，服务器不落盘。
- 本地任务使用更短的 `VDS_LOCAL_FILE_TTL_SECONDS`（默认 900 秒），服务端转存仍为 3600 秒。
- `/api/files/{id}` 支持 `Range`，下载文件名由 `build_filename(title, label, ext)` 生成；传输期间用 `begin_serve/end_serve` 计数，避免清理线程删除正在读取的文件。
- 前端结果页主按钮为「下载到本地」，「服务端转存」和「直链」作为次级操作；任务卡完成后提供「再次保存到本机」。

### 4.2 抖音无水印解析（无需用户 Cookie）

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

### 4.3 B 站去水印

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

### 4.4 后端依赖迁移到 uv

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

### 4.5 前端

- `Home.vue`：解析、下载、轮询、自动接收文件；「下载到本地」与「服务端转存」共用任务进度组件。
- `ResultPanel.vue`：主按钮「下载到本地」；直链/服务端转存次级操作；去水印开关。
- `TaskProgress.vue`：`cleaning` 状态显示「去水印中」；本地任务完成后提示 15 分钟清理。
- 平台标签沿用 `utils/format.ts`，抖音显示为「抖音」。
- `frontend/vite.config.ts` 保留用户添加的 `watch.ignored` 配置。

## 5. API 与数据结构

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/probe` | 解析链接；返回 `watermark: {available, label}` |
| POST | `/api/download` | 创建下载；`mode=server/direct/proxy/local`，`remove_watermark` 可选 |
| GET | `/api/tasks/{id}` | 任务状态、进度、速度、ETA、`expires_in`、下载地址 |
| DELETE | `/api/tasks/{id}` | 主动删除任务与文件 |
| GET | `/api/files/{id}` | 服务端文件下载，支持 Range |
| GET | `/api/proxy/{token}` | 代理直链，透传 Range 与 Referer/UA |
| GET | `/api/health` | 健康检查（ffmpeg、大小上限、TTL） |

任务状态：`queued`、`downloading`、`processing`、`cleaning`、`finished`、`error`。

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
| `VDS_PROBE_CACHE_TTL_SECONDS` | `1200` | 解析缓存 |
| `VDS_DIRECT_LINK_TTL_SECONDS` | `1800` | 直链/代理 token 有效期 |

## 7. 安全与清理

- `validate_public_url` 拒绝内网/环回/保留地址，防 SSRF。
- 单 IP 与全局并发、滑动窗口限流、单文件 2GB 上限。
- 代理链接使用短期随机 token，不暴露内部请求头。
- 服务端文件按任务 TTL 清理；`serving` 计数防止传输中被删。
- 抖音 ttwid 只存在内存中，不落盘、不要求用户 Cookie、不登录。
- 去水印仅对配置了 profile 的视频生效，属于有损处理。

## 8. 验证记录

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

- `uv sync --locked` 通过；`uv run python -c "import app.main"` 通过。
- 前端 `npm run build` 通过；后端可挂载 `frontend/dist`。
- 验证时的临时视频、浏览器 profile、uv 缓存均已从 `runtime/` 清理；`runtime/` 不包含代码。

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

## 10. 后续可做

- 为更多平台增加专用解析（快手、小红书、视频号等），复用 `media` 调度层。
- 抖音图文/图集下载。
- 任务持久化与多进程/队列支持。
- 可选登录态（用户自愿提供 Cookie）以获取更高清晰度。
- 去水印区域的可视化框选，而不是手工维护 JSON。
- 自动化测试：URL 解析、分享页 JSON 解析、任务状态机、Range 下载。

## 11. 相关文件

- [需求文档](./requirements.md)
- [README](../README.md)
- [抖音解析](../backend/app/services/douyin.py)
- [平台调度](../backend/app/services/media.py)
- [任务管理](../backend/app/services/task_manager.py)
- [去水印](../backend/app/services/watermark.py)
- [水印配置](../backend/app/data/watermark_profiles.json)
- [前端结果面板](../frontend/src/components/ResultPanel.vue)
- [前端进度卡](../frontend/src/components/TaskProgress.vue)
