import type {
  AgentResponse,
  ApprovalAction,
  Conversation,
  ConversationDetail,
  ModelProvider,
  StreamEvent,
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

export async function streamMessage(
  id: string,
  content: string,
  modelProvider: ModelProvider,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  const response = await fetch(`/api/conversations/${id}/messages/stream`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ content, model_provider: modelProvider }),
  })

  if (!response.ok || !response.body) {
    const body = await response.text()
    throw new Error(body || `HTTP ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''

    for (const chunk of chunks) {
      const dataLine = chunk
        .split('\n')
        .find((line) => line.startsWith('data: '))
      if (!dataLine) continue
      onEvent(JSON.parse(dataLine.slice(6)) as StreamEvent)
    }
  }
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
