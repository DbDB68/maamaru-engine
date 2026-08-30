<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { signed } from './reportModel'

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

interface OverviewPart { key: string; label: string; color: string; value: number }
interface OverviewRow { resource: string; total: number | null; parts: OverviewPart[] }

const props = defineProps<{ rows: OverviewRow[]; loading?: boolean }>()
const box = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function cssVar(name: string, fallback: string) {
  return getComputedStyle(box.value || document.documentElement).getPropertyValue(name).trim() || fallback
}

function buildOption(): any {
  const ink = cssVar('--ink', '#3d3229')
  const inkDim = cssVar('--ink-dim', '#8a7f72')
  const line = cssVar('--paper-line', '#ddd6cb')
  const card = cssVar('--paper-card', '#faf6ef')
  const compact = (box.value?.clientWidth || 999) < 520
  const categories = new Map<string, { label: string; color: string }>()
  for (const row of props.rows) for (const part of row.parts) categories.set(part.key, part)
  const scales = props.rows.map(row => Math.max(1, row.parts.reduce((sum, part) => sum + Math.abs(part.value), 0)))
  const series: any[] = [...categories.entries()].map(([key, category]) => ({
    id: key,
    name: category.label,
    type: 'bar',
    stack: 'resource',
    barWidth: compact ? 18 : 22,
    itemStyle: { color: category.color, borderRadius: 2 },
    emphasis: { focus: 'series' },
    data: props.rows.map((row, index) => {
      const actual = row.parts.find(part => part.key === key)?.value || 0
      return { value: actual / scales[index] * 100, actual, resource: row.resource }
    }),
  }))
  series.push({
    id: 'total-label', name: '', type: 'bar', silent: true, barWidth: compact ? 18 : 22,
    barGap: '-100%', itemStyle: { color: 'transparent' }, tooltip: { show: false }, z: 10,
    data: props.rows.map(row => ({
      value: row.total == null ? 0 : row.total < 0 ? -104 : 104,
      total: row.total,
      label: {
        show: true, position: row.total != null && row.total < 0 ? 'insideBottom' : 'top',
        color: row.total == null ? inkDim : row.total < 0 ? cssVar('--danger', '#b0492e') : row.total > 0 ? '#47734f' : ink,
        fontSize: compact ? 10 : 13, fontWeight: 700, rotate: compact ? 38 : 0,
        formatter: signed(row.total),
      },
    })),
  })
  return {
    animationDuration: 650,
    animationEasing: 'cubicOut',
    grid: { left: compact ? 24 : 42, right: compact ? 12 : 20, top: compact ? 58 : 44, bottom: compact ? 64 : 40, containLabel: false },
    legend: { top: 0, icon: 'roundRect', itemWidth: 11, itemHeight: 11, textStyle: { color: inkDim, fontSize: 11 } },
    tooltip: {
      trigger: 'item', backgroundColor: card, borderColor: line,
      textStyle: { color: ink, fontSize: 13 },
      formatter(params: any) {
        const data = params?.data || {}
        if (!data.actual) return `${data.resource || ''}：这项来源没有变化`
        return `<b>${data.resource}</b><br>${params.marker}${params.seriesName}　<b>${signed(Number(data.actual))}</b>`
      },
    },
    xAxis: {
      type: 'category', data: props.rows.map(row => row.resource),
      axisLine: { show: true, lineStyle: { color: line } }, axisTick: { show: false },
      axisLabel: { color: ink, fontSize: compact ? 10 : 12, fontWeight: 600, interval: 0, rotate: compact ? 38 : 0 },
    },
    yAxis: {
      type: 'value', min: -112, max: 112,
      axisLabel: { show: false }, axisTick: { show: false }, axisLine: { show: false },
      splitLine: { show: false },
    },
    series,
  }
}

function render() {
  if (!chart && box.value) chart = echarts.init(box.value)
  if (chart) chart.setOption(buildOption(), true)
}

onMounted(() => {
  render()
  if (box.value) {
    observer = new ResizeObserver(() => { chart?.resize(); render() })
    observer.observe(box.value)
  }
})
watch(() => [props.rows, props.loading], render, { deep: true })
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose(); chart = null })
</script>

<template>
  <div class="overview-chart" :class="{ loading }">
    <div ref="box" class="overview-chart-box" role="img" aria-label="24小时八种资源收支统计图"></div>
    <p v-if="loading" class="overview-chart-hint">狐之助正在整理这 24 小时的收支……</p>
  </div>
</template>

<style scoped>
.overview-chart { position: relative; }
.overview-chart-box { width: 100%; height: 360px; }
.overview-chart-hint { position: absolute; inset: 0; display: grid; place-items: center; margin: 0; color: var(--ink-dim); background: color-mix(in srgb, var(--paper-card) 70%, transparent); }
@media (max-width: 520px) { .overview-chart-box { height: 390px; } }
</style>
