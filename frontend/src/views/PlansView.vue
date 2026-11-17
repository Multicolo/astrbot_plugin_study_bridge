<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api, humanError } from '../api'
import StateBlock from '../components/StateBlock'
import { toast } from '../toast'
import type { Material, Plan } from '../types'

const plans = ref<Plan[]>([])
const detail = ref<Plan | null>(null)
const materials = ref<Material[]>([])
const loading = ref(false)
const error = ref('')
const generating = ref(false)

const goal = ref('')
const dailyMinutes = ref(60)
const deadline = ref('')
const selectedMaterials = ref<string[]>([])
const confirmApply = ref(false)

const today = new Date().toISOString().slice(0, 10)
const defaultDeadline = computed(() => {
  const date = new Date()
  date.setDate(date.getDate() + 13)
  return date.toISOString().slice(0, 10)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [planData, materialData] = await Promise.all([
      api.get('/plans'),
      api.get('/materials'),
    ])
    plans.value = planData.plans
    materials.value = materialData.materials
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

async function generate() {
  if (!goal.value.trim()) {
    toast('先写下目标，例如「考研数学 14 天冲刺」')
    return
  }
  generating.value = true
  try {
    const plan = await api.post('/plans/generate', {
      goal: goal.value.trim(),
      daily_minutes: Number(dailyMinutes.value),
      deadline: deadline.value || defaultDeadline.value,
      material_ids: selectedMaterials.value,
    })
    detail.value = plan
    toast('计划已生成，确认后再写入日程')
    await load()
  } catch (err) {
    toast(humanError(err))
  } finally {
    generating.value = false
  }
}

async function open(plan: Plan) {
  try {
    detail.value = await api.get(`/plans/${plan.id}`)
  } catch (err) {
    toast(humanError(err))
  }
}

async function doApply() {
  if (!detail.value) return
  try {
    const result = await api.post(`/plans/${detail.value.id}/apply`)
    toast(
      result.created === 0
        ? '已写过（幂等），没有新增'
        : `已写入 ${result.created} 个日程，跳过 ${result.skipped}`,
    )
    confirmApply.value = false
    detail.value = await api.get(`/plans/${detail.value.id}`)
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function rollback() {
  if (!detail.value) return
  if (!window.confirm('撤销这个计划写入的日程？（被改过的任务会跳过）')) return
  try {
    const result = await api.post(`/plans/${detail.value.id}/rollback`)
    toast(`已撤销 ${result.deleted} 个，跳过 ${result.skipped.length} 个`)
    detail.value = await api.get(`/plans/${detail.value.id}`)
    await load()
  } catch (err) {
    toast(humanError(err))
  }
}

async function remove(plan: Plan) {
  if (!window.confirm(`删除计划「${plan.title}」？`)) return
  try {
    await api.del(`/plans/${plan.id}`)
    if (detail.value?.id === plan.id) detail.value = null
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
        <h1>计划</h1>
        <p>AI 拆解 → 预览 → 你确认后才写入日程</p>
      </div>
    </div>

    <section class="card" style="margin-bottom: 14px">
      <h2>新建计划</h2>
      <div class="grid two">
        <div class="field-group">
          <label class="field">目标</label>
          <input v-model="goal" placeholder="例：考研数学 14 天冲刺" />
        </div>
        <div class="field-group">
          <label class="field">每天可用分钟</label>
          <input v-model.number="dailyMinutes" type="number" min="5" max="720" />
        </div>
      </div>
      <div class="grid two">
        <div class="field-group">
          <label class="field">截止日期</label>
          <input v-model="deadline" type="date" :min="today" :placeholder="defaultDeadline" />
        </div>
        <div class="field-group">
          <label class="field">参考资料（可选）</label>
          <select
            v-if="materials.length"
            v-model="selectedMaterials"
            multiple
            size="3"
            style="height: 96px"
          >
            <option v-for="item in materials" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
          <p v-else class="muted" style="margin: 0">还没有资料，去「资料」页添加后再选</p>
        </div>
      </div>
      <button class="primary" :disabled="generating" @click="generate">
        {{ generating ? 'AI 拆解中…' : '生成计划（仅预览）' }}
      </button>
    </section>

    <div class="grid two">
      <section class="card">
        <div class="row between">
          <h2>我的计划</h2>
          <button class="sm ghost" @click="load">刷新</button>
        </div>
        <StateBlock :loading="loading" :error="error" :empty="!plans.length" empty-text="还没有计划" @retry="load">
          <div class="list">
            <div v-for="plan in plans" :key="plan.id" class="list-row">
              <div style="flex: 1; min-width: 0">
                <div class="title">{{ plan.title }}</div>
                <div class="muted tiny">
                  截止 {{ plan.deadline || '未设置' }} · 每天 {{ plan.daily_minutes }} 分钟
                  <span class="badge" :class="plan.applied_at ? 'ok' : 'warn'" style="margin-left: 6px">
                    {{ plan.applied_at ? '已写入' : '未写入' }}
                  </span>
                </div>
              </div>
              <button class="sm" @click="open(plan)">查看</button>
              <button class="sm danger ghost" @click="remove(plan)">删除</button>
            </div>
          </div>
        </StateBlock>
      </section>

      <section class="card">
        <h2>计划详情</h2>
        <div v-if="!detail" class="empty">
          选一个计划看详情
        </div>
        <div v-else>
          <div class="row between">
            <div>
              <strong>{{ detail.title }}</strong>
              <div class="muted tiny">
                {{ detail.items.length }} 项 · 共 {{ detail.total_minutes }} 分钟 · 截止
                {{ detail.deadline || '—' }}
              </div>
            </div>
            <span class="badge" :class="detail.applied_at ? 'ok' : 'warn'">
              {{ detail.applied_at ? '已写入' : '未写入' }}
            </span>
          </div>

          <div class="list" style="margin-top: 12px; max-height: 320px; overflow: auto">
            <div v-for="item in detail.items" :key="item.id" class="list-row">
              <span class="badge">{{ item.seq }}</span>
              <div style="flex: 1; min-width: 0">
                <div class="title">{{ item.title }}</div>
                <div class="muted tiny">{{ item.scheduled_date }} · {{ item.duration_min }} 分钟</div>
              </div>
              <span class="badge" :class="item.task_id ? 'ok' : ''">{{ item.status }}</span>
            </div>
          </div>

          <div class="row" style="margin-top: 12px">
            <button class="primary sm" :disabled="Boolean(detail.applied_at)" @click="confirmApply = true">
              写入日程
            </button>
            <button class="sm ghost" :disabled="!detail.applied_at" @click="rollback">撤销写入</button>
          </div>
        </div>
      </section>
    </div>

    <div v-if="confirmApply" class="modal-mask" @click.self="confirmApply = false">
      <div class="modal card">
        <h2>确认写入日程？</h2>
        <p class="muted">
          将把 {{ detail?.items.length }} 个条目写入日历（每日 19:00 开始，按条目时长结束）。
          重复点击不会重复创建。
        </p>
        <div class="row">
          <button class="primary sm" @click="doApply">确认写入</button>
          <button class="ghost sm" @click="confirmApply = false">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>
