import { defineComponent, h } from 'vue'
import { Inbox } from 'lucide-vue-next'

/**
 * 统一的加载 / 空态 / 错误块：
 * - loading: 骨架屏
 * - error: 可重试的错误提示
 * - empty: 空态（一个图标 + 一句事实 + 可选动作）
 *
 * 图标只用 Lucide 一套，不用 emoji（见 DESIGN.md）。
 */
export const StateBlock = defineComponent({
  name: 'StateBlock',
  props: {
    loading: { type: Boolean, default: false },
    error: { type: String, default: '' },
    empty: { type: Boolean, default: false },
    emptyText: { type: String, default: '这里还没有内容' },
  },
  emits: ['retry'],
  setup(props, { slots, emit }) {
    return () => {
      if (props.loading) {
        return h('div', { class: 'card' }, [
          h('div', { class: 'skeleton', style: 'width:60%' }),
          h('div', { class: 'skeleton', style: 'width:86%' }),
          h('div', { class: 'skeleton', style: 'width:74%' }),
        ])
      }
      if (props.error) {
        return h('div', { class: 'alert error' }, [
          h('div', { style: 'margin-bottom:8px' }, props.error),
          h('button', { class: 'sm ghost', onClick: () => emit('retry') }, '重试'),
        ])
      }
      if (props.empty) {
        return h('div', { class: 'empty' }, [
          h('span', { class: 'empty-icon' }, [h(Inbox, { size: 22, strokeWidth: 1.6 })]),
          h('div', props.emptyText),
          slots.default ? h('div', { style: 'margin-top:12px' }, slots.default()) : null,
        ])
      }
      return slots.default ? slots.default() : null
    }
  },
})

export default StateBlock
