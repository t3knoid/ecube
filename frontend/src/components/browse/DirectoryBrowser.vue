<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getDirectory } from '@/api/browse.js'
import Pagination from '@/components/common/Pagination.vue'

const props = defineProps({
  /** The mount root path (USB mount_path or network local_mount_point). */
  mountPath: {
    type: String,
    required: true,
  },
})

const { t } = useI18n()

// --- State ---
const subdir = ref('')
const page = ref(1)
const pageSize = ref(100)

const entries = ref([])
const total = ref(0)
const loading = ref(false)
const error = ref('')

// --- Breadcrumbs ---
const breadcrumbs = computed(() => {
  const parts = subdir.value ? subdir.value.split('/').filter(Boolean) : []
  return parts
})

// --- Sorting ---
const sortKey = ref('name')
const sortDir = ref('asc')

function toggleSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'asc'
  }
}

const sortedEntries = computed(() => {
  const sorted = [...entries.value]
  sorted.sort((a, b) => {
    let aVal = a[sortKey.value]
    let bVal = b[sortKey.value]
    if (sortKey.value === 'size_bytes') {
      aVal = aVal ?? -1
      bVal = bVal ?? -1
    } else if (sortKey.value === 'modified_at') {
      aVal = aVal ? new Date(aVal).getTime() : -1
      bVal = bVal ? new Date(bVal).getTime() : -1
    } else {
      aVal = (aVal || '').toLowerCase()
      bVal = (bVal || '').toLowerCase()
    }
    if (aVal < bVal) return sortDir.value === 'asc' ? -1 : 1
    if (aVal > bVal) return sortDir.value === 'asc' ? 1 : -1
    return 0
  })
  return sorted
})

// --- Navigation ---
function navigateInto(dirName) {
  subdir.value = subdir.value ? `${subdir.value}/${dirName}` : dirName
  page.value = 1
}

function navigateToCrumb(index) {
  // index -1 = root
  if (index < 0) {
    subdir.value = ''
  } else {
    const parts = subdir.value.split('/').filter(Boolean)
    subdir.value = parts.slice(0, index + 1).join('/')
  }
  page.value = 1
}

// --- Data fetching ---
async function loadEntries() {
  loading.value = true
  error.value = ''
  try {
    const result = await getDirectory(props.mountPath, subdir.value, page.value, pageSize.value)
    entries.value = result.entries
    total.value = result.total
  } catch (err) {
    console.error('[DirectoryBrowser] Failed to load directory listing:', err)
    error.value = t('browse.loadError')
  } finally {
    loading.value = false
  }
}

watch([() => props.mountPath, subdir, page], loadEntries, { immediate: true })

// --- Helpers ---
function formatSize(bytes) {
  if (bytes == null) return '—'
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unit]}`
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return isNaN(d.getTime()) ? '—' : d.toLocaleDateString()
}

function isNavigable(entry) {
  return entry.type === 'directory'
}
</script>

<template>
  <div class="directory-browser">
    <!-- Breadcrumb trail -->
    <nav class="breadcrumb" aria-label="breadcrumb">
      <button class="crumb-btn" @click="navigateToCrumb(-1)">{{ mountPath }}</button>
      <template v-for="(crumb, index) in breadcrumbs" :key="index">
        <span class="crumb-sep" aria-hidden="true">/</span>
        <button
          class="crumb-btn"
          :class="{ 'crumb-current': index === breadcrumbs.length - 1 }"
          :aria-current="index === breadcrumbs.length - 1 ? 'page' : undefined"
          @click="navigateToCrumb(index)"
        >
          {{ crumb }}
        </button>
      </template>
    </nav>

    <!-- Status messages -->
    <p v-if="loading" class="status-msg muted">{{ t('common.labels.loading') }}</p>
    <p v-else-if="error" class="status-msg error-banner">{{ error }}</p>

    <!-- Directory table -->
    <table v-if="!loading && !error" class="dir-table">
      <thead>
        <tr>
          <th class="col-name"
            :aria-sort="sortKey === 'name' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
          >
            <button class="sort-btn" @click="toggleSort('name')">
              {{ t('browse.columns.name') }}
              <span class="sort-indicator" aria-hidden="true">
                {{ sortKey === 'name' ? (sortDir === 'asc' ? '▲' : '▼') : '⇅' }}
              </span>
            </button>
          </th>
          <th class="col-type"
            :aria-sort="sortKey === 'type' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
          >
            <button class="sort-btn" @click="toggleSort('type')">
              {{ t('browse.columns.type') }}
              <span class="sort-indicator" aria-hidden="true">
                {{ sortKey === 'type' ? (sortDir === 'asc' ? '▲' : '▼') : '⇅' }}
              </span>
            </button>
          </th>
          <th class="col-size"
            :aria-sort="sortKey === 'size_bytes' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
          >
            <button class="sort-btn" @click="toggleSort('size_bytes')">
              {{ t('browse.columns.size') }}
              <span class="sort-indicator" aria-hidden="true">
                {{ sortKey === 'size_bytes' ? (sortDir === 'asc' ? '▲' : '▼') : '⇅' }}
              </span>
            </button>
          </th>
          <th class="col-modified"
            :aria-sort="sortKey === 'modified_at' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
          >
            <button class="sort-btn" @click="toggleSort('modified_at')">
              {{ t('browse.columns.modified') }}
              <span class="sort-indicator" aria-hidden="true">
                {{ sortKey === 'modified_at' ? (sortDir === 'asc' ? '▲' : '▼') : '⇅' }}
              </span>
            </button>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="sortedEntries.length === 0">
          <td colspan="4" class="empty-row muted">{{ t('browse.empty') }}</td>
        </tr>
        <tr
          v-for="entry in sortedEntries"
          :key="entry.name"
          :class="['dir-row', { 'dir-row--navigable': isNavigable(entry) }]"
        >
          <td class="col-name">
            <span class="entry-icon" aria-hidden="true">
              {{ entry.type === 'directory' ? '📁' : entry.type === 'symlink' ? '🔗' : '📄' }}
            </span>
            <button
              v-if="isNavigable(entry)"
              class="entry-nav-btn"
              @click="navigateInto(entry.name)"
            >{{ entry.name }}</button>
            <span v-else>{{ entry.name }}</span>
          </td>
          <td class="col-type">{{ t(`browse.types.${entry.type}`) }}</td>
          <td class="col-size">{{ formatSize(entry.size_bytes) }}</td>
          <td class="col-modified">{{ formatDate(entry.modified_at) }}</td>
        </tr>
      </tbody>
    </table>

    <!-- Pagination -->
    <Pagination v-if="total > pageSize" v-model:page="page" :page-size="pageSize" :total="total" />
  </div>
</template>

<style scoped>
.directory-browser {
  display: grid;
  gap: var(--space-sm);
}

/* Breadcrumb */
.breadcrumb {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 2px;
  font-size: 0.875rem;
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
  overflow-x: auto;
}

.crumb-btn {
  background: none;
  border: none;
  color: var(--color-accent, var(--color-text-primary));
  cursor: pointer;
  padding: 0 2px;
  font-size: inherit;
  text-decoration: underline;
  text-underline-offset: 2px;
}

.crumb-btn.crumb-current {
  color: var(--color-text-primary);
  text-decoration: none;
  cursor: default;
  font-weight: var(--font-weight-bold, 600);
}

.crumb-sep {
  color: var(--color-text-secondary);
  user-select: none;
}

/* Table */
.dir-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.dir-table th {
  text-align: left;
  padding: var(--space-xs) var(--space-sm);
  border-bottom: 2px solid var(--color-border);
  font-weight: var(--font-weight-bold, 600);
  white-space: nowrap;
}

.dir-table td {
  padding: var(--space-xs) var(--space-sm);
  border-bottom: 1px solid var(--color-border);
  vertical-align: middle;
}

.sort-btn {
  display: inline-flex;
  align-items: center;
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  font-weight: inherit;
  color: inherit;
  cursor: pointer;
  white-space: nowrap;
}

.sort-btn:hover {
  color: var(--color-accent, inherit);
}

.sort-btn:focus-visible {
  outline: 2px solid var(--color-accent, currentColor);
  outline-offset: 2px;
  border-radius: 2px;
}

.sort-indicator {
  font-size: 0.75em;
  margin-left: 4px;
  opacity: 0.6;
}

.dir-row--navigable {
  cursor: pointer;
}

.dir-row--navigable:hover td {
  background: var(--color-bg-hover, var(--color-bg-primary));
}

.entry-icon {
  margin-right: var(--space-xs);
}

.entry-nav-btn {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  color: var(--color-accent, inherit);
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}

.entry-nav-btn:hover,
.entry-nav-btn:focus-visible {
  color: var(--color-accent-hover, var(--color-accent, inherit));
  outline: 2px solid var(--color-accent, currentColor);
  outline-offset: 2px;
  border-radius: 2px;
}

.col-size,
.col-modified {
  text-align: right;
  white-space: nowrap;
}

.empty-row {
  text-align: center;
  padding: var(--space-md);
}

.status-msg {
  padding: var(--space-xs);
}

.muted {
  color: var(--color-text-secondary);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}
</style>
