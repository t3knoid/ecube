<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { getSystemHealth } from '@/api/introspection.js'
import { getDrives } from '@/api/drives.js'
import { listJobs } from '@/api/jobs.js'
import { getMounts } from '@/api/mounts.js'
import { usePolling } from '@/composables/usePolling.js'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import { useAuthStore } from '@/stores/auth.js'
import { calculateJobProgress, isJobProgressActive } from '@/utils/jobProgress.js'
import { MOUNT_WORKFLOW_BUCKETS, buildMountWorkflowCounts } from '@/utils/mountWorkflow.js'
import { normalizeProjectId, normalizeProjectRecord } from '@/utils/projectId.js'

const { t } = useI18n()
const router = useRouter()
const authStore = useAuthStore()

const PASSWORD_WARNING_DISMISS_KEY = 'ecube-password-warning-dismissed-days'

const health = ref({ status: 'unknown', database: 'unknown', active_jobs: 0 })
const drives = ref([])
const mounts = ref([])
const jobs = ref([])
const loading = ref(true)
const error = ref('')
const dismissedPasswordWarning = ref(sessionStorage.getItem(PASSWORD_WARNING_DISMISS_KEY) || '')
const canViewOperationalSummary = computed(() => !authStore.hasRole('auditor'))

const showPasswordWarning = computed(() => {
  if (!Number.isInteger(authStore.passwordWarningDays)) return false
  return String(authStore.passwordWarningDays) !== dismissedPasswordWarning.value
})

function dismissPasswordWarning() {
  const value = Number.isInteger(authStore.passwordWarningDays) ? String(authStore.passwordWarningDays) : ''
  dismissedPasswordWarning.value = value
  sessionStorage.setItem(PASSWORD_WARNING_DISMISS_KEY, value)
}

const driveCounts = computed(() => {
  const counts = { DISCONNECTED: 0, DISABLED: 0, AVAILABLE: 0, IN_USE: 0 }
  for (const drive of drives.value) {
    const key = String(drive.current_state || '').toUpperCase()
    if (counts[key] !== undefined) counts[key] += 1
  }
  return counts
})

const mountCounts = computed(() => buildMountWorkflowCounts(mounts.value))

const activeJobs = computed(() =>
  jobs.value.filter((job) => ['PENDING', 'RUNNING', 'VERIFYING'].includes(String(job.status || '').toUpperCase())),
)

const healthColumns = computed(() => [
  { key: 'id', label: t('dashboard.jobId') },
  { key: 'project_id', label: t('dashboard.project') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'progress', label: t('dashboard.progress') },
])

const driveSummaryEntries = computed(() => [
  { key: 'DISCONNECTED', label: t('drives.states.disconnected'), count: driveCounts.value.DISCONNECTED },
  { key: 'DISABLED', label: t('drives.states.disabled'), count: driveCounts.value.DISABLED },
  { key: 'AVAILABLE', label: t('drives.states.available'), count: driveCounts.value.AVAILABLE },
  { key: 'IN_USE', label: t('drives.states.inUse'), count: driveCounts.value.IN_USE },
])

const mountSummaryEntries = computed(() => [
  { key: MOUNT_WORKFLOW_BUCKETS.UNASSIGNED, label: t('dashboard.mountUnassigned'), count: mountCounts.value.UNASSIGNED },
  { key: MOUNT_WORKFLOW_BUCKETS.ASSIGNED, label: t('dashboard.mountAssigned'), count: mountCounts.value.ASSIGNED },
  { key: MOUNT_WORKFLOW_BUCKETS.IN_PROGRESS, label: t('dashboard.mountInProgress'), count: mountCounts.value.IN_PROGRESS },
  { key: MOUNT_WORKFLOW_BUCKETS.COMPLETED, label: t('dashboard.mountCompleted'), count: mountCounts.value.COMPLETED },
  { key: MOUNT_WORKFLOW_BUCKETS.UNAVAILABLE, label: t('dashboard.mountUnavailable'), count: mountCounts.value.UNAVAILABLE },
])

function formatProjectId(value) {
  return normalizeProjectId(value) || '-'
}

function openJobDetail(jobId) {
  const normalizedJobId = Number(jobId)
  if (!Number.isInteger(normalizedJobId) || normalizedJobId < 1) return
  router.push({ name: 'job-detail', params: { id: normalizedJobId } })
}

function openDriveSummary(state) {
  router.push({ name: 'drives', query: { state } })
}

function openMountSummary(workflow) {
  router.push({ name: 'mounts', query: { workflow } })
}

function progressPercent(job) {
  return calculateJobProgress(job).percent
}

function progressLabel(job) {
  const metrics = calculateJobProgress(job)
  if (metrics.initializing) {
    return t('jobs.progressPreparingShort')
  }
  return `${metrics.percent}%`
}

function progressActive(job) {
  return isJobProgressActive(job)
}

async function refreshDashboard() {
  const warnings = []
  const results = await Promise.allSettled([
    getSystemHealth(),
    getDrives({ include_disconnected: true }),
    getMounts(),
    listJobs({ limit: 200 }),
  ])

  if (results[0].status === 'fulfilled') {
    health.value = results[0].value
  } else {
    warnings.push(t('common.errors.networkError'))
  }

  if (results[1].status === 'fulfilled') {
    drives.value = Array.isArray(results[1].value)
      ? results[1].value.map((item) => normalizeProjectRecord(item, ['current_project_id']))
      : []
  } else {
    warnings.push(t('dashboard.loadDrivesError'))
  }

  if (results[2].status === 'fulfilled') {
    mounts.value = Array.isArray(results[2].value)
      ? results[2].value.map((item) => normalizeProjectRecord(item, ['project_id']))
      : []
  } else {
    warnings.push(t('dashboard.loadMountsError'))
  }

  if (results[3].status === 'fulfilled') {
    jobs.value = Array.isArray(results[3].value)
      ? results[3].value.map((item) => normalizeProjectRecord(item, ['project_id']))
      : []
  } else {
    // Backward compatibility for servers that do not yet expose GET /jobs.
    jobs.value = []
  }

  error.value = warnings.join(' ')
}

const dashboardPoller = usePolling(refreshDashboard, { intervalMs: 10000, immediate: false })

function requestDashboardRefresh() {
  return dashboardPoller.tick()
}

onMounted(async () => {
  loading.value = true
  error.value = ''
  try {
    await requestDashboardRefresh()
    dashboardPoller.start()
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  dashboardPoller.stop()
})
</script>

<template>
  <section class="view-root">
    <header class="view-header">
      <h1>{{ t('nav.dashboard') }}</h1>
      <button class="btn" @click="requestDashboardRefresh">{{ t('common.actions.refresh') }}</button>
    </header>

    <div v-if="showPasswordWarning" class="warning-banner">
      <p>{{ t('dashboard.passwordExpiryWarning', { days: authStore.passwordWarningDays }) }}</p>
      <button class="btn" type="button" @click="dismissPasswordWarning">{{ t('common.actions.dismiss') }}</button>
    </div>

    <p v-if="error" class="error-banner">{{ error }}</p>
    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>

    <div class="card-grid">
      <article class="summary-card">
        <h2>{{ t('dashboard.systemHealth') }}</h2>
        <div class="summary-row">
          <span>{{ t('common.labels.status') }}</span>
          <StatusBadge :status="health.status" />
        </div>
        <div class="summary-row">
          <span>{{ t('common.labels.db') }}</span>
          <StatusBadge :status="health.database" />
        </div>
        <div v-if="canViewOperationalSummary" class="summary-row">
          <span>{{ t('jobs.activeJobs') }}</span>
          <strong>{{ health.active_jobs || 0 }}</strong>
        </div>
      </article>

      <article v-if="canViewOperationalSummary" class="summary-card">
        <h2>{{ t('dashboard.driveSummary') }}</h2>
        <button
          v-for="entry in driveSummaryEntries"
          :key="entry.key"
          class="summary-link"
          type="button"
          @click="openDriveSummary(entry.key)"
        >
          <span>{{ entry.label }}</span>
          <strong>{{ entry.count }}</strong>
        </button>
      </article>

      <article v-if="canViewOperationalSummary" class="summary-card">
        <h2>{{ t('dashboard.mountsSummary') }}</h2>
        <button
          v-for="entry in mountSummaryEntries"
          :key="entry.key"
          class="summary-link"
          type="button"
          @click="openMountSummary(entry.key)"
        >
          <span>{{ entry.label }}</span>
          <strong>{{ entry.count }}</strong>
        </button>
      </article>
    </div>

    <article v-if="canViewOperationalSummary" class="panel">
      <h2>{{ t('jobs.activeJobs') }}</h2>
      <DataTable :columns="healthColumns" :rows="activeJobs" row-key="id" :empty-text="t('dashboard.noActiveJobs')">
        <template #cell-id="{ row }">
          <button
            v-if="Number.isInteger(Number(row.id)) && Number(row.id) > 0"
            class="cell-link"
            type="button"
            @click="openJobDetail(row.id)"
          >
            {{ row.id }}
          </button>
          <span v-else class="job-id-text">{{ row.id ?? '-' }}</span>
        </template>
        <template #cell-project_id="{ row }">{{ formatProjectId(row.project_id) }}</template>
        <template #cell-status="{ row }">
          <StatusBadge :status="row.status" />
        </template>
        <template #cell-progress="{ row }">
          <div class="dashboard-progress-cell">
            <ProgressBar
              class="dashboard-progress-bar"
              :value="progressPercent(row)"
              :total="100"
              :label="progressLabel(row)"
              :active="progressActive(row)"
            />
            <span class="dashboard-progress-mobile-label">{{ progressLabel(row) }}</span>
          </div>
        </template>
      </DataTable>
    </article>
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-lg);
}

.warning-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-sm) var(--space-md);
  border: 1px solid var(--color-alert-warning-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-alert-warning-bg);
  color: var(--color-alert-warning-text);
}

.view-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: var(--space-md);
}

.summary-card,
.panel {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  box-shadow: var(--shadow-sm);
  padding: var(--space-md);
}

.summary-card h2,
.panel h2 {
  font-size: var(--font-size-lg);
  margin-bottom: var(--space-sm);
}

.summary-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-xs) 0;
}

.summary-link {
  display: flex;
  width: 100%;
  justify-content: space-between;
  align-items: center;
  padding: var(--space-xs) 0;
  border: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.summary-link:hover,
.summary-link:focus-visible {
  text-decoration: underline;
  text-decoration-thickness: 2px;
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

.dashboard-progress-cell {
  display: flex;
  align-items: center;
}

.dashboard-progress-mobile-label {
  display: none;
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  white-space: nowrap;
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

@media (max-width: 768px) {
  .view-root {
    gap: var(--space-md);
  }

  .view-header {
    gap: var(--space-sm);
  }

  .card-grid {
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  }

  .summary-card,
  .panel {
    padding: var(--space-sm);
  }

  .dashboard-progress-bar {
    display: none;
  }

  .dashboard-progress-mobile-label {
    display: inline;
  }
}
</style>
