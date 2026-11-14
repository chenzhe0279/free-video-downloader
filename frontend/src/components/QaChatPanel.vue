<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref } from 'vue'
import {
  streamSummaryAnswer,
  type QaErrorEvent,
  type QaHistoryMessage,
  type QaPhase,
  type QaRefusalEvent,
  type QaTokenEvent,
  type QaStatusEvent,
} from '../api/client'

const props = defineProps<{
  taskId: string
  suggestions: string[]
  dailyLimit: number
  maxLength: number
}>()

const emit = defineEmits<{
  (e: 'regenerate'): void
}>()

type Role = 'user' | 'assistant'

interface ChatMessage {
  id: string
  role: Role
  content: string
  streaming?: boolean
  refusal?: boolean
  stopped?: boolean
  error?: boolean
  errorText?: string
  suggestions?: string[]
}

const messages = ref<ChatMessage[]>([])
const input = ref('')
const streaming = ref(false)
const phase = ref<QaPhase | 'idle'>('idle')
const expired = ref(false)
const scrollRef = ref<HTMLElement | null>(null)
let controller: AbortController | null = null
let nextId = 0

const canSend = computed(
  () => Boolean(input.value.trim()) && !streaming.value && !expired.value,
)
const phaseText = computed(() =>
  phase.value === 'checking'
    ? '正在判断问题是否与视频相关…'
    : phase.value === 'answering'
      ? '正在生成回答…'
      : '',
)
const limitText = computed(() =>
  props.dailyLimit > 0 ? `每日 ${props.dailyLimit} 次` : '不限次数',
)
const charCount = computed(() => input.value.length)

function id(): string {
  nextId += 1
  return `qa-${nextId}`
}

function scrollToBottom() {
  void nextTick(() => {
    const element = scrollRef.value
    if (element) element.scrollTop = element.scrollHeight
  })
}

function buildHistory(): QaHistoryMessage[] {
  const history: QaHistoryMessage[] = []
  for (const message of messages.value) {
    if (message.streaming || message.stopped || message.refusal || message.error) {
      continue
    }
    if (!message.content.trim()) continue
    history.push({
      role: message.role,
      content: message.content.slice(0, 2000),
    })
  }
  return history.slice(-6)
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

function handleEvent(block: string, assistant: ChatMessage): boolean {
  let eventName = 'message'
  let data = ''
  for (const line of block.split('\n')) {
    if (line.startsWith('event:')) {
      eventName = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      data += line.slice(5).trim()
    }
  }
  if (!data) return false

  let payload: unknown
  try {
    payload = JSON.parse(data)
  } catch {
    return false
  }

  if (eventName === 'status') {
    const status = payload as QaStatusEvent
    if (status.phase === 'checking' || status.phase === 'answering') {
      phase.value = status.phase
    }
    return false
  }
  if (eventName === 'token') {
    const token = payload as QaTokenEvent
    assistant.content += token.text || ''
    scrollToBottom()
    return false
  }
  if (eventName === 'refusal') {
    const refusal = payload as QaRefusalEvent
    assistant.content = refusal.message || ''
    assistant.refusal = true
    assistant.suggestions = Array.isArray(refusal.suggestions)
      ? refusal.suggestions
      : []
    assistant.streaming = false
    return true
  }
  if (eventName === 'error') {
    const error = payload as QaErrorEvent
    assistant.error = true
    assistant.errorText = error.message || '问答失败，请稍后重试'
    assistant.streaming = false
    return true
  }
  if (eventName === 'done') {
    assistant.streaming = false
    return true
  }
  return false
}

async function readStream(response: Response, assistant: ChatMessage) {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('当前浏览器不支持流式读取')
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const block = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        if (handleEvent(block, assistant)) {
          await reader.cancel().catch(() => {})
          return
        }
        boundary = buffer.indexOf('\n\n')
      }
    }
    buffer += decoder.decode()
    if (buffer.trim()) handleEvent(buffer, assistant)
  } finally {
    try {
      reader.releaseLock()
    } catch {
      /* reader 已被取消时释放可能抛错，忽略即可 */
    }
  }
}

async function send(question?: string) {
  if (streaming.value || expired.value) return
  const text = (question ?? input.value).trim()
  if (!text) return
  if (text.length > props.maxLength) {
    input.value = text.slice(0, props.maxLength)
    return
  }

  const history = buildHistory()
  input.value = ''
  const userMessage: ChatMessage = { id: id(), role: 'user', content: text }
  const assistant = reactive<ChatMessage>({
    id: id(),
    role: 'assistant',
    content: '',
    streaming: true,
  })
  messages.value.push(userMessage, assistant)
  streaming.value = true
  phase.value = 'checking'
  controller = new AbortController()
  scrollToBottom()

  try {
    const response = await streamSummaryAnswer(
      props.taskId,
      { question: text, history },
      controller.signal,
    )
    await readStream(response, assistant)
    if (
      !assistant.content &&
      !assistant.refusal &&
      !assistant.error &&
      !assistant.stopped
    ) {
      assistant.error = true
      assistant.errorText = '没有收到有效回答，请重试'
    }
  } catch (error) {
    if (isAbortError(error)) {
      assistant.stopped = true
      if (!assistant.content) assistant.content = '已停止生成。'
    } else {
      const message = error instanceof Error ? error.message : '问答失败，请稍后重试'
      assistant.error = true
      assistant.errorText = message
      if (message.includes('过期') || message.includes('不存在')) {
        expired.value = true
      }
    }
  } finally {
    assistant.streaming = false
    streaming.value = false
    phase.value = 'idle'
    controller = null
    scrollToBottom()
  }
}

function stop() {
  controller?.abort()
}

function onKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey) return
  if (event.isComposing) return
  event.preventDefault()
  void send()
}

function requestRegenerate() {
  emit('regenerate')
}

onBeforeUnmount(() => {
  controller?.abort()
})
</script>

<template>
  <div class="space-y-3">
    <div class="rounded-xl border border-violet-100 bg-violet-50/60 px-3 py-2 text-[11px] leading-relaxed text-violet-700">
      只基于当前视频的 AI 总结回答；与视频无关的问题会被拒答，总结没覆盖的细节会回复“材料中没有提到”。
    </div>

    <div ref="scrollRef" class="max-h-[26rem] space-y-3 overflow-y-auto pr-1">
      <div v-if="!messages.length" class="rounded-xl border border-dashed border-slate-200 bg-white px-4 py-5">
        <p class="text-sm font-semibold text-ink-900">针对这个视频提问</p>
        <p class="mt-1 text-xs leading-relaxed text-ink-500">
          可以问大纲、章节、核心观点、概念含义；也可以先点下面的推荐问题。
        </p>
        <div class="mt-3 flex flex-wrap gap-1.5">
          <button
            v-for="suggestion in suggestions"
            :key="suggestion"
            type="button"
            class="rounded-full border border-violet-200 bg-white px-2.5 py-1 text-[11px] text-violet-700 transition hover:bg-violet-50"
            @click="send(suggestion)"
          >
            {{ suggestion }}
          </button>
        </div>
      </div>

      <div
        v-for="message in messages"
        :key="message.id"
        class="flex"
        :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
      >
        <div
          class="max-w-[85%] rounded-2xl border px-3.5 py-2.5 text-sm leading-relaxed"
          :class="
            message.role === 'user'
              ? 'border-brand-600 bg-brand-600 text-white'
              : message.refusal
                ? 'border-amber-200 bg-amber-50 text-amber-900'
                : message.error
                  ? 'border-red-200 bg-red-50 text-red-700'
                  : 'border-slate-200 bg-white text-ink-700'
          "
        >
          <p
            v-if="message.role === 'assistant' && message.streaming && !message.content"
            class="text-xs text-violet-600"
          >
            {{ phaseText || '正在准备回答…' }}
          </p>

          <p v-if="message.content" class="whitespace-pre-wrap break-words">
            {{ message.content }}<span
              v-if="message.streaming"
              class="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-violet-500 align-middle"
            />
          </p>

          <p v-if="message.stopped" class="mt-1 text-[11px] opacity-70">
            已停止生成，可继续提问。
          </p>
          <p v-if="message.error && message.errorText" class="mt-1 text-[11px]">
            {{ message.errorText }}
          </p>

          <div
            v-if="message.suggestions?.length"
            class="mt-2 flex flex-wrap gap-1.5 border-t border-amber-200/70 pt-2"
          >
            <button
              v-for="suggestion in message.suggestions"
              :key="suggestion"
              type="button"
              class="rounded-full border border-amber-300 bg-white px-2 py-0.5 text-[10px] text-amber-800 hover:bg-amber-50"
              @click="send(suggestion)"
            >
              {{ suggestion }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="expired" class="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
      当前总结任务已过期，需要重新生成总结后再提问。
      <button type="button" class="ml-1 font-semibold underline" @click="requestRegenerate">
        重新生成总结
      </button>
    </div>

    <div class="rounded-xl border border-slate-200 bg-white p-2">
      <textarea
        v-model="input"
        rows="2"
        :maxlength="maxLength"
        :disabled="streaming || expired"
        placeholder="问一个与当前视频相关的问题，例如：这个视频的核心观点是什么？"
        class="block w-full resize-none rounded-lg border-0 bg-transparent px-2 py-1.5 text-sm text-ink-900 placeholder:text-ink-400 focus:outline-none disabled:opacity-60"
        @keydown="onKeydown"
      />
      <div class="mt-1 flex items-center justify-between gap-2 px-1">
        <span class="text-[10px] text-ink-400">
          {{ charCount }}/{{ maxLength }} · {{ limitText }}
        </span>
        <div class="flex items-center gap-2">
          <button
            v-if="streaming"
            type="button"
            class="rounded-full border border-red-200 bg-red-50 px-3 py-1.5 text-xs font-semibold text-red-600 hover:bg-red-100"
            @click="stop"
          >
            停止
          </button>
          <button
            v-else
            type="button"
            class="btn-primary px-4 py-1.5 text-xs"
            :disabled="!canSend"
            @click="send()"
          >
            发送
          </button>
        </div>
      </div>
    </div>

    <p class="text-[11px] leading-relaxed text-ink-400">
      回答仅基于当前 AI 总结，可能不完整；请结合原视频核对。Enter 发送，Shift+Enter 换行。
    </p>
  </div>
</template>
