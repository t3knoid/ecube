<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { listJobs, createJob } from '@/api/jobs.js'
import { getDrives } from '@/api/drives.js'
import { getMounts } from '@/api/mounts.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import { useStatusLabels } from '@/composables/useStatusLabels.js'

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

const showWizard = ref(false)
const wizardStep = ref(1)

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

async function loadSupportingData() {
  const [driveResult, mountResult] = await Promise.allSettled([getDrives(), getMounts()])
  drives.value = driveResult.status === 'fulfilled' ? driveResult.value : []
  mounts.value = mountResult.status === 'fulfilled' ? mountResult.value : []
}

async function loadJobs() {
  loading.value = true
  error.value = ''
  compatibilityNote.value = ''
  try {
    jobs.value = await listJobs({ limit: 200 })
  } catch {
    jobs.value = []
    compatibilityNote.value = t('jobs.listUnavailable')
  } finally {
    loading.value = false
  }
}

function resolveSourcePath() {
  const mount = mounts.value.find((item) => item.id === Number(form.value.mount_id))
  const source = form.value.source_path.trim()
  if (!mount || source.startsWith('/')) return source
  const prefix = String(mount.local_mount_point || '').replace(/\/$/, '')
  return `${prefix}/${source}`
}

async function submitCreateJob() {
  saving.value = true
  error.value = ''
  try {
    const payload = {
      project_id: form.value.project_id.trim(),
      evidence_number: form.value.evidence_number.trim(),
      source_path: resolveSourcePath(),
      drive_id: form.value.drive_id ? Number(form.value.drive_id) : undefined,
      thread_count: Number(form.value.thread_count),
    }
    const created = await createJob(payload)
    jobs.value = [created, ...jobs.value]
    showWizard.value = false
    wizardStep.value = 1
    router.push({ name: 'job-detail', params: { id: created.id } })
  } catch {
    error.value = t('common.errors.validationFailed')
  } finally {
    saving.value = false
  }
}

function openWizard() {
  form.value = {
    project_id: '',
    evidence_number: '',
    drive_id: null,
    mount_id: null,
    source_path: '',
    thread_count: 4,
  }
  wizardStep.value = 1
  showWizard.value = true
}

function canMoveNext() {
  if (wizardStep.value === 1) return !!form.value.drive_id
  if (wizardStep.value === 2) return !!form.value.mount_id
  if (wizardStep.value === 3) return !!form.value.project_id.trim() && !!form.value.evidence_number.trim() && !!form.value.source_path.trim()
  return true
}

onMounted(async () => {
  await Promise.all([loadJobs(), loadSupportingData()])
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('jobs.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadJobs">{{ t('common.actions.refresh') }}</button>
        <button class="btn btn-primary" :disabled="!canOperate" @click="openWizard">
          {{ t('jobs.create') }}
        </button>
      </div>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>
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
      <div v-if="showWizard" class="dialog-overlay" @click.self="showWizard = false">
        <div class="dialog-panel" role="dialog" aria-modal="true">
          <h2>{{ t('jobs.createWizard') }} - {{ wizardStep }}/4</h2>

          <div v-if="wizardStep === 1" class="step-grid">
            <label>{{ t('jobs.selectDrive') }}</label>
            <select v-model="form.drive_id">
              <option :value="null">{{ t('jobs.chooseDrive') }}</option>
              <option v-for="drive in drives" :key="drive.id" :value="drive.id">
                #{{ drive.id }} - {{ drive.device_identifier }}
              </option>
            </select>
          </div>

          <div v-else-if="wizardStep === 2" class="step-grid">
            <label>{{ t('jobs.selectMount') }}</label>
            <select v-model="form.mount_id">
              <option :value="null">{{ t('jobs.chooseMount') }}</option>
              <option v-for="mount in mounts" :key="mount.id" :value="mount.id">
                {{ mount.remote_path }} ({{ mount.local_mount_point }})
              </option>
            </select>
          </div>

          <div v-else-if="wizardStep === 3" class="step-grid">
            <label>{{ t('dashboard.project') }}</label>
            <input v-model="form.project_id" type="text" />
            <label>{{ t('jobs.evidence') }}</label>
            <input v-model="form.evidence_number" type="text" />
            <label>{{ t('jobs.sourcePath') }}</label>
            <input v-model="form.source_path" type="text" :placeholder="t('jobs.sourcePathHint')" />
          </div>

          <div v-else class="step-grid">
            <label>{{ t('jobs.threadCount') }}</label>
            <input v-model.number="form.thread_count" type="number" min="1" max="8" />
          </div>

          <div class="dialog-actions">
            <button class="btn" @click="showWizard = false">{{ t('common.actions.cancel') }}</button>
            <button class="btn" :disabled="wizardStep <= 1" @click="wizardStep -= 1">{{ t('common.actions.back') }}</button>
            <button
              v-if="wizardStep < 4"
              class="btn btn-primary"
              :disabled="!canMoveNext()"
              @click="wizardStep += 1"
            >
              {{ t('common.actions.next') }}
            </button>
            <button
              v-else
              class="btn btn-primary"
              :disabled="saving || !canMoveNext()"
              @click="submitCreateJob"
            >
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
  width: min(620px, 100%);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-lg);
  display: grid;
  gap: var(--space-md);
}

.step-grid {
  display: grid;
  gap: var(--space-xs);
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}
</style>
