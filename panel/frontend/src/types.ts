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
