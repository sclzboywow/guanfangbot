const API_BASE = import.meta.env.VITE_API_BASE || '/api'

export interface ChatContact {
  bot_id: string
  user_openid: string
  display_name: string
  active: boolean
  accepts_messages: boolean
  unread_count: number
  last_message_at?: string | null
  last_message_preview: string
  last_inbound_msg_id: string
  last_inbound_at?: string | null
  last_event_id: string
  created_at: string
  updated_at: string
}

export interface ChatMessage {
  id: number
  bot_id: string
  user_openid: string
  direction: 'inbound' | 'outbound' | 'system'
  kind: 'text' | 'event'
  qq_message_id: string
  event_id: string
  reply_to_msg_id: string
  msg_seq?: number | null
  content: string
  success: boolean
  status_code?: number | null
  detail: string
  created_at: string
}

export interface ChatStatus {
  bot_id: string
  bot_name: string
  app_id: string
  contacts: ChatContact[]
  counts: { total: number; active: number; unread: number; messages: number }
  required_events: Array<{ code: string; configured: boolean }>
  requirements_ready: boolean
  official_friend_list_supported: false
  source_note: string
}

interface ConversationResponse {
  contact: ChatContact
  messages: ChatMessage[]
}

function errorMessage(data: unknown, status: number): string {
  if (data && typeof data === 'object' && 'detail' in data) {
    const detail = (data as { detail: unknown }).detail
    if (typeof detail === 'string') return detail
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

export const chatApi = {
  status: (botId: string) => request<ChatStatus>(`/chat/status?bot_id=${encodeURIComponent(botId)}`),
  messages: (botId: string, userOpenid: string) => request<ConversationResponse>(
    `/chat/messages?bot_id=${encodeURIComponent(botId)}&user_openid=${encodeURIComponent(userOpenid)}&limit=150`,
  ),
  send: (botId: string, userOpenid: string, content: string) => request<{ message: ChatMessage; delivery_mode: string }>(
    '/chat/messages',
    {
      method: 'POST',
      body: JSON.stringify({ bot_id: botId, user_openid: userOpenid, content }),
    },
  ),
}
