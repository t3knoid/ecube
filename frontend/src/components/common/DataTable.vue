<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps({
  columns: {
    type: Array,
    default: () => [],
  },
  rows: {
    type: Array,
    default: () => [],
  },
  rowKey: {
    type: String,
    default: 'id',
  },
  emptyText: {
    type: String,
    default: '',
  },
  sortable: {
    type: Boolean,
    default: false,
  },
  sortKey: {
    type: String,
    default: '',
  },
  sortDir: {
    type: String,
    default: 'asc',
  },
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

const emit = defineEmits(['sort-change', 'page-change', 'update:page'])

const normalizedColumns = computed(() =>
  props.columns.map((column) => ({
    key: column.key,
    label: column.label,
    align: column.align || 'left',
    width: column.width || null,
  })),
)

const resolvedEmptyText = computed(() => props.emptyText || t('common.labels.noData'))
const totalPages = computed(() => {
  if (!props.total || !props.pageSize) return 0
  return Math.max(1, Math.ceil(props.total / props.pageSize))
})
const hasPagination = computed(() => totalPages.value > 1)

function columnSortable(column) {
  return props.sortable && column.key && column.key !== 'actions' && column.sortable !== false
}

function onSort(column) {
  if (!columnSortable(column)) return
  let nextDir = 'asc'
  if (props.sortKey === column.key) {
    nextDir = props.sortDir === 'asc' ? 'desc' : 'asc'
  }
  emit('sort-change', { key: column.key, dir: nextDir })
}

function goToPage(nextPage) {
  const bounded = Math.min(Math.max(nextPage, 1), totalPages.value)
  if (bounded === props.page) return
  emit('update:page', bounded)
  emit('page-change', bounded)
}

function getRowKey(row, index) {
  if (row && row[props.rowKey] !== undefined && row[props.rowKey] !== null) {
    return row[props.rowKey]
  }
  return index
}
</script>

<template>
  <div class="table-wrap">
    <table class="data-table">
      <thead>
        <tr>
          <th
            v-for="column in normalizedColumns"
            :key="column.key"
            :class="`align-${column.align}`"
            :style="column.width ? { width: column.width } : undefined"
            scope="col"
          >
            <button
              v-if="columnSortable(column)"
              type="button"
              class="sort-button"
              @click="onSort(column)"
            >
              <span>{{ column.label }}</span>
              <span class="sort-indicator" :class="{ active: sortKey === column.key }">
                {{ sortKey === column.key ? (sortDir === 'asc' ? '↑' : '↓') : '↕' }}
              </span>
            </button>
            <span v-else>{{ column.label }}</span>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="rows.length === 0">
          <td :colspan="normalizedColumns.length || 1" class="empty-state">
            <slot name="empty">{{ resolvedEmptyText }}</slot>
          </td>
        </tr>
        <tr v-for="(row, index) in rows" :key="getRowKey(row, index)">
          <td
            v-for="column in normalizedColumns"
            :key="column.key"
            :class="`align-${column.align}`"
          >
            <slot :name="`cell-${column.key}`" :row="row" :value="row[column.key]" :column="column">
              {{ row[column.key] ?? '-' }}
            </slot>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="hasPagination" class="table-pagination">
      <button type="button" class="btn" :disabled="page <= 1" @click="goToPage(page - 1)">{{ t('common.actions.previous') }}</button>
      <span class="pagination-label">{{ page }} / {{ totalPages }}</span>
      <button type="button" class="btn" :disabled="page >= totalPages" @click="goToPage(page + 1)">{{ t('common.actions.next') }}</button>
    </div>
  </div>
</template>

<style scoped>
.table-wrap {
  width: 100%;
  overflow-x: auto;
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-secondary);
}

.data-table {
  width: 100%;
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--color-border);
  color: var(--color-text-primary);
  font-size: var(--font-size-sm);
}

.data-table th {
  background: var(--color-bg-header);
  font-weight: var(--font-weight-bold);
  position: sticky;
  top: 0;
  z-index: 1;
}

.sort-button {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  padding: 0;
  cursor: pointer;
}

.sort-indicator {
  opacity: 0.45;
}

.sort-indicator.active {
  opacity: 1;
}

.data-table tr:last-child td {
  border-bottom: none;
}

.align-left {
  text-align: left;
}

.align-right {
  text-align: right;
}

.align-center {
  text-align: center;
}

.empty-state {
  text-align: center;
  color: var(--color-text-secondary);
  padding: var(--space-lg);
}

.table-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--space-sm);
  padding: var(--space-sm);
  border-top: 1px solid var(--color-border);
}

.pagination-label {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}
</style>
