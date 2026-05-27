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
  <aside class="sidebar">
    <div class="sidebar-header">
      <div>
        <h1>文旅智能体</h1>
        <p>广东路线、酒店、景点规划</p>
      </div>
      <button class="icon-button" type="button" title="新建对话" @click="emit('create')">
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
            <span>{{ conversation.status }}</span>
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

      <div v-if="!loading && conversations.length === 0" class="empty-list">
        暂无对话
      </div>
      <div v-if="loading" class="empty-list">加载中...</div>
    </div>
  </aside>
</template>
