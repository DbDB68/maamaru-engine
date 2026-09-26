import { describe, expect, it } from 'vitest'
import { forgePityEstimate } from './forgePity'

const rows = [
  { resource: '木炭', current: 70000, per_forge: 7000, forge_capacity: 10 },
  { resource: '玉钢', current: 70000, per_forge: 7000, forge_capacity: 10 },
  { resource: '冷却材', current: 70000, per_forge: 7000, forge_capacity: 10 },
  { resource: '砥石', current: 70000, per_forge: 7000, forge_capacity: 10 },
  { resource: '委托符', current: 90, per_forge: 9, forge_capacity: 10 },
  { resource: '加速符', current: 80, per_forge: 10, forge_capacity: 8 },
]

describe('limited forge manifestation points', () => {
  it('rounds the remaining points up to a whole ten-forge batch', () => {
    const result = forgePityEstimate(4510, 5000, 'none', rows)!
    expect(result.batches).toBe(10)
    expect(result.resultingPoints).toBe(5010)
    expect(result.costs.find(row => row.resource === '加速符')?.shortfall).toBe(20)
    expect(result.trackedCostsCovered).toBe(false)
  })

  it('uses the selected talisman point rate and accounts for ten per batch', () => {
    const result = forgePityEstimate(4300, 5000, 'fuji', rows)!
    expect(result.batches).toBe(2)
    expect(result.talismans).toBe(20)
    expect(result.costs.find(row => row.resource === '委托符')?.required).toBe(18)
  })

  it('preserves unknown inventory and does not claim the budget is covered', () => {
    const result = forgePityEstimate(4950, 5000, 'none', [
      ...rows.slice(0, 5), { ...rows[5], current: null, forge_capacity: null },
    ])!
    expect(result.costs[5].shortfall).toBeNull()
    expect(result.trackedCostsCovered).toBe(false)
  })

  it('needs no more batches after the threshold and rejects invalid inputs', () => {
    expect(forgePityEstimate(5000, 5000, 'none', rows)?.batches).toBe(0)
    expect(forgePityEstimate(-1, 5000, 'none', rows)).toBeNull()
    expect(forgePityEstimate(0, 0, 'none', rows)).toBeNull()
  })
})
