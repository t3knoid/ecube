<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { getSystemHealth, getVersion } from '@/api/introspection.js'

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
