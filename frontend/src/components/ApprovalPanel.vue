<script setup lang="ts">
import { Check, PencilLine, X } from 'lucide-vue-next'
import { ref } from 'vue'
import type { ApprovalAction, ApprovalPayload } from '../types/api'

defineProps<{
  payload: ApprovalPayload
  submitting: boolean
}>()

const emit = defineEmits<{
  submit: [action: ApprovalAction, comment?: string]
}>()

const comment = ref('')
</script>

<template>
  <section class="approval-panel">
    <div class="approval-main">
      <span class="page-kicker">Human in the loop</span>
      <h2>需要人工确认</h2>
      <p>{{ payload.question || '请确认是否继续采用当前方案。' }}</p>
      <pre v-if="payload.draft">{{ payload.draft }}</pre>
      <textarea
        v-model="comment"
        rows="3"
        placeholder="可填写要调整的日期、预算、酒店区域或景点偏好"
      />
    </div>
    <div class="approval-actions">
      <button
        class="primary"
        type="button"
        :disabled="submitting"
        @click="emit('submit', 'approve', comment)"
      >
        <Check :size="16" />
        确认方案
      </button>
      <button
        type="button"
        :disabled="submitting"
        @click="emit('submit', 'revise', comment)"
      >
        <PencilLine :size="16" />
        修改需求
      </button>
      <button
        class="danger"
        type="button"
        :disabled="submitting"
        @click="emit('submit', 'cancel', comment)"
      >
        <X :size="16" />
        取消规划
      </button>
    </div>
  </section>
</template>
