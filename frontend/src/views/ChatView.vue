<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type Bot } from '@/services/api'
import { chatApi, type ChatContact, type ChatMessage, type ChatStatus } from '@/services/chatApi'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const status = ref<ChatStatus | null>(null)
const selectedOpenid = ref('')
const messages = ref<ChatMessage[]>([])
const search = ref('')
const contactFilter = ref<'active' | 'all'>('active')
const draft = ref('')
const loading = ref(false)
const loadingMessages = ref(false)
const sending = ref(false)
const polling = ref(false)
const error = ref('')
const notice = ref('')
const messageList = ref<HTMLElement | null>(null)
let pollTimer: number | undefined

const currentBot = computed(() => bots.value.find(bot => bot.id === botId.value) || null)
const filteredContacts = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return (status.value?.contacts || []).filter((contact) => {
    if (contactFilter.value === 'active' && !contact.active) return false
    if (!keyword) return true
    return [contact.display_name, contact.user_openid, contact.last_message_preview]
      .some(value => String(value || '').toLowerCase().includes(keyword))
  })
})
const selectedContact = computed(() =>
  status.value?.contacts.find(contact => contact.user_openid === selectedOpenid.value) || null,
)

function shortOpenid(value: string) {
  if (!value) return '—'
  return value.length > 22 ? `${value.slice(0, 9)}…${value.slice(-7)}` : value
}

function contactName(contact: ChatContact) {
  return contact.display_name || `QQ 用户 ${shortOpenid(contact.user_openid)}`
}

function avatarText(contact: ChatContact) {
  const name = contact.display_name.trim()
  return name ? name.slice(0, 1).toUpperCase() : contact.user_openid.slice(0, 2).toUpperCase()
}

function formatTime(value?: string | null) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const today = new Date()
  if (date.toDateString() === today.toDateString()) {
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  }
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function scrollToBottom() {
  await nextTick()
  if (messageList.value) messageList.value.scrollTop = messageList.value.scrollHeight
}

async function loadStatus(preserveSelection = true) {
  if (!botId.value) return
  const result = await chatApi.status(botId.value)
  status.value = result
  if (preserveSelection && result.contacts.some(item => item.user_openid === selectedOpenid.value)) return
  selectedOpenid.value = result.contacts.find(item => item.active)?.user_openid || result.contacts[0]?.user_openid || ''
}

async function loadConversation(scroll = false) {
  if (!botId.value || !selectedOpenid.value) {
    messages.value = []
    return
  }
  loadingMessages.value = true
  try {
    const result = await chatApi.messages(botId.value, selectedOpenid.value)
    messages.value = result.messages
    if (status.value) {
      const index = status.value.contacts.findIndex(item => item.user_openid === result.contact.user_openid)
      if (index >= 0) status.value.contacts[index] = result.contact
    }
    if (scroll) await scrollToBottom()
  } finally {
    loadingMessages.value = false
  }
}

async function refresh(showNotice = true) {
  if (!botId.value) return
  loading.value = true
  error.value = ''
  try {
    await loadStatus(true)
    await loadConversation(false)
    if (showNotice) notice.value = '聊天状态已刷新'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载聊天状态失败'
  } finally {
    loading.value = false
  }
}

async function poll() {
  if (polling.value || loading.value || sending.value || !botId.value) return
  polling.value = true
  try {
    const oldLastId = messages.value.at(-1)?.id || 0
    await loadStatus(true)
    await loadConversation(false)
    if ((messages.value.at(-1)?.id || 0) !== oldLastId) await scrollToBottom()
  } catch {
    // 后台轮询失败不覆盖用户正在查看的错误信息。
  } finally {
    polling.value = false
  }
}

async function selectContact(contact: ChatContact) {
  selectedOpenid.value = contact.user_openid
}

async function renameSelectedContact() {
  if (!botId.value || !selectedContact.value) return
  const current = selectedContact.value.display_name || ''
  const next = window.prompt('设置联系人昵称（本地备注，QQ 单聊多数情况下不会下发昵称）', current)
  if (next === null) return
  const cleaned = next.trim()
  if (!cleaned) {
    error.value = '昵称不能为空'
    return
  }
  error.value = ''
  try {
    const result = await chatApi.renameContact(botId.value, selectedContact.value.user_openid, cleaned)
    if (status.value) {
      const index = status.value.contacts.findIndex(item => item.user_openid === result.contact.user_openid)
      if (index >= 0) status.value.contacts[index] = result.contact
    }
    notice.value = '昵称已更新'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '更新昵称失败'
  }
}

async function send() {
  const content = draft.value.trim()
  if (!content || !botId.value || !selectedOpenid.value || sending.value) return
  sending.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await chatApi.send(botId.value, selectedOpenid.value, content)
    messages.value.push(result.message)
    draft.value = ''
    notice.value = result.delivery_mode === 'passive'
      ? '已作为用户消息的被动回复发送'
      : result.delivery_mode === 'active_fallback'
        ? '回复凭证已过期，已改用主动消息发送'
        : '已作为主动消息发送'
    await loadStatus(true)
    await scrollToBottom()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '发送失败'
    await loadConversation(true).catch(() => undefined)
  } finally {
    sending.value = false
  }
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

watch(botId, async () => {
  status.value = null
  selectedOpenid.value = ''
  messages.value = []
  error.value = ''
  notice.value = ''
  if (!botId.value) return
  loading.value = true
  try {
    await loadStatus(false)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载聊天状态失败'
  } finally {
    loading.value = false
  }
})

watch(selectedOpenid, async (value, oldValue) => {
  if (!value || value === oldValue) return
  error.value = ''
  await loadConversation(true).catch((e) => {
    error.value = e instanceof Error ? e.message : '加载消息失败'
  })
})

onMounted(async () => {
  try {
    bots.value = await api.listBots()
    const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
    botId.value = bots.value.some(bot => bot.id === preferred) ? preferred : (bots.value[0]?.id || '')
    pollTimer = window.setInterval(() => void poll(), 4000)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '机器人列表加载失败'
  }
})

onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
})
</script>

<template>
  <section class="page chat-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">好友聊天</h1>
        <p class="page-sub">查看机器人实际接触过的单聊用户，并通过 QQ 官方单聊接口进行互动。</p>
      </div>
      <div class="page-actions">
        <button class="btn" :disabled="loading || !botId" @click="refresh()">{{ loading ? '刷新中…' : '刷新' }}</button>
      </div>
    </div>

    <div v-if="!bots.length" class="card empty">暂无机器人，请先新增机器人。</div>
    <template v-else>
      <div class="top-row">
        <div class="field bot-selector">
          <label>当前机器人</label>
          <select v-model="botId" class="select">
            <option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }} · {{ bot.app_id }}</option>
          </select>
        </div>
        <div class="summary">
          <span><b>{{ status?.counts.active || 0 }}</b> 有效好友</span>
          <span><b>{{ status?.counts.unread || 0 }}</b> 未读</span>
          <span><b>{{ status?.counts.messages || 0 }}</b> 本地消息</span>
        </div>
      </div>

      <div class="source-note">
        <strong>好友来源</strong>
        <span>{{ status?.source_note || '联系人会在收到 QQ 单聊或好友事件后出现。' }}</span>
      </div>

      <div v-if="status && !status.requirements_ready" class="requirements">
        <div>
          <strong>事件尚未完整配置</strong>
          <p>至少需要接收单聊与好友关系事件，网页才能持续建立联系人和聊天记录。</p>
        </div>
        <div class="event-tags">
          <span v-for="item in status.required_events" :key="item.code" :class="item.configured ? 'ready' : 'missing'">
            {{ item.code }} · {{ item.configured ? '已记录' : '未记录' }}
          </span>
        </div>
        <RouterLink :to="`/events?bot=${botId}`" class="btn">前往事件配置</RouterLink>
      </div>

      <div class="card chat-shell">
        <aside class="contacts-panel">
          <div class="contacts-head">
            <div><h2>联系人</h2><small>{{ filteredContacts.length }} / {{ status?.counts.total || 0 }}</small></div>
            <div class="filter-switch">
              <button :class="{ active: contactFilter === 'active' }" @click="contactFilter = 'active'">好友</button>
              <button :class="{ active: contactFilter === 'all' }" @click="contactFilter = 'all'">全部</button>
            </div>
          </div>
          <input v-model="search" class="input contact-search" placeholder="搜索昵称或 OpenID" />
          <div class="contact-list">
            <button
              v-for="contact in filteredContacts"
              :key="contact.user_openid"
              class="contact-row"
              :class="{ selected: selectedOpenid === contact.user_openid, inactive: !contact.active }"
              @click="selectContact(contact)"
            >
              <span class="avatar">{{ avatarText(contact) }}</span>
              <span class="contact-main">
                <span class="contact-title"><strong>{{ contactName(contact) }}</strong><time>{{ formatTime(contact.last_message_at) }}</time></span>
                <span class="contact-preview">{{ contact.last_message_preview || '尚无聊天内容' }}</span>
                <span class="contact-meta">
                  <em :class="contact.active ? 'online' : 'offline'">{{ contact.active ? '好友' : '已删除' }}</em>
                  <em v-if="contact.active && !contact.accepts_messages" class="reject">拒收主动消息</em>
                </span>
              </span>
              <span v-if="contact.unread_count" class="unread">{{ contact.unread_count > 99 ? '99+' : contact.unread_count }}</span>
            </button>
            <div v-if="!filteredContacts.length" class="empty-contacts">
              <strong>暂无联系人</strong>
              <span>让用户先添加机器人好友并发送一条单聊消息。</span>
            </div>
          </div>
        </aside>

        <main class="conversation">
          <template v-if="selectedContact">
            <header class="conversation-head">
              <div class="person">
                <span class="avatar large">{{ avatarText(selectedContact) }}</span>
                <div>
                  <h2>{{ contactName(selectedContact) }}</h2>
                  <code>{{ selectedContact.user_openid }}</code>
                </div>
              </div>
              <div class="relation">
                <button class="btn ghost" type="button" @click="renameSelectedContact">设置昵称</button>
                <span :class="selectedContact.active ? 'active' : 'deleted'">{{ selectedContact.active ? '好友关系有效' : '好友已删除' }}</span>
                <small>{{ selectedContact.accepts_messages ? '允许主动消息' : '主动消息已关闭' }}</small>
              </div>
            </header>

            <div ref="messageList" class="message-list">
              <div v-if="loadingMessages && !messages.length" class="conversation-empty">正在加载消息…</div>
              <div v-else-if="!messages.length" class="conversation-empty">暂无聊天记录。</div>
              <template v-for="item in messages" :key="item.id">
                <div v-if="item.direction === 'system'" class="system-message">
                  <span>{{ item.content }}</span><time>{{ formatTime(item.created_at) }}</time>
                </div>
                <div v-else class="message-row" :class="item.direction">
                  <div class="bubble" :class="{ failed: !item.success }">
                    <p>{{ item.content }}</p>
                    <div class="message-meta">
                      <span v-if="!item.success">发送失败 · {{ item.detail || item.status_code }}</span>
                      <span v-else-if="item.direction === 'outbound' && item.reply_to_msg_id">被动回复</span>
                      <time>{{ formatTime(item.created_at) }}</time>
                    </div>
                  </div>
                </div>
              </template>
            </div>

            <footer class="composer">
              <textarea
                v-model="draft"
                class="textarea"
                rows="3"
                :disabled="sending || !selectedContact.active"
                :placeholder="selectedContact.active ? '输入消息；Enter 发送，Shift+Enter 换行' : '该用户已删除机器人好友'"
                @keydown="handleComposerKeydown"
              ></textarea>
              <div class="composer-foot">
                <span>优先使用最近用户消息进行被动回复，过期后改用主动消息。</span>
                <button class="btn primary" :disabled="sending || !draft.trim() || !selectedContact.active" @click="send">
                  {{ sending ? '发送中…' : '发送消息' }}
                </button>
              </div>
            </footer>
          </template>
          <div v-else class="conversation-placeholder">
            <div class="placeholder-icon">✦</div>
            <h2>选择一个联系人</h2>
            <p>联系人由 QQ 单聊和好友关系回调自动建立，不支持从 QQ 全量拉取。</p>
          </div>
        </main>
      </div>

      <p v-if="notice" class="notice ok">{{ notice }}</p>
      <p v-if="error" class="notice error">{{ error }}</p>
      <p class="security-note">聊天内容保存在服务器 Docker 数据卷的 chat.db。当前管理台仍需通过登录或反向代理限制管理员访问。</p>
    </template>
  </section>
</template>

<style scoped>
.chat-page{max-width:1380px}.empty{padding:32px}.top-row{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:14px}.bot-selector{width:min(500px,100%)}.summary{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.summary span{padding:9px 12px;border:1px solid var(--line);border-radius:12px;background:#fff;color:var(--ink-3);font-size:11px}.summary b{color:var(--ink);font-size:13px}.source-note{display:flex;align-items:center;gap:10px;margin-bottom:14px;padding:12px 15px;border:1px solid rgba(0,153,255,.18);border-radius:13px;background:rgba(0,153,255,.06);font-size:12px}.source-note strong{color:var(--accent);white-space:nowrap}.source-note span{color:var(--ink-3);line-height:1.5}.requirements{display:grid;grid-template-columns:minmax(180px,1fr) minmax(0,2fr) auto;align-items:center;gap:15px;margin-bottom:14px;padding:14px 16px;border:1px solid #f0cf91;border-radius:14px;background:#fff8e8}.requirements strong{color:#8d5b08}.requirements p{margin:5px 0 0;color:#8d6a2d;font-size:11px;line-height:1.5}.event-tags{display:flex;flex-wrap:wrap;gap:6px}.event-tags span{padding:5px 7px;border-radius:999px;font-size:9.5px}.event-tags .ready{background:#e8f7ec;color:#26783d}.event-tags .missing{background:#fff0ed;color:#aa4939}.chat-shell{display:grid;grid-template-columns:330px minmax(0,1fr);height:min(740px,calc(100vh - 255px));min-height:580px;overflow:hidden}.contacts-panel{display:flex;flex-direction:column;min-width:0;border-right:1px solid var(--line);background:#fafafa}.contacts-head{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:17px 16px 10px}.contacts-head h2{margin:0;font-size:15px}.contacts-head small{display:block;margin-top:3px;color:var(--ink-4);font-size:10px}.filter-switch{display:flex;padding:3px;border-radius:9px;background:rgba(60,60,67,.07)}.filter-switch button{padding:5px 8px;border:0;border-radius:7px;background:transparent;color:var(--ink-4);font-size:10px}.filter-switch button.active{background:#fff;color:var(--accent);box-shadow:0 1px 5px rgba(0,0,0,.08)}.contact-search{width:auto;margin:0 12px 10px;padding:9px 11px;font-size:11.5px}.contact-list{flex:1;min-height:0;overflow-y:auto;padding:0 8px 12px}.contact-row{display:flex;align-items:center;gap:10px;width:100%;padding:11px 9px;border:0;border-radius:12px;background:transparent;text-align:left;transition:.15s ease}.contact-row:hover{background:rgba(0,0,0,.04)}.contact-row.selected{background:#fff;box-shadow:0 4px 15px rgba(17,24,39,.07)}.contact-row.inactive{opacity:.68}.avatar{display:grid;place-items:center;flex:none;width:38px;height:38px;border-radius:13px;background:linear-gradient(145deg,#e7f5ff,#d4eaff);color:#1677b8;font-size:12px;font-weight:800}.avatar.large{width:44px;height:44px;border-radius:15px;font-size:14px}.contact-main{min-width:0;flex:1}.contact-title{display:flex;align-items:center;justify-content:space-between;gap:8px}.contact-title strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}.contact-title time{flex:none;color:var(--ink-4);font-size:8.5px}.contact-preview{display:block;margin-top:5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-4);font-size:10.5px}.contact-meta{display:flex;gap:5px;margin-top:6px}.contact-meta em{padding:2px 5px;border-radius:999px;font-size:8px;font-style:normal}.contact-meta .online{background:#e8f7ec;color:#26783d}.contact-meta .offline{background:#eee;color:#777}.contact-meta .reject{background:#fff0ed;color:#aa4939}.unread{display:grid;place-items:center;flex:none;min-width:20px;height:20px;padding:0 5px;border-radius:999px;background:var(--accent);color:#fff;font-size:9px;font-weight:750}.empty-contacts{display:flex;flex-direction:column;align-items:center;gap:6px;padding:46px 20px;text-align:center}.empty-contacts strong{font-size:13px}.empty-contacts span{color:var(--ink-4);font-size:11px;line-height:1.5}.conversation{display:flex;flex-direction:column;min-width:0;min-height:0;background:#fff}.conversation-head{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:15px 19px;border-bottom:1px solid var(--line)}.person{display:flex;align-items:center;gap:11px;min-width:0}.person h2{margin:0;font-size:14px}.person code{display:block;max-width:420px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-4);font-size:9px}.relation{display:flex;flex-direction:column;align-items:flex-end;gap:6px;color:var(--ink-4);font-size:12px}.relation .btn{min-height:32px;padding:6px 10px}.relation span,.relation small{display:block}.relation span{font-size:11px;font-weight:700}.relation span.active{color:#238541}.relation span.deleted{color:var(--danger)}.relation small{margin-top:4px;color:var(--ink-4);font-size:9.5px}.message-list{flex:1;min-height:0;overflow-y:auto;padding:24px 26px;background:linear-gradient(180deg,#f7f9fb,#f3f6f9)}.message-row{display:flex;margin:9px 0}.message-row.inbound{justify-content:flex-start}.message-row.outbound{justify-content:flex-end}.bubble{max-width:min(72%,680px);padding:11px 13px;border:1px solid rgba(60,60,67,.08);border-radius:15px;background:#fff;box-shadow:0 3px 10px rgba(17,24,39,.04)}.outbound .bubble{border-color:rgba(0,153,255,.15);background:#e8f5ff}.bubble.failed{border-color:rgba(255,59,48,.25);background:#fff0ee}.bubble p{margin:0;white-space:pre-wrap;word-break:break-word;font-size:12.5px;line-height:1.65}.message-meta{display:flex;align-items:center;justify-content:flex-end;gap:8px;margin-top:6px;color:var(--ink-4);font-size:8.5px}.bubble.failed .message-meta{color:var(--danger)}.system-message{display:flex;justify-content:center;align-items:center;gap:7px;margin:14px 0;color:var(--ink-4);font-size:9.5px}.system-message span{padding:5px 9px;border-radius:999px;background:rgba(60,60,67,.08)}.system-message time{font-size:8px}.conversation-empty,.conversation-placeholder{display:flex;flex-direction:column;align-items:center;justify-content:center;flex:1;color:var(--ink-4);text-align:center}.conversation-placeholder h2{margin:12px 0 5px;color:var(--ink-2);font-size:16px}.conversation-placeholder p{max-width:380px;margin:0;font-size:11.5px;line-height:1.6}.placeholder-icon{display:grid;place-items:center;width:54px;height:54px;border-radius:18px;background:var(--accent-soft);color:var(--accent);font-size:23px}.composer{padding:14px 16px;border-top:1px solid var(--line);background:#fff}.composer .textarea{min-height:76px;max-height:160px;padding:11px 12px;font-family:var(--font-sans);font-size:12px;line-height:1.55}.composer-foot{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:9px}.composer-foot span{color:var(--ink-4);font-size:9.5px}.notice{margin:12px 0 0;font-size:12px}.ok{color:#238541}.error{color:var(--danger)}.security-note{margin:15px 2px 0;color:var(--ink-4);font-size:10.5px;line-height:1.6}@media(max-width:1050px){.requirements{grid-template-columns:1fr}.requirements .btn{justify-self:start}.chat-shell{grid-template-columns:290px minmax(0,1fr)}}@media(max-width:780px){.top-row{align-items:stretch;flex-direction:column}.summary{justify-content:flex-start}.chat-shell{display:flex;height:auto;min-height:0;overflow:visible}.contacts-panel{height:320px;border-right:0;border-bottom:1px solid var(--line)}.conversation{height:620px}.bubble{max-width:86%}.source-note{align-items:flex-start;flex-direction:column}.conversation-head{align-items:flex-start}.relation{display:none}}@media(max-width:520px){.chat-page{padding-left:10px;padding-right:10px}.message-list{padding:18px 12px}.composer-foot{align-items:flex-end;flex-direction:column}.composer-foot .btn{width:100%}.person code{max-width:230px}}
</style>
