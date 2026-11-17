<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import { toast } from '../toast'

interface Bubble {
  role: 'user' | 'assistant' | 'tool'
  text: string
}

const sessionKey = 'app-default'
const bubbles = ref<Bubble[]>([])
const input = ref('')
const sending = ref(false)
const scrollEl = ref<HTMLDivElement | null>(null)
const planDraft = ref<any>(null)

async function loadHistory() {
  try {
    const data = await api.get(`/chat/history?session_key=${sessionKey}&limit=50`)
    bubbles.value = (data.messages || [])
      .filter((row: any) => row.role !== 'tool')
      .map((row: any) => ({ role: row.role, text: row.content || '' }))
    await scrollToEnd()
  } catch (error) {
    toast(humanError(error))
  }
}

async function scrollToEnd() {
  await nextTick()
  if (scrollEl.value) scrollEl.value.scrollTop = scrollEl.value.scrollHeight
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  input.value = ''
  bubbles.value.push({ role: 'user', text })
  sending.value = true
  await scrollToEnd()
  try {
    const result = await api.post('/chat', { text, session_key: sessionKey }, undefined, {
      timeoutMs: 120000,
    } as any)
    for (const call of result.tool_calls || []) {
      bubbles.value.push({
        role: 'tool',
        text: `工具 · ${call.name} ${call.ok ? '成功' : '失败'}${call.error ? `：${call.error}` : ''}`,
      })
    }
    bubbles.value.push({ role: 'assistant', text: result.reply || '（没有回复）' })
    if (result.plan_draft) planDraft.value = result.plan_draft
  } catch (error) {
    bubbles.value.push({ role: 'assistant', text: humanError(error) })
  } finally {
    sending.value = false
    await scrollToEnd()
  }
}

async function applyDraft() {
  if (!planDraft.value) return
  try {
    const result = await api.post(`/plans/${planDraft.value.id}/apply`)
    toast(result.created === 0 ? '已写过，没有新增' : `已写入 ${result.created} 个日程`)
    planDraft.value = null
  } catch (error) {
    toast(humanError(error))
  }
}

async function reset() {
  if (!window.confirm('清空当前会话历史？（长期记忆保留）')) return
  try {
    await api.post('/chat/reset', { session_key: sessionKey })
    bubbles.value = []
    planDraft.value = null
    toast('已清空')
  } catch (error) {
    toast(humanError(error))
  }
}

onMounted(loadHistory)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>AI 对话</h1>
        <p>和 QQ 里是同一个 pipeline：同一份日程、同一份记忆</p>
      </div>
      <button class="sm ghost" @click="reset">清空会话</button>
    </div>

    <div class="chat-box">
      <div ref="scrollEl" class="chat-scroll">
        <div v-if="!bubbles.length" class="empty">
          
          试试：「明天下午三点背单词一小时」或「我什么时候有空」
        </div>
        <div v-for="(bubble, index) in bubbles" :key="index" class="bubble" :class="bubble.role">
          {{ bubble.text }}
        </div>
        <div v-if="sending" class="bubble assistant muted">思考中…</div>
      </div>
      <div class="chat-input">
        <input
          v-model="input"
          placeholder="说点什么，或让 AI 排日程…"
          :disabled="sending"
          @keyup.enter="send"
        />
        <button class="primary" :disabled="sending || !input.trim()" @click="send">发送</button>
      </div>
    </div>

    <div v-if="planDraft" class="modal-mask" @click.self="planDraft = null">
      <div class="modal card">
        <h2>计划预览：{{ planDraft.title }}</h2>
        <p class="muted">
          共 {{ planDraft.items }} 项，{{ planDraft.total_minutes }} 分钟，截止
          {{ planDraft.deadline }}
        </p>
        <p class="muted tiny">写入后会出现在日历里；重复确认不会重复创建。</p>
        <div class="row">
          <button class="primary sm" @click="applyDraft">写入日程</button>
          <button class="ghost sm" @click="planDraft = null">先不写</button>
        </div>
      </div>
    </div>
  </div>
</template>
