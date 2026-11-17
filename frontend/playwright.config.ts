import { defineConfig, devices } from '@playwright/test'

// E2E 跑在 scripts/e2e.py 启动的独立服务上（不需要 AstrBot）
export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  retries: 0,
  // 两个 project 共用同一个服务端与同一份数据，必须串行（否则会互相污染）
  workers: 1,
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: process.env.STUDY_BASE || 'http://127.0.0.1:6199',
    headless: true,
    viewport: { width: 1280, height: 900 },
    screenshot: 'only-on-failure',
    trace: 'off',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
})
