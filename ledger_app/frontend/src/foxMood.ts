import { ref } from 'vue'

// 账房狐之助的舞台动作：idle 站着迎宾，read 摊开卷轴看账。
// 这是纯表现层状态，由成绩单的数据加载/记账反馈驱动，不参与任何业务逻辑。
export const foxMood = ref<'idle' | 'read'>('idle')

let settleTimer: ReturnType<typeof setTimeout> | undefined

export function foxReads(milliseconds = 2600) {
  foxMood.value = 'read'
  clearTimeout(settleTimer)
  settleTimer = setTimeout(() => { foxMood.value = 'idle' }, milliseconds)
}
