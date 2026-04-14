import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getAudit(params = {}) {
  return toData(apiClient.get(`${API_BASE}/audit`, { params }))
}

export function getChainOfCustody(params = {}) {
  return toData(apiClient.get(`${API_BASE}/audit/chain-of-custody`, { params }))
}

export function confirmChainOfCustodyHandoff(payload) {
  return toData(apiClient.post(`${API_BASE}/audit/chain-of-custody/handoff`, payload))
}
