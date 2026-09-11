import type { VisibilityRule } from './types'

/*
 * 参数字段显隐规则：is/not 单值比较，is_any 多值之一，
 * all/any 组合子规则（与/或）。三个表单组件共用这一份，别各写各的。
 */
export function matchesRule(rule: VisibilityRule | undefined, get: (key: string) => unknown): boolean {
  if (!rule) return true
  if (rule.all) return rule.all.every(r => matchesRule(r, get))
  if (rule.any) return rule.any.some(r => matchesRule(r, get))
  const current = String(get(rule.key ?? '') ?? '')
  if (rule.is_any) return rule.is_any.some(v => current === String(v))
  if (rule.is !== undefined) return current === String(rule.is)
  if (rule.not !== undefined) return current !== String(rule.not)
  return true
}
