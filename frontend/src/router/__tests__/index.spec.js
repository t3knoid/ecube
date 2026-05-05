import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  authStore: {
    isAuthenticated: false,
    expiredOnLoad: false,
    checkExpiry: vi.fn(() => false),
    clearAuth: vi.fn(),
    hasAnyRole: vi.fn(() => true),
  },
  getSetupStatus: vi.fn(),
  getPublicAuthConfig: vi.fn(),
  postUiNavigationTelemetry: vi.fn(),
  logger: {
    debug: vi.fn(),
  },
}))

vi.mock('@/stores/auth.js', () => ({
  useAuthStore: () => mocks.authStore,
}))

vi.mock('@/api/setup.js', () => ({
  getSetupStatus: (...args) => mocks.getSetupStatus(...args),
}))

vi.mock('@/api/auth.js', () => ({
  getPublicAuthConfig: (...args) => mocks.getPublicAuthConfig(...args),
}))

vi.mock('@/api/telemetry.js', () => ({
  postUiNavigationTelemetry: (...args) => mocks.postUiNavigationTelemetry(...args),
}))

vi.mock('@/utils/logger.js', () => ({
  logger: mocks.logger,
}))

async function loadRouter() {
  vi.resetModules()
  const module = await import('@/router/index.js')
  return module.default
}

describe('router demo login access', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/')
    mocks.authStore.isAuthenticated = false
    mocks.authStore.expiredOnLoad = false
    mocks.authStore.checkExpiry.mockReset()
    mocks.authStore.checkExpiry.mockReturnValue(false)
    mocks.authStore.clearAuth.mockReset()
    mocks.authStore.hasAnyRole.mockReset()
    mocks.authStore.hasAnyRole.mockReturnValue(true)
    mocks.getSetupStatus.mockReset()
    mocks.getPublicAuthConfig.mockReset()
    mocks.postUiNavigationTelemetry.mockReset()
    mocks.logger.debug.mockReset()
  })

  it('allows navigation to login in demo mode before setup is marked initialized', async () => {
    mocks.getSetupStatus.mockResolvedValue({ initialized: false })
    mocks.getPublicAuthConfig.mockResolvedValue({ demo_mode_enabled: true })

    const router = await loadRouter()
    await router.push({ name: 'login' })

    expect(router.currentRoute.value.name).toBe('login')
  })

  it('redirects login to setup when demo mode is not enabled and setup is incomplete', async () => {
    mocks.getSetupStatus.mockResolvedValue({ initialized: false })
    mocks.getPublicAuthConfig.mockResolvedValue({ demo_mode_enabled: false })

    const router = await loadRouter()
    await router.push({ name: 'login' })

    expect(router.currentRoute.value.name).toBe('setup')
  })
})