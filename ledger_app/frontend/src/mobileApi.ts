import swordData from '../../../touken/data/swords.json'
import type { HumanReport, ManualInventory, ManualSession, PlanningGoalAdvice, PlanningReport, ResourceLedger } from './types'

const STORAGE_KEY = 'maamaru-ledger-demo-v1'
const resources = ['木炭', '玉钢', '冷却材', '砥石', '小判', '甲州金', '委托符', '加速符']
const scriptLabels: Record<string, string> = {
  osaka: '地下城', raid: '联队战', edocastle: '江户城潜入调查', sortie: '合战场',
  yosari: '夜花夺还作战', pumpkin: '特命调查',
}

interface MobileGoal {
  id: number
  resource: string
  goal_mode: 'amount_target' | 'deadline_target'
  target?: number
  deadline?: string
  note?: string
  created_at: number
}

interface MobileState {
  schema_version: 1
  created_at: number
  next_id: number
  hero_resource: string
  opening_resources: Record<string, number>
  human_reports: HumanReport[]
  inventories: ManualInventory[]
  sessions: ManualSession[]
  goals: MobileGoal[]
  sword_wishlist: string[]
  sword_records: Record<string, { level: number; ranbu: number; note?: string; updated_at: number }>
}

function seedState(): MobileState {
  const now = Date.now() / 1000
  const day = 86400
  return {
    schema_version: 1,
    created_at: now - 8 * day,
    next_id: 20,
    hero_resource: '小判',
    opening_resources: {
      木炭: 514740, 玉钢: 456785, 冷却材: 437608, 砥石: 406813,
      小判: 872056, 甲州金: 650, 委托符: 819, 加速符: 350,
    },
    human_reports: [
      { id: 1, group_id: 'demo-mail', occurred_at: now - 2 * day, source: 'proactive', activities: ['领邮箱'], resource: '小判', claimed_delta: 130200, note: '邮件里的活动奖励' },
      { id: 2, group_id: 'demo-sortie', occurred_at: now - day, source: 'proactive', activities: ['手动出阵'], resource: '小判', claimed_delta: 25900, note: '大阪城' },
      { id: 3, group_id: 'demo-today', occurred_at: now - 3600, source: 'proactive', activities: ['手动领奖'], resource: '木炭', claimed_delta: 1585 },
      { id: 4, group_id: 'demo-today', occurred_at: now - 3600, source: 'proactive', activities: ['手动领奖'], resource: '玉钢', claimed_delta: 3991 },
      { id: 5, group_id: 'demo-today', occurred_at: now - 3600, source: 'proactive', activities: ['手动领奖'], resource: '冷却材', claimed_delta: 2467 },
      { id: 6, group_id: 'demo-today', occurred_at: now - 3600, source: 'proactive', activities: ['手动领奖'], resource: '砥石', claimed_delta: -914 },
      { id: 7, group_id: 'demo-today', occurred_at: now - 3600, source: 'proactive', activities: ['手动领奖'], resource: '委托符', claimed_delta: 10 },
      { id: 8, group_id: 'demo-today', occurred_at: now - 3600, source: 'proactive', activities: ['手动领奖'], resource: '加速符', claimed_delta: 39 },
    ],
    inventories: [],
    sessions: [{
      id: 9, created_at: now - 1800, script: 'edocastle', activity: '江户城潜入调查',
      started_at: now - 5400, ended_at: now - 1800, loops: 6, duration_seconds: 3600,
      average_loop_seconds: 600, note: '试玩示例', source: 'manual',
    }],
    goals: [],
    sword_wishlist: [],
    sword_records: {},
  }
}

function readState(): MobileState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const state = JSON.parse(raw) as MobileState
      state.sword_records ||= {}
      return state
    }
  } catch { /* A fresh demo is better than a dead screen if storage is damaged. */ }
  const state = seedState()
  writeState(state)
  return state
}

function writeState(state: MobileState) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
}

function nextId(state: MobileState) {
  const value = state.next_id
  state.next_id += 1
  return value
}

function currentResources(state: MobileState) {
  const result = { ...state.opening_resources }
  for (const resource of resources) {
    const anchor = [...state.inventories]
      .filter(item => item.resources?.[resource] != null)
      .sort((a, b) => b.ts - a.ts)[0]
    const since = anchor?.ts ?? state.created_at
    if (anchor) result[resource] = Number(anchor.resources[resource])
    result[resource] += state.human_reports
      .filter(item => item.resource === resource && Number(item.occurred_at) > since)
      .reduce((sum, item) => sum + Number(item.claimed_delta || 0), 0)
  }
  return result
}

function buildLedger(days: number): ResourceLedger {
  const state = readState()
  const now = Date.now() / 1000
  const from = now - days * 86400
  const current = currentResources(state)
  const rows = resources.map(resource => {
    const total = state.human_reports
      .filter(item => item.resource === resource && item.occurred_at >= from)
      .reduce((sum, item) => sum + Number(item.claimed_delta || 0), 0)
    return {
      resource, opening: current[resource] - total, closing: current[resource], total_delta: total,
      attributed_delta: total, unattributed_delta: 0, observation_count: 1, confidence: 'manual',
    }
  })
  return {
    schema_version: 1, generated_at: now,
    window: { from, to: now, timezone: 'Asia/Shanghai', days },
    per_resource: rows, daily_series: [], gaps: [],
    attributions: state.human_reports.filter(item => item.occurred_at >= from).map(item => ({
      id: `mobile:${item.id}`, ts: item.occurred_at, resource: String(item.resource),
      delta: Number(item.claimed_delta || 0), source: 'manual', label: item.activities?.[0] || '手账', confidence: 'manual',
    })),
  }
}

function localDate(timestamp: number) {
  const date = new Date(timestamp * 1000)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 10)
}

function buildPlanning(): PlanningReport {
  const state = readState()
  const ledger = buildLedger(7)
  const current = currentResources(state)
  const now = Date.now() / 1000
  const rates = Object.fromEntries(ledger.per_resource.map(row => [row.resource, { daily: Number(row.total_delta || 0) / 7, days_observed: 7 }]))
  const goals: PlanningGoalAdvice[] = state.goals.map(goal => {
    const value = current[goal.resource] ?? null
    const daily = rates[goal.resource]?.daily ?? null
    const target = goal.goal_mode === 'amount_target' ? Number(goal.target || 0) : null
    const remaining = target == null || value == null ? null : Math.max(0, target - value)
    const daysLeft = goal.deadline ? Math.ceil((new Date(`${goal.deadline}T23:59:59`).getTime() / 1000 - now) / 86400) : null
    const projected = daysLeft == null || value == null || daily == null ? null : value + daily * Math.max(0, daysLeft)
    const done = target != null && value != null && value >= target
    const onTrack = goal.goal_mode === 'deadline_target' || done || (daily != null && daily > 0)
    return {
      id: goal.id, kind: 'resource', goal_mode: goal.goal_mode, resource: goal.resource,
      target, deadline: goal.deadline || null, note: goal.note || '', days_left: daysLeft,
      current: value, rate: daily, projected, shortfall: remaining, extra_daily: null, extra_floors: null,
      status: done ? 'done' : onTrack ? 'on_track' : 'behind',
      message: done ? '已经攒够了' : remaining == null ? '继续观察' : `还差 ${Math.round(remaining).toLocaleString()}`,
    }
  })
  return {
    schema_version: 1, generated_at: now, today: localDate(now), rate_window_days: 7,
    rates, koban_per_floor: null, current, goals, events: [],
  }
}

function makeSession(id: number, value: { script: string; started_at: number; ended_at: number; loops: number; note?: string }): ManualSession {
  const duration = Math.max(0, value.ended_at - value.started_at)
  return {
    id, created_at: Date.now() / 1000, script: value.script,
    activity: scriptLabels[value.script] || value.script, started_at: value.started_at, ended_at: value.ended_at,
    loops: value.loops, duration_seconds: duration, average_loop_seconds: value.loops ? duration / value.loops : 0,
    note: value.note || '', source: 'manual',
  }
}

function batchReports(state: MobileState, value: any, groupId = `mobile-${Date.now()}`) {
  return Object.entries(value.entries || {}).map(([resource, amount]) => ({
    id: nextId(state), group_id: groupId, occurred_at: Number(value.occurred_at), source: 'proactive',
    activities: value.activities || [], note: value.note || '', resource, claimed_delta: Number(amount),
  } satisfies HumanReport))
}

const swordEntries = Object.entries(swordData.chars).map(([id, info]) => ({
  id, name: info.name, name_zh: info.name_zh, type: info.type,
}))

export const mobileApi = {
  settings: async () => ({ hero_resource: readState().hero_resource }),
  saveLedgerHeroResource: async (heroResource: string) => {
    const state = readState(); state.hero_resource = heroResource; writeState(state); return { ok: true }
  },
  resourceLedger: async (days = 7) => buildLedger(days),
  planning: async () => buildPlanning(),
  humanReports: async () => ({ schema_version: 1, items: readState().human_reports, inventory_gaps: [] }),
  manualInventory: async (limit = 200) => ({ schema_version: 1, items: readState().inventories.slice(-limit).reverse() }),
  manualSessions: async (limit = 200) => ({ schema_version: 1, items: readState().sessions.slice(-limit).reverse() }),
  addHumanReportBatch: async (value: any) => {
    const state = readState(); const group_id = `mobile-${Date.now()}`; const items = batchReports(state, value, group_id)
    state.human_reports.push(...items); writeState(state); return { ok: true, items, group_id }
  },
  updateHumanReport: async (id: number, value: any) => {
    const state = readState(); const index = state.human_reports.findIndex(item => item.id === id)
    if (index < 0) throw new Error('没找到这条手账')
    state.human_reports[index] = { ...state.human_reports[index], ...value }; writeState(state)
    return { ok: true, item: state.human_reports[index] }
  },
  updateHumanReportGroup: async (groupId: string, value: any) => {
    const state = readState(); state.human_reports = state.human_reports.filter(item => item.group_id !== groupId)
    const items = batchReports(state, value, groupId); state.human_reports.push(...items); writeState(state)
    return { ok: true, items, group_id: groupId }
  },
  deleteHumanReport: async (id: number) => {
    const state = readState(); state.human_reports = state.human_reports.filter(item => item.id !== id); writeState(state); return { ok: true }
  },
  deleteHumanReportGroup: async (groupId: string) => {
    const state = readState(); state.human_reports = state.human_reports.filter(item => item.group_id !== groupId); writeState(state); return { ok: true }
  },
  addManualInventory: async (values: Record<string, number>, observedAt = Date.now() / 1000) => {
    const state = readState(); const snapshot: ManualInventory = { id: nextId(state), ts: observedAt, captured_at: new Date(observedAt * 1000).toISOString(), source: 'manual_entry', resources: values }
    state.inventories.push(snapshot); writeState(state); return { ok: true, snapshot }
  },
  updateManualInventory: async (id: number, values: Record<string, number>, observedAt: number) => {
    const state = readState(); const index = state.inventories.findIndex(item => item.id === id)
    if (index < 0) throw new Error('没找到这次家底盘点')
    const snapshot: ManualInventory = { ...state.inventories[index], ts: observedAt, captured_at: new Date(observedAt * 1000).toISOString(), resources: values }
    state.inventories[index] = snapshot; writeState(state); return { ok: true, snapshot }
  },
  deleteManualInventory: async (id: number) => {
    const state = readState(); state.inventories = state.inventories.filter(item => item.id !== id); writeState(state); return { ok: true }
  },
  addManualSession: async (value: any) => {
    const state = readState(); const item = makeSession(nextId(state), value); state.sessions.push(item); writeState(state); return { ok: true, item }
  },
  updateManualSession: async (id: number, value: any) => {
    const state = readState(); const index = state.sessions.findIndex(item => item.id === id)
    if (index < 0) throw new Error('没找到这段活动')
    const item = makeSession(id, value); state.sessions[index] = item; writeState(state); return { ok: true, item }
  },
  deleteManualSession: async (id: number) => {
    const state = readState(); state.sessions = state.sessions.filter(item => item.id !== id); writeState(state); return { ok: true }
  },
  addPlanningGoal: async (value: any) => {
    const state = readState(); const goal = { id: nextId(state), created_at: Date.now() / 1000, ...value } as MobileGoal
    state.goals.push(goal); writeState(state); return { ok: true, goal }
  },
  deletePlanningGoal: async (id: number) => {
    const state = readState(); state.goals = state.goals.filter(goal => goal.id !== id); writeState(state); return { ok: true }
  },
  configLists: async () => ({ sword_wishlist: readState().sword_wishlist }),
  swords: async () => ({ swords: swordEntries }),
  saveConfigLists: async (value: Record<string, string[]>) => {
    const state = readState(); state.sword_wishlist = [...(value.sword_wishlist || [])]; writeState(state); return { ok: true }
  },
  swordRecords: async () => ({ ...readState().sword_records }),
  saveSwordRecord: async (name: string, value: { level: number; ranbu: number; note?: string }) => {
    const state = readState()
    state.sword_records[name] = { level: Number(value.level), ranbu: Number(value.ranbu), note: value.note || '', updated_at: Date.now() / 1000 }
    writeState(state)
    return { ok: true, item: state.sword_records[name] }
  },
  deleteSwordRecord: async (name: string) => {
    const state = readState(); delete state.sword_records[name]; writeState(state); return { ok: true }
  },
}
