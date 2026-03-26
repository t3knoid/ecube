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
const originalFetch = globalThis.fetch

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

/** Simulate the browser firing the onload event for the theme <link>. */
function simulateLoad() {
  const link = document.getElementById('ecube-theme-stylesheet')
  if (link && link.onload) link.onload()
}

/** Simulate the browser firing the onerror event for the theme <link>. */
function simulateError() {
  const link = document.getElementById('ecube-theme-stylesheet')
  if (link && link.onerror) link.onerror()
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
    globalThis.fetch = originalFetch
    const link = document.getElementById('ecube-theme-stylesheet')
    if (link) link.remove()
  })

  it('initializes with default theme', () => {
    const store = useThemeStore()
    store.initialize()
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

  it('persists theme preference to localStorage on successful load', () => {
    const store = useThemeStore()
    store.loadTheme('dark')
    simulateLoad()
    expect(localStorage.getItem(STORAGE_THEME_KEY)).toBe('dark')
  })

  it('reverts to default on stylesheet load error', () => {
    const store = useThemeStore()
    store.loadTheme('dark')
    simulateError()
    expect(store.currentTheme).toBe('default')
  })

  it('restores theme preference from localStorage', () => {
    localStorage.setItem(STORAGE_THEME_KEY, 'dark')
    const store = useThemeStore()
    store.initialize()
    expect(store.currentTheme).toBe('dark')
  })

  it('falls back to default for unknown saved theme', () => {
    localStorage.setItem(STORAGE_THEME_KEY, 'nonexistent')
    const store = useThemeStore()
    store.initialize()
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
    store.initialize()
    await vi.waitFor(() => expect(store.availableThemes).toEqual(custom))
  })

  it('restores saved custom theme after manifest loads', async () => {
    const custom = [
      { name: 'custom', label: 'Custom' },
    ]
    mockFetchManifest(custom)
    localStorage.setItem(STORAGE_THEME_KEY, 'custom')
    const store = useThemeStore()
    store.initialize()
    // 'custom' is not in built-in list, so initialize applies 'default' first.
    expect(store.currentTheme).toBe('default')
    // After manifest resolves, saved custom theme is automatically applied.
    await vi.waitFor(() => expect(store.currentTheme).toBe('custom'))
    expect(store.availableThemes).toEqual([
      { name: 'default', label: 'Light' },
      { name: 'dark', label: 'Dark' },
      { name: 'custom', label: 'Custom' },
    ])
  })

  it('preserves built-in themes when manifest omits them', async () => {
    // Manifest only has a custom theme — built-ins must still be present
    mockFetchManifest([{ name: 'corporate', label: 'Corporate' }])
    const store = useThemeStore()
    store.initialize()
    await vi.waitFor(() => expect(store.availableThemes).toEqual([
      { name: 'default', label: 'Light' },
      { name: 'dark', label: 'Dark' },
      { name: 'corporate', label: 'Corporate' },
    ]))
  })

  it('keeps built-in list when manifest fetch fails', async () => {
    mockFetchManifestFailure()
    const store = useThemeStore()
    store.initialize()
    // Let the background fetch settle
    await vi.waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    expect(store.availableThemes).toEqual(BUILT_IN_MANIFEST)
    expect(store.currentTheme).toBe('default')
  })
})
