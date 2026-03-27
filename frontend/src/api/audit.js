import apiClient from './client.js'
import { toData } from './data.js'

export function getAudit(params = {}) {
  return toData(apiClient.get('/api/audit', { params }))
}
