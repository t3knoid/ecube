<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getUsers, setUserRoles, deleteUserRoles } from '@/api/users.js'
import {
  createOsUser,
  getOsUsers,
  resetOsUserPassword,
  getOsGroups,
  createOsGroup,
  deleteOsGroup,
} from '@/api/admin.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'
import ConfirmDialog from '@/components/common/ConfirmDialog.vue'

const { t } = useI18n()

const roles = ['admin', 'manager', 'processor', 'auditor']

const activeTab = ref('roles')
const loading = ref(false)
const saving = ref(false)
const error = ref('')

const users = ref([])
const osUsers = ref([])
const osGroups = ref([])
const passwordResetTarget = ref('')
const passwordResetValue = ref('')
const showDeleteGroupDialog = ref(false)
const deleteGroupTarget = ref(null)

const userPage = ref(1)
const osUserPage = ref(1)
const osGroupPage = ref(1)
const pageSize = ref(10)

const createUserDialog = ref(false)
const createUserForm = ref({
  username: '',
  password: '',
  groups: 'ecube-processors',
  roles: [],
})

const createGroupInput = ref('ecube-')

const roleColumns = computed(() => [
  { key: 'username', label: t('auth.username') },
  { key: 'roles', label: t('users.roles') },
  { key: 'actions', label: t('common.actions.save'), align: 'center' },
])

const osUserColumns = computed(() => [
  { key: 'username', label: t('auth.username') },
  { key: 'groups', label: t('users.groups') },
  { key: 'actions', label: t('common.actions.edit'), align: 'center' },
])

const osGroupColumns = computed(() => [
  { key: 'name', label: t('users.groupName') },
  { key: 'members', label: t('users.members') },
  { key: 'actions', label: t('common.actions.delete'), align: 'center' },
])

const pagedUsers = computed(() => {
  const start = (userPage.value - 1) * pageSize.value
  return users.value.slice(start, start + pageSize.value)
})

const pagedOsUsers = computed(() => {
  const start = (osUserPage.value - 1) * pageSize.value
  return osUsers.value.slice(start, start + pageSize.value)
})

const pagedOsGroups = computed(() => {
  const start = (osGroupPage.value - 1) * pageSize.value
  return osGroups.value.slice(start, start + pageSize.value)
})

function normalizeRoleSelection(value) {
  return roles.filter((role) => value.includes(role))
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [roleResult, osUserResult, osGroupResult] = await Promise.allSettled([
      getUsers(),
      getOsUsers(),
      getOsGroups(),
    ])
    users.value = roleResult.status === 'fulfilled' ? roleResult.value.users || [] : []
    osUsers.value = osUserResult.status === 'fulfilled' ? osUserResult.value.users || [] : []
    osGroups.value = osGroupResult.status === 'fulfilled' ? osGroupResult.value.groups || [] : []
  } catch {
    error.value = t('common.errors.networkError')
  } finally {
    loading.value = false
  }
}

async function saveRoles(user) {
  saving.value = true
  error.value = ''
  try {
    const roleList = normalizeRoleSelection(user.roles || [])
    if (roleList.length === 0) {
      await deleteUserRoles(user.username)
      user.roles = []
    } else {
      const updated = await setUserRoles(user.username, { roles: roleList })
      user.roles = updated.roles
    }
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

async function submitCreateOsUser() {
  saving.value = true
  error.value = ''
  try {
    const payload = {
      username: createUserForm.value.username.trim(),
      password: createUserForm.value.password,
      groups: createUserForm.value.groups
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean),
      roles: normalizeRoleSelection(createUserForm.value.roles),
    }
    await createOsUser(payload)
    createUserDialog.value = false
    createUserForm.value = { username: '', password: '', groups: 'ecube-processors', roles: [] }
    await loadAll()
  } catch {
    error.value = t('common.errors.validationFailed')
  } finally {
    saving.value = false
  }
}

async function submitResetPassword(username) {
  if (!passwordResetValue.value) return
  saving.value = true
  error.value = ''
  try {
    await resetOsUserPassword(username, { password: passwordResetValue.value })
    passwordResetTarget.value = ''
    passwordResetValue.value = ''
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

async function submitCreateGroup() {
  const name = createGroupInput.value.trim()
  if (!name.startsWith('ecube-')) {
    error.value = t('users.groupPrefixError')
    return
  }
  saving.value = true
  error.value = ''
  try {
    await createOsGroup({ name })
    createGroupInput.value = 'ecube-'
    await loadAll()
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

async function submitDeleteGroup() {
  if (!deleteGroupTarget.value) return
  saving.value = true
  error.value = ''
  try {
    await deleteOsGroup(deleteGroupTarget.value.name)
    deleteGroupTarget.value = null
    showDeleteGroupDialog.value = false
    await loadAll()
  } catch {
    error.value = t('common.errors.requestConflict')
  } finally {
    saving.value = false
  }
}

onMounted(loadAll)
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('users.title') }}</h1>
      <button class="btn" @click="loadAll">{{ t('common.actions.refresh') }}</button>
    </header>

    <div class="tabs">
      <button class="btn" :class="{ active: activeTab === 'roles' }" @click="activeTab = 'roles'">{{ t('users.roleTab') }}</button>
      <button class="btn" :class="{ active: activeTab === 'os-users' }" @click="activeTab = 'os-users'">{{ t('users.osUsersTab') }}</button>
      <button class="btn" :class="{ active: activeTab === 'os-groups' }" @click="activeTab = 'os-groups'">{{ t('users.osGroupsTab') }}</button>
    </div>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <article v-if="activeTab === 'roles'" class="panel">
      <DataTable :columns="roleColumns" :rows="pagedUsers" row-key="username" :empty-text="t('users.empty')">
        <template #cell-roles="{ row }">
          <div class="role-grid">
            <label v-for="role in roles" :key="`${row.username}-${role}`">
              <input v-model="row.roles" type="checkbox" :value="role" />
              {{ role }}
            </label>
          </div>
        </template>
        <template #cell-actions="{ row }">
          <button class="btn btn-primary" :disabled="saving" @click="saveRoles(row)">{{ t('common.actions.save') }}</button>
        </template>
      </DataTable>
      <Pagination v-model:page="userPage" :page-size="pageSize" :total="users.length" />
    </article>

    <article v-else-if="activeTab === 'os-users'" class="panel">
      <div class="panel-actions">
        <button class="btn btn-primary" @click="createUserDialog = true">{{ t('users.createOsUser') }}</button>
      </div>
      <DataTable :columns="osUserColumns" :rows="pagedOsUsers" row-key="username" :empty-text="t('users.emptyOsUsers')">
        <template #cell-groups="{ row }">{{ (row.groups || []).join(', ') }}</template>
        <template #cell-actions="{ row }">
          <div class="inline-reset">
            <button class="btn" @click="passwordResetTarget = row.username">{{ t('users.resetPassword') }}</button>
            <div v-if="passwordResetTarget === row.username" class="inline-form">
              <input v-model="passwordResetValue" type="password" :placeholder="t('auth.password')" autocomplete="new-password" />
              <button class="btn btn-primary" @click="submitResetPassword(row.username)">{{ t('common.actions.save') }}</button>
            </div>
          </div>
        </template>
      </DataTable>
      <Pagination v-model:page="osUserPage" :page-size="pageSize" :total="osUsers.length" />
    </article>

    <article v-else class="panel">
      <div class="panel-actions">
        <input v-model="createGroupInput" type="text" :placeholder="t('users.groupName')" />
        <button class="btn btn-primary" @click="submitCreateGroup">{{ t('users.createGroup') }}</button>
      </div>
      <DataTable :columns="osGroupColumns" :rows="pagedOsGroups" row-key="name" :empty-text="t('users.emptyGroups')">
        <template #cell-members="{ row }">{{ (row.members || []).join(', ') }}</template>
        <template #cell-actions="{ row }">
          <button class="btn btn-danger" @click="deleteGroupTarget = row; showDeleteGroupDialog = true">{{ t('common.actions.delete') }}</button>
        </template>
      </DataTable>
      <Pagination v-model:page="osGroupPage" :page-size="pageSize" :total="osGroups.length" />
    </article>

    <teleport to="body">
      <div v-if="createUserDialog" class="dialog-overlay" @click.self="createUserDialog = false">
        <div class="dialog-panel" role="dialog" aria-modal="true">
          <h2>{{ t('users.createOsUser') }}</h2>
          <label>{{ t('auth.username') }}</label>
          <input v-model="createUserForm.username" type="text" />
          <label>{{ t('auth.password') }}</label>
          <input v-model="createUserForm.password" type="password" autocomplete="new-password" />
          <label>{{ t('users.groupsCsv') }}</label>
          <input v-model="createUserForm.groups" type="text" />
          <label>{{ t('users.roles') }}</label>
          <div class="role-grid">
            <label v-for="role in roles" :key="`new-${role}`">
              <input v-model="createUserForm.roles" type="checkbox" :value="role" />
              {{ role }}
            </label>
          </div>

          <div class="dialog-actions">
            <button class="btn" @click="createUserDialog = false">{{ t('common.actions.cancel') }}</button>
            <button class="btn btn-primary" :disabled="saving" @click="submitCreateOsUser">{{ t('common.actions.create') }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <ConfirmDialog
      v-model="showDeleteGroupDialog"
      :title="t('users.deleteGroupTitle')"
      :message="t('users.deleteGroupBody')"
      :confirm-label="t('common.actions.delete')"
      :cancel-label="t('common.actions.cancel')"
      :busy="saving"
      dangerous
      @confirm="submitDeleteGroup"
    />
  </section>
</template>

<style scoped>
.view-root {
  display: grid;
  gap: var(--space-md);
}

.header-row,
.tabs,
.panel-actions,
.role-grid,
.inline-form,
.dialog-actions {
  display: flex;
  gap: var(--space-sm);
}

.header-row {
  justify-content: space-between;
  align-items: center;
}

.tabs,
.panel-actions,
.role-grid,
.inline-form {
  flex-wrap: wrap;
}

.panel {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
  display: grid;
  gap: var(--space-sm);
}

input,
.btn {
  border: 1px solid var(--color-border);
  background: var(--color-bg-input);
  color: var(--color-text-primary);
  border-radius: var(--border-radius);
  padding: var(--space-xs) var(--space-sm);
}

.btn {
  cursor: pointer;
}

.btn.active {
  background: var(--color-bg-selected);
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
  justify-content: flex-end;
  margin-top: var(--space-sm);
}
</style>
