<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import { useAuthStore } from '../stores/auth'
import { toast } from '../toast'

const auth = useAuthStore()
const devices = ref<any[]>([])
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    devices.value = (await api.get('/auth/devices')).devices
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

async function revoke(device: any) {
  if (!window.confirm(`吊销「${device.label || device.id.slice(0, 8)}」？该设备会立即失效。`)) return
  try {
    await api.post('/auth/revoke', { token_id: device.id })
    toast('已吊销')
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

onMounted(async () => {
  await auth.refresh()
  await load()
})
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>设备管理</h1>
        <p>同一主体可绑多台设备；吊销后该设备令牌立即 401</p>
      </div>
    </div>

    <section class="card" style="margin-bottom: 14px">
      <div class="row between">
        <div>
          <div class="muted tiny">当前主体</div>
          <div>{{ auth.principal?.kind }} / {{ auth.principal?.external_id }}</div>
        </div>
        <div>
          <div class="muted tiny">设备数</div>
          <div>{{ auth.deviceCount }}</div>
        </div>
        <button class="sm ghost" @click="load">刷新</button>
      </div>
    </section>

    <StateBlock :loading="loading" :error="error" :empty="!devices.length" empty-text="还没有设备" @retry="load">
      <div class="list">
        <div v-for="device in devices" :key="device.id" class="list-row">
          <span class="badge" :class="device.revoked ? 'danger' : 'ok'">
            {{ device.revoked ? '已吊销' : '有效' }}
          </span>
          <div style="flex: 1; min-width: 0">
            <div class="title">{{ device.label || '未命名设备' }}</div>
            <div class="muted tiny">
              创建 {{ new Date(device.created_at).toLocaleString('zh-CN') }}
              · 最近使用
              {{ device.last_used_at ? new Date(device.last_used_at).toLocaleString('zh-CN') : '从未' }}
            </div>
          </div>
          <button class="sm danger ghost" :disabled="device.revoked" @click="revoke(device)">吊销</button>
        </div>
      </div>
    </StateBlock>
  </div>
</template>
