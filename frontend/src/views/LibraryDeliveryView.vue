<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type Bot } from '@/services/api'
import {
  libraryDeliveryApi,
  type BaiduOAuthSession,
  type LibraryDeliverySettingsPayload,
  type LibraryDeliveryStatus,
  type LibraryResult,
} from '@/services/libraryDeliveryApi'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const status = ref<LibraryDeliveryStatus | null>(null)
const oauthSession = ref<BaiduOAuthSession | null>(null)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const authorizing = ref(false)
const message = ref('')
const error = ref('')
const testKeyword = ref('')
const testResults = ref<LibraryResult[]>([])
const testTotal = ref<number | null>(null)
let pollTimer: number | undefined

const form = reactive<LibraryDeliverySettingsPayload>({
  enabled: false,
  database_path: '/app/data/library.sqlite3',
  table_name: '新网盘资料',
  title_column: '标题',
  category_column: '分类',
  size_column: '大小',
  fsid_column: 'fsid',
  path_column: '网盘地址',
  share_period: 7,
  session_ttl_seconds: 180,
  api_url: 'https://pan.baidu.com/rest/2.0/xpan/share',
  api_method: 'rapidshare',
})

const currentBot = computed(() => bots.value.find(item => item.id === botId.value) || null)
const ttlMinutes = computed(() => Math.max(1, Math.round(form.session_ttl_seconds / 60)))
const qrImageUrl = computed(() => {
  if (!oauthSession.value?.qr_image_url) return ''
  return `${oauthSession.value.qr_image_url}?expires=${encodeURIComponent(oauthSession.value.expires_at)}`
})

function stopPolling() {
  if (pollTimer !== undefined) window.clearTimeout(pollTimer)
  pollTimer = undefined
}

function schedulePoll(session: BaiduOAuthSession) {
  stopPolling()
  if (session.status !== 'pending') return
  const delay = Math.max(3, session.interval_seconds || 5) * 1000
  pollTimer = window.setTimeout(() => void pollOAuth(session.session_id), delay)
}

function applyStatus(value: LibraryDeliveryStatus) {
  status.value = value
  Object.assign(form, {
    enabled: value.settings.enabled,
    database_path: value.settings.database_path,
    table_name: value.settings.table_name,
    title_column: value.settings.title_column,
    category_column: value.settings.category_column,
    size_column: value.settings.size_column,
    fsid_column: value.settings.fsid_column,
    path_column: value.settings.path_column,
    share_period: value.settings.share_period,
    session_ttl_seconds: value.settings.session_ttl_seconds,
    api_url: value.settings.api_url,
    api_method: value.settings.api_method,
  })
  if (value.oauth.pending_session?.status === 'pending') {
    oauthSession.value = value.oauth.pending_session
    schedulePoll(value.oauth.pending_session)
  } else if (value.oauth.authorized) {
    oauthSession.value = null
    stopPolling()
  }
}

async function load() {
  if (!botId.value) return
  loading.value = true
  error.value = ''
  try {
    applyStatus(await libraryDeliveryApi.status(botId.value))
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!botId.value) return
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    applyStatus(await libraryDeliveryApi.updateSettings(botId.value, { ...form }))
    message.value = '共享文库配置已保存'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function startOAuth() {
  if (!botId.value) return
  authorizing.value = true
  error.value = ''
  message.value = ''
  stopPolling()
  try {
    const result = await libraryDeliveryApi.startOAuth(botId.value)
    oauthSession.value = result.session
    if (status.value) status.value.oauth = result.oauth
    message.value = '请使用百度网盘 App 扫描二维码并确认授权'
    schedulePoll(result.session)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '无法生成授权二维码'
  } finally {
    authorizing.value = false
  }
}

async function pollOAuth(sessionId: string) {
  try {
    const result = await libraryDeliveryApi.pollOAuth(sessionId)
    oauthSession.value = result.session
    if (status.value) status.value.oauth = result.oauth
    if (result.oauth.authorized || result.session.authorized) {
      stopPolling()
      oauthSession.value = null
      message.value = '百度网盘授权成功，Access Token 与刷新凭证已由后端保存'
      await load()
      return
    }
    if (result.session.status === 'pending') {
      schedulePoll(result.session)
      return
    }
    stopPolling()
    error.value = result.session.last_error || '授权未完成，请重新生成二维码'
  } catch (e) {
    stopPolling()
    error.value = e instanceof Error ? e.message : '授权状态检查失败'
  }
}

async function testSearch() {
  if (!botId.value || !testKeyword.value.trim()) return
  testing.value = true
  error.value = ''
  testResults.value = []
  testTotal.value = null
  try {
    const result = await libraryDeliveryApi.testSearch(botId.value, testKeyword.value.trim())
    testResults.value = result.results
    testTotal.value = result.total_count
  } catch (e) {
    error.value = e instanceof Error ? e.message : '测试检索失败'
  } finally {
    testing.value = false
  }
}

function formatTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function actionText(action: string) {
  if (action === 'search') return '标题检索'
  if (action === 'share_created') return '创建分享并发货'
  return action
}

watch(botId, () => {
  stopPolling()
  oauthSession.value = null
  message.value = ''
  error.value = ''
  testResults.value = []
  testTotal.value = null
  void load()
})

onMounted(async () => {
  try {
    bots.value = await api.listBots()
    const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
    botId.value = bots.value.some(item => item.id === preferred) ? preferred : (bots.value[0]?.id || '')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '机器人列表加载失败'
  }
})

onBeforeUnmount(stopPolling)
</script>

<template>
  <section class="page library-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">共享文库发货</h1>
        <p class="page-sub">群成员 @机器人检索标题，回复编号后由后端统一创建百度网盘分享链接。</p>
      </div>
      <div class="page-actions">
        <button class="btn" :disabled="loading || !botId" @click="load">{{ loading ? '刷新中…' : '刷新状态' }}</button>
        <button class="btn primary" :disabled="saving || !botId" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
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
          <span>功能状态</span>
          <strong :class="form.enabled ? 'good' : 'muted'">{{ form.enabled ? '已启用' : '未启用' }}</strong>
          <small>当前机器人：{{ currentBot?.name }}</small>
        </section>
        <section class="card summary-card">
          <span>资料数据库</span>
          <strong :class="status?.database.ready ? 'good' : 'warn'">{{ status?.database.ready ? `${status.database.row_count} 条` : '未就绪' }}</strong>
          <small>{{ status?.database.ready ? status.settings.database_path : (status?.database.error || '等待检测') }}</small>
        </section>
        <section class="card summary-card">
          <span>百度网盘账号</span>
          <strong :class="status?.oauth.authorized ? 'good' : 'warn'">{{ status?.oauth.authorized ? '已扫码授权' : '未授权' }}</strong>
          <small>{{ status?.oauth.authorized ? `后端自动续期 · ${formatTime(status.oauth.token_expires_at)}` : '前端只扫码，不接触 Token' }}</small>
        </section>
        <section class="card summary-card">
          <span>成功发货</span>
          <strong>{{ status?.counts.delivered || 0 }}</strong>
          <small>检索 {{ status?.counts.searches || 0 }} 次 · 失败 {{ status?.counts.failures || 0 }} 次</small>
        </section>
      </div>

      <div v-if="status && (!status.requirements_ready || !status.database.ready || !status.oauth.app_configured || !status.oauth.authorized)" class="warning-box">
        <strong>启用前检查</strong>
        <span v-if="!status.requirements_ready">请在 QQ 管理端开通 GROUP_AT_MESSAGE_CREATE 和 GROUP_MESSAGE_CREATE。</span>
        <span v-if="!status.database.ready">{{ status.database.error }}</span>
        <span v-if="!status.oauth.app_configured">服务器需要配置 BAIDU_PAN_APP_KEY 和 BAIDU_PAN_SECRET_KEY。</span>
        <span v-else-if="!status.oauth.authorized">请在下方生成二维码并使用百度网盘 App 扫码授权。</span>
      </div>

      <div class="layout">
        <main class="stack">
          <section class="card panel">
            <div class="section-head">
              <div><h2 class="section-title">功能开关</h2><p class="section-sub">开启后把必需事件加入本地清单，QQ 管理端仍需实际开通。</p></div>
              <label class="switch"><input v-model="form.enabled" type="checkbox" /><span></span></label>
            </div>
            <div class="event-tags">
              <span v-for="event in status?.required_events" :key="event.code" :class="event.configured ? 'ready' : 'missing'">{{ event.code }} · {{ event.configured ? '已记录' : '未记录' }}</span>
            </div>
          </section>

          <section class="card panel oauth-panel">
            <div class="section-head">
              <div><h2 class="section-title">百度网盘扫码授权</h2><p class="section-sub">整个后端共用一个网盘账号。Access Token、Refresh Token 和自动刷新全部由服务器管理。</p></div>
              <button class="btn" :disabled="authorizing || !status?.oauth.app_configured" @click="startOAuth">{{ authorizing ? '生成中…' : (status?.oauth.authorized ? '重新扫码授权' : '生成授权二维码') }}</button>
            </div>
            <div v-if="status?.oauth.authorized && !oauthSession" class="oauth-ready">
              <strong>授权可用</strong>
              <span>授权时间：{{ formatTime(status.oauth.authorized_at) }}</span>
              <span>Token 预计过期：{{ formatTime(status.oauth.token_expires_at) }}</span>
              <small>到期前后端会使用 Refresh Token 自动续期，QQ群用户不需要操作。</small>
            </div>
            <div v-else-if="oauthSession" class="oauth-qr">
              <img v-if="qrImageUrl" :src="qrImageUrl" alt="百度网盘授权二维码" />
              <div>
                <strong>请使用百度网盘 App 扫码并确认</strong>
                <span>授权码：<b class="mono">{{ oauthSession.user_code || '—' }}</b></span>
                <span>二维码有效至：{{ formatTime(oauthSession.expires_at) }}</span>
                <span>状态：{{ oauthSession.status === 'pending' ? '等待扫码确认' : oauthSession.status }}</span>
                <a v-if="oauthSession.verification_url" :href="oauthSession.verification_url" target="_blank" rel="noopener noreferrer">二维码无法识别时打开百度授权页 ↗</a>
                <small>页面会按百度返回的轮询间隔自动检查，不会把设备码或 Token 写入浏览器存储。</small>
              </div>
            </div>
            <p v-else-if="!status?.oauth.app_configured" class="oauth-empty">先在服务器 `backend/.env` 配置百度开放平台 AppKey 与 SecretKey，再重建后端容器。</p>
            <p v-else class="oauth-empty">点击“生成授权二维码”，扫码一次即可供本服务的全部资料发货使用。</p>
          </section>

          <section class="card panel">
            <h2 class="section-title">SQLite 资料库</h2>
            <p class="section-sub">数据库由服务端统一持有并以只读方式检索，QQ群用户只有查询和发货能力。</p>
            <div class="fields top">
              <div class="field wide"><label>容器内数据库路径</label><input v-model="form.database_path" class="input mono" /><small>当前建议：/app/data/library.sqlite3</small></div>
              <div class="field"><label>表名</label><input v-model="form.table_name" class="input" /></div>
              <div class="field"><label>标题字段</label><input v-model="form.title_column" class="input" /></div>
              <div class="field"><label>分类字段</label><input v-model="form.category_column" class="input" /></div>
              <div class="field"><label>大小字段</label><input v-model="form.size_column" class="input" /></div>
              <div class="field"><label>fsid 字段</label><input v-model="form.fsid_column" class="input" /></div>
              <div class="field"><label>网盘路径字段</label><input v-model="form.path_column" class="input" /></div>
            </div>
          </section>

          <section class="card panel">
            <h2 class="section-title">发货设置</h2>
            <div class="fields top">
              <div class="field"><label>分享有效期</label><select v-model.number="form.share_period" class="select"><option :value="1">1 天</option><option :value="7">7 天</option><option :value="30">30 天</option><option :value="0">永久</option></select></div>
              <div class="field"><label>选择会话有效期</label><select v-model.number="form.session_ttl_seconds" class="select"><option :value="60">1 分钟</option><option :value="180">3 分钟</option><option :value="300">5 分钟</option><option :value="600">10 分钟</option></select></div>
              <details class="advanced wide"><summary>高级接口配置</summary><div class="advanced-grid"><div class="field"><label>接口地址</label><input v-model="form.api_url" class="input mono" /></div><div class="field"><label>method</label><input v-model="form.api_method" class="input mono" /></div></div></details>
            </div>
          </section>

          <section class="card panel">
            <h2 class="section-title">数据库测试检索</h2>
            <p class="section-sub">只测试标题匹配，不创建百度分享。</p>
            <div class="test-row"><input v-model="testKeyword" class="input" placeholder="例如：不动产" @keyup.enter="testSearch" /><button class="btn" :disabled="testing || !testKeyword.trim()" @click="testSearch">{{ testing ? '检索中…' : '测试检索' }}</button></div>
            <p v-if="testTotal !== null" class="test-total">找到 {{ testTotal }} 个，显示前 {{ testResults.length }} 个</p>
            <div v-for="(item, index) in testResults" :key="`${item.fsid}-${index}`" class="result-row"><b>{{ index + 1 }}. {{ item.title }}</b><span>{{ item.category || '未分类' }} · fsid {{ item.fsid }}</span><small>{{ item.pan_path }}</small></div>
          </section>
        </main>

        <aside class="stack side">
          <section class="card panel flow">
            <h2 class="section-title">群内流程</h2>
            <div><b>1</b><span>@机器人 不动产</span></div>
            <div><b>2</b><span>找到匹配结果并列出前 5 个，请在 {{ ttlMinutes }} 分钟内回复编号。</span></div>
            <div><b>3</b><span>用户直接回复 1</span></div>
            <div><b>4</b><span>后端使用统一百度授权创建分享，并发送标题、链接、提取码和有效期。</span></div>
            <small>数据库和百度账号都属于服务器；QQ群用户不会获得数据库访问权、AppKey、SecretKey 或 Token。</small>
          </section>

          <section class="card panel logs">
            <div class="section-head"><div><h2 class="section-title">最近记录</h2><p class="section-sub">最多显示 80 条</p></div></div>
            <div v-if="!status?.logs.length" class="empty-small">暂无记录</div>
            <div v-for="log in status?.logs" :key="log.id" class="log-row">
              <span><b>{{ actionText(log.action) }}</b><em :class="log.success ? 'success' : 'failed'">{{ log.success ? '成功' : '失败' }}</em></span>
              <small>{{ log.title || log.query || log.detail || '—' }}</small>
              <time>{{ formatTime(log.created_at) }}</time>
            </div>
          </section>
        </aside>
      </div>

      <p v-if="message" class="notice ok">{{ message }}</p>
      <p v-if="error" class="notice error">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.library-page{max-width:1240px}.selector{max-width:500px;margin-bottom:18px}.empty{padding:32px}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}.summary-card{padding:17px;min-width:0}.summary-card span,.summary-card strong,.summary-card small{display:block}.summary-card span{color:var(--ink-4);font-size:11px}.summary-card strong{margin-top:7px;font-size:18px}.summary-card small{margin-top:6px;color:var(--ink-4);font-size:10.5px;overflow:hidden;text-overflow:ellipsis}.good{color:#238541}.warn{color:#b66b00}.muted{color:var(--ink-4)}.warning-box{display:flex;flex-direction:column;gap:6px;margin-bottom:14px;padding:14px 16px;border:1px solid #f2d29a;border-radius:14px;background:#fff8e8;color:#80520b;font-size:12px}.layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:16px;align-items:start}.stack{display:flex;flex-direction:column;gap:16px}.panel{padding:20px}.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.fields.top{margin-top:18px}.wide{grid-column:1/-1}.event-tags{display:flex;flex-wrap:wrap;gap:8px;margin-top:16px}.event-tags span{padding:7px 9px;border-radius:999px;font-size:10.5px}.event-tags .ready{background:#eaf8ee;color:#23763a}.event-tags .missing{background:#fff0ed;color:#a64232}.switch input{display:none}.switch span{display:block;width:46px;height:26px;padding:3px;border-radius:999px;background:#bbb;transition:.2s}.switch span:after{content:'';display:block;width:20px;height:20px;border-radius:50%;background:#fff;transition:.2s}.switch input:checked+span{background:var(--accent)}.switch input:checked+span:after{transform:translateX(20px)}.oauth-panel{overflow:hidden}.oauth-ready{display:flex;flex-direction:column;gap:6px;margin-top:16px;padding:16px;border-radius:14px;background:#edf9f0}.oauth-ready strong{color:#238541}.oauth-ready span,.oauth-ready small{color:var(--ink-3);font-size:12px}.oauth-qr{display:grid;grid-template-columns:210px minmax(0,1fr);gap:20px;align-items:center;margin-top:16px;padding:18px;border-radius:16px;background:var(--bg-sunken)}.oauth-qr img{width:210px;height:210px;object-fit:contain;border-radius:12px;background:#fff}.oauth-qr div{display:flex;flex-direction:column;gap:9px}.oauth-qr span,.oauth-qr a,.oauth-qr small{font-size:12px}.oauth-qr a{color:var(--accent)}.oauth-qr small{color:var(--ink-4);line-height:1.6}.oauth-empty{margin:16px 0 0;padding:15px;border-radius:13px;background:var(--bg-sunken);color:var(--ink-3);font-size:12px}.advanced{padding:12px;border:1px solid var(--line);border-radius:13px}.advanced summary{cursor:pointer;font-weight:700}.advanced-grid{display:grid;grid-template-columns:1fr 180px;gap:12px;margin-top:14px}.test-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px;margin-top:16px}.test-total{color:var(--ink-3);font-size:12px}.result-row{display:flex;flex-direction:column;gap:4px;padding:11px 0;border-bottom:1px solid var(--line)}.result-row span,.result-row small{color:var(--ink-4);font-size:11px;word-break:break-all}.flow>div{display:grid;grid-template-columns:24px 1fr;gap:9px;margin-top:13px;align-items:start}.flow>div b{display:grid;place-items:center;width:24px;height:24px;border-radius:50%;background:var(--accent-soft);color:var(--accent);font-size:11px}.flow>div span{font-size:12px;line-height:1.6}.flow>small{display:block;margin-top:15px;color:var(--ink-4);font-size:11px;line-height:1.6}.log-row{display:flex;flex-direction:column;gap:4px;padding:11px 0;border-bottom:1px solid var(--line)}.log-row>span{display:flex;justify-content:space-between;gap:10px}.log-row em{font-style:normal;font-size:10px}.log-row em.success{color:#238541}.log-row em.failed{color:var(--danger)}.log-row small,.log-row time{color:var(--ink-4);font-size:10.5px;word-break:break-all}.empty-small{padding:24px 0;color:var(--ink-4);text-align:center}.notice{margin-top:14px}.notice.ok{color:#238541}.notice.error{color:var(--danger)}@media(max-width:1020px){.summary-grid{grid-template-columns:repeat(2,1fr)}.layout{grid-template-columns:1fr}.side{display:grid;grid-template-columns:1fr 1fr}}@media(max-width:680px){.summary-grid,.fields,.advanced-grid,.side,.oauth-qr{grid-template-columns:1fr}.oauth-qr img{width:min(100%,260px);height:auto;aspect-ratio:1}.section-head{flex-direction:column}.test-row{grid-template-columns:1fr}}
</style>
