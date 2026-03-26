import apiClient from './client.js'

export function postLogin(username, password) {
  return apiClient.post('/auth/token', { username, password })
}
