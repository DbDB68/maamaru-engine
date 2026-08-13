<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'

const status = ref<any>(null)
const loading = ref(false)
async function refresh() { loading.value = true; try { status.value = await api.qqStatus() } finally { loading.value = false } }
onMounted(refresh)
</script>

<template>
  <div class="qq-status" :class="status?.state">
    <div><strong>{{ loading ? '正在检测协议端……' : status?.state === 'connected' ? '协议端已连接' : '未检测到协议端' }}</strong><button class="secondary" @click="refresh">重新检测</button></div>
    <div v-if="status" class="qq-checks"><span :class="{ ok: status.api_online }">消息 API：{{ status.api_online ? '可用' : status.api_detail }}</span><span :class="{ ok: status.gui_online }">管理页面：{{ status.gui_online ? '可打开' : status.gui_detail }}</span><span :class="{ ok: status.webhook_ready }">消息入口：{{ status.webhook_ready ? '已准备' : '未挂载' }}</span></div>
    <a v-if="status?.gui_url" :href="status.gui_url" target="_blank" rel="noreferrer">打开协议端管理页 ↗</a>
  </div>
</template>
