export interface FormatOption {
  id: string
  label: string
  note: string
  height: number | null
  ext: string | null
  filesize: number | null
  fps: number | null
  progressive: boolean
  direct_format_id: string | null
  audio_only: boolean
}

export interface ProbeResult {
  id: string
  url: string
  title: string
  thumbnail: string | null
  duration: number | null
  uploader: string | null
  platform: string | null
  is_playlist: boolean
  entry_count: number | null
  options: FormatOption[]
  subtitles: string[]
  watermark: WatermarkInfo
}

export interface WatermarkInfo {
  available: boolean
  label: string | null
}

export type DownloadMode = 'server' | 'direct' | 'proxy' | 'local'

export type TaskMode = 'server' | 'local' | 'preview'

export type TaskState = 'queued' | 'downloading' | 'processing' | 'cleaning' | 'finished' | 'error'

export interface TaskStatus {
  task_id: string
  mode: TaskMode
  status: TaskState
  progress: number
  downloaded_bytes: number
  total_bytes: number | null
  speed: number | null
  eta: number | null
  filename: string | null
  size: number | null
  download_url: string | null
  expires_in: number | null
  error: string | null
}

export interface DownloadResponse {
  mode: DownloadMode
  task_id?: string
  url?: string
  proxy_url?: string
  stream_url?: string
  filename?: string
  expires_in?: number
  file_ttl_seconds?: number
}

export interface PreviewResponse {
  mode: 'proxy' | 'file' | 'task'
  preview_url?: string
  task_id?: string
  filename?: string
  expires_in?: number
}

export type PreviewState = 'idle' | 'preparing' | 'ready' | 'error'

export type SummaryTaskState =
  | 'queued'
  | 'fetching'
  | 'transcribing'
  | 'summarizing'
  | 'finished'
  | 'error'
  | 'cancelled'

export type SummaryTranscriptSource = 'subtitle' | 'asr'

export interface SummaryConfig {
  enabled: boolean
  provider: string
  model: string
  max_duration_seconds: number
  daily_limit_per_ip: number
  rate_limit_per_minute: number
  asr_chunk_seconds: number
  qa_enabled: boolean
  qa_daily_limit_per_ip: number
  qa_rate_limit_per_minute: number
  qa_max_question_chars: number
  reason: string | null
}

export interface MindmapNode {
  title: string
  children: MindmapNode[]
}

export interface SummaryChapter {
  start_seconds: number
  end_seconds: number | null
  title: string
  summary: string
  key_points: string[]
}

export interface SummaryKeyPoint {
  title: string
  detail: string
  timestamp_seconds: number | null
}

export interface SummaryConcept {
  term: string
  explanation: string
}

export interface SummaryPayload {
  tldr: string
  overview: string
  keywords: string[]
  chapters: SummaryChapter[]
  key_points: SummaryKeyPoint[]
  concepts: SummaryConcept[]
  mindmap: MindmapNode | null
  markdown: string
}

export interface SummaryStats {
  chunks: number
  asr_seconds: number
  transcript_chars: number
  segments: number
  model: string
  elapsed_seconds: number
  cached: boolean
  asr_cost_estimate_cny: number | null
}

export interface SummaryTaskStatus {
  task_id: string
  status: SummaryTaskState
  stage: string
  progress: number
  message: string | null
  title: string
  duration: number | null
  platform: string | null
  thumbnail: string | null
  uploader: string | null
  cached: boolean
  transcript_source: SummaryTranscriptSource | null
  transcript_language: string | null
  stats: SummaryStats
  summary: SummaryPayload | null
  error: string | null
  expires_in: number | null
}

export interface SummaryCreateResponse {
  task_id: string
  status: SummaryTaskState
  cached: boolean
}

export interface SummaryTranscriptSegment {
  start_seconds: number
  end_seconds: number | null
  text: string
}

export interface SummaryTranscriptResponse {
  task_id: string
  source: SummaryTranscriptSource | null
  language: string | null
  segments: SummaryTranscriptSegment[]
}

export type SubtitleFormat = 'srt' | 'vtt' | 'txt' | 'md'

export interface SummarySubtitleFile {
  blob: Blob
  filename: string
}

export interface QaHistoryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface QaAskRequest {
  question: string
  history?: QaHistoryMessage[]
}

export type QaPhase = 'checking' | 'answering'

export interface QaRefusalEvent {
  message: string
  suggestions: string[]
}

export interface QaTokenEvent {
  text: string
}

export interface QaStatusEvent {
  phase: QaPhase
}

export interface QaDoneEvent {
  finish_reason?: string
}

export interface QaErrorEvent {
  message: string
}

export interface SummaryStreamState {
  status: string
  stage: string
  message: string | null
}

export interface SummaryStreamHandlers {
  onState?: (state: SummaryStreamState) => void
  onMeta?: (task: SummaryTaskStatus) => void
  onDelta?: (text: string) => void
  onDone?: (task: SummaryTaskStatus) => void
  onError?: (message: string) => void
  onCancelled?: (message: string) => void
  onGone?: (message: string) => void
}

const BASE = import.meta.env.VITE_API_BASE ?? ''

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...init,
    })
  } catch {
    throw new Error('无法连接服务端，请确认后端已启动')
  }

  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const payload = await response.json()
      if (payload?.detail) {
        detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
      }
    } catch {
      /* keep default message */
    }
    throw new Error(detail)
  }

  return (await response.json()) as T
}

export async function streamSummaryAnswer(
  taskId: string,
  payload: QaAskRequest,
  signal?: AbortSignal,
): Promise<Response> {
  let response: Response
  try {
    response = await fetch(`${BASE}/api/summary/${taskId}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') throw err
    throw new Error('无法连接服务端，请确认后端已启动')
  }

  if (!response.ok) {
    let detail = `请求失败（${response.status}）`
    try {
      const payloadData = await response.json()
      if (payloadData?.detail) {
        detail =
          typeof payloadData.detail === 'string'
            ? payloadData.detail
            : JSON.stringify(payloadData.detail)
      }
    } catch {
      /* keep default message */
    }
    throw new Error(detail)
  }

  return response
}

/**
 * 订阅总结任务的 SSE：未完成时收到 state（用于“正在总结中……”），
 * 完成后先收到 meta，再把已生成好的 Markdown 逐块以 delta 下发。
 */
export async function streamSummaryTask(
  taskId: string,
  handlers: SummaryStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`${BASE}/api/summary/${encodeURIComponent(taskId)}/stream`, {
      method: 'GET',
      headers: { Accept: 'text/event-stream' },
      signal,
    })
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') throw err
    throw new Error('无法连接服务端，请确认后端已启动')
  }

  if (!response.ok || !response.body) {
    let detail = `请求失败（${response.status}）`
    try {
      const payload = await response.json()
      if (payload?.detail) {
        detail = typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
      }
    } catch {
      /* keep default message */
    }
    throw new Error(detail)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  const dispatch = (block: string) => {
    let eventName = 'message'
    let data = ''
    for (const line of block.split('\n')) {
      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        data += line.slice(5).trim()
      }
    }
    if (!data) return

    let payload: unknown
    try {
      payload = JSON.parse(data)
    } catch {
      return
    }

    switch (eventName) {
      case 'state':
        handlers.onState?.(payload as SummaryStreamState)
        break
      case 'meta':
        handlers.onMeta?.(payload as SummaryTaskStatus)
        break
      case 'delta': {
        const text = (payload as { text?: unknown })?.text
        if (typeof text === 'string' && text) handlers.onDelta?.(text)
        break
      }
      case 'done':
        handlers.onDone?.(payload as SummaryTaskStatus)
        break
      case 'error':
        handlers.onError?.(String((payload as { message?: unknown })?.message || '总结失败'))
        break
      case 'cancelled':
        handlers.onCancelled?.(
          String((payload as { message?: unknown })?.message || '任务已取消'),
        )
        break
      case 'gone':
        handlers.onGone?.(
          String((payload as { message?: unknown })?.message || '总结任务不存在或已过期'),
        )
        break
      default:
        break
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        if (block.trim() && !block.startsWith(':')) dispatch(block)
        boundary = buffer.indexOf('\n\n')
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) dispatch(buffer)
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* reader 已被取消时释放可能抛错，忽略即可 */
    }
  }
}

function parseDownloadFilename(disposition: string, fallback: string): string {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (encoded?.[1]) {
    try {
      return decodeURIComponent(encoded[1])
    } catch {
      /* 非法编码时回退到 ASCII 文件名 */
    }
  }
  const plain = /filename="([^"]+)"/i.exec(disposition)
  return plain?.[1] || fallback
}

export async function downloadSummarySubtitle(
  taskId: string,
  format: SubtitleFormat,
): Promise<SummarySubtitleFile> {
  let response: Response
  try {
    response = await fetch(
      `${BASE}/api/summary/${encodeURIComponent(taskId)}/subtitles?format=${encodeURIComponent(format)}`,
    )
  } catch {
    throw new Error('无法连接服务端，请确认后端已启动')
  }

  if (!response.ok) {
    let detail = `下载字幕失败（${response.status}）`
    try {
      const payload = await response.json()
      if (payload?.detail) {
        detail =
          typeof payload.detail === 'string' ? payload.detail : JSON.stringify(payload.detail)
      }
    } catch {
      /* keep default message */
    }
    throw new Error(detail)
  }

  const disposition = response.headers.get('content-disposition') || ''
  return {
    blob: await response.blob(),
    filename: parseDownloadFilename(disposition, `字幕.${format}`),
  }
}

export const api = {
  probe(url: string) {
    return request<ProbeResult>('/api/probe', {
      method: 'POST',
      body: JSON.stringify({ url }),
    })
  },
  download(url: string, optionId: string, mode: DownloadMode, removeWatermark = false) {
    return request<DownloadResponse>('/api/download', {
      method: 'POST',
      body: JSON.stringify({
        url,
        option_id: optionId,
        mode,
        remove_watermark: removeWatermark,
      }),
    })
  },
  preview(url: string, optionId: string) {
    return request<PreviewResponse>('/api/preview', {
      method: 'POST',
      body: JSON.stringify({ url, option_id: optionId }),
    })
  },
  task(taskId: string) {
    return request<TaskStatus>(`/api/tasks/${taskId}`)
  },
  removeTask(taskId: string) {
    return request<{ status: string }>(`/api/tasks/${taskId}`, { method: 'DELETE' })
  },
  summaryConfig() {
    return request<SummaryConfig>('/api/summary/config')
  },
  createSummary(url: string, force = false) {
    return request<SummaryCreateResponse>('/api/summary', {
      method: 'POST',
      body: JSON.stringify({ url, force }),
    })
  },
  summaryTask(taskId: string) {
    return request<SummaryTaskStatus>(`/api/summary/${taskId}`)
  },
  summaryTranscript(taskId: string) {
    return request<SummaryTranscriptResponse>(`/api/summary/${taskId}/transcript`)
  },
  deleteSummary(taskId: string) {
    return request<{ status: string }>(`/api/summary/${taskId}`, { method: 'DELETE' })
  },
}
