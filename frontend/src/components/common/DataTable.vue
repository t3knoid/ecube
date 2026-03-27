<script setup>
import { computed } from 'vue'

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
    default: 'No data',
  },
})

const normalizedColumns = computed(() =>
  props.columns.map((column) => ({
    key: column.key,
    label: column.label,
    align: column.align || 'left',
    width: column.width || null,
  })),
)

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
            {{ column.label }}
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="rows.length === 0">
          <td :colspan="normalizedColumns.length || 1" class="empty-state">
            <slot name="empty">{{ emptyText }}</slot>
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
</style>
