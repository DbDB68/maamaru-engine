import { describe, expect, it } from 'vitest'
import type { PlanningReport } from '../../types'
import { resourceSuggestion } from './resourceSuggestion'

const planning = (watch: PlanningReport['resource_watch'], goals: PlanningReport['goals'] = []) => ({
  resource_watch: watch,
  goals,
}) as PlanningReport

describe('default resource suggestion', () => {
  it('uses the confirmed forge blocker only when no normal forge is possible', () => {
    expect(resourceSuggestion(planning({ resources: [], forge_capacity: 0, limiting: ['委托符'] }))?.resource).toBe('委托符')
  })

  it('does not call a merely smaller forge capacity a shortage', () => {
    expect(resourceSuggestion(planning({ resources: [], forge_capacity: 500, limiting: ['砥石'] }))?.resource).toBe('小判')
  })

  it('keeps unknown forge inventory unknown and still allows koban as a default', () => {
    const suggestion = resourceSuggestion(planning({ resources: [], forge_capacity: null, limiting: [] }))
    expect(suggestion?.resource).toBe('小判')
    expect(suggestion?.reason).toContain('还没读齐')
  })

  it('defers to an existing player resource goal', () => {
    const goals = [{ kind: 'resource', status: 'active', resource: '玉钢' }] as PlanningReport['goals']
    expect(resourceSuggestion(planning({ resources: [], forge_capacity: 0, limiting: ['委托符'] }, goals))).toBeNull()
  })
})
