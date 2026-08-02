<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type Bot } from '@/services/api'
import {
  libraryDeliveryApi,
  type LibraryDeliverySettingsPayload,
  type LibraryDeliveryStatus,
  type LibraryResult,
} from '@/services/libraryDeliveryApi'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const status = ref<LibraryDeliveryStatus | null>(null)
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const message = ref('')
const error = ref('')
const accessToken = ref('')
const clearAccessToken = ref(false)
const testKeyword = ref('')
const testResults = ref<LibraryResult[]>([])
const testTotal = ref<number | null>(null)

const form = reactive<LibraryDeliverySettingsPayload>({
  enabled: false,
  database_path: '/app/data/library.sqlite3',
  table_name: '新网盘资料',
  title_column: '标题',
  category_column: '分类',
  size_column: '大小',
  fsid_column: 'fsid',
  path_column: '网盘地址',
  clear_access_token: false,
  share_period: 7,
  session_ttl_seconds: 180,
  api_url: 'https://pan.baidu.com/rest/2.0/xpan/share',
  api_method: 'rapidshare',
})

const currentBot = computed(() => bots.value.find(item => item.id === botId.value) || null)
const ttlMinutes = computed(() => Math.max(1, Math.round(form.session_ttl_seconds / 60)))

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
    clear_access_token: false,
    share_period: value.settings.share_period,
    session_ttl_seconds: value.settings.session_ttl_seconds,
    api_url: value.settings.api_url,
    api_method: value.settings.api_method,
  })
  accessToken.value = ''
  clearAccessToken.value = false
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
    const payload: LibraryDeliverySettingsPayload = {
      ...form,
      clear_access_token: clearAccessToken.value,
    }
    if (accessToken.value.trim()) payload.access_token = accessToken.value.trim()
    applyStatus(await libraryDeliveryApi.updateSettings(botId.value, payload))
    message.value = '共享文库配置已保存'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
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
</script>

<template>
  <section class="page library-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">共享文库发货</h1>
        <p class="page-sub">群成员 @机器人检索标题，回复编号后创建百度网盘分享链接并自动发货。</p>
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
          <span>百度授权</span>
          <strong :class="status?.settings.access_token_configured ? 'good' : 'warn'">{{ status?.settings.access_token_configured ? 'Access Token 已配置' : '未配置' }}</strong>
          <small>凭证仅保存在服务端，不返回浏览器</small>
        </section>
        <section class="card summary-card">
          <span>成功发货</span>
          <strong>{{ status?.counts.delivered || 0 }}</strong>
          <small>检索 {{ status?.counts.searches || 0 }} 次 · 失败 {{ status?.counts.failures || 0 }} 次</small>
        </section>
      </div>

      <div v-if="status && (!status.requirements_ready || !status.database.ready || !status.settings.access_token_configured)" class="warning-box">
        <strong>启用前检查</strong>
        <span v-if="!status.requirements_ready">请在 QQ 管理端开通 GROUP_AT_MESSAGE_CREATE 和 GROUP_MESSAGE_CREATE。</span>
        <span v-if="!status.database.ready">{{ status.database.error }}</span>
        <span v-if="!status.settings.access_token_configured">请填写具备创建分享权限的百度网盘 Access Token。</span>
      </div>

      <div class="layout">
        <main class="stack">
          <section class="card panel">
            <div class="section-head">
              <div><h2 class="section-title">功能开关</h2><p class="section-sub">开启后自动把两个必需事件加入本地事件清单，QQ 管理端仍需手动授权。</p></div>
              <label class="switch"><input v-model="form.enabled" type="checkbox" /><span></span></label>
            </div>
            <div class="event-tags">
              <span v-for="event in status?.required_events" :key="event.code" :class="event.configured ? 'ready' : 'missing'">{{ event.code }} · {{ event.configured ? '已记录' : '未记录' }}</span>
            </div>
          </section>

          <section class="card panel">
            <h2 class="section-title">SQLite 资料库</h2>
            <p class="section-sub">数据库只读打开。默认映射与你截图中的“新网盘资料”表一致。</p>
            <div class="fields top">
              <div class="field wide"><label>容器内数据库路径</label><input v-model="form.database_path" class="input mono" /><small>建议上传为 /app/data/library.sqlite3</small></div>
              <div class="field"><label>表名</label><input v-model="form.table_name" class="input" /></div>
              <div class="field"><label>标题字段</label><input v-model="form.title_column" class="input" /></div>
              <div class="field"><label>分类字段</label><input v-model="form.category_column" class="input" /></div>
              <div class="field"><label>大小字段</label><input v-model="form.size_column" class="input" /></div>
              <div class="field"><label>fsid 字段</label><input v-model="form.fsid_column" class="input" /></div>
              <div class="field"><label>网盘路径字段</label><input v-model="form.path_column" class="input" /></div>
            </div>
          </section>

          <section class="card panel">
            <h2 class="section-title">百度网盘分享</h2>
            <p class="section-sub">选择资料后使用 fsid 创建独立分享链接，分享码自动生成 4 位小写字母和数字。</p>
            <div class="fields top">
              <div class="field wide">
                <label>百度网盘 Access Token</label>
                <input v-model="accessToken" class="input mono" type="password" :placeholder="status?.settings.access_token_configured ? '已保存，留空不修改' : '请输入 Access Token'" />
                <label class="check"><input v-model="clearAccessToken" type="checkbox" /> 清除已保存的 Access Token</label>
              </div>
              <div class="field"><label>分享有效期</label><select v-model.number="form.share_period" class="select"><option :value="1">1 天</option><option :value="7">7 天</option><option :value="30">30 天</option><option :value="0">永久</option></select></div>
              <div class="field"><label>选择会话有效期</label><select v-model.number="form.session_ttl_seconds" class="select"><option :value="60">1 分钟</option><option :value="180">3 分钟</option><option :value="300">5 分钟</option><option :value="600">10 分钟</option></select></div>
              <details class="advanced wide"><summary>高级接口配置</summary><div class="advanced-grid"><div class="field"><label>接口地址</label><input v-model="form.api_url" class="input mono" /></div><div class="field"><label>method</label><input v-model="form.api_method" class="input mono" /></div></div></details>
            </div>
          </section>

          <section class="card panel">
            <div class="section-head">
              <div><h2 class="section-title">数据库测试检索</h2><p class="section-sub">保存配置后可先验证表名、字段和标题匹配结果，不会创建分享链接。</p></div>
            </div>
            <div class="test-row"><input v-model="testKeyword" class="input" placeholder="例如：不动产" @keyup.enter="testSearch" /><button class="btn" :disabled="testing || !testKeyword.trim()" @click="testSearch">{{ testing ? '检索中…' : '测试检索' }}</button></div>
            <p v-if="testTotal !== null" class="test-total">找到 {{ testTotal }} 个，显示前 {{ testResults.length }} 个</p>
            <div v-for="(item, index) in testResults" :key="`${item.fsid}-${index}`" class="result-row"><b>{{ index + 1 }}. {{ item.title }}</b><span>{{ item.category || '未分类' }} · fsid {{ item.fsid }}</span><small>{{ item.pan_path }}</small></div>
          </section>
        </main>

        <aside class="stack side">
          <section class="card panel flow">
            <h2 class="section-title">群内流程</h2>
            <div><b>1</b><span>@机器人 不动产</span></div>
            <div><b>2</b><span>找到12个结果，前5个：1.资料A；2.资料B；请在{{ ttlMinutes }}分钟内回复编号。</span></div>
            <div><b>3</b><span>用户直接回复 1</span></div>
            <div><b>4</b><span>标题：资料A 分享链接：https://pan.baidu.com/s/... 提取码：a1b2 有效期：{{ form.share_period === 0 ? '永久' : `${form.share_period}天` }}</span></div>
            <small>所有群消息均为单行；搜索会话按机器人、群和用户隔离，成功发货后立即失效。</small>
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
.library-page{max-width:1240px}.selector{max-width:500px;margin-bottom:18px}.empty{padding:32px}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}.summary-card{padding:17px;min-width:0}.summary-card span,.summary-card strong,.summary-card small{display:block}.summary-card span{color:var(--ink-4);font-size:11px}.summary-card strong{margin-top:7px;font-size:18px}.summary-card small{margin-top:6px;color:var(--ink-4);font-size:10.5px;line-height:1.45;overflow-wrap:anywhere}.good{color:#238541}.warn{color:var(--warn)}.muted{color:var(--ink-4)}.warning-box{display:flex;flex-direction:column;gap:5px;margin-bottom:18px;padding:13px 15px;border:1px solid rgba(255,149,0,.25);border-radius:13px;background:rgba(255,149,0,.07);font-size:12px}.warning-box strong{color:var(--warn)}.warning-box span{color:#7b5600}.layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;align-items:start}.stack{display:flex;flex-direction:column;gap:18px}.panel{padding:22px}.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:15px}.top{margin-top:18px}.fields{display:grid;grid-template-columns:1fr 1fr;gap:14px}.wide{grid-column:1/-1}.field small{display:block;margin-top:6px;color:var(--ink-4);font-size:10.5px}.check{display:flex!important;align-items:center;gap:7px;margin-top:8px;color:var(--ink-3)!important;font-size:11px!important}.check input{accent-color:var(--accent)}.switch{position:relative;display:inline-flex}.switch input{position:absolute;opacity:0}.switch span{width:44px;height:25px;border-radius:99px;background:#d7d7dc;transition:.15s}.switch span:after{content:'';display:block;width:21px;height:21px;margin:2px;border-radius:50%;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.25);transition:.15s}.switch input:checked+span{background:var(--accent)}.switch input:checked+span:after{transform:translateX(19px)}.event-tags{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}.event-tags span{padding:6px 9px;border-radius:999px;font-size:10px}.event-tags .ready{background:rgba(52,199,89,.12);color:#238541}.event-tags .missing{background:rgba(255,149,0,.12);color:var(--warn)}.advanced{padding:12px;border:1px solid var(--line);border-radius:12px}.advanced summary{cursor:pointer;font-size:12px;font-weight:700}.advanced-grid{display:grid;grid-template-columns:2fr 1fr;gap:12px;margin-top:13px}.test-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:9px;margin-top:16px}.test-total{margin:14px 0 6px;color:var(--ink-3);font-size:12px}.result-row{display:flex;flex-direction:column;gap:4px;padding:11px 0;border-top:1px solid var(--line)}.result-row b{font-size:12px}.result-row span,.result-row small{color:var(--ink-4);font-size:10.5px;overflow-wrap:anywhere}.side{position:sticky;top:22px}.flow>div{display:grid;grid-template-columns:24px 1fr;gap:8px;padding:10px 0;border-bottom:1px solid var(--line)}.flow>div b{display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--accent-soft);color:var(--accent);font-size:10px}.flow>div span{font-size:11px;line-height:1.55;overflow-wrap:anywhere}.flow>small{display:block;margin-top:12px;color:var(--ink-4);font-size:10.5px;line-height:1.55}.empty-small{padding:18px 0;color:var(--ink-4);font-size:11px}.log-row{padding:11px 0;border-top:1px solid var(--line)}.log-row>span{display:flex;align-items:center;justify-content:space-between;gap:8px}.log-row b{font-size:11.5px}.log-row em{padding:3px 6px;border-radius:999px;font-size:9px;font-style:normal}.log-row em.success{background:rgba(52,199,89,.12);color:#238541}.log-row em.failed{background:rgba(255,59,48,.1);color:var(--danger)}.log-row small,.log-row time{display:block;margin-top:5px;color:var(--ink-4);font-size:9.5px;line-height:1.4;overflow-wrap:anywhere}.notice{margin-top:14px}.ok{color:#238541}.error{color:var(--danger)}@media(max-width:1050px){.summary-grid{grid-template-columns:1fr 1fr}.layout{grid-template-columns:1fr}.side{position:static;display:grid;grid-template-columns:1fr 1fr}}@media(max-width:700px){.summary-grid,.fields,.side,.advanced-grid{grid-template-columns:1fr}.wide{grid-column:auto}.test-row{grid-template-columns:1fr}}
</style>
