import type {
  AgentResponse,
  ApprovalAction,
  Conversation,
  ConversationDetail,
  KnowledgeCategory,
  KnowledgeDocument,
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
  if (response.status === 204) {
    return undefined as T
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

export async function deleteConversation(id: string): Promise<void> {
  await request<void>(`/api/conversations/${id}`, {
    method: 'DELETE',
  })
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

export async function listKnowledgeDocuments(
  category?: KnowledgeCategory | '',
  q?: string,
): Promise<KnowledgeDocument[]> {
  const params = new URLSearchParams()
  if (category) params.set('category', category)
  if (q?.trim()) params.set('q', q.trim())
  const query = params.toString()
  return request(`/api/knowledge/documents${query ? `?${query}` : ''}`)
}

export async function createKnowledgeDocument(input: {
  title: string
  category: KnowledgeCategory
  content: string
  source_url?: string
}): Promise<KnowledgeDocument> {
  return request('/api/knowledge/documents', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(input),
  })
}

export async function uploadKnowledgeDocument(input: {
  title: string
  category: KnowledgeCategory
  file: File
}): Promise<KnowledgeDocument> {
  const formData = new FormData()
  formData.set('title', input.title)
  formData.set('category', input.category)
  formData.set('file', input.file)
  return request('/api/knowledge/documents/upload', {
    method: 'POST',
    body: formData,
  })
}

export async function deleteKnowledgeDocument(id: string): Promise<void> {
  await request<void>(`/api/knowledge/documents/${id}`, {
    method: 'DELETE',
  })
}
