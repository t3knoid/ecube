<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { getDrives, formatDrive, initializeDrive, prepareEjectDrive } from '@/api/drives.js'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const drive = ref(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const infoMessage = ref('')

const showFormatDialog = ref(false)
const showEjectDialog = ref(false)
const showInitializeDialog = ref(false)

const filesystemType = ref('ext4')
const projectId = ref('')

const driveId = computed(() => Number(route.params.id))
const canManage = computed(() => authStore.hasAnyRole(['admin', 'manager']))

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
  error.value = ''
  infoMessage.value = ''
  try {
    const drives = await getDrives()
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
  error.value = ''
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

async function runInitialize() {
  if (!drive.value || !projectId.value.trim()) return
  saving.value = true
  error.value = ''
  try {
    drive.value = await initializeDrive(drive.value.id, { project_id: projectId.value.trim() })
    infoMessage.value = t('drives.initializeSuccess')
    showInitializeDialog.value = false
    projectId.value = ''
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

async function runPrepareEject() {
  if (!drive.value) return
  saving.value = true
  error.value = ''
  try {
    drive.value = await prepareEjectDrive(drive.value.id)
    infoMessage.value = t('drives.ejectSuccess')
    showEjectDialog.value = false
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

onMounted(loadDrive)
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

    <article v-if="drive" class="detail-card">
      <div class="detail-grid">
        <div><strong>ID</strong><span>{{ drive.id }}</span></div>
        <div><strong>{{ t('drives.device') }}</strong><span>{{ drive.device_identifier }}</span></div>
        <div><strong>{{ t('drives.filesystemPath') }}</strong><span>{{ drive.filesystem_path || '-' }}</span></div>
        <div><strong>{{ t('drives.filesystem') }}</strong><span>{{ drive.filesystem_type || '-' }}</span></div>
        <div><strong>{{ t('common.labels.size') }}</strong><span>{{ formatBytes(drive.capacity_bytes) }}</span></div>
        <div><strong>{{ t('dashboard.project') }}</strong><span>{{ drive.current_project_id || '-' }}</span></div>
        <div><strong>{{ t('common.labels.status') }}</strong><StatusBadge :status="drive.current_state" /></div>
      </div>

      <div class="action-row">
        <button class="btn" :disabled="!canManage" @click="showFormatDialog = true">{{ t('drives.format') }}</button>
        <button class="btn" :disabled="!canManage" @click="showInitializeDialog = true">{{ t('drives.initialize') }}</button>
        <button class="btn btn-danger" :disabled="!canManage" @click="showEjectDialog = true">{{ t('drives.prepareEject') }}</button>
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
    />

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
          <p class="muted">{{ t('drives.projectWarning') }}</p>
          <label class="field-label" for="project-id">{{ t('dashboard.project') }}</label>
          <input id="project-id" v-model="projectId" type="text" />
          <div class="dialog-actions">
            <button class="btn" :disabled="saving" @click="showInitializeDialog = false">{{ t('common.actions.cancel') }}</button>
            <button class="btn btn-primary" :disabled="saving || !projectId.trim()" @click="runInitialize">{{ t('drives.initialize') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <div class="fs-selector" v-if="showFormatDialog">
      <label for="filesystem-selector">{{ t('drives.filesystem') }}</label>
      <select id="filesystem-selector" v-model="filesystemType">
        <option value="ext4">ext4</option>
        <option value="exfat">exfat</option>
      </select>
    </div>
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

.btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
  cursor: pointer;
}

.btn-primary {
  background: var(--color-btn-primary-bg);
  color: var(--color-btn-primary-text);
  border-color: var(--color-btn-primary-bg);
}

.btn-danger {
  background: var(--color-btn-danger-bg);
  color: var(--color-btn-danger-text);
  border-color: var(--color-btn-danger-bg);
}

.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.muted {
  color: var(--color-text-secondary);
}

.error-banner,
.ok-banner {
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
}

.ok-banner {
  color: var(--color-success);
  background: color-mix(in srgb, var(--color-success) 14%, var(--color-bg-secondary));
  border: 1px solid color-mix(in srgb, var(--color-success) 45%, var(--color-border));
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

.fs-selector {
  position: fixed;
  bottom: var(--space-md);
  right: var(--space-md);
  display: grid;
  gap: var(--space-xs);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
  box-shadow: var(--shadow-sm);
}
</style>
