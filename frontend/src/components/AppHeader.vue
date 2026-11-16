<script setup lang="ts">
import BrandMark from './BrandMark.vue'
import { useMembership } from '../membership'

const { account, show } = useMembership()

const navs = [
  { label: '首页', href: '#top' },
  { label: '支持平台', href: '#platforms' },
  { label: '会员权益', href: '#pricing' },
  { label: '常见问题', href: '#faq' },
]
</script>

<template>
  <header class="studio-header sticky top-0 z-40">
    <div class="mx-auto flex h-16 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
      <a href="#top" class="flex items-center gap-2.5">
        <span class="studio-header__mark">
          <BrandMark class="h-6 w-6" />
        </span>
        <span class="studio-header__name">ClipNest</span>
      </a>

      <nav class="hidden items-center gap-1 md:flex">
        <a
          v-for="item in navs"
          :key="item.href"
          :href="item.href"
          class="studio-header__link"
        >
          {{ item.label }}
        </a>
      </nav>

      <div class="flex items-center gap-2">
        <button
          v-if="account.enabled"
          type="button"
          class="studio-header__link"
          @click="show(account.user ? 'account' : 'login')"
        >
          {{ account.user ? '我的会员' : '登录' }}
        </button>
        <a href="#pricing" class="studio-header__pro" aria-label="升级 Pro，查看会员权益">升级 Pro <span aria-hidden="true">↗</span></a>
      </div>
    </div>
  </header>
</template>
