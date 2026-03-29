<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getDrives, refreshDrives } from '@/api/drives.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'

const { t } = useI18n()
const router = useRouter()

const drives = ref([])
const loading = ref(false)
const refreshing = ref(false)
const error = ref('')
const search = ref('')
const stateFilter = ref('ALL')
const sortKey = ref('id')
const sortDir = ref('asc')
const page = ref(1)
const pageSize = ref(10)

const columns = computed(() => [
  { key: 'id', label: t('common.labels.id'), align: 'right' },
  { key: 'device_identifier', label: t('drives.device') },
  { key: 'filesystem_type', label: t('drives.filesystem') },
  { key: 'capacity_bytes', label: t('common.labels.size'), align: 'right' },
  { key: 'current_state', label: t('common.labels.status') },
  { key: 'current_project_id', label: t('dashboard.project') },
  { key: 'actions', label: t('common.actions.edit'), align: 'center' },
])

function formatBytes(value) {
  if (typeof value !== 'number' || value <= 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let next = value
  let unit = 0
  while (next >= 1024 && unit < units.length - 1) {
    next /= 1024
    unit += 1
  }
  return `${next.toFixed(next >= 10 ? 0 : 1)} ${units[unit]}`
}

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return drives.value.filter((drive) => {
    const state = String(drive.current_state || '').toUpperCase()
    const stateMatch = stateFilter.value === 'ALL' || state === stateFilter.value
    const text = [
      drive.device_identifier,
      drive.filesystem_type,
      drive.current_project_id,
      drive.filesystem_path,
      String(drive.id),
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    const queryMatch = !query || text.includes(query)
    return stateMatch && queryMatch
  })
})

const sorted = computed(() => {
  const list = [...filtered.value]
  list.sort((a, b) => {
    const left = a[sortKey.value]
    const right = b[sortKey.value]
    if (left === right) return 0
    const order = sortDir.value === 'asc' ? 1 : -1
    if (left === undefined || left === null) return 1
    if (right === undefined || right === null) return -1
    if (typeof left === 'number' && typeof right === 'number') {
      return (left - right) * order
    }
    return String(left).localeCompare(String(right)) * order
  })
  return list
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return sorted.value.slice(start, start + pageSize.value)
})

function setSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}

async function loadDrives() {
  loading.value = true
  error.value = ''
  try {
    drives.value = await getDrives()
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
}

async function rescan() {
  refreshing.value = true
  error.value = ''
  try {
    await refreshDrives()
    await loadDrives()
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    refreshing.value = false
  }
}

function openDrive(drive) {
  router.push({ name: 'drive-detail', params: { id: drive.id } })
}

onMounted(loadDrives)
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('drives.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadDrives">{{ t('common.actions.refresh') }}</button>
        <button class="btn btn-primary" :disabled="refreshing" @click="rescan">
          {{ refreshing ? t('common.labels.loading') : t('drives.rescan') }}
        </button>
      </div>
    </header>

    <p v-if="error" class="error-banner">{{ error }}</p>

    <div class="filters">
      <input v-model="search" type="text" :placeholder="t('drives.searchPlaceholder')" />
      <select v-model="stateFilter">
        <option value="ALL">{{ t('drives.allStates') }}</option>
        <option value="EMPTY">{{ t('drives.states.empty') }}</option>
        <option value="AVAILABLE">{{ t('drives.states.available') }}</option>
        <option value="IN_USE">{{ t('drives.states.inUse') }}</option>
      </select>
      <select v-model="sortKey">
        <option value="id">{{ t('common.labels.id') }}</option>
        <option value="device_identifier">{{ t('drives.device') }}</option>
        <option value="filesystem_type">{{ t('drives.filesystem') }}</option>
        <option value="current_state">{{ t('common.labels.status') }}</option>
      </select>
      <button class="btn" @click="setSort(sortKey)">
        {{ sortDir === 'asc' ? t('drives.sortAsc') : t('drives.sortDesc') }}
      </button>
    </div>

    <DataTable :columns="columns" :rows="paged" :empty-text="t('drives.empty')">
      <template #cell-current_state="{ row }">
        <StatusBadge :status="row.current_state" />
      </template>
      <template #cell-capacity_bytes="{ row }">
        {{ formatBytes(row.capacity_bytes) }}
      </template>
      <template #cell-actions="{ row }">
        <button class="btn" @click="openDrive(row)">{{ t('drives.open') }}</button>
      </template>
    </DataTable>

    <Pagination v-model:page="page" :page-size="pageSize" :total="sorted.length" />
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
  align-items: center;
  justify-content: space-between;
}

.filters {
  flex-wrap: wrap;
}

input,
select {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}
</style>
