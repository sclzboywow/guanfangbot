<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { api, type Bot, type CredentialStatus } from '@/services/api'

const bots = ref<Bot[]>([])
const botId = ref('')
const method = ref('GET')
const path = ref('/users/@me')
const body = ref('{}')
const running = ref(false)
const result = ref('尚未发送请求。')
const credential = ref<CredentialStatus | null>(null)

async function loadBots() {
  bots.value = await api.listBots()
  if (!botId.value && bots.value.length) botId.value = bots.value[0].id
}

async function loadCredential() {
  if (!botId.value) {
    credential.value = null
    return
  }
  try { credential.value = await api.credentialStatus(botId.value) }
  catch { credential.value = null }
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

async function refresh() {
  if (!botId.value) return
  try {
    await api.refreshToken(botId.value)
    await loadCredential()
    result.value = JSON.stringify({ ok: true, message: 'Access Token 已刷新' }, null, 2)
  } catch (e) {
    result.value = JSON.stringify({ error: e instanceof Error ? e.message : '刷新失败' }, null, 2)
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
        <h1 class="page-title">API 调试台</h1>
        <p class="page-sub">选择前台已配置的机器人，通过后端代理调用 QQ OpenAPI。</p>
      </div>
      <span v-if="credential" class="status-pill" :class="credential.configured ? 'online' : 'warn'">
        {{ credential.configured ? '凭证已配置' : '未配置凭证' }}
      </span>
    </div>

    <div class="console-grid">
      <section class="card request-card">
        <div class="field bot-field">
          <label>使用机器人</label>
          <select v-model="botId" class="select">
            <option disabled value="">请选择机器人</option>
            <option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }} · {{ bot.app_id || '无 AppID' }}</option>
          </select>
        </div>
        <div class="request-line">
          <select v-model="method" class="select method">
            <option>GET</option><option>POST</option><option>PUT</option><option>PATCH</option><option>DELETE</option>
          </select>
          <input v-model="path" class="input mono path" placeholder="/users/@me" />
          <button class="btn primary" :disabled="running || !botId" @click="run">{{ running ? '发送中…' : '发送' }}</button>
        </div>
        <div class="field body-field"><label>JSON Body</label><textarea v-model="body" class="textarea" :disabled="['GET','DELETE'].includes(method)"></textarea></div>
        <div class="actions">
          <button class="btn" :disabled="!botId" @click="refresh">刷新 Access Token</button>
          <span class="hint">Token 按机器人分别缓存；AppSecret 不会进入浏览器。</span>
        </div>
      </section>
      <section class="card response-card">
        <div class="response-head">
          <h2 class="section-title">响应</h2>
          <span v-if="credential" class="mono muted">{{ credential.api_base }}</span>
        </div>
        <pre>{{ result }}</pre>
      </section>
    </div>
  </section>
</template>

<style scoped>
.console-page { max-width: 1180px; }
.console-grid { display: grid; grid-template-columns: minmax(0,1fr) minmax(360px,.9fr); gap: 18px; }
.request-card, .response-card { padding: 20px; }
.bot-field { margin-bottom: 14px; }
.request-line { display: grid; grid-template-columns: 110px minmax(0,1fr) auto; gap: 10px; }
.method { font-weight: 750; color: var(--accent); }
.body-field { margin-top: 18px; }
.actions { display: flex; align-items: center; gap: 12px; margin-top: 14px; }
.hint { color: var(--ink-4); font-size: 11.5px; line-height: 1.45; }
.response-head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.response-head span { font-size: 10.5px; }
pre { min-height: 340px; max-height: 600px; overflow: auto; margin: 16px 0 0; padding: 16px; border-radius: 14px; background: #111827; color: #d6e4ff; font: 12px/1.65 var(--font-mono); white-space: pre-wrap; word-break: break-word; }
@media (max-width: 960px) { .console-grid { grid-template-columns: 1fr; } }
@media (max-width: 620px) { .request-line { grid-template-columns: 92px 1fr; } .request-line .btn { grid-column: 1/-1; } .actions { align-items: flex-start; flex-direction: column; } }
</style>
