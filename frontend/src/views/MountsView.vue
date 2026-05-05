<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getMounts, createMount, updateMount, deleteMount, validateMount, validateMountCandidate, discoverMountShares } from '@/api/mounts.js'
import { getPublicAuthConfig } from '@/api/auth.js'
import { listAllJobs } from '@/api/jobs.js'
import { normalizeErrorMessage } from '@/api/client.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import DirectoryBrowser from '@/components/browse/DirectoryBrowser.vue'
import { useAuthStore } from '@/stores/auth.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'
import { buildProjectEvidenceMap, getProjectEvidenceJobId } from '@/utils/projectEvidence.js'

const { t } = useI18n()
const authStore = useAuthStore()
const router = useRouter()

const mounts = ref([])
const mountJobByProject = ref(new Map())
const loading = ref(false)
const saving = ref(false)
const dialogTesting = ref(false)
const error = ref('')
const successMessage = ref('')
const dialogError = ref('')
const dialogSuccessMessage = ref('')
const editingMountId = ref(null)
const dialogValidationPassed = ref(false)
const dialogBrowsing = ref(false)

const showAddDialog = ref(false)
const showRemoveDialog = ref(false)
const showShareBrowserDialog = ref(false)
const removeTarget = ref(null)

const page = ref(1)
const pageSize = ref(10)
const search = ref('')
const isMobileViewport = ref(false)
let mobileViewportQuery = null

/** Mount ID currently being browsed (null = none open). */
const browsingMountId = ref(null)

/** The currently-browsed mount object (computed from browsingMountId). */
const activeBrowsedMount = computed(() =>
  browsingMountId.value !== null
    ? mounts.value.find((m) => m.id === browsingMountId.value) || null
    : null
)

const form = ref({
  type: 'SMB',
  remote_path: '',
  project_id: '',
  nfs_client_version: '',
  username: '',
  password: '',
  credentials_file: '',
})

const credentialFieldState = ref({
  username: false,
  password: false,
  credentials_file: false,
})

const addDialogRef = ref(null)
const addDialogTriggerRef = ref(null)
const addMountDialogTitleId = 'add-mount-dialog-title'
const shareBrowserDialogRef = ref(null)
const shareBrowserTriggerRef = ref(null)
const shareBrowserTitleId = 'mount-share-browser-title'

const publicAuthConfig = ref({
  demo_mode_enabled: false,
  default_nfs_client_version: '4.1',
  nfs_client_version_options: ['4.2', '4.1', '4.0', '3'],
})

const discoveredShares = ref([])
const shareBrowserError = ref('')

const canManageMounts = computed(() => authStore.hasAnyRole(['admin', 'manager']))
const isEditMode = computed(() => editingMountId.value !== null)
const activeEditMount = computed(() => (
  editingMountId.value !== null
    ? mounts.value.find((mount) => mount.id === editingMountId.value) || null
    : null
))
const dialogTitle = computed(() => (isEditMode.value ? t('mounts.editDialogTitle') : t('mounts.addDialogTitle')))
const dialogSubmitLabel = computed(() => (isEditMode.value ? t('common.actions.save') : t('common.actions.create')))
const dialogLocalMountPoint = computed(() => activeEditMount.value?.local_mount_point || '')
const shareDiscoveryAvailable = computed(() => !isEditMode.value)
const nfsClientVersionOptions = computed(() => {
  const configured = Array.isArray(publicAuthConfig.value?.nfs_client_version_options)
    ? publicAuthConfig.value.nfs_client_version_options
    : []
  return configured.length ? configured : ['4.2', '4.1', '4.0', '3']
})
const nfsClientVersionSelectOptions = computed(() => [
  {
    value: '',
    label: t('mounts.nfsClientVersionDefaultOption', {
      version: publicAuthConfig.value.default_nfs_client_version || '4.1',
    }),
  },
  ...nfsClientVersionOptions.value.map((option) => ({ value: option, label: option })),
])

const columns = computed(() => {
  const nextColumns = [
    { key: 'id', label: t('common.labels.id'), align: 'right' },
    { key: 'type', label: t('common.labels.type') },
    { key: 'project_id', label: t('dashboard.project') },
    { key: 'status', label: t('common.labels.status') },
    { key: 'current_project_job_id', label: t('jobs.jobId'), align: 'right' },
    { key: 'last_checked_at', label: t('mounts.lastChecked') },
  ]

  if (isMobileViewport.value) {
    return nextColumns.filter((column) => column.key !== 'type' && column.key !== 'last_checked_at')
  }

  return nextColumns
})

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return mounts.value.filter((mount) => {
    if (!query) return true
    const text = [mount.type, mount.project_id, mount.remote_path, mount.local_mount_point, mount.status].join(' ').toLowerCase()
    return text.includes(query)
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

function toIso(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleString()
}

function normalizeStatusValue(status) {
  return String(status ?? 'unknown').toUpperCase()
}

function mountStatusTone(status) {
  const value = normalizeStatusValue(status)

  if (['COMPLETED', 'DONE', 'MOUNTED', 'CONNECTED', 'AVAILABLE', 'OK', 'TRUE'].includes(value)) {
    return 'success'
  }
  if (['FAILED', 'ERROR', 'DISCONNECTED', 'UNMOUNTED', 'FALSE'].includes(value)) {
    return 'danger'
  }
  if (['RUNNING', 'VERIFYING', 'COPYING', 'IN_USE', 'DEGRADED'].includes(value)) {
    return 'warning'
  }
  if (['PENDING', 'UNKNOWN'].includes(value)) {
    return 'muted'
  }

  return 'info'
}

function mountStatusIcon(status) {
  const tone = mountStatusTone(status)

  if (tone === 'success') return '✓'
  if (tone === 'warning') return '!'
  if (tone === 'danger') return '×'
  if (tone === 'muted') return '•'
  return '?'
}

async function loadMounts() {
  loading.value = true
  error.value = ''
  try {
    const [mountResult, jobResult] = await Promise.allSettled([
      getMounts(),
      listAllJobs({ include_archived: true }),
    ])

    if (mountResult.status !== 'fulfilled') {
      throw mountResult.reason
    }

    const jobs = jobResult.status === 'fulfilled' ? (jobResult.value || []) : []
    mountJobByProject.value = buildProjectEvidenceMap(jobs)

    mounts.value = (mountResult.value || []).map((item) => {
      const mount = normalizeProjectRecord(item, ['project_id'])
      return {
        ...mount,
        current_project_job_id: getProjectEvidenceJobId(mount.project_id, mountJobByProject.value),
      }
    })
  } catch (requestError) {
    error.value = normalizeErrorMessage(requestError?.response?.data, t('common.errors.networkError'))
  } finally {
    loading.value = false
  }
}

function isValidJobId(value) {
  const normalizedJobId = Number(value)
  return Number.isInteger(normalizedJobId) && normalizedJobId > 0
}

function openMountDetails(mountId) {
  const normalizedMountId = Number(mountId)
  if (!Number.isInteger(normalizedMountId) || normalizedMountId < 1) return
  router.push({ name: 'mount-detail', params: { id: normalizedMountId } })
}

function openRelatedJob(jobId) {
  const normalizedJobId = Number(jobId)
  if (!Number.isInteger(normalizedJobId) || normalizedJobId < 1) return
  router.push({ name: 'job-detail', params: { id: normalizedJobId } })
}

async function loadPublicAuthConfig() {
  try {
    const config = await getPublicAuthConfig()
    publicAuthConfig.value = {
      demo_mode_enabled: Boolean(config?.demo_mode_enabled),
      default_nfs_client_version: String(config?.default_nfs_client_version || '4.1'),
      nfs_client_version_options: Array.isArray(config?.nfs_client_version_options) && config.nfs_client_version_options.length
        ? config.nfs_client_version_options.map((value) => String(value))
        : ['4.2', '4.1', '4.0', '3'],
    }
  } catch {
    publicAuthConfig.value = {
      demo_mode_enabled: false,
      default_nfs_client_version: '4.1',
      nfs_client_version_options: ['4.2', '4.1', '4.0', '3'],
    }
  }
}

function resetForm() {
  editingMountId.value = null
  dialogValidationPassed.value = false
  dialogTesting.value = false
  dialogError.value = ''
  dialogSuccessMessage.value = ''
  form.value = {
    type: 'SMB',
    remote_path: '',
    project_id: '',
    nfs_client_version: '',
    username: '',
    password: '',
    credentials_file: '',
  }
  credentialFieldState.value = {
    username: false,
    password: false,
    credentials_file: false,
  }
  dialogBrowsing.value = false
  showShareBrowserDialog.value = false
  discoveredShares.value = []
  shareBrowserError.value = ''
}

function invalidateDialogValidation() {
  if (dialogValidationPassed.value && dialogSuccessMessage.value === t('mounts.testSuccess')) {
    dialogSuccessMessage.value = ''
  }
  dialogValidationPassed.value = false
}

function markCredentialFieldChanged(fieldName) {
  credentialFieldState.value[fieldName] = true
  invalidateDialogValidation()
}

function clearStoredCredentials() {
  form.value.username = ''
  form.value.password = ''
  form.value.credentials_file = ''
  credentialFieldState.value = {
    username: true,
    password: true,
    credentials_file: true,
  }
  invalidateDialogValidation()
}

function trapFocusWithin(event, container) {
  if (!container) return
  const focusable = Array.from(
    container.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'),
  ).filter((element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true')

  if (!focusable.length) return

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement

  if (event.shiftKey && active === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

function protectedValue(value) {
  return value ? t('common.labels.protected') : '-'
}

function formatProjectId(value) {
  return normalizeProjectId(value) || '-'
}

function syncViewportState() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return

  if (!mobileViewportQuery) {
    mobileViewportQuery = window.matchMedia('(max-width: 768px)')
  }

  isMobileViewport.value = mobileViewportQuery.matches
}

function browseLabel(mount) {
  return mount?.project_id
    ? `${t('mounts.browse')} ${formatProjectId(mount.project_id)}`
    : t('mounts.browse')
}

function mountBrowseTitle(mount) {
  if (!mount?.project_id) return t('browse.browseMountContents')
  return t('browse.browseMountContentsTitle', { project: formatProjectId(mount.project_id) })
}

function formValid() {
  return !!form.value.type && !!form.value.remote_path.trim() && !!form.value.project_id.trim()
}

function buildMountPayload() {
  const payload = {
    type: form.value.type,
    remote_path: form.value.remote_path.trim(),
    project_id: normalizeProjectId(form.value.project_id),
  }

  if (form.value.type === 'NFS') {
    if (form.value.nfs_client_version) {
      payload.nfs_client_version = form.value.nfs_client_version
    }
  }

  const username = form.value.username.trim()
  const credentialsFile = form.value.credentials_file.trim()

  if (!isEditMode.value || credentialFieldState.value.username) payload.username = username || null
  if (!isEditMode.value || credentialFieldState.value.password) payload.password = form.value.password || null
  if (!isEditMode.value || credentialFieldState.value.credentials_file) payload.credentials_file = credentialsFile || null

  return payload
}

function buildShareDiscoveryPayload() {
  return {
    type: form.value.type,
    remote_path: form.value.remote_path.trim(),
    username: form.value.username.trim() || null,
    password: form.value.password || null,
    credentials_file: form.value.credentials_file.trim() || null,
  }
}

function replaceMount(nextMount) {
  if (!nextMount || nextMount.id == null) return
  const normalizedMount = normalizeProjectRecord(nextMount, ['project_id'])
  const index = mounts.value.findIndex((item) => item.id === normalizedMount.id)
  if (index >= 0) {
    mounts.value[index] = normalizedMount
  }
}

async function submitMountDialog() {
  if (!formValid()) return
  saving.value = true
  error.value = ''
  dialogError.value = ''
  try {
    const payload = buildMountPayload()
    if (isEditMode.value && editingMountId.value !== null) {
      const updatedMount = await updateMount(editingMountId.value, payload)
      replaceMount(updatedMount)
      if (updatedMount?.status === 'ERROR') {
        dialogError.value = t('mounts.updateFailed')
        return
      }
      successMessage.value = t('mounts.updateSuccess')
    } else {
      await createMount(payload)
      successMessage.value = t('mounts.createSuccess')
    }
    showAddDialog.value = false
    resetForm()
    await loadMounts()
  } catch (requestError) {
    dialogError.value = normalizeErrorMessage(requestError?.response?.data, t('common.errors.validationFailed'))
  } finally {
    saving.value = false
  }
}

async function runDialogValidate() {
  if (!formValid()) return
  dialogTesting.value = true
  dialogValidationPassed.value = false
  dialogError.value = ''
  dialogSuccessMessage.value = ''
  try {
    const payload = buildMountPayload()
    const result = isEditMode.value && editingMountId.value !== null
      ? await validateMount(editingMountId.value, payload)
      : await validateMountCandidate(payload)
    if (result?.status === 'MOUNTED') {
      dialogValidationPassed.value = true
      dialogSuccessMessage.value = t('mounts.testSuccess')
      return
    }
    dialogError.value = t('mounts.testFailed')
  } catch (requestError) {
    dialogError.value = normalizeErrorMessage(requestError?.response?.data, t('mounts.testFailed'))
  } finally {
    dialogTesting.value = false
  }
}

async function openShareBrowser(event) {
  if (!shareDiscoveryAvailable.value || !form.value.type || !form.value.remote_path.trim()) return

  shareBrowserTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement
  showShareBrowserDialog.value = true
  dialogBrowsing.value = true
  shareBrowserError.value = ''
  discoveredShares.value = []

  try {
    const result = await discoverMountShares(buildShareDiscoveryPayload())
    discoveredShares.value = Array.isArray(result?.shares) ? result.shares : []
  } catch (requestError) {
    shareBrowserError.value = normalizeErrorMessage(requestError?.response?.data, t('mounts.browseSharesFailed'))
  } finally {
    dialogBrowsing.value = false
  }
}

function closeShareBrowser() {
  showShareBrowserDialog.value = false
  dialogBrowsing.value = false
  shareBrowserError.value = ''
  discoveredShares.value = []
}

function selectDiscoveredShare(remotePath) {
  form.value.remote_path = String(remotePath || '')
  invalidateDialogValidation()
  closeShareBrowser()
}

function openAddDialog(event) {
  if (!canManageMounts.value) return
  addDialogTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement
  editingMountId.value = null
  error.value = ''
  resetForm()
  showAddDialog.value = true
  void nextTick(() => {
    const target = addDialogRef.value?.querySelector('#mount-type')
    if (target instanceof HTMLElement) {
      target.focus()
    }
  })
}

function openEditDialog(mount, event) {
  if (!mount || !canManageMounts.value) return
  addDialogTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement
  editingMountId.value = mount.id
  error.value = ''
  dialogValidationPassed.value = false
  dialogTesting.value = false
  dialogError.value = ''
  dialogSuccessMessage.value = ''
  form.value = {
    type: mount.type || 'SMB',
    remote_path: mount.remote_path || '',
    project_id: normalizeProjectId(mount.project_id),
    nfs_client_version: mount.nfs_client_version || '',
    username: '',
    password: '',
    credentials_file: '',
  }
  credentialFieldState.value = {
    username: false,
    password: false,
    credentials_file: false,
  }
  showAddDialog.value = true
  void nextTick(() => {
    const target = addDialogRef.value?.querySelector('#mount-type')
    if (target instanceof HTMLElement) {
      target.focus()
    }
  })
}

function closeAddDialog() {
  showAddDialog.value = false
  closeShareBrowser()
  dialogError.value = ''
  dialogSuccessMessage.value = ''
  resetForm()
}

function handleAddDialogKeydown(event) {
  if (!showAddDialog.value) return
  if (showShareBrowserDialog.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      closeShareBrowser()
      return
    }
    if (event.key === 'Tab') {
      trapFocusWithin(event, shareBrowserDialogRef.value)
    }
    return
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    closeAddDialog()
    return
  }
  if (event.key === 'Tab') {
    trapFocusWithin(event, addDialogRef.value)
  }
}

async function runRemove(target = removeTarget.value) {
  if (!target) return
  removeTarget.value = target
  saving.value = true
  error.value = ''
  successMessage.value = ''
  try {
    await deleteMount(target.id)
    if (browsingMountId.value === target.id) {
      browsingMountId.value = null
    }
    removeTarget.value = null
    showRemoveDialog.value = false
    await loadMounts()
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

function requestRemove(mount) {
  if (!mount) return
  removeTarget.value = mount
  if (mount.status === 'MOUNTED' && mount.local_mount_point) {
    showRemoveDialog.value = true
    return
  }
  showRemoveDialog.value = false
  void runRemove(mount)
}

const browsePanelRef = ref(null)

async function toggleBrowse(mountId) {
  browsingMountId.value = browsingMountId.value === mountId ? null : mountId
  if (browsingMountId.value !== null) {
    await nextTick()
    if (typeof browsePanelRef.value?.scrollIntoView === 'function') {
      browsePanelRef.value.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }
}

onMounted(async () => {
  syncViewportState()
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    if (!mobileViewportQuery) {
      mobileViewportQuery = window.matchMedia('(max-width: 768px)')
    }
    mobileViewportQuery.addEventListener('change', syncViewportState)
  }

  await Promise.allSettled([loadMounts(), loadPublicAuthConfig()])
})

watch(
  () => form.value.project_id,
  (value) => {
    const normalized = normalizeProjectId(value)
    if (value !== normalized) {
      form.value.project_id = normalized
    }
  },
)

watch(
  () => [form.value.type, form.value.remote_path, form.value.project_id],
  () => {
    invalidateDialogValidation()
  },
)

watch(showAddDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleAddDialogKeydown)
    await nextTick()
    const target = addDialogRef.value?.querySelector('#mount-type')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  document.removeEventListener('keydown', handleAddDialogKeydown)
  const trigger = addDialogTriggerRef.value
  addDialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

watch(showShareBrowserDialog, async (open) => {
  if (open) {
    await nextTick()
    const target = shareBrowserDialogRef.value?.querySelector('.share-select-btn, .share-browser-close-btn')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  const trigger = shareBrowserTriggerRef.value
  shareBrowserTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement && showAddDialog.value) {
    trigger.focus()
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleAddDialogKeydown)
  mobileViewportQuery?.removeEventListener('change', syncViewportState)
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('mounts.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadMounts">{{ t('common.actions.refresh') }}</button>
        <button v-if="canManageMounts" class="btn btn-primary" @click="openAddDialog">{{ t('mounts.add') }}</button>
      </div>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner" role="alert" aria-live="assertive">{{ error }}</p>
    <p v-if="successMessage" class="success-banner" role="status" aria-live="polite">{{ successMessage }}</p>

    <input v-model="search" type="text" :placeholder="t('mounts.searchPlaceholder')" :aria-label="t('mounts.searchPlaceholder')" />

    <DataTable :columns="columns" :rows="paged" :empty-text="t('mounts.empty')">
      <template #cell-id="{ row }">
        <button class="cell-link mount-id-link" type="button" @click="openMountDetails(row.id)">
          {{ row.id }}
        </button>
      </template>
      <template #cell-project_id="{ row }">
        <button
          v-if="row.status === 'MOUNTED'"
          class="cell-link mount-project-link"
          type="button"
          :aria-expanded="browsingMountId === row.id"
          :aria-label="mountBrowseTitle(row)"
          @click="toggleBrowse(row.id)"
        >
          {{ formatProjectId(row.project_id) }}
        </button>
        <span v-else>{{ formatProjectId(row.project_id) }}</span>
      </template>
      <template #cell-current_project_job_id="{ row }">
        <button
          v-if="isValidJobId(row.current_project_job_id)"
          class="cell-link"
          type="button"
          @click="openRelatedJob(row.current_project_job_id)"
        >
          {{ row.current_project_job_id }}
        </button>
        <span v-else>-</span>
      </template>
      <template #cell-status="{ row }">
        <span
          v-if="isMobileViewport"
          class="mount-status-icon"
          :class="`mount-status-icon--${mountStatusTone(row.status)}`"
          :aria-label="row.status"
          :title="row.status"
          role="img"
        >
          <span aria-hidden="true">{{ mountStatusIcon(row.status) }}</span>
        </span>
        <StatusBadge v-else :status="row.status" />
      </template>
      <template #cell-last_checked_at="{ row }">{{ toIso(row.last_checked_at) }}</template>
    </DataTable>

    <!-- Inline directory browser panel for the currently browsed mount -->
    <section
      v-if="activeBrowsedMount?.status === 'MOUNTED'"
      ref="browsePanelRef"
      class="browse-panel"
      :aria-label="mountBrowseTitle(activeBrowsedMount)"
    >
      <header class="browse-panel-header">
        <h3 class="browse-panel-title">{{ mountBrowseTitle(activeBrowsedMount) }}</h3>
        <button class="btn" @click="toggleBrowse(activeBrowsedMount.id)">
          {{ t('common.actions.close') }}
        </button>
      </header>
      <DirectoryBrowser
        :mount-id="activeBrowsedMount.id"
        root-label=""
        :show-root-crumb-at-root="true"
      />
    </section>

    <Pagination v-model:page="page" :page-size="pageSize" :total="filtered.length" />

    <teleport to="body">
      <div v-if="showAddDialog" class="dialog-overlay">
        <div ref="addDialogRef" class="dialog-panel mount-dialog-panel" role="dialog" aria-modal="true" :aria-labelledby="addMountDialogTitleId">
          <div class="dialog-header mount-dialog-header">
            <h2 :id="addMountDialogTitleId">{{ dialogTitle }}</h2>
            <p v-if="dialogError" class="error-banner" role="alert" aria-live="assertive">{{ dialogError }}</p>
            <p v-if="dialogSuccessMessage" class="success-banner" role="status" aria-live="polite">{{ dialogSuccessMessage }}</p>
          </div>

          <div class="dialog-body mount-dialog-scroll-region">
            <label for="mount-type" class="field-label">
              {{ t('common.labels.type') }}
              <span class="required-indicator" aria-hidden="true">*</span>
              <span class="sr-only">required</span>
            </label>
            <select id="mount-type" v-model="form.type" required aria-required="true">
              <option value="SMB">SMB</option>
              <option value="NFS">NFS</option>
            </select>
            <label for="mount-remote-path" class="field-label">
              {{ t('mounts.remotePath') }}
              <span class="required-indicator" aria-hidden="true">*</span>
              <span class="sr-only">required</span>
            </label>
            <input id="mount-remote-path" v-model="form.remote_path" type="text" required aria-required="true" />
            <label for="mount-project-id" class="field-label">
              {{ t('dashboard.project') }}
              <span class="required-indicator" aria-hidden="true">*</span>
              <span class="sr-only">required</span>
            </label>
            <input id="mount-project-id" v-model="form.project_id" type="text" required aria-required="true" />
            <template v-if="form.type === 'NFS'">
              <label for="mount-nfs-client-version">{{ t('mounts.nfsClientVersion') }}</label>
              <select id="mount-nfs-client-version" v-model="form.nfs_client_version">
                <option v-for="option in nfsClientVersionSelectOptions" :key="option.value || 'default'" :value="option.value">{{ option.label }}</option>
              </select>
              <p class="field-help">{{ t('mounts.nfsClientVersionHelp') }}</p>
            </template>
            <template v-if="isEditMode && dialogLocalMountPoint">
              <label for="mount-local-path">{{ t('mounts.localMountPointInfo') }}</label>
              <input id="mount-local-path" :value="dialogLocalMountPoint" type="text" readonly />
            </template>
            <div v-if="isEditMode" class="credential-header-row">
              <span class="field-label">{{ t('mounts.storedCredentials') }}</span>
              <button class="btn btn-secondary btn-inline" type="button" @click="clearStoredCredentials">
                {{ t('mounts.clearStoredCredentials') }}
              </button>
            </div>
            <label for="mount-username">{{ t('auth.username') }}</label>
            <input id="mount-username" v-model="form.username" type="text" autocomplete="off" @input="markCredentialFieldChanged('username')" />
            <label for="mount-password">{{ t('auth.password') }}</label>
            <input id="mount-password" v-model="form.password" type="password" autocomplete="new-password" @input="markCredentialFieldChanged('password')" />
            <label for="mount-creds-file">{{ t('mounts.credentialsFile') }}</label>
            <input id="mount-creds-file" v-model="form.credentials_file" type="text" @input="markCredentialFieldChanged('credentials_file')" />
          </div>

          <div class="dialog-actions dialog-footer">
            <button class="btn" @click="closeAddDialog">{{ t('common.actions.cancel') }}</button>
            <button
              v-if="shareDiscoveryAvailable"
              class="btn"
              :disabled="saving || dialogTesting || dialogBrowsing || !form.type || !form.remote_path.trim()"
              @click="openShareBrowser($event)"
            >
              {{ dialogBrowsing ? t('common.labels.loading') : t('mounts.browseShares') }}
            </button>
            <button
              class="btn"
              :disabled="saving || dialogTesting || !formValid()"
              @click="runDialogValidate"
            >
              {{ dialogTesting ? t('common.labels.loading') : t('mounts.test') }}
            </button>
            <button
              class="btn btn-primary"
              :disabled="saving || dialogTesting || !formValid() || !dialogValidationPassed"
              @click="submitMountDialog"
            >
              {{ saving ? t('common.labels.loading') : dialogSubmitLabel }}
            </button>
          </div>
        </div>
      </div>

      <div v-if="showShareBrowserDialog" class="dialog-overlay">
        <div ref="shareBrowserDialogRef" class="dialog-panel share-browser-panel" role="dialog" aria-modal="true" :aria-labelledby="shareBrowserTitleId">
          <h2 :id="shareBrowserTitleId">{{ t('mounts.browseSharesTitle') }}</h2>
          <p class="muted">{{ t('mounts.browseSharesHelp') }}</p>
          <p v-if="shareBrowserError" class="error-banner" role="alert" aria-live="assertive">{{ shareBrowserError }}</p>
          <p v-else-if="dialogBrowsing" class="muted">{{ t('common.labels.loading') }}</p>
          <p v-else-if="!discoveredShares.length" class="muted">{{ t('mounts.browseSharesEmpty') }}</p>
          <div v-else class="share-discovery-scroll" aria-live="polite">
            <ul class="share-discovery-list">
              <li v-for="share in discoveredShares" :key="share.remote_path" class="share-discovery-item">
                <div class="share-discovery-copy">
                  <strong>{{ share.display_name }}</strong>
                  <span class="muted">{{ share.remote_path }}</span>
                </div>
                <button class="btn share-select-btn" @click="selectDiscoveredShare(share.remote_path)">
                  {{ t('mounts.selectShare') }}
                </button>
              </li>
            </ul>
          </div>
          <div class="dialog-actions">
            <button class="btn share-browser-close-btn" @click="closeShareBrowser">{{ t('common.actions.cancel') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <ConfirmDialog
      v-model="showRemoveDialog"
      :title="t('mounts.removeConfirmTitle')"
      :message="t('mounts.removeConfirmBody')"
      :confirm-label="t('mounts.remove')"
      :cancel-label="t('common.actions.cancel')"
      :busy="saving"
      dangerous
      @confirm="runRemove"
    />
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.cell-link {
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--color-text-link);
  cursor: pointer;
  font: inherit;
  text-decoration: underline;
}

.cell-link:hover,
.cell-link:focus-visible {
  text-decoration-thickness: 2px;
}

.header-row,
.actions,
.credential-header-row,
.share-discovery-item {
  display: flex;
  gap: var(--space-sm);
}

:deep(.data-table th),
:deep(.data-table th > span),
:deep(.data-table th .sort-button),
:deep(.data-table th .sort-button > span) {
  font-weight: var(--font-weight-bold);
}

.mount-status-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border: 1px solid transparent;
  border-radius: 9999px;
  font-size: 0.9rem;
  font-weight: var(--font-weight-bold);
  line-height: 1;
}

.mount-status-icon--success {
  background: color-mix(in srgb, var(--color-success) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  color: var(--color-status-ok-text, #14532d);
}

.mount-status-icon--warning {
  background: color-mix(in srgb, var(--color-warning) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-warning) 45%, var(--color-border));
  color: var(--color-status-warn-text, #7c3f00);
}

.mount-status-icon--danger {
  background: color-mix(in srgb, var(--color-danger) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-danger) 45%, var(--color-border));
  color: var(--color-status-danger-text, #991b1b);
}

.mount-status-icon--info {
  background: color-mix(in srgb, var(--color-info) 16%, var(--color-bg-secondary));
  border-color: color-mix(in srgb, var(--color-info) 45%, var(--color-border));
  color: var(--color-status-info-text, #1e40af);
}

.mount-status-icon--muted {
  background: var(--color-bg-hover);
  border-color: var(--color-border);
  color: var(--color-status-muted-text, #475569);
}

.header-row {
  justify-content: space-between;
  align-items: center;
}

.credential-header-row {
  justify-content: space-between;
  align-items: center;
  margin-top: var(--space-xs);
}

.share-discovery-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  gap: var(--space-sm);
}

.share-discovery-scroll {
  max-height: min(55vh, 26rem);
  overflow-y: auto;
  padding-right: var(--space-2xs);
}

.share-discovery-item {
  justify-content: space-between;
  align-items: center;
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.share-discovery-copy {
  display: grid;
  gap: var(--space-2xs);
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

.success-banner {
  color: var(--color-text-primary);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.muted {
  color: var(--color-text-secondary);
}

.dialog-overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, var(--color-bg-primary) 30%, #000000);
  display: grid;
  place-items: center;
  z-index: 1000;
}

.dialog-panel {
  width: min(640px, 100%);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-lg);
  display: grid;
  gap: var(--space-xs);
}

.mount-dialog-panel {
  max-height: min(85vh, 44rem);
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}

.mount-dialog-header,
.dialog-footer {
  gap: var(--space-xs);
}

.mount-dialog-scroll-region {
  display: grid;
  gap: var(--space-xs);
  min-height: 0;
  overflow-y: auto;
  padding-right: var(--space-2xs);
}

.browse-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
}

.share-browser-panel {
  max-height: min(85vh, 44rem);
}

.field-label {
  font-weight: var(--font-weight-bold);
}

.required-indicator {
  color: var(--color-danger, #b91c1c);
  margin-left: 0.15rem;
}

.dialog-actions {
  margin-top: var(--space-sm);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}

@media (max-width: 768px) {
  :deep(.table-scroll-wrapper) {
    overflow: visible;
  }
}
</style>
