<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { getDrives, formatDrive, initializeDrive, mountDrive, prepareEjectDrive, refreshDrives } from '@/api/drives.js'
import { getMounts } from '@/api/mounts.js'
import { enablePort } from '@/api/admin.js'
import { normalizeErrorMessage } from '@/api/client.js'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useStatusLabels } from '@/composables/useStatusLabels.js'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import DirectoryBrowser from '@/components/browse/DirectoryBrowser.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const drive = ref(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const infoMessage = ref('')
const warnMessage = ref('')

function clearBanners() {
  error.value = ''
  infoMessage.value = ''
  warnMessage.value = ''
}

const showFormatDialog = ref(false)
const showEjectDialog = ref(false)
const showInitializeDialog = ref(false)
const browseExpanded = ref(false)
const showCocPrompt = ref(false)

const filesystemType = ref('ext4')
const projectId = ref('')
const loadingProjects = ref(false)
const mountedProjectOptions = ref([])

const { driveStateLabel } = useStatusLabels()

const driveId = computed(() => Number(route.params.id))
const canManage = computed(() => authStore.hasAnyRole(['admin', 'manager']))
const canEnable = computed(
  () => drive.value?.current_state === 'DISCONNECTED' && drive.value?.port_id != null && canManage.value,
)
const canFormat = computed(
  () => drive.value?.current_state === 'AVAILABLE' && canManage.value,
)
const canInitialize = computed(
  () => drive.value?.current_state === 'AVAILABLE' && canManage.value,
)
const canMount = computed(
  () => canManage.value
    && ['AVAILABLE', 'IN_USE'].includes(drive.value?.current_state)
    && !drive.value?.mount_path
    && !!drive.value?.filesystem_path,
)
const canEject = computed(
  () => drive.value?.current_state === 'IN_USE' && canManage.value,
)
const hasMountedProjectOptions = computed(() => mountedProjectOptions.value.length > 0)

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

async function loadDrive() {
  loading.value = true
  clearBanners()
  try {
    const drives = await getDrives({ include_disconnected: true })
    drive.value = drives.find((item) => item.id === driveId.value) || null
    if (!drive.value) {
      error.value = t('drives.notFound')
    }
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
}

async function runFormat() {
  if (!drive.value) return
  saving.value = true
  clearBanners()
  try {
    drive.value = await formatDrive(drive.value.id, { filesystem_type: filesystemType.value })
    infoMessage.value = t('drives.formatSuccess')
    showFormatDialog.value = false
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

function normalizeMountedProjectOptions(mounts) {
  return [...new Set(
    (mounts || [])
      .filter((mount) => mount?.status === 'MOUNTED')
      .map((mount) => (typeof mount?.project_id === 'string' ? mount.project_id.trim() : ''))
      .filter((value) => value && value.toUpperCase() !== 'UNASSIGNED'),
  )].sort((left, right) => left.localeCompare(right))
}

async function loadMountedProjects() {
  loadingProjects.value = true
  try {
    const mounts = await getMounts()
    mountedProjectOptions.value = normalizeMountedProjectOptions(mounts)
    const currentProject = typeof drive.value?.current_project_id === 'string'
      ? drive.value.current_project_id.trim()
      : ''

    if (currentProject && mountedProjectOptions.value.includes(currentProject)) {
      projectId.value = currentProject
    } else {
      projectId.value = mountedProjectOptions.value[0] || ''
    }
  } catch {
    mountedProjectOptions.value = []
    projectId.value = ''
    error.value = t('common.errors.networkError')
  } finally {
    loadingProjects.value = false
  }
}

async function runInitialize() {
  if (!drive.value || !projectId.value.trim()) return
  saving.value = true
  clearBanners()
  try {
    drive.value = await initializeDrive(drive.value.id, { project_id: projectId.value.trim() })
    infoMessage.value = t('drives.initializeSuccess')
    showInitializeDialog.value = false
    projectId.value = ''
  } catch (err) {
    const status = err?.response?.status
    const detail = normalizeErrorMessage(err?.response?.data, null)
    if (!status) {
      error.value = t('common.errors.networkError')
    } else if (status === 403) {
      error.value = detail || t('common.errors.insufficientPermissions')
    } else if (status === 404) {
      error.value = detail || t('common.errors.notFound')
    } else if (status === 409) {
      error.value = detail || t('common.errors.requestConflict')
    } else if (status === 422) {
      error.value = detail || t('common.errors.validationFailed')
    } else if (status >= 500) {
      error.value = t('common.errors.serverError', { status })
    } else {
      error.value = t('common.errors.serverErrorGeneric')
    }
  } finally {
    saving.value = false
  }
}

function openInitializeDialog() {
  showInitializeDialog.value = true
  void loadMountedProjects()
}

async function runEnable() {
  if (!drive.value) return
  if (drive.value.port_id == null) {
    clearBanners()
    error.value = t('drives.enableNoPort')
    return
  }
  saving.value = true
  clearBanners()
  try {
    await enablePort(drive.value.port_id)
    await refreshDrives()
    await loadDrive()
    if (!drive.value) return
    if (drive.value.current_state === 'AVAILABLE') {
      infoMessage.value = t('drives.enableSuccess')
    } else {
      warnMessage.value = t('drives.enablePending', {
        state: driveStateLabel(drive.value.current_state),
      })
    }
  } catch (err) {
    const status = err?.response?.status
    const detail = normalizeErrorMessage(err?.response?.data, null)
    if (!status) {
      error.value = t('common.errors.networkError')
    } else if (status === 403) {
      error.value = t('common.errors.insufficientPermissions')
    } else if (status === 400) {
      error.value = detail || t('common.errors.invalidRequest')
    } else if (status === 404) {
      error.value = detail || t('drives.enablePortNotFound')
    } else if (status === 409) {
      error.value = t('common.errors.requestConflict')
    } else if (status === 422) {
      error.value = detail || t('common.errors.validationFailed')
    } else if (status >= 500) {
      error.value = t('common.errors.serverError', { status })
    } else {
      error.value = t('common.errors.serverErrorGeneric')
    }
  } finally {
    saving.value = false
  }
}

async function runMount() {
  if (!drive.value) return
  saving.value = true
  clearBanners()
  try {
    drive.value = await mountDrive(drive.value.id)
    infoMessage.value = t('drives.mountSuccess')
  } catch (err) {
    const status = err?.response?.status
    const detail = normalizeErrorMessage(err?.response?.data, null)
    if (!status) {
      error.value = t('common.errors.networkError')
    } else if (status === 403) {
      error.value = detail || t('common.errors.insufficientPermissions')
    } else if (status === 404) {
      error.value = detail || t('common.errors.notFound')
    } else if (status === 409) {
      error.value = detail || t('common.errors.requestConflict')
    } else if (status === 422) {
      error.value = detail || t('common.errors.validationFailed')
    } else if (status >= 500) {
      error.value = detail || t('common.errors.serverError', { status })
    } else {
      error.value = t('common.errors.serverErrorGeneric')
    }
  } finally {
    saving.value = false
  }
}

async function runPrepareEject() {
  if (!drive.value) return
  saving.value = true
  clearBanners()
  try {
    drive.value = await prepareEjectDrive(drive.value.id)
    infoMessage.value = t('drives.ejectSuccess')
    showEjectDialog.value = false
    showCocPrompt.value = true
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

function openChainOfCustody() {
  if (!drive.value) return
  const query = {
    coc: '1',
    drive_id: String(drive.value.id),
  }
  if (drive.value.device_identifier) query.drive_sn = drive.value.device_identifier
  if (drive.value.current_project_id) query.project_id = drive.value.current_project_id
  router.push({ name: 'audit', query })
}

onMounted(loadDrive)

watch(driveId, () => {
  browseExpanded.value = false
  loadDrive()
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('drives.detail') }} #{{ driveId }}</h1>
      <div class="actions">
        <button class="btn" @click="router.push({ name: 'drives' })">{{ t('common.actions.back') }}</button>
        <button class="btn" @click="loadDrive">{{ t('common.actions.refresh') }}</button>
      </div>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="infoMessage" class="ok-banner">{{ infoMessage }}</p>
    <p v-if="warnMessage" class="warn-banner">{{ warnMessage }}</p>
    <div v-if="showCocPrompt" class="coc-banner">
      <p>{{ t('drives.cocPrompt') }}</p>
      <div class="actions">
        <button class="btn btn-primary" @click="openChainOfCustody">{{ t('drives.openCocReport') }}</button>
        <button class="btn" @click="showCocPrompt = false">{{ t('common.actions.close') }}</button>
      </div>
    </div>

    <article v-if="drive" class="detail-card">
      <div class="detail-grid">
        <div><strong>{{ t('common.labels.id') }}</strong><span>{{ drive.id }}</span></div>
        <div><strong>{{ t('drives.device') }}</strong><span>{{ drive.device_identifier }}</span></div>
        <div><strong>{{ t('drives.filesystemPath') }}</strong><span>{{ drive.filesystem_path || '-' }}</span></div>
        <div><strong>{{ t('drives.mountPoint') }}</strong><span>{{ drive.mount_path || '-' }}</span></div>
        <div><strong>{{ t('drives.filesystem') }}</strong><span>{{ drive.filesystem_type || '-' }}</span></div>
        <div><strong>{{ t('common.labels.size') }}</strong><span>{{ formatBytes(drive.capacity_bytes) }}</span></div>
        <div><strong>{{ t('dashboard.project') }}</strong><span>{{ drive.current_project_id || '-' }}</span></div>
        <div><strong>{{ t('common.labels.status') }}</strong><StatusBadge :status="drive.current_state" :label="driveStateLabel(drive.current_state)" /></div>
      </div>

      <div class="action-row">
        <button v-if="canEnable" class="btn btn-primary" :disabled="saving" @click="runEnable">{{ t('drives.enable') }}</button>
        <button v-if="canMount" class="btn" :disabled="saving" @click="runMount">{{ t('drives.mount') }}</button>
        <button class="btn" :disabled="!canFormat || saving" @click="showFormatDialog = true">{{ t('drives.format') }}</button>
        <button class="btn" :disabled="!canInitialize || saving" @click="openInitializeDialog">{{ t('drives.initialize') }}</button>
        <button class="btn btn-danger" :disabled="!canEject || saving" @click="showEjectDialog = true">{{ t('drives.prepareEject') }}</button>
      </div>

      <p v-if="!canManage" class="muted">{{ t('auth.insufficientPermissions') }}</p>
    </article>

    <ConfirmDialog
      v-model="showFormatDialog"
      :title="t('drives.formatConfirmTitle')"
      :message="t('drives.formatConfirmBody')"
      :confirm-label="t('drives.format')"
      :cancel-label="t('common.actions.cancel')"
      :busy="saving"
      dangerous
      @confirm="runFormat"
    >
      <div class="format-selector">
        <label class="field-label" for="filesystem-selector">{{ t('drives.filesystem') }}</label>
        <select id="filesystem-selector" v-model="filesystemType">
          <option value="ext4">ext4</option>
          <option value="exfat">exfat</option>
        </select>
      </div>
    </ConfirmDialog>

    <!-- Browse section — shown when drive has an active mount_path and is not DISCONNECTED -->
    <section v-if="drive && drive.mount_path" class="browse-section">
      <button
        class="browse-toggle btn"
        :aria-expanded="browseExpanded"
        @click="browseExpanded = !browseExpanded"
      >
        <span aria-hidden="true">{{ browseExpanded ? '▼' : '▶' }}</span> {{ t('browse.browseContents') }}
      </button>
      <div v-if="browseExpanded" class="browse-panel">
        <DirectoryBrowser :mount-path="drive.mount_path" />
      </div>
    </section>

    <ConfirmDialog
      v-model="showEjectDialog"
      :title="t('drives.ejectConfirmTitle')"
      :message="t('drives.ejectConfirmBody')"
      :confirm-label="t('drives.prepareEject')"
      :cancel-label="t('common.actions.cancel')"
      :busy="saving"
      dangerous
      @confirm="runPrepareEject"
    />

    <teleport to="body">
      <div v-if="showInitializeDialog" class="dialog-overlay" @click.self="showInitializeDialog = false">
        <div class="dialog-panel" role="dialog" aria-modal="true">
          <h3>{{ t('drives.initializeTitle') }}</h3>
          <p class="muted">
            {{ t('drives.projectWarning') }}
            <template v-if="drive.current_project_id"> {{ t('drives.initializeProjectHint', { project: drive.current_project_id }) }}</template>
          </p>
          <label class="field-label" for="project-id">{{ t('dashboard.project') }}</label>
          <select id="project-id" v-model="projectId" :disabled="loadingProjects || !hasMountedProjectOptions">
            <option value="" disabled>{{ t('audit.selectProject') }}</option>
            <option v-for="option in mountedProjectOptions" :key="option" :value="option">{{ option }}</option>
          </select>
          <p v-if="!loadingProjects && !hasMountedProjectOptions" class="muted">{{ t('drives.initializeNoProjects') }}</p>
          <div class="dialog-actions">
            <button class="btn" :disabled="saving" @click="showInitializeDialog = false">{{ t('common.actions.cancel') }}</button>
            <button class="btn btn-primary" :disabled="saving || loadingProjects || !projectId.trim()" @click="runInitialize">{{ t('drives.initialize') }}</button>
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

.action-row {
  margin-top: var(--space-md);
}

.muted {
  color: var(--color-text-secondary);
}

.error-banner,
.ok-banner,
.warn-banner,
.coc-banner {
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
}

.ok-banner {
  color: var(--color-ok-banner-text, #14532d);
  background: color-mix(in srgb, var(--color-success) 14%, var(--color-bg-secondary));
  border: 1px solid color-mix(in srgb, var(--color-success) 45%, var(--color-border));
}

.warn-banner {
  color: var(--color-text-primary);
  background: color-mix(in srgb, var(--color-warning, #f59e0b) 14%, var(--color-bg-secondary));
  border: 1px solid color-mix(in srgb, var(--color-warning, #f59e0b) 45%, var(--color-border));
}

.coc-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--space-sm);
  color: var(--color-text-primary);
  background: color-mix(in srgb, var(--color-warning, #f59e0b) 14%, var(--color-bg-secondary));
  border: 1px solid color-mix(in srgb, var(--color-warning, #f59e0b) 45%, var(--color-border));
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
  width: min(480px, 100%);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  padding: var(--space-lg);
  box-shadow: var(--shadow-lg);
  display: grid;
  gap: var(--space-sm);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}

.field-label {
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

.format-selector {
  display: grid;
  gap: var(--space-xs);
}

.browse-section {
  display: grid;
  gap: var(--space-sm);
}

.browse-toggle {
  justify-self: start;
}
</style>
