import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth.js'

// Helper: create a valid JWT-like token with a given payload
function makeToken(payload) {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = btoa(JSON.stringify(payload))
  const sig = btoa('fakesig')
  return `${header}.${body}.${sig}`
}

describe('Auth Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('starts unauthenticated', () => {
    const store = useAuthStore()
    expect(store.isAuthenticated).toBe(false)
    expect(store.token).toBeNull()
    expect(store.username).toBeNull()
    expect(store.roles).toEqual([])
    expect(store.groups).toEqual([])
  })

  it('isAuthenticated returns false when token is expired', () => {
    const store = useAuthStore()
    const pastExp = Math.floor(Date.now() / 1000) - 60 // 1 minute ago
    const jwt = makeToken({ sub: 'alice', roles: ['admin'], groups: [], exp: pastExp })
    sessionStorage.setItem('ecube_token', jwt)
    store.initialize()
    expect(store.isAuthenticated).toBe(false)
  })

  it('initialize restores valid token from sessionStorage', () => {
    const store = useAuthStore()
    const futureExp = Math.floor(Date.now() / 1000) + 3600
    const jwt = makeToken({ sub: 'bob', roles: ['processor'], groups: ['ops'], exp: futureExp })
    sessionStorage.setItem('ecube_token', jwt)
    store.initialize()
    expect(store.isAuthenticated).toBe(true)
    expect(store.username).toBe('bob')
    expect(store.roles).toEqual(['processor'])
    expect(store.groups).toEqual(['ops'])
  })

  it('hasRole checks single role membership', () => {
    const store = useAuthStore()
    const futureExp = Math.floor(Date.now() / 1000) + 3600
    const jwt = makeToken({ sub: 'alice', roles: ['admin', 'manager'], groups: [], exp: futureExp })
    sessionStorage.setItem('ecube_token', jwt)
    store.initialize()
    expect(store.hasRole('admin')).toBe(true)
    expect(store.hasRole('auditor')).toBe(false)
  })

  it('hasAnyRole checks multiple roles', () => {
    const store = useAuthStore()
    const futureExp = Math.floor(Date.now() / 1000) + 3600
    const jwt = makeToken({ sub: 'alice', roles: ['auditor'], groups: [], exp: futureExp })
    sessionStorage.setItem('ecube_token', jwt)
    store.initialize()
    expect(store.hasAnyRole(['admin', 'auditor'])).toBe(true)
    expect(store.hasAnyRole(['admin', 'manager'])).toBe(false)
  })

  it('logout clears all state and sessionStorage', () => {
    const store = useAuthStore()
    const futureExp = Math.floor(Date.now() / 1000) + 3600
    const jwt = makeToken({ sub: 'alice', roles: ['admin'], groups: [], exp: futureExp })
    sessionStorage.setItem('ecube_token', jwt)
    store.initialize()
    expect(store.isAuthenticated).toBe(true)

    store.logout()
    expect(store.isAuthenticated).toBe(false)
    expect(store.token).toBeNull()
    expect(store.username).toBeNull()
    expect(store.roles).toEqual([])
    expect(sessionStorage.getItem('ecube_token')).toBeNull()
  })

  it('checkExpiry returns true and logs out when token expired', () => {
    const store = useAuthStore()
    // Token expires 10 seconds from now
    const exp = Math.floor(Date.now() / 1000) + 10
    const jwt = makeToken({ sub: 'alice', roles: ['admin'], groups: [], exp })
    sessionStorage.setItem('ecube_token', jwt)
    store.initialize()
    expect(store.isAuthenticated).toBe(true)

    // Advance time past expiry
    vi.advanceTimersByTime(15000)
    const expired = store.checkExpiry()
    expect(expired).toBe(true)
    expect(store.isAuthenticated).toBe(false)
  })
})
