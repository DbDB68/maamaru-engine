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
