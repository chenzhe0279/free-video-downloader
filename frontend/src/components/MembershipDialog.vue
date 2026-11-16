<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { displayDate, isPending, orderStatus, planName, useMembership } from '../membership'

const { account, view, mailToken, pending, error, notice, returnedOrder, show, refresh,
  action, checkout, cancel } = useMembership()
const dialog = ref<HTMLDialogElement>()
const email = ref('')
const password = ref('')
const working = ref(false)
const labels = {
  login: '登录', register: '注册账号', forgot: '找回密码', verify: '验证邮箱',
  reset: '重置密码', account: '我的会员',
}
const needsEmail = computed(() => view.value === 'login' || view.value === 'register' || view.value === 'forgot')
const needsPassword = computed(() => view.value !== 'forgot' && view.value !== 'account')
const orders = computed(() => returnedOrder.value && !account.value.orders.some(order => order.id === returnedOrder.value?.id)
  ? [returnedOrder.value, ...account.value.orders]
  : account.value.orders)

watch(view, (next) => {
  password.value = ''
  if (next && !dialog.value?.open) dialog.value?.showModal()
  if (!next && dialog.value?.open) dialog.value.close()
}, { flush: 'post' })

async function run(task: () => Promise<void>) {
  if (working.value) return
  working.value = true
  error.value = ''
  notice.value = ''
  try {
    await task()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : '操作失败，请重试'
  } finally {
    working.value = false
  }
}

function submit() {
  return run(async () => {
    const credentials = { email: email.value, password: password.value }
    switch (view.value) {
      case 'login':
        await action('login', credentials)
        await refresh()
        show('account')
        break
      case 'register':
        await action('register', credentials)
        show('login')
        notice.value = '若该地址需要验证，系统会发送邮件。请打开邮件链接并输入注册密码。'
        break
      case 'forgot':
        await action('password-reset-email', { email: email.value })
        notice.value = '如果该邮箱已注册，系统会发送密码重置邮件。'
        break
      case 'verify':
      case 'reset': {
        const reset = view.value === 'reset'
        await action(reset ? 'password-reset' : 'verify', { token: mailToken.value, password: password.value })
        mailToken.value = ''
        await refresh()
        show(account.value.user ? 'account' : 'login')
        notice.value = reset ? '密码已重置，请重新登录。' : '邮箱已验证。'
        break
      }
    }
  })
}
</script>

<template>
  <dialog ref="dialog" aria-labelledby="membership-dialog-title"
    class="studio-dialog"
    @cancel.prevent="show(null)">
    <div v-if="view" class="space-y-4">
      <div class="flex items-center justify-between gap-3">
        <h2 id="membership-dialog-title" class="text-xl font-bold">{{ labels[view] }}</h2>
        <button type="button" class="studio-dialog__close" @click="show(null)">关闭</button>
      </div>

      <p v-if="error" role="alert" class="rounded-lg bg-red-50 p-3 text-sm text-red-800">{{ error }}</p>
      <p v-if="notice" role="status" class="rounded-lg bg-brand-50 p-3 text-sm text-brand-800">{{ notice }}</p>

      <template v-if="view === 'account'">
        <p class="break-all text-sm">{{ account.user?.email }}</p>
        <p v-if="account.membership && account.membership.expires_at" class="studio-dialog__benefit">
          {{ planName[account.membership.plan] }}有效至 {{ displayDate(account.membership.expires_at) }}
          <br />今天剩余 {{ account.quota?.remaining }} / {{ account.quota?.limit }} 次 AI 总结
        </p>
        <p v-else class="text-sm text-ink-500">当前没有生效的会员。</p>
        <button v-if="account.user && !account.user.verified" type="button" class="btn-outline px-3 py-2 text-sm"
          :disabled="working" @click="run(async () => {
            if (!account.user) return
            await action('verification-email', { email: account.user.email })
            notice = '请在邮箱查收验证链接。'
          })">发送验证邮件</button>

        <div v-if="orders.length" class="space-y-2">
          <h3 class="text-sm font-semibold">最近订单</h3>
          <ul class="space-y-2">
            <li v-for="order in orders" :key="order.id" class="studio-dialog__order">
              <div class="flex flex-wrap justify-between gap-1">
                <span>{{ planName[order.plan] }} · ¥{{ order.amount / 100 }}</span>
                <span>{{ orderStatus[order.status] }}</span>
              </div>
              <div class="text-xs text-ink-500">{{ displayDate(order.created_at) }}</div>
              <div v-if="isPending(order) && order.status !== 'review'" class="mt-2 flex gap-3 text-brand-700">
                <button v-if="account.checkout_enabled" type="button" :disabled="pending || working" @click="checkout(order.plan)">继续付款</button>
                <button type="button" :disabled="pending || working" @click="run(async () => { notice = await cancel(order) })">取消订单</button>
              </div>
              <p v-if="order.status === 'review'" class="mt-2 break-all text-xs">请联系站点运营并提供订单号 {{ order.id }}</p>
            </li>
          </ul>
        </div>
        <button type="button" class="btn-outline px-3 py-2 text-sm" :disabled="working" @click="run(async () => {
          await action('logout', {})
          await refresh()
          show(null)
        })">退出登录</button>
      </template>

      <form v-else class="space-y-3" @submit.prevent="submit">
        <label v-if="needsEmail" class="block text-sm font-medium">
          邮箱
          <input v-model.trim="email" type="email" autocomplete="email" required
            class="studio-dialog__input" />
        </label>
        <label v-if="needsPassword" class="block text-sm font-medium">
          {{ view === 'reset' ? '新密码' : view === 'verify' ? '注册密码' : '密码' }}
          <input v-model="password" type="password" required :minlength="view === 'login' ? 1 : 12" maxlength="128"
            :autocomplete="view === 'register' || view === 'reset' ? 'new-password' : 'current-password'"
            class="studio-dialog__input" />
          <span v-if="view === 'register' || view === 'reset'" class="text-xs text-ink-500">至少 12 个字符</span>
        </label>
        <button type="submit" :disabled="working" class="studio-plan__button studio-dialog__submit">
          {{ working ? '处理中…' : view === 'forgot' ? '发送重置邮件' : labels[view] }}
        </button>
        <div class="flex flex-wrap gap-3 text-sm text-brand-700">
          <button v-if="view !== 'login'" type="button" @click="show('login')">返回登录</button>
          <button v-if="view === 'login'" type="button" @click="show('register')">注册账号</button>
          <button v-if="view === 'login' || view === 'verify'" type="button" @click="show('forgot')">忘记密码</button>
        </div>
      </form>
    </div>
  </dialog>
</template>
