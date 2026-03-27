import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { useAuthStore } from './stores/auth.js'
import { useThemeStore } from './stores/theme.js'
import { AUTH_RESET_EVENT } from './constants/auth.js'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(i18n)

// Initialize auth store from sessionStorage before installing the router,
// so the beforeEach guard sees the restored session on first navigation.
const authStore = useAuthStore()
authStore.initialize()

// Keep auth reset centralized without introducing api/store circular imports.
window.addEventListener(AUTH_RESET_EVENT, () => {
	authStore.clearAuth()
})

// Restore theme synchronously from localStorage, then fetch manifest in background.
const themeStore = useThemeStore()
themeStore.initialize()

app.use(router)
app.mount('#app')
