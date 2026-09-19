import { describe, expect, it } from 'vitest'
import { dailyRunTarget } from './eventTimelineModel'

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
