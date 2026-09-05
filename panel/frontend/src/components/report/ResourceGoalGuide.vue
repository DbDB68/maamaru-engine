<script setup lang="ts">
import type { AcquisitionGuide } from '../../types'

const props = defineProps<{ guide: AcquisitionGuide }>()

function fmtDuration(minutes: number) {
  if (minutes < 60) return `${minutes}分钟`
  const hours = minutes / 60
  return `${Number.isInteger(hours) ? hours : hours.toFixed(1)}小时`
}

function fmtPerHour(value: number) {
  return value >= 10 ? String(Math.round(value)) : String(Math.round(value * 10) / 10)
}
</script>

<template>
  <section class="resource-guide">
    <header>
      <span><small>怎么更接近目标</small><h4>{{ props.guide.resource }}，去哪弄</h4></span>
    </header>

    <div class="strategy-list">
      <article v-if="props.guide.expeditions.length" class="strategy-card primary-strategy">
        <span class="strategy-mark">稳</span>
        <div>
          <small>每天都能做 · 远征挑时薪高的图</small>
          <h5>远征排这几张图</h5>
          <ul class="expedition-list">
            <li v-for="entry in props.guide.expeditions" :key="entry.map">
              <b>{{ entry.label }}</b><template v-if="entry.name">「{{ entry.name }}」</template>：{{ fmtDuration(entry.duration_min) }} 收
              {{ entry.amount }}，约 {{ fmtPerHour(entry.per_hour) }}／小时<template v-if="entry.level_req">（要 {{ entry.level_req }} 级）</template>
            </li>
          </ul>
          <p v-if="props.guide.expedition_caveat" class="strategy-impact">{{ props.guide.expedition_caveat }}</p>
        </div>
      </article>

      <article v-if="props.guide.mission" class="strategy-card">
        <span class="strategy-mark">稳</span>
        <div>
          <small>每天都能做 · 任务奖励</small>
          <h5>日课周课别漏领</h5>
          <p>{{ props.guide.mission }}</p>
        </div>
      </article>

      <article v-if="props.guide.event" class="strategy-card">
        <span class="strategy-mark">等</span>
        <div>
          <small>活动开放时</small>
          <h5>等活动再给</h5>
          <p>{{ props.guide.event }}</p>
        </div>
      </article>

      <article v-if="props.guide.note" class="strategy-card">
        <span class="strategy-mark">!</span>
        <div>
          <small>先把丑话说前头</small>
          <p>{{ props.guide.note }}</p>
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.resource-guide { margin-top: 16px; padding-top: 16px; border-top: 1px dashed var(--paper-line); }
.resource-guide > header { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; }
.resource-guide > header span { display: grid; gap: 2px; }
.resource-guide > header small { color: var(--ink-dim); font-size: 11px; }
.resource-guide > header h4 { margin: 0; font-size: 17px; }
.strategy-list { display: grid; gap: 8px; margin-top: 12px; }
.strategy-card { display: grid; grid-template-columns: 32px minmax(0, 1fr); align-items: center; gap: 11px; padding: 12px; background: color-mix(in srgb, var(--paper-card) 82%, var(--paper-panel)); border: 1px solid var(--paper-line); border-radius: 10px; }
.strategy-card.primary-strategy { background: color-mix(in srgb, #e9efdf 58%, var(--paper-card)); border-color: color-mix(in srgb, #7f9d68 50%, var(--paper-line)); }
.strategy-mark { display: grid; width: 30px; height: 30px; place-items: center; color: var(--fox-gold-deep); background: var(--fox-gold-pale); border-radius: 50%; font-size: 12px; font-weight: 700; }
.strategy-card > div { min-width: 0; }
.strategy-card small { color: var(--ink-dim); font-size: 10px; }
.strategy-card h5 { margin: 2px 0 3px; font-size: 14px; }
.strategy-card p { margin: 0; color: var(--ink-dim); font-size: 11px; line-height: 1.55; }
.expedition-list { margin: 2px 0 0; padding-left: 16px; color: var(--ink-dim); font-size: 11px; line-height: 1.65; }
.expedition-list b { color: var(--ink); }
.strategy-card .strategy-impact { margin-top: 3px; color: var(--ink); }
@media (max-width: 700px) {
  .strategy-card { grid-template-columns: 32px minmax(0, 1fr); }
}
</style>
