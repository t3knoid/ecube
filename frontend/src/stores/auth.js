import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { postLogin } from '@/api/auth.js'

function decodeJwtPayload(token) {
  const base64Url = token.split('.')[1]
  const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
  const json = decodeURIComponent(
    atob(base64)
      .split('')
      .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
      .join(''),
  )
  return JSON.parse(json)
}

export const useAuthStore = defineStore('auth', () => {
  const token = ref(null)
  const username = ref(null)
  const roles = ref([])
  const groups = ref([])
  const expiresAt = ref(null)

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
    token.value = jwt
    const payload = decodeJwtPayload(jwt)
    username.value = payload.sub || payload.username || null
    roles.value = payload.roles || []
    groups.value = payload.groups || []
    // exp is in seconds; convert to ms
    expiresAt.value = payload.exp ? payload.exp * 1000 : null
    sessionStorage.setItem('ecube_token', jwt)
  }

  async function login(user, password) {
    const response = await postLogin(user, password)
    const jwt = response.data.access_token
    _applyToken(jwt)
    _startExpiryCheck()
  }

  function logout() {
    _stopExpiryCheck()
    token.value = null
    username.value = null
    roles.value = []
    groups.value = []
    expiresAt.value = null
    sessionStorage.removeItem('ecube_token')
  }

  function checkExpiry() {
    if (expiresAt.value && Date.now() >= expiresAt.value) {
      logout()
      return true
    }
    return false
  }

  function _startExpiryCheck() {
    _stopExpiryCheck()
    expiryInterval = setInterval(() => {
      checkExpiry()
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
    const saved = sessionStorage.getItem('ecube_token')
    if (saved) {
      try {
        _applyToken(saved)
        if (!isAuthenticated.value) {
          logout()
        } else {
          _startExpiryCheck()
        }
      } catch {
        logout()
      }
    }
  }

  return {
    token,
    username,
    roles,
    groups,
    expiresAt,
    isAuthenticated,
    hasRole,
    hasAnyRole,
    login,
    logout,
    checkExpiry,
    initialize,
  }
})
