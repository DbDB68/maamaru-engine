import type { PlanningReport } from '../../types'

export type ResourceSuggestion = {
  resource: string
  reason: string
  forgeShortfalls: string[]
}

export function resourceSuggestion(planning: PlanningReport): ResourceSuggestion | null {
  const hasPlayerGoal = planning.goals.some(goal =>
    (goal.kind || 'resource') === 'resource'
    && !['done', 'expired'].includes(goal.status))
  if (hasPlayerGoal) return null

  const watch = planning.resource_watch
  if (watch?.forge_capacity === 0 && watch.limiting.length) {
    return {
      resource: watch.limiting[0],
      reason: `按普通锻刀的配比，${watch.limiting.join('、')}已经锻不了下一炉。先补这块短板。`,
      forgeShortfalls: watch.limiting,
    }
  }
  return {
    resource: '小判',
    reason: watch?.forge_capacity == null
      ? '锻刀资源还没读齐；小判可以先继续攒，等盘点完整再看锻刀短板。'
      : '目前没有已确认的锻刀缺口；小判有余力就继续攒，不设“够了”的线。',
    forgeShortfalls: [],
  }
}
