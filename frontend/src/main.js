import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import i18n from './i18n'
import { useAuthStore } from './stores/auth.js'
import { useThemeStore } from './stores/theme.js'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(i18n)

// Initialize auth store from sessionStorage before installing the router,
// so the beforeEach guard sees the restored session on first navigation.
const authStore = useAuthStore()
authStore.initialize()

// Restore theme preference from localStorage
const themeStore = useThemeStore()
themeStore.initialize()

app.use(router)

app.mount('#app')
