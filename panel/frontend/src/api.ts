import type { ScriptParams, ScriptsResponse } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail || body.error || body.reason || `请求失败（${response.status}）`)
  return body as T
}

export const api = {
  scripts: () => request<ScriptsResponse>('/api/scripts'),
  settings: () => request<{ params?: Record<string, ScriptParams>; theme?: string }>('/api/saved-settings'),
  saveSettings: (params: Record<string, ScriptParams>) => request<{ ok: boolean }>('/api/saved-settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
  }),
  saveTheme: (theme: string) => request<{ ok: boolean }>('/api/saved-settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ theme }),
  }),
  run: (script: string, params: ScriptParams) => request<{ ok: boolean }>('/api/scripts/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ script, params }),
  }),
  stop: () => request<{ ok: boolean }>('/api/scripts/stop', { method: 'POST' }),
  dashboard: () => request<any>('/api/dashboard'),
  dataSummary: (days = 30) => request<any>(`/api/data/summary?days=${days}`),
  dataEvents: (limit = 100) => request<{ schema_version: number; items: any[] }>(`/api/data/events?limit=${limit}`),
  dataRuns: (limit = 20) => request<{ schema_version: number; items: any[] }>(`/api/data/runs?limit=${limit}`),
  attachRunInventory: (runId: string) => request<{ ok: boolean; run: any }>(`/api/data/runs/${encodeURIComponent(runId)}/attach-inventory`, { method: 'POST' }),
  humanReports: () => request<{ schema_version: number; items: any[]; inventory_gaps: any[] }>('/api/data/human-reports?limit=500'),
  addHumanReport: (value: any) => request<{ ok: boolean; item: any }>('/api/data/human-reports', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  deleteHumanReport: (id: number) => request<{ ok: boolean }>(`/api/data/human-reports/${id}`, { method: 'DELETE' }),
  logs: () => request<{ logs: any[] }>('/api/logs?limit=200'),
  chatHistory: () => request<{ history: Array<{ role: string; content: string; ts: number }> }>('/api/chat/history'),
  chat: (message: string) => request<{ reply: string }>('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message }),
  }),
  configLists: () => request<Record<string, string[]>>('/api/config-lists'),
  swords: () => request<{ swords: Array<{ id: string; name: string; name_zh: string; type: string }> }>('/api/swords'),
  saveConfigLists: (value: Record<string, string[]>) => request<{ ok: boolean }>('/api/config-lists', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  expeditionSchedule: () => request<any>('/api/expedition-schedule'),
  saveExpeditionSchedule: (value: any) => request<{ ok: boolean }>('/api/expedition-schedule', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  pauseExpeditions: (minutes: number) => request<{ ok: boolean; paused_until: string }>('/api/expedition-pause', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ minutes }),
  }),
  chatConfig: () => request<any>('/api/chat-config'),
  botConfig: () => request<any>('/api/bot-config'),
  qqStatus: () => request<any>('/api/qq-status'),
  saveChatConfig: (value: any) => request<{ ok: boolean }>('/api/chat-config', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  saveBotConfig: (value: any) => request<any>('/api/bot-config', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
}
