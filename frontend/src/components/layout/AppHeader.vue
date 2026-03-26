<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth.js'

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
      <span class="header-app-name">ECUBE</span>
    </div>
    <div class="header-right">
      <span class="header-username">{{ authStore.username }}</span>
      <span
        v-for="role in authStore.roles"
        :key="role"
        class="header-role-badge"
      >
        {{ role }}
      </span>
      <span
        v-if="remainingMinutes !== null"
        class="header-timer"
        :class="{ 'timer-warning': expiryWarning }"
      >
        ⏱ {{ remainingMinutes }}m
      </span>
      <button class="btn-logout" @click="handleLogout">Log Out</button>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 1rem;
  height: 56px;
  background: var(--color-background-soft);
  border-bottom: 1px solid var(--color-border);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.header-logo {
  font-size: 0.75rem;
  color: var(--color-text);
  opacity: 0.5;
}

.header-app-name {
  font-weight: 700;
  font-size: 1.125rem;
  color: var(--color-heading);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.header-username {
  font-weight: 600;
  color: var(--color-heading);
}

.header-role-badge {
  display: inline-block;
  padding: 0.125rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 600;
  border-radius: 9999px;
  background: #dbeafe;
  color: #1d4ed8;
}

.header-timer {
  font-size: 0.85rem;
  color: var(--color-text);
}

.timer-warning {
  color: #dc2626;
  font-weight: 700;
}

.btn-logout {
  padding: 0.375rem 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: 4px;
  background: transparent;
  color: var(--color-text);
  cursor: pointer;
  font-size: 0.875rem;
}

.btn-logout:hover {
  background: var(--color-background-mute);
}
</style>
