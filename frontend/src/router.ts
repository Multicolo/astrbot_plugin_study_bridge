import { createRouter, createWebHistory } from 'vue-router'
import { getToken, onUnauthorized } from './api'

const routes = [
  { path: '/', redirect: '/today' },
  { path: '/setup', name: 'setup', component: () => import('./views/SetupView.vue'), meta: { public: true, title: '绑定与自检' } },
  { path: '/today', name: 'today', component: () => import('./views/TodayView.vue'), meta: { title: '今日' } },
  { path: '/calendar', name: 'calendar', component: () => import('./views/CalendarView.vue'), meta: { title: '日历' } },
  { path: '/plans', name: 'plans', component: () => import('./views/PlansView.vue'), meta: { title: '计划' } },
  { path: '/materials', name: 'materials', component: () => import('./views/MaterialsView.vue'), meta: { title: '资料' } },
  { path: '/stats', name: 'stats', component: () => import('./views/StatsView.vue'), meta: { title: '报表' } },
  { path: '/chat', name: 'chat', component: () => import('./views/ChatView.vue'), meta: { title: 'AI 对话' } },
  { path: '/memory', name: 'memory', component: () => import('./views/MemoryView.vue'), meta: { title: '记忆中心' } },
  { path: '/push', name: 'push', component: () => import('./views/PushView.vue'), meta: { title: '推送目标' } },
  { path: '/notifications', name: 'notifications', component: () => import('./views/NotificationsView.vue'), meta: { title: '通知记录' } },
  { path: '/ai', name: 'ai', component: () => import('./views/AISettingsView.vue'), meta: { title: 'AI 设置' } },
  { path: '/devices', name: 'devices', component: () => import('./views/DevicesView.vue'), meta: { title: '设备管理' } },
  { path: '/settings', name: 'settings', component: () => import('./views/SettingsView.vue'), meta: { title: '设置' } },
]

export const router = createRouter({
  history: createWebHistory('/study/'),
  routes,
})

router.beforeEach((to) => {
  if (!to.meta.public && !getToken()) {
    return { name: 'setup', query: { from: to.fullPath } }
  }
  return true
})

onUnauthorized(() => {
  if (router.currentRoute.value.name !== 'setup') {
    router.push({ name: 'setup', query: { expired: '1' } })
  }
})
