<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getDirectory, getDirectoryByMountId } from '@/api/browse.js'
import { logger } from '@/utils/logger.js'

const props = defineProps({
  /** The mount root path (USB mount_path or network local_mount_point). */
  mountPath: {
    type: String,
    default: '',
  },
  mountId: {
    type: Number,
    default: null,
  },
  rootLabel: {
    type: String,
    default: '',
  },
  showRootCrumbAtRoot: {
    type: Boolean,
    default: false,
  },
  directoriesOnly: {
    type: Boolean,
    default: false,
  },
  currentDirectory: {
    type: String,
    default: null,
  },
  showBreadcrumb: {
    type: Boolean,
    default: true,
  },
  showParentEntry: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:currentDirectory'])

const { t } = useI18n()

const displayedRootLabel = computed(() => props.rootLabel || props.mountPath)

// --- State ---
const internalCurrentDirectory = ref('/')
const lastInvalidControlledPath = ref('')
const page = ref(1)
const pageSize = ref(100)

const entries = ref([])
const hasMore = ref(false)
const loading = ref(false)
const error = ref('')

// --- Breadcrumbs ---
function normalizeDirectoryPath(path) {
  const trimmed = String(path ?? '').trim()
  if (!trimmed || trimmed === '/') {
    return '/'
  }

  const normalized = trimmed
    .replace(/\\/g, '/')
    .replace(/^\/+/, '')
    .replace(/\/+/g, '/')
    .replace(/\/+$/, '')

  return normalized ? `/${normalized}` : '/'
}

const currentDirectoryPath = computed(() => normalizeDirectoryPath(
  props.currentDirectory != null ? props.currentDirectory : internalCurrentDirectory.value,
))

const subdir = computed(() => (
  currentDirectoryPath.value === '/' ? '' : currentDirectoryPath.value.slice(1)
))

const breadcrumbs = computed(() => {
  const parts = subdir.value ? subdir.value.split('/').filter(Boolean) : []
  return parts
})

const showRootCrumb = computed(() => Boolean(props.rootLabel) || props.showRootCrumbAtRoot || breadcrumbs.value.length > 0)

const rootCrumbLabel = computed(() => {
  if (props.rootLabel) {
    return displayedRootLabel.value
  }
  return '/'
})

const canNavigateToParent = computed(() => props.showParentEntry && currentDirectoryPath.value !== '/')

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

const displayedEntries = computed(() => (
  props.directoriesOnly
    ? sortedEntries.value.filter((entry) => entry.type === 'directory')
    : sortedEntries.value
))

function setCurrentDirectory(path) {
  const normalized = normalizeDirectoryPath(path)
  if (props.currentDirectory != null) {
    emit('update:currentDirectory', normalized)
    return
  }
  internalCurrentDirectory.value = normalized
}

// --- Navigation ---
function navigateInto(dirName) {
  const nextPath = currentDirectoryPath.value === '/'
    ? `/${dirName}`
    : `${currentDirectoryPath.value}/${dirName}`
  setCurrentDirectory(nextPath)
  page.value = 1
}

function navigateToParent() {
  if (currentDirectoryPath.value === '/') return

  const parts = subdir.value.split('/').filter(Boolean)
  const nextPath = parts.length <= 1 ? '/' : `/${parts.slice(0, -1).join('/')}`
  setCurrentDirectory(nextPath)
  page.value = 1
}

function navigateToCrumb(index) {
  // index -1 = root
  if (index < 0) {
    setCurrentDirectory('/')
  } else {
    const parts = subdir.value.split('/').filter(Boolean)
    setCurrentDirectory(`/${parts.slice(0, index + 1).join('/')}`)
  }
  page.value = 1
}

// --- Data fetching ---
async function loadEntries() {
  loading.value = true
  error.value = ''
  try {
    const result = props.mountId != null
      ? await getDirectoryByMountId(props.mountId, subdir.value, page.value, pageSize.value, props.directoriesOnly)
      : await getDirectory(props.mountPath, subdir.value, page.value, pageSize.value, props.directoriesOnly)
    entries.value = result.entries
    hasMore.value = Boolean(result.has_more)
    lastInvalidControlledPath.value = ''
  } catch (err) {
    const status = Number(err?.response?.status || 0)
    if (
      props.currentDirectory != null
      && currentDirectoryPath.value !== '/'
      && (status === 400 || status === 404)
      && lastInvalidControlledPath.value !== currentDirectoryPath.value
    ) {
      lastInvalidControlledPath.value = currentDirectoryPath.value
      setCurrentDirectory('/')
      return
    }

    logger.error('[DirectoryBrowser] Failed to load directory listing:', err)
    error.value = t('browse.loadError')
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.mountPath, props.mountId],
  () => {
    if (props.currentDirectory == null) {
      internalCurrentDirectory.value = '/'
    }
    page.value = 1
    loadEntries()
  },
  { immediate: true },
)
watch([subdir, page], loadEntries)

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
  return isNaN(d.getTime()) ? '—' : d.toLocaleString()
}

function isNavigable(entry) {
  return entry.type === 'directory'
}

function onRowArrowKey(event) {
  const buttons = Array.from(event.currentTarget.closest('tbody').querySelectorAll('.entry-nav-btn'))
  const idx = buttons.indexOf(event.currentTarget)
  if (idx < 0) return
  const next = event.key === 'ArrowDown' ? idx + 1 : idx - 1
  if (next >= 0 && next < buttons.length) {
    event.preventDefault()
    buttons[next].focus()
  }
}

function goToPreviousPage() {
  if (page.value > 1) {
    page.value -= 1
  }
}

function goToNextPage() {
  if (hasMore.value) {
    page.value += 1
  }
}
</script>

<template>
  <div class="directory-browser">
    <!-- Breadcrumb trail -->
    <nav v-if="showBreadcrumb" class="breadcrumb" aria-label="breadcrumb">
      <button v-if="showRootCrumb" class="crumb-btn" @click="navigateToCrumb(-1)">{{ rootCrumbLabel }}</button>
      <template v-for="(crumb, index) in breadcrumbs" :key="index">
        <span v-if="props.rootLabel || index > 0" class="crumb-sep" aria-hidden="true">/</span>
        <span
          v-if="index === breadcrumbs.length - 1"
          class="crumb-btn crumb-current"
          aria-current="page"
        >
          {{ crumb }}
        </span>
        <button
          v-else
          class="crumb-btn"
          @click="navigateToCrumb(index)"
        >
          {{ crumb }}
        </button>
      </template>
    </nav>

    <!-- Status messages -->
    <div aria-live="polite">
      <p v-if="loading" class="status-msg muted">{{ t('common.labels.loading') }}</p>
      <p v-else-if="error" class="status-msg error-banner" role="alert">{{ error }}</p>
    </div>

    <!-- Directory table -->
    <div v-if="!loading && !error" class="dir-table-scroll">
    <table class="dir-table" :aria-label="t('browse.tableLabel')">
      <thead>
        <tr>
          <th class="col-name"
            :aria-sort="sortKey === 'name' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
          >
            <button class="sort-btn" @click="toggleSort('name')">
              {{ t('browse.columns.name') }}
              <span
                class="sort-indicator"
                :class="sortKey === 'name' ? (sortDir === 'asc' ? 'sort-asc' : 'sort-desc') : 'sort-none'"
                aria-hidden="true"
              ></span>
            </button>
          </th>
          <th class="col-type"
            :aria-sort="sortKey === 'type' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
          >
            <button class="sort-btn" @click="toggleSort('type')">
              {{ t('browse.columns.type') }}
              <span
                class="sort-indicator"
                :class="sortKey === 'type' ? (sortDir === 'asc' ? 'sort-asc' : 'sort-desc') : 'sort-none'"
                aria-hidden="true"
              ></span>
            </button>
          </th>
          <th class="col-size"
            :aria-sort="sortKey === 'size_bytes' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
          >
            <button class="sort-btn" @click="toggleSort('size_bytes')">
              {{ t('browse.columns.size') }}
              <span
                class="sort-indicator"
                :class="sortKey === 'size_bytes' ? (sortDir === 'asc' ? 'sort-asc' : 'sort-desc') : 'sort-none'"
                aria-hidden="true"
              ></span>
            </button>
          </th>
          <th class="col-modified"
            :aria-sort="sortKey === 'modified_at' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'"
          >
            <button class="sort-btn" @click="toggleSort('modified_at')">
              {{ t('browse.columns.modified') }}
              <span
                class="sort-indicator"
                :class="sortKey === 'modified_at' ? (sortDir === 'asc' ? 'sort-asc' : 'sort-desc') : 'sort-none'"
                aria-hidden="true"
              ></span>
            </button>
          </th>
        </tr>
      </thead>
      <tbody>
        <tr v-if="displayedEntries.length === 0">
          <td colspan="4" class="empty-row muted">{{ t('browse.empty') }}</td>
        </tr>
        <tr v-if="canNavigateToParent" class="dir-row dir-row--navigable dir-row--parent">
          <td class="col-name">
            <span class="entry-icon" aria-hidden="true">↩</span>
            <button
              class="entry-nav-btn entry-nav-btn--parent"
              type="button"
              :aria-label="t('browse.parentDirectory')"
              @click="navigateToParent"
              @keydown.arrow-down="onRowArrowKey($event)"
              @keydown.arrow-up="onRowArrowKey($event)"
            >..</button>
          </td>
          <td class="col-type muted">{{ t('browse.parentDirectory') }}</td>
          <td class="col-size">—</td>
          <td class="col-modified">—</td>
        </tr>
        <tr
          v-for="entry in displayedEntries"
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
              @keydown.arrow-down="onRowArrowKey($event)"
              @keydown.arrow-up="onRowArrowKey($event)"
            >{{ entry.name }}</button>
            <span v-else>{{ entry.name }}</span>
          </td>
          <td class="col-type">{{ t(`browse.types.${entry.type}`) }}</td>
          <td class="col-size">{{ formatSize(entry.size_bytes) }}</td>
          <td class="col-modified">{{ formatDate(entry.modified_at) }}</td>
        </tr>
      </tbody>
    </table>
    </div>

    <div v-if="page > 1 || hasMore" class="browse-pagination" role="navigation" :aria-label="t('common.labels.pagination')">
      <span class="page-label">{{ page }}</span>
      <button type="button" class="btn page-btn" :disabled="page <= 1" @click="goToPreviousPage">{{ t('common.actions.previous') }}</button>
      <button type="button" class="btn page-btn" :disabled="!hasMore" @click="goToNextPage">{{ t('common.actions.next') }}</button>
    </div>
  </div>
</template>

<style scoped>
.directory-browser {
  display: grid;
  gap: var(--space-sm);
  min-width: 0;
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
.dir-table-scroll {
  overflow-x: auto;
}

.browse-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: var(--space-sm);
}

.page-label {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.page-btn {
  background: var(--color-bg-secondary);
}

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
  display: inline-block;
  font-size: 0.75em;
  margin-left: 4px;
  opacity: 0.6;
  width: 0;
  height: 0;
  vertical-align: middle;
}

.sort-indicator.sort-asc {
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-bottom: 5px solid currentColor;
  opacity: 1;
}

.sort-indicator.sort-desc {
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 5px solid currentColor;
  opacity: 1;
}

.sort-indicator.sort-none {
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-top: 4px solid currentColor;
  border-bottom: 0;
  position: relative;
}

.sort-indicator.sort-none::after {
  content: '';
  display: block;
  width: 0;
  height: 0;
  border-left: 4px solid transparent;
  border-right: 4px solid transparent;
  border-bottom: 4px solid currentColor;
  position: absolute;
  top: -8px;
  left: -4px;
}

.dir-row--navigable {
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
