import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'
import { getSetupStatus } from '@/api/setup.js'
import AppShell from '@/components/AppShell.vue'

const routes = [
  {
    path: '/setup',
    name: 'setup',
    component: () => import('@/views/SetupWizardView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { requiresAuth: false },
  },
  {
    path: '/',
    component: AppShell,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
      },
      {
        path: 'drives',
        name: 'drives',
        component: () => import('@/views/DrivesView.vue'),
      },
      {
        path: 'drives/:id',
        name: 'drive-detail',
        component: () => import('@/views/DriveDetailView.vue'),
      },
      {
        path: 'mounts',
        name: 'mounts',
        component: () => import('@/views/MountsView.vue'),
      },
      {
        path: 'jobs',
        name: 'jobs',
        component: () => import('@/views/JobsView.vue'),
      },
      {
        path: 'jobs/:id',
        name: 'job-detail',
        component: () => import('@/views/JobDetailView.vue'),
      },
      {
        path: 'audit',
        name: 'audit',
        component: () => import('@/views/AuditView.vue'),
        meta: { roles: ['admin', 'manager', 'auditor'] },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/UsersView.vue'),
        meta: { roles: ['admin'] },
      },
      {
        path: 'system',
        name: 'system',
        component: () => import('@/views/SystemView.vue'),
      },
    ],
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

let systemInitialized = false

router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  // Re-check setup status on every navigation until the system is initialized.
  // Once initialized it cannot revert, so we stop polling.
  if (!systemInitialized) {
    try {
      const resp = await getSetupStatus()
      systemInitialized = resp.data.initialized === true
    } catch {
      // Fail closed: if the backend is unreachable, treat as not initialized
      // so the user is redirected to /setup rather than bypassing it
      systemInitialized = false
    }
  }

  // Redirect to setup if system not initialized
  if (!systemInitialized && to.name !== 'setup') {
    return { name: 'setup' }
  }

  // Redirect away from setup if system is already initialized
  if (systemInitialized && to.name === 'setup') {
    return authStore.isAuthenticated ? { name: 'dashboard' } : { name: 'login' }
  }

  // Allow unauthenticated routes
  if (to.meta.requiresAuth === false) {
    return true
  }

  // Check if the route (or its parent) requires auth
  const needsAuth = to.matched.some((record) => record.meta.requiresAuth)
  if (needsAuth && !authStore.isAuthenticated) {
    // Check if there's an expired token so we can show the banner
    const wasExpired = authStore.checkExpiry()
    if (!wasExpired) {
      // Not an expiry — just unauthenticated; ensure storage is clean
      authStore.logout()
    }
    // checkExpiry/logout already handle redirect via window.location.href,
    // but return login as fallback for the router
    return { name: 'login', query: wasExpired ? { expired: '1' } : {} }
  }

  // Role-based guard
  const requiredRoles = to.meta.roles
  if (requiredRoles && !authStore.hasAnyRole(requiredRoles)) {
    return { name: 'dashboard' }
  }

  return true
})

export default router
