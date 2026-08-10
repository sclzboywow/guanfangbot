<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  api,
  type Bot,
  type GroupVerificationSession,
  type GroupVerificationStatus,
} from '@/services/api'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const status = ref<GroupVerificationStatus | null>(null)
const enabled = ref(false)
const verificationMode = ref<'math' | 'manual_mute'>('math')
const minOperand = ref(1)
const maxOperand = ref(20)
const verificationTimeoutMinutes = ref(3)
const maxWrongAttempts = ref(3)
const failureAction = ref<'mute' | 'retract_only'>('mute')
const failureMuteMinutes = ref(1440)
const successMessage = ref('验证通过，你现在可以正常发言。')
const manualReviewMessage = ref('新成员正在等待管理员审核，审核通过后恢复发言。')
const loading = ref(false)
const saving = ref(false)
const actionId = ref('')
const filter = ref<'all' | 'pending' | 'verified' | 'failed' | 'removed'>('pending')
const filters = [
  { key: 'pending' as const, label: '等待' },
  { key: 'verified' as const, label: '已通过' },
  { key: 'failed' as const, label: '验证失败' },
  { key: 'removed' as const, label: '已结束' },
  { key: 'all' as const, label: '全部' },
]
const message = ref('')
const error = ref('')

const currentBot = computed(() => bots.value.find(bot => bot.id === botId.value) || null)
const filteredSessions = computed(() => {
  const sessions = status.value?.sessions || []
  return filter.value === 'all' ? sessions : sessions.filter(item => item.status === filter.value)
})

function formatTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function shortId(value: string) {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value
}

function statusText(value: GroupVerificationSession['status']) {
  if (value === 'pending') return '等待验证'
  if (value === 'verified') return '已通过'
  if (value === 'failed') return '失败并禁言'
  return '已结束'
}

function actionText(action: string) {
  const labels: Record<string, string> = {
    send_question: '发送验证题',
    retract_message: '撤回未验证消息',
    verification_passed: '用户验证通过',
    manual_verify: '管理员手动通过',
    manual_close: '管理员结束验证',
    verification_unmute: '解除验证来源禁言',
    send_manual_review_notice: '发送人工审核提示',
    member_add_missing_identity: '入群事件字段缺失',
  }
  return labels[action] || action
}

async function loadStatus() {
  if (!botId.value) {
    status.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await api.groupVerificationStatus(botId.value)
    status.value = result
    enabled.value = result.settings.enabled
    verificationMode.value = result.settings.verification_mode
    minOperand.value = result.settings.min_operand
    maxOperand.value = result.settings.max_operand
    verificationTimeoutMinutes.value = result.settings.verification_timeout_minutes
    maxWrongAttempts.value = result.settings.max_wrong_attempts
    failureAction.value = result.settings.failure_action
    failureMuteMinutes.value = result.settings.failure_mute_minutes
    successMessage.value = result.settings.success_message
    manualReviewMessage.value = result.settings.manual_review_message
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function saveSettings() {
  if (!botId.value) return
  saving.value = true
  error.value = ''
  message.value = ''
  try {
    status.value = await api.updateGroupVerificationSettings(botId.value, {
      enabled: enabled.value,
      verification_mode: verificationMode.value,
      min_operand: Number(minOperand.value),
      max_operand: Number(maxOperand.value),
      verification_timeout_minutes: Number(verificationTimeoutMinutes.value),
      max_wrong_attempts: Number(maxWrongAttempts.value),
      failure_action: failureAction.value,
      failure_mute_minutes: Number(failureMuteMinutes.value),
      success_message: successMessage.value,
      manual_review_message: manualReviewMessage.value,
    })
    successMessage.value = status.value.settings.success_message
    message.value = enabled.value
      ? '入群验证已启用；请确认 QQ 管理端已开通三个必需事件，并将机器人设为群管理员。'
      : '入群验证已关闭。现有记录保留，但不会继续拦截新消息。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function runAction(session: GroupVerificationSession, action: 'verify' | 'reset' | 'close') {
  if (action === 'close' && !confirm('确认结束这条验证记录？结束后该成员消息不会再被自动撤回。')) return
  actionId.value = session.id
  error.value = ''
  message.value = ''
  try {
    if (action === 'verify') status.value = await api.verifyGroupMember(session.id)
    if (action === 'reset') status.value = await api.resetGroupVerification(session.id)
    if (action === 'close') status.value = await api.closeGroupVerification(session.id)
    message.value = action === 'verify' ? '已手动通过并释放验证来源禁言' : action === 'reset' ? '已按当前模式重新开始验证' : '验证记录已结束并释放验证来源禁言'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    actionId.value = ''
  }
}

watch(botId, loadStatus)

onMounted(async () => {
  try {
    bots.value = await api.listBots()
    const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
    botId.value = bots.value.some(item => item.id === preferred) ? preferred : (bots.value[0]?.id || '')
    if (botId.value) await loadStatus()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载机器人失败'
  }
})
</script>

<template>
  <section class="page verification-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">入群验证</h1>
        <p class="page-sub">兼容入群后验证：可选择数学题失败后禁言，或入群立即禁言并由管理员审核。</p>
      </div>
      <button class="btn primary" :disabled="saving || !botId" @click="saveSettings">
        {{ saving ? '保存中…' : '保存设置' }}
      </button>
    </div>

    <div v-if="!bots.length" class="card empty">暂无机器人，请先添加机器人。</div>
    <template v-else>
      <div class="field selector">
        <label>当前机器人</label>
        <select v-model="botId" class="select">
          <option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }} · {{ bot.app_id }}</option>
        </select>
      </div>

      <div v-if="loading" class="card loading-card">正在加载验证状态…</div>
      <template v-else-if="status">
        <section class="card official-choice"><div><strong>推荐：入群前使用QQ官方审批</strong><span>成员未进入群前完成审核，无需禁言或撤回；本页保留给需要入群后处理的群。</span></div><RouterLink :to="`/group-management?bot=${botId}`" class="btn primary">打开官方群审批</RouterLink></section>
        <div class="summary-grid">
          <section class="card summary-card">
            <span>功能状态</span>
            <strong :class="enabled ? 'good' : 'muted'">{{ enabled ? '已启用' : '未启用' }}</strong>
            <small>对该机器人的所有群生效</small>
          </section>
          <section class="card summary-card">
            <span>等待验证</span>
            <strong class="warn">{{ status.counts.pending }}</strong>
            <small>{{ verificationMode === 'manual_mute' ? '等待管理员审核并保持禁言' : '等待答题或管理员处理' }}</small>
          </section>
          <section class="card summary-card">
            <span>已通过</span>
            <strong class="good">{{ status.counts.verified }}</strong>
            <small>通过后恢复正常发言</small>
          </section>
          <section class="card summary-card">
            <span>验证失败</span>
            <strong class="danger-text">{{ status.counts.failed }}</strong>
            <small>已由QQ官方禁言；结束记录 {{ status.counts.removed }}</small>
          </section>
        </div>

        <div class="layout">
          <div class="main-column">
            <section class="card panel settings-panel">
              <div class="section-head">
                <div>
                  <h2 class="section-title">验证规则</h2>
                  <p class="section-sub">先选择适合本群的验证方式；设置只影响后续新入群成员，旧记录不会突然批量禁言。</p>
                </div>
                <label class="switch-row">
                  <input v-model="enabled" type="checkbox" />
                  <span>{{ enabled ? '已启用' : '已关闭' }}</span>
                </label>
              </div>

              <div class="mode-cards"><label :class="{selected:verificationMode==='math'}"><input v-model="verificationMode" type="radio" value="math"><b>数学题验证</b><span>成员可以发送答案；错误消息撤回，超时或错误过多后按设置禁言。</span></label><label :class="{selected:verificationMode==='manual_mute'}"><input v-model="verificationMode" type="radio" value="manual_mute"><b>管理员人工审核</b><span>成员入群立即禁言，不要求答题；管理员通过后自动解除验证来源禁言。</span></label></div>

              <div v-if="verificationMode === 'math'" class="number-grid">
                <div class="field">
                  <label>最小数字</label>
                  <input v-model.number="minOperand" class="input" type="number" min="0" max="100" />
                </div>
                <div class="field">
                  <label>最大数字</label>
                  <input v-model.number="maxOperand" class="input" type="number" min="1" max="100" />
                </div>
              </div>

              <div v-if="verificationMode === 'math'" class="number-grid policy-grid">
                <div class="field"><label>验证时限（分钟）</label><input v-model.number="verificationTimeoutMinutes" class="input" type="number" min="1" max="1440"></div>
                <div class="field"><label>最大错误次数</label><input v-model.number="maxWrongAttempts" class="input" type="number" min="1" max="20"></div>
                <div class="field"><label>达到限制后</label><select v-model="failureAction" class="select"><option value="mute">QQ官方禁言</option><option value="retract_only">继续保持等待并撤回</option></select></div>
                <div v-if="failureAction === 'mute'" class="field"><label>禁言时长（分钟）</label><input v-model.number="failureMuteMinutes" class="input" type="number" min="1" max="43200"><small>例如 1440 表示24小时</small></div>
              </div>

              <div v-else class="number-grid policy-grid"><div class="field"><label>人工审核禁言时长（分钟）</label><input v-model.number="failureMuteMinutes" class="input" type="number" min="1" max="43200"><small>管理员提前通过会立即解除；默认24小时</small></div></div>

              <div class="field success-message-field">
                <label>验证成功提示</label>
                <input
                  v-model="successMessage"
                  class="input"
                  type="text"
                  maxlength="200"
                  placeholder="验证通过，你现在可以正常发言。"
                />
                <small>成员答题正确或管理员手动通过后发送，最多 200 字。</small>
              </div>

              <div v-if="verificationMode === 'manual_mute'" class="field success-message-field"><label>人工审核群内提示</label><input v-model="manualReviewMessage" class="input" maxlength="200"><small>入群并成功设置禁言后发送。</small></div>

              <div class="behavior-grid">
                <div><b>无需 @ 机器人</b><span>直接发送纯数字答案</span></div>
                <div><b>统一禁言来源</b><span>验证通过不会误解除广告治理禁言</span></div>
                <div><b>{{ verificationMode === 'math' ? '失败后处理' : '入群立即处理' }}</b><span>{{ verificationMode === 'math' ? (failureAction === 'mute' ? '超时或错误过多后官方禁言' : '继续撤回非正确答案') : 'QQ官方禁言并等待管理员' }}</span></div>
                <div><b>管理员通过</b><span>只释放“入群验证”来源的禁言</span></div>
              </div>

              <div class="preview">
                <span>群内提示示例</span>
                <code>{{ verificationMode === 'math' ? '欢迎加入本群，请先完成验证：8 + 7 = ? 请直接发送数字答案。' : manualReviewMessage }}</code>
              </div>
              <div class="preview">
                <span>验证成功提示预览</span>
                <code>{{ successMessage || '请输入验证成功提示' }}</code>
              </div>
            </section>

            <section class="card panel sessions-panel">
              <div class="section-head sessions-head">
                <div>
                  <h2 class="section-title">成员验证记录</h2>
                  <p class="section-sub">状态、撤回计数和验证禁言来源保存在 SQLite，容器重启后不会丢失。</p>
                </div>
                <div class="filters">
                  <button v-for="item in filters" :key="item.key" type="button" :class="{active:filter === item.key}" @click="filter = item.key">
                    {{ item.label }}
                  </button>
                </div>
              </div>

              <div v-if="!filteredSessions.length" class="empty-list">暂无对应记录。</div>
              <div v-else class="table-wrap">
                <table>
                  <thead><tr><th>成员</th><th>群</th><th>题目</th><th>状态</th><th>撤回</th><th>时间</th><th>操作</th></tr></thead>
                  <tbody>
                    <tr v-for="session in filteredSessions" :key="session.id">
                      <td><strong>{{ session.member_name || shortId(session.member_openid) }}</strong><small class="mono">{{ shortId(session.member_openid) }}</small></td>
                      <td class="mono">{{ shortId(session.group_openid) }}</td>
                      <td><strong>{{ session.question }}</strong><small v-if="session.question !== '等待管理员审核'">答案 {{ session.answer }}</small></td>
                      <td><span class="state" :class="session.status">{{ statusText(session.status) }}</span><small v-if="session.failure_reason">{{ session.failure_reason === 'timeout' ? '验证超时' : '错误次数过多' }}</small><small v-if="session.last_error" class="row-error">{{ session.last_error }}</small></td>
                      <td><strong>{{ session.retracted_messages }}</strong><small>错误 {{ session.wrong_attempts }} 次</small></td>
                      <td><span>{{ formatTime(session.joined_at) }}</span><small v-if="session.deadline_at">截止 {{ formatTime(session.deadline_at) }}</small><small v-if="session.muted_until">禁言至 {{ formatTime(session.muted_until) }}</small><small v-if="session.last_message_at">最后消息 {{ formatTime(session.last_message_at) }}</small></td>
                      <td>
                        <div class="row-actions">
                          <button v-if="session.status === 'pending' || session.status === 'failed'" class="mini good-btn" :disabled="actionId === session.id" @click="runAction(session, 'verify')">通过</button>
                          <button class="mini" :disabled="actionId === session.id" @click="runAction(session, 'reset')">重新开始</button>
                          <button v-if="session.status !== 'removed'" class="mini danger-btn" :disabled="actionId === session.id" @click="runAction(session, 'close')">结束</button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          <aside class="side-column">
            <section class="card panel requirement-panel">
              <h2 class="section-title">开通条件</h2>
              <div v-for="item in status.required_events" :key="item.code" class="requirement-row">
                <code>{{ item.code }}</code>
                <span :class="item.configured ? 'ready' : 'missing'">{{ item.configured ? '已记录' : '未记录' }}</span>
              </div>
              <p>启用功能会自动加入本地事件清单，但仍需前往 QQ 管理端勾选这些事件，并开启普通群消息事件。</p>
              <RouterLink :to="`/events?bot=${botId}`" class="btn full">前往事件配置</RouterLink>
              <div class="admin-warning"><strong>群管理员权限</strong><span>机器人必须在目标群内被设为管理员，才能撤回消息和调用QQ官方成员禁言。</span></div>
            </section>

            <section class="card panel log-panel">
              <div class="section-head"><h2 class="section-title">最近处理</h2><button class="mini" @click="loadStatus">刷新</button></div>
              <div v-if="!status.logs.length" class="empty-list compact">暂无处理日志。</div>
              <div v-for="log in status.logs.slice(0, 20)" :key="log.id" class="log-row">
                <div><strong>{{ actionText(log.action) }}</strong><span :class="log.success ? 'ready' : 'missing'">{{ log.success ? '成功' : '失败' }}</span></div>
                <small>{{ formatTime(log.created_at) }}<template v-if="log.status_code"> · HTTP {{ log.status_code }}</template></small>
              </div>
            </section>
          </aside>
        </div>
      </template>

      <p v-if="message" class="notice ok">{{ message }}</p>
      <p v-if="error" class="notice error">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.verification-page{max-width:1280px}.selector{max-width:480px;margin-bottom:18px}.empty,.loading-card{padding:30px}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}.summary-card{padding:17px}.summary-card span,.summary-card strong,.summary-card small{display:block}.summary-card span{color:var(--ink-4);font-size:11.5px}.summary-card strong{margin-top:7px;font-size:19px}.summary-card small{margin-top:6px;color:var(--ink-4);font-size:11px;line-height:1.45}.good{color:#238541}.warn{color:var(--warn)}.muted{color:var(--ink-4)}.layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:18px;align-items:start}.main-column,.side-column{display:flex;flex-direction:column;gap:18px}.side-column{position:sticky;top:22px}.panel{padding:22px}.section-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.switch-row{display:flex;align-items:center;gap:8px;padding:8px 11px;border:1px solid var(--line);border-radius:999px;font-size:12px;font-weight:700}.switch-row input{accent-color:var(--accent)}.number-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:20px}.behavior-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:18px}.behavior-grid div{padding:13px;border-radius:12px;background:var(--bg-sunken)}.behavior-grid b,.behavior-grid span{display:block}.behavior-grid b{font-size:12px}.behavior-grid span{margin-top:4px;color:var(--ink-4);font-size:10.5px}.preview{margin-top:16px;padding:13px;border:1px dashed var(--accent-border);border-radius:12px;background:var(--accent-soft)}.preview span,.preview code{display:block}.preview span{color:var(--ink-4);font-size:10.5px}.preview code{margin-top:7px;color:var(--ink-2);font:11px/1.55 var(--font-mono);white-space:normal}.sessions-head{align-items:center}.filters{display:flex;gap:5px;flex-wrap:wrap}.filters button,.mini{padding:5px 8px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink-3);font-size:10.5px}.filters button.active{border-color:var(--accent-border);background:var(--accent-soft);color:var(--accent)}.table-wrap{overflow:auto;margin-top:16px}table{width:100%;border-collapse:collapse;font-size:11.5px}th,td{padding:12px 10px;border-top:1px solid var(--line);text-align:left;vertical-align:top}th{color:var(--ink-4);font-size:10px;font-weight:650;white-space:nowrap}td strong,td small,td span{display:block}td small{margin-top:4px;color:var(--ink-4);font-size:9.5px;line-height:1.4}.state{display:inline-block!important;padding:4px 7px;border-radius:999px;font-size:9.5px;font-weight:700}.state.pending{background:rgba(255,149,0,.12);color:var(--warn)}.state.verified{background:rgba(52,199,89,.12);color:#238541}.state.removed{background:rgba(60,60,67,.08);color:var(--ink-4)}.row-error{max-width:180px;color:var(--danger)!important}.row-actions{display:flex;gap:5px;flex-wrap:wrap;min-width:130px}.good-btn{color:#238541}.danger-btn{color:var(--danger)}.empty-list{padding:28px 8px;text-align:center;color:var(--ink-4);font-size:12px}.empty-list.compact{padding:16px 0}.requirement-row{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:11px 0;border-bottom:1px solid var(--line)}.requirement-row code{font-size:9.5px}.ready{color:#238541}.missing{color:var(--danger)}.requirement-panel>p{margin:14px 0;color:var(--ink-4);font-size:11px;line-height:1.55}.full{width:100%;justify-content:center}.admin-warning{margin-top:14px;padding:12px;border-radius:11px;background:rgba(255,149,0,.09)}.admin-warning strong,.admin-warning span{display:block}.admin-warning strong{color:#8a5a00;font-size:11px}.admin-warning span{margin-top:5px;color:#815500;font-size:10.5px;line-height:1.5}.log-row{padding:11px 0;border-top:1px solid var(--line)}.log-row>div{display:flex;align-items:center;justify-content:space-between;gap:8px}.log-row strong{font-size:11px}.log-row span{font-size:9.5px}.log-row small{display:block;margin-top:4px;color:var(--ink-4);font-size:9.5px}.notice{margin-top:14px}.ok{color:#238541}.error{color:var(--danger)}@media(max-width:1050px){.layout{grid-template-columns:1fr}.side-column{position:static;display:grid;grid-template-columns:1fr 1fr}.summary-grid{grid-template-columns:repeat(2,1fr)}}@media(max-width:700px){.summary-grid,.side-column,.number-grid,.behavior-grid{grid-template-columns:1fr}.section-head,.sessions-head{align-items:flex-start;flex-direction:column}.table-wrap{margin-left:-10px;margin-right:-10px}.page-head{padding-right:50px}}
.success-message-field{margin-top:16px}.success-message-field small{display:block;margin-top:6px;color:var(--ink-4);font-size:10.5px}
.official-choice{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:18px;padding:17px;border-color:var(--accent-border);background:var(--accent-soft)}.official-choice strong,.official-choice span{display:block}.official-choice span{margin-top:5px;color:var(--ink-3);font-size:11px}.mode-cards{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:18px}.mode-cards label{padding:14px;border:1px solid var(--line);border-radius:12px;cursor:pointer}.mode-cards label.selected{border-color:var(--accent-border);background:var(--accent-soft)}.mode-cards input{display:none}.mode-cards b,.mode-cards span{display:block}.mode-cards span{margin-top:5px;color:var(--ink-4);font-size:10px;line-height:1.5}.policy-grid small{display:block;margin-top:5px;color:var(--ink-4);font-size:10px}.state.failed{background:rgba(255,59,48,.1);color:var(--danger)}.danger-text{color:var(--danger)}@media(max-width:700px){.official-choice{align-items:flex-start;flex-direction:column}.mode-cards{grid-template-columns:1fr}}
</style>
