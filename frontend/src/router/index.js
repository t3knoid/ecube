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

let setupChecked = false
let systemInitialized = true

router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  // Check setup status once on first navigation
  if (!setupChecked) {
    setupChecked = true
    try {
      const resp = await getSetupStatus()
      systemInitialized = resp.data.initialized === true
    } catch {
      // If the endpoint is unreachable, assume initialized
      systemInitialized = true
    }
  }

  // Redirect to setup if system not initialized
  if (!systemInitialized && to.name !== 'setup') {
    return { name: 'setup' }
  }

  // Allow unauthenticated routes
  if (to.meta.requiresAuth === false) {
    return true
  }

  // Check if the route (or its parent) requires auth
  const needsAuth = to.matched.some((record) => record.meta.requiresAuth)
  if (needsAuth && !authStore.isAuthenticated) {
    return { name: 'login' }
  }

  // Role-based guard
  const requiredRoles = to.meta.roles
  if (requiredRoles && !authStore.hasAnyRole(requiredRoles)) {
    return { name: 'dashboard' }
  }

  return true
})

export default router
