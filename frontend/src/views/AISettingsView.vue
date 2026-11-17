<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import { toast } from '../toast'

const providers = ref<any[]>([])
const mode = ref('astrbot')
const providerId = ref('')
const manual = ref({ base_url: '', model: '', has_key: false })
const keyInput = ref('')
const loading = ref(false)
const error = ref('')
const testing = ref(false)
const testResult = ref<any>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [providerData, manualData] = await Promise.all([
      api.get('/ai/providers'),
      api.get('/ai/manual'),
    ])
    providers.value = providerData.providers
    mode.value = providerData.mode
    providerId.value = providerData.selected.provider_id || ''
    manual.value = {
      base_url: manualData.base_url || '',
      model: manualData.model || '',
      has_key: manualData.has_key,
    }
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

async function selectProvider() {
  try {
    await api.post('/ai/select', { provider_id: providerId.value })
    mode.value = 'astrbot'
    toast('已切换到 AstrBot 配置的模型')
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function saveManual() {
  try {
    await api.put('/ai/manual', {
      base_url: manual.value.base_url,
      model: manual.value.model,
      api_key: keyInput.value || undefined,
    })
    keyInput.value = ''
    mode.value = 'manual'
    toast('已保存（Key 加密存储，接口不回显）')
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function runTest() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await api.post('/ai/test')
  } catch (err) {
    testResult.value = { ok: false, error: humanError(err) }
  } finally {
    testing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>AI 设置</h1>
        <p>默认复用 AstrBot 已配置的模型，不复制、不落库任何 Key</p>
      </div>
    </div>

    <StateBlock :loading="loading" :error="error" @retry="load">
      <div class="grid two">
        <section class="card">
          <h2>使用 AstrBot 的模型</h2>
          <p class="muted tiny">从 AstrBot 已配置的对话模型里选一个，插件只保存 provider id。</p>
          <div class="field-group">
            <label class="field">Provider</label>
            <select v-model="providerId">
              <option value="">（用当前默认模型）</option>
              <option v-for="item in providers" :key="item.id" :value="item.id">
                {{ item.id }} · {{ item.model || item.type }}
              </option>
            </select>
          </div>
          <div class="row">
            <button class="primary sm" @click="selectProvider">保存选择</button>
            <span class="badge" :class="mode === 'astrbot' ? 'ok' : ''">
              {{ mode === 'astrbot' ? '当前模式' : '' }}
            </span>
          </div>
          <p v-if="!providers.length" class="muted tiny" style="margin-top: 8px">
            没有读到 provider：可能是独立运行模式（没有 AstrBot 运行时），此时请用手动模式。
          </p>
        </section>

        <section class="card">
          <h2>手动填写 OpenAI 兼容接口</h2>
          <div class="field-group">
            <label class="field">Base URL</label>
            <input v-model="manual.base_url" placeholder="https://api.openai.com/v1" />
          </div>
          <div class="field-group">
            <label class="field">模型</label>
            <input v-model="manual.model" placeholder="gpt-4o-mini / qwen-plus" />
          </div>
          <div class="field-group">
            <label class="field">API Key</label>
            <input
              v-model="keyInput"
              type="password"
              :placeholder="manual.has_key ? '已保存（留空则不修改）' : '粘贴你的 Key'"
            />
          </div>
          <div class="row">
            <button class="primary sm" @click="saveManual">保存</button>
            <span class="badge" :class="mode === 'manual' ? 'ok' : ''">
              {{ mode === 'manual' ? '当前模式' : '' }}
            </span>
          </div>
        </section>
      </div>

      <section class="card" style="margin-top: 14px">
        <h2>连通性测试</h2>
        <div class="row">
          <button :disabled="testing" @click="runTest">{{ testing ? '测试中…' : '开始测试' }}</button>
          <span v-if="testResult" class="badge" :class="testResult.ok ? 'ok' : 'danger'">
            {{ testResult.ok ? `可用 · ${testResult.latency_ms} ms` : testResult.error }}
          </span>
        </div>
        <p class="muted tiny" style="margin-top: 8px">
          测试会真实调用一次模型（消耗少量 token）。失败时插件会自动降级为规则解析，不影响主流程。
        </p>
      </section>
    </StateBlock>
  </div>
</template>
