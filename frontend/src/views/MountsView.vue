<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getMounts, createMount, updateMount, deleteMount, validateAllMounts, validateMount } from '@/api/mounts.js'
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
const error = ref('')
const successMessage = ref('')
const editingMountId = ref(null)

const showAddDialog = ref(false)
const showRemoveDialog = ref(false)
const removeTarget = ref(null)

const page = ref(1)
const pageSize = ref(10)
const search = ref('')

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

const columns = computed(() => [
  { key: 'id', label: t('common.labels.id'), align: 'right' },
  { key: 'type', label: t('common.labels.type') },
  { key: 'project_id', label: t('dashboard.project') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'last_checked_at', label: t('mounts.lastChecked') },
  { key: 'actions', label: '', align: 'center' },
])

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

function resetForm() {
  editingMountId.value = null
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
}

function markCredentialFieldChanged(fieldName) {
  credentialFieldState.value[fieldName] = true
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
  try {
    const payload = buildMountPayload()
    if (isEditMode.value && editingMountId.value !== null) {
      const updatedMount = await updateMount(editingMountId.value, payload)
      replaceMount(updatedMount)
      if (updatedMount?.status === 'ERROR') {
        error.value = t('mounts.updateFailed')
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
    error.value = normalizeErrorMessage(requestError?.response?.data, t('common.errors.validationFailed'))
  } finally {
    saving.value = false
  }
}

async function runValidateAll() {
  loading.value = true
  error.value = ''
  successMessage.value = ''
  try {
    const response = await validateAllMounts()
    mounts.value = (response || []).map((item) => normalizeProjectRecord(item, ['project_id']))
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    loading.value = false
  }
}

async function runValidateOne(mountId) {
  error.value = ''
  successMessage.value = ''
  try {
    const next = normalizeProjectRecord(await validateMount(mountId), ['project_id'])
    const index = mounts.value.findIndex((item) => item.id === mountId)
    if (index >= 0) mounts.value[index] = next
  } catch {
    error.value = t('common.errors.requestConflict')
  }
}

function openAddDialog(event) {
  addDialogTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement
  editingMountId.value = null
  error.value = ''
  successMessage.value = ''
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
  successMessage.value = ''
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
  error.value = ''
  resetForm()
}

function handleAddDialogKeydown(event) {
  if (!showAddDialog.value) return
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

onMounted(loadMounts)

watch(
  () => form.value.project_id,
  (value) => {
    const normalized = normalizeProjectId(value)
    if (value !== normalized) {
      form.value.project_id = normalized
    }
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

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleAddDialogKeydown)
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('mounts.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadMounts">{{ t('common.actions.refresh') }}</button>
        <button class="btn" @click="runValidateAll">{{ t('mounts.testAll') }}</button>
        <button class="btn btn-primary" @click="openAddDialog">{{ t('mounts.add') }}</button>
      </div>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner" role="alert" aria-live="assertive">{{ error }}</p>
    <p v-if="successMessage" class="success-banner" role="status" aria-live="polite">{{ successMessage }}</p>

    <input v-model="search" type="text" :placeholder="t('mounts.searchPlaceholder')" :aria-label="t('mounts.searchPlaceholder')" />

    <DataTable :columns="columns" :rows="paged" :empty-text="t('mounts.empty')">
      <template #cell-project_id="{ row }">{{ formatProjectId(row.project_id) }}</template>
      <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
      <template #cell-last_checked_at="{ row }">{{ toIso(row.last_checked_at) }}</template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn" @click="runValidateOne(row.id)">{{ t('mounts.test') }}</button>
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
          <button class="btn btn-danger" @click="requestRemove(row)">{{ t('mounts.remove') }}</button>
        </div>
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
            <button class="btn btn-primary" :disabled="saving || !formValid()" @click="submitMountDialog">
              {{ saving ? t('common.labels.loading') : dialogSubmitLabel }}
            </button>
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
.credential-header-row {
  display: flex;
  gap: var(--space-sm);
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
</style>
