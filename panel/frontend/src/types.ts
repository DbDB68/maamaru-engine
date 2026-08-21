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
}

export interface InventoryGap {
  gap_key: string
  started_at: number
  ended_at: number
  resource_delta?: Record<string, number>
  reported?: boolean
}
