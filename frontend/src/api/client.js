import axios from 'axios'
import { LOGIN_PATH, SETUP_PATH } from '@/constants/routes.js'
import { STORAGE_TOKEN_KEY } from '@/constants/storage.js'
import { AUTH_RESET_EVENT, EXPIRED_QUERY_KEY, EXPIRED_QUERY_VALUE } from '@/constants/auth.js'
import { useToast } from '@/composables/useToast.js'
import i18n from '@/i18n'

export function normalizeErrorMessage(data, fallbackMessage) {
  if (!data) return fallbackMessage

  if (typeof data.message === 'string' && data.message.trim()) {
    return data.message
  }

  if (typeof data.detail === 'string' && data.detail.trim()) {
    return data.detail
  }

  if (Array.isArray(data.detail)) {
    const detailMessage = data.detail
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

    return detailMessage.trim() ? detailMessage : fallbackMessage
  }

  return fallbackMessage
}

function isAlreadyProvisionedConflict(status, data, requestUrl = '') {
  if (status !== 409) return false
  const detail = normalizeErrorMessage(data, '').toLowerCase()
  const url = String(requestUrl || '')
  return url.includes('/api/setup/database/provision') && detail.includes('already provisioned')
}

function isInlineAuthFlowRequest(requestUrl = '') {
  const url = String(requestUrl || '')
  return url.includes('/api/auth/token') || url.includes('/api/auth/change-password')
}

export function isExpiredAuthPayload(data) {
  const message = normalizeErrorMessage(data, '').toLowerCase()
  return message.includes('expired')
}

export function isUnauthorizedAuthPayload(data) {
  if (!data || typeof data !== 'object') return false

  const code = typeof data.code === 'string' ? data.code.trim().toUpperCase() : ''
  const message = normalizeErrorMessage(data, '').trim().toLowerCase()

  return code === 'UNAUTHORIZED' && message === 'missing authentication token'
}

export function isDatabaseNotConfiguredPayload(status, data) {
  if (status !== 503 || !data || typeof data !== 'object') return false

  const code = typeof data.code === 'string' ? data.code.trim().toUpperCase() : ''
  const message = normalizeErrorMessage(data, '').trim().toLowerCase()

  return code === 'HTTP_503' && message === 'database is not configured yet. complete setup first.'
}

function resetAuthAndRedirect(data) {
  sessionStorage.removeItem(STORAGE_TOKEN_KEY)
  window.dispatchEvent(new Event(AUTH_RESET_EVENT))

  if (window.location.pathname !== LOGIN_PATH) {
    const isExpired = isExpiredAuthPayload(data)
    window.location.href = isExpired ? `${LOGIN_PATH}?${EXPIRED_QUERY_KEY}=${EXPIRED_QUERY_VALUE}` : LOGIN_PATH
  }
}

function redirectToSetup() {
  if (window.location.pathname !== SETUP_PATH) {
    window.location.href = SETUP_PATH
  }
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
// (store → api/auth → api/client → store). Instead, auth-loss responses
// dispatch a global auth-reset event that main.js wires to authStore.clearAuth().
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const { error: toastError, warning } = useToast()

    if (!error.response) {
      toastError(i18n.global.t('common.errors.networkError'))
      return Promise.reject(error)
    }

    const status = error.response?.status
    const data = error.response?.data || {}
    const requestUrl = error.config?.url || ''

    if (status === 401 || isUnauthorizedAuthPayload(data)) {
      resetAuthAndRedirect(data)
    } else if (status === 403) {
      warning(i18n.global.t('common.errors.insufficientPermissions'))
    } else if (status === 409) {
      if (!isAlreadyProvisionedConflict(status, data, requestUrl)) {
        warning(normalizeErrorMessage(data, i18n.global.t('common.errors.requestConflict')))
      }
    } else if (status === 422) {
      if (isInlineAuthFlowRequest(requestUrl)) {
        return Promise.reject(error)
      }
      warning(normalizeErrorMessage(data, i18n.global.t('common.errors.validationFailed')))
    } else if (isDatabaseNotConfiguredPayload(status, data)) {
      redirectToSetup()
    } else if (status >= 500 && status < 600) {
      toastError(normalizeErrorMessage(data, i18n.global.t('common.errors.serverErrorGeneric')), { traceId: data.trace_id || null })
    }

    return Promise.reject(error)
  },
)

export default apiClient
