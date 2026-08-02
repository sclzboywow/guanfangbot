const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export interface LibraryDeliverySettings {
  bot_id: string
  enabled: boolean
  database_path: string
  table_name: string
  title_column: string
  category_column: string
  size_column: string
  fsid_column: string
  path_column: string
  share_period: 0 | 1 | 7 | 30
  session_ttl_seconds: number
  api_url: string
  api_method: string
  updated_at?: string | null
}

export interface BaiduOAuthSession {
  session_id: string
  status: 'pending' | 'authorized' | 'expired' | 'denied' | 'failed' | 'cancelled' | 'superseded'
  user_code: string
  verification_url: string
  qr_image_url: string
  expires_at: string
  interval_seconds: number
  last_error: string
  authorized?: boolean
}

export interface BaiduOAuthStatus {
  app_configured: boolean
  authorized: boolean
  refreshable: boolean
  token_expires_at?: string | null
  authorized_at?: string | null
  scope: string
  pending_session?: BaiduOAuthSession | null
}

export interface LibraryDatabaseStatus {
  ready: boolean
  row_count: number
  columns: string[]
  error: string
}

export interface LibraryResult {
  title: string
  category: string
  size: string
  fsid: string
  pan_path: string
}

export interface LibraryDeliveryLog {
  id: number
  bot_id: string
  session_id?: string | null
  group_openid: string
  member_openid: string
  action: string
  query: string
  title: string
  fsid: string
  success: boolean
  status_code?: number | null
  detail: string
  created_at: string
}

export interface LibraryDeliveryStatus {
  bot_id: string
  app_id: string
  bot_name: string
  settings: LibraryDeliverySettings
  oauth: BaiduOAuthStatus
  database: LibraryDatabaseStatus
  required_events: Array<{ code: string; configured: boolean }>
  requirements_ready: boolean
  counts: { active_sessions: number; searches: number; delivered: number; failures: number }
  logs: LibraryDeliveryLog[]
  behavior: {
    search_requires_at: boolean
    selection_requires_at: boolean
    max_results: number
    session_one_use: boolean
    outbound_messages_single_line: boolean
    baidu_account_scope: string
  }
}

export interface LibraryDeliverySettingsPayload {
  enabled: boolean
  database_path: string
  table_name: string
  title_column: string
  category_column: string
  size_column: string
  fsid_column: string
  path_column: string
  share_period: 0 | 1 | 7 | 30
  session_ttl_seconds: number
  api_url: string
  api_method: string
}

function errorMessage(data: unknown, status: number): string {
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = (data as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map(item => typeof item === 'object' && item && 'msg' in item
        ? String((item as { msg: unknown }).msg) : String(item)).join('; ')
    }
  }
  return `请求失败：${status}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
  })
  const contentType = response.headers.get('content-type') || ''
  const data = contentType.includes('application/json')
    ? await response.json().catch(() => ({}))
    : await response.text().catch(() => '')
  if (!response.ok) throw new Error(errorMessage(data, response.status))
  return data as T
}

export const libraryDeliveryApi = {
  status: (botId: string) => request<LibraryDeliveryStatus>(`/library-delivery/status?bot_id=${encodeURIComponent(botId)}`),
  updateSettings: (botId: string, payload: LibraryDeliverySettingsPayload) =>
    request<LibraryDeliveryStatus>(`/library-delivery/settings/${encodeURIComponent(botId)}`, {
      method: 'PUT', body: JSON.stringify(payload),
    }),
  testSearch: (botId: string, keyword: string) =>
    request<{ keyword: string; total_count: number; results: LibraryResult[] }>('/library-delivery/test-search', {
      method: 'POST', body: JSON.stringify({ bot_id: botId, keyword }),
    }),
  startOAuth: (botId: string) =>
    request<{ oauth: BaiduOAuthStatus; session: BaiduOAuthSession }>(`/library-delivery/oauth/start?bot_id=${encodeURIComponent(botId)}`, {
      method: 'POST',
    }),
  pollOAuth: (sessionId: string) =>
    request<{ oauth: BaiduOAuthStatus; session: BaiduOAuthSession }>(`/library-delivery/oauth/poll/${encodeURIComponent(sessionId)}`, {
      method: 'POST',
    }),
}
