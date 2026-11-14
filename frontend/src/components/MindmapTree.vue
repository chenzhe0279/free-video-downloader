<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Markmap, type IMarkmapOptions } from 'markmap-view'
import type { MindmapNode } from '../api/client'

interface PureNode {
  content: string
  children: PureNode[]
}

const props = defineProps<{
  node: MindmapNode
}>()

const PALETTE = [
  '#5ad8a6',
  '#f6bd16',
  '#7262fd',
  '#5b8ff9',
  '#f6903d',
  '#9661bc',
  '#78d3f8',
  '#008685',
  '#f08bb4',
]

const svgEl = ref<SVGSVGElement | null>(null)
const shellEl = ref<HTMLDivElement | null>(null)
let markmap: Markmap | null = null
let observer: ResizeObserver | null = null
let branchColors = new Map<string, string>()
let branchSequence = 0

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function toPureNode(node: MindmapNode): PureNode {
  return {
    content: escapeHtml((node.title || '').trim() || '未命名节点'),
    children: (node.children || []).map(toPureNode),
  }
}

function colorFor(node: { state?: { path?: string } }): string {
  const parts = String(node.state?.path || '').split('.')
  if (parts.length <= 1) return '#2563eb'
  const branchKey = parts.slice(0, 2).join('.')
  const existing = branchColors.get(branchKey)
  if (existing) return existing
  const color = PALETTE[branchSequence % PALETTE.length]
  branchSequence += 1
  branchColors.set(branchKey, color)
  return color
}

function applyNodeColors() {
  const svg = svgEl.value
  if (!svg) return
  svg.querySelectorAll<SVGGElement>('.markmap-node').forEach((node) => {
    const foreign = node.querySelector<SVGForeignObjectElement>('.markmap-foreign')
    if (!foreign) return
    if (node.getAttribute('data-depth') === '1') {
      foreign.style.color = '#1d4ed8'
      return
    }
    const stroke = node.querySelector('line')?.getAttribute('stroke')
    if (stroke) foreign.style.color = stroke
  })
}

const OPTIONS: Partial<IMarkmapOptions> = {
  autoFit: true,
  duration: 350,
  embedGlobalCSS: true,
  initialExpandLevel: -1,
  maxWidth: 250,
  nodeMinHeight: 18,
  paddingX: 10,
  spacingHorizontal: 110,
  spacingVertical: 14,
  colorFreezeLevel: 0,
  color: colorFor,
  lineWidth: () => 2.2,
  maxInitialScale: 1.25,
  pan: true,
  zoom: true,
  scrollForPan: false,
  fitRatio: 0.94,
}

async function render() {
  if (!svgEl.value) return
  await nextTick()
  branchColors = new Map()
  branchSequence = 0
  try {
    if (!markmap) {
      markmap = Markmap.create(svgEl.value, OPTIONS, toPureNode(props.node))
    } else {
      await markmap.setData(toPureNode(props.node), OPTIONS)
    }
    await markmap.fit()
    applyNodeColors()
  } catch (error) {
    console.error('思维导图渲染失败', error)
  }
}

onMounted(() => {
  void render()
  if (shellEl.value && typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(() => {
      void markmap?.fit()
    })
    observer.observe(shellEl.value)
  }
})

watch(
  () => props.node,
  () => {
    void render()
  },
  { deep: true },
)

onBeforeUnmount(() => {
  observer?.disconnect()
  observer = null
  markmap?.destroy()
  markmap = null
})
</script>

<template>
  <div ref="shellEl" class="relative">
    <div class="pointer-events-none absolute right-2 top-2 z-10 rounded-full bg-white/85 px-2.5 py-1 text-[10px] text-ink-400 shadow-sm">
      滚轮缩放 · 拖拽移动 · 点击圆点展开/收起
    </div>
    <svg
      ref="svgEl"
      class="h-[540px] w-full rounded-lg bg-white"
      role="img"
      aria-label="视频思维导图"
    />
  </div>
</template>

<style scoped>
:deep(.markmap) {
  font-family: inherit;
}

:deep(.markmap-node > circle) {
  cursor: pointer;
}

:deep(.markmap-foreign) {
  line-height: 1.35;
}

:deep(.markmap-node[data-depth='1'] .markmap-foreign) {
  overflow: visible;
}

:deep(.markmap-node[data-depth='1'] .markmap-foreign > div) {
  margin: -4px -11px;
  padding: 4px 11px;
  border: 1.5px solid #2563eb;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 700;
}
</style>
