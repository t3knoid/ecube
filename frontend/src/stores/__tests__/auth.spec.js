import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore, TokenError } from '@/stores/auth.js'
import * as authApi from '@/api/auth.js'

// Helper: create a valid JWT-like token with a given payload
function makeToken(payload) {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const body = btoa(JSON.stringify(payload))
  const sig = btoa('fakesig')
  return `${header}.${body}.${sig}`
}

// Helper: create a JWT with unpadded Base64URL segments (no trailing '=')
function makeUnpaddedToken(payload) {
  const encode = (obj) =>
    btoa(JSON.stringify(obj))
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '')
  const header = encode({ alg: 'HS256', typ: 'JWT' })
  const body = encode(payload)
  const sig = encode({ fake: true })
  return `${header}.${body}.${sig}`
}

// Helper: current time in epoch seconds
function nowSec() {
  return Math.floor(Date.now() / 1000)
}

// Helper: create a store, inject a token into sessionStorage and initialize
function initWithToken(payload, { unpadded = false } = {}) {
  const store = useAuthStore()
  const jwt = unpadded ? makeUnpaddedToken(payload) : makeToken(payload)
  sessionStorage.setItem('ecube_token', jwt)
  store.initialize()
  return { store, jwt }
}

describe('Auth Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionStorage.clear()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.clearAllTimers()
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
    const { store } = initWithToken({ sub: 'frank', roles: ['admin'], groups: [], exp: nowSec() - 60 })
    expect(store.isAuthenticated).toBe(false)
  })

  it('initialize restores valid token from sessionStorage', () => {
    const { store } = initWithToken({ sub: 'jordan', roles: ['processor'], groups: ['ops'], exp: nowSec() + 3600 })
    expect(store.isAuthenticated).toBe(true)
    expect(store.username).toBe('jordan')
    expect(store.roles).toEqual(['processor'])
    expect(store.groups).toEqual(['ops'])
  })

  it('hasRole checks single role membership', () => {
    const { store } = initWithToken({ sub: 'frank', roles: ['admin', 'manager'], groups: [], exp: nowSec() + 3600 })
    expect(store.hasRole('admin')).toBe(true)
    expect(store.hasRole('auditor')).toBe(false)
  })

  it('hasAnyRole checks multiple roles', () => {
    const { store } = initWithToken({ sub: 'frank', roles: ['auditor'], groups: [], exp: nowSec() + 3600 })
    expect(store.hasAnyRole(['admin', 'auditor'])).toBe(true)
    expect(store.hasAnyRole(['admin', 'manager'])).toBe(false)
  })

  it('clearAuth resets all state and sessionStorage', () => {
    const { store } = initWithToken({ sub: 'frank', roles: ['admin'], groups: [], exp: nowSec() + 3600 })
    expect(store.isAuthenticated).toBe(true)

    store.clearAuth()
    expect(store.isAuthenticated).toBe(false)
    expect(store.token).toBeNull()
    expect(store.username).toBeNull()
    expect(store.roles).toEqual([])
    expect(sessionStorage.getItem('ecube_token')).toBeNull()
  })

  it('logout delegates to clearAuth without navigation', () => {
    const { store } = initWithToken({ sub: 'frank', roles: ['admin'], groups: [], exp: nowSec() + 3600 })
    expect(store.isAuthenticated).toBe(true)

    store.logout()
    expect(store.isAuthenticated).toBe(false)
    expect(store.token).toBeNull()
    expect(sessionStorage.getItem('ecube_token')).toBeNull()
  })

  it('checkExpiry returns true and clears auth when token expired', () => {
    const { store } = initWithToken({ sub: 'frank', roles: ['admin'], groups: [], exp: nowSec() + 10 })
    expect(store.isAuthenticated).toBe(true)

    // Advance time past expiry
    vi.advanceTimersByTime(15000)
    const expired = store.checkExpiry()
    expect(expired).toBe(true)
    expect(store.isAuthenticated).toBe(false)
  })

  it('decodes unpadded Base64URL tokens correctly', () => {
    const { store } = initWithToken(
      { sub: 'griffin', roles: ['manager'], groups: ['team-a'], exp: nowSec() + 3600 },
      { unpadded: true },
    )
    expect(store.isAuthenticated).toBe(true)
    expect(store.username).toBe('griffin')
    expect(store.roles).toEqual(['manager'])
    expect(store.groups).toEqual(['team-a'])
  })

  it('login() calls postLogin and applies the returned token', async () => {
    const store = useAuthStore()
    const jwt = makeToken({ sub: 'alba', roles: ['processor', 'auditor'], groups: ['ops'], exp: nowSec() + 3600 })

    const spy = vi.spyOn(authApi, 'postLogin').mockResolvedValue({
      data: { access_token: jwt },
    })

    await store.login('alba', 's3cret')

    expect(spy).toHaveBeenCalledWith('alba', 's3cret')
    expect(store.isAuthenticated).toBe(true)
    expect(store.username).toBe('alba')
    expect(store.roles).toEqual(['processor', 'auditor'])
    expect(store.groups).toEqual(['ops'])
    expect(sessionStorage.getItem('ecube_token')).toBe(jwt)

    spy.mockRestore()
  })

  it('login() surfaces API errors to the caller', async () => {
    const store = useAuthStore()
    const error = new Error('Request failed')
    error.response = { status: 401, data: { detail: 'Invalid username or password.' } }

    vi.spyOn(authApi, 'postLogin').mockRejectedValue(error)

    await expect(store.login('bad', 'creds')).rejects.toThrow('Request failed')
    expect(store.isAuthenticated).toBe(false)
    expect(store.token).toBeNull()

    vi.restoreAllMocks()
  })

  it('login() throws TokenError when access_token is not a string', async () => {
    const store = useAuthStore()
    vi.spyOn(authApi, 'postLogin').mockResolvedValue({ data: { access_token: 12345 } })

    await expect(store.login('frank', 'pass')).rejects.toThrow(TokenError)
    await expect(store.login('frank', 'pass')).rejects.toThrow('not a string')
    expect(store.isAuthenticated).toBe(false)

    vi.restoreAllMocks()
  })

  it('login() throws TokenError when access_token is malformed', async () => {
    const store = useAuthStore()
    vi.spyOn(authApi, 'postLogin').mockResolvedValue({ data: { access_token: 'not-a-jwt' } })

    await expect(store.login('frank', 'pass')).rejects.toThrow(TokenError)
    await expect(store.login('frank', 'pass')).rejects.toThrow('malformed token')
    expect(store.isAuthenticated).toBe(false)

    vi.restoreAllMocks()
  })

  it('login() throws TokenError when payload is not valid JSON', async () => {
    const store = useAuthStore()
    // Build a three-segment token whose payload is not valid JSON
    const header = btoa(JSON.stringify({ alg: 'HS256' }))
    const badPayload = btoa('not-json')
    const sig = btoa('sig')
    vi.spyOn(authApi, 'postLogin').mockResolvedValue({
      data: { access_token: `${header}.${badPayload}.${sig}` },
    })

    await expect(store.login('frank', 'pass')).rejects.toThrow(TokenError)
    await expect(store.login('frank', 'pass')).rejects.toThrow('unreadable payload')
    expect(store.isAuthenticated).toBe(false)

    vi.restoreAllMocks()
  })

  it('initialize() silently logs out when stored token is malformed', () => {
    const store = useAuthStore()
    sessionStorage.setItem('ecube_token', 'garbage')
    store.initialize()
    expect(store.isAuthenticated).toBe(false)
    expect(store.token).toBeNull()
  })
})
