<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import {
  api,
  type Bot,
  type GroupModerationMember,
  type GroupModerationSettings,
  type GroupModerationStatus,
} from '@/services/api'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const status = ref<GroupModerationStatus | null>(null)
const settings = ref<GroupModerationSettings | null>(null)
const penaltyText = ref('10, 60, 1440, 10080')
const contentKeywordsText = ref('')
const nicknameKeywordsText = ref('')
const search = ref('')
const memberFilter = ref<'all' | 'blocked' | 'permanent' | 'trusted'>('all')
const loading = ref(false)
const saving = ref(false)
const busyMember = ref('')
const message = ref('')
const error = ref('')

const filteredMembers = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return (status.value?.members || []).filter((member) => {
    if (memberFilter.value === 'blocked' && !isBlocked(member)) return false
    if (memberFilter.value === 'permanent' && !member.permanent) return false
    if (memberFilter.value === 'trusted' && !member.trusted) return false
    if (!keyword) return true
    return [member.member_name, member.member_openid, member.group_openid, member.last_match]
      .some(value => String(value || '').toLowerCase().includes(keyword))
  })
})

function applyStatus(result: GroupModerationStatus) {
  status.value = result
  settings.value = { ...result.settings }
  penaltyText.value = result.settings.penalty_minutes.join(', ')
  contentKeywordsText.value = result.settings.content_keywords.join('\n')
  nicknameKeywordsText.value = result.settings.nickname_keywords.join('\n')
}

function parseWords(value: string) {
  return Array.from(new Set(value.split(/[\n,，]+/).map(item => item.trim()).filter(Boolean)))
}

function parsePenaltyMinutes() {
  const values = penaltyText.value.split(/[,，\s]+/).filter(Boolean).map(Number)
  if (!values.length || values.some(value => !Number.isInteger(value) || value < 1)) {
    throw new Error('阶梯时长必须填写正整数分钟，例如 10, 60, 1440, 10080')
  }
  return values
}

function formatTime(value?: string | null) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN')
}

function isBlocked(member: GroupModerationMember) {
  if (member.trusted) return false
  if (member.permanent) return true
  if (!member.blocked_until) return false
  return new Date(member.blocked_until).getTime() > Date.now()
}

function memberState(member: GroupModerationMember) {
  if (member.trusted) return '白名单'
  if (member.permanent) return '长期治理'
  if (isBlocked(member)) return `${settings.value?.use_official_mute ? '禁言' : '撤回'}至 ${formatTime(member.blocked_until)}`
  return member.strike_count ? '处罚已结束' : '观察记录'
}

function ruleText(rule: string) {
  const map: Record<string, string> = {
    mobile_phone: '手机号',
    landline_phone: '座机/400 电话',
    wechat: '微信联系方式',
    content_keyword: '内容广告词',
    nickname_keyword: '昵称广告词',
    merged_message: '合并消息',
    group_card: '群名片',
    active_penalty: '处罚期发言',
  }
  return map[rule] || rule || '—'
}

async function load() {
  if (!botId.value) return
  loading.value = true
  error.value = ''
  try {
    applyStatus(await api.groupModerationStatus(botId.value))
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  if (!botId.value || !settings.value) return
  saving.value = true
  message.value = ''
  error.value = ''
  try {
    const payload = {
      enabled: settings.value.enabled,
      detect_mobile: settings.value.detect_mobile,
      detect_landline: settings.value.detect_landline,
      detect_wechat: settings.value.detect_wechat,
      detect_content_keywords: settings.value.detect_content_keywords,
      detect_nickname_keywords: settings.value.detect_nickname_keywords,
      exempt_admins: settings.value.exempt_admins,
      use_official_mute: settings.value.use_official_mute,
      retract_merged_messages: settings.value.retract_merged_messages,
      retract_group_cards: settings.value.retract_group_cards,
      penalty_minutes: parsePenaltyMinutes(),
      permanent_after: Number(settings.value.permanent_after),
      escalation_cooldown_seconds: Number(settings.value.escalation_cooldown_seconds),
      warning_cooldown_seconds: Number(settings.value.warning_cooldown_seconds),
      content_keywords: parseWords(contentKeywordsText.value),
      nickname_keywords: parseWords(nicknameKeywordsText.value),
    }
    applyStatus(await api.updateGroupModerationSettings(botId.value, payload))
    message.value = '群消息治理配置已保存'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '保存失败'
  } finally {
    saving.value = false
  }
}

async function memberAction(member: GroupModerationMember, action: 'release' | 'reset' | 'permanent' | 'trust' | 'untrust') {
  busyMember.value = member.id
  message.value = ''
  error.value = ''
  try {
    let result: GroupModerationStatus
    if (action === 'release') result = await api.releaseModeratedMember(member.id, false)
    else if (action === 'reset') result = await api.releaseModeratedMember(member.id, true)
    else if (action === 'permanent') result = await api.makeModeratedMemberPermanent(member.id)
    else if (action === 'trust') result = await api.trustModeratedMember(member.id)
    else result = await api.untrustModeratedMember(member.id)
    applyStatus(result)
    message.value = '成员治理状态已更新'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    busyMember.value = ''
  }
}

watch(botId, load)
onMounted(async () => {
  try {
    bots.value = await api.listBots()
    const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
    botId.value = bots.value.some(bot => bot.id === preferred) ? preferred : (bots.value[0]?.id || '')
    if (botId.value) await load()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载失败'
  }
})
</script>

<template>
  <section class="page moderation-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">群消息治理</h1>
        <p class="page-sub">识别广告联系方式和广告昵称，撤回违规消息后优先调用QQ官方成员禁言。</p>
      </div>
      <div class="page-actions">
        <button class="btn" :disabled="loading || !botId" @click="load">刷新</button>
        <button class="btn primary" :disabled="saving || !settings" @click="save">{{ saving ? '保存中…' : '保存配置' }}</button>
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

      <div v-if="status && settings" class="content">
        <div class="summary-grid">
          <section class="card summary"><span>治理状态</span><strong :class="settings.enabled ? 'good' : 'muted'">{{ settings.enabled ? '已启用' : '未启用' }}</strong><small>依赖 GROUP_MESSAGE_CREATE</small></section>
          <section class="card summary"><span>当前治理</span><strong>{{ status.counts.blocked }}</strong><small>{{ settings.use_official_mute ? '优先使用QQ官方禁言' : '兼容连续撤回模式' }}</small></section>
          <section class="card summary"><span>长期治理</span><strong class="danger-text">{{ status.counts.permanent }}</strong><small>官方禁言到期后按规则续期</small></section>
          <section class="card summary"><span>白名单</span><strong>{{ status.counts.trusted }}</strong><small>不参与自动检测</small></section>
        </div>

        <div v-if="!status.requirements_ready" class="warning">需要在 QQ 管理端开通 GROUP_MESSAGE_CREATE。启用本功能只会同步本地事件清单，不能代替 QQ 管理端授权。</div>

        <div class="layout">
          <div class="main-column">
            <section class="card panel">
              <div class="section-head"><div><h2 class="section-title">检测规则</h2><p class="section-sub">管理员默认豁免。联系方式和关键词均可独立关闭。</p></div><label class="switch"><input v-model="settings.enabled" type="checkbox"><span>{{ settings.enabled ? '已启用' : '已停用' }}</span></label></div>
              <div class="toggle-grid">
                <label><input v-model="settings.detect_mobile" type="checkbox"> 手机号</label>
                <label><input v-model="settings.detect_landline" type="checkbox"> 座机与 400/800 电话</label>
                <label><input v-model="settings.detect_wechat" type="checkbox"> 微信联系方式</label>
                <label><input v-model="settings.detect_content_keywords" type="checkbox"> 消息广告词</label>
                <label><input v-model="settings.detect_nickname_keywords" type="checkbox"> 昵称广告词</label>
                <label><input v-model="settings.retract_merged_messages" type="checkbox"> 合并消息</label>
                <label><input v-model="settings.retract_group_cards" type="checkbox"> 群名片</label>
                <label><input v-model="settings.exempt_admins" type="checkbox"> 豁免群主和管理员</label>
                <label><input v-model="settings.use_official_mute" type="checkbox"> 使用QQ官方禁言</label>
              </div>
              <div class="keyword-grid">
                <div class="field"><label>消息广告词</label><textarea v-model="contentKeywordsText" class="textarea" rows="6" placeholder="每行或逗号分隔"></textarea></div>
                <div class="field"><label>昵称广告词</label><textarea v-model="nicknameKeywordsText" class="textarea" rows="6" placeholder="每行或逗号分隔"></textarea></div>
              </div>
            </section>

            <section class="card panel">
              <h2 class="section-title">阶梯处罚</h2>
              <p class="section-sub">默认 10 分钟 → 1 小时 → 24 小时 → 7 天 → 第 5 次长期治理。启用官方群禁言后，仅撤回触发消息，其余发言由QQ直接限制。</p>
              <div class="form-grid">
                <div class="field wide"><label>各级时长（分钟）</label><input v-model="penaltyText" class="input mono"><small>例如：10, 60, 1440, 10080</small></div>
                <div class="field"><label>第几次长期治理</label><input v-model.number="settings.permanent_after" class="input" type="number" min="2" max="20"></div>
                <div class="field"><label>升级冷却（秒）</label><input v-model.number="settings.escalation_cooldown_seconds" class="input" type="number" min="0" max="3600"></div>
                <div class="field"><label>警告冷却（秒）</label><input v-model.number="settings.warning_cooldown_seconds" class="input" type="number" min="0" max="3600"></div>
              </div>
              <div class="preview">群内警告示例：<code>警告：某成员触发群广告治理，已由QQ官方禁言10分钟。</code></div>
            </section>

            <section class="card panel">
              <div class="table-head"><div><h2 class="section-title">成员治理状态</h2><p class="section-sub">状态按机器人、群和成员分别记录。</p></div><div class="filters"><select v-model="memberFilter" class="select small"><option value="all">全部</option><option value="blocked">正在禁言</option><option value="permanent">长期治理</option><option value="trusted">白名单</option></select><input v-model="search" class="input small" placeholder="搜索昵称、OpenID 或命中词"></div></div>
              <div v-if="!filteredMembers.length" class="empty-row">暂无匹配记录。</div>
              <div v-for="member in filteredMembers" :key="member.id" class="member-row">
                <div class="member-main"><strong>{{ member.member_name || '未获取昵称' }}</strong><small class="mono">{{ member.member_openid }}</small><small class="mono">群 {{ member.group_openid }}</small></div>
                <div class="member-stat"><span :class="{ danger: member.permanent, active: isBlocked(member) }">{{ memberState(member) }}</span><small>命中 {{ member.strike_count }} 次 · 撤回 {{ member.retracted_messages }} 条</small><small>{{ ruleText(member.last_rule) }} {{ member.last_match || '' }}</small></div>
                <div class="member-actions">
                  <button class="mini" :disabled="busyMember === member.id" @click="memberAction(member, 'release')">解除</button>
                  <button class="mini" :disabled="busyMember === member.id" @click="memberAction(member, 'reset')">解除并清零</button>
                  <button v-if="!member.permanent" class="mini danger" :disabled="busyMember === member.id" @click="memberAction(member, 'permanent')">长期治理</button>
                  <button v-if="!member.trusted" class="mini" :disabled="busyMember === member.id" @click="memberAction(member, 'trust')">白名单</button>
                  <button v-else class="mini" :disabled="busyMember === member.id" @click="memberAction(member, 'untrust')">取消白名单</button>
                </div>
              </div>
            </section>
          </div>

          <aside class="card panel logs">
            <h2 class="section-title">最近治理日志</h2>
            <p class="section-sub">记录命中、撤回和警告结果。</p>
            <div v-if="!status.logs.length" class="empty-row">暂无日志。</div>
            <div v-for="log in status.logs" :key="log.id" class="log-row">
              <div><strong>{{ ruleText(log.rule) }}</strong><span :class="log.success ? 'ok' : 'fail'">{{ log.success ? '成功' : '失败' }}</span></div>
              <small>{{ log.action }} · {{ formatTime(log.created_at) }}</small>
              <p v-if="log.matched">命中：{{ log.matched }}</p>
              <p v-if="log.message_excerpt">内容：{{ log.message_excerpt }}</p>
              <p v-if="!log.success">{{ log.status_code || '' }} {{ log.detail }}</p>
            </div>
          </aside>
        </div>
      </div>

      <div v-if="loading" class="card loading">正在加载…</div>
      <p v-if="message" class="notice ok">{{ message }}</p>
      <p v-if="error" class="notice error">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.moderation-page{max-width:1280px}.selector{max-width:500px;margin-bottom:18px}.empty,.loading{padding:32px;text-align:center}.summary-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:14px}.summary{padding:17px}.summary span,.summary strong,.summary small{display:block}.summary span{color:var(--ink-4);font-size:11px}.summary strong{margin-top:7px;font-size:20px}.summary small{margin-top:5px;color:var(--ink-4);font-size:10.5px}.good{color:#238541}.muted{color:var(--ink-4)}.danger-text{color:var(--danger)}.warning{margin-bottom:16px;padding:13px 15px;border:1px solid rgba(255,149,0,.25);border-radius:13px;background:rgba(255,149,0,.08);color:#815500;font-size:12px}.layout{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:18px;align-items:start}.main-column{display:flex;flex-direction:column;gap:18px}.panel{padding:22px}.section-head,.table-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.switch{display:flex;align-items:center;gap:8px;padding:8px 11px;border:1px solid var(--line);border-radius:12px;font-size:12px}.switch input,.toggle-grid input{accent-color:var(--accent)}.toggle-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:18px}.toggle-grid label{padding:11px;border:1px solid var(--line);border-radius:11px;font-size:12px}.keyword-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:18px}.textarea{width:100%;resize:vertical;padding:11px 12px;border:1px solid var(--line);border-radius:11px;background:white;color:var(--ink);font:inherit;line-height:1.5}.form-grid{display:grid;grid-template-columns:2fr 1fr 1fr;gap:14px;margin-top:18px}.field.wide{grid-column:span 2}.field small{color:var(--ink-4);font-size:10.5px}.preview{margin-top:16px;padding:12px;border-radius:11px;background:var(--bg-sunken);color:var(--ink-3);font-size:11px;line-height:1.55}.preview code{color:var(--ink)}.filters{display:flex;gap:8px}.small{width:190px}.select.small{width:130px}.empty-row{padding:28px 0;text-align:center;color:var(--ink-4)}.member-row{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(0,1fr) auto;gap:14px;align-items:center;padding:14px 0;border-top:1px solid var(--line)}.member-main strong,.member-main small,.member-stat span,.member-stat small{display:block}.member-main small,.member-stat small{margin-top:4px;color:var(--ink-4);font-size:10px}.member-stat span{font-size:12px;font-weight:700}.member-stat span.active{color:var(--warn)}.member-stat span.danger{color:var(--danger)}.member-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px;max-width:230px}.mini{padding:6px 8px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink-2);font-size:10px}.mini.danger{color:var(--danger)}.logs{position:sticky;top:22px;max-height:calc(100vh - 44px);overflow:auto}.log-row{padding:12px 0;border-top:1px solid var(--line)}.log-row div{display:flex;justify-content:space-between;gap:8px}.log-row strong{font-size:11.5px}.log-row span{font-size:9.5px;font-weight:700}.log-row .ok{color:#238541}.log-row .fail{color:var(--danger)}.log-row small,.log-row p{display:block;margin:4px 0 0;color:var(--ink-4);font-size:9.5px;line-height:1.45;word-break:break-all}.notice{margin-top:12px}.notice.ok{color:#238541}.notice.error{color:var(--danger)}@media(max-width:1050px){.layout{grid-template-columns:1fr}.logs{position:static;max-height:none}.summary-grid{grid-template-columns:1fr 1fr}}@media(max-width:760px){.toggle-grid{grid-template-columns:1fr 1fr}.keyword-grid{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.field.wide{grid-column:auto}.table-head{flex-direction:column}.filters{width:100%}.filters .small{flex:1;width:auto}.member-row{grid-template-columns:1fr}.member-actions{justify-content:flex-start;max-width:none}}@media(max-width:520px){.summary-grid,.toggle-grid{grid-template-columns:1fr}.filters{flex-direction:column}.select.small{width:100%}}
</style>
