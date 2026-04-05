import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getConfiguration() {
  return toData(apiClient.get(`${API_BASE}/admin/configuration`))
}

export function updateConfiguration(payload) {
  return toData(apiClient.put(`${API_BASE}/admin/configuration`, payload))
}

export function restartConfigurationService(payload = { confirm: true }) {
  return toData(apiClient.post(`${API_BASE}/admin/configuration/restart`, payload))
}
