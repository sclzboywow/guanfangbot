<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, type Bot } from '@/services/api'
import AppIcon from '@/components/AppIcon.vue'

const route = useRoute()
const router = useRouter()
const bot = ref<Bot | null>(null)
const loading = ref(true)
const saving = ref(false)
const deleting = ref(false)
const error = ref('')
const name = ref('')
const description = ref('')
const appId = ref('')
const clientSecret = ref('')
const status = ref<Bot['status']>('created')
const copied = ref('')
const botId = computed(() => String(route.params.id))

async function load() {
  loading.value = true
  error.value = ''
  try {
    bot.value = await api.getBot(botId.value)
    name.value = bot.value.name
    description.value = bot.value.description
    appId.value = bot.value.app_id
    status.value = bot.value.status
    clientSecret.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!bot.value) return
  saving.value = true
  error.value = ''
  try {
    const payload: Parameters<typeof api.updateBot>[1] = {
      name: name.value.trim(),
      description: description.value.trim(),
      app_id: appId.value.trim(),
      status: status.value,
    }
    if (clientSecret.value.trim()) payload.client_secret = clientSecret.value.trim()
    bot.value = await api.updateBot(bot.value.id, payload)
    clientSecret.value = ''
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function removeBot() {
  if (!bot.value) return
  if (!confirm(`确认删除机器人「${bot.value.name}」？此操作不可恢复。`)) return
  deleting.value = true
  try {
    await api.deleteBot(bot.value.id)
    router.push('/bots')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除失败'
  } finally {
    deleting.value = false
  }
}

async function copy(text: string, label: string) {
  await navigator.clipboard.writeText(text)
  copied.value = label
  setTimeout(() => { copied.value = '' }, 1200)
}

onMounted(load)
</script>

<template>
  <section class="page manage-page">
    <button class="back" type="button" @click="router.push('/bots')">← 返回机器人列表</button>
    <div v-if="loading" class="card loading">正在加载…</div>
    <div v-else-if="error && !bot" class="card loading error">{{ error }}</div>
    <template v-else-if="bot">
      <div class="page-head manage-head">
        <div class="title-line">
          <div class="title-avatar">BOT</div>
          <div>
            <h1 class="page-title">{{ bot.name }}</h1>
            <p class="page-sub mono">AppID {{ bot.app_id || '—' }}</p>
          </div>
          <span class="status-pill" :class="bot.status">{{ bot.status === 'online' ? '在线' : bot.status === 'created' ? '待接入' : '离线' }}</span>
        </div>
        <div class="page-actions">
          <button class="btn danger" type="button" :disabled="deleting" @click="removeBot">{{ deleting ? '删除中…' : '删除' }}</button>
          <button class="btn primary" type="button" :disabled="saving" @click="save">{{ saving ? '保存中…' : '保存修改' }}</button>
        </div>
      </div>

      <div class="manage-layout">
        <aside class="manage-nav card">
          <a href="#basic">基本信息</a>
          <a href="#credentials">开发凭证</a>
          <a href="#events">事件订阅</a>
          <a href="#security">安全说明</a>
        </aside>
        <div class="manage-body">
          <section id="basic" class="section-card card">
            <div class="section-head"><div><h2 class="section-title">基本信息</h2><p class="section-sub">名称、介绍与状态会保存在服务端，可供所有使用者在前台维护。</p></div></div>
            <div class="form-grid">
              <div class="field"><label>机器人名称</label><input v-model="name" class="input" maxlength="32" /></div>
              <div class="field">
                <label>状态</label>
                <select v-model="status" class="select">
                  <option value="created">待接入</option>
                  <option value="online">在线</option>
                  <option value="offline">离线</option>
                </select>
              </div>
              <div class="field full"><label>机器人介绍</label><textarea v-model="description" class="textarea normal" maxlength="120"></textarea></div>
            </div>
          </section>

          <section id="credentials" class="section-card card">
            <div class="section-head">
              <div>
                <h2 class="section-title">开发凭证</h2>
                <p class="section-sub">在前台填写并保存。AppSecret 仅服务端存储，接口只返回是否已配置。</p>
              </div>
              <span class="secure-tag">{{ bot.has_secret ? '已配置密钥' : '尚未配置密钥' }}</span>
            </div>
            <div class="form-grid">
              <div class="field"><label>AppID</label><input v-model="appId" class="input mono" placeholder="QQ 开放平台 AppID" /></div>
              <div class="field">
                <label>AppSecret</label>
                <input v-model="clientSecret" class="input mono" type="password" :placeholder="bot.has_secret ? '已保存，留空表示不修改' : '请输入 AppSecret'" />
              </div>
            </div>
            <div class="setting-row">
              <div><strong>当前 AppID</strong><span>可用于复制到开放平台或文档</span></div>
              <code>{{ bot.app_id || '—' }}</code>
              <button class="icon-btn" type="button" :disabled="!bot.app_id" @click="copy(bot.app_id, 'AppID')"><AppIcon name="copy" :size="15" /></button>
            </div>
            <div v-if="copied" class="toast">已复制 {{ copied }}</div>
          </section>

          <section id="events" class="section-card card">
            <div class="section-head">
              <div><h2 class="section-title">事件订阅</h2><p class="section-sub">回调地址与订阅范围可在事件页按机器人单独配置。</p></div>
              <RouterLink :to="`/events?bot=${bot.id}`" class="btn">打开配置</RouterLink>
            </div>
            <div class="event-summary">
              <span class="event-icon">↯</span>
              <div>
                <strong>{{ bot.event_scopes.length ? `已选 ${bot.event_scopes.length} 类事件` : '尚未选择事件订阅' }}</strong>
                <p>{{ bot.callback_url || 'https://bot.yzdoc.cn/api/events/callback' }}</p>
              </div>
            </div>
          </section>

          <section id="security" class="section-card card">
            <div class="section-head"><div><h2 class="section-title">安全说明</h2><p class="section-sub">开放给其他用户前建议完成登录鉴权与审计。</p></div></div>
            <label class="check-row"><input type="checkbox" checked disabled /><span><strong>密钥仅服务端保存</strong><small>前端不会收到 AppSecret 明文与 Access Token。</small></span></label>
            <label class="check-row"><input type="checkbox" /><span><strong>管理台登录鉴权</strong><small>当前尚未实现，正式对外开放前必须接入。</small></span></label>
            <label class="check-row"><input type="checkbox" checked disabled /><span><strong>配置持久化</strong><small>机器人配置写入服务端 data/bots.json，重启后保留。</small></span></label>
          </section>
          <p v-if="error" class="inline-error">{{ error }}</p>
        </div>
      </div>
    </template>
  </section>
</template>

<style scoped>
.manage-page { max-width: 1120px; }
.back { margin: 0 0 20px; padding: 0; border: 0; background: transparent; color: var(--ink-3); font-size: 13px; }
.back:hover { color: var(--accent); }
.manage-head { align-items: center; }
.title-line { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.title-avatar { width: 42px; height: 42px; display: grid; place-items: center; border-radius: 50%; background: linear-gradient(135deg,#c2e6ff,#0099ff); color: white; font-size: 11px; font-weight: 850; }
.manage-layout { display: grid; grid-template-columns: 220px minmax(0,1fr); gap: 22px; align-items: start; }
.manage-nav { position: sticky; top: 24px; display: flex; flex-direction: column; gap: 4px; padding: 9px; }
.manage-nav a { padding: 12px 13px; border-radius: 12px; color: var(--ink-2); font-weight: 650; }
.manage-nav a:hover { background: var(--accent-soft); color: var(--accent); }
.manage-body { display: flex; flex-direction: column; gap: 18px; }
.section-card { position: relative; padding: 24px; scroll-margin-top: 20px; }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 20px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.field.full { grid-column: 1 / -1; }
.textarea.normal { font-family: var(--font-sans); min-height: 100px; }
.setting-row { display: grid; grid-template-columns: minmax(170px,1fr) minmax(180px,1fr) auto; gap: 12px; align-items: center; padding: 15px 0; border-top: 1px solid var(--line); margin-top: 8px; }
.setting-row strong, .setting-row span { display: block; }
.setting-row span { margin-top: 3px; color: var(--ink-4); font-size: 11.5px; }
.setting-row code { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; padding: 9px 11px; border-radius: 9px; background: var(--bg-sunken); color: var(--ink-2); }
.icon-btn { width: 34px; height: 34px; display: grid; place-items: center; border: 1px solid var(--line); border-radius: 9px; background: white; color: var(--ink-3); }
.icon-btn:hover { color: var(--accent); border-color: var(--accent-border); }
.secure-tag { padding: 5px 9px; border-radius: 999px; background: rgba(52,199,89,.1); color: #238541; font-size: 11px; font-weight: 700; white-space: nowrap; }
.event-summary { display: flex; align-items: flex-start; gap: 13px; padding: 16px; border: 1px solid var(--accent-border); border-radius: 15px; background: var(--accent-soft); }
.event-summary p { margin: 5px 0 0; color: var(--ink-3); font-size: 12.5px; line-height: 1.55; word-break: break-all; }
.event-icon { font-size: 22px; color: var(--accent); }
.check-row { display: flex; gap: 12px; padding: 14px 0; border-top: 1px solid var(--line); }
.check-row input { width: 17px; height: 17px; accent-color: var(--accent); }
.check-row strong, .check-row small { display: block; }
.check-row small { margin-top: 4px; color: var(--ink-4); line-height: 1.45; }
.toast { position: absolute; top: 18px; right: 18px; padding: 8px 12px; border-radius: 10px; background: rgba(29,29,31,.9); color: white; font-size: 12px; }
.loading { padding: 48px; text-align: center; }
.error, .inline-error { color: var(--danger); }
.btn.danger { background: rgba(255,59,48,.1); color: var(--danger); }
@media (max-width: 900px) { .manage-layout { grid-template-columns: 1fr; } .manage-nav { position: static; flex-direction: row; overflow-x: auto; } }
@media (max-width: 620px) { .form-grid { grid-template-columns: 1fr; } .setting-row { grid-template-columns: 1fr auto; } .setting-row > div { grid-column: 1/-1; } }
</style>
