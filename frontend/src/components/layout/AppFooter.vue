<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getSystemHealth, getVersion } from '@/api/introspection.js'

const version = ref('—')
const dbConnected = ref(null)
const activeJobs = ref(null)

let pollInterval = null

async function fetchVersion() {
  try {
    const resp = await getVersion()
    version.value = resp.data.version || '—'
  } catch {
    // Version endpoint is best-effort; leave default
  }
}

async function fetchHealth() {
  try {
    const resp = await getSystemHealth()
    const data = resp.data
    dbConnected.value = data.database === 'connected' || data.database === true
    activeJobs.value = data.active_jobs ?? null
  } catch {
    dbConnected.value = false
    activeJobs.value = null
  }
}

function schedulePoll() {
  pollInterval = setTimeout(async () => {
    await fetchHealth()
    schedulePoll()
  }, 30000)
}

onMounted(() => {
  fetchVersion()
  fetchHealth()
  schedulePoll()
})

onUnmounted(() => {
  if (pollInterval) clearTimeout(pollInterval)
})
</script>

<template>
  <footer class="app-footer">
    <span class="footer-version">ECUBE {{ version }}</span>
    <span class="footer-separator">│</span>
    <span class="footer-db">
      DB:
      <span
        class="db-indicator"
        :class="dbConnected === true ? 'db-ok' : dbConnected === false ? 'db-err' : ''"
      >●</span>
      {{ dbConnected === true ? 'Connected' : dbConnected === false ? 'Disconnected' : '…' }}
    </span>
    <span class="footer-separator">│</span>
    <span class="footer-jobs">
      Active Jobs: {{ activeJobs !== null ? activeJobs : '…' }}
    </span>
  </footer>
</template>

<style scoped>
.app-footer {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  font-size: 0.8rem;
  color: var(--color-text);
  background: var(--color-background-soft);
  border-top: 1px solid var(--color-border);
}

.footer-separator {
  opacity: 0.4;
}

.db-indicator {
  font-size: 0.7rem;
}

.db-ok {
  color: #16a34a;
}

.db-err {
  color: #dc2626;
}
</style>
