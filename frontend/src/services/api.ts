import { request } from '@/services/http'

export interface Bot {
  id: string
  name: string
  description: string
  status: 'online' | 'offline' | 'created'
  role: 'admin' | 'member'
  app_id: string
  has_secret: boolean
  avatar_seed: number
  avatar_url?: string
  updated_at: string
  callback_url: string
  event_scopes: string[]
  owner_user_id?: string
}

export interface BotCreatePayload {
  app_id: string
  client_secret: string
  callback_url: string
}

export interface BotUpdatePayload {
  app_id?: string
  client_secret?: string
  callback_url?: string
  event_scopes?: string[]
}

export interface CredentialStatus {
  mode: string
  configured: boolean
  configured_count?: number
  total_bots?: number
  token_cached: boolean
  api_base: string
  bot_id?: string
  app_id?: string
  detail?: string
}

export interface BotEvent {
  id: string
  bot_id?: string
  app_id?: string
  type: string
  received_at: string
  payload: unknown
}

export type EventPermission = 'basic' | 'special' | 'platform'

export interface EventStatusItem {
  code: string
  label: string
  description: string
  permission: EventPermission
  selected: boolean
  observed: boolean
  last_received_at?: string | null
}

export interface EventStatusGroup {
  key: string
  label: string
  events: EventStatusItem[]
}

export interface EventStatusResponse {
  bot_id: string
  app_id: string
  callback_url: string
  callback_verified: boolean
  callback_verified_at?: string | null
  official_subscription_query_supported: boolean
  detection_note: string
  selected_count: number
  observed_count: number
  total_count: number
  groups: EventStatusGroup[]
}

export interface GroupVerificationSettings {
  bot_id: string
  enabled: boolean
  verification_mode: 'math' | 'manual_mute'
  min_operand: number
  max_operand: number
  verification_timeout_minutes: number
  max_wrong_attempts: number
  failure_action: 'mute' | 'retract_only'
  failure_mute_minutes: number
  success_message: string
  manual_review_message: string
  updated_at?: string | null
}

export interface GroupVerificationSession {
  id: string
  bot_id: string
  group_openid: string
  member_openid: string
  member_name: string
  operand_a: number
  operand_b: number
  operator: '+' | '-'
  answer: number
  question: string
  status: 'pending' | 'verified' | 'failed' | 'removed'
  joined_at: string
  deadline_at?: string | null
  verified_at?: string | null
  failed_at?: string | null
  failure_reason: string
  muted_until?: string | null
  removed_at?: string | null
  wrong_attempts: number
  retracted_messages: number
  last_message_at?: string | null
  last_error: string
}

export interface GroupVerificationLog {
  id: number
  bot_id: string
  session_id?: string | null
  action: string
  success: boolean
  status_code?: number | null
  detail: string
  created_at: string
}

export interface GroupVerificationStatus {
  bot_id: string
  app_id: string
  bot_name: string
  settings: GroupVerificationSettings
  required_events: Array<{ code: string; configured: boolean }>
  requirements_ready: boolean
  counts: { pending: number; verified: number; failed: number; removed: number; total: number }
  sessions: GroupVerificationSession[]
  logs: GroupVerificationLog[]
  behavior: {
    answer_requires_at: boolean
    pending_messages_retracted: boolean
    verification_expires: boolean
    official_mute_on_failure: boolean
    verification_mode: 'math' | 'manual_mute'
    outbound_messages_single_line: boolean
  }
}

export interface ManagedGroup {
  bot_id: string
  group_openid: string
  group_name: string
  source: string
  last_seen_at: string
}

export interface OfficialJoinRequest {
  join_request_id: string
  group_openid: string
  member_openid: string
  union_openid: string
  username: string
  risk_tips: string
  apply_at: string
  apply_source: 'self_apply' | 'invited' | string
  invited_by: string
  bot: boolean
  verify_info: {
    method?: string
    verify_message?: string
    review_qa_list?: Array<{ question: string; answer: string }>
  }
  auto_strategy_id: string
  status: 'pending' | 'approved' | 'declined' | 'auto_approved'
  decision: string
  decision_detail: string
  updated_at: string
}

export interface GroupManagementStatus {
  bot_id: string
  app_id: string
  bot_name: string
  required_events: Array<{ code: string; configured: boolean }>
  requirements_ready: boolean
  groups: ManagedGroup[]
  join_requests: OfficialJoinRequest[]
  logs: Array<{
    id: number
    action: string
    success: boolean
    status_code?: number | null
    detail: string
    created_at: string
  }>
  limits: Record<string, number>
}

export interface ApprovalStrategy {
  strategy_id: string
  group_openids: string[]
  group_ids: Array<string | number>
  whitelist_user_count: number
  is_enable: 'on' | 'off'
  expire_at: string
  created_at: string
  updated_at: string
  remark?: string
}

export interface GroupMuteSetting {
  global_rule: {
    mode?: 'none' | 'always' | 'schedule' | string
    schedule_rules?: unknown[]
    recurring_rules?: unknown[]
  }
  members: Array<{
    member_openid: string
    mute_expire_at: string
    username: string
    union_openid: string
  }>
}

export interface GroupModerationSettings {
  bot_id: string
  enabled: boolean
  detect_mobile: boolean
  detect_landline: boolean
  detect_wechat: boolean
  detect_content_keywords: boolean
  detect_nickname_keywords: boolean
  exempt_admins: boolean
  use_official_mute: boolean
  retract_merged_messages: boolean
  retract_group_cards: boolean
  merged_message_action: 'retract' | 'mute'
  group_card_action: 'retract' | 'mute'
  special_rule_mute_minutes: number
  penalty_minutes: number[]
  permanent_after: number
  escalation_cooldown_seconds: number
  warning_cooldown_seconds: number
  content_keywords: string[]
  nickname_keywords: string[]
  updated_at?: string | null
}

export interface GroupModerationMember {
  id: string
  bot_id: string
  group_openid: string
  member_openid: string
  member_name: string
  trusted: boolean
  strike_count: number
  penalty_level: number
  blocked_until?: string | null
  permanent: boolean
  last_violation_at?: string | null
  last_rule: string
  last_match: string
  last_message_at?: string | null
  retracted_messages: number
  warning_count: number
  last_warning_at?: string | null
  last_error: string
  updated_at: string
}

export interface GroupModerationLog {
  id: number
  bot_id: string
  member_id?: string | null
  group_openid: string
  member_openid: string
  action: string
  rule: string
  matched: string
  message_excerpt: string
  success: boolean
  status_code?: number | null
  detail: string
  created_at: string
}

export interface GroupModerationStatus {
  bot_id: string
  app_id: string
  bot_name: string
  settings: GroupModerationSettings
  required_events: Array<{ code: string; configured: boolean }>
  requirements_ready: boolean
  counts: { total: number; blocked: number; permanent: number; trusted: number }
  members: GroupModerationMember[]
  logs: GroupModerationLog[]
  behavior: {
    warning_before_penalty: boolean
    blocked_messages_retracted: boolean
    official_mute_enabled: boolean
    outbound_messages_single_line: boolean
    scope: string
  }
}

export const api = {
  listBots: () => request<Bot[]>('/bots'),
  getBot: (id: string) => request<Bot>(`/bots/${encodeURIComponent(id)}`),
  createBot: (payload: BotCreatePayload) => request<Bot>('/bots', { method: 'POST', body: JSON.stringify(payload) }),
  updateBot: (id: string, payload: BotUpdatePayload) => request<Bot>(`/bots/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  syncBotProfile: (id: string) => request<Bot>(`/bots/${encodeURIComponent(id)}/sync-profile`, { method: 'POST' }),
  deleteBot: (id: string) => request<{ ok: boolean }>(`/bots/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  credentialStatus: (botId?: string) => request<CredentialStatus>(botId ? `/qqbot/credential-status?bot_id=${encodeURIComponent(botId)}` : '/qqbot/credential-status'),
  openApi: (payload: { bot_id: string; method: string; path: string; query?: Record<string, string>; body?: unknown }) =>
    request<{ status_code: number; data: unknown; headers: Record<string, string> }>('/qqbot/openapi', { method: 'POST', body: JSON.stringify(payload) }),
  recentEvents: (botId?: string) => request<BotEvent[]>(botId ? `/events/recent?bot_id=${encodeURIComponent(botId)}` : '/events/recent'),
  eventStatus: (botId: string) => request<EventStatusResponse>(`/events/status?bot_id=${encodeURIComponent(botId)}`),
  groupVerificationStatus: (botId: string) => request<GroupVerificationStatus>(`/group-verification/status?bot_id=${encodeURIComponent(botId)}`),
  updateGroupVerificationSettings: (botId: string, payload: Omit<GroupVerificationSettings, 'bot_id' | 'updated_at'>) =>
    request<GroupVerificationStatus>(`/group-verification/settings/${encodeURIComponent(botId)}`, { method: 'PUT', body: JSON.stringify(payload) }),
  verifyGroupMember: (sessionId: string) => request<GroupVerificationStatus>(`/group-verification/sessions/${encodeURIComponent(sessionId)}/verify`, { method: 'POST' }),
  resetGroupVerification: (sessionId: string) => request<GroupVerificationStatus>(`/group-verification/sessions/${encodeURIComponent(sessionId)}/reset`, { method: 'POST' }),
  closeGroupVerification: (sessionId: string) => request<GroupVerificationStatus>(`/group-verification/sessions/${encodeURIComponent(sessionId)}/close`, { method: 'POST' }),
  groupManagementStatus: (botId: string) => request<GroupManagementStatus>(`/group-management/status?bot_id=${encodeURIComponent(botId)}`),
  enableGroupManagementEvents: (botId: string) => request<GroupManagementStatus>(`/group-management/events/${encodeURIComponent(botId)}/enable`, { method: 'POST' }),
  syncJoinRequests: (botId: string, groupOpenid: string) =>
    request<{ sync: { synced: number; pages: number; truncated: boolean }; status: GroupManagementStatus }>(`/group-management/join-requests/sync?bot_id=${encodeURIComponent(botId)}&group_openid=${encodeURIComponent(groupOpenid)}`, { method: 'POST' }),
  decideJoinRequest: (botId: string, payload: {
    group_openid: string
    member_openid: string
    join_request_id: string
    op: 'approve' | 'decline'
    reject_reason?: string
    add_to_member_blacklist?: boolean
  }) => request<{ result: { ok: boolean; decision: string }; status: GroupManagementStatus }>(`/group-management/join-requests/decision?bot_id=${encodeURIComponent(botId)}`, { method: 'POST', body: JSON.stringify(payload) }),
  getGroupMutes: (botId: string, groupOpenid: string) => request<GroupMuteSetting>(`/group-management/mutes?bot_id=${encodeURIComponent(botId)}&group_openid=${encodeURIComponent(groupOpenid)}`),
  setGroupMutes: (botId: string, payload: { group_openid: string; members: Array<{ op: 'add' | 'update' | 'del'; member_openid: string; mute_expire_at?: string }> }) =>
    request<GroupMuteSetting>(`/group-management/mutes?bot_id=${encodeURIComponent(botId)}`, { method: 'POST', body: JSON.stringify(payload) }),
  listApprovalStrategies: (botId: string) => request<{ strategies: ApprovalStrategy[]; truncated: boolean }>(`/group-management/strategies?bot_id=${encodeURIComponent(botId)}`),
  createApprovalStrategy: (botId: string, payload: { group_mode: 'group_openids' | 'group_ids'; groups: string[]; is_enable: 'on' | 'off'; expire_at?: string | null; remark?: string }) =>
    request<Record<string, unknown>>(`/group-management/strategies?bot_id=${encodeURIComponent(botId)}`, { method: 'POST', body: JSON.stringify(payload) }),
  updateApprovalStrategy: (botId: string, strategyId: string, payload: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/group-management/strategies/${encodeURIComponent(strategyId)}?bot_id=${encodeURIComponent(botId)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteApprovalStrategy: (botId: string, strategyId: string) =>
    request<{ ok: boolean }>(`/group-management/strategies/${encodeURIComponent(strategyId)}?bot_id=${encodeURIComponent(botId)}`, { method: 'DELETE' }),
  executeApprovalStrategy: (botId: string, strategyId: string) =>
    request<{ ok: boolean; message: string }>(`/group-management/strategies/${encodeURIComponent(strategyId)}/execute?bot_id=${encodeURIComponent(botId)}`, { method: 'POST' }),
  updateApprovalWhitelist: (botId: string, strategyId: string, payload: { op: 'add' | 'del'; whitelist_users: string[] }) =>
    request<Record<string, unknown>>(`/group-management/strategies/${encodeURIComponent(strategyId)}/whitelist?bot_id=${encodeURIComponent(botId)}`, { method: 'POST', body: JSON.stringify(payload) }),
  refreshManagedGroupInfo: (botId: string, groupOpenid: string) =>
    request<Record<string, unknown>>(`/group-management/groups/info?bot_id=${encodeURIComponent(botId)}&group_openid=${encodeURIComponent(groupOpenid)}`, { method: 'POST' }),
  groupModerationStatus: (botId: string) => request<GroupModerationStatus>(`/group-moderation/status?bot_id=${encodeURIComponent(botId)}`),
  updateGroupModerationSettings: (botId: string, payload: Omit<GroupModerationSettings, 'bot_id' | 'updated_at'>) =>
    request<GroupModerationStatus>(`/group-moderation/settings/${encodeURIComponent(botId)}`, { method: 'PUT', body: JSON.stringify(payload) }),
  releaseModeratedMember: (memberId: string, resetStrikes = false) => request<GroupModerationStatus>(`/group-moderation/members/${encodeURIComponent(memberId)}/release?reset_strikes=${resetStrikes}`, { method: 'POST' }),
  makeModeratedMemberPermanent: (memberId: string) => request<GroupModerationStatus>(`/group-moderation/members/${encodeURIComponent(memberId)}/permanent`, { method: 'POST' }),
  trustModeratedMember: (memberId: string) => request<GroupModerationStatus>(`/group-moderation/members/${encodeURIComponent(memberId)}/trust`, { method: 'POST' }),
  untrustModeratedMember: (memberId: string) => request<GroupModerationStatus>(`/group-moderation/members/${encodeURIComponent(memberId)}/untrust`, { method: 'POST' }),
}
