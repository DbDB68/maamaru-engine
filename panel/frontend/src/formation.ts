import type { CustomFormation, CustomFormationSlotEntry, FormationCandidate, FormationSwapEvent, FormationSwapResult } from './types'

// 编队页的纯逻辑：候选展示、换人门闩、结果文案。组件只负责渲染，
// 判定全收在这里好测。纪律与后端一致：前端不做匹配，只做「能不能
// 把请求递出去」的门闩；换没换成永远以后端回读验收为准。

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

export interface SwapEligibilityInput {
  poolDone: boolean
  poolReason?: string
  running: boolean
  slotNo: number | null
  candidate: FormationCandidate | null
}

export interface SwapEligibility {
  ok: boolean
  reason: string
}

// 启动换人的门闩：档案不完整、有任务在跑、没选位置/目标、目标身份
// 证据不足，一律不许递请求，并告诉玩家下一步干什么。
export function swapEligibility(input: SwapEligibilityInput): SwapEligibility {
  if (!input.poolDone) {
    return {
      ok: false,
      reason: input.poolReason
        ? `本丸档案还不可信：${input.poolReason}。先去「流程工房 → 玩法设置 → 后勤配置 → 刀帐盘点」跑一次完整盘点。`
        : '还没有可信的本丸档案。先去「流程工房 → 玩法设置 → 后勤配置 → 刀帐盘点」跑一次完整盘点。',
    }
  }
  if (input.running) {
    return { ok: false, reason: '有任务正在运行，等它跑完（或先停止）再换人。' }
  }
  if (input.slotNo == null) {
    return { ok: false, reason: '先点一下要换的位置（1～6 号位）。' }
  }
  if (!input.candidate) {
    return { ok: false, reason: '再从候选名单里选一振要换上去的刀。' }
  }
  const gaps = candidateEvidenceGaps(input.candidate)
  if (gaps.length) {
    return {
      ok: false,
      reason: `这振${candidateName(input.candidate)}的档案缺${gaps.join('、')}，同名时分辨不出来；先重新跑一次「刀帐盘点」再换。`,
    }
  }
  return { ok: true, reason: '' }
}

export interface FormationResultText {
  title: string
  tone: 'ok' | 'warn' | 'bad'
  detail: string
}

// 机器结果 → 生活化中文。只有 changed / already_correct 算办成；
// 其余各自说清发生了什么、玩家下一步该干什么，绝不统一显示「失败」。
export const FORMATION_RESULT_TEXT: Record<FormationSwapResult, FormationResultText> = {
  changed: {
    title: '换好了',
    tone: 'ok',
    detail: '这位已经站到位置上，狐之助回读逐项核对无误。',
  },
  already_correct: {
    title: '本来就是他',
    tone: 'ok',
    detail: '这个位置上已经是你选的这位了，一下都没动。',
  },
  ambiguous: {
    title: '不敢随便点',
    tone: 'warn',
    detail: '名单里有几振同名的刀分不清谁是谁，怕换错人，一下都没点。重新跑一次「刀帐盘点」把档案认清后再试。',
  },
  not_found: {
    title: '名单里没找到他',
    tone: 'warn',
    detail: '翻遍整份刀剑名单都没见到这振刀：他可能在别的队里、手入/修行/远征中，或者档案旧了。先去游戏里看看他在哪儿。',
  },
  unavailable: {
    title: '游戏不让他上岗',
    tone: 'warn',
    detail: '点了「决定」但游戏没答应（多半在手入、修行或远征中），队伍没动。等他闲下来再试。',
  },
  screen_unrecognized: {
    title: '没认出画面',
    tone: 'bad',
    detail: '游戏画面跟预期对不上，为安全起见一刀没动。看看模拟器是不是卡在奇怪界面，再试一次。',
  },
  verification_failed: {
    title: '换完对不上账',
    tone: 'bad',
    detail: '点了「决定」但回读对不上，队伍可能已经变了。请去游戏里亲眼核对一下部队编成。',
  },
  invalid_request: {
    title: '这次请求有问题',
    tone: 'bad',
    detail: '换人请求本身不成立，没有发出任何点击。刷新档案后再选一次。',
  },
}

export function formationResultText(result: string): FormationResultText {
  return FORMATION_RESULT_TEXT[result as FormationSwapResult] || {
    title: '结果没看懂',
    tone: 'bad',
    detail: '后端给了一个不认识的回读结果，请以游戏里的队伍为准。',
  }
}

// 从事件流里找回本轮换人的回读验收（run_id 对上的那条，别的任务的不管）。
export function pickSwapEvent(
  events: FormationSwapEvent[],
  runId: string,
): FormationSwapEvent | null {
  return events.find(item => item.run_id === runId) || null
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
  return null
}

// 槽位格子里的一行小字：有档案快照显示「名字（形态 · 等级）」，空槽显示「不动」。
export function presetSlotSummary(entry: CustomFormationSlotEntry | null | undefined): string {
  if (!entry) return '不动'
  const name = entry.name_zh || entry.sword_catalog_id || '没认出名字'
  const form = entry.form_status === 'kiwame' ? '极'
    : entry.form_status === 'normal' ? '普通' : '未确认'
  const bits = [form, entry.level != null ? `Lv.${entry.level}` : ''].filter(Boolean).join(' · ')
  return bits ? `${name}（${bits}）` : name
}

// 预设的选刀池：没认出名字的候选（没图鉴号也没名字）禁选——存进去也分辨
// 不出是谁；缺等级只挂提示牌，照常能选（与候选证据缺口同一口径）。
export function presetCandidatePickable(entry: Pick<FormationCandidate, 'sword_catalog_id' | 'name_zh'>): boolean {
  return Boolean(entry.sword_catalog_id || entry.name_zh)
}
