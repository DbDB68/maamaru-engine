export type Option = string | [string, string]

export interface VisibilityRule {
  key: string
  is?: string
  not?: string
}

export interface ParamField {
  key: string
  type: 'select' | 'number' | 'text' | 'checks' | 'note' | 'toggle'
  label?: string
  default?: unknown
  options?: Option[]
  min?: number
  max?: number
  help?: string
  text?: string
  placeholder?: string
  swords?: boolean
  visibleWhen?: VisibilityRule
}

export interface ScriptInfo {
  label: string
  desc: string
  params: ParamField[]
}

export interface ScriptsResponse {
  running: boolean
  current: string | null
  scripts: Record<string, ScriptInfo>
  event_hidden?: string[]
}

// ---- 自定义工作流 /api/workflows ----

export interface WorkflowNode {
  type: string
  params: ScriptParams
  on_error: 'stop' | 'continue'
}

export interface WorkflowPreset {
  id: string
  name: string
  nodes: WorkflowNode[]
}

export type WorkflowNodeCategory = 'cold' | 'chore' | 'battle' | 'finish'

export interface WorkflowNodeDef {
  type: string
  label: string
  desc: string
  category: WorkflowNodeCategory
  params: ParamField[]
}

export type ScriptParams = Record<string, unknown>

// ---- 本丸成绩单 /api/data/resource-ledger ----

export interface LedgerAttribution {
  id: string
  ts: number
  resource: string
  delta: number
  source: string
  script?: string
  run_id?: string
  event_id?: number
  label?: string
  confidence?: string
}

export interface LedgerDay {
  date: string
  resource: string
  opening?: number | null
  closing?: number | null
  total_delta: number | null
  attributed_delta?: number
  unattributed_delta?: number | null
  observation_count?: number
  confidence?: string
  attribution_ids?: string[]
  gap_ids?: string[]
}

export interface LedgerResource {
  resource: string
  opening: number | null
  closing: number | null
  total_delta: number | null
  attributed_delta: number
  unattributed_delta: number | null
  observation_count: number
  confidence: string
}

export interface ResourceLedger {
  schema_version: number
  generated_at: number
  window: { from: number; to: number; timezone: string; days: number }
  per_resource: LedgerResource[]
  daily_series: LedgerDay[]
  gaps: any[]
  attributions: LedgerAttribution[]
}

export interface HumanReport {
  id: number
  occurred_at: number
  activities?: string[]
  note?: string
  source?: string
  gap_key?: string | null
  resource?: string | null
  claimed_delta?: number | null
  group_id?: string | null
}

export interface ManualSession {
  id: number
  created_at: number
  script: string
  activity: string
  started_at: number
  ended_at: number
  loops: number
  duration_seconds: number
  average_loop_seconds: number
  note?: string
  source: 'manual'
}

export interface ManualInventory {
  id: number
  ts: number
  captured_at: string
  source: 'manual_entry' | 'manual_import'
  resources: Record<string, number>
}

export interface LedgerImportItem {
  kind: 'transaction' | 'inventory' | 'session'
  row: number
  status: 'new' | 'duplicate' | 'conflict'
  detail: string
  summary: string
}

export interface LedgerImportPreview {
  ok: boolean
  schema_version: number
  preview_id: string
  filename: string
  source_sha256: string
  counts: { new: number; duplicate: number; conflict: number; invalid: number; ignored: number }
  items: LedgerImportItem[]
  issues: Array<{ row: number; ignored: boolean; reason: string }>
}

export interface LedgerOnboarding {
  schema_version: number
  visible: boolean
  status: 'pending' | 'active' | 'completed' | 'dismissed' | 'not_needed'
  step: 1 | 2 | 3
  has_inventory: boolean
  reason: string
}

export interface ActivityPace {
  source: 'maamaru' | 'manual'
  secondsPerLoop: number
  loops: number
  runStartedAt: number
}

export interface InventoryGap {
  gap_key: string
  started_at: number
  ended_at: number
  resource_delta?: Record<string, number>
  reported?: boolean
}

// ---- 规划建议 /api/planning ----

export interface PlanningGoalAdvice {
  id: number
  kind?: 'resource' | 'event'
  event?: string | null
  goal_mode?: 'budget' | 'stock_target' | 'combined' | 'amount_target' | 'deadline_target' | null
  resource: string
  target: number | null
  deadline: string | null
  estimated_deadline?: string | null
  deadline_at?: string | null
  note?: string
  days_left: number | null
  current: number | null
  rate: number | null
  projected: number | null
  shortfall: number | null
  extra_daily: number | null
  extra_floors: number | null
  floors_needed?: number | null
  floors_per_day?: number | null
  seconds_per_floor?: number | null
  speed_sample_floors?: number | null
  estimated_seconds?: number | null
  remaining_seconds?: number | null
  time_margin_seconds?: number | null
  can_finish?: boolean | null
  status: 'done' | 'on_track' | 'behind' | 'active' | 'expired' | 'unknown'
  message: string
}

export interface PlanningReport {
  schema_version: number
  generated_at: number
  today: string
  rate_window_days: number
  rates: Record<string, { daily: number | null; days_observed: number }>
  koban_per_floor: { per_floor: number; sessions: number } | null
  osaka_floor_speed?: { seconds_per_floor: number; floors: number; run_started_at?: number | null } | null
  current?: Record<string, number | null>
  goals: PlanningGoalAdvice[]
  events?: EventAbacus[]
}

// ---- 活动日历 /api/events ----

export interface EventAnnouncement {
  title: string
  publish_time: number
  publish_date: string | null
  update_date: string | null
  events: string[]
  url: string | null
}

export interface EventsCalendar {
  generated_at?: number
  source?: string
  announcements: EventAnnouncement[]
  stale: boolean
  reason?: string
}

// ---- 活动算盘（/api/planning 的 events 字段） ----

export interface EventAbacus {
  event: string
  goal_mode?: 'budget' | 'stock_target'
  goal_resource?: string
  start_date: string | null
  end_date: string | null
  keys_total: number
  boxes: number | null
  ticket_price: number
  daily_free_tickets: number
  note: string
  keys_per_run: number | null
  keys_source: 'measured' | 'history' | 'estimate' | null
  keys_basis?: string | null
  runs_needed: number | null
  free_runs: number | null
  paid_tickets: number | null
  koban_cost: number | null
  days_left: number | null
  available_now: number | null
  sufficient: boolean | null
  shortfall: number | null
  yield_per_floor?: number | null
  yield_sessions?: number | null
  message: string
}

export interface EventGoalResult {
  ok: boolean
  sufficient: boolean | null
  goal: Record<string, unknown> | null
  goal_mode?: 'budget' | 'stock_target'
  target?: number
  koban_cost: number | null
  available_now: number | null
  shortfall: number | null
}

// ---- 事件时间轴 /api/events/timeline ----

export interface EventTimelineBudget {
  koban_cost: number | null
  available_now: number | null
  shortfall: number | null
  sufficient: boolean | null
  message: string
}

export interface EventTimelineEntry {
  name: string
  precise: boolean
  start_at: string | null
  end_at: string | null
  start_date: string
  end_date: string | null
  note: string
  days_left: number | null
  days_until_start?: number
  budget: EventTimelineBudget | null
}

export interface EventTimelineCandidate {
  name: string | null
  section: string | null
  start_at: string | null
  end_at: string | null
  announcement: string | null
  url: string | null
}

export interface EventTimelineReport {
  generated_at: string
  calendar_stale: boolean
  ongoing: EventTimelineEntry[]
  upcoming: EventTimelineEntry[]
  later: EventTimelineEntry[]
  unverified: EventTimelineCandidate[]
}

// ---- 异常与通知中心 /api/incidents ----

export interface Incident {
  code: string
  severity: 'info' | 'warning' | 'urgent'
  title: string
  cause: string
  action: string
  needs_human: boolean
  entry: { tab?: string; script?: string }
  status: 'active' | 'acknowledged' | 'resolved'
  first_seen: number
  last_seen: number
  count: number
}
