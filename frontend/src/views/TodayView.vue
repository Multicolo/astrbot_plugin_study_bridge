<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Circle, CircleCheck } from 'lucide-vue-next'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import { toast } from '../toast'
import type { DayView, Task } from '../types'

const offset = ref(0)
const view = ref<DayView | null>(null)
const loading = ref(false)
const error = ref('')

const natural = ref('')
const parsing = ref(false)
const draft = ref<any>(null)
const saving = ref(false)

const title = computed(() => (offset.value === 0 ? '今日' : '明日'))

async function load() {
  loading.value = true
  error.value = ''
  try {
    view.value = await api.get(`/tasks/today?offset=${offset.value}`)
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

async function parseText() {
  if (!natural.value.trim()) return
  parsing.value = true
  error.value = ''
  try {
    const result = await api.post('/tasks/parse', { text: natural.value.trim() })
    draft.value = { ...result.draft, confidence: result.confidence, source: result.source }
  } catch (err) {
    error.value = humanError(err)
  } finally {
    parsing.value = false
  }
}

async function confirmDraft() {
  if (!draft.value) return
  saving.value = true
  try {
    await api.post('/tasks', {
      title: draft.value.title,
      start_at: draft.value.start_at,
      end_at: draft.value.end_at,
      priority: draft.value.priority,
      remind_offsets: draft.value.remind_offsets,
    })
    draft.value = null
    natural.value = ''
    toast('已写入日程')
    await load()
  } catch (err) {
    toast(humanError(err))
  } finally {
    saving.value = false
  }
}

async function toggle(task: Task) {
  try {
    await api.patch(`/tasks/${task.id}/status`, {
      status: task.status === 'done' ? 'pending' : 'done',
    })
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function remove(task: Task) {
  if (!window.confirm(`删除「${task.title}」？`)) return
  try {
    await api.del(`/tasks/${task.id}`)
    toast('已删除')
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

function switchOffset(value: number) {
  offset.value = value
  load()
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>{{ title }}</h1>
        <p v-if="view">
          {{ view.date }} · {{ view.total }} 项，已完成 {{ view.done }}（{{ view.rate }}%）
          <span v-if="view.overdue" class="badge warn" style="margin-left: 8px"
            >逾期 {{ view.overdue }}</span
          >
        </p>
      </div>
      <div class="tabs" style="margin: 0">
        <button :class="{ active: offset === 0 }" @click="switchOffset(0)">今天</button>
        <button :class="{ active: offset === 1 }" @click="switchOffset(1)">明天</button>
      </div>
    </div>

    <section class="card" style="margin-bottom: 14px">
      <h2>说一句话，自动排进日程</h2>
      <div class="row">
        <input
          v-model="natural"
          style="flex: 1; min-width: 200px"
          placeholder="例：明天下午三点背单词一小时"
          @keyup.enter="parseText"
        />
        <button class="primary" :disabled="parsing || !natural.trim()" @click="parseText">
          {{ parsing ? '解析中…' : '解析' }}
        </button>
      </div>

      <div v-if="draft" class="card" style="margin-top: 12px; background: rgba(79,140,255,0.08)">
        <div class="row between">
          <strong>{{ draft.title || '（无标题）' }}</strong>
          <span class="badge" :class="draft.source === 'ai' ? 'brand' : 'warn'">
            {{ draft.source === 'ai' ? 'AI 解析' : '规则解析' }} · {{ Math.round((draft.confidence || 0) * 100) }}%
          </span>
        </div>
        <p class="muted" style="margin: 8px 0">
          <template v-if="draft.local_date">
            {{ draft.local_date }} {{ draft.local_start || '' }}
            <span v-if="draft.local_end">~ {{ draft.local_end }}</span>
          </template>
          <template v-else>没有识别出具体时间，请补充。</template>
        </p>
        <div class="row">
          <button class="primary sm" :disabled="saving || !draft.start_at" @click="confirmDraft">
            写入日程
          </button>
          <button class="ghost sm" @click="draft = null">取消</button>
        </div>
      </div>
    </section>

    <StateBlock :loading="loading" :error="error" :empty="!view?.items.length" empty-text="这一天还没有安排" @retry="load">
      <div class="list">
        <div
          v-for="task in view?.items"
          :key="task.id"
          class="list-row"
          :class="{ done: task.status === 'done' }"
        >
          <button class="sm ghost" :aria-label="task.status === 'done' ? '标记未完成' : '标记完成'" @click="toggle(task)">
            <CircleCheck v-if="task.status === 'done'" :size="18" :stroke-width="1.8" />
            <Circle v-else :size="18" :stroke-width="1.8" />
          </button>
          <div style="min-width: 0; flex: 1">
            <div class="title">{{ task.title }}</div>
            <div class="muted tiny">
              {{ task.local_start || '全天' }}
              <span v-if="task.local_end">~ {{ task.local_end }}</span>
              · 来源 {{ task.source }}
              <span v-if="task.priority === 3" class="badge warn" style="margin-left: 6px">重要</span>
            </div>
          </div>
          <button class="sm danger ghost" @click="remove(task)">删除</button>
        </div>
      </div>
    </StateBlock>
  </div>
</template>
