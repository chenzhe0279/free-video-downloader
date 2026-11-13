<script setup lang="ts">
import { computed } from 'vue'
import PreviewPlayer from './PreviewPlayer.vue'
import type { DownloadMode, PreviewState, ProbeResult } from '../api/client'
import { formatBytes, platformLabel } from '../utils/format'

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

function canDirect(opt: ProbeResult['options'][number]) {
  return Boolean(opt.progressive && opt.direct_format_id && !opt.audio_only)
}

function isBusy(optId: string) {
  return props.busyOption === optId
}

function onWatermarkChange(event: Event) {
  emit('toggle-watermark', (event.target as HTMLInputElement).checked)
}
</script>

<template>
  <section class="mt-8 card overflow-hidden animate-float-in" id="result">
    <div class="p-5">
      <PreviewPlayer
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

      <div class="mt-4 min-w-0">
        <h2 class="line-clamp-2 text-lg font-bold leading-snug text-ink-900">
          {{ props.result.title }}
        </h2>
        <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <span class="rounded-full bg-brand-50 px-2.5 py-1 font-semibold text-brand-700">
            {{ platformLabel(props.result.platform) }}
          </span>
          <span v-if="props.result.uploader" class="text-ink-500">
            作者：{{ props.result.uploader }}
          </span>
          <span v-if="props.result.is_playlist" class="text-ink-500">
            合集 · {{ props.result.entry_count ?? '多' }} 个视频
          </span>
          <span v-if="props.result.subtitles.length" class="text-ink-500">
            含 {{ props.result.subtitles.length }} 种字幕
          </span>
        </div>
        <p class="mt-3 text-xs leading-relaxed text-ink-400">
          上面的播放器可以直接在线预览当前选中的清晰度：单文件格式边下边播、秒开；音视频分离的高清格式会先由服务端合并，完成后再开始播放。「下载到本地」由服务端完成合并后立即传回本机，服务器只做临时中转；「服务端转存」会把文件暂存 1 小时，方便换设备或稍后取回。
        </p>
      </div>
    </div>

    <div class="border-t border-slate-100 px-5 py-4">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <p class="text-sm font-semibold text-ink-900">选择清晰度</p>
          <p class="mt-0.5 text-[11px] text-ink-400">
            选中某个清晰度后，点上方播放器即可在线预览该画质。
          </p>
        </div>
        <label
          v-if="props.result.watermark?.available"
          class="flex items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-3 py-1.5 text-[11px] font-medium text-amber-700"
        >
          <input
            type="checkbox"
            class="h-3.5 w-3.5 accent-amber-600"
            :checked="props.removeWatermark"
            @change="onWatermarkChange"
          />
          去水印 · 有损重编码
        </label>
      </div>
      <p
        v-if="props.result.watermark?.available"
        class="mb-3 rounded-lg bg-amber-50/70 px-3 py-2 text-[11px] leading-relaxed text-amber-700"
      >
        已识别：{{ props.result.watermark.label }}。勾选后会在音视频合并完成后重绘水印区域，耗时略长。
      </p>
      <ul class="space-y-2">
        <li
          v-for="opt in props.result.options"
          :key="opt.id"
          class="flex flex-col gap-3 rounded-xl border p-3 transition sm:flex-row sm:items-center"
          :class="
            props.selectedId === opt.id
              ? 'border-brand-500 bg-brand-50/60 shadow-[0_0_0_1px_rgba(37,99,235,0.2)]'
              : 'border-slate-200 bg-white hover:border-brand-200 hover:bg-slate-50/60'
          "
        >
          <button
            type="button"
            class="flex flex-1 items-center gap-3 text-left"
            @click="emit('select', opt.id)"
          >
            <span
              class="grid h-4 w-4 shrink-0 place-items-center rounded-full border-2"
              :class="props.selectedId === opt.id ? 'border-brand-600' : 'border-slate-300'"
            >
              <span
                v-if="props.selectedId === opt.id"
                class="h-2 w-2 rounded-full bg-brand-600"
              />
            </span>
            <span class="min-w-0">
              <span class="flex flex-wrap items-center gap-1.5">
                <span class="text-sm font-semibold text-ink-900">{{ opt.label }}</span>
                <span
                  v-if="opt.ext"
                  class="rounded border border-slate-200 bg-white px-1.5 py-0.5 text-[10px] font-medium uppercase text-ink-400"
                >
                  {{ opt.ext }}
                </span>
                <span
                  v-if="canDirect(opt)"
                  class="rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-600"
                >
                  支持直链
                </span>
              </span>
              <span class="mt-0.5 block text-xs text-ink-400">
                {{ opt.note }}<template v-if="opt.filesize"> · 约 {{ formatBytes(opt.filesize) }}</template>
              </span>
            </span>
          </button>

          <div class="flex shrink-0 flex-col items-stretch gap-1.5 sm:items-end">
            <button
              type="button"
              class="btn-primary w-full px-4 py-2 text-xs sm:w-auto"
              :disabled="isBusy(opt.id)"
              @click="emit('local', opt.id)"
            >
              {{ isBusy(opt.id) && props.busyMode === 'local' ? '准备中…' : '下载到本地' }}
            </button>
            <div class="flex items-center justify-center gap-3 text-[11px] text-ink-400">
              <button
                v-if="canDirect(opt) && !props.removeWatermark"
                type="button"
                class="font-medium transition hover:text-brand-600 disabled:opacity-40"
                :disabled="isBusy(opt.id)"
                @click="emit('direct', opt.id)"
              >
                {{ isBusy(opt.id) && props.busyMode === 'direct' ? '获取直链中…' : '直链' }}
              </button>
              <button
                type="button"
                class="font-medium transition hover:text-brand-600 disabled:opacity-40"
                :disabled="isBusy(opt.id)"
                @click="emit('server', opt.id)"
              >
                {{ isBusy(opt.id) && props.busyMode === 'server' ? '转存中…' : '服务端转存' }}
              </button>
            </div>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>
