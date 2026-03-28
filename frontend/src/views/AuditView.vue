<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAudit } from '@/api/audit.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'

const { t } = useI18n()

const logs = ref([])
const loading = ref(false)
const error = ref('')
const expanded = ref(new Set())

const filters = ref({
  user: '',
  action: '',
  since: '',
  until: '',
})

const page = ref(1)
const pageSize = ref(20)

const columns = computed(() => [
  { key: 'timestamp', label: t('common.labels.date') },
  { key: 'user', label: t('auth.username') },
  { key: 'action', label: t('audit.action') },
  { key: 'job_id', label: t('audit.jobId'), align: 'right' },
  { key: 'client_ip', label: t('audit.clientIp') },
  { key: 'details', label: t('audit.details') },
])

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return logs.value.slice(start, start + pageSize.value)
})

function toggleDetails(id) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
  expanded.value = new Set(expanded.value)
}

function asLocalDate(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleString()
}

function toIsoDate(value) {
  return value ? new Date(value).toISOString() : undefined
}

async function loadAudit() {
  loading.value = true
  error.value = ''
  try {
    logs.value = await getAudit({
      user: filters.value.user || undefined,
      action: filters.value.action || undefined,
      since: toIsoDate(filters.value.since),
      until: toIsoDate(filters.value.until),
      limit: 500,
      offset: 0,
    })
    page.value = 1
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
}

function exportCsv() {
  const rows = logs.value.map((entry) => ({
    timestamp: entry.timestamp || '',
    user: entry.user || '',
    action: entry.action || '',
    job_id: entry.job_id || '',
    client_ip: entry.client_ip || '',
    details: JSON.stringify(entry.details || {}),
  }))

  const header = Object.keys(rows[0] || { timestamp: '', user: '', action: '', job_id: '', client_ip: '', details: '' })
  const lines = [
    header.join(','),
    ...rows.map((row) => header.map((key) => `"${String(row[key]).replace(/"/g, '""')}"`).join(',')),
  ]

  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = 'audit-log-export.csv'
  anchor.click()
  URL.revokeObjectURL(url)
}

onMounted(loadAudit)
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('audit.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadAudit">{{ t('common.actions.refresh') }}</button>
        <button class="btn btn-primary" @click="exportCsv">{{ t('audit.exportCsv') }}</button>
      </div>
    </header>

    <div class="filters">
      <input v-model="filters.user" type="text" :placeholder="t('audit.userFilter')" />
      <input v-model="filters.action" type="text" :placeholder="t('audit.actionFilter')" />
      <input v-model="filters.since" type="datetime-local" />
      <input v-model="filters.until" type="datetime-local" />
      <button class="btn" @click="loadAudit">{{ t('audit.applyFilters') }}</button>
    </div>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <DataTable :columns="columns" :rows="paged" :empty-text="t('audit.empty')">
      <template #cell-timestamp="{ row }">{{ asLocalDate(row.timestamp) }}</template>
      <template #cell-action="{ row }"><StatusBadge :status="row.action" /></template>
      <template #cell-details="{ row }">
        <div class="details-cell">
          <button class="btn" @click="toggleDetails(row.id)">
            {{ expanded.has(row.id) ? t('audit.hideDetails') : t('audit.showDetails') }}
          </button>
          <pre v-if="expanded.has(row.id)">{{ JSON.stringify(row.details || {}, null, 2) }}</pre>
        </div>
      </template>
    </DataTable>

    <Pagination v-model:page="page" :page-size="pageSize" :total="logs.length" />
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row,
.actions,
.filters {
  display: flex;
  gap: var(--space-sm);
}

.header-row {
  justify-content: space-between;
  align-items: center;
}

.filters {
  flex-wrap: wrap;
}

input,
.btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.btn {
  cursor: pointer;
}

.details-cell {
  display: grid;
  gap: var(--space-xs);
}

pre {
  max-width: 420px;
  max-height: 180px;
  overflow: auto;
  margin: 0;
  background: var(--color-bg-input);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-xs);
  font-size: var(--font-size-xs);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.muted {
  color: var(--color-text-secondary);
}
</style>
