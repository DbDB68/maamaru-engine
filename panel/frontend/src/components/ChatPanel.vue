<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import { api } from '../api'
import PanelHeader from './PanelHeader.vue'
import PixelControl from './PixelControl.vue'

interface Message { role: string; content: string; ts?: number }
const messages = ref<Message[]>([])
const input = ref('')
const busy = ref(false)
const container = ref<HTMLElement | null>(null)

async function scrollEnd() { await nextTick(); container.value?.scrollTo({ top: container.value.scrollHeight }) }
async function load() { messages.value = (await api.chatHistory()).history || []; scrollEnd() }
async function send() {
  const value = input.value.trim()
  if (!value || busy.value) return
  messages.value.push({ role: 'user', content: value })
  input.value = ''
  busy.value = true
  scrollEnd()
  try {
    const result = await api.chat(value)
    messages.value.push({ role: 'assistant', content: result.reply })
  } catch (_) {
    messages.value.push({ role: 'assistant', content: '（狐之助耳朵耷拉下来：主君……面板好像断线了）' })
  } finally {
    busy.value = false
    scrollEnd()
  }
}
function clearLocal() { messages.value = [] }
onMounted(load)
</script>

<template>
  <section class="chat-panel">
    <PanelHeader variant="page" title="狐之助" subtitle="本丸近侍"><template #actions><button class="secondary" @click="clearLocal">清屏</button></template></PanelHeader>
    <div ref="container" class="messages">
      <div v-if="!messages.length" class="message assistant"><i>🦊</i><p>主君，您来了！有什么需要我帮忙的吗？</p></div>
      <div v-for="(message, index) in messages" :key="index" class="message" :class="message.role === 'user' ? 'user' : 'assistant'">
        <i>{{ message.role === 'user' ? '🧑' : '🦊' }}</i><p>{{ message.content }}</p>
      </div>
      <div v-if="busy" class="message assistant"><i>🦊</i><p>思考中……</p></div>
    </div>
    <form class="chat-input" @submit.prevent="send"><PixelControl v-model="input" placeholder="跟狐之助说点什么……" :disabled="busy" /><button class="primary" :disabled="busy || !input.trim()">发送</button></form>
  </section>
</template>
