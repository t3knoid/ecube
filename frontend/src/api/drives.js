import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getDrives() {
  return toData(apiClient.get(`${API_BASE}/drives`))
}

export function refreshDrives() {
  return toData(apiClient.post(`${API_BASE}/drives/refresh`))
}

export function initializeDrive(driveId, payload) {
  return toData(apiClient.post(`${API_BASE}/drives/${driveId}/initialize`, payload))
}

export function formatDrive(driveId, payload = {}) {
  return toData(apiClient.post(`${API_BASE}/drives/${driveId}/format`, payload))
}

export function prepareEjectDrive(driveId) {
  return toData(apiClient.post(`${API_BASE}/drives/${driveId}/prepare-eject`))
}
