import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth.js'
import { getSetupStatus } from '@/api/setup.js'
import { AUDIT_ROLES, USERS_ROLES } from '@/constants/roles.js'
import { EXPIRED_QUERY_KEY, EXPIRED_QUERY_VALUE } from '@/constants/auth.js'
import AppShell from '@/components/layout/AppShell.vue'
import { logger } from '@/utils/logger.js'
import { postUiNavigationTelemetry } from '@/api/telemetry.js'

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
        meta: { roles: AUDIT_ROLES },
      },
      {
        path: 'users',
        name: 'users',
        component: () => import('@/views/UsersView.vue'),
        meta: { roles: USERS_ROLES },
      },
      {
        path: 'configuration',
        name: 'configuration',
        component: () => import('@/views/ConfigurationView.vue'),
        meta: { roles: USERS_ROLES },
      },
      {
        path: 'system',
        name: 'system',
        component: () => import('@/views/SystemView.vue'),
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: { name: 'dashboard' },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

let systemInitialized = false

router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  logger.debug('UI_NAVIGATION_ATTEMPT', {
    to: to?.fullPath || to?.path || '(unknown)',
    route_name: to?.name || '(unnamed)',
  })

  // Re-check setup status on every navigation until the system is initialized.
  // Once initialized it cannot revert, so we stop polling.
  if (!systemInitialized) {
    try {
      const setupStatus = await getSetupStatus()
      systemInitialized = setupStatus.initialized === true
    } catch {
      // Fail closed: if the backend is unreachable, treat as not initialized
      // so the user is redirected to /setup rather than bypassing it
      systemInitialized = false
    }
  }

  // Redirect to setup if system not initialized
  if (!systemInitialized && to.name !== 'setup') {
    const currentTarget = to?.fullPath || to?.path || '(unknown)'
    logger.debug('UI_NAVIGATION_REDIRECT', {
      reason: 'system_not_initialized',
      to: currentTarget,
      redirect_to: '/setup',
    })
    void postUiNavigationTelemetry({
      event_type: 'UI_NAVIGATION_REDIRECT',
      reason: 'system_not_initialized',
      source: currentTarget,
      destination: '/setup',
      route_name: 'setup',
    })
    return { name: 'setup' }
  }

  // Redirect away from setup if system is already initialized
  if (systemInitialized && to.name === 'setup') {
    const destination = authStore.isAuthenticated ? '/' : '/login'
    logger.debug('UI_NAVIGATION_REDIRECT', {
      reason: 'setup_already_initialized',
      to: '/setup',
      redirect_to: destination,
    })
    void postUiNavigationTelemetry({
      event_type: 'UI_NAVIGATION_REDIRECT',
      reason: 'setup_already_initialized',
      source: '/setup',
      destination,
      route_name: authStore.isAuthenticated ? 'dashboard' : 'login',
    })
    return authStore.isAuthenticated ? { name: 'dashboard' } : { name: 'login' }
  }

  // Allow unauthenticated routes
  if (to.meta.requiresAuth === false) {
    return true
  }

  // Check if the route (or its parent) requires auth
  const needsAuth = to.matched.some((record) => record.meta.requiresAuth)
  if (needsAuth && !authStore.isAuthenticated) {
    // Check if token expired at runtime, or was already expired when the app loaded
    const wasExpired = authStore.checkExpiry() || authStore.expiredOnLoad
    if (authStore.expiredOnLoad) {
      authStore.expiredOnLoad = false
    }
    if (!wasExpired) {
      // Not an expiry — just unauthenticated; ensure storage is clean
      authStore.clearAuth()
    }
    const requestedPath = to?.fullPath || to?.path || '(unknown)'
    logger.debug('UI_NAVIGATION_REDIRECT', {
      reason: wasExpired ? 'token_expired' : 'authentication_required',
      to: requestedPath,
      redirect_to: '/login',
    })
    void postUiNavigationTelemetry({
      event_type: 'UI_NAVIGATION_REDIRECT',
      reason: wasExpired ? 'token_expired' : 'authentication_required',
      source: requestedPath,
      destination: '/login',
      route_name: 'login',
    })
    return { name: 'login', query: wasExpired ? { [EXPIRED_QUERY_KEY]: EXPIRED_QUERY_VALUE } : {} }
  }

  // Role-based guard
  const requiredRoles = to.meta.roles
  if (requiredRoles && !authStore.hasAnyRole(requiredRoles)) {
    const requestedPath = to?.fullPath || to?.path || '(unknown)'
    logger.debug('UI_NAVIGATION_REDIRECT', {
      reason: 'insufficient_roles',
      to: requestedPath,
      redirect_to: '/',
    })
    void postUiNavigationTelemetry({
      event_type: 'UI_NAVIGATION_REDIRECT',
      reason: 'insufficient_roles',
      source: requestedPath,
      destination: '/',
      route_name: 'dashboard',
    })
    return { name: 'dashboard' }
  }

  return true
})

export default router
