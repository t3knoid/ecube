<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { listJobs, createJob, startJob } from '@/api/jobs.js'
import { getDrives } from '@/api/drives.js'
import { getMounts } from '@/api/mounts.js'
import { normalizeErrorMessage } from '@/api/client.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useStatusLabels } from '@/composables/useStatusLabels.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'

const router = useRouter()
const { t } = useI18n()
const { jobStatusLabel } = useStatusLabels()
const authStore = useAuthStore()

const jobs = ref([])
const drives = ref([])
const mounts = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const compatibilityNote = ref('')

const showCreateDialog = ref(false)
const createDialogRef = ref(null)
const createDialogTriggerRef = ref(null)

const search = ref('')
const statusFilter = ref('ALL')
const page = ref(1)
const pageSize = ref(10)

const form = ref({
  project_id: '',
  evidence_number: '',
  drive_id: null,
  mount_id: null,
  source_path: '',
  thread_count: 4,
  notes: '',
  run_immediately: false,
})

const canOperate = computed(() => authStore.hasAnyRole(['admin', 'manager', 'processor']))

const columns = computed(() => [
  { key: 'id', label: t('common.labels.id'), align: 'right' },
  { key: 'project_id', label: t('dashboard.project') },
  { key: 'evidence_number', label: t('jobs.evidence') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'progress', label: t('dashboard.progress') },
  { key: 'actions', label: t('common.actions.edit'), align: 'center' },
])

function progressPercent(job) {
  if (!job || !job.total_bytes) return 0
  return Math.min(100, Math.round((job.copied_bytes / job.total_bytes) * 100))
}

function formatProjectId(value) {
  return normalizeProjectId(value) || '-'
}

function formatDriveLabel(drive) {
  return `#${drive.id} - ${drive.device_identifier || '-'}`
}

function formatMountLabel(mount) {
  return mount?.remote_path || t('jobs.chooseMount')
}

function resetForm() {
  form.value = {
    project_id: '',
    evidence_number: '',
    drive_id: null,
    mount_id: null,
    source_path: '',
    thread_count: 4,
    notes: '',
    run_immediately: false,
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

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return jobs.value.filter((job) => {
    const status = String(job.status || '').toUpperCase()
    const matchesStatus = statusFilter.value === 'ALL' || status === statusFilter.value
    const text = [job.project_id, job.evidence_number, String(job.id), job.source_path]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()
    const matchesQuery = !query || text.includes(query)
    return matchesStatus && matchesQuery
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

const availableProjects = computed(() =>
  [...new Set(
    mounts.value
      .filter((mount) => String(mount?.status || '').toUpperCase() === 'MOUNTED')
      .map((mount) => normalizeProjectId(mount?.project_id))
      .filter((value) => value && value !== 'UNASSIGNED'),
  )].sort((left, right) => left.localeCompare(right)),
)

const selectedProject = computed(() => normalizeProjectId(form.value.project_id))
const projectSelected = computed(() => Boolean(selectedProject.value))

const eligibleMounts = computed(() => {
  if (!projectSelected.value) return []
  return mounts.value.filter(
    (mount) => String(mount?.status || '').toUpperCase() === 'MOUNTED'
      && normalizeProjectId(mount?.project_id) === selectedProject.value,
  )
})

const eligibleDrives = computed(() => {
  if (!projectSelected.value) return []
  return drives.value.filter((drive) => {
    const state = String(drive?.current_state || '').toUpperCase()
    const boundProject = normalizeProjectId(drive?.current_project_id)
    return ['AVAILABLE', 'IN_USE'].includes(state)
      && !!drive?.mount_path
      && (!boundProject || boundProject === selectedProject.value)
  })
})

function formReady() {
  return projectSelected.value
    && !!form.value.evidence_number.trim()
    && !!form.value.source_path.trim()
    && form.value.mount_id != null
    && form.value.mount_id !== ''
    && form.value.drive_id != null
    && form.value.drive_id !== ''
}

async function loadSupportingData() {
  const [driveResult, mountResult] = await Promise.allSettled([getDrives(), getMounts()])
  drives.value = driveResult.status === 'fulfilled'
    ? (driveResult.value || []).map((item) => normalizeProjectRecord(item, ['current_project_id']))
    : []
  mounts.value = mountResult.status === 'fulfilled'
    ? (mountResult.value || []).map((item) => normalizeProjectRecord(item, ['project_id']))
    : []
}

async function loadJobs() {
  loading.value = true
  error.value = ''
  compatibilityNote.value = ''
  try {
    const response = await listJobs({ limit: 200 })
    jobs.value = (response || []).map((item) => normalizeProjectRecord(item, ['project_id']))
  } catch {
    jobs.value = []
    compatibilityNote.value = t('jobs.listUnavailable')
  } finally {
    loading.value = false
  }
}

function syncEligibleSelections() {
  if (!projectSelected.value) {
    form.value.drive_id = null
    form.value.mount_id = null
    return
  }

  const hasDrive = eligibleDrives.value.some((drive) => Number(drive.id) === Number(form.value.drive_id))
  const hasMount = eligibleMounts.value.some((mount) => Number(mount.id) === Number(form.value.mount_id))

  if (!hasDrive) {
    form.value.drive_id = eligibleDrives.value[0]?.id ?? null
  }
  if (!hasMount) {
    form.value.mount_id = eligibleMounts.value[0]?.id ?? null
  }
}

function resolveSourcePath() {
  const mount = eligibleMounts.value.find((item) => item.id === Number(form.value.mount_id))
  const source = form.value.source_path.trim()
  if (!mount || source.startsWith('/')) return source
  const prefix = String(mount.local_mount_point || '').replace(/\/$/, '')
  return `${prefix}/${source}`
}

function buildJobError(err) {
  const status = err?.response?.status
  const detail = normalizeErrorMessage(err?.response?.data, '')

  if (!status) return t('common.errors.networkError')
  if (status === 403) return detail || t('common.errors.insufficientPermissions')
  if (status === 404) return detail || t('common.errors.notFound')
  if (status === 409) return detail || t('common.errors.requestConflict')
  if (status === 422) return detail || t('common.errors.validationFailed')
  if (status >= 500) return t('common.errors.serverError', { status })
  return detail || t('common.errors.serverErrorGeneric')
}

async function submitCreateJob() {
  if (!formReady()) return

  saving.value = true
  error.value = ''
  try {
    await loadSupportingData()
    syncEligibleSelections()

    const driveStillEligible = eligibleDrives.value.some((drive) => Number(drive.id) === Number(form.value.drive_id))
    const mountStillEligible = eligibleMounts.value.some((mount) => Number(mount.id) === Number(form.value.mount_id))

    if (!driveStillEligible || !mountStillEligible) {
      error.value = t('jobs.selectionUnavailable')
      return
    }

    const payload = {
      project_id: selectedProject.value,
      evidence_number: form.value.evidence_number.trim(),
      source_path: resolveSourcePath(),
      drive_id: Number(form.value.drive_id),
      thread_count: Number(form.value.thread_count),
    }

    const created = normalizeProjectRecord(await createJob(payload), ['project_id'])

    if (form.value.run_immediately) {
      try {
        const started = normalizeProjectRecord(await startJob(created.id), ['project_id'])
        jobs.value = [started, ...jobs.value.filter((job) => job.id !== started.id)]
        closeCreateDialog()
        router.push({ name: 'job-detail', params: { id: started.id } })
        return
      } catch (err) {
        jobs.value = [created, ...jobs.value.filter((job) => job.id !== created.id)]
        closeCreateDialog()
        error.value = buildJobError(err) || t('jobs.autoStartFailed')
        return
      }
    }

    jobs.value = [created, ...jobs.value.filter((job) => job.id !== created.id)]
    closeCreateDialog()
    router.push({ name: 'job-detail', params: { id: created.id } })
  } catch (err) {
    error.value = buildJobError(err)
  } finally {
    saving.value = false
  }
}

function openCreateDialog(event) {
  createDialogTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement
  resetForm()
  error.value = ''
  showCreateDialog.value = true
  void loadSupportingData()
}

function closeCreateDialog() {
  showCreateDialog.value = false
  resetForm()
}

function handleCreateDialogKeydown(event) {
  if (!showCreateDialog.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeCreateDialog()
    return
  }
  if (event.key === 'Tab') {
    trapFocusWithin(event, createDialogRef.value)
  }
}

watch(
  () => form.value.project_id,
  (value) => {
    const normalized = normalizeProjectId(value)
    if (value !== normalized) {
      form.value.project_id = normalized
      return
    }
    syncEligibleSelections()
  },
)

watch(showCreateDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleCreateDialogKeydown)
    await nextTick()
    const target = createDialogRef.value?.querySelector('#job-project')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  document.removeEventListener('keydown', handleCreateDialogKeydown)
  const trigger = createDialogTriggerRef.value
  createDialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

onMounted(async () => {
  await Promise.all([loadJobs(), loadSupportingData()])
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleCreateDialogKeydown)
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('jobs.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadJobs">{{ t('common.actions.refresh') }}</button>
        <button class="btn btn-primary" :disabled="!canOperate" @click="openCreateDialog">
          {{ t('jobs.create') }}
        </button>
      </div>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner" role="alert" aria-live="assertive">{{ error }}</p>
    <p v-if="compatibilityNote" class="muted">{{ compatibilityNote }}</p>

    <div class="filters">
      <input v-model="search" type="text" :placeholder="t('jobs.searchPlaceholder')" />
      <select v-model="statusFilter">
        <option value="ALL">{{ t('jobs.allStatuses') }}</option>
        <option value="PENDING">{{ t('jobs.statuses.pending') }}</option>
        <option value="RUNNING">{{ t('jobs.statuses.running') }}</option>
        <option value="VERIFYING">{{ t('jobs.statuses.verifying') }}</option>
        <option value="COMPLETED">{{ t('jobs.statuses.completed') }}</option>
        <option value="FAILED">{{ t('jobs.statuses.failed') }}</option>
      </select>
    </div>

    <DataTable :columns="columns" :rows="paged" :empty-text="t('jobs.empty')">
      <template #cell-project_id="{ row }">{{ formatProjectId(row.project_id) }}</template>
      <template #cell-status="{ row }">
        <StatusBadge :status="row.status" :label="jobStatusLabel(row.status)" />
      </template>
      <template #cell-progress="{ row }">{{ progressPercent(row) }}%</template>
      <template #cell-actions="{ row }">
        <button class="btn" @click="router.push({ name: 'job-detail', params: { id: row.id } })">
          {{ t('jobs.open') }}
        </button>
      </template>
    </DataTable>

    <Pagination v-model:page="page" :page-size="pageSize" :total="filtered.length" />

    <teleport to="body">
      <div v-if="showCreateDialog" class="dialog-overlay" @click.self="closeCreateDialog">
        <div ref="createDialogRef" class="dialog-panel" role="dialog" aria-modal="true" aria-labelledby="job-create-title">
          <h2 id="job-create-title">{{ t('jobs.createDialog') }}</h2>
          <p class="muted">{{ t('jobs.dialogDescription') }}</p>

          <div class="dialog-groups">
            <fieldset class="dialog-group">
              <legend>{{ t('jobs.jobDetailsGroup') }}</legend>

              <label for="job-project">{{ t('dashboard.project') }}</label>
              <select id="job-project" v-model="form.project_id">
                <option value="">{{ t('jobs.chooseProject') }}</option>
                <option v-for="project in availableProjects" :key="project" :value="project">{{ project }}</option>
              </select>

              <label for="job-evidence">{{ t('jobs.evidence') }}</label>
              <input id="job-evidence" v-model="form.evidence_number" type="text" :disabled="!projectSelected" />

              <label for="job-notes">{{ t('jobs.additionalNotes') }}</label>
              <textarea id="job-notes" v-model="form.notes" rows="3" :disabled="!projectSelected" :placeholder="t('jobs.notesHint')"></textarea>

              <label for="job-thread-count">{{ t('jobs.threadCount') }}</label>
              <input id="job-thread-count" v-model.number="form.thread_count" type="number" min="1" max="8" :disabled="!projectSelected" />
            </fieldset>

            <fieldset class="dialog-group">
              <legend>{{ t('jobs.sourceGroup') }}</legend>

              <label for="job-mount">{{ t('jobs.selectMount') }}</label>
              <select id="job-mount" v-model="form.mount_id" :disabled="!projectSelected">
                <option :value="null">{{ t('jobs.chooseMount') }}</option>
                <option v-for="mount in eligibleMounts" :key="mount.id" :value="mount.id">
                  {{ formatMountLabel(mount) }}
                </option>
              </select>

              <label for="job-source-path">{{ t('jobs.sourcePath') }}</label>
              <input id="job-source-path" v-model="form.source_path" type="text" :disabled="!projectSelected" :placeholder="t('jobs.sourcePathHint')" />
            </fieldset>

            <fieldset class="dialog-group">
              <legend>{{ t('jobs.destinationGroup') }}</legend>

              <label for="job-drive">{{ t('jobs.selectDrive') }}</label>
              <select id="job-drive" v-model="form.drive_id" :disabled="!projectSelected">
                <option :value="null">{{ t('jobs.chooseDrive') }}</option>
                <option v-for="drive in eligibleDrives" :key="drive.id" :value="drive.id">
                  {{ formatDriveLabel(drive) }}
                </option>
              </select>
            </fieldset>

            <fieldset class="dialog-group">
              <legend>{{ t('jobs.executionGroup') }}</legend>
              <label class="checkbox-row" for="job-run-immediately">
                <input id="job-run-immediately" v-model="form.run_immediately" type="checkbox" :disabled="!projectSelected" />
                <span>{{ t('jobs.runImmediately') }}</span>
              </label>
            </fieldset>
          </div>

          <p v-if="!availableProjects.length" class="muted">{{ t('jobs.noProjectsAvailable') }}</p>
          <p v-else-if="projectSelected && !eligibleMounts.length" class="muted">{{ t('jobs.noEligibleMounts') }}</p>
          <p v-else-if="projectSelected && !eligibleDrives.length" class="muted">{{ t('jobs.noEligibleDrives') }}</p>

          <div class="dialog-actions">
            <button class="btn" @click="closeCreateDialog">{{ t('common.actions.cancel') }}</button>
            <button id="job-submit" class="btn btn-primary" :disabled="saving || !formReady()" @click="submitCreateJob">
              {{ saving ? t('common.labels.loading') : t('jobs.create') }}
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

input,
select,
textarea {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

textarea {
  resize: vertical;
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

.dialog-overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, var(--color-bg-primary) 30%, #000000);
  display: grid;
  place-items: center;
  z-index: 1000;
}

.dialog-panel {
  width: min(760px, 100%);
  max-height: min(90vh, 900px);
  overflow: auto;
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-lg);
  display: grid;
  gap: var(--space-md);
}

.dialog-groups {
  display: grid;
  gap: var(--space-md);
}

.dialog-group {
  display: grid;
  gap: var(--space-xs);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-md);
}

.dialog-group legend {
  padding: 0 var(--space-xs);
  font-weight: 600;
}

.checkbox-row {
  display: inline-flex;
  align-items: center;
  gap: var(--space-sm);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}
</style>
