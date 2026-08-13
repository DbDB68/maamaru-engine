<script setup lang="ts">
import { computed } from 'vue'
import ParamField from './ParamField.vue'
import PaperCard from './PaperCard.vue'
import type { ParamField as Field, ScriptInfo, ScriptParams } from '../types'

const props = defineProps<{
  scriptKey: string
  info: ScriptInfo
  modelValue: ScriptParams
  running: boolean
  busy: boolean
  hasAdvanced?: boolean
  advancedLabel?: string
}>()
const emit = defineEmits<{
  'update:modelValue': [value: ScriptParams]
  save: []
  run: []
  stop: []
}>()

const visibleFields = computed(() => props.info.params.filter(isVisible))

function isVisible(field: Field) {
  const rule = field.visibleWhen
  if (!rule) return true
  const current = String(props.modelValue[rule.key] ?? '')
  if (rule.is !== undefined) return current === String(rule.is)
  if (rule.not !== undefined) return current !== String(rule.not)
  return true
}

function update(key: string, value: unknown) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<template>
  <PaperCard variant="task">
    <header>
      <div>
        <h2>
          {{ info.label }}
          <button v-if="info.desc" type="button" class="help-trigger" :aria-label="`${info.label}说明`">
            ?
            <span class="help-tooltip" role="tooltip">{{ info.desc }}</span>
          </button>
        </h2>
      </div>
      <span class="status" :class="{ running }">{{ running ? '运行中' : '待命' }}</span>
    </header>
    <div class="fields">
      <ParamField
        v-for="field in visibleFields"
        :key="field.key"
        :field="field"
        :model-value="modelValue[field.key]"
        @update:model-value="update(field.key, $event)"
      />
    </div>
    <div v-if="hasAdvanced" class="advanced-settings-slot">
      <span class="advanced-settings-label">{{ advancedLabel || '特有高级设置' }}</span>
      <slot name="advanced" />
    </div>
    <footer>
      <button type="button" class="secondary" @click="emit('save')">保存配置</button>
      <button v-if="running" type="button" class="danger" @click="emit('stop')">紧急停止</button>
      <button v-else type="button" class="primary" :disabled="busy" @click="emit('run')">
        {{ busy ? '有其他任务正在运行' : '开始任务' }}
      </button>
    </footer>
  </PaperCard>
</template>
