import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getSetupStatus({ timeout = 5000 } = {}) {
  return toData(apiClient.get(`${API_BASE}/setup/status`, { timeout }))
}

export function initializeSetup(payload) {
  return toData(apiClient.post(`${API_BASE}/setup/initialize`, payload))
}

export function testDatabaseConnection(payload) {
  return toData(apiClient.post(`${API_BASE}/setup/database/test-connection`, payload))
}

export function provisionDatabase(payload) {
  return toData(apiClient.post(`${API_BASE}/setup/database/provision`, payload))
}

export function getDatabaseProvisionStatus() {
  return toData(apiClient.get(`${API_BASE}/setup/database/provision-status`))
}

export function getDatabaseStatus() {
  return toData(apiClient.get(`${API_BASE}/setup/database/status`))
}

export function getSystemInfo() {
  return toData(apiClient.get(`${API_BASE}/setup/database/system-info`))
}

export function updateDatabaseSettings(payload) {
  return toData(apiClient.put(`${API_BASE}/setup/database/settings`, payload))
}
