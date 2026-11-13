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

export type TaskMode = 'server' | 'local'

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
  task(taskId: string) {
    return request<TaskStatus>(`/api/tasks/${taskId}`)
  },
  removeTask(taskId: string) {
    return request<{ status: string }>(`/api/tasks/${taskId}`, { method: 'DELETE' })
  },
}
