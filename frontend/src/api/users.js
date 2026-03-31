import apiClient from './client.js'
import { toData } from './data.js'
import { API_BASE } from '@/constants/routes.js'

export function getUsers() {
  return toData(apiClient.get(`${API_BASE}/users`))
}

export function getUserRoles(username) {
  return toData(apiClient.get(`${API_BASE}/users/${username}/roles`))
}

export function setUserRoles(username, payload) {
  return toData(apiClient.put(`${API_BASE}/users/${username}/roles`, payload))
}

export function deleteUserRoles(username) {
  return toData(apiClient.delete(`${API_BASE}/users/${username}/roles`))
}
