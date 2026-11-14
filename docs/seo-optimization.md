# SEO 优化与搜索引擎收录 · 审计、实施与运营文档

> 版本：v1.0（2026-11-14）
> 范围：仅前端与文档，**未改动任何后端接口、下载/预览/解析/AI 业务逻辑**
> 依据：[鱼厂 SEO 优化工作流](./鱼厂%20SEO%20优化工作流.md) · `seo-audit` / `schema` 技能

---

## 1. 决策记录（已与用户确认）

| 决策点 | 结论 |
|------|------|
| 正式域名 | 尚未确定，暂用占位地址 `https://clipnest.example`（RFC 2606 保留域名，不可真实访问；**上线前必须替换**） |
| 对外产品名 | `ClipNest · 万能视频下载总结器`（保留 ClipNest 品牌 + 覆盖中文核心产品词） |
| 收录方案 | 首页**静态预渲染（SSG）**：核心正文直接进入 HTML 源码；浏览器加载后由 Vue 接管，交互与之前完全一致 |
| 约束 | 只扩展 SEO 能力，不修改现有功能；所有内容以页面真实可见信息为准，不虚构评分/用户量 |

---

## 2. SEO 审计结论（实施前）

| 类别 | 问题 | 影响 | 状态 |
|------|------|------|------|
| TDK | 只有基础 Title/Description，无 Keywords | 百度/360/搜狗关键词权重不足 | ✅ 已修复 |
| TDK | H1「粘贴链接，3 秒拿到原片」不含产品关键词 | 主题相关性弱 | ✅ 已修复（sr-only 关键词前缀，视觉不变） |
| 技术收录 | 无 `robots.txt`、无 `sitemap.xml` | 爬虫缺少入口与 URL 列表 | ✅ 已修复 |
| 技术收录 | 无 canonical | 参数 URL（`?url=...`）可能造成重复收录 | ✅ 已修复 |
| 技术收录 | 正文完全依赖 JS 渲染（Vue SPA） | 百度等弱 JS 爬虫只能看到空壳，**最大风险项** | ✅ 已修复（静态预渲染） |
| 结构化数据 | 无任何 JSON-LD | 搜索引擎无法识别产品/软件/FAQ 语义 | ✅ 已修复 |
| 社交分享 | 无 Open Graph / Twitter Card | 微信、微博、Facebook 分享无卡片 | ✅ 已修复 |
| 图标 | 无 Apple Touch 图标、无独立 Logo 文件 | 移动端收藏体验、Organization logo 缺失 | ✅ 已修复 |
| 可访问性 | 输入框无 aria-label；装饰图标无语义标记 | 影响部分机器阅读与语义解析 | ✅ 已修复 |

---

## 3. TDK 规范表

按《鱼厂 SEO 优化工作流》第 2.3 节格式维护；新增页面类型时按此表扩展：

| 字段 | 首页（当前唯一页面模板） |
|------|------|
| 页面模板名称 | 首页 |
| 页面路径规则 | `/`（唯一可收录页） |
| 标题模板 | `{产品名} - {品牌} \| {核心介绍}`；核心关键词前置，≤60 字符 |
| 描述模板 | 首句核心价值 + 平台词 + 功能词 + 场景词 + 行动号召；150–160 字符 |
| 关键词模板 | 按重要性排序，≤10 个，含 1 个品牌词 |
| 动态变量 | 无（单页静态）；后续内容页可用 `{视频标题}` `{平台}` 等 |
| 示例（当前值） | 标题：`万能视频下载总结器 - ClipNest \| 在线视频解析下载与AI总结`（36 字符）<br/>描述：148 字符，见 `frontend/index.html`<br/>关键词：`万能视频下载,视频下载器,在线视频解析,B站视频下载,抖音无水印下载,YouTube视频下载,视频AI总结,视频转文字,字幕下载,ClipNest` |
| 负责人 | 待定（建议前端负责人） |
| 更新时间 | 2026-11-14 |

> 说明：Google 已不使用 Keywords 排名，但百度/360/搜狗仍参考，故保留（工作流 §1.3 结论）。

---

## 4. 已实施改动清单（全部为新增或最小侵入）

| 文件 | 改动 | 对现有功能影响 |
|------|------|------|
| `frontend/index.html` | 完整 TDK、canonical、OG/Twitter、robots meta、JSON-LD（WebSite/Organization/SoftwareApplication/FAQPage）、apple-touch-icon | 无（仅 head 元数据） |
| `frontend/src/entry-server.ts` | 新增：SSR 渲染入口，只输出初始页面 | 无（构建期专用，浏览器不走它） |
| `frontend/scripts/prerender.mjs` | 新增：构建后注入预渲染 HTML 到 `dist/index.html`，按 `VITE_SITE_URL` 生成 `robots.txt`/`sitemap.xml` | 无 |
| `frontend/scripts/check-seo.mjs` | 新增：构建产物回归检查（26 项），失败即构建失败 | 无 |
| `frontend/scripts/generate-seo-assets.py` | 新增：生成 OG 图 1200×630 与 Apple 图标 180×180 | 无 |
| `frontend/public/robots.txt`、`sitemap.xml`、`logo.svg` | 新增：开发/预览默认值（构建时按真实域名覆盖 robots/sitemap） | 无 |
| `frontend/public/og-image.png`、`apple-touch-icon.png` | 新增：分享图与图标（Pillow 生成） | 无 |
| `frontend/src/views/Home.vue` | ① `readAutoSummary()` 增加 `typeof window === 'undefined'` 守卫（SSR 时按默认开，浏览器行为不变）；② H1 增加 `sr-only` 品牌关键词前缀（视觉不变）；③ 输入框 `aria-label`；④ 特性图标 `aria-hidden` | 浏览器端逻辑与视觉均不变 |
| `frontend/package.json` | `build` 脚本串联预渲染+校验；声明 `@vue/server-renderer` 依赖 | 构建链增强 |
| `frontend/.env.example` | 新增：`VITE_SITE_URL` 说明 | 无 |

**为什么不影响现有功能**：浏览器仍执行 `src/main.ts` 的 `createApp(...).mount('#app')`，挂载时替换容器内容并完整重建界面；预渲染 HTML 只是让「不执行 JS 的爬虫」看到内容。所有下载/预览/AI 交互代码未改（仅 Home.vue 4 处无关行为的微调），后端零改动。

---

## 5. 静态预渲染方案（SSG 原理）

```
npm run build
 ├─ 1. vite build                     # 常规打包（与之前一致）
 ├─ 2. node scripts/prerender.mjs     # Vite SSR 渲染 App → 注入 dist/index.html
 │     └─ 读取 VITE_SITE_URL（环境变量 > frontend/.env.local > 占位域名）
 │     └─ 重写 dist/robots.txt、dist/sitemap.xml
 └─ 3. node scripts/check-seo.mjs     # 26 项产物回归检查，失败即构建失败
```

- 预渲染只输出初始页面（无解析结果/无任务/无总结面板），不含任何动态接口数据。
- 爬虫看到的正文：H1、卖点、支持平台列表、使用步骤、会员权益、FAQ 全文。
- 用户看到的界面：JS 挂载后由 Vue 重建，视觉与交互不变。

---

## 6. 结构化数据（JSON-LD）说明

| 类型 | 用途 | 与页面内容对应 |
|------|------|------|
| `WebSite` | 站点名称与标识 | 首页站点本身 |
| `Organization` | 品牌实体 | 品牌名 ClipNest + logo（512×512 SVG） |
| `SoftwareApplication` | 网页应用描述 | 真实功能列表；`offers.price=0` 对应页面「免费体验 ¥0」「当前版本全部免费体验」 |
| `FAQPage` | 常见问题语义 | 页面可见的 4 条 FAQ，逐字对应 |

注意事项：

1. **FAQ 富媒体结果**：Google 已于 2026-05-07 停用 FAQ 富媒体结果展示；保留该标记是为了语义理解与其他搜索引擎（百度等），**不以获取 Google 富媒体结果为目的**。
2. 全部字段来自页面真实内容；未添加任何 `aggregateRating`/虚构数值（首页「已解析 128,436」等运营数字未进入结构化数据）。
3. 校验入口：Schema.org Validator（https://validator.schema.org）、Google Rich Results Test（https://search.google.com/test/rich-results，登录 GSC 账号后可测）。

---

## 7. 上线前必做：替换占位域名

`https://clipnest.example` 是保留占位域名，**在替换前不能提交 sitemap，否则会被平台视为错误地址**。

替换方式（三选一，任一生效后重新构建并重新部署）：

```powershell
# 方式一：临时环境变量（最优先）
$env:VITE_SITE_URL = "https://你的域名.com"
cd frontend; npm run build

# 方式二：frontend/.env.local（已 gitignore，适合长期配置）
VITE_SITE_URL=https://你的域名.com

# 方式三：复制 frontend/.env.example 为 .env 并填写
```

`npm run build` 会同时把 canonical、OG 链接、JSON-LD、robots、sitemap 全部替换为该域名；`check-seo.mjs` 会在构建末尾自动回归校验。

---

## 8. 验证记录（2026-11-14）

| 检查 | 命令 | 结果 |
|------|------|------|
| 前端构建 + 预渲染 | `npm run build` | ✅ 通过；`dist/index.html` 8.09 KiB → 22.6 KiB，正文已注入 |
| 类型检查 | `npx tsc --noEmit` | ✅ 通过（0 错误） |
| SEO 产物回归 | `node scripts/check-seo.mjs` | ✅ 26 项全过（TDK/OG/Twitter/JSON-LD/预渲染正文/唯一 H1/robots/sitemap/图片） |
| JSON-LD 解析 | check-seo 内 JSON.parse | ✅ 可解析；@graph 含 4 个类型，FAQ 4 条与页面一致 |
| 图片产物 | Pillow 校验 | ✅ og-image.png 1200×630（61.6 KB）、apple-touch-icon.png 180×180 |
| 后端 | 未改动 | 后端 110 个测试不受影响（无后端文件变更） |

> 环境说明：本机沙箱下 `vite build` 需以更高权限运行（esbuild 需拉起编译子进程），属环境限制而非代码问题。

浏览器交互回归建议（UI 只有 4 处微调，风险极低）：部署前跑一次现有 `backend/tests/workspace_e2e.py` / `content_e2e.py` 即可。

---

## 9. 上线检查清单（按顺序执行）

1. [ ] 替换占位域名为真实域名（§7）并重新构建部署
2. [ ] 验证线上 `https://域名/robots.txt` 与 `https://域名/sitemap.xml` 返回正确内容
3. [ ] 验证线上页面「查看网页源代码」能看到正文与 JSON-LD
4. [ ] Google Search Console（https://search.google.com/search-console）：验证站点 → 提交 sitemap → 跑 Rich Results Test
5. [ ] 百度搜索资源平台（https://ziyuan.baidu.com）：验证站点 → 提交 sitemap / 普通收录推送；如需 HTML 文件验证可放 `frontend/public/`
6. [ ] 必应 Webmaster（https://www.bing.com/webmasters）：提交 sitemap（可用「从 GSC 导入」）
7. [ ] 360 站长平台（https://zhanzhang.so.com）、搜狗站长平台（https://zhanzhang.sogou.com）：验证并提交
8. [ ] 社交分享验证：Facebook Sharing Debugger（https://developers.facebook.com/tools/debug）、微信内打开分享卡片
9. [ ] 记录首个收录基线（各平台 site: 查询与 GSC/站长平台索引量）

---

## 10. 已知限制与后续计划

| 事项 | 说明 |
|------|------|
| 单页应用 | 目前只有一个可收录 URL；后续新增路由（帮助中心、功能页、平台页）时需按 §3 表格为每个模板配 TDK，并扩展 sitemap |
| 占位域名 | 未替换前 SEO 配置不可视为上线状态 |
| 平台账号 | 提交 sitemap、站点验证需要各平台账号，属运营侧动作（§9） |
| 持续优化 | 按工作流 §10 建议：上线后每月做一次 SEO 审计，结合 GSC/百度站长数据调整 TDK 与内容；优先推进「AI 总结/问答」相关长尾内容页 |

关联文档：[需求分析](./requirements.md) · [实现总结](./implementation-summary.md) · [鱼厂 SEO 优化工作流](./鱼厂%20SEO%20优化工作流.md) · [项目 README](../README.md)
