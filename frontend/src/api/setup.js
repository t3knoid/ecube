import apiClient from './client.js'

export function getSetupStatus({ timeout = 5000 } = {}) {
  return apiClient.get('/setup/status', { timeout })
}
