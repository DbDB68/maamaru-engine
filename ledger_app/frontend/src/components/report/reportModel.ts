// 本丸成绩单共享的展示模型：来源分类、配色、格式化与小助手
import type { LedgerAttribution } from '../../types'

export const resourceNames = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符', '甲州金']

export interface SourceCategory { key: string; label: string; color: string }

// 顺序即柱子堆叠顺序；unknown 永远垫底（视觉上最贴近零线的是它也行，主要是灰色一眼可辨）
export const sourceCategories: SourceCategory[] = [
  { key: 'osaka', label: '大阪城', color: '#d4a017' },
  { key: 'expedition', label: '远征', color: '#7a9e5f' },
  { key: 'forge', label: '锻刀', color: '#b56a4c' },
  { key: 'repair', label: '手入', color: '#6a8caf' },
  { key: 'task_rewards', label: '任务报酬', color: '#9a7bb0' },
  { key: 'yosari', label: '异去', color: '#4fa3a5' },
  { key: 'other', label: '其他来源', color: '#c7b299' },
  { key: 'human', label: '审神者已说明', color: '#a89c8d' },
  { key: 'unknown', label: '还不知道', color: '#ddd6cb' },
]

export const resourceColors: Record<string, string> = {
  小判: '#d4a017', 木炭: '#6a8caf', 玉钢: '#7a9e5f', 冷却材: '#4fa3a5',
  砥石: '#b56a4c', 委托符: '#9a7bb0', 加速符: '#c96f4a', 甲州金: '#8a7f72',
}

export function categoryOf(source: string | undefined): string {
  const head = String(source || '').split(/[./]/)[0]
  return sourceCategories.some(item => item.key === head) ? head : 'other'
}

export function categoryLabel(key: string): string {
  return sourceCategories.find(item => item.key === key)?.label || key
}

export function signed(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${value > 0 ? '+' : ''}${value.toLocaleString()}`
}

const dateFmt = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai' })

export function shanghaiDate(ts: number): string {
  return dateFmt.format(new Date(ts * 1000))
}

export function dayRange(date: string): [number, number] {
  const start = new Date(`${date}T00:00:00+08:00`).getTime() / 1000
  return [start, start + 86400]
}

export function dayLabel(date: string): string {
  return String(date || '').slice(5).replace('-', '/')
}

export function eventTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

export const scriptNames: Record<string, string> = {
  osaka: '大阪城', edocastle: '江户城潜入调查', sortie: '合战场', yosari: '异去', raid: '联队战',
  pumpkin: '南瓜大作战', daily: '一键日课',
  expedition: '远征', practice: '演练', smith: '锻刀', repair: '手入',
  sakura: '刷花', sugar: '炼糖', rotate_captain: '换队长', scheduler: '排班',
  inbox_supplies: '收杂物箱', snapshot: '库存盘点',
}

// ---- 每轮任务（run）展示助手 ----

export function runElapsedSeconds(run: any): number | null {
  const precise = Number(run.play_duration_seconds)
  if (Number.isFinite(precise) && precise >= 0) return precise
  const fallback = Number(run.duration_seconds)
  return Number.isFinite(fallback) && fallback >= 0 ? fallback : null
}

export function elapsedTime(seconds: number | null): string {
  if (seconds == null || seconds < 0) return '用时未记录'
  const minutes = Math.max(0, Math.round(seconds / 60))
  const hours = Math.floor(minutes / 60), rest = minutes % 60
  return hours ? `${hours}小时${rest ? `${rest}分` : ''}` : `${rest}分钟`
}

export function loopTime(seconds: number | null): string {
  if (!seconds) return '圈速积累中'
  const value = Math.round(seconds)
  return `${Math.floor(value / 60)}分${String(value % 60).padStart(2, '0')}秒/圈`
}

export function runTitle(run: any): string {
  const name = scriptNames[run.script] || '挂机任务'
  const loops = Number(run.loops || 0)
  if (run.script === 'osaka' && run.selected_floor != null) {
    return loops > 0 ? `大阪城 ${run.selected_floor}F · ${loops} 圈` : `大阪城 ${run.selected_floor}F`
  }
  return loops > 0 ? `${name} · ${loops} 圈` : name
}

export function runStatusLabel(run: any): string {
  const labels: Record<string, string> = {
    completed: '已完成', stopped: '已手动停止', failed: '翻车',
  }
  return labels[String(run.status || '')] || String(run.status || '状态未记录')
}

const deltaOrder = ['小判', '木炭', '玉钢', '冷却材', '砥石', '委托符', '加速符', '甲州金']

export function deltaStats(run: any): string {
  return deltaOrder.filter(name => run.resource_delta?.[name])
    .map(name => `${name} ${signed(Number(run.resource_delta[name]))}`).join(' · ')
}

export function attributedStats(run: any): string {
  return deltaOrder.filter(name => run.attributed_resource_delta?.[name])
    .map(name => `${name} ${signed(Number(run.attributed_resource_delta[name]))}`).join(' · ')
}

export interface DayStack {
  date: string
  total: number | null
  byCategory: Record<string, number>
}

export interface ChartSeries {
  key: string
  name: string
  color: string
  values: (number | null)[]
}

export function kobanPerHour(run: any): number | null {
  const koban = Number(run.resource_delta?.['小判'])
  const seconds = Number(runElapsedSeconds(run))
  return Number.isFinite(koban) && seconds > 0 ? Math.round(koban * 3600 / seconds) : null
}

export function kobanPerHourLabel(run: any): string {
  const value = kobanPerHour(run)
  return value == null ? '' : value.toLocaleString()
}

export function kobanPerFloorLabel(run: any): string {
  const ks = run.koban_session
  if (!ks || !ks.floors) return ''
  const delta = Number(ks.after) - Number(ks.before)
  if (!Number.isFinite(delta)) return ''
  return `${(delta / ks.floors).toFixed(1)} 小判`
}

// 把一天的归因明细按来源分类汇总
export function sumByCategory(attributions: LedgerAttribution[]): Record<string, number> {
  const totals: Record<string, number> = {}
  for (const item of attributions) {
    const key = categoryOf(item.source)
    totals[key] = (totals[key] || 0) + Number(item.delta || 0)
  }
  return totals
}

// 刀剑进账来源的展示名
export function obtainSourceLabel(source: string | undefined): string {
  if (source === 'sortie.drop') return '出阵掉落'
  if (source === 'osaka.drop') return '大阪城挖地'
  if (source === 'forge') return '锻刀'
  if (source === 'pumpkin') return '南瓜大作战'
  return source || ''
}
