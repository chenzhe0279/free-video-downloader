<script setup lang="ts">
const navs = [
  { label: '首页', href: '#top' },
  { label: '支持平台', href: '#platforms' },
  { label: '会员权益', href: '#pricing' },
  { label: '常见问题', href: '#faq' },
]
</script>

<template>
  <header class="sticky top-0 z-40 glass">
    <div class="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
      <a href="#top" class="flex items-center gap-2.5">
        <span class="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-violet-500 shadow-lift">
          <svg viewBox="0 0 24 24" class="h-5 w-5 text-white" fill="currentColor">
            <path d="M8 5.5v13l11-6.5z" />
          </svg>
        </span>
        <span class="flex items-baseline gap-1.5">
          <span class="text-[15px] font-bold tracking-tight text-ink-900">万能视频下载站</span>
          <span class="rounded bg-brand-50 px-1.5 py-0.5 text-[10px] font-bold uppercase text-brand-600">Beta</span>
        </span>
      </a>

      <nav class="hidden items-center gap-1 md:flex">
        <a
          v-for="item in navs"
          :key="item.href"
          :href="item.href"
          class="rounded-full px-3.5 py-2 text-sm font-medium text-ink-600 transition hover:bg-white hover:text-brand-600"
        >
          {{ item.label }}
        </a>
      </nav>

      <div class="flex items-center gap-2">
        <button
          type="button"
          class="hidden text-sm font-medium text-ink-600 transition hover:text-brand-600 sm:block"
        >
          登录
        </button>
        <a href="#pricing" class="pro-cta" aria-label="升级 Pro，查看会员权益">升级 Pro</a>
      </div>
    </div>
  </header>
</template>
