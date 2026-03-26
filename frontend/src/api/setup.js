import apiClient from './client.js'

export function getSetupStatus() {
  return apiClient.get('/setup/status')
}
