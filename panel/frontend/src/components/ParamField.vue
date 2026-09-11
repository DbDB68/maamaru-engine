<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ParamField } from '../types'
import PixelControl from './PixelControl.vue'

const props = defineProps<{ field: ParamField; modelValue: unknown }>()
const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

function optionValue(option: string | [string, string]) {
  return Array.isArray(option) ? option[0] : option
}

function optionLabel(option: string | [string, string]) {
  return Array.isArray(option) ? option[1] : option
}

function updateChecks(value: string) {
  const current = Array.isArray(props.modelValue) ? [...props.modelValue] as string[] : []
  const index = current.indexOf(value)
  if (index >= 0) current.splice(index, 1)
  else current.push(value)
  emit('update:modelValue', current)
}
function setAllChecks(selected: boolean) {
  emit('update:modelValue', selected ? (props.field.options || []).map(optionValue) : [])
}

// duration-list：旧版同款交互（时分秒拾取＋可删 chips），底层存逗号分隔字符串，后端 _build_forge 直接拆
const draftHour = ref(3)
const draftMinute = ref(20)
const draftSecond = ref(0)

function parseDurations(raw: unknown): string[] {
  const text = Array.isArray(raw) ? raw.join(',') : String(raw ?? '')
  return [...new Set(text.split(/[,，、;；\s]+/).map(value => value.trim()).filter(Boolean))]
}
const durations = computed(() => parseDurations(props.modelValue))
function addDuration() {
  const parts = [draftHour.value, draftMinute.value, draftSecond.value]
  const caps = [23, 59, 59]
  const value = parts.map((part, i) =>
    String(Math.max(0, Math.min(caps[i], Math.floor(Number(part) || 0)))).padStart(2, '0'),
  ).join(':')
  if (durations.value.includes(value)) return
  emit('update:modelValue', [...durations.value, value].join(','))
}
function removeDuration(value: string) {
  emit('update:modelValue', durations.value.filter(item => item !== value).join(','))
}
</script>

<template>
  <div v-if="field.type === 'note'" class="field-note">
    <span>说明</span>
    <button type="button" class="help-trigger" aria-label="查看说明">
      ?
      <span class="help-tooltip" role="tooltip">{{ field.text }}</span>
    </button>
  </div>
  <div v-else-if="field.type === 'duration-list'" class="field">
    <span class="field-label">
      {{ field.label }}
      <button v-if="field.help" type="button" class="help-trigger" :aria-label="`${field.label}说明`">
        ?
        <span class="help-tooltip" role="tooltip">{{ field.help }}</span>
      </button>
    </span>
    <span class="duration-pick">
      <PixelControl type="number" numeric :min="0" :max="23" :model-value="draftHour" @update:model-value="draftHour = Number($event)" aria-label="时" />
      <i>:</i>
      <PixelControl type="number" numeric :min="0" :max="59" :model-value="draftMinute" @update:model-value="draftMinute = Number($event)" aria-label="分" />
      <i>:</i>
      <PixelControl type="number" numeric :min="0" :max="59" :model-value="draftSecond" @update:model-value="draftSecond = Number($event)" aria-label="秒" />
      <button type="button" class="duration-add" @click="addDuration">＋ 添加关注时长</button>
    </span>
    <span class="duration-chips">
      <button
        v-for="item in durations"
        :key="item"
        type="button"
        class="duration-chip"
        :aria-label="`删除 ${item}`"
        @click="removeDuration(item)"
      ><span>{{ item }}</span><b aria-hidden="true">×</b></button>
      <span v-if="!durations.length" class="duration-empty">没有关注时长，命中时不会特别提醒</span>
    </span>
  </div>
  <label v-else class="field">
    <span class="field-label">
      {{ field.label }}
      <button v-if="field.help" type="button" class="help-trigger" :aria-label="`${field.label}说明`">
        ?
        <span class="help-tooltip" role="tooltip">{{ field.help }}</span>
      </button>
    </span>
    <PixelControl
      v-if="field.type === 'select'"
      as="select"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
    >
      <option v-for="option in field.options" :key="optionValue(option)" :value="optionValue(option)">
        {{ optionLabel(option) }}
      </option>
    </PixelControl>
    <PixelControl
      v-else-if="field.type === 'number'"
      type="number"
      numeric
      :min="field.min"
      :max="field.max"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <button
      v-else-if="field.type === 'toggle'"
      type="button"
      class="toggle-control"
      :class="{ active: modelValue === true || modelValue === 'true' }"
      :aria-pressed="modelValue === true || modelValue === 'true'"
      @click="emit('update:modelValue', !(modelValue === true || modelValue === 'true'))"
    >
      <span aria-hidden="true"></span>
      {{ modelValue === true || modelValue === 'true' ? '开启' : '关闭' }}
    </button>
    <PixelControl
      v-else-if="field.type === 'text' && field.swords"
      as="textarea"
      :placeholder="field.placeholder"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <PixelControl
      v-else-if="field.type === 'text'"
      :placeholder="field.placeholder"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <span v-if="field.type === 'checks'" class="checks">
      <span class="checks-actions">
        <button type="button" @click="setAllChecks(true)">全选</button>
        <button type="button" @click="setAllChecks(false)">清空</button>
      </span>
      <button
        v-for="option in field.options"
        :key="optionValue(option)"
        type="button"
        :class="{ active: Array.isArray(modelValue) && modelValue.includes(optionValue(option)) }"
        @click="updateChecks(optionValue(option))"
      >{{ optionLabel(option) }}</button>
    </span>
  </label>
</template>
