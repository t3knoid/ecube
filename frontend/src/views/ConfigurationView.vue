<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import { getConfiguration, restartConfigurationService, updateConfiguration } from '@/api/configuration.js'
import { getPasswordPolicy, updatePasswordPolicy } from '@/api/admin.js'
import { useToast } from '@/composables/useToast.js'

const { t } = useI18n()
const toast = useToast()

const loading = ref(false)
const saving = ref(false)
const restarting = ref(false)
const error = ref('')
const passwordPolicyError = ref('')
const passwordPolicyAvailable = ref(true)

const showRestartConfirm = ref(false)
const restartPending = ref(false)
const pendingRestartSettings = ref([])
const logFileEnabled = ref(false)
const originalLogFileEnabled = ref(false)

const DEFAULT_LOG_FILE_PATH = '/var/log/ecube/app.log'
const CALLBACK_PAYLOAD_FIELDS_PLACEHOLDER = `[
  "event",
  "project_id",
  "completion_result"
]`
const CALLBACK_PAYLOAD_FIELD_MAP_PLACEHOLDER = `{
  "type": "event",
  "summary": "project=${'${project_id}'};result=${'${completion_result}'}"
}`

const form = ref({
  log_level: 'INFO',
  log_format: 'text',
  log_file: '',
  log_file_max_bytes: 10485760,
  log_file_backup_count: 5,
  nfs_client_version: '4.1',
  db_pool_size: 5,
  db_pool_max_overflow: 10,
  db_pool_recycle_seconds: -1,
  startup_analysis_batch_size: 500,
  mkfs_exfat_cluster_size: '4K',
  drive_format_timeout_seconds: 900,
  drive_mount_timeout_seconds: 120,
  network_mount_timeout_seconds: 120,
  mount_share_discovery_timeout_seconds: 60,
  copy_job_timeout: 3600,
  job_detail_files_page_size: 40,
  callback_default_url: '',
  callback_proxy_url: '',
  callback_payload_fields: '',
  callback_payload_field_map: '',
  callback_hmac_secret: '',
  callback_hmac_secret_configured: false,
  clear_callback_hmac_secret: false,
})
const originalForm = ref({ ...form.value })
const passwordPolicyForm = ref({
  minlen: 14,
  minclass: 3,
  maxrepeat: 3,
  maxsequence: 4,
  maxclassrepeat: 0,
  dictcheck: 1,
  usercheck: 1,
  difok: 5,
  retry: 3,
})
const originalPasswordPolicyForm = ref({ ...passwordPolicyForm.value })

const fieldOrder = [
  'log_level',
  'log_format',
  'log_file',
  'log_file_max_bytes',
  'log_file_backup_count',
  'nfs_client_version',
  'db_pool_size',
  'db_pool_max_overflow',
  'db_pool_recycle_seconds',
  'startup_analysis_batch_size',
  'mkfs_exfat_cluster_size',
  'drive_format_timeout_seconds',
  'drive_mount_timeout_seconds',
  'network_mount_timeout_seconds',
  'mount_share_discovery_timeout_seconds',
  'copy_job_timeout',
  'job_detail_files_page_size',
  'callback_default_url',
  'callback_proxy_url',
  'callback_payload_fields',
  'callback_payload_field_map',
]

const levelOptions = ['DEBUG', 'INFO', 'WARNING', 'ERROR']
const formatOptions = ['text', 'json']
const nfsClientVersionOptions = ['4.2', '4.1', '4.0', '3']
const exfatClusterSizeOptions = ['4K', '64K', '128K', '256K']

const hasChanges = computed(() => {
  for (const key of fieldOrder) {
    if (key === 'log_file') {
      const currentLogFile = effectiveLogFileValue(logFileEnabled.value, form.value.log_file)
      const originalLogFile = effectiveLogFileValue(originalLogFileEnabled.value, originalForm.value.log_file)
      if (currentLogFile !== originalLogFile) {
        return true
      }
      continue
    }
    if (form.value[key] !== originalForm.value[key]) {
      return true
    }
  }

  const nextSecret = String(form.value.callback_hmac_secret || '').trim()
  if (nextSecret) {
    return true
  }
  if (passwordPolicyAvailable.value && Object.keys(passwordPolicyForm.value).some((key) => passwordPolicyForm.value[key] !== originalPasswordPolicyForm.value[key])) {
    return true
  }
  return !!(form.value.clear_callback_hmac_secret && originalForm.value.callback_hmac_secret_configured)
})

const changedFieldLabels = computed(() => {
  return fieldOrder
    .filter((key) => pendingRestartSettings.value.includes(key))
    .map((key) => t(`configuration.fields.${key}.label`))
})

function getConfigurationErrorMessage(err, operation) {
  if (!err?.response) {
    return t('common.errors.networkError')
  }

  const status = Number(err.response?.status || 0)
  const code = String(err.response?.data?.code || '')

  if (code === 'HTTP_400' || status === 400) {
    return t('common.errors.invalidRequest')
  }

  if (code === 'HTTP_403' || status === 403) {
    return t('common.errors.insufficientPermissions')
  }

  if (code === 'HTTP_409' || status === 409) {
    return t('common.errors.requestConflict')
  }

  if (code === 'HTTP_422' || status === 422) {
    return t('common.errors.validationFailed')
  }

  if (code === 'HTTP_503' || status === 503) {
    return operation === 'restart'
      ? t('configuration.errors.restartUnavailable')
      : t(`configuration.errors.${operation}Failed`)
  }

  if ((code.startsWith('HTTP_5') && code !== 'HTTP_503') || (status >= 500 && status < 600)) {
    return t(`configuration.errors.${operation}Failed`)
  }

  return t(`configuration.errors.${operation}Failed`)
}

function normalizeForm(data) {
  const next = { ...form.value }
  const list = Array.isArray(data?.settings) ? data.settings : []
  let backendLogFileValue = ''
  for (const entry of list) {
    if (!entry?.key) continue
    const key = entry.key
    if (!fieldOrder.includes(key) && key !== 'callback_hmac_secret_configured') continue
    let value = entry.value
    if (key === 'log_file') {
      value = value || ''
      backendLogFileValue = String(value)
    }
    if (key === 'callback_payload_fields' || key === 'callback_payload_field_map') {
      value = value == null ? '' : JSON.stringify(value, null, 2)
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
  next.callback_hmac_secret = ''
  next.clear_callback_hmac_secret = false
  next.callback_hmac_secret_configured = Boolean(next.callback_hmac_secret_configured)

  form.value = next
  originalForm.value = { ...next }
}

function normalizePasswordPolicy(data) {
  const next = {
    minlen: Number(data?.minlen ?? 14),
    minclass: Number(data?.minclass ?? 3),
    maxrepeat: Number(data?.maxrepeat ?? 3),
    maxsequence: Number(data?.maxsequence ?? 4),
    maxclassrepeat: Number(data?.maxclassrepeat ?? 0),
    dictcheck: Number(data?.dictcheck ?? 1),
    usercheck: Number(data?.usercheck ?? 1),
    difok: Number(data?.difok ?? 5),
    retry: Number(data?.retry ?? 3),
  }
  passwordPolicyForm.value = next
  originalPasswordPolicyForm.value = { ...next }
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
      if (key === 'callback_payload_fields') {
        payload[key] = parseJsonConfigurationField(form.value[key], key, 'array')
      } else if (key === 'callback_payload_field_map') {
        payload[key] = parseJsonConfigurationField(form.value[key], key, 'object')
      } else {
        payload[key] = form.value[key]
      }
    }
  }

  const nextSecret = String(form.value.callback_hmac_secret || '').trim()
  if (nextSecret) {
    payload.callback_hmac_secret = nextSecret
  } else if (form.value.clear_callback_hmac_secret && originalForm.value.callback_hmac_secret_configured) {
    payload.clear_callback_hmac_secret = true
  }

  return payload
}

function parseJsonConfigurationField(value, key, kind) {
  const trimmed = String(value || '').trim()
  if (!trimmed) return null

  let parsed
  try {
    parsed = JSON.parse(trimmed)
  } catch {
    throw new Error(t(`configuration.fields.${key}.invalidJson`))
  }

  if (kind === 'array' && !Array.isArray(parsed)) {
    throw new Error(t(`configuration.fields.${key}.invalidType`))
  }
  if (kind === 'object' && (parsed == null || Array.isArray(parsed) || typeof parsed !== 'object')) {
    throw new Error(t(`configuration.fields.${key}.invalidType`))
  }
  return parsed
}

function resetForm() {
  form.value = {
    ...originalForm.value,
    callback_hmac_secret: '',
    clear_callback_hmac_secret: false,
  }
  logFileEnabled.value = originalLogFileEnabled.value
  passwordPolicyForm.value = { ...originalPasswordPolicyForm.value }
}

function buildPasswordPolicyPayload() {
  const payload = {}
  for (const key of Object.keys(passwordPolicyForm.value)) {
    if (passwordPolicyForm.value[key] !== originalPasswordPolicyForm.value[key]) {
      payload[key] = passwordPolicyForm.value[key]
    }
  }
  return payload
}

async function loadConfiguration() {
  loading.value = true
  error.value = ''
  passwordPolicyError.value = ''
  passwordPolicyAvailable.value = true
  try {
    const configurationResponse = await getConfiguration()
    normalizeForm(configurationResponse)
  } catch (err) {
    error.value = getConfigurationErrorMessage(err, 'load')
    loading.value = false
    return
  }

  try {
    const passwordPolicyResponse = await getPasswordPolicy()
    normalizePasswordPolicy(passwordPolicyResponse)
  } catch (err) {
    passwordPolicyAvailable.value = false
    passwordPolicyError.value = getConfigurationErrorMessage(err, 'load')
  } finally {
    loading.value = false
  }
}

async function saveConfiguration() {
  let payload
  try {
    payload = buildPatchPayload()
  } catch (err) {
    error.value = err instanceof Error ? err.message : t('common.errors.validationFailed')
    return
  }
  const passwordPolicyPayload = passwordPolicyAvailable.value ? buildPasswordPolicyPayload() : {}
  if (Object.keys(payload).length === 0 && Object.keys(passwordPolicyPayload).length === 0) return

  saving.value = true
  error.value = ''
  try {
    if (Object.keys(passwordPolicyPayload).length) {
      const nextPasswordPolicy = await updatePasswordPolicy(passwordPolicyPayload)
      normalizePasswordPolicy(nextPasswordPolicy)
    }

    if (Object.keys(payload).length) {
      const result = await updateConfiguration(payload)
      form.value.log_file = effectiveLogFileValue(logFileEnabled.value, form.value.log_file) || DEFAULT_LOG_FILE_PATH
      if (payload.callback_hmac_secret) {
        form.value.callback_hmac_secret_configured = true
      }
      if (payload.clear_callback_hmac_secret) {
        form.value.callback_hmac_secret_configured = false
      }
      form.value.callback_hmac_secret = ''
      form.value.clear_callback_hmac_secret = false
      originalForm.value = { ...form.value }
      originalLogFileEnabled.value = logFileEnabled.value

      pendingRestartSettings.value = result.restart_required_settings || []
      restartPending.value = !!result.restart_required

      if (result.restart_required) {
        toast.warning(t('configuration.toasts.pendingRestart'))
      }
    }

    toast.success(t('configuration.toasts.saved'))
  } catch (err) {
    error.value = getConfigurationErrorMessage(err, 'save')
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
    error.value = getConfigurationErrorMessage(err, 'restart')
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

    <div class="settings-grid">
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
        <h2>{{ t('configuration.sections.shares') }}</h2>

        <label for="cfg-nfs-client-version">{{ t('configuration.fields.nfs_client_version.label') }}</label>
        <select id="cfg-nfs-client-version" v-model="form.nfs_client_version">
          <option v-for="option in nfsClientVersionOptions" :key="option" :value="option">{{ option }}</option>
        </select>
        <p class="field-help">{{ t('configuration.fields.nfs_client_version.help') }}</p>

        <label for="cfg-network-mount-timeout-seconds">{{ t('configuration.fields.network_mount_timeout_seconds.label') }}</label>
        <input
          id="cfg-network-mount-timeout-seconds"
          v-model.number="form.network_mount_timeout_seconds"
          type="number"
          min="1"
        />
        <p class="field-help">{{ t('configuration.fields.network_mount_timeout_seconds.help') }}</p>

        <label for="cfg-mount-share-discovery-timeout-seconds">{{ t('configuration.fields.mount_share_discovery_timeout_seconds.label') }}</label>
        <input
          id="cfg-mount-share-discovery-timeout-seconds"
          v-model.number="form.mount_share_discovery_timeout_seconds"
          type="number"
          min="1"
        />
        <p class="field-help">{{ t('configuration.fields.mount_share_discovery_timeout_seconds.help') }}</p>
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

      <article class="panel">
        <h2>{{ t('configuration.sections.passwordPolicy') }}</h2>

        <p v-if="passwordPolicyError" class="error-banner">{{ passwordPolicyError }}</p>

        <label for="cfg-policy-minlen">{{ t('configuration.passwordPolicy.minlen') }}</label>
        <input id="cfg-policy-minlen" v-model.number="passwordPolicyForm.minlen" type="number" min="12" max="128" :disabled="!passwordPolicyAvailable || saving" />

        <label for="cfg-policy-minclass">{{ t('configuration.passwordPolicy.minclass') }}</label>
        <input id="cfg-policy-minclass" v-model.number="passwordPolicyForm.minclass" type="number" min="0" max="4" :disabled="!passwordPolicyAvailable || saving" />

        <label for="cfg-policy-maxrepeat">{{ t('configuration.passwordPolicy.maxrepeat') }}</label>
        <input id="cfg-policy-maxrepeat" v-model.number="passwordPolicyForm.maxrepeat" type="number" min="0" :disabled="!passwordPolicyAvailable || saving" />

        <label for="cfg-policy-maxsequence">{{ t('configuration.passwordPolicy.maxsequence') }}</label>
        <input id="cfg-policy-maxsequence" v-model.number="passwordPolicyForm.maxsequence" type="number" min="0" :disabled="!passwordPolicyAvailable || saving" />

        <label for="cfg-policy-maxclassrepeat">{{ t('configuration.passwordPolicy.maxclassrepeat') }}</label>
        <input id="cfg-policy-maxclassrepeat" v-model.number="passwordPolicyForm.maxclassrepeat" type="number" min="0" :disabled="!passwordPolicyAvailable || saving" />

        <label for="cfg-policy-dictcheck">{{ t('configuration.passwordPolicy.dictcheck') }}</label>
        <select id="cfg-policy-dictcheck" v-model.number="passwordPolicyForm.dictcheck" :disabled="!passwordPolicyAvailable || saving">
          <option :value="1">{{ t('common.labels.enabled') }}</option>
          <option :value="0">{{ t('common.labels.disabled') }}</option>
        </select>

        <label for="cfg-policy-usercheck">{{ t('configuration.passwordPolicy.usercheck') }}</label>
        <select id="cfg-policy-usercheck" v-model.number="passwordPolicyForm.usercheck" :disabled="!passwordPolicyAvailable || saving">
          <option :value="1">{{ t('common.labels.enabled') }}</option>
          <option :value="0">{{ t('common.labels.disabled') }}</option>
        </select>

        <label for="cfg-policy-difok">{{ t('configuration.passwordPolicy.difok') }}</label>
        <input id="cfg-policy-difok" v-model.number="passwordPolicyForm.difok" type="number" min="0" max="255" :disabled="!passwordPolicyAvailable || saving" />

        <label for="cfg-policy-retry">{{ t('configuration.passwordPolicy.retry') }}</label>
        <input id="cfg-policy-retry" v-model.number="passwordPolicyForm.retry" type="number" min="1" max="10" :disabled="!passwordPolicyAvailable || saving" />

        <p class="field-help">{{ t('configuration.passwordPolicy.enforceForRoot') }}</p>
      </article>

      <article class="panel">
        <h2>{{ t('configuration.sections.copyJobs') }}</h2>

        <label for="cfg-startup-analysis-batch-size">{{ t('configuration.fields.startup_analysis_batch_size.label') }}</label>
        <input
          id="cfg-startup-analysis-batch-size"
          v-model.number="form.startup_analysis_batch_size"
          type="number"
          min="1"
          max="5000"
        />
        <p class="field-help">{{ t('configuration.fields.startup_analysis_batch_size.help') }}</p>

        <label for="cfg-copy-job-timeout">{{ t('configuration.fields.copy_job_timeout.label') }}</label>
        <input id="cfg-copy-job-timeout" v-model.number="form.copy_job_timeout" type="number" min="0" />
        <p class="field-help">{{ t('configuration.fields.copy_job_timeout.help') }}</p>

        <label for="cfg-mkfs-exfat-cluster-size">{{ t('configuration.fields.mkfs_exfat_cluster_size.label') }}</label>
        <select id="cfg-mkfs-exfat-cluster-size" v-model="form.mkfs_exfat_cluster_size">
          <option v-for="option in exfatClusterSizeOptions" :key="option" :value="option">{{ option }}</option>
        </select>
        <p class="field-help">{{ t('configuration.fields.mkfs_exfat_cluster_size.help') }}</p>

        <label for="cfg-drive-format-timeout-seconds">{{ t('configuration.fields.drive_format_timeout_seconds.label') }}</label>
        <input
          id="cfg-drive-format-timeout-seconds"
          v-model.number="form.drive_format_timeout_seconds"
          type="number"
          min="1"
        />
        <p class="field-help">{{ t('configuration.fields.drive_format_timeout_seconds.help') }}</p>

        <label for="cfg-drive-mount-timeout-seconds">{{ t('configuration.fields.drive_mount_timeout_seconds.label') }}</label>
        <input
          id="cfg-drive-mount-timeout-seconds"
          v-model.number="form.drive_mount_timeout_seconds"
          type="number"
          min="1"
        />
        <p class="field-help">{{ t('configuration.fields.drive_mount_timeout_seconds.help') }}</p>

        <label for="cfg-job-detail-files-page-size">{{ t('configuration.fields.job_detail_files_page_size.label') }}</label>
        <input
          id="cfg-job-detail-files-page-size"
          v-model.number="form.job_detail_files_page_size"
          type="number"
          min="20"
          max="100"
        />
        <p class="field-help">{{ t('configuration.fields.job_detail_files_page_size.help') }}</p>
      </article>

      <article class="panel">
        <h2>{{ t('configuration.sections.webhooks') }}</h2>

        <label for="cfg-callback-default-url">{{ t('configuration.fields.callback_default_url.label') }}</label>
        <input
          id="cfg-callback-default-url"
          v-model="form.callback_default_url"
          type="url"
          :placeholder="t('configuration.fields.callback_default_url.placeholder')"
        />
        <p class="field-help">{{ t('configuration.fields.callback_default_url.help') }}</p>

        <label for="cfg-callback-proxy-url">{{ t('configuration.fields.callback_proxy_url.label') }}</label>
        <input
          id="cfg-callback-proxy-url"
          v-model="form.callback_proxy_url"
          type="url"
          :placeholder="t('configuration.fields.callback_proxy_url.placeholder')"
        />
        <p class="field-help">{{ t('configuration.fields.callback_proxy_url.help') }}</p>

        <label for="cfg-callback-hmac-secret">{{ t('configuration.fields.callback_hmac_secret.label') }}</label>
        <input
          id="cfg-callback-hmac-secret"
          v-model="form.callback_hmac_secret"
          type="password"
          autocomplete="new-password"
          :placeholder="t('configuration.fields.callback_hmac_secret.placeholder')"
        />
        <p class="field-help">{{ t('configuration.fields.callback_hmac_secret.help') }}</p>
        <p class="field-help">
          {{ form.callback_hmac_secret_configured
            ? t('configuration.fields.callback_hmac_secret.statusConfigured')
            : t('configuration.fields.callback_hmac_secret.statusNotConfigured') }}
        </p>
        <label class="checkbox-row" for="cfg-clear-callback-hmac-secret">
          <input
            id="cfg-clear-callback-hmac-secret"
            v-model="form.clear_callback_hmac_secret"
            type="checkbox"
            :disabled="!!String(form.callback_hmac_secret || '').trim() || !form.callback_hmac_secret_configured"
          />
          <span>{{ t('configuration.fields.callback_hmac_secret.clearLabel') }}</span>
        </label>

        <label for="cfg-callback-payload-fields">{{ t('configuration.fields.callback_payload_fields.label') }}</label>
        <textarea
          id="cfg-callback-payload-fields"
          v-model="form.callback_payload_fields"
          rows="6"
          :placeholder="CALLBACK_PAYLOAD_FIELDS_PLACEHOLDER"
        />
        <p class="field-help">{{ t('configuration.fields.callback_payload_fields.help') }}</p>

        <label for="cfg-callback-payload-field-map">{{ t('configuration.fields.callback_payload_field_map.label') }}</label>
        <textarea
          id="cfg-callback-payload-field-map"
          v-model="form.callback_payload_field_map"
          rows="8"
          :placeholder="CALLBACK_PAYLOAD_FIELD_MAP_PLACEHOLDER"
        />
        <p class="field-help">{{ t('configuration.fields.callback_payload_field_map.help') }}</p>
      </article>
    </div>

    <div v-if="restartPending" class="settings-grid">
      <article class="panel warning-panel">
        <h2>{{ t('configuration.pendingRestartTitle') }}</h2>
        <p>{{ t('configuration.pendingRestartBody') }}</p>
        <ul>
          <li v-for="label in changedFieldLabels" :key="label">{{ label }}</li>
        </ul>
        <button class="btn btn-primary" :disabled="restarting" @click="showRestartConfirm = true">
          {{ t('configuration.actions.restartService') }}
        </button>
      </article>
    </div>

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

.settings-grid {
  display: grid;
  gap: var(--space-md);
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

@media (max-width: 960px) {
  .settings-grid {
    grid-template-columns: minmax(0, 1fr);
  }
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
  align-content: start;
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
  font: inherit;
  line-height: 1.4;
  padding: 0.5em 0.75em;
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

@media (max-width: 768px) {
  .settings-grid,
  .header-row,
  .action-row {
    grid-template-columns: minmax(0, 1fr);
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
