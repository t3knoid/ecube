import axios from 'axios'
import { API_BASE, LOGIN_PATH } from '@/constants/routes.js'
import { STORAGE_TOKEN_KEY } from '@/constants/storage.js'
import { EXPIRED_QUERY_KEY, EXPIRED_QUERY_VALUE } from '@/constants/auth.js'

const apiClient = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor: attach Bearer token
apiClient.interceptors.request.use((config) => {
  const token = sessionStorage.getItem(STORAGE_TOKEN_KEY)
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
      sessionStorage.removeItem(STORAGE_TOKEN_KEY)
      if (window.location.pathname !== LOGIN_PATH) {
        // Only show the expired banner when the backend explicitly says so
        const detail = (error.response.data?.detail || '').toLowerCase()
        const isExpired = detail.includes('expired')
        window.location.href = isExpired ? `${LOGIN_PATH}?${EXPIRED_QUERY_KEY}=${EXPIRED_QUERY_VALUE}` : LOGIN_PATH
      }
    }
    return Promise.reject(error)
  },
)

export default apiClient
