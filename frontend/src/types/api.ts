export interface Message {
  id: string | null
  role: string
  content: string
  metadata: Record<string, unknown>
  created_at: string | null
}

export interface Conversation {
  id: string
  title: string
  status: string
  created_at: string
  updated_at: string
}

export interface ConversationDetail extends Conversation {
  messages: Message[]
  pending_approval: ApprovalPayload | null
}

export interface ApprovalPayload {
  approval_id?: string
  kind?: string
  draft?: string
  question?: string
  tool_results?: Record<string, unknown>
}

export interface AgentResponse {
  conversation_id: string
  messages: Message[]
  status: string
  requires_human_approval: boolean
  approval_payload: ApprovalPayload | null
  error: string | null
}

export interface StreamEvent {
  event: 'start' | 'token' | 'message' | 'approval' | 'done' | 'error'
  conversation_id: string
  message?: Message
  text?: string
  status?: string
  approval_payload?: ApprovalPayload | null
  error?: string | null
}

export type ModelProvider = 'auto' | 'deepseek' | 'qwen'
export type ApprovalAction = 'approve' | 'revise' | 'cancel'
