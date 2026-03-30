import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth.js'

export function useRoleGuard(requiredRoles = []) {
  const authStore = useAuthStore()

  const normalizedRoles = typeof requiredRoles === 'string'
    ? [requiredRoles]
    : requiredRoles

  const canAccess = computed(() => {
    if (!Array.isArray(normalizedRoles) || normalizedRoles.length === 0) return true
    return authStore.hasAnyRole(normalizedRoles)
  })

  return {
    canAccess,
    hasRole: authStore.hasRole,
    hasAnyRole: authStore.hasAnyRole,
  }
}