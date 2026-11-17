<script setup lang="ts">
import { computed, markRaw, onMounted, ref } from 'vue'
import { RouterView, useRoute, useRouter } from 'vue-router'
import {
  BarChart3,
  Bell,
  BookOpen,
  Brain,
  CalendarDays,
  Inbox,
  Link as LinkIcon,
  ListChecks,
  MessageSquare,
  MoreHorizontal,
  Settings as SettingsIcon,
  Smartphone,
  Sparkles,
} from 'lucide-vue-next'
import { useAuthStore } from './stores/auth'
import { toasts } from './toast'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const moreOpen = ref(false)

type NavItem = { name: string; label: string; icon: any }

const primary: NavItem[] = [
  { name: 'today', label: '今日', icon: markRaw(CalendarDays) },
  { name: 'plans', label: '计划', icon: markRaw(ListChecks) },
  { name: 'stats', label: '报表', icon: markRaw(BarChart3) },
  { name: 'chat', label: '对话', icon: markRaw(MessageSquare) },
  { name: 'more', label: '更多', icon: markRaw(MoreHorizontal) },
]

const nav: NavItem[] = [
  { name: 'today', label: '今日', icon: markRaw(CalendarDays) },
  { name: 'calendar', label: '日历', icon: markRaw(CalendarDays) },
  { name: 'plans', label: '计划', icon: markRaw(ListChecks) },
  { name: 'materials', label: '资料', icon: markRaw(BookOpen) },
  { name: 'stats', label: '报表', icon: markRaw(BarChart3) },
  { name: 'chat', label: 'AI 对话', icon: markRaw(MessageSquare) },
  { name: 'memory', label: '记忆中心', icon: markRaw(Brain) },
  { name: 'push', label: '推送目标', icon: markRaw(Bell) },
  { name: 'notifications', label: '通知记录', icon: markRaw(Inbox) },
  { name: 'ai', label: 'AI 设置', icon: markRaw(Sparkles) },
  { name: 'devices', label: '设备管理', icon: markRaw(Smartphone) },
  { name: 'settings', label: '设置', icon: markRaw(SettingsIcon) },
]

const more = computed(() =>
  nav.filter((item) => !['today', 'plans', 'stats', 'chat'].includes(item.name)),
)
const isSetup = computed(() => route.name === 'setup')

function isActive(name: string) {
  return route.name === name
}

function go(name: string) {
  moreOpen.value = false
  if (name === 'more') {
    moreOpen.value = true
    return
  }
  router.push({ name })
}

function activeTab() {
  const name = String(route.name || '')
  if (['today', 'plans', 'stats', 'chat'].includes(name)) return name
  return 'more'
}

onMounted(async () => {
  if (auth.bound) {
    await auth.refresh()
    auth.loadInfo().catch(() => {})
  }
})
</script>

<template>
  <div class="shell">
    <aside v-if="!isSetup" class="sidebar">
      <div class="brand">
        <div class="brand-logo">学</div>
        <div>
          <div class="brand-name">学习桥梁</div>
          <div class="brand-sub">Study Bridge</div>
        </div>
      </div>
      <div
        v-for="item in nav"
        :key="item.name"
        class="nav-item"
        :class="{ active: isActive(item.name) }"
        @click="go(item.name)"
      >
        <span class="nav-icon"><component :is="item.icon" :size="17" :stroke-width="1.8" /></span>
        <span>{{ item.label }}</span>
      </div>
      <div class="nav-item" :class="{ active: isSetup }" @click="go('setup')">
        <span class="nav-icon"><LinkIcon :size="17" :stroke-width="1.8" /></span>
        <span>绑定与自检</span>
      </div>
    </aside>

    <main class="main">
      <RouterView />
    </main>

    <nav v-if="!isSetup" class="tabbar">
      <button
        v-for="item in primary"
        :key="item.name"
        :class="{ active: activeTab() === item.name }"
        @click="go(item.name)"
      >
        <span class="nav-icon"><component :is="item.icon" :size="19" :stroke-width="1.8" /></span>
        <span>{{ item.label }}</span>
      </button>
    </nav>

    <div v-if="moreOpen" class="modal-mask" @click.self="moreOpen = false">
      <div class="modal card">
        <div class="row between" style="margin-bottom: 12px">
          <h2 style="margin: 0">全部页面</h2>
          <button class="sm ghost" @click="moreOpen = false">关闭</button>
        </div>
        <div class="grid two">
          <div
            v-for="item in more"
            :key="item.name"
            class="nav-item"
            :class="{ active: isActive(item.name) }"
            @click="go(item.name)"
          >
            <span class="nav-icon"><component :is="item.icon" :size="17" :stroke-width="1.8" /></span>
            <span>{{ item.label }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="toast-wrap">
      <div v-for="item in toasts" :key="item.id" class="toast" :class="item.kind">
        {{ item.text }}
      </div>
    </div>
  </div>
</template>
