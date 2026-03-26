<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import ThemeSwitcher from '@/components/ThemeSwitcher.vue'

const { t } = useI18n()
const authStore = useAuthStore()

const now = ref(Date.now())
let timerInterval = null

onMounted(() => {
  timerInterval = setInterval(() => {
    now.value = Date.now()
  }, 1000)
})

onUnmounted(() => {
  if (timerInterval) clearInterval(timerInterval)
})

const remainingMinutes = computed(() => {
  if (!authStore.expiresAt) return null
  const diff = authStore.expiresAt - now.value
  if (diff <= 0) return 0
  return Math.ceil(diff / 60000)
})

const expiryWarning = computed(() => {
  return remainingMinutes.value !== null && remainingMinutes.value <= 5
})

function handleLogout() {
  authStore.logout()
}
</script>

<template>
  <header class="app-header">
    <div class="header-left">
      <span class="header-logo">[LOGO]</span>
      <span class="header-app-name">{{ t('app.name') }}</span>
    </div>
    <div class="header-right">
      <span class="header-username">{{ authStore.username }}</span>
      <span
        v-for="role in authStore.roles"
        :key="role"
        class="header-role-badge"
        :class="`badge-${role}`"
      >
        {{ role }}
      </span>
      <span
        v-if="remainingMinutes !== null"
        class="header-timer"
        :class="{ 'timer-warning': expiryWarning }"
        :aria-label="t('auth.sessionExpiresIn', remainingMinutes, { minutes: remainingMinutes })"
      >
        <span aria-hidden="true">⏱</span> {{ remainingMinutes }}m
      </span>
      <ThemeSwitcher />
      <button class="btn-logout" @click="handleLogout">{{ t('auth.logout') }}</button>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-md);
  height: var(--header-height);
  background: var(--color-bg-header);
  border-bottom: 1px solid var(--color-border);
}

.header-left {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.header-logo {
  font-size: var(--font-size-xs);
  color: var(--color-text-secondary);
  opacity: 0.5;
}

.header-app-name {
  font-weight: var(--font-weight-bold);
  font-size: var(--font-size-lg);
  color: var(--color-text-primary);
}

.header-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}

.header-username {
  font-weight: var(--font-weight-medium);
  color: var(--color-text-primary);
}

.header-role-badge {
  display: inline-block;
  padding: var(--space-xs) var(--space-sm);
  font-size: var(--font-size-xs);
  font-weight: var(--font-weight-bold);
  border-radius: 9999px;
  background: var(--color-badge-manager-bg);
  color: var(--color-badge-manager-text);
}

.badge-admin {
  background: var(--color-badge-admin-bg);
  color: var(--color-badge-admin-text);
}

.badge-manager {
  background: var(--color-badge-manager-bg);
  color: var(--color-badge-manager-text);
}

.badge-processor {
  background: var(--color-badge-processor-bg);
  color: var(--color-badge-processor-text);
}

.badge-auditor {
  background: var(--color-badge-auditor-bg);
  color: var(--color-badge-auditor-text);
}

.header-timer {
  font-size: var(--font-size-sm);
  color: var(--color-text-primary);
}

.timer-warning {
  color: var(--color-danger);
  font-weight: var(--font-weight-bold);
}

.btn-logout {
  padding: var(--space-xs) var(--space-sm);
  border: 1px solid var(--color-border);
  border-radius: var(--border-radius);
  background: transparent;
  color: var(--color-text-primary);
  cursor: pointer;
  font-size: var(--font-size-sm);
}

.btn-logout:hover {
  background: var(--color-bg-hover);
}
</style>
