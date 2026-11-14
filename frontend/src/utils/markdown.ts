import DOMPurify, { type Config } from 'dompurify'
import MarkdownIt, { type Token } from 'markdown-it'

/**
 * Markdown 笔记渲染工具。
 *
 * 后端 `build_markdown()` 生成的时间戳格式为 `[00:00](#t=0)`。这里在
 * markdown-it 的 token 流上做三件事，再把结果交给 DOMPurify 消毒：
 * 1. 给 `heading_open` 注入稳定 id，并收集 h2/h3 作为目录；
 * 2. 给 `href="#t=..."` 的链接加 `md-timestamp` class 与 `data-seek`；
 * 3. 给 http(s) 外链补 `target="_blank"` 与 `rel="noopener noreferrer"`。
 */

export interface MarkdownHeading {
  id: string
  level: 2 | 3
  text: string
}

export interface RenderMarkdownOptions {
  /** 是否支持点击时间戳跳转；false 时置灰并给出禁用提示。 */
  seekable?: boolean
}

export interface RenderedMarkdown {
  html: string
  headings: MarkdownHeading[]
}

const HEADING_ID_PREFIX = 'md-h-'
const TIMESTAMP_HREF_PREFIX = '#t='
const EXTERNAL_LINK_RE = /^https?:\/\//i

const SANITIZE_CONFIG: Config = {
  USE_PROFILES: { html: true },
  // markdown-it 生成的外链需要保留 target / rel；其余属性走 DOMPurify 默认白名单。
  ADD_ATTR: ['target', 'rel'],
}

const md = new MarkdownIt({
  html: false,
  linkify: true,
})

/** 判断 href 是否为后端约定的时间戳链接（`#t=秒`）。 */
export function isTimestampHref(href: string | null | undefined): href is string {
  return typeof href === 'string' && href.startsWith(TIMESTAMP_HREF_PREFIX)
}

/** 把 `#t=秒` 解析成非负整数秒；非法值返回 null。 */
export function parseTimestampHref(href: string | null | undefined): number | null {
  if (!isTimestampHref(href)) return null
  const raw = href.slice(TIMESTAMP_HREF_PREFIX.length).trim()
  if (!raw) return null
  const seconds = Number(raw)
  if (!Number.isFinite(seconds) || seconds < 0) return null
  return Math.floor(seconds)
}

/** markdown-it 的属性值类型是 `string | number | null`，统一转成字符串。 */
function tokenAttr(token: Token, name: string): string | null {
  const value = token.attrGet(name)
  if (value === null) return null
  return typeof value === 'string' ? value : String(value)
}

/**
 * 取 inline token 的纯文本。
 *
 * 标题里的 `[00:00](#t=0)` 只是给正文提供跳转胶囊，目录里不需要重复时间，
 * 因此计算目录标题时跳过时间戳链接；其余行内文本（含行内代码、图片 alt）保留。
 */
function inlineText(token: Token | undefined): string {
  if (!token) return ''
  const children = token.children
  if (!children?.length) return token.content.replace(/\s+/g, ' ').trim()

  let text = ''
  let timestampDepth = 0
  for (const child of children) {
    if (child.type === 'link_open' && isTimestampHref(tokenAttr(child, 'href'))) {
      timestampDepth += 1
      continue
    }
    if (child.type === 'link_close') {
      if (timestampDepth > 0) timestampDepth -= 1
      continue
    }
    if (timestampDepth > 0) continue
    if (
      child.type === 'text' ||
      child.type === 'code_inline' ||
      child.type === 'image'
    ) {
      text += child.content
    } else if (child.type === 'softbreak' || child.type === 'hardbreak') {
      text += ' '
    }
  }
  return text.replace(/\s+/g, ' ').trim()
}

/** 给所有标题注入 id，并返回 h2/h3 目录（id 与渲染结果保持一致）。 */
function annotateHeadings(tokens: Token[]): MarkdownHeading[] {
  const headings: MarkdownHeading[] = []
  let index = 0

  for (let position = 0; position < tokens.length; position += 1) {
    const token = tokens[position]
    if (token.type !== 'heading_open') continue

    const level = Number.parseInt(token.tag.slice(1), 10)
    const id = `${HEADING_ID_PREFIX}${index}`
    index += 1
    token.attrSet('id', id)

    const text = inlineText(tokens[position + 1])
    if ((level === 2 || level === 3) && text) {
      headings.push({ id, level, text })
    }
  }

  return headings
}

function annotateLink(token: Token, seekable: boolean): void {
  const href = tokenAttr(token, 'href')
  if (!href) return

  const seconds = parseTimestampHref(href)
  if (seconds !== null) {
    token.attrJoin('class', 'md-timestamp')
    token.attrSet('data-seek', String(seconds))
    if (seekable) {
      token.attrSet('title', '跳转到视频对应位置')
    } else {
      token.attrJoin('class', 'md-timestamp--disabled')
      token.attrSet('aria-disabled', 'true')
      token.attrSet('title', '当前清晰度不支持在线预览跳转')
    }
    return
  }

  if (EXTERNAL_LINK_RE.test(href)) {
    token.attrSet('target', '_blank')
    token.attrSet('rel', 'noopener noreferrer')
  }
}

/** 链接 token 在 inline token 的 children 里，需要逐层遍历。 */
function annotateLinks(tokens: Token[], seekable: boolean): void {
  for (const token of tokens) {
    const children = token.children
    if (!children) continue
    for (const child of children) {
      if (child.type === 'link_open') annotateLink(child, seekable)
    }
  }
}

/**
 * 渲染 Markdown 为已消毒的 HTML，并同时返回 h2/h3 目录。
 *
 * 调用方必须使用返回值中的 `html`（已经过 DOMPurify），不要直接渲染原始输入。
 */
export function renderMarkdown(
  markdown: string,
  options: RenderMarkdownOptions = {},
): RenderedMarkdown {
  const source = typeof markdown === 'string' ? markdown : ''
  if (!source.trim()) return { html: '', headings: [] }

  const tokens = md.parse(source, {})
  const headings = annotateHeadings(tokens)
  annotateLinks(tokens, options.seekable !== false)

  const rawHtml = md.renderer.render(tokens, md.options, {})
  return {
    html: DOMPurify.sanitize(rawHtml, SANITIZE_CONFIG),
    headings,
  }
}

/**
 * 只提取目录（h2/h3），不返回 HTML。
 * 标题 id 的编号规则与 `renderMarkdown` 一致，可直接用于同内容的锚点。
 */
export function extractHeadings(markdown: string): MarkdownHeading[] {
  if (!markdown || !markdown.trim()) return []
  return annotateHeadings(md.parse(markdown, {}))
}
