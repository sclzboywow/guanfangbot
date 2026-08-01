const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export interface Bot {
  id: string
  name: string
  description: string
  status: 'online' | 'offline' | 'created'
  role: 'admin' | 'member'
  app_id: string
  has_secret: boolean
  avatar_seed: number
  updated_at: string
  callback_url: string
  event_scopes: string[]
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

function errorMessage(data: unknown, status: number): string {
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = (data as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((item) => (typeof item === 'object' && item && 'msg' in item ? String((item as { msg: unknown }).msg) : String(item))).join('; ')
    }
  }
  if (data && typeof data === 'object' && 'message' in data) {
    return String((data as { message: unknown }).message)
  }
  return `请求失败：${status}`
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers || {}),
    },
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(errorMessage(data, response.status))
  return data as T
}

export const api = {
  listBots: () => request<Bot[]>('/bots'),
  getBot: (id: string) => request<Bot>(`/bots/${encodeURIComponent(id)}`),
  createBot: (payload: BotCreatePayload) => request<Bot>('/bots', { method: 'POST', body: JSON.stringify(payload) }),
  updateBot: (id: string, payload: BotUpdatePayload) => request<Bot>(`/bots/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  deleteBot: (id: string) => request<{ ok: boolean }>(`/bots/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  credentialStatus: (botId?: string) => request<CredentialStatus>(botId ? `/qqbot/credential-status?bot_id=${encodeURIComponent(botId)}` : '/qqbot/credential-status'),
  refreshToken: (botId: string) => request<{ ok: boolean; expires_in: number }>(`/qqbot/token/refresh?bot_id=${encodeURIComponent(botId)}`, { method: 'POST' }),
  openApi: (payload: { bot_id: string; method: string; path: string; query?: Record<string, string>; body?: unknown }) =>
    request<{ status_code: number; data: unknown; headers: Record<string, string> }>('/qqbot/openapi', { method: 'POST', body: JSON.stringify(payload) }),
  recentEvents: (botId?: string) => request<BotEvent[]>(botId ? `/events/recent?bot_id=${encodeURIComponent(botId)}` : '/events/recent'),
}
