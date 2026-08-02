<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, type Bot } from '@/services/api'
import {
  aiApi,
  type AiBotStatus,
  type AiImageAsset,
  type AiProfile,
} from '@/services/aiApi'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const status = ref<AiBotStatus | null>(null)
const profile = ref<AiProfile | null>(null)
const apiKey = ref('')
const credential = ref<{ configured: boolean; key_hint: string }>({ configured: false, key_hint: '' })
const testPrompt = ref('你好，请用你的身份介绍一下自己。')
const testResult = ref('')
const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const credentialBusy = ref(false)
const error = ref('')
const notice = ref('')

const currentBot = computed(() => bots.value.find(item => item.id === botId.value) || null)
const canManageCredential = computed(() => status.value?.credential.owner_is_current_user !== false)

function emptyAsset(): AiImageAsset {
  return { key: '', label: '', description: '', url: '' }
}

function formatTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function jobLabel(value: string) {
  return ({ pending: '等待中', running: '生成中', completed: '已完成', failed: '失败' } as Record<string, string>)[value] || value
}

function addAsset() {
  profile.value?.image_assets.push(emptyAsset())
}

function removeAsset(index: number) {
  profile.value?.image_assets.splice(index, 1)
}

async function loadCredential() {
  credential.value = await aiApi.credential()
}

async function loadBotStatus() {
  if (!botId.value) return
  status.value = await aiApi.botStatus(botId.value)
  profile.value = {
    ...status.value.profile,
    image_assets: status.value.profile.image_assets.map(item => ({ ...item })),
  }
}

async function refresh(showNotice = false) {
  if (!botId.value) return
  loading.value = true
  error.value = ''
  try {
    await Promise.all([loadCredential(), loadBotStatus()])
    if (showNotice) notice.value = 'AI 配置状态已刷新'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载 AI 配置失败'
  } finally {
    loading.value = false
  }
}

async function saveCredential() {
  const key = apiKey.value.trim()
  if (!key || credentialBusy.value) return
  credentialBusy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await aiApi.saveCredential(key)
    credential.value = result
    apiKey.value = ''
    notice.value = `DeepSeek Key 已验证并加密保存，可用模型：${result.models.join('、') || '已连接'}`
    await loadBotStatus()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存 DeepSeek Key 失败'
  } finally {
    credentialBusy.value = false
  }
}

async function testCredential() {
  credentialBusy.value = true
  error.value = ''
  try {
    const result = await aiApi.testCredential()
    notice.value = `DeepSeek 连接正常：${result.models.join('、') || '模型接口可访问'}`
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'DeepSeek 连接测试失败'
  } finally {
    credentialBusy.value = false
  }
}

async function deleteCredential() {
  if (!window.confirm('删除后，你名下所有机器人的 AI 自动回复都会停止。确定删除吗？')) return
  credentialBusy.value = true
  error.value = ''
  try {
    await aiApi.deleteCredential()
    credential.value = { configured: false, key_hint: '' }
    notice.value = 'DeepSeek Key 已删除'
    await loadBotStatus()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除 DeepSeek Key 失败'
  } finally {
    credentialBusy.value = false
  }
}

async function saveProfile() {
  if (!profile.value || !botId.value || saving.value) return
  saving.value = true
  error.value = ''
  notice.value = ''
  try {
    const { bot_id: _botId, updated_at: _updatedAt, ...payload } = profile.value
    const result = await aiApi.saveProfile(botId.value, payload)
    profile.value = { ...result.profile, image_assets: result.profile.image_assets.map(item => ({ ...item })) }
    notice.value = profile.value.enabled ? 'AI 身份已保存并启用' : 'AI 身份已保存，自动回复当前关闭'
    await loadBotStatus()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存 AI 身份失败'
  } finally {
    saving.value = false
  }
}

async function testProfile() {
  if (!botId.value || !testPrompt.value.trim() || testing.value) return
  testing.value = true
  error.value = ''
  testResult.value = ''
  try {
    const result = await aiApi.testProfile(botId.value, testPrompt.value.trim())
    testResult.value = result.text || `[仅图片素材：${result.image_key}]`
    if (result.image_key) testResult.value += `\n\n建议图片素材：${result.image_key}`
    notice.value = `测试完成，使用 ${result.model}，共 ${result.usage.total_tokens} tokens`
  } catch (e) {
    error.value = e instanceof Error ? e.message : '测试 AI 身份失败'
  } finally {
    testing.value = false
  }
}

watch(botId, async () => {
  status.value = null
  profile.value = null
  testResult.value = ''
  error.value = ''
  notice.value = ''
  if (botId.value) await refresh(false)
})

onMounted(async () => {
  loading.value = true
  try {
    bots.value = await api.listBots()
    const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
    botId.value = bots.value.some(item => item.id === preferred) ? preferred : (bots.value[0]?.id || '')
    await loadCredential()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '初始化 AI 页面失败'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="ai-page page-shell">
    <header class="page-head">
      <div>
        <div class="eyebrow">DEEPSEEK AI COMPANION</div>
        <h1>AI 身份与自动回复</h1>
        <p>每个登录用户提供自己的 DeepSeek Key；每个机器人只保存一套独立身份和回复策略。</p>
      </div>
      <div class="head-actions">
        <select v-model="botId" class="input bot-select">
          <option value="" disabled>选择机器人</option>
          <option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }} · {{ bot.app_id }}</option>
        </select>
        <button class="btn" type="button" :disabled="loading || !botId" @click="refresh(true)">刷新</button>
      </div>
    </header>

    <p v-if="error" class="alert error">{{ error }}</p>
    <p v-if="notice" class="alert success">{{ notice }}</p>

    <div v-if="!bots.length && !loading" class="empty card">
      <h2>还没有机器人</h2>
      <p>先在“我的机器人”中接入一个 QQ 官方机器人，再配置 AI 身份。</p>
    </div>

    <template v-if="currentBot && profile">
      <section class="status-grid">
        <article class="metric card">
          <span>自动回复</span>
          <strong>{{ profile.enabled ? '已启用' : '已关闭' }}</strong>
          <small>{{ status?.event_configured ? 'C2C 事件已记录' : '需在 QQ 管理端开通 C2C_MESSAGE_CREATE' }}</small>
        </article>
        <article class="metric card">
          <span>DeepSeek Key</span>
          <strong>{{ status?.credential.configured ? '已配置' : '未配置' }}</strong>
          <small>{{ status?.credential.key_hint || credential.key_hint || '密钥不会返回浏览器' }}</small>
        </article>
        <article class="metric card">
          <span>回复任务</span>
          <strong>{{ status?.counts.completed || 0 }}</strong>
          <small>等待 {{ status?.counts.pending || 0 }} · 失败 {{ status?.counts.failed || 0 }}</small>
        </article>
      </section>

      <section class="card section-card">
        <div class="section-head">
          <div>
            <h2>1. DeepSeek 凭证</h2>
            <p>Key 按登录用户保存，并使用服务端密钥加密。你名下的多个机器人可共用该 Key。</p>
          </div>
          <span class="pill" :class="credential.configured ? 'ok' : 'warn'">{{ credential.configured ? credential.key_hint : '未配置' }}</span>
        </div>
        <div v-if="canManageCredential" class="credential-row">
          <input v-model="apiKey" class="input mono" type="password" autocomplete="new-password" placeholder="输入 DeepSeek API Key，保存前会先验证" />
          <button class="btn primary" type="button" :disabled="credentialBusy || !apiKey.trim()" @click="saveCredential">验证并保存</button>
          <button class="btn" type="button" :disabled="credentialBusy || !credential.configured" @click="testCredential">测试已保存 Key</button>
          <button class="btn danger" type="button" :disabled="credentialBusy || !credential.configured" @click="deleteCredential">删除</button>
        </div>
        <p v-else class="muted">当前机器人属于其他用户。管理员可以调整身份，但不能查看或替换对方的 Key。</p>
      </section>

      <section class="card section-card">
        <div class="section-head">
          <div>
            <h2>2. 模型与身份</h2>
            <p>一个机器人只能保存这一套身份。系统提示由后端构造，聊天用户无法覆盖。</p>
          </div>
          <label class="switch-line"><input v-model="profile.enabled" type="checkbox" /><span>启用自动回复</span></label>
        </div>

        <div class="form-grid two">
          <label class="field"><span>模型</span><select v-model="profile.model" class="input"><option value="deepseek-v4-flash">DeepSeek V4 Flash</option><option value="deepseek-v4-pro">DeepSeek V4 Pro</option></select></label>
          <label class="field"><span>机器人身份名称</span><input v-model="profile.identity_name" class="input" maxlength="80" /></label>
          <label class="field full"><span>身份设定</span><textarea v-model="profile.role_description" class="input textarea" rows="3"></textarea></label>
          <label class="field full"><span>与用户的关系</span><textarea v-model="profile.relationship_description" class="input textarea" rows="2"></textarea></label>
          <label class="field full"><span>说话风格</span><textarea v-model="profile.speaking_style" class="input textarea" rows="2"></textarea></label>
          <label class="field"><span>回复长度</span><select v-model="profile.response_length" class="input"><option value="brief">一句话</option><option value="short">简短</option><option value="normal">正常</option><option value="detailed">较详细</option></select></label>
          <label class="field"><span>上下文轮数</span><input v-model.number="profile.context_turns" class="input" type="number" min="1" max="30" /></label>
          <label class="field"><span>最大输出 Tokens</span><input v-model.number="profile.max_tokens" class="input" type="number" min="64" max="4000" /></label>
          <label class="check-field"><input v-model="profile.thinking_enabled" type="checkbox" /><span>启用思考模式（更慢、消耗更多）</span></label>
          <label class="field full"><span>必须遵守的限制</span><textarea v-model="profile.restrictions" class="input textarea" rows="3"></textarea></label>
          <label class="field full"><span>高级补充提示词</span><textarea v-model="profile.custom_prompt" class="input textarea mono" rows="5" placeholder="可选。不要放入 API Key 或其他机密。"></textarea></label>
          <label class="field full"><span>最终失败提示</span><input v-model="profile.failure_message" class="input" maxlength="500" /></label>
        </div>
      </section>

      <section class="card section-card">
        <div class="section-head"><div><h2>3. 回复方式</h2><p>引用回复冻结本次触发消息 ID，不会误引用用户后来发送的新消息。</p></div></div>
        <div class="reply-options">
          <label class="choice" :class="{ active: profile.reply_mode === 'auto' }"><input v-model="profile.reply_mode" type="radio" value="auto" /><strong>自动</strong><span>优先引用；凭证过期时转普通主动消息。</span></label>
          <label class="choice" :class="{ active: profile.reply_mode === 'quote' }"><input v-model="profile.reply_mode" type="radio" value="quote" /><strong>引用回复</strong><span>始终回复触发这次 AI 任务的消息。</span></label>
          <label class="choice" :class="{ active: profile.reply_mode === 'normal' }"><input v-model="profile.reply_mode" type="radio" value="normal" /><strong>普通回复</strong><span>不带 msg_id，受主动消息权限与额度限制。</span></label>
        </div>
        <label v-if="profile.reply_mode === 'quote'" class="check-field inline"><input v-model="profile.quote_fallback" type="checkbox" /><span>引用凭证过期时自动改用普通回复</span></label>
      </section>

      <section class="card section-card">
        <div class="section-head">
          <div><h2>4. 图片素材回复</h2><p>模型只能选择你配置的素材键。后端先上传到 QQ 富媒体接口，再发送图片消息。</p></div>
          <label class="switch-line"><input v-model="profile.allow_images" type="checkbox" /><span>允许图片回复</span></label>
        </div>
        <div v-if="profile.allow_images" class="asset-list">
          <div v-for="(asset, index) in profile.image_assets" :key="index" class="asset-row">
            <input v-model="asset.key" class="input mono" placeholder="素材键，如 happy" maxlength="40" />
            <input v-model="asset.label" class="input" placeholder="显示名称" maxlength="80" />
            <input v-model="asset.description" class="input" placeholder="何时使用这张图" maxlength="300" />
            <input v-model="asset.url" class="input mono asset-url" placeholder="https://.../image.png" />
            <button class="btn danger" type="button" @click="removeAsset(index)">删除</button>
          </div>
          <button class="btn" type="button" :disabled="profile.image_assets.length >= 20" @click="addAsset">添加图片素材</button>
          <p class="muted">仅支持公开可访问的 HTTPS 图片地址。当前 DeepSeek 文本模型不会读取或生成图片。</p>
        </div>
      </section>

      <section class="actions-card card">
        <div><strong>保存后立即影响新收到的单聊消息</strong><span>正在执行的任务会读取最新身份配置，但始终引用自己的触发消息。</span></div>
        <button class="btn primary large" type="button" :disabled="saving" @click="saveProfile">{{ saving ? '保存中…' : '保存 AI 配置' }}</button>
      </section>

      <section class="workspace-grid">
        <article class="card section-card">
          <div class="section-head"><div><h2>身份测试</h2><p>只调用 DeepSeek，不会向 QQ 用户发送。</p></div></div>
          <textarea v-model="testPrompt" class="input textarea" rows="4"></textarea>
          <button class="btn primary" type="button" :disabled="testing || !testPrompt.trim()" @click="testProfile">{{ testing ? '生成中…' : '测试回复' }}</button>
          <pre v-if="testResult" class="test-result">{{ testResult }}</pre>
        </article>

        <article class="card section-card jobs-card">
          <div class="section-head"><div><h2>最近 AI 任务</h2><p>持久化任务可防止重复回复，并保证同一联系人按顺序执行。</p></div></div>
          <div v-if="!status?.jobs.length" class="muted">还没有 AI 回复任务。</div>
          <div v-else class="job-list">
            <div v-for="job in status.jobs" :key="job.id" class="job-row">
              <div class="job-main"><span class="job-state" :class="job.status">{{ jobLabel(job.status) }}</span><strong>{{ job.trigger_content || '空消息' }}</strong><small>{{ formatTime(job.created_at) }} · {{ job.model || profile.model }}</small></div>
              <div class="job-meta"><span v-if="job.total_tokens">{{ job.total_tokens }} tokens</span><span v-if="job.delivery_mode">{{ job.delivery_mode }}</span><span v-if="job.error" class="job-error">{{ job.error }}</span></div>
            </div>
          </div>
        </article>
      </section>
    </template>
  </div>
</template>

<style scoped>
.ai-page { padding: 30px; max-width: 1500px; margin: 0 auto; }
.page-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; margin-bottom: 22px; }
.eyebrow { color: var(--accent); font-size: 10px; font-weight: 800; letter-spacing: .13em; }
h1 { margin: 7px 0 6px; font-size: clamp(24px, 3vw, 36px); }
.page-head p, .section-head p { margin: 0; color: var(--ink-4); line-height: 1.6; }
.head-actions { display: flex; gap: 10px; align-items: center; }
.bot-select { min-width: 280px; }
.card { background: #fff; border: 1px solid var(--line); border-radius: 20px; box-shadow: var(--shadow-sm); }
.alert { padding: 12px 15px; border-radius: 14px; margin: 0 0 16px; }
.alert.error { color: #b42318; background: #fff1f0; border: 1px solid #ffccc7; }
.alert.success { color: #067647; background: #ecfdf3; border: 1px solid #abefc6; }
.status-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-bottom: 16px; }
.metric { padding: 18px; }
.metric span, .metric small { display: block; color: var(--ink-4); }
.metric strong { display: block; margin: 8px 0; font-size: 24px; }
.section-card { padding: 22px; margin-bottom: 16px; }
.section-head { display: flex; justify-content: space-between; gap: 20px; align-items: flex-start; margin-bottom: 18px; }
.section-head h2 { margin: 0 0 5px; font-size: 18px; }
.pill { padding: 6px 10px; border-radius: 999px; font-size: 11px; font-weight: 750; }
.pill.ok { color: #067647; background: #ecfdf3; }
.pill.warn { color: #b54708; background: #fffaeb; }
.credential-row { display: grid; grid-template-columns: minmax(220px, 1fr) auto auto auto; gap: 10px; }
.form-grid { display: grid; gap: 15px; }
.form-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.field { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.field > span { color: var(--ink-3); font-size: 12px; font-weight: 700; }
.full { grid-column: 1 / -1; }
.textarea { resize: vertical; line-height: 1.6; }
.check-field, .switch-line { display: inline-flex; align-items: center; gap: 9px; color: var(--ink-2); font-size: 13px; font-weight: 650; }
.check-field.inline { margin-top: 14px; }
.reply-options { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.choice { position: relative; display: grid; gap: 6px; padding: 16px; border: 1px solid var(--line); border-radius: 16px; cursor: pointer; }
.choice.active { border-color: var(--accent); background: var(--accent-soft); }
.choice input { position: absolute; right: 14px; top: 14px; }
.choice span { color: var(--ink-4); font-size: 12px; line-height: 1.5; padding-right: 20px; }
.asset-list { display: grid; gap: 10px; }
.asset-row { display: grid; grid-template-columns: 140px 160px minmax(180px, .8fr) minmax(260px, 1.4fr) auto; gap: 8px; align-items: center; }
.asset-url { min-width: 0; }
.actions-card { display: flex; justify-content: space-between; align-items: center; gap: 20px; padding: 18px 22px; margin-bottom: 16px; }
.actions-card strong, .actions-card span { display: block; }
.actions-card span { margin-top: 4px; color: var(--ink-4); font-size: 12px; }
.large { min-width: 160px; }
.workspace-grid { display: grid; grid-template-columns: minmax(320px, .8fr) minmax(420px, 1.2fr); gap: 16px; }
.test-result { margin: 14px 0 0; padding: 16px; border-radius: 14px; background: #f7f7f8; white-space: pre-wrap; line-height: 1.65; max-height: 360px; overflow: auto; }
.job-list { display: grid; gap: 9px; max-height: 520px; overflow: auto; padding-right: 4px; }
.job-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; padding: 12px; border: 1px solid var(--line); border-radius: 14px; }
.job-main { min-width: 0; }
.job-main strong { display: block; margin: 5px 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.job-main small { color: var(--ink-4); }
.job-state { display: inline-flex; padding: 3px 7px; border-radius: 999px; font-size: 10px; font-weight: 750; background: #f2f4f7; }
.job-state.completed { color: #067647; background: #ecfdf3; }
.job-state.failed { color: #b42318; background: #fff1f0; }
.job-state.running { color: #175cd3; background: #eff8ff; }
.job-meta { display: flex; flex-direction: column; align-items: flex-end; gap: 5px; color: var(--ink-4); font-size: 10px; max-width: 220px; }
.job-error { color: #b42318; text-align: right; overflow-wrap: anywhere; }
.muted { color: var(--ink-4); font-size: 12px; line-height: 1.6; }
.empty { padding: 42px; text-align: center; }
@media (max-width: 1100px) {
  .asset-row { grid-template-columns: 1fr 1fr; }
  .asset-url { grid-column: 1 / -1; }
  .workspace-grid { grid-template-columns: 1fr; }
}
@media (max-width: 760px) {
  .ai-page { padding: 20px 14px; }
  .page-head, .section-head, .actions-card { flex-direction: column; align-items: stretch; }
  .head-actions, .credential-row { display: grid; grid-template-columns: 1fr; }
  .bot-select { min-width: 0; }
  .status-grid, .form-grid.two, .reply-options { grid-template-columns: 1fr; }
  .full { grid-column: auto; }
  .asset-row { grid-template-columns: 1fr; }
  .asset-url { grid-column: auto; }
  .job-row { grid-template-columns: 1fr; }
  .job-meta { align-items: flex-start; max-width: none; }
}
</style>
