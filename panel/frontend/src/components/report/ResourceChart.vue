<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { dayLabel, signed } from './reportModel'
import type { ChartSeries } from './reportModel'

echarts.use([BarChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = withDefaults(defineProps<{
  dates: string[]
  series: ChartSeries[]
  stacked?: boolean
  selectedDate?: string
  loading?: boolean
}>(), { stacked: true, selectedDate: '', loading: false })

const emit = defineEmits<{ select: [payload: { date: string; key: string }] }>()

const box = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

function cssVar(name: string, fallback: string) {
  return getComputedStyle(box.value || document.documentElement).getPropertyValue(name).trim() || fallback
}

function buildOption() {
  const ink = cssVar('--ink', '#3d3229')
  const inkDim = cssVar('--ink-dim', '#8a7f72')
  const line = cssVar('--paper-line', '#ddd6cb')
  const card = cssVar('--paper-card', '#faf6ef')
  const selected = props.selectedDate
  return {
    grid: { left: 12, right: 12, top: 30, bottom: 8, containLabel: true },
    legend: { top: 0, icon: 'roundRect', itemWidth: 12, itemHeight: 12, textStyle: { color: inkDim, fontSize: 12 } },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: card,
      borderColor: line,
      textStyle: { color: ink, fontSize: 13 },
      formatter(params: any) {
        const items = (Array.isArray(params) ? params : [params]).filter((item: any) => item.value != null && item.value !== 0)
        if (!items.length) return `${dayLabel(props.dates[items[0]?.dataIndex ?? 0] || '')}：这天没有读数变化`
        const total = items.reduce((sum: number, item: any) => sum + Number(item.value || 0), 0)
        const rows = items.map((item: any) =>
          `<div style="display:flex;justify-content:space-between;gap:16px"><span>${item.marker}${item.seriesName}</span><b>${signed(Number(item.value))}</b></div>`,
        ).join('')
        return `<div style="min-width:180px"><div style="margin-bottom:4px"><b>${dayLabel(props.dates[items[0].dataIndex] || '')}</b> 合计 <b>${signed(total)}</b></div>${rows}</div>`
      },
    },
    xAxis: {
      type: 'category',
      data: props.dates.map(dayLabel),
      axisLine: { lineStyle: { color: line } },
      axisTick: { show: false },
      axisLabel: { color: inkDim, fontSize: 12 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: line, type: 'dashed' } },
      axisLabel: { color: inkDim, fontSize: 12, formatter: (value: number) => Math.abs(value) >= 10000 ? `${value / 10000}万` : String(value) },
    },
    series: props.series.map(item => ({
      id: item.key,
      name: item.name,
      type: 'bar',
      stack: props.stacked ? 'total' : undefined,
      barMaxWidth: 42,
      itemStyle: { color: item.color, borderRadius: props.stacked ? 0 : [3, 3, 0, 0] },
      emphasis: { focus: 'series' },
      data: item.values.map((value, index) => ({
        value,
        itemStyle: selected && props.dates[index] === selected
          ? { borderColor: ink, borderWidth: 1.5 }
          : undefined,
      })),
    })),
  }
}

function render() {
  if (!chart && box.value) {
    chart = echarts.init(box.value)
    chart.on('click', (params: any) => {
      const date = props.dates[params.dataIndex]
      if (date) emit('select', { date, key: String(params.seriesId || params.seriesName || '') })
    })
  }
  if (chart) chart.setOption(buildOption(), true)
}

onMounted(() => {
  render()
  if (box.value) {
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(box.value)
  }
})

watch(() => [props.dates, props.series, props.stacked, props.selectedDate], render, { deep: true })

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="resource-echart" :class="{ loading }">
    <div ref="box" class="resource-echart-box" role="img" aria-label="资源收支柱状图"></div>
    <p v-if="loading" class="resource-echart-hint">狐之助正在整理这段时间的收支……</p>
    <p v-else-if="!dates.length" class="resource-echart-hint">同一时间段至少需要两次库存读数，狐之助再攒一会儿账。</p>
  </div>
</template>

<style scoped>
.resource-echart { position: relative; }
.resource-echart-box { width: 100%; height: 320px; }
.resource-echart-hint { position: absolute; inset: 0; display: grid; place-items: center; color: var(--ink-dim); background: color-mix(in srgb, var(--paper-card) 70%, transparent); margin: 0; }
</style>
