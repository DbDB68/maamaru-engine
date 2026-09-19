import { describe, expect, it } from 'vitest'
import { dailyRunTarget, immediateBatchPlan, nextCnDailyReset } from './eventTimelineModel'

describe('活动每日挂机圈数', () => {
  it('按剩余连续天数向上取整，给出可以直接开工的圈数', () => {
    expect(dailyRunTarget(338, 104 * 3600 + 52 * 60)).toBe(78)
  })

  it('不足一天时不会报出比全部剩余圈数更多的任务', () => {
    expect(dailyRunTarget(12, 6 * 3600)).toBe(12)
  })

  it('没有有效圈数或截止时间时保持未知', () => {
    expect(dailyRunTarget(null, 86400)).toBeNull()
    expect(dailyRunTarget(10, 0)).toBeNull()
  })
})

describe('活动现在这一锅', () => {
  it('北京时间凌晨四点换日', () => {
    expect(nextCnDailyReset(Date.parse('2026-09-20T02:34:00+08:00')))
      .toBe(Date.parse('2026-09-20T04:00:00+08:00'))
    expect(nextCnDailyReset(Date.parse('2026-09-20T12:00:00+08:00')))
      .toBe(Date.parse('2026-09-21T04:00:00+08:00'))
  })

  it('临近换日前按实测圈速留五分钟收尾，给出可直接开工的圈数', () => {
    const now = Date.parse('2026-09-20T02:34:00+08:00')
    const plan = immediateBatchPlan(338, 5 * 60 + 40, 98 * 3600, now)
    expect(plan).toMatchObject({ runs: 14, horizon: 'daily-reset', reserveSeconds: 300 })
    expect(plan?.finishAtMs).toBe(Date.parse('2026-09-20T03:53:20+08:00'))
  })

  it('白天有充足时间时只安排当天平均目标，不把全部欠账塞进一锅', () => {
    const now = Date.parse('2026-09-20T12:00:00+08:00')
    expect(immediateBatchPlan(338, 5 * 60 + 40, 98 * 3600, now)?.runs).toBe(83)
  })

  it('收摊早于换日时以收摊为界，来不及一圈就劝先别开', () => {
    const now = Date.parse('2026-09-20T03:50:00+08:00')
    const plan = immediateBatchPlan(20, 6 * 60, 9 * 60, now)
    expect(plan).toMatchObject({ runs: 0, horizon: 'event-end' })
  })
})
