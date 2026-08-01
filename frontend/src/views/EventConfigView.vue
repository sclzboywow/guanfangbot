<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  api,
  type Bot,
  type BotEvent,
  type EventStatusGroup,
  type EventStatusResponse,
} from '@/services/api'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const callbackUrl = ref('')
const groups = ref<EventStatusGroup[]>([])
const status = ref<EventStatusResponse | null>(null)
const events = ref<BotEvent[]>([])
const search = ref('')
const saving = ref(false)
const detecting = ref(false)
const message = ref('')
const error = ref('')

const currentBot = computed(() => bots.value.find(item => item.id === botId.value) || null)
const totalCount = computed(() => groups.value.reduce((sum, group) => sum + group.events.length, 0))
const selectedCount = computed(() => groups.value.reduce(
  (sum, group) => sum + group.events.filter(event => event.selected).length,
  0,
))
const observedCount = computed(() => groups.value.reduce(
  (sum, group) => sum + group.events.filter(event => event.observed).length,
  0,
))
const filteredGroups = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return groups.value
  return groups.value
    .map(group => ({
      ...group,
      events: group.events.filter(event =>
        event.code.toLowerCase().includes(keyword)
        || event.label.toLowerCase().includes(keyword)
        || event.description.toLowerCase().includes(keyword),
      ),
    }))
    .filter(group => group.events.length > 0)
})

function permissionText(permission: string) {
  if (permission === 'basic') return '基础事件'
  if (permission === 'special') return '需平台权限'
  return '以管理端为准'
}

function isGroupSelected(group: EventStatusGroup) {
  return group.events.length > 0 && group.events.every(event => event.selected)
}

function toggleGroup(group: EventStatusGroup) {
  const next = !isGroupSelected(group)
  group.events.forEach(event => { event.selected = next })
}

function formatTime(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

async function loadDetection() {
  if (!botId.value) return
  const result = await api.eventStatus(botId.value)
  status.value = result
  callbackUrl.value = result.callback_url
  groups.value = result.groups
}

async function loadEvents() {
  events.value = botId.value ? await api.recentEvents(botId.value) : []
}

async function refreshDetection(showMessage = true) {
  if (!botId.value) return
  detecting.value = true
  error.value = ''
  try {
    await Promise.all([loadDetection(), loadEvents()])
    if (showMessage) message.value = '接入状态已更新'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '检测失败'
  } finally {
    detecting.value = false
  }
}

async function save() {
  if (!botId.value) return
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    const selectedEvents = groups.value.flatMap(group =>
      group.events.filter(event => event.selected).map(event => event.code),
    )
    const updated = await api.updateBot(botId.value, {
      callback_url: callbackUrl.value.trim(),
      event_scopes: selectedEvents,
    })
    const index = bots.value.findIndex(item => item.id === updated.id)
    if (index >= 0) bots.value[index] = updated
    await loadDetection()
    message.value = '事件清单已保存。请在 QQ 管理端勾选相同事件。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

watch(botId, async () => {
  message.value = ''
  error.value = ''
  await refreshDetection(false)
})

onMounted(async () => {
  try {
    bots.value = await api.listBots()
    const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
    botId.value = bots.value.some(item => item.id === preferred) ? preferred : (bots.value[0]?.id || '')
    if (botId.value) await refreshDetection(false)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
})
</script>

<template>
  <section class="page events-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">事件与回调</h1>
        <p class="page-sub">完整维护 QQ 管理端事件清单，并记录回调验证和真实事件接收状态。</p>
      </div>
      <div class="page-actions">
        <button class="btn" :disabled="detecting || !botId" @click="refreshDetection">
          {{ detecting ? '检测中…' : '刷新检测' }}
        </button>
        <button class="btn primary" :disabled="saving || !botId" @click="save">
          {{ saving ? '保存中…' : '保存配置' }}
        </button>
      </div>
    </div>

    <div v-if="!bots.length" class="card empty">暂无机器人，请先新增机器人。</div>
    <template v-else>
      <div class="field selector">
        <label>当前机器人</label>
        <select v-model="botId" class="select">
          <option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }} · {{ bot.app_id }}</option>
        </select>
      </div>

      <div class="summary-grid">
        <section class="card summary-card">
          <span>回调验证</span>
          <strong :class="status?.callback_verified ? 'good' : 'warn'">
            {{ status?.callback_verified ? 'QQ 已验证' : '等待 QQ 验证' }}
          </strong>
          <small>{{ status?.callback_verified_at ? formatTime(status.callback_verified_at) : '在 QQ 管理端保存回调地址后触发验证' }}</small>
        </section>
        <section class="card summary-card">
          <span>本地事件清单</span>
          <strong>{{ selectedCount }} / {{ totalCount || 43 }}</strong>
          <small>用于与 QQ 管理端勾选项进行人工核对</small>
        </section>
        <section class="card summary-card">
          <span>已真实收到</span>
          <strong class="good">{{ observedCount }}</strong>
          <small>只有事件真实到达后才会标记，状态会持久化</small>
        </section>
      </div>

      <div class="truth-notice">
        <strong>检测边界</strong>
        <span>{{ status?.detection_note || 'QQ Webhook 没有公开接口查询管理端已勾选事件。' }}</span>
        <a href="https://q.qq.com/" target="_blank" rel="noopener noreferrer">打开 QQ 管理端核对 ↗</a>
      </div>

      <div class="grid">
        <div class="main">
          <section class="card panel">
            <div class="section-head">
              <div>
                <h2 class="section-title">回调地址</h2>
                <p class="section-sub">多机器人使用带 AppID 的独立路径，避免凭证和事件串用。</p>
              </div>
              <span class="status-badge" :class="status?.callback_verified ? 'observed' : 'pending'">
                {{ status?.callback_verified ? '已验证' : '未验证' }}
              </span>
            </div>
            <div class="field top"><input v-model="callbackUrl" class="input mono" /></div>
            <code class="path">POST /api/events/callback/{{ currentBot?.app_id }}</code>
          </section>

          <section class="card panel catalog-panel">
            <div class="catalog-head">
              <div>
                <h2 class="section-title">完整事件清单</h2>
                <p class="section-sub">共 {{ totalCount || 43 }} 项。勾选结果保存在本平台，不会自动修改 QQ 管理端。</p>
              </div>
              <input v-model="search" class="input search" placeholder="搜索事件名称或代码" />
            </div>

            <div v-for="group in filteredGroups" :key="group.key" class="event-group">
              <div class="group-head">
                <div>
                  <h3>{{ group.label }}</h3>
                  <span>{{ group.events.filter(event => event.selected).length }} / {{ group.events.length }} 已选择</span>
                </div>
                <button class="group-toggle" type="button" @click="toggleGroup(group)">
                  {{ isGroupSelected(group) ? '取消本组' : '选择本组' }}
                </button>
              </div>

              <div class="scope-grid">
                <label v-for="event in group.events" :key="event.code" class="scope" :class="{ active: event.selected, received: event.observed }">
                  <input v-model="event.selected" type="checkbox" />
                  <span class="scope-content">
                    <span class="scope-title">
                      <strong>{{ event.label }}</strong>
                      <span v-if="event.observed" class="status-badge observed">已收到</span>
                      <span v-else-if="event.selected" class="status-badge selected">已记录</span>
                      <span v-else class="status-badge idle">未选择</span>
                    </span>
                    <small class="description">{{ event.description }}</small>
                    <span class="meta-line">
                      <code>{{ event.code }}</code>
                      <em :class="`permission-${event.permission}`">{{ permissionText(event.permission) }}</em>
                    </span>
                    <small v-if="event.last_received_at" class="last-time">最后收到：{{ formatTime(event.last_received_at) }}</small>
                  </span>
                </label>
              </div>
            </div>

            <div v-if="!filteredGroups.length" class="empty-events">没有匹配的事件。</div>
          </section>
        </div>

        <aside class="card panel recent">
          <div class="recent-head">
            <div><h2 class="section-title">最近回调</h2><p class="section-sub">当前进程最近 100 条</p></div>
            <button class="btn" :disabled="detecting" @click="refreshDetection">刷新</button>
          </div>
          <div v-if="!events.length" class="empty-events">尚未收到事件。</div>
          <div v-for="event in events" :key="event.id" class="event-row">
            <strong>{{ event.type }}</strong>
            <small>{{ formatTime(event.received_at) }}</small>
          </div>
        </aside>
      </div>

      <p v-if="message" class="ok">{{ message }}</p>
      <p v-if="error" class="error">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.events-page{max-width:1240px}.selector{max-width:480px;margin-bottom:18px}.empty{padding:30px}.summary-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:14px}.summary-card{padding:17px}.summary-card span,.summary-card strong,.summary-card small{display:block}.summary-card span{color:var(--ink-4);font-size:11.5px}.summary-card strong{margin-top:7px;font-size:19px}.summary-card small{margin-top:6px;color:var(--ink-4);font-size:11px;line-height:1.45}.good{color:#238541}.warn{color:var(--warn)}.truth-notice{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:18px;padding:13px 15px;border:1px solid rgba(255,149,0,.22);border-radius:13px;background:rgba(255,149,0,.07);font-size:12px;line-height:1.5}.truth-notice strong{color:var(--warn)}.truth-notice span{flex:1;min-width:240px;color:#815500}.truth-notice a{color:var(--accent);font-weight:650}.grid{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:18px;align-items:start}.main{display:flex;flex-direction:column;gap:18px}.panel{padding:22px}.section-head,.catalog-head,.recent-head,.group-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.top{margin-top:18px}.path{display:block;margin-top:10px;padding:10px 12px;border-radius:10px;background:var(--bg-sunken);color:var(--ink-3);word-break:break-all}.catalog-panel{padding-bottom:26px}.search{width:min(300px,100%)}.event-group{margin-top:22px}.event-group+.event-group{padding-top:22px;border-top:1px solid var(--line)}.group-head{align-items:center;margin-bottom:11px}.group-head h3{margin:0;font-size:15px}.group-head span{display:block;margin-top:4px;color:var(--ink-4);font-size:11px}.group-toggle{padding:6px 9px;border:1px solid var(--line);border-radius:9px;background:white;color:var(--accent);font-size:11px}.scope-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}.scope{display:flex;gap:10px;min-width:0;padding:13px;border:1px solid var(--line);border-radius:13px;cursor:pointer;transition:.15s ease}.scope:hover{border-color:var(--accent-border)}.scope.active{border-color:var(--accent-border);background:var(--accent-soft)}.scope.received{box-shadow:inset 3px 0 #34c759}.scope input{flex:none;margin-top:3px;accent-color:var(--accent)}.scope-content{min-width:0;flex:1}.scope-title{display:flex;align-items:flex-start;justify-content:space-between;gap:8px}.scope-title strong{font-size:12.5px;line-height:1.45}.description{display:block;margin-top:5px;color:var(--ink-4);font-size:11px;line-height:1.45}.meta-line{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-top:8px}.meta-line code{min-width:0;overflow:hidden;text-overflow:ellipsis;color:var(--ink-3);font-size:9.5px}.meta-line em{flex:none;padding:3px 6px;border-radius:999px;font-size:9px;font-style:normal}.permission-basic{background:rgba(52,199,89,.1);color:#238541}.permission-special{background:rgba(255,149,0,.11);color:#9b6500}.permission-platform{background:rgba(125,92,255,.1);color:#6846d6}.status-badge{flex:none;padding:4px 7px;border-radius:999px;font-size:9.5px;font-weight:700}.status-badge.observed{background:rgba(52,199,89,.12);color:#238541}.status-badge.selected{background:rgba(0,153,255,.11);color:var(--accent)}.status-badge.pending{background:rgba(255,149,0,.12);color:var(--warn)}.status-badge.idle{background:rgba(60,60,67,.07);color:var(--ink-4)}.last-time{display:block;margin-top:6px;color:#238541;font-size:9.5px}.recent{position:sticky;top:22px}.recent-head{align-items:center}.event-row{padding:12px 0;border-top:1px solid var(--line)}.event-row strong,.event-row small{display:block}.event-row strong{font-size:11.5px;word-break:break-all}.event-row small{margin-top:4px;color:var(--ink-4);font-size:10px}.empty-events{padding:28px 8px;text-align:center;color:var(--ink-4)}.ok{color:#238541}.error{color:var(--danger)}@media(max-width:980px){.grid{grid-template-columns:1fr}.recent{position:static}.summary-grid{grid-template-columns:1fr 1fr 1fr}}@media(max-width:720px){.summary-grid{grid-template-columns:1fr}.scope-grid{grid-template-columns:1fr}.catalog-head{flex-direction:column}.search{width:100%}}
</style>
