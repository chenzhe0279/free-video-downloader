<script setup lang="ts">
import BrandMark from './BrandMark.vue'
</script>

<template>
  <footer class="border-t border-slate-200/70 bg-white/70 backdrop-blur-md">
    <div class="mx-auto max-w-6xl px-4 py-12 sm:px-6">
      <div class="grid grid-cols-1 gap-12 md:grid-cols-3">
        <div>
          <div class="flex items-center gap-2.5 mb-4">
            <span class="grid h-8 w-8 place-items-center rounded-xl bg-gradient-to-br from-brand-500 to-violet-500">
              <BrandMark class="h-5 w-5 text-white" />
            </span>
            <span class="text-sm font-bold text-ink-900">ClipNest</span>
          </div>
          <p class="text-sm text-ink-500 leading-relaxed">
            一个轻量级的网页端视频下载工具，基于 yt-dlp 支持上千个视频平台解析，无需安装任何客户端。
          </p>
        </div>

        <div>
          <h4 class="text-sm font-semibold text-ink-900 uppercase tracking-wider">快速链接</h4>
          <ul class="mt-4 space-y-2.5">
            <li><a href="#top" class="text-sm text-ink-500 hover:text-brand-600 transition">首页</a></li>
            <li><a href="#platforms" class="text-sm text-ink-500 hover:text-brand-600 transition">支持平台</a></li>
            <li><a href="#pricing" class="text-sm text-ink-500 hover:text-brand-600 transition">会员权益</a></li>
            <li><a href="#faq" class="text-sm text-ink-500 hover:text-brand-600 transition">常见问题</a></li>
          </ul>
        </div>

        <div>
          <h4 class="text-sm font-semibold text-ink-900 uppercase tracking-wider">合规提示</h4>
          <ul class="mt-4 space-y-2.5 text-sm text-ink-500 leading-relaxed">
            <li>仅用于学习与个人技术研究</li>
            <li>请尊重各平台版权与服务条款</li>
            <li>不下载、传播未经授权的内容</li>
            <li>不代用户登录，不存储账号 Cookie</li>
          </ul>
        </div>
      </div>

      <div class="mt-12 pt-8 border-t border-slate-100/50 text-center">
        <p class="text-xs text-ink-400">
          © 2026 ClipNest · 内容更新于 2026-11-14 · 本项目用于学习交流，不为盈利提供下载服务
        </p>
      </div>
    </div>
  </footer>
</template>
