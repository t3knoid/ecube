import axios from 'axios'
import { useAuthStore } from '@/stores/auth.js'

const apiClient = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor: attach Bearer token
apiClient.interceptors.request.use((config) => {
  const token = sessionStorage.getItem('ecube_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Response interceptor: handle auth errors
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Determine if the backend specifically reports token expiration
      const detail = (error.response.data?.detail || '').toLowerCase()
      const isExpired = detail.includes('expired')

      try {
        const authStore = useAuthStore()
        authStore.logout({ expired: isExpired })
      } catch {
        // Store may not be available yet (e.g. during app bootstrap);
        // fall back to manual cleanup
        sessionStorage.removeItem('ecube_token')
        if (window.location.pathname !== '/login') {
          window.location.href = isExpired ? '/login?expired=1' : '/login'
        }
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
