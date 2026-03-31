import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getAudit(params = {}) {
  return toData(apiClient.get(`${API_BASE}/audit`, { params }))
}
