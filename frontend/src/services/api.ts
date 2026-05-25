import type {
  AgentResponse,
  ApprovalAction,
  Conversation,
  ConversationDetail,
  ModelProvider,
} from '../types/api'

const jsonHeaders = {
  'Content-Type': 'application/json',
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init)
  if (!response.ok) {
    const body = await response.text()
    throw new Error(body || `HTTP ${response.status}`)
  }
  return response.json() as Promise<T>
}

export async function createConversation(title?: string): Promise<Conversation> {
  return request('/api/conversations', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ title }),
  })
}

export async function listConversations(): Promise<Conversation[]> {
  return request('/api/conversations')
}

export async function getConversation(id: string): Promise<ConversationDetail> {
  return request(`/api/conversations/${id}`)
}

export async function sendMessage(
  id: string,
  content: string,
  modelProvider: ModelProvider,
): Promise<AgentResponse> {
  return request(`/api/conversations/${id}/messages`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ content, model_provider: modelProvider }),
  })
}

export async function submitApproval(
  id: string,
  action: ApprovalAction,
  comment?: string,
): Promise<AgentResponse> {
  return request(`/api/conversations/${id}/approvals`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ action, comment }),
  })
}
