<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getSystemHealth, getVersion } from '@/api/introspection.js'

const { t } = useI18n()

const version = ref('—')
const buildTimestamp = ref('')
const dbConnected = ref(null)
const activeJobs = ref(null)

let pollInterval = null
let stopped = false

function formatBuildTimestamp(value) {
  if (!value) return ''

  const timestamp = new Date(value)
  if (Number.isNaN(timestamp.getTime())) return value

  return `${timestamp.toISOString().slice(0, 16).replace('T', ' ')} UTC`
}

async function fetchVersion() {
  try {
    const versionData = await getVersion()
    if (!stopped) {
      version.value = versionData.version || '—'
      buildTimestamp.value = formatBuildTimestamp(versionData.build_timestamp)
    }
  } catch (err) {
    console.debug('Failed to fetch version:', err.message || err)
  }
}

async function fetchHealth() {
  try {
    const data = await getSystemHealth()
    if (stopped) return
    dbConnected.value = data.database === 'connected' || data.database === true
    activeJobs.value = data.active_jobs ?? null
  } catch {
    if (stopped) return
    dbConnected.value = false
    activeJobs.value = null
  }
}

function schedulePoll() {
  pollInterval = setTimeout(async () => {
    await fetchHealth()
    if (!stopped) schedulePoll()
  }, 30000)
}

onMounted(() => {
  stopped = false
  fetchVersion()
  fetchHealth()
  schedulePoll()
})

onUnmounted(() => {
  stopped = true
  if (pollInterval) clearTimeout(pollInterval)
})
</script>

<template>
  <footer class="app-footer">
    <span class="footer-version">{{ t('app.name') }} {{ version }}</span>
    <template v-if="buildTimestamp">
      <span class="footer-separator">│</span>
      <span class="footer-build">{{ t('app.buildDate') }}: {{ buildTimestamp }}</span>
    </template>
    <span class="footer-separator">│</span>
    <span class="footer-db">
      {{ t('common.labels.db') }}:
      <span
        class="db-indicator"
        :class="dbConnected === true ? 'db-ok' : dbConnected === false ? 'db-err' : ''"
      >●</span>
      {{ dbConnected === true ? t('system.dbConnected') : dbConnected === false ? t('system.dbDisconnected') : t('common.labels.loading') }}
    </span>
    <span class="footer-separator">│</span>
    <span class="footer-jobs">
      {{ t('jobs.activeJobs') }}: {{ activeJobs !== null ? activeJobs : t('common.labels.loading') }}
    </span>
  </footer>
</template>

<style scoped>
.app-footer {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-sm) var(--space-md);
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  background: var(--color-bg-footer);
  border-top: 1px solid var(--color-border);
}

.footer-separator {
  opacity: 0.4;
}

.db-indicator {
  font-size: var(--font-size-xs);
}

.db-ok {
  color: var(--color-success);
}

.db-err {
  color: var(--color-danger);
}
</style>
