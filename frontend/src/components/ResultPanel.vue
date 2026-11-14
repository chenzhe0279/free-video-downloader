<script setup lang="ts">
import { computed, ref } from 'vue'
import PreviewPlayer from './PreviewPlayer.vue'
import type { DownloadMode, PreviewState, ProbeResult } from '../api/client'
import { formatBytes, formatDuration, platformLabel } from '../utils/format'

const props = defineProps<{
  result: ProbeResult
  selectedId: string
  busyOption: string
  busyMode: DownloadMode | ''
  removeWatermark: boolean
  previewStatus: PreviewState
  previewUrl: string
  previewProgress: number
  previewMessage: string
}>()

const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'server', id: string): void
  (e: 'local', id: string): void
  (e: 'direct', id: string): void
  (e: 'preview'): void
  (e: 'toggle-watermark', value: boolean): void
}>()

const selectedOption = computed(() =>
  props.result.options.find((opt) => opt.id === props.selectedId),
)

const playerRef = ref<{ seekTo: (seconds: number) => void } | null>(null)

defineExpose({
  seekTo: (seconds: number) => playerRef.value?.seekTo(seconds),
})

function canDirect(opt: ProbeResult['options'][number] | undefined) {
  if (!opt) return false
  return Boolean(opt.progressive && opt.direct_format_id && !opt.audio_only)
}

function isBusy(mode: DownloadMode) {
  return Boolean(props.busyOption) && props.busyOption === props.selectedId && props.busyMode === mode
}

const primaryBusy = computed(() => Boolean(props.busyOption) && props.busyOption === props.selectedId)

function primaryLabel(): string {
  if (isBusy('local')) return '准备中…'
  if (props.busyOption === props.selectedId) return '处理中…'
  return '下载到本地'
}

function onWatermarkChange(event: Event) {
  emit('toggle-watermark', (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <section
    id="result"
    class="card animate-float-in overflow-hidden lg:flex lg:h-full lg:min-h-0 lg:flex-col"
  >
    <div class="p-4">
      <PreviewPlayer
        ref="playerRef"
        :poster="props.result.thumbnail"
        :src="props.previewUrl"
        :status="props.previewStatus"
        :progress="props.previewProgress"
        :message="props.previewMessage"
        :label="selectedOption?.label ?? ''"
        :duration="props.result.duration"
        :disabled="Boolean(selectedOption?.audio_only)"
        @request-preview="emit('preview')"
      />

      <div class="mt-3 min-w-0">
        <h2 class="line-clamp-2 text-base font-bold leading-snug text-ink-900 sm:text-lg">
          {{ props.result.title }}
        </h2>
        <div class="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-ink-500">
          <span class="rounded-full bg-brand-50 px-2 py-0.5 font-semibold text-brand-700">
            {{ platformLabel(props.result.platform) }}
          </span>
          <span v-if="props.result.uploader" class="max-w-[14rem] truncate">
            {{ props.result.uploader }}
          </span>
          <span v-if="props.result.duration">{{ formatDuration(props.result.duration) }}</span>
          <span v-if="props.result.subtitles.length">含 {{ props.result.subtitles.length }} 种字幕</span>
          <span v-if="props.result.is_playlist">
            合集 · {{ props.result.entry_count ?? '多' }} 个视频
          </span>
        </div>
      </div>
    </div>

    <div class="border-t border-slate-100 px-4 py-3 lg:flex lg:min-h-0 lg:flex-1 lg:flex-col lg:overflow-y-auto lg:overscroll-contain">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <p class="text-xs font-semibold text-ink-900">清晰度</p>
        <label
          v-if="props.result.watermark?.available"
          class="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-700"
        >
          <input
            type="checkbox"
            class="h-3 w-3 accent-amber-600"
            :checked="props.removeWatermark"
            @change="onWatermarkChange"
          />
          去水印 · 有损
        </label>
      </div>

      <div class="mt-2 flex flex-wrap gap-1.5" role="radiogroup" aria-label="清晰度">
        <button
          v-for="opt in props.result.options"
          :key="opt.id"
          type="button"
          role="radio"
          :aria-checked="props.selectedId === opt.id"
          class="shrink-0 rounded-full border px-3 py-1.5 text-xs font-semibold transition"
          :class="
            props.selectedId === opt.id
              ? 'border-brand-500 bg-brand-50 text-brand-700 shadow-[0_0_0_1px_rgba(37,99,235,0.2)]'
              : 'border-slate-200 bg-white text-ink-600 hover:border-brand-300 hover:text-brand-600'
          "
          @click="emit('select', opt.id)"
        >
          {{ opt.label }}
        </button>
      </div>

      <div v-if="selectedOption" class="mt-2 space-y-0.5">
        <p class="flex flex-wrap items-center gap-x-1.5 text-[11px] text-ink-500">
          <span v-if="selectedOption.ext" class="font-medium uppercase">
            {{ selectedOption.ext }}
          </span>
          <span v-if="selectedOption.filesize">· 约 {{ formatBytes(selectedOption.filesize) }}</span>
          <span v-if="canDirect(selectedOption)" class="text-emerald-600">· 支持直链</span>
          <span v-if="selectedOption.audio_only" class="text-amber-600">· 音频不支持在线预览</span>
        </p>
        <p v-if="selectedOption.note" class="line-clamp-1 text-[11px] text-ink-400" :title="selectedOption.note">
          {{ selectedOption.note }}
        </p>
      </div>
      <p v-else class="mt-2 text-[11px] text-ink-400">该链接没有可下载的清晰度。</p>

      <div class="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <button
          type="button"
          class="btn-primary flex-1 px-4 py-2.5 text-sm"
          :disabled="!selectedOption || primaryBusy"
          @click="emit('local', props.selectedId)"
        >
          {{ primaryLabel() }}
        </button>
        <div class="flex items-center justify-center gap-2">
          <button
            v-if="canDirect(selectedOption) && !props.removeWatermark"
            type="button"
            class="chip px-3 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="primaryBusy"
            @click="emit('direct', props.selectedId)"
          >
            {{ isBusy('direct') ? '获取中…' : '直链下载' }}
          </button>
          <button
            type="button"
            class="chip px-3 py-1.5 text-xs disabled:cursor-not-allowed disabled:opacity-40"
            :disabled="primaryBusy"
            @click="emit('server', props.selectedId)"
          >
            {{ isBusy('server') ? '转存中…' : '服务端转存' }}
          </button>
        </div>
      </div>

      <p
        v-if="props.removeWatermark && props.result.watermark?.available"
        class="mt-2 rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-700"
      >
        已识别：{{ props.result.watermark.label }}。合并完成后重绘水印区域，耗时略长。
      </p>

      <details class="group mt-2.5 lg:mt-auto">
        <summary class="cursor-pointer text-[11px] font-medium text-ink-400 marker:content-none hover:text-brand-600">
          预览与下载说明
        </summary>
        <p class="mt-1.5 text-[11px] leading-relaxed text-ink-400">
          上方播放器在线预览当前清晰度：单文件格式边下边播；音视频分离的高清格式先由服务端合并，完成后再播放。「下载到本地」由服务端合并后立即传回本机，服务器只做临时中转；「服务端转存」把文件暂存 1 小时，方便换设备或稍后取回。
        </p>
      </details>
    </div>
  </section>
</template>
