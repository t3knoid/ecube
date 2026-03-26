import './assets/main.css'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth.js'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)

// Initialize auth store from sessionStorage before installing the router,
// so the beforeEach guard sees the restored session on first navigation.
const authStore = useAuthStore()
authStore.initialize()

app.use(router)

app.mount('#app')
