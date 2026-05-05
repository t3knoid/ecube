import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

function withTimeout(timeout) {
  const config = {}
  if (timeout != null) {
    config.timeout = timeout
  }
  return config
}

export function getMounts() {
  return toData(apiClient.get(`${API_BASE}/mounts`))
}

export function validateAllMounts() {
  return toData(apiClient.post(`${API_BASE}/mounts/validate`))
}

export function validateMountCandidate(payload, { timeout } = {}) {
  return toData(apiClient.post(`${API_BASE}/mounts/test`, payload, withTimeout(timeout)))
}

export function validateMount(mountId, payload, { timeout } = {}) {
  return toData(apiClient.post(`${API_BASE}/mounts/${mountId}/validate`, payload, withTimeout(timeout)))
}

export function discoverMountShares(payload, { timeout } = {}) {
  return toData(apiClient.post(`${API_BASE}/mounts/discover`, payload, withTimeout(timeout)))
}

export function createMount(payload, { timeout } = {}) {
  return toData(apiClient.post(`${API_BASE}/mounts`, payload, withTimeout(timeout)))
}

export function updateMount(mountId, payload, { timeout } = {}) {
  return toData(apiClient.patch(`${API_BASE}/mounts/${mountId}`, payload, withTimeout(timeout)))
}

export function deleteMount(mountId) {
  return toData(apiClient.delete(`${API_BASE}/mounts/${mountId}`))
}
