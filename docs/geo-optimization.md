# GEO 优化与 AI 引用 · 审计、实施与运营文档

> 版本：v1.0（2026-11-14）
> 范围：仅前端与文档，**未改动任何后端接口与下载/解析/AI 业务逻辑**
> 依据：[GEO 优化入门指南](./GEO优化入门指南.md) · `ai-seo` / `schema` / `seo-audit` 技能 · 上轮 [SEO 优化文档](./seo-optimization.md)

---

## 1. 决策记录（已与用户确认）

| 决策点 | 结论 |
|------|------|
| 目标 AI 引擎 | 国际 + 国内全覆盖：ChatGPT、Perplexity、Gemini、Copilot、Google AI Overviews，及秘塔、豆包、Kimi、文心一言等国内引擎 |
| 站点可访问性 | 部署后海外爬虫（OAI-SearchBot、PerplexityBot 等）可访问 |
| 首页内容增强 | 允许新增 GEO 友好可见区块（产品定义块、下载方式对比表、FAQ 扩充），不动现有交互 |
| 运营数字 | 真实可信可公开；已按 GEO 规范加「统计口径 + 截至日期」标注 |
| 域名 | 沿用占位地址 `https://clipnest.example`，上线前替换（同 SEO 文档 §7） |

---

## 2. GEO 审计结论（实施前，对照 ai-seo 检查清单）

| 检查项 | 实施前 | 状态 |
|------|------|------|
| 首页首屏是否「结论先行」 | Hero 只有营销语，无产品定义 | ✅ 新增定义块 |
| 可被直接摘取的对比表 | 无（仅特性卡片） | ✅ 新增「四种下载方式对比」表 |
| FAQ 覆盖下载与 AI 两类问题 | 只有 4 条下载类 | ✅ 扩充至 8 条（+AI 总结/问答/支持范围/收费） |
| 统计数字带来源与日期 | 无 | ✅ 加口径与「数据截至 2026-11-14」 |
| 新鲜度信号 | 页面无更新日期 | ✅ 页脚标注「内容更新于 2026-11-14」 |
| `llms.txt` / `llms-full.txt` | 无 | ✅ 已提供（中英双语） |
| `/pricing.md`（AI 代理可读定价） | 无 | ✅ 已提供（现状免费 + 规划档位） |
| robots.txt 对 AI 爬虫 | 通配允许但未文档化 | ✅ 文档化发现类/训练类策略，默认全部允许 |
| 结构化数据 | WebSite/Organization/SoftwareApplication/FAQPage(4) | ✅ FAQ 增至 8 条 + HowTo（3 步） |
| 页面正文依赖 JS | 已由 SEO 轮解决（静态预渲染） | ✅ 保持并扩展检查 |

---

## 3. 已实施改动清单

| 文件 | 改动 | 对现有功能影响 |
|------|------|------|
| `frontend/public/llms.txt` | 新增：AI 上下文文件（中文为主 + English Summary），链到 llms-full.txt / pricing.md / sitemap | 无 |
| `frontend/public/llms-full.txt` | 新增：产品定位、下载方式对比、AI 总结/问答、8 条 FAQ、运营数据（含日期）全文 | 无 |
| `frontend/public/pricing.md` | 新增：机器可读定价（免费现状 + 月卡/年卡规划档位，明确「尚未开放购买」） | 无 |
| `frontend/public/robots.txt` | 注释文档化 AI 爬虫策略（发现类/训练类均默认允许，仅屏蔽 `/api/`）；保留通配规则避免误伤 | 无 |
| `frontend/src/views/Home.vue` | 新增「什么是万能视频下载总结器」定义块、「四种下载方式对比」表；FAQ 数组 4→8 条；运营数字加口径与截至日期；全部为静态新增区块 | 无（不触碰任何交互逻辑） |
| `frontend/src/components/AppFooter.vue` | 版权行追加「内容更新于 2026-11-14」 | 无 |
| `frontend/index.html` | JSON-LD：FAQPage 4→8 条（与页面逐字一致）+ 新增 HowTo（3 步，与页面步骤一致） | 无 |
| `frontend/scripts/prerender.mjs` | 新增：构建时把 GEO 三个文件的占位域名替换为真实站点地址；robots 模板同步 | 无 |
| `frontend/scripts/check-seo.mjs` | 回归检查 26→37 项：新增 GEO 文件存在性/内容/域名一致性、FAQ=8、HowTo=3、定义块与对比表预渲染可见 | 无 |

**为什么不影响现有功能**：所有前端改动都是新增静态区块/元数据；下载、预览、总结、问答等交互代码零改动，后端零改动。

### 3.1 功能对比表（用户提供素材的保守化改造，2026-11-14 追加）

用户提供的对比截图涉及真实的竞品断言，按确认结论做了三项改造：

| 决策 | 处理 |
|------|------|
| 品牌列 | 截图中的 `SaveAny` 改为当前品牌 `ClipNest` |
| 竞品口径 | 原始断言（如「其他在线工具无 AI 总结」「最高 720p–1080p」）与市面产品不符，改为可辩护的克制表述：「部分支持」「多数 720p–1080p」「多数 10–50」等 |
| 位置 | 放在「四种下载方式对比」之后、会员权益之前 |

- 表格附口径说明：「对比为同类工具的常见能力概览，具体功能与画质以各产品官方说明为准；信息整理于 2026-11-14」。
- 同一份对比已同步到 `llms-full.txt`，保证 AI 引擎读到的口径与页面一致。
- 未把竞品对比写入 JSON-LD，避免将不可审计的第三方断言结构化放大。

---

## 4. 对照《GEO 优化入门指南》六招的落地情况

| 指南要点 | 落地位置 |
|------|------|
| 1. 结论先行 | 定义块首句即产品定义（约 80 字）；对比表区首段一句话结论 |
| 2. 结构化写作 | 定义块 / 对比表格 / 8 条 FAQ / H2-H3 层级 / FAQPage + HowTo Schema |
| 3. 让别人提到你 | 属运营动作，见 §8 第三方 presence 计划（知乎、公众号、Reddit、YouTube、目录站） |
| 4. 多模态内容 | OG 图带 alt；站点暂无自有视频，已在 llms-full.txt 提供纯文本版内容；后续做产品演示视频时按 YouTube 引用规范（标题/字幕/章节）执行 |
| 5. 保持内容新鲜 | 页脚与 llms-full.txt、pricing.md 均标注「更新于 2026-11-14」；文档要求每季度刷新数据日期 |
| 6. 技术基础 | robots 允许 AI 爬虫（含 GPTBot、Google-Extended）；https 由部署层保证；sitemap 已有；正文已静态预渲染（SEO 轮） |

---

## 5. 机器可读文件说明

| 文件 | 用途 | 消费方 |
|------|------|------|
| `/llms.txt` | 站点一页式上下文：定位、适用人群、功能链接、English Summary | ChatGPT、Perplexity、各类 Agent 抓取 |
| `/llms-full.txt` | 完整产品说明：可被直接当作参考资料引用 | 需要更多上下文的引擎 |
| `/pricing.md` | 机器可读定价，避免「AI 代理看不到价格就跳过你」 | 购物/比价类 Agent |
| `/robots.txt` | AI 爬虫访问策略（发现类与训练类默认允许） | 所有爬虫 |

- 三个文件随 `npm run build` 自动完成占位域名替换（`VITE_SITE_URL`）。
- Google 官方口径：AI Overviews / AI Mode 不需要任何特殊文件或标记，这些文件主要服务**非 Google 引擎与自主代理**，且不影响 Google 收录。
- 遵循「不为 AI 单独写内容」原则：以上文件内容全部与页面可见信息一致，未制造页面外的新事实。

---

## 6. 结构化数据与 AI

- 现有：`WebSite`、`Organization`、`SoftwareApplication`（价格 0 与页面免费现状一致）。
- 本轮：`FAQPage` 4→8 条（与页面 FAQ 逐字对应）；新增 `HowTo`（3 步，与页面「01 粘贴链接 / 02 选择清晰度 / 03 一键保存」一致）。
- 说明：Google 已于 2023-09 停用 HowTo 富媒体结果、2026-05 停用 FAQ 富媒体结果；保留标记是为了**语义理解与其他引擎**，不以获取 Google 富媒体结果为目的。
- 校验：Schema.org Validator（https://validator.schema.org）。

---

## 7. 验证记录（2026-11-14）

| 检查 | 命令 | 结果 |
|------|------|------|
| 类型检查 | `npx tsc --noEmit` | ✅ 0 错误 |
| 完整构建链 | `npm run build` | ✅ vite build + 预渲染 + 37 项回归全过 |
| 预渲染增量 | dist/index.html | ✅ 10.56 KiB → 28.5 KiB；定义块/对比表/8 条 FAQ/更新日期均在 HTML 源码中 |
| 功能对比表 | `npm run build` | ✅ 预渲染可见「与同类工具的功能对比」；llms-full.txt 同步同一份对比；品牌列与页面一致为 ClipNest |
| JSON-LD | check-seo 内 JSON.parse | ✅ 5 个类型；FAQ=8；HowTo=3 步 |
| 域名替换链路 | `VITE_SITE_URL=https://demo.geo.test npm run build` | ✅ 全部产物（html/robots/sitemap/llms/llms-full/pricing）一致替换，无占位残留；随后恢复默认构建 |
| 后端 | 未改动 | ✅ 后端 110 个测试不受影响 |

> 本机沙箱下 `vite build`/`prerender` 需提权运行（esbuild 子进程派生被沙箱禁止，EPERM），属环境限制；CI/生产环境无此问题。

浏览器交互回归建议：新增区块均为静态渲染，原交互代码零改动；部署前可跑一次 `backend/tests/workspace_e2e.py` 确认整体无回归。

---

## 8. 上线后运营清单（GEO 核心在「被引用」）

### 8.1 监控（DIY，每月一次，每查询跑 3–5 次记引用率，如「3/5, n=5」）

20 个核心 prompt 模板（中英对照）：

| # | 中文 prompt | 英文 prompt |
|---|------|------|
| 1 | 如何下载 B 站视频 | How to download Bilibili videos |
| 2 | 抖音无水印下载方法 | Download Douyin video without watermark |
| 3 | 在线视频下载工具推荐 | Best online video downloader |
| 4 | 免安装网页视频下载 | Web-based video downloader no install |
| 5 | 视频 AI 总结工具 | AI video summarizer |
| 6 | 视频转文字/字幕导出工具 | Video to text with subtitles export |
| 7 | 长视频如何做思维导图 | Mind map for long videos |
| 8 | 什么是万能视频下载总结器 | What is a video downloader with AI summary |
| 9 | ClipNest 是什么 | What is ClipNest |
| 10 | ClipNest 收费吗 | ClipNest pricing |
| 11 | BibiGPT 替代品 | BibiGPT alternatives |
| 12 | YouTube 视频怎么下载到本地 | How to save YouTube videos locally |
| 13 | B 站视频如何下载到手机 | Download Bilibili videos to phone |
| 14 | 视频总结问答工具（可以追问视频内容） | AI tool to ask questions about a video |
| 15 | 视频字幕 SRT 下载工具 | Download video subtitles as SRT |
| 16 | 无水印视频下载器 | Watermark-free video downloader |
| 17 | 学习视频做笔记的工具 | Note-taking tool for lecture videos |
| 18 | 网课视频存档工具 | Archive online course videos |
| 19 | 视频解析下载 4K | Download videos in 4K |
| 20 | 最好的免费视频下载器 | Best free video downloader |

记录字段：引擎、prompt、是否引用、引用页、竞品被引名单、备注。工具可选：Otterly、Peec AI、ZipTie、LLMrefs、Profound（按预算选用）。

### 8.2 第三方 presence（让别人提到你，优先级从高到低）

1. **目录与产品库**：AlternativeTo、Product Hunt、AI 工具导航站、awesome 列表（GEO/下载工具类）
2. **中文内容**：知乎（「如何下载 B 站视频」「视频总结工具」问题下深度回答）、公众号、B 站官方账号做产品演示视频（标题/字幕/章节/简介规范）
3. **海外内容**：Reddit r/software、r/edtech 等真实参与；YouTube 教程视频；Quora
4. **评测站点**：争取被工具评测文章/榜单收录（BibiGPT、NoteGPT、通义听悟等对比文中被提及）
5. **一致口径**：所有第三方资料与本站 `llms.txt` 用同一句话定义产品（「网页端视频下载 + AI 总结工具，免安装免登录，当前免费」），保证模型眼中的共识一致

### 8.3 内容刷新节奏

- 每季度：更新页面与 llms-full.txt 中的「更新于」日期、运营数据口径
- 每月：跑 §8.1 prompt 表并记录引用率变化
- 每次功能发布：同步更新 llms.txt/llms-full.txt/pricing.md 与页面可见内容

---

## 9. 已知限制与后续计划

| 事项 | 说明 |
|------|------|
| 单页结构 | 目前可被引用的页面只有首页；后续新增帮助中心、功能页、对比页（如「ClipNest vs BibiGPT」）时，每页按 SEO 文档 §3 TDK 表配模板并同步 llms.txt 链接 |
| 权威性 | 站内无作者体系与「关于我们」；llms.txt 中已声明维护方为 ClipNest，不建议虚构作者。后续可在页面补充真实团队/维护信息增强 E-E-A-T |
| 多模态 | 暂无自有视频；上线后产品演示视频按 YouTube 引用规范执行（标题、字幕、章节、简介） |
| AI 训练策略 | 当前默认允许 GPTBot/ClaudeBot/Google-Extended（按你的指南 §6）；如需退出训练，按 robots.txt 内注释单独收紧即可，不影响 AI 搜索引用 |
| 引用 ≠ 推荐 | 被引用代表内容被查阅；进入 AI 的「推荐短名单」依赖全网共识（评测、社区、榜单），见 §8.2 |

关联文档：[需求分析](./requirements.md) · [SEO 优化与搜索引擎收录](./seo-optimization.md) · [GEO 优化入门指南](./GEO优化入门指南.md) · [项目 README](../README.md)
