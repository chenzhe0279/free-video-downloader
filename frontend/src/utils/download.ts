const UNSAFE_CHARS = /[\\/:*?"<>|\x00-\x1f\x7f]+/g
const SPACES = /\s+/g
const MAX_LENGTH = 120

/**
 * 把视频标题清洗成跨平台安全、可放进下载文件名的字符串。
 * 与后端 `app/utils.py` 的 safe_filename 保持相同的字符规则。
 */
export function safeFilename(name: string, fallback = 'video'): string {
  const cleaned = (name || '')
    .replace(UNSAFE_CHARS, '_')
    .replace(SPACES, ' ')
    .trim()
    .replace(/^[.\s]+|[.\s]+$/g, '')
  return (cleaned || fallback).slice(0, MAX_LENGTH)
}

/** 触发浏览器下载一个 Blob，并释放临时 URL。 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // 给浏览器留出读取时间，再释放 URL
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
