<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getSystemHealth } from '@/api/introspection.js'
import { getDrives } from '@/api/drives.js'
import { listJobs } from '@/api/jobs.js'
import { usePolling } from '@/composables/usePolling.js'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'

const { t } = useI18n()

const health = ref({ status: 'unknown', database: 'unknown', active_jobs: 0 })
const drives = ref([])
const jobs = ref([])
const loading = ref(true)
const error = ref('')

const driveCounts = computed(() => {
  const counts = { EMPTY: 0, AVAILABLE: 0, IN_USE: 0 }
  for (const drive of drives.value) {
    const key = String(drive.current_state || '').toUpperCase()
    if (counts[key] !== undefined) counts[key] += 1
  }
  return counts
})

const activeJobs = computed(() =>
  jobs.value.filter((job) => ['PENDING', 'RUNNING', 'VERIFYING'].includes(String(job.status || '').toUpperCase())),
)

const healthColumns = computed(() => [
  { key: 'id', label: t('dashboard.jobId') },
  { key: 'project_id', label: t('dashboard.project') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'progress', label: t('dashboard.progress') },
])

function progressPercent(job) {
  if (!job || !job.total_bytes) return 0
  return Math.min(100, Math.round((job.copied_bytes / job.total_bytes) * 100))
}

async function refreshSnapshot() {
  const results = await Promise.allSettled([getDrives(), listJobs({ limit: 200 })])

  if (results[0].status === 'fulfilled') {
    drives.value = Array.isArray(results[0].value) ? results[0].value : []
  }

  if (results[1].status === 'fulfilled') {
    jobs.value = Array.isArray(results[1].value) ? results[1].value : []
  } else {
    // Backward compatibility for servers that do not yet expose GET /jobs.
    jobs.value = []
  }
}

const healthPoller = usePolling(async () => {
  const next = await getSystemHealth()
  health.value = next
  return next
}, { intervalMs: 10000 })

onMounted(async () => {
  loading.value = true
  error.value = ''
  try {
    await Promise.all([healthPoller.tick(), refreshSnapshot()])
    healthPoller.start()
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  healthPoller.stop()
})
</script>

<template>
  <section class="view-root">
    <header class="view-header">
      <h1>{{ t('nav.dashboard') }}</h1>
      <button class="btn" @click="refreshSnapshot">{{ t('common.actions.refresh') }}</button>
    </header>

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
        <div class="summary-row">
          <span>{{ t('jobs.activeJobs') }}</span>
          <strong>{{ health.active_jobs || 0 }}</strong>
        </div>
      </article>

      <article class="summary-card">
        <h2>{{ t('dashboard.driveSummary') }}</h2>
        <div class="summary-row"><span>{{ t('drives.states.empty') }}</span><strong>{{ driveCounts.EMPTY }}</strong></div>
        <div class="summary-row"><span>{{ t('drives.states.available') }}</span><strong>{{ driveCounts.AVAILABLE }}</strong></div>
        <div class="summary-row"><span>{{ t('drives.states.inUse') }}</span><strong>{{ driveCounts.IN_USE }}</strong></div>
      </article>
    </div>

    <article class="panel">
      <h2>{{ t('jobs.activeJobs') }}</h2>
      <DataTable :columns="healthColumns" :rows="activeJobs" row-key="id" :empty-text="t('dashboard.noActiveJobs')">
        <template #cell-status="{ row }">
          <StatusBadge :status="row.status" />
        </template>
        <template #cell-progress="{ row }">
          <div class="progress-wrap">
            <div class="progress-track">
              <div class="progress-bar" :style="{ width: `${progressPercent(row)}%` }" />
            </div>
            <span>{{ progressPercent(row) }}%</span>
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

.progress-wrap {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.progress-track {
  width: 120px;
  height: 8px;
  border-radius: 999px;
  background: var(--color-progress-track);
  overflow: hidden;
}

.progress-bar {
  height: 100%;
  background: var(--color-progress-bar);
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
</style>
