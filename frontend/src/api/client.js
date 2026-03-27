import axios from 'axios'
import { LOGIN_PATH } from '@/constants/routes.js'
import { STORAGE_TOKEN_KEY } from '@/constants/storage.js'
import { AUTH_RESET_EVENT, EXPIRED_QUERY_KEY, EXPIRED_QUERY_VALUE } from '@/constants/auth.js'
import { useToast } from '@/composables/useToast.js'

function normalizeErrorMessage(data, fallbackMessage) {
  if (!data) return fallbackMessage

  if (typeof data.message === 'string' && data.message.trim()) {
    return data.message
  }

  if (typeof data.detail === 'string' && data.detail.trim()) {
    return data.detail
  }

  if (Array.isArray(data.detail)) {
    return data.detail
      .map((item) => {
        if (typeof item === 'string') return item
        if (item && typeof item.msg === 'string') {
          const loc = Array.isArray(item.loc) ? item.loc.join('.') : ''
          return loc ? `${loc}: ${item.msg}` : item.msg
        }
        return null
      })
      .filter(Boolean)
      .join('; ')
  }

  return fallbackMessage
}

const apiClient = axios.create({
  baseURL: '',
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
// (store → api/auth → api/client → store). Instead, 401 dispatches a global
// auth-reset event that main.js wires to authStore.clearAuth().
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const { error: toastError, warning } = useToast()
    const status = error.response?.status
    const data = error.response?.data || {}

    if (status === 401) {
      sessionStorage.removeItem(STORAGE_TOKEN_KEY)
      window.dispatchEvent(new Event(AUTH_RESET_EVENT))
      if (window.location.pathname !== LOGIN_PATH) {
        // Only show the expired banner when the backend explicitly says so
        const detail = (data.detail || '').toLowerCase()
        const isExpired = detail.includes('expired')
        window.location.href = isExpired ? `${LOGIN_PATH}?${EXPIRED_QUERY_KEY}=${EXPIRED_QUERY_VALUE}` : LOGIN_PATH
      }
    } else if (status === 403) {
      warning('Insufficient permissions. Your role may not allow this action.')
    } else if (status === 409) {
      warning(normalizeErrorMessage(data, 'Request conflict. Please refresh and try again.'))
    } else if (status === 422) {
      warning(normalizeErrorMessage(data, 'Validation failed. Please review your input.'))
    } else if (status >= 500 && status < 600) {
      toastError(normalizeErrorMessage(data, 'Server error.'), { traceId: data.trace_id || null })
    }

    return Promise.reject(error)
  },
)

export default apiClient
