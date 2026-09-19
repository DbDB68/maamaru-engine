/**
 * 把活动剩余圈数摊到离收摊的连续天数里。
 * 向上取整，避免每天抹掉小数后在最后差几圈；不足一天时最多报全部剩余圈数。
 */
export function dailyRunTarget(runsNeeded: number | null | undefined, secondsToEnd: number | null | undefined): number | null {
  if (!Number.isFinite(runsNeeded) || Number(runsNeeded) <= 0) return null
  if (!Number.isFinite(secondsToEnd) || Number(secondsToEnd) <= 0) return null
  const runs = Math.ceil(Number(runsNeeded))
  const daysLeft = Number(secondsToEnd) / 86400
  return Math.min(runs, Math.max(1, Math.ceil(runs / daysLeft)))
}

export interface ImmediateBatchPlan {
  runs: number
  finishAtMs: number
  horizonAtMs: number
  horizon: 'daily-reset' | 'event-end'
  reserveSeconds: number
}

const SHANGHAI_OFFSET_MS = 8 * 3600 * 1000

/** 国服以北京时间凌晨 4 点换日；返回当前时刻之后的下一次换日。 */
export function nextCnDailyReset(nowMs: number): number {
  const shanghai = new Date(nowMs + SHANGHAI_OFFSET_MS)
  const year = shanghai.getUTCFullYear()
  const month = shanghai.getUTCMonth()
  const day = shanghai.getUTCDate()
  const hour = shanghai.getUTCHours()
  const resetDay = day + (hour >= 4 ? 1 : 0)
  return Date.UTC(year, month, resetDay, 4) - SHANGHAI_OFFSET_MS
}

/**
 * 给“现在这一锅”算一个能直接填进任务的保守圈数。
 * 不超过今日平均目标、活动剩余圈数和任务表单上限，并给 4 点换日或收摊留出收尾时间。
 */
export function immediateBatchPlan(
  runsNeeded: number | null | undefined,
  secondsPerLoop: number | null | undefined,
  secondsToEnd: number | null | undefined,
  nowMs: number,
  reserveSeconds = 300,
  maxRuns = 99,
): ImmediateBatchPlan | null {
  const dailyRuns = dailyRunTarget(runsNeeded, secondsToEnd)
  if (dailyRuns == null || !Number.isFinite(secondsPerLoop) || Number(secondsPerLoop) <= 0) return null
  if (!Number.isFinite(nowMs) || !Number.isFinite(secondsToEnd) || Number(secondsToEnd) <= 0) return null

  const resetAtMs = nextCnDailyReset(nowMs)
  const eventEndAtMs = nowMs + Number(secondsToEnd) * 1000
  const horizon = eventEndAtMs < resetAtMs ? 'event-end' : 'daily-reset'
  const horizonAtMs = Math.min(resetAtMs, eventEndAtMs)
  const usableSeconds = Math.max(0, Math.floor((horizonAtMs - nowMs) / 1000) - reserveSeconds)
  const capacity = Math.max(0, Math.floor(usableSeconds / Number(secondsPerLoop)))
  const runs = Math.min(Math.ceil(Number(runsNeeded)), dailyRuns, maxRuns, capacity)
  return {
    runs,
    finishAtMs: nowMs + runs * Number(secondsPerLoop) * 1000,
    horizonAtMs,
    horizon,
    reserveSeconds,
  }
}
