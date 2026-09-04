import type { EventGoalResult, EventTimelineReport, EventsCalendar, HomeLayout, HomeLayoutEntry, Incident, LedgerImportPreview, LedgerOnboarding, ManualInventory, ManualSession, PlanningReport, ResourceLedger, ScriptParams, ScriptsResponse, WorkflowNodeDef, WorkflowPreset } from './types'

import type { HonmaruHomeData, HonmaruProfile, HonmaruNote, WorkflowIdentity } from './types'

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  const body = await response.json()
  if (!response.ok) throw new Error(body.detail || body.error || body.reason || `请求失败（${response.status}）`)
  return body as T
}

export const api = {
  honmaruHome: () => request<HonmaruHomeData>('/api/honmaru-home'),
  saveHonmaruProfile: (profile: HonmaruProfile) => request<{ profile: HonmaruProfile }>('/api/honmaru-home/profile', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(profile),
  }),
  saveHonmaruNote: (body: string, id?: string) => request<{ note: HonmaruNote }>(`/api/honmaru-home/notes${id ? `/${encodeURIComponent(id)}` : ''}`, {
    method: id ? 'PUT' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ body }),
  }),
  appMode: () => request<{ mode: 'automation' | 'ledger'; automation_enabled: boolean }>('/api/app-mode'),
  scripts: () => request<ScriptsResponse>('/api/scripts'),
  settings: () => request<{ params?: Record<string, ScriptParams>; theme?: string; backdrop?: string }>('/api/saved-settings'),
  saveSettings: (params: Record<string, ScriptParams>) => request<{ ok: boolean }>('/api/saved-settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ params }),
  }),
  saveTheme: (theme: string) => request<{ ok: boolean }>('/api/saved-settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ theme }),
  }),
  saveBackdrop: (backdrop: string) => request<{ ok: boolean }>('/api/saved-settings', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ backdrop }),
  }),
  run: (script: string, params: ScriptParams) => request<{ ok: boolean; workflow?: WorkflowIdentity | null }>('/api/scripts/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ script, params }),
  }),
  stop: () => request<{ ok: boolean }>('/api/scripts/stop', { method: 'POST' }),
  workflows: () => request<{ presets: WorkflowPreset[] }>('/api/workflows'),
  homeLayout: () => request<HomeLayout>('/api/home-layout'),
  saveHomeLayout: (order: string[], hidden: string[]) => request<{ ok: boolean; entries: HomeLayoutEntry[] }>('/api/home-layout', {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order, hidden }),
  }),
  workflowNodes: () => request<{ nodes: WorkflowNodeDef[] }>('/api/workflows/nodes'),
  createWorkflow: (preset: Omit<WorkflowPreset, 'id'>) => request<{ ok: boolean; id?: string }>('/api/workflows', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(preset),
  }),
  updateWorkflow: (preset: WorkflowPreset) => request<{ ok: boolean }>(`/api/workflows/${encodeURIComponent(preset.id)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(preset),
  }),
  deleteWorkflow: (id: string) => request<{ ok: boolean }>(`/api/workflows/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  dashboard: () => request<any>('/api/dashboard'),
  dataSummary: (days = 30) => request<any>(`/api/data/summary?days=${days}`),
  resourceLedger: (days = 7) => request<ResourceLedger>(`/api/data/resource-ledger?days=${days}`),
  ledgerOnboarding: () => request<LedgerOnboarding>('/api/data/ledger-onboarding'),
  updateLedgerOnboarding: (action: 'start' | 'advance' | 'complete' | 'dismiss', step?: 2 | 3) => request<LedgerOnboarding & { ok: boolean }>('/api/data/ledger-onboarding', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, step }),
  }),
  ledgerExport: async (format: 'xlsx' | 'csv') => {
    const response = await fetch(`/api/data/ledger-export?format=${format}`)
    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.detail || body.error || body.reason || `导出失败（${response.status}）`)
    }
    const disposition = response.headers.get('Content-Disposition') || ''
    const matched = disposition.match(/filename\*=UTF-8''([^;]+)/i)
    return { blob: await response.blob(), filename: matched ? decodeURIComponent(matched[1]) : `maamaru-ledger.${format}` }
  },
  previewLedgerImport: (file: File) => request<LedgerImportPreview>(`/api/data/ledger-import/preview?filename=${encodeURIComponent(file.name)}`, {
    method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
  }),
  applyLedgerImport: (previewId: string, acceptConflicts: boolean) => request<{ ok: boolean; imported: number; duplicates: number; conflicts: number; backup: string | null }>('/api/data/ledger-import/apply', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ preview_id: previewId, accept_conflicts: acceptConflicts }),
  }),
  manualInventory: (limit = 200) => request<{ schema_version: number; items: ManualInventory[] }>(`/api/data/manual-inventory?limit=${limit}`),
  addManualInventory: (resources: Record<string, number>, observedAt?: number) => request<{ ok: boolean; snapshot: ManualInventory }>('/api/data/manual-inventory', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resources, observed_at: observedAt }),
  }),
  updateManualInventory: (id: number, resources: Record<string, number>, observedAt: number) => request<{ ok: boolean; snapshot: ManualInventory }>(`/api/data/manual-inventory/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ resources, observed_at: observedAt }),
  }),
  deleteManualInventory: (id: number) => request<{ ok: boolean }>(`/api/data/manual-inventory/${id}`, { method: 'DELETE' }),
  manualSessions: (limit = 200, fromTs?: number, toTs?: number) => request<{ schema_version: number; items: ManualSession[] }>(`/api/data/manual-sessions?limit=${limit}${fromTs == null ? '' : `&from_ts=${fromTs}`}${toTs == null ? '' : `&to_ts=${toTs}`}`),
  addManualSession: (value: { script: string; started_at: number; ended_at: number; loops: number; note?: string }) => request<{ ok: boolean; item: ManualSession }>('/api/data/manual-sessions', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  updateManualSession: (id: number, value: { script: string; started_at: number; ended_at: number; loops: number; note?: string }) => request<{ ok: boolean; item: ManualSession }>(`/api/data/manual-sessions/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  deleteManualSession: (id: number) => request<{ ok: boolean }>(`/api/data/manual-sessions/${id}`, { method: 'DELETE' }),
  dataEvents: (limit = 100, beforeId?: number, fromTs?: number, toTs?: number) => request<{ schema_version: number; items: any[]; has_more: boolean; next_cursor: number | null }>(`/api/data/events?limit=${limit}${beforeId == null ? '' : `&before_id=${beforeId}`}${fromTs == null ? '' : `&from_ts=${fromTs}`}${toTs == null ? '' : `&to_ts=${toTs}`}`),
  dataRuns: (limit = 20, beforeStartedAt?: number, fromTs?: number, toTs?: number) => request<{ schema_version: number; items: any[]; has_more: boolean; next_cursor: number | null }>(`/api/data/runs?limit=${limit}${beforeStartedAt == null ? '' : `&before_started_at=${beforeStartedAt}`}${fromTs == null ? '' : `&from_ts=${fromTs}`}${toTs == null ? '' : `&to_ts=${toTs}`}`),
  attachRunInventory: (runId: string) => request<{ ok: boolean; run: any }>(`/api/data/runs/${encodeURIComponent(runId)}/attach-inventory`, { method: 'POST' }),
  humanReports: () => request<{ schema_version: number; items: any[]; inventory_gaps: any[] }>('/api/data/human-reports?limit=500'),
  addHumanReport: (value: any) => request<{ ok: boolean; item: any }>('/api/data/human-reports', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  addHumanReportBatch: (value: any) => request<{ ok: boolean; items: any[]; group_id: string }>('/api/data/human-reports/batch', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  updateHumanReport: (id: number, value: any) => request<{ ok: boolean; item: any }>(`/api/data/human-reports/${id}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  updateHumanReportGroup: (groupId: string, value: any) => request<{ ok: boolean; items: any[]; group_id: string }>(`/api/data/human-reports/group/${encodeURIComponent(groupId)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  deleteHumanReport: (id: number) => request<{ ok: boolean }>(`/api/data/human-reports/${id}`, { method: 'DELETE' }),
  deleteHumanReportGroup: (groupId: string) => request<{ ok: boolean }>(`/api/data/human-reports/group/${encodeURIComponent(groupId)}`, { method: 'DELETE' }),
  planning: () => request<PlanningReport>('/api/planning'),
  addPlanningGoal: (value: { resource: string; goal_mode: 'amount_target' | 'deadline_target'; target?: number; deadline?: string; note?: string }) => request<{ ok: boolean; goal: any }>('/api/planning/goals', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value),
  }),
  deletePlanningGoal: (id: number) => request<{ ok: boolean }>(`/api/planning/goals/${id}`, { method: 'DELETE' }),
  events: () => request<EventsCalendar>('/api/events'),
  eventsTimeline: () => request<EventTimelineReport>('/api/events/timeline'),
  saveEventEstimate: (event: string, keysPerRun: number) => request<{ ok: boolean }>('/api/planning/event-estimate', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event, keys_per_run: keysPerRun }),
  }),
  addEventGoal: (event: string, target?: number) => request<EventGoalResult>('/api/planning/event-goals', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event, ...(target == null ? {} : { target }) }),
  }),
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
  incidents: () => request<{ items: Incident[]; unread: number }>('/api/incidents'),
  ackIncident: (code: string) => request<{ ok: boolean }>(`/api/incidents/${encodeURIComponent(code)}/ack`, { method: 'POST' }),
  resolveIncident: (code: string) => request<{ ok: boolean }>(`/api/incidents/${encodeURIComponent(code)}/resolve`, { method: 'POST' }),
}
