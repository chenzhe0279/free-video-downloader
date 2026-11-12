<script setup lang="ts">
import { formatBytes, formatDuration, platformLabel } from '../utils/format'
import type { ProbeResult } from '../api/client'

const props = defineProps<{
  result: ProbeResult
  selectedId: string
  busyOption: string
}>()

const emit = defineEmits<{
  (e: 'select', id: string): void
  (e: 'server', id: string): void
  (e: 'direct', id: string): void
  (e: 'proxy', id: string): void
}>()

function canDirect(opt: ProbeResult['options'][number]) {
  return Boolean(opt.progressive && opt.direct_format_id && !opt.audio_only)
}
</script>

<template>
  <section class="mt-8 card overflow-hidden animate-float-in" id="result">
    <div class="flex flex-col gap-4 p-5 sm:flex-row">
      <div class="relative w-full shrink-0 overflow-hidden rounded-xl bg-slate-100 sm:w-56">
        <img
          v-if="props.result.thumbnail"
          :src="props.result.thumbnail"
          :alt="props.result.title"
          class="aspect-video w-full object-cover"
          referrerpolicy="no-referrer"
        />
        <div v-else class="grid aspect-video w-full place-items-center text-ink-400">
          <svg viewBox="0 0 24 24" class="h-10 w-10" fill="currentColor">
            <path d="M8 5.5v13l11-6.5z" />
          </svg>
        </div>
        <span
          class="absolute bottom-2 right-2 rounded-md bg-black/70 px-1.5 py-0.5 text-xs font-medium text-white"
        >
          {{ formatDuration(props.result.duration) }}
        </span>
      </div>

      <div class="min-w-0 flex-1">
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
          直链下载不占用服务器空间，速度取决于平台 CDN；服务端转存会把文件先保存到服务器再提供下载，兼容性更好，文件保留 1 小时。
        </p>
      </div>
    </div>

    <div class="border-t border-slate-100 px-5 py-4">
      <p class="mb-3 text-sm font-semibold text-ink-900">选择清晰度</p>
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

          <div class="flex shrink-0 gap-2">
            <button
              v-if="canDirect(opt)"
              type="button"
              class="btn-outline px-4 py-2 text-xs"
              :disabled="props.busyOption === opt.id"
              @click="emit('direct', opt.id)"
            >
              直链下载
            </button>
            <button
              v-if="canDirect(opt)"
              type="button"
              class="btn-outline px-4 py-2 text-xs"
              :disabled="props.busyOption === opt.id"
              @click="emit('proxy', opt.id)"
            >
              代理加速
            </button>
            <button
              type="button"
              class="btn-primary px-4 py-2 text-xs"
              :disabled="props.busyOption === opt.id"
              @click="emit('server', opt.id)"
            >
              {{ props.busyOption === opt.id ? '处理中…' : '服务端转存' }}
            </button>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>
