<script setup lang="ts">
// 异常与通知中心：顶栏铃铛 + 事故单抽屉。
// 每张事故单按统一格式展示——发生了什么 / 可能原因 / 现在该做什么 /
// 是否必须人工接管 / 对应任务入口 / 去重编号。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'
import type { Incident } from '../types'

const emit = defineEmits<{ (e: 'open-entry', entry: Incident['entry']): void }>()

const items = ref<Incident[]>([])
const unread = ref(0)
const open = ref(false)
const busy = ref('')
let pollTimer = 0

const active = computed(() => items.value.filter(item => item.status !== 'resolved'))
const resolved = computed(() => items.value.filter(item => item.status === 'resolved'))

async function refresh() {
  try {
    const data = await api.incidents()
    items.value = data.items
    unread.value = data.unread
  } catch { /* 面板自己还在启动，下一轮再说 */ }
}

async function ack(item: Incident) {
  busy.value = item.code
  try { await api.ackIncident(item.code); await refresh() } finally { busy.value = '' }
}

async function resolve(item: Incident) {
  busy.value = item.code
  try { await api.resolveIncident(item.code); await refresh() } finally { busy.value = '' }
}

function openEntry(item: Incident) {
  open.value = false
  if (item.status === 'active') void ack(item)
  emit('open-entry', item.entry || {})
}

function timeLabel(ts: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

const severityLabel: Record<Incident['severity'], string> = {
  urgent: '得管', warning: '留意', info: '知道就好',
}

onMounted(() => { void refresh(); pollTimer = window.setInterval(refresh, 5000) })
onBeforeUnmount(() => window.clearInterval(pollTimer))
</script>

<template>
  <div class="notice-center">
    <button
      type="button"
      class="notice-bell"
      :class="{ ringing: unread > 0 }"
      :title="unread ? `${unread} 张事故单待处理` : '通知中心'"
      :aria-label="unread ? `通知中心，${unread} 张事故单待处理` : '通知中心'"
      @click="open = !open"
    >🔔<i v-if="unread">{{ unread > 99 ? '99+' : unread }}</i></button>

    <section v-if="open" class="notice-drawer" aria-label="异常与通知中心">
      <header class="notice-head">
        <strong>通知中心</strong>
        <span v-if="active.length">{{ active.length }} 张待处理</span>
        <span v-else>本丸一切太平</span>
      </header>

      <p v-if="!items.length" class="notice-empty">还没有事故单，狐之助盯着呢。</p>

      <article
        v-for="item in active"
        :key="item.code"
        class="notice-card"
        :class="[item.severity, { acknowledged: item.status === 'acknowledged' }]"
      >
        <header>
          <span class="notice-severity">{{ severityLabel[item.severity] }}</span>
          <strong>{{ item.title }}</strong>
          <span v-if="item.needs_human" class="notice-human">需要人工接管</span>
        </header>
        <dl>
          <dt>可能原因</dt><dd>{{ item.cause }}</dd>
          <dt>现在该做什么</dt><dd>{{ item.action }}</dd>
        </dl>
        <footer>
          <span class="notice-meta">
            № {{ item.code }} · 第 {{ item.count }} 次 · {{ timeLabel(item.last_seen) }}
          </span>
          <span class="notice-actions">
            <button type="button" class="notice-go" @click="openEntry(item)">去看看</button>
            <button v-if="item.status === 'active'" type="button" :disabled="busy === item.code" @click="ack(item)">知道了</button>
            <button type="button" :disabled="busy === item.code" @click="resolve(item)">结案</button>
          </span>
        </footer>
      </article>

      <details v-if="resolved.length" class="notice-resolved">
        <summary>已结案（{{ resolved.length }}）</summary>
        <article v-for="item in resolved" :key="item.code" class="notice-card resolved">
          <header><strong>{{ item.title }}</strong></header>
          <footer><span class="notice-meta">№ {{ item.code }} · 共 {{ item.count }} 次 · {{ timeLabel(item.last_seen) }}</span></footer>
        </article>
      </details>
    </section>
  </div>
</template>

<style scoped>
.notice-center { position: relative; }

.notice-bell {
  position: relative;
  border: 1px solid var(--paper-line);
  background: var(--paper-card);
  border-radius: 999px;
  width: 34px;
  height: 34px;
  font-size: 15px;
  cursor: pointer;
  display: grid;
  place-items: center;
}
.notice-bell.ringing { border-color: var(--fox-gold); }
.notice-bell i {
  position: absolute;
  top: -6px;
  right: -8px;
  min-width: 17px;
  height: 17px;
  padding: 0 4px;
  border-radius: 999px;
  background: #b5423a;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  font-style: normal;
  display: grid;
  place-items: center;
}

.notice-drawer {
  position: absolute;
  right: 0;
  top: calc(100% + 8px);
  width: min(400px, 88vw);
  max-height: 70vh;
  overflow-y: auto;
  background: var(--paper-card);
  border: 1px solid var(--paper-line);
  border-radius: 12px;
  box-shadow: var(--shadow-pop);
  padding: 12px;
  z-index: 60;
  display: grid;
  gap: 10px;
}
.notice-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  color: var(--ink);
}
.notice-head span { font-size: 12px; color: var(--ink-dim); }
.notice-empty { margin: 4px 0; font-size: 13px; color: var(--ink-dim); }

.notice-card {
  border: 1px solid var(--paper-line);
  border-left-width: 4px;
  border-radius: var(--r-md);
  padding: 10px 12px;
  background: var(--paper);
  display: grid;
  gap: 8px;
}
.notice-card.urgent { border-left-color: #b5423a; }
.notice-card.warning { border-left-color: var(--fox-gold); }
.notice-card.info { border-left-color: var(--ink-dim); }
.notice-card.acknowledged { opacity: .75; }
.notice-card.resolved { opacity: .6; }

.notice-card header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--ink);
  font-size: 14px;
}
.notice-severity {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--paper-panel);
  color: var(--ink-dim);
}
.notice-card.urgent .notice-severity { background: #b5423a; color: #fff; }
.notice-card.warning .notice-severity { background: var(--fox-gold-pale); color: var(--fox-gold-deep); }
.notice-human {
  font-size: 11px;
  font-weight: 700;
  color: #b5423a;
}

.notice-card dl { margin: 0; display: grid; gap: 4px; }
.notice-card dt { font-size: 11px; font-weight: 700; color: var(--ink-dim); }
.notice-card dd { margin: 0; font-size: 13px; color: var(--ink); line-height: 1.5; }

.notice-card footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.notice-meta { font-size: 11px; color: var(--ink-dim); }
.notice-actions { display: flex; gap: 6px; }
.notice-actions button {
  border: 1px solid var(--paper-line);
  background: var(--paper-card);
  color: var(--ink);
  border-radius: 999px;
  padding: 3px 12px;
  font-size: 12px;
  cursor: pointer;
}
.notice-actions button:disabled { opacity: .5; cursor: default; }
.notice-actions .notice-go {
  background: var(--fox-gold);
  border-color: var(--fox-gold);
  color: #fff;
  font-weight: 700;
}

.notice-resolved summary {
  font-size: 12px;
  color: var(--ink-dim);
  cursor: pointer;
}
.notice-resolved[open] { display: grid; gap: 8px; }
.notice-resolved[open] summary { margin-bottom: 2px; }
</style>
