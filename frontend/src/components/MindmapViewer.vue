<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import type { MindmapNode } from '../api/client'
import { safeFilename, saveBlob } from '../utils/download'
import MindmapTree from './MindmapTree.vue'

const props = defineProps<{
  node: MindmapNode
  title: string
}>()

type ExportKind = 'png2x' | 'png3x' | 'svg'
type FeedbackKind = 'success' | 'error'

interface Feedback {
  kind: FeedbackKind
  text: string
}

interface MindmapTreeExposed {
  fit: () => Promise<void>
  expandAll: () => Promise<void>
  exportPng: (scale: 2 | 3) => Promise<Blob>
  exportSvgString: () => Promise<{ content: string; width: number; height: number }>
}

const inlineTree = ref<MindmapTreeExposed | null>(null)
const fullscreenTree = ref<MindmapTreeExposed | null>(null)
const isFullscreen = ref(false)
const exportMenuOpen = ref(false)
const exportMenuPosition = ref({ top: 0, right: 0 })
const exporting = ref<ExportKind | null>(null)
const feedback = ref<Feedback | null>(null)

const EXPORT_MENU_HEIGHT = 158

let feedbackTimer: number | undefined
let bodyOverflowBeforeLock = ''
let bodyLocked = false

function setInlineTree(instance: unknown) {
  inlineTree.value = (instance as MindmapTreeExposed | null) ?? null
}

function setFullscreenTree(instance: unknown) {
  fullscreenTree.value = (instance as MindmapTreeExposed | null) ?? null
}

function activeTree(): MindmapTreeExposed | null {
  return isFullscreen.value ? fullscreenTree.value : inlineTree.value
}

function errorText(error: unknown): string {
  return error instanceof Error && error.message ? error.message : '未知错误'
}

function pngFailureText(error: unknown): string {
  const reason = errorText(error).replace(/[，,。]?\s*请改用\s*SVG/g, '').trim()
  return reason ? `PNG 导出失败，请改用 SVG（${reason}）` : 'PNG 导出失败，请改用 SVG'
}

function clearFeedbackTimer() {
  if (feedbackTimer !== undefined) {
    window.clearTimeout(feedbackTimer)
    feedbackTimer = undefined
  }
}

function showFeedback(kind: FeedbackKind, text: string) {
  clearFeedbackTimer()
  feedback.value = { kind, text }
  feedbackTimer = window.setTimeout(
    () => {
      feedback.value = null
      feedbackTimer = undefined
    },
    kind === 'error' ? 7000 : 3500,
  )
}

function clearFeedback() {
  clearFeedbackTimer()
  feedback.value = null
}

function safeTitle(): string {
  return safeFilename(props.title, '视频')
}

async function runExport(kind: ExportKind) {
  if (exporting.value) return
  closeExportMenu()
  const tree = activeTree()
  if (!tree) {
    showFeedback('error', '思维导图尚未准备好，请稍后重试')
    return
  }

  clearFeedback()
  exporting.value = kind
  try {
    if (kind === 'svg') {
      try {
        const { content } = await tree.exportSvgString()
        if (!content.trim()) throw new Error('导出的 SVG 为空')
        const blob = new Blob([content], { type: 'image/svg+xml;charset=utf-8' })
        saveBlob(blob, `${safeTitle()}-思维导图.svg`)
        showFeedback('success', '已开始下载 SVG 矢量图')
      } catch (error) {
        showFeedback('error', `SVG 导出失败，请稍后重试：${errorText(error)}`)
      }
      return
    }

    const scale = kind === 'png2x' ? 2 : 3
    try {
      const blob = await tree.exportPng(scale)
      if (!blob.size) throw new Error('导出的 PNG 为空')
      saveBlob(blob, `${safeTitle()}-思维导图-${scale}x.png`)
      showFeedback('success', `已开始下载 PNG ${scale}x`)
    } catch (error) {
      showFeedback('error', pngFailureText(error))
    }
  } finally {
    exporting.value = null
  }
}

async function fitCurrentTree() {
  const tree = activeTree()
  if (!tree) return
  try {
    await tree.fit()
  } catch (error) {
    showFeedback('error', `适应屏幕失败：${errorText(error)}`)
  }
}

async function expandCurrentTree() {
  const tree = activeTree()
  if (!tree) return
  try {
    await tree.expandAll()
  } catch (error) {
    showFeedback('error', `展开全部失败：${errorText(error)}`)
  }
}

function toggleExportMenu(event: MouseEvent) {
  if (exporting.value) return
  if (exportMenuOpen.value) {
    exportMenuOpen.value = false
    return
  }
  const target = event.currentTarget
  if (!(target instanceof HTMLElement)) return
  const rect = target.getBoundingClientRect()
  const openBelow = rect.bottom + EXPORT_MENU_HEIGHT + 12 <= window.innerHeight
  exportMenuPosition.value = {
    top: openBelow
      ? Math.round(rect.bottom + 6)
      : Math.max(8, Math.round(rect.top - EXPORT_MENU_HEIGHT - 6)),
    // 菜单右边缘与按钮右边缘对齐，同时保证不超出视口
    right: Math.max(8, Math.round(window.innerWidth - rect.right)),
  }
  exportMenuOpen.value = true
}

function closeExportMenu() {
  exportMenuOpen.value = false
}

function handleViewportChange() {
  exportMenuOpen.value = false
}

function closeExportMenuOnOutside(event: PointerEvent) {
  if (!exportMenuOpen.value) return
  const target = event.target
  if (target instanceof Element && target.closest('[data-mindmap-export-menu]')) return
  exportMenuOpen.value = false
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

function lockBodyScroll() {
  if (bodyLocked) return
  bodyOverflowBeforeLock = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  bodyLocked = true
}

function unlockBodyScroll() {
  if (!bodyLocked) return
  if (bodyOverflowBeforeLock) {
    document.body.style.overflow = bodyOverflowBeforeLock
  } else {
    document.body.style.removeProperty('overflow')
  }
  bodyLocked = false
  bodyOverflowBeforeLock = ''
}

function handleFullscreenKeydown(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  event.preventDefault()
  closeFullscreen()
}

async function openFullscreen() {
  if (isFullscreen.value) return
  closeExportMenu()
  clearFeedback()
  isFullscreen.value = true
  lockBodyScroll()
  document.addEventListener('keydown', handleFullscreenKeydown, true)
  await nextTick()
  if (!isFullscreen.value) return
  await nextFrame()
  if (!isFullscreen.value) return
  try {
    await fullscreenTree.value?.fit()
  } catch (error) {
    console.warn('全屏思维导图适应失败', error)
  }
}

function closeFullscreen() {
  if (!isFullscreen.value) return
  closeExportMenu()
  isFullscreen.value = false
  unlockBodyScroll()
  document.removeEventListener('keydown', handleFullscreenKeydown, true)
}

onMounted(() => {
  document.addEventListener('pointerdown', closeExportMenuOnOutside)
  window.addEventListener('resize', handleViewportChange)
  window.addEventListener('scroll', handleViewportChange, true)
})

onBeforeUnmount(() => {
  clearFeedbackTimer()
  document.removeEventListener('pointerdown', closeExportMenuOnOutside)
  window.removeEventListener('resize', handleViewportChange)
  window.removeEventListener('scroll', handleViewportChange, true)
  document.removeEventListener('keydown', handleFullscreenKeydown, true)
  unlockBodyScroll()
})
</script>

<template>
  <section class="rounded-xl border border-slate-200 bg-white shadow-sm">
    <!-- 内嵌工具条 -->
    <div class="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50/70 px-3 py-2 sm:flex-nowrap">
      <div class="flex min-w-0 flex-1 items-center gap-2">
        <span class="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-violet-100 text-sm text-violet-600">
          🧠
        </span>
        <div class="min-w-0">
          <p class="truncate text-sm font-semibold leading-5 text-ink-900">
            {{ props.title || '视频思维导图' }}
          </p>
          <p class="hidden truncate text-[10px] leading-4 text-ink-400 sm:block">
            思维导图 · 全屏查看与高清导出
          </p>
        </div>
      </div>

      <div class="-mx-1 flex w-full flex-wrap items-center justify-end gap-1.5 px-1 pb-0.5 sm:mx-0 sm:w-auto sm:shrink-0 sm:flex-nowrap sm:px-0">
        <button
          type="button"
          class="inline-flex h-7 shrink-0 items-center rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-ink-600 transition hover:border-violet-200 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="exporting !== null"
          @click="fitCurrentTree"
        >
          适应屏幕
        </button>
        <button
          type="button"
          class="inline-flex h-7 shrink-0 items-center rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-ink-600 transition hover:border-violet-200 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="exporting !== null"
          @click="expandCurrentTree"
        >
          展开全部
        </button>

        <div class="relative shrink-0" data-mindmap-export-menu>
          <button
            type="button"
            class="inline-flex h-7 items-center gap-1 rounded-lg border border-violet-200 bg-violet-50 px-2.5 text-[11px] font-semibold text-violet-700 transition hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="exporting !== null"
            aria-haspopup="menu"
            :aria-expanded="exportMenuOpen"
            @click="toggleExportMenu"
          >
            {{ exporting !== null ? '导出中…' : '导出' }}
            <svg class="h-3 w-3" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M4 6.5 8 10l4-3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </button>
        </div>

        <button
          type="button"
          class="inline-flex h-7 shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-ink-600 transition hover:border-violet-200 hover:text-violet-700"
          @click="openFullscreen"
        >
          <svg class="h-3 w-3" viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <path d="M6 2.5H2.5V6M10 2.5h3.5V6M13.5 10v3.5H10M6 13.5H2.5V10" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
          全屏
        </button>
      </div>
    </div>

    <!-- 内嵌思维导图 -->
    <div class="relative p-2 sm:p-3">
      <MindmapTree :ref="setInlineTree" :node="props.node" height="600px" />
      <div
        v-if="feedback"
        class="pointer-events-none absolute left-3 right-3 top-3 z-30 flex items-start gap-2 rounded-xl border px-3 py-2 text-xs leading-relaxed shadow-lg sm:right-auto sm:max-w-sm"
        :class="
          feedback.kind === 'error'
            ? 'border-red-200 bg-red-50/95 text-red-700'
            : 'border-emerald-200 bg-emerald-50/95 text-emerald-700'
        "
        :role="feedback.kind === 'error' ? 'alert' : 'status'"
      >
        <span class="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-white/80 text-[10px] font-bold">
          {{ feedback.kind === 'error' ? '!' : '✓' }}
        </span>
        <span>{{ feedback.text }}</span>
      </div>
    </div>

    <!-- 全屏弹层 -->
    <Teleport to="body">
      <div
        v-if="isFullscreen"
        class="v0-6-mindmap-layer fixed inset-0 z-[100] flex items-stretch justify-center bg-slate-950/60 backdrop-blur-sm sm:px-4"
        role="dialog"
        aria-modal="true"
        aria-label="思维导图全屏"
        @click.self="closeFullscreen"
      >
        <div class="flex h-full min-h-0 w-full flex-col overflow-hidden bg-white sm:rounded-2xl" @click.stop>
          <div class="flex h-14 shrink-0 items-center gap-2 border-b border-slate-200 bg-gradient-to-r from-violet-50 via-white to-slate-50 px-3 sm:px-4">
            <div class="hidden min-w-0 flex-1 items-center gap-2 sm:flex">
              <span class="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-violet-100 text-sm text-violet-600">
                🧠
              </span>
              <div class="min-w-0">
                <p class="truncate text-sm font-semibold leading-5 text-ink-900">
                  {{ props.title || '视频思维导图' }}
                </p>
                <p class="hidden truncate text-[10px] leading-4 text-ink-400 sm:block">
                  思维导图全屏
                </p>
              </div>
            </div>

            <div class="ml-auto flex shrink-0 items-center gap-1.5 overflow-x-auto">
              <button
                type="button"
                class="inline-flex h-7 shrink-0 items-center rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-ink-600 transition hover:border-violet-200 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="exporting !== null"
                @click="fitCurrentTree"
              >
                适应屏幕
              </button>
              <button
                type="button"
                class="inline-flex h-7 shrink-0 items-center rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-ink-600 transition hover:border-violet-200 hover:text-violet-700 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="exporting !== null"
                @click="expandCurrentTree"
              >
                展开全部
              </button>

              <div class="relative shrink-0" data-mindmap-export-menu>
                <button
                  type="button"
                  class="inline-flex h-7 items-center gap-1 rounded-lg border border-violet-200 bg-violet-50 px-2.5 text-[11px] font-semibold text-violet-700 transition hover:bg-violet-100 disabled:cursor-not-allowed disabled:opacity-50"
                  :disabled="exporting !== null"
                  aria-haspopup="menu"
                  :aria-expanded="exportMenuOpen"
                  @click="toggleExportMenu"
                >
                  {{ exporting !== null ? '导出中…' : '导出' }}
                  <svg class="h-3 w-3" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                    <path d="M4 6.5 8 10l4-3.5" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" />
                  </svg>
                </button>
              </div>

              <button
                type="button"
                class="inline-flex h-7 shrink-0 items-center gap-1 rounded-lg border border-slate-200 bg-white px-2.5 text-[11px] font-medium text-ink-600 transition hover:border-red-200 hover:bg-red-50 hover:text-red-600"
                aria-label="退出全屏"
                @click="closeFullscreen"
              >
                <svg class="h-3 w-3" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                  <path d="m4.5 4.5 7 7m0-7-7 7" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
                </svg>
                退出全屏
              </button>
            </div>
          </div>

          <div class="relative min-h-0 flex-1">
            <MindmapTree
              :ref="setFullscreenTree"
              :node="props.node"
              height="calc(100dvh - 56px)"
            />
            <div
              v-if="feedback"
              class="pointer-events-none absolute left-3 right-3 top-3 z-30 flex items-start gap-2 rounded-xl border px-3 py-2 text-xs leading-relaxed shadow-lg sm:right-auto sm:max-w-sm"
              :class="
                feedback.kind === 'error'
                  ? 'border-red-200 bg-red-50/95 text-red-700'
                  : 'border-emerald-200 bg-emerald-50/95 text-emerald-700'
              "
              :role="feedback.kind === 'error' ? 'alert' : 'status'"
            >
              <span class="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-white/80 text-[10px] font-bold">
                {{ feedback.kind === 'error' ? '!' : '✓' }}
              </span>
              <span>{{ feedback.text }}</span>
            </div>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- 导出菜单：Teleport 到 body + fixed 定位，避免被工具栏的 overflow 裁切 -->
    <Teleport to="body">
      <div
        v-if="exportMenuOpen"
        data-mindmap-export-menu
        class="fixed z-[130] w-48 rounded-xl border border-slate-200 bg-white p-1 shadow-xl"
        :style="{
          top: `${exportMenuPosition.top}px`,
          right: `${exportMenuPosition.right}px`,
        }"
        role="menu"
        aria-label="思维导图导出菜单"
      >
        <p class="px-2.5 py-1.5 text-[10px] text-ink-400">导出当前展开的内容</p>
        <button
          type="button"
          class="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs font-medium text-ink-700 transition hover:bg-violet-50 hover:text-violet-700 disabled:opacity-50"
          role="menuitem"
          :disabled="exporting !== null"
          @click="runExport('png2x')"
        >
          <span>PNG 2x</span>
          <span class="text-[10px] text-ink-400">分享 / 文档</span>
        </button>
        <button
          type="button"
          class="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs font-medium text-ink-700 transition hover:bg-violet-50 hover:text-violet-700 disabled:opacity-50"
          role="menuitem"
          :disabled="exporting !== null"
          @click="runExport('png3x')"
        >
          <span>PNG 3x</span>
          <span class="text-[10px] text-ink-400">打印级</span>
        </button>
        <button
          type="button"
          class="flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs font-medium text-ink-700 transition hover:bg-violet-50 hover:text-violet-700 disabled:opacity-50"
          role="menuitem"
          :disabled="exporting !== null"
          @click="runExport('svg')"
        >
          <span>SVG</span>
          <span class="text-[10px] text-ink-400">矢量备份</span>
        </button>
      </div>
    </Teleport>
  </section>
</template>
