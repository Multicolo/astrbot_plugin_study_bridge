<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, humanError } from '../api'
import Chart from '../components/Chart'
import StateBlock from '../components/StateBlock'

const range = ref('week')
const overview = ref<any>(null)
const progress = ref<any[]>([])
const loading = ref(false)
const error = ref('')

const lineOption = computed(() => {
  const daily = overview.value?.daily || []
  return {
    backgroundColor: 'transparent',
    grid: { left: 36, right: 16, top: 28, bottom: 28 },
    tooltip: { trigger: 'axis' },
    legend: { data: ['完成', '总数'], textStyle: { color: '#8b6b77' }, top: 0 },
    xAxis: {
      type: 'category',
      data: daily.map((item: any) => item.date.slice(5)),
      axisLine: { lineStyle: { color: '#f2d8e2' } },
      axisLabel: { color: '#8b6b77' },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      splitLine: { lineStyle: { color: '#f7e4ec' } },
      axisLabel: { color: '#8b6b77' },
    },
    series: [
      {
        name: '完成',
        type: 'line',
        smooth: true,
        data: daily.map((item: any) => item.done),
        itemStyle: { color: '#d6336c' },
        areaStyle: { color: 'rgba(214,51,108,0.10)' },
      },
      {
        name: '总数',
        type: 'line',
        smooth: true,
        data: daily.map((item: any) => item.total),
        itemStyle: { color: '#c9a7b4' },
        lineStyle: { type: 'dashed' },
      },
    ],
  }
})

const pieOption = computed(() => {
  const sources = Object.entries(overview.value?.sources || {}).map(([name, value]) => ({
    name,
    value,
  }))
  return {
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item' },
    color: ['#d6336c', '#e885a8', '#b02a57', '#f0c2d2'],
    series: [
      {
        type: 'pie',
        radius: ['46%', '72%'],
        data: sources.length ? sources : [{ name: '暂无数据', value: 1 }],
        label: { color: '#8b6b77', formatter: '{b} {d}%' },
        itemStyle: { borderColor: '#ffffff', borderWidth: 2 },
      },
    ],
  }
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [data, planData] = await Promise.all([
      api.get(`/stats/overview?range=${range.value}`),
      api.get('/stats/plan-progress'),
    ])
    overview.value = data
    progress.value = planData.plans
  } catch (err) {
    error.value = humanError(err)
  } finally {
    loading.value = false
  }
}

watch(range, load)
onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <div>
        <h1>报表</h1>
        <p>完成率、趋势、来源与计划进度</p>
      </div>
      <div class="tabs" style="margin: 0">
        <button :class="{ active: range === 'today' }" @click="range = 'today'">今日</button>
        <button :class="{ active: range === 'week' }" @click="range = 'week'">本周</button>
        <button :class="{ active: range === 'month' }" @click="range = 'month'">本月</button>
      </div>
    </div>

    <StateBlock :loading="loading" :error="error" @retry="load">
      <div class="grid three" style="margin-bottom: 12px">
        <div class="card stat">
          <div class="stat-label">完成率</div>
          <div class="stat-value">{{ overview?.rate ?? 0 }}%</div>
          <div class="muted">{{ overview?.done ?? 0 }} / {{ overview?.total ?? 0 }}</div>
        </div>
        <div class="card stat">
          <div class="stat-label">专注时长</div>
          <div class="stat-value">{{ overview?.minutes ?? 0 }}</div>
          <div class="muted">分钟（已完成任务）</div>
        </div>
        <div class="card stat">
          <div class="stat-label">区间</div>
          <div class="stat-value" style="font-size: 18px">{{ overview?.start }}</div>
          <div class="muted">至 {{ overview?.end }}</div>
        </div>
      </div>

      <div class="grid two">
        <section class="card">
          <h2>每日完成趋势</h2>
          <Chart :option="lineOption" />
        </section>
        <section class="card">
          <h2>任务来源占比</h2>
          <Chart :option="pieOption" />
        </section>
      </div>

      <section class="card" style="margin-top: 12px">
        <h2>计划进度</h2>
        <div v-if="!progress.length" class="empty">
          还没有已写入的计划
        </div>
        <div v-else class="list">
          <div v-for="plan in progress" :key="plan.plan_id" style="margin-bottom: 12px">
            <div class="row between">
              <strong>{{ plan.title }}</strong>
              <span class="muted">{{ plan.done }}/{{ plan.total }} · {{ plan.rate }}%</span>
            </div>
            <div class="bar" style="margin-top: 6px">
              <i :style="{ width: `${plan.rate}%` }" />
            </div>
          </div>
        </div>
      </section>
    </StateBlock>
  </div>
</template>
