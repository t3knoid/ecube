import { describe, expect, it, vi } from 'vitest'

describe('routes.js — API_BASE resolution', () => {
  it('defaults to /api when VITE_API_BASE_URL is not set', async () => {
    vi.stubEnv('VITE_API_BASE_URL', '')
    vi.stubEnv('BASE_URL', '/')
    const { API_BASE } = await import('@/constants/routes.js')
    expect(API_BASE).toBe('/api')
    vi.unstubAllEnvs()
  })

  it('uses VITE_API_BASE_URL when set, stripping trailing slash', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.corp.local:8443/api/')
    vi.stubEnv('BASE_URL', '/')
    const { API_BASE } = await import('@/constants/routes.js')
    expect(API_BASE).toBe('https://api.corp.local:8443/api')
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('uses VITE_API_BASE_URL without trailing slash unchanged', async () => {
    vi.resetModules()
    vi.stubEnv('VITE_API_BASE_URL', 'https://api.corp.local:8443/api')
    vi.stubEnv('BASE_URL', '/')
    const { API_BASE } = await import('@/constants/routes.js')
    expect(API_BASE).toBe('https://api.corp.local:8443/api')
    vi.unstubAllEnvs()
    vi.resetModules()
  })
})
