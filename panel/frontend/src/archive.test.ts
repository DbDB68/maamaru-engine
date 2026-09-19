import { describe, expect, it } from 'vitest'
import type { SwordArchiveAttentionItem, SwordArchiveEntry, SwordArchiveHuman } from './types'
import {
  ARCHIVE_ALL_TYPES,
  ATTENTION_REASON_TEXT,
  archiveFormLabel,
  archiveFormSource,
  attentionReasonTexts,
  attentionTarget,
  duplicateOrdinals,
  favoriteBody,
  filterArchiveEntries,
  formConfirmBody,
  groupAttentionItems,
  keeperBody,
  levelConfirmBody,
  parseLevelInput,
  partitionWatchEntries,
  sortArchiveEntries,
  watchBody,
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
    machine_form_status: null,
    form_overridden: false,
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
    favorite: false,
    watch: false,
    note: '修行回来的',
    level: null,
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

  it('整本排序：按刀帐番号升序（对齐游戏刀帐顺序），同名多振组内按显现日期升序，番号认不出的排最后', () => {
    const rows = [
      entry({ observation_id: '9:1', sword_catalog_id: 'touken_005_kogitsunemaru', name_zh: '小狐丸', kiwame_date: '2026-03-01' }),
      entry({ observation_id: '9:2', sword_catalog_id: null, name_zh: null, kiwame_date: '2026-01-01' }),
      entry({ observation_id: '9:3', sword_catalog_id: 'touken_005_kogitsunemaru', name_zh: '小狐丸', kiwame_date: null }),
      entry({ observation_id: '9:4', sword_catalog_id: 'touken_005_kogitsunemaru', name_zh: '小狐丸', kiwame_date: '2026-01-01' }),
      entry({ observation_id: '9:5', sword_catalog_id: 'touken_003_mikazuki', name_zh: '三日月宗近', kiwame_date: null }),
    ]
    const sorted = sortArchiveEntries(rows)
    // 3 号三日月在最前；5 号小狐丸三振挨着（有日期的升序，没日期的殿后）；
    // 认不出番号的 9:2 排整本最后
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
  it('五种 reason 各归各的说法', () => {
    expect(ATTENTION_REASON_TEXT.form_unknown).toBe('形态没读出来')
    expect(ATTENTION_REASON_TEXT.form_ambiguous).toBe('两处证据打架')
    expect(ATTENTION_REASON_TEXT.duplicate_fingerprint).toBe('同名同日多振，指纹撞车')
    expect(ATTENTION_REASON_TEXT.stale_annotation).toBe('标注对不上号')
    expect(ATTENTION_REASON_TEXT.level_unknown).toBe('等级没读出来')
  })

  it('reasons 可多值并存，逐条翻译、保留顺序；不认识的 reason 原样透出，不炸页面', () => {
    expect(attentionReasonTexts(['form_unknown', 'level_unknown']))
      .toEqual(['形态没读出来', '等级没读出来'])
    expect(attentionReasonTexts(['duplicate_fingerprint', 'stale_annotation']))
      .toEqual(['同名同日多振，指纹撞车', '标注对不上号'])
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

  it('翻别的位时不弄丢人工等级：form/keeper 确认带旧 level_confirmed 递回', () => {
    const byForm = formConfirmBody(attentionTarget(attention()), 'normal', human({ level: 55 }))
    expect(byForm.level_confirmed).toBe(55)
    const byKeeper = keeperBody(attentionTarget(attention()), false, human({ level: 55 }))
    expect(byKeeper.level_confirmed).toBe(55)
    // 旧标注没有等级时不递这个键
    expect(formConfirmBody(attentionTarget(attention()), 'normal', human()).level_confirmed).toBeUndefined()
    expect(keeperBody(attentionTarget(attention()), true, null).level_confirmed).toBeUndefined()
  })
})

describe('等级填写', () => {
  it('parseLevelInput：空/非数/非整数/超界都给 null，合法值放行', () => {
    expect(parseLevelInput('')).toBeNull()
    expect(parseLevelInput('   ')).toBeNull()
    expect(parseLevelInput('abc')).toBeNull()
    expect(parseLevelInput('1.5')).toBeNull()
    expect(parseLevelInput('0')).toBeNull()
    expect(parseLevelInput('100')).toBeNull()
    expect(parseLevelInput('-3')).toBeNull()
    expect(parseLevelInput('42')).toBe(42)
    expect(parseLevelInput(' 9 ')).toBe(9)
    expect(parseLevelInput('99')).toBe(99)
    expect(parseLevelInput('1')).toBe(1)
  })

  it('levelConfirmBody：只翻 level_confirmed 一位，旧标注的 form/keeper/note 原样递回', () => {
    expect(levelConfirmBody(attentionTarget(attention()), 42)).toEqual({
      sword_catalog_id: '00003',
      kiwame_date: '2026-01-01',
      level_confirmed: 42,
    })
    const body = levelConfirmBody(attentionTarget(attention()), 42, human())
    expect(body).toEqual({
      sword_catalog_id: '00003',
      kiwame_date: '2026-01-01',
      level_confirmed: 42,
      form_confirmed: 'kiwame',
      keeper: true,
      favorite: false,
      watch: false,
      note: '修行回来的',
    })
  })

  it('levelConfirmBody：1 和 99 边界放行，0/100/小数/NaN 返回 null', () => {
    expect(levelConfirmBody(attentionTarget(attention()), 1)?.level_confirmed).toBe(1)
    expect(levelConfirmBody(attentionTarget(attention()), 99)?.level_confirmed).toBe(99)
    expect(levelConfirmBody(attentionTarget(attention()), 0)).toBeNull()
    expect(levelConfirmBody(attentionTarget(attention()), 100)).toBeNull()
    expect(levelConfirmBody(attentionTarget(attention()), 55.5)).toBeNull()
    expect(levelConfirmBody(attentionTarget(attention()), Number.NaN)).toBeNull()
    expect(levelConfirmBody(attentionTarget(attention()), Number('x'))).toBeNull()
  })
})


describe('常用/特别关心开关', () => {
  it('favoriteBody：没标注时只递 favorite 新建', () => {
    expect(favoriteBody(attentionTarget(attention()), true)).toEqual({
      sword_catalog_id: '00003',
      kiwame_date: '2026-01-01',
      favorite: true,
    })
  })

  it('favoriteBody：只翻 favorite 一位，旧标注的形态/要练/特别关心/备注/等级原样递回', () => {
    const body = favoriteBody(attentionTarget(attention()), true, human({ favorite: false, watch: true, level: 55 }))
    expect(body.favorite).toBe(true)
    expect(body.form_confirmed).toBe('kiwame')
    expect(body.keeper).toBe(true)
    expect(body.watch).toBe(true)
    expect(body.note).toBe('修行回来的')
    expect(body.level_confirmed).toBe(55)
  })

  it('watchBody：没标注时只递 watch 新建', () => {
    expect(watchBody(attentionTarget(attention()), true)).toEqual({
      sword_catalog_id: '00003',
      kiwame_date: '2026-01-01',
      watch: true,
    })
  })

  it('watchBody：只翻 watch 一位，旧标注的其余字段原样递回（取反点亮/熄灭都对）', () => {
    const on = watchBody(attentionTarget(attention()), true, human({ keeper: false, favorite: true }))
    expect(on.watch).toBe(true)
    expect(on.favorite).toBe(true)
    expect(on.keeper).toBe(false)
    expect(on.form_confirmed).toBe('kiwame')
    const off = watchBody(attentionTarget(attention()), false, human({ watch: true }))
    expect(off.watch).toBe(false)
    // 没有等级的旧标注不递 level_confirmed
    expect(off.level_confirmed).toBeUndefined()
  })

  it('翻别的位时三个标记互不牵连：form/keeper/level 确认都原样递回 favorite/watch', () => {
    const byForm = formConfirmBody(attentionTarget(attention()), 'normal', human({ favorite: true, watch: true }))
    expect(byForm.favorite).toBe(true)
    expect(byForm.watch).toBe(true)
    const byKeeper = keeperBody(attentionTarget(attention()), false, human({ favorite: true }))
    expect(byKeeper.favorite).toBe(true)
    expect(byKeeper.watch).toBe(false)
    const byLevel = levelConfirmBody(attentionTarget(attention()), 42, human({ watch: true }))
    expect(byLevel?.favorite).toBe(false)
    expect(byLevel?.watch).toBe(true)
  })
})

describe('形态来源徽标', () => {
  it('没人碰过 → machine（盘点识别），哪怕档案形态已经有机器结论', () => {
    expect(archiveFormSource(entry({ human: null, machine_form_status: 'kiwame', form_overridden: false })))
      .toEqual({ kind: 'machine' })
  })

  it('有人工结论且和机器不冲突 → human（你确认过）', () => {
    expect(archiveFormSource(entry({ human: human(), machine_form_status: 'kiwame', form_overridden: false })))
      .toEqual({ kind: 'human' })
  })

  it('人工与机器冲突 → overridden（你改判的），附带机器原识别：极/普通/存疑', () => {
    expect(archiveFormSource(entry({ human: human(), machine_form_status: 'kiwame', form_overridden: true })))
      .toEqual({ kind: 'overridden', machineText: '极' })
    expect(archiveFormSource(entry({ human: human({ form: 'normal' }), machine_form_status: 'normal', form_overridden: true })))
      .toEqual({ kind: 'overridden', machineText: '普通' })
    expect(archiveFormSource(entry({ human: human(), machine_form_status: 'ambiguous', form_overridden: true })))
      .toEqual({ kind: 'overridden', machineText: '存疑' })
  })

  it('form_overridden 但机器没结论（null/unknown）→ 兜底「未确认」，不炸页面', () => {
    expect(archiveFormSource(entry({ human: human(), machine_form_status: null, form_overridden: true })))
      .toEqual({ kind: 'overridden', machineText: '未确认' })
    expect(archiveFormSource(entry({ human: human(), machine_form_status: 'unknown', form_overridden: true })))
      .toEqual({ kind: 'overridden', machineText: '未确认' })
  })
})

describe('特别关心置顶', () => {
  it('watch 的刀单独成组排最前，组内和其余都保持整本排序不变', () => {
    const rows = [
      entry({ observation_id: '9:1', sword_catalog_id: 'touken_003_mikazuki' }),
      entry({ observation_id: '9:2', sword_catalog_id: 'touken_005_kogitsunemaru', human: human({ watch: true }) }),
      entry({ observation_id: '9:3', sword_catalog_id: 'touken_007_ishikiri' }),
      entry({ observation_id: '9:4', sword_catalog_id: 'touken_009_iwatooshi', human: human({ watch: true }) }),
    ]
    const sorted = sortArchiveEntries(rows)
    const { watched, rest } = partitionWatchEntries(sorted)
    const sortedIds = sorted.map(row => row.observation_id)
    // 切分不是重排：两组各自保持整本排序里的相对顺序
    expect(watched.map(row => row.observation_id))
      .toEqual(sortedIds.filter(id => ['9:2', '9:4'].includes(id)))
    expect(rest.map(row => row.observation_id))
      .toEqual(sortedIds.filter(id => !['9:2', '9:4'].includes(id)))
  })

  it('没人标 watch 时 watched 为空，rest 是全部；human 为 null 的行不炸', () => {
    const rows = [entry({ observation_id: '9:1' }), entry({ observation_id: '9:2', human: null })]
    const { watched, rest } = partitionWatchEntries(rows)
    expect(watched).toHaveLength(0)
    expect(rest.map(row => row.observation_id)).toEqual(['9:1', '9:2'])
  })
})

describe('待核对分组', () => {
  it('按首条 reason 分组，组标题用人话，组间按上手优先级排序', () => {
    const items = [
      attention({ observation_id: '9:1', reasons: ['level_unknown'] }),
      attention({ observation_id: '9:2', reasons: ['duplicate_fingerprint'] }),
      attention({ observation_id: '9:3', reasons: ['form_unknown', 'level_unknown'] }),
      attention({ observation_id: '9:4', reasons: ['stale_annotation'] }),
      attention({ observation_id: '9:5', reasons: ['form_ambiguous'] }),
      attention({ observation_id: '9:6', reasons: ['form_unknown'] }),
    ]
    const groups = groupAttentionItems(items)
    expect(groups.map(group => group.reason))
      .toEqual(['form_unknown', 'form_ambiguous', 'duplicate_fingerprint', 'stale_annotation', 'level_unknown'])
    expect(groups.map(group => group.title))
      .toEqual(['形态没读出来', '两处证据打架', '同名同日多振，指纹撞车', '标注对不上号', '等级没读出来'])
    // 多因条目归首条 reason 那一组，不跨组重复
    expect(groups[0].items.map(item => item.observation_id)).toEqual(['9:3', '9:6'])
    expect(groups.reduce((sum, group) => sum + group.items.length, 0)).toBe(items.length)
  })

  it('空清单返回空数组；认不出的 reason 也能兜出组来', () => {
    expect(groupAttentionItems([])).toEqual([])
    const groups = groupAttentionItems([attention({ observation_id: '9:1', reasons: ['some_new_reason' as never] })])
    expect(groups).toHaveLength(1)
    expect(groups[0].title).toBe('some_new_reason')
    expect(groups[0].items).toHaveLength(1)
  })
})
