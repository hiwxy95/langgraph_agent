<script setup lang="ts">
import { Bot, UserRound } from 'lucide-vue-next'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'
import type { Message } from '../types/api'

const props = defineProps<{
  message: Message
}>()

marked.setOptions({
  breaks: true,
  gfm: true,
})

const renderedMarkdown = computed(() => {
  if (props.message.role === 'user') return ''
  return DOMPurify.sanitize(marked.parse(props.message.content, { async: false }) as string)
})
</script>

<template>
  <article class="message" :class="message.role">
    <div class="message-avatar" aria-hidden="true">
      <UserRound v-if="message.role === 'user'" :size="18" />
      <Bot v-else :size="18" />
    </div>
    <div class="message-stack">
      <div class="message-role-label">{{ message.role === 'user' ? '你的需求' : '智能规划助手' }}</div>
      <div class="message-body">
        <div
          v-if="message.role === 'assistant'"
          class="message-content markdown-content"
          v-html="renderedMarkdown"
        />
        <div v-else class="message-content">{{ message.content }}</div>
        <div v-if="message.metadata?.provider" class="message-meta">
          {{ message.metadata.provider }} / {{ message.metadata.model }}
        </div>
      </div>
    </div>
  </article>
</template>
