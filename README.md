# 万能视频下载站

一个基于 **FastAPI + yt-dlp** 的网页端视频下载工具：粘贴链接解析清晰度，支持「下载到本地」「服务端转存」「直链」三种交付方式，并可为特定视频配置去水印。

> 实现细节、接口说明与验证记录见 [docs/implementation-summary.md](docs/implementation-summary.md)。

## 目录结构

```
backend/
  app/                 # 全部后端业务代码
    api/               # probe / download / stream 路由
    services/          # yt-dlp、任务管理、清理、去水印
    data/              # 去水印配置（按视频 ID）
    config.py          # VDS_* 环境变量
  pyproject.toml       # 依赖声明（uv）
  uv.lock              # 锁定依赖版本
  .python-version      # Python 3.12
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

ffmpeg 优先使用系统 `ffmpeg`，缺失时回退到 `imageio-ffmpeg` 自带二进制。

## 前端（npm）

```powershell
cd frontend
npm install
npm run dev      # 开发：http://127.0.0.1:5173 ，/api 代理到 8000
npm run build    # 产物在 frontend/dist，后端启动时自动挂载
```

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

## 免责声明

仅用于学习与个人技术研究。请遵守各平台版权与服务条款，不要下载、传播未经授权的内容；去水印功能仅在你拥有相应权利时使用。
