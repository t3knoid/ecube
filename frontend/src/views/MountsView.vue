<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getMounts, createMount, updateMount, deleteMount, validateMount, validateMountCandidate, discoverMountShares } from '@/api/mounts.js'
import { getPublicAuthConfig } from '@/api/auth.js'
import { normalizeErrorMessage } from '@/api/client.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import DirectoryBrowser from '@/components/browse/DirectoryBrowser.vue'
import { useAuthStore } from '@/stores/auth.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'

const { t } = useI18n()
const authStore = useAuthStore()

const mounts = ref([])
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
const shareDiscoveryAvailable = computed(() => !isEditMode.value && !publicAuthConfig.value?.demo_mode_enabled)

const columns = computed(() => {
  const nextColumns = [
    { key: 'id', label: t('common.labels.id'), align: 'right' },
    { key: 'type', label: t('common.labels.type') },
    { key: 'project_id', label: t('dashboard.project') },
    { key: 'status', label: t('common.labels.status') },
    { key: 'last_checked_at', label: t('mounts.lastChecked') },
    { key: 'actions', label: '', align: 'center' },
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
    const response = await getMounts()
    mounts.value = (response || []).map((item) => normalizeProjectRecord(item, ['project_id']))
  } catch (requestError) {
    error.value = normalizeErrorMessage(requestError?.response?.data, t('common.errors.networkError'))
  } finally {
    loading.value = false
  }
}

async function loadPublicAuthConfig() {
  try {
    const config = await getPublicAuthConfig()
    publicAuthConfig.value = {
      demo_mode_enabled: Boolean(config?.demo_mode_enabled),
    }
  } catch {
    publicAuthConfig.value = { demo_mode_enabled: false }
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

function mountRootLabel(mount) {
  const mountPath = String(mount?.local_mount_point || '').trim()
  const parts = mountPath.split('/').filter(Boolean)
  return parts.at(-1) || t('mounts.browse')
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

function closeRowActionsMenu(event) {
  const menu = event?.currentTarget instanceof HTMLElement ? event.currentTarget.closest('details') : null
  if (menu instanceof HTMLDetailsElement) {
    menu.removeAttribute('open')
  }
}

function handleMenuEdit(mount, event) {
  closeRowActionsMenu(event)
  openEditDialog(mount, event)
}

function handleMenuBrowse(mount, event) {
  closeRowActionsMenu(event)
  void toggleBrowse(mount.id)
}

function handleMenuRemove(mount, event) {
  closeRowActionsMenu(event)
  requestRemove(mount)
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
        <button class="btn btn-primary" @click="openAddDialog">{{ t('mounts.add') }}</button>
      </div>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner" role="alert" aria-live="assertive">{{ error }}</p>
    <p v-if="successMessage" class="success-banner" role="status" aria-live="polite">{{ successMessage }}</p>

    <input v-model="search" type="text" :placeholder="t('mounts.searchPlaceholder')" :aria-label="t('mounts.searchPlaceholder')" />

    <DataTable :columns="columns" :rows="paged" :empty-text="t('mounts.empty')">
      <template #cell-project_id="{ row }">{{ formatProjectId(row.project_id) }}</template>
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
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button v-if="canManageMounts" class="btn" @click="openEditDialog(row, $event)">{{ t('common.actions.edit') }}</button>
          <button
            class="btn"
            :disabled="row.status !== 'MOUNTED' || !row.local_mount_point"
            :title="row.status !== 'MOUNTED' || !row.local_mount_point ? t('mounts.browseUnavailable') : ''"
            :aria-expanded="browsingMountId === row.id"
            :aria-label="browseLabel(row)"
            @click="toggleBrowse(row.id)"
          >
            {{ t('mounts.browse') }}
          </button>
          <button v-if="canManageMounts" class="btn btn-danger" @click="requestRemove(row)">{{ t('mounts.remove') }}</button>
        </div>
        <details class="row-actions-menu">
          <summary class="row-actions-toggle" :aria-label="`${formatProjectId(row.project_id)} mount actions`">
            <span class="row-actions-toggle-dots" aria-hidden="true">
              <span class="row-actions-toggle-dot" />
              <span class="row-actions-toggle-dot" />
              <span class="row-actions-toggle-dot" />
            </span>
          </summary>
          <div class="row-actions-popover">
            <button
              v-if="canManageMounts"
              class="btn row-action-menu-edit"
              @click="handleMenuEdit(row, $event)"
            >
              {{ t('common.actions.edit') }}
            </button>
            <button
              class="btn row-action-menu-browse"
              :disabled="row.status !== 'MOUNTED' || !row.local_mount_point"
              :title="row.status !== 'MOUNTED' || !row.local_mount_point ? t('mounts.browseUnavailable') : ''"
              :aria-expanded="browsingMountId === row.id"
              :aria-label="browseLabel(row)"
              @click="handleMenuBrowse(row, $event)"
            >
              {{ t('mounts.browse') }}
            </button>
            <button
              v-if="canManageMounts"
              class="btn btn-danger row-action-menu-remove"
              @click="handleMenuRemove(row, $event)"
            >
              {{ t('mounts.remove') }}
            </button>
          </div>
        </details>
      </template>
    </DataTable>

    <!-- Inline directory browser panel for the currently browsed mount -->
    <section
      v-if="activeBrowsedMount"
      ref="browsePanelRef"
      class="browse-panel"
      :aria-label="browseLabel(activeBrowsedMount)"
    >
      <h3 class="browse-panel-title">
        {{ t('browse.browseMountContents') }}: {{ formatProjectId(activeBrowsedMount.project_id) }}
      </h3>
      <DirectoryBrowser
        :mount-path="activeBrowsedMount.local_mount_point"
        :root-label="mountRootLabel(activeBrowsedMount)"
      />
    </section>

    <Pagination v-model:page="page" :page-size="pageSize" :total="filtered.length" />

    <teleport to="body">
      <div v-if="showAddDialog" class="dialog-overlay">
        <div ref="addDialogRef" class="dialog-panel" role="dialog" aria-modal="true" :aria-labelledby="addMountDialogTitleId">
          <h2 :id="addMountDialogTitleId">{{ dialogTitle }}</h2>
          <p v-if="dialogError" class="error-banner" role="alert" aria-live="assertive">{{ dialogError }}</p>
          <p v-if="dialogSuccessMessage" class="success-banner" role="status" aria-live="polite">{{ dialogSuccessMessage }}</p>
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

          <div class="dialog-actions">
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

.header-row,
.actions,
.row-actions,
.credential-header-row,
.share-discovery-item {
  display: flex;
  gap: var(--space-sm);
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

.row-actions {
  flex-wrap: wrap;
  justify-content: center;
}

.row-actions-menu {
  display: none;
  position: relative;
}

.row-actions-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  list-style: none;
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  cursor: pointer;
}

.row-actions-toggle-dots {
  display: inline-grid;
  gap: 0.15rem;
}

.row-actions-toggle-dot {
  width: 0.25rem;
  height: 0.25rem;
  border-radius: 9999px;
  background: currentColor;
}

.row-actions-toggle::-webkit-details-marker {
  display: none;
}

.row-actions-popover {
  position: absolute;
  top: calc(100% + var(--space-2xs));
  right: 0;
  z-index: 2;
  min-width: 8.5rem;
  display: grid;
  gap: var(--space-2xs);
  padding: var(--space-2xs);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: var(--color-bg-primary);
  box-shadow: var(--shadow-md, 0 8px 24px rgba(0, 0, 0, 0.12));
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
  .row-actions {
    display: none;
  }

  .row-actions-menu {
    display: inline-block;
  }
}
</style>
