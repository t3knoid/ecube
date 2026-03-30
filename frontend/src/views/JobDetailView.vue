<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { getJob, getJobFiles, startJob, verifyJob, generateManifest } from '@/api/jobs.js'
import { getJobDebug } from '@/api/introspection.js'
import { getFileHashes, compareFiles } from '@/api/files.js'
import { usePolling } from '@/composables/usePolling.js'
import DataTable from '@/components/common/DataTable.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ProgressBar from '@/components/common/ProgressBar.vue'
import { useStatusLabels } from '@/composables/useStatusLabels.js'

const route = useRoute()
const { t } = useI18n()
const authStore = useAuthStore()

const jobId = computed(() => Number(route.params.id))

const job = ref(null)
const debug = ref({ files: [] })
const loading = ref(false)
const acting = ref(false)
const error = ref('')

const selectedFileId = ref(null)
const fileHashes = ref(null)
const compareA = ref(null)
const compareB = ref(null)
const compareResult = ref(null)

const canOperate = computed(() => authStore.hasAnyRole(['admin', 'manager', 'processor']))
const canInspectHashes = computed(() => authStore.hasAnyRole(['admin', 'auditor']))
const canViewIntrospectionDebug = computed(() => authStore.hasAnyRole(['admin', 'auditor']))

const fileColumns = computed(() => [
  { key: 'id', label: t('common.labels.id'), align: 'right' },
  { key: 'relative_path', label: t('jobs.path') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'checksum', label: t('jobs.checksum') },
  { key: 'actions', label: t('common.actions.edit'), align: 'center' },
])

function progressPercent() {
  if (!job.value || !job.value.total_bytes) return 0
  return Math.min(100, Math.round((job.value.copied_bytes / job.value.total_bytes) * 100))
}

async function loadDebug() {
  if (!canViewIntrospectionDebug.value) {
    try {
      const response = await getJobFiles(jobId.value)
      debug.value = { files: Array.isArray(response?.files) ? response.files : [] }
    } catch {
      debug.value = { files: [] }
    }
    return
  }

  try {
    debug.value = await getJobDebug(jobId.value)
  } catch {
    try {
      const response = await getJobFiles(jobId.value)
      debug.value = { files: Array.isArray(response?.files) ? response.files : [] }
    } catch {
      debug.value = { files: [] }
    }
  }
}

const jobPoller = usePolling(
  async () => {
    const next = await getJob(jobId.value)
    job.value = next
    await loadDebug()
    return next
  },
  {
    intervalMs: 3000,
    isTerminal: (next) => {
      const status = String(next?.status || '').toUpperCase()
      return status === 'COMPLETED' || status === 'FAILED'
    },
  },
)

async function refreshAll() {
  loading.value = true
  error.value = ''
  try {
    await jobPoller.tick()
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
}

async function runAction(action) {
  if (!job.value) return
  acting.value = true
  error.value = ''
  try {
    if (action === 'start') {
      job.value = await startJob(job.value.id, { thread_count: job.value.thread_count || 4 })
    } else if (action === 'verify') {
      job.value = await verifyJob(job.value.id)
    } else {
      job.value = await generateManifest(job.value.id)
    }
    await refreshAll()
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    acting.value = false
  }
}

async function loadHashes(fileId) {
  if (!canInspectHashes.value) return
  selectedFileId.value = fileId
  fileHashes.value = null
  try {
    fileHashes.value = await getFileHashes(fileId)
  } catch {
    error.value = t('common.errors.requestConflict')
  }
}

async function runCompare() {
  if (!compareA.value || !compareB.value) return
  compareResult.value = null
  try {
    compareResult.value = await compareFiles({ file_id_a: Number(compareA.value), file_id_b: Number(compareB.value) })
  } catch {
    error.value = t('common.errors.requestConflict')
  }
}

onMounted(async () => {
  await refreshAll()
  jobPoller.start()
})

onUnmounted(() => {
  jobPoller.stop()
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('jobs.detail') }} #{{ jobId }}</h1>
      <button class="btn" @click="refreshAll">{{ t('common.actions.refresh') }}</button>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <article v-if="job" class="panel">
      <div class="job-header">
        <StatusBadge :status="job.status" />
        <span>{{ t('dashboard.project') }}: {{ job.project_id }}</span>
        <span>{{ t('jobs.evidence') }}: {{ job.evidence_number }}</span>
      </div>

      <ProgressBar :value="job.copied_bytes || 0" :total="job.total_bytes || 0" />
      <p class="muted">{{ progressPercent() }}% ({{ job.copied_bytes }} / {{ job.total_bytes }} bytes)</p>

      <div class="actions">
        <button class="btn" :disabled="!canOperate || acting" @click="runAction('start')">{{ t('jobs.start') }}</button>
        <button class="btn" :disabled="!canOperate || acting" @click="runAction('verify')">{{ t('jobs.verify') }}</button>
        <button class="btn" :disabled="!canOperate || acting" @click="runAction('manifest')">{{ t('jobs.manifest') }}</button>
      </div>
    </article>

    <article class="panel">
      <h2>{{ t('jobs.files') }}</h2>
      <DataTable :columns="fileColumns" :rows="debug.files || []" row-key="id" :empty-text="t('jobs.noFiles')">
        <template #cell-status="{ row }">
          <StatusBadge :status="row.status" />
        </template>
        <template #cell-checksum="{ row }">
          <span class="mono">{{ row.checksum || '-' }}</span>
        </template>
        <template #cell-actions="{ row }">
          <button class="btn" :disabled="!canInspectHashes" @click="loadHashes(row.id)">{{ t('jobs.hashes') }}</button>
        </template>
      </DataTable>
    </article>

    <div class="split-grid">
      <article class="panel">
        <h2>{{ t('jobs.hashViewer') }}</h2>
        <p class="muted" v-if="!selectedFileId">{{ t('jobs.hashViewerEmpty') }}</p>
        <div v-else-if="fileHashes" class="hash-grid">
          <span>{{ t('common.labels.id') }}</span><strong>{{ fileHashes.file_id }}</strong>
          <span>{{ t('jobs.md5') }}</span><strong class="mono">{{ fileHashes.md5 || '-' }}</strong>
          <span>{{ t('jobs.sha256') }}</span><strong class="mono">{{ fileHashes.sha256 || '-' }}</strong>
          <span>{{ t('common.labels.size') }}</span><strong>{{ fileHashes.size_bytes || '-' }}</strong>
        </div>
      </article>

      <article class="panel">
        <h2>{{ t('jobs.compareTitle') }}</h2>
        <div class="compare-form">
          <label for="compare-file-a">{{ t('jobs.fileA') }}</label>
          <select id="compare-file-a" v-model="compareA">
            <option :value="null">-</option>
            <option v-for="file in debug.files || []" :key="`a-${file.id}`" :value="file.id">
              #{{ file.id }} {{ file.relative_path }}
            </option>
          </select>
          <label for="compare-file-b">{{ t('jobs.fileB') }}</label>
          <select id="compare-file-b" v-model="compareB">
            <option :value="null">-</option>
            <option v-for="file in debug.files || []" :key="`b-${file.id}`" :value="file.id">
              #{{ file.id }} {{ file.relative_path }}
            </option>
          </select>
          <button class="btn" :disabled="!compareA || !compareB" @click="runCompare">
            {{ t('jobs.compare') }}
          </button>
        </div>

        <div v-if="compareResult" class="hash-grid">
          <span>{{ t('jobs.compareMatch') }}</span><StatusBadge :status="compareResult.match" />
          <span>{{ t('jobs.hashMatch') }}</span><StatusBadge :status="compareResult.hash_match" />
          <span>{{ t('jobs.sizeMatch') }}</span><StatusBadge :status="compareResult.size_match" />
          <span>{{ t('jobs.pathMatch') }}</span><StatusBadge :status="compareResult.path_match" />
        </div>
      </article>
    </div>
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row,
.job-header,
.actions,
.split-grid {
  display: flex;
  gap: var(--space-sm);
}

.header-row {
  justify-content: space-between;
  align-items: center;
}

.panel {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
  display: grid;
  gap: var(--space-sm);
}

.job-header {
  flex-wrap: wrap;
  align-items: center;
}

select {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.split-grid {
  display: grid;
  gap: var(--space-md);
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
}

.compare-form,
.hash-grid {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: var(--space-xs) var(--space-sm);
  align-items: center;
}

.mono {
  font-family: ui-monospace, Menlo, Monaco, Consolas, monospace;
}

.muted {
  color: var(--color-text-secondary);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}
</style>
