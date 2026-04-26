import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getMounts() {
  return toData(apiClient.get(`${API_BASE}/mounts`))
}

export function validateAllMounts() {
  return toData(apiClient.post(`${API_BASE}/mounts/validate`))
}

export function validateMountCandidate(payload) {
  return toData(apiClient.post(`${API_BASE}/mounts/test`, payload))
}

export function validateMount(mountId, payload) {
  return toData(apiClient.post(`${API_BASE}/mounts/${mountId}/validate`, payload))
}

export function discoverMountShares(payload) {
  return toData(apiClient.post(`${API_BASE}/mounts/discover`, payload))
}

export function createMount(payload) {
  return toData(apiClient.post(`${API_BASE}/mounts`, payload))
}

export function updateMount(mountId, payload) {
  return toData(apiClient.patch(`${API_BASE}/mounts/${mountId}`, payload))
}

export function deleteMount(mountId) {
  return toData(apiClient.delete(`${API_BASE}/mounts/${mountId}`))
}
