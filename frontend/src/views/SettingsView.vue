<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import { toast } from '../toast'

const settings = ref<any>(null)
const loading = ref(false)
const error = ref('')
const saving = ref(false)
const exporting = ref(false)

/** 安卓外壳会注入 window.StudyBridgeShell；浏览器里就是 undefined。 */
const shell = typeof window === 'undefined' ? undefined : (window as any).StudyBridgeShell
const inShell = Boolean(shell)
const currentOrigin = typeof window === 'undefined' ? '' : window.location.origin

function changeServer() {
  if (shell && typeof shell.changeServer === 'function') {
    shell.changeServer()
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    settings.value = await api.get('/settings')
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    settings.value = await api.put('/settings', {
      tz: settings.value.tz,
      brief: settings.value.brief,
      nudge: settings.value.nudge,
      offsets: settings.value.offsets,
      duration: String(settings.value.duration),
    })
    toast('已保存')
  } catch (err) {
    toast(humanError(err))
  } finally {
    saving.value = false
  }
}

async function exportAll() {
  exporting.value = true
  try {
    const data = await api.get('/export')
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `study-bridge-export-${new Date().toISOString().slice(0, 10)}.json`
    link.click()
    URL.revokeObjectURL(url)
    toast('已导出全量 JSON')
  } catch (err) {
    toast(humanError(err))
  } finally {
    exporting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>设置</h1>
        <p>时区、早报、督促与提醒偏移——按主体保存，不影响别人</p>
      </div>
      <button class="sm ghost" :disabled="exporting" @click="exportAll">
        {{ exporting ? '导出中…' : '导出全量 JSON' }}
      </button>
    </div>

    <StateBlock :loading="loading" :error="error" @retry="load">
      <section v-if="settings" class="card">
        <div class="grid two">
          <div class="field-group">
            <label class="field">时区（IANA）</label>
            <input v-model="settings.tz" placeholder="Asia/Shanghai" />
          </div>
          <div class="field-group">
            <label class="field">默认任务时长（分钟）</label>
            <input v-model.number="settings.duration" type="number" min="5" max="600" />
          </div>
          <div class="field-group">
            <label class="field">早报时间（HH:MM）</label>
            <input v-model="settings.brief" placeholder="08:00" />
          </div>
          <div class="field-group">
            <label class="field">计划督促时间（HH:MM）</label>
            <input v-model="settings.nudge" placeholder="21:00" />
          </div>
          <div class="field-group">
            <label class="field">提醒偏移（逗号分隔的分钟）</label>
            <input v-model="settings.offsets" placeholder="30,0" />
          </div>
        </div>
        <button class="primary" :disabled="saving" @click="save">保存设置</button>
      </section>

      <section v-if="inShell" class="card" style="margin-top: 14px">
        <h2>App 服务器地址</h2>
        <p class="muted tiny" style="margin: 6px 0 12px">
          App 现在打开的是 {{ currentOrigin }}。换电脑或路由器换了 IP 后在这里改，不用重装 App。
        </p>
        <button class="primary" @click="changeServer">换服务器地址</button>
      </section>

      <section class="card" style="margin-top: 14px">
        <h2>数据与隐私</h2>
        <ul class="muted tiny" style="margin: 0; padding-left: 18px; line-height: 1.9">
          <li>所有数据都在你自己的 AstrBot 机器上（SQLite），没有开发者侧后端。</li>
          <li>导出得到的是当前主体的全量 JSON，可自行备份。</li>
          <li>卸载插件后，删除 <span class="mono">data/plugin_data/astrbot_plugin_study_bridge/</span> 即可彻底清除。</li>
          <li>手填 API Key 只以密文形式保存在数据库，接口永远只回 <span class="mono">has_key</span>。</li>
        </ul>
      </section>
    </StateBlock>
  </div>
</template>
