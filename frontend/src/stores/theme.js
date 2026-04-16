import { defineStore } from 'pinia'
import { ref } from 'vue'
import { STORAGE_THEME_KEY } from '@/constants/storage.js'
import { logger } from '@/utils/logger.js'

const THEME_LINK_ID = 'ecube-theme-stylesheet'
const THEME_FALLBACK_STYLE_ID = 'ecube-theme-inline-fallback'
const VALID_THEME_NAME = /^[a-z0-9][a-z0-9-]*$/
const VALID_LOGO_FILENAME = /^[a-zA-Z0-9][a-zA-Z0-9._-]*\.(?:svg|png|gif|webp)$/
const MANIFEST_TIMEOUT_MS = 3000
function _defaultLogoAlt() {
  if (typeof document !== 'undefined') {
    const localizedTitle = document.title.trim()
    if (localizedTitle) {
      return localizedTitle
    }
  }
  return 'ECUBE'
}

/** Returns the trimmed logoAlt string, or '' if absent or whitespace-only. */
function _trimmedLogoAlt(value) {
  return typeof value === 'string' ? value.trim() : ''
}

/** Constructs a URL for a file under the themes directory. */
function _themesUrl(filename) {
  return `${import.meta.env.BASE_URL}themes/${filename}`
}

/** Theme subsystem debug log. */
function _debug(...args) {
  logger.debug(...args)
}

/** Wraps a localStorage operation, swallowing errors when storage is unavailable. */
function _safeStorage(fn) {
  try {
    return fn()
  } catch (err) {
    logger.debug('[theme] localStorage unavailable:', err)
  }
}

/** Returns true if the given value is a syntactically valid logo filename. */
function _isValidLogoFilename(logo) {
  return typeof logo === 'string' && VALID_LOGO_FILENAME.test(logo)
}

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
  --header-height: 96px;
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
  const currentLogo = ref(null)
  const currentLogoAlt = ref(_defaultLogoAlt())
  const availableThemes = ref([...BUILT_IN_THEMES])

  function _isValidEntry(t) {
    return (
      t !== null &&
      typeof t === 'object' &&
      typeof t.name === 'string' &&
      typeof t.label === 'string' &&
      VALID_THEME_NAME.test(t.name) &&
      t.label.trim().length > 0
    )
  }

  function _normalizeEntry(entry) {
    const normalized = {
      name: entry.name,
      label: entry.label.trim(),
    }

    const hasValidLogo = _isValidLogoFilename(entry.logo)

    if (hasValidLogo) {
      normalized.logo = entry.logo
      const trimmedLogoAlt = _trimmedLogoAlt(entry.logoAlt)
      if (trimmedLogoAlt.length > 0) {
        normalized.logoAlt = trimmedLogoAlt
      }
    }

    return normalized
  }

  function _clearBranding() {
    currentLogo.value = null
    currentLogoAlt.value = _defaultLogoAlt()
  }

  function _setBrandingForTheme(themeName) {
    const theme = availableThemes.value.find((t) => t.name === themeName)
    if (theme && _isValidLogoFilename(theme.logo)) {
      currentLogo.value = _themesUrl(theme.logo)
      const trimmedLogoAlt = _trimmedLogoAlt(theme.logoAlt)
      currentLogoAlt.value = trimmedLogoAlt.length > 0 ? trimmedLogoAlt : _defaultLogoAlt()
      return
    }

    _clearBranding()
  }

  /**
   * Fetch the theme manifest from the server and merge with built-in themes.
   * Built-ins are always present; manifest entries are merged (de-duplicated
   * by name). For built-in themes a manifest-provided label takes precedence
   * in the UI; the built-in labelKey is kept as a localised fallback for when
   * no manifest label is present.
   */
  async function fetchManifest() {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), MANIFEST_TIMEOUT_MS)
    try {
      const url = _themesUrl('manifest.json')
      _debug('[theme] fetchManifest: url=%s', url)
      const resp = await fetch(url, { signal: controller.signal })
      if (!resp.ok) {
        _debug('[theme] fetchManifest: HTTP %d %s', resp.status, resp.statusText)
        return
      }
      const data = await resp.json()
      if (Array.isArray(data)) {
        const valid = data.filter(_isValidEntry).map(_normalizeEntry)
        if (valid.length > 0) {
          // Start with built-ins, then overlay/append manifest entries
          const merged = new Map(BUILT_IN_THEMES.map((t) => [t.name, t]))
          for (const entry of valid) {
            const existing = merged.get(entry.name)
            merged.set(entry.name, existing ? { ...existing, ...entry } : entry)
          }
          availableThemes.value = [...merged.values()]
        }
        _setBrandingForTheme(currentTheme.value)
      }
    } catch (err) {
      _debug('[theme] fetchManifest error:', err)
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
    _clearBranding()
  }

  /**
   * Inject or replace the theme <link> element in <head>.
   * Sets currentTheme optimistically so the UI reflects the selection
   * immediately. Persists to localStorage only after successful load.
   * Falls back to 'default' if the stylesheet fails to load (unless already default).
   */
  function loadTheme(name) {
    if (!VALID_THEME_NAME.test(name)) {
      _debug('[theme] loadTheme: rejected invalid name:', name)
      return
    }
    const href = _themesUrl(`${name}.css`)
    _debug('[theme] loadTheme: name=%s href=%s', name, href)

    const oldLink = document.getElementById(THEME_LINK_ID)

    // Short-circuit when the desired stylesheet is already active — avoids
    // cancelling an in-flight load and an unnecessary network request.
    if (oldLink && oldLink.getAttribute('href') === href) {
      currentTheme.value = name
      _setBrandingForTheme(name)
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
      _debug('[theme] loadTheme: CSS loaded OK for %s', name)
      _clearInlineFallbackTheme()
      currentTheme.value = name
      _setBrandingForTheme(name)
      _safeStorage(() => localStorage.setItem(STORAGE_THEME_KEY, name))
    }

    link.onerror = () => {
      if (document.getElementById(THEME_LINK_ID) !== link) return
      _debug('[theme] loadTheme: CSS FAILED for %s (href=%s)', name, href)
      // Stylesheet failed to load — clear broken preference and fall back.
      _safeStorage(() => localStorage.removeItem(STORAGE_THEME_KEY))
      if (name !== 'default') {
        loadTheme('default')
        return
      }

      // Even default.css failed — use embedded defaults as a safe fallback.
      _debug('[theme] loadTheme: even default.css failed — using inline fallback')
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
    _setBrandingForTheme(name)
  }

  /**
   * Apply the saved (or default) theme synchronously from the built-in list,
   * then fetch the manifest in the background. If the manifest makes a saved
   * custom theme available, switch to it — but only if the user hasn't
   * changed the theme via the switcher since initialization.
   */
  function initialize() {
    const saved = _safeStorage(() => localStorage.getItem(STORAGE_THEME_KEY)) ?? null
    const themeName = saved && _isKnownTheme(saved) ? saved : 'default'
    _debug('[theme] initialize: saved=%s, resolved=%s', saved, themeName)
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
    currentLogo,
    currentLogoAlt,
    availableThemes,
    loadTheme,
    initialize,
  }
})
