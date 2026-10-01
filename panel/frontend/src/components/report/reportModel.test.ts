import { describe, expect, it } from 'vitest'
import type { LedgerAttribution } from '../../types'
import { categoryOf, gameLedgerRecords, recordOrigin, honmaruReceipts, swordReceiptEntries } from './reportModel'

it('counts every sword in a batch including duplicate names, alongside battle drops', () => {
  const batch = { event_type: 'forge.collected', payload: { swords: Array.from({ length: 10 }, (_, i) => ({ name: '堀川国广', serial_id: i + 1 })) } }
  const entries = swordReceiptEntries([batch, { event_type: 'sword.obtained', payload: { name: '宗三左文字' } }, { event_type: 'forge.started', payload: { name: '不应计入' } }])
  expect(entries).toHaveLength(11)
  expect(entries.filter(event => event.payload.name === '堀川国广')).toHaveLength(10)
})

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

describe('honmaru receipt summary', () => {
  it('keeps spending visible even when the same activity earns more', () => {
    const items = [receipt('小判', 1000, 1), receipt('小判', -300, 2)]
    expect(honmaruReceipts(items, 'gain')[0].total).toBe(1000)
    expect(honmaruReceipts(items, 'cost')[0].total).toBe(300)
  })
  it('uses only known resources and sources and keeps resource ordering', () => {
    const items = [receipt('木炭', 5000, 1), receipt('小判', 20, 2),
      { ...receipt('小判', 10000, 3), source: 'unknown.youzu_log' }, receipt('审神者经验', 20, 4)]
    expect(honmaruReceipts(items, 'gain').map(i => [i.resource, i.total])).toEqual([['小判', 20], ['木炭', 5000]])
    expect(honmaruReceipts([], 'cost')).toEqual([])
  })
})
