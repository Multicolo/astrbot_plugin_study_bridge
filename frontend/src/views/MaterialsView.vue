<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import { toast } from '../toast'
import type { Material } from '../types'

const materials = ref<Material[]>([])
const loading = ref(false)
const error = ref('')
const name = ref('')
const text = ref('')
const url = ref('')
const busy = ref(false)

async function load() {
  loading.value = true
  error.value = ''
  try {
    materials.value = (await api.get('/materials')).materials
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

async function add() {
  busy.value = true
  try {
    if (url.value.trim()) {
      await api.post('/materials', { url: url.value.trim(), name: name.value || undefined })
      url.value = ''
    } else {
      if (!text.value.trim()) {
        toast('粘贴一些资料内容，或填一个链接')
        return
      }
      await api.post('/materials', { text: text.value, name: name.value || undefined })
      text.value = ''
    }
    name.value = ''
    toast('已添加')
    await load()
  } catch (err) {
    toast(humanError(err))
  } finally {
    busy.value = false
  }
}

async function remove(material: Material) {
  if (!window.confirm(`删除资料「${material.name}」？`)) return
  try {
    await api.del(`/materials/${material.id}`)
    toast('已删除')
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const form = new FormData()
  form.append('file', file)
  form.append('name', file.name)
  busy.value = true
  try {
    const response = await fetch(
      `${localStorage.getItem('study.server') || ''}/api/study/materials`,
      {
        method: 'POST',
        headers: { Authorization: `Bearer ${localStorage.getItem('study.token') || ''}` },
        body: form,
      },
    )
    if (!response.ok) {
      const payload = await response.json().catch(() => null)
      throw new Error(payload?.error?.message || `上传失败（HTTP ${response.status}）`)
    }
    toast('已上传')
    await load()
  } catch (err) {
    toast(humanError(err))
  } finally {
    busy.value = false
    input.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>资料</h1>
        <p>课程笔记、大纲、链接——AI 拆计划前会先读它们</p>
      </div>
    </div>

    <section class="card" style="margin-bottom: 14px">
      <h2>添加资料</h2>
      <div class="grid two">
        <div>
          <div class="field-group">
            <label class="field">名称（可选）</label>
            <input v-model="name" placeholder="例：高数第七版目录" />
          </div>
          <div class="field-group">
            <label class="field">链接</label>
            <input v-model="url" placeholder="https://…（填了链接就忽略下面的文本）" />
          </div>
          <div class="row">
            <button class="primary" :disabled="busy" @click="add">添加</button>
            <label class="btn sm ghost" style="cursor: pointer">
              上传 .txt/.md
              <input type="file" accept=".txt,.md,.markdown,text/plain" style="display: none" @change="upload" />
            </label>
          </div>
        </div>
        <div class="field-group">
          <label class="field">文本内容</label>
          <textarea v-model="text" rows="7" placeholder="粘贴笔记 / 章节目录…"></textarea>
        </div>
      </div>
    </section>

    <StateBlock :loading="loading" :error="error" :empty="!materials.length" empty-text="还没有资料" @retry="load">
      <div class="list">
        <div v-for="material in materials" :key="material.id" class="list-row">
          <span class="badge brand">{{ material.type }}</span>
          <div style="flex: 1; min-width: 0">
            <div class="title">{{ material.name }}</div>
            <div class="muted tiny">
              {{ material.raw_len }} 字符 · {{ new Date(material.created_at).toLocaleString('zh-CN') }}
            </div>
          </div>
          <button class="sm danger ghost" @click="remove(material)">删除</button>
        </div>
      </div>
    </StateBlock>
  </div>
</template>
