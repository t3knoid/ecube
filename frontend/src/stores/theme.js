import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { STORAGE_THEME_KEY } from '@/constants/storage.js'

const THEME_LINK_ID = 'ecube-theme-stylesheet'

const BUILT_IN_THEMES = [
  { name: 'default', label: 'Light' },
  { name: 'dark', label: 'Dark' },
]

export const useThemeStore = defineStore('theme', () => {
  const currentTheme = ref('default')
  const availableThemes = computed(() => BUILT_IN_THEMES)

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
   * Restore saved theme from localStorage, falling back to 'default'.
   */
  function initialize() {
    const saved = localStorage.getItem(STORAGE_THEME_KEY)
    const themeName = saved && BUILT_IN_THEMES.some((t) => t.name === saved) ? saved : 'default'
    loadTheme(themeName)
  }

  return {
    currentTheme,
    availableThemes,
    loadTheme,
    initialize,
  }
})
