<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { getMounts, createMount, deleteMount, validateAllMounts, validateMount } from '@/api/mounts.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import StatusBadge from '@/components/common/StatusBadge.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'
import DirectoryBrowser from '@/components/browse/DirectoryBrowser.vue'

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

/** Mount ID currently being browsed (null = none open). */
const browsingMountId = ref(null)

/** The currently-browsed mount object (computed from browsingMountId). */
const activeBrowsedMount = computed(() =>
  browsingMountId.value !== null
    ? mounts.value.find((m) => m.id === browsingMountId.value) || null
    : null
)

const form = ref({
  type: 'SMB',
  remote_path: '',
  project_id: '',
  username: '',
  password: '',
  credentials_file: '',
})

const addDialogRef = ref(null)
const addDialogTriggerRef = ref(null)
const addMountDialogTitleId = 'add-mount-dialog-title'

const columns = computed(() => [
  { key: 'id', label: t('common.labels.id'), align: 'right' },
  { key: 'type', label: t('common.labels.type') },
  { key: 'project_id', label: t('dashboard.project') },
  { key: 'remote_path', label: t('mounts.remotePath') },
  { key: 'local_mount_point', label: t('mounts.localPath') },
  { key: 'status', label: t('common.labels.status') },
  { key: 'last_checked_at', label: t('mounts.lastChecked') },
  { key: 'actions', label: '', align: 'center' },
])

const filtered = computed(() => {
  const query = search.value.trim().toLowerCase()
  return mounts.value.filter((mount) => {
    if (!query) return true
    const text = [mount.type, mount.project_id, mount.remote_path, mount.local_mount_point, mount.status].join(' ').toLowerCase()
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
    project_id: '',
    username: '',
    password: '',
    credentials_file: '',
  }
}

function trapFocusWithin(event, container) {
  if (!container) return
  const focusable = Array.from(
    container.querySelectorAll('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'),
  ).filter((element) => !element.hasAttribute('disabled') && element.getAttribute('aria-hidden') !== 'true')

  if (!focusable.length) return

  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  const active = document.activeElement

  if (event.shiftKey && active === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && active === last) {
    event.preventDefault()
    first.focus()
  }
}

function formValid() {
  return !!form.value.type && !!form.value.remote_path.trim() && !!form.value.project_id.trim()
}

async function submitAddMount() {
  if (!formValid()) return
  saving.value = true
  error.value = ''
  try {
    const payload = {
      type: form.value.type,
      remote_path: form.value.remote_path.trim(),
      project_id: form.value.project_id.trim(),
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

function openAddDialog(event) {
  addDialogTriggerRef.value = event?.currentTarget instanceof HTMLElement ? event.currentTarget : document.activeElement
  showAddDialog.value = true
}

function closeAddDialog() {
  showAddDialog.value = false
}

function handleAddDialogKeydown(event) {
  if (!showAddDialog.value) return
  if (event.key === 'Escape') {
    event.preventDefault()
    closeAddDialog()
    return
  }
  if (event.key === 'Tab') {
    trapFocusWithin(event, addDialogRef.value)
  }
}

async function runRemove(target = removeTarget.value) {
  if (!target) return
  removeTarget.value = target
  saving.value = true
  error.value = ''
  try {
    await deleteMount(target.id)
    if (browsingMountId.value === target.id) {
      browsingMountId.value = null
    }
    removeTarget.value = null
    showRemoveDialog.value = false
    await loadMounts()
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

function requestRemove(mount) {
  if (!mount) return
  removeTarget.value = mount
  if (mount.status === 'MOUNTED' && mount.local_mount_point) {
    showRemoveDialog.value = true
    return
  }
  showRemoveDialog.value = false
  void runRemove(mount)
}

const browsePanelRef = ref(null)

async function toggleBrowse(mountId) {
  browsingMountId.value = browsingMountId.value === mountId ? null : mountId
  if (browsingMountId.value !== null) {
    await nextTick()
    browsePanelRef.value?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }
}

onMounted(loadMounts)

watch(showAddDialog, async (open) => {
  if (open) {
    document.addEventListener('keydown', handleAddDialogKeydown)
    await nextTick()
    const target = addDialogRef.value?.querySelector('#mount-type')
    if (target instanceof HTMLElement) {
      target.focus()
    }
    return
  }

  document.removeEventListener('keydown', handleAddDialogKeydown)
  const trigger = addDialogTriggerRef.value
  addDialogTriggerRef.value = null
  await nextTick()
  if (trigger instanceof HTMLElement) {
    trigger.focus()
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleAddDialogKeydown)
})
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('mounts.title') }}</h1>
      <div class="actions">
        <button class="btn" @click="loadMounts">{{ t('common.actions.refresh') }}</button>
        <button class="btn" @click="runValidateAll">{{ t('mounts.testAll') }}</button>
        <button class="btn btn-primary" @click="openAddDialog">{{ t('mounts.add') }}</button>
      </div>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <input v-model="search" type="text" :placeholder="t('mounts.searchPlaceholder')" :aria-label="t('mounts.searchPlaceholder')" />

    <DataTable :columns="columns" :rows="paged" :empty-text="t('mounts.empty')">
      <template #cell-status="{ row }"><StatusBadge :status="row.status" /></template>
      <template #cell-last_checked_at="{ row }">{{ toIso(row.last_checked_at) }}</template>
      <template #cell-actions="{ row }">
        <div class="row-actions">
          <button class="btn" @click="runValidateOne(row.id)">{{ t('mounts.test') }}</button>
          <button
            class="btn"
            :disabled="row.status !== 'MOUNTED' || !row.local_mount_point"
            :title="row.status !== 'MOUNTED' || !row.local_mount_point ? t('mounts.browseUnavailable') : ''"
            :aria-expanded="browsingMountId === row.id"
            :aria-label="row.local_mount_point ? t('mounts.browse') + ' ' + row.local_mount_point : t('mounts.browse')"
            @click="toggleBrowse(row.id)"
          >
            {{ t('mounts.browse') }}
          </button>
          <button class="btn btn-danger" @click="requestRemove(row)">{{ t('mounts.remove') }}</button>
        </div>
      </template>
    </DataTable>

    <!-- Inline directory browser panels (one per browsed mount) -->
    <section
      v-if="activeBrowsedMount"
      ref="browsePanelRef"
      class="browse-panel"
      :aria-label="t('browse.browseMountContents') + ': ' + activeBrowsedMount.local_mount_point"
    >
      <h3 class="browse-panel-title">
        {{ t('browse.browseMountContents') }}: {{ activeBrowsedMount.local_mount_point }}
      </h3>
      <DirectoryBrowser
        :mount-path="activeBrowsedMount.local_mount_point"
      />
    </section>

    <Pagination v-model:page="page" :page-size="pageSize" :total="filtered.length" />

    <teleport to="body">
      <div v-if="showAddDialog" class="dialog-overlay">
        <div ref="addDialogRef" class="dialog-panel" role="dialog" aria-modal="true" :aria-labelledby="addMountDialogTitleId">
          <h2 :id="addMountDialogTitleId">{{ t('mounts.add') }}</h2>
          <label for="mount-type">{{ t('common.labels.type') }}</label>
          <select id="mount-type" v-model="form.type">
            <option value="SMB">SMB</option>
            <option value="NFS">NFS</option>
          </select>
          <label for="mount-remote-path">{{ t('mounts.remotePath') }}</label>
          <input id="mount-remote-path" v-model="form.remote_path" type="text" />
          <label for="mount-project-id">{{ t('dashboard.project') }}</label>
          <input id="mount-project-id" v-model="form.project_id" type="text" />
          <label for="mount-username">{{ t('auth.username') }}</label>
          <input id="mount-username" v-model="form.username" type="text" autocomplete="off" />
          <label for="mount-password">{{ t('auth.password') }}</label>
          <input id="mount-password" v-model="form.password" type="password" autocomplete="new-password" />
          <label for="mount-creds-file">{{ t('mounts.credentialsFile') }}</label>
          <input id="mount-creds-file" v-model="form.credentials_file" type="text" />

          <div class="dialog-actions">
            <button class="btn" @click="closeAddDialog">{{ t('common.actions.cancel') }}</button>
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
