<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  api,
  downloadSummarySubtitle,
  streamSummaryTask,
  type ProbeResult,
  type SubtitleFormat,
  type SummaryConfig,
  type SummaryStreamState,
  type SummaryTaskStatus,
  type SummaryTranscriptSegment,
} from '../api/client'
import { formatDuration } from '../utils/format'
import { safeFilename, saveBlob } from '../utils/download'
import MarkdownNote from './MarkdownNote.vue'
import MindmapViewer from './MindmapViewer.vue'
import QaChatPanel from './QaChatPanel.vue'
import SummaryTabIcon from './SummaryTabIcon.vue'

const props = defineProps<{
  result: ProbeResult
  seekable: boolean
  autoStart: boolean
}>()

const emit = defineEmits<{
  (e: 'seek', seconds: number): void
  (e: 'update:autoSummary', value: boolean): void
  (e: 'task-change', taskId: string | null): void
}>()

type TabKey = 'summary' | 'chapters' | 'transcript' | 'mindmap' | 'qa'
type SummaryView = 'note' | 'cards'

const tabs: { key: TabKey; label: string }[] = [
  { key: 'summary', label: '总结' },
  { key: 'chapters', label: '章节' },
  { key: 'transcript', label: '文稿' },
  { key: 'mindmap', label: '思维导图' },
  { key: 'qa', label: '问答' },
]

const config = ref<SummaryConfig | null>(null)
const configState = ref<'loading' | 'ready' | 'error'>('loading')
const configError = ref('')
const task = ref<SummaryTaskStatus | null>(null)
const starting = ref(false)
const errorMsg = ref('')
const activeTab = ref<TabKey>('summary')
const transcript = ref<SummaryTranscriptSegment[] | null>(null)
const transcriptLoading = ref(false)
const transcriptError = ref('')
const transcriptLimit = ref(200)
const elapsed = ref(0)
const copied = ref(false)
const subtitleFormat = ref<SubtitleFormat>('srt')
const subtitleDownloading = ref(false)
const subtitleError = ref('')
const autoStarted = ref(false)
const autoNotice = ref('')
const autoNoticeRetryable = ref(false)

// 生成过程不再展示进度条：只用 state 事件驱动“正在总结中……”的思考动画，
// 总结就绪后由 meta + delta 把内容逐步流出来。
const streaming = ref(false)
const streamText = ref('')
const streamStage = ref('')
const streamMessage = ref<string | null>(null)
const activeTaskId = ref('')

const subtitleFormats: { value: SubtitleFormat; label: string }[] = [
  { value: 'srt', label: 'SRT 字幕' },
  { value: 'vtt', label: 'VTT 字幕' },
  { value: 'txt', label: 'TXT 纯文本' },
  { value: 'md', label: 'Markdown 文稿' },
]

const SUMMARY_VIEW_KEY = 'vds-summary-view'

function readSummaryView(): SummaryView {
  try {
    return window.localStorage.getItem(SUMMARY_VIEW_KEY) === 'cards' ? 'cards' : 'note'
  } catch {
    return 'note'
  }
}

const summaryView = ref<SummaryView>(readSummaryView())

let pollTimer: number | undefined
let elapsedTimer: number | undefined
let streamController: AbortController | null = null

const summary = computed(() => task.value?.summary ?? null)
const effectiveSummaryView = computed<SummaryView>(() => {
  if (streaming.value && summary.value?.markdown?.trim()) return 'note'
  return summaryView.value === 'note' && summary.value?.markdown?.trim() ? 'note' : 'cards'
})

function setSummaryView(view: SummaryView) {
  summaryView.value = view
  try {
    window.localStorage.setItem(SUMMARY_VIEW_KEY, view)
  } catch {
    /* 隐私模式下 localStorage 可能不可用，忽略即可 */
  }
}
const visibleTabs = computed(() =>
  tabs.filter((tab) => tab.key !== 'qa' || Boolean(config.value?.qa_enabled)),
)
const qaSuggestions = computed(() => {
  const items = ['用三句话总结这个视频', '这个视频的核心结论是什么？']
  for (const chapter of summary.value?.chapters.slice(0, 2) ?? []) {
    const title = chapter.title?.trim()
    if (title) items.push(`「${title}」讲了什么？`)
  }
  return [...new Set(items)].slice(0, 4)
})
const isBusy = computed(() => {
  if (starting.value || streaming.value) return true
  const status = task.value?.status
  return (
    status === 'queued' ||
    status === 'fetching' ||
    status === 'transcribing' ||
    status === 'summarizing'
  )
})
// 总结还没就绪（或在创建任务）时展示“正在总结中……”，不再有进度百分比
const thinking = computed(() => starting.value || (streaming.value && !summary.value))
const thinkingTitle = computed(() =>
  starting.value ? '正在创建总结任务' : '正在总结中',
)
const thinkingDetail = computed(
  () =>
    streamMessage.value ||
    (streamStage.value ? `${streamStage.value}…` : '正在准备视频与逐字稿…'),
)
const taskError = computed(() => task.value?.error || errorMsg.value)
// 供 E2E 与样式使用的稳定阶段标记：starting → thinking → streaming → done/error/cancelled
const summaryPhase = computed(() => {
  if (starting.value) return 'starting'
  if (streaming.value) return summary.value ? 'streaming' : 'thinking'
  if (task.value?.status === 'error' || errorMsg.value) return 'error'
  if (task.value?.status === 'cancelled') return 'cancelled'
  if (task.value?.status === 'finished') return 'done'
  return 'idle'
})
const sourceLabel = computed(() => {
  if (task.value?.transcript_source === 'subtitle') return '平台字幕'
  if (task.value?.transcript_source === 'asr') return 'AI 语音识别'
  return ''
})
const visibleTranscript = computed(() =>
  (transcript.value ?? []).slice(0, transcriptLimit.value),
)
const canLoadMore = computed(
  () => (transcript.value?.length ?? 0) > transcriptLimit.value,
)
const elapsedText = computed(() => {
  const minutes = Math.floor(elapsed.value / 60)
  const seconds = Math.floor(elapsed.value % 60)
  return `${minutes}:${String(seconds).padStart(2, '0')}`
})
const costText = computed(() => {
  const stats = task.value?.stats
  if (!stats) return ''
  if (task.value?.cached) return '缓存复用，本次未产生新的语音识别费用'
  if (!stats.asr_seconds) return '本次使用平台字幕，未产生语音识别费用'
  const minutes = Math.max(1, Math.round(stats.asr_seconds / 60))
  const cost =
    stats.asr_cost_estimate_cny === null
      ? ''
      : ` · 估算 ¥${stats.asr_cost_estimate_cny.toFixed(2)}`
  return `语音识别 ${minutes} 分钟${cost}`
})
const maxDurationText = computed(() =>
  config.value
    ? `${Math.round(config.value.max_duration_seconds / 60)} 分钟`
    : '120 分钟',
)

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : '操作失败，请稍后重试'
}

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearTimeout(pollTimer)
    pollTimer = undefined
  }
}

function stopElapsed() {
  if (elapsedTimer !== undefined) {
    window.clearInterval(elapsedTimer)
    elapsedTimer = undefined
  }
}

function startElapsed() {
  stopElapsed()
  elapsed.value = 0
  elapsedTimer = window.setInterval(() => {
    elapsed.value += 1
  }, 1000)
}

function stopTimers() {
  stopPolling()
  stopElapsed()
}

async function loadConfig() {
  configState.value = 'loading'
  configError.value = ''
  try {
    config.value = await api.summaryConfig()
    configState.value = 'ready'
    void maybeAutoGenerate()
  } catch (err) {
    configState.value = 'error'
    configError.value = errorText(err)
  }
}

// 前端可提前判定的“不可能成功”场景，直接拦下，避免无谓的额度消耗与报错噪音。
function autoBlockReason(): string {
  if (props.result.is_playlist) {
    return '合集/播放列表暂不支持 AI 总结，请粘贴单个视频链接。'
  }
  const limit = config.value?.max_duration_seconds ?? 0
  const duration = props.result.duration
  if (limit > 0 && duration && duration > limit) {
    return `视频约 ${Math.round(duration / 60)} 分钟，超过 AI 总结上限 ${Math.round(limit / 60)} 分钟。`
  }
  return ''
}

async function maybeAutoGenerate() {
  if (autoStarted.value) return
  autoStarted.value = true
  if (!props.autoStart) return
  if (!config.value?.enabled) return
  const blocked = autoBlockReason()
  if (blocked) {
    autoNotice.value = blocked
    autoNoticeRetryable.value = false
    return
  }
  await generate(false, { automatic: true })
}

function softAutoFailure(message: string): boolean {
  return [
    '已达上限',
    '未启用',
    '暂不支持',
    '无法确定视频时长',
    '超过 AI 总结上限',
    '无法连接服务端',
  ].some((keyword) => message.includes(keyword))
}

function autoFailureRetryable(message: string): boolean {
  return (
    message.includes('已达上限') ||
    message.includes('无法连接服务端') ||
    message.includes('请稍后再试')
  )
}

async function loadTranscript() {
  const taskId = task.value?.task_id
  if (!taskId || transcriptLoading.value) return
  transcriptLoading.value = true
  transcriptError.value = ''
  try {
    const data = await api.summaryTranscript(taskId)
    transcript.value = data.segments
    transcriptLimit.value = 200
  } catch (err) {
    transcriptError.value = errorText(err)
  } finally {
    transcriptLoading.value = false
  }
}

async function refreshTask(taskId: string): Promise<SummaryTaskStatus | null> {
  try {
    const data = await api.summaryTask(taskId)
    task.value = data
    return data
  } catch {
    return null
  }
}

function schedulePoll(taskId: string) {
  pollTimer = window.setTimeout(() => {
    void tick(taskId)
  }, 1200)
}

async function tick(taskId: string) {
  const data = await refreshTask(taskId)
  if (!data) {
    schedulePoll(taskId)
    return
  }
  if (data.status === 'finished') {
    stopPolling()
    finishStream()
    activeTab.value = 'summary'
    void loadTranscript()
    return
  }
  if (data.status === 'error' || data.status === 'cancelled') {
    stopPolling()
    finishStream()
    return
  }
  schedulePoll(taskId)
}

function stopStream() {
  if (streamController !== null) {
    streamController.abort()
    streamController = null
  }
}

function finishStream() {
  stopStream()
  streaming.value = false
  streamText.value = ''
  streamStage.value = ''
  streamMessage.value = null
  stopElapsed()
}

function resetStreamState() {
  streaming.value = false
  streamText.value = ''
  streamStage.value = ''
  streamMessage.value = null
  activeTaskId.value = ''
}

function applyState(state: SummaryStreamState) {
  if (state.stage) streamStage.value = state.stage
  streamMessage.value = state.message ?? null
}

/**
 * 连上进度流：未完成时只更新“正在总结中……”的文案；
 * meta 到达后立刻渲染成品界面，delta 把 Markdown 逐块吐出来。
 */
async function attachStream(taskId: string) {
  stopStream()
  streaming.value = true
  streamText.value = ''
  streamStage.value = '准备总结'
  streamMessage.value = null
  activeTaskId.value = taskId
  emit('task-change', taskId)

  const controller = new AbortController()
  streamController = controller
  let terminalEvent = false
  try {
    await streamSummaryTask(
      taskId,
      {
        onState: applyState,
        onMeta(meta) {
          task.value = meta
          // meta 到达即进入结果态，思考计时不再有意义
          stopElapsed()
        },
        onDelta(text) {
          streamText.value += text
        },
        onDone(final) {
          terminalEvent = true
          task.value = final
          finishStream()
          activeTab.value = 'summary'
          void loadTranscript()
        },
        onError(message) {
          terminalEvent = true
          finishStream()
          autoNotice.value = ''
          errorMsg.value = message
        },
        onCancelled(message) {
          terminalEvent = true
          finishStream()
          resetStreamState()
          task.value = null
          autoNotice.value = message
          autoNoticeRetryable.value = false
        },
        onGone(message) {
          terminalEvent = true
          finishStream()
          resetStreamState()
          task.value = null
          errorMsg.value = message
        },
      },
      controller.signal,
    )
    if (!terminalEvent && streaming.value) {
      // 代理/服务端可能在未发终态事件时提前关闭连接：回退轮询，避免停在“正在输出”
      schedulePoll(taskId)
    }
  } catch (err) {
    if (err instanceof Error && err.name === 'AbortError') return
    // 流式接口不可用时回退到轮询，避免一直停在思考动画
    if (task.value?.status !== 'finished') {
      schedulePoll(taskId)
    } else {
      finishStream()
    }
  } finally {
    if (streamController === controller) streamController = null
  }
}

async function generate(force = false, options: { automatic?: boolean } = {}) {
  if (isBusy.value) return
  errorMsg.value = ''
  autoNotice.value = ''
  autoNoticeRetryable.value = false
  copied.value = false
  if (force) {
    task.value = null
    transcript.value = null
    transcriptError.value = ''
    resetStreamState()
  }
  starting.value = true
  activeTab.value = 'summary'
  startElapsed()

  let taskId = ''
  try {
    const created = await api.createSummary(props.result.url, force)
    taskId = created.task_id
  } catch (err) {
    stopTimers()
    starting.value = false
    const message = errorText(err)
    if (options.automatic && softAutoFailure(message)) {
      // 自动触发的可预期失败：用中性提示，不占用红色错误位
      autoNotice.value = message
      autoNoticeRetryable.value = autoFailureRetryable(message)
    } else {
      errorMsg.value = message
    }
    return
  }

  starting.value = false
  void attachStream(taskId)
}

async function cancel() {
  const taskId = task.value?.task_id || activeTaskId.value
  stopTimers()
  stopStream()
  resetStreamState()
  if (taskId) {
    try {
      await api.deleteSummary(taskId)
    } catch {
      /* 任务可能已结束或已过期 */
    }
  }
  task.value = null
  transcript.value = null
  transcriptError.value = ''
  errorMsg.value = ''
  autoNotice.value = ''
  autoNoticeRetryable.value = false
  emit('task-change', null)
}

function selectTab(tab: TabKey) {
  activeTab.value = tab
  subtitleError.value = ''
  if (tab === 'transcript' && transcript.value === null) {
    void loadTranscript()
  }
}

function emitSeek(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined) return
  emit('seek', Math.max(0, seconds))
}

function safeTitle(): string {
  return (props.result.title || '视频').replace(/[\\/:*?"<>|]+/g, '_').slice(0, 80)
}

async function copyMarkdown() {
  const markdown = summary.value?.markdown
  if (!markdown) return
  try {
    await navigator.clipboard.writeText(markdown)
    copied.value = true
    window.setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    const area = document.createElement('textarea')
    area.value = markdown
    document.body.appendChild(area)
    area.select()
    document.execCommand('copy')
    area.remove()
    copied.value = true
    window.setTimeout(() => {
      copied.value = false
    }, 2000)
  }
}

function downloadMarkdown() {
  const markdown = summary.value?.markdown
  if (!markdown) return
  const blob = new Blob([markdown], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${safeTitle()}-AI总结.md`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

async function copyTranscript() {
  const segments = transcript.value
  if (!segments?.length) return
  const text = segments
    .map((segment) => `[${formatDuration(segment.start_seconds)}] ${segment.text}`)
    .join('\n')
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    window.setTimeout(() => {
      copied.value = false
    }, 2000)
  } catch {
    /* 忽略剪贴板权限错误 */
  }
}

async function downloadSubtitle() {
  const taskId = task.value?.task_id
  if (!taskId || subtitleDownloading.value) return
  subtitleDownloading.value = true
  subtitleError.value = ''
  try {
    const file = await downloadSummarySubtitle(taskId, subtitleFormat.value)
    const fallback = `${safeFilename(props.result.title || '视频')}-字幕.${subtitleFormat.value}`
    saveBlob(file.blob, file.filename || fallback)
  } catch (err) {
    subtitleError.value = errorText(err)
  } finally {
    subtitleDownloading.value = false
  }
}

watch(
  () => task.value?.task_id ?? null,
  (taskId) => emit('task-change', taskId),
)

function onAutoToggle(event: Event) {
  emit('update:autoSummary', (event.target as HTMLInputElement).checked)
}

onMounted(() => {
  void loadConfig()
})

onBeforeUnmount(() => {
  stopTimers()
  stopStream()
  emit('task-change', null)
  const taskId = task.value?.task_id || activeTaskId.value
  if (isBusy.value && taskId) {
    void api.deleteSummary(taskId).catch(() => {})
  }
})
</script>

<template>
  <section
    id="ai-summary"
    :data-summary-phase="summaryPhase"
    class="card min-w-0 scroll-mt-20 animate-float-in lg:flex lg:h-full lg:min-h-0 lg:flex-col lg:overflow-hidden"
  >
    <div class="rounded-t-[1rem] border-b border-violet-100 bg-gradient-to-r from-violet-50 via-indigo-50/70 to-white px-4 py-3 sm:px-5">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="flex min-w-0 items-start gap-3">
          <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-500 text-lg text-white shadow-lg shadow-violet-200">
            ✨
          </span>
          <div class="min-w-0">
            <h3 class="text-base font-bold text-ink-900">AI 视频总结</h3>
            <p class="mt-0.5 text-xs leading-relaxed text-ink-500">
              平台字幕优先，无字幕时自动语音识别；输出带时间戳的章节、要点、文稿和思维导图。
            </p>
          </div>
        </div>
        <div class="flex shrink-0 flex-wrap items-center gap-1.5 text-[10px]">
          <label
            v-if="config?.enabled"
            class="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-violet-200 bg-white px-2.5 py-1 text-[11px] font-medium text-violet-700"
          >
            <input
              type="checkbox"
              class="h-3 w-3 accent-violet-600"
              :checked="props.autoStart"
              @change="onAutoToggle"
            />
            解析后自动总结
          </label>
          <span class="rounded-full border border-violet-200 bg-white px-2 py-0.5 font-medium text-violet-600">
            单视频 ≤ {{ maxDurationText }}
          </span>
          <span class="rounded-full border border-violet-200 bg-white px-2 py-0.5 font-medium text-violet-600">
            中文输出
          </span>
        </div>
      </div>
    </div>

    <div data-summary-scroll class="px-4 py-4 sm:px-5 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:overscroll-contain lg:pr-4">
      <!-- 配置加载 -->
      <div v-if="configState === 'loading'" class="space-y-2">
        <div class="h-3 w-2/3 animate-pulse rounded bg-slate-100" />
        <div class="h-3 w-1/2 animate-pulse rounded bg-slate-100" />
      </div>

      <!-- 配置失败 -->
      <div v-else-if="configState === 'error'" class="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <p class="font-semibold">AI 总结暂时不可用</p>
        <p class="mt-1 text-xs leading-relaxed">{{ configError }}</p>
        <button type="button" class="mt-2 text-xs font-semibold text-amber-700 underline" @click="loadConfig">
          重试
        </button>
      </div>

      <!-- 未配置 Key -->
      <div v-else-if="config && !config.enabled" class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-ink-600">
        <p class="font-semibold text-ink-900">AI 总结未启用</p>
        <p class="mt-1 text-xs leading-relaxed">
          {{ config.reason || '服务端未配置 DeepSeek API Key' }}。在
          <code class="rounded bg-white px-1 py-0.5 text-[11px] text-ink-700">backend/.env</code>
          中配置后重启后端即可使用。
        </p>
      </div>

      <template v-else-if="config">
        <p
          v-if="errorMsg && !task"
          class="mb-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-600"
        >
          {{ errorMsg }}
        </p>

        <div
          v-if="autoNotice && !task && !starting"
          class="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs leading-relaxed text-amber-800"
        >
          <p class="font-semibold">本次没有自动总结</p>
          <p class="mt-0.5">{{ autoNotice }}</p>
          <button
            v-if="autoNoticeRetryable"
            type="button"
            class="mt-1.5 font-semibold underline"
            @click="generate(false)"
          >
            立即生成
          </button>
        </div>

        <!-- 未开始 -->
        <div v-if="!task && !starting && !streaming" class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0">
            <p class="text-sm font-semibold text-ink-900">
              {{ props.autoStart ? '把这条视频变成可复习的笔记' : '自动总结已关闭，可手动生成' }}
            </p>
            <p class="mt-1 text-xs leading-relaxed text-ink-500">
              先看 TL;DR 和章节，再按时间戳回看原片。无字幕视频会产生语音识别费用（约 0.4–0.8 元/小时），同一视频 6 小时内重复总结命中缓存。
            </p>
          </div>
          <button type="button" class="btn-primary shrink-0 px-5 py-2.5 text-sm" @click="generate(false)">
            生成总结
          </button>
        </div>

        <!-- 思考中（AI 大模型式的等待动画，不展示进度条） -->
        <div
          v-else-if="thinking"
          role="status"
          aria-live="polite"
          class="rounded-xl border border-violet-100 bg-gradient-to-br from-violet-50/80 via-white to-white px-4 py-4"
        >
          <div class="flex items-center gap-2.5">
            <span class="thinking-dots text-violet-500" aria-hidden="true">
              <i /><i /><i />
            </span>
            <p class="text-sm font-semibold text-violet-800">
              {{ thinkingTitle }}<span class="thinking-ellipsis">…</span>
            </p>
            <span class="ml-auto text-[11px] tabular-nums text-ink-400">{{ elapsedText }}</span>
          </div>
          <p class="mt-2 text-xs leading-relaxed text-violet-600">
            {{ thinkingDetail }}
          </p>
          <div class="mt-3 flex flex-wrap items-center justify-between gap-2">
            <span class="text-[11px] leading-relaxed text-ink-400">
              本次生成会占用每 IP 每日额度（默认 {{ config.daily_limit_per_ip }} 次/天）；命中缓存不占用额度。
            </span>
            <button type="button" class="text-xs font-medium text-red-500 hover:text-red-600" @click="cancel">
              取消
            </button>
          </div>
        </div>

        <!-- 任务错误 -->
        <div v-else-if="task?.status === 'error'" class="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <p class="font-semibold">总结失败</p>
          <p class="mt-1 text-xs leading-relaxed">{{ taskError }}</p>
          <button type="button" class="mt-2 text-xs font-semibold underline" @click="generate(false)">
            重试
          </button>
        </div>

        <!-- 结果 -->
        <div v-else-if="summary" class="space-y-4">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <div class="flex flex-wrap items-center gap-1.5 text-[11px]">
              <span
                v-if="streaming"
                role="status"
                aria-live="polite"
                class="inline-flex items-center gap-1.5 rounded-full bg-violet-50 px-2 py-0.5 font-medium text-violet-700"
              >
                <span class="thinking-dots text-violet-500" aria-hidden="true"><i /><i /><i /></span>
                正在输出
              </span>
              <span v-if="sourceLabel" class="rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700">
                {{ sourceLabel }}
              </span>
              <span class="rounded-full bg-slate-100 px-2 py-0.5 text-ink-500">
                {{ task?.stats.model || 'deepseek-flash' }}
              </span>
              <span v-if="task?.cached" class="rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-700">
                缓存复用
              </span>
              <span v-if="task?.stats.elapsed_seconds" class="text-ink-400">
                耗时 {{ task.stats.elapsed_seconds.toFixed(1) }}s
              </span>
            </div>
            <div v-if="!streaming" class="flex flex-wrap items-center gap-2 text-xs">
              <button type="button" class="font-medium text-brand-600 hover:text-brand-700" @click="copyMarkdown">
                {{ copied ? '已复制' : '复制 Markdown' }}
              </button>
              <button type="button" class="font-medium text-brand-600 hover:text-brand-700" @click="downloadMarkdown">
                下载 .md
              </button>
              <button type="button" class="font-medium text-ink-400 hover:text-brand-600" @click="generate(true)">
                重新生成
              </button>
            </div>
          </div>

          <p v-if="costText && !streaming" class="rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-ink-500">
            {{ costText }}；AI 生成内容可能有偏差，请结合原视频核对。
          </p>

          <div class="scrollbar-hidden z-10 flex gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1 lg:sticky lg:top-0">
            <button
              v-for="tab in visibleTabs"
              :key="tab.key"
              type="button"
              class="inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition"
              :class="
                activeTab === tab.key
                  ? 'bg-white text-violet-700 shadow-sm'
                  : 'text-ink-500 hover:text-ink-700'
              "
              @click="selectTab(tab.key)"
            >
              <SummaryTabIcon :name="tab.key" class="text-[14px]" />
              {{ tab.label }}
              <span v-if="tab.key === 'chapters' && summary.chapters.length" class="ml-0.5 text-[10px] text-ink-400">
                {{ summary.chapters.length }}
              </span>
              <span v-if="tab.key === 'transcript' && task?.stats.segments" class="ml-0.5 text-[10px] text-ink-400">
                {{ task.stats.segments }}
              </span>
            </button>
          </div>

          <!-- 总结 -->
          <div v-if="activeTab === 'summary'" class="space-y-4">
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div
                class="inline-flex rounded-xl bg-slate-100 p-1"
                :class="streaming ? 'pointer-events-none opacity-50' : ''"
              >
                <button
                  type="button"
                  class="rounded-lg px-3 py-1 text-xs font-medium transition"
                  :class="
                    effectiveSummaryView === 'note'
                      ? 'bg-white text-violet-700 shadow-sm'
                      : 'text-ink-500 hover:text-ink-700'
                  "
                  :disabled="streaming"
                  @click="setSummaryView('note')"
                >
                  笔记
                </button>
                <button
                  type="button"
                  class="rounded-lg px-3 py-1 text-xs font-medium transition"
                  :class="
                    effectiveSummaryView === 'cards'
                      ? 'bg-white text-violet-700 shadow-sm'
                      : 'text-ink-500 hover:text-ink-700'
                  "
                  :disabled="streaming"
                  @click="setSummaryView('cards')"
                >
                  卡片
                </button>
              </div>
              <span
                v-if="summaryView === 'note' && effectiveSummaryView === 'cards' && !streaming"
                class="text-[11px] text-ink-400"
              >
                本次总结没有 Markdown 笔记，已显示卡片视图
              </span>
            </div>

            <div
              v-if="streaming && effectiveSummaryView === 'note' && !streamText"
              class="max-w-[52rem] rounded-xl border border-violet-100 bg-violet-50/50 px-4 py-4"
            >
              <div class="flex items-center gap-2.5">
                <span class="thinking-dots text-violet-500" aria-hidden="true"><i /><i /><i /></span>
                <span class="text-xs font-medium text-violet-700">正在整理总结内容…</span>
              </div>
              <div class="mt-3 space-y-2">
                <div class="h-3 w-3/4 animate-pulse rounded bg-violet-100/80" />
                <div class="h-3 w-2/3 animate-pulse rounded bg-violet-100/60" />
                <div class="h-3 w-1/2 animate-pulse rounded bg-violet-100/40" />
              </div>
            </div>

            <MarkdownNote
              v-else-if="effectiveSummaryView === 'note'"
              class="max-w-[52rem]"
              :markdown="streaming ? streamText : summary.markdown"
              :seekable="seekable && !streaming"
              @seek="emitSeek"
            />

            <div v-else class="max-w-[52rem] space-y-4">
              <div class="rounded-xl border border-violet-100 bg-violet-50/70 px-4 py-3">
                <p class="text-[11px] font-semibold uppercase tracking-wide text-violet-500">TL;DR</p>
                <p class="mt-1 text-sm font-medium leading-relaxed text-ink-900">
                  {{ summary.tldr }}
                </p>
              </div>

              <div v-if="summary.overview">
                <h4 class="text-sm font-semibold text-ink-900">内容概述</h4>
                <p class="mt-1.5 text-sm leading-relaxed text-ink-600">{{ summary.overview }}</p>
              </div>

              <div v-if="summary.keywords.length" class="flex flex-wrap gap-1.5">
                <span
                  v-for="keyword in summary.keywords"
                  :key="keyword"
                  class="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-[11px] text-ink-500"
                >
                  {{ keyword }}
                </span>
              </div>

              <div v-if="summary.key_points.length">
                <h4 class="text-sm font-semibold text-ink-900">核心要点</h4>
                <ol class="mt-2 space-y-2">
                  <li
                    v-for="(point, index) in summary.key_points"
                    :key="`${index}-${point.title}`"
                    class="flex gap-3 rounded-xl border border-slate-100 bg-white px-3 py-2.5"
                  >
                    <span class="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-violet-50 text-[10px] font-bold text-violet-600">
                      {{ index + 1 }}
                    </span>
                    <div class="min-w-0">
                      <p class="text-sm font-semibold text-ink-900">
                        {{ point.title }}
                        <button
                          v-if="point.timestamp_seconds !== null"
                          type="button"
                          class="ml-1 rounded bg-violet-50 px-1.5 py-0.5 text-[10px] font-medium text-violet-600 hover:bg-violet-100 disabled:opacity-40"
                          :disabled="!seekable"
                          @click="emitSeek(point.timestamp_seconds)"
                        >
                          {{ formatDuration(point.timestamp_seconds) }}
                        </button>
                      </p>
                      <p v-if="point.detail" class="mt-0.5 text-xs leading-relaxed text-ink-500">
                        {{ point.detail }}
                      </p>
                    </div>
                  </li>
                </ol>
              </div>

              <div v-if="summary.concepts.length">
                <h4 class="text-sm font-semibold text-ink-900">关键概念</h4>
                <dl class="mt-2 grid gap-2 sm:grid-cols-2">
                  <div
                    v-for="concept in summary.concepts"
                    :key="concept.term"
                    class="rounded-xl border border-slate-100 bg-white px-3 py-2.5"
                  >
                    <dt class="text-sm font-semibold text-ink-900">{{ concept.term }}</dt>
                    <dd class="mt-0.5 text-xs leading-relaxed text-ink-500">{{ concept.explanation }}</dd>
                  </div>
                </dl>
              </div>
            </div>
          </div>

          <!-- 章节 -->
          <div v-else-if="activeTab === 'chapters'" class="space-y-2">
            <div
              v-for="chapter in summary.chapters"
              :key="`${chapter.start_seconds}-${chapter.title}`"
              class="rounded-xl border border-slate-100 bg-white px-4 py-3"
            >
              <div class="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  class="rounded-lg bg-violet-50 px-2 py-1 text-xs font-semibold text-violet-700 hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-40"
                  :disabled="!seekable"
                  :title="seekable ? '跳转到视频对应位置' : '当前清晰度不支持在线预览跳转'"
                  @click="emitSeek(chapter.start_seconds)"
                >
                  {{ formatDuration(chapter.start_seconds) }}
                </button>
                <h4 class="text-sm font-semibold text-ink-900">{{ chapter.title }}</h4>
              </div>
              <p v-if="chapter.summary" class="mt-2 text-sm leading-relaxed text-ink-600">
                {{ chapter.summary }}
              </p>
              <ul v-if="chapter.key_points.length" class="mt-2 space-y-1">
                <li
                  v-for="point in chapter.key_points"
                  :key="point"
                  class="flex gap-2 text-xs leading-relaxed text-ink-500"
                >
                  <span class="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-violet-300" />
                  {{ point }}
                </li>
              </ul>
            </div>
          </div>

          <!-- 文稿 -->
          <div v-else-if="activeTab === 'transcript'" class="space-y-2">
            <div class="flex flex-wrap items-start justify-between gap-2">
              <p class="text-[11px] leading-relaxed text-ink-400">
                共 {{ transcript?.length ?? 0 }} 段；时间戳为{{ task?.transcript_source === 'asr' ? '语音识别分片起点（约 1 分钟粒度）' : '平台字幕时间' }}。
              </p>
              <div class="flex flex-wrap items-center gap-2">
                <button
                  v-if="transcript?.length"
                  type="button"
                  class="rounded-lg border border-slate-200 px-2.5 py-1 text-[11px] font-medium text-ink-600 transition hover:border-violet-200 hover:text-violet-700"
                  @click="copyTranscript"
                >
                  复制文稿
                </button>
                <select
                  v-model="subtitleFormat"
                  class="rounded-lg border border-slate-200 bg-white px-2 py-1 text-[11px] text-ink-600 focus:border-violet-300 focus:outline-none"
                  :disabled="subtitleDownloading || !transcript?.length"
                  aria-label="字幕文件格式"
                >
                  <option v-for="item in subtitleFormats" :key="item.value" :value="item.value">
                    {{ item.label }}
                  </option>
                </select>
                <button
                  type="button"
                  class="rounded-lg bg-violet-600 px-2.5 py-1 text-[11px] font-semibold text-white transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="subtitleDownloading || !transcript?.length"
                  @click="downloadSubtitle"
                >
                  {{ subtitleDownloading ? '下载中…' : '下载字幕' }}
                </button>
              </div>
            </div>
            <p v-if="subtitleError" class="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">
              {{ subtitleError }}
            </p>

            <p v-if="transcriptLoading" class="rounded-lg bg-slate-50 px-3 py-2 text-xs text-ink-400">
              正在加载文稿…
            </p>
            <p v-else-if="transcriptError" class="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-600">
              {{ transcriptError }}
            </p>
            <div v-else class="max-h-[28rem] space-y-1.5 overflow-y-auto pr-1">
              <div
                v-for="(segment, index) in visibleTranscript"
                :key="`${index}-${segment.start_seconds}`"
                class="flex gap-3 rounded-lg px-2 py-1.5 hover:bg-slate-50"
              >
                <button
                  type="button"
                  class="w-12 shrink-0 text-left text-[11px] font-medium tabular-nums text-violet-600 hover:underline disabled:opacity-40"
                  :disabled="!seekable"
                  @click="emitSeek(segment.start_seconds)"
                >
                  {{ formatDuration(segment.start_seconds) }}
                </button>
                <p class="min-w-0 flex-1 text-xs leading-relaxed text-ink-600">
                  {{ segment.text }}
                </p>
              </div>
            </div>
            <button
              v-if="canLoadMore"
              type="button"
              class="w-full rounded-lg border border-slate-200 py-2 text-xs font-medium text-ink-500 hover:border-violet-200 hover:text-violet-600"
              @click="transcriptLimit += 200"
            >
              加载更多
            </button>
          </div>

          <!-- 思维导图 -->
          <div v-else-if="activeTab === 'mindmap'" class="rounded-xl border border-slate-100 bg-white px-4 py-3">
            <MindmapViewer v-if="summary.mindmap" :node="summary.mindmap" :title="safeTitle()" />
            <p v-else class="text-xs text-ink-400">本次总结没有生成思维导图。</p>
          </div>

          <!-- 问答：用 v-show 保持切换标签时的会话与流式请求 -->
          <div
            v-if="config.qa_enabled"
            v-show="activeTab === 'qa'"
            class="rounded-xl border border-slate-100 bg-white p-3"
          >
            <QaChatPanel
              v-if="task?.task_id"
              :key="task.task_id"
              :task-id="task.task_id"
              :suggestions="qaSuggestions"
              :daily-limit="config.qa_daily_limit_per_ip"
              :max-length="config.qa_max_question_chars"
              @regenerate="generate(true)"
            />
          </div>

          <p class="border-t border-slate-100 pt-3 text-[11px] leading-relaxed text-ink-400">
            本笔记由 AI 自动生成，可能存在遗漏或偏差；请结合原视频核对。仅用于学习与个人研究。
          </p>
        </div>

        <!-- 意外状态兜底 -->
        <div v-else class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-ink-500">
          任务状态异常，请重新生成。
          <button type="button" class="ml-2 font-semibold text-brand-600 underline" @click="generate(true)">
            重新生成
          </button>
        </div>
      </template>
    </div>
  </section>
</template>
