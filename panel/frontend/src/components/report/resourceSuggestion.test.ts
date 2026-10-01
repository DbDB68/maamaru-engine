import { describe, expect, it } from 'vitest'
import { resourceSuggestion } from './resourceSuggestion'

describe('shared expedition resource focus', () => {
  it('uses the server priority even with ample forge inventory', () => {
    expect(resourceSuggestion({ rounds_per_team: 1, available_teams: [4], suggested_resource: '砥石' })).toBe('砥石')
  })
  it('uses the saved player choice over the automatic priority', () => {
    expect(resourceSuggestion({ rounds_per_team: 1, available_teams: [4], suggested_resource: '砥石', resource_focus: '小判' })).toBe('小判')
  })
  it('leaves unsynchronized inventory unknown', () => {
    expect(resourceSuggestion(null)).toBe('')
  })
})
