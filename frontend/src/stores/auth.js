import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { postLogin } from '@/api/auth.js'
import { LOGIN_PATH } from '@/constants/routes.js'
import { STORAGE_TOKEN_KEY } from '@/constants/storage.js'
import { EXPIRED_QUERY_KEY, EXPIRED_QUERY_VALUE } from '@/constants/auth.js'

class TokenError extends Error {
  constructor(message) {
    super(message)
    this.name = 'TokenError'
  }
}

function decodeJwtPayload(token) {
  if (typeof token !== 'string' || !token) {
    throw new TokenError('Server returned an invalid token (not a string).')
  }
  const parts = token.split('.')
  if (parts.length !== 3 || !parts[1]) {
    throw new TokenError('Server returned a malformed token.')
  }
  const base64Url = parts[1]
  let base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
  // Add padding to a multiple of 4 — JWT Base64URL commonly omits '='
  const pad = base64.length % 4
  if (pad) {
    base64 += '='.repeat(4 - pad)
  }
  try {
    const json = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join(''),
    )
    return JSON.parse(json)
  } catch {
    throw new TokenError('Server returned a token with an unreadable payload.')
  }
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(null)
  const username = ref(null)
  const roles = ref([])
  const groups = ref([])
  const expiresAt = ref(null)
  const expiredOnLoad = ref(false)

  let expiryInterval = null

  const isAuthenticated = computed(() => {
    return !!token.value && !!expiresAt.value && Date.now() < expiresAt.value
  })

  function hasRole(role) {
    return roles.value.includes(role)
  }

  function hasAnyRole(roleList) {
    return roleList.some((r) => roles.value.includes(r))
  }

  function _applyToken(jwt) {
    // Decode first so a malformed token never leaves the store partially updated
    const payload = decodeJwtPayload(jwt)
    token.value = jwt
    username.value = payload.sub || payload.username || null
    roles.value = payload.roles || []
    groups.value = payload.groups || []
    // exp is in seconds; convert to ms
    expiresAt.value = payload.exp ? payload.exp * 1000 : null
    sessionStorage.setItem(STORAGE_TOKEN_KEY, jwt)
  }

  function clearAuth() {
    _stopExpiryCheck()
    token.value = null
    username.value = null
    roles.value = []
    groups.value = []
    expiresAt.value = null
    expiredOnLoad.value = false
    sessionStorage.removeItem(STORAGE_TOKEN_KEY)
  }

  async function login(user, password) {
    // Clear any existing auth state before attempting a new login
    clearAuth()

    const response = await postLogin(user, password)
    const jwt = response.data.access_token
    _applyToken(jwt)
    _startExpiryCheck()
  }

  function logout() {
    clearAuth()
    window.location.href = LOGIN_PATH
  }

  function checkExpiry() {
    if (expiresAt.value && Date.now() >= expiresAt.value) {
      clearAuth()
      return true
    }
    return false
  }

  function _startExpiryCheck() {
    _stopExpiryCheck()
    expiryInterval = setInterval(() => {
      if (checkExpiry()) {
        // Background expiry — no router guard runs, so hard redirect is needed
        window.location.href = `${LOGIN_PATH}?${EXPIRED_QUERY_KEY}=${EXPIRED_QUERY_VALUE}`
      }
    }, 30000)
  }

  function _stopExpiryCheck() {
    if (expiryInterval) {
      clearInterval(expiryInterval)
      expiryInterval = null
    }
  }

  // Restore from sessionStorage on store creation
  function initialize() {
    const saved = sessionStorage.getItem(STORAGE_TOKEN_KEY)
    if (saved) {
      try {
        _applyToken(saved)
        if (!isAuthenticated.value) {
          // Distinguish an expired token from a corrupt/invalid one
          const wasExpired = !!expiresAt.value && Date.now() >= expiresAt.value
          clearAuth()
          expiredOnLoad.value = wasExpired
        } else {
          _startExpiryCheck()
        }
      } catch {
        clearAuth()
      }
    }
  }

  return {
    token,
    username,
    roles,
    groups,
    expiresAt,
    expiredOnLoad,
    isAuthenticated,
    hasRole,
    hasAnyRole,
    clearAuth,
    login,
    logout,
    checkExpiry,
    initialize,
  }
})

export { TokenError }
