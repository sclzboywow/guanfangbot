<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/services/api'
import { useBotsStore } from '@/stores/bots'
import AppIcon from '@/components/AppIcon.vue'

const store = useBotsStore()
const router = useRouter()
const showCreate = ref(false)
const creating = ref(false)
const error = ref('')
const appId = ref('')
const key = ref('')
const callbackUrl = ref('')
const suggestedCallback = computed(() => appId.value.trim()
  ? `${window.location.origin}/api/events/callback/${encodeURIComponent(appId.value.trim())}`
  : `${window.location.origin}/api/events/callback/{AppID}`)

watch(appId, () => {
  if (!callbackUrl.value || callbackUrl.value.includes('/api/events/callback/')) {
    callbackUrl.value = suggestedCallback.value
  }
})

function openCreate() {
  appId.value = ''
  key.value = ''
  callbackUrl.value = `${window.location.origin}/api/events/callback/{AppID}`
  error.value = ''
  showCreate.value = true
}

async function createBot() {
  creating.value = true
  error.value = ''
  try {
    const bot = await api.createBot({
      app_id: appId.value.trim(),
      client_secret: key.value.trim(),
      callback_url: callbackUrl.value.trim(),
    })
    showCreate.value = false
    await store.load()
    router.push(`/bots/${bot.id}`)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建失败'
  } finally {
    creating.value = false
  }
}

onMounted(() => store.load())
</script>

<template>
  <section class="page">
    <div class="page-head">
      <div>
        <h1 class="page-title">我的机器人</h1>
        <p class="page-sub">这里只管理机器人接入配置；事件、Token 与 OpenAPI 调试在开发工具中完成。</p>
      </div>
      <button class="btn primary" type="button" @click="openCreate"><AppIcon name="plus" :size="16" />新增机器人</button>
    </div>

    <div v-if="store.loading" class="card state">正在加载…</div>
    <div v-else-if="store.error" class="card state error">{{ store.error }}</div>
    <div v-else-if="!store.bots.length" class="card empty">
      <strong>还没有机器人</strong>
      <span>新增时只需填写 AppID、AppSecret / Key 和回调地址。</span>
      <button class="btn primary" type="button" @click="openCreate">新增第一个机器人</button>
    </div>
    <div v-else class="bots-grid">
      <article v-for="bot in store.bots" :key="bot.id" class="bot-card" @click="router.push(`/bots/${bot.id}`)">
        <div class="avatar" :style="bot.avatar_url ? { backgroundImage: `url(${bot.avatar_url})`, backgroundSize: 'cover' } : undefined">
          <span v-if="!bot.avatar_url">BOT</span>
        </div>
        <div class="bot-main">
          <div class="name-row"><strong>{{ bot.name }}</strong><span>{{ bot.has_secret ? '已接入' : '缺少 Key' }}</span></div>
          <p class="mono">AppID {{ bot.app_id }}</p>
          <small>{{ bot.callback_url }}</small>
        </div>
        <AppIcon name="arrow" :size="16" />
      </article>
    </div>

    <div v-if="showCreate" class="mask" @click.self="showCreate = false">
      <form class="card modal" @submit.prevent="createBot">
        <div class="modal-head"><div><h2>新增机器人</h2><p>填写开放平台中的三项接入信息。</p></div><button type="button" @click="showCreate = false">×</button></div>
        <div class="field"><label>AppID</label><input v-model="appId" class="input mono" autocomplete="off" /></div>
        <div class="field"><label>AppSecret / Key</label><input v-model="key" class="input mono" type="password" autocomplete="new-password" /></div>
        <div class="field"><label>回调地址</label><input v-model="callbackUrl" class="input mono" autocomplete="off" /><small>推荐：{{ suggestedCallback }}</small></div>
        <p v-if="error" class="error">{{ error }}</p>
        <div class="actions"><button class="btn" type="button" @click="showCreate = false">取消</button><button class="btn primary" :disabled="creating || !appId.trim() || !key.trim() || !callbackUrl.trim()">{{ creating ? '保存中…' : '保存并进入开发' }}</button></div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.state,.empty{padding:32px}.empty{min-height:280px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;text-align:center}.empty span{color:var(--ink-4)}
.bots-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:16px}.bot-card{display:flex;align-items:center;gap:13px;padding:18px;border:1px solid transparent;border-radius:var(--radius);background:#fff;box-shadow:var(--shadow-sm);cursor:pointer;transition:.16s}.bot-card:hover{transform:translateY(-2px);border-color:var(--line);box-shadow:var(--shadow)}.avatar{width:48px;height:48px;display:grid;place-items:center;flex:none;border-radius:50%;background:linear-gradient(135deg,#c2e6ff,#0099ff);color:#fff;font-size:11px;font-weight:800}.bot-main{flex:1;min-width:0}.name-row{display:flex;align-items:center;gap:8px}.name-row strong{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.name-row span{padding:3px 8px;border-radius:999px;background:var(--accent-soft);color:var(--accent);font-size:10.5px;font-weight:700}.bot-main p,.bot-main small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.bot-main p{margin:5px 0 0;color:var(--ink-3);font-size:11.5px}.bot-main small{display:block;margin-top:5px;color:var(--ink-4)}
.mask{position:fixed;inset:0;z-index:90;display:grid;place-items:center;padding:20px;background:rgba(20,20,24,.42);backdrop-filter:blur(4px)}.modal{width:min(520px,100%);padding:22px;display:flex;flex-direction:column;gap:15px}.modal-head{display:flex;justify-content:space-between;gap:16px}.modal-head h2{margin:0}.modal-head p{margin:6px 0 0;color:var(--ink-4)}.modal-head button{width:34px;height:34px;border:0;border-radius:10px;background:var(--bg-sunken);font-size:22px}.field small{color:var(--ink-4);word-break:break-all}.actions{display:flex;justify-content:flex-end;gap:10px}.error{color:var(--danger)}
</style>
