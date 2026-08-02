import { request } from '@/services/http'

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

export const chatApi = {
  status: (botId: string) => request<ChatStatus>(`/chat/status?bot_id=${encodeURIComponent(botId)}`),
  messages: (botId: string, userOpenid: string) => request<ConversationResponse>(
    `/chat/messages?bot_id=${encodeURIComponent(botId)}&user_openid=${encodeURIComponent(userOpenid)}&limit=150`,
  ),
  renameContact: (botId: string, userOpenid: string, displayName: string) =>
    request<{ contact: ChatContact }>('/chat/contacts', {
      method: 'PATCH',
      body: JSON.stringify({ bot_id: botId, user_openid: userOpenid, display_name: displayName }),
    }),
  send: (botId: string, userOpenid: string, content: string) => request<{ message: ChatMessage; delivery_mode: string }>(
    '/chat/messages',
    {
      method: 'POST',
      body: JSON.stringify({ bot_id: botId, user_openid: userOpenid, content }),
    },
  ),
}
