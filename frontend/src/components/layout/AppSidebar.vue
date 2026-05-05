<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth.js'
import { AUDIT_ROLES, CONFIGURATION_ROLES, USERS_ROLES } from '@/constants/roles.js'

const props = defineProps({
  sidebarOpen: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['close-sidebar'])

const { t } = useI18n()
const authStore = useAuthStore()
const isMobileViewport = ref(false)
let mobileMediaQuery = null

const navItems = computed(() => [
  { label: t('nav.dashboard'), to: '/', roles: null },
  { label: t('nav.drives'), to: '/drives', roles: null },
  { label: t('nav.mounts'), to: '/mounts', roles: null },
  { label: t('nav.jobs'), to: '/jobs', roles: null },
  { label: t('nav.audit'), to: '/audit', roles: AUDIT_ROLES },
  { label: t('nav.system'), to: '/system', roles: null },
])

const adminItems = computed(() => [
  { label: t('nav.configuration'), to: '/configuration', roles: CONFIGURATION_ROLES },
  { label: t('nav.admin'), to: '/admin', roles: USERS_ROLES },
  { label: t('nav.users'), to: '/users', roles: USERS_ROLES },
])

function isVisible(item) {
  if (!item.roles) return true
  return authStore.hasAnyRole(item.roles)
}

const visibleNav = computed(() => navItems.value.filter(isVisible))
const visibleAdmin = computed(() => adminItems.value.filter(isVisible))
const isSidebarHidden = computed(() => isMobileViewport.value && !props.sidebarOpen)

function syncMobileViewport(event) {
  isMobileViewport.value = event.matches
}

onMounted(() => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  mobileMediaQuery = window.matchMedia('(max-width: 768px)')
  syncMobileViewport(mobileMediaQuery)

  if (typeof mobileMediaQuery.addEventListener === 'function') {
    mobileMediaQuery.addEventListener('change', syncMobileViewport)
    return
  }

  mobileMediaQuery.addListener(syncMobileViewport)
})

onUnmounted(() => {
  if (!mobileMediaQuery) return

  if (typeof mobileMediaQuery.removeEventListener === 'function') {
    mobileMediaQuery.removeEventListener('change', syncMobileViewport)
    return
  }

  mobileMediaQuery.removeListener(syncMobileViewport)
})
</script>

<template>
  <aside
    id="app-sidebar"
    class="app-sidebar"
    :class="{ 'app-sidebar-open': sidebarOpen }"
    :aria-hidden="isSidebarHidden ? 'true' : undefined"
    :inert="isSidebarHidden || undefined"
  >
    <nav>
      <RouterLink
        v-for="item in visibleNav"
        :key="item.to"
        :to="item.to"
        class="sidebar-link"
        :active-class="item.to === '/' ? '' : 'sidebar-link-active'"
        :exact-active-class="item.to === '/' ? 'sidebar-link-active' : ''"
        @click="emit('close-sidebar')"
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
        @click="emit('close-sidebar')"
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

@media (max-width: 768px) {
  .app-sidebar {
    position: fixed;
    top: var(--header-height);
    left: 0;
    bottom: 0;
    max-width: min(var(--sidebar-width), 90vw);
    transform: translateX(-100%);
    transition: transform 0.2s ease;
    z-index: 950;
    box-shadow: var(--shadow-lg);
  }

  .app-sidebar[aria-hidden='true'] {
    visibility: hidden;
    pointer-events: none;
  }

  .app-sidebar-open {
    transform: translateX(0);
  }
}
</style>
