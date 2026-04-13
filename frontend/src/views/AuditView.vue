<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { confirmChainOfCustodyHandoff, getAudit, getChainOfCustody } from '@/api/audit.js'
import { getDrives } from '@/api/drives.js'
import { useSettingsStore } from '@/stores/settings.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'

const { t } = useI18n()
const route = useRoute()
const settingsStore = useSettingsStore()

const logs = ref([])
const loading = ref(false)
const error = ref('')
const expanded = ref(new Set())

const filters = ref({
  user: '',
  action: '',
  since: '',
  until: '',
})

const cocFilters = ref({
  drive_id: '',
  drive_sn: '',
  project_id: '',
})
const cocLoading = ref(false)
const cocError = ref('')
const cocReport = ref(null)
const cocStatusMessage = ref('')
const handoffSaving = ref(false)
const showHandoffWarning = ref(false)
const handoffForm = ref({
  drive_id: '',
  project_id: '',
  possessor: '',
  delivery_time: '',
  received_by: '',
  receipt_ref: '',
  notes: '',
})
const driveOptions = ref([])
const projectOptions = ref([])

const page = ref(1)
const pageSize = ref(20)

const columns = computed(() => [
  { key: 'timestamp', label: t('common.labels.date') },
  { key: 'user', label: t('auth.username') },
  { key: 'action', label: t('audit.action') },
  { key: 'job_id', label: t('audit.jobId'), align: 'right' },
  { key: 'client_ip', label: t('audit.clientIp') },
  { key: 'details', label: t('audit.details') },
])

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return logs.value.slice(start, start + pageSize.value)
})

function toggleDetails(id) {
  if (expanded.value.has(id)) {
    expanded.value.delete(id)
  } else {
    expanded.value.add(id)
  }
  expanded.value = new Set(expanded.value)
}

function asLocalDate(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleString()
}

function toIsoDate(value) {
  return value ? new Date(value).toISOString() : undefined
}

async function loadAudit() {
  loading.value = true
  error.value = ''
  try {
    logs.value = await getAudit({
      user: filters.value.user || undefined,
      action: filters.value.action || undefined,
      since: toIsoDate(filters.value.since),
      until: toIsoDate(filters.value.until),
      limit: 500,
      offset: 0,
    })
    page.value = 1
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
}

async function loadDriveOptions() {
  try {
    const drives = await getDrives()
    const activeDrives = drives.filter((drive) => drive.current_state !== 'ARCHIVED')
    driveOptions.value = activeDrives
      .map((drive) => ({
        id: String(drive.id),
        label: `#${drive.id} (${drive.device_identifier || '-'})`,
      }))
      .sort((a, b) => Number(a.id) - Number(b.id))

    projectOptions.value = [...new Set(
      activeDrives
        .map((drive) => drive.current_project_id)
        .filter((value) => typeof value === 'string' && value.trim())
        .map((value) => value.trim())
    )].sort((a, b) => a.localeCompare(b))
  } catch {
    driveOptions.value = []
    projectOptions.value = []
  }
}

function buildCocParams() {
  const params = {}
  const driveId = Number(cocFilters.value.drive_id)
  if (Number.isInteger(driveId) && driveId > 0) {
    params.drive_id = driveId
  }
  if (cocFilters.value.drive_sn.trim()) {
    params.drive_sn = cocFilters.value.drive_sn.trim()
  }
  if (cocFilters.value.project_id.trim()) {
    params.project_id = cocFilters.value.project_id.trim()
  }
  return params
}

async function loadChainOfCustody() {
  cocLoading.value = true
  cocError.value = ''
  cocStatusMessage.value = ''
  try {
    cocReport.value = await getChainOfCustody(buildCocParams())
  } catch {
    cocError.value = t('common.errors.requestConflict')
  } finally {
    cocLoading.value = false
  }
}

function prepareHandoff(report) {
  handoffForm.value = {
    drive_id: String(report.drive_id),
    project_id: report.project_id || '',
    possessor: '',
    delivery_time: '',
    received_by: '',
    receipt_ref: '',
    notes: '',
  }
}

async function submitHandoff() {
  const driveId = Number(handoffForm.value.drive_id)
  if (!Number.isInteger(driveId) || driveId <= 0 || !handoffForm.value.possessor.trim() || !handoffForm.value.delivery_time) {
    cocError.value = t('audit.handoffInvalid')
    return
  }

  // Show the warning modal instead of submitting directly
  showHandoffWarning.value = true
}

async function confirmHandoffSubmission() {
  showHandoffWarning.value = false
  
  const driveId = Number(handoffForm.value.drive_id)
  handoffSaving.value = true
  cocError.value = ''
  try {
    await confirmChainOfCustodyHandoff({
      drive_id: driveId,
      project_id: handoffForm.value.project_id.trim() || undefined,
      possessor: handoffForm.value.possessor.trim(),
      delivery_time: new Date(handoffForm.value.delivery_time).toISOString(),
      received_by: handoffForm.value.received_by.trim() || undefined,
      receipt_ref: handoffForm.value.receipt_ref.trim() || undefined,
      notes: handoffForm.value.notes.trim() || undefined,
    })
    cocStatusMessage.value = t('audit.handoffSaved')
    await loadChainOfCustody()
  } catch {
    cocError.value = t('common.errors.requestConflict')
  } finally {
    handoffSaving.value = false
  }
}

function cancelHandoffSubmission() {
  showHandoffWarning.value = false
}

function saveCocReport() {
  if (!cocReport.value) return
  const blob = new Blob([JSON.stringify(cocReport.value, null, 2)], { type: 'application/json;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
  anchor.download = `chain-of-custody-${timestamp}.json`
  anchor.click()
  URL.revokeObjectURL(url)
}

function printCocReport() {
  window.print()
}

function initCocFromRoute() {
  cocFilters.value.drive_id = typeof route.query.drive_id === 'string' ? route.query.drive_id : ''
  cocFilters.value.drive_sn = typeof route.query.drive_sn === 'string' ? route.query.drive_sn : ''
  cocFilters.value.project_id = typeof route.query.project_id === 'string' ? route.query.project_id : ''
  if (route.query.coc === '1' && (cocFilters.value.drive_id || cocFilters.value.drive_sn || cocFilters.value.project_id)) {
    loadChainOfCustody()
  }
}

function exportCsv() {
  const rows = logs.value.map((entry) => ({
    timestamp: entry.timestamp || '',
    user: entry.user || '',
    action: entry.action || '',
    job_id: entry.job_id || '',
    client_ip: entry.client_ip || '',
    details: JSON.stringify(entry.details || {}),
  }))

  const header = Object.keys(rows[0] || { timestamp: '', user: '', action: '', job_id: '', client_ip: '', details: '' })
  const lines = [
    header.join(','),
    ...rows.map((row) => header.map((key) => `"${String(row[key]).replace(/"/g, '""')}"`).join(',')),
  ]

  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
  anchor.download = `${settingsStore.auditExportFilename}-${timestamp}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}

onMounted(() => {
  loadAudit()
  loadDriveOptions()
  initCocFromRoute()
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('audit.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadAudit">{{ t('common.actions.refresh') }}</button>
        <button class="btn btn-primary" @click="exportCsv">{{ t('audit.exportCsv') }}</button>
      </div>
    </header>

    <div class="filters">
      <input v-model="filters.user" type="text" :placeholder="t('audit.userFilter')" :aria-label="t('audit.userFilter')" />
      <input v-model="filters.action" type="text" :placeholder="t('audit.actionFilter')" :aria-label="t('audit.actionFilter')" />
      <input v-model="filters.since" type="datetime-local" :aria-label="t('audit.dateFrom')" />
      <input v-model="filters.until" type="datetime-local" :aria-label="t('audit.dateTo')" />
      <button class="btn" @click="loadAudit">{{ t('audit.applyFilters') }}</button>
    </div>

    <section class="coc-section">
      <header class="header-row">
        <h2>{{ t('audit.chainTitle') }}</h2>
        <div class="actions">
          <button class="btn" :disabled="!cocReport" @click="printCocReport">{{ t('audit.printCoc') }}</button>
          <button class="btn btn-primary" :disabled="!cocReport" @click="saveCocReport">{{ t('audit.saveCoc') }}</button>
        </div>
      </header>

      <div class="filters">
        <select v-model="cocFilters.drive_id" :aria-label="t('audit.driveIdFilter')">
          <option value="">{{ t('audit.anyDrive') }}</option>
          <option v-for="drive in driveOptions" :key="drive.id" :value="drive.id">{{ drive.label }}</option>
        </select>
        <input v-model="cocFilters.drive_sn" type="text" :placeholder="t('audit.driveSnFilter')" :aria-label="t('audit.driveSnFilter')" />
        <select v-model="cocFilters.project_id" :aria-label="t('audit.projectFilter')">
          <option value="">{{ t('audit.anyProject') }}</option>
          <option v-for="projectId in projectOptions" :key="projectId" :value="projectId">{{ projectId }}</option>
        </select>
        <button class="btn" @click="loadChainOfCustody">{{ t('audit.loadCoc') }}</button>
      </div>

      <p v-if="cocLoading" class="muted">{{ t('common.labels.loading') }}</p>
      <p v-if="cocError" class="error-banner">{{ cocError }}</p>
      <p v-if="cocStatusMessage" class="ok-banner">{{ cocStatusMessage }}</p>

      <div v-if="cocReport" class="coc-results">
        <p class="muted">{{ t('audit.selectorMode') }}: {{ cocReport.selector_mode }}</p>

        <article v-for="report in cocReport.reports" :key="report.drive_id" class="coc-card">
          <header class="header-row">
            <h3>{{ t('audit.cocDriveHeader', { driveId: report.drive_id, driveSn: report.drive_sn }) }}</h3>
            <StatusBadge :status="report.custody_complete ? 'COMPLETED' : 'PENDING'" :label="report.custody_complete ? t('audit.custodyComplete') : t('audit.custodyIncomplete')" />
          </header>
          <p class="muted">
            {{ t('dashboard.project') }}: {{ report.project_id || '-' }}
            | {{ t('audit.deliveryTime') }}: {{ asLocalDate(report.delivery_time) }}
          </p>

          <div class="coc-actions">
            <button class="btn" @click="prepareHandoff(report)">{{ t('audit.prefillHandoff') }}</button>
          </div>

          <div class="manifest-grid" v-if="report.manifest_summary.length">
            <div v-for="manifest in report.manifest_summary" :key="manifest.job_id" class="manifest-item">
              <strong>{{ t('jobs.jobId') }} {{ manifest.job_id }}</strong>
              <span>{{ t('common.labels.count') }}: {{ manifest.total_files }}</span>
              <span>{{ t('common.labels.size') }}: {{ manifest.total_bytes }}</span>
              <span>{{ t('audit.manifestCount') }}: {{ manifest.manifest_count }}</span>
            </div>
          </div>

          <pre>{{ JSON.stringify(report.chain_of_custody_events, null, 2) }}</pre>
        </article>
      </div>

      <div class="handoff-form">
        <h3>{{ t('audit.handoffTitle') }}</h3>
        <div class="handoff-grid">
          <select v-model="handoffForm.drive_id" :aria-label="t('audit.driveIdFilter')">
            <option value="">{{ t('audit.selectDrive') }}</option>
            <option v-for="drive in driveOptions" :key="`handoff-${drive.id}`" :value="drive.id">{{ drive.label }}</option>
          </select>
          <select v-model="handoffForm.project_id" :aria-label="t('audit.projectFilter')">
            <option value="">{{ t('audit.selectProject') }}</option>
            <option v-for="projectId in projectOptions" :key="`handoff-project-${projectId}`" :value="projectId">{{ projectId }}</option>
          </select>
          <input v-model="handoffForm.possessor" type="text" :placeholder="t('audit.possessor')" :aria-label="t('audit.possessor')" />
          <input v-model="handoffForm.delivery_time" type="datetime-local" :placeholder="t('audit.deliveryTime')" :aria-label="t('audit.deliveryTime')" />
          <input v-model="handoffForm.received_by" type="text" :placeholder="t('audit.receivedBy')" :aria-label="t('audit.receivedBy')" />
          <input v-model="handoffForm.receipt_ref" type="text" :placeholder="t('audit.receiptRef')" :aria-label="t('audit.receiptRef')" />
        </div>
        <textarea v-model="handoffForm.notes" rows="3" :placeholder="t('audit.notes')" :aria-label="t('audit.notes')"></textarea>
        <button class="btn btn-primary" :disabled="handoffSaving" @click="submitHandoff">{{ t('audit.confirmHandoff') }}</button>
      </div>
    </section>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <DataTable :columns="columns" :rows="paged" :empty-text="t('audit.empty')">
      <template #cell-timestamp="{ row }">{{ asLocalDate(row.timestamp) }}</template>
      <template #cell-action="{ row }"><StatusBadge :status="row.action" /></template>
      <template #cell-details="{ row }">
        <div class="details-cell">
          <button class="btn" @click="toggleDetails(row.id)">
            {{ expanded.has(row.id) ? t('audit.hideDetails') : t('audit.showDetails') }}
          </button>
          <pre v-if="expanded.has(row.id)">{{ JSON.stringify(row.details || {}, null, 2) }}</pre>
        </div>
      </template>
    </DataTable>

    <Pagination v-model:page="page" :page-size="pageSize" :total="logs.length" />

    <!-- Handoff Warning Modal -->
    <div v-if="showHandoffWarning" class="modal-overlay">
      <div class="modal-dialog">
        <div class="modal-header">
          <h2>{{ t('audit.handoffWarning') }}</h2>
          <button class="modal-close" @click="cancelHandoffSubmission" :aria-label="t('common.actions.close')">×</button>
        </div>
        <div class="modal-body">
          <p>{{ t('audit.handoffWarningMessage') }}</p>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="cancelHandoffSubmission">{{ t('audit.handoffWarningCancel') }}</button>
          <button class="btn btn-danger" :disabled="handoffSaving" @click="confirmHandoffSubmission">{{ t('audit.handoffWarningConfirm') }}</button>
        </div>
      </div>
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

input {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.details-cell {
  display: grid;
  gap: var(--space-xs);
}

pre {
  max-width: 420px;
  max-height: 180px;
  overflow: auto;
  margin: 0;
  background: var(--color-bg-input);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-xs);
  font-size: var(--font-size-xs);
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

.ok-banner {
  color: var(--color-ok-banner-text, #14532d);
  background: color-mix(in srgb, var(--color-success) 14%, var(--color-bg-secondary));
  border: 1px solid color-mix(in srgb, var(--color-success) 45%, var(--color-border));
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}

.coc-section,
.coc-card,
.handoff-form {
  display: grid;
  gap: var(--space-sm);
}

.coc-card,
.handoff-form {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
}

.coc-results,
.handoff-grid,
.manifest-grid,
.coc-actions {
  display: grid;
  gap: var(--space-sm);
}

.handoff-grid {
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.manifest-item {
  display: grid;
  gap: 2px;
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  padding: var(--space-xs);
}

textarea {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

/* Modal Styles */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-dialog {
  background: var(--color-bg-primary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  max-width: 500px;
  width: 90%;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-md);
  border-bottom: 1px solid var(--color-border);
}

.modal-header h2 {
  margin: 0;
  font-size: 1.25rem;
}

.modal-close {
  background: none;
  border: none;
  font-size: 1.5rem;
  cursor: pointer;
  color: var(--color-text-secondary);
  padding: 0;
  line-height: 1;
}

.modal-close:hover {
  color: var(--color-text-primary);
}

.modal-body {
  padding: var(--space-md);
}

.modal-body p {
  margin: 0;
  line-height: 1.6;
  color: var(--color-text-primary);
}

.modal-footer {
  display: flex;
  gap: var(--space-sm);
  padding: var(--space-md);
  border-top: 1px solid var(--color-border);
  justify-content: flex-end;
}

.btn-danger {
  background: var(--color-error, #dc2626);
  color: white;
  border: 1px solid var(--color-error, #dc2626);
}

.btn-danger:hover:not(:disabled) {
  background: var(--color-error-hover, #b91c1c);
  border-color: var(--color-error-hover, #b91c1c);
}

.btn-secondary {
  background: var(--color-bg-secondary);
  color: var(--color-text-primary);
  border: 1px solid var(--color-border);
}

.btn-secondary:hover:not(:disabled) {
  background: color-mix(in srgb, var(--color-bg-secondary) 80%, var(--color-text-primary));
}
</style>
