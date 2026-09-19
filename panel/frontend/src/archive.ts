import type { SwordAnnotationBody, SwordArchiveAttentionItem, SwordArchiveEntry, SwordArchiveHuman, SwordAttentionReason, SwordMachineFormStatus } from './types'

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

// 机器原始形态结论的人话（改判行拿它当「原识别」小字；unknown 只能算没读出来）。
export const MACHINE_FORM_TEXT: Record<Exclude<SwordMachineFormStatus, null>, string> = {
  kiwame: '极',
  normal: '普通',
  ambiguous: '存疑',
  unknown: '未确认',
}

export type ArchiveFormSource =
  | { kind: 'machine' }
  | { kind: 'human' }
  | { kind: 'overridden'; machineText: string }

// 形态来源徽标：没人碰过 → 盘点识别；有人工结论且和机器不冲突 → 你确认过；
// 人工和机器打架（form_overridden）→ 你改判的，附带机器原来的说法。
export function archiveFormSource(entry: Pick<SwordArchiveEntry, 'human' | 'form_overridden' | 'machine_form_status'>): ArchiveFormSource {
  if (!entry.human?.form) return { kind: 'machine' }
  if (!entry.form_overridden) return { kind: 'human' }
  return { kind: 'overridden', machineText: MACHINE_FORM_TEXT[entry.machine_form_status ?? 'unknown'] }
}

function byAcquisitionDate(a: string | null, b: string | null): number {
  if (a == null && b == null) return 0
  if (a == null) return 1
  if (b == null) return -1
  return a < b ? -1 : a > b ? 1 : 0
}

// 刀帐番号：sword_catalog_id 形如 touken_118_heshikiri_hasebe，118 即
// 游戏刀帐里的官方编号；纯数字字符串（旧测试数据）也认。
function catalogNo(id: string | null): number | null {
  if (!id) return null
  const match = /touken_(\d+)_/.exec(id)
  if (match) return Number(match[1])
  return /^\d+$/.test(id) ? Number(id) : null
}

// 整本刀帐的排列：按刀帐番号升序——和游戏里「刀帐顺序」排序一致，
// 对照游戏翻页对账不用来回滑；同名多振挨在一起，组内按显现日期升序
// （与游戏内同名排法一致，老振在前）；番号认不出的排最后按名字兜底。
export function sortArchiveEntries(entries: SwordArchiveEntry[]): SwordArchiveEntry[] {
  return [...entries].sort((a, b) => {
    const na = catalogNo(a.sword_catalog_id)
    const nb = catalogNo(b.sword_catalog_id)
    if (na != null && nb != null && na !== nb) return na - nb
    if (na != null && nb == null) return -1
    if (na == null && nb != null) return 1
    if (na == null && nb == null) {
      const byName = (a.name_zh || '').localeCompare(b.name_zh || '', 'zh-CN')
      if (byName) return byName
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

// 特别关心置顶：整本列表里把 watch 的刀单独切出来排最前（组内仍按整本
// 排序），组件在两组之间画分隔线。搜索/刀种筛选先做完再切，搜出来的
// 特别关心同样置顶。允许打标（stale 组的标记挂在整组上，行内另给提示）。
export function partitionWatchEntries(entries: SwordArchiveEntry[]): { watched: SwordArchiveEntry[]; rest: SwordArchiveEntry[] } {
  const watched: SwordArchiveEntry[] = []
  const rest: SwordArchiveEntry[] = []
  for (const entry of entries) {
    if (entry.human?.watch) watched.push(entry)
    else rest.push(entry)
  }
  return { watched, rest }
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
  form_unknown: '形态没读出来',
  form_ambiguous: '两处证据打架',
  duplicate_fingerprint: '同名同日多振，指纹撞车',
  stale_annotation: '标注对不上号',
  level_unknown: '等级没读出来',
}

export function attentionReasonTexts(reasons: SwordAttentionReason[]): string[] {
  return reasons.map(reason => ATTENTION_REASON_TEXT[reason] || reason)
}

// 待核对分组的展示顺序（跟着上手优先级走：先认形态，再指认多振，最后补等级）。
export const ATTENTION_REASON_ORDER: SwordAttentionReason[] = ['form_unknown', 'form_ambiguous', 'duplicate_fingerprint', 'stale_annotation', 'level_unknown']

export interface ArchiveAttentionGroup {
  reason: SwordAttentionReason
  title: string
  items: SwordArchiveAttentionItem[]
}

function reasonRank(reason: SwordAttentionReason): number {
  const index = ATTENTION_REASON_ORDER.indexOf(reason)
  return index < 0 ? ATTENTION_REASON_ORDER.length : index
}

// 按首条 reason 分组：一条一般就一个主因；多因的归第一条，免得同一张卡片
// 在好几个组里重复出现。组间按 ATTENTION_REASON_ORDER 排，认不出的 reason 殿后。
export function groupAttentionItems(items: SwordArchiveAttentionItem[]): ArchiveAttentionGroup[] {
  const groups: ArchiveAttentionGroup[] = []
  for (const item of items) {
    const reason = item.reasons[0] ?? 'form_unknown'
    let group = groups.find(candidate => candidate.reason === reason)
    if (!group) {
      group = { reason, title: ATTENTION_REASON_TEXT[reason] || reason, items: [] }
      groups.push(group)
    }
    group.items.push(item)
  }
  return groups.sort((a, b) => reasonRank(a.reason) - reasonRank(b.reason))
}

// ---- 标注请求体 ----

// 档案行和 attention 条目都够格当标注目标（字段名一致）。
export interface ArchiveAnnotationTarget {
  sword_catalog_id: string | null
  kiwame_date: string | null
  level?: number | null
  reasons?: SwordAttentionReason[]
}

export type ArchiveHumanLike = Pick<SwordArchiveHuman, 'form' | 'keeper' | 'favorite' | 'watch' | 'note' | 'level'>

function baseBody(target: ArchiveAnnotationTarget): SwordAnnotationBody {
  return { sword_catalog_id: target.sword_catalog_id, kiwame_date: target.kiwame_date }
}

// 旧标注的人工等级原样递回（有的话）——它是合并进档案的空缺补值，
// 别的字段翻位时不该把它弄丢。
function preserveLevel(body: SwordAnnotationBody, human?: ArchiveHumanLike | null) {
  if (human && human.level != null) body.level_confirmed = human.level
}

// 旧标注的三个标记位（keeper/favorite/watch）原样递回——单字段翻位时
// 别把别的标记顺手清掉。没标注（human 为 null）就不递，干净新建。
function preserveMarks(body: SwordAnnotationBody, human: ArchiveHumanLike) {
  body.keeper = human.keeper
  body.favorite = human.favorite
  body.watch = human.watch
}

// 确认形态：只翻 form 这一位，旧标注的标记/备注/等级原样递回，
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
    preserveMarks(body, human)
    body.note = human.note
  }
  preserveLevel(body, human)
  return body
}

// 要练开关：只翻 keeper 这一位（next 由调用方算好取反），
// 旧标注的形态结论/其余标记/备注/等级原样递回。没标注时就只递 keeper 新建。
export function keeperBody(
  target: ArchiveAnnotationTarget,
  next: boolean,
  human?: ArchiveHumanLike | null,
): SwordAnnotationBody {
  const body = baseBody(target)
  body.keeper = next
  if (human) {
    body.form_confirmed = human.form
    body.favorite = human.favorite
    body.watch = human.watch
    body.note = human.note
  }
  preserveLevel(body, human)
  return body
}

// 常用开关：只翻 favorite 这一位，其余照 keeperBody 的纪律原样递回。
export function favoriteBody(
  target: ArchiveAnnotationTarget,
  next: boolean,
  human?: ArchiveHumanLike | null,
): SwordAnnotationBody {
  const body = baseBody(target)
  body.favorite = next
  if (human) {
    body.form_confirmed = human.form
    body.keeper = human.keeper
    body.watch = human.watch
    body.note = human.note
  }
  preserveLevel(body, human)
  return body
}

// 特别关心开关：只翻 watch 这一位，其余照 keeperBody 的纪律原样递回。
// 组件里别解构 human.watch——和 vue 的 watch API 撞名，全程走 entry.human?.watch。
export function watchBody(
  target: ArchiveAnnotationTarget,
  next: boolean,
  human?: ArchiveHumanLike | null,
): SwordAnnotationBody {
  const body = baseBody(target)
  body.watch = next
  if (human) {
    body.form_confirmed = human.form
    body.keeper = human.keeper
    body.favorite = human.favorite
    body.note = human.note
  }
  preserveLevel(body, human)
  return body
}

// 输入框草稿 → 等级：空/非数/非整数/超界都给 null（按钮据此禁用）。
export function parseLevelInput(raw: string): number | null {
  const text = raw.trim()
  if (!text) return null
  const value = Number(text)
  if (!Number.isInteger(value) || value < 1 || value > 99) return null
  return value
}

// 记下等级：只翻 level_confirmed 这一位，旧标注的 form/标记/note 原样递回。
// 等级限 1~99 整数，非法返回 null（组件据 null 拒绝提交并提示）。
export function levelConfirmBody(
  target: ArchiveAnnotationTarget,
  level: number,
  human?: ArchiveHumanLike | null,
): SwordAnnotationBody | null {
  if (!Number.isInteger(level) || level < 1 || level > 99) return null
  const body = baseBody(target)
  body.level_confirmed = level
  if (human) {
    body.form_confirmed = human.form
    preserveMarks(body, human)
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
