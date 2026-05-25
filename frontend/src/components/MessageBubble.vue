<script setup lang="ts">
import { Bot, UserRound } from 'lucide-vue-next'
import type { Message } from '../types/api'

defineProps<{
  message: Message
}>()
</script>

<template>
  <article class="message" :class="message.role">
    <div class="message-avatar" aria-hidden="true">
      <UserRound v-if="message.role === 'user'" :size="18" />
      <Bot v-else :size="18" />
    </div>
    <div class="message-body">
      <div class="message-content">{{ message.content }}</div>
      <div v-if="message.metadata?.provider" class="message-meta">
        {{ message.metadata.provider }} / {{ message.metadata.model }}
      </div>
    </div>
  </article>
</template>
