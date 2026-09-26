import { reactive } from 'vue'
import type { ForgePointKey } from './forgePity'

// 面板会话内保留手填数字；不落盘，避免把上期积分带进下期。
export const forgePityDraft = reactive({
  currentPoints: '',
  targetPoints: '',
  talisman: 'none' as ForgePointKey,
})
