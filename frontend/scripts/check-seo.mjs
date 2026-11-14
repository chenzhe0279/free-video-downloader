// SEO 产物回归检查：校验 dist/index.html、robots.txt、sitemap.xml。
// 在 prerender 之后执行，任何一项失败都会让构建退出非零。
import { readFileSync, existsSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const dist = resolve(root, 'dist')
const failures = []

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
    check('JSON-LD 覆盖 WebSite/Organization/SoftwareApplication/FAQPage', ['WebSite', 'Organization', 'SoftwareApplication', 'FAQPage'].every((t) => types.includes(t)), types.join(','))
    check('FAQ 问答与页面一致（4 条）', graph['@graph'].find((n) => n['@type'] === 'FAQPage')?.mainEntity?.length === 4)
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

if (failures.length) {
  console.error(`\n[seo] 检查失败 ${failures.length} 项`)
  process.exit(1)
}
console.log('[seo] 全部检查通过')
