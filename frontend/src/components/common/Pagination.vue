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
  showRange: {
    type: Boolean,
    default: true,
  },
  showPageWindow: {
    type: Boolean,
    default: false,
  },
  windowSize: {
    type: Number,
    default: 10,
  },
  jumpSize: {
    type: Number,
    default: 0,
  },
})

const emit = defineEmits(['update:page'])

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const normalizedWindowSize = computed(() => Math.max(1, props.windowSize))
const resolvedJumpSize = computed(() => Math.max(1, props.jumpSize || normalizedWindowSize.value))

watch(totalPages, (maxPage) => {
  if (props.page > maxPage) {
    emit('update:page', maxPage)
  }
}, { immediate: true })
const startIndex = computed(() => (props.total === 0 ? 0 : (props.page - 1) * props.pageSize + 1))
const endIndex = computed(() => Math.min(props.page * props.pageSize, props.total))
const windowStart = computed(() => {
  const pageIndex = Math.max(1, props.page) - 1
  return Math.floor(pageIndex / normalizedWindowSize.value) * normalizedWindowSize.value + 1
})
const windowEnd = computed(() => Math.min(totalPages.value, windowStart.value + normalizedWindowSize.value - 1))
const visiblePages = computed(() => Array.from(
  { length: windowEnd.value - windowStart.value + 1 },
  (_, index) => windowStart.value + index,
))

function goToPage(nextPage) {
  const normalized = Math.max(1, Math.min(totalPages.value, nextPage))
  if (normalized !== props.page) {
    emit('update:page', normalized)
  }
}

function goToPreviousWindow() {
  goToPage(windowStart.value - resolvedJumpSize.value)
}

function goToNextWindow() {
  goToPage(windowStart.value + resolvedJumpSize.value)
}
</script>

<template>
  <div class="pagination-wrap" role="navigation" :aria-label="t('common.labels.pagination')">
    <span v-if="showRange" class="pagination-range">{{ t('common.labels.range', { start: startIndex, end: endIndex, total }) }}</span>
    <template v-if="showPageWindow">
      <div class="page-window-controls">
        <button
          type="button"
          class="btn page-btn page-window-btn page-window-prev"
          :disabled="windowStart <= 1"
          :aria-label="t('common.actions.previousPageWindow', { count: resolvedJumpSize })"
          @click="goToPreviousWindow"
        >
          <span aria-hidden="true">&lt;</span>
        </button>
        <button
          v-for="visiblePage in visiblePages"
          :key="visiblePage"
          type="button"
          class="btn page-btn page-number-btn"
          :class="{ 'page-number-btn--active': visiblePage === page }"
          :aria-current="visiblePage === page ? 'page' : undefined"
          @click="goToPage(visiblePage)"
        >
          {{ visiblePage }}
        </button>
        <button
          type="button"
          class="btn page-btn page-window-btn page-window-next"
          :disabled="windowEnd >= totalPages"
          :aria-label="t('common.actions.nextPageWindow', { count: resolvedJumpSize })"
          @click="goToNextWindow"
        >
          <span aria-hidden="true">&gt;</span>
        </button>
      </div>
    </template>
    <template v-else>
      <button type="button" class="btn page-btn" :disabled="page <= 1" @click="goToPage(page - 1)">{{ t('common.actions.previous') }}</button>
      <span class="page-label">{{ page }} / {{ totalPages }}</span>
      <button type="button" class="btn page-btn" :disabled="page >= totalPages" @click="goToPage(page + 1)">{{ t('common.actions.next') }}</button>
    </template>
  </div>
</template>

<style scoped>
.pagination-wrap {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-top: var(--space-sm);
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.page-window-controls {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--space-xs);
}

.page-btn {
  background: var(--color-bg-secondary);
}

.page-number-btn--active {
  border-color: var(--color-accent);
  color: var(--color-accent);
}

.page-label,
.pagination-range {
  color: var(--color-text-secondary);
}
</style>
