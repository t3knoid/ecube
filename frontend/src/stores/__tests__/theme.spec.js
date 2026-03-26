import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useThemeStore } from '@/stores/theme.js'

// Provide a simple localStorage mock for jsdom environments where
// the native implementation may be incomplete.
const storage = {}
const localStorageMock = {
  getItem: vi.fn((key) => storage[key] ?? null),
  setItem: vi.fn((key, value) => { storage[key] = String(value) }),
  removeItem: vi.fn((key) => { delete storage[key] }),
  clear: vi.fn(() => { Object.keys(storage).forEach((k) => delete storage[k]) }),
}
Object.defineProperty(globalThis, 'localStorage', { value: localStorageMock, writable: true })

describe('Theme Store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorageMock.clear()
    vi.clearAllMocks()
    // Remove any injected link elements
    const link = document.getElementById('ecube-theme-stylesheet')
    if (link) link.remove()
  })

  afterEach(() => {
    const link = document.getElementById('ecube-theme-stylesheet')
    if (link) link.remove()
  })

  it('initializes with default theme', () => {
    const store = useThemeStore()
    store.initialize()
    expect(store.currentTheme).toBe('default')
  })

  it('lists available themes', () => {
    const store = useThemeStore()
    expect(store.availableThemes).toEqual([
      { name: 'default', label: 'Light' },
      { name: 'dark', label: 'Dark' },
    ])
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
    expect(localStorage.getItem('ecube_theme')).toBe('dark')
  })

  it('restores theme preference from localStorage', () => {
    localStorage.setItem('ecube_theme', 'dark')
    const store = useThemeStore()
    store.initialize()
    expect(store.currentTheme).toBe('dark')
  })

  it('falls back to default for unknown saved theme', () => {
    localStorage.setItem('ecube_theme', 'nonexistent')
    const store = useThemeStore()
    store.initialize()
    expect(store.currentTheme).toBe('default')
  })
})
