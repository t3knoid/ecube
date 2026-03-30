import { defineStore } from 'pinia'
import { ref } from 'vue'
import { STORAGE_THEME_KEY } from '@/constants/storage.js'

const THEME_LINK_ID = 'ecube-theme-stylesheet'
const THEME_FALLBACK_STYLE_ID = 'ecube-theme-inline-fallback'
const VALID_THEME_NAME = /^[a-z0-9][a-z0-9-]*$/
const MANIFEST_TIMEOUT_MS = 3000
const BUILT_IN_THEMES = [
  { name: 'default', labelKey: 'themes.light' },
  { name: 'dark', labelKey: 'themes.dark' },
]

// Safety net: if external theme files are missing (e.g. empty mounted
// /themes directory in Docker), keep the UI readable with built-in defaults.
const DEFAULT_THEME_INLINE_CSS = `
:root {
  --color-bg-primary: #ffffff;
  --color-bg-secondary: #f8f9fa;
  --color-bg-sidebar: #f1f5f9;
  --color-bg-header: #f8f9fa;
  --color-bg-footer: #f8f9fa;
  --color-bg-input: #ffffff;
  --color-bg-hover: #e2e8f0;
  --color-bg-selected: #dbeafe;

  --color-text-primary: #1e293b;
  --color-text-secondary: #64748b;
  --color-text-inverse: #ffffff;
  --color-text-link: #2563eb;
  --color-text-disabled: #94a3b8;

  --color-success: #16a34a;
  --color-warning: #d97706;
  --color-danger: #dc2626;
  --color-info: #2563eb;

  --color-alert-warning-bg: #fff3cd;
  --color-alert-warning-text: #856404;
  --color-alert-warning-border: #d97706;
  --color-alert-danger-bg: #fef2f2;
  --color-alert-danger-text: #dc2626;
  --color-alert-danger-border: #fecaca;

  --color-border: #e2e8f0;
  --color-border-focus: #3b82f6;
  --color-divider: #e2e8f0;

  --color-btn-primary-bg: #2563eb;
  --color-btn-primary-text: #ffffff;
  --color-btn-primary-hover-bg: #1d4ed8;
  --color-btn-danger-bg: #dc2626;
  --color-btn-danger-text: #ffffff;
  --color-btn-danger-hover-bg: #b91c1c;

  --color-badge-admin-bg: #fef2f2;
  --color-badge-admin-text: #dc2626;
  --color-badge-manager-bg: #eff6ff;
  --color-badge-manager-text: #2563eb;
  --color-badge-processor-bg: #f0fdf4;
  --color-badge-processor-text: #16a34a;
  --color-badge-auditor-bg: #fefce8;
  --color-badge-auditor-text: #ca8a04;

  --color-status-ok-text: #14532d;
  --color-status-warn-text: #7c3f00;
  --color-status-danger-text: #991b1b;
  --color-status-info-text: #1e40af;
  --color-status-muted-text: #475569;
  --color-ok-banner-text: #14532d;

  --color-progress-bar: #2563eb;
  --color-progress-track: #e2e8f0;

  --font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Fira Sans', 'Droid Sans', 'Helvetica Neue', sans-serif;
  --font-size-xs: 0.75rem;
  --font-size-sm: 0.875rem;
  --font-size-base: 1rem;
  --font-size-lg: 1.125rem;
  --font-size-xl: 1.25rem;
  --font-size-2xl: 1.5rem;
  --font-weight-normal: 400;
  --font-weight-medium: 500;
  --font-weight-bold: 700;

  --space-xs: 0.25rem;
  --space-sm: 0.5rem;
  --space-md: 1rem;
  --space-lg: 1.5rem;
  --space-xl: 2rem;
  --space-2xl: 3rem;

  --sidebar-width: 200px;
  --header-height: 56px;
  --footer-height: 40px;
  --border-radius: 4px;
  --border-radius-lg: 8px;
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px rgba(0, 0, 0, 0.07);
  --shadow-lg: 0 10px 15px rgba(0, 0, 0, 0.1);
}
`

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

  function _clearInlineFallbackTheme() {
    const style = document.getElementById(THEME_FALLBACK_STYLE_ID)
    if (style) {
      style.remove()
    }
  }

  function _applyInlineFallbackTheme() {
    let style = document.getElementById(THEME_FALLBACK_STYLE_ID)
    if (!style) {
      style = document.createElement('style')
      style.id = THEME_FALLBACK_STYLE_ID
      document.head.appendChild(style)
    }
    style.textContent = DEFAULT_THEME_INLINE_CSS
    currentTheme.value = 'default'
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

    // Short-circuit when the desired stylesheet is already active — avoids
    // cancelling an in-flight load and an unnecessary network request.
    if (oldLink && oldLink.getAttribute('href') === href) {
      currentTheme.value = name
      return
    }

    const link = document.createElement('link')
    link.id = THEME_LINK_ID
    link.rel = 'stylesheet'

    // Attach handlers before setting href so cached loads cannot fire
    // before the callbacks are in place.  Guard against stale events from
    // a previous loadTheme call whose <link> has since been replaced.
    link.onload = () => {
      if (document.getElementById(THEME_LINK_ID) !== link) return
      _clearInlineFallbackTheme()
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
        return
      }

      // Even default.css failed — use embedded defaults as a safe fallback.
      _applyInlineFallbackTheme()
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
