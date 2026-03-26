import { defineStore } from 'pinia'
import { ref } from 'vue'
import { STORAGE_THEME_KEY } from '@/constants/storage.js'

const THEME_LINK_ID = 'ecube-theme-stylesheet'

const BUILT_IN_THEMES = [
  { name: 'default', label: 'Light' },
  { name: 'dark', label: 'Dark' },
]

export const useThemeStore = defineStore('theme', () => {
  const currentTheme = ref('default')
  const availableThemes = ref([...BUILT_IN_THEMES])

  /**
   * Fetch the theme manifest from the server and merge with built-in themes.
   * Falls back to built-ins if the manifest is missing or malformed.
   */
  async function fetchManifest() {
    try {
      const url = `${import.meta.env.BASE_URL}themes/manifest.json`
      const resp = await fetch(url)
      if (!resp.ok) return
      const data = await resp.json()
      if (Array.isArray(data) && data.every((t) => t.name && t.label)) {
        availableThemes.value = data
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
    localStorage.setItem(STORAGE_THEME_KEY, name)
  }

  /**
   * Fetch the manifest, then restore saved theme from localStorage,
   * falling back to 'default'.
   */
  async function initialize() {
    await fetchManifest()
    const saved = localStorage.getItem(STORAGE_THEME_KEY)
    const themeName = saved && _isKnownTheme(saved) ? saved : 'default'
    loadTheme(themeName)
  }

  return {
    currentTheme,
    availableThemes,
    loadTheme,
    initialize,
  }
})
