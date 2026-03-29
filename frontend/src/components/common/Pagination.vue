<script setup>
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  page: {
    type: Number,
    default: 1,
  },
  pageSize: {
    type: Number,
    default: 10,
  },
  total: {
    type: Number,
    default: 0,
  },
})

const emit = defineEmits(['update:page'])

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

watch(totalPages, (maxPage) => {
  if (props.page > maxPage) {
    emit('update:page', maxPage)
  }
}, { immediate: true })
const startIndex = computed(() => (props.total === 0 ? 0 : (props.page - 1) * props.pageSize + 1))
const endIndex = computed(() => Math.min(props.page * props.pageSize, props.total))

function goToPage(nextPage) {
  const normalized = Math.max(1, Math.min(totalPages.value, nextPage))
  if (normalized !== props.page) {
    emit('update:page', normalized)
  }
}
</script>

<template>
  <div class="pagination-wrap" role="navigation" :aria-label="t('common.labels.pagination')">
    <span class="pagination-range">{{ startIndex }}-{{ endIndex }} / {{ total }}</span>
    <button class="btn page-btn" :disabled="page <= 1" @click="goToPage(page - 1)">{{ t('common.actions.previous') }}</button>
    <span class="page-label">{{ page }} / {{ totalPages }}</span>
    <button class="btn page-btn" :disabled="page >= totalPages" @click="goToPage(page + 1)">{{ t('common.actions.next') }}</button>
  </div>
</template>

<style scoped>
.pagination-wrap {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-sm);
  margin-top: var(--space-sm);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.page-btn {
  background: var(--color-bg-secondary);
}

.page-label,
.pagination-range {
  color: var(--color-text-secondary);
}
</style>
