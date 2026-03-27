<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { AUDIT_ROLES, USERS_ROLES } from '@/constants/roles.js'

const { t } = useI18n()
const authStore = useAuthStore()

const navItems = computed(() => [
  { label: t('nav.dashboard'), to: '/', roles: null },
  { label: t('nav.drives'), to: '/drives', roles: null },
  { label: t('nav.mounts'), to: '/mounts', roles: null },
  { label: t('nav.jobs'), to: '/jobs', roles: null },
  { label: t('nav.audit'), to: '/audit', roles: AUDIT_ROLES },
  { label: t('nav.system'), to: '/system', roles: null },
])

const adminItems = computed(() => [
  { label: t('nav.users'), to: '/users', roles: USERS_ROLES },
])

function isVisible(item) {
  if (!item.roles) return true
  return authStore.hasAnyRole(item.roles)
}

const visibleNav = computed(() => navItems.value.filter(isVisible))
const visibleAdmin = computed(() => adminItems.value.filter(isVisible))
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
  width: var(--sidebar-width);
  min-width: var(--sidebar-width);
  background: var(--color-bg-sidebar);
  border-right: 1px solid var(--color-border);
  padding: var(--space-md) 0;
  overflow-y: auto;
}

.app-sidebar nav {
  display: flex;
  flex-direction: column;
}

.sidebar-link {
  display: block;
  padding: var(--space-sm) var(--space-lg);
  color: var(--color-text-primary);
  text-decoration: none;
  font-size: var(--font-size-sm);
  transition: background 0.15s;
}

.sidebar-link:hover {
  background: var(--color-bg-hover);
}

.sidebar-link-active {
  font-weight: var(--font-weight-bold);
  color: var(--color-text-primary);
  background: var(--color-bg-selected);
}

.sidebar-divider {
  margin: var(--space-sm) var(--space-md);
  border: none;
  border-top: 1px solid var(--color-divider);
}
</style>
