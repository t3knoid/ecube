import apiClient from './client.js'

export function getSystemHealth() {
  return apiClient.get('/introspection/system-health')
}

export function getVersion() {
  return apiClient.get('/introspection/version')
}
