import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function createOsUser(payload) {
  return toData(apiClient.post(`${API_BASE}/admin/os-users`, payload))
}

export function getOsUsers() {
  return toData(apiClient.get(`${API_BASE}/admin/os-users`))
}

export function deleteOsUser(username) {
  return toData(apiClient.delete(`${API_BASE}/admin/os-users/${username}`))
}

export function resetOsUserPassword(username, payload) {
  return toData(apiClient.put(`${API_BASE}/admin/os-users/${username}/password`, payload))
}

export function setOsUserGroups(username, payload) {
  return toData(apiClient.put(`${API_BASE}/admin/os-users/${username}/groups`, payload))
}

export function addOsUserGroups(username, payload) {
  return toData(apiClient.post(`${API_BASE}/admin/os-users/${username}/groups`, payload))
}

export function createOsGroup(payload) {
  return toData(apiClient.post(`${API_BASE}/admin/os-groups`, payload))
}

export function getOsGroups() {
  return toData(apiClient.get(`${API_BASE}/admin/os-groups`))
}

export function deleteOsGroup(name) {
  return toData(apiClient.delete(`${API_BASE}/admin/os-groups/${name}`))
}

export function getLogFiles() {
  return toData(apiClient.get(`${API_BASE}/admin/logs`))
}

export function downloadLogFile(name) {
  return apiClient.get(`${API_BASE}/admin/logs/${encodeURIComponent(name)}`, {
    responseType: 'blob',
  })
}

export function getLogLines(params = {}) {
  return toData(apiClient.get(`${API_BASE}/admin/logs/view`, { params }))
}
