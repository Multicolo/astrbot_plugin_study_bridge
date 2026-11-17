<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ApiFailure,
  api,
  bindStatus,
  createBindCode,
  exchangeToken,
  getServer,
  getToken,
  humanError,
  setServer,
  setToken,
} from '../api'
import { useAuthStore } from '../stores/auth'
import { toast } from '../toast'
import StateBlock from '../components/StateBlock'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const server = ref(getServer())
const code = ref('')
const expiresAt = ref(0)
const secondsLeft = ref(0)
const polling = ref(false)
const busy = ref(false)
const errorText = ref('')
const info = ref<any>(null)
const infoError = ref('')
const infoLoading = ref(false)
const tokenInput = ref('')
const health = ref<string>('')

let pollTimer: number | null = null
let tickTimer: number | null = null

const expired = computed(() => route.query.expired === '1')
const bound = computed(() => Boolean(getToken()))

function stopTimers() {
  if (pollTimer) window.clearInterval(pollTimer)
  if (tickTimer) window.clearInterval(tickTimer)
  pollTimer = null
  tickTimer = null
}

async function loadInfo() {
  infoError.value = ''
  // 未绑定就没有令牌，/info 必然 401。以前会在这张卡里显示红色「令牌已失效」，
  // 让第一次装好的用户以为坏了 —— 未绑定时保持空态，绑定后再拉。
  if (!getToken()) {
    info.value = null
    infoLoading.value = false
    return
  }
  infoLoading.value = true
  try {
    info.value = await api.get('/info')
  } catch (error) {
    infoError.value = humanError(error)
  } finally {
    infoLoading.value = false
  }
}

async function testConnection() {
  busy.value = true
  health.value = ''
  errorText.value = ''
  setServer(server.value)
  try {
    const result = await api.get('/health', { auth: false })
    health.value = `连接正常 · 插件 ${result.version}`
    await loadInfo()
  } catch (error) {
    const failure = error as ApiFailure
    errorText.value =
      failure.kind === 'network'
        ? '端口不通：请确认地址、端口、防火墙，或手机与电脑在同一局域网'
        : humanError(error)
  } finally {
    busy.value = false
  }
}

async function startBind() {
  busy.value = true
  errorText.value = ''
  setServer(server.value)
  try {
    const data = await createBindCode()
    code.value = data.code
    expiresAt.value = Date.now() + data.expires_in * 1000
    secondsLeft.value = data.expires_in
    startTimers()
  } catch (error) {
    errorText.value = humanError(error)
  } finally {
    busy.value = false
  }
}

function startTimers() {
  stopTimers()
  tickTimer = window.setInterval(() => {
    secondsLeft.value = Math.max(0, Math.round((expiresAt.value - Date.now()) / 1000))
    if (secondsLeft.value === 0) stopTimers()
  }, 1000)
  polling.value = true
  pollTimer = window.setInterval(async () => {
    if (!code.value) return
    try {
      const status = await bindStatus(code.value)
      if (status.bound) {
        stopTimers()
        await finishBind()
      }
    } catch {
      /* 轮询失败继续等下一次 */
    }
  }, 2000)
}

async function finishBind() {
  try {
    const data = await exchangeToken(code.value)
    auth.saveConnection(getServer(), data.token)
    toast('绑定成功，欢迎使用')
    await auth.refresh()
    await loadInfo()
    router.replace({ name: 'today' })
  } catch (error) {
    errorText.value = humanError(error)
  } finally {
    polling.value = false
  }
}

async function useManualToken() {
  if (!tokenInput.value.trim()) return
  setServer(server.value)
  setToken(tokenInput.value.trim())
  auth.server = getServer()
  auth.token = getToken()
  try {
    await auth.refresh()
    toast('令牌已保存')
    await loadInfo()
    router.replace({ name: 'today' })
  } catch (error) {
    errorText.value = humanError(error)
  }
}

function unbind() {
  auth.logout()
  code.value = ''
  info.value = null
  health.value = ''
  stopTimers()
}

onMounted(async () => {
  if (bound.value) {
    await auth.refresh()
    await loadInfo()
  }
})

onUnmounted(stopTimers)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>绑定与安装自检</h1>
        <p>数据全部保存在你自己的 AstrBot 机器上，没有开发者后端。</p>
      </div>
      <div class="row">
        <span class="badge" :class="bound ? 'ok' : 'warn'">{{ bound ? '已绑定' : '未绑定' }}</span>
      </div>
    </div>

    <div v-if="expired" class="alert error" style="margin-bottom: 14px">
      令牌已失效，请重新绑定（数据不会丢）。
    </div>

    <div class="grid two">
      <section class="card">
        <h2>1. 服务地址</h2>
        <div class="field-group">
          <label class="field">AstrBot 上本插件的地址</label>
          <input v-model="server" placeholder="留空 = 当前站点；或 http://192.168.1.10:6188" />
          <p class="muted tiny" style="margin: 6px 0 0">
            局域网填内网 IP；公网填域名。反代请用 https。
          </p>
        </div>
        <div class="row">
          <button class="primary" :disabled="busy" @click="testConnection">测试连接</button>
          <span v-if="health" class="badge ok">{{ health }}</span>
        </div>
      </section>

      <section class="card">
        <h2>2. 绑定这台设备</h2>
        <template v-if="!code">
          <p class="muted tiny">点下面按钮生成 6 位绑定码，然后在 QQ 里私聊机器人发送：</p>
          <div class="code">/bind 123456</div>
          <div class="row" style="margin-top: 12px">
            <button class="primary" :disabled="busy" @click="startBind">生成绑定码</button>
            <span class="muted tiny">5 分钟有效，一次性</span>
          </div>
        </template>
        <template v-else>
          <div class="code">{{ code }}</div>
          <p class="muted" style="margin-top: 10px">
            在 QQ 私聊里发送 <span class="mono">/bind {{ code }}</span>，绑定会自动完成。
          </p>
          <p class="muted tiny">
            剩余 {{ Math.floor(secondsLeft / 60) }}:{{ String(secondsLeft % 60).padStart(2, '0') }}
            · {{ polling ? '正在等待确认…' : '已停止轮询' }}
          </p>
          <div class="row">
            <button class="ghost sm" @click="stopTimers(); code = ''">换一个码</button>
            <button class="sm" :disabled="!polling" @click="finishBind">我已绑定，立即完成</button>
          </div>
        </template>
      </section>
    </div>

    <div v-if="errorText" class="alert error" style="margin-top: 14px">{{ errorText }}</div>

    <section v-if="bound" class="card" style="margin-top: 14px">
      <h2>当前身份</h2>
      <div class="row" style="gap: 18px">
        <div>
          <div class="muted tiny">主体</div>
          <div>{{ auth.principal?.kind }} / {{ auth.principal?.external_id }}</div>
        </div>
        <div>
          <div class="muted tiny">设备数</div>
          <div>{{ auth.deviceCount }}</div>
        </div>
        <div class="spacer" />
        <button class="danger sm" @click="unbind">解除本机绑定</button>
      </div>
    </section>

    <section class="card" style="margin-top: 14px">
      <div class="row between">
        <h2>安装自检</h2>
        <button class="sm ghost" @click="loadInfo">刷新</button>
      </div>
      <StateBlock :loading="infoLoading" :error="infoError" @retry="loadInfo">
        <div v-if="!info" class="empty">
          
          绑定后可查看插件版本、迁移版本、记忆适配器与 AI 状态
        </div>
        <div v-else class="list">
          <div class="list-row">
            <span class="badge ok">插件</span>
            <span class="title">{{ info.plugin_version }}</span>
            <span class="spacer" />
            <span class="muted tiny">AstrBot {{ info.astrbot_version }}</span>
          </div>
          <div class="list-row">
            <span class="badge brand">数据库</span>
            <span>迁移版本 v{{ info.schema_version }}</span>
            <span class="spacer" />
            <span class="muted tiny">{{ info.timezone }}</span>
          </div>
          <div class="list-row">
            <span class="badge" :class="info.memory.active.ok ? 'ok' : 'warn'">记忆</span>
            <span>{{ info.memory.active.name }}</span>
            <span class="spacer" />
            <span class="muted tiny">{{ info.memory.active.reason }}</span>
          </div>
          <div class="list-row">
            <span class="badge" :class="info.ai.available ? 'ok' : 'warn'">AI</span>
            <span>{{ info.ai.mode }} · {{ info.ai.provider_id || '默认模型' }}</span>
            <span class="spacer" />
            <span class="muted tiny">{{ info.ai.available ? '可用' : '不可用（将使用规则解析）' }}</span>
          </div>
          <div class="list-row">
            <span class="badge" :class="info.http.enabled ? 'ok' : 'warn'">HTTP</span>
            <span>{{ info.http.host }}:{{ info.http.port }}</span>
            <span class="spacer" />
            <span class="muted tiny">设备 {{ info.counts.devices }} · 任务 {{ info.counts.tasks }}</span>
          </div>
          <div v-for="warning in info.warnings" :key="warning" class="alert warn">
            {{ warning }}
          </div>
        </div>
      </StateBlock>
    </section>

    <section v-if="!bound" class="card" style="margin-top: 14px">
      <h2>已有令牌？直接粘贴</h2>
      <div class="row">
        <input v-model="tokenInput" placeholder="粘贴 32 字节令牌" style="flex: 1" />
        <button @click="useManualToken">使用</button>
      </div>
      <p class="muted tiny" style="margin-top: 8px">
        令牌只保存在本机浏览器 localStorage，不会上传到任何第三方。
      </p>
    </section>
  </div>
</template>
