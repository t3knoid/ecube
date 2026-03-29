import { computed } from 'vue'
import { useAuthStore } from '@/stores/auth.js'

export function useRoleGuard(requiredRoles = []) {
  const authStore = useAuthStore()

  const canAccess = computed(() => {
    if (!Array.isArray(requiredRoles) || requiredRoles.length === 0) return true
    return authStore.hasAnyRole(requiredRoles)
  })

  return {
    canAccess,
    hasRole: authStore.hasRole,
    hasAnyRole: authStore.hasAnyRole,
  }
}