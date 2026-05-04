<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getAudit, getAuditOptions } from '@/api/audit.js'
import { useSettingsStore } from '@/stores/settings.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'

const { t } = useI18n()
const settingsStore = useSettingsStore()

const logs = ref([])
const loading = ref(false)
const exportBusy = ref(false)
const error = ref('')
const expanded = ref(new Set())
const filterOptions = ref({
  actions: [],
  users: [],
  job_ids: [],
})

const filters = ref({
  user: '',
  action: '',
  job_id: '',
  search: '',
  since: '',
  until: '',
})

const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const isMobileViewport = ref(false)
const includeTotalOnNextPageChange = ref(false)
let mobileViewportQuery = null

const columns = computed(() => [
  { key: 'timestamp', label: t('common.labels.date') },
  { key: 'user', label: t('auth.username') },
  { key: 'action', label: t('audit.action') },
  { key: 'job_id', label: t('audit.jobId'), align: 'right' },
  { key: 'client_ip', label: t('audit.clientIp') },
  { key: 'details', label: t('audit.details') },
])

const paginationWindowSize = computed(() => (isMobileViewport.value ? 5 : 10))

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

function buildAuditParams(overrides = {}) {
  return {
    user: filters.value.user || undefined,
    action: filters.value.action || undefined,
    job_id: filters.value.job_id ? Number(filters.value.job_id) : undefined,
    search: filters.value.search.trim() || undefined,
    since: toIsoDate(filters.value.since),
    until: toIsoDate(filters.value.until),
    limit: overrides.limit ?? pageSize.value,
    offset: overrides.offset ?? (page.value - 1) * pageSize.value,
  }
}

async function loadAudit({ includeTotal = false } = {}) {
  loading.value = true
  error.value = ''
  try {
    const response = await getAudit({
      ...buildAuditParams(),
      include_total: includeTotal,
    })
    logs.value = response.entries || []
    if (typeof response.total === 'number') {
      total.value = response.total
    }
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
}

async function loadFilterOptions() {
  try {
    filterOptions.value = await getAuditOptions()
  } catch {
    error.value = t('common.errors.networkError')
  }
}

async function refreshAudit() {
  expanded.value = new Set()
  await loadFilterOptions()
  await loadAudit({ includeTotal: true })
}

async function applyFilters() {
  expanded.value = new Set()
  if (page.value !== 1) {
    includeTotalOnNextPageChange.value = true
    page.value = 1
    return
  }
  await loadAudit({ includeTotal: true })
}

async function exportCsv() {
  exportBusy.value = true
  error.value = ''
  try {
    const rows = []
    let offset = 0
    let hasMore = true

    while (hasMore) {
      const response = await getAudit(buildAuditParams({ limit: 500, offset }))
      const entries = response.entries || []
      rows.push(
        ...entries.map((entry) => ({
          timestamp: entry.timestamp || '',
          user: entry.user || '',
          action: entry.action || '',
          job_id: entry.job_id || '',
          client_ip: entry.client_ip || '',
          details: JSON.stringify(entry.details || {}),
        })),
      )
      hasMore = Boolean(response.has_more)
      if (!entries.length) break
      offset += entries.length
    }

    const header = Object.keys(rows[0] || { timestamp: '', user: '', action: '', job_id: '', client_ip: '', details: '' })
    const lines = [
      header.join(','),
      ...rows.map((row) => header.map((key) => `"${String(row[key]).replace(/"/g, '""')}"`).join(',')),
    ]

    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
    anchor.download = `${settingsStore.auditExportFilename}-${timestamp}.csv`
    anchor.click()
    setTimeout(() => URL.revokeObjectURL(url), settingsStore.downloadRevokeDelayMs)
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    exportBusy.value = false
  }
}

function syncViewportState(event) {
  isMobileViewport.value = Boolean(event?.matches)
}

watch(page, () => {
  const includeTotal = includeTotalOnNextPageChange.value
  includeTotalOnNextPageChange.value = false
  void loadAudit({ includeTotal })
})

onMounted(async () => {
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    mobileViewportQuery = window.matchMedia('(max-width: 768px)')
    syncViewportState(mobileViewportQuery)
    if (typeof mobileViewportQuery.addEventListener === 'function') {
      mobileViewportQuery.addEventListener('change', syncViewportState)
    } else if (typeof mobileViewportQuery.addListener === 'function') {
      mobileViewportQuery.addListener(syncViewportState)
    }
  }
  await loadFilterOptions()
  await loadAudit({ includeTotal: true })
})

onUnmounted(() => {
  if (!mobileViewportQuery) return
  if (typeof mobileViewportQuery.removeEventListener === 'function') {
    mobileViewportQuery.removeEventListener('change', syncViewportState)
  } else if (typeof mobileViewportQuery.removeListener === 'function') {
    mobileViewportQuery.removeListener(syncViewportState)
  }
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('audit.title') }}</h1>
      <div class="actions audit-toolbar">
        <button class="btn" :disabled="loading || exportBusy" @click="refreshAudit">{{ t('common.actions.refresh') }}</button>
        <button class="btn btn-primary" :disabled="loading || exportBusy" @click="exportCsv">{{ t('audit.exportAuditCsv') }}</button>
      </div>
    </header>

    <div class="filters">
      <select v-model="filters.user" :aria-label="t('audit.userFilter')">
        <option value="">{{ t('audit.anyUser') }}</option>
        <option v-for="userOption in filterOptions.users" :key="userOption" :value="userOption">{{ userOption }}</option>
      </select>
      <select v-model="filters.action" :aria-label="t('audit.actionFilter')">
        <option value="">{{ t('audit.anyAction') }}</option>
        <option v-for="actionOption in filterOptions.actions" :key="actionOption" :value="actionOption">{{ actionOption }}</option>
      </select>
      <select v-model="filters.job_id" :aria-label="t('audit.jobIdFilter')">
        <option value="">{{ t('audit.anyJob') }}</option>
        <option v-for="jobIdOption in filterOptions.job_ids" :key="jobIdOption" :value="String(jobIdOption)">#{{ jobIdOption }}</option>
      </select>
      <input
        v-model="filters.search"
        type="text"
        :placeholder="t('audit.searchFilter')"
        :aria-label="t('audit.searchFilter')"
        @keydown.enter.prevent="applyFilters"
      />
      <input
        v-model="filters.since"
        type="datetime-local"
        :aria-label="t('audit.dateFrom')"
      />
      <input
        v-model="filters.until"
        type="datetime-local"
        :aria-label="t('audit.dateTo')"
      />
      <button class="btn" :disabled="loading || exportBusy" @click="applyFilters">{{ t('audit.applyFilters') }}</button>
    </div>

    <section class="audit-log-section">
      <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
      <p v-if="error" class="error-banner">{{ error }}</p>

      <DataTable :columns="columns" :rows="logs" :empty-text="t('audit.empty')">
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

      <Pagination
        v-model:page="page"
        :page-size="pageSize"
        :total="total"
        :show-page-window="true"
        :window-size="paginationWindowSize"
        :jump-size="paginationWindowSize"
      />
    </section>
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

:deep(.data-table th),
:deep(.data-table th > span),
:deep(.data-table th .sort-button),
:deep(.data-table th .sort-button > span) {
  font-weight: var(--font-weight-bold);
}

input,
select {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
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
