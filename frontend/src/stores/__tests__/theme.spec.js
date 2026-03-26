import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useThemeStore } from '@/stores/theme.js'
import { STORAGE_THEME_KEY } from '@/constants/storage.js'

// Provide a simple localStorage mock for jsdom environments where
// the native implementation may be incomplete.
const storage = {}
const localStorageMock = {
  getItem: vi.fn((key) => storage[key] ?? null),
  setItem: vi.fn((key, value) => { storage[key] = String(value) }),
  removeItem: vi.fn((key) => { delete storage[key] }),
  clear: vi.fn(() => { Object.keys(storage).forEach((k) => delete storage[k]) }),
}

const originalLocalStorage = globalThis.localStorage

// Default manifest response used by most tests
const BUILT_IN_MANIFEST = [
  { name: 'default', label: 'Light' },
  { name: 'dark', label: 'Dark' },
]

function mockFetchManifest(data = BUILT_IN_MANIFEST) {
  globalThis.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(data) }),
  )
}

function mockFetchManifestFailure() {
  globalThis.fetch = vi.fn(() => Promise.resolve({ ok: false }))
}

describe('Theme Store', () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, writable: true, configurable: true })
    setActivePinia(createPinia())
    localStorageMock.clear()
    vi.clearAllMocks()
    mockFetchManifest()
    // Remove any injected link elements
    const link = document.getElementById('ecube-theme-stylesheet')
    if (link) link.remove()
  })

  afterEach(() => {
    Object.defineProperty(globalThis, 'localStorage', { value: originalLocalStorage, writable: true, configurable: true })
    const link = document.getElementById('ecube-theme-stylesheet')
    if (link) link.remove()
    delete globalThis.fetch
  })

  it('initializes with default theme', async () => {
    const store = useThemeStore()
    await store.initialize()
    expect(store.currentTheme).toBe('default')
  })

  it('lists built-in themes before manifest fetch', () => {
    const store = useThemeStore()
    expect(store.availableThemes).toEqual(BUILT_IN_MANIFEST)
  })

  it('loadTheme injects a <link> into <head>', () => {
    const store = useThemeStore()
    store.loadTheme('dark')
    const link = document.getElementById('ecube-theme-stylesheet')
    expect(link).not.toBeNull()
    expect(link.getAttribute('href')).toContain('themes/dark.css')
    expect(store.currentTheme).toBe('dark')
  })

  it('loadTheme replaces existing <link>', () => {
    const store = useThemeStore()
    store.loadTheme('default')
    store.loadTheme('dark')
    const links = document.querySelectorAll('#ecube-theme-stylesheet')
    expect(links.length).toBe(1)
    expect(links[0].getAttribute('href')).toContain('themes/dark.css')
  })

  it('persists theme preference to localStorage', () => {
    const store = useThemeStore()
    store.loadTheme('dark')
    expect(localStorage.getItem(STORAGE_THEME_KEY)).toBe('dark')
  })

  it('restores theme preference from localStorage', async () => {
    localStorage.setItem(STORAGE_THEME_KEY, 'dark')
    const store = useThemeStore()
    await store.initialize()
    expect(store.currentTheme).toBe('dark')
  })

  it('falls back to default for unknown saved theme', async () => {
    localStorage.setItem(STORAGE_THEME_KEY, 'nonexistent')
    const store = useThemeStore()
    await store.initialize()
    expect(store.currentTheme).toBe('default')
  })

  it('populates availableThemes from manifest', async () => {
    const custom = [
      { name: 'default', label: 'Light' },
      { name: 'dark', label: 'Dark' },
      { name: 'corporate', label: 'Corporate' },
    ]
    mockFetchManifest(custom)
    const store = useThemeStore()
    await store.initialize()
    expect(store.availableThemes).toEqual(custom)
  })

  it('allows custom theme from manifest to be selected', async () => {
    const custom = [
      { name: 'default', label: 'Light' },
      { name: 'custom', label: 'Custom' },
    ]
    mockFetchManifest(custom)
    localStorage.setItem(STORAGE_THEME_KEY, 'custom')
    const store = useThemeStore()
    await store.initialize()
    expect(store.currentTheme).toBe('custom')
  })

  it('keeps built-in list when manifest fetch fails', async () => {
    mockFetchManifestFailure()
    const store = useThemeStore()
    await store.initialize()
    expect(store.availableThemes).toEqual(BUILT_IN_MANIFEST)
    expect(store.currentTheme).toBe('default')
  })
})
