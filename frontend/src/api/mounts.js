import apiClient from './client.js'
import { toData } from './data.js'

export function getMounts() {
  return toData(apiClient.get('/api/mounts'))
}

export function createMount(payload) {
  return toData(apiClient.post('/api/mounts', payload))
}

export function deleteMount(mountId) {
  return toData(apiClient.delete(`/api/mounts/${mountId}`))
}
