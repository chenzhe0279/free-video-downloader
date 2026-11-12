<script setup lang="ts">
import { computed } from 'vue'
import { formatBytes } from '../utils/format'
import type { TaskStatus } from '../api/client'

const props = defineProps<{
  task: TaskStatus
  title: string
}>()

const emit = defineEmits<{
  (e: 'cancel', taskId: string): void
}>()

const pct = computed(() => Math.max(0, Math.min(100, props.task.progress)))

const stateText = computed(() => {
  switch (props.task.status) {
    case 'queued':
      return '排队中'
    case 'downloading':
      return '正在下载'
    case 'processing':
      return '合并音视频中'
    case 'finished':
      return '已完成'
    case 'error':
      return '下载失败'
    default:
      return '处理中'
  }
})

const stateClass = computed(() => {
  switch (props.task.status) {
    case 'finished':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700'
    case 'error':
      return 'border-red-200 bg-red-50 text-red-600'
    default:
      return 'border-brand-200 bg-brand-50 text-brand-700'
  }
})

const isActive = computed(
  () => props.task.status === 'queued' || props.task.status === 'downloading' || props.task.status === 'processing',
)

const speedText = computed(() => (props.task.speed ? `${formatBytes(props.task.speed)}/s` : '--'))
const etaText = computed(() => (props.task.eta && props.task.eta > 0 ? `${props.task.eta} 秒` : '--'))

function downloadFile() {
  const href = props.task.download_url
  if (!href) return
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = props.task.filename || 'video.mp4'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}
</script>

<template>
  <section class="mt-6 card animate-float-in overflow-hidden">
    <div class="flex items-start justify-between gap-3 border-b border-slate-100 bg-slate-50/60 px-5 py-3">
      <h3 class="flex min-w-0 items-center gap-2 text-sm font-semibold text-ink-900">
        <svg viewBox="0 0 24 24" class="h-4 w-4 shrink-0 text-brand-600" fill="none" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
        </svg>
        <span class="truncate">{{ props.title }}</span>
      </h3>
      <span
        class="shrink-0 rounded-full border px-2.5 py-0.5 text-xs font-semibold"
        :class="stateClass"
      >
        {{ stateText }}
      </span>
    </div>

    <div class="space-y-4 px-5 py-4">
      <div class="flex items-center gap-3">
        <div class="h-2 flex-1 overflow-hidden rounded-full border border-slate-200 bg-slate-100">
          <div
            class="h-full rounded-full bg-gradient-to-r from-brand-500 to-brand-600 transition-all duration-500"
            :style="{ width: `${pct}%` }"
          />
        </div>
        <span class="w-14 shrink-0 text-right text-sm font-bold tabular-nums text-ink-900">
          {{ pct.toFixed(1) }}%
        </span>
      </div>

      <dl class="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        <div class="rounded-lg bg-slate-50 px-3 py-2">
          <dt class="text-ink-400">已下载</dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-ink-900">
            {{ formatBytes(props.task.downloaded_bytes) || '0 B' }}
          </dd>
        </div>
        <div class="rounded-lg bg-slate-50 px-3 py-2">
          <dt class="text-ink-400">总大小</dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-ink-900">
            {{ formatBytes(props.task.total_bytes) || '计算中' }}
          </dd>
        </div>
        <div class="rounded-lg bg-slate-50 px-3 py-2">
          <dt class="text-ink-400">速度</dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-ink-900">{{ speedText }}</dd>
        </div>
        <div class="rounded-lg bg-slate-50 px-3 py-2">
          <dt class="text-ink-400">剩余时间</dt>
          <dd class="mt-0.5 text-sm font-semibold tabular-nums text-ink-900">{{ etaText }}</dd>
        </div>
      </dl>

      <p v-if="props.task.status === 'error'" class="rounded-lg bg-red-50 px-3 py-2 text-xs leading-relaxed text-red-600">
        {{ props.task.error }}
      </p>

      <div class="flex flex-col gap-2 sm:flex-row sm:justify-end">
        <button
          v-if="isActive"
          type="button"
          class="btn-outline w-full py-2.5 text-sm sm:w-auto"
          @click="emit('cancel', props.task.task_id)"
        >
          取消下载
        </button>
        <button
          v-if="props.task.status === 'finished'"
          type="button"
          class="btn-primary w-full py-2.5 text-sm sm:w-auto"
          @click="downloadFile"
        >
          保存到本地
        </button>
        <p v-if="props.task.status === 'finished'" class="mt-1 text-center text-[11px] text-ink-400 sm:mt-0 sm:text-right">
          文件将在 1 小时后自动清理
        </p>
      </div>
    </div>
  </section>
</template>
