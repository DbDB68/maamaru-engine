import type { PlanningReport } from '../../types'

export const FORGE_POINT_OPTIONS = [
  { key: 'none', label: '不用御札', perForge: 5 },
  { key: 'plum', label: '御札·梅', perForge: 10 },
  { key: 'bamboo', label: '御札·竹', perForge: 15 },
  { key: 'pine', label: '御札·松', perForge: 20 },
  { key: 'fuji', label: '御札·富士', perForge: 35 },
] as const

export type ForgePointKey = typeof FORGE_POINT_OPTIONS[number]['key']
type ForgeRows = NonNullable<NonNullable<PlanningReport['resource_watch']>['ten_forge']>['resources']

export function forgePityEstimate(
  currentPoints: number,
  targetPoints: number,
  pointKey: ForgePointKey,
  rows: ForgeRows,
) {
  if (!Number.isSafeInteger(currentPoints) || currentPoints < 0
      || !Number.isSafeInteger(targetPoints) || targetPoints <= 0 || targetPoints > 1_000_000) return null
  const option = FORGE_POINT_OPTIONS.find(item => item.key === pointKey)
  if (!option || rows.length !== 6 || rows.some(row => !Number.isFinite(row.per_forge) || row.per_forge <= 0)) return null

  const remainingPoints = Math.max(0, targetPoints - currentPoints)
  const pointsPerTen = option.perForge * 10
  const batches = Math.ceil(remainingPoints / pointsPerTen)
  const costs = rows.map(row => ({
    resource: row.resource,
    required: row.per_forge * batches,
    current: row.current,
    shortfall: row.current == null ? null : Math.max(0, row.per_forge * batches - row.current),
  }))
  return {
    remainingPoints,
    pointsPerTen,
    batches,
    swords: batches * 10,
    resultingPoints: currentPoints + batches * pointsPerTen,
    talismans: pointKey === 'none' ? 0 : batches * 10,
    costs,
    trackedCostsCovered: costs.every(row => row.shortfall === 0),
  }
}
