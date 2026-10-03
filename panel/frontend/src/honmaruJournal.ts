import { shanghaiDate, signed } from './components/report/reportModel'

export interface JournalPost {
  key: string; ts: number; title: string; text: string; label: string
  scene: string; icon: string; facts: string[]
}

// 同类、同一来源的一小批操作合成一张小报；保留真实时间，不随机改写旧动态。
export function buildJournalPosts(events: any[], departures: any[] = []): JournalPost[] {
  const batches = new Map<string, Array<{ ts: number; key: string; payload: any }>>()
  const seen = new Set<string>()
  for (const event of events) {
    const p = event.payload || {}
    const kind = event.event_type === 'forge.collected' ? 'forge'
      : event.event_type === 'sword.obtained' ? 'drop'
      : event.event_type === 'sword.inbox_received' ? 'inbox'
      : event.event_type === 'expedition.settled' ? 'expedition' : ''
    if (!kind || !Number.isFinite(Number(event.ts))) continue
    const key = String(p.receipt_key || `event-${event.id}`)
    if (seen.has(key)) continue
    seen.add(key)
    const source = kind === 'drop' ? `${p.source || ''}:${p.chapter || ''}:${p.map_no || ''}`
      : kind === 'expedition' ? String(p.team_no || '') : ''
    const group = `${kind}|${source}|${shanghaiDate(Number(event.ts))}`
    const list = batches.get(group) || []
    list.push({ ts: Number(event.ts), key, payload: p })
    batches.set(group, list)
  }
  for (const item of departures) {
    if (!Number.isFinite(Number(item.ts)) || !['链结', '习合', '刀解'].includes(item.reason)) continue
    const key = `departure-${item.serial_id}`
    if (seen.has(key)) continue
    seen.add(key)
    const group = `tidy||${shanghaiDate(Number(item.ts))}`
    const list = batches.get(group) || []
    list.push({ ts: Number(item.ts), key, payload: item })
    batches.set(group, list)
  }
  const posts: JournalPost[] = []
  for (const [group, rows] of batches) {
    const kind = group.split('|')[0]!
    rows.sort((a, b) => a.ts - b.ts || a.key.localeCompare(b.key))
    const chunks: typeof rows[] = []
    for (const row of rows) {
      const chunk = chunks[chunks.length - 1]
      if (chunk && row.ts - chunk[0]!.ts <= 300) chunk.push(row)
      else chunks.push([row])
    }
    for (const chunk of chunks) {
      const first = chunk[0]!, last = chunk[chunk.length - 1]!
      const swords = chunk.flatMap(row => Array.isArray(row.payload.swords) ? row.payload.swords : [row.payload])
      const names = new Map<string, number>()
      for (const sword of swords) if (sword.name) names.set(sword.name, (names.get(sword.name) || 0) + 1)
      const nameFacts = [...names].map(([name, count]) => `${name}${count > 1 ? ` ×${count}` : ''}`)
      let title = '', text = '', label = '', icon = '', scene = 'honmaru_garden_stage.png', facts = nameFacts
      if (kind === 'forge') {
        title = '炉火歇了，新刀来了'; label = '锻刀手记'; icon = 'forge.png'; scene = 'honmaru_forge_stage.png'
        text = `收下了 ${swords.length} 振锻好的刀。今天的炉边又热闹了一些。`
      } else if (kind === 'drop') {
        title = '归途中，迎来了新伙伴'; label = '出阵见闻'; icon = 'sortie.png'; scene = 'honmaru_sortie_stage.png'
        const route = first.payload.chapter && first.payload.map_no ? `${first.payload.chapter}-${first.payload.map_no}`
          : first.payload.source === 'raid.drop' ? '联队战' : '战斗'
        text = `在 ${route} 带回了 ${swords.length} 振刀，名字记在这里。`
      } else if (kind === 'inbox') {
        title = '收件箱里的刀，接回来了'; label = '本丸来信'; icon = 'sword.svg'
        text = `从收件箱接回 ${swords.length} 振刀。`
        facts = [...new Set(chunk.map(row => row.payload.origin_label).filter(Boolean)), ...nameFacts]
      } else if (kind === 'tidy') {
        title = '今天整理了一下刀剑'; label = '刀剑手记'; icon = 'sword.svg'
        facts = ['链结', '习合', '刀解'].map(reason => {
          const count = chunk.filter(row => row.payload.reason === reason).length
          return count ? `${reason} ${count} 振` : ''
        }).filter(Boolean)
        text = '整理妥当，留下一页小记。'
      } else {
        title = first.payload.team_no ? `第 ${first.payload.team_no} 部队回来了` : '远征的部队回来了'
        label = '远征来信'; icon = 'expedition.png'
        text = '一路辛苦，带回来的收获收好了。'
        const rewards = new Map<string, number>()
        for (const row of chunk) for (const [name, amount] of Object.entries(row.payload.rewards || {})) {
          if (typeof amount === 'number' && Number.isFinite(amount)) rewards.set(name, (rewards.get(name) || 0) + amount)
        }
        facts = [...rewards].map(([name, value]) => `${name} ${signed(value)}`)
      }
      posts.push({ key: `journal-${kind}-${first.key}`, ts: last.ts, title, text, label, icon, scene, facts })
    }
  }
  return posts.sort((a, b) => b.ts - a.ts)
}
