<script setup lang="ts">
import { displayDate, useMembership } from '../membership'

const { account, pending, checkout, show } = useMembership()
const plans = [
  { id: 'month', name: '月卡会员', price: 19, duration: 30 },
  { id: 'year', name: '年卡会员', price: 149, duration: 365 },
] as const
</script>

<template>
  <section id="pricing" class="studio-pricing">
    <div class="studio-pricing__intro">
      <h2>会员权益</h2>
      <p>会员每天可新建 20 次 AI 视频总结，北京时间零点重置。</p>
    </div>
    <ul class="studio-pricing__cards">
      <li class="studio-plan">
        <h3>免费体验</h3>
        <p class="studio-plan__price">¥0</p>
        <p class="studio-plan__description">视频下载和预览，AI 总结默认每 IP 每天 3 次。</p>
        <a href="#download" class="studio-plan__button">立即体验 <span aria-hidden="true">↗</span></a>
      </li>
      <li v-for="plan in plans" :key="plan.id" class="studio-plan"
        :class="{ 'studio-plan--featured': plan.id === 'year' }">
        <h3>{{ plan.name }}</h3>
        <p class="studio-plan__price">
          ¥{{ plan.price }} <span>/ {{ plan.duration }} 天</span>
        </p>
        <p class="studio-plan__description">每个账号每天 20 次 AI 总结，命中缓存免扣额度。</p>
        <button v-if="account.membership" type="button" class="studio-plan__button"
          @click="show('account')">查看会员</button>
        <button v-else type="button" class="studio-plan__button"
          :disabled="!account.checkout_enabled || pending" @click="checkout(plan.id)">
          {{ !account.checkout_enabled ? '暂未开放购买' : plan.id === 'month' ? '开通月卡' : '开通年卡' }}
        </button>
      </li>
    </ul>
    <p v-if="account.membership?.expires_at" class="studio-pricing__status" role="status">
      会员有效至 {{ displayDate(account.membership.expires_at) }}，今日剩余 {{ account.quota?.remaining }} 次。
    </p>
    <p v-else class="studio-pricing__status">银行卡一次性付款，到期后可自行续买。</p>
  </section>
</template>
