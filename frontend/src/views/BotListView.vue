<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '@/services/api'
import { useBotsStore } from '@/stores/bots'
import AppIcon from '@/components/AppIcon.vue'

const store = useBotsStore()
const router = useRouter()
const showCreate = ref(false)
const creating = ref(false)
const createError = ref('')
const form = ref({
  name: '',
  description: '',
  app_id: '',
  client_secret: '',
})

const gradients = [
  ['#ffd6a3', '#ff8a4d'], ['#c2e6ff', '#0099ff'], ['#ffd1e0', '#ff5b8a'],
  ['#d3f2dc', '#34c759'], ['#e6dcff', '#7d5cff'], ['#ffe8b5', '#f3a712'],
]
const onlineCount = computed(() => store.bots.filter(bot => bot.status === 'online').length)
const configuredCount = computed(() => store.bots.filter(bot => bot.has_secret && bot.app_id).length)

function avatarStyle(seed: number) {
  const pair = gradients[seed % gradients.length]
  return { background: `linear-gradient(135deg, ${pair[0]}, ${pair[1]})` }
}

function openCreate() {
  createError.value = ''
  form.value = { name: '', description: '', app_id: '', client_secret: '' }
  showCreate.value = true
}

async function createBot() {
  creating.value = true
  createError.value = ''
  try {
    const bot = await api.createBot({
      name: form.value.name.trim(),
      description: form.value.description.trim(),
      app_id: form.value.app_id.trim(),
      client_secret: form.value.client_secret.trim(),
      status: 'created',
      callback_url: 'https://bot.yzdoc.cn/api/events/callback',
    })
    showCreate.value = false
    await store.load()
    router.push(`/bots/${bot.id}`)
  } catch (e) {
    createError.value = e instanceof Error ? e.message : '创建失败'
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
        <p class="page-sub">在前台创建并管理机器人配置、凭证、事件订阅与 OpenAPI 调用。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate"><AppIcon name="plus" :size="16" />创建机器人</button>
      </div>
    </div>

    <div class="meta-row">
      <span class="meta-pill"><b>{{ store.bots.length }}</b> 个机器人</span>
      <span class="meta-pill online"><b>{{ onlineCount }}</b> 个在线</span>
      <span class="meta-pill"><b>{{ configuredCount }}</b> 已配置凭证</span>
      <span class="limit-hint"><i></i> AppSecret 仅保存在服务端，接口不会回传明文</span>
    </div>

    <div v-if="store.loading" class="state-card">正在加载机器人…</div>
    <div v-else-if="store.error" class="state-card error">{{ store.error }}</div>
    <div v-else class="bots-grid">
      <article v-for="bot in store.bots" :key="bot.id" class="bot-card" @click="router.push(`/bots/${bot.id}`)">
        <div class="bot-head">
          <div class="bot-avatar" :style="avatarStyle(bot.avatar_seed)">
            <svg viewBox="0 0 48 48" fill="none"><rect x="8" y="13" width="32" height="26" rx="10" fill="rgba(255,255,255,.93)"/><circle cx="18" cy="25" r="2.3" fill="currentColor"/><circle cx="30" cy="25" r="2.3" fill="currentColor"/><path d="M17 32c4.5 3 9.5 3 14 0" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/><path d="M24 8v5" stroke="rgba(255,255,255,.93)" stroke-width="3" stroke-linecap="round"/></svg>
          </div>
          <div class="bot-info">
            <div class="bot-name-row">
              <span class="bot-name">{{ bot.name }}</span>
              <span class="role-tag">{{ bot.has_secret ? '已配置' : '缺凭证' }}</span>
            </div>
            <div class="bot-status">
              <span class="status-dot" :class="bot.status"></span>
              {{ bot.status === 'online' ? '在线' : bot.status === 'created' ? '待接入' : '离线（服务不可用）' }}
            </div>
          </div>
          <AppIcon name="arrow" class="arrow" :size="16" />
        </div>
        <div class="bot-foot"><span class="mono">AppID {{ bot.app_id || '—' }}</span><span>{{ bot.updated_at }}</span></div>
      </article>
    </div>

    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal card">
        <div class="modal-head">
          <div>
            <h2 class="section-title">创建机器人</h2>
            <p class="section-sub">配置将保存在服务端，可随时在前台修改。</p>
          </div>
          <button class="icon-close" type="button" @click="showCreate = false">×</button>
        </div>
        <div class="form-grid">
          <div class="field"><label>机器人名称</label><input v-model="form.name" class="input" maxlength="32" placeholder="例如：客服助手" /></div>
          <div class="field"><label>AppID</label><input v-model="form.app_id" class="input mono" placeholder="QQ 开放平台 AppID" /></div>
          <div class="field full"><label>AppSecret</label><input v-model="form.client_secret" class="input mono" type="password" placeholder="仅服务端保存，不会再次展示明文" /></div>
          <div class="field full"><label>机器人介绍</label><textarea v-model="form.description" class="textarea normal" maxlength="120" placeholder="可选"></textarea></div>
        </div>
        <p v-if="createError" class="inline-error">{{ createError }}</p>
        <div class="modal-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" type="button" :disabled="creating || !form.name.trim() || !form.app_id.trim() || !form.client_secret.trim()" @click="createBot">
            {{ creating ? '创建中…' : '创建并进入配置' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.meta-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
.meta-pill { display: inline-flex; gap: 5px; padding: 6px 10px; border-radius: 999px; background: rgba(60,60,67,.06); color: var(--ink-3); font-size: 12px; }
.meta-pill b { color: var(--ink); }
.meta-pill.online { background: rgba(52,199,89,.10); color: #238541; }
.limit-hint { display: inline-flex; align-items: center; gap: 7px; margin-left: auto; color: var(--warn); font-size: 12.5px; }
.limit-hint i { width: 6px; height: 6px; border-radius: 50%; background: var(--warn); box-shadow: 0 0 0 3px rgba(255,149,0,.16); }
.bots-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 16px; }
.bot-card { position: relative; overflow: hidden; padding: 18px; background: white; border: 1px solid transparent; border-radius: var(--radius); box-shadow: var(--shadow-sm); cursor: pointer; transition: .18s ease; }
.bot-card::after { content: ""; position: absolute; inset: 0; background: radial-gradient(120% 120% at 100% 0%,rgba(0,153,255,.06),transparent 60%); pointer-events: none; }
.bot-card:hover { transform: translateY(-2px); border-color: var(--line); box-shadow: var(--shadow); }
.bot-head { position: relative; z-index: 1; display: flex; align-items: center; gap: 12px; }
.bot-avatar { width: 52px; height: 52px; display: grid; place-items: center; flex: none; overflow: hidden; border-radius: 50%; color: #0099ff; box-shadow: 0 2px 6px rgba(0,0,0,.08); }
.bot-avatar svg { width: 46px; height: 46px; }
.bot-info { flex: 1; min-width: 0; }
.bot-name-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.bot-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 15px; font-weight: 650; }
.role-tag { flex: none; display: inline-flex; align-items: center; height: 20px; padding: 0 8px; border-radius: 999px; background: var(--accent-soft); color: var(--accent); font-size: 11px; font-weight: 700; }
.bot-status { display: flex; align-items: center; gap: 5px; margin-top: 3px; color: var(--ink-3); font-size: 12px; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--ink-4); }
.status-dot.online { background: var(--online); }
.status-dot.created { background: var(--warn); }
.arrow { color: var(--ink-4); transition: .15s ease; }
.bot-card:hover .arrow { color: var(--accent); transform: translateX(2px); }
.bot-foot { position: relative; z-index: 1; display: flex; justify-content: space-between; gap: 12px; margin-top: 16px; padding-top: 12px; border-top: 1px solid rgba(60,60,67,.08); color: var(--ink-4); font-size: 11.5px; }
.modal-mask { position: fixed; inset: 0; z-index: 80; display: grid; place-items: center; padding: 20px; background: rgba(20,20,24,.42); backdrop-filter: blur(4px); }
.modal { width: min(560px, 100%); padding: 22px; }
.modal-head { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 18px; }
.icon-close { width: 34px; height: 34px; border: 0; border-radius: 10px; background: var(--bg-sunken); color: var(--ink-3); font-size: 22px; line-height: 1; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.field.full { grid-column: 1 / -1; }
.textarea.normal { font-family: var(--font-sans); min-height: 88px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 18px; }
.inline-error, .error { color: var(--danger); }
@media (max-width: 620px) { .form-grid { grid-template-columns: 1fr; } .limit-hint { margin-left: 0; } }
</style>
