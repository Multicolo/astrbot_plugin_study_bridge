<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import { toast } from '../toast'
import type { PushTarget } from '../types'

const targets = ref<PushTarget[]>([])
const loading = ref(false)
const error = ref('')
const umo = ref('')
const alias = ref('')
const busy = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    targets.value = (await api.get('/push-targets')).targets
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

async function add() {
  if (!umo.value.trim()) {
    toast('先填 UMO：在 QQ 里发 /umo 获取')
    return
  }
  busy.value = true
  try {
    await api.post('/push-targets', { umo: umo.value.trim(), alias: alias.value || undefined })
    umo.value = ''
    alias.value = ''
    toast('已添加推送目标')
    await load()
  } catch (err) {
    toast(humanError(err))
  } finally {
    busy.value = false
  }
}

async function toggle(target: PushTarget) {
  try {
    await api.patch(`/push-targets/${target.id}`, { enabled: !target.enabled })
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function test(target: PushTarget) {
  try {
    const result = await api.post(`/push-targets/${target.id}/test`)
    toast(result.ok ? '已发送测试消息' : '发送失败：检查机器人是否在目标会话、平台是否在线')
  } catch (err) {
    toast(humanError(err))
  }
}

async function remove(target: PushTarget) {
  if (!window.confirm('删除这个推送目标？')) return
  try {
    await api.del(`/push-targets/${target.id}`)
    toast('已删除')
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>推送目标</h1>
        <p>早报、提醒、周报都会发到这里的第一个启用目标</p>
      </div>
    </div>

    <section class="card" style="margin-bottom: 14px">
      <h2>添加会话</h2>
      <div class="grid two">
        <div class="field-group">
          <label class="field">UMO（QQ 里发 /umo 获取）</label>
          <input v-model="umo" placeholder="qq:FriendMessage:12345678" />
        </div>
        <div class="field-group">
          <label class="field">别名（可选）</label>
          <input v-model="alias" placeholder="例如：我的私聊" />
        </div>
      </div>
      <button class="primary" :disabled="busy" @click="add">添加</button>
      <p class="muted tiny" style="margin-top: 8px">
        UMO 一律来自 AstrBot 事件对象，插件内部不做任何字符串拼接，换平台也不用改。
      </p>
    </section>

    <StateBlock :loading="loading" :error="error" :empty="!targets.length" empty-text="还没有推送目标" @retry="load">
      <div class="list">
        <div v-for="target in targets" :key="target.id" class="list-row">
          <span class="badge" :class="target.enabled ? 'ok' : 'warn'">
            {{ target.enabled ? '启用' : '停用' }}
          </span>
          <div style="flex: 1; min-width: 0">
            <div class="title">{{ target.alias || '未命名' }}</div>
            <div class="muted tiny mono">{{ target.umo }}</div>
          </div>
          <button class="sm ghost" @click="test(target)">测试推送</button>
          <button class="sm ghost" @click="toggle(target)">
            {{ target.enabled ? '停用' : '启用' }}
          </button>
          <button class="sm danger ghost" @click="remove(target)">删除</button>
        </div>
      </div>
    </StateBlock>
  </div>
</template>
