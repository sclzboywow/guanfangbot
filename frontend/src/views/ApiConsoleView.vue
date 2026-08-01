<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type Bot, type CredentialStatus } from '@/services/api'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const method = ref('GET')
const path = ref('/users/@me')
const body = ref('{}')
const running = ref(false)
const result = ref('尚未发送请求。')
const credential = ref<CredentialStatus | null>(null)
const presets = [
  { label: '机器人身份', method: 'GET', path: '/users/@me', body: '{}' },
  { label: '频道列表', method: 'GET', path: '/users/@me/guilds', body: '{}' },
]

async function loadBots() {
  bots.value = await api.listBots()
  const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
  if (preferred && bots.value.some(bot => bot.id === preferred)) botId.value = preferred
  else if (!botId.value && bots.value.length) botId.value = bots.value[0].id
}

async function loadCredential() {
  if (!botId.value) {
    credential.value = null
    return
  }
  try { credential.value = await api.credentialStatus(botId.value) }
  catch { credential.value = null }
}

function applyPreset(preset: typeof presets[number]) {
  method.value = preset.method
  path.value = preset.path
  body.value = preset.body
}

async function run() {
  if (!botId.value) {
    result.value = JSON.stringify({ error: '请先选择机器人' }, null, 2)
    return
  }
  running.value = true
  try {
    let parsed: unknown = undefined
    if (!['GET', 'DELETE'].includes(method.value) && body.value.trim()) parsed = JSON.parse(body.value)
    const response = await api.openApi({ bot_id: botId.value, method: method.value, path: path.value, body: parsed })
    result.value = JSON.stringify(response, null, 2)
    await loadCredential()
  } catch (e) {
    result.value = JSON.stringify({ error: e instanceof Error ? e.message : '请求失败' }, null, 2)
  } finally {
    running.value = false
  }
}

watch(botId, () => { loadCredential() })
onMounted(async () => {
  try { await loadBots(); await loadCredential() }
  catch { bots.value = [] }
})
</script>

<template>
  <section class="page console-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">OpenAPI 调试</h1>
        <p class="page-sub">使用选中机器人的服务端凭证调用 QQ 官方 API，Key 和 Access Token 不会进入浏览器。</p>
      </div>
      <span v-if="credential" class="status-pill" :class="credential.configured ? 'online' : 'warn'">
        {{ credential.configured ? (credential.token_cached ? 'Token 已缓存' : '凭证已配置') : '未配置凭证' }}
      </span>
    </div>

    <div v-if="!bots.length" class="card empty-card">暂无机器人，请先添加 AppID、Key 和回调地址。</div>
    <div v-else class="console-grid">
      <section class="card request-card">
        <div class="field bot-field">
          <label>使用机器人</label>
          <select v-model="botId" class="select">
            <option disabled value="">请选择机器人</option>
            <option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }} · {{ bot.app_id }}</option>
          </select>
        </div>

        <div class="preset-row">
          <span>快捷请求</span>
          <button v-for="preset in presets" :key="preset.label" class="preset-btn" type="button" @click="applyPreset(preset)">{{ preset.label }}</button>
        </div>

        <div class="request-line">
          <select v-model="method" class="select method">
            <option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option>
          </select>
          <input v-model="path" class="input mono path" placeholder="/users/@me" />
          <button class="btn primary" :disabled="running || !botId" @click="run">{{ running ? '发送中…' : '发送请求' }}</button>
        </div>
        <div class="field body-field"><label>JSON Body</label><textarea v-model="body" class="textarea" :disabled="['GET','DELETE'].includes(method)"></textarea></div>
        <div class="actions">
          <span class="token-hint">Access Token 由后端自动获取、缓存并在到期后重新申请。</span>
          <a href="https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/api-call-guide.html" target="_blank" rel="noopener noreferrer" class="doc-link">查看官方调用指南 ↗</a>
        </div>
      </section>

      <section class="card response-card">
        <div class="response-head">
          <h2 class="section-title">完整响应</h2>
          <span v-if="credential" class="mono muted">{{ credential.api_base }}</span>
        </div>
        <pre>{{ result }}</pre>
      </section>
    </div>
  </section>
</template>

<style scoped>
.console-page { max-width: 1180px; }
.empty-card { padding: 28px; color: var(--ink-3); }
.console-grid { display: grid; grid-template-columns: minmax(0,1fr) minmax(360px,.9fr); gap: 18px; }
.request-card, .response-card { padding: 20px; }
.bot-field { margin-bottom: 14px; }
.preset-row { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; margin-bottom: 14px; }
.preset-row > span { margin-right: 3px; color: var(--ink-4); font-size: 11.5px; }
.preset-btn { padding: 5px 9px; border: 1px solid var(--line); border-radius: 999px; background: var(--bg-sunken); color: var(--ink-3); font-size: 11.5px; }
.preset-btn:hover { border-color: var(--accent-border); background: var(--accent-soft); color: var(--accent); }
.request-line { display: grid; grid-template-columns: 110px minmax(0,1fr) auto; gap: 10px; }
.method { font-weight: 750; color: var(--accent); }
.body-field { margin-top: 18px; }
.actions { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 14px; }
.token-hint { color: var(--ink-4); font-size: 11.5px; line-height: 1.5; }
.doc-link { flex: none; color: var(--accent); font-size: 11.5px; }
.response-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.response-head span { font-size: 10.5px; }
pre { min-height: 390px; max-height: 680px; overflow: auto; margin: 16px 0 0; padding: 16px; border-radius: 14px; background: #111827; color: #d6e4ff; font: 12px/1.65 var(--font-mono); white-space: pre-wrap; word-break: break-word; }
@media (max-width: 960px) { .console-grid { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .request-line { grid-template-columns: 92px 1fr; } .request-line .btn { grid-column: 1/-1; } .actions { align-items: flex-start; flex-direction: column; } }
</style>
