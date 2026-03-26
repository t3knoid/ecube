import axios from 'axios'

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
// Intentionally store-agnostic to avoid a circular dependency
// (store → api/auth → api/client → store). The redirect triggers a full
// page reload which re-initializes the Pinia store from sessionStorage.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      sessionStorage.removeItem('ecube_token')
      if (window.location.pathname !== '/login') {
        // Only show the expired banner when the backend explicitly says so
        const detail = (error.response.data?.detail || '').toLowerCase()
        const isExpired = detail.includes('expired')
        window.location.href = isExpired ? '/login?expired=1' : '/login'
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
