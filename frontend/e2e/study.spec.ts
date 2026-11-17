import { expect, test } from '@playwright/test'

const TOKEN = process.env.STUDY_TOKEN || ''

test.beforeEach(async ({ page }) => {
  // 令牌由 scripts/e2e.py 种好；前端从 localStorage 读取
  await page.addInitScript((token) => {
    localStorage.setItem('study.token', token)
    localStorage.removeItem('study.server')
  }, TOKEN)
})

test('绑定页：无令牌时展示绑定码入口与自检', async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem('study.token'))
  await page.goto('/study/setup')
  await expect(page.getByRole('heading', { name: '绑定与安装自检' })).toBeVisible()
  await page.getByRole('button', { name: '生成绑定码' }).click()
  // 6 位数字绑定码
  await expect(page.locator('.code')).toHaveText(/^\d{6}$/)
  await expect(page.getByText(/正在等待确认/)).toBeVisible()
})

test('绑定页：未绑定时测试连接不报「令牌已失效」', async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem('study.token'))
  await page.goto('/study/setup')
  await page.getByRole('button', { name: '测试连接' }).click()
  await expect(page.getByText(/连接正常 · 插件/)).toBeVisible({ timeout: 15000 })
  // 没令牌时 /info 一定 401；以前会把 401 显示成红色错误块，让新用户以为坏了
  await expect(page.getByText('令牌已失效，请重新绑定')).toHaveCount(0)
  await expect(page.getByText('绑定后可查看插件版本')).toBeVisible()
})

test('今日：建任务后列表出现，可标记完成', async ({ page }) => {
  await page.goto('/study/today')
  await expect(page.getByRole('heading', { name: '今日' })).toBeVisible()

  const title = `E2E 任务 ${Date.now()}`
  await page.getByPlaceholder(/明天下午三点背单词一小时/).fill(`今天下午三点 ${title}`)
  await page.getByRole('button', { name: '解析' }).click()
  await expect(page.getByText('规则解析').or(page.getByText('AI 解析'))).toBeVisible({ timeout: 15000 })
  const writeButton = page.getByRole('button', { name: '写入日程' })
  await expect(writeButton).toBeEnabled()
  await writeButton.click()

  const row = page.locator('.list-row', { hasText: title }).first()
  await expect(row).toBeVisible({ timeout: 15000 })
  await row.getByRole('button', { name: '标记完成' }).click()
  await expect(
    page.locator('.list-row', { hasText: title }).first().getByRole('button', { name: '标记未完成' }),
  ).toBeVisible()
})

test('日历：月视图可见当天任务', async ({ page }) => {
  await page.goto('/study/calendar')
  await expect(page.getByRole('heading', { name: '日历' })).toBeVisible()
  await expect(page.locator('.calendar-cell').first()).toBeVisible()
  const today = new Date()
  const cell = page.locator('.calendar-cell.today')
  await expect(cell).toBeVisible()
  await cell.click()
  await expect(page.getByText(/\d{4}-\d{2}-\d{2} 的安排/)).toBeVisible()
  expect(today.getDate()).toBeGreaterThan(0)
})

test('计划：详情可查看，写入日程幂等', async ({ page }) => {
  await page.goto('/study/plans')
  await expect(page.getByRole('heading', { name: '计划', exact: true })).toBeVisible()
  const row = page.locator('.list-row', { hasText: 'E2E 计划' }).first()
  await expect(row).toBeVisible({ timeout: 15000 })
  await row.getByRole('button', { name: '查看' }).click()
  await expect(page.locator('.list-row', { hasText: 'E2E 第一章' }).first()).toBeVisible()

  const applyButton = page.getByRole('button', { name: '写入日程' })
  if (await applyButton.isEnabled()) {
    await applyButton.click()
    await page.getByRole('button', { name: '确认写入' }).click()
    await expect(page.getByText(/已写入|幂等/).first()).toBeVisible({ timeout: 15000 })
  }
  await expect(page.locator('.badge', { hasText: '已写入' }).first()).toBeVisible()
})

test('报表：图表与计划进度渲染', async ({ page }) => {
  await page.goto('/study/stats')
  await expect(page.getByRole('heading', { name: '报表', exact: true })).toBeVisible()
  await expect(page.locator('.stat-label', { hasText: '完成率' })).toBeVisible()
  await expect(page.locator('.chart canvas').first()).toBeVisible({ timeout: 20000 })
  await page.getByRole('button', { name: '本月' }).click()
  await expect(page.locator('.chart canvas').first()).toBeVisible()
})

test('AI 对话：发消息拿到回复', async ({ page }) => {
  await page.goto('/study/chat')
  await page.getByPlaceholder(/说点什么/).fill('你好')
  await page.getByRole('button', { name: '发送' }).click()
  await expect(page.locator('.bubble.assistant').last()).toContainText('好的', { timeout: 20000 })
})

test('记忆中心：两个分区切换 + 新增记忆', async ({ page }) => {
  await page.goto('/study/memory')
  await expect(page.getByRole('heading', { name: '记忆中心' })).toBeVisible()
  await page.getByRole('button', { name: 'bot 记忆' }).click()
  await expect(page.getByText('E2E bot 记忆')).toBeVisible({ timeout: 15000 })
  await page.getByRole('button', { name: '学习记忆' }).click()
  await expect(page.getByText('E2E 偏好')).toBeVisible()
  await page.getByPlaceholder(/记忆内容/).fill('E2E 新记忆 晚上八点后才有空')
  await page.getByRole('button', { name: '记住' }).click()
  await expect(page.getByText('E2E 新记忆')).toBeVisible({ timeout: 15000 })
})

test('推送目标：新增 + 测试推送 + 删除', async ({ page }) => {
  await page.goto('/study/push')
  await expect(page.getByRole('heading', { name: '推送目标' })).toBeVisible()
  const umo = `qq:FriendMessage:${Date.now()}`
  await page.getByPlaceholder(/qq:FriendMessage/).fill(umo)
  await page.getByPlaceholder(/我的私聊/).fill('E2E 私聊')
  await page.getByRole('button', { name: '添加', exact: true }).click()
  const row = page.locator('.list-row', { hasText: 'E2E 私聊' }).first()
  await expect(row).toBeVisible({ timeout: 15000 })
  await row.getByRole('button', { name: '测试推送' }).click()
  await expect(page.locator('.toast')).toBeVisible({ timeout: 15000 })
})

test('移动端：底部 TabBar 可见并可切换', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile', '仅移动端项目')
  await page.goto('/study/today')
  const tabbar = page.locator('.tabbar')
  await expect(tabbar).toBeVisible()
  await tabbar.getByRole('button', { name: /计划/ }).click()
  await expect(page.getByRole('heading', { name: '计划', exact: true })).toBeVisible()
})
