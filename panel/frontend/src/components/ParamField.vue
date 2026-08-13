<script setup lang="ts">
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
</script>

<template>
  <div v-if="field.type === 'note'" class="field-note">
    <span>说明</span>
    <button type="button" class="help-trigger" aria-label="查看说明">
      ?
      <span class="help-tooltip" role="tooltip">{{ field.text }}</span>
    </button>
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
