<script setup lang="ts">
defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  as?: 'input' | 'select' | 'textarea'
  modelValue: unknown
  type?: string
  numeric?: boolean
}>(), { as: 'input', type: 'text', numeric: false })

const emit = defineEmits<{ 'update:modelValue': [value: unknown] }>()

function update(event: Event) {
  const value = (event.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement).value
  emit('update:modelValue', props.numeric ? Number(value) : value)
}
</script>

<template>
  <select v-if="as === 'select'" class="pixel-control" v-bind="$attrs" :value="String(modelValue ?? '')" @change="update"><slot /></select>
  <textarea v-else-if="as === 'textarea'" class="pixel-control" v-bind="$attrs" :value="String(modelValue ?? '')" @input="update" />
  <input v-else class="pixel-control" v-bind="$attrs" :type="type" :value="modelValue as any" @input="update" />
</template>
