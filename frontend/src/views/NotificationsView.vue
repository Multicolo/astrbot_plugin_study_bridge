<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import type { Notification } from '../types'

const items = ref<Notification[]>([])
const loading = ref(false)
const error = ref('')
const status = ref('')

const labels: Record<string, string> = {
  daily_brief: '早报',
  reminder: '提醒',
  plan_nudge: '计划督促',
  weekly_report: '周报',
  custom: '自定义',
}
const statusLabels: Record<string, string> = {
  pending: '待发送',
  sent: '已发送',
  failed: '失败',
  cancelled: '已取消',
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const query = status.value ? `?status=${status.value}&limit=100` : '?limit=100'
    items.value = (await api.get(`/notifications${query}`)).notifications
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>通知记录</h1>
        <p>推送成功与失败都如实记录，失败会重试</p>
      </div>
      <div class="tabs" style="margin: 0">
        <button :class="{ active: status === '' }" @click="status = ''; load()">全部</button>
        <button :class="{ active: status === 'sent' }" @click="status = 'sent'; load()">已发送</button>
        <button :class="{ active: status === 'failed' }" @click="status = 'failed'; load()">失败</button>
        <button :class="{ active: status === 'pending' }" @click="status = 'pending'; load()">待发送</button>
      </div>
    </div>

    <StateBlock :loading="loading" :error="error" :empty="!items.length" empty-text="还没有通知" @retry="load">
      <div class="list">
        <div v-for="item in items" :key="item.id" class="list-row">
          <span class="badge" :class="item.status === 'sent' ? 'ok' : item.status === 'failed' ? 'danger' : 'warn'">
            {{ statusLabels[item.status] || item.status }}
          </span>
          <div style="flex: 1; min-width: 0">
            <div class="title">{{ item.title || labels[item.kind] || item.kind }}</div>
            <div class="muted tiny">
              {{ new Date(item.scheduled_at).toLocaleString('zh-CN') }}
              · 尝试 {{ item.attempts }} 次
              <span v-if="item.error" style="color: #ffb6b8"> · {{ item.error }}</span>
            </div>
          </div>
        </div>
      </div>
    </StateBlock>
  </div>
</template>
