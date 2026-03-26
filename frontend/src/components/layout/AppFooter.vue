<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { getSystemHealth, getVersion } from '@/api/introspection.js'

const { t } = useI18n()

const version = ref('—')
const dbConnected = ref(null)
const activeJobs = ref(null)

let pollInterval = null
let stopped = false

async function fetchVersion() {
  try {
    const resp = await getVersion()
    if (!stopped) version.value = resp.data.version || '—'
  } catch (err) {
    console.debug('Failed to fetch version:', err.message || err)
  }
}

async function fetchHealth() {
  try {
    const resp = await getSystemHealth()
    if (stopped) return
    const data = resp.data
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
  font-size: 0.7rem;
}

.db-ok {
  color: var(--color-success);
}

.db-err {
  color: var(--color-danger);
}
</style>
