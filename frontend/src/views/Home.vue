<script setup lang="ts">
import { ref, onBeforeUnmount, onMounted } from 'vue'
import { api, type ProbeResult, type TaskStatus } from '../api/client'
import { suggestFilename } from '../utils/format'
import ResultPanel from '../components/ResultPanel.vue'
import TaskProgress from '../components/TaskProgress.vue'
import PricingSection from '../components/PricingSection.vue'

const url = ref('')
const loading = ref(false)
const errorMsg = ref('')
const noticeMsg = ref('')
const result = ref<ProbeResult | null>(null)
const selectedId = ref('')
const busyOption = ref('')
const task = ref<TaskStatus | null>(null)
const taskTitle = ref('')

let pollTimer: number | undefined

const platforms = [
  'YouTube',
  'Bilibili',
  '抖音',
  'TikTok',
  '小红书',
  'Instagram',
  'X / Twitter',
  'Vimeo',
  '快手',
  '视频号',
]

const features = [
  {
    icon: '🌐',
    title: '千站通吃',
    desc: '基于 yt-dlp 的站点解析能力，主流平台与长尾站点一并覆盖。',
  },
  {
    icon: '⚡',
    title: '双通道下载',
    desc: '直链加速不占服务器空间，服务端转存兼容受限格式，随时切换。',
  },
  {
    icon: '🎞️',
    title: '最高 4K 原片',
    desc: '音视频分离再合并，自动挑选最佳编码，画质不打折。',
  },
  {
    icon: '📱',
    title: '手机即用',
    desc: '响应式界面，手机浏览器打开就能下，无需安装任何 App。',
  },
]

const steps = [
  { no: '01', title: '粘贴视频链接', desc: '复制视频页面地址，粘贴到搜索框。' },
  { no: '02', title: '选择清晰度', desc: '查看真实可用的画质与格式，按需挑选。' },
  { no: '03', title: '一键保存', desc: '直链秒下，或交给服务器转存后取回。' },
]

const faqs = [
  {
    q: '为什么有些视频解析失败？',
    a: '常见原因包括：平台要求登录、地区限制、链接已失效，或该站点暂未被解析引擎支持。可以换一个清晰度选项或稍后重试。',
  },
  {
    q: '直链下载提示 403 / 无法下载怎么办？',
    a: '部分平台带防盗链校验，直链会拒绝浏览器直接访问。此时改用「代理加速」或「服务端转存」即可绕过，服务端会补全 Referer 等请求头。',
  },
  {
    q: '下载的文件能保存多久？',
    a: '服务端转存的文件默认保留 1 小时，到期自动清理，请及时保存到本地。直链本身通常有数小时有效期。',
  },
  {
    q: '使用本站会封号吗？',
    a: '本站不需要登录你的平台账号，也不会替你发请求到已登录的会话，因此不会直接影响账号。请遵守各平台规则，仅下载你有权使用的内容。',
  },
]

function stopPolling() {
  if (pollTimer !== undefined) {
    window.clearTimeout(pollTimer)
    pollTimer = undefined
  }
}

function errorText(err: unknown): string {
  return err instanceof Error ? err.message : '操作失败，请稍后重试'
}

async function analyze() {
  const target = url.value.trim()
  if (!target) {
    errorMsg.value = '请先粘贴视频链接'
    return
  }
  stopPolling()
  loading.value = true
  errorMsg.value = ''
  noticeMsg.value = ''
  result.value = null
  task.value = null
  try {
    const data = await api.probe(target)
    result.value = data
    selectedId.value = data.options[0]?.id ?? ''
  } catch (err) {
    errorMsg.value = errorText(err)
  } finally {
    loading.value = false
  }
}

function pollTask(taskId: string) {
  stopPolling()
  const tick = async () => {
    try {
      const data = await api.task(taskId)
      task.value = data
      if (data.status === 'finished' || data.status === 'error') {
        stopPolling()
        return
      }
    } catch {
      /* transient network error: keep polling */
    }
    pollTimer = window.setTimeout(tick, 1200)
  }
  void tick()
}

async function startServer(optionId: string) {
  if (!result.value) return
  busyOption.value = optionId
  errorMsg.value = ''
  noticeMsg.value = ''
  task.value = null
  try {
    const res = await api.download(result.value.url, optionId, 'server')
    if (!res.task_id) throw new Error('任务创建失败')
    const opt = result.value.options.find((o) => o.id === optionId)
    taskTitle.value = `${result.value.title} · ${opt?.label ?? optionId}`
    pollTask(res.task_id)
  } catch (err) {
    errorMsg.value = errorText(err)
  } finally {
    busyOption.value = ''
  }
}

function triggerDownload(href: string, filename: string, newTab = false) {
  const anchor = document.createElement('a')
  anchor.href = href
  anchor.download = filename
  if (newTab) {
    anchor.target = '_blank'
    anchor.rel = 'noopener'
  }
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
}

async function directDownload(optionId: string) {
  if (!result.value) return
  busyOption.value = optionId
  errorMsg.value = ''
  noticeMsg.value = ''
  try {
    const res = await api.download(result.value.url, optionId, 'direct')
    if (!res.url) throw new Error('未获取到直链')
    const opt = result.value.options.find((o) => o.id === optionId)
    triggerDownload(res.url, suggestFilename(result.value.title, opt?.ext), true)
    noticeMsg.value = '已尝试在浏览器中打开直链。若无反应或提示 403，请改用「代理加速」或「服务端转存」。'
  } catch (err) {
    errorMsg.value = errorText(err)
  } finally {
    busyOption.value = ''
  }
}

async function proxyDownload(optionId: string) {
  if (!result.value) return
  busyOption.value = optionId
  errorMsg.value = ''
  noticeMsg.value = ''
  try {
    const res = await api.download(result.value.url, optionId, 'proxy')
    if (!res.proxy_url) throw new Error('未获取到代理链接')
    const opt = result.value.options.find((o) => o.id === optionId)
    triggerDownload(res.proxy_url, suggestFilename(result.value.title, opt?.ext))
    noticeMsg.value = '代理下载已开始，大文件请耐心等待浏览器写入磁盘。'
  } catch (err) {
    errorMsg.value = errorText(err)
  } finally {
    busyOption.value = ''
  }
}

async function cancelTask(taskId: string) {
  stopPolling()
  try {
    await api.removeTask(taskId)
  } catch {
    /* task may already be gone */
  }
  task.value = null
  noticeMsg.value = '已取消下载任务'
}

onMounted(() => {
  const shared = new URLSearchParams(window.location.search).get('url')
  if (shared) {
    url.value = shared
    void analyze()
  }
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <div id="top">
    <!-- Hero -->
    <section class="relative overflow-hidden pb-10 pt-14 sm:pt-20">
      <div class="pointer-events-none absolute inset-0 -z-10">
        <div class="absolute left-1/2 top-[-14rem] h-[28rem] w-[42rem] -translate-x-1/2 rounded-full bg-brand-200/40 blur-[120px]" />
        <div class="absolute right-[-8rem] top-24 h-72 w-72 rounded-full bg-violet-200/40 blur-[100px]" />
      </div>

      <div class="mx-auto max-w-3xl px-4 text-center sm:px-6">
        <span class="inline-flex items-center gap-2 rounded-full border border-brand-100 bg-white/80 px-3.5 py-1.5 text-xs font-medium text-brand-700 shadow-soft">
          <span class="relative flex h-2 w-2">
            <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span class="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
          支持上千个平台 · 解析服务运行中
        </span>

        <h1 class="mt-6 text-[34px] font-black leading-[1.15] tracking-tight text-ink-900 text-balance sm:text-5xl">
          粘贴链接，<span class="text-gradient">3 秒拿到原片</span>
        </h1>
        <p class="mx-auto mt-4 max-w-xl text-base leading-relaxed text-ink-500 sm:text-lg">
          YouTube、Bilibili、抖音、TikTok 等站点一键解析。直链加速与服务端转存双模式，手机电脑都能用。
        </p>

        <!-- Search -->
        <form id="download" class="mt-8" @submit.prevent="analyze">
          <div class="card flex flex-col gap-2 p-2 sm:flex-row sm:items-center sm:rounded-full">
            <label class="flex flex-1 items-center gap-3 px-3">
              <svg class="h-5 w-5 shrink-0 text-ink-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M17 11a6 6 0 11-12 0 6 6 0 0112 0z" />
              </svg>
              <input
                v-model="url"
                type="text"
                inputmode="url"
                autocomplete="off"
                placeholder="粘贴视频链接，例如 https://www.bilibili.com/video/..."
                class="w-full bg-transparent py-3 text-[15px] text-ink-900 placeholder:text-ink-400 focus:outline-none"
              />
            </label>
            <button type="submit" class="btn-primary rounded-full sm:w-auto" :disabled="loading">
              <svg v-if="loading" class="mr-2 h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.4 0 0 5.4 0 12h4z" />
              </svg>
              {{ loading ? '解析中…' : '开始解析' }}
            </button>
          </div>
        </form>

        <div class="mt-4 min-h-[20px]">
          <p v-if="errorMsg" class="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600" role="alert">
            {{ errorMsg }}
          </p>
          <p v-else-if="noticeMsg" class="rounded-xl bg-brand-50 px-3 py-2 text-sm text-brand-700">
            {{ noticeMsg }}
          </p>
        </div>

        <div class="mt-6 flex flex-wrap items-center justify-center gap-2">
          <span
            v-for="name in platforms"
            :key="name"
            class="chip cursor-default text-xs"
          >
            {{ name }}
          </span>
          <span class="chip cursor-default text-xs text-ink-400">+1800 更多</span>
        </div>

        <dl class="mx-auto mt-8 grid max-w-lg grid-cols-3 divide-x divide-slate-200 rounded-2xl border border-slate-200/70 bg-white/70 py-3 text-center shadow-soft">
          <div>
            <dt class="text-[11px] text-ink-400">已解析</dt>
            <dd class="mt-0.5 text-base font-bold text-ink-900">128,436</dd>
          </div>
          <div>
            <dt class="text-[11px] text-ink-400">平均耗时</dt>
            <dd class="mt-0.5 text-base font-bold text-ink-900">6.2s</dd>
          </div>
          <div>
            <dt class="text-[11px] text-ink-400">直链成功率</dt>
            <dd class="mt-0.5 text-base font-bold text-ink-900">92%</dd>
          </div>
        </dl>
      </div>
    </section>

    <div class="mx-auto max-w-3xl px-4 sm:px-6">
      <ResultPanel
        v-if="result"
        :result="result"
        :selected-id="selectedId"
        :busy-option="busyOption"
        @select="selectedId = $event"
        @server="startServer"
        @direct="directDownload"
        @proxy="proxyDownload"
      />

      <TaskProgress v-if="task" :task="task" :title="taskTitle" @cancel="cancelTask" />
    </div>

    <!-- Features -->
    <section id="platforms" class="mx-auto max-w-6xl px-4 pt-20 sm:px-6">
      <div class="mx-auto max-w-2xl text-center">
        <p class="text-sm font-semibold uppercase tracking-wider text-brand-700">为什么选我们</p>
        <h2 class="mt-2 text-3xl font-bold tracking-tight text-ink-900 text-balance">
          比别人更快一步的<span class="text-gradient">下载体验</span>
        </h2>
      </div>
      <ul class="mt-10 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
        <li
          v-for="item in features"
          :key="item.title"
          class="card p-6 transition hover:-translate-y-0.5 hover:shadow-lift"
        >
          <span class="grid h-11 w-11 place-items-center rounded-xl bg-brand-50 text-xl">{{ item.icon }}</span>
          <h3 class="mt-4 text-base font-bold text-ink-900">{{ item.title }}</h3>
          <p class="mt-2 text-sm leading-relaxed text-ink-500">{{ item.desc }}</p>
        </li>
      </ul>
    </section>

    <!-- Steps -->
    <section class="mx-auto max-w-6xl px-4 pt-20 sm:px-6">
      <ul class="grid grid-cols-1 gap-5 md:grid-cols-3">
        <li v-for="step in steps" :key="step.no" class="card p-6">
          <span class="text-2xl font-black text-brand-200">{{ step.no }}</span>
          <h3 class="mt-2 text-base font-bold text-ink-900">{{ step.title }}</h3>
          <p class="mt-1.5 text-sm text-ink-500">{{ step.desc }}</p>
        </li>
      </ul>
    </section>

    <!-- Pricing -->
    <PricingSection />

    <!-- FAQ -->
    <section id="faq" class="mx-auto max-w-3xl px-4 pb-16 sm:px-6">
      <div class="text-center">
        <p class="text-sm font-semibold uppercase tracking-wider text-brand-700">常见问题</p>
        <h2 class="mt-2 text-3xl font-bold tracking-tight text-ink-900">你可能想知道</h2>
      </div>
      <ul class="mt-8 space-y-3">
        <li v-for="item in faqs" :key="item.q" class="card p-5">
          <details class="group">
            <summary class="flex cursor-pointer items-center justify-between gap-3 text-sm font-semibold text-ink-900 marker:content-none">
              {{ item.q }}
              <span class="text-brand-500 transition group-open:rotate-45">+</span>
            </summary>
            <p class="mt-3 text-sm leading-relaxed text-ink-500">{{ item.a }}</p>
          </details>
        </li>
      </ul>
      <p class="mt-8 text-center text-xs leading-relaxed text-ink-400">
        本站仅用于学习与技术研究，请尊重版权，切勿下载、传播未经授权的内容。
      </p>
    </section>
  </div>
</template>
