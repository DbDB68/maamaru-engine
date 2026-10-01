import { describe, expect, it } from 'vitest'
import type { LedgerAttribution } from '../../types'
import { categoryOf, gameLedgerRecords, recordOrigin } from './reportModel'

const receipt = (resource: string, delta: number, eventId: number): LedgerAttribution => ({
  id: `a${eventId}`, event_id: eventId, ts: 1790733600, resource, delta,
  source: 'expedition.youzu_log.conquest/complete', script: 'youzu_log',
  label: `远征完成·一队·A1 鸟羽之战 ${resource} ${delta > 0 ? '+' : ''}${delta}`,
})

describe('game receipts and caretaker execution', () => {
  it('puts translated game sources into the matching ledger category', () => {
    expect(categoryOf(receipt('木炭', 15, 1).source)).toBe('expedition')
    expect(categoryOf('artifact.youzu_log.artifact/buybindingagent')).toBe('artifact')
  })
  it('groups resources from one receipt and keeps map detail without duplicate events', () => {
    const a = receipt('木炭', 15, 1), b = receipt('玉钢', 20, 2)
    const groups = gameLedgerRecords([a, b, a])
    expect(groups).toHaveLength(1)
    expect(groups[0].payload.label).toBe('远征完成·一队·A1 鸟羽之战')
    expect(groups[0].payload.resources).toEqual({ 木炭: 15, 玉钢: 20 })
  })
  it('labels game evidence separately from a linked execution', () => {
    const a = receipt('木炭', 15, 1)
    expect(recordOrigin(a)).toBe('游戏记录')
    expect(recordOrigin({ ...a, run_id: 'run-a', execution_script: 'expedition' })).toBe('游戏记录 · まあ丸执行远征')
    expect(gameLedgerRecords([{ ...a, script: 'expedition' }])).toEqual([])
  })
})
