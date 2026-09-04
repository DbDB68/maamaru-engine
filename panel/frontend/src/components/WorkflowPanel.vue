<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import PanelHeader from './PanelHeader.vue'
import PaperCard from './PaperCard.vue'
import PixelControl from './PixelControl.vue'
import ParamField from './ParamField.vue'
import SegmentedControl from './SegmentedControl.vue'
import type { ParamField as Field, WorkflowNode, WorkflowNodeCategory, WorkflowNodeDef, WorkflowPreset } from '../types'

withDefaults(defineProps<{ embedded?: boolean; running?: boolean }>(), { embedded: false, running: false })

const categoryOrder: WorkflowNodeCategory[] = ['cold', 'chore', 'battle', 'finish']
const categoryLabels: Record<WorkflowNodeCategory, string> = {
  cold: '冷启动', chore: '后勤', battle: '出阵', finish: '收尾',
}

const presets = ref<WorkflowPreset[]>([])
const defs = ref<WorkflowNodeDef[]>([])
const currentId = ref<string | null>(null)
const draft = ref<WorkflowPreset | null>(null)
const expanded = ref<number | null>(null)
const pickerOpen = ref(false)
const saving = ref(false)
const renamingId = ref<string | null>(null)
const renameText = ref('')
const message = ref('')

const groupedDefs = computed(() => categoryOrder
  .map(category => ({ category, nodes: defs.value.filter(def => def.category === category) }))
  .filter(group => group.nodes.length))

const dirty = computed(() => {
  if (!draft.value) return false
  if (!draft.value.id) return true
  const saved = presets.value.find(preset => preset.id === draft.value?.id)
  return !saved || JSON.stringify(saved) !== JSON.stringify(draft.value)
})

function cloneNodes(nodes: WorkflowNode[]): WorkflowNode[] {
  return JSON.parse(JSON.stringify(nodes)) as WorkflowNode[]
}

function defaults(def: WorkflowNodeDef) {
  return Object.fromEntries((def.params || []).map(field => [field.key, field.default ?? '']))
}

function defOf(type: string) {
  return defs.value.find(def => def.type === type)
}

function isVisible(field: Field, node: WorkflowNode) {
  const rule = field.visibleWhen
  if (!rule) return true
  const current = String(node.params[rule.key] ?? '')
  if (rule.is !== undefined) return current === String(rule.is)
  if (rule.not !== undefined) return current !== String(rule.not)
  return true
}

async function load() {
  try {
    const [workflowData, nodeData] = await Promise.all([api.workflows(), api.workflowNodes()])
    presets.value = workflowData.presets || []
    defs.value = nodeData.nodes || []
  } catch (error) {
    message.value = error instanceof Error ? `工作流加载失败：${error.message}` : '工作流加载失败，请刷新重试'
  }
}

function select(preset: WorkflowPreset) {
  draft.value = { ...preset, nodes: cloneNodes(preset.nodes) }
  currentId.value = preset.id
  expanded.value = null
  pickerOpen.value = false
}

function newPreset() {
  draft.value = { id: '', name: `新流水线 ${presets.value.length + 1}`, nodes: [] }
  currentId.value = ''
  expanded.value = null
  pickerOpen.value = false
}

function duplicate(preset: WorkflowPreset) {
  draft.value = { id: '', name: `${preset.name} 副本`, nodes: cloneNodes(preset.nodes) }
  currentId.value = ''
  expanded.value = null
  message.value = '复制好了，点「保存成新流水线」落成正式预设'
}

async function remove(preset: WorkflowPreset) {
  if (!window.confirm(`确定删掉「${preset.name}」吗？删了就找不回来了。`)) return
  await api.deleteWorkflow(preset.id)
  if (currentId.value === preset.id) { draft.value = null; currentId.value = null }
  presets.value = presets.value.filter(item => item.id !== preset.id)
  message.value = `已删除「${preset.name}」`
}

function startRename(preset: WorkflowPreset) {
  renamingId.value = preset.id
  renameText.value = preset.name
}

async function commitRename(preset: WorkflowPreset) {
  if (renamingId.value !== preset.id) return
  renamingId.value = null
  const name = renameText.value.trim()
  if (!name || name === preset.name) return
  await api.updateWorkflow({ ...preset, name })
  preset.name = name
  if (draft.value?.id === preset.id) draft.value.name = name
  message.value = '改名完成'
}

async function run(preset: WorkflowPreset) {
  await api.run('workflow', { workflow_id: preset.id })
  message.value = `「${preset.name}」已开始，去「概览」看实况`
}

function addNode(def: WorkflowNodeDef) {
  if (!draft.value) return
  draft.value.nodes.push({ type: def.type, params: defaults(def), on_error: 'stop' })
  pickerOpen.value = false
  expanded.value = draft.value.nodes.length - 1
}

function move(index: number, delta: number) {
  if (!draft.value) return
  const target = index + delta
  if (target < 0 || target >= draft.value.nodes.length) return
  const nodes = draft.value.nodes
  ;[nodes[index], nodes[target]] = [nodes[target], nodes[index]]
  expanded.value = target
}

function removeNode(index: number) {
  if (!draft.value) return
  draft.value.nodes.splice(index, 1)
  if (expanded.value === index) expanded.value = null
  else if (expanded.value != null && expanded.value > index) expanded.value -= 1
}

function toggle(index: number) {
  expanded.value = expanded.value === index ? null : index
}

async function save() {
  if (!draft.value || saving.value) return
  saving.value = true
  try {
    if (draft.value.id) {
      await api.updateWorkflow(draft.value)
      message.value = '改动已保存'
    } else {
      const result = await api.createWorkflow({ name: draft.value.name, nodes: cloneNodes(draft.value.nodes) })
      draft.value.id = result.id || ''
      message.value = '新流水线已保存'
    }
    await load()
    if (draft.value?.id) currentId.value = draft.value.id
  } catch (error) {
    message.value = error instanceof Error ? `保存失败：${error.message}` : '保存失败，请重试'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="workflow-panel">
    <PanelHeader :variant="embedded ? 'embedded' : 'section'" title="工作流" subtitle="把任务积木排成一条流水线，一键从头跑到尾">
      <template #actions><button type="button" class="primary" @click="newPreset">＋ 新建流水线</button></template>
    </PanelHeader>
    <div class="workflow-body">
      <PaperCard variant="settings" class="preset-list-card">
        <h3>已保存的流水线</h3>
        <p v-if="!presets.length" class="empty">还没有流水线，点右上角「新建」搭一条吧。</p>
        <div v-for="preset in presets" :key="preset.id" class="preset-item" :class="{ active: currentId === preset.id }">
          <button type="button" class="preset-name" @click="select(preset)">
            <PixelControl v-if="renamingId === preset.id" v-model="renameText" @keyup.enter="commitRename(preset)" @blur="commitRename(preset)" />
            <strong v-else>{{ preset.name }}</strong>
            <small>{{ preset.nodes.length }} 块积木</small>
          </button>
          <span class="preset-tools">
            <button type="button" class="primary" :disabled="running" :title="running ? '有任务在跑，先等它忙完' : '按这条流水线从头跑一遍'" @click="run(preset)">跑这条</button>
            <button v-if="renamingId !== preset.id" type="button" @click="startRename(preset)">重命名</button>
            <button type="button" @click="duplicate(preset)">复制</button>
            <button type="button" class="danger" @click="remove(preset)">删除</button>
          </span>
        </div>
      </PaperCard>

      <PaperCard v-if="draft" variant="settings" class="workflow-editor">
        <div class="editor-head">
          <label class="stacked-field">流水线名字
            <PixelControl v-model="draft.name" placeholder="比如：早课快线" />
          </label>
          <span v-if="dirty" class="dirty-flag">有未保存的改动</span>
        </div>

        <div class="node-list">
          <p v-if="!draft.nodes.length" class="empty">一块积木都还没搭。点下面的「＋ 加积木」，从冷启动开始一块块往上垒。</p>
          <article v-for="(node, index) in draft.nodes" :key="index" class="workflow-node" :class="{ open: expanded === index }">
            <header @click="toggle(index)">
              <span class="step-number">{{ index + 1 }}</span>
              <strong>{{ defOf(node.type)?.label || node.type }}</strong>
              <small v-if="node.on_error === 'continue'" class="skip-tag">翻车跳过</small>
              <span class="node-tools">
                <button type="button" title="往上挪一格" :disabled="index === 0" @click.stop="move(index, -1)">↑</button>
                <button type="button" title="往下挪一格" :disabled="index === draft.nodes.length - 1" @click.stop="move(index, 1)">↓</button>
                <button type="button" class="danger" title="删掉这块积木" @click.stop="removeNode(index)">✕</button>
              </span>
            </header>
            <div v-if="expanded === index" class="node-detail">
              <p v-if="defOf(node.type)?.desc" class="node-desc">{{ defOf(node.type)?.desc }}</p>
              <div class="fields">
                <ParamField
                  v-for="field in (defOf(node.type)?.params || []).filter(item => isVisible(item, node))"
                  :key="field.key"
                  :field="field"
                  :model-value="node.params[field.key]"
                  @update:model-value="node.params[field.key] = $event"
                />
              </div>
              <div class="on-error-row">
                <span>这块翻车了怎么办？</span>
                <SegmentedControl
                  v-model="node.on_error"
                  label="翻车策略"
                  :items="[
                    { value: 'stop', label: '停下喊人', caption: '后面的积木先不跑' },
                    { value: 'continue', label: '跳过继续', caption: '记一笔翻车，接着跑下一块' },
                  ]"
                />
              </div>
            </div>
          </article>
        </div>

        <div class="add-block">
          <button type="button" class="secondary" @click="pickerOpen = !pickerOpen">＋ 加积木</button>
          <div v-if="pickerOpen" class="node-picker">
            <section v-for="group in groupedDefs" :key="group.category">
              <h4>{{ categoryLabels[group.category] }}</h4>
              <div class="picker-grid">
                <button v-for="def in group.nodes" :key="def.type" type="button" @click="addNode(def)">
                  <b>{{ def.label }}</b>
                  <small>{{ def.desc }}</small>
                </button>
              </div>
            </section>
          </div>
        </div>

        <footer class="editor-foot">
          <button type="button" class="primary" :disabled="!dirty || saving || !draft.name.trim()" @click="save">
            {{ saving ? '正在保存…' : draft.id ? '保存改动' : '保存成新流水线' }}
          </button>
        </footer>
      </PaperCard>
      <PaperCard v-else variant="settings" class="workflow-editor empty-editor">
        <p class="empty">从左边挑一条流水线开始编辑，或者点右上角「新建」搭一条新的。</p>
      </PaperCard>
      <p v-if="message" class="inline-message">{{ message }}</p>
    </div>
  </section>
</template>
