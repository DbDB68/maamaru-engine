import type { CustomFormation, CustomFormationSlotEntry, FormationCandidate } from './types'

// 部队预设页的纯逻辑：候选展示与存前校验。真正套用预设由玩法入口
// 和后端执行器负责，前端不展示历史队伍，也不自行宣称换人成功。

export function candidateName(entry: FormationCandidate): string {
  return entry.name_zh || entry.sword_catalog_id || '没认出名字'
}

// 形态标签走后端档案的独立结论（form_status）：编队页槽位直读（刀种+
// 花数/白樱花）是实例级证据，图鉴「极」字标是种级证据（分不清哪振，
// 只给 ambiguous）。kiwame_date 是「显现日期」，每振刀都有，永远不当
// 形态证据（2026-09-15 P0：旧版拿它推形态，把 185/196 振全盖了极章）。
// 没有可靠证据就是「未确认」——不默认极，也不默认普通。
export function candidateFormLabel(entry: FormationCandidate): '极' | '普通' | '未确认' {
  if (entry.form_status === 'kiwame') return '极'
  if (entry.form_status === 'normal') return '普通'
  return '未确认'
}

// 目标身份证据缺口：缺这些就别让玩家把请求递出去（递了也只会 ambiguous）。
export function candidateEvidenceGaps(entry: FormationCandidate): string[] {
  const gaps: string[] = []
  if (!entry.sword_catalog_id && !entry.name_zh) gaps.push('名字')
  if (entry.level == null) gaps.push('等级')
  return gaps
}

// ---- 预设编队 ----
// 预设只是用户存的换人安排（记录），应用是后端的事；这里只管展示文案与
// 存前校验。槽位键 "1"-"6"，缺省 = 应用时该位置不动。

const TEAM_NUMERALS = ['一', '二', '三', '四', '五']

// 预设卡片标题：名字 + 覆盖哪支游戏内部队（部队一~五）。
export function presetLabel(f: Pick<CustomFormation, 'name' | 'target_team'>): string {
  const numeral = TEAM_NUMERALS[f.target_team - 1] || String(f.target_team)
  return `${f.name}（覆盖部队${numeral}）`
}

// 已指定几槽：只数 1~6 里真的带了刀身份（图鉴号或名字）的格子。
export function presetSlotCount(f: Pick<CustomFormation, 'slots'>): number {
  return Object.entries(f.slots || {}).filter(([key, value]) => {
    const no = Number(key)
    return no >= 1 && no <= 6 && Boolean(value && (value.sword_catalog_id || value.name_zh))
  }).length
}

// 存预设前的门闩：名字非空 ≤20 字、目标部队 1~5。一个位置都不指定也放行
// （玩家可能有他的用意），但 UI 要另行提示「应用时会直接停下」。
export function validatePresetDraft(draft: Pick<CustomFormation, 'name' | 'target_team' | 'slots'>): string | null {
  const name = draft.name.trim()
  if (!name) return '先给预设起个名字吧。'
  if (name.length > 20) return '名字最多 20 个字，精简一点。'
  if (!Number.isInteger(draft.target_team) || draft.target_team < 1 || draft.target_team > 5) {
    return '目标部队只能选部队一到部队五。'
  }
  for (const [slot, entry] of Object.entries(draft.slots || {})) {
    if (entry.selection_policy === 'locked_highest_level' &&
        (!entry.sword_catalog_id || !['normal', 'kiwame'].includes(entry.form_status || ''))) {
      return `${slot} 号位请明确刀名和普通／极形态。`
    }
    if (entry.treasure && (typeof entry.treasure.name !== 'string' || !entry.treasure.name.trim() || !Number.isInteger(entry.treasure.level)
      || entry.treasure.level < 1 || !Number.isInteger(entry.treasure.affection)
      || entry.treasure.affection < 0)) return `${slot} 号位的宝物需填写名称、等级和爱用度。`
    if (entry.troops && Object.entries(entry.troops).some(([position, name]) =>
      !['1', '2', '3'].includes(position) || typeof name !== 'string' || !name.trim())) {
      return `${slot} 号位的刀装需按第 1／2／3 格填写游戏中的完整名称。`
    }
  }
  const treasureKeys = Object.values(draft.slots || {}).filter(entry => entry.treasure)
    .map(entry => `${entry.treasure!.name.trim()}|${entry.treasure!.level}|${entry.treasure!.affection}`)
  if (new Set(treasureKeys).size !== treasureKeys.length) {
    return '同一件宝物不能指定给多个位置；同款多件暂时分不清。'
  }
  return null
}

// 槽位格子里的一行小字：有档案快照显示「名字（形态 · 等级）」，空槽显示「不动」。
export function presetSlotSummary(entry: CustomFormationSlotEntry | null | undefined): string {
  if (!entry) return '不动'
  const name = entry.name_zh || entry.sword_catalog_id || '没认出名字'
  const form = entry.form_status === 'kiwame' ? '极'
    : entry.form_status === 'normal' ? '普通' : '未确认'
  const equipment = [entry.troops && Object.keys(entry.troops).length ? `刀装 ${Object.keys(entry.troops).length} 格` : '', entry.treasure ? `宝物：${entry.treasure.name || '未填'}` : ''].filter(Boolean).join(' · ')
  if (entry.selection_policy === 'locked_highest_level') return `${name}（${form} · 上锁最高级）${equipment ? ` · ${equipment}` : ''}`
  const bits = [form, entry.level != null ? `Lv.${entry.level}` : ''].filter(Boolean).join(' · ')
  return (bits ? `${name}（${bits}）` : name) + (equipment ? ` · ${equipment}` : '')
}

// 预设的选刀池：没认出名字的候选（没图鉴号也没名字）禁选——存进去也分辨
// 不出是谁；缺等级只挂提示牌，照常能选（与候选证据缺口同一口径）。
export function presetCandidatePickable(entry: Pick<FormationCandidate, 'sword_catalog_id' | 'name_zh'>): boolean {
  return Boolean(entry.sword_catalog_id || entry.name_zh)
}
