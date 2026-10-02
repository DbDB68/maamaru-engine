<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { api } from '../api'
import { matchesRule } from '../visibility'
import ParamField from './ParamField.vue'
import type { ScriptInfo, ScriptParams } from '../types'

const emit = defineEmits<{ saved: [script: string, params: ScriptParams] }>()
const dialog = ref<HTMLDialogElement>()
const script = ref('')
const info = ref<ScriptInfo>()
const params = ref<ScriptParams>({})
const busy = ref(false)
const message = ref('')
let requestId = 0
const fields = computed(() => (info.value?.params || []).filter(field =>
  !['runs', 'rounds', 'loops', 'floors', 'max_runs', 'refill_run_limit'].includes(field.key)
  && matchesRule(field.visibleWhen, key => params.value[key])))

async function open(key: string) {
  const id = ++requestId
  script.value = key
  info.value = undefined
  params.value = {}
  message.value = ''
  busy.value = true
  await nextTick()
  if (!dialog.value?.open) dialog.value?.showModal()
  try {
    const result = await api.gameplaySettings(key)
    if (id !== requestId) return
    info.value = result.info
    params.value = result.params
  } catch (error) {
    message.value = error instanceof Error ? error.message : '设置没读到，请关闭后重试'
  } finally {
    if (id === requestId) busy.value = false
  }
}

function close() {
  if (busy.value) return
  ++requestId
  dialog.value?.close()
}

async function save() {
  if (!info.value || busy.value) return
  busy.value = true
  message.value = ''
  try {
    const result = await api.saveGameplaySettings(script.value, params.value)
    emit('saved', script.value, result.params)
    dialog.value?.close()
  } catch (error) {
    message.value = error instanceof Error ? error.message : '没存上，请重试'
  } finally {
    busy.value = false
  }
}
defineExpose({ open })
</script>

<template>
  <dialog ref="dialog" class="gameplay-dialog" aria-labelledby="gameplay-dialog-title"
    @cancel.prevent="close" @click="($event.target === dialog) && close()">
    <header>
      <h2 id="gameplay-dialog-title">{{ info?.label || '读取中…' }} · 玩法设置</h2>
      <button type="button" :disabled="busy" aria-label="关闭玩法设置" @click="close">关闭</button>
    </header>
    <p class="note">与玩法页共用设置；本段出阵次数以时间表为准。保存后还需保存时间表，才会到点开工。</p>
    <div class="gameplay-fields">
      <ParamField v-for="field in fields" :key="field.key" :field="field"
        :model-value="params[field.key]" @update:model-value="params[field.key] = $event" />
    </div>
    <p v-if="message" role="alert">{{ message }}</p>
    <footer>
      <button type="button" :disabled="busy || !info" @click="save">{{ busy ? '请稍候…' : '保存并关闭' }}</button>
      <button type="button" :disabled="busy" @click="close">取消</button>
    </footer>
  </dialog>
</template>

<style scoped>
.gameplay-dialog { width: min(680px, calc(100vw - 32px)); max-height: calc(100dvh - 40px); box-sizing: border-box; overflow: auto; padding: 24px; border: 1px solid var(--paper-line); border-radius: 14px; color: var(--ink); background: var(--paper-card); }
.gameplay-dialog::backdrop { background: rgb(0 0 0 / 38%); }
header, footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h2 { margin: 0; font-size: 18px; }
.note { font-size: 13px; line-height: 1.7; }
.gameplay-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin: 20px 0; }
footer { justify-content: flex-start; }
header button, footer button { padding: 9px 14px; border: 1px solid var(--paper-line); border-radius: 8px; color: var(--ink); background: var(--paper-card); font: inherit; cursor: pointer; }
footer button:first-child { border-color: var(--fox-gold); background: var(--paper-panel); }
header button:disabled, footer button:disabled { cursor: wait; opacity: .6; }
header button:focus-visible, footer button:focus-visible { outline: 2px solid var(--fox-gold); outline-offset: 3px; }
@media (max-width: 560px) { .gameplay-dialog { padding: 18px; } .gameplay-fields { grid-template-columns: 1fr; } }
</style>
