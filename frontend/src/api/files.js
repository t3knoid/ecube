import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getFileHashes(fileId) {
  return toData(apiClient.get(`${API_BASE}/files/${fileId}/hashes`))
}

export function compareFiles(payload) {
  return toData(apiClient.post(`${API_BASE}/files/compare`, payload))
}
