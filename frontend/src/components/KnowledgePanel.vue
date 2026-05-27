<script setup lang="ts">
import { FilePlus2, RefreshCw, Trash2, UploadCloud } from 'lucide-vue-next'
import { ref } from 'vue'
import type { KnowledgeCategory, KnowledgeDocument } from '../types/api'

const props = defineProps<{
  documents: KnowledgeDocument[]
  loading: boolean
  submitting: boolean
}>()

const emit = defineEmits<{
  refresh: [category?: KnowledgeCategory | '', q?: string]
  create: [payload: { title: string; category: KnowledgeCategory; content: string; source_url?: string }]
  upload: [payload: { title: string; category: KnowledgeCategory; file: File }]
  delete: [id: string]
}>()

const categories: Array<{ value: KnowledgeCategory; label: string }> = [
  { value: 'tourism_material', label: '文旅资料' },
  { value: 'policy_document', label: '政策文档' },
  { value: 'attraction_intro', label: '景区介绍' },
  { value: 'hotel_description', label: '酒店说明' },
]

const filterCategory = ref<KnowledgeCategory | ''>('')
const query = ref('')
const mode = ref<'text' | 'file'>('text')
const title = ref('')
const category = ref<KnowledgeCategory>('tourism_material')
const content = ref('')
const sourceUrl = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const selectedFile = ref<File | null>(null)

function refresh(): void {
  emit('refresh', filterCategory.value, query.value)
}

function submitText(): void {
  if (!title.value.trim() || !content.value.trim()) return
  emit('create', {
    title: title.value.trim(),
    category: category.value,
    content: content.value.trim(),
    source_url: sourceUrl.value.trim() || undefined,
  })
  title.value = ''
  content.value = ''
  sourceUrl.value = ''
}

function submitFile(): void {
  if (!title.value.trim() || !selectedFile.value) return
  emit('upload', {
    title: title.value.trim(),
    category: category.value,
    file: selectedFile.value,
  })
  title.value = ''
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

function onFileChange(event: Event): void {
  const files = (event.target as HTMLInputElement).files
  selectedFile.value = files?.[0] ?? null
  if (!title.value && selectedFile.value) {
    title.value = selectedFile.value.name.replace(/\.[^.]+$/, '')
  }
}

function formatTime(value: string): string {
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(value))
}

function categoryName(value: KnowledgeCategory): string {
  return categories.find((item) => item.value === value)?.label ?? value
}
</script>

<template>
  <div class="knowledge-panel">
    <header class="knowledge-header">
      <div>
        <span class="page-kicker">Content Operations</span>
        <h1>资料库</h1>
        <p>录入文旅资料、政策文档、景区介绍和酒店说明，作为 RAG 检索依据。</p>
      </div>
      <button class="icon-button" type="button" title="刷新资料" @click="refresh">
        <RefreshCw :size="18" />
      </button>
    </header>

    <div class="knowledge-layout">
      <section class="knowledge-editor panel-surface" aria-label="资料录入">
        <div class="panel-heading">
          <div>
            <span class="page-kicker">Editor</span>
            <h3>新增资料源</h3>
          </div>
        </div>

        <div class="segmented">
          <button type="button" :class="{ active: mode === 'text' }" @click="mode = 'text'">
            <FilePlus2 :size="16" />
            文本录入
          </button>
          <button type="button" :class="{ active: mode === 'file' }" @click="mode = 'file'">
            <UploadCloud :size="16" />
            文件上传
          </button>
        </div>

        <input v-model="title" type="text" placeholder="资料标题" />
        <select v-model="category">
          <option v-for="item in categories" :key="item.value" :value="item.value">
            {{ item.label }}
          </option>
        </select>

        <template v-if="mode === 'text'">
          <input v-model="sourceUrl" type="url" placeholder="来源链接，可选" />
          <textarea
            v-model="content"
            rows="12"
            placeholder="粘贴政策、景区介绍、酒店说明或文旅资料正文"
          />
          <button
            class="primary icon-text"
            type="button"
            :disabled="props.submitting || !title.trim() || !content.trim()"
            @click="submitText"
          >
            <FilePlus2 :size="16" />
            录入资料
          </button>
        </template>

        <template v-else>
          <input
            ref="fileInput"
            type="file"
            accept=".txt,.md,.pdf,.docx"
            @change="onFileChange"
          />
          <button
            class="primary icon-text"
            type="button"
            :disabled="props.submitting || !title.trim() || !selectedFile"
            @click="submitFile"
          >
            <UploadCloud :size="16" />
            上传并向量化
          </button>
        </template>
      </section>

      <section class="knowledge-browser panel-surface" aria-label="资料列表">
        <div class="panel-heading">
          <div>
            <span class="page-kicker">Library</span>
            <h3>资料浏览</h3>
          </div>
        </div>

        <div class="knowledge-controls">
          <select v-model="filterCategory" @change="refresh">
            <option value="">全部分类</option>
            <option v-for="item in categories" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
          <input
            v-model="query"
            type="search"
            placeholder="搜索标题或正文"
            @keydown.enter="refresh"
          />
        </div>

        <div class="knowledge-list">
          <div v-if="props.loading" class="empty-list state-card">加载资料中...</div>
          <article v-for="document in props.documents" :key="document.id" class="knowledge-item">
            <div>
              <h3>{{ document.title }}</h3>
              <p>
                {{ categoryName(document.category) }}
                · {{ document.chunk_count }} 片段 · {{ formatTime(document.updated_at) }}
              </p>
              <p v-if="document.source_name">{{ document.source_name }}</p>
            </div>
            <button
              class="conversation-delete"
              type="button"
              title="删除资料"
              aria-label="删除资料"
              @click="emit('delete', document.id)"
            >
              <Trash2 :size="16" />
            </button>
          </article>
          <div v-if="!props.loading && props.documents.length === 0" class="empty-list state-card">
            暂无资料
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
