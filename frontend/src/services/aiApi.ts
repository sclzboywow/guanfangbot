import { request } from '@/services/http'

export type AiModel = 'deepseek-v4-flash' | 'deepseek-v4-pro'
export type AiReplyMode = 'auto' | 'quote' | 'normal'
export type AiResponseLength = 'brief' | 'short' | 'normal' | 'detailed'

export interface AiImageAsset {
  key: string
  label: string
  description: string
  url: string
}

export interface AiProfile {
  bot_id: string
  enabled: boolean
  model: AiModel
  thinking_enabled: boolean
  identity_name: string
  role_description: string
  relationship_description: string
  speaking_style: string
  response_length: AiResponseLength
  restrictions: string
  custom_prompt: string
  reply_mode: AiReplyMode
  quote_fallback: boolean
  context_turns: number
  max_tokens: number
  allow_images: boolean
  image_assets: AiImageAsset[]
  failure_message: string
  updated_at?: string | null
}

export interface AiJob {
  id: number
  bot_id: string
  user_openid: string
  trigger_message_id: string
  trigger_content: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  attempts: number
  output_text: string
  output_image_key: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  delivery_mode: string
  error: string
  created_at: string
  completed_at?: string | null
}

export interface AiBotStatus {
  bot_id: string
  bot_name: string
  profile: AiProfile
  credential: {
    configured: boolean
    key_hint: string
    owner_is_current_user: boolean
  }
  jobs: AiJob[]
  counts: Record<'pending' | 'running' | 'completed' | 'failed', number>
  required_event: string
  required_events: string[]
  event_configured: boolean
  group_event_configured: boolean
}

export const aiApi = {
  credential: () => request<{ configured: boolean; key_hint: string; updated_at?: string | null }>('/ai/credential'),
  saveCredential: (apiKey: string) => request<{ configured: boolean; key_hint: string; models: string[] }>('/ai/credential', {
    method: 'PUT',
    body: JSON.stringify({ api_key: apiKey }),
  }),
  testCredential: () => request<{ ok: boolean; models: string[] }>('/ai/credential/test', { method: 'POST' }),
  deleteCredential: () => request<{ ok: boolean }>('/ai/credential', { method: 'DELETE' }),
  botStatus: (botId: string) => request<AiBotStatus>(`/ai/bots/${encodeURIComponent(botId)}`),
  saveProfile: (botId: string, profile: Omit<AiProfile, 'bot_id' | 'updated_at'>) =>
    request<{ profile: AiProfile }>(`/ai/bots/${encodeURIComponent(botId)}`, {
      method: 'PUT',
      body: JSON.stringify(profile),
    }),
  testProfile: (botId: string, prompt: string) => request<{
    text: string
    image_key: string
    model: string
    usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  }>(`/ai/bots/${encodeURIComponent(botId)}/test`, {
    method: 'POST',
    body: JSON.stringify({ prompt }),
  }),
}
