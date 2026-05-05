import { afterEach, describe, expect, it, vi } from 'vitest'

async function loadRouter({ roles = [], initialized = true, demoModeEnabled = false } = {}) {
  vi.resetModules()

  const authStore = {
    isAuthenticated: true,
    expiredOnLoad: false,
    hasAnyRole: (requiredRoles) => requiredRoles.some((role) => roles.includes(role)),
    checkExpiry: () => false,
    clearAuth: vi.fn(),
  }

  vi.doMock('@/stores/auth.js', () => ({
    useAuthStore: () => authStore,
  }))
  vi.doMock('@/api/auth.js', () => ({
    getPublicAuthConfig: vi.fn().mockResolvedValue({ demo_mode_enabled: demoModeEnabled }),
  }))
  vi.doMock('@/api/setup.js', () => ({
    getSetupStatus: vi.fn().mockResolvedValue({ initialized }),
  }))
  vi.doMock('@/api/telemetry.js', () => ({
    postUiNavigationTelemetry: vi.fn().mockResolvedValue(undefined),
  }))
  vi.doMock('@/utils/logger.js', () => ({
    logger: { debug: vi.fn() },
  }))

  const router = (await import('@/router/index.js')).default
  return { router }
}

afterEach(() => {
  window.history.replaceState({}, '', '/')
  vi.clearAllMocks()
  vi.resetModules()
})

describe('router configuration/admin guards', () => {
  it('allows navigation to login in demo mode before setup is marked initialized', async () => {
    const { router } = await loadRouter({ initialized: false, demoModeEnabled: true })

    await router.push({ name: 'login' })

    expect(router.currentRoute.value.name).toBe('login')
  })

  it('redirects login to setup when demo mode is not enabled and setup is incomplete', async () => {
    const { router } = await loadRouter({ initialized: false, demoModeEnabled: false })

    await router.push({ name: 'login' })

    expect(router.currentRoute.value.name).toBe('setup')
  })

  it('allows managers to access Configuration', async () => {
    const { router } = await loadRouter({ roles: ['manager'] })

    await router.push('/configuration')

    expect(router.currentRoute.value.name).toBe('configuration')
  })

  it('redirects managers away from Admin', async () => {
    const { router } = await loadRouter({ roles: ['manager'] })

    await router.push('/admin')

    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it('allows admins to access Admin', async () => {
    const { router } = await loadRouter({ roles: ['admin'] })

    await router.push('/admin')

    expect(router.currentRoute.value.name).toBe('admin')
  })

  it('redirects auditors away from Configuration', async () => {
    const { router } = await loadRouter({ roles: ['auditor'] })

    await router.push('/configuration')

    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it('allows auditors to access Mounts', async () => {
    const { router } = await loadRouter({ roles: ['auditor'] })

    await router.push('/mounts')

    expect(router.currentRoute.value.name).toBe('mounts')
  })

  it('allows processors to access Mounts', async () => {
    const { router } = await loadRouter({ roles: ['processor'] })

    await router.push('/mounts')

    expect(router.currentRoute.value.name).toBe('mounts')
  })
})