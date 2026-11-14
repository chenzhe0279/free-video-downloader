// SEO 构建后置脚本：把首页预渲染成静态 HTML，并按站点地址生成 robots.txt / sitemap.xml。
// 站点地址读取顺序：环境变量 VITE_SITE_URL > frontend/.env(.local/.production) > 占位域名。
// 正式上线前必须把 VITE_SITE_URL 换成真实域名（如 https://clipnest.com）后重新构建。
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createServer, loadEnv } from 'vite'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const PLACEHOLDER_SITE = 'https://clipnest.example'
const LAST_MODIFIED = '2026-11-14'

const env = loadEnv('production', root, '')
const siteUrl = (process.env.VITE_SITE_URL || env.VITE_SITE_URL || PLACEHOLDER_SITE).trim().replace(/\/+$/, '')

const distDir = resolve(root, 'dist')
const indexPath = resolve(distDir, 'index.html')

// 1) 用 Vite SSR 把首页渲染为静态 HTML
const vite = await createServer({
  root,
  logLevel: 'error',
  server: { middlewareMode: true },
  appType: 'custom',
})
let appHtml = ''
try {
  const mod = await vite.ssrLoadModule('/src/entry-server.ts')
  appHtml = await mod.render()
} finally {
  await vite.close()
}

// 2) 注入到构建产物，并统一替换占位域名
let html = readFileSync(indexPath, 'utf8')
html = html.split(PLACEHOLDER_SITE).join(siteUrl)
if (!html.includes('<div id="app"></div>')) {
  throw new Error('dist/index.html 缺少 <div id="app"></div>，无法注入预渲染内容')
}
html = html.replace('<div id="app"></div>', () => `<div id="app">${appHtml}</div>`)
writeFileSync(indexPath, html)

// 3) 生成搜索引擎抓取文件（覆盖 vite 从 public/ 拷贝的占位版本）
mkdirSync(distDir, { recursive: true })
writeFileSync(
  resolve(distDir, 'robots.txt'),
  `# ClipNest · 万能视频下载总结器\n# AI 爬虫策略：默认允许全部爬虫（含搜索发现类与内容训练类），仅屏蔽接口目录。\n#   搜索发现类（影响 AI 引用）：OAI-SearchBot、ChatGPT-User、PerplexityBot、Perplexity-User、\n#     Claude-SearchBot、Claude-User、meta-webindexer、meta-externalfetcher、Googlebot、Bingbot 等 → 允许\n#   训练类（不影响 AI 搜索引用）：GPTBot、ClaudeBot、meta-externalagent、Google-Extended 等 → 默认允许；\n#     如需退出训练可在下方按爬虫名收紧，例如：\n#       User-agent: GPTBot\n#       Disallow: /\nUser-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: ${siteUrl}/sitemap.xml\n`,
)
writeFileSync(
  resolve(distDir, 'sitemap.xml'),
  `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n  <url>\n    <loc>${siteUrl}/</loc>\n    <lastmod>${LAST_MODIFIED}</lastmod>\n    <changefreq>weekly</changefreq>\n    <priority>1.0</priority>\n  </url>\n</urlset>\n`,
)

// 4) GEO 机器可读文件：把占位域名替换为真实站点地址
for (const name of ['llms.txt', 'llms-full.txt', 'pricing.md']) {
  const filePath = resolve(distDir, name)
  if (!existsSync(filePath)) continue
  writeFileSync(filePath, readFileSync(filePath, 'utf8').split(PLACEHOLDER_SITE).join(siteUrl))
}

console.log(`[seo] 站点地址：${siteUrl}`)
console.log(`[seo] 已注入预渲染首页（dist/index.html 共 ${(html.length / 1024).toFixed(1)} KiB）`)
console.log('[seo] 已生成 dist/robots.txt、dist/sitemap.xml 并同步 GEO 文件域名（llms.txt / llms-full.txt / pricing.md）')
