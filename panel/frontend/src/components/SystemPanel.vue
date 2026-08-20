<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import QQStatus from './QQStatus.vue'
import PanelHeader from './PanelHeader.vue'
import SideNavItem from './SideNavItem.vue'
import PixelControl from './PixelControl.vue'

const selected = ref<'ai' | 'qq' | 'telegram' | 'broadcast'>('ai')
const ai = ref<any>(null)
const bot = ref<any>(null)
const apiKey = ref('')
const telegramToken = ref('')
const message = ref('')
async function load() { [ai.value, bot.value] = await Promise.all([api.chatConfig(), api.botConfig()]) }
async function save() {
  message.value = '正在保存……'
  try {
    if (selected.value === 'ai') {
      await api.saveChatConfig({ api_key: apiKey.value, base_url: ai.value.base_url, model: ai.value.model, system_prompt: ai.value.system_prompt })
      apiKey.value = ''
    } else if (selected.value === 'qq') {
      await api.saveBotConfig({ enabled: bot.value.qq.enabled || (bot.value.platform === 'telegram' && bot.value.enabled), platform: bot.value.qq.enabled ? 'qq' : bot.value.platform, qq: bot.value.qq })
    } else if (selected.value === 'telegram') {
      await api.saveBotConfig({ enabled: bot.value.telegram.enabled || bot.value.qq.enabled, platform: bot.value.telegram.enabled ? 'telegram' : (bot.value.qq.enabled ? 'qq' : 'telegram'), telegram: { token: telegramToken.value, allowed_users: bot.value.telegram.allowed_users } })
      telegramToken.value = ''
    } else await api.saveBotConfig({ broadcast: bot.value.broadcast })
    message.value = '设置已保存'
  } catch (_) { message.value = '保存失败，请检查面板连接' }
}
onMounted(async () => { await load(); if (bot.value.telegram.enabled == null) bot.value.telegram.enabled = bot.value.platform === 'telegram' && bot.value.enabled })
</script>

<template>
  <section v-if="ai && bot" class="system-panel">
    <PanelHeader variant="page" title="系统设置" subtitle="近侍、协议端与播报"><template #actions><button class="primary" @click="save">保存设置</button></template></PanelHeader>
    <div class="system-layout"><nav class="system-nav"><SideNavItem :active="selected === 'ai'" @click="selected = 'ai'">近侍 AI</SideNavItem><SideNavItem :active="selected === 'qq'" @click="selected = 'qq'">QQ</SideNavItem><SideNavItem :active="selected === 'telegram'" @click="selected = 'telegram'">Telegram</SideNavItem><SideNavItem :active="selected === 'broadcast'" @click="selected = 'broadcast'">播报</SideNavItem></nav>
      <div class="system-form" :class="`${selected}-form`">
        <template v-if="selected === 'ai'"><h3>近侍 AI</h3><label>API Key<PixelControl v-model="apiKey" type="password" :placeholder="ai.has_key ? `已配置（${ai.api_key_masked}），留空不改` : '输入 API Key'" /></label><label>API 地址<PixelControl v-model="ai.base_url" /></label><label>模型<PixelControl v-model="ai.model" /></label><label>角色设定<PixelControl v-model="ai.system_prompt" as="textarea" /></label><p>保存后立即生效，不需要重启。</p></template>
        <template v-else-if="selected === 'qq'"><h3>QQ 协议端</h3><QQStatus /><label class="check-label"><input v-model="bot.qq.enabled" type="checkbox" />启用 QQ</label><label>协议端<PixelControl v-model="bot.qq.provider" as="select"><option value="napcat">NapCat</option><option value="snowluma">SnowLuma</option><option value="custom">其他 OneBot 实现</option></PixelControl></label><label>消息接口<PixelControl v-model="bot.qq.snowluma_http" /></label><label>管理页<PixelControl v-model="bot.qq.snowluma_gui_http" /></label><label>管理员 QQ<PixelControl :model-value="(bot.qq.admin_qq || []).join(', ')" @update:model-value="bot.qq.admin_qq = $event" /></label><p>QQ 配置修改后需要重启まあ丸。</p></template>
        <template v-else-if="selected === 'telegram'"><h3>Telegram</h3><label class="check-label"><input v-model="bot.telegram.enabled" type="checkbox" />启用 Telegram Bot</label><label>Bot Token<PixelControl v-model="telegramToken" type="password" :placeholder="bot.telegram.has_token ? `已配置（${bot.telegram.token_masked}），留空不改` : '输入 Token'" /></label><label>允许的用户 ID<PixelControl :model-value="(bot.telegram.allowed_users || []).join(', ')" @update:model-value="bot.telegram.allowed_users = $event" /></label><p>Token 留空不会改变现有配置。</p></template>
        <template v-else><h3>运行播报</h3><label class="check-label"><input v-model="bot.broadcast.qq" type="checkbox" />QQ 渠道播报</label><label class="check-label"><input v-model="bot.broadcast.ntfy" type="checkbox" />ntfy 推送</label><p>脚本运行状态变化时通知已启用的渠道。</p></template>
        <p v-if="message" class="inline-message">{{ message }}</p>
      </div>
    </div>
  </section>
</template>
