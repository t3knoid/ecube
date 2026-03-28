import apiClient from './client.js'
import { toData } from './data.js'

export function getSetupStatus({ timeout = 5000 } = {}) {
  return toData(apiClient.get('/api/setup/status', { timeout }))
}

export function initializeSetup(payload) {
  return toData(apiClient.post('/api/setup/initialize', payload))
}

export function testDatabaseConnection(payload) {
  return toData(apiClient.post('/api/setup/database/test-connection', payload))
}

export function provisionDatabase(payload) {
  return toData(apiClient.post('/api/setup/database/provision', payload))
}

export function getDatabaseProvisionStatus() {
  return toData(apiClient.get('/api/setup/database/provision-status'))
}

export function getDatabaseStatus() {
  return toData(apiClient.get('/api/setup/database/status'))
}

export function updateDatabaseSettings(payload) {
  return toData(apiClient.put('/api/setup/database/settings', payload))
}
