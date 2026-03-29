import apiClient from './client.js'
import { toData } from './data.js'

export function createOsUser(payload) {
  return toData(apiClient.post('/api/admin/os-users', payload))
}

export function getOsUsers() {
  return toData(apiClient.get('/api/admin/os-users'))
}

export function deleteOsUser(username) {
  return toData(apiClient.delete(`/api/admin/os-users/${username}`))
}

export function resetOsUserPassword(username, payload) {
  return toData(apiClient.put(`/api/admin/os-users/${username}/password`, payload))
}

export function setOsUserGroups(username, payload) {
  return toData(apiClient.put(`/api/admin/os-users/${username}/groups`, payload))
}

export function addOsUserGroups(username, payload) {
  return toData(apiClient.post(`/api/admin/os-users/${username}/groups`, payload))
}

export function createOsGroup(payload) {
  return toData(apiClient.post('/api/admin/os-groups', payload))
}

export function getOsGroups() {
  return toData(apiClient.get('/api/admin/os-groups'))
}

export function deleteOsGroup(name) {
  return toData(apiClient.delete(`/api/admin/os-groups/${name}`))
}

export function getLogFiles() {
  return toData(apiClient.get('/api/admin/logs'))
}

export function downloadLogFile(name) {
  return apiClient.get(`/api/admin/logs/${encodeURIComponent(name)}`, {
    responseType: 'blob',
  })
}
