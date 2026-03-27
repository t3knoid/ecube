import apiClient from './client.js'
import { toData } from './data.js'

export function getDrives() {
  return toData(apiClient.get('/api/drives'))
}

export function initializeDrive(driveId, payload) {
  return toData(apiClient.post(`/api/drives/${driveId}/initialize`, payload))
}

export function formatDrive(driveId, payload = {}) {
  return toData(apiClient.post(`/api/drives/${driveId}/format`, payload))
}

export function prepareEjectDrive(driveId) {
  return toData(apiClient.post(`/api/drives/${driveId}/prepare-eject`))
}
