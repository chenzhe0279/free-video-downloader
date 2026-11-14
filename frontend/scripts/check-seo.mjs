// SEO 产物回归检查：校验 dist/index.html、robots.txt、sitemap.xml。
// 在 prerender 之后执行，任何一项失败都会让构建退出非零。
import { readFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { loadEnv } from 'vite'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dist = resolve(root, 'dist')
const PLACEHOLDER_SITE = 'https://clipnest.example'
const failures = []

const env = loadEnv('production', root, '')
const siteUrl = (process.env.VITE_SITE_URL || env.VITE_SITE_URL || PLACEHOLDER_SITE).trim().replace(/\/+$/, '')

function check(name, condition, detail = '') {
  if (condition) {
    console.log(`  ok  ${name}`)
  } else {
    failures.push(`${name}${detail ? `：${detail}` : ''}`)
    console.log(`FAIL  ${name}${detail ? `：${detail}` : ''}`)
  }
}

const indexPath = resolve(dist, 'index.html')
check('dist/index.html 存在', existsSync(indexPath))
const html = existsSync(indexPath) ? readFileSync(indexPath, 'utf8') : ''

check('标题包含核心关键词', html.includes('<title>万能视频下载总结器 - ClipNest | 在线视频解析下载与AI总结</title>'))
check('description 存在且非空', /<meta\s+name="description"\s+content="[^"]{80,}"/.test(html))
check('keywords 存在', html.includes('name="keywords"'))
check('canonical 存在', html.includes('rel="canonical"'))
check('Open Graph 标签齐全（og:title/description/url/image/type）', ['og:title', 'og:description', 'og:url', 'og:image', 'og:type'].every((t) => html.includes(`property="${t}"`)))
check('Twitter Card 标签存在', html.includes('twitter:card') && html.includes('summary_large_image'))
check('robots meta 允许收录', html.includes('name="robots"') && html.includes('content="index, follow'))

const ldStart = html.indexOf('<script type="application/ld+json">')
check('JSON-LD 存在', ldStart !== -1)
if (ldStart !== -1) {
  const ldEnd = html.indexOf('</script>', ldStart)
  const ldText = html.slice(ldStart + '<script type="application/ld+json">'.length, ldEnd).trim()
  let graph = null
  try {
    graph = JSON.parse(ldText)
  } catch (error) {
    check('JSON-LD 可解析', false, String(error))
  }
  if (graph) {
    const types = (graph['@graph'] || []).map((node) => node['@type'])
    check('JSON-LD 覆盖 WebSite/Organization/SoftwareApplication/FAQPage/HowTo', ['WebSite', 'Organization', 'SoftwareApplication', 'FAQPage', 'HowTo'].every((t) => types.includes(t)), types.join(','))
    check('FAQ 问答与页面一致（8 条）', graph['@graph'].find((n) => n['@type'] === 'FAQPage')?.mainEntity?.length === 8)
    check('HowTo 步骤与页面一致（3 步）', graph['@graph'].find((n) => n['@type'] === 'HowTo')?.step?.length === 3)
  }
}

const appStart = html.indexOf('<div id="app">')
const bodyEnd = html.indexOf('</body>', appStart)
const appClose = bodyEnd === -1 ? -1 : html.lastIndexOf('</div>', bodyEnd)
const appHtml = appStart === -1 || appClose === -1 ? '' : html.slice(appStart + '<div id="app">'.length, appClose)
check('已注入预渲染正文', appHtml.length > 4000, `长度 ${appHtml.length}`)
check('预渲染包含核心卖点文案', appHtml.includes('粘贴链接，') && appHtml.includes('3 秒拿到原片'))
check('预渲染包含支持平台文案', appHtml.includes('支持上千个平台'))
check('预渲染 H1 含品牌关键词', appHtml.includes('ClipNest 万能视频下载总结器'))
check('预渲染 FAQ 可见', appHtml.includes('为什么有些视频解析失败？'))
check('预渲染含唯一 H1', (appHtml.match(/<h1[\s>]/g) || []).length === 1)
check('预渲染含产品定义块', appHtml.includes('什么是万能视频下载总结器'))
check('预渲染含下载方式对比表', appHtml.includes('四种下载方式对比') && appHtml.includes('代理加速'))
check('预渲染含同类工具功能对比表', appHtml.includes('与同类工具的功能对比') && appHtml.includes('1800+') && appHtml.includes('无需安装'))
check('预渲染含更新日期标注', appHtml.includes('内容更新于 2026-11-14'))

const robotsPath = resolve(dist, 'robots.txt')
check('robots.txt 存在', existsSync(robotsPath))
const robots = existsSync(robotsPath) ? readFileSync(robotsPath, 'utf8') : ''
check('robots 引用 sitemap', robots.includes('Sitemap: '))
check('robots 不阻止页面收录', !/^\s*Disallow:\s*\/\s*$/m.test(robots))

const sitemapPath = resolve(dist, 'sitemap.xml')
check('sitemap.xml 存在', existsSync(sitemapPath))
const sitemap = existsSync(sitemapPath) ? readFileSync(sitemapPath, 'utf8') : ''
check('sitemap 包含首页 URL', /<loc>https:\/\/[^<]+\/<\/loc>/.test(sitemap))
check('sitemap 包含 lastmod', sitemap.includes('<lastmod>'))
check('OG 图片已生成（1200x630）', existsSync(resolve(root, 'public', 'og-image.png')))
check('Apple Touch 图标已生成', existsSync(resolve(root, 'public', 'apple-touch-icon.png')))
check('构建产物站点地址一致（无占位域名残留）', siteUrl === PLACEHOLDER_SITE || !(html + robots + sitemap).includes(PLACEHOLDER_SITE))

// GEO 机器可读文件
const llmsPath = resolve(dist, 'llms.txt')
check('llms.txt 存在', existsSync(llmsPath))
const llms = existsSync(llmsPath) ? readFileSync(llmsPath, 'utf8') : ''
check('llms.txt 含产品名与关键链接', llms.includes('万能视频下载总结器') && llms.includes('llms-full.txt') && llms.includes('pricing.md'))

const llmsFullPath = resolve(dist, 'llms-full.txt')
check('llms-full.txt 存在', existsSync(llmsFullPath))
const llmsFull = existsSync(llmsFullPath) ? readFileSync(llmsFullPath, 'utf8') : ''
check('llms-full.txt 含对比表与运营数据', llmsFull.includes('四种下载方式对比') && llmsFull.includes('运营数据') && llmsFull.includes('128,436') && llmsFull.includes('同类工具能力对比'))

const pricingPath = resolve(dist, 'pricing.md')
check('pricing.md 存在', existsSync(pricingPath))
const pricing = existsSync(pricingPath) ? readFileSync(pricingPath, 'utf8') : ''
check('pricing.md 含免费与规划档位', pricing.includes('¥0') && pricing.includes('¥19') && pricing.includes('尚未开放'))
check('GEO 文件无占位域名残留', siteUrl === PLACEHOLDER_SITE || !(llms + llmsFull + pricing).includes(PLACEHOLDER_SITE))

if (failures.length) {
  console.error(`\n[seo] 检查失败 ${failures.length} 项`)
  process.exit(1)
}
console.log('[seo] 全部检查通过')
