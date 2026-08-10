<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import {
  api,
  type ApprovalStrategy,
  type Bot,
  type GroupManagementStatus,
  type GroupMuteSetting,
  type OfficialJoinRequest,
} from '@/services/api'

type Tab = 'requests' | 'strategies' | 'mutes' | 'legacy'

const route = useRoute()
const bots = ref<Bot[]>([])
const botId = ref('')
const status = ref<GroupManagementStatus | null>(null)
const strategies = ref<ApprovalStrategy[]>([])
const muteSetting = ref<GroupMuteSetting | null>(null)
const tab = ref<Tab>('requests')
const loading = ref(false)
const busy = ref('')
const message = ref('')
const error = ref('')

const selectedGroup = ref('')
const requestFilter = ref<'pending' | 'all'>('pending')
const rejectReasons = ref<Record<string, string>>({})
const rejectBlacklists = ref<Record<string, boolean>>({})

const createMode = ref<'group_openids' | 'group_ids'>('group_openids')
const createGroups = ref('')
const createEnabled = ref(true)
const createExpire = ref('')
const createRemark = ref('')

const editingStrategy = ref('')
const strategyGroupOp = ref<'add' | 'del'>('add')
const strategyGroupMode = ref<'group_openids' | 'group_ids'>('group_openids')
const strategyGroupValues = ref('')
const strategyRemark = ref('')
const strategyExpire = ref('')

const whitelistStrategyId = ref('')
const whitelistOp = ref<'add' | 'del'>('add')
const whitelistUsers = ref('')

const muteGroup = ref('')
const muteMember = ref('')
const muteMode = ref<'single' | 'batch'>('single')
const muteOp = ref<'add' | 'update'>('add')
const muteDuration = ref('60')
const muteCustomEnd = ref('')

const pendingCount = computed(() => status.value?.join_requests.filter(item => item.status === 'pending').length || 0)
const eventStateClass = computed(() => status.value?.requirements_ready ? 'ready' : 'warn')
const eventStateLabel = computed(() => status.value?.requirements_ready ? '入群申请事件已记录' : '还未加入事件清单')
const displayedRequests = computed(() => {
  const items = status.value?.join_requests || []
  return requestFilter.value === 'pending' ? items.filter(item => item.status === 'pending') : items
})

function splitValues(value: string): string[] {
  return [...new Set(value.split(/[\s,，;；]+/).map(item => item.trim()).filter(Boolean))]
}

function shortId(value: string): string {
  if (!value) return '-'
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value
}

function formatTime(value?: string | null): string {
  if (!value) return '-'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString('zh-CN', { hour12: false })
}

function requestStatus(item: OfficialJoinRequest): string {
  if (item.status === 'pending') return '等待审批'
  if (item.status === 'approved') return '已通过'
  if (item.status === 'declined') return '已拒绝'
  if (item.status === 'auto_approved') return '策略自动通过'
  return item.status
}

function chooseKnownGroup(groupOpenid: string) {
  selectedGroup.value = groupOpenid
  muteGroup.value = groupOpenid
}

function localToRfc3339(value: string): string | null {
  if (!value) return null
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString()
}

function toLocalDateTime(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const offset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function expireAtFromMuteForm(): string | null {
  if (muteDuration.value === 'custom') return localToRfc3339(muteCustomEnd.value)
  const minutes = Number(muteDuration.value)
  if (!Number.isFinite(minutes) || minutes < 1) return null
  return new Date(Date.now() + minutes * 60_000).toISOString()
}

function clearNotice() {
  message.value = ''
  error.value = ''
}

async function loadStatus() {
  if (!botId.value) return
  loading.value = true
  clearNotice()
  try {
    status.value = await api.groupManagementStatus(botId.value)
    if (!selectedGroup.value && status.value.groups.length) selectedGroup.value = status.value.groups[0].group_openid
    if (!muteGroup.value && status.value.groups.length) muteGroup.value = status.value.groups[0].group_openid
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载群管理数据失败'
  } finally {
    loading.value = false
  }
}

async function loadStrategies() {
  if (!botId.value) return
  try {
    const result = await api.listApprovalStrategies(botId.value)
    strategies.value = result.strategies
    if (!whitelistStrategyId.value && strategies.value.length) whitelistStrategyId.value = strategies.value[0].strategy_id
  } catch (e) {
    strategies.value = []
    error.value = e instanceof Error ? e.message : '读取自动审批策略失败'
  }
}

async function reloadAll() {
  await loadStatus()
  await loadStrategies()
  muteSetting.value = null
}

async function enableEvent() {
  busy.value = 'event'
  clearNotice()
  try {
    status.value = await api.enableGroupManagementEvents(botId.value)
    message.value = '已加入 GROUP_JOIN_REQUEST 事件清单；还需在QQ开放平台确认该事件已勾选。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '启用事件失败'
  } finally {
    busy.value = ''
  }
}

async function syncRequests() {
  if (!selectedGroup.value.trim()) {
    error.value = '请选择已识别的群，或粘贴群 OpenID。'
    return
  }
  busy.value = 'sync'
  clearNotice()
  try {
    const result = await api.syncJoinRequests(botId.value, selectedGroup.value.trim())
    status.value = result.status
    message.value = `同步完成：共读取 ${result.sync.pages} 页，更新 ${result.sync.synced} 条申请。`
  } catch (e) {
    error.value = e instanceof Error ? e.message : '同步申请失败'
  } finally {
    busy.value = ''
  }
}

async function decide(item: OfficialJoinRequest, op: 'approve' | 'decline') {
  if (op === 'approve' && !confirm(`确认通过“${item.username || shortId(item.member_openid)}”的入群申请？`)) return
  if (op === 'decline' && !confirm(`确认拒绝“${item.username || shortId(item.member_openid)}”的入群申请？`)) return
  busy.value = item.join_request_id
  clearNotice()
  try {
    const result = await api.decideJoinRequest(botId.value, {
      group_openid: item.group_openid,
      member_openid: item.member_openid,
      join_request_id: item.join_request_id,
      op,
      reject_reason: op === 'decline' ? (rejectReasons.value[item.join_request_id] || '') : '',
      add_to_member_blacklist: op === 'decline' && Boolean(rejectBlacklists.value[item.join_request_id]),
    })
    status.value = result.status
    message.value = op === 'approve' ? '已通过该入群申请。' : '已拒绝该入群申请。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '审批失败'
  } finally {
    busy.value = ''
  }
}

async function createStrategy() {
  const groups = splitValues(createGroups.value)
  if (!groups.length) {
    error.value = createMode.value === 'group_ids' ? '请填写至少一个QQ群号。' : '请填写至少一个群 OpenID。'
    return
  }
  busy.value = 'create-strategy'
  clearNotice()
  try {
    await api.createApprovalStrategy(botId.value, {
      group_mode: createMode.value,
      groups,
      is_enable: createEnabled.value ? 'on' : 'off',
      expire_at: localToRfc3339(createExpire.value),
      remark: createRemark.value.trim(),
    })
    createGroups.value = ''
    createRemark.value = ''
    createExpire.value = ''
    await loadStrategies()
    message.value = '自动审批策略已创建。接下来可为它添加白名单QQ号。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '创建策略失败'
  } finally {
    busy.value = ''
  }
}

async function toggleStrategy(item: ApprovalStrategy) {
  busy.value = `toggle-${item.strategy_id}`
  clearNotice()
  try {
    await api.updateApprovalStrategy(botId.value, item.strategy_id, { is_enable: item.is_enable === 'on' ? 'off' : 'on' })
    await loadStrategies()
    message.value = item.is_enable === 'on' ? '策略已停用。' : '策略已启用。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '修改策略失败'
  } finally {
    busy.value = ''
  }
}

async function executeStrategy(item: ApprovalStrategy) {
  if (item.is_enable !== 'on') {
    error.value = '该策略目前已关闭，请先启用再执行扫描。'
    return
  }
  if (!confirm('将扫描策略关联群内的现有申请，命中白名单的申请会自动通过。确认执行？')) return
  busy.value = `execute-${item.strategy_id}`
  clearNotice()
  try {
    const result = await api.executeApprovalStrategy(botId.value, item.strategy_id)
    message.value = result.message
  } catch (e) {
    error.value = e instanceof Error ? e.message : '提交扫描失败'
  } finally {
    busy.value = ''
  }
}

async function removeStrategy(item: ApprovalStrategy) {
  if (!confirm(`确认删除策略 ${item.strategy_id}？删除后无法恢复。`)) return
  busy.value = `delete-${item.strategy_id}`
  clearNotice()
  try {
    await api.deleteApprovalStrategy(botId.value, item.strategy_id)
    await loadStrategies()
    message.value = '策略已删除。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '删除策略失败'
  } finally {
    busy.value = ''
  }
}

function openGroupEditor(item: ApprovalStrategy) {
  editingStrategy.value = editingStrategy.value === item.strategy_id ? '' : item.strategy_id
  strategyGroupMode.value = item.group_ids?.length ? 'group_ids' : 'group_openids'
  strategyGroupValues.value = ''
  strategyRemark.value = item.remark || ''
  strategyExpire.value = toLocalDateTime(item.expire_at)
}

async function updateStrategyDetails(item: ApprovalStrategy) {
  busy.value = `details-${item.strategy_id}`
  clearNotice()
  try {
    const expireAt = localToRfc3339(strategyExpire.value)
    await api.updateApprovalStrategy(botId.value, item.strategy_id, {
      remark: strategyRemark.value.trim(),
      ...(expireAt ? { expire_at: expireAt } : {}),
    })
    await loadStrategies()
    message.value = '策略备注和到期时间已更新。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '更新策略信息失败'
  } finally {
    busy.value = ''
  }
}

async function updateStrategyGroups(item: ApprovalStrategy) {
  const groups = splitValues(strategyGroupValues.value)
  if (!groups.length) {
    error.value = '请填写需要新增或移除的群。'
    return
  }
  busy.value = `groups-${item.strategy_id}`
  clearNotice()
  try {
    await api.updateApprovalStrategy(botId.value, item.strategy_id, {
      group_action: { op: strategyGroupOp.value, group_mode: strategyGroupMode.value, groups },
    })
    await loadStrategies()
    editingStrategy.value = ''
    message.value = strategyGroupOp.value === 'add' ? '已增加关联群。' : '已移除关联群。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '修改关联群失败'
  } finally {
    busy.value = ''
  }
}

async function updateWhitelist() {
  const users = splitValues(whitelistUsers.value)
  if (!whitelistStrategyId.value) {
    error.value = '请先选择一个策略。'
    return
  }
  if (!users.length || users.some(item => !/^\d+$/.test(item))) {
    error.value = '请填写有效QQ号，每行一个，也可以用逗号分隔。'
    return
  }
  busy.value = 'whitelist'
  clearNotice()
  try {
    await api.updateApprovalWhitelist(botId.value, whitelistStrategyId.value, {
      op: whitelistOp.value,
      whitelist_users: users,
    })
    whitelistUsers.value = ''
    await loadStrategies()
    message.value = `已${whitelistOp.value === 'add' ? '添加' : '删除'} ${users.length} 个白名单QQ号。`
  } catch (e) {
    error.value = e instanceof Error ? e.message : '更新白名单失败'
  } finally {
    busy.value = ''
  }
}

async function loadMutes() {
  if (!muteGroup.value.trim()) {
    error.value = '请选择或填写群 OpenID。'
    return
  }
  busy.value = 'load-mutes'
  clearNotice()
  try {
    muteSetting.value = await api.getGroupMutes(botId.value, muteGroup.value.trim())
  } catch (e) {
    error.value = e instanceof Error ? e.message : '查询禁言状态失败'
  } finally {
    busy.value = ''
  }
}

async function applyMute() {
  const expireAt = expireAtFromMuteForm()
  const members = splitValues(muteMember.value)
  if (!muteGroup.value.trim() || !members.length) {
    error.value = '请填写群 OpenID 和成员 OpenID。'
    return
  }
  if (muteMode.value === 'single' && members.length !== 1) {
    error.value = '单个操作只能填写一名成员；如需一次处理多人，请选择“批量”。'
    return
  }
  if (members.length > 10) {
    error.value = 'QQ官方接口每次最多处理10名成员，请分批提交。'
    return
  }
  if (!expireAt) {
    error.value = '请选择有效的禁言结束时间。'
    return
  }
  busy.value = 'apply-mute'
  clearNotice()
  try {
    muteSetting.value = await api.setGroupMutes(botId.value, {
      group_openid: muteGroup.value.trim(),
      members: members.map(member_openid => ({ op: muteOp.value, member_openid, mute_expire_at: expireAt })),
    })
    muteMember.value = ''
    message.value = muteOp.value === 'add'
      ? `已通过QQ官方接口禁言 ${members.length} 名成员。`
      : `已更新 ${members.length} 名成员的禁言结束时间。`
  } catch (e) {
    error.value = e instanceof Error ? e.message : '设置禁言失败'
  } finally {
    busy.value = ''
  }
}

function prepareMuteUpdate(memberOpenid: string) {
  muteMember.value = memberOpenid
  muteMode.value = 'single'
  muteOp.value = 'update'
  muteDuration.value = '60'
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function unmute(memberOpenid: string) {
  if (!confirm('确认立即解除该成员禁言？')) return
  busy.value = `unmute-${memberOpenid}`
  clearNotice()
  try {
    muteSetting.value = await api.setGroupMutes(botId.value, {
      group_openid: muteGroup.value.trim(),
      members: [{ op: 'del', member_openid: memberOpenid, mute_expire_at: '' }],
    })
    message.value = '已解除该成员禁言。'
  } catch (e) {
    error.value = e instanceof Error ? e.message : '解除禁言失败'
  } finally {
    busy.value = ''
  }
}

watch(botId, (value, oldValue) => {
  if (oldValue && value !== oldValue) reloadAll()
})

onMounted(async () => {
  try {
    bots.value = await api.listBots()
    const preferred = typeof route.query.bot === 'string' ? route.query.bot : ''
    botId.value = bots.value.some(item => item.id === preferred) ? preferred : (bots.value[0]?.id || '')
    if (botId.value) await reloadAll()
  } catch (e) {
    error.value = e instanceof Error ? e.message : '加载机器人失败'
  }
})
</script>

<template>
  <section class="page management-page">
    <div class="page-head">
      <div>
        <h1 class="page-title">官方群管理</h1>
        <p class="page-sub">不需要编写接口或JSON，选择操作方式并填写群号、OpenID或QQ号即可。</p>
      </div>
      <button class="btn" :disabled="loading || !botId" @click="reloadAll">刷新全部</button>
    </div>

    <div v-if="!bots.length" class="card empty">暂无机器人，请先添加 AppID、AppSecret 和回调地址。</div>
    <template v-else>
      <div class="toolbar">
        <div class="field bot-picker"><label>当前机器人</label><select v-model="botId" class="select"><option v-for="bot in bots" :key="bot.id" :value="bot.id">{{ bot.name }} · {{ bot.app_id }}</option></select></div>
        <div v-if="status" class="event-state" :class="eventStateClass">
          <div><strong>{{ eventStateLabel }}</strong><small>机器人必须是目标群管理员</small></div>
          <button v-if="!status.requirements_ready" class="mini" :disabled="busy === 'event'" @click="enableEvent">一键加入事件清单</button>
        </div>
      </div>

      <nav class="tabs">
        <button :class="{ active: tab === 'requests' }" @click="tab = 'requests'">待审批 <span>{{ pendingCount }}</span></button>
        <button :class="{ active: tab === 'strategies' }" @click="tab = 'strategies'">自动审批策略</button>
        <button :class="{ active: tab === 'mutes' }" @click="tab = 'mutes'">成员禁言</button>
        <button :class="{ active: tab === 'legacy' }" @click="tab = 'legacy'">兼容验证</button>
      </nav>

      <div v-if="loading" class="card loading">正在加载群管理数据…</div>

      <template v-else-if="status && tab === 'requests'">
        <section class="card panel sync-panel">
          <div><h2 class="section-title">同步指定群的申请</h2><p class="section-sub">新申请会通过事件自动进入列表；手动同步用于补回服务离线期间遗漏的申请。</p></div>
          <div class="inline-form">
            <input v-model="selectedGroup" class="input mono" list="known-groups" placeholder="选择已识别群，或粘贴群 OpenID">
            <datalist id="known-groups"><option v-for="group in status.groups" :key="group.group_openid" :value="group.group_openid">{{ group.group_name || shortId(group.group_openid) }}</option></datalist>
            <button class="btn primary" :disabled="busy === 'sync'" @click="syncRequests">{{ busy === 'sync' ? '同步中…' : '同步申请' }}</button>
          </div>
          <div v-if="status.groups.length" class="group-chips"><button v-for="group in status.groups" :key="group.group_openid" @click="chooseKnownGroup(group.group_openid)">{{ group.group_name || shortId(group.group_openid) }}</button></div>
        </section>

        <section class="card panel">
          <div class="section-head"><div><h2 class="section-title">入群申请</h2><p class="section-sub">审批时会自动携带申请令牌和成员标识。</p></div><div class="filters"><button :class="{active:requestFilter==='pending'}" @click="requestFilter='pending'">仅待审</button><button :class="{active:requestFilter==='all'}" @click="requestFilter='all'">全部</button></div></div>
          <div v-if="!displayedRequests.length" class="empty-row">暂无{{ requestFilter === 'pending' ? '待审批' : '' }}申请。</div>
          <article v-for="item in displayedRequests" :key="item.join_request_id" class="request-card">
            <div class="request-main">
              <div class="request-title"><strong>{{ item.username || '未获取昵称' }}</strong><span class="state" :class="item.status">{{ requestStatus(item) }}</span></div>
              <small class="mono">成员 {{ shortId(item.member_openid) }} · 群 {{ shortId(item.group_openid) }}</small>
              <small>{{ item.apply_source === 'invited' ? '由群成员邀请' : '主动申请' }} · {{ formatTime(item.apply_at) }}</small>
              <div v-if="item.risk_tips" class="risk"><strong>QQ安全提示</strong>{{ item.risk_tips }}</div>
              <div v-if="item.verify_info?.verify_message" class="answer"><span>验证消息</span><strong>{{ item.verify_info.verify_message }}</strong></div>
              <div v-for="qa in item.verify_info?.review_qa_list || []" :key="qa.question" class="answer"><span>{{ qa.question }}</span><strong>{{ qa.answer }}</strong></div>
              <div v-if="item.auto_strategy_id" class="auto-note">由策略 {{ item.auto_strategy_id }} 自动通过</div>
            </div>
            <div v-if="item.status === 'pending'" class="decision-box">
              <button class="btn primary" :disabled="busy === item.join_request_id" @click="decide(item, 'approve')">通过</button>
              <details>
                <summary>拒绝选项</summary>
                <input v-model="rejectReasons[item.join_request_id]" class="input" maxlength="200" placeholder="拒绝原因（选填）">
                <label class="check"><input v-model="rejectBlacklists[item.join_request_id]" type="checkbox">同时加入群黑名单</label>
                <button class="btn danger" :disabled="busy === item.join_request_id" @click="decide(item, 'decline')">确认拒绝</button>
              </details>
            </div>
          </article>
        </section>
      </template>

      <template v-else-if="status && tab === 'strategies'">
        <div class="two-column">
          <section class="card panel">
            <h2 class="section-title">新建自动审批策略</h2>
            <p class="section-sub">可按普通QQ群号，也可按机器人事件中的群 OpenID 建立策略。</p>
            <div class="mode-cards"><label :class="{selected:createMode==='group_ids'}"><input v-model="createMode" type="radio" value="group_ids"><b>按QQ群号</b><span>适合用户知道群号的常规场景</span></label><label :class="{selected:createMode==='group_openids'}"><input v-model="createMode" type="radio" value="group_openids"><b>按群 OpenID</b><span>适合从事件自动识别的群</span></label></div>
            <div class="field"><label>{{ createMode === 'group_ids' ? 'QQ群号' : '群 OpenID' }}</label><textarea v-model="createGroups" class="textarea" rows="5" :placeholder="createMode === 'group_ids' ? '每行一个QQ群号，最多100个' : '每行一个群 OpenID，最多100个'"></textarea></div>
            <div class="form-grid"><div class="field"><label>策略备注</label><input v-model="createRemark" class="input" maxlength="255" placeholder="例如：付费会员群"></div><div class="field"><label>过期时间</label><input v-model="createExpire" class="input" type="datetime-local"><small>不填默认一年</small></div></div>
            <label class="check standalone"><input v-model="createEnabled" type="checkbox">创建后立即启用</label>
            <button class="btn primary full" :disabled="busy === 'create-strategy'" @click="createStrategy">{{ busy === 'create-strategy' ? '创建中…' : '创建策略' }}</button>
          </section>

          <section class="card panel">
            <h2 class="section-title">批量维护白名单</h2><p class="section-sub">这里填写真实QQ号，不是成员 OpenID。每次最多1万个，后台会自动分批。</p>
            <div class="field"><label>目标策略</label><select v-model="whitelistStrategyId" class="select"><option disabled value="">请先选择策略</option><option v-for="item in strategies" :key="item.strategy_id" :value="item.strategy_id">{{ item.remark || item.strategy_id }} · 当前约{{ item.whitelist_user_count }}人</option></select></div>
            <div class="field"><label>操作方式</label><select v-model="whitelistOp" class="select"><option value="add">添加白名单</option><option value="del">删除白名单</option></select></div>
            <div class="field"><label>QQ号码</label><textarea v-model="whitelistUsers" class="textarea" rows="8" placeholder="每行一个QQ号，也可以用逗号分隔"></textarea></div>
            <button class="btn primary full" :disabled="busy === 'whitelist' || !strategies.length" @click="updateWhitelist">{{ busy === 'whitelist' ? '处理中…' : '提交白名单' }}</button>
          </section>
        </div>

        <section class="card panel strategy-list">
          <div class="section-head"><div><h2 class="section-title">现有策略</h2><p class="section-sub">一个机器人最多20个策略。执行扫描为异步任务，通常约10分钟完成。</p></div><button class="mini" @click="loadStrategies">刷新策略</button></div>
          <div v-if="!strategies.length" class="empty-row">暂无自动审批策略。</div>
          <article v-for="item in strategies" :key="item.strategy_id" class="strategy-card">
            <div class="strategy-info"><div><strong>{{ item.remark || '未命名策略' }}</strong><span :class="item.is_enable === 'on' ? 'on' : 'off'">{{ item.is_enable === 'on' ? '已启用' : '已停用' }}</span></div><small class="mono">{{ item.strategy_id }}</small><p>关联群 {{ (item.group_openids?.length || item.group_ids?.length || 0) }} 个 · 白名单约 {{ item.whitelist_user_count }} 人 · 到期 {{ formatTime(item.expire_at) }}</p></div>
            <div class="strategy-actions"><button class="mini" @click="toggleStrategy(item)">{{ item.is_enable === 'on' ? '停用' : '启用' }}</button><button class="mini" @click="openGroupEditor(item)">编辑</button><button class="mini primary-text" :disabled="item.is_enable !== 'on'" @click="executeStrategy(item)">扫描现有申请</button><button class="mini danger-text" @click="removeStrategy(item)">删除</button></div>
            <div v-if="editingStrategy === item.strategy_id" class="group-editor">
              <div class="editor-details"><div class="field"><label>策略备注</label><input v-model="strategyRemark" class="input" maxlength="255"></div><div class="field"><label>到期时间</label><input v-model="strategyExpire" class="input" type="datetime-local"></div><button class="btn" :disabled="busy === `details-${item.strategy_id}`" @click="updateStrategyDetails(item)">保存基本信息</button></div>
              <div class="editor-groups"><select v-model="strategyGroupOp" class="select"><option value="add">新增关联群</option><option value="del">移除关联群</option></select><select v-model="strategyGroupMode" class="select" disabled><option value="group_ids">使用QQ群号</option><option value="group_openids">使用群 OpenID</option></select><textarea v-model="strategyGroupValues" class="textarea" rows="3" placeholder="每行一个群；标识方式与创建策略时保持一致"></textarea><button class="btn" :disabled="busy === `groups-${item.strategy_id}`" @click="updateStrategyGroups(item)">保存关联群</button></div>
            </div>
          </article>
        </section>
      </template>

      <template v-else-if="status && tab === 'mutes'">
        <section class="card panel mute-form">
          <div><h2 class="section-title">查询和设置成员禁言</h2><p class="section-sub">所有操作直接调用QQ官方接口；不能禁言群主、管理员或机器人。</p></div>
          <div class="inline-form"><input v-model="muteGroup" class="input mono" list="mute-groups" placeholder="选择或粘贴群 OpenID"><datalist id="mute-groups"><option v-for="group in status.groups" :key="group.group_openid" :value="group.group_openid">{{ group.group_name || shortId(group.group_openid) }}</option></datalist><button class="btn" :disabled="busy === 'load-mutes'" @click="loadMutes">查询当前禁言</button></div>
          <div class="mute-fields"><div class="field"><label>填写方式</label><select v-model="muteMode" class="select"><option value="single">单个成员</option><option value="batch">批量成员（最多10名）</option></select></div><div class="field"><label>操作</label><select v-model="muteOp" class="select"><option value="add">新增禁言</option><option value="update">修改结束时间</option></select></div><div class="field"><label>禁言时长</label><select v-model="muteDuration" class="select"><option value="10">10分钟</option><option value="60">1小时</option><option value="1440">24小时</option><option value="10080">7天</option><option value="43200">30天</option><option value="custom">自定义结束时间</option></select></div><div v-if="muteDuration === 'custom'" class="field"><label>结束时间</label><input v-model="muteCustomEnd" class="input" type="datetime-local"></div></div>
          <div class="field mute-members"><label>成员 OpenID</label><textarea v-model="muteMember" class="textarea mono" :rows="muteMode === 'batch' ? 5 : 2" :placeholder="muteMode === 'batch' ? '每行一个成员 OpenID，最多10名' : '从下方禁言列表复制，或从事件记录获取'"></textarea><small v-if="muteMode === 'batch'">本次会为所有成员使用相同的操作和结束时间。</small></div>
          <button class="btn primary" :disabled="busy === 'apply-mute'" @click="applyMute">{{ muteOp === 'add' ? '确认禁言' : '更新禁言' }}</button>
        </section>

        <section class="card panel">
          <div class="section-head"><div><h2 class="section-title">QQ当前禁言状态</h2><p class="section-sub">这里展示QQ服务器仍然生效的状态，不含已经过期的成员。</p></div><span v-if="muteSetting" class="mode-pill">全员规则：{{ muteSetting.global_rule?.mode || 'none' }}</span></div>
          <div v-if="!muteSetting" class="empty-row">先选择群并点击“查询当前禁言”。</div>
          <div v-else-if="!muteSetting.members.length" class="empty-row">该群目前没有成员级禁言。</div>
          <div v-for="member in muteSetting?.members || []" :key="member.member_openid" class="mute-row"><div><strong>{{ member.username || '未获取昵称' }}</strong><small class="mono">{{ member.member_openid }}</small><small>禁言至 {{ formatTime(member.mute_expire_at) }}</small></div><div><button class="mini" @click="prepareMuteUpdate(member.member_openid)">改时间</button><button class="mini danger-text" :disabled="busy === `unmute-${member.member_openid}`" @click="unmute(member.member_openid)">解除</button></div></div>
        </section>
      </template>

      <section v-else-if="tab === 'legacy'" class="card panel legacy-panel">
        <h2 class="section-title">入群后数学题验证</h2><p>该功能保留为兼容模式：成员先进入群，再答题，错误消息由机器人撤回。新群建议优先使用官方群审批。</p><RouterLink :to="`/group-verification-legacy?bot=${botId}`" class="btn">打开兼容验证设置</RouterLink>
      </section>

      <p v-if="message" class="notice ok">{{ message }}</p>
      <p v-if="error" class="notice error">{{ error }}</p>
    </template>
  </section>
</template>

<style scoped>
.management-page{max-width:1280px}.empty,.loading{padding:32px}.toolbar{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin-bottom:16px}.bot-picker{width:min(500px,100%)}.event-state{display:flex;align-items:center;gap:14px;padding:10px 12px;border-radius:13px;background:var(--bg-sunken)}.event-state div strong,.event-state div small{display:block}.event-state small{margin-top:3px;color:var(--ink-4);font-size:10px}.event-state.ready strong{color:#238541}.event-state.warn strong{color:var(--warn)}.tabs{display:flex;gap:6px;margin-bottom:18px;padding:5px;border:1px solid var(--line);border-radius:15px;background:white;width:max-content;max-width:100%;overflow:auto}.tabs button{padding:9px 13px;border-radius:10px;color:var(--ink-3);font-size:12px;font-weight:700;white-space:nowrap}.tabs button.active{background:var(--accent-soft);color:var(--accent)}.tabs span{margin-left:4px;padding:1px 5px;border-radius:999px;background:rgba(0,0,0,.06)}.panel{padding:22px;margin-bottom:18px}.sync-panel{display:grid;grid-template-columns:minmax(220px,.8fr) minmax(360px,1.2fr);gap:18px;align-items:end}.inline-form{display:flex;gap:9px}.inline-form .input{flex:1}.group-chips{grid-column:1/-1;display:flex;gap:7px;flex-wrap:wrap}.group-chips button{padding:5px 9px;border:1px solid var(--line);border-radius:999px;color:var(--ink-3);font-size:10px}.section-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start}.filters{display:flex;gap:5px}.filters button,.mini{padding:6px 9px;border:1px solid var(--line);border-radius:8px;background:white;color:var(--ink-3);font-size:10.5px}.filters button.active{border-color:var(--accent-border);background:var(--accent-soft);color:var(--accent)}.empty-row{padding:30px 0;text-align:center;color:var(--ink-4);font-size:12px}.request-card{display:grid;grid-template-columns:minmax(0,1fr) 230px;gap:18px;padding:18px 0;border-top:1px solid var(--line)}.request-title{display:flex;align-items:center;gap:8px}.request-title strong{font-size:14px}.state{padding:3px 7px;border-radius:999px;font-size:9px;font-weight:750}.state.pending{background:rgba(255,149,0,.12);color:var(--warn)}.state.approved,.state.auto_approved{background:rgba(52,199,89,.12);color:#238541}.state.declined{background:rgba(255,59,48,.1);color:var(--danger)}.request-main>small{display:block;margin-top:5px;color:var(--ink-4);font-size:10px}.risk,.answer,.auto-note{margin-top:11px;padding:10px;border-radius:10px;background:var(--bg-sunken);font-size:11px;line-height:1.55}.risk{background:rgba(255,149,0,.09);color:#815500}.risk strong,.answer span,.answer strong{display:block}.answer span{color:var(--ink-4);font-size:10px}.answer strong{margin-top:3px}.auto-note{color:#238541}.decision-box{display:flex;flex-direction:column;gap:8px}.decision-box details{padding:9px;border:1px solid var(--line);border-radius:11px}.decision-box summary{cursor:pointer;color:var(--danger);font-size:11px;font-weight:700}.decision-box details .input,.decision-box details .check,.decision-box details .btn{margin-top:9px;width:100%}.check{display:flex;align-items:center;gap:7px;font-size:11px}.check input{accent-color:var(--accent)}.two-column{display:grid;grid-template-columns:1fr 1fr;gap:18px}.mode-cards{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin:16px 0}.mode-cards label{padding:12px;border:1px solid var(--line);border-radius:11px}.mode-cards label.selected{border-color:var(--accent-border);background:var(--accent-soft)}.mode-cards input{display:none}.mode-cards b,.mode-cards span{display:block}.mode-cards b{font-size:12px}.mode-cards span{margin-top:4px;color:var(--ink-4);font-size:9.5px;line-height:1.4}.textarea{width:100%;resize:vertical;padding:11px 12px;border:1px solid var(--line);border-radius:11px;background:white;color:var(--ink);font:inherit;line-height:1.5}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.field small{display:block;margin-top:5px;color:var(--ink-4);font-size:9.5px}.standalone{margin:13px 0}.full{width:100%;justify-content:center}.strategy-list{margin-top:18px}.strategy-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:16px;padding:16px 0;border-top:1px solid var(--line)}.strategy-info>div{display:flex;align-items:center;gap:8px}.strategy-info span{padding:3px 6px;border-radius:999px;font-size:9px}.strategy-info span.on{background:rgba(52,199,89,.12);color:#238541}.strategy-info span.off{background:rgba(60,60,67,.08);color:var(--ink-4)}.strategy-info small,.strategy-info p{display:block;margin:5px 0 0;color:var(--ink-4);font-size:10px}.strategy-actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}.primary-text{color:var(--accent)!important}.danger-text{color:var(--danger)!important}.group-editor{grid-column:1/-1;display:flex;flex-direction:column;gap:12px;padding:12px;border-radius:11px;background:var(--bg-sunken)}.editor-details{display:grid;grid-template-columns:1fr 260px auto;gap:8px;align-items:end}.editor-groups{display:grid;grid-template-columns:170px 180px 1fr auto;gap:8px;align-items:start}.mute-form .inline-form{margin-top:16px}.mute-fields{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}.mute-members{margin-bottom:14px}.mode-pill{padding:5px 8px;border-radius:999px;background:var(--bg-sunken);color:var(--ink-3);font-size:10px}.mute-row{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 0;border-top:1px solid var(--line)}.mute-row strong,.mute-row small{display:block}.mute-row small{margin-top:4px;color:var(--ink-4);font-size:10px}.mute-row>div:last-child{display:flex;gap:6px}.legacy-panel p{max-width:700px;margin:10px 0 16px;color:var(--ink-3);font-size:12px;line-height:1.7}.notice{position:sticky;bottom:14px;z-index:10;margin:14px 0 0;padding:12px 14px;border-radius:12px;box-shadow:var(--shadow-sm);font-size:12px}.notice.ok{background:#eaf8ee;color:#237b3b}.notice.error{background:#fff0ef;color:var(--danger)}@media(max-width:900px){.sync-panel,.two-column{grid-template-columns:1fr}.editor-details,.editor-groups{grid-template-columns:1fr 1fr}.editor-groups .textarea,.editor-groups .btn{grid-column:1/-1}.mute-fields{grid-template-columns:1fr 1fr}.toolbar{align-items:stretch;flex-direction:column}.event-state{justify-content:space-between}}@media(max-width:650px){.tabs{width:100%}.request-card,.strategy-card{grid-template-columns:1fr}.decision-box{max-width:none}.strategy-actions{justify-content:flex-start}.inline-form{flex-direction:column}.mode-cards,.form-grid,.mute-fields,.editor-details,.editor-groups{grid-template-columns:1fr}.sync-panel{display:block}.sync-panel>div+div{margin-top:14px}.group-chips{margin-top:12px}}
</style>
