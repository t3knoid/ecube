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
   * Fetch the theme manifest from the server to replace the built-in theme list.
   * Falls back to built-ins if the manifest is missing or malformed.
   */
  async function fetchManifest() {
    try {
      const url = `${import.meta.env.BASE_URL}themes/manifest.json`
      const controller = new AbortController()
      const timer = setTimeout(() => controller.abort(), MANIFEST_TIMEOUT_MS)
      const resp = await fetch(url, { signal: controller.signal })
      clearTimeout(timer)
      if (!resp.ok) return
      const data = await resp.json()
      if (Array.isArray(data)) {
        const valid = data.filter(_isValidEntry)
        if (valid.length > 0) {
          availableThemes.value = valid
        }
      }
    } catch {
      // Manifest unavailable — keep built-in list
    }
  }

  function _isKnownTheme(name) {
    return availableThemes.value.some((t) => t.name === name)
  }

  /**
   * Inject or replace the theme <link> element in <head>.
   */
  function loadTheme(name) {
    if (!VALID_THEME_NAME.test(name)) return
    const href = `${import.meta.env.BASE_URL}themes/${name}.css`

    let link = document.getElementById(THEME_LINK_ID)
    if (link) {
      link.setAttribute('href', href)
    } else {
      link = document.createElement('link')
      link.id = THEME_LINK_ID
      link.rel = 'stylesheet'
      link.href = href
      document.head.appendChild(link)
    }

    currentTheme.value = name
    try {
      localStorage.setItem(STORAGE_THEME_KEY, name)
    } catch {
      // Storage may be unavailable (quota exceeded, privacy mode, etc.)
    }
  }

  /**
   * Apply the saved (or default) theme synchronously from the built-in list,
   * then fetch the manifest in the background. If the manifest reveals the
   * saved theme is valid, the theme stays; otherwise it is corrected.
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

    // Fetch manifest in background — updates available themes list and
    // corrects theme if the saved one isn't in the manifest.
    fetchManifest().then(() => {
      if (!_isKnownTheme(currentTheme.value)) {
        loadTheme('default')
      }
    }).catch(() => {
      // Manifest unavailable — built-in list is already active
    })
  }

  return {
    currentTheme,
    availableThemes,
    loadTheme,
    initialize,
  }
})
