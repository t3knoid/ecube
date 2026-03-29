<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import {
  getSetupStatus,
  getDatabaseProvisionStatus,
  getSystemInfo,
  testDatabaseConnection,
  provisionDatabase,
  initializeSetup,
} from '@/api/setup.js'

const router = useRouter()
const { t } = useI18n()
const authStore = useAuthStore()

const step = ref(1)
const busy = ref(false)
const error = ref('')
const complete = ref(false)
const provisionNote = ref('')

const db = ref({
  host: 'localhost',
  port: 5432,
  admin_username: 'ecube',
  admin_password: '',
  app_database: 'ecube',
  app_username: 'ecube',
  app_password: '',
})

const admin = ref({
  username: 'admin',
  password: '',
})

const connectionOk = ref(false)
const provisionOk = ref(false)
const provisionDetected = ref(false)
const inDocker = ref(false)

function extractApiMessage(err, fallback) {
  const data = err?.response?.data || {}

  if (typeof data.message === 'string' && data.message.trim()) {
    return data.message
  }

  if (typeof data.detail === 'string' && data.detail.trim()) {
    return data.detail
  }

  return fallback
}

function routeAfterSetupCheck() {
  if (authStore.isAuthenticated) {
    router.replace({ name: 'dashboard' })
    return
  }
  router.replace({ name: 'login' })
}

function step1Valid() {
  return !!db.value.host && !!db.value.port && !!db.value.admin_username && !!db.value.admin_password
}

function step2Valid() {
  return step1Valid() && !!db.value.app_database && !!db.value.app_username && !!db.value.app_password
}

function step3Valid() {
  return !!admin.value.username && !!admin.value.password
}

async function runConnectionTest() {
  if (!step1Valid()) return
  busy.value = true
  error.value = ''
  try {
    await testDatabaseConnection({
      host: db.value.host,
      port: Number(db.value.port),
      admin_username: db.value.admin_username,
      admin_password: db.value.admin_password,
    })
    connectionOk.value = true
  } catch (err) {
    if (err?.response?.status === 401) {
      error.value = t('setup.alreadyInitialized')
      routeAfterSetupCheck()
      return
    }
    connectionOk.value = false
    error.value = extractApiMessage(err, t('common.errors.requestConflict'))
  } finally {
    busy.value = false
  }
}

async function runProvision() {
  if (!step2Valid() || provisionDetected.value) return
  busy.value = true
  error.value = ''
  provisionNote.value = ''
  try {
    await provisionDatabase({
      host: db.value.host,
      port: Number(db.value.port),
      admin_username: db.value.admin_username,
      admin_password: db.value.admin_password,
      app_database: db.value.app_database,
      app_username: db.value.app_username,
      app_password: db.value.app_password,
      force: false,
    })
    provisionOk.value = true
    provisionNote.value = t('setup.provisionOk')
  } catch (err) {
    const errorData = err?.response?.data || {}
    const detail = String(errorData.detail || errorData.message || '')
    const alreadyProvisioned = err?.response?.status === 409 && detail.toLowerCase().includes('already provisioned')

    if (alreadyProvisioned) {
      // Backend confirms schema/db already exist; allow setup flow to continue.
      provisionOk.value = true
      error.value = ''
      provisionNote.value = t('setup.provisionAlready')
    } else if (err?.response?.status === 401) {
      error.value = t('setup.alreadyInitialized')
      routeAfterSetupCheck()
    } else {
      provisionOk.value = false
      error.value = extractApiMessage(err, t('common.errors.requestConflict'))
    }
  } finally {
    busy.value = false
  }
}

async function runInitializeSetup() {
  if (!step3Valid()) return
  busy.value = true
  error.value = ''
  try {
    await initializeSetup({
      username: admin.value.username,
      password: admin.value.password,
    })
    complete.value = true
  } catch (err) {
    if (err?.response?.status === 401) {
      error.value = t('setup.alreadyInitialized')
      routeAfterSetupCheck()
      return
    }
    error.value = extractApiMessage(err, t('common.errors.requestConflict'))
  } finally {
    busy.value = false
  }
}

function goNext() {
  if (step.value < 4) step.value += 1
}

function goBack() {
  if (step.value > 1) step.value -= 1
}

function finish() {
  router.push({ name: 'login' })
}

onMounted(async () => {
  try {
    // Detect runtime environment first so db.host is correct before any
    // user interaction.
    try {
      const info = await getSystemInfo()
      inDocker.value = info?.in_docker ?? false
      if (info?.suggested_db_host) {
        db.value.host = info.suggested_db_host
      }
    } catch {
      // Non-fatal; keep localhost default.
    }

    const setupStatus = await getSetupStatus()
    if (setupStatus?.initialized === true) {
      error.value = t('setup.alreadyInitialized')
      routeAfterSetupCheck()
      return
    }

    try {
      const provisionStatus = await getDatabaseProvisionStatus()
      if (provisionStatus?.provisioned === true) {
        provisionDetected.value = true
        provisionOk.value = true
        provisionNote.value = t('setup.provisionAlready')
      }
    } catch {
      // Provision-status check is best effort; keep manual provision path available.
    }
  } catch {
    // If status check fails, keep wizard visible so user can retry once backend is ready.
  }
})
</script>

<template>
  <section class="setup-wizard">
    <div class="setup-card">
      <h1>{{ t('system.setup') }}</h1>
      <p class="muted">{{ t('setup.stepCounter', { step }) }}</p>
      <p v-if="error" class="error-banner">{{ error }}</p>

      <div v-if="step === 1" class="step-grid">
        <h2>{{ t('setup.testConnection') }}</h2>
        <label>{{ t('setup.dbHost') }}</label>
        <input v-model="db.host" type="text" />
        <p v-if="inDocker" class="info-hint">{{ t('setup.dockerHostHint') }}</p>
        <label>{{ t('setup.dbPort') }}</label>
        <input v-model.number="db.port" type="number" min="1" max="65535" />
        <label>{{ t('setup.dbAdminUser') }}</label>
        <input v-model="db.admin_username" type="text" />
        <label>{{ t('setup.dbAdminPass') }}</label>
        <input v-model="db.admin_password" type="password" autocomplete="new-password" />
        <button class="btn" :disabled="busy || !step1Valid()" @click="runConnectionTest">
          {{ t('setup.testConnection') }}
        </button>
        <p v-if="connectionOk" class="ok-text">{{ t('setup.connectionOk') }}</p>
      </div>

      <div v-else-if="step === 2" class="step-grid">
        <h2>{{ t('setup.provisionDb') }}</h2>
        <label>{{ t('setup.appDbName') }}</label>
        <input v-model="db.app_database" type="text" />
        <label>{{ t('setup.appDbUser') }}</label>
        <input v-model="db.app_username" type="text" />
        <label>{{ t('setup.appDbPass') }}</label>
        <input v-model="db.app_password" type="password" autocomplete="new-password" />
        <button class="btn" :disabled="busy || !step2Valid() || provisionDetected" @click="runProvision">
          {{ t('setup.provisionDb') }}
        </button>
        <p v-if="provisionOk" class="ok-text">{{ provisionNote || t('setup.provisionOk') }}</p>
      </div>

      <div v-else-if="step === 3" class="step-grid">
        <h2>{{ t('setup.createAdmin') }}</h2>
        <label>{{ t('auth.username') }}</label>
        <input v-model="admin.username" type="text" />
        <label>{{ t('auth.password') }}</label>
        <input v-model="admin.password" type="password" autocomplete="new-password" />
        <button class="btn" :disabled="busy || !step3Valid() || complete" @click="runInitializeSetup">
          {{ t('setup.createAdmin') }}
        </button>
        <p v-if="complete" class="ok-text">{{ t('setup.adminCreated') }}</p>
      </div>

      <div v-else class="step-grid">
        <h2>{{ t('setup.completeTitle') }}</h2>
        <p class="ok-text" v-if="complete">{{ t('setup.completeBody') }}</p>
        <button class="btn btn-primary" :disabled="!complete" @click="finish">{{ t('setup.goToLogin') }}</button>
      </div>

      <div class="actions">
        <button class="btn" :disabled="busy || step === 1" @click="goBack">{{ t('common.actions.back') }}</button>
        <button
          v-if="step < 4"
          class="btn btn-primary"
          :disabled="busy || (step === 1 && !connectionOk) || (step === 2 && !provisionOk) || (step === 3 && !complete)"
          @click="goNext"
        >
          {{ t('common.actions.next') }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.setup-wizard {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-lg);
}

.setup-card {
  width: min(720px, 100%);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  box-shadow: var(--shadow-md);
  padding: var(--space-xl);
  display: grid;
  gap: var(--space-md);
}

.step-grid {
  display: grid;
  gap: var(--space-xs);
}

input {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.actions {
  display: flex;
  justify-content: space-between;
  gap: var(--space-sm);
}

.muted {
  color: var(--color-text-secondary);
}

.ok-text {
  color: var(--color-success);
  font-weight: var(--font-weight-medium);
}

.info-hint {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  border-left: 3px solid var(--color-border-focus);
  padding-left: var(--space-sm);
  margin: 0;
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}
</style>
