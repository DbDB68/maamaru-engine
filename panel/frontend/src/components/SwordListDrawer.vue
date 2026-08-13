<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { api } from '../api'
import PixelControl from './PixelControl.vue'

const props = defineProps<{ open: boolean; title: string; description: string; modelValue: string[] }>()
const emit = defineEmits<{ close: []; 'update:modelValue': [value: string[]] }>()
const swords = ref<Array<{ name: string; name_zh: string; type: string }>>([])
const search = ref('')
const candidates = computed(() => {
  const query = search.value.trim().toLowerCase()
  return swords.value.filter(sword => !query || `${sword.name}${sword.name_zh}${sword.type}`.toLowerCase().includes(query))
})
function nameOf(sword: { name: string; name_zh: string }) { return sword.name_zh || sword.name }
function toggle(name: string) {
  const value = [...props.modelValue]
  const index = value.indexOf(name)
  if (index >= 0) value.splice(index, 1); else value.push(name)
  emit('update:modelValue', value)
}
onMounted(async () => { swords.value = (await api.swords()).swords })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="drawer-backdrop" @click.self="$emit('close')">
      <aside class="settings-drawer" role="dialog" aria-modal="true" :aria-label="title">
        <header><div><span>特有高级设置</span><h2>{{ title }}</h2><p>{{ description }}</p></div><button type="button" aria-label="关闭" @click="$emit('close')">×</button></header>
        <section>
          <div class="drawer-selected"><button v-for="name in modelValue" :key="name" @click="toggle(name)">{{ name }} ×</button><span v-if="!modelValue.length">当前未指定目标，会正常刷完遇到的剪影。</span></div>
          <PixelControl v-model="search" class="drawer-search" placeholder="搜索刀剑名字或刀种" autofocus />
          <div class="drawer-candidates"><button v-for="sword in candidates" :key="sword.name" :class="{ active: modelValue.includes(nameOf(sword)) }" @click="toggle(nameOf(sword))"><b>{{ nameOf(sword) }}</b><small>{{ sword.type }}</small></button></div>
        </section>
        <footer><span>已选 {{ modelValue.length }} 把</span><button class="primary" type="button" @click="$emit('close')">完成</button></footer>
      </aside>
    </div>
  </Teleport>
</template>
