import { normalizeErrorMessage } from '@/api/client.js'

export function buildJobErrorMessage(err, t, { includeInvalidId = false } = {}) {
  const status = err?.response?.status
  const detail = normalizeErrorMessage(err?.response?.data, '')

  if (includeInvalidId && err instanceof TypeError && String(err.message || '').includes('Invalid job id')) {
    return t('common.errors.invalidRequest')
  }
  if (!status) return t('common.errors.networkError')
  if (status === 403) return detail || t('common.errors.insufficientPermissions')
  if (status === 404) return detail || t('common.errors.notFound')
  if (status === 409) return detail || t('common.errors.requestConflict')
  if (status === 422) return detail || t('common.errors.validationFailed')
  if (status >= 500) return t('common.errors.serverError', { status })
  return detail || t('common.errors.serverErrorGeneric')
}