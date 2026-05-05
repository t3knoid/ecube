<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getMounts, updateMount, deleteMount, validateMount } from '@/api/mounts.js'
import { getPublicAuthConfig } from '@/api/auth.js'
import { listAllJobs } from '@/api/jobs.js'
import { normalizeErrorMessage } from '@/api/client.js'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import DirectoryBrowser from '@/components/browse/DirectoryBrowser.vue'
import { useAuthStore } from '@/stores/auth.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'
import { buildProjectEvidenceMap, getProjectEvidenceJobId } from '@/utils/projectEvidence.js'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const mountRecord = ref(null)
const loading = ref(false)
const saving = ref(false)
const dialogTesting = ref(false)
const error = ref('')
const infoMessage = ref('')
const dialogError = ref('')
const dialogSuccessMessage = ref('')
const showEditDialog = ref(false)
const showRemoveDialog = ref(false)
const dialogValidationPassed = ref(false)
const browseExpanded = ref(false)

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

const editDialogRef = ref(null)
const editDialogTriggerRef = ref(null)
const editDialogTitleId = 'edit-mount-dialog-title'
const relatedJobId = ref(null)

const publicAuthConfig = ref({
  demo_mode_enabled: false,
  default_nfs_client_version: '4.1',
  network_mount_timeout_seconds: 120,
  nfs_client_version_options: ['4.2', '4.1', '4.0', '3'],
})

const mountId = computed(() => Number(route.params.id))
const canManageMounts = computed(() => authStore.hasAnyRole(['admin', 'manager']))
const canBrowse = computed(() => mountRecord.value?.status === 'MOUNTED' && Number.isInteger(mountRecord.value?.id))
const redactedMountValue = computed(() => t('mounts.redactedValue'))
const visibleRemotePath = computed(() => {
  if (!mountRecord.value?.remote_path) return '-'
  return canManageMounts.value ? mountRecord.value.remote_path : redactedMountValue.value
})
const visibleLocalMountPoint = computed(() => {
  if (!mountRecord.value?.local_mount_point) return '-'
  return canManageMounts.value ? mountRecord.value.local_mount_point : redactedMountValue.value
})
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

function networkMountTimeoutMs() {
  const seconds = Number(publicAuthConfig.value?.network_mount_timeout_seconds)
  return (Number.isFinite(seconds) && seconds >= 1 ? seconds : 120) * 1000
}

function mountBrowseTitle(record) {
  if (!record?.project_id) return t('browse.browseMountContents')
  return t('browse.browseMountContentsTitle', { project: normalizeProjectId(record.project_id) || '-' })
}

function toIso(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleString()
}

function isValidJobId(value) {
  const normalizedJobId = Number(value)
  return Number.isInteger(normalizedJobId) && normalizedJobId > 0
}

function openRelatedJob() {
  const normalizedJobId = Number(relatedJobId.value)
  if (!Number.isInteger(normalizedJobId) || normalizedJobId < 1) return
  router.push({ name: 'job-detail', params: { id: normalizedJobId } })
}

function clearBanners() {
  error.value = ''
  infoMessage.value = ''
}

async function loadMount() {
  loading.value = true
  clearBanners()
  try {
    const [mountResult, jobResult, configResult] = await Promise.allSettled([
      getMounts(),
      listAllJobs({ include_archived: true }),
      getPublicAuthConfig(),
    ])

    if (mountResult.status !== 'fulfilled') {
      throw mountResult.reason
    }

    if (configResult.status === 'fulfilled') {
      publicAuthConfig.value = {
        demo_mode_enabled: Boolean(configResult.value?.demo_mode_enabled),
        default_nfs_client_version: String(configResult.value?.default_nfs_client_version || '4.1'),
        network_mount_timeout_seconds: Number(configResult.value?.network_mount_timeout_seconds) || 120,
        nfs_client_version_options: Array.isArray(configResult.value?.nfs_client_version_options) && configResult.value.nfs_client_version_options.length
          ? configResult.value.nfs_client_version_options.map((value) => String(value))
          : ['4.2', '4.1', '4.0', '3'],
      }
    }

    const jobs = jobResult.status === 'fulfilled' ? (jobResult.value || []) : []
    const mountJobByProject = buildProjectEvidenceMap(jobs)
    const nextMount = (mountResult.value || [])
      .map((item) => normalizeProjectRecord(item, ['project_id']))
      .find((item) => item.id === mountId.value) || null

    mountRecord.value = nextMount
    relatedJobId.value = nextMount
      ? getProjectEvidenceJobId(nextMount.project_id, mountJobByProject)
      : null

    if (!nextMount) {
      error.value = t('mounts.notFound')
    }
  } catch (requestError) {
    error.value = normalizeErrorMessage(requestError?.response?.data, t('common.errors.networkError'))
  } finally {
    loading.value = false
  }
}

function resetEditForm() {
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

function formValid() {
  return !!form.value.type && !!form.value.remote_path.trim() && !!form.value.project_id.trim()
}

function buildMountPayload() {
  const payload = {
    type: form.value.type,
    remote_path: form.value.remote_path.trim(),
    project_id: normalizeProjectId(form.value.project_id),
  }

  if (form.value.type === 'NFS' && form.value.nfs_client_version) {
    payload.nfs_client_version = form.value.nfs_client_version
  }

  const username = form.value.username.trim()
  const credentialsFile = form.value.credentials_file.trim()

  if (credentialFieldState.value.username) payload.username = username || null
  if (credentialFieldState.value.password) payload.password = form.value.password || null
  if (credentialFieldState.value.credentials_file) payload.credentials_file = credentialsFile || null

  return payload
}

function openEditDialog(event) {
  if (!mountRecord.value || !canManageMounts.value) return
  editDialogTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement
  resetEditForm()
  form.value = {
    type: mountRecord.value.type || 'SMB',
    remote_path: mountRecord.value.remote_path || '',
    project_id: normalizeProjectId(mountRecord.value.project_id),
    nfs_client_version: mountRecord.value.nfs_client_version || '',
    username: '',
    password: '',
    credentials_file: '',
  }
  showEditDialog.value = true
}

function closeEditDialog() {
  showEditDialog.value = false
  resetEditForm()
}

async function runDialogValidate() {
  if (!mountRecord.value || !formValid()) return
  dialogTesting.value = true
  dialogValidationPassed.value = false
  dialogError.value = ''
  dialogSuccessMessage.value = ''
  try {
    const result = await validateMount(mountRecord.value.id, buildMountPayload(), { timeout: networkMountTimeoutMs() })
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

async function submitMountDialog() {
  if (!mountRecord.value || !formValid()) return
  saving.value = true
  clearBanners()
  dialogError.value = ''
  try {
    const updatedMount = await updateMount(mountRecord.value.id, buildMountPayload(), { timeout: networkMountTimeoutMs() })
    if (updatedMount?.status === 'ERROR') {
      dialogError.value = t('mounts.updateFailed')
      return
    }
    closeEditDialog()
    await loadMount()
    infoMessage.value = t('mounts.updateSuccess')
  } catch (requestError) {
    dialogError.value = normalizeErrorMessage(requestError?.response?.data, t('common.errors.validationFailed'))
  } finally {
    saving.value = false
  }
}

function requestRemove() {
  if (!mountRecord.value || !canManageMounts.value) return
  if (mountRecord.value.status === 'MOUNTED' && mountRecord.value.local_mount_point) {
    showRemoveDialog.value = true
    return
  }
  showRemoveDialog.value = false
  void runRemove()
}

async function runRemove() {
  if (!mountRecord.value) return
  saving.value = true
  clearBanners()
  try {
    await deleteMount(mountRecord.value.id)
    showRemoveDialog.value = false
    router.push({ name: 'mounts' })
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

function handleEditDialogKeydown(event) {
  if (!showEditDialog.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeEditDialog()
    return
  }
  if (event.key === 'Tab') {
    trapFocusWithin(event, editDialogRef.value)
  }
}

watch(
  () => route.params.id,
  () => {
    browseExpanded.value = false
    void loadMount()
  },
)

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
  () => [form.value.type, form.value.remote_path, form.value.project_id, form.value.nfs_client_version],
  () => {
    invalidateDialogValidation()
  },
)

watch(showEditDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleEditDialogKeydown)
    await nextTick()
    const target = editDialogRef.value?.querySelector('#mount-type')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  document.removeEventListener('keydown', handleEditDialogKeydown)
  const trigger = editDialogTriggerRef.value
  editDialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

onMounted(() => {
  void loadMount()
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleEditDialogKeydown)
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('mounts.detail') }} #{{ mountId }}</h1>
      <div class="actions">
        <button class="btn" @click="router.push({ name: 'mounts' })">{{ t('common.actions.back') }}</button>
        <button class="btn" @click="loadMount">{{ t('common.actions.refresh') }}</button>
      </div>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner" role="alert" aria-live="assertive">{{ error }}</p>
    <p v-if="infoMessage" class="ok-banner" role="status" aria-live="polite">{{ infoMessage }}</p>

    <article v-if="mountRecord" class="detail-card">
      <div class="detail-grid">
        <div><strong>{{ t('common.labels.type') }}</strong><span>{{ mountRecord.type || '-' }}</span></div>
        <div><strong>{{ t('mounts.remotePath') }}</strong><span>{{ visibleRemotePath }}</span></div>
        <div><strong>{{ t('dashboard.project') }}</strong><span>{{ mountRecord.project_id || '-' }}</span></div>
        <div><strong>{{ t('mounts.nfsClientVersion') }}</strong><span>{{ mountRecord.nfs_client_version || '-' }}</span></div>
        <div><strong>{{ t('mounts.localMountPointInfo') }}</strong><span>{{ visibleLocalMountPoint }}</span></div>
        <div><strong>{{ t('mounts.lastChecked') }}</strong><span>{{ toIso(mountRecord.last_checked_at) }}</span></div>
        <div>
          <strong>{{ t('jobs.jobId') }}</strong>
          <span>
            <button
              v-if="isValidJobId(relatedJobId)"
              class="cell-link"
              type="button"
              @click="openRelatedJob"
            >
              {{ relatedJobId }}
            </button>
            <template v-else>-</template>
          </span>
        </div>
        <div><strong>{{ t('common.labels.status') }}</strong><StatusBadge :status="mountRecord.status" /></div>
      </div>

      <div class="action-row">
        <button class="btn" :disabled="!canBrowse" @click="browseExpanded = !browseExpanded">{{ t('mounts.browse') }}</button>
        <button v-if="canManageMounts" class="btn" :disabled="saving" @click="openEditDialog($event)">{{ t('common.actions.edit') }}</button>
        <button v-if="canManageMounts" class="btn btn-danger" :disabled="saving" @click="requestRemove">{{ t('mounts.remove') }}</button>
      </div>

      <p v-if="!canManageMounts" class="muted">{{ t('auth.insufficientPermissions') }}</p>
    </article>

    <section v-if="browseExpanded && mountRecord?.id" class="browse-panel">
      <header class="browse-panel-header">
        <h2>{{ mountBrowseTitle(mountRecord) }}</h2>
        <button class="btn" @click="browseExpanded = false">{{ t('common.actions.close') }}</button>
      </header>
      <DirectoryBrowser :mount-id="mountRecord.id" root-label="" :show-root-crumb-at-root="true" />
    </section>

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

    <teleport to="body">
      <div v-if="showEditDialog" class="dialog-overlay">
        <div ref="editDialogRef" class="dialog-panel mount-dialog-panel" role="dialog" aria-modal="true" :aria-labelledby="editDialogTitleId">
          <div class="dialog-header mount-dialog-header">
            <h2 :id="editDialogTitleId">{{ t('mounts.editDialogTitle') }}</h2>
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
            <template v-if="mountRecord?.local_mount_point">
              <label for="mount-local-path">{{ t('mounts.localMountPointInfo') }}</label>
              <input id="mount-local-path" :value="mountRecord.local_mount_point" type="text" readonly />
            </template>
            <div class="credential-header-row">
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
            <button class="btn" @click="closeEditDialog">{{ t('common.actions.cancel') }}</button>
            <button class="btn" :disabled="saving || dialogTesting || !formValid()" @click="runDialogValidate">
              {{ dialogTesting ? t('common.labels.loading') : t('mounts.test') }}
            </button>
            <button class="btn btn-primary" :disabled="saving || dialogTesting || !formValid() || !dialogValidationPassed" @click="submitMountDialog">
              {{ saving ? t('common.labels.loading') : t('common.actions.save') }}
            </button>
          </div>
        </div>
      </div>
    </teleport>
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row,
.actions,
.detail-grid,
.action-row {
  display: flex;
  gap: var(--space-sm);
}

.header-row {
  justify-content: space-between;
  align-items: center;
}

.detail-card {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
  display: grid;
  gap: var(--space-md);
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--space-md);
}

.detail-grid > div {
  display: grid;
  gap: var(--space-xs);
}

.detail-grid > div > strong {
  font-weight: var(--font-weight-bold);
}

.action-row {
  flex-wrap: wrap;
}

.browse-panel {
  display: grid;
  gap: var(--space-sm);
  padding: var(--space-md);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
}

.browse-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
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

.ok-banner,
.warn-banner,
.error-banner {
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--border-radius-md);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
}

.ok-banner {
  color: var(--color-ok-banner-text, #14532d);
  background: var(--color-ok-banner-bg, #dcfce7);
}

.success-banner {
  color: var(--color-text-primary);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

input,
select {
  width: 100%;
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
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
  width: min(720px, calc(100vw - 2rem));
  max-height: min(720px, calc(100vh - 2rem));
  grid-template-rows: auto minmax(0, 1fr) auto;
  overflow: hidden;
}

.mount-dialog-header {
  display: grid;
  gap: var(--space-sm);
}

.mount-dialog-scroll-region {
  display: grid;
  gap: var(--space-xs);
  min-height: 0;
  overflow-y: auto;
  padding-right: var(--space-2xs);
}

.dialog-footer {
  position: sticky;
  bottom: 0;
  background: var(--color-bg-secondary);
  padding-top: var(--space-sm);
}

.dialog-actions {
  margin-top: var(--space-sm);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
  flex-wrap: wrap;
}

.field-label {
  font-weight: var(--font-weight-bold);
}

.required-indicator {
  color: var(--color-danger, #b91c1c);
  margin-left: 0.15rem;
}

.credential-header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-sm);
}

.btn-inline {
  padding-top: 0;
  padding-bottom: 0;
}

@media (max-width: 768px) {
  .header-row {
    align-items: stretch;
    flex-direction: column;
  }

  .actions {
    flex-wrap: wrap;
  }

  .detail-grid {
    grid-template-columns: 1fr;
  }

  .credential-header-row {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>