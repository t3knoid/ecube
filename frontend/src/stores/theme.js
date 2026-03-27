import { defineStore } from 'pinia'
import { ref } from 'vue'
import { STORAGE_THEME_KEY } from '@/constants/storage.js'

const THEME_LINK_ID = 'ecube-theme-stylesheet'
const VALID_THEME_NAME = /^[a-z0-9][a-z0-9-]*$/
const MANIFEST_TIMEOUT_MS = 3000
const BUILT_IN_THEMES = [
  { name: 'default', label: 'Light' },
  { name: 'dark', label: 'Dark' },
]

export const useThemeStore = defineStore('theme', () => {
  const currentTheme = ref('default')
  const availableThemes = ref([...BUILT_IN_THEMES])

  function _isValidEntry(t) {
    return (
      typeof t.name === 'string' &&
      typeof t.label === 'string' &&
      VALID_THEME_NAME.test(t.name) &&
      t.label.length > 0
    )
  }

  /**
   * Fetch the theme manifest from the server and merge with built-in themes.
   * Built-ins are always present; manifest entries are merged (de-duplicated
   * by name, with manifest labels taking precedence). Falls back to built-ins
   * if the manifest is missing or malformed.
   */
  async function fetchManifest() {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), MANIFEST_TIMEOUT_MS)
    try {
      const url = `${import.meta.env.BASE_URL}themes/manifest.json`
      const resp = await fetch(url, { signal: controller.signal })
      if (!resp.ok) return
      const data = await resp.json()
      if (Array.isArray(data)) {
        const valid = data.filter(_isValidEntry)
        if (valid.length > 0) {
          // Start with built-ins, then overlay/append manifest entries
          const merged = new Map(BUILT_IN_THEMES.map((t) => [t.name, t]))
          for (const entry of valid) {
            merged.set(entry.name, entry)
          }
          availableThemes.value = [...merged.values()]
        }
      }
    } catch {
      // Manifest unavailable — keep built-in list
    } finally {
      clearTimeout(timer)
    }
  }

  function _isKnownTheme(name) {
    return availableThemes.value.some((t) => t.name === name)
  }

  /**
   * Inject or replace the theme <link> element in <head>.
   * Sets currentTheme optimistically so the UI reflects the selection
   * immediately. Persists to localStorage only after successful load.
   * Falls back to 'default' if the stylesheet fails to load (unless already default).
   */
  function loadTheme(name) {
    if (!VALID_THEME_NAME.test(name)) return
    const href = `${import.meta.env.BASE_URL}themes/${name}.css`

    const oldLink = document.getElementById(THEME_LINK_ID)
    const link = document.createElement('link')
    link.id = THEME_LINK_ID
    link.rel = 'stylesheet'

    // Attach handlers before setting href so cached loads cannot fire
    // before the callbacks are in place.  Guard against stale events from
    // a previous loadTheme call whose <link> has since been replaced.
    link.onload = () => {
      if (document.getElementById(THEME_LINK_ID) !== link) return
      currentTheme.value = name
      try {
        localStorage.setItem(STORAGE_THEME_KEY, name)
      } catch {
        // Storage may be unavailable (quota exceeded, privacy mode, etc.)
      }
    }

    link.onerror = () => {
      if (document.getElementById(THEME_LINK_ID) !== link) return
      // Stylesheet failed to load — clear broken preference and fall back.
      try {
        localStorage.removeItem(STORAGE_THEME_KEY)
      } catch {
        // Storage may be unavailable
      }
      if (name !== 'default') {
        loadTheme('default')
      }
    }

    link.setAttribute('href', href)
    if (oldLink) {
      oldLink.replaceWith(link)
    } else {
      document.head.appendChild(link)
    }

    // Commit optimistically so the UI reflects the selection immediately.
    // The onerror handler will revert if the stylesheet fails.
    currentTheme.value = name
  }

  /**
   * Apply the saved (or default) theme synchronously from the built-in list,
   * then fetch the manifest in the background. If the manifest makes a saved
   * custom theme available, switch to it — but only if the user hasn't
   * changed the theme via the switcher since initialization.
   */
  function initialize() {
    let saved = null
    try {
      saved = localStorage.getItem(STORAGE_THEME_KEY)
    } catch {
      // Storage may be unavailable
    }
    const themeName = saved && _isKnownTheme(saved) ? saved : 'default'
    loadTheme(themeName)

    // Remember what initialize() applied so the manifest callback can
    // detect whether the user switched themes in the meantime.
    const initialTheme = themeName

    // Fetch manifest in background — may unlock a saved custom theme or
    // invalidate the current one.
    fetchManifest().then(() => {
      // If the user changed the theme since initialization, respect their choice.
      if (currentTheme.value !== initialTheme) return

      if (saved && saved !== currentTheme.value && _isKnownTheme(saved)) {
        // Saved custom theme is now available after manifest loaded
        loadTheme(saved)
      } else if (!_isKnownTheme(currentTheme.value)) {
        loadTheme('default')
      }
    })
  }

  return {
    currentTheme,
    availableThemes,
    loadTheme,
    initialize,
  }
})
