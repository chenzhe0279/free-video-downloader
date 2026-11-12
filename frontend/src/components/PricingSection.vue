<template>
  <section id="pricing" class="mt-16 relative overflow-hidden pt-12 pb-20">
    <div class="absolute inset-0 -z-10">
      <div class="absolute top-[-10%] left-[-10%] h-96 w-96 bg-brand-200/40 rounded-full blur-[100px]" />
      <div class="absolute bottom-[-10%] right-[-10%] h-96 w-96 bg-accent-200/40 rounded-full blur-[100px]" />
    </div>

    <div class="mx-auto max-w-2xl px-4 sm:px-6 text-center">
      <p class="text-sm font-semibold text-brand-700 tracking-wider uppercase">会员权益</p>
      <h2 class="mt-2 text-3xl font-bold tracking-tight text-ink-900 text-balance">
        解锁 <span class="text-gradient">更高清的体验</span>
      </h2>
      <p class="mt-4 text-lg text-ink-500">
        高清原片、批量下载、优先下载通道，支持字幕与音频导出。
      </p>
    </div>

    <div class="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
      <ul class="grid grid-cols-1 gap-6 mt-12 md:grid-cols-3 lg:gap-8">
        <li class="card p-7 flex flex-col gap-5 text-center">
          <div class="flex flex-col gap-1">
            <span class="text-sm font-semibold text-ink-500 uppercase tracking-wide">免费体验</span>
            <span class="text-[32px] font-extrabold tracking-tight text-ink-900">¥0</span>
          </div>
          <p class="text-xs leading-relaxed text-ink-400">适合偶尔使用</p>
          <ul class="space-y-3 text-sm text-ink-600">
            <li class="flex items-center gap-2 text-sm">
              <svg class="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              单次下载，文件保留 1 小时
            </li>
            <li class="flex items-center gap-2 text-sm">
              <svg class="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              最高支持 720P 画质
            </li>
            <li class="flex items-center gap-2 text-sm">
              <svg class="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              直链下载，不占服务器空间
            </li>
          </ul>
          <button type="button" class="w-full btn-outline rounded-lg py-3 text-sm font-semibold text-ink-700">
            立即体验
          </button>
        </li>

        <li class="card p-7 flex flex-col gap-5 relative border-2 border-brand-500 bg-brand-50 shadow-[0_20px_40px_-10px_rgba(37,99,235,0.25)]">
          <div class="absolute -top-3 left-1/2 -translate-x-1/2">
            <span class="rounded-full bg-brand-600 px-2.5 py-0.5 text-[10px] font-bold text-white uppercase">最受欢迎</span>
          </div>
          <div class="flex flex-col gap-1">
            <span class="text-sm font-semibold text-brand-700 uppercase tracking-wide">月卡会员</span>
            <span class="text-[32px] font-extrabold tracking-tight text-ink-900">¥19<span class="text-sm font-semibold text-ink-500">/月</span></span>
          </div>
          <p class="text-xs leading-relaxed text-ink-400">适合高频下载用户</p>
          <ul class="space-y-3 text-sm text-ink-600">
            <li class="flex items-center gap-2 text-sm">
              <svg class="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              不限下载次数
            </li>
            <li class="flex items-center gap-2 text-sm">
              <svg class="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              最高 4K 原片下载
            </li>
            <li class="flex items-center gap-2 text-sm">
              <svg class="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              优先下载通道，免排队
            </li>
            <li class="flex items-center gap-2 text-sm">
              <svg class="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              批量 playlist 一键下载
            </li>
          </ul>
          <button type="button" class="w-full vip-cta rounded-lg py-3 text-sm font-semibold">
            开通月卡
          </button>
        </li>

        <li class="card p-7 flex flex-col gap-5 text-center">
          <div class="flex flex-col gap-1">
            <span class="text-sm font-semibold text-accent-600 uppercase tracking-wide">年卡会员</span>
            <span class="text-[32px] font-extrabold tracking-tight text-ink-900">¥149<span class="text-sm font-semibold text-ink-500">/年</span></span>
            <span class="text-xs font-semibold text-accent-500">省 ¥79（相当 ¥12.4/月）</span>
          </div>
          <p class="text-xs leading-relaxed text-ink-400">适合重度内容消费者</p>
          <ul class="space-y-3 text-sm text-ink-600">
            <li class="flex items-center gap-2 text-sm">
              <svg class="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              月卡全部权益
            </li>
            <li class="flex items-center gap-2 text-sm">
              <svg class="h-4 w-4 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              优先响应的技术支持
            </li>
            <li class="flex items-center gap-2 text-sm text-ink-400">
              <svg class="h-4 w-4 text-ink-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
              视频总结、字幕翻译（近期推出）
            </li>
          </ul>
          <button type="button" class="w-full btn-outline rounded-lg py-3 text-sm font-semibold text-ink-700">
            开通年卡
          </button>
        </li>
      </ul>

      <p class="mt-6 text-xs text-ink-300">
        会员功能为后续规划，当前版本全部免费体验，付费能力将在后续版本开放。
      </p>
    </div>
  </section>
</template>
