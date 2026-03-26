<script setup>
import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth.js'
import { AUDIT_ROLES, USERS_ROLES } from '@/constants/roles.js'

const authStore = useAuthStore()

const navItems = [
  { label: 'Dashboard', to: '/', roles: null },
  { label: 'Drives', to: '/drives', roles: null },
  { label: 'Mounts', to: '/mounts', roles: null },
  { label: 'Jobs', to: '/jobs', roles: null },
  { label: 'Audit', to: '/audit', roles: AUDIT_ROLES },
  { label: 'System', to: '/system', roles: null },
]

const adminItems = [
  { label: 'Users', to: '/users', roles: USERS_ROLES },
]

function isVisible(item) {
  if (!item.roles) return true
  return authStore.hasAnyRole(item.roles)
}

const visibleNav = computed(() => navItems.filter(isVisible))
const visibleAdmin = computed(() => adminItems.filter(isVisible))
</script>

<template>
  <aside class="app-sidebar">
    <nav>
      <RouterLink
        v-for="item in visibleNav"
        :key="item.to"
        :to="item.to"
        class="sidebar-link"
        :active-class="item.to === '/' ? '' : 'sidebar-link-active'"
        :exact-active-class="item.to === '/' ? 'sidebar-link-active' : ''"
      >
        {{ item.label }}
      </RouterLink>

      <hr v-if="visibleAdmin.length" class="sidebar-divider" />

      <RouterLink
        v-for="item in visibleAdmin"
        :key="item.to"
        :to="item.to"
        class="sidebar-link"
        :active-class="item.to === '/' ? '' : 'sidebar-link-active'"
        :exact-active-class="item.to === '/' ? 'sidebar-link-active' : ''"
      >
        {{ item.label }}
      </RouterLink>
    </nav>
  </aside>
</template>

<style scoped>
.app-sidebar {
  width: 200px;
  min-width: 200px;
  background: var(--color-background-soft);
  border-right: 1px solid var(--color-border);
  padding: 1rem 0;
  overflow-y: auto;
}

.app-sidebar nav {
  display: flex;
  flex-direction: column;
}

.sidebar-link {
  display: block;
  padding: 0.625rem 1.25rem;
  color: var(--color-text);
  text-decoration: none;
  font-size: 0.9rem;
  transition: background 0.15s;
}

.sidebar-link:hover {
  background: var(--color-background-mute);
}

.sidebar-link-active {
  font-weight: 700;
  color: var(--color-heading);
  background: var(--color-background-mute);
}

.sidebar-divider {
  margin: 0.5rem 1rem;
  border: none;
  border-top: 1px solid var(--color-border);
}
</style>
