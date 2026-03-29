<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { getUsers, setUserRoles, deleteUserRoles } from '@/api/users.js'
import {
  createOsUser,
  getOsUsers,
  resetOsUserPassword,
} from '@/api/admin.js'
import DataTable from '@/components/common/DataTable.vue'
import Pagination from '@/components/common/Pagination.vue'

const { t } = useI18n()

const roles = ['admin', 'manager', 'processor', 'auditor']

const loading = ref(false)
const saving = ref(false)
const error = ref('')

const osUsers = ref([])
const passwordResetTarget = ref('')
const passwordResetValue = ref('')

const osUserPage = ref(1)
const pageSize = ref(10)

const createUserDialog = ref(false)
const createUserForm = ref({
  username: '',
  password: '',
  roles: ['processor'],
})

const userColumns = computed(() => [
  { key: 'username', label: t('auth.username') },
  { key: 'roles', label: t('users.roles') },
  { key: 'reset', label: t('users.resetPassword'), align: 'center' },
])

const pagedOsUsers = computed(() => {
  const start = (osUserPage.value - 1) * pageSize.value
  return osUsers.value.slice(start, start + pageSize.value)
})

function roleLabel(role) {
  return t(`users.roleNames.${role}`)
}

function normalizeRoleSelection(value) {
  return roles.filter((role) => value.includes(role))
}

function rolesEqual(left, right) {
  const normalizedLeft = normalizeRoleSelection(left || [])
  const normalizedRight = normalizeRoleSelection(right || [])
  return normalizedLeft.length === normalizedRight.length
    && normalizedLeft.every((role, index) => role === normalizedRight[index])
}

function hasRoleChanges(user) {
  return !rolesEqual(user.roles, user.savedRoles)
}

async function loadAll() {
  loading.value = true
  error.value = ''
  try {
    const [roleResult, osUserResult] = await Promise.allSettled([
      getUsers(),
      getOsUsers(),
    ])
    const roleUsers = roleResult.status === 'fulfilled' ? roleResult.value.users || [] : []
    const roleMap = new Map(
      roleUsers.map((row) => [row.username, normalizeRoleSelection(row.roles || [])]),
    )
    const rawOsUsers = osUserResult.status === 'fulfilled' ? osUserResult.value.users || [] : []
    osUsers.value = rawOsUsers.map((row) => ({
      ...row,
      roles: roleMap.get(row.username) || [],
      savedRoles: roleMap.get(row.username) || [],
    }))
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
      user.roles = normalizeRoleSelection(updated.roles || [])
    }
    user.savedRoles = normalizeRoleSelection(user.roles || [])
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
      roles: normalizeRoleSelection(createUserForm.value.roles),
    }
    await createOsUser(payload)
    createUserDialog.value = false
    createUserForm.value = { username: '', password: '', roles: ['processor'] }
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

function cancelResetPassword() {
  passwordResetTarget.value = ''
  passwordResetValue.value = ''
}

onMounted(loadAll)
</script>

<template>
  <section class="view-root">
    <header class="header-row">
      <h1>{{ t('users.title') }}</h1>
      <button class="btn" @click="loadAll">{{ t('common.actions.refresh') }}</button>
    </header>

    <p v-if="loading" class="muted">{{ t('common.labels.loading') }}</p>
    <p v-if="error" class="error-banner">{{ error }}</p>

    <article class="panel">
      <div class="panel-actions">
        <button class="btn btn-primary" @click="createUserDialog = true">{{ t('users.createOsUser') }}</button>
      </div>
      <DataTable :columns="userColumns" :rows="pagedOsUsers" row-key="uid" :empty-text="t('users.emptyOsUsers')">
        <template #cell-roles="{ row }">
          <div class="role-cell">
            <div class="role-grid">
              <label v-for="role in roles" :key="`${row.username}-${role}`">
                <input v-model="row.roles" type="checkbox" :value="role" />
                {{ roleLabel(role) }}
              </label>
            </div>
            <button class="btn btn-primary" :disabled="saving || !hasRoleChanges(row)" @click="saveRoles(row)">{{ t('users.saveRoles') }}</button>
          </div>
        </template>
        <template #cell-reset="{ row }">
          <div class="inline-reset">
            <button class="btn" @click="passwordResetTarget = row.username">{{ t('users.resetPassword') }}</button>
            <div v-if="passwordResetTarget === row.username" class="inline-form">
              <input v-model="passwordResetValue" type="password" :placeholder="t('auth.password')" autocomplete="new-password" />
              <button class="btn btn-primary" @click="submitResetPassword(row.username)">{{ t('users.savePassword') }}</button>
              <button class="btn" @click="cancelResetPassword">{{ t('common.actions.cancel') }}</button>
            </div>
          </div>
        </template>
      </DataTable>
      <Pagination v-model:page="osUserPage" :page-size="pageSize" :total="osUsers.length" />
    </article>

    <teleport to="body">
      <div v-if="createUserDialog" class="dialog-overlay" @click.self="createUserDialog = false">
        <div class="dialog-panel" role="dialog" aria-modal="true">
          <h2>{{ t('users.createOsUser') }}</h2>
          <label>{{ t('auth.username') }}</label>
          <input v-model="createUserForm.username" type="text" />
          <label>{{ t('auth.password') }}</label>
          <input v-model="createUserForm.password" type="password" autocomplete="new-password" />
          <label>{{ t('users.roles') }}</label>
          <div class="role-grid">
            <label v-for="role in roles" :key="`new-${role}`">
              <input v-model="createUserForm.roles" type="checkbox" :value="role" />
              {{ roleLabel(role) }}
            </label>
          </div>

          <div class="dialog-actions">
            <button class="btn" @click="createUserDialog = false">{{ t('common.actions.cancel') }}</button>
            <button class="btn btn-primary" :disabled="saving" @click="submitCreateOsUser">{{ t('common.actions.create') }}</button>
          </div>
        </div>
      </div>
    </teleport>

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
.role-cell,
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
.role-cell,
.inline-form {
  flex-wrap: wrap;
}

.role-cell {
  justify-content: space-between;
  align-items: center;
}

.panel {
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius-lg);
  background: var(--color-bg-secondary);
  padding: var(--space-md);
  display: grid;
  gap: var(--space-sm);
}

input {
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
  justify-content: flex-end;
  margin-top: var(--space-sm);
}
</style>
