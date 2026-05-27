<script setup lang="ts">
import { MessageSquarePlus, Trash2 } from 'lucide-vue-next'
import type { Conversation } from '../types/api'

defineProps<{
  conversations: Conversation[]
  activeId: string | null
  loading: boolean
}>()

const emit = defineEmits<{
  create: []
  select: [id: string]
  delete: [id: string]
}>()

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}
</script>

<template>
  <aside class="sidebar panel-surface">
    <div class="sidebar-header">
      <div>
        <span class="page-kicker">Travel Sessions</span>
        <h1>灵感会话</h1>
        <p>广东路线、酒店、景点与城市体验策划</p>
      </div>
      <button class="icon-button primary-icon" type="button" title="新建对话" @click="emit('create')">
        <MessageSquarePlus :size="20" />
      </button>
    </div>

    <div class="conversation-list" aria-label="对话列表">
      <div
        v-for="conversation in conversations"
        :key="conversation.id"
        class="conversation-item"
        :class="{ active: conversation.id === activeId }"
      >
        <button class="conversation-select" type="button" @click="emit('select', conversation.id)">
          <span class="conversation-title">{{ conversation.title }}</span>
          <span class="conversation-meta">
            <span class="conversation-status">{{ conversation.status }}</span>
            <span>{{ formatTime(conversation.updated_at) }}</span>
          </span>
        </button>
        <button
          class="conversation-delete"
          type="button"
          title="删除对话"
          aria-label="删除对话"
          @click.stop="emit('delete', conversation.id)"
        >
          <Trash2 :size="16" />
        </button>
      </div>

      <div v-if="!loading && conversations.length === 0" class="empty-list state-card">
        暂无对话，点击右上角开始新的旅行策划。
      </div>
      <div v-if="loading" class="empty-list state-card">加载中...</div>
    </div>
  </aside>
</template>
