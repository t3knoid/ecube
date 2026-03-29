<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getMounts, createMount, deleteMount, validateAllMounts, validateMount } from '@/api/mounts.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

const { t } = useI18n()

const mounts = ref([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')

const showAddDialog = ref(false)
const showRemoveDialog = ref(false)
const removeTarget = ref(null)

const page = ref(1)
const pageSize = ref(10)
const search = ref('')

const form = ref({
  type: 'SMB',
  remote_path: '',
  local_mount_point: '',
  username: '',
  password: '',
  credentials_file: '',
})

const columns = computed(() => [
  { key: 'id', label: 'ID', align: 'right' },
  { key: 'type', label: t('common.labels.type') },
  { key: 'remote_path', label: t('mounts.remotePath') },
  { key: 'local_mount_point', label: t('mounts.localPath') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'last_checked_at', label: t('mounts.lastChecked') },
  { key: 'actions', label: t('common.actions.edit'), align: 'center' },
])

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return mounts.value.filter((mount) => {
    if (!query) return true
    const text = [mount.type, mount.remote_path, mount.local_mount_point, mount.status].join(' ').toLowerCase()
    return text.includes(query)
  })
})

const paged = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filtered.value.slice(start, start + pageSize.value)
})

function toIso(value) {
  if (!value) return '-'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '-'
  return parsed.toLocaleString()
}

async function loadMounts() {
  loading.value = true
  error.value = ''
  try {
    mounts.value = await getMounts()
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
}

function resetForm() {
  form.value = {
    type: 'SMB',
    remote_path: '',
    local_mount_point: '',
    username: '',
    password: '',
    credentials_file: '',
  }
}

function formValid() {
  return !!form.value.type && !!form.value.remote_path.trim() && !!form.value.local_mount_point.trim()
}

async function submitAddMount() {
  if (!formValid()) return
  saving.value = true
  error.value = ''
  try {
    const payload = {
      type: form.value.type,
      remote_path: form.value.remote_path.trim(),
      local_mount_point: form.value.local_mount_point.trim(),
      username: form.value.username.trim() || null,
      password: form.value.password || null,
      credentials_file: form.value.credentials_file.trim() || null,
    }
    await createMount(payload)
    showAddDialog.value = false
    resetForm()
    await loadMounts()
  } catch {
    error.value = t('common.errors.validationFailed')
  } finally {
    saving.value = false
  }
}

async function runValidateAll() {
  loading.value = true
  error.value = ''
  try {
    mounts.value = await validateAllMounts()
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    loading.value = false
  }
}

async function runValidateOne(mountId) {
  error.value = ''
  try {
    const next = await validateMount(mountId)
    const index = mounts.value.findIndex((item) => item.id === mountId)
    if (index >= 0) mounts.value[index] = next
  } catch {
    error.value = t('common.errors.requestConflict')
  }
}

async function runRemove() {
  if (!removeTarget.value) return
  saving.value = true
  error.value = ''
  try {
    await deleteMount(removeTarget.value.id)
    removeTarget.value = null
    showRemoveDialog.value = false
    await loadMounts()
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

onMounted(loadMounts)
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('mounts.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadMounts">{{ t('common.actions.refresh') }}</button>
        <button class="btn" @click="runValidateAll">{{ t('mounts.testAll') }}</button>
        <button class="btn btn-primary" @click="showAddDialog = true">{{ t('mounts.add') }}</button>
      </div>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <input v-model="search" type="text" :placeholder="t('mounts.searchPlaceholder')" />

    <DataTable :columns="columns" :rows="paged" :empty-text="t('mounts.empty')">
      <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
      <template #cell-last_checked_at="{ row }">{{ toIso(row.last_checked_at) }}</template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn" @click="runValidateOne(row.id)">{{ t('mounts.test') }}</button>
          <button class="btn btn-danger" @click="removeTarget = row; showRemoveDialog = true">{{ t('mounts.remove') }}</button>
        </div>
      </template>
    </DataTable>

    <Pagination v-model:page="page" :page-size="pageSize" :total="filtered.length" />

    <teleport to="body">
      <div v-if="showAddDialog" class="dialog-overlay" @click.self="showAddDialog = false">
        <div class="dialog-panel" role="dialog" aria-modal="true">
          <h2>{{ t('mounts.add') }}</h2>
          <label>{{ t('common.labels.type') }}</label>
          <select v-model="form.type">
            <option value="SMB">SMB</option>
            <option value="NFS">NFS</option>
          </select>
          <label>{{ t('mounts.remotePath') }}</label>
          <input v-model="form.remote_path" type="text" />
          <label>{{ t('mounts.localPath') }}</label>
          <input v-model="form.local_mount_point" type="text" />
          <label>{{ t('auth.username') }}</label>
          <input v-model="form.username" type="text" autocomplete="off" />
          <label>{{ t('auth.password') }}</label>
          <input v-model="form.password" type="password" autocomplete="new-password" />
          <label>{{ t('mounts.credentialsFile') }}</label>
          <input v-model="form.credentials_file" type="text" />

          <div class="dialog-actions">
            <button class="btn" @click="showAddDialog = false">{{ t('common.actions.cancel') }}</button>
            <button class="btn btn-primary" :disabled="saving || !formValid()" @click="submitAddMount">
              {{ saving ? t('common.labels.loading') : t('common.actions.create') }}
            </button>
          </div>
        </div>
      </div>
    </teleport>

    <ConfirmDialog
      v-model="showRemoveDialog"
      :title="t('mounts.removeConfirmTitle')"
      :message="t('mounts.removeConfirmBody')"
      :confirm-label="t('mounts.remove')"
      :cancel-label="t('common.actions.cancel')"
      :busy="saving"
      dangerous
      @confirm="runRemove"
    />
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row,
.actions,
.row-actions {
  display: flex;
  gap: var(--space-sm);
}

.header-row {
  justify-content: space-between;
  align-items: center;
}

input,
select {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
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

.dialog-overlay {
  position: fixed;
  inset: 0;
  background: color-mix(in srgb, var(--color-bg-primary) 30%, #000000);
  display: grid;
  place-items: center;
  z-index: 1000;
}

.dialog-panel {
  width: min(640px, 100%);
  background: var(--color-bg-secondary);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  box-shadow: var(--shadow-lg);
  padding: var(--space-lg);
  display: grid;
  gap: var(--space-xs);
}

.dialog-actions {
  margin-top: var(--space-sm);
  display: flex;
  justify-content: flex-end;
  gap: var(--space-sm);
}
</style>
