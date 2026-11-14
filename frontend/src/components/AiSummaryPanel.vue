<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  api,
  type ProbeResult,
  type SummaryConfig,
  type SummaryTaskStatus,
  type SummaryTranscriptSegment,
} from '../api/client'
import { formatDuration } from '../utils/format'
import MindmapTree from './MindmapTree.vue'
import QaChatPanel from './QaChatPanel.vue'

const props = defineProps<{
  result: ProbeResult
  seekable: boolean
}>()

const emit = defineEmits<{
  (e: 'seek', seconds: number): void
}>()

type TabKey = 'summary' | 'chapters' | 'transcript' | 'mindmap' | 'qa'

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

let pollTimer: number | undefined
let elapsedTimer: number | undefined

const summary = computed(() => task.value?.summary ?? null)
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
  if (starting.value) return true
  const status = task.value?.status
  return (
    status === 'queued' ||
    status === 'fetching' ||
    status === 'transcribing' ||
    status === 'summarizing'
  )
})
const progress = computed(() => Math.max(0, Math.min(100, task.value?.progress ?? 0)))
const stageText = computed(() => task.value?.stage || '准备中')
const statusMessage = computed(() => task.value?.message || '')
const taskError = computed(() => task.value?.error || errorMsg.value)
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
  } catch (err) {
    configState.value = 'error'
    configError.value = errorText(err)
  }
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
    stopElapsed()
    activeTab.value = 'summary'
    void loadTranscript()
    return
  }
  if (data.status === 'error' || data.status === 'cancelled') {
    stopPolling()
    stopElapsed()
    return
  }
  schedulePoll(taskId)
}

async function generate(force = false) {
  if (isBusy.value) return
  errorMsg.value = ''
  copied.value = false
  if (force) {
    task.value = null
    transcript.value = null
    transcriptError.value = ''
  }
  starting.value = true
  activeTab.value = 'summary'
  startElapsed()
  try {
    const created = await api.createSummary(props.result.url, force)
    const data = await refreshTask(created.task_id)
    if (created.status === 'finished' || data?.status === 'finished') {
      stopElapsed()
      activeTab.value = 'summary'
      void loadTranscript()
      return
    }
    schedulePoll(created.task_id)
  } catch (err) {
    stopTimers()
    errorMsg.value = errorText(err)
  } finally {
    starting.value = false
  }
}

async function cancel() {
  const taskId = task.value?.task_id
  stopTimers()
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
}

function selectTab(tab: TabKey) {
  activeTab.value = tab
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

onMounted(() => {
  void loadConfig()
})

onBeforeUnmount(() => {
  stopTimers()
  if (isBusy.value && task.value) {
    void api.deleteSummary(task.value.task_id).catch(() => {})
  }
})
</script>

<template>
  <section id="ai-summary" class="scroll-mt-20 mt-6 card animate-float-in overflow-hidden">
    <div class="border-b border-violet-100 bg-gradient-to-r from-violet-50 via-indigo-50/70 to-white px-5 py-4">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div class="flex min-w-0 items-start gap-3">
          <span class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-violet-500 to-indigo-500 text-lg text-white shadow-lg shadow-violet-200">
            ✨
          </span>
          <div class="min-w-0">
            <h3 class="flex flex-wrap items-center gap-2 text-base font-bold text-ink-900">
              AI 视频总结
              <span class="rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold text-violet-700">
                DeepSeek V4.1 Flash
              </span>
            </h3>
            <p class="mt-0.5 text-xs leading-relaxed text-ink-500">
              平台字幕优先；没有字幕时自动语音识别。生成带时间戳的章节、要点、文稿和思维导图。
            </p>
          </div>
        </div>
        <div class="flex shrink-0 flex-wrap items-center gap-1.5 text-[10px]">
          <span class="rounded-full border border-violet-200 bg-white px-2 py-0.5 font-medium text-violet-600">
            单视频 ≤ {{ maxDurationText }}
          </span>
          <span class="rounded-full border border-violet-200 bg-white px-2 py-0.5 font-medium text-violet-600">
            中文输出
          </span>
        </div>
      </div>
    </div>

    <div class="px-5 py-5">
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

        <!-- 未开始 -->
        <div v-if="!task && !starting" class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div class="min-w-0">
            <p class="text-sm font-semibold text-ink-900">把这条视频变成可复习的笔记</p>
            <p class="mt-1 text-xs leading-relaxed text-ink-500">
              先看 TL;DR 和章节，再按时间戳回看原片。无字幕视频会产生语音识别费用（约 0.4–0.8 元/小时），同一视频 6 小时内重复总结命中缓存。
            </p>
          </div>
          <button type="button" class="btn-primary shrink-0 px-5 py-2.5 text-sm" @click="generate(false)">
            生成总结
          </button>
        </div>

        <!-- 生成中 -->
        <div v-else-if="isBusy" class="rounded-xl border border-violet-100 bg-violet-50/60 px-4 py-4">
          <div class="flex items-center justify-between gap-3">
            <p class="text-sm font-semibold text-violet-800">
              {{ starting && !task ? '正在创建总结任务…' : stageText }}
            </p>
            <span class="text-xs font-semibold tabular-nums text-violet-600">
              {{ progress.toFixed(0) }}%
            </span>
          </div>
          <div class="mt-2 h-2 overflow-hidden rounded-full bg-white">
            <div
              class="h-full rounded-full bg-gradient-to-r from-violet-500 to-indigo-500 transition-all duration-500"
              :style="{ width: `${Math.max(3, progress)}%` }"
            />
          </div>
          <p class="mt-2 text-xs leading-relaxed text-violet-700">
            {{ statusMessage || '正在准备视频与逐字稿…' }}
          </p>
          <div class="mt-3 flex items-center justify-between gap-3">
            <span class="text-[11px] text-ink-400">已用时 {{ elapsedText }}</span>
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
            <div class="flex flex-wrap items-center gap-2 text-xs">
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

          <p v-if="costText" class="rounded-lg bg-slate-50 px-3 py-2 text-[11px] leading-relaxed text-ink-500">
            {{ costText }}；AI 生成内容可能有偏差，请结合原视频核对。
          </p>

          <div class="flex gap-1 overflow-x-auto rounded-xl bg-slate-100 p-1">
            <button
              v-for="tab in visibleTabs"
              :key="tab.key"
              type="button"
              class="shrink-0 rounded-lg px-3 py-1.5 text-xs font-medium transition"
              :class="
                activeTab === tab.key
                  ? 'bg-white text-violet-700 shadow-sm'
                  : 'text-ink-500 hover:text-ink-700'
              "
              @click="selectTab(tab.key)"
            >
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
            <div class="flex items-center justify-between gap-2">
              <p class="text-[11px] text-ink-400">
                共 {{ transcript?.length ?? 0 }} 段；时间戳为{{ task?.transcript_source === 'asr' ? '语音识别分片起点（约 1 分钟粒度）' : '平台字幕时间' }}。
              </p>
              <button
                v-if="transcript?.length"
                type="button"
                class="shrink-0 text-xs font-medium text-brand-600 hover:text-brand-700"
                @click="copyTranscript"
              >
                复制文稿
              </button>
            </div>

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
            <MindmapTree v-if="summary.mindmap" :node="summary.mindmap" />
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
