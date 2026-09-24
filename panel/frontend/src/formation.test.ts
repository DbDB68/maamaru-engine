import { describe, expect, it } from 'vitest'
import type { CustomFormation, FormationCandidate } from './types'
import {
  candidateEvidenceGaps,
  candidateFormLabel,
  candidateName,
  presetCandidatePickable,
  presetLabel,
  presetSlotCount,
  presetSlotSummary,
  validatePresetDraft,
} from './formation'

function entry(over: Partial<FormationCandidate> = {}): FormationCandidate {
  return {
    observation_id: '9:41',
    row_no: 41,
    sword_catalog_id: '00003',
    same_team_exclusion_key: '00003',
    name_zh: '三日月宗近',
    level: 99,
    tou_level: 4,
    survival: 60,
    survival_max: 60,
    fatigue: 100,
    fatigue_max: 100,
    stats: {},
    kiwame_date: '2026-01-01',
    locked: true,
    page_no: 3,
    unknown_fields: [],
    observed_at: 1700000000,
    source_snapshot_id: 9,
    ...over,
  }
}

describe('候选展示', () => {
  it('形态只认档案结论；kiwame_date 是显现日期，有值也推不出极（P0 反例）', () => {
    // 旧规矩「kiwame_date 有值=极」把 185/196 振全盖了极章，钉死反例
    expect(candidateFormLabel(entry())).toBe('未确认')
    expect(candidateFormLabel(entry({ kiwame_date: null }))).toBe('未确认')
    expect(candidateFormLabel(entry({ form_status: 'kiwame' }))).toBe('极')
    expect(candidateFormLabel(entry({ form_status: 'normal' }))).toBe('普通')
    expect(candidateFormLabel(entry({ form_status: 'ambiguous' }))).toBe('未确认')
  })

  it('同名多振不合并：每条候选各自带 identity，展示名回退链稳定', () => {
    expect(candidateName(entry())).toBe('三日月宗近')
    expect(candidateName(entry({ name_zh: null }))).toBe('00003')
    expect(candidateName(entry({ name_zh: null, sword_catalog_id: null }))).toBe('没认出名字')
  })

  it('身份证据缺口：缺名字或缺等级都要如实列出', () => {
    expect(candidateEvidenceGaps(entry())).toEqual([])
    expect(candidateEvidenceGaps(entry({ level: null }))).toEqual(['等级'])
    expect(candidateEvidenceGaps(entry({ name_zh: null, sword_catalog_id: null }))).toEqual(['名字'])
  })
})

function preset(over: Partial<CustomFormation> = {}): CustomFormation {
  return {
    id: 'pf1',
    name: '预设编队一',
    target_team: 3,
    slots: {
      '2': { sword_catalog_id: '00003', name_zh: '三日月宗近', level: 99, form_status: 'kiwame', kiwame_date: '2026-01-01' },
    },
    created_at: '2026-09-18T12:00:00',
    updated_at: '2026-09-18T12:00:00',
    ...over,
  }
}

describe('预设编队', () => {
  it('卡片标题：名字 + 覆盖部队（部队一~五的中文数字）', () => {
    expect(presetLabel(preset())).toBe('预设编队一（覆盖部队三）')
    expect(presetLabel(preset({ target_team: 1 }))).toBe('预设编队一（覆盖部队一）')
    expect(presetLabel(preset({ target_team: 5 }))).toBe('预设编队一（覆盖部队五）')
  })

  it('已指定槽数：只数 1~6 里真带了刀身份的格子，空槽/越界键不算', () => {
    expect(presetSlotCount(preset({ slots: {} }))).toBe(0)
    expect(presetSlotCount(preset())).toBe(1)
    expect(presetSlotCount(preset({ slots: { '1': {}, '6': { name_zh: '小狐丸' } } }))).toBe(1)
    expect(presetSlotCount(preset({ slots: { '0': { name_zh: '岩融' }, '7': { name_zh: '今剣' } } }))).toBe(0)
  })

  it('校验：名字非空 ≤20 字、目标部队 1~5；一个位置都不指定也放行（UI 另行提示）', () => {
    const ok = { name: '演练队', target_team: 2, slots: { '1': { name_zh: '三日月宗近' } } }
    expect(validatePresetDraft(ok)).toBeNull()
    expect(validatePresetDraft({ ...ok, name: '   ' })).toContain('名字')
    expect(validatePresetDraft({ ...ok, name: '一'.repeat(21) })).toContain('20')
    expect(validatePresetDraft({ ...ok, target_team: 0 })).toContain('部队')
    expect(validatePresetDraft({ ...ok, target_team: 6 })).toContain('部队')
    expect(validatePresetDraft({ ...ok, target_team: 2.5 })).toContain('部队')
    expect(validatePresetDraft({ ...ok, slots: {} })).toBeNull()
    expect(validatePresetDraft({ ...ok, slots: { '1': {
      selection_policy: 'locked_highest_level', sword_catalog_id: '00005', form_status: 'normal',
    } } })).toBeNull()
    expect(validatePresetDraft({ ...ok, slots: { '1': {
      selection_policy: 'locked_highest_level', sword_catalog_id: '00005',
    } } })).toContain('形态')
  })

  it('格子小字：有快照显示「名字（形态 · 等级）」，空槽显示「不动」', () => {
    expect(presetSlotSummary(null)).toBe('不动')
    expect(presetSlotSummary(preset().slots['2'])).toBe('三日月宗近（极 · Lv.99）')
    expect(presetSlotSummary({ name_zh: '小狐丸', form_status: 'normal' })).toBe('小狐丸（普通）')
    expect(presetSlotSummary({ sword_catalog_id: '00005' })).toBe('00005（未确认）')
    expect(presetSlotSummary({ selection_policy: 'locked_highest_level',
      name_zh: '小狐丸', form_status: 'kiwame' })).toBe('小狐丸（极 · 上锁最高级）')
  })

  it('宝物需完整可见条件；不同宝物可分配多槽，同一件不能重复', () => {
    const treasure = { name: '锷·月下梅树透图', level: 1, affection: 0 }
    const slot = { name_zh: '小狐丸', treasure }
    expect(validatePresetDraft({ name: '出阵', target_team: 3, slots: { '1': slot } })).toBeNull()
    expect(presetSlotSummary(slot)).toContain('宝物：锷·月下梅树透图')
    expect(validatePresetDraft({ name: '出阵', target_team: 3,
      slots: { '1': { ...slot, treasure: { ...treasure, name: '' } } } })).toContain('宝物')
    expect(validatePresetDraft({ name: '出阵', target_team: 3,
      slots: { '1': slot, '2': { name_zh: '今剑', treasure } } })).toContain('不能指定给多个位置')
    expect(validatePresetDraft({ name: '出阵', target_team: 3,
      slots: { '1': slot, '2': { name_zh: '今剑', treasure: { ...treasure, name: '三所物·菊' } } } })).toBeNull()
    const equipped = { ...slot, troops: { '1': '轻步兵·特上', '3': '盾兵·特上' } }
    expect(validatePresetDraft({ name: '出阵', target_team: 3, slots: { '1': equipped } })).toBeNull()
    expect(presetSlotSummary(equipped)).toContain('刀装 2 格')
    expect(validatePresetDraft({ name: '出阵', target_team: 3,
      slots: { '1': { ...slot, troops: { '4': '轻步兵·特上' } } } })).toContain('刀装')
  })

  it('选刀池：没认出名字的候选禁选，有图鉴号兜底或缺等级的照常能选', () => {
    expect(presetCandidatePickable(entry())).toBe(true)
    expect(presetCandidatePickable(entry({ name_zh: null, sword_catalog_id: null }))).toBe(false)
    expect(presetCandidatePickable(entry({ name_zh: null }))).toBe(true)
    expect(presetCandidatePickable(entry({ level: null }))).toBe(true)
  })
})
