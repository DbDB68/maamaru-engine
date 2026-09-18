import { describe, expect, it } from 'vitest'
import type { SwordArchiveAttentionItem, SwordArchiveEntry, SwordArchiveHuman } from './types'
import {
  ARCHIVE_ALL_TYPES,
  ATTENTION_REASON_TEXT,
  attentionReasonTexts,
  attentionTarget,
  archiveFormLabel,
  duplicateOrdinals,
  filterArchiveEntries,
  formConfirmBody,
  keeperBody,
  sortArchiveEntries,
} from './archive'

function entry(over: Partial<SwordArchiveEntry> = {}): SwordArchiveEntry {
  return {
    observation_id: '9:41',
    sword_catalog_id: '00003',
    name_zh: '三日月宗近',
    sword_type: '太刀',
    level: 99,
    tou_level: 4,
    kiwame_date: '2026-01-01',
    form_status: 'unknown',
    form_evidence: [],
    unknown_fields: [],
    human: null,
    hints: [],
    ...over,
  }
}

function attention(over: Partial<SwordArchiveAttentionItem> = {}): SwordArchiveAttentionItem {
  return {
    observation_id: '9:41',
    sword_catalog_id: '00003',
    name_zh: '三日月宗近',
    level: 99,
    kiwame_date: '2026-01-01',
    reasons: ['form_unknown'],
    hints: [],
    ...over,
  }
}

function human(over: Partial<SwordArchiveHuman> = {}): SwordArchiveHuman {
  return {
    id: 7,
    form: 'kiwame',
    keeper: true,
    note: '修行回来的',
    confirmed_at: 1700000000,
    stale: false,
    ...over,
  }
}

describe('形态标签', () => {
  it('只认档案结论：kiwame=极 / normal=普通 / ambiguous=存疑 / 其余=未确认', () => {
    expect(archiveFormLabel(entry({ form_status: 'kiwame' }))).toBe('极')
    expect(archiveFormLabel(entry({ form_status: 'normal' }))).toBe('普通')
    expect(archiveFormLabel(entry({ form_status: 'ambiguous' }))).toBe('存疑')
    expect(archiveFormLabel(entry({ form_status: 'unknown' }))).toBe('未确认')
    // kiwame_date 是显现日期，有值也推不出极（和编队页同一条 P0 纪律）
    expect(archiveFormLabel(entry({ form_status: 'unknown', kiwame_date: '2020-01-01' }))).toBe('未确认')
  })
})

describe('同名编号与整本排序', () => {
  it('同 sword_catalog_id 多振按显现日期升序编号，没日期的排最后', () => {
    const rows = [
      entry({ observation_id: '9:1', sword_catalog_id: '00005', name_zh: '小狐丸', kiwame_date: '2026-03-01' }),
      entry({ observation_id: '9:2', sword_catalog_id: '00005', name_zh: '小狐丸', kiwame_date: null }),
      entry({ observation_id: '9:3', sword_catalog_id: '00005', name_zh: '小狐丸', kiwame_date: '2026-01-01' }),
      entry({ observation_id: '9:4', sword_catalog_id: '00007', name_zh: '石切丸', kiwame_date: '2026-02-01' }),
    ]
    const ordinals = duplicateOrdinals(rows)
    expect(ordinals.get('9:3')).toBe(1)
    expect(ordinals.get('9:1')).toBe(2)
    expect(ordinals.get('9:2')).toBe(3)
    // 只有一振的不编号
    expect(ordinals.has('9:4')).toBe(false)
  })

  it('编号跟日期走，不认传入顺序（乱序输入也得编对）', () => {
    const rows = [
      entry({ observation_id: '9:9', sword_catalog_id: '00005', kiwame_date: null }),
      entry({ observation_id: '9:8', sword_catalog_id: '00005', kiwame_date: '2026-05-05' }),
      entry({ observation_id: '9:7', sword_catalog_id: '00005', kiwame_date: '2026-04-04' }),
    ]
    const ordinals = duplicateOrdinals(rows)
    expect([...ordinals.entries()].sort()).toEqual([['9:7', 1], ['9:8', 2], ['9:9', 3]])
  })

  it('认不出 catalog id 的刀没法证明是同名多振，不许互相串组编号', () => {
    const rows = [
      entry({ observation_id: '9:1', sword_catalog_id: null, name_zh: null }),
      entry({ observation_id: '9:2', sword_catalog_id: null, name_zh: null }),
    ]
    const ordinals = duplicateOrdinals(rows)
    expect(ordinals.size).toBe(0)
  })

  it('整本排序：按刀名分组（拼音序），组内按显现日期升序，没日期的排最后，没名字的排最后', () => {
    const rows = [
      entry({ observation_id: '9:1', name_zh: '小狐丸', kiwame_date: '2026-03-01' }),
      entry({ observation_id: '9:2', name_zh: null, sword_catalog_id: null, kiwame_date: '2026-01-01' }),
      entry({ observation_id: '9:3', name_zh: '小狐丸', kiwame_date: null }),
      entry({ observation_id: '9:4', name_zh: '小狐丸', kiwame_date: '2026-01-01' }),
      entry({ observation_id: '9:5', name_zh: '石切丸', kiwame_date: null }),
    ]
    const sorted = sortArchiveEntries(rows)
    expect(sorted.map(row => row.observation_id)).toEqual(['9:5', '9:4', '9:1', '9:3', '9:2'])
  })
})

describe('搜索与刀种筛选', () => {
  const rows = [
    entry({ observation_id: '9:1', name_zh: '三日月宗近', sword_type: '太刀' }),
    entry({ observation_id: '9:2', name_zh: '小狐丸', sword_type: '太刀' }),
    entry({ observation_id: '9:3', name_zh: '加州清光', sword_type: '打刀' }),
    entry({ observation_id: '9:4', name_zh: null, sword_catalog_id: '00123', sword_type: null }),
  ]

  it('刀种筛选：全部不挑，挑具体刀种时认不出刀种的不算', () => {
    expect(filterArchiveEntries(rows, '', ARCHIVE_ALL_TYPES)).toHaveLength(4)
    expect(filterArchiveEntries(rows, '', '太刀').map(row => row.observation_id)).toEqual(['9:1', '9:2'])
    expect(filterArchiveEntries(rows, '', '打刀')).toHaveLength(1)
    expect(filterArchiveEntries(rows, '', '短刀')).toHaveLength(0)
  })

  it('搜索按刀名；认不出名字的按刀帐编号兜底', () => {
    expect(filterArchiveEntries(rows, '小狐丸', ARCHIVE_ALL_TYPES)).toHaveLength(1)
    expect(filterArchiveEntries(rows, ' 清光 ', ARCHIVE_ALL_TYPES)).toHaveLength(1)
    expect(filterArchiveEntries(rows, '00123', ARCHIVE_ALL_TYPES).map(row => row.observation_id)).toEqual(['9:4'])
    expect(filterArchiveEntries(rows, '不存在的刀', ARCHIVE_ALL_TYPES)).toHaveLength(0)
  })

  it('搜索和刀种可以叠加', () => {
    expect(filterArchiveEntries(rows, '小狐丸', '打刀')).toHaveLength(0)
    expect(filterArchiveEntries(rows, '小狐丸', '太刀')).toHaveLength(1)
  })
})

describe('reason 人话', () => {
  it('四种 reason 各归各的说法', () => {
    expect(ATTENTION_REASON_TEXT.form_unknown).toBe('分不清极/普通')
    expect(ATTENTION_REASON_TEXT.form_ambiguous).toBe('两处证据打架')
    expect(ATTENTION_REASON_TEXT.duplicate_fingerprint).toBe('同名同日多振，要你指认')
    expect(ATTENTION_REASON_TEXT.stale_annotation).toBe('之前的确认对不上号了')
  })

  it('逐条翻译、保留顺序；不认识的 reason 原样透出，不炸页面', () => {
    expect(attentionReasonTexts(['duplicate_fingerprint', 'stale_annotation']))
      .toEqual(['同名同日多振，要你指认', '之前的确认对不上号了'])
    expect(attentionReasonTexts(['some_new_reason' as never])).toEqual(['some_new_reason'])
  })
})

describe('标注请求体', () => {
  it('确认形态：同名同日多振要把等级作为 level_at_mark 带上，别的 reason 不带', () => {
    const dup = attention({ reasons: ['duplicate_fingerprint'], level: 42 })
    expect(formConfirmBody(attentionTarget(dup), 'kiwame')).toEqual({
      sword_catalog_id: '00003',
      kiwame_date: '2026-01-01',
      form_confirmed: 'kiwame',
      level_at_mark: 42,
    })
    const unknown = attention({ reasons: ['form_unknown'], level: 42 })
    const body = formConfirmBody(attentionTarget(unknown), 'normal')
    expect(body.level_at_mark).toBeUndefined()
    expect(body.form_confirmed).toBe('normal')
  })

  it('确认形态带上旧标注时，keeper/note 原样递回，只翻 form', () => {
    const dup = attention({ reasons: ['duplicate_fingerprint'] })
    const body = formConfirmBody(attentionTarget(dup), 'normal', human())
    expect(body.form_confirmed).toBe('normal')
    expect(body.keeper).toBe(true)
    expect(body.note).toBe('修行回来的')
  })

  it('要练开关：没标注时只递 keeper=true 新建', () => {
    expect(keeperBody(attentionTarget(attention()), true)).toEqual({
      sword_catalog_id: '00003',
      kiwame_date: '2026-01-01',
      keeper: true,
    })
  })

  it('要练开关：有标注时取反，并把旧形态/备注原样带回', () => {
    const off = keeperBody(attentionTarget(attention()), true, human({ keeper: false }))
    expect(off.keeper).toBe(true)
    expect(off.form_confirmed).toBe('kiwame')
    expect(off.note).toBe('修行回来的')
    const on = keeperBody(attentionTarget(attention()), false, human({ keeper: true, form: null, note: null }))
    expect(on.keeper).toBe(false)
    expect(on.form_confirmed).toBeNull()
    expect(on.note).toBeNull()
  })
})
