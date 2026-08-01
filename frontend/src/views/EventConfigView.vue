<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type Bot } from '@/services/api'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const callbackUrl = ref('https://bot.yzdoc.cn/api/events/callback')
const saving = ref(false)
const saved = ref(false)
const error = ref('')
const events = ref<Array<{ id: string; type: string; received_at: string; payload: unknown }>>([])
const scopes = ref([
  { key: 'C2C_MESSAGE_CREATE', label: '单聊消息', checked: false },
  { key: 'GROUP_AT_MESSAGE_CREATE', label: '群聊 @ 消息', checked: false },
  { key: 'AT_MESSAGE_CREATE', label: '频道 @ 消息', checked: false },
  { key: 'DIRECT_MESSAGE_CREATE', label: '频道私信', checked: false },
  { key: 'INTERACTION_CREATE', label: '按钮交互', checked: false },
  { key: 'GROUP_ADD_ROBOT', label: '机器人加入群聊', checked: false },
])

const currentBot = computed(() => bots.value.find(bot => bot.id === botId.value) || null)

function applyBot(bot: Bot | null) {
  if (!bot) return
  callbackUrl.value = bot.callback_url || 'https://bot.yzdoc.cn/api/events/callback'
  const selected = new Set(bot.event_scopes || [])
  scopes.value = scopes.value.map(scope => ({ ...scope, checked: selected.has(scope.key) }))
}

async function loadBots() {
  bots.value = await api.listBots()
  const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
  if (preferred && bots.value.some(bot => bot.id === preferred)) botId.value = preferred
  else if (!botId.value && bots.value.length) botId.value = bots.value[0].id
  applyBot(currentBot.value)
}

async function save() {
  if (!botId.value) {
    error.value = '请先选择机器人'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const bot = await api.updateBot(botId.value, {
      callback_url: callbackUrl.value.trim(),
      event_scopes: scopes.value.filter(scope => scope.checked).map(scope => scope.key),
    })
    const index = bots.value.findIndex(item => item.id === bot.id)
    if (index >= 0) bots.value[index] = bot
    saved.value = true
    setTimeout(() => { saved.value = false }, 1400)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

watch(botId, () => applyBot(currentBot.value))
onMounted(async () => {
  try {
    await loadBots()
    events.value = await api.recentEvents()
  } catch {
    events.value = []
  }
})
</script>

<template>
  <section class="page events-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">事件与回调</h1>
        <p class="page-sub">按机器人配置回调地址与订阅范围，配置保存在服务端。</p>
      </div>
      <button class="btn primary" :disabled="saving || !botId" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
    </div>

    <div class="field bot-field">
      <label>当前机器人</label>
      <select v-model="botId" class="select">
        <option disabled value="">请选择机器人</option>
        <option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }} · {{ bot.app_id || '无 AppID' }}</option>
      </select>
    </div>

    <div v-if="!bots.length" class="card empty-card">暂无机器人，请先在「我的机器人」中创建并填写凭证。</div>
    <div v-else class="grid">
      <div class="main-col">
        <section class="card section-card">
          <h2 class="section-title">HTTP 回调地址</h2>
          <p class="section-sub">正式部署后将地址填写到 QQ 开放平台。当前项目提供同路径接收接口。</p>
          <div class="field url-field"><label>Callback URL</label><input v-model="callbackUrl" class="input mono" /></div>
          <div class="notice"><b>安全提醒</b><span>示例接口尚未实现平台签名验证，不能直接作为生产环境最终方案。</span></div>
        </section>
        <section class="card section-card">
          <h2 class="section-title">订阅事件</h2>
          <p class="section-sub">勾选后保存到当前机器人配置，最终范围以开放平台实际授权为准。</p>
          <div class="scope-grid">
            <label v-for="scope in scopes" :key="scope.key" class="scope-card" :class="{ active: scope.checked }">
              <input v-model="scope.checked" type="checkbox" />
              <span><strong>{{ scope.label }}</strong><code>{{ scope.key }}</code></span>
            </label>
          </div>
        </section>
      </div>
      <aside class="side-col">
        <section class="card section-card">
          <h2 class="section-title">接入状态</h2>
          <div class="status-box">
            <span class="status-pill" :class="currentBot?.has_secret ? 'online' : 'warn'">{{ currentBot?.has_secret ? '凭证已配置' : '待配置凭证' }}</span>
            <p>{{ currentBot ? `正在编辑「${currentBot.name}」的事件配置。` : '请选择机器人。' }}</p>
          </div>
          <div class="kv"><span>入口路径</span><code>/api/events/callback</code></div>
          <div class="kv"><span>最近事件</span><b>{{ events.length }}</b></div>
        </section>
        <section class="card section-card">
          <h2 class="section-title">最近事件</h2>
          <div v-if="events.length === 0" class="empty">暂无事件。可向回调接口 POST 测试 JSON。</div>
          <div v-for="event in events" :key="event.id" class="event-item"><strong>{{ event.type }}</strong><span>{{ event.received_at }}</span></div>
        </section>
      </aside>
    </div>
    <p v-if="error" class="inline-error">{{ error }}</p>
    <div v-if="saved" class="global-toast">事件配置已保存到服务端</div>
  </section>
</template>

<style scoped>
.events-page { max-width: 1120px; }
.bot-field { max-width: 420px; margin-bottom: 18px; }
.empty-card { padding: 28px; color: var(--ink-3); }
.grid { display: grid; grid-template-columns: minmax(0,1fr) 320px; gap: 18px; align-items: start; }
.main-col, .side-col { display: flex; flex-direction: column; gap: 18px; }
.side-col { position: sticky; top: 24px; }
.section-card { padding: 22px; }
.url-field { margin-top: 18px; }
.notice { display: flex; gap: 8px; margin-top: 14px; padding: 12px 14px; border-radius: 12px; background: rgba(255,149,0,.08); color: var(--warn); font-size: 12px; line-height: 1.5; }
.notice span { color: #9b6500; }
.scope-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 18px; }
.scope-card { display: flex; gap: 11px; padding: 13px; border: 1px solid var(--line); border-radius: 13px; background: white; cursor: pointer; transition: .15s ease; }
.scope-card.active { border-color: var(--accent); background: var(--accent-soft); }
.scope-card input { width: 16px; height: 16px; accent-color: var(--accent); }
.scope-card strong, .scope-card code { display: block; }
.scope-card code { margin-top: 5px; color: var(--ink-4); font-size: 10.5px; }
.status-box { margin-top: 18px; padding: 14px; border-radius: 14px; background: var(--bg-sunken); }
.status-box p { margin: 10px 0 0; color: var(--ink-3); font-size: 12px; line-height: 1.55; }
.kv { display: flex; justify-content: space-between; gap: 10px; padding: 13px 0; border-top: 1px solid var(--line); color: var(--ink-3); font-size: 12px; }
.kv code { color: var(--ink); }
.empty { margin-top: 16px; padding: 24px 12px; border: 1px dashed var(--line); border-radius: 12px; text-align: center; color: var(--ink-4); font-size: 12px; }
.event-item { padding: 12px 0; border-top: 1px solid var(--line); }
.event-item strong, .event-item span { display: block; }
.event-item span { margin-top: 4px; color: var(--ink-4); font-size: 11px; }
.inline-error { margin-top: 12px; color: var(--danger); }
.global-toast { position: fixed; top: 24px; left: 50%; transform: translateX(-50%); z-index: 100; padding: 10px 16px; border-radius: 12px; background: rgba(29,29,31,.92); color: white; box-shadow: var(--shadow-lg); }
@media (max-width: 900px) { .grid { grid-template-columns: 1fr; } .side-col { position: static; } }
@media (max-width: 600px) { .scope-grid { grid-template-columns: 1fr; } }
</style>
