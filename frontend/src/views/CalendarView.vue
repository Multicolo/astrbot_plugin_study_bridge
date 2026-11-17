<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import type { Task } from '../types'

const cursor = ref(new Date())
const tasks = ref<Task[]>([])
const loading = ref(false)
const error = ref('')
const selected = ref<string | null>(null)

const monthLabel = computed(() =>
  cursor.value.toLocaleDateString('zh-CN', { year: 'numeric', month: 'long' }),
)

const days = computed(() => {
  const year = cursor.value.getFullYear()
  const month = cursor.value.getMonth()
  const first = new Date(year, month, 1)
  const startOffset = (first.getDay() + 6) % 7 // 周一为一周起点
  const start = new Date(year, month, 1 - startOffset)
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(start)
    day.setDate(start.getDate() + index)
    return day
  })
})

const byDate = computed(() => {
  const map: Record<string, Task[]> = {}
  for (const task of tasks.value) {
    if (!task.local_date) continue
    ;(map[task.local_date] ||= []).push(task)
  }
  return map
})

const todayKey = new Date().toISOString().slice(0, 10)

function key(day: Date) {
  const y = day.getFullYear()
  const m = String(day.getMonth() + 1).padStart(2, '0')
  const d = String(day.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const from = key(days.value[0])
    const to = key(days.value[days.value.length - 1])
    const data = await api.get(`/tasks?from=${from}&to=${to}&limit=500`)
    tasks.value = data.tasks
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

function shift(months: number) {
  const next = new Date(cursor.value)
  next.setMonth(next.getMonth() + months)
  cursor.value = next
  load()
}

function select(day: Date) {
  selected.value = key(day)
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>日历</h1>
        <p>点某一天查看当日安排</p>
      </div>
      <div class="row">
        <button class="sm ghost" @click="shift(-1)">‹ 上月</button>
        <strong>{{ monthLabel }}</strong>
        <button class="sm ghost" @click="shift(1)">下月 ›</button>
      </div>
    </div>

    <StateBlock :loading="loading" :error="error" @retry="load">
      <div class="card">
        <div class="calendar-grid" style="margin-bottom: 6px">
          <div v-for="weekday in ['一', '二', '三', '四', '五', '六', '日']" :key="weekday" class="muted tiny" style="text-align: center">
            {{ weekday }}
          </div>
        </div>
        <div class="calendar-grid">
          <div
            v-for="day in days"
            :key="key(day)"
            class="calendar-cell"
            :class="{
              dim: day.getMonth() !== cursor.getMonth(),
              today: key(day) === todayKey,
            }"
            @click="select(day)"
          >
            <div class="calendar-day">{{ day.getDate() }}</div>
            <span
              v-for="task in (byDate[key(day)] || []).slice(0, 2)"
              :key="task.id"
              class="calendar-dot"
            >
              · {{ task.title }}
            </span>
            <span v-if="(byDate[key(day)] || []).length > 2" class="calendar-dot muted">
              +{{ (byDate[key(day)] || []).length - 2 }}
            </span>
          </div>
        </div>
      </div>

      <section v-if="selected" class="card" style="margin-top: 14px">
        <h2>{{ selected }} 的安排</h2>
        <div v-if="!(byDate[selected] || []).length" class="empty">
          这天没有安排
        </div>
        <div v-else class="list">
          <div
            v-for="task in byDate[selected]"
            :key="task.id"
            class="list-row"
            :class="{ done: task.status === 'done' }"
          >
            <span class="badge">{{ task.local_start || '全天' }}</span>
            <span class="title">{{ task.title }}</span>
            <span class="spacer" />
            <span class="muted tiny">{{ task.status }}</span>
          </div>
        </div>
      </section>
    </StateBlock>
  </div>
</template>
