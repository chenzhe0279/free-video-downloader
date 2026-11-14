import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import App from './App.vue'

/**
 * 构建期静态预渲染入口（SEO）：
 * 仅渲染初始页面（无解析结果、无 AI 总结、无下载任务），
 * 由 scripts/prerender.mjs 在 `vite build` 之后调用，
 * 把渲染结果注入 dist/index.html 的 <div id="app"> 中。
 *
 * 浏览器端仍走 src/main.ts 的 createApp 挂载，交互行为不变。
 */
export async function render(): Promise<string> {
  const app = createSSRApp(App)
  return await renderToString(app)
}
