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

export function getShares() {
  return toData(apiClient.get(`${API_BASE}/shares`))
}

export function validateAllShares() {
  return toData(apiClient.post(`${API_BASE}/shares/validate`))
}

export function validateShareCandidate(payload, { timeout } = {}) {
  return toData(apiClient.post(`${API_BASE}/shares/test`, payload, withTimeout(timeout)))
}

export function validateShare(shareId, payload, { timeout } = {}) {
  return toData(apiClient.post(`${API_BASE}/shares/${shareId}/validate`, payload, withTimeout(timeout)))
}

export function discoverShares(payload, { timeout } = {}) {
  return toData(apiClient.post(`${API_BASE}/shares/discover`, payload, withTimeout(timeout)))
}

export function createShare(payload, { timeout } = {}) {
  return toData(apiClient.post(`${API_BASE}/shares`, payload, withTimeout(timeout)))
}

export function updateShare(shareId, payload, { timeout } = {}) {
  return toData(apiClient.patch(`${API_BASE}/shares/${shareId}`, payload, withTimeout(timeout)))
}

export function deleteShare(shareId) {
  return toData(apiClient.delete(`${API_BASE}/shares/${shareId}`))
}

export function testShareThroughput(shareId, { timeout = 0 } = {}) {
  return toData(apiClient.post(`${API_BASE}/shares/${shareId}/throughput-test`, null, withTimeout(timeout)))
}
