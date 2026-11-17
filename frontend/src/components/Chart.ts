import { defineComponent, h, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

/**
 * 极薄的 ECharts 包装：
 * - 挂载后初始化（保证容器真实存在，避免 ref 为空导致图表不渲染）
 * - option 变化时整体重设
 * - 监听窗口 resize
 */
export default defineComponent({
  name: 'Chart',
  props: {
    option: { type: Object, required: true },
  },
  setup(props) {
    const el = ref<HTMLDivElement | null>(null)
    let chart: echarts.ECharts | null = null

    function resize() {
      chart?.resize()
    }

    onMounted(() => {
      if (!el.value) return
      chart = echarts.init(el.value)
      chart.setOption(props.option)
      window.addEventListener('resize', resize)
    })

    watch(
      () => props.option,
      (value) => {
        chart?.setOption(value, true)
      },
      { deep: true },
    )

    onBeforeUnmount(() => {
      window.removeEventListener('resize', resize)
      chart?.dispose()
      chart = null
    })

    return () =>
      h('div', {
        class: 'chart',
        ref: (value: any) => {
          el.value = value as HTMLDivElement | null
        },
      })
  },
})
