import { describe, expect, it } from 'vitest'
import type { CustomFormation, FormationCandidate, FormationSwapEvent } from './types'
import {
  FORMATION_RESULT_TEXT,
  candidateEvidenceGaps,
  candidateFormLabel,
  candidateName,
  formationResultText,
  pickSwapEvent,
  presetCandidatePickable,
  presetLabel,
  presetSlotCount,
  presetSlotSummary,
  swapEligibility,
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

function swapEvent(runId: string, result = 'changed'): FormationSwapEvent {
  return {
    id: 1,
    ts: 1700000000,
    run_id: runId,
    script: 'formation',
    event_type: 'formation.member_ensured',
    payload: {
      team_no: 2,
      slot_no: 3,
      result: result as FormationSwapEvent['payload']['result'],
      reason: '回读逐项验收通过',
    },
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

describe('换人门闩', () => {
  const base = { poolDone: true, running: false, slotNo: 3, candidate: entry() }

  it('档案不完整先拦，指引去盘点', () => {
    const verdict = swapEligibility({ ...base, poolDone: false, poolReason: '只有残缺盘点' })
    expect(verdict.ok).toBe(false)
    expect(verdict.reason).toContain('只有残缺盘点')
    expect(verdict.reason).toContain('刀帐盘点')
  })

  it('任务占用先拦，且优先于位置/目标检查', () => {
    const verdict = swapEligibility({ ...base, running: true, slotNo: null, candidate: null })
    expect(verdict.ok).toBe(false)
    expect(verdict.reason).toContain('正在运行')
  })

  it('没选位置或没选目标都拦', () => {
    expect(swapEligibility({ ...base, slotNo: null }).ok).toBe(false)
    expect(swapEligibility({ ...base, candidate: null }).ok).toBe(false)
  })

  it('目标缺身份证据（名字/等级）拦下并说清下一步', () => {
    const noName = swapEligibility({ ...base, candidate: entry({ name_zh: null, sword_catalog_id: null }) })
    expect(noName.ok).toBe(false)
    expect(noName.reason).toContain('名字')
    const noLevel = swapEligibility({ ...base, candidate: entry({ level: null }) })
    expect(noLevel.ok).toBe(false)
    expect(noLevel.reason).toContain('等级')
    expect(noLevel.reason).toContain('刀帐盘点')
  })

  it('档案可信 + 没在跑 + 位置目标齐全 + 证据充分才放行', () => {
    expect(swapEligibility(base)).toEqual({ ok: true, reason: '' })
  })
})

describe('结果文案', () => {
  it('八种机器结果各有自己的生活化说法，没有统一「失败」', () => {
    const codes = ['changed', 'already_correct', 'ambiguous', 'not_found',
      'unavailable', 'screen_unrecognized', 'verification_failed', 'invalid_request'] as const
    const titles = new Set(codes.map(code => FORMATION_RESULT_TEXT[code].title))
    expect(titles.size).toBe(codes.length)
    for (const code of codes) {
      expect(FORMATION_RESULT_TEXT[code].title).not.toBe('失败')
      expect(FORMATION_RESULT_TEXT[code].detail.length).toBeGreaterThan(0)
    }
  })

  it('只有 changed / already_correct 是办成，其余都不是 ok 色调', () => {
    expect(FORMATION_RESULT_TEXT.changed.tone).toBe('ok')
    expect(FORMATION_RESULT_TEXT.already_correct.tone).toBe('ok')
    for (const code of ['ambiguous', 'not_found', 'unavailable'] as const) {
      expect(FORMATION_RESULT_TEXT[code].tone).toBe('warn')
    }
    for (const code of ['screen_unrecognized', 'verification_failed', 'invalid_request'] as const) {
      expect(FORMATION_RESULT_TEXT[code].tone).toBe('bad')
    }
  })

  it('不认识的结果给兜底文案，不炸页面', () => {
    expect(formationResultText('weird_new_code').title).toBe('结果没看懂')
  })
})

describe('回读验收事件', () => {
  it('只认本轮 run_id 的事件，别的任务/旧事件不算数', () => {
    const events = [swapEvent('other-run'), swapEvent('my-run'), swapEvent('my-run', 'ambiguous')]
    const found = pickSwapEvent(events, 'my-run')
    expect(found?.payload.result).toBe('changed')
    expect(pickSwapEvent(events, 'no-such-run')).toBeNull()
    expect(pickSwapEvent([], 'my-run')).toBeNull()
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
  })

  it('格子小字：有快照显示「名字（形态 · 等级）」，空槽显示「不动」', () => {
    expect(presetSlotSummary(null)).toBe('不动')
    expect(presetSlotSummary(preset().slots['2'])).toBe('三日月宗近（极 · Lv.99）')
    expect(presetSlotSummary({ name_zh: '小狐丸', form_status: 'normal' })).toBe('小狐丸（普通）')
    expect(presetSlotSummary({ sword_catalog_id: '00005' })).toBe('00005（未确认）')
  })

  it('选刀池：没认出名字的候选禁选，有图鉴号兜底或缺等级的照常能选', () => {
    expect(presetCandidatePickable(entry())).toBe(true)
    expect(presetCandidatePickable(entry({ name_zh: null, sword_catalog_id: null }))).toBe(false)
    expect(presetCandidatePickable(entry({ name_zh: null }))).toBe(true)
    expect(presetCandidatePickable(entry({ level: null }))).toBe(true)
  })
})
