import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getDrives(params = {}) {
  return toData(apiClient.get(`${API_BASE}/drives`, { params }))
}

export function refreshDrives() {
  return toData(apiClient.post(`${API_BASE}/drives/refresh`))
}

export function initializeDrive(driveId, payload) {
  return toData(apiClient.post(`${API_BASE}/drives/${driveId}/initialize`, payload))
}

export function formatDrive(driveId, payload = {}, { timeout } = {}) {
  const config = {}
  if (timeout != null) {
    config.timeout = timeout
  }
  return toData(apiClient.post(`${API_BASE}/drives/${driveId}/format`, payload, config))
}

export function mountDrive(driveId, { timeout } = {}) {
  const config = {}
  if (timeout != null) {
    config.timeout = timeout
  }
  return toData(apiClient.post(`${API_BASE}/drives/${driveId}/mount`, null, config))
}

export function prepareEjectDrive(driveId, options = {}) {
  const { confirm_incomplete = false } = options
  return toData(apiClient.post(`${API_BASE}/drives/${driveId}/prepare-eject`, null, {
    params: { confirm_incomplete },
  }))
}
