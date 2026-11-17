import { reactive } from 'vue'

export interface Toast {
  id: number
  text: string
  kind: 'info' | 'error'
}

let seq = 0
export const toasts = reactive<Toast[]>([])

export function toast(text: string, kind: 'info' | 'error' = 'info') {
  const item: Toast = { id: ++seq, text, kind }
  toasts.push(item)
  setTimeout(() => {
    const index = toasts.findIndex((entry) => entry.id === item.id)
    if (index >= 0) toasts.splice(index, 1)
  }, kind === 'error' ? 4200 : 2200)
}

export function toastError(error: unknown) {
  const text = error instanceof Error ? error.message : String(error)
  toast(text, 'error')
}
