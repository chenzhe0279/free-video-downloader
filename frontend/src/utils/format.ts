export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return ''
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let size = bytes / 1024
  let i = 0
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(1)} ${units[i]}`
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return '--:--'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`
}

const PLATFORM_LABELS: Record<string, string> = {
  youtube: 'YouTube',
  bilibili: 'Bilibili',
  tiktok: 'TikTok',
  douyin: '抖音',
  xiaohongshu: '小红书',
  instagram: 'Instagram',
  twitter: 'X / Twitter',
  facebook: 'Facebook',
  vimeo: 'Vimeo',
  youku: '优酷',
  iqiyi: '爱奇艺',
}

export function platformLabel(platform?: string | null): string {
  if (!platform) return '视频平台'
  const key = String(platform).toLowerCase()
  return PLATFORM_LABELS[key] || key.charAt(0).toUpperCase() + key.slice(1)
}

export function suggestFilename(title: string, ext?: string | null): string {
  const safe = title.replace(/[\\/:*?"<>|]+/g, '_').slice(0, 80) || 'video'
  return `${safe}.${ext || 'mp4'}`
}
