<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  name: 'summary' | 'chapters' | 'transcript' | 'mindmap' | 'qa'
}>()

// 与参考截图保持一致：📝 总结、📄 字幕文本、🧠 思维导图、💬 AI 问答
const ICONS = {
  summary: '📝',
  chapters: '📑',
  transcript: '📄',
  mindmap: '🧠',
  qa: '💬',
} as const

const emoji = computed(() => ICONS[props.name])
</script>

<template>
  <span aria-hidden="true" class="inline-flex shrink-0 items-center justify-center leading-none">{{ emoji }}</span>
</template>
