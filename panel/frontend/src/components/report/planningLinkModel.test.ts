import { describe, expect, it } from 'vitest'
import type { DayTimeline } from '../../types'
import { canAdoptRaidRecommendation, raidDayRecommendation } from './planningLinkModel'

function day(overrides: Partial<DayTimeline> = {}): DayTimeline {
  return {
    now: 1000, day_start: 0, markers: [], expeditions: [], expedition_schedule_enabled: true,
    expedition_help: { rounds_per_team: 1, available_teams: [1, 4, 5] },
    expedition_suggestions: [], expedition_advice_note: null,
    runs: [], hint: null, suggestions: null, shortfall_seconds: null, booking: null,
    conductor: { enabled: false, available: false, workflow_id: '', workflow_name: '', blocks: [], issues: [], options: [] },
    activity: {
      name: '联队战', target_runs: 20, planned_runs: 0, completed_today: 0,
      seconds_per_loop: 600, remaining_runs: 100, event_end_at: 2000, occupied: [],
    },
    ...overrides,
  }
}

describe('联队战时间表入口', () => {
  it('缺少联队战快照时不编圈数，并优先说明时间表已知原因', () => {
    expect(raidDayRecommendation(day({ activity: null, hint: '执务台正在运行，暂时无法刷新时间表' }), true)).toEqual({
      available: false, runs: 0, targetRuns: 0, reason: '执务台正在运行，暂时无法刷新时间表',
    })
    expect(raidDayRecommendation(null, true)?.available).toBe(false)
    expect(raidDayRecommendation(day(), false)).toBeNull()
  })

  it('直接合计时间表建议块，并保留今日目标与可排圈数的差额', () => {
    const result = raidDayRecommendation(day({
      suggestions: [
        { start_min: 500, duration_min: 60, runs: 6, note: '' },
        { start_min: 700, duration_min: 80, runs: 8, note: '' },
      ],
    }), true)
    expect(result).toEqual({ available: true, runs: 14, targetRuns: 20, reason: '' })
  })

  it('没有可排建议或已有安排时拒绝跨卡采纳', () => {
    expect(raidDayRecommendation(day({ suggestions: [] }), true)?.available).toBe(false)
    expect(canAdoptRaidRecommendation(true, true, false)).toBe(false)
    expect(canAdoptRaidRecommendation(true, false, true)).toBe(false)
    expect(canAdoptRaidRecommendation(true, false, false)).toBe(true)
  })
})
