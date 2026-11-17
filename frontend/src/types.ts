export interface Task {
  id: string
  title: string
  note?: string | null
  start_at?: string | null
  end_at?: string | null
  all_day: boolean
  status: 'pending' | 'done' | 'skipped'
  priority: number
  source: string
  plan_item_id?: string | null
  remind_offsets: number[]
  local_date?: string | null
  local_start?: string | null
  local_end?: string | null
}

export interface DayView {
  date: string
  items: Task[]
  total: number
  done: number
  rate: number
  overdue: number
}

export interface PlanItem {
  id: string
  plan_id: string
  seq: number
  title: string
  scheduled_date: string
  duration_min: number
  task_id?: string | null
  status: string
}

export interface Plan {
  id: string
  title: string
  goal?: string | null
  deadline?: string | null
  daily_minutes?: number | null
  status: string
  applied_at?: string | null
  created_at: string
  items: PlanItem[]
  total_minutes: number
  warnings?: string[]
}

export interface Material {
  id: string
  name: string
  type: string
  summary?: string | null
  raw_len: number
  created_at: string
}

export interface MemoryNote {
  id: string
  kind: string
  content: string
  tags: string[]
  importance: number
  source: string
  source_ref?: string | null
  created_at: string
}

export interface BotMemory {
  remote_ref: string
  content: string
  tags: string[]
  adopted: boolean
  synced_at: string
}

export interface PushTarget {
  id: string
  umo: string
  alias?: string | null
  enabled: boolean
}

export interface Notification {
  id: string
  kind: string
  title?: string | null
  content: string
  scheduled_at: string
  status: string
  attempts: number
  sent_at?: string | null
  error?: string | null
}

export interface InfoPayload {
  name: string
  plugin_version: string
  astrbot_version: string
  schema_version: number
  timezone: string
  http: { enabled: boolean; host: string; port: number }
  memory: { active: any; attempts: any[]; sync_mode: string }
  ai: { mode: string; provider_id: string; model: string; available: boolean }
  capabilities: Record<string, unknown>
  counts: { devices: number; tasks: number }
  warnings: string[]
}
