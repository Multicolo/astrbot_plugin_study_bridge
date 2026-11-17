<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import { toast } from '../toast'
import type { BotMemory, MemoryNote } from '../types'

const tab = ref<'study' | 'bot'>('study')
const notes = ref<MemoryNote[]>([])
const botNotes = ref<BotMemory[]>([])
const status = ref<any>(null)
const loading = ref(false)
const error = ref('')

const kind = ref('preference')
const content = ref('')
const importance = ref(3)
const busy = ref(false)

const kinds = [
  { value: 'preference', label: '偏好' },
  { value: 'goal', label: '目标' },
  { value: 'fact', label: '事实' },
  { value: 'mistake', label: '常错点' },
  { value: 'constraint', label: '限制' },
]

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [noteData, botData, syncData] = await Promise.all([
      api.get('/memory/notes'),
      api.get('/memory/bot'),
      api.get('/memory/sync-status'),
    ])
    notes.value = noteData.notes
    botNotes.value = botData.entries
    status.value = syncData
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

async function addNote() {
  if (!content.value.trim()) {
    toast('先写点内容，例如「晚上 8 点后才有空」')
    return
  }
  busy.value = true
  try {
    await api.post('/memory/notes', {
      kind: kind.value,
      content: content.value.trim(),
      importance: Number(importance.value),
    })
    content.value = ''
    toast('已记住')
    await load()
  } catch (err) {
    toast(humanError(err))
  } finally {
    busy.value = false
  }
}

async function updateImportance(note: MemoryNote, value: number) {
  try {
    await api.patch(`/memory/notes/${note.id}`, { importance: value })
    toast('已更新重要性')
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function removeNote(note: MemoryNote) {
  if (!window.confirm(`删除记忆「${note.content.slice(0, 20)}…」？`)) return
  try {
    await api.del(`/memory/notes/${note.id}`)
    toast('已删除')
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function adopt(entry: BotMemory) {
  try {
    await api.post(`/memory/bot/${encodeURIComponent(entry.remote_ref)}/adopt`)
    toast('已采纳为学习记忆')
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function compact() {
  try {
    const result = await api.post('/memory/compact')
    toast(`已合并 ${result.removed} 条相似记忆`)
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
        <h1>记忆中心</h1>
        <p>学习记忆可编辑；bot 记忆只读，可一键采纳</p>
      </div>
      <button class="sm ghost" :disabled="busy" @click="compact">合并相似记忆</button>
    </div>

    <div class="tabs">
      <button :class="{ active: tab === 'study' }" @click="tab = 'study'">学习记忆</button>
      <button :class="{ active: tab === 'bot' }" @click="tab = 'bot'">bot 记忆</button>
    </div>

    <section v-if="status" class="card" style="margin-bottom: 14px">
      <div class="row between">
        <div>
          <div class="muted tiny">适配器</div>
          <div>
            <span class="badge" :class="status.adapter.ok ? 'ok' : 'warn'">{{ status.adapter.name }}</span>
            <span class="muted tiny" style="margin-left: 8px">{{ status.adapter.reason }}</span>
          </div>
        </div>
        <div>
          <div class="muted tiny">同步模式</div>
          <div>{{ status.mode }}</div>
        </div>
        <div>
          <div class="muted tiny">待同步</div>
          <div>{{ status.pending_outbox }}</div>
        </div>
        <div>
          <div class="muted tiny">orphan</div>
          <div>{{ status.orphan }}</div>
        </div>
      </div>
      <div v-if="status.orphan" class="alert warn" style="margin-top: 10px">
        有 {{ status.orphan }} 条记忆远端不支持删除，已如实标记 orphan（不会假装删成功）。
      </div>
    </section>

    <StateBlock
      :loading="loading"
      :error="error"
      :empty="tab === 'study' ? !notes.length : !botNotes.length"
      :empty-text="tab === 'study' ? '还没有记住任何东西' : 'bot 侧还没有可同步的记忆'"
      @retry="load"
    >
      <div v-if="tab === 'study'" class="list">
        <div v-for="note in notes" :key="note.id" class="list-row">
          <span class="badge brand">{{ note.kind }}</span>
          <div style="flex: 1; min-width: 0">
            <div class="title">{{ note.content }}</div>
            <div class="muted tiny">
              {{ note.source }} · {{ new Date(note.created_at).toLocaleDateString('zh-CN') }}
              <span v-if="note.source_ref" class="mono"> · {{ note.source_ref }}</span>
            </div>
          </div>
          <select
            :value="note.importance"
            style="width: 88px"
            @change="updateImportance(note, Number(($event.target as HTMLSelectElement).value))"
          >
            <option v-for="level in [1, 2, 3, 4, 5]" :key="level" :value="level">重要度 {{ level }}</option>
          </select>
          <button class="sm danger ghost" @click="removeNote(note)">删除</button>
        </div>
      </div>

      <div v-else class="list">
        <div v-for="entry in botNotes" :key="entry.remote_ref" class="list-row">
          <span class="badge" :class="entry.adopted ? 'ok' : ''">{{ entry.adopted ? '已采纳' : '未采纳' }}</span>
          <div style="flex: 1; min-width: 0">
            <div class="title">{{ entry.content }}</div>
            <div class="muted tiny">{{ new Date(entry.synced_at).toLocaleString('zh-CN') }}</div>
          </div>
          <button class="sm" :disabled="entry.adopted" @click="adopt(entry)">采纳</button>
        </div>
      </div>
    </StateBlock>

    <section v-if="tab === 'study'" class="card" style="margin-top: 14px">
      <h2>新增记忆</h2>
      <p class="muted tiny">
        超过 200 字、含代码块/结构化块的文本会被污染过滤器拒绝（防污染规则见 docs/MEMORY_SYNC.md）。
      </p>
      <div class="row">
        <select v-model="kind" style="width: 130px">
          <option v-for="item in kinds" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
        <input v-model="content" placeholder="记忆内容（≤200 字）" style="flex: 1" />
        <select v-model.number="importance" style="width: 110px">
          <option v-for="level in [1, 2, 3, 4, 5]" :key="level" :value="level">重要度 {{ level }}</option>
        </select>
        <button class="primary sm" :disabled="busy" @click="addNote">记住</button>
      </div>
    </section>
  </div>
</template>
