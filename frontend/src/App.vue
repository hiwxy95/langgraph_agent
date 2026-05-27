<script setup lang="ts">
import { BookOpenText, MessagesSquare } from 'lucide-vue-next'
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import ApprovalPanel from './components/ApprovalPanel.vue'
import ChatComposer from './components/ChatComposer.vue'
import ConversationList from './components/ConversationList.vue'
import KnowledgePanel from './components/KnowledgePanel.vue'
import MessageBubble from './components/MessageBubble.vue'
import {
  createConversation,
  createKnowledgeDocument,
  deleteConversation,
  deleteKnowledgeDocument,
  getConversation,
  listConversations,
  listKnowledgeDocuments,
  streamMessage,
  submitApproval,
  uploadKnowledgeDocument,
} from './services/api'
import type {
  AgentResponse,
  ApprovalAction,
  ApprovalPayload,
  Conversation,
  KnowledgeCategory,
  KnowledgeDocument,
  Message,
  ModelProvider,
  StreamEvent,
} from './types/api'

const conversations = ref<Conversation[]>([])
const activeId = ref<string | null>(null)
const messages = ref<Message[]>([])
const pendingApproval = ref<ApprovalPayload | null>(null)
const loadingList = ref(false)
const loadingConversation = ref(false)
const sending = ref(false)
const error = ref<string | null>(null)
const modelProvider = ref<ModelProvider>('auto')
const messageViewport = ref<HTMLElement | null>(null)
const streamingMessageId = ref<string | null>(null)
const knowledgeDocuments = ref<KnowledgeDocument[]>([])
const loadingKnowledge = ref(false)
const submittingKnowledge = ref(false)
const currentPage = ref<'chat' | 'knowledge'>('chat')

const activeConversation = computed(() =>
  conversations.value.find((conversation) => conversation.id === activeId.value) ?? null,
)

onMounted(async () => {
  syncPageFromLocation()
  window.addEventListener('popstate', syncPageFromLocation)

  if (currentPage.value === 'knowledge') {
    await refreshKnowledge()
  }

  await refreshConversations()
  if (conversations.value.length > 0) {
    await selectConversation(conversations.value[0].id)
  } else {
    await handleCreateConversation()
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('popstate', syncPageFromLocation)
})

function syncPageFromLocation(): void {
  currentPage.value = window.location.pathname.startsWith('/knowledge') ? 'knowledge' : 'chat'
}

async function navigate(page: 'chat' | 'knowledge'): Promise<void> {
  const path = page === 'knowledge' ? '/knowledge' : '/'
  if (window.location.pathname !== path) {
    window.history.pushState({}, '', path)
  }
  currentPage.value = page
  error.value = null
  if (page === 'knowledge' && knowledgeDocuments.value.length === 0) {
    await refreshKnowledge()
  }
}

async function refreshConversations(): Promise<void> {
  loadingList.value = true
  try {
    conversations.value = await listConversations()
  } catch (err) {
    error.value = normalizeError(err)
  } finally {
    loadingList.value = false
  }
}

async function refreshKnowledge(category?: KnowledgeCategory | '', q?: string): Promise<void> {
  loadingKnowledge.value = true
  error.value = null
  try {
    knowledgeDocuments.value = await listKnowledgeDocuments(category, q)
  } catch (err) {
    error.value = normalizeError(err)
  } finally {
    loadingKnowledge.value = false
  }
}

async function handleCreateKnowledge(payload: {
  title: string
  category: KnowledgeCategory
  content: string
  source_url?: string
}): Promise<void> {
  submittingKnowledge.value = true
  error.value = null
  try {
    await createKnowledgeDocument(payload)
    await refreshKnowledge()
  } catch (err) {
    error.value = normalizeError(err)
  } finally {
    submittingKnowledge.value = false
  }
}

async function handleUploadKnowledge(payload: {
  title: string
  category: KnowledgeCategory
  file: File
}): Promise<void> {
  submittingKnowledge.value = true
  error.value = null
  try {
    await uploadKnowledgeDocument(payload)
    await refreshKnowledge()
  } catch (err) {
    error.value = normalizeError(err)
  } finally {
    submittingKnowledge.value = false
  }
}

async function handleDeleteKnowledge(id: string): Promise<void> {
  submittingKnowledge.value = true
  error.value = null
  try {
    await deleteKnowledgeDocument(id)
    knowledgeDocuments.value = knowledgeDocuments.value.filter((document) => document.id !== id)
  } catch (err) {
    error.value = normalizeError(err)
  } finally {
    submittingKnowledge.value = false
  }
}

async function handleCreateConversation(): Promise<void> {
  error.value = null
  try {
    const conversation = await createConversation()
    conversations.value = [conversation, ...conversations.value]
    await selectConversation(conversation.id)
  } catch (err) {
    error.value = normalizeError(err)
  }
}

async function selectConversation(id: string): Promise<void> {
  activeId.value = id
  pendingApproval.value = null
  loadingConversation.value = true
  error.value = null
  try {
    const detail = await getConversation(id)
    messages.value = detail.messages
    pendingApproval.value = detail.pending_approval
    await scrollToBottom()
  } catch (err) {
    error.value = normalizeError(err)
  } finally {
    loadingConversation.value = false
  }
}

async function handleDeleteConversation(id: string): Promise<void> {
  error.value = null
  try {
    await deleteConversation(id)
    conversations.value = conversations.value.filter((conversation) => conversation.id !== id)

    if (activeId.value !== id) return

    const nextConversation = conversations.value[0]
    if (nextConversation) {
      await selectConversation(nextConversation.id)
      return
    }

    activeId.value = null
    messages.value = []
    pendingApproval.value = null
    await handleCreateConversation()
  } catch (err) {
    error.value = normalizeError(err)
  }
}

async function handleSend(content: string): Promise<void> {
  if (!activeId.value) return

  const userMessage: Message = {
    id: `local-user-${Date.now()}`,
    role: 'user',
    content,
    metadata: {},
    created_at: new Date().toISOString(),
  }
  const assistantMessage: Message = {
    id: `stream-assistant-${Date.now()}`,
    role: 'assistant',
    content: '',
    metadata: {},
    created_at: new Date().toISOString(),
  }

  messages.value.push(userMessage, assistantMessage)
  streamingMessageId.value = assistantMessage.id
  sending.value = true
  error.value = null
  pendingApproval.value = null
  await scrollToBottom()

  try {
    await streamMessage(activeId.value, content, modelProvider.value, applyStreamEvent)
    await refreshConversations()
  } catch (err) {
    error.value = normalizeError(err)
    removeEmptyStreamingMessage()
  } finally {
    sending.value = false
    streamingMessageId.value = null
    await scrollToBottom()
  }
}

async function handleApproval(action: ApprovalAction, comment?: string): Promise<void> {
  if (!activeId.value) return
  sending.value = true
  error.value = null
  try {
    const response = await submitApproval(activeId.value, action, comment)
    applyAgentResponse(response)
    if (!response.requires_human_approval) {
      pendingApproval.value = null
    }
    await refreshConversations()
  } catch (err) {
    error.value = normalizeError(err)
  } finally {
    sending.value = false
    await scrollToBottom()
  }
}

function applyStreamEvent(event: StreamEvent): void {
  if (event.event === 'token') {
    const target = messages.value.find((message) => message.id === streamingMessageId.value)
    if (target) {
      target.content += event.text ?? ''
    }
    void scrollToBottom()
    return
  }

  if (event.event === 'message' && event.message) {
    const index = messages.value.findIndex((message) => message.id === streamingMessageId.value)
    if (index >= 0) {
      messages.value[index] = event.message
    } else {
      messages.value.push(event.message)
    }
    void scrollToBottom()
    return
  }

  if (event.event === 'approval') {
    pendingApproval.value = event.approval_payload ?? null
    return
  }

  if (event.event === 'error') {
    error.value = event.error ?? '请求失败'
    removeEmptyStreamingMessage()
    return
  }

  if (event.event === 'done') {
    streamingMessageId.value = null
  }
}

function applyAgentResponse(response: AgentResponse): void {
  if (response.error) {
    error.value = response.error
  }
  messages.value.push(...response.messages)
  pendingApproval.value = response.requires_human_approval ? response.approval_payload : null
}

function removeEmptyStreamingMessage(): void {
  const index = messages.value.findIndex((message) => message.id === streamingMessageId.value)
  if (index >= 0 && !messages.value[index].content) {
    messages.value.splice(index, 1)
  }
}

async function scrollToBottom(): Promise<void> {
  await nextTick()
  if (messageViewport.value) {
    messageViewport.value.scrollTop = messageViewport.value.scrollHeight
  }
}

function normalizeError(err: unknown): string {
  if (err instanceof Error) return err.message
  return '请求失败'
}
</script>

<template>
  <main class="app-root">
    <nav class="app-nav" aria-label="主导航">
      <button
        type="button"
        :class="{ active: currentPage === 'chat' }"
        @click="navigate('chat')"
      >
        <MessagesSquare :size="18" />
        智能对话
      </button>
      <button
        type="button"
        :class="{ active: currentPage === 'knowledge' }"
        @click="navigate('knowledge')"
      >
        <BookOpenText :size="18" />
        资料库
      </button>
    </nav>

    <section v-if="currentPage === 'chat'" class="chat-shell">
      <ConversationList
        :conversations="conversations"
        :active-id="activeId"
        :loading="loadingList"
        @create="handleCreateConversation"
        @select="selectConversation"
        @delete="handleDeleteConversation"
      />

      <section class="chat-panel">
        <header class="chat-header">
          <div>
            <h2>{{ activeConversation?.title || '新的文旅对话' }}</h2>
            <p>{{ activeConversation?.status || 'active' }}</p>
          </div>
        </header>

        <div ref="messageViewport" class="message-viewport">
          <div v-if="loadingConversation" class="state-line">加载对话中...</div>
          <template v-else>
            <div v-if="messages.length === 0" class="welcome">
              <h3>从一句需求开始</h3>
              <p>例如：帮我规划广州两日游，想看历史建筑和夜景，预算中等。</p>
            </div>
            <MessageBubble
              v-for="message in messages"
              :key="message.id || message.content"
              :message="message"
            />
            <div v-if="sending" class="state-line">智能体处理中...</div>
            <div v-if="error" class="error-line">{{ error }}</div>
          </template>
        </div>

        <ApprovalPanel
          v-if="pendingApproval"
          :payload="pendingApproval"
          :submitting="sending"
          @submit="handleApproval"
        />

        <ChatComposer
          v-model:model-provider="modelProvider"
          :disabled="sending || !activeId"
          @send="handleSend"
        />
      </section>
    </section>

    <section v-else class="knowledge-page">
      <KnowledgePanel
        :documents="knowledgeDocuments"
        :loading="loadingKnowledge"
        :submitting="submittingKnowledge"
        @refresh="refreshKnowledge"
        @create="handleCreateKnowledge"
        @upload="handleUploadKnowledge"
        @delete="handleDeleteKnowledge"
      />
      <div v-if="error" class="knowledge-page-error error-line">{{ error }}</div>
    </section>
  </main>
</template>
