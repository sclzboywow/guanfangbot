<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type Bot, type BotEvent } from '@/services/api'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const callbackUrl = ref('')
const events = ref<BotEvent[]>([])
const saving = ref(false)
const message = ref('')
const error = ref('')
const scopes = ref([
  { key:'C2C_MESSAGE_CREATE', label:'单聊消息', checked:false },
  { key:'GROUP_AT_MESSAGE_CREATE', label:'群聊 @ 消息', checked:false },
  { key:'AT_MESSAGE_CREATE', label:'频道 @ 消息', checked:false },
  { key:'DIRECT_MESSAGE_CREATE', label:'频道私信', checked:false },
  { key:'INTERACTION_CREATE', label:'按钮交互', checked:false },
  { key:'GROUP_ADD_ROBOT', label:'机器人加入群聊', checked:false },
])
const currentBot = computed(() => bots.value.find(item => item.id === botId.value) || null)

function applyBot() {
  const bot = currentBot.value
  if (!bot) return
  callbackUrl.value = bot.callback_url
  const selected = new Set(bot.event_scopes)
  scopes.value.forEach(scope => { scope.checked = selected.has(scope.key) })
}

async function loadEvents() {
  events.value = botId.value ? await api.recentEvents(botId.value) : []
}

async function save() {
  if (!botId.value) return
  saving.value = true; error.value = ''; message.value = ''
  try {
    const updated = await api.updateBot(botId.value, {
      callback_url: callbackUrl.value.trim(),
      event_scopes: scopes.value.filter(item => item.checked).map(item => item.key),
    })
    const index = bots.value.findIndex(item => item.id === updated.id)
    if (index >= 0) bots.value[index] = updated
    message.value = '事件配置已保存'
  } catch (e) { error.value = e instanceof Error ? e.message : '保存失败' }
  finally { saving.value = false }
}

watch(botId, async () => { applyBot(); await loadEvents() })
onMounted(async () => {
  bots.value = await api.listBots()
  const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
  botId.value = bots.value.some(item => item.id === preferred) ? preferred : (bots.value[0]?.id || '')
  applyBot(); await loadEvents()
})
</script>

<template>
  <section class="page events-page">
    <div class="page-head"><div><h1 class="page-title">事件与回调</h1><p class="page-sub">选择机器人，维护回调地址和开发阶段关注的事件。</p></div><button class="btn primary" :disabled="saving || !botId" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button></div>
    <div v-if="!bots.length" class="card empty">暂无机器人，请先新增机器人。</div>
    <template v-else>
      <div class="field selector"><label>当前机器人</label><select v-model="botId" class="select"><option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }} · {{ bot.app_id }}</option></select></div>
      <div class="grid">
        <div class="main">
          <section class="card panel"><h2 class="section-title">回调地址</h2><p class="section-sub">将此地址填入 QQ 开放平台。多机器人建议使用带 AppID 的独立路径。</p><div class="field top"><input v-model="callbackUrl" class="input mono" /></div><code class="path">POST /api/events/callback/{{ currentBot?.app_id }}</code></section>
          <section class="card panel"><h2 class="section-title">事件范围</h2><p class="section-sub">这里用于开发台筛选和记录，最终权限以开放平台授权为准。</p><div class="scope-grid"><label v-for="scope in scopes" :key="scope.key" class="scope" :class="{active:scope.checked}"><input v-model="scope.checked" type="checkbox" /><span><strong>{{ scope.label }}</strong><small>{{ scope.key }}</small></span></label></div></section>
        </div>
        <aside class="card panel recent"><div class="recent-head"><h2 class="section-title">最近事件</h2><button class="btn" @click="loadEvents">刷新</button></div><div v-if="!events.length" class="empty-events">尚未收到事件。</div><div v-for="event in events" :key="event.id" class="event"><strong>{{ event.type }}</strong><small>{{ event.received_at }}</small></div></aside>
      </div>
      <p v-if="message" class="ok">{{ message }}</p><p v-if="error" class="error">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.events-page{max-width:1120px}.selector{max-width:440px;margin-bottom:18px}.empty{padding:30px}.grid{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:18px;align-items:start}.main{display:flex;flex-direction:column;gap:18px}.panel{padding:22px}.top{margin-top:18px}.path{display:block;margin-top:10px;padding:10px 12px;border-radius:10px;background:var(--bg-sunken);color:var(--ink-3);word-break:break-all}.scope-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:18px}.scope{display:flex;gap:10px;padding:13px;border:1px solid var(--line);border-radius:13px;cursor:pointer}.scope.active{border-color:var(--accent);background:var(--accent-soft)}.scope input{accent-color:var(--accent)}.scope strong,.scope small{display:block}.scope small{margin-top:4px;color:var(--ink-4);font-size:10.5px}.recent{position:sticky;top:22px}.recent-head{display:flex;align-items:center;justify-content:space-between}.empty-events{padding:28px 8px;text-align:center;color:var(--ink-4)}.event{padding:12px 0;border-top:1px solid var(--line)}.event strong,.event small{display:block}.event small{margin-top:4px;color:var(--ink-4)}.ok{color:#238541}.error{color:var(--danger)}@media(max-width:900px){.grid{grid-template-columns:1fr}.recent{position:static}}@media(max-width:600px){.scope-grid{grid-template-columns:1fr}}
</style>
