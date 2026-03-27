import apiClient from './client.js'
import { toData } from './data.js'

export function getUsers() {
  return toData(apiClient.get('/api/users'))
}

export function getUserRoles(username) {
  return toData(apiClient.get(`/api/users/${username}/roles`))
}

export function setUserRoles(username, payload) {
  return toData(apiClient.put(`/api/users/${username}/roles`, payload))
}

export function deleteUserRoles(username, payload) {
  return toData(apiClient.delete(`/api/users/${username}/roles`, { data: payload }))
}
