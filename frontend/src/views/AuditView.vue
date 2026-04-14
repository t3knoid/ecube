<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { confirmChainOfCustodyHandoff, getAudit, getChainOfCustody } from '@/api/audit.js'
import { getDrives } from '@/api/drives.js'
import { useRoleGuard } from '@/composables/useRoleGuard.js'
import { COC_HANDOFF_ROLES } from '@/constants/roles.js'
import { useSettingsStore } from '@/stores/settings.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

const { t } = useI18n()
const route = useRoute()
const settingsStore = useSettingsStore()
const { canAccess: canConfirmHandoff } = useRoleGuard(COC_HANDOFF_ROLES)

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
const expandedCocEvents = ref(new Set())
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
const allActiveDrives = ref([])

// Drives in IN_USE (active job) or AVAILABLE (after prepare-eject) with a project
// binding — the two states that need CoC and handoff selectors.  EMPTY drives that
// retain a stale project_id after removal/port-disable are intentionally excluded.
const initializedDrives = computed(() =>
  allActiveDrives.value.filter(
    (drive) =>
      (drive.current_state === 'IN_USE' || drive.current_state === 'AVAILABLE') &&
      typeof drive.current_project_id === 'string' &&
      drive.current_project_id.trim() !== ''
  )
)

function _toDriveOption(drive) {
  return { id: String(drive.id), label: `#${drive.id} (${drive.device_identifier || '-'})` }
}

function _toProjectList(drives) {
  return [...new Set(
    drives
      .map((drive) => drive.current_project_id)
      .filter((value) => typeof value === 'string' && value.trim())
      .map((value) => value.trim())
  )].sort((a, b) => a.localeCompare(b))
}

// CoC filter selectors — initialized drives, cross-filtered by selected project
const driveOptions = computed(() => {
  const project = cocFilters.value.project_id.trim()
  const source = project
    ? initializedDrives.value.filter((d) => d.current_project_id === project)
    : initializedDrives.value
  return source.map(_toDriveOption).sort((a, b) => Number(a.id) - Number(b.id))
})

const projectOptions = computed(() => _toProjectList(initializedDrives.value))

// Handoff form selectors — initialized drives, cross-filtered by selected project
const handoffDriveOptions = computed(() => {
  const project = handoffForm.value.project_id.trim()
  const source = project
    ? initializedDrives.value.filter((d) => d.current_project_id === project)
    : initializedDrives.value
  return source.map(_toDriveOption).sort((a, b) => Number(a.id) - Number(b.id))
})

const handoffProjectOptions = computed(() => _toProjectList(initializedDrives.value))

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

function toggleCocEvents(driveId) {
  if (expandedCocEvents.value.has(driveId)) {
    expandedCocEvents.value.delete(driveId)
  } else {
    expandedCocEvents.value.add(driveId)
  }
  expandedCocEvents.value = new Set(expandedCocEvents.value)
}

function asLocalDate(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleString()
}

function asUtcDate(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  }).format(parsed) + ' UTC'
}

function toIsoDate(value) {
  return value ? new Date(value).toISOString() : undefined
}

/**
 * Convert a datetime-local string to a UTC ISO-8601 timestamp.
 *
 * <input type="datetime-local"> yields a bare "YYYY-MM-DDTHH:mm" string with no
 * timezone.  If we pass that directly to `new Date()`, JavaScript interprets it
 * as local time and toISOString() silently shifts it by the browser's UTC offset
 * -- recording the wrong physical moment and triggering the backend UTC
 * validation check.
 *
 * The user is entering the handoff time in UTC (field labelled "UTC"), so we
 * treat the value as-is UTC by appending ":00Z" (or just "Z" when seconds are
 * already present) without any offset conversion.
 */
function localDateTimeAsUtcIso(value) {
  if (!value) return undefined
  // datetime-local format: "YYYY-MM-DDTHH:mm" (16 chars) or "YYYY-MM-DDTHH:mm:ss" (19 chars)
  const withSeconds = value.length === 16 ? value + ':00' : value
  return withSeconds + 'Z'
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
    allActiveDrives.value = drives.filter((drive) => drive.current_state !== 'ARCHIVED')
  } catch {
    allActiveDrives.value = []
    cocError.value = t('common.errors.networkError')
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

const hasCocSelector = computed(() => Object.keys(buildCocParams()).length > 0)

async function loadChainOfCustody() {
  if (!hasCocSelector.value) {
    cocError.value = t('audit.cocSelectRequired')
    return
  }
  cocLoading.value = true
  cocError.value = ''
  cocStatusMessage.value = ''
  const previousReport = cocReport.value
  const requestedParams = buildCocParams()
  cocReport.value = null
  expandedCocEvents.value = new Set()
  try {
    cocReport.value = await getChainOfCustody(requestedParams)
  } catch (err) {
    if (err?.response?.status === 410) {
      // Drive has been archived after handoff. Only restore the previous report
      // if it actually corresponds to the selectors that just produced the 410
      // — a stale report from a different drive or project must not be shown.
      const prevMatchesRequest =
        previousReport &&
        (() => {
          if (requestedParams.drive_id != null) {
            return previousReport.reports?.some((r) => r.drive_id === requestedParams.drive_id)
          }
          if (requestedParams.drive_sn != null) {
            return previousReport.reports?.some((r) => r.drive_sn === requestedParams.drive_sn)
          }
          if (requestedParams.project_id != null) {
            return previousReport.project_id === requestedParams.project_id
          }
          return false
        })()
      if (prevMatchesRequest) {
        cocReport.value = previousReport
      } else {
        cocStatusMessage.value = t('audit.driveArchived')
      }
    } else {
      const status = err?.response?.status
      if (status === 404) {
        cocError.value = t('common.errors.notFound')
      } else if (status === 409) {
        cocError.value = t('common.errors.requestConflict')
      } else if (status === 422) {
        cocError.value = t('common.errors.invalidRequest')
      } else if (status >= 500) {
        cocError.value = t('common.errors.serverError', { status })
      } else if (!status) {
        cocError.value = t('common.errors.networkError')
      } else {
        cocError.value = t('common.errors.serverErrorGeneric')
      }
    }
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

function submitHandoff() {
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
  cocStatusMessage.value = ''
  try {
    const handoffResult = await confirmChainOfCustodyHandoff({
      drive_id: driveId,
      project_id: handoffForm.value.project_id.trim() || undefined,
      possessor: handoffForm.value.possessor.trim(),
      delivery_time: localDateTimeAsUtcIso(handoffForm.value.delivery_time),
      received_by: handoffForm.value.received_by.trim() || undefined,
      receipt_ref: handoffForm.value.receipt_ref.trim() || undefined,
      notes: handoffForm.value.notes.trim() || undefined,
    })
    cocStatusMessage.value = t('audit.handoffSaved')
    // Patch the loaded report directly — the drive is now ARCHIVED so
    // reloading via the CoC endpoint returns 410 and would leave the report
    // showing custody_complete: false with no delivery_time.
    if (cocReport.value) {
      const match = cocReport.value.reports.find((r) => r.drive_id === driveId)
      if (match) {
        match.custody_complete = true
        match.delivery_time = handoffResult.delivery_time
        // Append the new COC_HANDOFF_CONFIRMED event so the compliance record
        // is fully visible without reloading (archived drives return 410).
        match.chain_of_custody_events = [
          ...match.chain_of_custody_events,
          {
            event_id: handoffResult.event_id,
            event_type: handoffResult.event_type,
            timestamp: handoffResult.recorded_at,
            actor: handoffResult.creator,
            action: 'Custody handoff confirmed',
            details: {
              drive_id: handoffResult.drive_id,
              drive_sn: match.drive_sn,
              project_id: handoffResult.project_id,
              creator: handoffResult.creator,
              possessor: handoffResult.possessor,
              delivery_time: handoffResult.delivery_time,
              received_by: handoffResult.received_by,
              receipt_ref: handoffResult.receipt_ref,
              notes: handoffResult.notes,
            },
          },
        ]
        // Trigger Vue reactivity by replacing the reports array reference.
        cocReport.value = { ...cocReport.value, reports: [...cocReport.value.reports] }
      }
    }
  } catch (err) {
    const status = err?.response?.status
    if (status === 409) {
      cocError.value = t('common.errors.requestConflict')
    } else if (status === 410) {
      cocError.value = t('audit.driveArchived')
    } else if (status === 422) {
      cocError.value = t('common.errors.invalidRequest')
    } else if (status >= 500) {
      cocError.value = t('common.errors.serverError', { status })
    } else if (!status) {
      cocError.value = t('common.errors.networkError')
    } else {
      cocError.value = t('common.errors.serverErrorGeneric')
    }
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
  setTimeout(() => URL.revokeObjectURL(url), 100)
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
  setTimeout(() => URL.revokeObjectURL(url), 100)
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
        <button class="btn" :disabled="!hasCocSelector" @click="loadChainOfCustody">{{ t('audit.loadCoc') }}</button>
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
            | {{ t('audit.deliveryTime') }}: {{ asUtcDate(report.delivery_time) }}
          </p>

          <div class="coc-actions">
            <button v-if="canConfirmHandoff" class="btn" @click="prepareHandoff(report)">{{ t('audit.prefillHandoff') }}</button>
          </div>

          <div class="manifest-grid" v-if="report.manifest_summary.length">
            <div v-for="manifest in report.manifest_summary" :key="manifest.job_id" class="manifest-item">
              <strong>{{ t('jobs.jobId') }} {{ manifest.job_id }}</strong>
              <span>{{ t('common.labels.count') }}: {{ manifest.total_files }}</span>
              <span>{{ t('common.labels.size') }}: {{ manifest.total_bytes }}</span>
              <span>{{ t('audit.manifestCount') }}: {{ manifest.manifest_count }}</span>
            </div>
          </div>

          <div class="coc-events">
            <p v-if="!report.chain_of_custody_events.length" class="muted">{{ t('audit.cocEventsEmpty') }}</p>
            <table v-else class="coc-events-table" :aria-label="t('audit.cocDriveHeader', { driveId: report.drive_id, driveSn: report.drive_sn })">
              <thead>
                <tr>
                  <th>{{ t('audit.action') }}</th>
                  <th>{{ t('common.labels.date') }}</th>
                  <th>{{ t('auth.username') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="event in report.chain_of_custody_events" :key="event.event_id">
                  <td>{{ event.action }}</td>
                  <td>{{ asUtcDate(event.timestamp) }}</td>
                  <td>{{ event.actor || '-' }}</td>
                </tr>
              </tbody>
            </table>
            <button class="btn" @click="toggleCocEvents(report.drive_id)">
              {{ expandedCocEvents.has(report.drive_id) ? t('audit.hideDetails') : t('audit.showDetails') }}
            </button>
            <pre v-if="expandedCocEvents.has(report.drive_id)">{{ JSON.stringify(report.chain_of_custody_events, null, 2) }}</pre>
          </div>
        </article>
      </div>

      <div v-if="canConfirmHandoff" class="handoff-form">
        <h3>{{ t('audit.handoffTitle') }}</h3>
        <div class="handoff-grid">
          <select v-model="handoffForm.drive_id" :aria-label="t('audit.driveIdFilter')">
            <option value="">{{ t('audit.selectDrive') }}</option>
            <option v-for="drive in handoffDriveOptions" :key="`handoff-${drive.id}`" :value="drive.id">{{ drive.label }}</option>
          </select>
          <select v-model="handoffForm.project_id" :aria-label="t('audit.projectFilter')">
            <option value="">{{ t('audit.selectProject') }}</option>
            <option v-for="projectId in handoffProjectOptions" :key="`handoff-project-${projectId}`" :value="projectId">{{ projectId }}</option>
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
    <ConfirmDialog
      v-model="showHandoffWarning"
      :title="t('audit.handoffWarning')"
      :message="t('audit.handoffWarningMessage')"
      :confirm-label="t('audit.handoffWarningConfirm')"
      :cancel-label="t('audit.handoffWarningCancel')"
      :dangerous="true"
      :busy="handoffSaving"
      @confirm="confirmHandoffSubmission"
      @cancel="cancelHandoffSubmission"
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
.coc-actions,
.coc-events {
  display: grid;
  gap: var(--space-sm);
}

.coc-events-table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--font-size-xs);
}

.coc-events-table th,
.coc-events-table td {
  text-align: left;
  padding: var(--space-xs) var(--space-sm);
  border-bottom: 1px solid var(--color-border);
}

.coc-events-table th {
  color: var(--color-text-secondary);
  font-weight: 600;
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
</style>
