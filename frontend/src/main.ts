import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import { router } from './router'
import './styles.css'

/**
 * 旧手机 WebView 的布局兜底。
 *
 * - flex 的 `gap` 到 Chrome 84 才有，旧内核上所有间距会消失（按钮和文字贴在一起）；
 * - CSS Grid 到 Chrome 57 才有，旧内核上卡片和日历会退化成竖排。
 *
 * 这里用特性检测在 <html> 上加 class，只有真的不支持时才补样式，
 * 现代浏览器（以及 Playwright E2E）完全不受影响。
 */
function markLegacyLayout() {
  const root = document.documentElement

  const probe = document.createElement('div')
  probe.style.display = 'flex'
  probe.style.flexDirection = 'column'
  probe.style.rowGap = '1px'
  probe.innerHTML = '<div style="height:1px"></div><div style="height:1px"></div>'
  document.body.appendChild(probe)
  const supportsFlexGap = Math.round(probe.getBoundingClientRect().height) === 3
  probe.remove()
  if (!supportsFlexGap) {
    root.classList.add('no-flex-gap')
  }

  const supportsGrid =
    typeof CSS !== 'undefined' && typeof CSS.supports === 'function' && CSS.supports('display', 'grid')
  if (!supportsGrid) {
    root.classList.add('no-css-grid')
  }
}

markLegacyLayout()

createApp(App).use(createPinia()).use(router).mount('#app')
