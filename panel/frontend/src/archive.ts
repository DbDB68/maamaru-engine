import type { SwordAnnotationBody, SwordArchiveAttentionItem, SwordArchiveEntry, SwordArchiveHuman, SwordAttentionReason } from './types'

// 刀帐档案页的纯逻辑：同名编号、整本排序、搜索/刀种筛选、reason 人话、
// 标注请求体。组件只负责渲染和递请求；凡是「怎么算」的都收在这里好测。
// 纪律同编队页：kiwame_date 是「显现日期」（获得日期），不当形态证据。

export const ARCHIVE_ALL_TYPES = '全部'
export const SWORD_TYPE_OPTIONS = ['短刀', '打刀', '太刀', '大太刀', '枪', '薙刀', '剑', '胁差'] as const

export function archiveName(entry: Pick<SwordArchiveEntry, 'name_zh' | 'sword_catalog_id'>): string {
  return entry.name_zh || entry.sword_catalog_id || '没认出名字'
}

// 形态标签：走后端档案的独立结论。ambiguous=两处证据打架（存疑），
// unknown/缺失=未确认——不默认极，也不默认普通。
export function archiveFormLabel(entry: Pick<SwordArchiveEntry, 'form_status'>): '极' | '普通' | '未确认' | '存疑' {
  if (entry.form_status === 'kiwame') return '极'
  if (entry.form_status === 'normal') return '普通'
  if (entry.form_status === 'ambiguous') return '存疑'
  return '未确认'
}

function byAcquisitionDate(a: string | null, b: string | null): number {
  if (a == null && b == null) return 0
  if (a == null) return 1
  if (b == null) return -1
  return a < b ? -1 : a > b ? 1 : 0
}

// 整本刀帐的排列：按刀名分组（没认出名字的排最后），组内按显现日期先后排。
export function sortArchiveEntries(entries: SwordArchiveEntry[]): SwordArchiveEntry[] {
  return [...entries].sort((a, b) => {
    const na = a.name_zh || ''
    const nb = b.name_zh || ''
    if (na || nb) {
      if (!na) return 1
      if (!nb) return -1
      const byName = na.localeCompare(nb, 'zh-CN')
      if (byName) return byName
    } else {
      const byId = String(a.sword_catalog_id || '').localeCompare(String(b.sword_catalog_id || ''))
      if (byId) return byId
    }
    return byAcquisitionDate(a.kiwame_date, b.kiwame_date) || a.observation_id.localeCompare(b.observation_id)
  })
}

// 同名多振编号：同 sword_catalog_id 超过一振的，按显现日期升序叫「第 N 振」，
// 没日期的排最后；只有一振的不编号。返回 observation_id → N。
export function duplicateOrdinals(entries: SwordArchiveEntry[]): Map<string, number> {
  const groups = new Map<string, SwordArchiveEntry[]>()
  for (const entry of entries) {
    const key = entry.sword_catalog_id || `obs:${entry.observation_id}`
    const rows = groups.get(key) || []
    rows.push(entry)
    groups.set(key, rows)
  }
  const ordinals = new Map<string, number>()
  for (const rows of groups.values()) {
    if (rows.length < 2) continue
    const ordered = [...rows].sort((a, b) =>
      byAcquisitionDate(a.kiwame_date, b.kiwame_date) || a.observation_id.localeCompare(b.observation_id))
    ordered.forEach((entry, index) => ordinals.set(entry.observation_id, index + 1))
  }
  return ordinals
}

// 搜索（按刀名，认不出名字时按刀帐编号兜底）+ 刀种筛选。
// 刀种选「全部」不挑；挑具体刀种时，认不出刀种的不算。
export function filterArchiveEntries(
  entries: SwordArchiveEntry[],
  query: string,
  swordType: string,
): SwordArchiveEntry[] {
  const needle = query.trim().toLocaleLowerCase('zh-CN')
  return entries.filter(entry => {
    if (swordType && swordType !== ARCHIVE_ALL_TYPES && entry.sword_type !== swordType) return false
    if (!needle) return true
    return (entry.name_zh || '').toLocaleLowerCase('zh-CN').includes(needle)
      || (entry.sword_catalog_id || '').toLocaleLowerCase('zh-CN').includes(needle)
  })
}

export const ATTENTION_REASON_TEXT: Record<SwordAttentionReason, string> = {
  form_unknown: '分不清极/普通',
  form_ambiguous: '两处证据打架',
  duplicate_fingerprint: '同名同日多振，要你指认',
  stale_annotation: '之前的确认对不上号了',
}

export function attentionReasonTexts(reasons: SwordAttentionReason[]): string[] {
  return reasons.map(reason => ATTENTION_REASON_TEXT[reason] || reason)
}

// ---- 标注请求体 ----

// 档案行和 attention 条目都够格当标注目标（字段名一致）。
export interface ArchiveAnnotationTarget {
  sword_catalog_id: string | null
  kiwame_date: string | null
  level?: number | null
  reasons?: SwordAttentionReason[]
}

export type ArchiveHumanLike = Pick<SwordArchiveHuman, 'form' | 'keeper' | 'note'>

function baseBody(target: ArchiveAnnotationTarget): SwordAnnotationBody {
  return { sword_catalog_id: target.sword_catalog_id, kiwame_date: target.kiwame_date }
}

// 确认形态：只翻 form 这一位，旧标注的 keeper/note 原样递回，
// 免得后端整行覆盖时把确认过的信息顺手清掉。
export function formConfirmBody(
  target: ArchiveAnnotationTarget,
  form: 'kiwame' | 'normal',
  human?: ArchiveHumanLike | null,
): SwordAnnotationBody {
  const body = baseBody(target)
  body.form_confirmed = form
  if (target.reasons?.includes('duplicate_fingerprint') && target.level != null) {
    body.level_at_mark = target.level
  }
  if (human) {
    body.keeper = human.keeper
    body.note = human.note
  }
  return body
}

// 要练开关：只翻 keeper 这一位（next 由调用方算好取反），
// 旧标注的形态结论和备注原样递回。没标注时就只递 keeper 新建。
export function keeperBody(
  target: ArchiveAnnotationTarget,
  next: boolean,
  human?: ArchiveHumanLike | null,
): SwordAnnotationBody {
  const body = baseBody(target)
  body.keeper = next
  if (human) {
    body.form_confirmed = human.form
    body.note = human.note
  }
  return body
}

export function attentionTarget(item: SwordArchiveAttentionItem): ArchiveAnnotationTarget {
  return {
    sword_catalog_id: item.sword_catalog_id,
    kiwame_date: item.kiwame_date,
    level: item.level,
    reasons: item.reasons,
  }
}
