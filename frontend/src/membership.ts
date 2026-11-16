import { inject, onMounted, onUnmounted, provide, ref, type InjectionKey } from 'vue'

export type Plan = 'month' | 'year'
export type AccountView = 'login' | 'register' | 'forgot' | 'verify' | 'reset' | 'account'
type Status = 'creating' | 'open' | 'review' | 'expired' | 'paid' | 'refunded' | 'disputed' | 'dispute_lost'

export interface Order {
  id: string
  plan: Plan
  amount: number
  status: Status
  created_at: string
  expires_at: string | null
  checkout_url: string | null
}

interface Account {
  enabled: boolean
  checkout_enabled: boolean
  user: { email: string; verified: boolean } | null
  membership: Order | null
  quota: { limit: number; remaining: number } | null
  orders: Order[]
}

const emptyAccount: Account = {
  enabled: false, checkout_enabled: false, user: null, membership: null, quota: null, orders: [],
}
const key: InjectionKey<ReturnType<typeof createMembership>> = Symbol('membership')

export const planName = { month: '月卡', year: '年卡' }
export const orderStatus: Record<Status, string> = {
  creating: '等待生成收银台', open: '待付款或付款确认中', review: '等待人工对账',
  expired: '已关闭', paid: '已付款', refunded: '已全额退款',
  disputed: '拒付处理中，权益暂停', dispute_lost: '拒付已结案，权益已撤销',
}

export const isPending = (order: Order) => ['creating', 'open', 'review'].includes(order.status)
export const displayDate = (date: string) => new Intl.DateTimeFormat('zh-CN', {
  dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai',
}).format(new Date(date))

async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(path, {
    cache: 'no-store',
    ...(body ? {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    } : {}),
  })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请检查输入后重试')
  return data as T
}

function createMembership() {
  const account = ref<Account>({ ...emptyAccount })
  const view = ref<AccountView | null>(null)
  const mailToken = ref('')
  const pending = ref(false)
  const error = ref('')
  const notice = ref('')
  const returnedOrder = ref<Order | null>(null)
  const returnedId = ref('')
  let refreshSequence = 0
  let polling: ReturnType<typeof setInterval> | undefined

  function show(next: AccountView | null) {
    view.value = next
    error.value = ''
    notice.value = ''
  }

  async function refresh() {
    const sequence = ++refreshSequence
    const updated = await request<Account>('/api/billing/account')
    if (sequence !== refreshSequence) return
    account.value = updated
    if (returnedId.value && updated.user) {
      const order = await request<Order>(`/api/billing/orders/${encodeURIComponent(returnedId.value)}`)
        .catch(() => null)
      if (sequence === refreshSequence) returnedOrder.value = order
    }
  }

  async function action(path: string, body: object) {
    return request(`/api/account/${path}`, body)
  }

  async function checkout(plan: Plan) {
    if (!account.value.user) { show('login'); return }
    if (!account.value.user.verified) { show('account'); notice.value = '购买前请验证邮箱。'; return }
    if (pending.value) return
    pending.value = true
    error.value = ''
    try {
      const order = await request<Order>('/api/billing/checkout', { plan })
      if (order.checkout_url) {
        window.location.assign(order.checkout_url)
        return
      }
      await refresh()
      show('account')
      notice.value = orderStatus[order.status]
    } catch (exc) {
      if (!view.value) show('account')
      error.value = exc instanceof Error ? exc.message : '暂时无法创建订单'
      await refresh().catch(() => {})
    } finally {
      pending.value = false
    }
  }

  async function cancel(order: Order) {
    const updated = await request<Order>(`/api/billing/orders/${order.id}/cancel`, {})
    await refresh()
    return orderStatus[updated.status]
  }

  function readMailLink() {
    const url = new URL(window.location.href)
    const fragment = new URLSearchParams(url.hash.slice(1))
    const mode = fragment.get('account')
    if ((mode === 'verify' || mode === 'reset') && fragment.has('token')) {
      mailToken.value = fragment.get('token') ?? ''
      show(mode)
      url.hash = ''
      window.history.replaceState(null, '', url)
    }
  }

  onMounted(() => {
    readMailLink()
    window.addEventListener('hashchange', readMailLink)
    const url = new URL(window.location.href)
    const id = url.searchParams.get('membership_order')
    if (id && /^[a-f0-9-]{36}$/.test(id)) returnedId.value = id
    url.searchParams.delete('membership_order')
    url.searchParams.delete('checkout_cancelled')
    if (url.href !== window.location.href) window.history.replaceState(null, '', url)

    void refresh().then(() => {
      if (returnedId.value) show(account.value.user ? 'account' : 'login')
    }).catch(() => {})
    polling = setInterval(() => {
      if (account.value.user && (view.value === 'account' || account.value.orders.some(isPending))) {
        void refresh().catch(() => {})
      }
    }, 3000)
  })
  onUnmounted(() => {
    clearInterval(polling)
    window.removeEventListener('hashchange', readMailLink)
  })
  return { account, view, mailToken, pending, error, notice, returnedOrder, show, refresh, action, checkout, cancel }
}

export function provideMembership() {
  provide(key, createMembership())
}

export function useMembership() {
  const membership = inject(key)
  if (!membership) throw new Error('Membership context is missing')
  return membership
}
