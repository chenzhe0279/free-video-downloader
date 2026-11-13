<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { PreviewState } from '../api/client'
import { formatDuration } from '../utils/format'

const props = defineProps<{
  poster: string | null
  src: string
  status: PreviewState
  progress: number
  message: string
  label: string
  duration: number | null
  disabled: boolean
}>()

const emit = defineEmits<{
  (e: 'request-preview'): void
}>()

const videoEl = ref<HTMLVideoElement | null>(null)
const started = ref(false)

watch(
  () => props.src,
  async (value) => {
    if (!value) return
    await nextTick()
    const el = videoEl.value
    if (!el) return
    el.load()
    if (started.value) {
      el.play().catch(() => {
        /* 浏览器可能拦截自动播放，保留原生控件让用户手动点 */
      })
    }
  },
)

function onPlayButton() {
  started.value = true
  if (props.status === 'ready' && videoEl.value) {
    videoEl.value.play().catch(() => {})
    return
  }
  emit('request-preview')
}

function onVideoPlay() {
  started.value = true
}
</script>

<template>
  <div class="relative aspect-video w-full overflow-hidden rounded-xl bg-slate-900">
    <video
      v-if="props.status === 'ready' && props.src"
      ref="videoEl"
      :src="props.src"
      :poster="props.poster ?? undefined"
      class="h-full w-full bg-black object-contain"
      controls
      playsinline
      preload="metadata"
      @play="onVideoPlay"
    />

    <template v-else>
      <img
        v-if="props.poster"
        :src="props.poster"
        alt=""
        class="h-full w-full object-cover"
        referrerpolicy="no-referrer"
      />
      <div v-else class="h-full w-full bg-gradient-to-br from-slate-700 to-slate-900" />

      <div
        class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/45 px-6 text-center"
      >
        <span
          v-if="props.status === 'preparing'"
          class="grid h-16 w-16 place-items-center rounded-full bg-white/15 ring-1 ring-white/40"
        >
          <svg class="h-7 w-7 animate-spin text-white" viewBox="0 0 24 24" fill="none">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z" />
          </svg>
        </span>

        <button
          v-else
          type="button"
          class="group grid h-16 w-16 place-items-center rounded-full bg-white/90 text-brand-700 shadow-xl transition hover:scale-105 hover:bg-white disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="props.disabled"
          :aria-label="props.status === 'error' ? '重新准备在线预览' : '在线播放'"
          @click="onPlayButton"
        >
          <svg v-if="props.status === 'error'" class="h-7 w-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v6h6M20 20v-6h-6M20 8a8 8 0 00-14.9-1M4 16a8 8 0 0014.9 1" />
          </svg>
          <svg v-else class="ml-1 h-8 w-8" viewBox="0 0 24 24" fill="currentColor">
            <path d="M8 5.5v13l11-6.5z" />
          </svg>
        </button>

        <p class="max-w-md text-sm font-medium leading-relaxed text-white">
          {{ props.message }}
        </p>
        <p v-if="props.status === 'preparing' && props.progress > 0" class="text-xs text-white/80">
          {{ Math.round(props.progress) }}%
        </p>
      </div>

      <div v-if="props.status === 'preparing'" class="absolute inset-x-0 bottom-0 h-1 bg-white/20">
        <div
          class="h-full bg-brand-500 transition-all duration-500"
          :style="{ width: `${Math.min(100, Math.max(3, props.progress))}%` }"
        />
      </div>
    </template>

    <span
      v-if="props.label || props.duration"
      class="pointer-events-none absolute right-2 top-2 rounded-md bg-black/70 px-2 py-0.5 text-xs font-medium text-white"
    >
      <template v-if="props.label">{{ props.label }}</template>
      <template v-if="props.label && props.duration"> · </template>
      <template v-if="props.duration">{{ formatDuration(props.duration) }}</template>
    </span>
  </div>
</template>
