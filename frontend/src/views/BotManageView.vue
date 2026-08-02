<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type Bot, type BotEvent, type CredentialStatus } from '@/services/api'

const route = useRoute()
const router = useRouter()
const bot = ref<Bot | null>(null)
const credential = ref<CredentialStatus | null>(null)
const events = ref<BotEvent[]>([])
const appId = ref('')
const key = ref('')
const callbackUrl = ref('')
const loading = ref(true)
const busy = ref(false)
const message = ref('')
const error = ref('')
const id = computed(() => String(route.params.id))
const suggestedCallback = computed(() => appId.value.trim()
  ? `${window.location.origin}/api/events/callback/${encodeURIComponent(appId.value.trim())}` : '')

async function load() {
  loading.value = true
  error.value = ''
  try {
    bot.value = await api.getBot(id.value)
    appId.value = bot.value.app_id
    callbackUrl.value = bot.value.callback_url
    key.value = ''
    ;[credential.value, events.value] = await Promise.all([
      api.credentialStatus(id.value), api.recentEvents(id.value),
    ])
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally { loading.value = false }
}

async function save() {
  if (!bot.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    const payload: Parameters<typeof api.updateBot>[1] = {
      app_id: appId.value.trim(), callback_url: callbackUrl.value.trim(),
    }
    if (key.value.trim()) payload.client_secret = key.value.trim()
    bot.value = await api.updateBot(bot.value.id, payload)
    key.value = ''
    credential.value = await api.credentialStatus(bot.value.id)
    message.value = '接入配置已保存'
  } catch (e) { error.value = e instanceof Error ? e.message : '保存失败' }
  finally { busy.value = false }
}

async function syncProfile() {
  if (!bot.value) return
  busy.value = true; error.value = ''; message.value = ''
  try {
    bot.value = await api.syncBotProfile(bot.value.id)
    message.value = '已同步机器人名称'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '同步失败'
  } finally {
    busy.value = false
  }
}

async function removeBot() {
  if (!bot.value || !confirm(`确认删除 AppID ${bot.value.app_id}？`)) return
  await api.deleteBot(bot.value.id)
  router.push('/bots')
}

async function copy(text: string) {
  await navigator.clipboard.writeText(text)
  message.value = '已复制'
}

onMounted(load)
</script>

<template>
  <section class="page manage-page">
    <button class="back" @click="router.push('/bots')">← 返回机器人列表</button>
    <div v-if="loading" class="card state">正在加载…</div>
    <div v-else-if="!bot" class="card state error">{{ error || '机器人不存在' }}</div>
    <template v-else>
      <div class="page-head">
        <div><h1 class="page-title">{{ bot.name }}</h1><p class="page-sub mono">AppID {{ bot.app_id }}</p></div>
        <div class="page-actions">
          <button class="btn" type="button" :disabled="busy" @click="syncProfile">同步名称</button>
          <span class="status-pill" :class="credential?.configured ? 'online' : 'warn'">{{ credential?.configured ? (credential.token_cached ? 'Token 已缓存' : '凭证已配置') : '待配置' }}</span>
        </div>
      </div>

      <div class="layout">
        <section class="card panel">
          <h2 class="section-title">接入配置</h2>
          <p class="section-sub">这里只维护 AppID、AppSecret / Key 与回调地址。</p>
          <div class="fields">
            <div class="field"><label>AppID</label><input v-model="appId" class="input mono" /></div>
            <div class="field"><label>AppSecret / Key</label><input v-model="key" class="input mono" type="password" :placeholder="bot.has_secret ? '已保存，留空不修改' : '请输入 Key'" /></div>
            <div class="field"><label>回调地址</label><div class="input-row"><input v-model="callbackUrl" class="input mono" /><button class="btn" @click="copy(callbackUrl)">复制</button></div><small>推荐：{{ suggestedCallback }}。须与上方 AppID 一致，且 AppSecret 已保存后，再到开放平台校验。</small></div>
          </div>
          <div class="actions"><button class="btn" @click="callbackUrl = suggestedCallback">使用推荐地址</button><button class="btn primary" :disabled="busy || !appId.trim() || !callbackUrl.trim()" @click="save">{{ busy ? '处理中…' : '保存配置' }}</button></div>
        </section>

        <aside class="side">
          <section class="card panel">
            <h2 class="section-title">开发状态</h2>
            <div class="kv"><span>凭证</span><b>{{ credential?.configured ? '可用' : '未配置' }}</b></div>
            <div class="kv"><span>Token</span><b>{{ credential?.token_cached ? '已缓存' : '按需获取' }}</b></div>
            <div class="kv"><span>最近事件</span><b>{{ events.length }}</b></div>
            <p class="token-note">Access Token 由后端在调用 OpenAPI 时自动获取、缓存并在到期后重新申请，无需手动刷新。</p>
          </section>
          <section class="card panel tools">
            <h2 class="section-title">开发工具</h2>
            <RouterLink :to="`/events?bot=${bot.id}`">事件与回调 <b>→</b></RouterLink>
            <RouterLink :to="`/group-verification?bot=${bot.id}`">入群验证 <b>→</b></RouterLink>
            <RouterLink :to="`/api-console?bot=${bot.id}`">OpenAPI 调试 <b>→</b></RouterLink>
            <a href="https://bot.q.qq.com/wiki/develop/api-v2/" target="_blank" rel="noopener noreferrer">官方文档 <b>↗</b></a>
          </section>
        </aside>
      </div>

      <section class="card danger-zone"><div><strong>删除本地配置</strong><span>不会删除 QQ 开放平台中的机器人。</span></div><button class="btn danger" @click="removeBot">删除</button></section>
      <p v-if="message" class="notice ok">{{ message }}</p><p v-if="error" class="notice error">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.manage-page{max-width:1080px}.back{margin:0 0 18px;padding:0;border:0;background:none;color:var(--ink-3)}.state{padding:40px;text-align:center}.layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:18px;align-items:start}.panel{padding:22px}.fields{display:flex;flex-direction:column;gap:15px;margin-top:20px}.input-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px}.field small{color:var(--ink-4);word-break:break-all}.actions{display:flex;justify-content:flex-end;gap:10px;margin-top:20px}.side{display:flex;flex-direction:column;gap:18px}.kv{display:flex;justify-content:space-between;padding:13px 0;border-bottom:1px solid var(--line);color:var(--ink-3)}.kv b{color:var(--ink)}.token-note{margin:14px 0 0;padding:12px;border-radius:11px;background:var(--bg-sunken);color:var(--ink-4);font-size:11.5px;line-height:1.55}.tools{display:flex;flex-direction:column;gap:8px}.tools h2{margin-bottom:6px}.tools a{display:flex;justify-content:space-between;padding:12px;border-radius:11px;background:var(--bg-sunken);font-weight:650}.tools a:hover{background:var(--accent-soft);color:var(--accent)}.danger-zone{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-top:18px;padding:18px 22px}.danger-zone strong,.danger-zone span{display:block}.danger-zone span{margin-top:4px;color:var(--ink-4);font-size:12px}.notice{margin-top:12px}.ok{color:#238541}.error{color:var(--danger)}@media(max-width:840px){.layout{grid-template-columns:1fr}.side{display:grid;grid-template-columns:1fr 1fr}}@media(max-width:620px){.side{display:flex}.danger-zone{align-items:flex-start;flex-direction:column}}
</style>
