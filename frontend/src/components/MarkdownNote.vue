<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { renderMarkdown } from '../utils/markdown'

const props = defineProps<{
  markdown: string
  seekable: boolean
}>()

const emit = defineEmits<{
  (e: 'seek', seconds: number): void
}>()

const articleRef = ref<HTMLElement | null>(null)
// 桌面默认展开、移动端默认收起；只在初始化时判断一次，避免覆盖用户手动切换。
const tocOpen = ref(
  typeof window === 'undefined' || window.matchMedia('(min-width: 768px)').matches,
)

// html 已由 utils/markdown.ts 里的 DOMPurify 消毒，模板中才允许使用 v-html。
const rendered = computed(() => renderMarkdown(props.markdown, { seekable: props.seekable }))
const html = computed(() => rendered.value.html)
const headings = computed(() => rendered.value.headings)
const isEmpty = computed(() => !props.markdown.trim() || !html.value.trim())

function scrollToHeading(id: string): void {
  const container = articleRef.value
  if (!container) return
  const target = container.querySelector<HTMLElement>(`#${id}`)
  if (!target) return

  // 移动端先收起目录再滚动，避免目录高度变化导致目标位置偏移。
  if (window.matchMedia('(max-width: 767px)').matches && tocOpen.value) {
    tocOpen.value = false
    void nextTick(() => target.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    return
  }
  target.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function onArticleClick(event: MouseEvent): void {
  const target = event.target
  if (!(target instanceof Element)) return
  const anchor = target.closest<HTMLAnchorElement>('a[href^="#t="]')
  if (!anchor || !articleRef.value?.contains(anchor)) return

  // 时间戳只用于 seek，阻止浏览器按 "#t=0" 跳转或改写地址栏 hash。
  event.preventDefault()
  if (!props.seekable) return

  const raw = anchor.dataset.seek ?? anchor.getAttribute('href')?.slice(3) ?? ''
  const seconds = Number.parseInt(raw, 10)
  if (!Number.isFinite(seconds) || seconds < 0) return
  emit('seek', seconds)
}
</script>

<template>
  <section class="space-y-3">
    <!-- 目录：由 h2/h3 生成，点击平滑滚动；移动端默认收起 -->
    <nav
      v-if="headings.length"
      class="overflow-hidden rounded-xl border border-slate-200 bg-white"
      aria-label="笔记目录"
    >
      <button
        type="button"
        class="flex w-full items-center justify-between gap-3 px-3.5 py-2.5 text-left transition hover:bg-slate-50"
        :aria-expanded="tocOpen"
        @click="tocOpen = !tocOpen"
      >
        <span class="flex min-w-0 items-center gap-2">
          <svg
            viewBox="0 0 20 20"
            class="h-4 w-4 shrink-0 text-brand-500"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            aria-hidden="true"
          >
            <path d="M3.5 5.5h13M3.5 10h9M3.5 14.5h11" />
          </svg>
          <span class="text-xs font-semibold text-ink-700">目录</span>
          <span class="rounded-full bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium tabular-nums text-ink-500">
            {{ headings.length }}
          </span>
          <span class="hidden text-[10px] text-ink-400 sm:inline">点击跳转章节</span>
        </span>
        <span
          class="shrink-0 text-ink-400 transition-transform duration-200"
          :class="tocOpen ? 'rotate-180' : ''"
        >
          <svg
            viewBox="0 0 20 20"
            class="h-4 w-4"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
          >
            <path d="M5 7.5 10 12.5l5-5" />
          </svg>
        </span>
      </button>

      <div v-show="tocOpen" class="max-h-64 overflow-y-auto border-t border-slate-100 px-2 py-2">
        <ol class="space-y-0.5">
          <li v-for="heading in headings" :key="heading.id">
            <button
              type="button"
              class="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-ink-600 transition hover:bg-brand-50 hover:text-brand-700"
              :class="
                heading.level === 3
                  ? 'pl-7 text-xs'
                  : 'text-[13px] font-medium'
              "
              @click="scrollToHeading(heading.id)"
            >
              <span
                class="mt-[0.4rem] h-1 w-1 shrink-0 rounded-full"
                :class="heading.level === 3 ? 'bg-slate-300' : 'bg-brand-400'"
              />
              <span class="min-w-0 break-words">{{ heading.text }}</span>
            </button>
          </li>
        </ol>
      </div>
    </nav>

    <!-- 空内容兜底；面板可据此回退卡片视图 -->
    <div
      v-if="isEmpty"
      class="rounded-xl border border-dashed border-slate-200 bg-slate-50/60 px-4 py-5"
    >
      <p class="text-sm font-medium text-ink-700">本次总结没有生成 Markdown 笔记</p>
      <p class="mt-1 text-xs leading-relaxed text-ink-400">
        可以切换到卡片视图查看结构化总结，或重新生成总结后再试。
      </p>
    </div>

    <!-- v-html 的内容来自 renderMarkdown() 的 DOMPurify 消毒结果 -->
    <article
      v-else
      ref="articleRef"
      class="md-body"
      aria-label="Markdown 笔记正文"
      @click="onArticleClick"
      v-html="html"
    />
  </section>
</template>
