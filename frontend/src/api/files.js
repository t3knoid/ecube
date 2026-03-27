import apiClient from './client.js'
import { toData } from './data.js'

export function getFileHashes(fileId) {
  return toData(apiClient.get(`/api/files/${fileId}/hashes`))
}

export function compareFiles(payload) {
  return toData(apiClient.post('/api/files/compare', payload))
}
