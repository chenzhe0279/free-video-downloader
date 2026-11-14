<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { Markmap, type IMarkmapOptions } from 'markmap-view'
import type { MindmapNode } from '../api/client'

interface PureNode {
  content: string
  children: PureNode[]
}

interface ExportSvg {
  content: string
  width: number
  height: number
}

interface ExportBounds {
  x: number
  y: number
  width: number
  height: number
}

interface FoldableNode {
  payload?: { fold?: number; [key: string]: unknown }
  children?: FoldableNode[]
}

const props = withDefaults(
  defineProps<{
    node: MindmapNode
    height?: string
  }>(),
  { height: '600px' },
)

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

const EXPORT_PADDING = 32
const MAX_CANVAS_SIDE = 16384
const FONT_FAMILY =
  '-apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Segoe UI", Roboto, sans-serif'

const svgEl = ref<SVGSVGElement | null>(null)
const shellEl = ref<HTMLDivElement | null>(null)
const exportNotice = ref('')
let exportNoticeTimer: number | undefined
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
  color: colorFor,
  lineWidth: () => 2.2,
  maxInitialScale: 1.25,
  pan: true,
  zoom: true,
  scrollForPan: false,
  fitRatio: 0.94,
  // 写入 SVG 的 <style>，页面与导出的 SVG/PNG 都能拿到同一套节点样式。
  style: (id) => `
.markmap.${id} {
  font-family: ${FONT_FAMILY};
}
.markmap.${id} .markmap-node > circle {
  cursor: pointer;
}
.markmap.${id} .markmap-foreign {
  line-height: 1.35;
}
.markmap.${id} .markmap-node[data-depth='1'] .markmap-foreign {
  overflow: visible;
}
.markmap.${id} .markmap-node[data-depth='1'] .markmap-foreign > div {
  width: max-content;
  max-width: var(--markmap-max-width);
  margin: -4px -11px;
  padding: 4px 11px;
  border: 1.5px solid #2563eb;
  border-radius: 999px;
  background: #eff6ff;
  color: #1d4ed8;
  font-weight: 700;
}
`,
}

async function ensureMarkmap(): Promise<Markmap> {
  await nextTick()
  if (!markmap) {
    // 首次挂载时 render() 还会等一个 tick；再让出一帧，避免工具条按钮比图先可用。
    await new Promise<void>((resolve) => {
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(() => resolve())
      } else {
        window.setTimeout(resolve, 0)
      }
    })
  }
  if (!markmap) throw new Error('思维导图尚未渲染完成，请稍后重试')
  return markmap
}

async function render() {
  if (!svgEl.value) return
  await nextTick()
  branchColors = new Map()
  branchSequence = 0
  try {
    if (!markmap) {
      markmap = new Markmap(svgEl.value, OPTIONS)
      await markmap.setData(toPureNode(props.node))
    } else {
      await markmap.setData(toPureNode(props.node), OPTIONS)
    }
    await markmap.fit()
    applyNodeColors()
  } catch (error) {
    console.error('思维导图渲染失败', error)
  }
}

async function fit(): Promise<void> {
  const instance = await ensureMarkmap()
  await instance.fit()
}

function unfoldAll(node: FoldableNode) {
  if (node.payload) {
    node.payload.fold = 0
  } else {
    node.payload = { fold: 0 }
  }
  node.children?.forEach(unfoldAll)
}

async function expandAll(): Promise<void> {
  const instance = await ensureMarkmap()
  const root = instance.state.data as unknown as FoldableNode | undefined
  if (!root) return
  unfoldAll(root)
  await instance.renderData()
  await instance.fit()
  applyNodeColors()
}

function showExportNotice(message: string) {
  exportNotice.value = message
  if (exportNoticeTimer !== undefined) window.clearTimeout(exportNoticeTimer)
  exportNoticeTimer = window.setTimeout(() => {
    exportNotice.value = ''
    exportNoticeTimer = undefined
  }, 6500)
}

function waitForFonts(): Promise<void> {
  if (typeof document === 'undefined' || !document.fonts?.ready) return Promise.resolve()
  return document.fonts.ready.then(
    () => undefined,
    () => undefined,
  )
}

function nextFrame(): Promise<void> {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()))
}

async function measureContent(): Promise<ExportBounds> {
  await waitForFonts()
  await nextTick()
  const instance = await ensureMarkmap()
  const content = instance.g.node()
  if (!content) throw new Error('无法读取思维导图内容')
  // 等待 foreignObject 文案排版完成，getBBox 才是最终尺寸。
  await nextFrame()
  const bbox = content.getBBox()
  if (!Number.isFinite(bbox.width) || !Number.isFinite(bbox.height)) {
    throw new Error('无法计算思维导图尺寸')
  }
  return {
    x: bbox.x - EXPORT_PADDING,
    y: bbox.y - EXPORT_PADDING,
    width: Math.max(1, Math.ceil(bbox.width + EXPORT_PADDING * 2)),
    height: Math.max(1, Math.ceil(bbox.height + EXPORT_PADDING * 2)),
  }
}

function buildExportSvg(
  bounds: ExportBounds,
  scale: number,
): { content: string; width: number; height: number } {
  const source = svgEl.value
  if (!source) throw new Error('思维导图尚未渲染完成')

  const clone = source.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  clone.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink')
  // d3 zoom 的 transform 由 markmap 写在内容 <g> 上；根 <svg> 若也被外部加上
  // transform/CSS transform，导出时应回到逻辑坐标，不能把当前视口缩放带进图片。
  clone.removeAttribute('transform')
  clone.style.transform = ''
  clone.setAttribute('viewBox', `${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`)

  const width = Math.max(1, Math.floor(bounds.width * scale))
  const height = Math.max(1, Math.floor(bounds.height * scale))
  clone.setAttribute('width', String(width))
  clone.setAttribute('height', String(height))

  // d3 zoom 会把当前视口缩放写在最外层内容 <g> 上；导出应该只保留图本身的逻辑尺寸。
  Array.from(clone.children).forEach((child) => {
    if (child.tagName.toLowerCase() === 'g') child.removeAttribute('transform')
  })
  clone.querySelectorAll('.markmap-highlight').forEach((node) => node.remove())
  // 交互用的折叠圆点不应出现在静态图里。
  clone.querySelectorAll('.markmap-node > circle').forEach((node) => node.remove())

  // XMLSerializer 不会替 foreignObject 中的 HTML 自动补默认命名空间。
  clone.querySelectorAll('foreignObject').forEach((foreign) => {
    Array.from(foreign.children).forEach((child) => {
      child.setAttribute('xmlns', 'http://www.w3.org/1999/xhtml')
    })
  })

  const serialized = new XMLSerializer().serializeToString(clone)
  return {
    content: `<?xml version="1.0" encoding="UTF-8"?>\n${serialized}`,
    width,
    height,
  }
}

async function exportSvgString(): Promise<ExportSvg> {
  const bounds = await measureContent()
  return buildExportSvg(bounds, 1)
}

function encodeSvgDataUrl(content: string): string {
  const bytes = new TextEncoder().encode(content)
  let binary = ''
  const chunkSize = 0x8000
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    const chunk = bytes.subarray(offset, offset + chunkSize)
    for (let index = 0; index < chunk.length; index += 1) {
      binary += String.fromCharCode(chunk[index])
    }
  }
  return `data:image/svg+xml;base64,${btoa(binary)}`
}

async function decodeImage(source: string): Promise<HTMLImageElement> {
  const image = new Image()
  image.src = source
  if (typeof image.decode === 'function') {
    try {
      await image.decode()
      return image
    } catch {
      if (image.complete && image.naturalWidth > 0) return image
      throw new Error('无法解码导出的图像，请改用 SVG')
    }
  }
  await new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('无法加载导出的图像，请改用 SVG'))
  })
  return image
}

function canvasToPng(canvas: HTMLCanvasElement): Promise<Blob> {
  return new Promise((resolve, reject) => {
    try {
      canvas.toBlob((blob) => {
        if (blob) {
          resolve(blob)
        } else {
          reject(new Error('PNG 编码失败，请改用 SVG'))
        }
      }, 'image/png')
    } catch {
      reject(new Error('PNG 编码失败，请改用 SVG'))
    }
  })
}

async function exportPng(scale: 2 | 3): Promise<Blob> {
  if (scale !== 2 && scale !== 3) throw new Error('不支持的导出倍率')
  const bounds = await measureContent()

  let effectiveScale: number = scale
  const maxScale = Math.min(MAX_CANVAS_SIDE / bounds.width, MAX_CANVAS_SIDE / bounds.height)
  if (effectiveScale > maxScale) {
    effectiveScale = maxScale
    const message = `图片单边超过 ${MAX_CANVAS_SIDE}px 上限，已自动降至 ${effectiveScale.toFixed(2)}x 导出`
    showExportNotice(message)
    console.warn(message)
  }

  const svg = buildExportSvg(bounds, effectiveScale)
  const image = await decodeImage(encodeSvgDataUrl(svg.content))
  const canvas = document.createElement('canvas')
  canvas.width = svg.width
  canvas.height = svg.height
  const context = canvas.getContext('2d')
  if (!context) throw new Error('当前浏览器不支持 Canvas 导出，请改用 SVG')

  context.fillStyle = '#ffffff'
  context.fillRect(0, 0, canvas.width, canvas.height)
  try {
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
  } catch {
    throw new Error('Canvas 绘制失败，请改用 SVG')
  }
  return canvasToPng(canvas)
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
  if (exportNoticeTimer !== undefined) {
    window.clearTimeout(exportNoticeTimer)
    exportNoticeTimer = undefined
  }
  markmap?.destroy()
  markmap = null
})

defineExpose({ fit, expandAll, exportPng, exportSvgString })
</script>

<template>
  <div ref="shellEl" class="relative w-full" :style="{ height: props.height }">
    <div class="pointer-events-none absolute right-2 top-2 z-10 rounded-full bg-white/85 px-2.5 py-1 text-[10px] text-ink-400 shadow-sm">
      滚轮缩放 · 拖拽移动 · 点击圆点展开/收起
    </div>
    <div
      v-if="exportNotice"
      class="pointer-events-none absolute bottom-2 left-2 right-2 z-20 rounded-lg border border-amber-200 bg-amber-50/95 px-3 py-2 text-[11px] leading-relaxed text-amber-800 shadow-sm"
      role="status"
    >
      {{ exportNotice }}
    </div>
    <svg
      ref="svgEl"
      class="block h-full w-full rounded-lg bg-white"
      role="img"
      aria-label="视频思维导图"
    />
  </div>
</template>
