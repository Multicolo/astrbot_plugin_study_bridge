import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import legacy from '@vitejs/plugin-legacy'

// 构建产物直接落到插件根目录的 web/，由 aiohttp 在 /study/ 下同源托管。
//
// legacy 插件是给安卓 WebView 兜底的：很多手机的系统 WebView 停在 Chrome 6x/7x，
// 不支持 <script type="module"> 和 ?? / ?. 这类语法，会表现为「白屏且没有报错」。
// 这里同时产出 modern（module）与 legacy（nomodule + polyfill）两套。
export default defineConfig({
  base: '/study/',
  plugins: [
    vue(),
    legacy({
      targets: ['android >= 7', 'chrome >= 61', 'safari >= 11', 'not dead'],
      renderLegacyChunks: true,
      modernPolyfills: false,
      // 旧内核缺的运行时 API：Chrome 53（安卓 7 原装 WebView）没有 padStart / Object.entries，
      // 少了它们页面能画出来但一点就报错。AbortController 在 api.ts 里做了降级。
      polyfills: [
        'es.promise',
        'es.promise.finally',
        'es.array.flat',
        'es.object.from-entries',
        'es.object.entries',
        'es.string.pad-start',
      ],
    }),
  ],
  build: {
    outDir: '../web',
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
  server: {
    port: 5173,
    proxy: {
      // 本地开发时把接口转发到独立运行的后端（python -m core.standalone）
      '/api/study': 'http://127.0.0.1:6188',
    },
  },
})
