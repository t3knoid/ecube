import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth.js'
import { useRoleGuard } from '@/composables/useRoleGuard.js'

describe('useRoleGuard', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('allows access when no roles are required', () => {
    const { canAccess } = useRoleGuard([])
    expect(canAccess.value).toBe(true)
  })

  it('allows access when user has any required role', () => {
    const authStore = useAuthStore()
    authStore.roles = ['processor']

    const { canAccess } = useRoleGuard(['admin', 'processor'])
    expect(canAccess.value).toBe(true)
  })

  it('denies access when user has none of the required roles', () => {
    const authStore = useAuthStore()
    authStore.roles = ['auditor']

    const { canAccess } = useRoleGuard(['admin', 'manager'])
    expect(canAccess.value).toBe(false)
  })
})
