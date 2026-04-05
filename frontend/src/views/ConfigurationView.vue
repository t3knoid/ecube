<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { getConfiguration, restartConfigurationService, updateConfiguration } from '@/api/configuration.js'
import { useToast } from '@/composables/useToast.js'

const { t } = useI18n()
const toast = useToast()

const loading = ref(false)
const saving = ref(false)
const restarting = ref(false)
const error = ref('')

const showRestartConfirm = ref(false)
const restartPending = ref(false)
const pendingRestartSettings = ref([])
const logFileEnabled = ref(false)
const originalLogFileEnabled = ref(false)

const DEFAULT_LOG_FILE_PATH = '/var/log/ecube/app.log'

const form = ref({
  log_level: 'INFO',
  log_format: 'text',
  log_file: '',
  log_file_max_bytes: 10485760,
  log_file_backup_count: 5,
  db_pool_size: 5,
  db_pool_max_overflow: 10,
  db_pool_recycle_seconds: -1,
})
const originalForm = ref({ ...form.value })

const fieldOrder = [
  'log_level',
  'log_format',
  'log_file',
  'log_file_max_bytes',
  'log_file_backup_count',
  'db_pool_size',
  'db_pool_max_overflow',
  'db_pool_recycle_seconds',
]

const levelOptions = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
const formatOptions = ['text', 'json']

const hasChanges = computed(() => Object.keys(buildPatchPayload()).length > 0)

const changedFieldLabels = computed(() => {
  return fieldOrder
    .filter((key) => pendingRestartSettings.value.includes(key))
    .map((key) => t(`configuration.fields.${key}.label`))
})

function normalizeForm(data) {
  const next = { ...form.value }
  const list = Array.isArray(data?.settings) ? data.settings : []
  let backendLogFileValue = ''
  for (const entry of list) {
    if (!entry?.key || !fieldOrder.includes(entry.key)) continue
    const key = entry.key
    let value = entry.value
    if (key === 'log_file') {
      value = value || ''
      backendLogFileValue = String(value)
    }
    if (typeof form.value[key] === 'number' && value != null) {
      value = Number(value)
    }
    next[key] = value
  }

  const hasBackendLogFile = backendLogFileValue.trim().length > 0
  logFileEnabled.value = hasBackendLogFile
  originalLogFileEnabled.value = hasBackendLogFile
  next.log_file = hasBackendLogFile ? backendLogFileValue : DEFAULT_LOG_FILE_PATH

  form.value = next
  originalForm.value = { ...next }
}

function effectiveLogFileValue(currentEnabled, currentValue) {
  if (!currentEnabled) return ''
  const trimmed = String(currentValue || '').trim()
  return trimmed || DEFAULT_LOG_FILE_PATH
}

function buildPatchPayload() {
  const payload = {}
  for (const key of fieldOrder) {
    if (key === 'log_file') {
      const currentLogFile = effectiveLogFileValue(logFileEnabled.value, form.value.log_file)
      const originalLogFile = effectiveLogFileValue(originalLogFileEnabled.value, originalForm.value.log_file)
      if (currentLogFile !== originalLogFile) {
        payload.log_file = currentLogFile
      }
      continue
    }
    if (form.value[key] !== originalForm.value[key]) {
      payload[key] = form.value[key]
    }
  }
  return payload
}

function resetForm() {
  form.value = { ...originalForm.value }
  logFileEnabled.value = originalLogFileEnabled.value
}

async function loadConfiguration() {
  loading.value = true
  error.value = ''
  try {
    const response = await getConfiguration()
    normalizeForm(response)
  } catch (err) {
    error.value = String(err?.response?.data?.detail || err?.response?.data?.message || t('common.errors.requestConflict'))
  } finally {
    loading.value = false
  }
}

async function saveConfiguration() {
  const payload = buildPatchPayload()
  if (Object.keys(payload).length === 0) return

  saving.value = true
  error.value = ''
  try {
    const result = await updateConfiguration(payload)
    form.value.log_file = effectiveLogFileValue(logFileEnabled.value, form.value.log_file) || DEFAULT_LOG_FILE_PATH
    originalForm.value = { ...form.value }
    originalLogFileEnabled.value = logFileEnabled.value

    pendingRestartSettings.value = result.restart_required_settings || []
    restartPending.value = !!result.restart_required

    if (result.applied_immediately?.length) {
      toast.success(t('configuration.toasts.saved'))
    }
    if (result.restart_required) {
      toast.warning(t('configuration.toasts.pendingRestart'))
    }
  } catch (err) {
    error.value = String(err?.response?.data?.detail || err?.response?.data?.message || t('common.errors.requestConflict'))
  } finally {
    saving.value = false
  }
}

async function confirmRestart() {
  restarting.value = true
  error.value = ''
  try {
    await restartConfigurationService({ confirm: true })
    restartPending.value = false
    pendingRestartSettings.value = []
    showRestartConfirm.value = false
    toast.success(t('configuration.toasts.restartRequested'))
  } catch (err) {
    error.value = String(err?.response?.data?.detail || err?.response?.data?.message || t('common.errors.serverErrorGeneric'))
  } finally {
    restarting.value = false
  }
}

onMounted(loadConfiguration)
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('configuration.title') }}</h1>
      <button class="btn" :disabled="loading" @click="loadConfiguration">{{ t('common.actions.refresh') }}</button>
    </header>

    <p class="muted">{{ t('configuration.description') }}</p>
    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <article class="panel">
      <h2>{{ t('configuration.sections.logging') }}</h2>

      <label for="cfg-log-level">{{ t('configuration.fields.log_level.label') }}</label>
      <select id="cfg-log-level" v-model="form.log_level">
        <option v-for="option in levelOptions" :key="option" :value="option">{{ option }}</option>
      </select>
      <p class="field-help">{{ t('configuration.fields.log_level.help') }}</p>

      <label for="cfg-log-format">{{ t('configuration.fields.log_format.label') }}</label>
      <select id="cfg-log-format" v-model="form.log_format">
        <option v-for="option in formatOptions" :key="option" :value="option">{{ option }}</option>
      </select>
      <p class="field-help">{{ t('configuration.fields.log_format.help') }}</p>

      <label for="cfg-log-file">{{ t('configuration.fields.log_file.label') }}</label>
      <label class="checkbox-row" for="cfg-log-file-enabled">
        <input id="cfg-log-file-enabled" v-model="logFileEnabled" type="checkbox" />
        <span>{{ t('configuration.fields.log_file.enabledLabel') }}</span>
      </label>
      <input id="cfg-log-file" v-model="form.log_file" type="text" :disabled="!logFileEnabled" />
      <p class="field-help">{{ t('configuration.fields.log_file.help') }}</p>

      <label for="cfg-log-max-bytes">{{ t('configuration.fields.log_file_max_bytes.label') }}</label>
      <input id="cfg-log-max-bytes" v-model.number="form.log_file_max_bytes" type="number" min="1" />

      <label for="cfg-log-backup-count">{{ t('configuration.fields.log_file_backup_count.label') }}</label>
      <input id="cfg-log-backup-count" v-model.number="form.log_file_backup_count" type="number" min="0" />
    </article>

    <article class="panel">
      <h2>{{ t('configuration.sections.databasePool') }}</h2>

      <label for="cfg-db-pool-size">{{ t('configuration.fields.db_pool_size.label') }}</label>
      <input id="cfg-db-pool-size" v-model.number="form.db_pool_size" type="number" min="1" max="100" />

      <label for="cfg-db-pool-overflow">{{ t('configuration.fields.db_pool_max_overflow.label') }}</label>
      <input id="cfg-db-pool-overflow" v-model.number="form.db_pool_max_overflow" type="number" min="0" max="200" />

      <label for="cfg-db-pool-recycle">{{ t('configuration.fields.db_pool_recycle_seconds.label') }}</label>
      <input id="cfg-db-pool-recycle" v-model.number="form.db_pool_recycle_seconds" type="number" min="-1" />
      <p class="field-help">{{ t('configuration.fields.db_pool_recycle_seconds.help') }}</p>
      <p class="restart-chip">{{ t('configuration.restartRequiredField') }}</p>
    </article>

    <article v-if="restartPending" class="panel warning-panel">
      <h2>{{ t('configuration.pendingRestartTitle') }}</h2>
      <p>{{ t('configuration.pendingRestartBody') }}</p>
      <ul>
        <li v-for="label in changedFieldLabels" :key="label">{{ label }}</li>
      </ul>
      <button class="btn btn-primary" :disabled="restarting" @click="showRestartConfirm = true">
        {{ t('configuration.actions.restartService') }}
      </button>
    </article>

    <footer class="action-row">
      <button class="btn" :disabled="saving || !hasChanges" @click="resetForm">
        {{ t('common.actions.cancel') }}
      </button>
      <button class="btn btn-primary" :disabled="saving || !hasChanges" @click="saveConfiguration">
        {{ t('common.actions.save') }}
      </button>
    </footer>

    <ConfirmDialog
      v-model="showRestartConfirm"
      :title="t('configuration.confirmRestart.title')"
      :message="t('configuration.confirmRestart.body')"
      :confirm-label="t('configuration.actions.restartService')"
      :cancel-label="t('common.actions.cancel')"
      :busy="restarting"
      @confirm="confirmRestart"
    />
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
  display: grid;
  gap: var(--space-xs);
}

.warning-panel {
  border-color: var(--color-alert-warning-border);
  background: var(--color-alert-warning-bg);
}

.warning-panel ul {
  margin: 0;
  padding-left: var(--space-lg);
}

.action-row {
  display: flex;
  gap: var(--space-sm);
  justify-content: flex-end;
}

.checkbox-row {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
}

input,
select {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.field-help,
.muted,
.restart-chip {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
}

.restart-chip {
  font-weight: var(--font-weight-medium);
}

.error-banner {
  color: var(--color-alert-danger-text);
  background: var(--color-alert-danger-bg);
  border: 1px solid var(--color-alert-danger-border);
  border-radius: var(--border-radius);
  padding: var(--space-sm);
}
</style>
