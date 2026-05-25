<script setup lang="ts">
import { SendHorizontal } from 'lucide-vue-next'
import { ref } from 'vue'
import type { ModelProvider } from '../types/api'

defineProps<{
  disabled: boolean
  modelProvider: ModelProvider
}>()

const emit = defineEmits<{
  send: [content: string]
  'update:modelProvider': [provider: ModelProvider]
}>()

const text = ref('')

function submit(): void {
  const content = text.value.trim()
  if (!content) return
  emit('send', content)
  text.value = ''
}
</script>

<template>
  <form class="composer" @submit.prevent="submit">
    <textarea
      v-model="text"
      :disabled="disabled"
      rows="2"
      placeholder="输入目的地、日期、人数、预算或偏好"
      @keydown.enter.exact.prevent="submit"
    />
    <div class="composer-actions">
      <select
        :value="modelProvider"
        :disabled="disabled"
        @change="emit('update:modelProvider', ($event.target as HTMLSelectElement).value as ModelProvider)"
      >
        <option value="auto">自动路由</option>
        <option value="deepseek">DeepSeek</option>
        <option value="qwen">通义千问</option>
      </select>
      <button class="primary icon-text" type="submit" :disabled="disabled || !text.trim()">
        <SendHorizontal :size="17" />
        发送
      </button>
    </div>
  </form>
</template>
