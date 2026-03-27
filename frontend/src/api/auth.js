import apiClient from './client.js'
import { toData } from './data.js'

export function postLogin(username, password) {
  return toData(apiClient.post('/api/auth/token', { username, password }))
}
