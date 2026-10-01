import type { DayExpeditionHelpPrefs } from '../../types'

// 狐之助与远征使用同一份时间表结果，不在前端另算资源优先级。
export function resourceSuggestion(prefs?: DayExpeditionHelpPrefs | null): string {
  return prefs?.resource_focus || prefs?.suggested_resource || ''
}
